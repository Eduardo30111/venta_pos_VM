from datetime import datetime
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
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


@router.get("/{id}/cxp")
async def get_cxp_proveedor(
    id: int,
    estado: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    query = select(CuentaPorPagar).where(CuentaPorPagar.proveedor_id == id)
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
                "monto_pagado": float(c.monto_pagado or 0.0),
                "saldo_pendiente": float(c.saldo_pendiente or 0.0),
                "estado": c.estado,
                "fecha": c.fecha or (c.created_at.strftime("%Y-%m-%d") if c.created_at else ""),
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

    res_cxp = await db.execute(
        select(CuentaPorPagar)
        .with_for_update()
        .where(
            CuentaPorPagar.proveedor_id == id,
            CuentaPorPagar.estado.in_(["Pendiente", "Parcial"]),
            CuentaPorPagar.saldo_pendiente > 0,
        )
        .order_by(CuentaPorPagar.id.asc())
    )
    pendientes = res_cxp.scalars().all()
    saldo_total = round(sum(float(c.saldo_pendiente or 0.0) for c in pendientes), 2)
    if saldo_total <= 0.009:
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
    for c in pendientes:
        if remanente <= 0.001:
            break
        ab = min(remanente, float(c.saldo_pendiente or 0.0))
        c.monto_pagado = round(float(c.monto_pagado or 0.0) + ab, 2)
        c.saldo_pendiente = round(max(0.0, float(c.saldo_pendiente or 0.0) - ab), 2)
        c.estado = "Pagada" if c.saldo_pendiente <= 0.009 else "Parcial"
        remanente = round(remanente - ab, 2)

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
        comprobante=req.comprobante or "",
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

    liq = LiquidacionProveedor(
        proveedor_id=prov.id,
        fecha=f_str,
        hora=h_str,
        monto_pagado=monto_pagar,
        metodo_pago=metodo,
        comprobante=req.comprobante or "",
        usuario=u_nom,
        observaciones=req.observaciones or "",
        gasto_id=gasto.id,
        movimiento_financiero_id=mf.id,
        estado="Completado",
    )
    db.add(liq)
    await db.flush()
    await VentaService._recalcular_acumulados_proveedor(db, prov.id)
    await db.commit()

    return {
        "ok": True,
        "liquidacion_id": liq.id,
        "monto_pagado": monto_pagar,
        "saldo_restante": float(prov.saldo_acumulado or 0.0),
        "metodo_pago": metodo,
    }
