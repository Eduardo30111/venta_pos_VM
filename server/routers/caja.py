from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_
from typing import Optional, List, Dict, Any

from ..database import get_db
from ..models.caja import SesionCaja, MovimientoCaja, MovimientoFinanciero
from ..services.caja_service import CajaService
from ..middleware.auth import get_current_user
from ..models.usuario import Usuario

router = APIRouter(prefix="/caja", tags=["caja"])


class AbrirCajaRequest(BaseModel):
    usuario: Optional[str] = None
    monto_inicial: float = 0.0
    terminal_id: Optional[int] = 1
    terminal_nombre: Optional[str] = "CAJA-01"
    arqueo_apertura: Optional[Dict[str, Any]] = None


class CerrarCajaRequest(BaseModel):
    usuario: Optional[str] = None
    monto_real_contado: Optional[float] = 0.0
    observaciones: Optional[str] = ""
    terminal: Optional[str] = "CAJA-01"
    monto_transferencias_verificado: Optional[float] = None


class MovimientoCajaCreateRequest(BaseModel):
    tipo: str
    monto: float
    usuario: Optional[str] = None
    terminal: Optional[str] = "CAJA-01"
    referencia_id: Optional[str] = ""
    descripcion: Optional[str] = ""
    sesion_id: Optional[int] = None
    sincronizar_financiero: bool = True


class MovimientoFinancieroCreateRequest(BaseModel):
    tipo: str
    concepto: str
    monto: float
    metodo_pago: str = "Efectivo"
    cuenta_afectada: str = "CAJA_FISICA"
    usuario: Optional[str] = None
    referencia_origen: Optional[str] = ""
    sesion_id: Optional[int] = None
    observaciones: Optional[str] = ""
    estado: str = "Activo"
    sincronizar_caja: bool = True
    terminal: Optional[str] = "CAJA-01"


class IngresoAutorizadoRequest(BaseModel):
    monto: float
    motivo: str
    usuario: Optional[str] = None
    sesion_id: Optional[int] = None


