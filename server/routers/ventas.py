from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from ..database import get_db
from ..models.venta import Venta, DetalleVenta
from ..models.producto import Producto
from ..models.inventario import MovimientoInventario
from ..schemas.venta import VentaCreate, VentaResponse, CobroOrdenCreate, DetalleVentaResponse
from ..services.venta_service import VentaService
from ..middleware.auth import get_current_user
from ..models.usuario import Usuario
from ..models.cliente import Cliente

router = APIRouter(prefix="/ventas", tags=["ventas"])

@router.post("", response_model=VentaResponse)
async def process_venta(venta_data: VentaCreate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    return await VentaService.procesar_venta(db, venta_data, current_user.id, venta_data.terminal_id, current_user)

@router.get("/pendientes-caja", response_model=List[VentaResponse])
async def list_ventas_pendientes_caja(db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Venta).where(Venta.estado == "Pendiente_Caja").order_by(Venta.id.desc()))
    ventas = result.scalars().all()

    users_res = await db.execute(select(Usuario))
    users_map = {u.id: (f"{u.nombre or ''} {u.apellidos or ''}".strip() or u.usuario) for u in users_res.scalars().all()}

    clients_res = await db.execute(select(Cliente))
    clients_map = {c.id: c.documento for c in clients_res.scalars().all()}

    res = []
    for v in ventas:
        det_res = await db.execute(select(DetalleVenta).where(DetalleVenta.venta_id == v.id))
        dets = det_res.scalars().all()
        v.detalles = dets
        v.operario_nombre = users_map.get(v.usuario_id, f"Usuario {v.usuario_id}")
        v.cliente_documento = clients_map.get(v.cliente_id, "")
        v.hora = v.created_at.strftime("%H:%M:%S") if v.created_at else ""
        v.total_items = sum(d.cantidad for d in dets)
        res.append(v)
    return res

@router.get("", response_model=List[VentaResponse])
async def list_ventas(db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Venta))
    return result.scalars().all()

@router.get("/{id}", response_model=VentaResponse)
async def get_venta(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    result = await db.execute(select(Venta).where(Venta.id == id))
    venta = result.scalars().first()
    if not venta:
        raise HTTPException(status_code=404, detail="Venta no encontrada")
    det_res = await db.execute(select(DetalleVenta).where(DetalleVenta.venta_id == id))
    venta.detalles = det_res.scalars().all()
    return venta

@router.post("/{id}/anular")
async def anular_venta(id: int, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    from ..services.venta_service import VentaService
    from ..models.terminal import Terminal
    terminal_id = 1 
    venta_anulada = await VentaService.anular_venta(db, id, current_user.id, terminal_id, current_user)
    return {"message": "Venta anulada exitosamente", "venta_id": venta_anulada.id}

@router.post("/{id}/autorizar-pago", response_model=VentaResponse)
async def autorizar_pago(id: int, cobro_data: CobroOrdenCreate, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    terminal_id = 1
    venta = await VentaService.autorizar_pago_orden(db, id, cobro_data, current_user.id, terminal_id, current_user)
    det_res = await db.execute(select(DetalleVenta).where(DetalleVenta.venta_id == venta.id))
    dets = det_res.scalars().all()
    venta.detalles = dets
    venta.total_items = sum(d.cantidad for d in dets)
    return venta

