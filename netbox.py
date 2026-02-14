import os
import logging
from pynetbox import api
from requests import RequestException

NETBOX_URL = os.getenv("NETBOX_URL", None)
NETBOX_TOKEN = os.getenv("NETBOX_TOKEN", "")
NETBOX_TENANT = os.getenv("NETBOX_TENANT", "default")
NETBOX_SITE = os.getenv("NETBOX_SITE", "default")

nb = api(NETBOX_URL, token=NETBOX_TOKEN)


def get_cluster_type_by_name(name):
    """
    Retrieve a cluster from Netbox by its name.
    Returns the cluster object if found, None otherwise.
    """
    try:
        cluster_type = nb.virtualization.cluster_types.get(name=name)
        return cluster_type
    except (RequestException, ValueError) as e:
        logging.error("Error retrieving cluster '%s' from Netbox: %s", name, e)
        return None

def create_or_update_cluster_in_netbox(name):
    """
    Create or update a cluster in Netbox using the pynetbox API.
    Expects a Cluster object as defined in kvm.py.
    """
    payload = {
        "name": name,
        "type": {"name": get_cluster_type_by_name("KVM").name},  # Assuming 'KVM' is a valid type in Netbox
        "status": "active",
        "tenant": {"name": NETBOX_TENANT},
        "site": {"name": NETBOX_SITE},
    }
    try:
        # Check if cluster already exists
        cluster = nb.virtualization.clusters.get(name=name)
        if cluster:
            logging.debug("Cluster '%s' exists in Netbox, checking for updates.", name)
            if needs_update(payload, cluster):
                logging.debug("Cluster '%s' needs update in Netbox.", name)
                updated = nb.virtualization.clusters.update([{
                    "id": cluster.id,
                    **payload
                }])
                if updated:
                    logging.info("Cluster '%s' updated in Netbox.", name)
                else:
                    logging.error("Failed to update cluster '%s' in Netbox.", name)
                    return None
            else:
                logging.debug("Cluster '%s' is up to date in Netbox.", name)
        else:
            cluster = nb.virtualization.clusters.create(payload)
            if cluster:
                logging.info("Cluster '%s' created in Netbox.", name)
            else:
                logging.error("Failed to create cluster '%s' in Netbox.", name)
                return None
    except (RequestException, ValueError) as e:
        logging.error("Error creating or updating cluster '%s' in Netbox: %s", name, e)
        return None

    try:
        existing_device = nb.dcim.devices.get(name=name)
        if existing_device:
            logging.debug("Device '%s' found in Netbox.", name)
            # Check if device is already assigned to this cluster
            if existing_device.cluster and existing_device.cluster.id == cluster.id:
                logging.debug("Device '%s' is already assigned to cluster '%s'.", name, name)
            else:
                # Assign device to cluster
                existing_device.cluster = cluster.id
                existing_device.save()
                logging.info("Device '%s' assigned to cluster '%s'.", name, name)
        else:
            logging.warning("No device found with name '%s'.", name)
            
    except (RequestException, ValueError) as e:
        logging.error("Error assigning device to cluster '%s' in Netbox: %s", name, e)
        return None

    return cluster
    
def create_or_update_vm_in_netbox(vm,cluster):
    """
    Create or update a VM in Netbox using the pynetbox API.
    Expects a VM object as defined in kvm.py.
    """
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
        # Check if VM already exists
        existing = nb.virtualization.virtual_machines.get(name=vm.name)       
        if existing:
            logging.debug("VM '%s' exists in Netbox, checking for updates.", vm.name)
            if needs_update(payload, existing):
                logging.debug("VM '%s' needs update in Netbox.", vm.name)
                updated = nb.virtualization.virtual_machines.update([{
                    "id": existing.id,
                    **payload
                }])
                if updated:
                    logging.info("VM '%s' updated in Netbox.", vm.name)
                    vm_record = updated[0]
                else:
                    logging.error("Failed to update VM '%s' in Netbox.", vm.name)
                    return None
            else:
                logging.debug("VM '%s' is up to date in Netbox.", vm.name)
                vm_record = existing
        else:
            created = nb.virtualization.virtual_machines.create(payload)
            if created:
                logging.info("VM '%s' created in Netbox.", vm.name)
                vm_record = created
            else:
                logging.error("Failed to create VM '%s' in Netbox.", vm.name)
                return None

        return vm_record

    except (RequestException, ValueError) as e:
        logging.error("Error creating or updating VM '%s' in Netbox: %s", vm.name, e)
        return None

