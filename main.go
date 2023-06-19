package main

import (
	"bytes"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"gitlabe2.ext.net.nokia.com/nice/kvmagent/hypervisor"
)

var k hypervisor.KVMHost
var cache string
var count int

type hv interface {
	GetHostname() (string, error)
	GetVMs() ([]hypervisor.VM, error)
	GetMemory() (int, error)
	GetIPAddress() (string, error)
	GetType() (string, error)
	GetCPU() (string, error)
	GetCores() (int, error)
	GetCPUNum() (int, error)
}

type hvInfo struct {
	Hostname  string
	IP        string
	VirtType  string
	CPUModel  string
	Cores     int
	CPUNumber int
	Memory    int
	VMs       []hypervisor.VM
}

func getJSON(hvObj hv) (string, error) {
	var returnObj hvInfo
	var err error

	returnObj.Hostname, err = hvObj.GetHostname()
	if err != nil {
		return "", err
	}
	returnObj.IP, err = hvObj.GetIPAddress()
	if err != nil {
		return "", err
	}
	returnObj.VirtType, err = hvObj.GetType()
	if err != nil {
		return "", err
	}
	returnObj.CPUModel, err = hvObj.GetCPU()
	if err != nil {
		return "", err
	}
	returnObj.Cores, err = hvObj.GetCores()
	if err != nil {
		return "", err
	}
	returnObj.CPUNumber, err = hvObj.GetCPUNum()
	if err != nil {
		return "", err
	}
	returnObj.Memory, err = hvObj.GetMemory()
	if err != nil {
		return "", err
	}
	returnObj.VMs, err = hvObj.GetVMs()
	if err != nil {
		return "", err
	}
	returnText, err := json.Marshal(returnObj)
	if err != nil {
		return "", err
	}
	return string(returnText), nil
}

func exec(url string) {

	text, err := getJSON(k)
	if err != nil {
		log.Fatal(err)
	}
	if text != cache {
		r, err := http.Post(url, "application/json", bytes.NewReader([]byte(text)))
		if err != nil {
			log.Printf("FAILED to send request to HVD %s", err)
		}
		if r.StatusCode == 200 {
			log.Println("Update successful")
		} else {
			log.Printf("Update failed %d", r.StatusCode)
		}

		cache = text
		count = 0
	} else {
		count++
		if count > 10 {
			log.Println("JSON data unchanged the last 1000 checks")
			count = 0
		}
	}

}
func main() {

	k = hypervisor.KVMHost{Addr: "peru"}
	os.Setenv("CHECK_INTERVAL", "1")

	log.Println("Started the KVM agent")

	url := os.Getenv("TARGET_URL")
	if url == "" {
		url = "https://hvd.nice.nokia.net/updateHost"
	}

	log.Printf("Target URL is " + url)

	log.Println("Initial update to HVD")
	exec(url)

	interval, err := strconv.Atoi(os.Getenv("CHECK_INTERVAL"))
	if err != nil || interval < 1 {
		interval = 60
	}

	log.Printf("Check for changes will be executed every %d seconds", interval)

	tickerInterval := time.Second * time.Duration(interval)
	ticker := time.NewTicker(tickerInterval)
	done := make(chan bool)

	for {
		select {
		case <-done:
			return
		case <-ticker.C:
			exec(url)
		}
	}

}
