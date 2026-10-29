from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class ComisionResponse(BaseModel):
    id: int
    usuario_id: int
    venta_id: int
    servicio_id: Optional[int] = None
    producto_id: Optional[int] = None
    valor_servicio: float
    utilidad: float
    porcentaje: float
    monto_comision: float
    estado: str
    created_at: datetime

    class Config:
        from_attributes = True

class AsistenciaCreate(BaseModel):
    usuario_id: int
    fecha: str
    estado: str

class AsistenciaResponse(BaseModel):
    id: int
    usuario_id: int
    fecha: datetime
    estado: str
    registrado_por: int
    salario_generado: float

    class Config:
        from_attributes = True

class LiquidacionCreate(BaseModel):
    usuario_id: int
    periodo_inicio: Optional[datetime] = None
    periodo_fin: Optional[datetime] = None
    observaciones: Optional[str] = None

class LiquidacionResponse(BaseModel):
    id: int
    usuario_id: int
    periodo_inicio: datetime
    periodo_fin: datetime
    total_servicios_vendidos: float
    total_comisiones: float
    total_salario_fijo: float
    total_liquidado: float
    estado: str
    observaciones: Optional[str] = None
    created_at: datetime
    nombre_persona: Optional[str] = None
    monto: Optional[float] = None
    fecha: Optional[str] = None
    mes_anio: Optional[str] = None

    class Config:
        from_attributes = True
