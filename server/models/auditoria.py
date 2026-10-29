from sqlalchemy import Column, BigInteger, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from ..database import Base

class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(BigInteger, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    usuario_nombre = Column(String, nullable=False)
    terminal_id = Column(Integer, ForeignKey("terminales.id"), nullable=True)
    terminal_nombre = Column(String, nullable=True)
    accion = Column(String, nullable=False)
    modulo = Column(String, nullable=False)
    tabla_afectada = Column(String, nullable=False)
    registro_id = Column(String, nullable=False)
    valor_anterior = Column(JSON, nullable=True)
    valor_nuevo = Column(JSON, nullable=True)
    descripcion = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
