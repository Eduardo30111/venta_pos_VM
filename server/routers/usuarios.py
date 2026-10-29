from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from ..database import get_db
from ..models.usuario import Usuario
from ..models.permiso import PermisoUsuario
from ..schemas.usuario import UserCreate, UserUpdate, UserResponse
from ..schemas.common import PaginatedResponse
from ..middleware.auth import get_current_user, hash_password

router = APIRouter(prefix="/usuarios", tags=["usuarios"])

@router.get("", response_model=PaginatedResponse[UserResponse])
async def list_usuarios(page: int = 1, size: int = 1000, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Usuario).offset((page - 1) * size).limit(size))
    items = result.scalars().all()
    total = len(items)
    return PaginatedResponse(items=items, total=total, page=page, size=size, pages=1)

@router.get("/{id}", response_model=UserResponse)
async def get_usuario(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Usuario).where(Usuario.id == id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return user

@router.post("", response_model=UserResponse)
async def create_usuario(user: UserCreate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    # Check if username already exists
    exist = await db.execute(select(Usuario).where(Usuario.usuario == user.usuario))
    if exist.scalars().first():
        raise HTTPException(status_code=400, detail=f"El nombre de usuario '{user.usuario}' ya existe.")
        
    if user.documento:
        exist_doc = await db.execute(select(Usuario).where(Usuario.documento == user.documento))
        if exist_doc.scalars().first():
            raise HTTPException(status_code=400, detail=f"El documento '{user.documento}' ya está registrado.")

    db_user = Usuario(
        nombre=user.nombre or "",
        apellidos=user.apellidos or "",
        documento=user.documento or None,
        usuario=user.usuario,
        password_hash=hash_password(user.password),
        rol=user.rol,
        tipo_remuneracion=user.tipo_remuneracion or "Porcentual",
        salario_diario=user.salario_diario or 0.0,
        porcentaje_comision=user.porcentaje_comision or 0.0,
        estado=user.estado or "Activo"
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user

@router.put("/{id}", response_model=UserResponse)
async def update_usuario(id: int, user_update: UserUpdate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Usuario).where(Usuario.id == id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    update_data = user_update.model_dump(exclude_unset=True)
    if "password" in update_data and update_data["password"]:
        update_data["password_hash"] = hash_password(update_data.pop("password"))
    elif "password" in update_data:
        update_data.pop("password")
        
    for key, value in update_data.items():
        setattr(user, key, value)
        
    await db.commit()
    await db.refresh(user)
    return user

@router.delete("/{id}")
async def delete_usuario(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Usuario).where(Usuario.id == id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="No puedes eliminar tu propio usuario de sesión.")
        
    from sqlalchemy import delete
    await db.execute(delete(PermisoUsuario).where(PermisoUsuario.usuario_id == id))
    await db.delete(user)
    await db.commit()
    return {"message": "Usuario eliminado exitosamente"}

@router.patch("/{id}/estado", response_model=UserResponse)
async def change_estado(id: int, estado: str, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Usuario).where(Usuario.id == id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    user.estado = estado
    await db.commit()
    await db.refresh(user)
    return user

@router.get("/{id}/permisos")
async def get_permisos(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(PermisoUsuario).where(PermisoUsuario.usuario_id == id))
    return result.scalars().all()

@router.put("/{id}/permisos")
async def update_permisos(id: int, permisos: List[str], db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    # Simple replace logic
    pass # To be implemented fully based on requirements
