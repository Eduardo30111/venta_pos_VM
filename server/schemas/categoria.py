from pydantic import BaseModel
from typing import Optional

class CategoriaBase(BaseModel):
    nombre: str
    tipo: str
    estado: Optional[str] = "Activo"

class CategoriaCreate(CategoriaBase):
    pass

class CategoriaUpdate(CategoriaBase):
    nombre: Optional[str] = None
    tipo: Optional[str] = None
    estado: Optional[str] = None

class CategoriaResponse(CategoriaBase):
    id: int

    class Config:
        from_attributes = True
