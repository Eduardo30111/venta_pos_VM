from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, or_, and_
from typing import Optional
from ..database import get_db
from ..models.servicio import Servicio
from ..schemas.servicio import ServicioCreate, ServicioUpdate, ServicioResponse
from ..schemas.common import PaginatedResponse
from ..middleware.auth import get_current_user
from ..models.usuario import Usuario
from ..middleware.audit import log_audit

router = APIRouter(prefix="/servicios", tags=["servicios"])

@router.get("", response_model=PaginatedResponse[ServicioResponse])
async def list_servicios(page: int = 1, size: int = 10, nombre: Optional[str] = None, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    query = select(Servicio)
    rol = (current_user.rol or "").strip().lower()
    if rol == "operario":
        query = query.where(or_(
            and_(Servicio.solo_operarios == True, Servicio.creado_por_operario_id.is_(None)),
            Servicio.creado_por_operario_id == current_user.id
        ))
    else:
        query = query.where(
            Servicio.solo_operarios == False,
            Servicio.creado_por_operario_id.is_(None)
        )
    if nombre:
        query = query.where(Servicio.nombre.ilike(f"%{nombre}%"))
        
    result = await db.execute(query.offset((page - 1) * size).limit(size))
    items = result.scalars().all()
    total = len(items)
    return PaginatedResponse(items=items, total=total, page=page, size=size, pages=1)

@router.get("/{id}", response_model=ServicioResponse)
async def get_servicio(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    rol = (current_user.rol or "").strip().lower()
    visibility = or_(
        and_(rol == "operario", Servicio.solo_operarios == True, Servicio.creado_por_operario_id.is_(None)),
        and_(rol == "operario", Servicio.creado_por_operario_id == current_user.id),
        and_(rol != "operario", Servicio.solo_operarios == False, Servicio.creado_por_operario_id.is_(None))
    )
    result = await db.execute(select(Servicio).where(Servicio.id == id, visibility))
    servicio = result.scalars().first()
    if not servicio:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    return servicio

@router.post("", response_model=ServicioResponse)
async def create_servicio(servicio: ServicioCreate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    async with db.begin_nested():
        result = await db.execute(select(Servicio.codigo))
        codigos = result.scalars().all()
        max_cod = 0
        for c in codigos:
            if c:
                num_part = c[1:] if str(c).startswith("S") else str(c)
                if num_part.isdigit():
                    max_cod = max(max_cod, int(num_part))
        next_cod = max_cod + 1
        codigo = f"S{next_cod:05d}"
        
        rol = (current_user.rol or "").strip().lower()
        datos = servicio.model_dump(exclude={'codigo'})
        if rol == "operario":
            datos["solo_operarios"] = True
            datos["creado_por_operario_id"] = current_user.id
        elif rol not in ["administrador", "admin", "gerente"]:
            datos["solo_operarios"] = False
            datos["creado_por_operario_id"] = None
        db_servicio = Servicio(**datos, codigo=codigo)
        db.add(db_servicio)
        
    await db.commit()
    await db.refresh(db_servicio)
    await log_audit(db, current_user.id, current_user.nombre, None, None, "CREAR", "SERVICIOS", "servicios", str(db_servicio.id))
    return db_servicio

@router.put("/{id}", response_model=ServicioResponse)
async def update_servicio(id: int, servicio_update: ServicioUpdate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Servicio).where(Servicio.id == id))
    servicio = result.scalars().first()
    if not servicio:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    rol = (current_user.rol or "").strip().lower()
    if rol == "operario" and servicio.creado_por_operario_id != current_user.id:
        raise HTTPException(status_code=403, detail="No puede editar un servicio de otro usuario")
    if rol not in ["administrador", "admin", "gerente"] and rol != "operario":
        raise HTTPException(status_code=403, detail="Solo el administrador puede gestionar servicios")
        
    cambios = servicio_update.model_dump(exclude_unset=True)
    if rol == "operario":
        cambios.pop("solo_operarios", None)
    for key, value in cambios.items():
        setattr(servicio, key, value)
        
    await db.commit()
    await db.refresh(servicio)
    await log_audit(db, current_user.id, current_user.nombre, None, None, "EDITAR", "SERVICIOS", "servicios", str(servicio.id))
    return servicio

@router.delete("/{id}")
async def delete_servicio(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Servicio).where(Servicio.id == id))
    servicio = result.scalars().first()
    if not servicio:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    rol = (current_user.rol or "").strip().lower()
    if rol == "operario" and servicio.creado_por_operario_id != current_user.id:
        raise HTTPException(status_code=403, detail="No puede eliminar un servicio de otro usuario")
    if rol not in ["administrador", "admin", "gerente", "operario"]:
        raise HTTPException(status_code=403, detail="No tiene permisos para eliminar servicios")
    await db.delete(servicio)
    await db.commit()
    await log_audit(db, current_user.id, current_user.nombre, None, None, "ELIMINAR", "SERVICIOS", "servicios", str(id))
    return {"message": "Servicio eliminado exitosamente"}

@router.patch("/{id}/estado", response_model=ServicioResponse)
async def change_estado(id: int, estado: str, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Servicio).where(Servicio.id == id))
    servicio = result.scalars().first()
    if not servicio:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    servicio.estado = estado
    await db.commit()
    await db.refresh(servicio)
    await log_audit(db, current_user.id, current_user.nombre, None, None, "ESTADO", "SERVICIOS", "servicios", str(servicio.id))
    return servicio
