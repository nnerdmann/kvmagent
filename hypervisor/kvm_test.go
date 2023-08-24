package hypervisor

import (
	"testing"
)

func TestGetHostnanme(t *testing.T) {

	k := KVMHost{Addr: "canceron"}
	hostname, err := k.GetHostname()
	if err != nil {
		t.Error(err)
	}
	t.Log(hostname)

}

func TestGetIPAddress(t *testing.T) {
	k := KVMHost{Addr: "canceron"}
	ip, err := k.GetIPAddress()
	if err != nil || ip == "0.0.0.0" {
		t.Error(err)
	} else {
		t.Log(ip)
	}
}

func TestGetType(t *testing.T) {
	k := KVMHost{Addr: "canceron"}
	hType, err := k.GetType()
	if err != nil || hType != "KVM" {
		t.Error(err)
	} else {
		t.Log(t)
	}
}

func TestGetCPU(t *testing.T) {
	k := KVMHost{Addr: "canceron"}
	cpu, err := k.GetCPU()
	if err != nil {
		t.Error(err)
	} else {
		t.Log(cpu)
	}
}

func TestGetMemory(t *testing.T) {
	k := KVMHost{Addr: "canceron"}
	mem, err := k.GetMemory()
	if err != nil {
		t.Error(err)
	} else {
		t.Log(mem / 1024 / 1024)
	}
}

func TestGetCores(t *testing.T) {
	k := KVMHost{Addr: "canceron"}
	cores, err := k.GetCores()
	if err != nil {
		t.Error(err)
	} else {
		t.Log(cores)
	}
}
func TestGetCPUNum(t *testing.T) {
	k := KVMHost{Addr: "canceron"}
	cpu, err := k.GetCPUNum()
	if err != nil {
		t.Error(err)
	} else {
		t.Log(cpu)
	}
}

func TestGetOS(t *testing.T) {
	k := KVMHost{Addr: "canceron"}
	os, err := k.GetOS()
	if err != nil {
		t.Error(err)
	} else {
		t.Log(os)
	}
}

func TestGetVMs(t *testing.T) {
	k := KVMHost{Addr: "kvm70"}
	vms, err := k.GetVMs()
	if err != nil {
		t.Error(err)
	} else {
		t.Logf("%+v", vms)
	}
}
