from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from ..database import get_db
from ..models.usuario import Usuario
from ..models.permiso import PermisoUsuario
from ..schemas.usuario import UserCreate, UserUpdate, UserResponse
from ..schemas.common import PaginatedResponse
from ..middleware.auth import (
    get_current_user,
    hash_password,
    is_admin_role,
    require_admin,
    validar_password_fuerte_servidor,
)
from ..middleware.audit import log_audit

router = APIRouter(prefix="/usuarios", tags=["usuarios"])


@router.get("", response_model=PaginatedResponse[UserResponse])
async def list_usuarios(
    page: int = 1,
    size: int = 1000,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
):
    result = await db.execute(select(Usuario).offset((page - 1) * size).limit(size))
    items = result.scalars().all()
    total = len(items)
    return PaginatedResponse(items=items, total=total, page=page, size=size, pages=1)


@router.get("/{id}", response_model=UserResponse)
async def get_usuario(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    if not is_admin_role(current_user) and current_user.id != id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado para consultar otros usuarios.")
    result = await db.execute(select(Usuario).where(Usuario.id == id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return user


@router.post("", response_model=UserResponse)
async def create_usuario(
    user: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
):
    ok_pwd, msg_pwd = validar_password_fuerte_servidor(user.password)
    if not ok_pwd:
        raise HTTPException(status_code=400, detail=msg_pwd)

    exist = await db.execute(select(Usuario).where(Usuario.usuario == user.usuario))
    if exist.scalars().first():
        raise HTTPException(status_code=400, detail=f"El nombre de usuario '{user.usuario}' ya existe.")

    if user.documento:
        exist_doc = await db.execute(select(Usuario).where(Usuario.documento == user.documento))
        if exist_doc.scalars().first():
            raise HTTPException(status_code=400, detail=f"El documento '{user.documento}' ya está registrado.")

    tipo_rem = user.tipo_remuneracion or "Porcentual"
    salario_final = (user.salario_diario or 0.0) if tipo_rem == "Fija" else 0.0
    comision_final = (user.porcentaje_comision or 0.0) if tipo_rem == "Porcentual" else 0.0

    db_user = Usuario(
        nombre=user.nombre or "",
        apellidos=user.apellidos or "",
        documento=user.documento or None,
        usuario=user.usuario,
        password_hash=hash_password(user.password),
        rol=user.rol,
        tipo_remuneracion=tipo_rem,
        salario_diario=salario_final,
        porcentaje_comision=comision_final,
        estado=user.estado or "Activo",
        requiere_cambio_password=False,
    )
    db.add(db_user)
    await db.flush()

    client_ip = request.client.host if request.client else None
    await log_audit(
        db=db,
        usuario_id=current_user.id,
        usuario_nombre=f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario,
        accion="CREAR_USUARIO",
        modulo="USUARIOS",
        tabla_afectada="usuarios",
        registro_id=str(db_user.id),
        valor_nuevo={
            "usuario": db_user.usuario,
            "rol": db_user.rol,
            "estado": db_user.estado,
            "tipo_remuneracion": db_user.tipo_remuneracion,
        },
        ip_address=client_ip,
        auto_commit=False,
    )
    await db.commit()
    await db.refresh(db_user)
    return db_user


@router.put("/{id}", response_model=UserResponse)
async def update_usuario(
    id: int,
    user_update: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    es_admin = is_admin_role(current_user)
    update_data = user_update.model_dump(exclude_unset=True)

    # Control estricto anti-escalada de privilegios:
    # Los usuarios no administradores únicamente pueden cambiar su propia contraseña.
    if not es_admin:
        if current_user.id != id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo un administrador puede modificar otros usuarios.",
            )
        campos_prohibidos = set(update_data.keys()) - {"password"}
        if campos_prohibidos:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"No autorizado para modificar los campos: {', '.join(sorted(campos_prohibidos))}.",
            )

    result = await db.execute(select(Usuario).where(Usuario.id == id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    valor_anterior = {
        "usuario": user.usuario,
        "rol": user.rol,
        "estado": user.estado,
        "tipo_remuneracion": user.tipo_remuneracion,
        "salario_diario": user.salario_diario,
        "porcentaje_comision": user.porcentaje_comision,
    }

    cambio_pwd = False
    if "password" in update_data and update_data["password"]:
        new_pwd = update_data.pop("password")
        ok_pwd, msg_pwd = validar_password_fuerte_servidor(new_pwd)
        if not ok_pwd:
            raise HTTPException(status_code=400, detail=msg_pwd)
        update_data["password_hash"] = hash_password(new_pwd)
        update_data["requiere_cambio_password"] = False
        cambio_pwd = True
    elif "password" in update_data:
        update_data.pop("password")

    for key, value in update_data.items():
        setattr(user, key, value)

    # Limpieza absoluta de residuos cruzados al cambiar esquema de remuneración
    if user.tipo_remuneracion == "Fija":
        user.porcentaje_comision = 0.0
    elif user.tipo_remuneracion == "Porcentual":
        user.salario_diario = 0.0

    valor_nuevo = {
        "usuario": user.usuario,
        "rol": user.rol,
        "estado": user.estado,
        "tipo_remuneracion": user.tipo_remuneracion,
        "salario_diario": user.salario_diario,
        "porcentaje_comision": user.porcentaje_comision,
        "password_actualizada": cambio_pwd,
    }

    client_ip = request.client.host if request.client else None
    await log_audit(
        db=db,
        usuario_id=current_user.id,
        usuario_nombre=f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario,
        accion="EDITAR_USUARIO",
        modulo="USUARIOS",
        tabla_afectada="usuarios",
        registro_id=str(user.id),
        valor_anterior=valor_anterior,
        valor_nuevo=valor_nuevo,
        ip_address=client_ip,
        auto_commit=False,
    )
    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/{id}")
async def delete_usuario(
    id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
):
    result = await db.execute(select(Usuario).where(Usuario.id == id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="No puedes eliminar tu propio usuario de sesión.")

    val_ant = {"usuario": user.usuario, "rol": user.rol, "estado": user.estado}
    await db.execute(delete(PermisoUsuario).where(PermisoUsuario.usuario_id == id))
    await db.delete(user)

    client_ip = request.client.host if request.client else None
    await log_audit(
        db=db,
        usuario_id=current_user.id,
        usuario_nombre=f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario,
        accion="ELIMINAR_USUARIO",
        modulo="USUARIOS",
        tabla_afectada="usuarios",
        registro_id=str(id),
        valor_anterior=val_ant,
        ip_address=client_ip,
        auto_commit=False,
    )
    await db.commit()
    return {"message": "Usuario eliminado exitosamente"}


@router.patch("/{id}/estado", response_model=UserResponse)
async def change_estado(
    id: int,
    estado: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
):
    result = await db.execute(select(Usuario).where(Usuario.id == id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if user.id == current_user.id and estado.strip().lower() != "activo":
        raise HTTPException(status_code=400, detail="No puedes desactivar tu propio usuario administrador.")

    est_ant = user.estado
    user.estado = estado

    client_ip = request.client.host if request.client else None
    await log_audit(
        db=db,
        usuario_id=current_user.id,
        usuario_nombre=f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario,
        accion="CAMBIAR_ESTADO_USUARIO",
        modulo="USUARIOS",
        tabla_afectada="usuarios",
        registro_id=str(user.id),
        valor_anterior={"estado": est_ant},
        valor_nuevo={"estado": estado},
        ip_address=client_ip,
        auto_commit=False,
    )
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/{id}/permisos")
async def get_permisos(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
):
    result = await db.execute(select(PermisoUsuario).where(PermisoUsuario.usuario_id == id))
    return result.scalars().all()


@router.put("/{id}/permisos")
async def update_permisos(
    id: int,
    permisos: List[str],
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
):
    res_u = await db.execute(select(Usuario).where(Usuario.id == id))
    user = res_u.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    res_prev = await db.execute(select(PermisoUsuario).where(PermisoUsuario.usuario_id == id))
    prev_perms = sorted({p.permiso for p in res_prev.scalars().all() if p.concedido})
    nuevos_perms = sorted({str(p).strip() for p in permisos if str(p).strip()})

    await db.execute(delete(PermisoUsuario).where(PermisoUsuario.usuario_id == id))
    for p_nom in nuevos_perms:
        db.add(PermisoUsuario(usuario_id=id, permiso=p_nom, concedido=True))

    client_ip = request.client.host if request.client else None
    await log_audit(
        db=db,
        usuario_id=current_user.id,
        usuario_nombre=f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario,
        accion="ACTUALIZAR_PERMISOS",
        modulo="USUARIOS",
        tabla_afectada="permisos_usuario",
        registro_id=str(id),
        valor_anterior={"permisos": prev_perms},
        valor_nuevo={"permisos": nuevos_perms},
        ip_address=client_ip,
        auto_commit=False,
    )
    await db.commit()
    return {"ok": True, "usuario_id": id, "permisos": nuevos_perms}
