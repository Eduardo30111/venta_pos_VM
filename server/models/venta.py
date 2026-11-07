from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from ..database import Base


class Venta(Base):
    __tablename__ = "ventas"
    id = Column(Integer, primary_key=True, index=True)
    numero = Column(String, unique=True, index=True, nullable=False)  # V-000001
    idempotency_key = Column(String, unique=True, index=True, nullable=True)
    fecha = Column(String, nullable=True, index=True)  # YYYY-MM-DD local
    hora = Column(String, nullable=True)  # HH:MM:SS local
    sesion_caja_id = Column(Integer, nullable=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=True, index=True)
    cliente_documento = Column(String, nullable=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    operario_nombre = Column(String, nullable=True)
    terminal_id = Column(Integer, ForeignKey("terminales.id"), nullable=False)
    subtotal = Column(Float, nullable=False)
    descuento = Column(Float, default=0.0)
    total = Column(Float, nullable=False)
    metodo_pago_principal = Column(String, default="Efectivo", nullable=True)
    recibido = Column(Float, default=0.0)
    cambio = Column(Float, default=0.0)
    saldo_pendiente = Column(Float, default=0.0)
    estado = Column(String, default="Completada", index=True)
    observaciones = Column(String, nullable=True)
    motivo_anulacion = Column(String, nullable=True)
    anulada_por = Column(String, nullable=True)
    anulada_at = Column(String, nullable=True)
    modificado_por = Column(String, nullable=True)
    fecha_modificacion = Column(String, nullable=True)
    snapshot_negocio = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DetalleVenta(Base):
    __tablename__ = "detalles_venta"
    id = Column(Integer, primary_key=True, index=True)
    venta_id = Column(Integer, ForeignKey("ventas.id"), nullable=False, index=True)
    tipo_item = Column(String, nullable=False)  # Producto/Servicio
    item_id = Column(Integer, nullable=False)
    item_codigo = Column(String, nullable=False)
    item_nombre = Column(String, nullable=False)
    precio_original = Column(Float, nullable=False)
    precio_vendido = Column(Float, nullable=False)
    cantidad = Column(Float, nullable=False)
    descuento = Column(Float, default=0.0)
    subtotal = Column(Float, nullable=False)
    costo_unitario = Column(Float, nullable=False)


class Pago(Base):
    __tablename__ = "pagos"
    id = Column(Integer, primary_key=True, index=True)
    venta_id = Column(Integer, ForeignKey("ventas.id"), nullable=False, index=True)
    metodo = Column(String, nullable=False)  # Efectivo/Transferencia/Fiado
    monto = Column(Float, nullable=False)
    referencia = Column(String, nullable=True)
    recibido = Column(Float, nullable=False)
    cambio = Column(Float, nullable=False)
