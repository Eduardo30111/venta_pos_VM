from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Any
from datetime import datetime

class ClienteBase(BaseModel):
    documento: str
    nombre: str
    email: Optional[str] = None
    telefono: Optional[str] = None
    direccion: Optional[str] = None
    permite_fiado: Optional[bool] = False
    limite_credito: Optional[float] = 0.0
    estado: Optional[str] = "Activo"

class ClienteCreate(ClienteBase):
    cedula: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def check_documento(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "cedula" in data and ("documento" not in data or not data.get("documento")):
                data["documento"] = data["cedula"]
            elif "documento" in data and ("cedula" not in data or not data.get("cedula")):
                data["cedula"] = data["documento"]
        return data

class ClienteUpdate(BaseModel):
    documento: Optional[str] = None
    cedula: Optional[str] = None
    nombre: Optional[str] = None
    email: Optional[str] = None
    telefono: Optional[str] = None
    direccion: Optional[str] = None
    permite_fiado: Optional[bool] = None
    limite_credito: Optional[float] = None
    estado: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def check_documento_update(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "cedula" in data and ("documento" not in data or not data.get("documento")):
                data["documento"] = data["cedula"]
        return data

class ClienteResponse(ClienteBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

class ClienteListItemResponse(BaseModel):
    id: int
    documento: str
    nombre: str
    telefono: Optional[str] = None
    email: Optional[str] = None
    operario_venta: Optional[str] = None
    vendedor: Optional[str] = None
    permite_fiado: bool = False
    total_compras: float = 0.0
    total_fiado: float = 0.0
    total_abonado: float = 0.0
    deuda_total: float = 0.0
    estado: str = "Activo"

class MovimientoClienteResponse(BaseModel):
    id: int
    cliente_id: int
    cuenta_id: Optional[int] = None
    venta_id: Optional[int] = None
    tipo: str
    monto: float
    saldo_anterior: float
    saldo_nuevo: float
    metodo_pago: Optional[str] = None
    usuario_id: int
    usuario_nombre: Optional[str] = None
    terminal_id: Optional[int] = None
    motivo: Optional[str] = None
    observacion: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class CuentaPendienteInfo(BaseModel):
    id: int
    venta_id: int
    numero_venta: Optional[str] = None
    monto_original: float
    saldo_pendiente: float
    estado: str
    created_at: datetime

class ClienteDeudaDetalleResponse(BaseModel):
    cliente: ClienteResponse
    total_compras: float
    total_fiado: float
    total_abonado: float
    deuda_actual: float
    cuentas_pendientes: List[CuentaPendienteInfo]
    movimientos: List[MovimientoClienteResponse]

class FiadoResumenItem(BaseModel):
    cliente_id: int
    documento: str
    nombre: str
    telefono: Optional[str] = None
    operario_venta: Optional[str] = None
    vendedor: Optional[str] = None
    total_fiado: float
    total_abonado: float
    deuda_actual: float
    ultimo_abono: Optional[datetime] = None
    estado: str


class AbonoCreate(BaseModel):
    monto: float
    metodo: str = "Efectivo" # Efectivo / Transferencia
    cuenta_id: Optional[int] = None
    observacion: Optional[str] = None

class AjusteDeudaCreate(BaseModel):
    monto: float # Monto positivo para incrementar deuda, negativo para reducir
    motivo: str
    observacion: Optional[str] = None