def create_or_update_vm_interfaces(vm_record, iface):
    """
    Create or update VM interfaces in Netbox.
    Expects a VM record from Netbox and an Interface object as defined in kvm.py.
    """
    try:
        existing_ifaces = nb.virtualization.interfaces.filter(virtual_machine_id=vm_record.id, name=iface.name)
        if existing_ifaces:
            logging.info("Interface '%s' already exists for VM '%s'.", iface.name, vm_record.name)
            return list(existing_ifaces)[0]

        payload = {
            "virtual_machine": vm_record.id,
            "name": iface.name,
            "mac_address": iface.mac,
            # "mtu": iface.mtu,
            #"mode": "access",  # Example type, adjust as needed
        }
        created_iface = nb.virtualization.interfaces.create(payload)
        if created_iface:
            logging.info("Interface '%s' created for VM '%s'.", iface.name, vm_record.name)
        else:
            logging.error("Failed to create interface '%s' for VM '%s'.", iface.name, vm_record.name)
            return None
        return created_iface

    except (RequestException, ValueError) as e:
        logging.error("Error creating interface '%s' for VM '%s': %s", iface.name, vm_record.name, e)
        return None

def create_or_update_vm_disks(vm_record, disk):
    """
    Create or update VM disks in Netbox.
    Expects a VM record from Netbox and a Disk object as defined in kvm.py.
    """
    try:
        existing_disks = nb.virtualization.virtual_disks.filter(virtual_machine_id=vm_record.id, name=os.path.basename(disk.file))
        if existing_disks:
            logging.info("Disk '%s' already exists for VM '%s'.", disk.file, vm_record.name)
            if needs_update(disk, list(existing_disks)[0]):
                logging.debug("Disk '%s' needs update in Netbox.", disk.file)
                updated = nb.virtualization.virtual_disks.update([{
                    "id": list(existing_disks)[0].id,
                    "size": disk.size,
                    "format": disk.format,
                }])
                if updated:
                    logging.info("Disk '%s' updated for VM '%s'.", disk.file, vm_record.name)
                else:
                    logging.error("Failed to update disk '%s' for VM '%s'.", disk.file, vm_record.name)
            return list(existing_disks)[0]

        payload = {
            "virtual_machine": vm_record.id,
            "name": os.path.basename(disk.file),
            "size": round(disk.size/1024/1024), 
            "custom_fields": {"type": disk.format,},
        }
        created_disk = nb.virtualization.virtual_disks.create(payload)
        if created_disk:
            logging.info("Disk '%s' created for VM '%s'.", disk.file, vm_record.name)
        else:
            logging.error("Failed to create disk '%s' for VM '%s'.", disk.file, vm_record.name)
            return None
        return created_disk

    except (RequestException, ValueError) as e:
        logging.error("Error creating disk '%s' for VM '%s': %s", disk.file, vm_record.name, e)
        return None

def needs_update(local_obj, netbox_obj):
    """
    Compare only the fields that are present in both local_obj and netbox_obj.
    Returns True if any common field differs, False otherwise.
    """
    # Get all attributes of the local object (excluding private and methods)
    local_fields = local_obj.keys() if isinstance(local_obj, dict) else [attr for attr in dir(local_obj) if not attr.startswith("_") and not callable(getattr(local_obj, attr))]
    # Determine which fields exist in both objects
    if isinstance(netbox_obj, dict):
        netbox_fields = netbox_obj.keys()
    else:
        netbox_fields = [attr for attr in dir(netbox_obj) if not attr.startswith("_") and not callable(getattr(netbox_obj, attr))]
    common_fields = set(local_fields) & set(netbox_fields)
    for field in common_fields:
        local_val = local_obj.get(field, None) if isinstance(local_obj, dict) else getattr(local_obj, field, None)
        if isinstance(local_val, dict):
            local_val = local_val.get(list(local_val.keys())[0], None) if local_val else None
        netbox_val = getattr(netbox_obj, field, None) if not isinstance(netbox_obj, dict) else netbox_obj.get(field, None)
        if str(local_val).lower() != str(netbox_val).lower():
            return True
    return False