@router.get("/sesion-activa")
async def get_sesion_activa(
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> Dict[str, Any]:
    activa = await CajaService.obtener_sesion_activa(db)
    if not activa:
        return {"activa": None}
    return {"activa": CajaService._sesion_to_dict(activa)}


@router.post("/abrir")
async def post_abrir_caja(
    req: AbrirCajaRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> Dict[str, Any]:
    u_nom = req.usuario or (f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario)
    sesion = await CajaService.abrir_sesion(
        db=db,
        usuario=u_nom,
        monto_inicial=req.monto_inicial,
        terminal_id=req.terminal_id,
        terminal_nombre=req.terminal_nombre,
        arqueo_apertura=req.arqueo_apertura,
    )
    await db.commit()
    await db.refresh(sesion)
    return {"ok": True, "sesion_id": sesion.id, "sesion": CajaService._sesion_to_dict(sesion)}


@router.get("/sesiones/{sesion_id}/arqueo")
async def get_arqueo_sesion(
    sesion_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> Dict[str, Any]:
    arqueo = await CajaService.calcular_arqueo_sesion(db, sesion_id)
    if not arqueo:
        raise HTTPException(status_code=404, detail="Sesión de caja no encontrada")
    return arqueo


@router.post("/sesiones/{sesion_id}/cerrar")
async def post_cerrar_sesion(
    sesion_id: int,
    req: CerrarCajaRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> Dict[str, Any]:
    u_nom = req.usuario or (f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario)
    res = await CajaService.cerrar_sesion(
        db=db,
        sesion_id=sesion_id,
        usuario=u_nom,
        monto_real_contado=req.monto_real_contado,
        observaciones=req.observaciones or "",
        terminal=req.terminal or "CAJA-01",
        monto_transferencias_verificado=req.monto_transferencias_verificado,
    )
    await db.commit()
    return res


@router.get("/cierres")
async def get_cierres_anteriores(
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    res = await db.execute(
        select(SesionCaja)
        .where(SesionCaja.estado == "Cerrada")
        .order_by(SesionCaja.id.desc())
        .limit(limit)
    )
    salida = []
    for s in res.scalars().all():
        salida.append(
            {
                "id": s.id,
                "fecha_apertura": s.fecha_apertura,
                "hora_apertura": s.hora_apertura,
                "usuario_apertura": s.usuario_apertura,
                "base_inicial": float(s.monto_inicial or 0.0),
                "monto_inicial": float(s.monto_inicial or 0.0),
                "fecha_cierre": s.fecha_cierre,
                "hora_cierre": s.hora_cierre,
                "usuario_cierre": s.usuario_cierre,
                "monto_esperado": float(s.monto_esperado_efectivo or 0.0),
                "monto_esperado_efectivo": float(s.monto_esperado_efectivo or 0.0),
                "monto_real_contado": float(s.monto_real_contado or 0.0),
                "diferencia": float(s.diferencia or 0.0),
                "observaciones": s.observaciones or "",
                "transferencias_esperadas": float(s.monto_transferencias_esperado or 0.0),
                "transferencias_verificadas": float(s.monto_transferencias_verificado or 0.0),
                "diferencia_banco": float(s.diferencia_banco or 0.0),
                "estado_banco": s.estado_banco or "Pendiente",
            }
        )
    return salida


@router.get("/movimientos-sesion/{sesion_id}")
async def get_movimientos_sesion(
    sesion_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    res_s = await db.execute(select(SesionCaja).where(SesionCaja.id == sesion_id))
    sesion = res_s.scalars().first()
    f_ap = sesion.fecha_apertura if sesion else None

    cond = MovimientoFinanciero.sesion_caja_id == sesion_id
    if f_ap:
        cond = or_(MovimientoFinanciero.sesion_caja_id == sesion_id, MovimientoFinanciero.fecha == f_ap)

    res_mf = await db.execute(
        select(MovimientoFinanciero)
        .where(cond, MovimientoFinanciero.estado != "Anulado")
        .order_by(MovimientoFinanciero.id.desc())
    )
    mfs = res_mf.scalars().all()
    if mfs:
        return [
            {
                "id": m.id,
                "fecha": m.fecha,
                "hora": m.hora,
                "tipo": m.tipo,
                "monto": float(m.monto or 0.0),
                "cuenta": m.cuenta_afectada,
                "cuenta_afectada": m.cuenta_afectada,
                "metodo_pago": m.metodo_pago,
                "usuario": m.usuario,
                "descripcion": m.concepto,
                "concepto": m.concepto,
                "estado": m.estado,
            }
            for m in mfs
        ]

    res_mc = await db.execute(
        select(MovimientoCaja)
        .where(MovimientoCaja.sesion_caja_id == sesion_id)
        .order_by(MovimientoCaja.id.desc())
    )
    return [
        {
            "id": c.id,
            "fecha": c.fecha,
            "hora": c.hora,
            "tipo": c.tipo,
            "monto": float(c.monto or 0.0),
            "cuenta": "CAJA_FISICA",
            "cuenta_afectada": "CAJA_FISICA",
            "metodo_pago": "Efectivo",
            "usuario": c.usuario,
            "descripcion": c.descripcion or "",
            "concepto": c.descripcion or "",
            "estado": "Activo",
        }
        for c in res_mc.scalars().all()
    ]


@router.post("/movimientos")
async def post_movimiento_caja(
    req: MovimientoCajaCreateRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> Dict[str, Any]:
    u_nom = req.usuario or (f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario)
    mov = await CajaService.registrar_movimiento_caja(
        db=db,
        tipo=req.tipo,
        monto=req.monto,
        usuario=u_nom,
        terminal=req.terminal or "CAJA-01",
        referencia_id=req.referencia_id,
        descripcion=req.descripcion or "",
        sesion_id=req.sesion_id,
        sincronizar_financiero=req.sincronizar_financiero,
    )
    await db.commit()
    return {"ok": True, "id": mov.id}


@router.post("/movimientos-financieros")
async def post_movimiento_financiero(
    req: MovimientoFinancieroCreateRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> Dict[str, Any]:
    u_nom = req.usuario or (f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario)
    mf = await CajaService.registrar_movimiento_financiero(
        db=db,
        tipo=req.tipo,
        concepto=req.concepto,
        monto=req.monto,
        metodo_pago=req.metodo_pago,
        cuenta_afectada=req.cuenta_afectada,
        usuario=u_nom,
        referencia_origen=req.referencia_origen or "",
        sesion_id=req.sesion_id,
        observaciones=req.observaciones or "",
        estado=req.estado,
        sincronizar_caja=req.sincronizar_caja,
        terminal=req.terminal or "CAJA-01",
    )
    await db.commit()
    return {"ok": True, "id": mf.id}


@router.post("/ingresos-autorizados")
async def post_ingreso_autorizado(
    req: IngresoAutorizadoRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> Dict[str, Any]:
    if req.monto <= 0:
        raise HTTPException(status_code=400, detail="El monto del ingreso autorizado debe ser mayor a cero.")
    if not req.motivo or len(req.motivo.strip()) < 3:
        raise HTTPException(
            status_code=400,
            detail="Debe indicar un motivo o justificación del ingreso (mínimo 3 caracteres).",
        )
    u_nom = req.usuario or (f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario)
    mf = await CajaService.registrar_movimiento_financiero(
        db=db,
        tipo="INGRESO_EXTRAORDINARIO",
        concepto=f"Ingreso autorizado: {req.motivo.strip()}",
        monto=req.monto,
        metodo_pago="Efectivo",
        cuenta_afectada="CAJA_FISICA",
        usuario=u_nom,
        referencia_origen="INGRESO_MANUAL",
        sesion_id=req.sesion_id,
        observaciones=req.motivo.strip(),
        sincronizar_caja=True,
    )
    await db.commit()
    return {"ok": True, "id": mf.id}
