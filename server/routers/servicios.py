from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, or_, and_
from typing import Optional

from ..database import get_db
from ..models.servicio import Servicio
from ..schemas.servicio import ServicioCreate, ServicioUpdate, ServicioResponse
from ..schemas.common import PaginatedResponse
from ..middleware.auth import get_current_user, is_admin_role
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
    es_admin = is_admin_role(current_user)
    if not es_admin and rol != "operario":
        raise HTTPException(
            status_code=403,
            detail="Permisos insuficientes: solo administradores u operarios pueden crear servicios.",
        )

    datos = servicio.model_dump(exclude={"codigo"})
    pct = float(datos.get("porcentaje_comision") or 0.0)
    if pct < 0.0 or pct > 100.0:
        raise HTTPException(status_code=400, detail="El porcentaje de comisión debe estar entre 0 y 100.")
    if datos.get("proveedor_id"):
        datos["tipo_servicio"] = "TERCERO"
        datos["genera_comision"] = True

    if rol == "operario" and not es_admin:
        datos["solo_operarios"] = True
        datos["creado_por_operario_id"] = current_user.id
    elif not es_admin:
        datos["solo_operarios"] = False
        datos["creado_por_operario_id"] = None

    db_servicio = Servicio(**datos, codigo=codigo)
    db.add(db_servicio)
    await db.flush()
    await log_audit(
        db=db,
        usuario_id=current_user.id,
        usuario_nombre=current_user.nombre or current_user.usuario,
        terminal_id=None,
        terminal_nombre="Terminal",
        accion="CREAR",
        modulo="SERVICIOS",
        tabla_afectada="servicios",
        registro_id=str(db_servicio.id),
        valor_nuevo={
            "codigo": db_servicio.codigo,
            "nombre": db_servicio.nombre,
            "precio": getattr(db_servicio, "precio_venta", getattr(db_servicio, "precio", 0.0)),
            "porcentaje_comision": db_servicio.porcentaje_comision,
            "proveedor_id": db_servicio.proveedor_id,
        },
        auto_commit=False,
    )
    await db.commit()
    await db.refresh(db_servicio)
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
    es_admin = is_admin_role(current_user)
    if not es_admin:
        if rol != "operario" or servicio.creado_por_operario_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="Permisos insuficientes: solo puede editar sus propios servicios privados o requiere rol Administrador.",
            )

    estado_anterior = {
        "nombre": servicio.nombre,
        "precio": servicio.precio,
        "costo_unitario": getattr(servicio, "costo_unitario", 0.0),
        "porcentaje_comision": servicio.porcentaje_comision,
        "proveedor_id": servicio.proveedor_id,
        "estado": servicio.estado,
    }

    cambios = servicio_update.model_dump(exclude_unset=True)
    if "porcentaje_comision" in cambios and cambios["porcentaje_comision"] is not None:
        pct = float(cambios["porcentaje_comision"])
        if pct < 0.0 or pct > 100.0:
            raise HTTPException(status_code=400, detail="El porcentaje de comisión debe estar entre 0 y 100.")
    if not es_admin:
        cambios.pop("solo_operarios", None)
        cambios.pop("creado_por_operario_id", None)
    for key, value in cambios.items():
        setattr(servicio, key, value)
    if servicio.proveedor_id:
        servicio.tipo_servicio = "TERCERO"
        servicio.genera_comision = True

    estado_nuevo = {
        "nombre": servicio.nombre,
        "precio": servicio.precio,
        "costo_unitario": getattr(servicio, "costo_unitario", 0.0),
        "porcentaje_comision": servicio.porcentaje_comision,
        "proveedor_id": servicio.proveedor_id,
        "estado": servicio.estado,
    }
    await log_audit(
        db=db,
        usuario_id=current_user.id,
        usuario_nombre=current_user.nombre or current_user.usuario,
        terminal_id=None,
        terminal_nombre="Terminal",
        accion="EDITAR",
        modulo="SERVICIOS",
        tabla_afectada="servicios",
        registro_id=str(servicio.id),
        valor_anterior=estado_anterior,
        valor_nuevo=estado_nuevo,
        auto_commit=False,
    )
    await db.commit()
    await db.refresh(servicio)
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
    es_admin = is_admin_role(current_user)
    if not es_admin:
        if rol != "operario" or servicio.creado_por_operario_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="Permisos insuficientes: solo un administrador o el operario creador puede eliminar este servicio.",
            )
    snap = {
        "codigo": servicio.codigo,
        "nombre": servicio.nombre,
        "precio": getattr(servicio, "precio_venta", getattr(servicio, "precio", 0.0)),
    }
    await db.delete(servicio)
    await log_audit(
        db=db,
        usuario_id=current_user.id,
        usuario_nombre=current_user.nombre or current_user.usuario,
        terminal_id=None,
        terminal_nombre="Terminal",
        accion="ELIMINAR",
        modulo="SERVICIOS",
        tabla_afectada="servicios",
        registro_id=str(id),
        valor_anterior=snap,
        auto_commit=False,
    )
    await db.commit()
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
    rol = (current_user.rol or "").strip().lower()
    es_admin = is_admin_role(current_user)
    if not es_admin:
        if rol != "operario" or servicio.creado_por_operario_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="Permisos insuficientes para cambiar el estado de este servicio.",
            )
    estado_ant = servicio.estado
    servicio.estado = estado
    await log_audit(
        db=db,
        usuario_id=current_user.id,
        usuario_nombre=current_user.nombre or current_user.usuario,
        terminal_id=None,
        terminal_nombre="Terminal",
        accion="ESTADO",
        modulo="SERVICIOS",
        tabla_afectada="servicios",
        registro_id=str(servicio.id),
        valor_anterior={"estado": estado_ant},
        valor_nuevo={"estado": estado},
        auto_commit=False,
    )
    await db.commit()
    await db.refresh(servicio)
    return servicio
