from pydantic import BaseModel
from typing import Optional


class ProveedorBase(BaseModel):
    nombre: str
    documento_nit: Optional[str] = ""
    telefono: Optional[str] = None
    email: Optional[str] = None
    direccion: Optional[str] = None
    contacto: Optional[str] = None
    saldo_acumulado: Optional[float] = 0.0
    total_ventas: Optional[float] = 0.0
    total_comisiones: Optional[float] = 0.0
    total_pagado: Optional[float] = 0.0
    estado: Optional[str] = "Activo"


class ProveedorCreate(ProveedorBase):
    pass


class ProveedorUpdate(BaseModel):
    nombre: Optional[str] = None
    documento_nit: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    direccion: Optional[str] = None
    contacto: Optional[str] = None
    estado: Optional[str] = None


class ProveedorResponse(ProveedorBase):
    id: int

    class Config:
        from_attributes = True


class AjusteSaldoRequest(BaseModel):
    tipo_ajuste: str = "AJUSTAR_A_CERO"  # 'AJUSTAR_A_CERO' o 'VALOR_ESPECIFICO'
    nuevo_saldo: float = 0.0
    motivo: str
    usuario: str = "Administrador"
    password_admin: Optional[str] = None
