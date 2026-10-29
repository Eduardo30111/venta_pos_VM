from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from datetime import datetime, date
from sqlalchemy import func
from ..database import get_db
from ..models.nomina import Comision, Asistencia, Liquidacion
from ..models.finanzas import Gasto, CuentaPorPagar
from ..models.proveedor import Proveedor
from ..models.usuario import Usuario
from ..models.venta import Venta, DetalleVenta
from ..schemas.nomina import ComisionResponse, AsistenciaCreate, AsistenciaResponse, LiquidacionCreate, LiquidacionResponse
from ..middleware.auth import get_current_user

router = APIRouter(prefix="/nomina", tags=["nomina"])

@router.get("/mi-recaudo")
async def get_mi_recaudo(db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Obtiene el recaudo pendiente (comisiones), ventas del día y acumulado del mes del usuario logueado"""
    # 1. Comisiones pendientes acumuladas (Historial total para Nómina)
    com_result = await db.execute(
        select(func.coalesce(func.sum(Comision.monto_comision), 0.0))
        .where(Comision.usuario_id == current_user.id, Comision.estado == 'Pendiente')
    )
    total_recaudo = com_result.scalar() or 0.0
    
    # 2. Recaudo diario (Solo comisiones de HOY de ventas completadas, se reinicia cada medianoche)
    today_start = datetime.combine(date.today(), datetime.min.time())
    com_diario_result = await db.execute(
        select(func.coalesce(func.sum(Comision.monto_comision), 0.0))
        .join(Venta, Comision.venta_id == Venta.id)
        .where(
            Comision.usuario_id == current_user.id,
            Comision.estado == 'Pendiente',
            Venta.estado == 'Completada',
            Venta.created_at >= today_start
        )
    )
    recaudo_diario = float(com_diario_result.scalar() or 0.0)

    # 3. Ventas hoy
    ventas_result = await db.execute(
        select(func.count(Venta.id))
        .where(Venta.usuario_id == current_user.id, Venta.created_at >= today_start, Venta.estado == 'Completada')
    )
    ventas_hoy = ventas_result.scalar() or 0
    
    # 4. Total liquidado este mes
    first_day_month = datetime(date.today().year, date.today().month, 1)
    liq_result = await db.execute(
        select(func.coalesce(func.sum(Liquidacion.total_liquidado), 0.0))
        .where(Liquidacion.usuario_id == current_user.id, Liquidacion.created_at >= first_day_month, Liquidacion.estado == 'Liquidado')
    )
    total_mes = liq_result.scalar() or 0.0
    
    return {
        "recaudo_diario": recaudo_diario,
        "recaudo_pendiente": float(total_recaudo),
        "ventas_hoy": int(ventas_hoy),
        "total_mes": float(total_mes),
        "porcentaje_comision": float(current_user.porcentaje_comision or 0.0),
        "tipo_remuneracion": current_user.tipo_remuneracion,
        "usuario": current_user.usuario
    }

@router.post("/solicitar-liquidacion")
async def solicitar_liquidacion(db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """El empleado solicita su liquidación al administrador"""
    com_result = await db.execute(
        select(func.coalesce(func.sum(Comision.monto_comision), 0.0))
        .where(Comision.usuario_id == current_user.id, Comision.estado == 'Pendiente')
    )
    total_com = float(com_result.scalar() or 0.0)

    current_user.solicitud_liquidacion = datetime.now()
    await db.commit()
    await db.refresh(current_user)

    return {
        "ok": True,
        "message": "Solicitud de liquidación registrada con éxito",
        "usuario": current_user.usuario,
        "comisiones_pendientes": total_com,
        "solicitud_liquidacion": current_user.solicitud_liquidacion.isoformat() if current_user.solicitud_liquidacion else None
    }

@router.get("/solicitudes-pendientes")
async def get_solicitudes_pendientes(db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Obtiene las solicitudes de liquidación activas para visualización del administrador"""
    result = await db.execute(
        select(Usuario).where(Usuario.rol != 'Administrador', Usuario.solicitud_liquidacion.isnot(None))
    )
    usuarios = result.scalars().all()
    ahora = datetime.now()

    solicitudes = []
    for u in usuarios:
        diff_seg = (ahora.astimezone() - u.solicitud_liquidacion).total_seconds() if (u.solicitud_liquidacion and u.solicitud_liquidacion.tzinfo) else ((ahora - u.solicitud_liquidacion).total_seconds() if u.solicitud_liquidacion else 99999)

        com_res = await db.execute(
            select(func.coalesce(func.sum(Comision.monto_comision), 0.0))
            .where(Comision.usuario_id == u.id, Comision.estado == 'Pendiente')
        )
        total_com = float(com_res.scalar() or 0.0)
        nombre_completo = f"{u.nombre or ''} {u.apellidos or ''}".strip() or u.usuario

        # Activa si se solicitó hace menos de 10 minutos (600s)
        activa = diff_seg <= 600

        solicitudes.append({
            "usuario_id": u.id,
            "usuario": u.usuario,
            "nombre_completo": nombre_completo,
            "rol": u.rol,
            "tipo_remuneracion": u.tipo_remuneracion or "Porcentual",
            "comisiones_pendientes": total_com,
            "solicitud_liquidacion": u.solicitud_liquidacion.isoformat() if u.solicitud_liquidacion else None,
            "segundos_transcurridos": int(diff_seg),
            "activa": activa
        })

    return solicitudes

@router.get("/empleados")
async def list_empleados(db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Usuario).where(Usuario.rol != 'Administrador'))
    usuarios = result.scalars().all()
    ahora = datetime.now()

    empleados_list = []
    for u in usuarios:
        com_res = await db.execute(
            select(func.coalesce(func.sum(Comision.monto_comision), 0.0))
            .where(Comision.usuario_id == u.id, Comision.estado == 'Pendiente')
        )
        total_com = float(com_res.scalar() or 0.0)

        sol_activa = False
        segundos = None
        estado_solicitud = "No solicitada"
        if u.solicitud_liquidacion:
            diff_seg = (ahora.astimezone() - u.solicitud_liquidacion).total_seconds() if u.solicitud_liquidacion.tzinfo else (ahora - u.solicitud_liquidacion).total_seconds()
            segundos = int(diff_seg)
            if diff_seg <= 300:
                sol_activa = True
                estado_solicitud = f"🟢 Solicitada (hace {int(diff_seg)}s)"
            else:
                estado_solicitud = f"🟡 Expirada (hace {int(diff_seg//60)}m)"

        nombre_comp = f"{u.nombre or ''} {u.apellidos or ''}".strip() or u.usuario

        empleados_list.append({
            "id": u.id,
            "usuario": u.usuario,
            "nombre": u.nombre,
            "apellidos": u.apellidos,
            "nombre_completo": nombre_comp,
            "rol": u.rol,
            "tipo_remuneracion": u.tipo_remuneracion or "Porcentual",
            "tipo_nomina": u.tipo_remuneracion or "Porcentual",
            "porcentaje_comision": u.porcentaje_comision or 0.0,
            "salario_diario": u.salario_diario or 0.0,
            "comisiones_acumuladas": total_com,
            "solicitud_liquidacion": u.solicitud_liquidacion.isoformat() if u.solicitud_liquidacion else None,
            "solicitud_activa": sol_activa,
            "solicitud_segundos": segundos,
            "estado_solicitud": estado_solicitud
        })

    return empleados_list

