from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from ..database import get_db
from ..models.auditoria import AuditLog
from ..middleware.auth import require_admin
from ..models.usuario import Usuario

router = APIRouter(prefix="/auditoria", tags=["auditoria"])

@router.get("")
async def listar_auditoria(limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(require_admin)):
    safe_limit = max(1, min(int(limit or 50), 500))
    safe_offset = max(0, int(offset or 0))
    result = await db.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(safe_limit).offset(safe_offset)
    )
    logs = result.scalars().all()
    return logs
