from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class GastoBase(BaseModel):
    concepto: str
    categoria: str = "Operativo diario"
    clasificacion: Optional[str] = "Operativo diario"
    descripcion: Optional[str] = ""
    valor: float
    fecha: Optional[str] = None
    hora: Optional[str] = None
    fecha_vencimiento: Optional[str] = None
    fecha_pago: Optional[str] = None
    frecuencia: Optional[str] = "Único"
    estado: Optional[str] = "Pagado"
    metodo_pago: str = "Efectivo"
    tipo: str = "Manual"
    proveedor: Optional[str] = ""
    comprobante: Optional[str] = ""
    es_recurrente: Optional[bool] = False
    recurrencia_id: Optional[int] = None
    sesion_caja_id: Optional[int] = None
    referencia_id: Optional[int] = None
    observacion: Optional[str] = None


class GastoCreate(GastoBase):
    pass


class GastoUpdate(BaseModel):
    concepto: Optional[str] = None
    categoria: Optional[str] = None
    clasificacion: Optional[str] = None
    descripcion: Optional[str] = None
    valor: Optional[float] = None
    fecha: Optional[str] = None
    fecha_vencimiento: Optional[str] = None
    frecuencia: Optional[str] = None
    estado: Optional[str] = None
    metodo_pago: Optional[str] = None
    proveedor: Optional[str] = None
    comprobante: Optional[str] = None
    observacion: Optional[str] = None


class PagarGastoRequest(BaseModel):
    metodo_pago: str = "Efectivo"
    comprobante: Optional[str] = ""
    terminal_id: Optional[int] = 1


class GastoRecurrenteCreate(BaseModel):
    concepto: str
    valor: float
    categoria: str = "Fijo periódico"
    clasificacion: str = "Fijo periódico"
    descripcion: Optional[str] = ""
    frecuencia: str = "Mensual"
    dia_corte: int = 1
    metodo_pago_defecto: str = "Efectivo"
    proveedor: Optional[str] = ""
    activo: bool = True


class GastoResponse(GastoBase):
    id: int
    usuario_id: int
    usuario_nombre: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
