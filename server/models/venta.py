from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from ..database import Base

class Venta(Base):
    __tablename__ = "ventas"
    id = Column(Integer, primary_key=True, index=True)
    numero = Column(String, unique=True, index=True, nullable=False) # V-000001
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    terminal_id = Column(Integer, ForeignKey("terminales.id"), nullable=False)
    subtotal = Column(Float, nullable=False)
    descuento = Column(Float, default=0.0)
    total = Column(Float, nullable=False)
    estado = Column(String, default="Completada")
    observaciones = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class DetalleVenta(Base):
    __tablename__ = "detalles_venta"
    id = Column(Integer, primary_key=True, index=True)
    venta_id = Column(Integer, ForeignKey("ventas.id"), nullable=False)
    tipo_item = Column(String, nullable=False) # Producto/Servicio
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
    venta_id = Column(Integer, ForeignKey("ventas.id"), nullable=False)
    metodo = Column(String, nullable=False) # Efectivo/Transferencia/Fiado
    monto = Column(Float, nullable=False)
    referencia = Column(String, nullable=True)
    recibido = Column(Float, nullable=False)
    cambio = Column(Float, nullable=False)
