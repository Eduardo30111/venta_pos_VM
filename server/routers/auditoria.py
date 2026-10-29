from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from ..database import get_db
from ..models.auditoria import AuditLog
from ..middleware.auth import get_current_user
from ..models.usuario import Usuario

router = APIRouter(prefix="/auditoria", tags=["auditoria"])

@router.get("")
async def listar_auditoria(limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    )
    logs = result.scalars().all()
    return logs
