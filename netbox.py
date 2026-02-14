import logging
import os
import time
from typing import Any, Callable, Optional

from pynetbox import api
from requests import RequestException

NETBOX_URL = os.getenv("NETBOX_URL")
NETBOX_TOKEN = os.getenv("NETBOX_TOKEN", "")
NETBOX_TENANT = os.getenv("NETBOX_TENANT", "default")
NETBOX_SITE = os.getenv("NETBOX_SITE", "default")
NETBOX_CLUSTER_TYPE = os.getenv("NETBOX_CLUSTER_TYPE", "KVM")
NETBOX_API_RETRIES = int(os.getenv("NETBOX_API_RETRIES", "3"))
NETBOX_RETRY_BACKOFF = float(os.getenv("NETBOX_RETRY_BACKOFF", "1.5"))

LOGGER = logging.getLogger(__name__)
nb = api(NETBOX_URL, token=NETBOX_TOKEN) if NETBOX_URL else None


class NetBoxUnavailableError(RuntimeError):
    """Raised when NetBox is not configured or cannot be reached."""


def _is_retryable_error(exc: Exception) -> bool:
    """Best-effort check for transient connectivity/server-side failures."""
    text = str(exc).lower()
    retryable_markers = (
        "timed out",
        "timeout",
        "temporarily unavailable",
        "connection reset",
        "connection aborted",
        "name or service not known",
        "bad gateway",
        "gateway timeout",
        "too many requests",
        "service unavailable",
    )
    return any(marker in text for marker in retryable_markers)


def _netbox_call(action: str, func: Callable[[], Any]) -> Any:
    """Run a NetBox API call with retries and structured logs."""
    if nb is None:
        raise NetBoxUnavailableError("NETBOX_URL is not set; NetBox client is not initialized")

    max_tries = max(1, NETBOX_API_RETRIES)
    for attempt in range(1, max_tries + 1):
        try:
            result = func()
            if attempt > 1:
                LOGGER.info("NetBox call recovered: action=%s attempt=%d", action, attempt)
            return result
        except (RequestException, ValueError) as exc:
            is_retryable = _is_retryable_error(exc)
            is_last_attempt = attempt == max_tries

            if not is_retryable or is_last_attempt:
                LOGGER.error(
                    "NetBox call failed: action=%s attempt=%d/%d retryable=%s error=%s",
                    action,
                    attempt,
                    max_tries,
                    is_retryable,
                    exc,
                )
                raise

            sleep_for = NETBOX_RETRY_BACKOFF * (2 ** (attempt - 1))
            LOGGER.warning(
                "NetBox call retrying: action=%s attempt=%d/%d sleep=%.1fs error=%s",
                action,
                attempt,
                max_tries,
                sleep_for,
                exc,
            )
            time.sleep(sleep_for)


def get_cluster_type_by_name(name: str) -> Optional[Any]:
    """Return cluster type object from NetBox by name."""
    try:
        return _netbox_call(
            action=f"cluster_type.get:{name}",
            func=lambda: nb.virtualization.cluster_types.get(name=name),
        )
    except (NetBoxUnavailableError, RequestException, ValueError) as exc:
        LOGGER.error("Unable to retrieve cluster type '%s': %s", name, exc)
        return None


def create_or_update_cluster_in_netbox(name: str) -> Optional[Any]:
    """Create or update a NetBox cluster and bind host device to it when available."""
    cluster_type = get_cluster_type_by_name(NETBOX_CLUSTER_TYPE)
    if cluster_type is None:
        LOGGER.error("Cluster type '%s' does not exist or is unreachable in NetBox.", NETBOX_CLUSTER_TYPE)
        return None

    payload = {
        "name": name,
        "type": {"name": cluster_type.name},
        "status": "active",
        "tenant": {"name": NETBOX_TENANT},
        "site": {"name": NETBOX_SITE},
    }

    try:
        cluster = _netbox_call(
            action=f"clusters.get:{name}",
            func=lambda: nb.virtualization.clusters.get(name=name),
        )

        if cluster:
            LOGGER.debug("Cluster '%s' found in NetBox.", name)
            if needs_update(payload, cluster):
                updated = _netbox_call(
                    action=f"clusters.update:{name}",
                    func=lambda: nb.virtualization.clusters.update([{"id": cluster.id, **payload}]),
                )
                if not updated:
                    LOGGER.error("Cluster '%s' update returned empty response.", name)
                    return None
                LOGGER.info("Cluster '%s' updated.", name)
            else:
                LOGGER.debug("Cluster '%s' already up to date.", name)
        else:
            cluster = _netbox_call(
                action=f"clusters.create:{name}",
                func=lambda: nb.virtualization.clusters.create(payload),
            )
            if not cluster:
                LOGGER.error("Cluster '%s' creation returned empty response.", name)
                return None
            LOGGER.info("Cluster '%s' created.", name)

        _assign_device_to_cluster(name, cluster)
        return cluster
    except (NetBoxUnavailableError, RequestException, ValueError) as exc:
        LOGGER.error("Failed to create/update cluster '%s': %s", name, exc)
        return None


