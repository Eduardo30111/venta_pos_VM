from pydantic import BaseModel, model_validator
from typing import Optional, List, Any, Dict
from datetime import datetime


class AjusteStock(BaseModel):
    cantidad: float
    tipo: str
    observacion: str


class MovimientoInventarioResponse(BaseModel):
    id: int
    fecha: Optional[str] = None
    hora: Optional[str] = None
    producto_id: int
    codigo_producto: Optional[str] = None
    nombre_producto: Optional[str] = None
    tipo: str
    cantidad: float
    unidad_medida: Optional[str] = "Unidad"
    ubicacion_origen: Optional[str] = None
    ubicacion_destino: Optional[str] = None
    stock_anterior: float = 0.0
    stock_nuevo: float = 0.0
    stock_origen_ant: Optional[float] = 0.0
    stock_origen_des: Optional[float] = 0.0
    stock_destino_ant: Optional[float] = 0.0
    stock_destino_des: Optional[float] = 0.0
    costo_unitario: Optional[float] = 0.0
    valor_total: Optional[float] = 0.0
    referencia: Optional[str] = None
    usuario_id: Optional[int] = None
    usuario_nombre: Optional[str] = None
    terminal_id: Optional[int] = None
    observacion: Optional[str] = None
    estado: Optional[str] = "Completado"
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ArticuloCatalogoCreate(BaseModel):
    codigo: str
    nombre: str
    tipo_producto: str = "Fisico"  # Fisico / Servicio
    precio: float = 0.0
    costo: float = 0.0
    categoria: str = "General"
    marca: str = ""
    codigo_barras: str = ""
    unidad_medida: str = "Unidad"
    descripcion: str = ""
    proveedor_id: Optional[int] = None
    estado: str = "Activo"
    precio_variable: bool = False
    porcentaje_comision: float = 0.0
    stock_bodega: float = 0.0
    stock_vitrina: float = 0.0
    stock_minimo_bodega: float = 5.0
    stock_minimo_vitrina: float = 3.0

    @model_validator(mode="before")
    @classmethod
    def normalizar_datos(cls, data: Any):
        if isinstance(data, dict):
            d = dict(data)
            raw_p = d.get("proveedor_id")
            if raw_p is not None:
                try:
                    s_p = str(raw_p).split("-")[0].strip()
                    d["proveedor_id"] = int(s_p) if s_p.isdigit() and int(s_p) > 0 else None
                except Exception:
                    d["proveedor_id"] = None
            return d
        return data


class ArticuloCatalogoUpdate(BaseModel):
    nombre: Optional[str] = None
    tipo_producto: Optional[str] = None
    precio: Optional[float] = None
    costo: Optional[float] = None
    categoria: Optional[str] = None
    marca: Optional[str] = None
    codigo_barras: Optional[str] = None
    unidad_medida: Optional[str] = None
    descripcion: Optional[str] = None
    proveedor_id: Optional[int] = None
    estado: Optional[str] = None
    precio_variable: Optional[bool] = None
    porcentaje_comision: Optional[float] = None
    stock_minimo_bodega: Optional[float] = None
    stock_minimo_vitrina: Optional[float] = None

    @model_validator(mode="before")
    @classmethod
    def normalizar_datos(cls, data: Any):
        if isinstance(data, dict):
            d = dict(data)
            if "proveedor_id" in d and d["proveedor_id"] is not None:
                try:
                    s_p = str(d["proveedor_id"]).split("-")[0].strip()
                    d["proveedor_id"] = int(s_p) if s_p.isdigit() and int(s_p) > 0 else None
                except Exception:
                    d["proveedor_id"] = None
            return d
        return data


class TrasladoCreate(BaseModel):
    codigo_o_id: Any
    origen: str
    destino: str
    cantidad: float
    usuario: Optional[str] = None
    observaciones: Optional[str] = ""


class AjusteInventarioCreate(BaseModel):
    codigo_o_id: Any
    ubicacion: str
    conteo_fisico: float
    usuario: Optional[str] = None
    motivo: Optional[str] = ""


class ItemCompraCreate(BaseModel):
    producto_id: Optional[int] = None
    codigo: str
    unidad_compra: str = "Unidad"
    factor_conversion: float = 1.0
    cantidad_comprada: float
    costo_unidad_compra: float
    subtotal: Optional[float] = 0.0


class CompraCreate(BaseModel):
    proveedor_id: Optional[int] = None
    proveedor_nombre: Optional[str] = ""
    doc_referencia: Optional[str] = ""
    ubicacion_destino: str = "BODEGA"
    usuario: Optional[str] = None
    observaciones: Optional[str] = ""
    items: List[ItemCompraCreate]
