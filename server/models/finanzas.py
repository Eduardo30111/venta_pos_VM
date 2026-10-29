from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from ..database import Base

class CuentaPorCobrar(Base):
    __tablename__ = "cuentas_por_cobrar"
    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False)
    venta_id = Column(Integer, ForeignKey("ventas.id"), nullable=True)
    monto_original = Column(Float, nullable=False)
    saldo_pendiente = Column(Float, nullable=False)
    estado = Column(String, default="Pendiente")

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Abono(Base):
    __tablename__ = "abonos"
    id = Column(Integer, primary_key=True, index=True)
    cuenta_id = Column(Integer, ForeignKey("cuentas_por_cobrar.id"), nullable=False)
    monto = Column(Float, nullable=False)
    metodo = Column(String, nullable=False)
    recibido_por = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    observacion = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class CuentaPorPagar(Base):
    __tablename__ = "cuentas_por_pagar"
    id = Column(Integer, primary_key=True, index=True)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"), nullable=False)
    venta_id = Column(Integer, ForeignKey("ventas.id"), nullable=True)
    concepto = Column(String, nullable=False)
    monto = Column(Float, nullable=False)
    estado = Column(String, default="Pendiente") # Pendiente/Pagada
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Gasto(Base):
    __tablename__ = "gastos"
    id = Column(Integer, primary_key=True, index=True)
    concepto = Column(String, nullable=False)
    categoria = Column(String, nullable=False)
    valor = Column(Float, nullable=False)
    metodo_pago = Column(String, nullable=False, default="Efectivo")
    tipo = Column(String, nullable=False) # Manual/Liquidacion_Nomina/Pago_Proveedor
    referencia_id = Column(Integer, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    observacion = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class MovimientoCuentaCliente(Base):
    __tablename__ = "movimientos_cliente"
    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False, index=True)
    cuenta_id = Column(Integer, ForeignKey("cuentas_por_cobrar.id"), nullable=True, index=True)
    venta_id = Column(Integer, ForeignKey("ventas.id"), nullable=True, index=True)
    abono_id = Column(Integer, ForeignKey("abonos.id"), nullable=True, index=True)
    tipo = Column(String, nullable=False) # FIADO, ABONO, ANULACION, AJUSTE_MANUAL, DEVOLUCION
    monto = Column(Float, nullable=False)
    saldo_anterior = Column(Float, nullable=False)
    saldo_nuevo = Column(Float, nullable=False)
    metodo_pago = Column(String, nullable=True) # Efectivo, Transferencia
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    terminal_id = Column(Integer, ForeignKey("terminales.id"), nullable=True)
    motivo = Column(String, nullable=True)
    observacion = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

