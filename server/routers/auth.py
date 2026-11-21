import time
import uuid
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..config import settings
from ..database import get_db
from ..schemas.usuario import LoginRequest, TokenResponse, UserResponse
from ..models.usuario import Usuario
from ..models.sesion import Sesion
from ..models.terminal import Terminal
from ..async_lock import LazyAsyncLock
from ..middleware.audit import log_audit
from ..middleware.auth import (
    hash_password,
    verify_and_rehash_password,
    dummy_verify_password,
    validar_password_fuerte_servidor,
    create_access_token,
    get_current_user,
)

logger = logging.getLogger("vmpos.auth")
router = APIRouter(prefix="/auth", tags=["auth"])

_BOOTSTRAP_LOCK = LazyAsyncLock()

# Protección contra ataques de fuerza bruta (ventana deslizante en memoria)
_MAX_LOGIN_ATTEMPTS = 5
_LOCKOUT_WINDOW_SECONDS = 300
_LOGIN_ATTEMPTS: Dict[str, List[float]] = defaultdict(list)


def reset_login_rate_limits() -> None:
    """Limpia los contadores de tasa de login (útil para suites de pruebas aisladas)."""
    _LOGIN_ATTEMPTS.clear()


def _attempt_key(usuario: str, ip: Optional[str]) -> str:
    return f"{(usuario or '').strip().lower()}|{(ip or 'local').strip()}"


def _is_rate_limited(key: str, now_ts: float) -> bool:
    cutoff = now_ts - _LOCKOUT_WINDOW_SECONDS
    recent = [t for t in _LOGIN_ATTEMPTS.get(key, []) if t > cutoff]
    if recent:
        _LOGIN_ATTEMPTS[key] = recent
    else:
        _LOGIN_ATTEMPTS.pop(key, None)
    return len(recent) >= _MAX_LOGIN_ATTEMPTS


def _record_failed_attempt(key: str, now_ts: float) -> int:
    cutoff = now_ts - _LOCKOUT_WINDOW_SECONDS
    recent = [t for t in _LOGIN_ATTEMPTS.get(key, []) if t > cutoff]
    recent.append(now_ts)
    _LOGIN_ATTEMPTS[key] = recent
    return len(recent)


def _clear_failed_attempts(key: str) -> None:
    _LOGIN_ATTEMPTS.pop(key, None)


class BootstrapAdminRequest(BaseModel):
    usuario: str
    password: str
    nombre: str = "Administrador"
    apellidos: str = "Principal"


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.get("/bootstrap-status")
async def bootstrap_status(db: AsyncSession = Depends(get_db)):
    """
    Indica de forma segura (fail-closed) si el servidor requiere activación inicial
    por ausencia absoluta de cuentas de Administrador.
    """
    try:
        res = await db.execute(
            select(func.count(Usuario.id)).where(
                func.lower(Usuario.rol).in_(("administrador", "admin"))
            )
        )
        total_admins = int(res.scalar() or 0)
        return {
            "requiere_activacion": total_admins == 0,
            "administradores_activos": total_admins,
        }
    except Exception as exc:
        logger.critical("Error consultando estado de activación inicial: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo verificar el estado de seguridad de la base de datos.",
        )


