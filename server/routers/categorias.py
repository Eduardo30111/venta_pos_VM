from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from ..database import get_db
from ..models.categoria import Categoria
from ..schemas.categoria import CategoriaCreate, CategoriaUpdate, CategoriaResponse
from ..middleware.auth import get_current_user
from ..models.usuario import Usuario

router = APIRouter(prefix="/categorias", tags=["categorias"])

@router.get("", response_model=List[CategoriaResponse])
async def list_categorias(db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Categoria))
    return result.scalars().all()

@router.post("", response_model=CategoriaResponse)
async def create_categoria(cat: CategoriaCreate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    db_cat = Categoria(**cat.model_dump())
    db.add(db_cat)
    await db.commit()
    await db.refresh(db_cat)
    return db_cat

@router.put("/{id}", response_model=CategoriaResponse)
async def update_categoria(id: int, cat_update: CategoriaUpdate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Categoria).where(Categoria.id == id))
    cat = result.scalars().first()
    if not cat:
        raise HTTPException(status_code=404, detail="Categoria no encontrada")
    for key, value in cat_update.model_dump(exclude_unset=True).items():
        setattr(cat, key, value)
    await db.commit()
    await db.refresh(cat)
    return cat
