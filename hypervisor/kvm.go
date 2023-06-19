package hypervisor

import (
	"fmt"
	"log"
	"net"
	"net/netip"
	"os"
	"strings"
	"time"

	"github.com/antchfx/xmlquery"
	"github.com/digitalocean/go-libvirt"
	"github.com/digitalocean/go-libvirt/socket"
	"github.com/digitalocean/go-libvirt/socket/dialers"
	"github.com/shirou/gopsutil/v3/cpu"
	"github.com/shirou/gopsutil/v3/host"
	"github.com/shirou/gopsutil/v3/mem"
)

type KVMHost struct {
	Addr       string
	libvirtCon *libvirt.Libvirt
}

type VM struct {
	Name       string
	Cores      int
	Memory     int
	Disk       []vmdisk
	State      string
	Snapshot   int
	UUID       string
	XML        string
	Interfaces []vmif
}

type vmif struct {
	Name string
	IP   string
	Mac  string
}

type vmdisk struct {
	file   string
	format string
	size   int
}

func (k KVMHost) GetMemory() (int, error) {
	mem, err := mem.VirtualMemory()
	if err != nil {
		return 0, err
	}
	return int(mem.Total), nil
}

func (k KVMHost) GetHostname() (string, error) {
	return os.Hostname()
}

func (k KVMHost) GetIPAddress() (string, error) {
	//TODO Implement based on with interface has default gateway
	addresses, err := net.InterfaceAddrs()
	if err != nil {
		return "", err
	}
	for _, addr := range addresses {
		ipnet, _ := addr.(*net.IPNet)

		if ipnet.IP.IsLoopback() || ipnet.IP.IsLinkLocalUnicast() {
			continue
		}

		return ipnet.IP.String(), nil
	}
	return "", err
}

func (k KVMHost) GetType() (string, error) {
	return "KVM", nil
}

func (k KVMHost) GetCPU() (string, error) {
	stat, err := cpu.Info()
	if err != nil {
		return "", err
	}
	return stat[0].ModelName, nil
}

func (k KVMHost) GetCores() (int, error) {
	stat, err := cpu.Info()
	if err != nil {
		return 0, err
	}
	return int(stat[0].Cores), nil
}

func (k KVMHost) GetCPUNum() (int, error) {
	stat, err := cpu.Info()
	if err != nil {
		return 0, err
	}
	return len(stat) / int(stat[0].Cores), nil
}

func (k KVMHost) GetOS() (string, error) {
	stat, err := host.Info()
	if err != nil {
		return "", err
	}
	return strings.ToUpper(stat.PlatformFamily) + " " + stat.PlatformVersion, nil
}

func (k KVMHost) getLibvirt() (*libvirt.Libvirt, error) {

	var d socket.Dialer
	if k.Addr != "" {
		d = dialers.NewRemote(k.Addr, dialers.UsePort("16509"), dialers.WithRemoteTimeout(time.Second*5))
	} else {
		d = dialers.NewLocal()
	}
	k.libvirtCon = libvirt.NewWithDialer(d)

	if err := k.libvirtCon.Connect(); err != nil {
		return nil, err
	}

	return k.libvirtCon, nil
}

func (k KVMHost) GetVMs() ([]VM, error) {
	l, err := k.getLibvirt()
	if err != nil {
		return nil, err
	}
	defer l.Disconnect()

	domains, _, err := l.ConnectListAllDomains(1, 0)
	if err != nil {
		return nil, err
	}

	var returnList []VM
	for _, d := range domains {

		state, memory, _, vcpu, _, err := l.DomainGetInfo(d)
		if err != nil {
			return nil, err
		}

		var vmObj VM
		vmObj.UUID = fmt.Sprintf("%x", d.UUID)
		vmObj.Name = d.Name
		vmObj.Memory = int(memory)
		vmObj.Cores = int(vcpu)

		switch state {
		case 0:
			vmObj.State = "No state"
		case 1:
			vmObj.State = "Running"
		case 2:
			vmObj.State = "Blocked"
		case 3:
			vmObj.State = "Paused"
		case 4:
			vmObj.State = "In shutdown"
		case 5:
			vmObj.State = "Shut off"
		case 6:
			vmObj.State = "Crashed"
		case 7:
			vmObj.State = "PM suspended"
		}

		numSnapshots, err := l.DomainSnapshotNum(d, 0)
		if err != nil {
			return nil, err
		}
		vmObj.Snapshot = int(numSnapshots)

		vmObj.XML, err = l.DomainGetXMLDesc(d, 2)
		if err != nil {
			return nil, err
		}
		xmlObj, err := xmlquery.Parse(strings.NewReader(vmObj.XML))
		if err != nil {
			return nil, err
		}
		diskTypes, err := xmlquery.QueryAll(xmlObj, "/domain/devices/disk[@device='disk']/driver/@type")
		if err != nil {
			return nil, err
		}
		diskFiles, err := xmlquery.QueryAll(xmlObj, "/domain/devices/disk[@device='disk']/source/@file")
		if err != nil {
			return nil, err
		}

		for i := range diskTypes {
			var diskObj vmdisk
			diskObj.file = diskFiles[i].FirstChild.Data
			diskObj.format = diskTypes[i].FirstChild.Data
			_, size, _, err := l.DomainGetBlockInfo(d, diskObj.file, 0)
			if err != nil {
				return nil, err
			}

			diskObj.size = int(size)
			vmObj.Disk = append(vmObj.Disk, diskObj)
		}

		interfaces, _ := l.DomainInterfaceAddresses(d, uint32(libvirt.DomainInterfaceAddressesSrcAgent), 0)
		// if err != nil {
		// 	if err.Error() != "Requested operation is not valid: domain is not running" {
		// 		log.Fatalf("failed to retrieve domains interfaces: %v", err)
		// 	}
		// }

		blacklistInterfaces := []string{"lo", "dummy", "flannel", "veth", "nodelocaldns", "kube", "cali", "tun", "virbr"}

	IFLOOP:
		for _, i := range interfaces {
			if string(i.Hwaddr[0]) == "00:00:00:00:00:00" {
				continue
			}
			for _, black := range blacklistInterfaces {
				if strings.Contains(i.Name, black) {
					continue IFLOOP
				}
			}

			var iface vmif
			iface.Name = i.Name
			iface.Mac = fmt.Sprintf("%s", i.Hwaddr)
			for _, a := range i.Addrs {
				addrObj, err := netip.ParseAddr(a.Addr)
				if err != nil {
					log.Fatalf("Unknown IP address: %v", err)
				}
				if addrObj.IsLoopback() || addrObj.IsLinkLocalUnicast() {
					continue
				}
				iface.IP = a.Addr
			}
			vmObj.Interfaces = append(vmObj.Interfaces, iface)
		}
		returnList = append(returnList, vmObj)

	}

	return returnList, nil
}
