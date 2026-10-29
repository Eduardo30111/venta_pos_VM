from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from ..database import Base

class Comision(Base):
    __tablename__ = "comisiones"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    venta_id = Column(Integer, ForeignKey("ventas.id"), nullable=False)
    detalle_venta_id = Column(Integer, ForeignKey("detalles_venta.id"), nullable=False)
    servicio_id = Column(Integer, ForeignKey("servicios.id"), nullable=True)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=True)
    valor_servicio = Column(Float, nullable=False)
    costo_servicio = Column(Float, default=0.0)
    utilidad = Column(Float, nullable=False)
    porcentaje = Column(Float, nullable=False)
    monto_comision = Column(Float, nullable=False)
    estado = Column(String, default="Pendiente") # Pendiente/Pendiente_Caja/Liquidada/Anulada
    liquidacion_id = Column(Integer, ForeignKey("liquidaciones.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Liquidacion(Base):
    __tablename__ = "liquidaciones"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    periodo_inicio = Column(DateTime(timezone=True), nullable=False)
    periodo_fin = Column(DateTime(timezone=True), nullable=False)
    total_servicios_vendidos = Column(Float, nullable=False)
    total_comisiones = Column(Float, nullable=False)
    total_salario_fijo = Column(Float, nullable=False)
    total_liquidado = Column(Float, nullable=False)
    estado = Column(String, default="Pendiente") # Pendiente/Liquidado/Anulado
    liquidado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    observaciones = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Asistencia(Base):
    __tablename__ = "asistencias"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    fecha = Column(DateTime, nullable=False)
    estado = Column(String, nullable=False) # Presente/Ausente/Permiso
    registrado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    salario_generado = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint('usuario_id', 'fecha', name='_usuario_fecha_uc'),)
