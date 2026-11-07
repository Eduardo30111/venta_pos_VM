import bcrypt as _bcrypt
from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional

from ..config import settings
from ..database import get_db
from ..models.usuario import Usuario

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

def hash_password(password: str) -> str:
    pwd_bytes = (password or "").encode("utf-8")[:72]
    return _bcrypt.hashpw(pwd_bytes, _bcrypt.gensalt()).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    try:
        pwd_bytes = (plain_password or "").encode("utf-8")[:72]
        if hashed_password.startswith("$2"):
            return _bcrypt.checkpw(pwd_bytes, hashed_password.encode("utf-8"))
        return plain_password == hashed_password
    except Exception:
        return False

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
    
    result = await db.execute(select(Usuario).where(Usuario.id == int(user_id)))
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
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
