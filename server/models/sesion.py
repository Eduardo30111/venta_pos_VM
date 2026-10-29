from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from ..database import Base

class Sesion(Base):
    __tablename__ = "sesiones"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    terminal_id = Column(Integer, ForeignKey("terminales.id"), nullable=False)
    token = Column(String, unique=True, index=True, nullable=False)
    inicio = Column(DateTime(timezone=True), nullable=False)
    expira = Column(DateTime(timezone=True), nullable=False)
    activa = Column(Boolean, default=True)
