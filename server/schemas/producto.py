from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class ProductoBase(BaseModel):
    codigo: Optional[str] = None
    nombre: str
    descripcion: Optional[str] = None
    categoria_id: Optional[int] = None
    categoria: Optional[str] = "General"
    marca: Optional[str] = ""
    unidad_medida: Optional[str] = "Unidad"
    precio_costo: float = 0.0
    precio_venta: float = 0.0
    stock: Optional[float] = 0.0
    stock_minimo: Optional[float] = 0.0
    stock_bodega: Optional[float] = 0.0
    stock_vitrina: Optional[float] = 0.0
    stock_minimo_bodega: Optional[float] = 5.0
    stock_minimo_vitrina: Optional[float] = 3.0
    proveedor_id: Optional[int] = None
    codigo_barras: Optional[str] = None
    imagen_url: Optional[str] = None
    precio_variable: Optional[bool] = False
    porcentaje_comision: Optional[float] = 0.0
    estado: Optional[str] = "Activo"


class ProductoCreate(ProductoBase):
    pass


class ProductoUpdate(BaseModel):
    codigo: Optional[str] = None
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    categoria_id: Optional[int] = None
    categoria: Optional[str] = None
    marca: Optional[str] = None
    unidad_medida: Optional[str] = None
    precio_costo: Optional[float] = None
    precio_venta: Optional[float] = None
    stock: Optional[float] = None
    stock_minimo: Optional[float] = None
    stock_bodega: Optional[float] = None
    stock_vitrina: Optional[float] = None
    stock_minimo_bodega: Optional[float] = None
    stock_minimo_vitrina: Optional[float] = None
    proveedor_id: Optional[int] = None
    codigo_barras: Optional[str] = None
    imagen_url: Optional[str] = None
    precio_variable: Optional[bool] = None
    porcentaje_comision: Optional[float] = None
    estado: Optional[str] = None


class ProductoResponse(ProductoBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
