from sqlalchemy import Column, Integer, String
from ..database import Base

class Categoria(Base):
    __tablename__ = "categorias"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    tipo = Column(String, nullable=False) # Producto/Servicio/Ambos
    estado = Column(String, default="Activo")
