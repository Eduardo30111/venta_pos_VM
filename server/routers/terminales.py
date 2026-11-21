from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from pydantic import BaseModel
from ..database import get_db
from ..models.terminal import Terminal
from ..middleware.auth import get_current_user, require_admin
from ..middleware.audit import log_audit

router = APIRouter(prefix="/terminales", tags=["terminales"])

class TerminalBase(BaseModel):
    nombre: str
    descripcion: str = None
    estado: str = "Activo"

class TerminalResponse(TerminalBase):
    id: int
    class Config:
        from_attributes = True

@router.get("", response_model=List[TerminalResponse])
async def list_terminales(db: AsyncSession = Depends(get_db), current_user = Depends(get_current_user)):
    result = await db.execute(select(Terminal))
    return result.scalars().all()

@router.post("", response_model=TerminalResponse)
async def create_terminal(terminal: TerminalBase, db: AsyncSession = Depends(get_db), current_user = Depends(require_admin)):
    db_terminal = Terminal(**terminal.model_dump())
    db.add(db_terminal)
    await db.flush()
    await log_audit(
        db=db,
        modulo="TERMINALES",
        accion="CREAR",
        entidad_id=db_terminal.id,
        usuario_id=current_user.id,
        usuario_nombre=current_user.nombre or current_user.usuario,
        valor_nuevo=terminal.model_dump(),
        auto_commit=False,
    )
    await db.commit()
    await db.refresh(db_terminal)
    return db_terminal

@router.put("/{id}", response_model=TerminalResponse)
async def update_terminal(id: int, terminal_update: TerminalBase, db: AsyncSession = Depends(get_db), current_user = Depends(require_admin)):
    result = await db.execute(select(Terminal).where(Terminal.id == id))
    terminal = result.scalars().first()
    if not terminal:
        raise HTTPException(status_code=404, detail="Terminal no encontrada")
    
    anterior = {"nombre": terminal.nombre, "descripcion": terminal.descripcion, "estado": terminal.estado}
    cambios = terminal_update.model_dump(exclude_unset=True)
    for key, value in cambios.items():
        setattr(terminal, key, value)
        
    await log_audit(
        db=db,
        modulo="TERMINALES",
        accion="EDITAR",
        entidad_id=terminal.id,
        usuario_id=current_user.id,
        usuario_nombre=current_user.nombre or current_user.usuario,
        valor_anterior=anterior,
        valor_nuevo=cambios,
        auto_commit=False,
    )
    await db.commit()
    await db.refresh(terminal)
    return terminal