def _assign_device_to_cluster(name: str, cluster: Any) -> None:
    """Assign dcim device to cluster if matching device name exists."""
    try:
        existing_device = _netbox_call(
            action=f"devices.get:{name}",
            func=lambda: nb.dcim.devices.get(name=name),
        )
        if not existing_device:
            LOGGER.warning("No NetBox device found for host '%s'; skipping cluster assignment.", name)
            return

        if existing_device.cluster and existing_device.cluster.id == cluster.id:
            LOGGER.debug("Device '%s' already bound to cluster '%s'.", name, cluster.name)
            return

        existing_device.cluster = cluster.id
        _netbox_call(action=f"devices.save:{name}", func=existing_device.save)
        LOGGER.info("Device '%s' assigned to cluster '%s'.", name, cluster.name)
    except (NetBoxUnavailableError, RequestException, ValueError) as exc:
        LOGGER.error("Unable to assign device '%s' to cluster '%s': %s", name, cluster.name, exc)


def create_or_update_vm_in_netbox(vm: Any, cluster: Any) -> Optional[Any]:
    """Create or update a VM in NetBox."""
    payload = {
        "name": vm.name,
        "status": vm.status.lower(),
        "vcpus": vm.vcpus,
        "memory": vm.memory,
        "serial": vm.serial,
        "site": {"name": NETBOX_SITE},
        "tenant": {"name": NETBOX_TENANT},
        "cluster": {"name": cluster.name},
    }

    try:
        existing = _netbox_call(
            action=f"virtual_machines.get:{vm.name}",
            func=lambda: nb.virtualization.virtual_machines.get(name=vm.name),
        )

        if existing:
            if needs_update(payload, existing):
                updated = _netbox_call(
                    action=f"virtual_machines.update:{vm.name}",
                    func=lambda: nb.virtualization.virtual_machines.update([{"id": existing.id, **payload}]),
                )
                if not updated:
                    LOGGER.error("VM '%s' update returned empty response.", vm.name)
                    return None
                LOGGER.info("VM '%s' updated.", vm.name)
                return updated[0]

            LOGGER.debug("VM '%s' already up to date.", vm.name)
            return existing

        created = _netbox_call(
            action=f"virtual_machines.create:{vm.name}",
            func=lambda: nb.virtualization.virtual_machines.create(payload),
        )
        if not created:
            LOGGER.error("VM '%s' create returned empty response.", vm.name)
            return None

        LOGGER.info("VM '%s' created.", vm.name)
        return created
    except (NetBoxUnavailableError, RequestException, ValueError) as exc:
        LOGGER.error("Failed to create/update VM '%s': %s", vm.name, exc)
        return None


