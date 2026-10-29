from sqlalchemy.ext.asyncio import AsyncSession
from ..models.auditoria import AuditLog

async def log_audit(db: AsyncSession, usuario_id: int, usuario_nombre: str, terminal_id: int, terminal_nombre: str, accion: str, modulo: str, tabla_afectada: str, registro_id: str, valor_anterior: dict = None, valor_nuevo: dict = None, descripcion: str = None, ip_address: str = None):
    audit_entry = AuditLog(
        usuario_id=usuario_id,
        usuario_nombre=usuario_nombre,
        terminal_id=terminal_id,
        terminal_nombre=terminal_nombre,
        accion=accion,
        modulo=modulo,
        tabla_afectada=tabla_afectada,
        registro_id=registro_id,
        valor_anterior=valor_anterior,
        valor_nuevo=valor_nuevo,
        descripcion=descripcion,
        ip_address=ip_address
    )
    db.add(audit_entry)
    await db.commit()
