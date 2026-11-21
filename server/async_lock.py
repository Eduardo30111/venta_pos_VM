import asyncio
from typing import Dict, Any


class LazyAsyncLock:
    """Mutex asíncrono seguro que se enlaza dinámicamente al event loop en ejecución.
    Evita 'Future attached to a different loop' cuando múltiples tests o ciclos de vida invocan el servicio."""

    def __init__(self):
        self._locks: Dict[Any, asyncio.Lock] = {}

    def _get_lock(self) -> asyncio.Lock:
        try:
            loop = asyncio.get_running_loop()
            key = id(loop)
        except RuntimeError:
            key = 0
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def __aenter__(self):
        return await self._get_lock().__aenter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return await self._get_lock().__aexit__(exc_type, exc_val, exc_tb)


# Lock compartido para serializar operaciones concurrentes de inventario, ventas, compras y traslados
SHARED_INVENTORY_LOCK = LazyAsyncLock()
