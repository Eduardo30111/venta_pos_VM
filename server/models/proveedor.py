from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from ..database import Base


class Proveedor(Base):
    __tablename__ = "proveedores"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    documento_nit = Column(String, default="", nullable=True)
    telefono = Column(String, nullable=True)
    email = Column(String, nullable=True)
    direccion = Column(String, nullable=True)
    contacto = Column(String, nullable=True)
    saldo_acumulado = Column(Float, default=0.0)
    total_ventas = Column(Float, default=0.0)
    total_comisiones = Column(Float, default=0.0)
    total_pagado = Column(Float, default=0.0)
    estado = Column(String, default="Activo")


class LiquidacionProveedor(Base):
    __tablename__ = "liquidaciones_proveedores"
    id = Column(Integer, primary_key=True, index=True)
    numero_liquidacion = Column(String, unique=True, index=True, nullable=False)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"), nullable=False, index=True)
    proveedor_nombre = Column(String, nullable=False)
    fecha = Column(String, nullable=False, index=True)
    hora = Column(String, nullable=False)
    monto_pagado = Column(Float, nullable=False)
    metodo_pago = Column(String, default="Efectivo")
    referencia = Column(String, nullable=True)
    saldo_anterior = Column(Float, default=0.0)
    saldo_restante = Column(Float, default=0.0)
    usuario = Column(String, nullable=False)
    observaciones = Column(String, nullable=True)
    estado = Column(String, default="Completada")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
