from io import BytesIO

import pytest
from openpyxl import Workbook

from app.config import get_settings
from app.parser.rvtools import parse_rvtools_xlsx


def _build_sample_workbook() -> bytes:
    wb = Workbook()
    wb.remove(wb.active)

    vinfo = wb.create_sheet("vInfo")
    vinfo.append(["VM", "Powerstate", "Guest", "# CPU", "Mem MB", "Datacenter", "Cluster", "Host", "UUID"])
    vinfo.append(["web-01", "poweredOn", "Ubuntu Linux (64-bit)", 2, 4096, "DC1", "Cluster-A", "esxi-01", "uuid-1"])
    vinfo.append(["db-01", "poweredOff", "Windows Server 2022", 4, 8192, "DC1", "Cluster-A", "esxi-02", "uuid-2"])

    vhost = wb.create_sheet("vHost")
    vhost.append(["Host", "Datacenter", "Cluster", "# CPU", "Memory MB", "ESX Version"])
    vhost.append(["esxi-01", "DC1", "Cluster-A", 16, 131072, "8.0.2"])
    vhost.append(["esxi-02", "DC1", "Cluster-A", 16, 131072, "8.0.2"])

    vcluster = wb.create_sheet("vCluster")
    vcluster.append(["Cluster", "Datacenter", "# Hosts", "HA enabled", "DRS enabled"])
    vcluster.append(["Cluster-A", "DC1", 2, "true", "true"])

    vdatastore = wb.create_sheet("vDatastore")
    vdatastore.append(["Name", "Capacity MiB", "Free MiB", "Used MiB", "Type"])
    vdatastore.append(["datastore1", 1024000, 512000, 512000, "VMFS"])

    vnetwork = wb.create_sheet("vNetwork")
    vnetwork.append(["VM", "Network", "Datacenter", "MAC Address", "IPv4"])
    vnetwork.append(["web-01", "VM Network", "DC1", "00:50:56:01:02:03", "10.0.0.10"])
    vnetwork.append(["db-01", "VM Network", "DC1", "00:50:56:01:02:04", "10.0.0.11"])

    vdisk = wb.create_sheet("vDisk")
    vdisk.append(["VM", "Disk", "Capacity MiB"])
    vdisk.append(["web-01", "Hard disk 1", 40960])
    vdisk.append(["db-01", "Hard disk 1", 102400])

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_parse_rvtools_sample():
    inventory = parse_rvtools_xlsx(_build_sample_workbook(), "sample.xlsx")
    assert inventory.is_loaded
    assert inventory.stats["vms"] == 2
    assert inventory.stats["hosts"] == 2
    assert inventory.stats["clusters"] == 1
    assert inventory.stats["datastores"] == 1
    assert any(vm.name == "web-01" for vm in inventory.vms.values())
    assert inventory.vm_disks


def test_api_session_and_vm_list():
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.store.inventory_store import inventory_store

    app = create_app()
    client = TestClient(app)

    inventory = parse_rvtools_xlsx(_build_sample_workbook(), "sample.xlsx")
    import asyncio

    asyncio.run(inventory_store.replace(inventory))

    session_resp = client.post(
        "/rest/com/vmware/cis/session",
        auth=(get_settings().api_username, get_settings().api_password),
    )
    assert session_resp.status_code == 200
    token = session_resp.json()
    assert isinstance(token, str)

    vm_resp = client.get("/rest/vcenter/vm", headers={"vmware-api-session-id": token})
    assert vm_resp.status_code == 200
    vms = vm_resp.json()
    assert len(vms) == 2
    assert vms[0]["name"] in {"web-01", "db-01"}


def test_power_on_simulation():
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.store.inventory_store import inventory_store

    app = create_app()
    client = TestClient(app)
    inventory = parse_rvtools_xlsx(_build_sample_workbook(), "sample.xlsx")
    import asyncio

    asyncio.run(inventory_store.replace(inventory))

    token = client.post(
        "/rest/com/vmware/cis/session",
        auth=(get_settings().api_username, get_settings().api_password),
    ).json()

    headers = {"vmware-api-session-id": token}
    vm_id = next(vm.vm_id for vm in inventory.vms.values() if vm.name == "db-01")

    assert client.get(f"/rest/vcenter/vm/{vm_id}", headers=headers).json()["value"]["power_state"] == "POWERED_OFF"

    power_resp = client.post(f"/rest/vcenter/vm/{vm_id}/power/start", headers=headers)
    assert power_resp.status_code == 200

    updated = client.get(f"/rest/vcenter/vm/{vm_id}", headers=headers).json()["value"]["power_state"]
    assert updated == "POWERED_ON"


