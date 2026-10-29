from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ProductoBase(BaseModel):
    codigo: Optional[str] = None
    nombre: str
    descripcion: Optional[str] = None
    categoria_id: Optional[int] = None
    precio_costo: float
    precio_venta: float
    stock: Optional[float] = 0.0
    stock_minimo: Optional[float] = 0.0
    proveedor_id: Optional[int] = None
    codigo_barras: Optional[str] = None
    imagen_url: Optional[str] = None
    estado: Optional[str] = "Activo"

class ProductoCreate(ProductoBase):
    pass

class ProductoUpdate(ProductoBase):
    codigo: Optional[str] = None
    nombre: Optional[str] = None
    categoria_id: Optional[int] = None
    precio_costo: Optional[float] = None
    precio_venta: Optional[float] = None
    proveedor_id: Optional[int] = None

class ProductoResponse(ProductoBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
