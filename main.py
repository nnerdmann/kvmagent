import logging
import os
import socket
import time

from kvm import KVMHost
from netbox import (
    create_or_update_cluster_in_netbox,
    create_or_update_vm_disks,
    create_or_update_vm_in_netbox,
    create_or_update_vm_interfaces,
)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))
RUN_ONCE = os.getenv("RUN_ONCE", "true").lower() in {"1", "true", "yes", "on"}
KVM_ADDR = os.getenv("KVM_ADDR", "")


def configure_logging() -> None:
    """Configure root logging for the agent with a readable format."""
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def exec_check(host: KVMHost, cluster) -> None:
    """Synchronize all VMs, interfaces, and disks from KVM host to NetBox."""
    vms = host.get_vms()
    logging.info("Discovered %d VM(s) from libvirt host '%s'.", len(vms), cluster.name)

    for vm in vms:
        logging.debug("Processing VM '%s'.", vm.name)
        vm_obj = create_or_update_vm_in_netbox(vm, cluster)
        if vm_obj is None:
            logging.warning("Skipping related objects for VM '%s' because VM sync failed.", vm.name)
            continue

        for interface in vm.interfaces:
            logging.debug(
                "Sync interface VM=%s, name=%s, ip=%s, mac=%s",
                vm.name,
                interface.name,
                interface.ip,
                interface.mac,
            )
            create_or_update_vm_interfaces(vm_obj, interface)

        for disk in vm.disks:
            logging.debug(
                "Sync disk VM=%s, file=%s, format=%s, size=%s",
                vm.name,
                disk.file,
                disk.format,
                disk.size,
            )
            create_or_update_vm_disks(vm_obj, disk)


def main() -> None:
    configure_logging()
    logging.info("Starting kvmagent")

    if CHECK_INTERVAL < 1:
        logging.warning("Invalid CHECK_INTERVAL=%s, using default 300 seconds.", CHECK_INTERVAL)
        interval = 300
    else:
        interval = CHECK_INTERVAL

    host = KVMHost(addr=KVM_ADDR)
    cluster_name = KVM_ADDR or socket.gethostname()
    cluster = create_or_update_cluster_in_netbox(cluster_name)

    if cluster is None:
        logging.error("Failed to create or update cluster in NetBox; exiting.")
        return

    exec_check(host, cluster)

    if RUN_ONCE:
        logging.info("RUN_ONCE enabled; exiting after initial sync.")
        return

    logging.info("Continuous mode enabled; checking every %d second(s).", interval)
    while True:
        time.sleep(interval)
        exec_check(host, cluster)


if __name__ == "__main__":
    main()
