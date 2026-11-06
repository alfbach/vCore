from __future__ import annotations

import asyncio
from copy import deepcopy

from app.models.inventory import HostRecord, Inventory, VMRecord


class InventoryStore:
    """Thread-safe async inventory store for concurrent API clients."""

    def __init__(self) -> None:
        self._inventory = Inventory()
        self._lock = asyncio.Lock()

    async def replace(self, inventory: Inventory) -> Inventory:
        async with self._lock:
            self._inventory = inventory
            return self._inventory

    async def get(self) -> Inventory:
        async with self._lock:
            return deepcopy(self._inventory)

    async def snapshot(self) -> Inventory:
        return await self.get()

    async def view(self) -> Inventory:
        """Return the current inventory for an immediate read-only request path.

        API handlers do not await again while reading this object, so returning the
        current immutable-by-convention snapshot avoids copying large inventories.
        Replacements swap the object rather than mutating it.
        """
        async with self._lock:
            return self._inventory

    async def update_vm_power(self, vm_id: str, power_state: str) -> VMRecord:
        async with self._lock:
            vm = self._inventory.vms.get(vm_id)
            if vm is None:
                raise KeyError(vm_id)
            vm.power_state = power_state
            return deepcopy(vm)

    async def transition_vm_power(
        self,
        vm_id: str,
        target_state: str,
        allowed_from: set[str],
    ) -> VMRecord:
        """Atomically validate and apply a VM power-state transition."""
        async with self._lock:
            if not self._inventory.is_loaded:
                raise RuntimeError("inventory not loaded")
            vm = self._inventory.vms.get(vm_id)
            if vm is None:
                raise KeyError(vm_id)
            if vm.power_state not in allowed_from:
                raise ValueError(vm.power_state)
            vm.power_state = target_state
            return deepcopy(vm)

    async def update_vm_annotation(self, vm_id: str, annotation: str) -> VMRecord:
        async with self._lock:
            vm = self._inventory.vms.get(vm_id)
            if vm is None:
                raise KeyError(vm_id)
            vm.annotation = annotation
            return deepcopy(vm)

    async def update_host_maintenance(self, host_id: str, maintenance_mode: bool) -> HostRecord:
        async with self._lock:
            host = self._inventory.hosts.get(host_id)
            if host is None:
                raise KeyError(host_id)
            host.maintenance_mode = maintenance_mode
            return deepcopy(host)


inventory_store = InventoryStore()