@router.get("/empleados/{id}/comisiones", response_model=List[ComisionResponse])
async def get_comisiones(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Comision).where(Comision.usuario_id == id, Comision.estado == 'Pendiente'))
    return result.scalars().all()

@router.post("/asistencia", response_model=AsistenciaResponse)
async def register_asistencia(asistencia: AsistenciaCreate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    user_result = await db.execute(select(Usuario).where(Usuario.id == asistencia.usuario_id))
    user = user_result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    from sqlalchemy import cast, Date
    fecha_dt = datetime.strptime(asistencia.fecha, "%Y-%m-%d")
    es_vendedor = str(user.rol or "").strip().lower() in ("vendedor", "vendedora")

    # Fase 3: El vendedor solo genera su salario diario cuando procesa su primera venta válida del día
    tiene_venta_valida = True
    if es_vendedor:
        v_res = await db.execute(
            select(func.count(Venta.id)).where(
                Venta.usuario_id == user.id,
                cast(Venta.created_at, Date) == fecha_dt.date(),
                Venta.estado == 'Completada'
            )
        )
        tiene_venta_valida = (v_res.scalar() or 0) > 0

    estado_final = asistencia.estado
    if es_vendedor and asistencia.estado == 'Presente' and not tiene_venta_valida:
        estado_final = 'Asistencia Marcada (Sin Venta)'
        salario_generado = 0.0
    else:
        salario_generado = (
            float(user.salario_diario or 0.0)
            if user.tipo_remuneracion in ('Fija', 'Mixta') and estado_final == 'Presente'
            else 0.0
        )

    res_exist = await db.execute(
        select(Asistencia).where(
            Asistencia.usuario_id == user.id,
            cast(Asistencia.fecha, Date) == fecha_dt.date()
        )
    )
    db_asist = res_exist.scalars().first()
    if db_asist:
        if db_asist.estado != estado_final or (salario_generado > 0 and float(db_asist.salario_generado or 0.0) == 0.0):
            db_asist.estado = estado_final
            db_asist.salario_generado = salario_generado
            await db.commit()
            await db.refresh(db_asist)
        return db_asist
    
    db_asist = Asistencia(
        usuario_id=user.id,
        fecha=fecha_dt,
        estado=estado_final,
        registrado_por=current_user.id,
        salario_generado=salario_generado
    )
    db.add(db_asist)
    await db.commit()
    await db.refresh(db_asist)
    return db_asist

@router.get("/asistencia", response_model=List[AsistenciaResponse])
async def get_asistencias(fecha: str, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    fecha_dt = datetime.strptime(fecha, "%Y-%m-%d")
    from sqlalchemy import cast, Date
    result = await db.execute(select(Asistencia).where(cast(Asistencia.fecha, Date) == fecha_dt.date()))
    return result.scalars().all()

@router.post("/liquidaciones", response_model=LiquidacionResponse)
async def create_liquidacion(liq: LiquidacionCreate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    try:
        p_inicio = liq.periodo_inicio or datetime(2000, 1, 1)
        p_fin = liq.periodo_fin or datetime.now()

        # 1. Comisiones pendientes
        com_result = await db.execute(select(Comision).with_for_update().where(Comision.usuario_id == liq.usuario_id, Comision.estado == 'Pendiente'))
        comisiones = com_result.scalars().all()
        total_com = sum(c.monto_comision for c in comisiones)
        
        # 2. Asistencias pendientes
        asi_result = await db.execute(select(Asistencia).where(Asistencia.usuario_id == liq.usuario_id, Asistencia.fecha >= p_inicio, Asistencia.fecha <= p_fin, Asistencia.salario_generado > 0))
        asistencias = asi_result.scalars().all()
        total_sal = sum(a.salario_generado for a in asistencias)
        
        # 3. Liquidacion
        liquidacion = Liquidacion(
            usuario_id=liq.usuario_id,
            periodo_inicio=p_inicio,
            periodo_fin=p_fin,
            total_servicios_vendidos=len(comisiones),
            total_comisiones=total_com,
            total_salario_fijo=total_sal,
            total_liquidado=total_com + total_sal,
            estado="Liquidado",
            liquidado_por=current_user.id,
            observaciones=liq.observaciones
        )
        db.add(liquidacion)
        await db.flush()
        
        # 4. Actualizar comisiones a Liquidada
        for c in comisiones:
            c.estado = 'Liquidada'
            c.liquidacion_id = liquidacion.id
            
        # 5. Limpiar solicitud de liquidación del usuario
        usr_res = await db.execute(select(Usuario).where(Usuario.id == liq.usuario_id))
        target_user = usr_res.scalars().first()
        nombre_emp = f"Usuario {liq.usuario_id}"
        if target_user:
            target_user.solicitud_liquidacion = None
            nombre_emp = f"{target_user.nombre or ''} {target_user.apellidos or ''}".strip() or target_user.usuario

        # 6. Gasto contable automático
        gasto = Gasto(
            concepto=f"Liquidación Nómina - {nombre_emp}",
            categoria="Nomina",
            valor=liquidacion.total_liquidado,
            tipo="Liquidacion_Nomina",
            referencia_id=liquidacion.id,
            usuario_id=current_user.id
        )
        db.add(gasto)
        
        await db.commit()
        await db.refresh(liquidacion)
        
        # Campos de conveniencia
        liquidacion.nombre_persona = nombre_emp
        liquidacion.monto = liquidacion.total_liquidado
        liquidacion.fecha = liquidacion.created_at.strftime("%Y-%m-%d %H:%M") if liquidacion.created_at else ""
        liquidacion.mes_anio = liquidacion.created_at.strftime("%m-%Y") if liquidacion.created_at else ""
        return liquidacion
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/liquidaciones", response_model=List[LiquidacionResponse])
async def list_liquidaciones(db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    query = select(Liquidacion)
    if current_user.rol != 'Administrador':
        query = query.where(Liquidacion.usuario_id == current_user.id)
    result = await db.execute(query.order_by(Liquidacion.id.desc()))
    liqs = result.scalars().all()

    users_res = await db.execute(select(Usuario))
    users_map = {u.id: (f"{u.nombre or ''} {u.apellidos or ''}".strip() or u.usuario) for u in users_res.scalars().all()}

    for l in liqs:
        l.nombre_persona = users_map.get(l.usuario_id, f"Usuario {l.usuario_id}")
        l.monto = l.total_liquidado
        l.fecha = l.created_at.strftime("%Y-%m-%d %H:%M") if l.created_at else ""
        l.mes_anio = l.created_at.strftime("%m-%Y") if l.created_at else ""

    return liqs

@router.get("/mis-comisiones")
async def get_mis_comisiones(db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Retorna las comisiones pendientes del usuario logueado con detalles de venta e ítem"""
    result = await db.execute(
        select(Comision, Venta.numero, DetalleVenta.item_nombre, DetalleVenta.tipo_item)
        .join(Venta, Comision.venta_id == Venta.id)
        .outerjoin(DetalleVenta, Comision.detalle_venta_id == DetalleVenta.id)
        .where(Comision.usuario_id == current_user.id, Comision.estado == 'Pendiente')
        .order_by(Comision.id.desc())
    )
    rows = result.all()
    comisiones = []
    for c, venta_num, item_nom, tipo_it in rows:
        comisiones.append({
            "id": c.id,
            "venta_numero": venta_num or f"V-{c.venta_id}",
            "fecha": c.created_at.strftime("%Y-%m-%d %H:%M") if c.created_at else "",
            "tipo_item": tipo_it or ("Servicio" if c.servicio_id else "Producto"),
            "item_nombre": item_nom or ("Servicio" if c.servicio_id else "Producto"),
            "valor_venta": float(c.valor_servicio or 0.0),
            "utilidad": float(c.utilidad or 0.0),
            "porcentaje": float(c.porcentaje or 0.0),
            "monto_comision": float(c.monto_comision or 0.0),
            "estado": c.estado
        })
    return comisiones

@router.get("/liquidaciones/{id}", response_model=LiquidacionResponse)
async def get_liquidacion(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Liquidacion).where(Liquidacion.id == id))
    liq = result.scalars().first()
    if not liq:
        raise HTTPException(status_code=404, detail="Liquidación no encontrada")
    usr = await db.execute(select(Usuario).where(Usuario.id == liq.usuario_id))
    u = usr.scalars().first()
    liq.nombre_persona = (f"{u.nombre or ''} {u.apellidos or ''}".strip() or u.usuario) if u else f"Usuario {liq.usuario_id}"
    liq.monto = liq.total_liquidado
    liq.fecha = liq.created_at.strftime("%Y-%m-%d %H:%M") if liq.created_at else ""
    liq.mes_anio = liq.created_at.strftime("%m-%Y") if liq.created_at else ""
    return liq

@router.get("/proveedores")
async def list_proveedores_nomina(db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Obtiene los proveedores y sus saldos pendientes por pagar generados por ventas de productos y servicios"""
    res = await db.execute(select(Proveedor).order_by(Proveedor.id.asc()))
    proveedores = res.scalars().all()
    
    resultado = []
    for p in proveedores:
        cxp_res = await db.execute(
            select(func.coalesce(func.sum(CuentaPorPagar.monto), 0.0))
            .where(CuentaPorPagar.proveedor_id == p.id, CuentaPorPagar.estado == 'Pendiente')
        )
        saldo_pendiente = float(cxp_res.scalar() or 0.0)
        resultado.append({
            "id": p.id,
            "nombre": p.nombre,
            "documento_nit": p.documento_nit,
            "telefono": p.telefono or "",
            "saldo_acumulado": saldo_pendiente,
            "saldo_pendiente": saldo_pendiente
        })
    return resultado

@router.get("/proveedores/historial")
async def list_historial_proveedores(mes_anio: Optional[str] = None, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Obtiene el historial de liquidaciones / pagos realizados a proveedores a través de Gastos de tipo 'Pago_Proveedor'"""
    query = select(Gasto).where(Gasto.tipo == 'Pago_Proveedor').order_by(Gasto.id.desc())
    res = await db.execute(query)
    gastos = res.scalars().all()
    
    historial = []
    for g in gastos:
        fecha_str = g.created_at.strftime("%Y-%m-%d %H:%M") if g.created_at else ""
        mes_str = g.created_at.strftime("%m-%Y") if g.created_at else ""
        if mes_anio and mes_anio != "Todos" and mes_str != mes_anio:
            continue
        
        nombre_prov = g.concepto.replace("Pago a Proveedor - ", "").strip()
        historial.append({
            "id": g.id,
            "id_liquidacion": g.id,
            "persona_id": g.referencia_id,
            "nombre_persona": nombre_prov,
            "monto": float(g.valor),
            "fecha": fecha_str,
            "mes_anio": mes_str,
            "concepto": g.concepto
        })
    return historial

@router.post("/proveedores/{id}/liquidar")
async def liquidar_proveedor(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Liquida las cuentas por pagar pendientes de un proveedor y genera el gasto contable"""
    prov_res = await db.execute(select(Proveedor).where(Proveedor.id == id))
    prov = prov_res.scalars().first()
    if not prov:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
        
    cxp_res = await db.execute(
        select(CuentaPorPagar).with_for_update().where(
            CuentaPorPagar.proveedor_id == id,
            CuentaPorPagar.estado == 'Pendiente'
        )
    )
    cuentas_pendientes = cxp_res.scalars().all()
    if not cuentas_pendientes:
        raise HTTPException(status_code=400, detail=f"El proveedor '{prov.nombre}' no tiene deudas pendientes por liquidar.")
        
    total_pagar = sum(float(c.monto) for c in cuentas_pendientes)
    
    for c in cuentas_pendientes:
        c.estado = 'Pagada'
        
    gasto = Gasto(
        concepto=f"Pago a Proveedor - {prov.nombre}",
        categoria="Proveedores",
        valor=total_pagar,
        tipo="Pago_Proveedor",
        referencia_id=prov.id,
        usuario_id=current_user.id,
        observacion=f"Liquidación de {len(cuentas_pendientes)} cuentas por pagar acumuladas"
    )
    db.add(gasto)
    
    await db.commit()
    await db.refresh(gasto)
    
    return {
        "ok": True,
        "message": f"Se liquidaron {len(cuentas_pendientes)} cuentas con éxito",
        "proveedor": prov.nombre,
        "total_pagado": total_pagar,
        "gasto_id": gasto.id
    }

