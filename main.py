import os
import time
import logging
from kvm import KVMHost
from netbox import create_or_update_vm_in_netbox, create_or_update_cluster_in_netbox, create_or_update_vm_interfaces, create_or_update_vm_disks

logging.basicConfig(level=logging.INFO)

def exec_check(host,cluster):
    vms = host.get_vms()
    for vm in vms:
        vm_obj = create_or_update_vm_in_netbox(vm,cluster)
        for interface in vm.interfaces:
            logging.debug("VM: %s, Interface: %s, IP: %s, MAC: %s", vm.name, interface.name, interface.ip, interface.mac)
            create_or_update_vm_interfaces(vm_obj, interface)
        for disk in vm.disks:
            logging.debug("VM: %s, Disk: %s, Format: %s, Size: %s", vm.name, disk.file, disk.format, disk.size)
            create_or_update_vm_disks(vm_obj, disk)

def main():
    logging.info("Started the KVM agent")
    
    addr = "liquid3.nice.nokia.net"
    host = KVMHost(addr=addr)
    
    logging.info("Updating cluster in Netbox")
    cluster = create_or_update_cluster_in_netbox(addr)
    if cluster is None:
        logging.error("Failed to create or update cluster in Netbox, exiting.")
        return
    logging.info("Initial update to Netbox")
    exec_check(host,cluster)

    # interval = int(os.getenv("CHECK_INTERVAL", "300"))
    # if interval < 1:
    #     interval = 300

    # logging.info(f"Check for changes will be executed every {interval} seconds")

    # while True:
    #     time.sleep(interval)
    #     exec_check(host)

if __name__ == "__main__":
    main()