from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from ..database import Base


class CuentaPorCobrar(Base):
    __tablename__ = "cuentas_por_cobrar"
    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False, index=True)
    venta_id = Column(Integer, ForeignKey("ventas.id"), nullable=True, index=True)
    fecha = Column(String, nullable=True, index=True)
    hora = Column(String, nullable=True)
    monto_original = Column(Float, nullable=False)
    saldo_pendiente = Column(Float, nullable=False)
    estado = Column(String, default="Pendiente", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Abono(Base):
    __tablename__ = "abonos"
    id = Column(Integer, primary_key=True, index=True)
    idempotency_key = Column(String, unique=True, index=True, nullable=True)
    cuenta_id = Column(Integer, ForeignKey("cuentas_por_cobrar.id"), nullable=False, index=True)
    fecha = Column(String, nullable=True, index=True)
    hora = Column(String, nullable=True)
    monto = Column(Float, nullable=False)
    metodo = Column(String, nullable=False)
    recibido_por = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    observacion = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CuentaPorPagar(Base):
    __tablename__ = "cuentas_por_pagar"
    id = Column(Integer, primary_key=True, index=True)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"), nullable=False, index=True)
    venta_id = Column(Integer, ForeignKey("ventas.id"), nullable=True, index=True)
    numero_venta = Column(String, nullable=True)
    codigo_servicio = Column(String, nullable=True)
    nombre_servicio = Column(String, nullable=True)
    precio_venta = Column(Float, default=0.0)
    porcentaje_comision = Column(Float, default=0.0)
    monto_comision = Column(Float, default=0.0)
    concepto = Column(String, nullable=False)
    monto = Column(Float, nullable=False)
    monto_pagado = Column(Float, default=0.0)
    saldo_pendiente = Column(Float, default=0.0)
    estado = Column(String, default="Pendiente")  # Pendiente/Pagada/Anulada
    fecha = Column(String, nullable=True)
    hora = Column(String, nullable=True)
    usuario = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Gasto(Base):
    __tablename__ = "gastos"
    id = Column(Integer, primary_key=True, index=True)
    concepto = Column(String, nullable=False)
    categoria = Column(String, nullable=False)
    clasificacion = Column(String, default="Operativo diario", nullable=True)
    descripcion = Column(String, default="", nullable=True)
    valor = Column(Float, nullable=False)
    fecha = Column(String, nullable=True, index=True)
    hora = Column(String, nullable=True)
    fecha_vencimiento = Column(String, nullable=True)
    fecha_pago = Column(String, nullable=True)
    frecuencia = Column(String, default="Único", nullable=True)
    estado = Column(String, default="Pagado", index=True)  # Pagado / Pendiente / Vencido / Anulado
    metodo_pago = Column(String, nullable=False, default="Efectivo")
    tipo = Column(String, nullable=False, default="Manual")  # Manual/Liquidacion_Nomina/Pago_Proveedor/Recurrente
    proveedor = Column(String, default="", nullable=True)
    comprobante = Column(String, default="", nullable=True)
    es_recurrente = Column(Boolean, default=False)
    recurrencia_id = Column(Integer, nullable=True)
    sesion_caja_id = Column(Integer, nullable=True)
    referencia_id = Column(Integer, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    usuario_nombre = Column(String, nullable=True)
    observacion = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class GastoRecurrente(Base):
    __tablename__ = "gastos_recurrentes"
    id = Column(Integer, primary_key=True, index=True)
    concepto = Column(String, nullable=False)
    valor = Column(Float, nullable=False)
    categoria = Column(String, default="Fijo periódico")
    clasificacion = Column(String, default="Fijo periódico")
    descripcion = Column(String, default="")
    frecuencia = Column(String, default="Mensual")  # Diaria / Semanal / Quincenal / Mensual / Anual
    dia_corte = Column(Integer, default=1)
    metodo_pago_defecto = Column(String, default="Efectivo")
    proveedor = Column(String, default="")
    activo = Column(Boolean, default=True)
    ultimo_periodo_generado = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MovimientoCuentaCliente(Base):
    __tablename__ = "movimientos_cliente"
    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False, index=True)
    cuenta_id = Column(Integer, ForeignKey("cuentas_por_cobrar.id"), nullable=True, index=True)
    venta_id = Column(Integer, ForeignKey("ventas.id"), nullable=True, index=True)
    abono_id = Column(Integer, ForeignKey("abonos.id"), nullable=True, index=True)
    fecha = Column(String, nullable=True, index=True)
    hora = Column(String, nullable=True)
    tipo = Column(String, nullable=False)  # FIADO, ABONO, ANULACION, AJUSTE_MANUAL, DEVOLUCION
    monto = Column(Float, nullable=False)
    saldo_anterior = Column(Float, nullable=False)
    saldo_nuevo = Column(Float, nullable=False)
    metodo_pago = Column(String, nullable=True)  # Efectivo, Transferencia, Fiado
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    terminal_id = Column(Integer, ForeignKey("terminales.id"), nullable=True)
    motivo = Column(String, nullable=True)
    observacion = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
