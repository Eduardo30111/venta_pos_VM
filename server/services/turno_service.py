from datetime import datetime, date, timezone
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, or_, and_, update
from fastapi import HTTPException

from ..models.turno import CicloTurno, ColaTurno, AtencionTurno, AlmuerzoTurno, EventoTurno
from ..models.usuario import Usuario
from ..models.venta import Venta
from ..models.terminal import Terminal
from ..schemas.turno import (
    EstadoActualResponse, CicloTurnoResponse, ColaItemResponse, TurnoActualResponse,
    ResumenDiaResponse, ResumenOperarioDia, EventoTurnoResponse, AlmuerzoResponse
)

class TurnoService:

    @staticmethod
    def _es_operario(usuario: Usuario) -> bool:
        return (usuario.rol or "").strip().lower() == "operario"

    @staticmethod
    def _calcular_formato_tiempo(segundos: int) -> str:
        if segundos < 0:
            segundos = 0
        horas = segundos // 3600
        minutos = (segundos % 3600) // 60
        segs = segundos % 60
        return f"{horas:02d}:{minutos:02d}:{segs:02d}"

    @staticmethod
    def _normalizar_turno_activo(cola_items: List[ColaTurno], preferido: Optional[ColaTurno] = None) -> Optional[ColaTurno]:
        """Garantiza que una cola tenga como maximo un operario EN_TURNO."""
        elegibles = [item for item in cola_items if item.estado not in ["ALMUERZO", "OCUPADO", "PAUSADO"]]
        activo = preferido or next((item for item in elegibles if item.estado == "EN_TURNO"), None)
        if activo is None and elegibles:
            activo = elegibles[0]

        for item in cola_items:
            if item is activo:
                item.estado = "EN_TURNO"
                if item.en_turno_desde is None:
                    item.en_turno_desde = func.now()
            elif item.estado == "EN_TURNO":
                item.estado = "DISPONIBLE"
                item.en_turno_desde = None
        return activo

    @staticmethod
    async def _agregar_operario_si_corresponde(db: AsyncSession, ciclo: CicloTurno, usuario_id: int) -> Optional[ColaTurno]:
        """Incorpora solo al operario que acaba de entrar, una sola vez."""
        usuario_res = await db.execute(select(Usuario).where(
            Usuario.id == usuario_id,
            Usuario.estado == "Activo",
            func.lower(Usuario.rol) == "operario"
        ))
        usuario = usuario_res.scalars().first()
        if not usuario:
            return None

        existente_res = await db.execute(select(ColaTurno).where(
            ColaTurno.ciclo_id == ciclo.id,
            ColaTurno.usuario_id == usuario_id
        ))
        existente = existente_res.scalars().first()
        if existente:
            return existente

        posicion_res = await db.execute(select(func.max(ColaTurno.posicion)).where(ColaTurno.ciclo_id == ciclo.id))
        siguiente_posicion = (posicion_res.scalar() or 0) + 1
        hay_activo_res = await db.execute(select(ColaTurno.id).where(
            ColaTurno.ciclo_id == ciclo.id,
            ColaTurno.estado == "EN_TURNO"
        ).limit(1))
        es_primer_turno = hay_activo_res.scalar() is None
        nuevo = ColaTurno(
            ciclo_id=ciclo.id,
            usuario_id=usuario_id,
            posicion=siguiente_posicion,
            estado="EN_TURNO" if es_primer_turno else "DISPONIBLE",
            en_turno_desde=func.now() if es_primer_turno else None
        )
        db.add(nuevo)
        await db.flush()
        return nuevo

    @staticmethod
    async def obtener_o_crear_ciclo_hoy(db: AsyncSession, usuario_id: int, terminal_id: int = 1, orden_inicial: Optional[List[int]] = None) -> CicloTurno:
        hoy = date.today()
        # Buscar ciclo abierto hoy
        stmt = select(CicloTurno).where(CicloTurno.fecha == hoy, CicloTurno.estado == "Abierto")
        res = await db.execute(stmt)
        ciclo = res.scalars().first()

        if ciclo:
            return ciclo

        # Crear nuevo ciclo para hoy
        ciclo = CicloTurno(
            fecha=hoy,
            estado="Abierto",
            iniciado_por=usuario_id
        )
        db.add(ciclo)
        await db.flush()

        # La cola se construye de forma incremental: solo entra el operario
        # que inició la sesión; los demás se agregan al acceder a su perfil.
        await TurnoService._agregar_operario_si_corresponde(db, ciclo, usuario_id)

        # Registrar evento de inicio de ciclo
        db.add(EventoTurno(
            ciclo_id=ciclo.id,
            usuario_id=usuario_id,
            autor_id=usuario_id,
            tipo_evento="INICIO_CICLO",
            posicion_nueva=1,
            estado_nuevo="Abierto",
            motivo="Apertura de jornada comercial y construcción de cola inicial",
            terminal_id=terminal_id
        ))

        await db.commit()
        await db.refresh(ciclo)
        return ciclo

    @staticmethod
    async def obtener_estado_actual(db: AsyncSession, usuario_id: Optional[int] = None) -> EstadoActualResponse:
        hoy = date.today()
        # Buscar ciclo abierto de hoy
        stmt = select(CicloTurno).where(CicloTurno.fecha == hoy, CicloTurno.estado == "Abierto")
        res = await db.execute(stmt)
        ciclo = res.scalars().first()

        # El administrador puede supervisar, pero no debe abrir ni poblar la
        # cola. El primer operario que consulte su perfil crea el ciclo diario.
        if not ciclo and usuario_id:
            usuario_res = await db.execute(select(Usuario).where(Usuario.id == usuario_id))
            usuario = usuario_res.scalars().first()
            if usuario and TurnoService._es_operario(usuario):
                ciclo = await TurnoService.obtener_o_crear_ciclo_hoy(db, usuario_id=usuario_id)

        if usuario_id:
            await TurnoService._agregar_operario_si_corresponde(db, ciclo, usuario_id)
            await db.commit()

        ahora_utc = datetime.now(timezone.utc)

        if not ciclo:
            return EstadoActualResponse(
                ciclo=None,
                turno_actual=None,
                cola=[],
                mi_turno=None,
                alerta_tiempo_elevado=False,
                total_atenciones_dia=0,
                servidor_hora=ahora_utc
            )

        # Cargar cola ordenada por posición
        q_stmt = select(ColaTurno, Usuario).join(Usuario, ColaTurno.usuario_id == Usuario.id).where(
            ColaTurno.ciclo_id == ciclo.id,
            func.lower(Usuario.rol) == "operario"
        ).order_by(ColaTurno.posicion.asc())
        q_res = await db.execute(q_stmt)
        filas = q_res.all()
        cola_db = [cola for cola, _ in filas]
        estados_antes = [(item.id, item.estado, item.en_turno_desde) for item in cola_db]
        TurnoService._normalizar_turno_activo(cola_db)
        estados_despues = [(item.id, item.estado, item.en_turno_desde) for item in cola_db]
        if estados_antes != estados_despues:
            await db.commit()

        cola_items: List[ColaItemResponse] = []
        turno_actual_obj: Optional[TurnoActualResponse] = None
        mi_turno_obj: Optional[ColaItemResponse] = None
        total_atenciones = 0
        alerta_elevado_global = False

        for cola, user in filas:
            nom = f"{user.nombre or ''} {user.apellidos or ''}".strip() or user.usuario

            # Contar atenciones de este operario hoy
            at_norm = await db.execute(
                select(func.count(AtencionTurno.id)).where(
                    AtencionTurno.ciclo_id == ciclo.id,
                    AtencionTurno.usuario_id == user.id,
                    AtencionTurno.tipo_turno == "NORMAL"
                )
            )
            count_norm = at_norm.scalar() or 0

            at_esp = await db.execute(
                select(func.count(AtencionTurno.id)).where(
                    AtencionTurno.ciclo_id == ciclo.id,
                    AtencionTurno.usuario_id == user.id,
                    AtencionTurno.tipo_turno == "ESPECIAL"
                )
            )
            count_esp = at_esp.scalar() or 0
            tot_user = count_norm + count_esp
            total_atenciones += tot_user

            # Calcular tiempo en turno si está EN_TURNO
            segundos_en_turno = 0
            if cola.estado == "EN_TURNO" and cola.en_turno_desde:
                dt_desde = cola.en_turno_desde
                if dt_desde.tzinfo is None:
                    dt_desde = dt_desde.replace(tzinfo=timezone.utc)
                segundos_en_turno = int((ahora_utc - dt_desde).total_seconds())
                if segundos_en_turno < 0:
                    segundos_en_turno = 0

            fmt_tiempo = TurnoService._calcular_formato_tiempo(segundos_en_turno)
            tiempo_elevado = (segundos_en_turno >= 900)  # 15 minutos

            item_dto = ColaItemResponse(
                id=cola.id,
                ciclo_id=cola.ciclo_id,
                usuario_id=cola.usuario_id,
                nombre_operario=nom,
                rol=user.rol,
                posicion=cola.posicion,
                estado=cola.estado,
                en_turno_desde=cola.en_turno_desde,
                tiempo_en_turno_segundos=segundos_en_turno,
                tiempo_en_turno_formato=fmt_tiempo,
                ultima_atencion=cola.ultima_atencion,
                turnos_normales=count_norm,
                turnos_especiales=count_esp,
                total_turnos=tot_user
            )
            cola_items.append(item_dto)

            if cola.estado == "EN_TURNO":
                if tiempo_elevado:
                    alerta_elevado_global = True
                turno_actual_obj = TurnoActualResponse(
                    usuario_id=user.id,
                    nombre_operario=nom,
                    posicion=cola.posicion,
                    estado=cola.estado,
                    en_turno_desde=cola.en_turno_desde,
                    tiempo_en_turno_segundos=segundos_en_turno,
                    tiempo_en_turno_formato=fmt_tiempo,
                    tiempo_elevado=tiempo_elevado,
                    turnos_normales=count_norm,
                    turnos_especiales=count_esp,
                    total_turnos=tot_user
                )

            if usuario_id and user.id == usuario_id:
                mi_turno_obj = item_dto

        # Si nadie tiene EN_TURNO explícito, buscar el primer DISPONIBLE
        if not turno_actual_obj and cola_items:
            primer_disp = next((it for it in cola_items if it.estado == "DISPONIBLE"), None)
            if primer_disp:
                turno_actual_obj = TurnoActualResponse(
                    usuario_id=primer_disp.usuario_id,
                    nombre_operario=primer_disp.nombre_operario,
                    posicion=primer_disp.posicion,
                    estado="EN_TURNO_SUGERIDO",
                    en_turno_desde=None,
                    tiempo_en_turno_segundos=0,
                    tiempo_en_turno_formato="00:00:00",
                    tiempo_elevado=False,
                    turnos_normales=primer_disp.turnos_normales,
                    turnos_especiales=primer_disp.turnos_especiales,
                    total_turnos=primer_disp.total_turnos
                )

        ciclo_dto = CicloTurnoResponse.model_validate(ciclo)
        return EstadoActualResponse(
            ciclo=ciclo_dto,
            turno_actual=turno_actual_obj,
            cola=cola_items,
            mi_turno=mi_turno_obj,
            alerta_tiempo_elevado=alerta_elevado_global,
            total_atenciones_dia=total_atenciones,
            servidor_hora=ahora_utc
        )

    @staticmethod
    async def registrar_atencion_venta(
        db: AsyncSession,
        venta: Venta,
        usuario_id: int,
        terminal_id: int,
        es_turno_especial: bool = False,
        motivo_especial: Optional[str] = None
    ):
        """
        Disparador atómico ejecutado cuando un operario manda una venta a caja o la completa.
        Garantiza IDEMPOTENCIA total: si ya existe una atención para venta.id, no hace nada.
        """
        operador_res = await db.execute(select(Usuario).where(Usuario.id == usuario_id))
        operador = operador_res.scalars().first()
        if not operador or not TurnoService._es_operario(operador):
            return

        # 1. Idempotencia: Verificar si ya existe registro para esta venta
        res_exist = await db.execute(select(AtencionTurno).where(AtencionTurno.venta_id == venta.id))
        if res_exist.scalars().first():
            return  # Idempotente: atención ya registrada

        # 2. Obtener ciclo abierto de hoy o crear uno si no existe
        hoy = date.today()
        stmt = select(CicloTurno).where(CicloTurno.fecha == hoy, CicloTurno.estado == "Abierto")
        ciclo = (await db.execute(stmt)).scalars().first()
        if not ciclo:
            ciclo = await TurnoService.obtener_o_crear_ciclo_hoy(db, usuario_id, terminal_id)

        # 3. Bloquear la cola para este ciclo con row-level lock (with_for_update)
        q_stmt = select(ColaTurno).join(Usuario, ColaTurno.usuario_id == Usuario.id).where(
            ColaTurno.ciclo_id == ciclo.id,
            func.lower(Usuario.rol) == "operario"
        ).order_by(ColaTurno.posicion.asc()).with_for_update()
        cola_items = list((await db.execute(q_stmt)).scalars().all())
        TurnoService._normalizar_turno_activo(cola_items)

        # Si el operario no está en la cola, agregarlo al final
        op_item = next((c for c in cola_items if c.usuario_id == usuario_id), None)
        if not op_item:
            nueva_pos = len(cola_items) + 1
            op_item = ColaTurno(
                ciclo_id=ciclo.id,
                usuario_id=usuario_id,
                posicion=nueva_pos,
                estado="DISPONIBLE"
            )
            db.add(op_item)
            await db.flush()
            cola_items.append(op_item)

        tipo_final = "ESPECIAL" if es_turno_especial else "NORMAL"
        estado_al_iniciar_atencion = op_item.estado
        fuera_de_orden = (op_item.estado != "EN_TURNO") and (tipo_final == "NORMAL")

        # 4. Registrar la atención
        atencion = AtencionTurno(
            ciclo_id=ciclo.id,
            usuario_id=usuario_id,
            venta_id=venta.id,
            tipo_turno=tipo_final,
            motivo_especial=motivo_especial if es_turno_especial else None,
            posicion_cola=op_item.posicion,
            terminal_id=terminal_id,
            fuera_de_orden=fuera_de_orden,
            observacion=f"Venta {venta.numero}" + (" (Atención fuera de posición inmediata)" if fuera_de_orden else "")
        )
        db.add(atencion)

        # 5. Actualizar última atención del operario
        op_item.ultima_atencion = func.now()

        # 6. Lógica de avance de la cola según tipo de turno
        if tipo_final == "NORMAL":
            # Una venta iniciada mientras el operario estaba OCUPADO no debe
            # robarle el turno al operario que actualmente atiende la cola.
            # El pago termina su atención y lo deja DISPONIBLE.
            if estado_al_iniciar_atencion == "OCUPADO":
                if op_item.turnos_pendientes:
                    op_item.turnos_pendientes = max(0, op_item.turnos_pendientes - 1)
                op_item.estado = "DISPONIBLE"
                op_item.en_turno_desde = None
                db.add(EventoTurno(
                    ciclo_id=ciclo.id,
                    usuario_id=usuario_id,
                    autor_id=usuario_id,
                    tipo_evento="ATENCION_REGISTRADA",
                    posicion_anterior=op_item.posicion,
                    posicion_nueva=op_item.posicion,
                    estado_anterior="OCUPADO",
                    estado_nuevo="DISPONIBLE",
                    motivo=f"Venta {venta.numero} finalizada mientras el operario estaba ocupado",
                    terminal_id=terminal_id
                ))
                await db.flush()
                return

            # Si el operario está atendiendo un turno recuperado, esta venta
            # consume una de sus vueltas pendientes.
            estaba_recuperando = (op_item.turnos_pendientes or 0) > 0
            if estaba_recuperando:
                op_item.turnos_pendientes -= 1

            # Si aún debe recuperar vueltas, conserva inmediatamente el turno.
            op_item.estado = "DISPONIBLE"
            op_item.en_turno_desde = None
            if estaba_recuperando and op_item.turnos_pendientes > 0:
                op_item.estado = "EN_TURNO"
                op_item.en_turno_desde = func.now()
                await db.flush()
                return

            # Avanzar la cola circularmente al siguiente operario elegible
            total_ops = len(cola_items)
            pos_actual = op_item.posicion
            siguiente_op: Optional[ColaTurno] = None

            # Si este operario estaba atendiendo un turno de retorno, primero
            # devuelve la cola al operario que quedó desplazado.
            if op_item.turno_retorno_posicion is not None:
                retorno = next((c for c in cola_items if c.posicion == op_item.turno_retorno_posicion), None)
                if retorno and retorno.id != op_item.id and retorno.estado not in ["ALMUERZO", "PAUSADO", "OCUPADO"]:
                    siguiente_op = retorno
                op_item.turno_retorno_posicion = None

            # Sin retorno pendiente, continuar el orden circular normal.
            if siguiente_op is None:
                for offset in range(1, total_ops + 1):
                    candidato_pos = ((pos_actual - 1 + offset) % total_ops) + 1
                    cand = next((c for c in cola_items if c.posicion == candidato_pos), None)
                    if cand and cand.id != op_item.id:
                        # Cada vuelta que se salta un operario ocupado queda
                        # pendiente para que pueda reclamarla al liberarse.
                        if cand.estado == "OCUPADO":
                            cand.turnos_pendientes = (cand.turnos_pendientes or 0) + 1
                            continue
                        if cand.estado not in ["ALMUERZO", "PAUSADO"]:
                            siguiente_op = cand
                            break

            # Si se encontró un siguiente operario elegible, pasa a EN_TURNO
            if siguiente_op:
                siguiente_op.estado = "EN_TURNO"
                siguiente_op.en_turno_desde = func.now()

            # Registrar evento de avance en auditoría
            db.add(EventoTurno(
                ciclo_id=ciclo.id,
                usuario_id=usuario_id,
                autor_id=usuario_id,
                tipo_evento="AVANCE_COLA",
                posicion_anterior=pos_actual,
                posicion_nueva=siguiente_op.posicion if siguiente_op else None,
                estado_anterior="EN_TURNO",
                estado_nuevo="DISPONIBLE",
                motivo=f"Atención venta {venta.numero}. Pasa turno a {siguiente_op.usuario_id if siguiente_op else 'N/A'}",
                terminal_id=terminal_id
            ))
        else:
            # TURNO ESPECIAL:
            # REGLA FUNDAMENTAL: NO altera ni avanza la cola normal.
            # El operario que estaba EN_TURNO sigue EN_TURNO.
            # El operario que atendió turno especial conserva su estado DISPONIBLE u OCUPADO.
            if op_item.estado not in ["ALMUERZO", "PAUSADO"]:
                op_item.estado = "DISPONIBLE"

            db.add(EventoTurno(
                ciclo_id=ciclo.id,
                usuario_id=usuario_id,
                autor_id=usuario_id,
                tipo_evento="TURNO_ESPECIAL",
                posicion_anterior=op_item.posicion,
                posicion_nueva=op_item.posicion,
                estado_anterior=op_item.estado,
                estado_nuevo=op_item.estado,
                motivo=motivo_especial or f"Atención turno especial por solicitud de cliente (Venta {venta.numero})",
                terminal_id=terminal_id
            ))

        await db.flush()

    @staticmethod
    async def iniciar_almuerzo(db: AsyncSession, usuario_id: int, terminal_id: int = 1) -> AlmuerzoResponse:
        operador_res = await db.execute(select(Usuario).where(Usuario.id == usuario_id))
        operador = operador_res.scalars().first()
        if not operador or not TurnoService._es_operario(operador):
            raise HTTPException(status_code=403, detail="Solo los operarios tienen control de turnos")
        hoy = date.today()
        stmt = select(CicloTurno).where(CicloTurno.fecha == hoy, CicloTurno.estado == "Abierto")
        ciclo = (await db.execute(stmt)).scalars().first()
        if not ciclo:
            ciclo = await TurnoService.obtener_o_crear_ciclo_hoy(db, usuario_id, terminal_id)

        # Bloquear cola con lock pesimista
        q_stmt = select(ColaTurno).join(Usuario, ColaTurno.usuario_id == Usuario.id).where(
            ColaTurno.ciclo_id == ciclo.id,
            func.lower(Usuario.rol) == "operario"
        ).order_by(ColaTurno.posicion.asc()).with_for_update()
        cola_items = list((await db.execute(q_stmt)).scalars().all())
        TurnoService._normalizar_turno_activo(cola_items)

        op_item = next((c for c in cola_items if c.usuario_id == usuario_id), None)
        if not op_item:
            raise HTTPException(status_code=404, detail="Operario no encontrado en la cola del turno")

        if op_item.estado == "ALMUERZO":
            raise HTTPException(status_code=400, detail="El operario ya se encuentra en horario de almuerzo")

        est_anterior = op_item.estado

        # Si estaba EN_TURNO, ceder el turno al siguiente operario elegible
        if est_anterior == "EN_TURNO":
            op_item.en_turno_desde = None
            total_ops = len(cola_items)
            for offset in range(1, total_ops + 1):
                cand_pos = ((op_item.posicion - 1 + offset) % total_ops) + 1
                cand = next((c for c in cola_items if c.posicion == cand_pos), None)
                if cand and cand.id != op_item.id and cand.estado == "DISPONIBLE":
                    cand.estado = "EN_TURNO"
                    cand.en_turno_desde = func.now()
                    break

        op_item.estado = "ALMUERZO"

        # Crear registro de almuerzo
        almuerzo = AlmuerzoTurno(
            ciclo_id=ciclo.id,
            usuario_id=usuario_id,
            terminal_id=terminal_id,
            hora_salida=func.now(),
            estado="En_Curso"
        )
        db.add(almuerzo)

        # Registrar evento
        db.add(EventoTurno(
            ciclo_id=ciclo.id,
            usuario_id=usuario_id,
            autor_id=usuario_id,
            tipo_evento="INICIO_ALMUERZO",
            posicion_anterior=op_item.posicion,
            posicion_nueva=op_item.posicion,
            estado_anterior=est_anterior,
            estado_nuevo="ALMUERZO",
            motivo="Salida a almorzar autorizada por el operario",
            terminal_id=terminal_id
        ))

        await db.commit()
        await db.refresh(almuerzo)

        u_res = await db.execute(select(Usuario).where(Usuario.id == usuario_id))
        u = u_res.scalars().first()
        nom = f"{u.nombre or ''} {u.apellidos or ''}".strip() or u.usuario if u else "Operario"

        return AlmuerzoResponse(
            id=almuerzo.id,
            ciclo_id=almuerzo.ciclo_id,
            usuario_id=almuerzo.usuario_id,
            usuario_nombre=nom,
            hora_salida=almuerzo.hora_salida,
            hora_regreso=almuerzo.hora_regreso,
            duracion_minutos=almuerzo.duracion_minutos,
            estado=almuerzo.estado
        )

    @staticmethod
    async def finalizar_almuerzo(db: AsyncSession, usuario_id: int, terminal_id: int = 1) -> AlmuerzoResponse:
        operador_res = await db.execute(select(Usuario).where(Usuario.id == usuario_id))
        operador = operador_res.scalars().first()
        if not operador or not TurnoService._es_operario(operador):
            raise HTTPException(status_code=403, detail="Solo los operarios tienen control de turnos")
        hoy = date.today()
        stmt = select(CicloTurno).where(CicloTurno.fecha == hoy, CicloTurno.estado == "Abierto")
        ciclo = (await db.execute(stmt)).scalars().first()
        if not ciclo:
            raise HTTPException(status_code=400, detail="No hay un ciclo de turno activo para hoy")

        # Buscar almuerzo en curso
        alm_stmt = select(AlmuerzoTurno).where(
            AlmuerzoTurno.ciclo_id == ciclo.id,
            AlmuerzoTurno.usuario_id == usuario_id,
            AlmuerzoTurno.estado == "En_Curso"
        ).order_by(AlmuerzoTurno.id.desc())
        almuerzo = (await db.execute(alm_stmt)).scalars().first()

        ahora_utc = datetime.now(timezone.utc)

        if not almuerzo:
            raise HTTPException(status_code=400, detail="No se encontró un registro de salida a almuerzo activo para este operario")

        salida_dt = almuerzo.hora_salida
        if salida_dt.tzinfo is None:
            salida_dt = salida_dt.replace(tzinfo=timezone.utc)

        dur_mins = round((ahora_utc - salida_dt).total_seconds() / 60.0, 1)
        almuerzo.hora_regreso = func.now()
        almuerzo.duracion_minutos = max(0.0, dur_mins)
        almuerzo.estado = "Finalizado"

        # Actualizar estado del operario en la cola a DISPONIBLE
        q_stmt = select(ColaTurno).where(
            ColaTurno.ciclo_id == ciclo.id,
            ColaTurno.usuario_id == usuario_id
        ).with_for_update()
        op_item = (await db.execute(q_stmt)).scalars().first()
        if op_item:
            op_item.estado = "DISPONIBLE"

        # Registrar evento
        db.add(EventoTurno(
            ciclo_id=ciclo.id,
            usuario_id=usuario_id,
            autor_id=usuario_id,
            tipo_evento="FIN_ALMUERZO",
            estado_anterior="ALMUERZO",
            estado_nuevo="DISPONIBLE",
            motivo=f"Regreso de almuerzo. Duración total: {dur_mins} minutos",
            terminal_id=terminal_id
        ))

        await db.commit()
        await db.refresh(almuerzo)

        u_res = await db.execute(select(Usuario).where(Usuario.id == usuario_id))
        u = u_res.scalars().first()
        nom = f"{u.nombre or ''} {u.apellidos or ''}".strip() or u.usuario if u else "Operario"

        return AlmuerzoResponse(
            id=almuerzo.id,
            ciclo_id=almuerzo.ciclo_id,
            usuario_id=almuerzo.usuario_id,
            usuario_nombre=nom,
            hora_salida=almuerzo.hora_salida,
            hora_regreso=almuerzo.hora_regreso or ahora_utc,
            duracion_minutos=almuerzo.duracion_minutos,
            estado=almuerzo.estado
        )

    @staticmethod
    async def cambiar_disponibilidad(db: AsyncSession, usuario_id: int, nuevo_estado: str, autor_id: int, motivo: Optional[str] = None, terminal_id: int = 1):
        operador_res = await db.execute(select(Usuario).where(Usuario.id == usuario_id))
        operador = operador_res.scalars().first()
        if not operador or not TurnoService._es_operario(operador):
            raise HTTPException(status_code=403, detail="Solo los operarios tienen control de turnos")
        estados_validos = ["DISPONIBLE", "OCUPADO", "PAUSADO"]
        if nuevo_estado not in estados_validos:
            raise HTTPException(status_code=400, detail=f"Estado inválido. Opciones permitidas: {estados_validos}")

        hoy = date.today()
        ciclo = (await db.execute(select(CicloTurno).where(CicloTurno.fecha == hoy, CicloTurno.estado == "Abierto"))).scalars().first()
        if not ciclo:
            ciclo = await TurnoService.obtener_o_crear_ciclo_hoy(db, autor_id, terminal_id)

        q_stmt = select(ColaTurno).join(Usuario, ColaTurno.usuario_id == Usuario.id).where(
            ColaTurno.ciclo_id == ciclo.id,
            func.lower(Usuario.rol) == "operario"
        ).order_by(ColaTurno.posicion.asc()).with_for_update()
        cola_items = list((await db.execute(q_stmt)).scalars().all())
        TurnoService._normalizar_turno_activo(cola_items)

        op_item = next((c for c in cola_items if c.usuario_id == usuario_id), None)
        if not op_item:
            raise HTTPException(status_code=404, detail="Operario no encontrado en la cola")

        est_anterior = op_item.estado
        if est_anterior == nuevo_estado:
            return {"message": f"El operario ya está en estado {nuevo_estado}"}

        # Si estaba EN_TURNO y pasa a OCUPADO o PAUSADO, avanzar el turno al siguiente DISPONIBLE
        if est_anterior == "EN_TURNO" and nuevo_estado in ["OCUPADO", "PAUSADO"]:
            op_item.en_turno_desde = None
            total_ops = len(cola_items)
            for offset in range(1, total_ops + 1):
                cand_pos = ((op_item.posicion - 1 + offset) % total_ops) + 1
                cand = next((c for c in cola_items if c.posicion == cand_pos), None)
                if cand and cand.id != op_item.id and cand.estado == "DISPONIBLE":
                    cand.estado = "EN_TURNO"
                    cand.en_turno_desde = func.now()
                    break

        # Al liberar a un operario ocupado, darle el turno inmediatamente.
        # Guardamos quién estaba atendiendo para reanudar la cola después de
        # que el operario liberado complete su atención.
        if est_anterior == "OCUPADO" and nuevo_estado == "DISPONIBLE":
            turno_actual = next((c for c in cola_items if c.estado == "EN_TURNO" and c.id != op_item.id), None)
            if turno_actual:
                op_item.turno_retorno_posicion = turno_actual.posicion
                turno_actual.estado = "DISPONIBLE"
                turno_actual.en_turno_desde = None
            op_item.estado = "EN_TURNO"
            op_item.en_turno_desde = func.now()

        if not (est_anterior == "OCUPADO" and nuevo_estado == "DISPONIBLE"):
            op_item.estado = nuevo_estado

        db.add(EventoTurno(
            ciclo_id=ciclo.id,
            usuario_id=usuario_id,
            autor_id=autor_id,
            tipo_evento="CAMBIO_ESTADO",
            posicion_anterior=op_item.posicion,
            posicion_nueva=op_item.posicion,
            estado_anterior=est_anterior,
            estado_nuevo=nuevo_estado,
            motivo=motivo or f"Cambio de disponibilidad a {nuevo_estado}",
            terminal_id=terminal_id
        ))

        await db.commit()
        return {"message": f"Estado actualizado exitosamente a {nuevo_estado}"}

    @staticmethod
    async def saltar_turno(db: AsyncSession, usuario_id: Optional[int], autor_id: int, motivo: str, terminal_id: int = 1):
        if not motivo or len(motivo.strip()) < 5:
            raise HTTPException(status_code=400, detail="El motivo del salto es obligatorio (mínimo 5 caracteres)")

        hoy = date.today()
        ciclo = (await db.execute(select(CicloTurno).where(CicloTurno.fecha == hoy, CicloTurno.estado == "Abierto"))).scalars().first()
        if not ciclo:
            raise HTTPException(status_code=400, detail="No hay un ciclo de turno activo para hoy")

        q_stmt = select(ColaTurno).join(Usuario, ColaTurno.usuario_id == Usuario.id).where(
            ColaTurno.ciclo_id == ciclo.id,
            func.lower(Usuario.rol) == "operario"
        ).order_by(ColaTurno.posicion.asc()).with_for_update()
        cola_items = list((await db.execute(q_stmt)).scalars().all())
        TurnoService._normalizar_turno_activo(cola_items)

        if usuario_id:
            op_item = next((c for c in cola_items if c.usuario_id == usuario_id), None)
        else:
            op_item = next((c for c in cola_items if c.estado == "EN_TURNO"), None)

        if not op_item:
            raise HTTPException(status_code=404, detail="No se encontró el operario en turno para saltar")

        est_anterior = op_item.estado
        op_item.estado = "DISPONIBLE"
        op_item.en_turno_desde = None

        # Avanzar al siguiente operario disponible
        total_ops = len(cola_items)
        siguiente_op = None
        for offset in range(1, total_ops + 1):
            cand_pos = ((op_item.posicion - 1 + offset) % total_ops) + 1
            cand = next((c for c in cola_items if c.posicion == cand_pos), None)
            if cand and cand.id != op_item.id and cand.estado not in ["ALMUERZO", "PAUSADO"]:
                siguiente_op = cand
                break

        if siguiente_op:
            siguiente_op.estado = "EN_TURNO"
            siguiente_op.en_turno_desde = func.now()

        db.add(EventoTurno(
            ciclo_id=ciclo.id,
            usuario_id=op_item.usuario_id,
            autor_id=autor_id,
            tipo_evento="SALTO_TURNO",
            posicion_anterior=op_item.posicion,
            posicion_nueva=siguiente_op.posicion if siguiente_op else None,
            estado_anterior=est_anterior,
            estado_nuevo="SALTADO",
            motivo=motivo.strip(),
            terminal_id=terminal_id
        ))

        await db.commit()
        return {"message": "Turno saltado exitosamente", "operario_saltado": op_item.usuario_id, "siguiente_operario": siguiente_op.usuario_id if siguiente_op else None}

    @staticmethod
    async def reubicar_operario(db: AsyncSession, usuario_id: int, nueva_posicion: int, autor_id: int, motivo: str, terminal_id: int = 1):
        if not motivo or len(motivo.strip()) < 5:
            raise HTTPException(status_code=400, detail="El motivo de la reubicación es obligatorio (mínimo 5 caracteres)")

        hoy = date.today()
        ciclo = (await db.execute(select(CicloTurno).where(CicloTurno.fecha == hoy, CicloTurno.estado == "Abierto"))).scalars().first()
        if not ciclo:
            raise HTTPException(status_code=400, detail="No hay un ciclo de turno activo para hoy")

        q_stmt = select(ColaTurno).join(Usuario, ColaTurno.usuario_id == Usuario.id).where(
            ColaTurno.ciclo_id == ciclo.id,
            func.lower(Usuario.rol) == "operario"
        ).order_by(ColaTurno.posicion.asc()).with_for_update()
        cola_items = list((await db.execute(q_stmt)).scalars().all())
        TurnoService._normalizar_turno_activo(cola_items)

        total = len(cola_items)
        if nueva_posicion < 1 or nueva_posicion > total:
            raise HTTPException(status_code=400, detail=f"Posición inválida. Debe estar entre 1 y {total}")

        target = next((c for c in cola_items if c.usuario_id == usuario_id), None)
        if not target:
            raise HTTPException(status_code=404, detail="Operario no encontrado en la cola")

        pos_anterior = target.posicion
        if pos_anterior == nueva_posicion:
            return {"message": "El operario ya ocupa esa posición"}

        cola_items.remove(target)
        cola_items.insert(nueva_posicion - 1, target)

        for idx, item in enumerate(cola_items, start=1):
            item.posicion = idx

        db.add(EventoTurno(
            ciclo_id=ciclo.id,
            usuario_id=usuario_id,
            autor_id=autor_id,
            tipo_evento="REUBICACION",
            posicion_anterior=pos_anterior,
            posicion_nueva=nueva_posicion,
            estado_anterior=target.estado,
            estado_nuevo=target.estado,
            motivo=motivo.strip(),
            terminal_id=terminal_id
        ))

        await db.commit()
        return {"message": f"Operario reubicado exitosamente a la posición {nueva_posicion}"}

    @staticmethod
    async def asignar_turno_manual(db: AsyncSession, usuario_id: int, autor_id: int, motivo: str, terminal_id: int = 1):
        if not motivo or len(motivo.strip()) < 5:
            raise HTTPException(status_code=400, detail="El motivo de asignación manual es obligatorio (mínimo 5 caracteres)")

        hoy = date.today()
        ciclo = (await db.execute(select(CicloTurno).where(CicloTurno.fecha == hoy, CicloTurno.estado == "Abierto"))).scalars().first()
        if not ciclo:
            raise HTTPException(status_code=400, detail="No hay un ciclo de turno activo para hoy")

        q_stmt = select(ColaTurno).join(Usuario, ColaTurno.usuario_id == Usuario.id).where(
            ColaTurno.ciclo_id == ciclo.id,
            func.lower(Usuario.rol) == "operario"
        ).with_for_update()
        cola_items = list((await db.execute(q_stmt)).scalars().all())
        TurnoService._normalizar_turno_activo(cola_items)

        target = next((c for c in cola_items if c.usuario_id == usuario_id), None)
        if not target:
            raise HTTPException(status_code=404, detail="Operario no encontrado en la cola")

        if target.estado == "ALMUERZO":
            raise HTTPException(status_code=400, detail="No se puede asignar turno manual a un operario en horario de almuerzo")

        # Quitar EN_TURNO a quien lo tuviera actualmente
        for c in cola_items:
            if c.estado == "EN_TURNO" and c.id != target.id:
                c.estado = "DISPONIBLE"
                c.en_turno_desde = None

        est_anterior = target.estado
        target.estado = "EN_TURNO"
        target.en_turno_desde = func.now()

        db.add(EventoTurno(
            ciclo_id=ciclo.id,
            usuario_id=usuario_id,
            autor_id=autor_id,
            tipo_evento="ASIGNACION_MANUAL",
            posicion_anterior=target.posicion,
            posicion_nueva=target.posicion,
            estado_anterior=est_anterior,
            estado_nuevo="EN_TURNO",
            motivo=motivo.strip(),
            terminal_id=terminal_id
        ))

        await db.commit()
        return {"message": "Turno asignado manualmente exitosamente"}

    @staticmethod
    async def obtener_historial_eventos(db: AsyncSession, ciclo_id: Optional[int] = None, fecha: Optional[date] = None) -> List[EventoTurnoResponse]:
        filtro_ciclo = ciclo_id
        if not filtro_ciclo:
            fec = fecha or date.today()
            c_res = await db.execute(select(CicloTurno.id).where(CicloTurno.fecha == fec))
            filtro_ciclo = c_res.scalars().first()

        if not filtro_ciclo:
            return []

        e_res = await db.execute(
            select(EventoTurno).where(EventoTurno.ciclo_id == filtro_ciclo).order_by(EventoTurno.created_at.desc())
        )
        eventos = list(e_res.scalars().all())

        u_res = await db.execute(select(Usuario))
        users_map = {u.id: (f"{u.nombre or ''} {u.apellidos or ''}".strip() or u.usuario) for u in u_res.scalars().all()}

        res: List[EventoTurnoResponse] = []
        for ev in eventos:
            res.append(EventoTurnoResponse(
                id=ev.id,
                ciclo_id=ev.ciclo_id,
                usuario_id=ev.usuario_id,
                usuario_nombre=users_map.get(ev.usuario_id),
                autor_id=ev.autor_id,
                autor_nombre=users_map.get(ev.autor_id, "Sistema"),
                tipo_evento=ev.tipo_evento,
                posicion_anterior=ev.posicion_anterior,
                posicion_nueva=ev.posicion_nueva,
                estado_anterior=ev.estado_anterior,
                estado_nuevo=ev.estado_nuevo,
                motivo=ev.motivo,
                created_at=ev.created_at
            ))
        return res

    @staticmethod
    async def obtener_resumen_dia(db: AsyncSession, ciclo_id: Optional[int] = None, fecha: Optional[date] = None) -> ResumenDiaResponse:
        fec = fecha or date.today()
        if ciclo_id:
            c_res = await db.execute(select(CicloTurno).where(CicloTurno.id == ciclo_id))
        else:
            c_res = await db.execute(select(CicloTurno).where(CicloTurno.fecha == fec).order_by(CicloTurno.id.desc()))
        ciclo = c_res.scalars().first()

        if not ciclo:
            return ResumenDiaResponse(
                ciclo_id=0,
                fecha=fec,
                estado_ciclo="Inexistente",
                total_atenciones=0,
                total_normales=0,
                total_especiales=0,
                total_saltados=0,
                operarios=[]
            )

        # Cargar cola de usuarios del ciclo
        q_res = await db.execute(
            select(ColaTurno, Usuario).join(Usuario, ColaTurno.usuario_id == Usuario.id).where(
                ColaTurno.ciclo_id == ciclo.id,
                func.lower(Usuario.rol) == "operario"
            ).order_by(ColaTurno.posicion.asc())
        )
        ops_filas = q_res.all()

        tot_norm_dia = 0
        tot_esp_dia = 0
        tot_saltos_dia = 0
        ops_dto: List[ResumenOperarioDia] = []

        for cola, user in ops_filas:
            nom = f"{user.nombre or ''} {user.apellidos or ''}".strip() or user.usuario

            # Atenciones normales y especiales
            n_res = await db.execute(
                select(func.count(AtencionTurno.id)).where(
                    AtencionTurno.ciclo_id == ciclo.id,
                    AtencionTurno.usuario_id == user.id,
                    AtencionTurno.tipo_turno == "NORMAL"
                )
            )
            c_norm = n_res.scalar() or 0

            e_res = await db.execute(
                select(func.count(AtencionTurno.id)).where(
                    AtencionTurno.ciclo_id == ciclo.id,
                    AtencionTurno.usuario_id == user.id,
                    AtencionTurno.tipo_turno == "ESPECIAL"
                )
            )
            c_esp = e_res.scalar() or 0

            # Saltos
            s_res = await db.execute(
                select(func.count(EventoTurno.id)).where(
                    EventoTurno.ciclo_id == ciclo.id,
                    EventoTurno.usuario_id == user.id,
                    EventoTurno.tipo_evento == "SALTO_TURNO"
                )
            )
            c_salt = s_res.scalar() or 0

            # Almuerzos
            alm_res = await db.execute(
                select(AlmuerzoTurno).where(
                    AlmuerzoTurno.ciclo_id == ciclo.id,
                    AlmuerzoTurno.usuario_id == user.id
                )
            )
            alms = list(alm_res.scalars().all())
            cant_alms = len(alms)
            mins_alm = sum(a.duracion_minutos or 0.0 for a in alms)

            tot_user = c_norm + c_esp
            tot_norm_dia += c_norm
            tot_esp_dia += c_esp
            tot_saltos_dia += c_salt

            ops_dto.append(ResumenOperarioDia(
                usuario_id=user.id,
                usuario_nombre=nom,
                posicion_actual=cola.posicion,
                estado_actual=cola.estado,
                normales=c_norm,
                especiales=c_esp,
                saltados=c_salt,
                almuerzos=cant_alms,
                minutos_almuerzo=round(mins_alm, 1),
                total_atendidos=tot_user,
                ultima_atencion=cola.ultima_atencion
            ))

        return ResumenDiaResponse(
            ciclo_id=ciclo.id,
            fecha=ciclo.fecha,
            estado_ciclo=ciclo.estado,
            total_atenciones=tot_norm_dia + tot_esp_dia,
            total_normales=tot_norm_dia,
            total_especiales=tot_esp_dia,
            total_saltados=tot_saltos_dia,
            operarios=ops_dto
        )

    @staticmethod
    async def cerrar_ciclo(db: AsyncSession, autor_id: int, terminal_id: int = 1):
        hoy = date.today()
        ciclo = (await db.execute(select(CicloTurno).where(CicloTurno.fecha == hoy, CicloTurno.estado == "Abierto"))).scalars().first()
        if not ciclo:
            raise HTTPException(status_code=400, detail="No hay un ciclo de turno abierto para cerrar hoy")

        ciclo.estado = "Cerrado"
        ciclo.cerrado_por = autor_id
        ciclo.closed_at = func.now()

        # Poner todos los operarios en FUERA_DE_TURNO
        await db.execute(
            update(ColaTurno).where(ColaTurno.ciclo_id == ciclo.id).values(
                estado="FUERA_DE_TURNO",
                en_turno_desde=None
            )
        )

        db.add(EventoTurno(
            ciclo_id=ciclo.id,
            autor_id=autor_id,
            tipo_evento="CIERRE_CICLO",
            estado_anterior="Abierto",
            estado_nuevo="Cerrado",
            motivo="Cierre formal de jornada comercial y consolidación de turnos",
            terminal_id=terminal_id
        ))

        await db.commit()
        return {"message": "Ciclo de turno cerrado exitosamente"}
