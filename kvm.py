import libvirt
import lxml.etree as ET
import logging
import socket

class VMInterface:
    def __init__(self, name, ip, mac):
        self.name = name
        self.ip = ip
        self.mac = mac

class VMDisk:
    def __init__(self, file, format, size):
        self.file = file
        self.format = format
        self.size = size

class VM:
    def __init__(self):
        self.name = ""
        self.vcpus = 0
        self.memory = 0
        self.disks = []
        self.status = ""
        self.snapshot = 0
        self.serial = ""
        self.xml = ""
        self.type = ""
        self.interfaces = []

class KVMHost:
    def __init__(self, addr=""):
        self.addr = addr
        self.conn = None

    def get_type(self):
        return "KVM"

    def get_libvirt(self):
        def is_connected(conn):
            try:
                # Try a simple call to check connection
                conn.getLibVersion()
                return True
            except libvirt.libvirtError:
                return False

        if self.conn and is_connected(self.conn):
            return self.conn

        uri = f"qemu+tcp://{self.addr}/system" if self.addr else "qemu:///system"
        try:
            self.conn = libvirt.open(uri)
            # libvirt.registerErrorHandler(None, None)
        except libvirt.libvirtError as e:
            self.conn = None
            raise ConnectionError(f"Unable to connect to libvirt at {uri}: {e}") from e

        return self.conn

    def get_vms(self):
        conn = self.get_libvirt()
        domains = conn.listAllDomains()
        vms = []
        for dom in domains:
            vm = VM()
            vm.name = dom.name()
            vm.serial = dom.UUIDString()
            info = dom.info()
            vm.memory = int(info[1]) // 1024  # Convert KB to MB
            vm.vcpus = float(info[3])
            state_map = {
                libvirt.VIR_DOMAIN_NOSTATE: "Failed",
                libvirt.VIR_DOMAIN_RUNNING: "Active",
                libvirt.VIR_DOMAIN_BLOCKED: "Failed",
                libvirt.VIR_DOMAIN_PAUSED: "Paused",
                libvirt.VIR_DOMAIN_SHUTDOWN: "Offline",
                libvirt.VIR_DOMAIN_SHUTOFF: "Offline",
                libvirt.VIR_DOMAIN_CRASHED: "Failed",
                libvirt.VIR_DOMAIN_PMSUSPENDED: "Failed"
            }
            vm.status = state_map.get(info[0], "Unknown")
            try:
                vm.snapshot = dom.snapshotNum()
            except libvirt.libvirtError:
                vm.snapshot = 0

            vm.type = "VM"
            try:
                xml = dom.XMLDesc(0)
                vm.xml = xml
                root = ET.fromstring(xml)
                # OS type detection
                os_type = root.findtext('./os/type')
                if os_type and "windows" in os_type.lower():
                    vm.type = "Windows VM"
                # Disks
                for disk in root.findall("./devices/disk[@device='disk']"):
                    driver = disk.find("driver")
                    source = disk.find("source")
                    if driver is not None and source is not None:
                        fmt = driver.get("type", "")
                        file_attr = source.get("file")
                        if file_attr:
                            file_path = file_attr
                        else:
                            pool = source.get("pool")
                            volume = source.get("volume")
                            if pool and volume:
                                file_path = f"{pool}/{volume}"
                            else:
                                continue
                        try:
                            blkinfo = dom.blockInfo(file_path)
                            size = int(blkinfo[1])
                        except libvirt.libvirtError as e:
                            if e.err[0] == libvirt.VIR_ERR_SYSTEM_ERROR:
                                logging.warning("Failed to access disk '%s' for VM '%s': %s. Setting size to 0.", file_path, vm.name, e)
                                size = 0
                        vm.disks.append(VMDisk(file_path, fmt, size))
                # Interfaces
                if vm.status == "Active":
                    blacklist = ["lo", "dummy", "flannel", "veth", "nodelocaldns", "kube", "cali", "tun", "virbr", "cni", "docker","br-"]
                    try:
                        ifaces = dom.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT, 0)
                        for name, iface in ifaces.items():
                            if any(b in name for b in blacklist):
                                continue
                            mac = iface['hwaddr'] if 'hwaddr' in iface else ""
                            ip = ""
                            if iface.get('addrs') is not None:
                                for addr in iface.get('addrs', []):
                                    if addr['type'] == libvirt.VIR_IP_ADDR_TYPE_IPV4 and not addr['addr'].startswith("127.") and not addr['addr'].startswith("169.254"):
                                        ip = addr['addr']
                                        break
                                    vm.interfaces.append(VMInterface(name, ip, mac))
                    except libvirt.libvirtError as e:
                        if e.err[0] == libvirt.VIR_ERR_ARGUMENT_UNSUPPORTED:
                            logging.warning("Guest agent not installed or not running; cannot retrieve IP addresses.")
            except Exception as e:
                logging.warning("Error parsing domain XML: %s", e)
            vms.append(vm)
        return vms