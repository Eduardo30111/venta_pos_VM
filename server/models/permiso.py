from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, UniqueConstraint
from ..database import Base

class PermisoUsuario(Base):
    __tablename__ = "permisos_usuarios"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    permiso = Column(String, nullable=False)
    concedido = Column(Boolean, default=False)
    __table_args__ = (UniqueConstraint('usuario_id', 'permiso', name='_usuario_permiso_uc'),)
