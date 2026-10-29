from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from datetime import date
from ..database import get_db
from ..models.venta import Venta, Pago
from ..models.finanzas import Gasto, Abono
from ..middleware.auth import get_current_user
from ..models.usuario import Usuario

router = APIRouter(prefix="/reportes", tags=["reportes"])

@router.get("/resumen-diario")
async def resumen_diario(fecha: date, db: AsyncSession = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    # Total ventas completadas
    ventas_result = await db.execute(
        select(func.sum(Venta.total)).where(func.date(Venta.created_at) == fecha, Venta.estado == 'Completada')
    )
    total_ventas = float(ventas_result.scalar() or 0.0)

    # Ventas en efectivo vs fiado
    ve_res = await db.execute(
        select(func.sum(Pago.monto))
        .join(Venta, Pago.venta_id == Venta.id)
        .where(func.date(Venta.created_at) == fecha, Venta.estado == 'Completada', Pago.metodo == 'Efectivo')
    )
    ventas_efectivo = float(ve_res.scalar() or 0.0)

    vt_res = await db.execute(
        select(func.sum(Pago.monto))
        .join(Venta, Pago.venta_id == Venta.id)
        .where(func.date(Venta.created_at) == fecha, Venta.estado == 'Completada', Pago.metodo == 'Transferencia')
    )
    ventas_transferencia = float(vt_res.scalar() or 0.0)

    vf_res = await db.execute(
        select(func.sum(Pago.monto))
        .join(Venta, Pago.venta_id == Venta.id)
        .where(func.date(Venta.created_at) == fecha, Venta.estado == 'Completada', Pago.metodo == 'Fiado')
    )
    ventas_fiado = float(vf_res.scalar() or 0.0)

    # Abonos del día
    ab_efectivo_res = await db.execute(
        select(func.sum(Abono.monto)).where(func.date(Abono.created_at) == fecha, Abono.metodo == 'Efectivo')
    )
    abonos_efectivo = float(ab_efectivo_res.scalar() or 0.0)

    ab_trans_res = await db.execute(
        select(func.sum(Abono.monto)).where(func.date(Abono.created_at) == fecha, Abono.metodo != 'Efectivo')
    )
    abonos_transferencia = float(ab_trans_res.scalar() or 0.0)

    # Total gastos
    gastos_result = await db.execute(
        select(func.sum(Gasto.valor)).where(func.date(Gasto.created_at) == fecha)
    )
    total_gastos = float(gastos_result.scalar() or 0.0)

    ge_result = await db.execute(select(func.sum(Gasto.valor)).where(
        func.date(Gasto.created_at) == fecha, Gasto.metodo_pago == "Efectivo"
    ))
    gastos_efectivo = float(ge_result.scalar() or 0.0)
    gt_result = await db.execute(select(func.sum(Gasto.valor)).where(
        func.date(Gasto.created_at) == fecha, Gasto.metodo_pago == "Transferencia"
    ))
    gastos_transferencia = float(gt_result.scalar() or 0.0)

    caja_efectivo = ventas_efectivo + abonos_efectivo - gastos_efectivo
    transferencia_real = ventas_transferencia + abonos_transferencia - gastos_transferencia

    return {
        "fecha": fecha,
        "ventas": total_ventas,
        "ventas_efectivo": ventas_efectivo,
        "ventas_transferencia": ventas_transferencia,
        "ventas_fiado": ventas_fiado,
        "abonos_efectivo": abonos_efectivo,
        "abonos_transferencia": abonos_transferencia,
        "gastos": total_gastos,
        "gastos_efectivo": gastos_efectivo,
        "gastos_transferencia": gastos_transferencia,
        "caja_efectivo": caja_efectivo,
        "transferencia_real": transferencia_real,
        "neto": total_ventas - total_gastos
    }

