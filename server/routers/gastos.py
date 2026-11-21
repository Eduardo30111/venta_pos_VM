import asyncio
from datetime import datetime
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from typing import List, Optional, Dict, Any

from ..database import get_db
from ..models.finanzas import Gasto, GastoRecurrente
from ..models.caja import MovimientoFinanciero
from ..schemas.gasto import (
    GastoCreate,
    GastoUpdate,
    GastoResponse,
    PagarGastoRequest,
    GastoRecurrenteCreate,
)
from ..services.caja_service import CajaService
from ..middleware.auth import get_current_user, require_admin
from ..middleware.audit import log_audit
from ..models.usuario import Usuario
from ..models.caja import SesionCaja
from ..async_lock import LazyAsyncLock

router = APIRouter(prefix="/gastos", tags=["gastos"])

_GASTO_LOCK = LazyAsyncLock()


def _normalizar_metodo_gasto(metodo: str) -> str:
    m = (metodo or "Efectivo").strip().lower()
    if m in ("efectivo", "cash"):
        return "Efectivo"
    if m in ("transferencia", "nequi", "daviplata", "bancolombia", "banco", "qr"):
        return "Transferencia"
    raise HTTPException(status_code=400, detail="El medio de pago debe ser Efectivo o Transferencia")


@router.get("", response_model=List[GastoResponse])
async def list_gastos(
    fecha_inicio: Optional[str] = Query(None),
    fecha_fin: Optional[str] = Query(None),
    estado: Optional[str] = Query(None),
    categoria: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    query = select(Gasto)
    f_col = func.coalesce(Gasto.fecha, func.date(Gasto.created_at))
    if fecha_inicio:
        query = query.where(f_col >= fecha_inicio)
    if fecha_fin:
        query = query.where(f_col <= fecha_fin)
    if estado and estado not in ("Todos", "Todas"):
        query = query.where(Gasto.estado == estado)
    if categoria and categoria not in ("Todas", "Todos"):
        query = query.where(Gasto.categoria == categoria)

    query = query.order_by(Gasto.id.desc())
    result = await db.execute(query)
    items = result.scalars().all()
    for g in items:
        if not g.fecha and g.created_at:
            g.fecha = g.created_at.strftime("%Y-%m-%d")
        if not g.hora and g.created_at:
            g.hora = g.created_at.strftime("%H:%M:%S")
    return items


@router.post("", response_model=GastoResponse)
async def create_gasto(
    gasto: GastoCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    if float(gasto.valor or 0.0) <= 0:
        raise HTTPException(status_code=400, detail="El valor del gasto debe ser mayor a cero")

    # Idempotencia estricta para evitar pagos de gastos duplicados ante reintentos
    idem_clean = (getattr(gasto, "idempotency_key", None) or "").strip() or None
    async with _GASTO_LOCK:
        try:
            if idem_clean:
                res_g = await db.execute(select(Gasto).where(Gasto.idempotency_key == idem_clean))
                gasto_existente = res_g.scalars().first()
                if gasto_existente:
                    gasto_existente.repetido = True
                    return gasto_existente

            metodo = _normalizar_metodo_gasto(gasto.metodo_pago)
            ahora = datetime.now()
            f_str = gasto.fecha or ahora.strftime("%Y-%m-%d")
            h_str = gasto.hora or ahora.strftime("%H:%M:%S")
            estado = gasto.estado or "Pagado"
            u_nom = f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario

            datos = gasto.model_dump()
            datos["metodo_pago"] = metodo
            datos["fecha"] = f_str
            datos["hora"] = h_str
            datos["estado"] = estado
            datos["idempotency_key"] = idem_clean
            datos["clasificacion"] = datos.get("clasificacion") or datos.get("categoria") or "Operativo diario"
            if estado == "Pagado" and not datos.get("fecha_pago"):
                datos["fecha_pago"] = f"{f_str} {h_str}"

            db_gasto = Gasto(**datos, usuario_id=current_user.id, usuario_nombre=u_nom)
            db.add(db_gasto)
            await db.flush()

            if estado == "Pagado":
                cuenta_af = "CAJA_FISICA" if metodo == "Efectivo" else "BANCO_TRANSFERENCIA"
                mf = await CajaService.registrar_movimiento_financiero(
                    db=db,
                    tipo="GASTO_PAGADO",
                    concepto=f"Gasto #{db_gasto.id}: {db_gasto.concepto}",
                    monto=float(db_gasto.valor),
                    metodo_pago=metodo,
                    cuenta_afectada=cuenta_af,
                    usuario=u_nom,
                    referencia_origen=f"GASTO-{db_gasto.id}",
                    sesion_id=db_gasto.sesion_caja_id,
                    observaciones=db_gasto.observacion or db_gasto.descripcion or "",
                    sincronizar_caja=(metodo == "Efectivo"),
                    fecha_str=f_str,
                    hora_str=h_str,
                )
                if not db_gasto.sesion_caja_id and mf.sesion_caja_id:
                    db_gasto.sesion_caja_id = mf.sesion_caja_id

            await log_audit(
                db=db,
                modulo="GASTOS",
                accion="CREAR",
                entidad_id=db_gasto.id,
                usuario_id=current_user.id,
                usuario_nombre=u_nom,
                valor_nuevo={"concepto": db_gasto.concepto, "valor": float(db_gasto.valor), "metodo_pago": metodo, "estado": estado},
                auto_commit=False,
            )
            await db.commit()
            await db.refresh(db_gasto)
            return db_gasto
        except IntegrityError:
            await db.rollback()
            if idem_clean:
                res_g = await db.execute(select(Gasto).where(Gasto.idempotency_key == idem_clean))
                gasto_existente = res_g.scalars().first()
                if gasto_existente:
                    gasto_existente.repetido = True
                    return gasto_existente
            raise HTTPException(status_code=409, detail="Conflicto de concurrencia al registrar gasto.")
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(status_code=500, detail=f"Fallo al registrar gasto: {str(e)}")


@router.put("/{id}", response_model=GastoResponse)
async def update_gasto(
    id: int,
    gasto_update: GastoUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
):
    result = await db.execute(select(Gasto).where(Gasto.id == id))
    gasto = result.scalars().first()
    if not gasto:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    if gasto.estado == "Anulado":
        raise HTTPException(status_code=400, detail="No se puede editar un gasto anulado.")

    cambios = gasto_update.model_dump(exclude_unset=True)
    if gasto.estado == "Pagado":
        campos_financieros = {"valor", "metodo_pago", "estado"}
        alterados = [c for c in campos_financieros if c in cambios and getattr(gasto, c, None) != cambios[c]]
        if alterados:
            raise HTTPException(
                status_code=400,
                detail="No se puede modificar valor, estado o medio de pago de un gasto ya pagado. Anule el gasto y registre uno nuevo.",
            )

    if "metodo_pago" in cambios and cambios["metodo_pago"] is not None:
        cambios["metodo_pago"] = _normalizar_metodo_gasto(cambios["metodo_pago"])

    anterior = {k: getattr(gasto, k, None) for k in cambios.keys()}
    for key, value in cambios.items():
        setattr(gasto, key, value)
    u_nom = f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario
    await log_audit(
        db=db,
        modulo="GASTOS",
        accion="EDITAR",
        entidad_id=gasto.id,
        usuario_id=current_user.id,
        usuario_nombre=u_nom,
        valor_anterior=anterior,
        valor_nuevo=cambios,
        auto_commit=False,
    )
    await db.commit()
    await db.refresh(gasto)
    return gasto


@router.post("/{id}/pagar")
async def pagar_gasto_endpoint(
    id: int,
    req: PagarGastoRequest = Body(default=PagarGastoRequest()),
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> Dict[str, Any]:
    result = await db.execute(select(Gasto).with_for_update().where(Gasto.id == id))
    g = result.scalars().first()
    if not g:
        raise HTTPException(status_code=404, detail=f"No existe el gasto #{id}")
    if g.estado == "Pagado":
        raise HTTPException(status_code=400, detail=f"El gasto #{id} ya fue pagado previamente.")
    if g.estado == "Anulado":
        raise HTTPException(status_code=400, detail=f"El gasto #{id} está anulado.")

    metodo = _normalizar_metodo_gasto(req.metodo_pago)
    ahora = datetime.now()
    f_str = ahora.strftime("%Y-%m-%d")
    h_str = ahora.strftime("%H:%M:%S")
    u_nom = f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario

    g.estado = "Pagado"
    g.metodo_pago = metodo
    g.fecha_pago = f"{f_str} {h_str}"
    g.usuario_nombre = u_nom
    if req.comprobante:
        g.comprobante = req.comprobante

    cuenta_af = "CAJA_FISICA" if metodo == "Efectivo" else "BANCO_TRANSFERENCIA"
    mf = await CajaService.registrar_movimiento_financiero(
        db=db,
        tipo="GASTO_PAGADO",
        concepto=f"Pago de Gasto #{g.id}: {g.concepto}",
        monto=float(g.valor),
        metodo_pago=metodo,
        cuenta_afectada=cuenta_af,
        usuario=u_nom,
        referencia_origen=f"GASTO-{g.id}",
        observaciones=g.observacion or "",
        sincronizar_caja=(metodo == "Efectivo"),
        fecha_str=f_str,
        hora_str=h_str,
    )
    g.sesion_caja_id = mf.sesion_caja_id
    await log_audit(
        db=db,
        modulo="GASTOS",
        accion="PAGAR",
        entidad_id=g.id,
        usuario_id=current_user.id,
        usuario_nombre=u_nom,
        valor_nuevo={"valor": float(g.valor), "metodo_pago": metodo, "sesion_caja_id": g.sesion_caja_id},
        auto_commit=False,
    )
    await db.commit()
    return {
        "ok": True,
        "id_gasto": g.id,
        "concepto": g.concepto,
        "monto": float(g.valor),
        "metodo_pago": metodo,
        "movimiento_financiero_id": mf.id,
        "fecha_pago": g.fecha_pago,
    }


@router.post("/{id}/anular")
async def anular_gasto_endpoint(
    id: int,
    motivo: Optional[str] = Query("Anulación administrativa"),
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
) -> Dict[str, Any]:
    result = await db.execute(select(Gasto).with_for_update().where(Gasto.id == id))
    g = result.scalars().first()
    if not g:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    if g.estado == "Anulado":
        return {"ok": True, "id_gasto": g.id, "estado": "Anulado"}

    estaba_pagado = g.estado == "Pagado"
    estado_anterior = g.estado
    g.estado = "Anulado"
    g.observacion = f"{g.observacion or ''} | Anulado: {motivo}".strip(" |")
    u_nom = f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario

    sesion_orig_abierta = False
    if g.sesion_caja_id:
        res_so = await db.execute(select(SesionCaja).where(SesionCaja.id == g.sesion_caja_id))
        so = res_so.scalars().first()
        sesion_orig_abierta = bool(so and so.estado == "Abierta")

    activa = await CajaService.obtener_sesion_activa(db)
    sesion_destino = g.sesion_caja_id if sesion_orig_abierta else (activa.id if activa else None)

    if estaba_pagado and g.metodo_pago == "Efectivo":
        if sesion_orig_abierta:
            # Misma sesión abierta: anular MF original y compensar gaveta en MovimientoCaja sin duplicar MF
            await CajaService.registrar_movimiento_caja(
                db=db,
                tipo="AJUSTE",
                monto=float(g.valor),
                usuario=u_nom,
                referencia_id=f"ANUL-GASTO-{g.id}",
                descripcion=f"Reversión egreso por anulación Gasto #{g.id}: {motivo}",
                sesion_id=sesion_destino,
                sincronizar_financiero=False,
            )
            mf_res = await db.execute(
                select(MovimientoFinanciero).where(MovimientoFinanciero.referencia_origen == f"GASTO-{g.id}")
            )
            for mf in mf_res.scalars().all():
                mf.estado = "Anulado"
        else:
            # Sesión histórica ya cerrada: preservar cierre histórico y registrar reversión en sesión actual
            await CajaService.registrar_movimiento_caja(
                db=db,
                tipo="AJUSTE",
                monto=float(g.valor),
                usuario=u_nom,
                referencia_id=f"ANUL-GASTO-{g.id}",
                descripcion=f"Reversión en sesión activa de Gasto histórico #{g.id}: {motivo}",
                sesion_id=sesion_destino,
                sincronizar_financiero=True,
            )
    else:
        mf_res = await db.execute(
            select(MovimientoFinanciero).where(MovimientoFinanciero.referencia_origen == f"GASTO-{g.id}")
        )
        for mf in mf_res.scalars().all():
            mf.estado = "Anulado"

    await log_audit(
        db=db,
        modulo="GASTOS",
        accion="ANULAR",
        entidad_id=g.id,
        usuario_id=current_user.id,
        usuario_nombre=u_nom,
        valor_anterior={"estado": estado_anterior, "valor": float(g.valor), "metodo_pago": g.metodo_pago},
        valor_nuevo={"estado": "Anulado", "motivo": motivo},
        auto_commit=False,
    )
    await db.commit()
    return {"ok": True, "id_gasto": g.id, "estado": "Anulado"}


@router.delete("/{id}")
async def delete_gasto(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
):
    return await anular_gasto_endpoint(id=id, motivo="Eliminación solicitada", db=db, current_user=current_user)


@router.get("/recurrentes")
async def list_recurrentes(
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    res = await db.execute(select(GastoRecurrente).order_by(GastoRecurrente.id.desc()))
    return [
        {
            "id": r.id,
            "concepto": r.concepto,
            "valor": float(r.valor or 0.0),
            "categoria": r.categoria,
            "clasificacion": r.clasificacion,
            "descripcion": r.descripcion or "",
            "frecuencia": r.frecuencia,
            "dia_corte": int(r.dia_corte or 1),
            "metodo_pago_defecto": r.metodo_pago_defecto,
            "proveedor": r.proveedor or "",
            "activo": 1 if r.activo else 0,
            "ultimo_periodo_generado": r.ultimo_periodo_generado,
        }
        for r in res.scalars().all()
    ]


@router.post("/recurrentes")
async def create_recurrente(
    rec: GastoRecurrenteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
) -> Dict[str, Any]:
    obj = GastoRecurrente(**rec.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return {"ok": True, "id": obj.id}


@router.put("/recurrentes/{id}")
async def update_recurrente(
    id: int,
    rec: GastoRecurrenteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
) -> Dict[str, Any]:
    res = await db.execute(select(GastoRecurrente).where(GastoRecurrente.id == id))
    obj = res.scalars().first()
    if not obj:
        raise HTTPException(status_code=404, detail="Plantilla recurrente no encontrada")
    for k, v in rec.model_dump().items():
        setattr(obj, k, v)
    await db.commit()
    return {"ok": True, "id": obj.id}


@router.delete("/recurrentes/{id}")
async def delete_recurrente(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
) -> Dict[str, Any]:
    res = await db.execute(select(GastoRecurrente).where(GastoRecurrente.id == id))
    obj = res.scalars().first()
    if not obj:
        raise HTTPException(status_code=404, detail="Plantilla recurrente no encontrada")
    await db.delete(obj)
    await db.commit()
    return {"ok": True}


@router.post("/recurrentes/procesar")
async def procesar_recurrentes_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> Dict[str, Any]:
    res = await db.execute(select(GastoRecurrente).where(GastoRecurrente.activo == True))  # noqa: E712
    recurrentes = res.scalars().all()
    hoy = datetime.now()
    f_str = hoy.strftime("%Y-%m-%d")
    h_str = hoy.strftime("%H:%M:%S")
    nuevos = 0

    for r in recurrentes:
        frecuencia = (r.frecuencia or "Mensual").strip()
        if frecuencia == "Diaria":
            periodo_key = hoy.strftime("%Y-%m-%d")
        elif frecuencia == "Semanal":
            periodo_key = f"{hoy.year}-W{hoy.isocalendar()[1]:02d}"
        elif frecuencia == "Quincenal":
            q = 1 if hoy.day <= 15 else 2
            periodo_key = f"{hoy.strftime('%Y-%m')}-Q{q}"
        elif frecuencia == "Anual":
            periodo_key = str(hoy.year)
        else:
            periodo_key = hoy.strftime("%Y-%m")

        if (r.ultimo_periodo_generado or "") == periodo_key:
            continue

        dia_corte = max(1, min(int(r.dia_corte or 1), 28))
        try:
            vencimiento = hoy.replace(day=dia_corte).strftime("%Y-%m-%d")
        except Exception:
            vencimiento = f_str

        obs = f"Gasto generado automáticamente ({frecuencia}) - Periodo {periodo_key}"
        db.add(
            Gasto(
                concepto=r.concepto,
                valor=float(r.valor or 0.0),
                fecha=f_str,
                hora=h_str,
                metodo_pago=r.metodo_pago_defecto or "Efectivo",
                categoria=r.categoria or "Fijo periódico",
                clasificacion=r.clasificacion or "Fijo periódico",
                descripcion=r.descripcion or "",
                fecha_vencimiento=vencimiento,
                frecuencia=frecuencia,
                estado="Pendiente",
                usuario_id=current_user.id,
                usuario_nombre="Sistema",
                proveedor=r.proveedor or "",
                comprobante="",
                observacion=obs,
                es_recurrente=True,
                recurrencia_id=r.id,
            )
        )
        r.ultimo_periodo_generado = periodo_key
        nuevos += 1

    if nuevos > 0:
        await db.commit()
    return {"ok": True, "nuevos": nuevos}
