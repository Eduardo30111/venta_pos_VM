from pydantic import BaseModel, model_validator
from typing import List, Optional, Dict, Any
from datetime import datetime


class DetalleVentaCreate(BaseModel):
    tipo_item: str = "producto"
    item_id: Optional[int] = 0
    item_codigo: str = ""
    item_nombre: str = ""
    precio_original: float = 0.0
    precio_vendido: float = 0.0
    cantidad: float = 1.0
    descuento: Optional[float] = 0.0
    subtotal: float = 0.0
    costo_unitario: Optional[float] = 0.0
    ubicacion: Optional[str] = "Vitrina"

    @model_validator(mode="before")
    @classmethod
    def normalizar_campos(cls, data: Any):
        if isinstance(data, dict):
            d = dict(data)
            if "tipo" in d and "tipo_item" not in d:
                d["tipo_item"] = d["tipo"]
            if "producto_id" in d and ("item_id" not in d or not d["item_id"]):
                d["item_id"] = d["producto_id"]
            if "codigo" in d and not d.get("item_codigo"):
                d["item_codigo"] = str(d["codigo"])
            if "nombre_producto" in d and not d.get("item_nombre"):
                d["item_nombre"] = str(d["nombre_producto"])
            if "precio_unitario" in d:
                pu = float(d["precio_unitario"])
                if "precio_vendido" not in d or d["precio_vendido"] == 0:
                    d["precio_vendido"] = pu
                if "precio_original" not in d or d["precio_original"] == 0:
                    d["precio_original"] = pu
            cant = float(d.get("cantidad", 1.0) or 1.0)
            pv = float(d.get("precio_vendido", 0.0) or 0.0)
            if "subtotal" not in d or not d["subtotal"]:
                d["subtotal"] = round(cant * pv, 2)
            return d
        return data


class PagoCreate(BaseModel):
    metodo: str
    monto: float
    referencia: Optional[str] = None
    recibido: Optional[float] = 0.0
    cambio: Optional[float] = 0.0


class VentaCreate(BaseModel):
    idempotency_key: Optional[str] = None
    cliente_id: Optional[int] = None
    cliente_documento: Optional[str] = None
    terminal_id: Optional[int] = 1
    sesion_caja_id: Optional[int] = None
    subtotal: float
    descuento: Optional[float] = 0.0
    total: float
    observaciones: Optional[str] = None
    detalles: Optional[List[DetalleVentaCreate]] = None
    items: Optional[List[DetalleVentaCreate]] = None
    pagos: Optional[List[PagoCreate]] = []
    estado: Optional[str] = "Completada"
    autorizado_exceso_credito: Optional[bool] = False
    es_turno_especial: Optional[bool] = False
    motivo_especial: Optional[str] = None
    snapshot_negocio: Optional[Dict[str, Any]] = None

    @model_validator(mode="before")
    @classmethod
    def preparar_detalles(cls, data: Any):
        if isinstance(data, dict):
            d = dict(data)
            if not d.get("detalles") and d.get("items"):
                d["detalles"] = d["items"]
            return d
        return data


class CobroOrdenCreate(BaseModel):
    idempotency_key: Optional[str] = None
    pagos: List[PagoCreate]
    cliente_id: Optional[int] = None
    cliente_documento: Optional[str] = None
    observaciones: Optional[str] = None
    autorizado_exceso_credito: Optional[bool] = False
    sesion_caja_id: Optional[int] = None


class AnularVentaRequest(BaseModel):
    motivo: Optional[str] = "Anulación administrativa"
    terminal_id: Optional[int] = 1


class EditarVentaItemRequest(BaseModel):
    codigo_producto: str
    nombre_producto: str
    precio_unitario: float
    cantidad: float


class EditarVentaRequest(BaseModel):
    nuevo_metodo: str = "Efectivo"
    nuevos_items: List[EditarVentaItemRequest]
    motivo: str = "Edición administrativa"
    terminal_id: Optional[int] = 1


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


class PagoResponse(BaseModel):
    id: int
    metodo: str
    monto: float
    referencia: Optional[str] = None
    recibido: float
    cambio: float

    class Config:
        from_attributes = True


class VentaResponse(BaseModel):
    id: int
    numero: str
    idempotency_key: Optional[str] = None
    fecha: Optional[str] = None
    hora: Optional[str] = None
    sesion_caja_id: Optional[int] = None
    cliente_id: Optional[int] = None
    cliente_documento: Optional[str] = None
    cliente_nombre: Optional[str] = None
    usuario_id: int
    terminal_id: int
    subtotal: float
    descuento: float
    total: float
    metodo_pago_principal: Optional[str] = None
    recibido: Optional[float] = 0.0
    cambio: Optional[float] = 0.0
    saldo_pendiente: Optional[float] = 0.0
    estado: str
    observaciones: Optional[str] = None
    motivo_anulacion: Optional[str] = None
    anulada_por: Optional[str] = None
    anulada_at: Optional[str] = None
    created_at: Optional[datetime] = None
    operario_nombre: Optional[str] = None
    total_items: Optional[float] = None
    cuenta_por_cobrar_id: Optional[int] = None
    ya_existia_idempotencia: Optional[bool] = False
    detalles: List[DetalleVentaResponse] = []
    pagos: List[PagoResponse] = []

    class Config:
        from_attributes = True
