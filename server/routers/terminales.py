from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from pydantic import BaseModel
from ..database import get_db
from ..models.terminal import Terminal
from ..middleware.auth import get_current_user

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
async def create_terminal(terminal: TerminalBase, db: AsyncSession = Depends(get_db), current_user = Depends(get_current_user)):
    db_terminal = Terminal(**terminal.model_dump())
    db.add(db_terminal)
    await db.commit()
    await db.refresh(db_terminal)
    return db_terminal

@router.put("/{id}", response_model=TerminalResponse)
async def update_terminal(id: int, terminal_update: TerminalBase, db: AsyncSession = Depends(get_db), current_user = Depends(get_current_user)):
    result = await db.execute(select(Terminal).where(Terminal.id == id))
    terminal = result.scalars().first()
    if not terminal:
        raise HTTPException(status_code=404, detail="Terminal no encontrada")
    
    for key, value in terminal_update.model_dump(exclude_unset=True).items():
        setattr(terminal, key, value)
        
    await db.commit()
    await db.refresh(terminal)
    return terminal
