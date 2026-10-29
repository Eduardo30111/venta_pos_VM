from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from ..database import Base

class MovimientoInventario(Base):
    __tablename__ = "movimientos_inventario"
    id = Column(Integer, primary_key=True, index=True)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    tipo = Column(String, nullable=False) # ENTRADA/VENTA/DEVOLUCION/AJUSTE/ANULACION/TRASLADO/MERMA
    cantidad = Column(Float, nullable=False)
    stock_anterior = Column(Float, nullable=False)
    stock_nuevo = Column(Float, nullable=False)
    referencia = Column(String, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    terminal_id = Column(Integer, ForeignKey("terminales.id"), nullable=False)
    observacion = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
