from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from ..database import get_db
from ..models.finanzas import Gasto
from ..schemas.gasto import GastoCreate, GastoUpdate, GastoResponse
from ..middleware.auth import get_current_user
from ..models.usuario import Usuario

router = APIRouter(prefix="/gastos", tags=["gastos"])

@router.get("", response_model=List[GastoResponse])
async def list_gastos(db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Gasto))
    return result.scalars().all()

@router.post("", response_model=GastoResponse)
async def create_gasto(gasto: GastoCreate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    if gasto.metodo_pago not in ["Efectivo", "Transferencia"]:
        raise HTTPException(status_code=400, detail="El medio de pago debe ser Efectivo o Transferencia")
    db_gasto = Gasto(**gasto.model_dump(), usuario_id=current_user.id)
    db.add(db_gasto)
    await db.commit()
    await db.refresh(db_gasto)
    return db_gasto

@router.put("/{id}", response_model=GastoResponse)
async def update_gasto(id: int, gasto_update: GastoUpdate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Gasto).where(Gasto.id == id))
    gasto = result.scalars().first()
    if not gasto:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    if gasto.tipo != 'Manual':
        raise HTTPException(status_code=400, detail="Solo se pueden editar gastos manuales")
    if gasto_update.metodo_pago is not None and gasto_update.metodo_pago not in ["Efectivo", "Transferencia"]:
        raise HTTPException(status_code=400, detail="El medio de pago debe ser Efectivo o Transferencia")
        
    for key, value in gasto_update.model_dump(exclude_unset=True).items():
        setattr(gasto, key, value)
    await db.commit()
    await db.refresh(gasto)
    return gasto

@router.delete("/{id}")
async def delete_gasto(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Gasto).where(Gasto.id == id))
    gasto = result.scalars().first()
    if not gasto:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    if gasto.tipo != 'Manual':
        raise HTTPException(status_code=400, detail="Solo se pueden eliminar gastos manuales")
    
    # Actually just delete since there's no estado in Gasto model, or we just throw error
    await db.delete(gasto)
    await db.commit()
    return {"message": "Gasto eliminado"}
