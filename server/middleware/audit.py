from typing import Any
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.auditoria import AuditLog

logger = logging.getLogger("vmpos.audit")


async def log_audit(
    db: AsyncSession,
    usuario_id: int = 1,
    usuario_nombre: str = "",
    terminal_id: int = None,
    terminal_nombre: str = None,
    accion: str = "",
    modulo: str = "",
    tabla_afectada: str = "",
    registro_id: str = "",
    entidad_id: Any = None,
    valor_anterior: dict = None,
    valor_nuevo: dict = None,
    descripcion: str = None,
    detalles: Any = None,
    ip_address: str = None,
    auto_commit: bool = True,
    **kwargs: Any,
):
    """
    Registra un evento en audit_log preservando la atomicidad de las transacciones.
    - Con auto_commit=False: usa un SAVEPOINT aislado dentro de la transacción abierta
      del llamador, evitando commits prematuros o rollbacks de la operación principal.
    - Con auto_commit=True: persiste el registro tras una transacción ya confirmada.
    """
    effective_reg_id = str(entidad_id if entidad_id is not None else (registro_id or ""))
    effective_desc = descripcion or (str(detalles) if detalles is not None else None)

    audit_entry = AuditLog(
        usuario_id=usuario_id,
        usuario_nombre=usuario_nombre or f"Usuario #{usuario_id}",
        terminal_id=terminal_id,
        terminal_nombre=terminal_nombre or "Terminal",
        accion=accion,
        modulo=modulo,
        tabla_afectada=tabla_afectada,
        registro_id=effective_reg_id,
        valor_anterior=valor_anterior,
        valor_nuevo=valor_nuevo,
        descripcion=effective_desc,
        ip_address=ip_address,
    )
    try:
        if auto_commit:
            db.add(audit_entry)
            await db.commit()
        else:
            async with db.begin_nested():
                db.add(audit_entry)
                await db.flush()
    except Exception as exc:
        if auto_commit:
            try:
                await db.rollback()
            except Exception:
                pass
        logger.warning("Aviso registrando audit_log (%s/%s): %s", modulo, accion, exc)
