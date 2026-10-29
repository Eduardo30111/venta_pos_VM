from sqlalchemy import Column, Integer, String
from ..database import Base

class Terminal(Base):
    __tablename__ = "terminales"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, unique=True, nullable=False)
    descripcion = Column(String, nullable=True)
    estado = Column(String, default="Activo")
