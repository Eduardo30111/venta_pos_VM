from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float
from sqlalchemy.sql import func
from ..database import Base

class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=True, default="")
    apellidos = Column(String, nullable=True, default="")
    documento = Column(String, unique=True, index=True, nullable=True)
    usuario = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    rol = Column(String, nullable=False) # Administrador/Vendedor/Operario
    tipo_remuneracion = Column(String, nullable=True, default='Porcentual') # Fija/Porcentual
    salario_diario = Column(Float, default=0.0)
    porcentaje_comision = Column(Float, default=0.0)
    estado = Column(String, default='Activo') # Activo/Inactivo
    fecha_registro = Column(DateTime(timezone=True), server_default=func.now())
    ultimo_acceso = Column(DateTime(timezone=True), nullable=True)
    solicitud_liquidacion = Column(DateTime(timezone=True), nullable=True)
