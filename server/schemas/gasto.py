from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class GastoBase(BaseModel):
    concepto: str
    categoria: str
    valor: float
    metodo_pago: str = "Efectivo"
    tipo: str
    referencia_id: Optional[int] = None
    observacion: Optional[str] = None

class GastoCreate(GastoBase):
    pass

class GastoUpdate(BaseModel):
    concepto: Optional[str] = None
    categoria: Optional[str] = None
    valor: Optional[float] = None
    metodo_pago: Optional[str] = None
    observacion: Optional[str] = None

class GastoResponse(GastoBase):
    id: int
    usuario_id: int
    created_at: datetime

    class Config:
        from_attributes = True
