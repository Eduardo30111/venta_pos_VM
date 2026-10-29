from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from ..database import get_db
from ..models.proveedor import Proveedor
from ..schemas.proveedor import ProveedorCreate, ProveedorUpdate, ProveedorResponse
from ..middleware.auth import get_current_user
from ..models.usuario import Usuario

router = APIRouter(prefix="/proveedores", tags=["proveedores"])

@router.get("", response_model=List[ProveedorResponse])
async def list_proveedores(db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Proveedor))
    return result.scalars().all()

@router.get("/{id}", response_model=ProveedorResponse)
async def get_proveedor(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Proveedor).where(Proveedor.id == id))
    proveedor = result.scalars().first()
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    return proveedor

@router.post("", response_model=ProveedorResponse)
async def create_proveedor(proveedor: ProveedorCreate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    db_prov = Proveedor(**proveedor.model_dump())
    db.add(db_prov)
    await db.commit()
    await db.refresh(db_prov)
    return db_prov

@router.put("/{id}", response_model=ProveedorResponse)
async def update_proveedor(id: int, prov_update: ProveedorUpdate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Proveedor).where(Proveedor.id == id))
    proveedor = result.scalars().first()
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    for key, value in prov_update.model_dump(exclude_unset=True).items():
        setattr(proveedor, key, value)
    await db.commit()
    await db.refresh(proveedor)
    return proveedor

@router.patch("/{id}/estado", response_model=ProveedorResponse)
async def change_estado(id: int, estado: str, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Proveedor).where(Proveedor.id == id))
    proveedor = result.scalars().first()
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    proveedor.estado = estado
    await db.commit()
    await db.refresh(proveedor)
    return proveedor
