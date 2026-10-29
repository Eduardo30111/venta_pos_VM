from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from ..database import Base

class Producto(Base):
    __tablename__ = "productos"
    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String, unique=True, index=True, nullable=True) # 00001
    nombre = Column(String, nullable=True)
    descripcion = Column(String, nullable=True)
    categoria_id = Column(Integer, ForeignKey("categorias.id"), nullable=True)
    precio_costo = Column(Float, nullable=True)
    precio_venta = Column(Float, nullable=True)
    stock = Column(Float, default=0)
    stock_minimo = Column(Float, default=0)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"), nullable=True)
    codigo_barras = Column(String, nullable=True)
    imagen_url = Column(String, nullable=True)
    estado = Column(String, default="Activo")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
