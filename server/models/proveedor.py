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
    idempotency_key = Column(String, unique=True, index=True, nullable=True)
    fecha_registro = Column(String, nullable=True)
    dinero_de_mas = Column(Float, default=0.0)
    monto_ajustado = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AjusteLiquidacionProveedor(Base):
    __tablename__ = "ajustes_liquidaciones_proveedores"
    id = Column(Integer, primary_key=True, index=True)
    numero_ajuste = Column(String, unique=True, index=True, nullable=False)
    liquidacion_id = Column(Integer, ForeignKey("liquidaciones_proveedores.id"), nullable=False, index=True)
    numero_recibo = Column(String, nullable=False)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"), nullable=False, index=True)
    proveedor_nombre = Column(String, nullable=False)
    monto_ajuste = Column(Float, nullable=False)
    fecha_movimiento = Column(String, nullable=False, index=True)
    hora_movimiento = Column(String, nullable=False)
    fecha_registro = Column(String, nullable=False)
    usuario = Column(String, nullable=False)
    motivo = Column(String, nullable=False)
    estado = Column(String, default="Aplicado")
    idempotency_key = Column(String, unique=True, index=True, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AuditoriaLiquidacion(Base):
    __tablename__ = "auditoria_liquidaciones"
    id = Column(Integer, primary_key=True, index=True)
    liquidacion_id = Column(Integer, nullable=False, index=True)
    numero_recibo = Column(String, nullable=False)
    proveedor_id = Column(Integer, nullable=False)
    proveedor_nombre = Column(String, nullable=False)
    accion = Column(String, nullable=False)
    fecha_anterior = Column(String, nullable=True)
    fecha_nueva = Column(String, nullable=True)
    monto = Column(Float, nullable=True)
    usuario = Column(String, nullable=False)
    motivo = Column(String, nullable=False)
    fecha_registro = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AjusteSaldoProveedor(Base):
    __tablename__ = "ajustes_saldos_proveedores"
    id = Column(Integer, primary_key=True, index=True)
    numero_ajuste = Column(String, unique=True, index=True, nullable=False)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"), nullable=False, index=True)
    proveedor_nombre = Column(String, nullable=False)
    tipo_ajuste = Column(String, nullable=False)  # 'AJUSTAR_A_CERO' o 'VALOR_ESPECIFICO'
    saldo_anterior = Column(Float, nullable=False)
    monto_ajuste = Column(Float, nullable=False)
    saldo_final = Column(Float, nullable=False)
    motivo = Column(String, nullable=False)
    usuario = Column(String, nullable=False)
    fecha = Column(String, nullable=False, index=True)
    hora = Column(String, nullable=False)
    estado = Column(String, default="Aplicado")
    idempotency_key = Column(String, unique=True, index=True, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
