import logging
import json
import base64
import os
import time

import libvirt
import lxml.etree as ET

LOGGER = logging.getLogger(__name__)


class VMInterface:
    """Lightweight representation of a VM network interface."""

    def __init__(self, name, ip, mac):
        self.name = name
        self.ip = ip
        self.mac = mac


class VMDisk:
    """Lightweight representation of a VM disk."""

    def __init__(self, file, format, size):
        self.file = file
        self.format = format
        self.size = size


class VM:
    """Aggregated VM model extracted from libvirt."""

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
        self.platform = ""
        self.tags = []


class KVMHost:
    """Wrapper around libvirt connection and VM inventory extraction."""

    def __init__(self, addr=""):
        self.addr = addr
        self.conn = None

    def get_type(self):
        return "KVM"

    def get_tags(self):
        return   os.getenv("NETBOX_KVMAGENT_TAGLIST", "").split(",")

    def _is_connected(self, conn) -> bool:
        """Check if an existing libvirt connection is still healthy."""
        try:
            conn.getLibVersion()
            return True
        except libvirt.libvirtError:
            return False

    def get_libvirt(self):
        """Return active libvirt connection, recreating it if needed."""
        if self.conn and self._is_connected(self.conn):
            return self.conn

        uri = f"qemu+tcp://{self.addr}/system" if self.addr else "qemu:///system"
        try:
            LOGGER.info("Opening libvirt connection to %s", uri)
            self.conn = libvirt.open(uri)
        except libvirt.libvirtError as exc:
            self.conn = None
            raise ConnectionError(f"Unable to connect to libvirt at {uri}: {exc}") from exc

        return self.conn

    def get_vms(self):
        """Collect VM metadata from all domains visible on the libvirt host."""
        conn = self.get_libvirt()
        try:
            domains = conn.listAllDomains()
        except libvirt.libvirtError as exc:
            raise RuntimeError(f"Unable to list domains from libvirt host '{self.addr}': {exc}") from exc

        vms = []
        for dom in domains:
            vm = VM()
            vm.name = dom.name()
            vm.serial = dom.UUIDString()
            vm.tags = self.get_tags()
            info = dom.info()
            vm.memory = int(info[1]) // 1024
            vm.vcpus = float(info[3])

            state_map = {
                libvirt.VIR_DOMAIN_NOSTATE: "Failed",
                libvirt.VIR_DOMAIN_RUNNING: "Active",
                libvirt.VIR_DOMAIN_BLOCKED: "Failed",
                libvirt.VIR_DOMAIN_PAUSED: "Paused",
                libvirt.VIR_DOMAIN_SHUTDOWN: "Offline",
                libvirt.VIR_DOMAIN_SHUTOFF: "Offline",
                libvirt.VIR_DOMAIN_CRASHED: "Failed",
                libvirt.VIR_DOMAIN_PMSUSPENDED: "Failed",
            }
            vm.status = state_map.get(info[0], "Unknown")

            if vm.status == "Active":
                vm.platform = self.detect_platform_string(dom)
                
            try:
                vm.snapshot = dom.snapshotNum()
            except libvirt.libvirtError:
                vm.snapshot = 0

            vm.type = "VM"
            try:
                xml = dom.XMLDesc(0)
                vm.xml = xml
                root = ET.fromstring(xml)

                # OS type and workload hints from domain XML.
                os_type = root.findtext("./os/type")
                if os_type and "windows" in os_type.lower():
                    vm.type = "Windows VM"

                for disk in root.findall("./devices/disk[@device='disk']"):
                    driver = disk.find("driver")
                    source = disk.find("source")
                    if driver is None or source is None:
                        continue

                    disk_format = driver.get("type", "")
                    file_path = source.get("file")
                    if not file_path:
                        pool = source.get("pool")
                        volume = source.get("volume")
                        if pool and volume:
                            file_path = f"{pool}/{volume}"
                        else:
                            continue

                    try:
                        blkinfo = dom.blockInfo(file_path)
                        size = int(blkinfo[1])
                    except libvirt.libvirtError as exc:
                        LOGGER.warning(
                            "Unable to read disk '%s' info for VM '%s': %s; using size=0.",
                            file_path,
                            vm.name,
                            exc,
                        )
                        size = 0

                    vm.disks.append(VMDisk(file_path, disk_format, size))

                if vm.status == "Active":
                    blacklist = [
                        "Loopback",
                        "lo",
                        "dummy",
                        "flannel",
                        "veth",
                        "nodelocaldns",
                        "kube",
                        "cali",
                        "tun",
                        "virbr",
                        "cni",
                        "docker",
                        "br-",
                    ]
                    try:
                        ifaces = dom.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT, 0)
                        for name, iface in ifaces.items():
                            if any(marker in name for marker in blacklist):
                                continue

                            mac = iface.get("hwaddr", "")
                            ip = None
                            if iface["addrs"] is not None:
                                for addr in iface["addrs"]:
                                    if (
                                        addr.get("type") == libvirt.VIR_IP_ADDR_TYPE_IPV4
                                        and not addr.get("addr", "").startswith("127.")
                                        and not addr.get("addr", "").startswith("169.254")
                                    ):
                                        ip = addr["addr"]+"/"+str(addr["prefix"])
                                        break                           

                            vm.interfaces.append(VMInterface(name, ip, mac))
                    except libvirt.libvirtError as exc:
                        LOGGER.warning(
                            "Unable to read interface addresses for VM '%s' (guest agent may be missing): %s",
                            vm.name,
                            exc,
                        )
            except ET.XMLSyntaxError as exc:
                LOGGER.warning("Unable to parse XML for VM '%s': %s", vm.name, exc)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Unexpected VM parsing error for '%s': %s", vm.name, exc)

            vms.append(vm)

        LOGGER.info("Collected inventory for %d VM(s).", len(vms))
        return vms

    def detect_platform_string(self, domain):
        """
        Returns exact platform string from inside the VM.
        """
        
        os_info = domain.guestInfo(2)  # Trigger guest agent update
        if os_info and "os.pretty-name" in os_info:
            return os_info["os.pretty-name"].replace('(', '').replace(')', '')  # Remove any surrounding quotes
        return ""