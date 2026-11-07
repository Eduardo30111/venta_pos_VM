from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from ..database import Base


class Producto(Base):
    __tablename__ = "productos"
    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String, unique=True, index=True, nullable=True)  # 00001
    nombre = Column(String, nullable=True)
    descripcion = Column(String, nullable=True)
    categoria_id = Column(Integer, ForeignKey("categorias.id"), nullable=True)
    categoria = Column(String, default="General", nullable=True)
    marca = Column(String, default="", nullable=True)
    unidad_medida = Column(String, default="Unidad", nullable=True)
    precio_costo = Column(Float, default=0.0, nullable=True)
    precio_venta = Column(Float, default=0.0, nullable=True)
    stock = Column(Float, default=0.0)
    stock_minimo = Column(Float, default=0.0)
    stock_bodega = Column(Float, default=0.0)
    stock_vitrina = Column(Float, default=0.0)
    stock_minimo_bodega = Column(Float, default=5.0)
    stock_minimo_vitrina = Column(Float, default=3.0)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"), nullable=True)
    codigo_barras = Column(String, nullable=True)
    imagen_url = Column(String, nullable=True)
    precio_variable = Column(Boolean, default=False)
    porcentaje_comision = Column(Float, default=0.0)
    estado = Column(String, default="Activo")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
