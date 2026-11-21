import asyncio
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_, and_
from sqlalchemy.exc import IntegrityError
from typing import Optional, List, Dict, Any

from ..database import get_db
from ..models.caja import SesionCaja, MovimientoCaja, MovimientoFinanciero
from ..services.caja_service import CajaService
from ..middleware.auth import get_current_user, require_admin, require_roles, is_admin_role
from ..middleware.audit import log_audit
from ..models.usuario import Usuario
from ..async_lock import LazyAsyncLock

router = APIRouter(prefix="/caja", tags=["caja"])

_CAJA_LOCK = LazyAsyncLock()


def _nombre_usuario_autenticado(current_user: Usuario) -> str:
    return f"{current_user.nombre or ''} {current_user.apellidos or ''}".strip() or current_user.usuario


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
    arqueo_cierre: Optional[Dict[str, Any]] = None
    arqueo_cierre_json: Optional[str] = None


class MovimientoCajaCreateRequest(BaseModel):
    tipo: str
    monto: float
    usuario: Optional[str] = None
    terminal: Optional[str] = "CAJA-01"
    referencia_id: Optional[str] = ""
    descripcion: Optional[str] = ""
    sesion_id: Optional[int] = None
    sincronizar_financiero: bool = True
    idempotency_key: Optional[str] = None


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
    idempotency_key: Optional[str] = None


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
    current_user: Usuario = Depends(require_roles("administrador", "admin", "gerente", "cajero", "vendedor")),
) -> Dict[str, Any]:
    u_nom = _nombre_usuario_autenticado(current_user)
    sesion = await CajaService.abrir_sesion(
        db=db,
        usuario=u_nom,
        monto_inicial=req.monto_inicial,
        terminal_id=req.terminal_id,
        terminal_nombre=req.terminal_nombre,
        arqueo_apertura=req.arqueo_apertura,
    )
    await log_audit(
        db=db,
        modulo="CAJA",
        accion="ABRIR_CAJA",
        entidad_id=sesion.id,
        usuario_id=current_user.id,
        usuario_nombre=u_nom,
        valor_nuevo={"sesion_id": sesion.id, "monto_inicial": float(sesion.monto_inicial or 0.0)},
        auto_commit=False,
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
    current_user: Usuario = Depends(require_roles("administrador", "admin", "gerente", "cajero", "vendedor")),
) -> Dict[str, Any]:
    u_nom = _nombre_usuario_autenticado(current_user)
    res = await CajaService.cerrar_sesion(
        db=db,
        sesion_id=sesion_id,
        usuario=u_nom,
        monto_real_contado=req.monto_real_contado,
        observaciones=req.observaciones or "",
        terminal=req.terminal or "CAJA-01",
        monto_transferencias_verificado=req.monto_transferencias_verificado,
        arqueo_cierre=req.arqueo_cierre,
        arqueo_cierre_json=req.arqueo_cierre_json,
    )
    await log_audit(
        db=db,
        modulo="CAJA",
        accion="CERRAR_CAJA",
        entidad_id=sesion_id,
        usuario_id=current_user.id,
        usuario_nombre=u_nom,
        valor_nuevo={
            "efectivo_esperado": res.get("efectivo_esperado"),
            "monto_real_contado": res.get("monto_real_contado"),
            "diferencia": res.get("diferencia"),
            "transferencias_esperadas": res.get("transferencias_esperadas"),
            "transferencias_verificadas": res.get("transferencias_verificadas"),
        },
        auto_commit=False,
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
                "arqueo_apertura_json": getattr(s, "arqueo_apertura_json", "") or "",
                "arqueo_cierre_json": getattr(s, "arqueo_cierre_json", "") or "",
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
        cond = or_(
            MovimientoFinanciero.sesion_caja_id == sesion_id,
            and_(MovimientoFinanciero.sesion_caja_id.is_(None), MovimientoFinanciero.fecha == f_ap),
        )

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
    tipo_up = (req.tipo or "").strip().upper()
    if tipo_up in ("AJUSTE", "RETIRO", "INGRESO_EXTRAORDINARIO") and not is_admin_role(current_user):
        raise HTTPException(
            status_code=403,
            detail="Operación restringida: solo un administrador puede registrar ajustes o retiros de caja.",
        )
    idem_clean = (getattr(req, "idempotency_key", None) or "").strip() or None
    async with _CAJA_LOCK:
        try:
            u_nom = _nombre_usuario_autenticado(current_user)
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
                idempotency_key=idem_clean,
            )
            await log_audit(
                db=db,
                modulo="CAJA",
                accion=f"MOVIMIENTO_{tipo_up or 'MANUAL'}",
                entidad_id=mov.id,
                usuario_id=current_user.id,
                usuario_nombre=u_nom,
                valor_nuevo={"tipo": req.tipo, "monto": req.monto, "descripcion": req.descripcion},
                auto_commit=False,
            )
            await db.commit()
            return {"ok": True, "id": mov.id}
        except IntegrityError:
            await db.rollback()
            if idem_clean:
                res_m = await db.execute(select(MovimientoCaja).where(MovimientoCaja.idempotency_key == idem_clean))
                m_existente = res_m.scalars().first()
                if m_existente:
                    return {"ok": True, "id": m_existente.id, "repetido": True}
            raise HTTPException(status_code=409, detail="Conflicto de concurrencia en movimiento de caja.")


