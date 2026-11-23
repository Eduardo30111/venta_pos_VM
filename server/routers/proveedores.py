import asyncio
import re
from datetime import datetime
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, cast, String, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from typing import List, Optional, Dict, Any

from ..database import get_db
from ..models.proveedor import Proveedor, LiquidacionProveedor, AjusteLiquidacionProveedor, AuditoriaLiquidacion
from ..models.finanzas import CuentaPorPagar, Gasto
from ..models.caja import MovimientoCaja, MovimientoFinanciero
from ..schemas.proveedor import ProveedorCreate, ProveedorUpdate, ProveedorResponse
from ..services.caja_service import CajaService
from ..services.venta_service import VentaService
from ..middleware.auth import get_current_user, require_admin
from ..middleware.audit import log_audit
from ..models.usuario import Usuario
from ..async_lock import LazyAsyncLock

router = APIRouter(prefix="/proveedores", tags=["proveedores"])

_LIQUIDACION_PROV_LOCK = LazyAsyncLock()


class LiquidarProveedorRequest(BaseModel):
    monto: Optional[float] = None
    metodo_pago: str = "Efectivo"
    comprobante: Optional[str] = ""
    referencia: Optional[str] = ""
    observaciones: Optional[str] = ""
    proveedor_nombre: Optional[str] = None
    documento_nit: Optional[str] = None
    idempotency_key: Optional[str] = None
    fecha: Optional[str] = None
    hora: Optional[str] = None
    fecha_movimiento: Optional[str] = None
    hora_movimiento: Optional[str] = None


class EditarFechaLiquidacionRequest(BaseModel):
    nueva_fecha: str
    nueva_hora: Optional[str] = None
    motivo: str = "Corrección de fecha operativa"


class DineroDeMasRequest(BaseModel):
    monto_sobrante: float
    motivo: str
    fecha_movimiento: Optional[str] = None
    hora_movimiento: Optional[str] = None


