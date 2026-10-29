from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from ..database import Base

class Servicio(Base):
    __tablename__ = "servicios"
    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String, unique=True, index=True, nullable=False) # S00001
    nombre = Column(String, nullable=False)
    descripcion = Column(String, nullable=True)
    categoria_id = Column(Integer, ForeignKey("categorias.id"), nullable=True)
    precio_venta = Column(Float, nullable=False)
    tipo_servicio = Column(String, default="Interno", nullable=False) # Interno/Proveedor
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"), nullable=True)
    costo_proveedor = Column(Float, default=0.0)
    porcentaje_comision = Column(Float, default=0.0)
    genera_comision = Column(Boolean, default=True)
    precio_variable = Column(Boolean, default=False)
    solo_operarios = Column(Boolean, default=False, nullable=False)
    creado_por_operario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    estado = Column(String, default="Activo")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
