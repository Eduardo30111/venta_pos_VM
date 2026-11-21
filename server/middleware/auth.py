import bcrypt as _bcrypt
import hashlib
import hmac
from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional, Tuple

from ..config import settings
from ..database import get_db
from ..models.usuario import Usuario

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

def hash_password(password: str) -> str:
    pwd_bytes = (password or "").encode("utf-8")[:72]
    return _bcrypt.hashpw(pwd_bytes, _bcrypt.gensalt(rounds=12)).decode("utf-8")

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

async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    payload = verify_token(token)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido")
    
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
    return user

def require_permission(permiso: str):
    async def permission_checker(current_user: Usuario = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
        from ..models.permiso import PermisoUsuario
        rol_norm = (current_user.rol or "").strip().lower()
        if rol_norm in ("administrador", "admin", "gerente"):
            return current_user
        
        result = await db.execute(
            select(PermisoUsuario).where(
                PermisoUsuario.usuario_id == current_user.id,
                PermisoUsuario.permiso == permiso,
                PermisoUsuario.concedido == True
            )
        )
        if not result.scalars().first():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permiso denegado")
        return current_user
    return permission_checker
