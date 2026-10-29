from pydantic import BaseModel
from typing import Optional

class ProveedorBase(BaseModel):
    nombre: str
    documento_nit: str
    telefono: Optional[str] = None
    email: Optional[str] = None
    direccion: Optional[str] = None
    contacto: Optional[str] = None
    estado: Optional[str] = "Activo"

class ProveedorCreate(ProveedorBase):
    pass

class ProveedorUpdate(ProveedorBase):
    nombre: Optional[str] = None
    documento_nit: Optional[str] = None

class ProveedorResponse(ProveedorBase):
    id: int

    class Config:
        from_attributes = True
