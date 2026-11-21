from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime
from ..database import get_db
from ..schemas.usuario import LoginRequest, TokenResponse, UserResponse
from ..models.usuario import Usuario
from ..middleware.auth import verify_password, verify_and_rehash_password, create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Usuario).where(Usuario.usuario == request.usuario))
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales invalidas")

    es_valido, debe_rehashear, nuevo_hash = verify_and_rehash_password(request.password, user.password_hash)
    if not es_valido:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales invalidas")

    # Migración progresiva transparente a bcrypt
    if debe_rehashear and nuevo_hash:
        user.password_hash = nuevo_hash
    
    if user.estado != 'Activo':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo")
        
    access_token = create_access_token(data={"sub": str(user.id), "terminal_id": request.terminal_id})
    
    user.ultimo_acceso = datetime.utcnow()
    await db.commit()
    
    req_cambio = bool(getattr(user, "requiere_cambio_password", False) or (request.password == "admin123"))
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "requiere_cambio_password": req_cambio,
        "usuario_id": user.id,
        "rol": user.rol,
    }

@router.post("/logout")
async def logout(current_user: Usuario = Depends(get_current_user)):
    return {"message": "Sesion cerrada exitosamente"}

@router.get("/me", response_model=UserResponse)
async def me(current_user: Usuario = Depends(get_current_user)):
    return current_user