@router.get("", response_model=List[ProveedorResponse])
async def list_proveedores(
    solo_activos: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    query = select(Proveedor)
    if solo_activos:
        query = query.where(Proveedor.estado == "Activo")
    query = query.order_by(Proveedor.nombre.asc())
    result = await db.execute(query)
    provs = result.scalars().all()
    for p in provs:
        try:
            res_cxp = await db.execute(
                select(
                    func.coalesce(func.sum(CuentaPorPagar.precio_venta), 0.0),
                    func.coalesce(func.sum(CuentaPorPagar.monto_comision), 0.0),
                    func.coalesce(func.sum(CuentaPorPagar.monto_pagado), 0.0),
                    func.coalesce(func.sum(CuentaPorPagar.saldo_pendiente), 0.0),
                    func.count(CuentaPorPagar.id),
                ).where(
                    CuentaPorPagar.proveedor_id == p.id,
                    CuentaPorPagar.estado.notin_(["Anulada", "Pendiente_Caja"]),
                )
            )
            row = res_cxp.first()
            if row and int(row[4] or 0) > 0:
                p.total_ventas = float(row[0] or 0.0)
                p.total_comisiones = float(row[1] or 0.0)
                p.total_pagado = float(row[2] or 0.0)
                p.saldo_acumulado = float(row[3] or 0.0)
        except Exception:
            pass
    return provs


@router.get("/liquidaciones")
async def list_liquidaciones_proveedores(
    proveedor_id: Optional[int] = Query(None),
    fecha_inicio: Optional[str] = Query(None),
    fecha_fin: Optional[str] = Query(None),
    fecha: Optional[str] = Query(None),
    mes_anio: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    query = select(LiquidacionProveedor)
    if proveedor_id:
        query = query.where(LiquidacionProveedor.proveedor_id == proveedor_id)
    if fecha:
        query = query.where(LiquidacionProveedor.fecha == fecha)
    elif fecha_inicio and fecha_fin:
        query = query.where(LiquidacionProveedor.fecha.between(fecha_inicio, fecha_fin))
    elif fecha_inicio:
        query = query.where(LiquidacionProveedor.fecha >= fecha_inicio)
    elif fecha_fin:
        query = query.where(LiquidacionProveedor.fecha <= fecha_fin)

    if mes_anio and mes_anio != "Todos":
        m_a = mes_anio
        if len(m_a) == 7 and m_a[2] == "-":
            m_a = f"{m_a[3:]}-{m_a[:2]}"
        query = query.where(
            or_(
                LiquidacionProveedor.fecha.like(f"{m_a}%"),
                LiquidacionProveedor.fecha.like(f"%{mes_anio}%")
            )
        )

    query = query.order_by(LiquidacionProveedor.id.desc())
    res = await db.execute(query)
    liqs = res.scalars().all()
    return [
        {
            "id": l.id,
            "numero_recibo": f"LP-{l.id:04d}" if not (l.numero_liquidacion or "").startswith("LP-") else l.numero_liquidacion,
            "proveedor_id": l.proveedor_id,
            "proveedor_nombre": l.proveedor_nombre or "",
            "monto_liquidado": float(l.monto_pagado or 0.0),
            "monto_pagado": float(l.monto_pagado or 0.0),
            "saldo_anterior": float(l.saldo_anterior or 0.0),
            "saldo_restante": float(l.saldo_restante or 0.0),
            "tipo_pago": "Total" if float(l.saldo_restante or 0.0) <= 0.01 else "Abono Parcial",
            "metodo_pago": l.metodo_pago or "Efectivo",
            "referencia": l.referencia or "",
            "comprobante": l.referencia or "",
            "fecha": l.fecha,
            "fecha_pago": l.fecha,
            "hora": l.hora or "",
            "usuario": l.usuario or "",
            "usuario_nombre": l.usuario or "",
            "observaciones": l.observaciones or "",
            "estado": l.estado or "Aplicado",
        }
        for l in liqs
    ]


@router.get("/{id}", response_model=ProveedorResponse)
async def get_proveedor(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    result = await db.execute(select(Proveedor).where(Proveedor.id == id))
    proveedor = result.scalars().first()
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    res_cxp = await db.execute(
        select(
            func.coalesce(func.sum(CuentaPorPagar.precio_venta), 0.0),
            func.coalesce(func.sum(CuentaPorPagar.monto_comision), 0.0),
            func.coalesce(func.sum(CuentaPorPagar.monto_pagado), 0.0),
            func.coalesce(func.sum(CuentaPorPagar.saldo_pendiente), 0.0),
            func.count(CuentaPorPagar.id),
        ).where(
            CuentaPorPagar.proveedor_id == proveedor.id,
            CuentaPorPagar.estado.notin_(["Anulada", "Pendiente_Caja"]),
        )
    )
    row = res_cxp.first()
    if row and int(row[4] or 0) > 0:
        proveedor.total_ventas = float(row[0] or 0.0)
        proveedor.total_comisiones = float(row[1] or 0.0)
        proveedor.total_pagado = float(row[2] or 0.0)
        proveedor.saldo_acumulado = float(row[3] or 0.0)
    return proveedor


@router.post("", response_model=ProveedorResponse)
async def create_proveedor(
    proveedor: ProveedorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
):
    nom = (proveedor.nombre or "").strip()
    if not nom:
        raise HTTPException(status_code=400, detail="El nombre del proveedor es obligatorio")
    dup = await db.execute(select(Proveedor).where(Proveedor.nombre.ilike(nom)))
    existente = dup.scalars().first()
    if existente:
        return existente

    datos = proveedor.model_dump()
    datos["nombre"] = nom
    datos["documento_nit"] = (datos.get("documento_nit") or "").strip()
    db_prov = Proveedor(**datos)
    db.add(db_prov)
    await db.flush()
    await log_audit(
        db=db,
        modulo="PROVEEDORES",
        accion="CREAR",
        entidad_id=db_prov.id,
        usuario_id=current_user.id,
        usuario_nombre=current_user.nombre or current_user.usuario,
        valor_nuevo={"nombre": db_prov.nombre, "documento_nit": db_prov.documento_nit},
        auto_commit=False,
    )
    await db.commit()
    await db.refresh(db_prov)
    return db_prov


@router.put("/{id}", response_model=ProveedorResponse)
async def update_proveedor(
    id: int,
    prov_update: ProveedorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
):
    result = await db.execute(select(Proveedor).where(Proveedor.id == id))
    proveedor = result.scalars().first()
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    cambios = prov_update.model_dump(exclude_unset=True)
    anterior = {k: getattr(proveedor, k, None) for k in cambios.keys()}
    for key, value in cambios.items():
        setattr(proveedor, key, value)
    await log_audit(
        db=db,
        modulo="PROVEEDORES",
        accion="EDITAR",
        entidad_id=proveedor.id,
        usuario_id=current_user.id,
        usuario_nombre=current_user.nombre or current_user.usuario,
        valor_anterior=anterior,
        valor_nuevo=cambios,
        auto_commit=False,
    )
    await db.commit()
    await db.refresh(proveedor)
    return proveedor


@router.patch("/{id}/estado", response_model=ProveedorResponse)
async def change_estado(
    id: int,
    estado: str,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
):
    result = await db.execute(select(Proveedor).where(Proveedor.id == id))
    proveedor = result.scalars().first()
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    est_ant = proveedor.estado
    proveedor.estado = estado
    await log_audit(
        db=db,
        modulo="PROVEEDORES",
        accion="ESTADO",
        entidad_id=proveedor.id,
        usuario_id=current_user.id,
        usuario_nombre=current_user.nombre or current_user.usuario,
        valor_anterior={"estado": est_ant},
        valor_nuevo={"estado": estado},
        auto_commit=False,
    )
    await db.commit()
    await db.refresh(proveedor)
    return proveedor


async def _sincronizar_cxp_retroactivas_server(db: AsyncSession, proveedor_id: int):
    """
    Sincronización retroactiva en servidor central:
    Detecta ventas de productos o servicios vinculados al proveedor que aún no tengan CuentaPorPagar
    y genera los registros correspondientes, recalculando los acumulados.
    """
    try:
        from ..models.venta import Venta, DetalleVenta
        from ..models.servicio import Servicio
        from ..models.producto import Producto

        res_p = await db.execute(select(Proveedor).where(Proveedor.id == proveedor_id))
        prov = res_p.scalars().first()
        if not prov:
            return

        p_str = str(proveedor_id)
        # Buscar servicios vinculados
        res_serv = await db.execute(
            select(Servicio).where(
                (Servicio.proveedor_id == proveedor_id) |
                (cast(Servicio.proveedor_id, String) == p_str) |
                (cast(Servicio.proveedor_id, String).like(f"{p_str} - %"))
            )
        )
        servicios = {s.codigo: s for s in res_serv.scalars().all() if s.codigo}
        servicios_nom = {s.nombre.strip().lower(): s for s in servicios.values() if s.nombre}

        # Buscar productos vinculados
        res_prod = await db.execute(
            select(Producto).where(
                (Producto.proveedor_id == proveedor_id) |
                (cast(Producto.proveedor_id, String) == p_str) |
                (cast(Producto.proveedor_id, String).like(f"{p_str} - %"))
            )
        )
        productos = {p.codigo: p for p in res_prod.scalars().all() if p.codigo}
        productos_nom = {p.nombre.strip().lower(): p for p in productos.values() if p.nombre}

        if not servicios and not productos and not servicios_nom and not productos_nom:
            return

        res_det = await db.execute(
            select(DetalleVenta, Venta)
            .join(Venta, DetalleVenta.venta_id == Venta.id)
            .where(Venta.estado != "Anulada", Venta.estado != "Pendiente_Caja")
        )
        detalles = res_det.all()

        creadas = 0
        for dv, v in detalles:
            cod = (dv.item_codigo or "").strip()
            nom = (dv.item_nombre or "").strip()
            item_match = (
                servicios.get(cod) or
                productos.get(cod) or
                servicios_nom.get(nom.lower()) or
                productos_nom.get(nom.lower())
            )
            if not item_match:
                continue

            res_ex = await db.execute(
                select(CuentaPorPagar).where(
                    CuentaPorPagar.venta_id == v.id,
                    (CuentaPorPagar.codigo_servicio == cod) | (CuentaPorPagar.nombre_servicio == nom)
                )
            )
            if res_ex.scalars().first():
                continue

            sub = float(dv.subtotal or 0.0)
            costo_u = float(getattr(item_match, "costo_proveedor", None) or getattr(item_match, "precio_costo", None) or dv.costo_unitario or 0.0)
            cant = float(dv.cantidad or 1.0)
            pct_c = float(getattr(item_match, "porcentaje_comision", 0.0) or 0.0)

            # Precedencia unificada con VentaService: si hay porcentaje de comisión configurado, aplicar primero
            if pct_c > 0:
                m_com = round(sub * (pct_c / 100.0), 2)
                m_pagar = max(0.0, round(sub - m_com, 2))
            elif costo_u > 0:
                m_pagar = round(costo_u * cant, 2)
                m_com = max(0.0, round(sub - m_pagar, 2))
            else:
                m_com = 0.0
                m_pagar = sub

            cxp = CuentaPorPagar(
                proveedor_id=prov.id,
                venta_id=v.id,
                numero_venta=v.numero or f"V-{v.id:06d}",
                codigo_servicio=cod or (item_match.codigo if hasattr(item_match, 'codigo') else ""),
                nombre_servicio=nom or (item_match.nombre if hasattr(item_match, 'nombre') else "Servicio"),
                precio_venta=sub,
                porcentaje_comision=pct_c,
                monto_comision=m_com,
                concepto=f"Servicio/Producto {nom}",
                monto=m_pagar,
                monto_pagado=0.0,
                saldo_pendiente=m_pagar,
                estado="Pendiente",
                fecha=v.fecha or datetime.now().strftime("%Y-%m-%d"),
                hora=v.hora or datetime.now().strftime("%H:%M:%S"),
                usuario=v.operario_nombre or "Administrador",
            )
            db.add(cxp)
            creadas += 1

        if creadas > 0:
            await db.commit()
            await VentaService._recalcular_acumulados_proveedor(db, prov.id)
    except Exception as e_retro:
        print(f"Aviso en _sincronizar_cxp_retroactivas_server: {e_retro}")


@router.get("/{id}/cxp")
async def get_cxp_proveedor(
    id: int,
    estado: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    await _sincronizar_cxp_retroactivas_server(db, id)
    p_str = str(id)
    query = select(CuentaPorPagar).where(
        (CuentaPorPagar.proveedor_id == id) |
        (cast(CuentaPorPagar.proveedor_id, String) == p_str) |
        (cast(CuentaPorPagar.proveedor_id, String).like(f"{p_str} - %"))
    )
    if estado and estado != "Todos":
        query = query.where(CuentaPorPagar.estado == estado)
    query = query.order_by(CuentaPorPagar.id.desc())
    res = await db.execute(query)
    items = []
    for c in res.scalars().all():
        items.append(
            {
                "id": c.id,
                "proveedor_id": c.proveedor_id,
                "id_venta": c.venta_id,
                "numero_venta": c.numero_venta or f"V-{c.venta_id or 0:06d}",
                "codigo_servicio": c.codigo_servicio or "",
                "nombre_servicio": c.nombre_servicio or c.concepto,
                "precio_venta": float(c.precio_venta or c.monto or 0.0),
                "porcentaje_comision": float(c.porcentaje_comision or 0.0),
                "monto_comision": float(c.monto_comision or 0.0),
                "monto_proveedor": float(c.monto or 0.0),
                "monto_por_pagar": float(c.monto or 0.0),
                "monto_pagado": float(c.monto_pagado or 0.0),
                "saldo_pendiente": float(c.saldo_pendiente or 0.0),
                "estado": c.estado,
                "fecha": c.fecha or (c.created_at.strftime("%Y-%m-%d") if c.created_at else ""),
                "fecha_venta": c.fecha or (c.created_at.strftime("%Y-%m-%d") if c.created_at else ""),
                "hora": c.hora or (c.created_at.strftime("%H:%M:%S") if c.created_at else ""),
                "usuario": c.usuario or "",
            }
        )
    return items


@router.get("/{id}/liquidaciones")
async def get_liquidaciones_proveedor(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    res = await db.execute(
        select(LiquidacionProveedor)
        .where(LiquidacionProveedor.proveedor_id == id)
        .order_by(LiquidacionProveedor.id.desc())
    )
    return [
        {
            "id": l.id,
            "proveedor_id": l.proveedor_id,
            "fecha": l.fecha,
            "hora": l.hora,
            "monto_pagado": float(l.monto_pagado or 0.0),
            "metodo_pago": l.metodo_pago,
            "referencia": l.referencia or "",
            "comprobante": l.referencia or "",
            "usuario": l.usuario or "",
            "observaciones": l.observaciones or "",
            "estado": l.estado,
            "fecha_registro": l.fecha_registro or "",
            "dinero_de_mas": float(l.dinero_de_mas or 0.0),
            "monto_ajustado": float(l.monto_ajustado or (l.monto_pagado or 0.0)),
            "monto_neto": max(0.0, float(l.monto_pagado or 0.0) - float(l.dinero_de_mas or 0.0)),
        }
        for l in res.scalars().all()
    ]


@router.post("/{id}/liquidar")
async def liquidar_proveedor(
    id: int,
    req: LiquidarProveedorRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
) -> Dict[str, Any]:
    # Idempotencia estricta para pagos de liquidaciones a proveedores
    idem_clean = (getattr(req, "idempotency_key", None) or "").strip() or None
    async with _LIQUIDACION_PROV_LOCK:
        try:
            if idem_clean:
                res_liq = await db.execute(select(LiquidacionProveedor).where(LiquidacionProveedor.idempotency_key == idem_clean))
                liq_existente = res_liq.scalars().first()
                if liq_existente:
                    return {
                        "ok": True,
                        "exito": True,
                        "liquidacion_id": liq_existente.id,
                        "numero_recibo": f"LQ-{liq_existente.id:05d}",
                        "monto_pagado": float(liq_existente.monto_pagado or 0.0),
                        "saldo_restante": float(liq_existente.saldo_restante or 0.0),
                        "metodo_pago": liq_existente.metodo_pago or "Efectivo",
                        "cuentas_afectadas": 0,
                        "repetido": True,
                    }

            res_p = await db.execute(select(Proveedor).with_for_update().where(Proveedor.id == id))
            prov = res_p.scalars().first()
            if not prov and req.proveedor_nombre:
                res_p_nom = await db.execute(
                    select(Proveedor).with_for_update().where(func.lower(Proveedor.nombre) == func.lower(req.proveedor_nombre.strip()))
                )
                prov = res_p_nom.scalars().first()

            if not prov:
                raise HTTPException(
                    status_code=404,
                    detail=f"Proveedor #{id} no encontrado. Registre el proveedor antes de liquidar.",
                )

            await _sincronizar_cxp_retroactivas_server(db, prov.id)

            p_str = str(prov.id)
            res_cxp = await db.execute(
                select(CuentaPorPagar)
                .with_for_update()
                .where(
                    (CuentaPorPagar.proveedor_id == prov.id) |
                    (cast(CuentaPorPagar.proveedor_id, String) == p_str) |
                    (cast(CuentaPorPagar.proveedor_id, String).like(f"{p_str} - %")),
                    CuentaPorPagar.estado.in_(["Pendiente", "Parcial"]),
                    CuentaPorPagar.saldo_pendiente > 0,
                )
                .order_by(CuentaPorPagar.id.asc())
            )
            pendientes = res_cxp.scalars().all()
            saldo_total = round(sum(float(c.saldo_pendiente or 0.0) for c in pendientes), 2)
            if saldo_total <= 0.009:
                if float(prov.saldo_acumulado or 0.0) > 0.009:
                    saldo_total = round(float(prov.saldo_acumulado), 2)
                else:
                    raise HTTPException(status_code=400, detail="El proveedor no tiene saldo pendiente por liquidar.")

            monto_pagar = round(float(req.monto if req.monto is not None else saldo_total), 2)
            if monto_pagar <= 0:
                raise HTTPException(status_code=400, detail="El monto a liquidar debe ser mayor a cero.")
            if monto_pagar > saldo_total + 0.01:
                raise HTTPException(status_code=400, detail=f"El monto excede el saldo pendiente (${saldo_total:,.0f}).")

            metodo = "Efectivo" if (req.metodo_pago or "").strip().lower() == "efectivo" else "Transferencia"
            ahora = datetime.now()
            f_mov = req.fecha_movimiento or req.fecha
            h_mov = req.hora_movimiento or req.hora
            f_str = f_mov.strip()[:10] if f_mov else ahora.strftime("%Y-%m-%d")
            h_str = h_mov.strip()[:8] if h_mov else ahora.strftime("%H:%M:%S")
            fecha_registro_str = ahora.strftime("%Y-%m-%d %H:%M:%S")
            u_nom = f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario

            remanente = monto_pagar
            cuentas_afectadas = 0
            for c in pendientes:
                if remanente <= 0.001:
                    break
                ab = min(remanente, float(c.saldo_pendiente or 0.0))
                c.monto_pagado = round(float(c.monto_pagado or 0.0) + ab, 2)
                c.saldo_pendiente = round(max(0.0, float(c.saldo_pendiente or 0.0) - ab), 2)
                c.estado = "Pagada" if c.saldo_pendiente <= 0.009 else "Parcial"
                remanente = round(remanente - ab, 2)
                cuentas_afectadas += 1

            if not pendientes:
                prov.saldo_acumulado = max(0.0, round(float(prov.saldo_acumulado or 0.0) - monto_pagar, 2))
                prov.total_pagado = round(float(prov.total_pagado or 0.0) + monto_pagar, 2)

            ref_val = (req.comprobante or req.referencia or "").strip()

            gasto = Gasto(
                concepto=f"Liquidación proveedor: {prov.nombre}",
                categoria="Operativo diario",
                clasificacion="Operativo diario",
                descripcion=req.observaciones or f"Liquidación servicios proveedor {prov.nombre}",
                valor=monto_pagar,
                fecha=f_str,
                hora=h_str,
                fecha_pago=f"{f_str} {h_str}",
                estado="Pagado",
                metodo_pago=metodo,
                tipo="Proveedor",
                proveedor=prov.nombre,
                comprobante=ref_val,
                usuario_id=current_user.id,
                usuario_nombre=u_nom,
                observacion=req.observaciones or "",
            )
            db.add(gasto)
            await db.flush()

            cuenta_af = "CAJA_FISICA" if metodo == "Efectivo" else "BANCO_TRANSFERENCIA"
            mf = await CajaService.registrar_movimiento_financiero(
                db=db,
                tipo="PAGO_PROVEEDOR",
                concepto=f"Liquidación proveedor {prov.nombre}",
                monto=monto_pagar,
                metodo_pago=metodo,
                cuenta_afectada=cuenta_af,
                usuario=u_nom,
                referencia_origen=f"PROVEEDOR-{prov.id}",
                observaciones=req.observaciones or "",
                sincronizar_caja=(metodo == "Efectivo"),
                fecha_str=f_str,
                hora_str=h_str,
            )

            num_liq = f"LIQ-PROV-{ahora.strftime('%Y%m%d%H%M%S')}-{prov.id}"
            saldo_restante_final = max(0.0, round(saldo_total - monto_pagar, 2))
            liq = LiquidacionProveedor(
                numero_liquidacion=num_liq,
                proveedor_id=prov.id,
                proveedor_nombre=prov.nombre,
                fecha=f_str,
                hora=h_str,
                monto_pagado=monto_pagar,
                metodo_pago=metodo,
                referencia=ref_val,
                saldo_anterior=saldo_total,
                saldo_restante=saldo_restante_final,
                usuario=u_nom,
                observaciones=req.observaciones or "",
                estado="Completada",
                idempotency_key=idem_clean,
                fecha_registro=fecha_registro_str,
                dinero_de_mas=0.0,
                monto_ajustado=monto_pagar,
            )
            db.add(liq)
            await db.flush()
            if pendientes:
                await VentaService._recalcular_acumulados_proveedor(db, prov.id)
            await log_audit(
                db=db,
                modulo="PROVEEDORES",
                accion="LIQUIDAR",
                entidad_id=liq.id,
                usuario_id=current_user.id,
                usuario_nombre=u_nom,
                valor_anterior={"proveedor_id": prov.id, "saldo_anterior": saldo_total},
                valor_nuevo={
                    "liquidacion_id": liq.id,
                    "monto_pagado": monto_pagar,
                    "metodo_pago": metodo,
                    "saldo_restante": float(prov.saldo_acumulado or 0.0),
                },
                auto_commit=False,
            )
            await db.commit()

            return {
                "ok": True,
                "exito": True,
                "liquidacion_id": liq.id,
                "numero_recibo": f"LQ-{liq.id:05d}",
                "monto_pagado": monto_pagar,
                "saldo_restante": float(prov.saldo_acumulado or 0.0),
                "metodo_pago": metodo,
                "cuentas_afectadas": len([c for c in pendientes if (float(c.monto_pagado or 0.0) > 0)]),
            }
        except IntegrityError:
            await db.rollback()
            if idem_clean:
                res_liq = await db.execute(select(LiquidacionProveedor).where(LiquidacionProveedor.idempotency_key == idem_clean))
                liq_existente = res_liq.scalars().first()
                if liq_existente:
                    return {
                        "ok": True,
                        "exito": True,
                        "liquidacion_id": liq_existente.id,
                        "numero_recibo": f"LQ-{liq_existente.id:05d}",
                        "monto_pagado": float(liq_existente.monto_pagado or 0.0),
                        "saldo_restante": float(liq_existente.saldo_restante or 0.0),
                        "metodo_pago": liq_existente.metodo_pago or "Efectivo",
                        "cuentas_afectadas": 0,
                        "repetido": True,
                    }
            raise HTTPException(status_code=409, detail="Conflicto de concurrencia al liquidar proveedor.")


async def _buscar_liquidacion_servidor_flexible(db: AsyncSession, id_str: Any) -> Optional[LiquidacionProveedor]:
    """Busca liquidación en el servidor por ID numérico, número de liquidación o variantes de prefijo."""
    clean_id = str(id_str or "").strip()
    if not clean_id:
        return None
    # 1. Búsqueda directa por ID entero si es numérico
    if clean_id.isdigit():
        res = await db.execute(select(LiquidacionProveedor).where(LiquidacionProveedor.id == int(clean_id)))
        liq = res.scalars().first()
        if liq:
            return liq
    # 2. Coincidencia exacta por número de liquidación
    res = await db.execute(select(LiquidacionProveedor).where(LiquidacionProveedor.numero_liquidacion == clean_id))
    liq = res.scalars().first()
    if liq:
        return liq
    # 3. Normalización de dígitos y variantes LP- / LQ- / LIQ-PROV-
    digitos = re.findall(r'\d+', clean_id)
    if digitos:
        d_val = digitos[-1]
        try:
            num_val = int(d_val)
        except Exception:
            num_val = 0
        v_lp = f"LP-{num_val:04d}"
        v_lq = f"LQ-{num_val:05d}"
        res = await db.execute(
            select(LiquidacionProveedor).where(
                or_(
                    LiquidacionProveedor.id == num_val,
                    LiquidacionProveedor.numero_liquidacion == v_lp,
                    LiquidacionProveedor.numero_liquidacion == v_lq,
                    LiquidacionProveedor.numero_liquidacion.like(f"%{d_val}%"),
                    LiquidacionProveedor.numero_liquidacion.like(f"%-{num_val}")
                )
            ).order_by(LiquidacionProveedor.id.desc())
        )
        liq = res.scalars().first()
        if liq:
            return liq
    return None


@router.get("/liquidaciones/{id}")
async def get_liquidacion_detalle(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> Dict[str, Any]:
    liq = await _buscar_liquidacion_servidor_flexible(db, id)
    if not liq:
        raise HTTPException(status_code=404, detail="Liquidación no encontrada.")
    rec_num = f"LP-{liq.id:04d}" if not (liq.numero_liquidacion or "").startswith("LP-") else liq.numero_liquidacion
    m_val = float(liq.monto_pagado or 0.0)
    d_mas = float(liq.dinero_de_mas or 0.0)
    m_aj = float(liq.monto_ajustado or m_val)
    return {
        "id": liq.id,
        "numero_recibo": rec_num,
        "proveedor_id": liq.proveedor_id,
        "proveedor_nombre": liq.proveedor_nombre or "",
        "monto_liquidado": m_val,
        "monto_pagado": m_val,
        "dinero_de_mas": d_mas,
        "monto_ajustado": m_aj,
        "limite_ajustable": max(0.0, round(m_val - d_mas, 2)),
        "saldo_anterior": float(liq.saldo_anterior or 0.0),
        "saldo_restante": float(liq.saldo_restante or 0.0),
        "metodo_pago": liq.metodo_pago or "Efectivo",
        "referencia": liq.referencia or "",
        "fecha": liq.fecha,
        "hora": liq.hora or "",
        "usuario": liq.usuario or "",
        "observaciones": liq.observaciones or "",
        "estado": liq.estado or "Aplicado"
    }


@router.post("/liquidaciones/{id}/editar-fecha")
async def editar_fecha_liquidacion(
    id: str,
    req: EditarFechaLiquidacionRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
) -> Dict[str, Any]:
    async with _LIQUIDACION_PROV_LOCK:
        liq = await _buscar_liquidacion_servidor_flexible(db, id)
        if not liq:
            raise HTTPException(status_code=404, detail="Liquidación no encontrada.")

        f_ant = liq.fecha
        h_ant = liq.hora
        nueva_f = req.nueva_fecha.strip()[:10]
        nueva_h = req.nueva_hora.strip()[:8] if req.nueva_hora else h_ant
        u_nom = f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario
        recibo = f"LQ-{liq.id:05d}"

        liq.fecha = nueva_f
        liq.hora = nueva_h

        # Actualizar gastos asociados
        res_g = await db.execute(
            select(Gasto).where(
                Gasto.categoria == "Pago Proveedores",
                Gasto.descripcion.like(f"%{recibo}%")
            )
        )
        for g in res_g.scalars().all():
            g.fecha = nueva_f

        # Actualizar movimientos de caja asociados
        res_mc = await db.execute(
            select(MovimientoCaja).where(
                or_(
                    MovimientoCaja.referencia_id == recibo,
                    MovimientoCaja.descripcion.like(f"%{recibo}%")
                )
            )
        )
        for mc in res_mc.scalars().all():
            mc.fecha = nueva_f
            mc.hora = nueva_h

        # Actualizar movimientos financieros
        res_mf = await db.execute(
            select(MovimientoFinanciero).where(
                or_(
                    MovimientoFinanciero.referencia_origen == recibo,
                    MovimientoFinanciero.concepto.like(f"%{recibo}%")
                )
            )
        )
        for mf in res_mf.scalars().all():
            mf.fecha = nueva_f
            mf.hora = nueva_h

        # Registrar auditoria
        aud = AuditoriaLiquidacion(
            liquidacion_id=liq.id,
            numero_recibo=recibo,
            proveedor_id=liq.proveedor_id,
            proveedor_nombre=liq.proveedor_nombre,
            accion="EDITAR_FECHA",
            fecha_anterior=f"{f_ant} {h_ant}".strip(),
            fecha_nueva=f"{nueva_f} {nueva_h}".strip(),
            monto=float(liq.monto_pagado or 0.0),
            usuario=u_nom,
            motivo=req.motivo or "Corrección de fecha operativa",
            fecha_registro=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        db.add(aud)
        await db.commit()

        return {
            "ok": True,
            "exito": True,
            "liquidacion_id": liq.id,
            "numero_recibo": recibo,
            "fecha_anterior": f_ant,
            "fecha_nueva": nueva_f,
            "hora_nueva": nueva_h
        }


@router.post("/liquidaciones/{id}/dinero-de-mas")
async def registrar_dinero_de_mas(
    id: str,
    req: DineroDeMasRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
) -> Dict[str, Any]:
    async with _LIQUIDACION_PROV_LOCK:
        liq = await _buscar_liquidacion_servidor_flexible(db, id)
        if not liq:
            raise HTTPException(status_code=404, detail="Liquidación no encontrada.")

        monto_sobrante = float(req.monto_sobrante)
        if monto_sobrante <= 0:
            raise HTTPException(status_code=400, detail="El monto sobrante debe ser mayor a 0.")

        dinero_de_mas_actual = float(liq.dinero_de_mas or 0.0)
        monto_pagado_orig = float(liq.monto_pagado or 0.0)
        limite_ajustable = round(monto_pagado_orig - dinero_de_mas_actual, 2)

        if monto_sobrante > limite_ajustable:
            raise HTTPException(
                status_code=400,
                detail=f"El monto no puede superar el saldo liquidado disponible (${limite_ajustable:,.2f})."
            )

        u_nom = f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario
        ahora = datetime.now()
        f_reg = ahora.strftime("%Y-%m-%d %H:%M:%S")
        f_mov = (req.fecha_movimiento or liq.fecha).strip()[:10]
        h_mov = (req.hora_movimiento or liq.hora).strip()[:8]
        recibo = f"LQ-{liq.id:05d}"
        num_ajuste = f"AJ-SOB-{ahora.strftime('%Y%m%d%H%M%S')}-{liq.id}"

        # 1. Actualizar liquidación
        nuevo_dinero_de_mas = round(dinero_de_mas_actual + monto_sobrante, 2)
        nuevo_monto_ajustado = round(monto_pagado_orig - nuevo_dinero_de_mas, 2)
        liq.dinero_de_mas = nuevo_dinero_de_mas
        liq.monto_ajustado = nuevo_monto_ajustado

        # 2. Registrar ajuste
        ajuste = AjusteLiquidacionProveedor(
            numero_ajuste=num_ajuste,
            liquidacion_id=liq.id,
            numero_recibo=recibo,
            proveedor_id=liq.proveedor_id,
            proveedor_nombre=liq.proveedor_nombre,
            monto_ajuste=monto_sobrante,
            fecha_movimiento=f_mov,
            hora_movimiento=h_mov,
            fecha_registro=f_reg,
            usuario=u_nom,
            motivo=req.motivo or "Ajuste por dinero de más",
            estado="Aplicado"
        )
        db.add(ajuste)

        # 3. Registrar contra-gasto (gasto negativo para reducir egresos contables en f_mov)
        contra_gasto = Gasto(
            descripcion=f"Ajuste Dinero de Más {recibo} - {liq.proveedor_nombre} [{num_ajuste}]",
            categoria="Pago Proveedores",
            valor=-monto_sobrante,
            fecha=f_mov,
            hora=h_mov,
            usuario=u_nom,
            comprobante=num_ajuste
        )
        db.add(contra_gasto)

        # 4. Si fue en efectivo, reingresar a caja física
        if (liq.metodo_pago or "").lower() == "efectivo":
            mc = MovimientoCaja(
                fecha=f_mov,
                hora=h_mov,
                tipo="AJUSTE",
                monto=monto_sobrante,
                usuario=u_nom,
                terminal="SERVER",
                referencia_id=num_ajuste,
                descripcion=f"Dinero de más recuperado de {recibo} - {liq.proveedor_nombre}"
            )
            db.add(mc)
            mf = MovimientoFinanciero(
                fecha=f_mov,
                hora=h_mov,
                tipo="AJUSTE_AUTORIZADO",
                concepto=f"Dinero de más recuperado {recibo} - {liq.proveedor_nombre}",
                monto=monto_sobrante,
                metodo_pago="Efectivo",
                cuenta_afectada="CAJA_FISICA",
                usuario=u_nom,
                referencia_origen=num_ajuste
            )
            db.add(mf)

        # 5. Reabrir cuentas por pagar (LIFO)
        p_str = str(liq.proveedor_id)
        res_cxp = await db.execute(
            select(CuentaPorPagar)
            .where(
                (CuentaPorPagar.proveedor_id == liq.proveedor_id) |
                (cast(CuentaPorPagar.proveedor_id, String) == p_str) |
                (cast(CuentaPorPagar.proveedor_id, String).like(f"{p_str} - %")),
                CuentaPorPagar.estado.in_(["Pagada", "Parcial"])
            )
            .order_by(CuentaPorPagar.id.desc())
        )
        remanente_restaurar = monto_sobrante
        for c in res_cxp.scalars().all():
            if remanente_restaurar <= 0.001:
                break
            pagado_c = float(c.monto_pagado or 0.0)
            if pagado_c <= 0:
                continue
            restaurar_c = min(pagado_c, remanente_restaurar)
            c.monto_pagado = round(pagado_c - restaurar_c, 2)
            c.saldo_pendiente = round(float(c.saldo_pendiente or 0.0) + restaurar_c, 2)
            c.estado = "Parcial" if c.saldo_pendiente < float(c.monto or 0.0) else "Pendiente"
            remanente_restaurar = round(remanente_restaurar - restaurar_c, 2)

        await VentaService._recalcular_acumulados_proveedor(db, liq.proveedor_id)

        # 6. Auditoria
        aud = AuditoriaLiquidacion(
            liquidacion_id=liq.id,
            numero_recibo=recibo,
            proveedor_id=liq.proveedor_id,
            proveedor_nombre=liq.proveedor_nombre,
            accion="DINERO_DE_MAS",
            fecha_anterior=liq.fecha,
            fecha_nueva=f_mov,
            monto=monto_sobrante,
            usuario=u_nom,
            motivo=req.motivo,
            fecha_registro=f_reg
        )
        db.add(aud)
        await db.commit()

        return {
            "ok": True,
            "exito": True,
            "numero_ajuste": num_ajuste,
            "numero_recibo": recibo,
            "monto_ajuste": monto_sobrante,
            "dinero_de_mas_total": nuevo_dinero_de_mas,
            "monto_neto": nuevo_monto_ajustado
        }


@router.get("/liquidaciones/{id}/ajustes")
async def get_ajustes_liquidacion(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    liq = await _buscar_liquidacion_servidor_flexible(db, id)
    target_id = liq.id if liq else (int(id) if str(id).isdigit() else 0)
    res = await db.execute(
        select(AjusteLiquidacionProveedor)
        .where(
            or_(
                AjusteLiquidacionProveedor.liquidacion_id == target_id,
                AjusteLiquidacionProveedor.numero_recibo == str(id),
                AjusteLiquidacionProveedor.numero_recibo == (f"LQ-{target_id:05d}" if target_id else "")
            )
        )
        .order_by(AjusteLiquidacionProveedor.id.desc())
    )
    return [
        {
            "id": a.id,
            "numero_ajuste": a.numero_ajuste,
            "liquidacion_id": a.liquidacion_id,
            "numero_recibo": a.numero_recibo,
            "proveedor_id": a.proveedor_id,
            "proveedor_nombre": a.proveedor_nombre,
            "monto_ajuste": float(a.monto_ajuste or 0.0),
            "fecha_movimiento": a.fecha_movimiento,
            "hora_movimiento": a.hora_movimiento,
            "fecha_registro": a.fecha_registro,
            "usuario": a.usuario,
            "motivo": a.motivo,
            "estado": a.estado,
        }
        for a in res.scalars().all()
    ]
