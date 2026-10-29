from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from sqlalchemy.sql import func
from ..database import Base

class Cliente(Base):
    __tablename__ = "clientes"
    id = Column(Integer, primary_key=True, index=True)
    documento = Column(String, unique=True, index=True, nullable=False)
    nombre = Column(String, nullable=False)
    email = Column(String, nullable=True)
    telefono = Column(String, nullable=True)
    direccion = Column(String, nullable=True)
    permite_fiado = Column(Boolean, default=False)
    limite_credito = Column(Float, default=0.0)
    estado = Column(String, default="Activo")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
