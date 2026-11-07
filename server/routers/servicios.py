from fastapi import APIRouter, Depends, HTTPException
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
async def list_servicios(
    page: int = 1,
    size: int = 1000,
    nombre: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    query = select(Servicio)
    rol = (current_user.rol or "").strip().lower()
    if rol == "operario":
        query = query.where(
            or_(
                Servicio.creado_por_operario_id.is_(None),
                Servicio.creado_por_operario_id == current_user.id,
            )
        )
    if nombre:
        query = query.where(Servicio.nombre.ilike(f"%{nombre}%"))

    count_q = select(func.count()).select_from(query.subquery())
    total = int((await db.execute(count_q)).scalar() or 0)

    result = await db.execute(query.order_by(Servicio.nombre.asc()).offset((page - 1) * size).limit(size))
    items = result.scalars().all()
    pages = max(1, (total + size - 1) // size)
    return PaginatedResponse(items=items, total=total, page=page, size=size, pages=pages)


@router.get("/{id}", response_model=ServicioResponse)
async def get_servicio(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    result = await db.execute(select(Servicio).where(Servicio.id == id))
    servicio = result.scalars().first()
    if not servicio:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    return servicio


@router.post("", response_model=ServicioResponse)
async def create_servicio(
    servicio: ServicioCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    codigo_custom = (servicio.codigo or "").strip()
    if codigo_custom:
        dup = await db.execute(select(Servicio).where(Servicio.codigo == codigo_custom))
        if dup.scalars().first():
            raise HTTPException(status_code=400, detail=f"El código {codigo_custom} ya existe")
        codigo = codigo_custom
    else:
        result = await db.execute(select(Servicio.codigo))
        codigos = result.scalars().all()
        max_cod = 0
        for c in codigos:
            if c:
                num_part = c[1:] if str(c).startswith("S") else str(c)
                if num_part.isdigit():
                    max_cod = max(max_cod, int(num_part))
        codigo = f"S{max_cod + 1:05d}"

    rol = (current_user.rol or "").strip().lower()
    datos = servicio.model_dump(exclude={"codigo"})
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
async def update_servicio(
    id: int,
    servicio_update: ServicioUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    result = await db.execute(select(Servicio).where(Servicio.id == id))
    servicio = result.scalars().first()
    if not servicio:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    rol = (current_user.rol or "").strip().lower()
    if rol == "operario" and servicio.creado_por_operario_id not in (None, current_user.id):
        raise HTTPException(status_code=403, detail="No puede editar un servicio privado de otro usuario")

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
async def delete_servicio(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    result = await db.execute(select(Servicio).where(Servicio.id == id))
    servicio = result.scalars().first()
    if not servicio:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    rol = (current_user.rol or "").strip().lower()
    if rol == "operario" and servicio.creado_por_operario_id != current_user.id:
        raise HTTPException(status_code=403, detail="No puede eliminar un servicio de otro usuario")
    await db.delete(servicio)
    await db.commit()
    await log_audit(db, current_user.id, current_user.nombre, None, None, "ELIMINAR", "SERVICIOS", "servicios", str(id))
    return {"message": "Servicio eliminado exitosamente"}


@router.patch("/{id}/estado", response_model=ServicioResponse)
async def change_estado(
    id: int,
    estado: str,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    result = await db.execute(select(Servicio).where(Servicio.id == id))
    servicio = result.scalars().first()
    if not servicio:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    servicio.estado = estado
    await db.commit()
    await db.refresh(servicio)
    await log_audit(db, current_user.id, current_user.nombre, None, None, "ESTADO", "SERVICIOS", "servicios", str(servicio.id))
    return servicio
