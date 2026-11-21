from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class UserBase(BaseModel):
    nombre: Optional[str] = ""
    apellidos: Optional[str] = ""
    documento: Optional[str] = None
    usuario: str
    rol: str
    tipo_remuneracion: Optional[str] = 'Porcentual'
    salario_diario: Optional[float] = 0.0
    porcentaje_comision: Optional[float] = 0.0
    estado: Optional[str] = 'Activo'
    requiere_cambio_password: Optional[bool] = False

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    nombre: Optional[str] = None
    apellidos: Optional[str] = None
    documento: Optional[str] = None
    usuario: Optional[str] = None
    password: Optional[str] = None
    rol: Optional[str] = None
    tipo_remuneracion: Optional[str] = None
    salario_diario: Optional[float] = None
    porcentaje_comision: Optional[float] = None
    estado: Optional[str] = None
    requiere_cambio_password: Optional[bool] = None

class UserResponse(UserBase):
    id: int
    fecha_registro: datetime
    ultimo_acceso: Optional[datetime] = None

    class Config:
        from_attributes = True

class LoginRequest(BaseModel):
    usuario: str
    password: str
    terminal_id: int

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    requiere_cambio_password: Optional[bool] = False
    usuario_id: Optional[int] = None
    rol: Optional[str] = None
