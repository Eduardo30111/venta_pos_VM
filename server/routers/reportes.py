from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from datetime import date

from ..database import get_db
from ..models.venta import Venta, DetalleVenta, Pago
from ..models.finanzas import Gasto, Abono
from ..models.cliente import Cliente
from ..middleware.auth import get_current_user
from ..models.usuario import Usuario

router = APIRouter(prefix="/reportes", tags=["reportes"])


@router.get("/resumen-diario")
async def resumen_diario(
    fecha: date,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    f_str = fecha.isoformat()
    pref_mes = fecha.strftime("%Y-%m")

    v_fecha = func.coalesce(Venta.fecha, func.date(Venta.created_at))
    ab_fecha = func.coalesce(Abono.fecha, func.date(Abono.created_at))
    g_fecha = func.coalesce(Gasto.fecha, func.date(Gasto.created_at))

    # Ventas activas del día
    ventas_result = await db.execute(
        select(func.sum(Venta.total), func.count(Venta.id)).where(
            v_fecha == f_str,
            Venta.estado != "Anulada",
            Venta.estado != "Pendiente_Caja",
        )
    )
    row_v = ventas_result.first()
    total_ventas = float((row_v[0] if row_v else 0.0) or 0.0)
    pedidos_hoy = int((row_v[1] if row_v else 0) or 0)

    # Ventas del mes
    v_mes_res = await db.execute(
        select(func.sum(Venta.total), func.count(Venta.id)).where(
            v_fecha.like(f"{pref_mes}%"),
            Venta.estado != "Anulada",
            Venta.estado != "Pendiente_Caja",
        )
    )
    row_vm = v_mes_res.first()
    ventas_mes = float((row_vm[0] if row_vm else 0.0) or 0.0)
    pedidos_mes = int((row_vm[1] if row_vm else 0) or 0)

    # Desglose de pagos del día
    ve_res = await db.execute(
        select(func.sum(Pago.monto))
        .join(Venta, Pago.venta_id == Venta.id)
        .where(
            v_fecha == f_str,
            Venta.estado != "Anulada",
            Venta.estado != "Pendiente_Caja",
            func.lower(Pago.metodo) == "efectivo",
        )
    )
    ventas_efectivo = float(ve_res.scalar() or 0.0)

    vt_res = await db.execute(
        select(func.sum(Pago.monto))
        .join(Venta, Pago.venta_id == Venta.id)
        .where(
            v_fecha == f_str,
            Venta.estado != "Anulada",
            Venta.estado != "Pendiente_Caja",
            func.lower(Pago.metodo) == "transferencia",
        )
    )
    ventas_transferencia = float(vt_res.scalar() or 0.0)

    vf_res = await db.execute(
        select(func.sum(Pago.monto))
        .join(Venta, Pago.venta_id == Venta.id)
        .where(
            v_fecha == f_str,
            Venta.estado != "Anulada",
            Venta.estado != "Pendiente_Caja",
            func.lower(Pago.metodo) == "fiado",
        )
    )
    ventas_fiado = float(vf_res.scalar() or 0.0)

    # Abonos del día (NUNCA sumados a total_ventas)
    ab_efectivo_res = await db.execute(
        select(func.sum(Abono.monto)).where(
            ab_fecha == f_str,
            func.lower(Abono.metodo) == "efectivo",
        )
    )
    abonos_efectivo = float(ab_efectivo_res.scalar() or 0.0)

    ab_trans_res = await db.execute(
        select(func.sum(Abono.monto)).where(
            ab_fecha == f_str,
            func.lower(Abono.metodo) != "efectivo",
        )
    )
    abonos_transferencia = float(ab_trans_res.scalar() or 0.0)

    # Gastos del día (excluyendo anulados)
    gastos_result = await db.execute(
        select(func.sum(Gasto.valor)).where(
            g_fecha == f_str,
            func.coalesce(Gasto.estado, "Pagado") != "Anulado",
        )
    )
    total_gastos = float(gastos_result.scalar() or 0.0)

    gastos_mes_res = await db.execute(
        select(func.sum(Gasto.valor)).where(
            g_fecha.like(f"{pref_mes}%"),
            func.coalesce(Gasto.estado, "Pagado") != "Anulado",
        )
    )
    gastos_mes = float(gastos_mes_res.scalar() or 0.0)

    ge_result = await db.execute(
        select(func.sum(Gasto.valor)).where(
            g_fecha == f_str,
            func.coalesce(Gasto.estado, "Pagado") == "Pagado",
            func.lower(Gasto.metodo_pago) == "efectivo",
        )
    )
    gastos_efectivo = float(ge_result.scalar() or 0.0)

    gt_result = await db.execute(
        select(func.sum(Gasto.valor)).where(
            g_fecha == f_str,
            func.coalesce(Gasto.estado, "Pagado") == "Pagado",
            func.lower(Gasto.metodo_pago) == "transferencia",
        )
    )
    gastos_transferencia = float(gt_result.scalar() or 0.0)

    # Clientes activos y atendidos hoy
    cli_total_res = await db.execute(select(func.count(Cliente.id)))
    clientes_total = int(cli_total_res.scalar() or 0)

    cli_hoy_res = await db.execute(
        select(func.count(func.distinct(Venta.cliente_id))).where(
            v_fecha == f_str,
            Venta.estado != "Anulada",
            Venta.cliente_id.isnot(None),
        )
    )
    clientes_hoy = int(cli_hoy_res.scalar() or 0)

    # Producto top del día
    top_res = await db.execute(
        select(DetalleVenta.item_nombre, func.sum(DetalleVenta.cantidad).label("u"))
        .join(Venta, DetalleVenta.venta_id == Venta.id)
        .where(v_fecha == f_str, Venta.estado != "Anulada")
        .group_by(DetalleVenta.item_nombre)
        .order_by(func.sum(DetalleVenta.cantidad).desc())
        .limit(1)
    )
    row_top = top_res.first()
    producto_top = row_top[0] if row_top else "Sin ventas hoy"
    producto_top_cant = float(row_top[1] or 0.0) if row_top else 0.0

    caja_efectivo = ventas_efectivo + abonos_efectivo - gastos_efectivo
    transferencia_real = ventas_transferencia + abonos_transferencia - gastos_transferencia

    return {
        "fecha": fecha,
        "ventas": total_ventas,
        "ventas_mes": ventas_mes,
        "pedidos": pedidos_hoy,
        "pedidos_mes": pedidos_mes,
        "ventas_efectivo": ventas_efectivo,
        "ventas_transferencia": ventas_transferencia,
        "ventas_fiado": ventas_fiado,
        "abonos_efectivo": abonos_efectivo,
        "abonos_transferencia": abonos_transferencia,
        "gastos": total_gastos,
        "gastos_mes": gastos_mes,
        "gastos_efectivo": gastos_efectivo,
        "gastos_transferencia": gastos_transferencia,
        "caja_efectivo": caja_efectivo,
        "transferencia_real": transferencia_real,
        "neto": total_ventas - total_gastos,
        "clientes": clientes_total,
        "clientes_hoy": clientes_hoy,
        "producto_top": producto_top,
        "producto_top_cant": producto_top_cant,
    }
