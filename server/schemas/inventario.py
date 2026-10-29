from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class AjusteStock(BaseModel):
    cantidad: float
    tipo: str
    observacion: str

class MovimientoInventarioResponse(BaseModel):
    id: int
    producto_id: int
    tipo: str
    cantidad: float
    stock_anterior: float
    stock_nuevo: float
    referencia: Optional[str] = None
    usuario_id: int
    terminal_id: int
    observacion: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
