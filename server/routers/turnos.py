from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import date

from ..database import get_db
from ..models.usuario import Usuario
from ..middleware.auth import get_current_user
from ..schemas.turno import (
    EstadoActualResponse, CicloTurnoResponse, AlmuerzoResponse,
    EventoTurnoResponse, ResumenDiaResponse, SaltoTurnoRequest,
    ReubicarTurnoRequest, AsignarManualRequest, AsignarEspecialRequest,
    CambiarDisponibilidadRequest, AbrirCicloRequest
)
from ..services.turno_service import TurnoService

router = APIRouter(prefix="/turnos", tags=["turnos"])

@router.get("/estado-actual", response_model=EstadoActualResponse)
async def get_estado_actual(
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene el estado en tiempo real de la cola de turnos y las estadísticas del día."""
    return await TurnoService.obtener_estado_actual(db, usuario_id=current_user.id)

@router.post("/abrir-ciclo", response_model=CicloTurnoResponse)
async def abrir_ciclo(
    req: Optional[AbrirCicloRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Inicia formalmente el ciclo de turnos del día."""
    user_rol = (current_user.rol or "").lower()
    if user_rol not in ["administrador", "admin", "gerente"]:
        raise HTTPException(status_code=403, detail="Solo el Administrador puede abrir manualmente el ciclo")
    orden = req.orden_inicial_usuario_ids if req else None
    ciclo = await TurnoService.obtener_o_crear_ciclo_hoy(db, usuario_id=current_user.id, terminal_id=1, orden_inicial=orden)
    return ciclo

@router.post("/cerrar-ciclo")
async def cerrar_ciclo(
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Cierra el ciclo de turnos del día (solo Administrador)."""
    user_rol = (current_user.rol or "").lower()
    if user_rol not in ["administrador", "admin", "gerente"]:
        raise HTTPException(status_code=403, detail="Solo el Administrador puede cerrar el ciclo de turnos")
    return await TurnoService.cerrar_ciclo(db, autor_id=current_user.id, terminal_id=1)

@router.post("/almuerzo/iniciar", response_model=AlmuerzoResponse)
async def iniciar_almuerzo(
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Registra la salida a almorzar del operario actual."""
    return await TurnoService.iniciar_almuerzo(db, usuario_id=current_user.id, terminal_id=1)

@router.post("/almuerzo/finalizar", response_model=AlmuerzoResponse)
async def finalizar_almuerzo(
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Registra el regreso del almuerzo del operario actual."""
    return await TurnoService.finalizar_almuerzo(db, usuario_id=current_user.id, terminal_id=1)

@router.post("/disponibilidad")
async def cambiar_disponibilidad(
    req: CambiarDisponibilidadRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Cambia el estado de disponibilidad del operario (DISPONIBLE, OCUPADO, PAUSADO)."""
    return await TurnoService.cambiar_disponibilidad(
        db,
        usuario_id=current_user.id,
        nuevo_estado=req.estado.upper(),
        autor_id=current_user.id,
        motivo=req.motivo,
        terminal_id=1
    )

@router.post("/saltar")
async def saltar_turno(
    req: SaltoTurnoRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Salta el turno del operario actual con motivo obligatorio (Administrador)."""
    user_rol = (current_user.rol or "").lower()
    if user_rol not in ["administrador", "admin", "gerente"]:
        raise HTTPException(status_code=403, detail="Solo el Administrador puede saltar turnos")
    return await TurnoService.saltar_turno(
        db,
        usuario_id=req.usuario_id,
        autor_id=current_user.id,
        motivo=req.motivo,
        terminal_id=1
    )

@router.post("/reubicar")
async def reubicar_operario(
    req: ReubicarTurnoRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Reubica a un operario en otra posición de la cola con motivo obligatorio (Administrador)."""
    user_rol = (current_user.rol or "").lower()
    if user_rol not in ["administrador", "admin", "gerente"]:
        raise HTTPException(status_code=403, detail="Solo el Administrador puede reubicar operarios en la cola")
    return await TurnoService.reubicar_operario(
        db,
        usuario_id=req.usuario_id,
        nueva_posicion=req.nueva_posicion,
        autor_id=current_user.id,
        motivo=req.motivo,
        terminal_id=1
    )

@router.post("/asignar-manual")
async def asignar_manual(
    req: AsignarManualRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Asignación manual extraordinaria del turno a un operario con motivo obligatorio (Administrador)."""
    user_rol = (current_user.rol or "").lower()
    if user_rol not in ["administrador", "admin", "gerente"]:
        raise HTTPException(status_code=403, detail="Solo el Administrador puede asignar turnos manualmente")
    return await TurnoService.asignar_turno_manual(
        db,
        usuario_id=req.usuario_id,
        autor_id=current_user.id,
        motivo=req.motivo,
        terminal_id=1
    )

@router.post("/asignar-especial")
async def asignar_especial(
    req: AsignarEspecialRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Registra autorización de un turno especial solicitado por un cliente (Administrador)."""
    user_rol = (current_user.rol or "").lower()
    if user_rol not in ["administrador", "admin", "gerente"]:
        raise HTTPException(status_code=403, detail="Solo el Administrador puede autorizar turnos especiales de forma administrativa")
    
    # Registra el evento en auditoría de turnos
    hoy = date.today()
    ciclo = await TurnoService.obtener_o_crear_ciclo_hoy(db, usuario_id=current_user.id, terminal_id=1)
    from ..models.turno import EventoTurno
    db.add(EventoTurno(
        ciclo_id=ciclo.id,
        usuario_id=req.usuario_id,
        autor_id=current_user.id,
        tipo_evento="TURNO_ESPECIAL",
        motivo=f"Asignación especial administrativa: {req.motivo}",
        terminal_id=1
    ))
    await db.commit()
    return {"message": "Turno especial autorizado y registrado en auditoría", "usuario_id": req.usuario_id}

@router.get("/historial", response_model=List[EventoTurnoResponse])
async def get_historial_eventos(
    fecha: Optional[date] = None,
    ciclo_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene la trazabilidad cronológica de todos los eventos del ciclo de turnos."""
    return await TurnoService.obtener_historial_eventos(db, ciclo_id=ciclo_id, fecha=fecha)

@router.get("/resumen-dia", response_model=ResumenDiaResponse)
async def get_resumen_dia(
    fecha: Optional[date] = None,
    ciclo_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene el resumen consolidado del día comparando turnos normales, especiales, saltos y almuerzos."""
    return await TurnoService.obtener_resumen_dia(db, ciclo_id=ciclo_id, fecha=fecha)
