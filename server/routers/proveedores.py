from datetime import datetime
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, cast, String, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional, Dict, Any

from ..database import get_db
from ..models.proveedor import Proveedor, LiquidacionProveedor
from ..models.finanzas import CuentaPorPagar, Gasto
from ..schemas.proveedor import ProveedorCreate, ProveedorUpdate, ProveedorResponse
from ..services.caja_service import CajaService
from ..services.venta_service import VentaService
from ..middleware.auth import get_current_user
from ..models.usuario import Usuario

router = APIRouter(prefix="/proveedores", tags=["proveedores"])


class LiquidarProveedorRequest(BaseModel):
    monto: Optional[float] = None
    metodo_pago: str = "Efectivo"
    comprobante: Optional[str] = ""
    referencia: Optional[str] = ""
    observaciones: Optional[str] = ""


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
                ).where(CuentaPorPagar.proveedor_id == p.id, CuentaPorPagar.estado != "Anulada")
            )
            row = res_cxp.first()
            if row:
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
    return proveedor


@router.post("", response_model=ProveedorResponse)
async def create_proveedor(
    proveedor: ProveedorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
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
    await db.commit()
    await db.refresh(db_prov)
    return db_prov


@router.put("/{id}", response_model=ProveedorResponse)
async def update_proveedor(
    id: int,
    prov_update: ProveedorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    result = await db.execute(select(Proveedor).where(Proveedor.id == id))
    proveedor = result.scalars().first()
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    for key, value in prov_update.model_dump(exclude_unset=True).items():
        setattr(proveedor, key, value)
    await db.commit()
    await db.refresh(proveedor)
    return proveedor


@router.patch("/{id}/estado", response_model=ProveedorResponse)
async def change_estado(
    id: int,
    estado: str,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    result = await db.execute(select(Proveedor).where(Proveedor.id == id))
    proveedor = result.scalars().first()
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    proveedor.estado = estado
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
            .where(Venta.estado != "Anulada")
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

            if costo_u > 0:
                m_pagar = round(costo_u * cant, 2)
                m_com = max(0.0, round(sub - m_pagar, 2))
            elif pct_c > 0:
                m_com = round(sub * (pct_c / 100.0), 2)
                m_pagar = max(0.0, round(sub - m_com, 2))
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
            "comprobante": l.comprobante or "",
            "usuario": l.usuario or "",
            "observaciones": l.observaciones or "",
            "estado": l.estado,
        }
        for l in res.scalars().all()
    ]


@router.post("/{id}/liquidar")
async def liquidar_proveedor(
    id: int,
    req: LiquidarProveedorRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> Dict[str, Any]:
    res_p = await db.execute(select(Proveedor).with_for_update().where(Proveedor.id == id))
    prov = res_p.scalars().first()
    if not prov:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")

    await _sincronizar_cxp_retroactivas_server(db, id)

    p_str = str(id)
    res_cxp = await db.execute(
        select(CuentaPorPagar)
        .with_for_update()
        .where(
            (CuentaPorPagar.proveedor_id == id) |
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
    f_str = ahora.strftime("%Y-%m-%d")
    h_str = ahora.strftime("%H:%M:%S")
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
    )
    db.add(liq)
    await db.flush()
    await VentaService._recalcular_acumulados_proveedor(db, prov.id)
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
