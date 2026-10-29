from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, Date, Float, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from ..database import Base

class CicloTurno(Base):
    __tablename__ = "ciclos_turno"

    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(Date, index=True, nullable=False)
    estado = Column(String(20), default="Abierto", nullable=False)  # 'Abierto', 'Cerrado'
    iniciado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    cerrado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    closed_at = Column(DateTime(timezone=True), nullable=True)


class ColaTurno(Base):
    __tablename__ = "cola_turno"

    id = Column(Integer, primary_key=True, index=True)
    ciclo_id = Column(Integer, ForeignKey("ciclos_turno.id", ondelete="CASCADE"), index=True, nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), index=True, nullable=False)
    posicion = Column(Integer, nullable=False)  # 1, 2, 3, ... N
    estado = Column(String(30), default="DISPONIBLE", nullable=False)  # DISPONIBLE, EN_TURNO, ATENDIENDO, OCUPADO, ALMUERZO, PAUSADO, FUERA_DE_TURNO
    en_turno_desde = Column(DateTime(timezone=True), nullable=True)
    turno_retorno_posicion = Column(Integer, nullable=True)
    turnos_pendientes = Column(Integer, default=0, nullable=False)
    ultima_atencion = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("ciclo_id", "usuario_id", name="uq_ciclo_usuario"),
    )


class AtencionTurno(Base):
    __tablename__ = "atenciones_turno"

    id = Column(Integer, primary_key=True, index=True)
    ciclo_id = Column(Integer, ForeignKey("ciclos_turno.id"), index=True, nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), index=True, nullable=False)
    venta_id = Column(Integer, ForeignKey("ventas.id"), unique=True, nullable=True)  # Idempotencia: una venta solo genera una atención
    tipo_turno = Column(String(20), default="NORMAL", nullable=False)  # 'NORMAL', 'ESPECIAL'
    motivo_especial = Column(String(255), nullable=True)
    posicion_cola = Column(Integer, nullable=True)
    terminal_id = Column(Integer, ForeignKey("terminales.id"), nullable=True)
    fecha_hora = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    duracion_segundos = Column(Integer, nullable=True)
    fuera_de_orden = Column(Boolean, default=False)
    observacion = Column(String(255), nullable=True)


class AlmuerzoTurno(Base):
    __tablename__ = "almuerzos_turno"

    id = Column(Integer, primary_key=True, index=True)
    ciclo_id = Column(Integer, ForeignKey("ciclos_turno.id"), index=True, nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), index=True, nullable=False)
    terminal_id = Column(Integer, ForeignKey("terminales.id"), nullable=True)
    hora_salida = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    hora_regreso = Column(DateTime(timezone=True), nullable=True)
    duracion_minutos = Column(Float, nullable=True)
    estado = Column(String(20), default="En_Curso", nullable=False)  # 'En_Curso', 'Finalizado'


class EventoTurno(Base):
    __tablename__ = "eventos_turno"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    ciclo_id = Column(Integer, ForeignKey("ciclos_turno.id"), index=True, nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)  # Operario afectado
    autor_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)  # Quien ejecutó la acción
    tipo_evento = Column(String(50), nullable=False)  # INICIO_CICLO, AVANCE_COLA, ATENCION_REGISTRADA, TURNO_ESPECIAL, SALTO_TURNO, REUBICACION, ASIGNACION_MANUAL, INICIO_ALMUERZO, FIN_ALMUERZO, CAMBIO_ESTADO, CIERRE_CICLO
    posicion_anterior = Column(Integer, nullable=True)
    posicion_nueva = Column(Integer, nullable=True)
    estado_anterior = Column(String(30), nullable=True)
    estado_nuevo = Column(String(30), nullable=True)
    motivo = Column(String(255), nullable=True)  # Obligatorio para acciones administrativas
    terminal_id = Column(Integer, ForeignKey("terminales.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