def create_or_update_vm_interfaces(vm_record: Any, iface: Any) -> Optional[Any]:
    """Create a VM interface in NetBox if it does not already exist."""
    try:
        existing_ifaces = _netbox_call(
            action=f"interfaces.filter:{vm_record.name}:{iface.name}",
            func=lambda: nb.virtualization.interfaces.filter(virtual_machine_id=vm_record.id, name=iface.name),
        )
        existing_ifaces = list(existing_ifaces)
        if existing_ifaces:
            LOGGER.debug("Interface '%s' already exists for VM '%s'.", iface.name, vm_record.name)
            return existing_ifaces[0]

        payload = {
            "virtual_machine": vm_record.id,
            "name": iface.name,
            "mac_address": iface.mac,
        }
        created_iface = _netbox_call(
            action=f"interfaces.create:{vm_record.name}:{iface.name}",
            func=lambda: nb.virtualization.interfaces.create(payload),
        )
        if not created_iface:
            LOGGER.error("Interface '%s' create returned empty response for VM '%s'.", iface.name, vm_record.name)
            return None

        LOGGER.info("Interface '%s' created for VM '%s'.", iface.name, vm_record.name)
        return created_iface
    except (NetBoxUnavailableError, RequestException, ValueError) as exc:
        LOGGER.error("Failed to create/update interface '%s' for VM '%s': %s", iface.name, vm_record.name, exc)
        return None


def create_or_update_vm_disks(vm_record: Any, disk: Any) -> Optional[Any]:
    """Create or update VM disk information in NetBox."""
    disk_name = os.path.basename(disk.file)

    try:
        existing_disks = _netbox_call(
            action=f"virtual_disks.filter:{vm_record.name}:{disk_name}",
            func=lambda: nb.virtualization.virtual_disks.filter(virtual_machine_id=vm_record.id, name=disk_name),
        )
        existing_disks = list(existing_disks)

        if existing_disks:
            existing_disk = existing_disks[0]
            payload = {
                "name": disk_name,
                "size": round(disk.size / 1024 / 1024),
                "custom_fields": {"type": disk.format},
            }
            if needs_update(payload, existing_disk):
                updated = _netbox_call(
                    action=f"virtual_disks.update:{vm_record.name}:{disk_name}",
                    func=lambda: nb.virtualization.virtual_disks.update(
                        [{"id": existing_disk.id, "size": payload["size"], "custom_fields": payload["custom_fields"]}]
                    ),
                )
                if not updated:
                    LOGGER.error("Disk '%s' update returned empty response for VM '%s'.", disk_name, vm_record.name)
                    return None
                LOGGER.info("Disk '%s' updated for VM '%s'.", disk_name, vm_record.name)
            else:
                LOGGER.debug("Disk '%s' already up to date for VM '%s'.", disk_name, vm_record.name)
            return existing_disk

        payload = {
            "virtual_machine": vm_record.id,
            "name": disk_name,
            "size": round(disk.size / 1024 / 1024),
            "custom_fields": {"type": disk.format},
        }
        created_disk = _netbox_call(
            action=f"virtual_disks.create:{vm_record.name}:{disk_name}",
            func=lambda: nb.virtualization.virtual_disks.create(payload),
        )
        if not created_disk:
            LOGGER.error("Disk '%s' create returned empty response for VM '%s'.", disk_name, vm_record.name)
            return None

        LOGGER.info("Disk '%s' created for VM '%s'.", disk_name, vm_record.name)
        return created_disk
    except (NetBoxUnavailableError, RequestException, ValueError) as exc:
        LOGGER.error("Failed to create/update disk '%s' for VM '%s': %s", disk_name, vm_record.name, exc)
        return None


def needs_update(local_obj: Any, netbox_obj: Any) -> bool:
    """Return True when comparable fields differ between local and NetBox objects."""
    local_fields = (
        local_obj.keys()
        if isinstance(local_obj, dict)
        else [attr for attr in dir(local_obj) if not attr.startswith("_") and not callable(getattr(local_obj, attr))]
    )
    netbox_fields = (
        netbox_obj.keys()
        if isinstance(netbox_obj, dict)
        else [attr for attr in dir(netbox_obj) if not attr.startswith("_") and not callable(getattr(netbox_obj, attr))]
    )

    for field in set(local_fields) & set(netbox_fields):
        local_val = local_obj.get(field) if isinstance(local_obj, dict) else getattr(local_obj, field, None)
        netbox_val = netbox_obj.get(field) if isinstance(netbox_obj, dict) else getattr(netbox_obj, field, None)

        if isinstance(local_val, dict):
            local_val = next(iter(local_val.values()), None)
        if isinstance(netbox_val, dict):
            netbox_val = next(iter(netbox_val.values()), None)

        if str(local_val).lower() != str(netbox_val).lower():
            return True
    return False
