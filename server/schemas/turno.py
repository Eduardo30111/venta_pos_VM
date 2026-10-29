from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime, date

# -----------------
# Peticiones
# -----------------

class SaltoTurnoRequest(BaseModel):
    usuario_id: Optional[int] = None  # Si no se envía, salta al que esté EN_TURNO
    motivo: str = Field(..., min_length=5, description="Motivo obligatorio del salto")

class ReubicarTurnoRequest(BaseModel):
    usuario_id: int
    nueva_posicion: int = Field(..., ge=1, description="Nueva posición en la cola (1..N)")
    motivo: str = Field(..., min_length=5, description="Motivo obligatorio de la reubicación")

class AsignarManualRequest(BaseModel):
    usuario_id: int
    motivo: str = Field(..., min_length=5, description="Motivo obligatorio de asignación manual")

class AsignarEspecialRequest(BaseModel):
    usuario_id: int
    motivo: str = Field(..., min_length=5, description="Motivo obligatorio del turno especial (ej. Cliente lo solicitó)")

class CambiarDisponibilidadRequest(BaseModel):
    estado: str = Field(..., description="Nuevo estado: DISPONIBLE, OCUPADO, PAUSADO")
    motivo: Optional[str] = None

class AbrirCicloRequest(BaseModel):
    orden_inicial_usuario_ids: Optional[List[int]] = None

# -----------------
# Respuestas
# -----------------

class CicloTurnoResponse(BaseModel):
    id: int
    fecha: date
    estado: str
    iniciado_por: int
    cerrado_por: Optional[int] = None
    created_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class ColaItemResponse(BaseModel):
    id: int
    ciclo_id: int
    usuario_id: int
    nombre_operario: str
    rol: str
    posicion: int
    estado: str
    en_turno_desde: Optional[datetime] = None
    tiempo_en_turno_segundos: int = 0
    tiempo_en_turno_formato: str = "00:00:00"
    ultima_atencion: Optional[datetime] = None
    turnos_normales: int = 0
    turnos_especiales: int = 0
    total_turnos: int = 0

class TurnoActualResponse(BaseModel):
    usuario_id: Optional[int] = None
    nombre_operario: Optional[str] = None
    posicion: Optional[int] = None
    estado: Optional[str] = None
    en_turno_desde: Optional[datetime] = None
    tiempo_en_turno_segundos: int = 0
    tiempo_en_turno_formato: str = "00:00:00"
    tiempo_elevado: bool = False
    turnos_normales: int = 0
    turnos_especiales: int = 0
    total_turnos: int = 0

class EstadoActualResponse(BaseModel):
    ciclo: Optional[CicloTurnoResponse] = None
    turno_actual: Optional[TurnoActualResponse] = None
    cola: List[ColaItemResponse] = []
    mi_turno: Optional[ColaItemResponse] = None  # Si el usuario solicitante es operario
    alerta_tiempo_elevado: bool = False
    total_atenciones_dia: int = 0
    servidor_hora: datetime

class AtencionTurnoResponse(BaseModel):
    id: int
    ciclo_id: int
    usuario_id: int
    usuario_nombre: str
    venta_id: Optional[int] = None
    venta_numero: Optional[str] = None
    tipo_turno: str
    motivo_especial: Optional[str] = None
    posicion_cola: Optional[int] = None
    terminal_id: Optional[int] = None
    fecha_hora: Optional[datetime] = None
    duracion_segundos: Optional[int] = None
    fuera_de_orden: bool = False
    observacion: Optional[str] = None

    class Config:
        from_attributes = True

class AlmuerzoResponse(BaseModel):
    id: int
    ciclo_id: int
    usuario_id: int
    usuario_nombre: str
    hora_salida: datetime
    hora_regreso: Optional[datetime] = None
    duracion_minutos: Optional[float] = None
    estado: str

    class Config:
        from_attributes = True

class EventoTurnoResponse(BaseModel):
    id: int
    ciclo_id: int
    usuario_id: Optional[int] = None
    usuario_nombre: Optional[str] = None
    autor_id: int
    autor_nombre: str
    tipo_evento: str
    posicion_anterior: Optional[int] = None
    posicion_nueva: Optional[int] = None
    estado_anterior: Optional[str] = None
    estado_nuevo: Optional[str] = None
    motivo: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class ResumenOperarioDia(BaseModel):
    usuario_id: int
    usuario_nombre: str
    posicion_actual: Optional[int] = None
    estado_actual: str
    normales: int = 0
    especiales: int = 0
    saltados: int = 0
    almuerzos: int = 0
    minutos_almuerzo: float = 0.0
    total_atendidos: int = 0
    ultima_atencion: Optional[datetime] = None

class ResumenDiaResponse(BaseModel):
    ciclo_id: int
    fecha: date
    estado_ciclo: str
    total_atenciones: int
    total_normales: int
    total_especiales: int
    total_saltados: int
    operarios: List[ResumenOperarioDia] = []
