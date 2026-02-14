# kvmagent

`kvmagent` synchronizes VM inventory from a libvirt/KVM host into NetBox.

## What it does

- Connects to a local or remote libvirt host.
- Discovers VMs, interfaces, and disks.
- Creates/updates corresponding objects in NetBox.
- Retries transient NetBox API failures with exponential backoff.
- Emits structured logs with configurable log levels.

## Requirements

- Python 3.11+
- Access to libvirt (local socket or remote TCP endpoint)
- NetBox API token and URL

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

Set environment variables (see `.env.example`):

- `NETBOX_URL` (required)
- `NETBOX_TOKEN` (required)
- `NETBOX_TENANT` (default: `default`)
- `NETBOX_SITE` (default: `default`)
- `NETBOX_CLUSTER_TYPE` (default: `KVM`)
- `NETBOX_API_RETRIES` (default: `3`)
- `NETBOX_RETRY_BACKOFF` (default: `1.5`)
- `KVM_ADDR` (empty means local libvirt)
- `CHECK_INTERVAL` (default: `300`)
- `RUN_ONCE` (`true`/`false`, default: `true`)
- `LOG_LEVEL` (`DEBUG`, `INFO`, `WARNING`, `ERROR`; default: `INFO`)

## Usage

Run one sync pass:

```bash
RUN_ONCE=true python3 main.py
```

Run continuously:

```bash
RUN_ONCE=false CHECK_INTERVAL=300 python3 main.py
```

## Logging

The app logs at multiple levels:

- `DEBUG`: payload-level and decision logs
- `INFO`: normal lifecycle/sync operations
- `WARNING`: transient issues and retries
- `ERROR`: failed API/libvirt operations

Example:

```bash
LOG_LEVEL=DEBUG python3 main.py
```
