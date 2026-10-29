from sqlalchemy import Column, Integer, String
from ..database import Base

class Proveedor(Base):
    __tablename__ = "proveedores"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    documento_nit = Column(String, nullable=False)
    telefono = Column(String, nullable=True)
    email = Column(String, nullable=True)
    direccion = Column(String, nullable=True)
    contacto = Column(String, nullable=True)
    estado = Column(String, default="Activo")
