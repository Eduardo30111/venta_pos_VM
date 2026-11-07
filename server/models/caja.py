from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from ..database import Base


class SesionCaja(Base):
    __tablename__ = "sesiones_caja"
    id = Column(Integer, primary_key=True, index=True)
    fecha_apertura = Column(String, nullable=False, index=True)
    hora_apertura = Column(String, nullable=False)
    usuario_apertura = Column(String, nullable=False)
    terminal_id = Column(Integer, ForeignKey("terminales.id"), nullable=True)
    terminal_nombre = Column(String, nullable=True)
    monto_inicial = Column(Float, default=0.0)
    fecha_cierre = Column(String, nullable=True)
    hora_cierre = Column(String, nullable=True)
    usuario_cierre = Column(String, nullable=True)
    monto_esperado_efectivo = Column(Float, default=0.0)
    monto_real_contado = Column(Float, default=0.0)
    diferencia = Column(Float, default=0.0)
    monto_transferencias_esperado = Column(Float, default=0.0)
    monto_transferencias_verificado = Column(Float, default=0.0)
    diferencia_banco = Column(Float, default=0.0)
    estado_banco = Column(String, default="Pendiente")
    observaciones = Column(String, nullable=True)
    estado = Column(String, default="Abierta", index=True)  # Abierta / Cerrada
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MovimientoCaja(Base):
    __tablename__ = "movimientos_caja"
    id = Column(Integer, primary_key=True, index=True)
    sesion_caja_id = Column(Integer, ForeignKey("sesiones_caja.id"), nullable=True, index=True)
    fecha = Column(String, nullable=False, index=True)
    hora = Column(String, nullable=False)
    tipo = Column(String, nullable=False, index=True)  # APERTURA / VENTA_EFECTIVO / ABONO_EFECTIVO / EGRESO / RETIRO / AJUSTE / DEVOLUCION_VENTA / CIERRE
    monto = Column(Float, nullable=False, default=0.0)
    usuario = Column(String, nullable=False)
    terminal = Column(String, nullable=True)
    referencia_id = Column(String, nullable=True)
    descripcion = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MovimientoFinanciero(Base):
    __tablename__ = "movimientos_financieros"
    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(String, nullable=False, index=True)
    hora = Column(String, nullable=False)
    tipo = Column(String, nullable=False, index=True)  # VENTA_EFECTIVO / VENTA_TRANSFERENCIA / VENTA_CREDITO / ABONO_EFECTIVO / ABONO_TRANSFERENCIA / GASTO_PAGADO / PAGO_PROVEEDOR / RETIRO_CAJA / INGRESO_EXTRAORDINARIO / DEVOLUCION_VENTA / AJUSTE_AUTORIZADO / APERTURA_CAJA
    concepto = Column(String, nullable=False)
    monto = Column(Float, nullable=False, default=0.0)
    metodo_pago = Column(String, default="Efectivo")
    cuenta_afectada = Column(String, default="CAJA_FISICA", index=True)  # CAJA_FISICA / BANCO_TRANSFERENCIA / CARTERA_CLIENTES / NINGUNA
    usuario = Column(String, nullable=False)
    referencia_origen = Column(String, nullable=True, index=True)
    sesion_caja_id = Column(Integer, ForeignKey("sesiones_caja.id"), nullable=True, index=True)
    estado = Column(String, default="Activo")  # Activo / Anulado
    observaciones = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
