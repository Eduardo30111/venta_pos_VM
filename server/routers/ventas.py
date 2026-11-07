from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, or_
from typing import List, Optional, Dict, Any

from ..database import get_db
from ..models.venta import Venta, DetalleVenta, Pago
from ..models.auditoria import AuditLog
from ..schemas.venta import (
    VentaCreate,
    VentaResponse,
    CobroOrdenCreate,
    AnularVentaRequest,
    EditarVentaRequest,
)
from ..services.venta_service import VentaService
from ..middleware.auth import get_current_user
from ..models.usuario import Usuario
from ..models.cliente import Cliente

router = APIRouter(prefix="/ventas", tags=["ventas"])


@router.post("", response_model=VentaResponse)
async def process_venta(
    venta_data: VentaCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return await VentaService.procesar_venta(
        db,
        venta_data,
        current_user.id,
        venta_data.terminal_id or 1,
        current_user,
    )


@router.get("/por-idempotencia/{idempotency_key}", response_model=VentaResponse)
async def get_venta_por_idempotencia(
    idempotency_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    venta = await VentaService.buscar_por_idempotencia(db, idempotency_key)
    if not venta:
        raise HTTPException(status_code=404, detail="No existe venta registrada con esa clave de idempotencia")
    return venta


@router.get("/pendientes-caja", response_model=List[VentaResponse])
async def list_ventas_pendientes_caja(
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    result = await db.execute(
        select(Venta).where(Venta.estado == "Pendiente_Caja").order_by(Venta.id.desc())
    )
    ventas = result.scalars().all()
    res = []
    for v in ventas:
        res.append(await VentaService.hidratar_venta(db, v, ya_existia=False))
    return res


@router.get("", response_model=List[VentaResponse])
async def list_ventas(
    estado: Optional[str] = Query(None),
    busqueda: Optional[str] = Query(None),
    fecha_inicio: Optional[str] = Query(None),
    fecha_fin: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    query = select(Venta)
    if estado and estado.lower() not in ("todas", "todos"):
        query = query.where(Venta.estado == estado)

    f_col = func.coalesce(Venta.fecha, func.date(Venta.created_at))
    if fecha_inicio:
        query = query.where(f_col >= fecha_inicio)
    if fecha_fin:
        query = query.where(f_col <= fecha_fin)

    if busqueda and busqueda.strip():
        term = f"%{busqueda.strip()}%"
        conditions = [
            Venta.numero.ilike(term),
            Venta.operario_nombre.ilike(term),
            Venta.cliente_documento.ilike(term),
        ]
        if busqueda.strip().isdigit():
            conditions.append(Venta.id == int(busqueda.strip()))
        query = query.where(or_(*conditions))

    query = query.order_by(Venta.id.desc()).limit(limit)
    result = await db.execute(query)
    ventas = result.scalars().all()

    users_res = await db.execute(select(Usuario))
    users_map = {
        u.id: (f"{u.nombre or ''} {u.apellidos or ''}".strip() or u.usuario)
        for u in users_res.scalars().all()
    }
    clients_res = await db.execute(select(Cliente))
    clients_map = {c.id: (c.documento, c.nombre) for c in clients_res.scalars().all()}

    res = []
    for v in ventas:
        det_res = await db.execute(select(DetalleVenta).where(DetalleVenta.venta_id == v.id))
        dets = det_res.scalars().all()
        pag_res = await db.execute(select(Pago).where(Pago.venta_id == v.id))
        pags = pag_res.scalars().all()
        v.detalles = dets
        v.pagos = pags
        if not v.operario_nombre:
            v.operario_nombre = users_map.get(v.usuario_id, f"Usuario {v.usuario_id}")
        if v.cliente_id and v.cliente_id in clients_map:
            doc_c, nom_c = clients_map[v.cliente_id]
            v.cliente_documento = v.cliente_documento or doc_c
            v.cliente_nombre = nom_c
        if not v.metodo_pago_principal:
            v.metodo_pago_principal = pags[0].metodo if pags else "Efectivo"
        if not v.fecha and v.created_at:
            v.fecha = v.created_at.strftime("%Y-%m-%d")
        if not v.hora and v.created_at:
            v.hora = v.created_at.strftime("%H:%M:%S")
        v.total_items = sum(float(d.cantidad or 0.0) for d in dets)
        res.append(v)
    return res


@router.get("/{id}", response_model=VentaResponse)
async def get_venta(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    result = await db.execute(select(Venta).where(Venta.id == id))
    venta = result.scalars().first()
    if not venta:
        raise HTTPException(status_code=404, detail="Venta no encontrada")
    return await VentaService.hidratar_venta(db, venta, ya_existia=False)


@router.get("/{id}/auditoria")
async def get_auditoria_venta(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    res = await db.execute(
        select(AuditLog)
        .where(AuditLog.tabla_afectada == "ventas", AuditLog.registro_id == str(id))
        .order_by(AuditLog.id.desc())
    )
    logs = res.scalars().all()
    salida = []
    for lg in logs:
        f_str = lg.created_at.strftime("%Y-%m-%d") if lg.created_at else ""
        h_str = lg.created_at.strftime("%H:%M:%S") if lg.created_at else ""
        vn = lg.valor_nuevo if isinstance(lg.valor_nuevo, dict) else {}
        va = lg.valor_anterior if isinstance(lg.valor_anterior, dict) else {}
        motivo = vn.get("motivo") or lg.descripcion or ""
        salida.append(
            {
                "id": lg.id,
                "id_venta": id,
                "accion": lg.accion,
                "usuario": lg.usuario_nombre,
                "terminal": lg.terminal_nombre or "Terminal",
                "fecha": f_str,
                "hora": h_str,
                "motivo": motivo,
                "valor_anterior": va.get("total", 0.0),
                "valor_nuevo": vn.get("total", 0.0),
                "detalles_json": str(vn or va),
            }
        )
    return salida


@router.post("/{id}/anular")
async def anular_venta(
    id: int,
    req: Optional[AnularVentaRequest] = Body(default=None),
    motivo: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    motivo_final = (
        (req.motivo if req and req.motivo else None)
        or motivo
        or "Anulación administrativa"
    )
    terminal_id = (req.terminal_id if req and req.terminal_id else None) or 1
    venta_anulada = await VentaService.anular_venta(
        db=db,
        venta_id=id,
        usuario_id=current_user.id,
        terminal_id=terminal_id,
        usuario=current_user,
        motivo=motivo_final,
    )
    return {
        "ok": True,
        "exito": True,
        "success": True,
        "message": "Venta anulada exitosamente",
        "venta_id": venta_anulada.id,
        "id_venta": venta_anulada.id,
        "total_anulado": venta_anulada.total,
        "metodo_pago": venta_anulada.metodo_pago_principal,
        "motivo": motivo_final,
        "usuario": current_user.nombre,
    }


@router.put("/{id}")
async def editar_venta(
    id: int,
    req: EditarVentaRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return await VentaService.editar_venta(
        db=db,
        venta_id=id,
        req=req,
        usuario_id=current_user.id,
        usuario=current_user,
    )


@router.post("/{id}/autorizar-pago", response_model=VentaResponse)
async def autorizar_pago(
    id: int,
    cobro_data: CobroOrdenCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    terminal_id = 1
    return await VentaService.autorizar_pago_orden(
        db, id, cobro_data, current_user.id, terminal_id, current_user
    )