def test_host_maintenance_and_extra_endpoints():
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.store.inventory_store import inventory_store

    app = create_app()
    client = TestClient(app)
    inventory = parse_rvtools_xlsx(_build_sample_workbook(), "sample.xlsx")
    import asyncio

    asyncio.run(inventory_store.replace(inventory))

    token = client.post(
        "/rest/com/vmware/cis/session",
        auth=(get_settings().api_username, get_settings().api_password),
    ).json()
    headers = {"vmware-api-session-id": token}

    host_id = next(h.host_id for h in inventory.hosts.values())
    maint_resp = client.post(f"/rest/vcenter/host/{host_id}/maintenance/enter", headers=headers)
    assert maint_resp.status_code == 200
    assert client.get(f"/rest/vcenter/host/{host_id}", headers=headers).json()["value"]["maintenance_mode"] is True

    guest_resp = client.get(
        f"/rest/vcenter/vm/{next(iter(inventory.vms))}/guest/identity",
        headers=headers,
    )
    assert guest_resp.status_code == 200
    assert "value" in guest_resp.json()


def test_delete_session_invalidates_header_token():
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.store.inventory_store import inventory_store

    import asyncio

    asyncio.run(inventory_store.replace(parse_rvtools_xlsx(_build_sample_workbook())))
    client = TestClient(create_app())
    token = client.post(
        "/rest/com/vmware/cis/session",
        auth=(get_settings().api_username, get_settings().api_password),
    ).json()
    headers = {"vmware-api-session-id": token}

    assert client.delete("/rest/com/vmware/cis/session", headers=headers).status_code == 200
    assert client.get("/rest/vcenter/vm", headers=headers).status_code == 401


def test_scoped_ids_do_not_collide_after_slug_normalization():
    from app.models.inventory import VMRecord

    first = VMRecord(name="web 01", datacenter="DC1", uuid="uuid-1")
    second = VMRecord(name="web-01", datacenter="DC1", uuid="uuid-2")
    assert first.vm_id != second.vm_id


def test_duplicate_vm_names_use_uuid_or_scope_for_relations():
    wb = Workbook()
    vinfo = wb.active
    vinfo.title = "vInfo"
    vinfo.append(["VM", "Datacenter", "Cluster", "Host", "UUID"])
    vinfo.append(["shared-name", "DC1", "A", "host-a", "uuid-a"])
    vinfo.append(["shared-name", "DC2", "B", "host-b", "uuid-b"])

    network = wb.create_sheet("vNetwork")
    network.append(["VM", "Datacenter", "Network", "MAC Address"])
    network.append(["shared-name", "DC1", "network-a", "00:00:00:00:00:0a"])
    network.append(["shared-name", "DC2", "network-b", "00:00:00:00:00:0b"])

    disk = wb.create_sheet("vDisk")
    disk.append(["VM", "VM UUID", "Disk", "Capacity MiB"])
    disk.append(["shared-name", "uuid-a", "disk-a", 10])
    disk.append(["shared-name", "uuid-b", "disk-b", 20])

    buffer = BytesIO()
    wb.save(buffer)
    inventory = parse_rvtools_xlsx(buffer.getvalue())

    vm_a = next(vm for vm in inventory.vms.values() if vm.uuid == "uuid-a")
    vm_b = next(vm for vm in inventory.vms.values() if vm.uuid == "uuid-b")
    assert inventory.vm_nics[vm_a.vm_id][0]["network"] == "network-a"
    assert inventory.vm_nics[vm_b.vm_id][0]["network"] == "network-b"
    assert inventory.vm_disks[vm_a.vm_id][0]["label"] == "disk-a"
    assert inventory.vm_disks[vm_b.vm_id][0]["label"] == "disk-b"


def test_resource_pools_are_scoped_by_cluster():
    wb = Workbook()
    vinfo = wb.active
    vinfo.title = "vInfo"
    vinfo.append(["VM", "Datacenter", "Cluster", "Resource Pool", "UUID"])
    vinfo.append(["vm-a", "DC1", "A", "Resources", "uuid-a"])
    vinfo.append(["vm-b", "DC1", "B", "Resources", "uuid-b"])
    buffer = BytesIO()
    wb.save(buffer)

    pools = parse_rvtools_xlsx(buffer.getvalue()).resource_pools.values()
    assert len(pools) == 2
    assert len({pool.resource_pool_id for pool in pools}) == 2


def test_xlsx_structural_limits_are_enforced():
    workbook = _build_sample_workbook()
    with pytest.raises(ValueError, match="uncompressed size"):
        parse_rvtools_xlsx(workbook, max_uncompressed_bytes=1)
    with pytest.raises(ValueError, match="row limit"):
        parse_rvtools_xlsx(workbook, max_rows=1)
    with pytest.raises(ValueError, match="cell limit"):
        parse_rvtools_xlsx(workbook, max_cells=1)

