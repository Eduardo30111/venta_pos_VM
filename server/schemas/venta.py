from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class DetalleVentaCreate(BaseModel):
    tipo_item: str
    item_id: int
    item_codigo: str
    item_nombre: str
    precio_original: float
    precio_vendido: float
    cantidad: float
    descuento: Optional[float] = 0.0
    subtotal: float
    costo_unitario: float

class PagoCreate(BaseModel):
    metodo: str
    monto: float
    referencia: Optional[str] = None
    recibido: float
    cambio: float

class VentaCreate(BaseModel):
    cliente_id: Optional[int] = None
    cliente_documento: Optional[str] = None
    terminal_id: int
    subtotal: float
    descuento: Optional[float] = 0.0
    total: float
    observaciones: Optional[str] = None
    detalles: List[DetalleVentaCreate]
    pagos: Optional[List[PagoCreate]] = []
    estado: Optional[str] = "Completada"
    es_turno_especial: Optional[bool] = False
    motivo_especial: Optional[str] = None

class CobroOrdenCreate(BaseModel):
    pagos: List[PagoCreate]
    cliente_id: Optional[int] = None
    cliente_documento: Optional[str] = None
    observaciones: Optional[str] = None

class DetalleVentaResponse(BaseModel):
    id: int
    tipo_item: str
    item_id: int
    item_codigo: str
    item_nombre: str
    precio_original: float
    precio_vendido: float
    cantidad: float
    descuento: float
    subtotal: float
    costo_unitario: Optional[float] = 0.0

    class Config:
        from_attributes = True

class VentaResponse(BaseModel):
    id: int
    numero: str
    cliente_id: Optional[int] = None
    cliente_documento: Optional[str] = None
    usuario_id: int
    terminal_id: int
    subtotal: float
    descuento: float
    total: float
    estado: str
    observaciones: Optional[str] = None
    created_at: datetime
    operario_nombre: Optional[str] = None
    hora: Optional[str] = None
    total_items: Optional[float] = None
    detalles: List[DetalleVentaResponse] = []

    class Config:
        from_attributes = True