@router.post("/bootstrap-admin")
async def bootstrap_admin(
    payload: BootstrapAdminRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Activación inicial segura de un solo uso para crear el primer Administrador.
    Se bloquea permanentemente con HTTP 403 en cuanto existe al menos un administrador.
    """
    async with _BOOTSTRAP_LOCK:
        res = await db.execute(
            select(func.count(Usuario.id)).where(
                func.lower(Usuario.rol).in_(("administrador", "admin"))
            )
        )
        total_admins = int(res.scalar() or 0)
        if total_admins > 0:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="El sistema ya fue activado y cuenta con un administrador configurado.",
            )

        u_limpio = (payload.usuario or "").strip()
        if len(u_limpio) < 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El nombre de usuario debe tener al menos 3 caracteres.",
            )

        ok_pwd, msg_pwd = validar_password_fuerte_servidor(payload.password)
        if not ok_pwd:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg_pwd)

        dup = await db.execute(select(Usuario).where(func.lower(Usuario.usuario) == u_limpio.lower()))
        if dup.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El nombre de usuario '{u_limpio}' ya existe.",
            )

        nuevo_admin = Usuario(
            nombre=(payload.nombre or "Administrador").strip(),
            apellidos=(payload.apellidos or "Principal").strip(),
            documento=None,
            usuario=u_limpio,
            password_hash=hash_password(payload.password.strip()),
            rol="Administrador",
            tipo_remuneracion="Fija",
            estado="Activo",
            requiere_cambio_password=False,
        )
        db.add(nuevo_admin)
        await db.flush()

        client_ip = request.client.host if request.client else None
        await log_audit(
            db=db,
            usuario_id=nuevo_admin.id,
            usuario_nombre=f"{nuevo_admin.nombre} {nuevo_admin.apellidos}".strip(),
            terminal_id=1,
            terminal_nombre="Servidor",
            accion="ACTIVACION_INICIAL_ADMIN",
            modulo="SEGURIDAD",
            tabla_afectada="usuarios",
            registro_id=str(nuevo_admin.id),
            valor_nuevo={"usuario": nuevo_admin.usuario, "rol": "Administrador"},
            ip_address=client_ip,
            auto_commit=False,
        )
        await db.commit()
        await db.refresh(nuevo_admin)

        return {
            "ok": True,
            "id": nuevo_admin.id,
            "usuario": nuevo_admin.usuario,
            "rol": nuevo_admin.rol,
            "message": "Administrador inicial activado correctamente.",
        }


@router.post("/login", response_model=TokenResponse)
async def login(request_body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    client_ip = request.client.host if request.client else "local"
    rate_key = _attempt_key(request_body.usuario, client_ip)
    now_ts = time.time()

    if _is_rate_limited(rate_key, now_ts):
        await log_audit(
            db=db,
            usuario_id=0,
            usuario_nombre=request_body.usuario,
            terminal_id=request_body.terminal_id,
            terminal_nombre=f"Terminal-{request_body.terminal_id or 1}",
            accion="LOGIN_BLOQUEADO",
            modulo="SEGURIDAD",
            tabla_afectada="usuarios",
            registro_id=request_body.usuario,
            descripcion="Bloqueo temporal por múltiples intentos fallidos de inicio de sesión",
            ip_address=client_ip,
            auto_commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos fallidos. Espere 5 minutos antes de volver a intentar.",
        )

    result = await db.execute(select(Usuario).where(Usuario.usuario == request_body.usuario))
    user = result.scalars().first()

    if not user:
        dummy_verify_password(request_body.password)
        _record_failed_attempt(rate_key, now_ts)
        await log_audit(
            db=db,
            usuario_id=0,
            usuario_nombre=request_body.usuario,
            terminal_id=request_body.terminal_id,
            terminal_nombre=f"Terminal-{request_body.terminal_id or 1}",
            accion="LOGIN_FALLIDO",
            modulo="SEGURIDAD",
            tabla_afectada="usuarios",
            registro_id=request_body.usuario,
            descripcion="Intento de acceso con usuario inexistente",
            ip_address=client_ip,
            auto_commit=True,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales invalidas")

    es_valido, debe_rehashear, nuevo_hash = verify_and_rehash_password(request_body.password, user.password_hash)
    if not es_valido:
        _record_failed_attempt(rate_key, now_ts)
        await log_audit(
            db=db,
            usuario_id=user.id,
            usuario_nombre=user.usuario,
            terminal_id=request_body.terminal_id,
            terminal_nombre=f"Terminal-{request_body.terminal_id or 1}",
            accion="LOGIN_FALLIDO",
            modulo="SEGURIDAD",
            tabla_afectada="usuarios",
            registro_id=str(user.id),
            descripcion="Contraseña incorrecta",
            ip_address=client_ip,
            auto_commit=True,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales invalidas")

    if str(user.estado or "").strip().lower() != "activo":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo")

    # Migración progresiva transparente a bcrypt
    if debe_rehashear and nuevo_hash:
        user.password_hash = nuevo_hash

    _clear_failed_attempts(rate_key)

    jti = str(uuid.uuid4())
    expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id), "terminal_id": request_body.terminal_id, "jti": jti},
        expires_delta=expires_delta,
    )

    ahora_utc = datetime.utcnow()
    user.ultimo_acceso = ahora_utc

    # Registrar sesión rastreable para soportar revocación inmediata en logout
    term_id = request_body.terminal_id or 1
    term_res = await db.execute(select(Terminal).where(Terminal.id == term_id))
    term = term_res.scalars().first()
    if not term:
        term_any = await db.execute(select(Terminal).order_by(Terminal.id.asc()))
        term = term_any.scalars().first()
        if term:
            term_id = term.id
        else:
            term = Terminal(nombre="CAJA-01", descripcion="Caja Principal")
            db.add(term)
            await db.flush()
            term_id = term.id

    db.add(
        Sesion(
            usuario_id=user.id,
            terminal_id=term_id,
            token=jti,
            inicio=ahora_utc,
            expira=ahora_utc + expires_delta,
            activa=True,
        )
    )

    await log_audit(
        db=db,
        usuario_id=user.id,
        usuario_nombre=f"{user.nombre or ''} {user.apellidos or ''}".strip() or user.usuario,
        terminal_id=term_id,
        terminal_nombre=term.nombre if term else f"Terminal-{term_id}",
        accion="LOGIN_EXITOSO",
        modulo="SEGURIDAD",
        tabla_afectada="sesiones",
        registro_id=jti,
        ip_address=client_ip,
        auto_commit=False,
    )
    await db.commit()

    req_cambio = bool(getattr(user, "requiere_cambio_password", False) or (request_body.password == "admin123"))
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "requiere_cambio_password": req_cambio,
        "usuario_id": user.id,
        "rol": user.rol,
    }


@router.post("/change-password")
async def change_own_password(
    payload: ChangePasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Permite al usuario autenticado cambiar su propia contraseña de forma segura."""
    es_valido, _, _ = verify_and_rehash_password(payload.current_password, current_user.password_hash)
    if not es_valido:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La contraseña actual es incorrecta.")

    ok_pwd, msg_pwd = validar_password_fuerte_servidor(payload.new_password)
    if not ok_pwd:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg_pwd)

    current_user.password_hash = hash_password(payload.new_password.strip())
    current_user.requiere_cambio_password = False

    client_ip = request.client.host if request.client else None
    await log_audit(
        db=db,
        usuario_id=current_user.id,
        usuario_nombre=f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario,
        accion="CAMBIO_PASSWORD",
        modulo="SEGURIDAD",
        tabla_afectada="usuarios",
        registro_id=str(current_user.id),
        descripcion="Actualización de contraseña personal por el usuario",
        ip_address=client_ip,
        auto_commit=False,
    )
    await db.commit()
    return {"ok": True, "message": "Contraseña actualizada correctamente."}


@router.post("/logout")
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    jti = getattr(current_user, "_token_jti", None)
    if jti:
        res = await db.execute(select(Sesion).where(Sesion.token == str(jti)))
        ses = res.scalars().first()
        if ses:
            ses.activa = False
    client_ip = request.client.host if request.client else None
    await log_audit(
        db=db,
        usuario_id=current_user.id,
        usuario_nombre=f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario,
        accion="LOGOUT",
        modulo="SEGURIDAD",
        tabla_afectada="sesiones",
        registro_id=str(jti or current_user.id),
        ip_address=client_ip,
        auto_commit=False,
    )
    await db.commit()
    return {"message": "Sesion cerrada exitosamente"}


@router.get("/me", response_model=UserResponse)
async def me(current_user: Usuario = Depends(get_current_user)):
    return current_user
