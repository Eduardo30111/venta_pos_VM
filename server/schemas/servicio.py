from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ServicioBase(BaseModel):
    codigo: Optional[str] = None
    nombre: str
    descripcion: Optional[str] = None
    categoria_id: Optional[int] = None
    precio_venta: float
    tipo_servicio: Optional[str] = "Interno"
    proveedor_id: Optional[int] = None
    costo_proveedor: Optional[float] = 0.0
    porcentaje_comision: Optional[float] = 0.0
    genera_comision: Optional[bool] = True
    precio_variable: Optional[bool] = False
    solo_operarios: Optional[bool] = False
    estado: Optional[str] = "Activo"

class ServicioCreate(ServicioBase):
    pass

class ServicioUpdate(BaseModel):
    codigo: Optional[str] = None
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    categoria_id: Optional[int] = None
    precio_venta: Optional[float] = None
    tipo_servicio: Optional[str] = None
    proveedor_id: Optional[int] = None
    costo_proveedor: Optional[float] = None
    porcentaje_comision: Optional[float] = None
    genera_comision: Optional[bool] = None
    precio_variable: Optional[bool] = None
    solo_operarios: Optional[bool] = None
    estado: Optional[str] = None

class ServicioResponse(ServicioBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    creado_por_operario_id: Optional[int] = None

    class Config:
        from_attributes = True