@router.post("/movimientos-financieros")
async def post_movimiento_financiero(
    req: MovimientoFinancieroCreateRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> Dict[str, Any]:
    tipo_up = (req.tipo or "").strip().upper()
    if tipo_up in ("AJUSTE_AUTORIZADO", "RETIRO_CAJA", "INGRESO_EXTRAORDINARIO") and not is_admin_role(current_user):
        raise HTTPException(
            status_code=403,
            detail="Operación restringida: solo un administrador puede registrar ajustes, retiros o ingresos extraordinarios.",
        )
    idem_clean = (getattr(req, "idempotency_key", None) or "").strip() or None
    async with _CAJA_LOCK:
        try:
            u_nom = _nombre_usuario_autenticado(current_user)
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
                idempotency_key=idem_clean,
            )
            await log_audit(
                db=db,
                modulo="CAJA",
                accion=f"MOV_FIN_{tipo_up or 'MANUAL'}",
                entidad_id=mf.id,
                usuario_id=current_user.id,
                usuario_nombre=u_nom,
                valor_nuevo={"tipo": req.tipo, "monto": req.monto, "cuenta": req.cuenta_afectada, "concepto": req.concepto},
                auto_commit=False,
            )
            await db.commit()
            return {"ok": True, "id": mf.id}
        except IntegrityError:
            await db.rollback()
            if idem_clean:
                res_mf = await db.execute(select(MovimientoFinanciero).where(MovimientoFinanciero.idempotency_key == idem_clean))
                mf_existente = res_mf.scalars().first()
                if mf_existente:
                    return {"ok": True, "id": mf_existente.id, "repetido": True}
            raise HTTPException(status_code=409, detail="Conflicto de concurrencia en movimiento financiero.")


@router.post("/ingresos-autorizados")
async def post_ingreso_autorizado(
    req: IngresoAutorizadoRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
) -> Dict[str, Any]:
    if req.monto <= 0:
        raise HTTPException(status_code=400, detail="El monto del ingreso autorizado debe ser mayor a cero.")
    if not req.motivo or len(req.motivo.strip()) < 3:
        raise HTTPException(
            status_code=400,
            detail="Debe indicar un motivo o justificación del ingreso (mínimo 3 caracteres).",
        )
    u_nom = _nombre_usuario_autenticado(current_user)
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
    await log_audit(
        db=db,
        modulo="CAJA",
        accion="INGRESO_AUTORIZADO",
        entidad_id=mf.id,
        usuario_id=current_user.id,
        usuario_nombre=u_nom,
        valor_nuevo={"monto": req.monto, "motivo": req.motivo.strip()},
        auto_commit=False,
    )
    await db.commit()
    return {"ok": True, "id": mf.id}
