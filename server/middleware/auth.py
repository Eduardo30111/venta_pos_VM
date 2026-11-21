import uuid
import bcrypt as _bcrypt
import hashlib
import hmac
from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional, Tuple

from ..config import settings
from ..database import get_db
from ..models.usuario import Usuario
from ..models.sesion import Sesion

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# Hash bcrypt precalculado para igualación de tiempos ante usuarios inexistentes
_DUMMY_BCRYPT_HASH = _bcrypt.hashpw(b"vmpos_dummy_timing_guard_2026", _bcrypt.gensalt(rounds=12))

CLAVES_BLOQUEADAS = frozenset({
    "admin123",
    "123456",
    "12345",
    "1234567",
    "12345678",
    "123456789",
    "admin",
    "password",
    "qwerty",
    "vmpos",
    "vmpos123",
    "000000",
})

ADMIN_ROLES = frozenset({"administrador", "admin", "gerente"})


def validar_password_fuerte_servidor(password: str) -> Tuple[bool, str]:
    """Valida que la contraseña cumpla la política mínima de seguridad del servidor."""
    pwd = (password or "").strip()
    if len(pwd) < 6:
        return False, "La contraseña debe tener al menos 6 caracteres."
    if pwd.lower() in CLAVES_BLOQUEADAS:
        return False, "La contraseña elegida es predeterminada o insegura. Defina una clave personalizada."
    return True, ""


def hash_password(password: str) -> str:
    pwd_bytes = (password or "").encode("utf-8")[:72]
    return _bcrypt.hashpw(pwd_bytes, _bcrypt.gensalt(rounds=12)).decode("utf-8")


def dummy_verify_password(plain_password: str) -> None:
    """Ejecuta una comparación bcrypt dummy para mitigar enumeración de usuarios por tiempo."""
    try:
        pwd_bytes = (plain_password or "x").encode("utf-8")[:72]
        _bcrypt.checkpw(pwd_bytes, _DUMMY_BCRYPT_HASH)
    except Exception:
        pass


def verify_and_rehash_password(plain_password: str, hashed_password: str) -> Tuple[bool, bool, Optional[str]]:
    """
    Verifica la contraseña contra el hash almacenado con protección de tiempo constante.
    Si la contraseña coincide con un hash legacy o texto plano previo a la migración,
    retorna (True, True, nuevo_hash_bcrypt) para re-hashearla atómicamente y erradicar texto plano.
    Si ya es un hash bcrypt ($2a$, $2b$, $2y$), valida directamente y retorna (True, False, None).
    """
    if not hashed_password or not plain_password:
        return False, False, None
    try:
        pwd_bytes = plain_password.encode("utf-8")[:72]
        if hashed_password.startswith(("$2a$", "$2b$", "$2y$")):
            es_valido = _bcrypt.checkpw(pwd_bytes, hashed_password.encode("utf-8"))
            return es_valido, False, None

        # Soporte seguro para migración transparente de hashes SHA-256 históricos
        sha_candidato = hashlib.sha256(plain_password.encode("utf-8")).hexdigest()
        if hmac.compare_digest(sha_candidato, hashed_password):
            return True, True, hash_password(plain_password)

        # Soporte transitorio de texto plano con protección contra timing attacks para usuarios legacy
        if hmac.compare_digest(plain_password, hashed_password):
            return True, True, hash_password(plain_password)

        return False, False, None
    except Exception:
        return False, False, None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    valido, _, _ = verify_and_rehash_password(plain_password, hashed_password)
    return valido


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if "jti" not in to_encode:
        to_encode["jti"] = str(uuid.uuid4())
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido")


def is_admin_role(user: Usuario) -> bool:
    return (getattr(user, "rol", "") or "").strip().lower() in ADMIN_ROLES


async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    payload = verify_token(token)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido")

    # Verificar revocación explícita de sesión mediante jti
    jti = payload.get("jti")
    if jti:
        try:
            ses_res = await db.execute(select(Sesion).where(Sesion.token == str(jti)))
            ses_obj = ses_res.scalars().first()
            if ses_obj is not None and not ses_obj.activa:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Sesión cerrada o revocada. Inicie sesión nuevamente.",
                )
        except HTTPException:
            raise
        except Exception:
            pass

    user = None
    try:
        user_int = int(user_id)
        result = await db.execute(select(Usuario).where(Usuario.id == user_int))
        user = result.scalars().first()
    except (ValueError, TypeError):
        pass

    if user is None:
        result = await db.execute(select(Usuario).where(Usuario.usuario == str(user_id)))
        user = result.scalars().first()

    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado o sesión expirada")

    # Bloqueo inmediato de usuarios inactivos/suspendidos
    if str(getattr(user, "estado", "Activo") or "").strip().lower() != "activo":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cuenta de usuario inactiva o suspendida.",
        )

    # Bloquear operación hasta completar cambio obligatorio de contraseña temporal
    if bool(getattr(user, "requiere_cambio_password", False)):
        path = (request.url.path or "").rstrip("/")
        rutas_permitidas = {
            "/auth/me",
            "/auth/logout",
            "/auth/change-password",
            f"/usuarios/{user.id}",
        }
        if path not in rutas_permitidas:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cambio de contraseña obligatorio pendiente. Actualice su clave para operar.",
            )

    # Adjuntar metadatos de sesión al objeto en memoria (sin mutar BD)
    try:
        user._token_jti = jti
        user._client_ip = request.client.host if request.client else None
    except Exception:
        pass
    return user


async def require_admin(current_user: Usuario = Depends(get_current_user)) -> Usuario:
    if not is_admin_role(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operación restringida: se requiere rol Administrador o Gerente.",
        )
    return current_user


def require_roles(*allowed_roles: str):
    allowed_norm = frozenset(r.strip().lower() for r in allowed_roles) | ADMIN_ROLES

    async def role_checker(current_user: Usuario = Depends(get_current_user)) -> Usuario:
        rol_norm = (getattr(current_user, "rol", "") or "").strip().lower()
        if rol_norm not in allowed_norm:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Acceso denegado para el rol '{current_user.rol}'.",
            )
        return current_user

    return role_checker


def require_permission(permiso: str):
    async def permission_checker(current_user: Usuario = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
        from ..models.permiso import PermisoUsuario
        if is_admin_role(current_user):
            return current_user

        result = await db.execute(
            select(PermisoUsuario).where(
                PermisoUsuario.usuario_id == current_user.id,
                PermisoUsuario.permiso == permiso,
                PermisoUsuario.concedido == True,
            )
        )
        if not result.scalars().first():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permiso denegado")
        return current_user

    return permission_checker
