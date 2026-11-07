from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from typing import Optional, Dict, Any, List

from ..database import get_db
from ..models.venta import Venta, DetalleVenta, Pago
from ..models.producto import Producto
from ..models.finanzas import CuentaPorCobrar, Abono, Gasto
from ..models.cliente import Cliente
from ..models.caja import SesionCaja, MovimientoCaja, MovimientoFinanciero
from ..models.nomina import Comision, Asistencia
from ..models.usuario import Usuario
from ..middleware.auth import get_current_user

router = APIRouter(prefix="/contabilidad", tags=["contabilidad"])


@router.get("/resumen-financiero")
async def get_resumen_financiero(
    fecha_inicio: Optional[str] = Query(None),
    fecha_fin: Optional[str] = Query(None),
    fecha: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> Dict[str, Any]:
    hoy_str = datetime.now().strftime("%Y-%m-%d")
    if fecha:
        fecha_inicio = fecha
        fecha_fin = fecha
    f_ini = fecha_inicio or hoy_str
    f_fin = fecha_fin or f_ini

    v_fecha = func.coalesce(Venta.fecha, func.date(Venta.created_at))

    # 1. Ventas activas
    res_act = await db.execute(
        select(func.sum(Venta.total), func.count(Venta.id)).where(
            v_fecha >= f_ini,
            v_fecha <= f_fin,
            Venta.estado != "Anulada",
            Venta.estado != "Pendiente_Caja",
        )
    )
    row_act = res_act.first()
    total_ventas = float((row_act[0] if row_act else 0.0) or 0.0)
    cant_ventas = int((row_act[1] if row_act else 0) or 0)
    ticket_promedio = (total_ventas / cant_ventas) if cant_ventas > 0 else 0.0

    # 2. Ventas anuladas
    res_anu = await db.execute(
        select(func.sum(Venta.total), func.count(Venta.id)).where(
            v_fecha >= f_ini,
            v_fecha <= f_fin,
            Venta.estado == "Anulada",
        )
    )
    row_anu = res_anu.first()
    total_anuladas = float((row_anu[0] if row_anu else 0.0) or 0.0)
    cant_anuladas = int((row_anu[1] if row_anu else 0) or 0)

    # 3. Desglose por método de pago
    res_pag = await db.execute(
        select(Pago.metodo, func.sum(Pago.monto))
        .join(Venta, Pago.venta_id == Venta.id)
        .where(
            v_fecha >= f_ini,
            v_fecha <= f_fin,
            Venta.estado != "Anulada",
            Venta.estado != "Pendiente_Caja",
        )
        .group_by(Pago.metodo)
    )
    metodos_map: Dict[str, float] = {}
    for m_raw, val in res_pag.all():
        m_norm = (m_raw or "Efectivo").strip().capitalize()
        metodos_map[m_norm] = metodos_map.get(m_norm, 0.0) + float(val or 0.0)

    efectivo_ventas = metodos_map.get("Efectivo", 0.0)
    transferencia_ventas = metodos_map.get("Transferencia", 0.0)
    fiado_ventas = metodos_map.get("Fiado", 0.0)

    # 4. Control de Caja Física
    res_mc = await db.execute(
        select(MovimientoCaja.tipo, func.sum(MovimientoCaja.monto))
        .where(MovimientoCaja.fecha >= f_ini, MovimientoCaja.fecha <= f_fin)
        .group_by(MovimientoCaja.tipo)
    )
    movs_caja = {t: float(val or 0.0) for t, val in res_mc.all()}

    base_inicial_caja = movs_caja.get("APERTURA", 0.0)
    ingresos_ventas_efectivo = movs_caja.get("VENTA_EFECTIVO", efectivo_ventas)
    ingresos_abonos_efectivo = movs_caja.get("ABONO_EFECTIVO", 0.0)
    egresos_caja = movs_caja.get("EGRESO", 0.0)
    retiros_caja = movs_caja.get("RETIRO", 0.0)
    devoluciones_caja = movs_caja.get("DEVOLUCION_VENTA", 0.0)
    ajustes_caja = movs_caja.get("AJUSTE", 0.0)

    efectivo_esperado_caja = (
        base_inicial_caja
        + ingresos_ventas_efectivo
        + ingresos_abonos_efectivo
        - egresos_caja
        - retiros_caja
        - devoluciones_caja
        + ajustes_caja
    )

    # Abonos en transferencia (Banco)
    ab_fecha = func.coalesce(Abono.fecha, func.date(Abono.created_at))
    res_ab_tr = await db.execute(
        select(func.sum(Abono.monto)).where(
            ab_fecha >= f_ini,
            ab_fecha <= f_fin,
            func.lower(Abono.metodo) != "efectivo",
        )
    )
    abonos_transferencia = float(res_ab_tr.scalar() or 0.0)

    # 5. Deuda global actual de clientes
    res_deuda = await db.execute(
        select(func.sum(CuentaPorCobrar.saldo_pendiente)).where(CuentaPorCobrar.estado == "Pendiente")
    )
    deuda_total_clientes = float(res_deuda.scalar() or 0.0)

    # 6. Desglose detallado por Operario
    users_res = await db.execute(select(Usuario))
    users_map = {
        u.id: (f"{u.nombre or ''} {u.apellidos or ''}".strip() or u.usuario)
        for u in users_res.scalars().all()
    }

    res_v_op = await db.execute(
        select(Venta).where(
            v_fecha >= f_ini,
            v_fecha <= f_fin,
            Venta.estado != "Anulada",
            Venta.estado != "Pendiente_Caja",
        )
    )
    op_stats: Dict[str, Dict[str, Any]] = {}
    for v in res_v_op.scalars().all():
        op_name = v.operario_nombre or users_map.get(v.usuario_id, f"Usuario {v.usuario_id}")
        entry = op_stats.setdefault(
            op_name,
            {
                "operario": op_name,
                "total_vendido": 0.0,
                "cant_ventas": 0,
                "efectivo": 0.0,
                "transferencia": 0.0,
                "fiado": 0.0,
            },
        )
        entry["total_vendido"] += float(v.total or 0.0)
        entry["cant_ventas"] += 1
        mp = (v.metodo_pago_principal or "Efectivo").strip().capitalize()
        if mp == "Efectivo":
            entry["efectivo"] += float(v.total or 0.0)
        elif mp == "Transferencia":
            entry["transferencia"] += float(v.total or 0.0)
        elif mp == "Fiado":
            entry["fiado"] += float(v.total or 0.0)

    operarios_list = sorted(op_stats.values(), key=lambda x: x["total_vendido"], reverse=True)

    suma_metodos = efectivo_ventas + transferencia_ventas + fiado_ventas
    diferencia_metodos = total_ventas - suma_metodos
    hay_inconsistencia_ventas = abs(diferencia_metodos) > 0.01

    return {
        "ventas_totales_facturadas": total_ventas,
        "cantidad_ventas": cant_ventas,
        "ganancia_neta_estimada": max(0.0, total_ventas - egresos_caja),
        "periodo": {"inicio": f_ini, "fin": f_fin},
        "ventas": {
            "total_ventas": total_ventas,
            "cant_ventas": cant_ventas,
            "ticket_promedio": ticket_promedio,
            "total_anuladas": total_anuladas,
            "cant_anuladas": cant_anuladas,
        },
        "metodos_pago": {
            "efectivo": efectivo_ventas,
            "transferencia": transferencia_ventas,
            "fiado": fiado_ventas,
            "abonos_efectivo": ingresos_abonos_efectivo,
            "abonos_transferencia": abonos_transferencia,
            "suma_metodos": suma_metodos,
            "inconsistencia": hay_inconsistencia_ventas,
            "diferencia": diferencia_metodos,
            "pct_efectivo": (efectivo_ventas / total_ventas * 100.0) if total_ventas > 0 else 0.0,
            "pct_transferencia": (transferencia_ventas / total_ventas * 100.0) if total_ventas > 0 else 0.0,
            "pct_fiado": (fiado_ventas / total_ventas * 100.0) if total_ventas > 0 else 0.0,
        },
        "caja_fisica": {
            "base_inicial": base_inicial_caja,
            "ventas_efectivo": ingresos_ventas_efectivo,
            "abonos_efectivo": ingresos_abonos_efectivo,
            "egresos": egresos_caja,
            "retiros": retiros_caja,
            "devoluciones": devoluciones_caja,
            "ajustes": ajustes_caja,
            "efectivo_esperado": efectivo_esperado_caja,
        },
        "cartera": {"total_deuda_clientes": deuda_total_clientes},
        "operarios": operarios_list,
    }


@router.get("/metricas")
async def get_metricas_contables(
    fecha_inicio: Optional[str] = Query(None),
    fecha_fin: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> Dict[str, Any]:
    hoy_str = datetime.now().strftime("%Y-%m-%d")
    f_ini = fecha_inicio or hoy_str
    f_fin = fecha_fin or f_ini

    v_fecha = func.coalesce(Venta.fecha, func.date(Venta.created_at))
    g_fecha = func.coalesce(Gasto.fecha, func.date(Gasto.created_at))
    ab_fecha = func.coalesce(Abono.fecha, func.date(Abono.created_at))

    # 1. Ventas activas y anuladas
    r_act = (
        await db.execute(
            select(func.sum(Venta.total), func.count(Venta.id)).where(
                v_fecha >= f_ini,
                v_fecha <= f_fin,
                Venta.estado != "Anulada",
                Venta.estado != "Pendiente_Caja",
            )
        )
    ).first()
    ventas_activas = float((r_act[0] if r_act else 0.0) or 0.0)
    cant_activas = int((r_act[1] if r_act else 0) or 0)

    r_anu = (
        await db.execute(
            select(func.sum(Venta.total), func.count(Venta.id)).where(
                v_fecha >= f_ini,
                v_fecha <= f_fin,
                Venta.estado == "Anulada",
            )
        )
    ).first()
    ventas_anuladas = float((r_anu[0] if r_anu else 0.0) or 0.0)
    cant_anuladas = int((r_anu[1] if r_anu else 0) or 0)

    ventas_brutas = ventas_activas + ventas_anuladas
    ventas_netas = ventas_activas
    ticket_promedio = (ventas_netas / cant_activas) if cant_activas > 0 else 0.0

    # 2. Métodos de pago en ventas netas
    res_mp = await db.execute(
        select(Pago.metodo, func.sum(Pago.monto))
        .join(Venta, Pago.venta_id == Venta.id)
        .where(
            v_fecha >= f_ini,
            v_fecha <= f_fin,
            Venta.estado != "Anulada",
            Venta.estado != "Pendiente_Caja",
        )
        .group_by(Pago.metodo)
    )
    map_metodos: Dict[str, float] = {}
    for m_raw, val in res_mp.all():
        m_norm = (m_raw or "Efectivo").strip().capitalize()
        map_metodos[m_norm] = map_metodos.get(m_norm, 0.0) + float(val or 0.0)

    ventas_efectivo = map_metodos.get("Efectivo", 0.0)
    ventas_transferencia = map_metodos.get("Transferencia", 0.0)
    ventas_fiado = map_metodos.get("Fiado", 0.0)

    # 3. Costo de Mercancía Vendida (COGS) histórico
    res_cogs = await db.execute(
        select(func.sum(DetalleVenta.cantidad * func.coalesce(DetalleVenta.costo_unitario, 0.0)))
        .join(Venta, DetalleVenta.venta_id == Venta.id)
        .where(
            v_fecha >= f_ini,
            v_fecha <= f_fin,
            Venta.estado != "Anulada",
            Venta.estado != "Pendiente_Caja",
            DetalleVenta.tipo_item == "Producto",
        )
    )
    cogs_total = float(res_cogs.scalar() or 0.0)
    utilidad_bruta = max(0.0, ventas_netas - cogs_total)
    margen_bruto_pct = (utilidad_bruta / ventas_netas * 100.0) if ventas_netas > 0 else 0.0

    # 4. Gastos Operativos desglosados en 4 categorías
    gastos_por_cat = {
        "Operativo diario": 0.0,
        "Fijo periódico": 0.0,
        "Variable": 0.0,
        "Extraordinario": 0.0,
    }
    gastos_pagados = 0.0
    gastos_pendientes = 0.0
    gastos_transferencia = 0.0

    res_g = await db.execute(
        select(Gasto).where(
            g_fecha >= f_ini,
            g_fecha <= f_fin,
            func.coalesce(Gasto.estado, "Pagado") != "Anulado",
        )
    )
    gastos_rows = res_g.scalars().all()
    for g in gastos_rows:
        cat_name = (g.categoria or g.clasificacion or "Operativo diario").lower()
        val = float(g.valor or 0.0)
        est = g.estado or "Pagado"
        if "fijo" in cat_name:
            cat_std = "Fijo periódico"
        elif "variable" in cat_name:
            cat_std = "Variable"
        elif "extraordinario" in cat_name or "imprevisto" in cat_name:
            cat_std = "Extraordinario"
        else:
            cat_std = "Operativo diario"

        gastos_por_cat[cat_std] = gastos_por_cat.get(cat_std, 0.0) + val
        if est == "Pagado":
            gastos_pagados += val
            if (g.metodo_pago or "").strip().lower() == "transferencia":
                gastos_transferencia += val
        else:
            gastos_pendientes += val

    total_gastos = sum(gastos_por_cat.values())

    # 5. Comisiones / Nómina devengada en el período
    c_fecha = func.date(Comision.created_at)
    res_com = await db.execute(
        select(func.sum(Comision.monto_comision)).where(
            c_fecha >= f_ini,
            c_fecha <= f_fin,
            Comision.estado != "Anulada",
        )
    )
    comisiones_dev = float(res_com.scalar() or 0.0)

    a_fecha = func.date(Asistencia.fecha)
    res_sal = await db.execute(
        select(func.sum(Asistencia.salario_generado)).where(
            a_fecha >= f_ini,
            a_fecha <= f_fin,
        )
    )
    salarios_dev = float(res_sal.scalar() or 0.0)
    comisiones_totales = round(comisiones_dev + salarios_dev, 2)

    metricas_nomina = {
        "gasto_personal_devengado": comisiones_totales,
        "salarios_devengados": salarios_dev,
        "comisiones_devengadas": comisiones_dev,
        "ajustes_devengados": 0.0,
        "pagos_nomina_realizados": 0.0,
        "pagos_efectivo": 0.0,
        "pagos_transferencia": 0.0,
        "obligaciones_pendientes": comisiones_totales,
    }

    utilidad_operacional_neta = utilidad_bruta - total_gastos - comisiones_totales
    margen_neto_pct = (utilidad_operacional_neta / ventas_netas * 100.0) if ventas_netas > 0 else 0.0

    # 6. Flujo de Caja Física y Abonos
    res_mc = await db.execute(
        select(MovimientoCaja.tipo, func.sum(MovimientoCaja.monto))
        .where(MovimientoCaja.fecha >= f_ini, MovimientoCaja.fecha <= f_fin)
        .group_by(MovimientoCaja.tipo)
    )
    movs = {t: float(val or 0.0) for t, val in res_mc.all()}
    apertura_caja = movs.get("APERTURA", 0.0)
    ingresos_ventas_efectivo = movs.get("VENTA_EFECTIVO", ventas_efectivo)
    ingresos_abonos_cartera = movs.get("ABONO_EFECTIVO", 0.0)
    egresos_caja = movs.get("EGRESO", 0.0)
    retiros_caja = movs.get("RETIRO", 0.0)
    devoluciones_caja = movs.get("DEVOLUCION_VENTA", 0.0)
    ajustes_caja = movs.get("AJUSTE", 0.0)

    efectivo_esperado_caja = (
        apertura_caja
        + ingresos_ventas_efectivo
        + ingresos_abonos_cartera
        - egresos_caja
        - retiros_caja
        - devoluciones_caja
        + ajustes_caja
    )

    res_ab_tr = await db.execute(
        select(func.sum(Abono.monto)).where(
            ab_fecha >= f_ini,
            ab_fecha <= f_fin,
            func.lower(Abono.metodo) != "efectivo",
        )
    )
    abonos_transferencia = float(res_ab_tr.scalar() or 0.0)

    # 7. Diferencia de Caja acumulada
    res_dif = await db.execute(
        select(func.sum(SesionCaja.diferencia)).where(
            SesionCaja.fecha_cierre.isnot(None),
            SesionCaja.fecha_apertura >= f_ini,
            SesionCaja.fecha_apertura <= f_fin,
        )
    )
    diferencia_caja_acumulada = float(res_dif.scalar() or 0.0)

    # 8. Cartera y Deudores desde CuentaPorCobrar + Cliente
    res_cxc_tot = await db.execute(
        select(func.sum(CuentaPorCobrar.saldo_pendiente)).where(CuentaPorCobrar.estado == "Pendiente")
    )
    saldo_cartera_pendiente = round(float(res_cxc_tot.scalar() or 0.0), 2)

    res_deudores = await db.execute(
        select(
            Cliente.documento,
            Cliente.nombre,
            Cliente.telefono,
            func.sum(CuentaPorCobrar.saldo_pendiente).label("saldo"),
        )
        .join(CuentaPorCobrar, CuentaPorCobrar.cliente_id == Cliente.id)
        .where(CuentaPorCobrar.estado == "Pendiente", CuentaPorCobrar.saldo_pendiente > 0)
        .group_by(Cliente.id, Cliente.documento, Cliente.nombre, Cliente.telefono)
        .order_by(func.sum(CuentaPorCobrar.saldo_pendiente).desc())
        .limit(15)
    )
    top_deudores = [
        {
            "cedula": doc,
            "documento": doc,
            "nombre": nom,
            "telefono": tel or "",
            "saldo_pendiente": round(float(sal or 0.0), 2),
        }
        for doc, nom, tel, sal in res_deudores.all()
    ]

    # 9. Rendimiento por Operario
    users_res = await db.execute(select(Usuario))
    users_map = {
        u.id: (f"{u.nombre or ''} {u.apellidos or ''}".strip() or u.usuario)
        for u in users_res.scalars().all()
    }
    res_v_list = await db.execute(
        select(Venta).where(
            v_fecha >= f_ini,
            v_fecha <= f_fin,
            Venta.estado != "Anulada",
            Venta.estado != "Pendiente_Caja",
        )
    )
    ventas_periodo = res_v_list.scalars().all()

    op_map: Dict[str, Dict[str, Any]] = {}
    diarias_map: Dict[str, Dict[str, Any]] = {}
    for v in ventas_periodo:
        op_name = v.operario_nombre or users_map.get(v.usuario_id, f"Usuario {v.usuario_id}")
        st = op_map.setdefault(
            op_name,
            {
                "operario": op_name,
                "total_vendido": 0.0,
                "cant_ventas": 0,
                "efectivo": 0.0,
                "transferencia": 0.0,
                "fiado": 0.0,
            },
        )
        tot_v = float(v.total or 0.0)
        st["total_vendido"] += tot_v
        st["cant_ventas"] += 1
        mp = (v.metodo_pago_principal or "Efectivo").strip().capitalize()
        if mp == "Efectivo":
            st["efectivo"] += tot_v
        elif mp == "Transferencia":
            st["transferencia"] += tot_v
        elif mp == "Fiado":
            st["fiado"] += tot_v

        f_key = v.fecha or (v.created_at.strftime("%Y-%m-%d") if v.created_at else f_ini)
        d_item = diarias_map.setdefault(f_key, {"fecha": f_key, "total": 0.0, "cantidad": 0})
        d_item["total"] += tot_v
        d_item["cantidad"] += 1

    operarios_stats = sorted(op_map.values(), key=lambda x: x["total_vendido"], reverse=True)

    ventas_diarias = []
    for f_key in sorted(diarias_map.keys()):
        d = diarias_map[f_key]
        try:
            d_label = datetime.strptime(f_key, "%Y-%m-%d").strftime("%d %b")
        except Exception:
            d_label = f_key[-5:]
        ventas_diarias.append(
            {
                "fecha": f_key,
                "dia_label": d_label,
                "total": d["total"],
                "cantidad": d["cantidad"],
            }
        )

    dia_mejor = max(ventas_diarias, key=lambda x: x["total"]) if ventas_diarias else None
    dia_peor = min(ventas_diarias, key=lambda x: x["total"]) if len(ventas_diarias) >= 2 else None

    # 10. Top 15 productos/servicios más vendidos
    res_top = await db.execute(
        select(
            DetalleVenta.item_codigo,
            DetalleVenta.item_nombre,
            func.sum(DetalleVenta.cantidad),
            func.sum(DetalleVenta.subtotal),
            func.sum(DetalleVenta.cantidad * func.coalesce(DetalleVenta.costo_unitario, 0.0)),
        )
        .join(Venta, DetalleVenta.venta_id == Venta.id)
        .where(
            v_fecha >= f_ini,
            v_fecha <= f_fin,
            Venta.estado != "Anulada",
            Venta.estado != "Pendiente_Caja",
        )
        .group_by(DetalleVenta.item_codigo, DetalleVenta.item_nombre)
        .order_by(func.sum(DetalleVenta.subtotal).desc())
        .limit(15)
    )
    top_productos = []
    for cod, nom, unid, tf_raw, ct_raw in res_top.all():
        tf = float(tf_raw or 0.0)
        ct = float(ct_raw or 0.0)
        gan = tf - ct
        mg = (gan / tf * 100.0) if tf > 0 else 0.0
        top_productos.append(
            {
                "codigo": cod,
                "nombre": nom,
                "unidades": int(round(float(unid or 0.0))),
                "facturado": tf,
                "costo": ct,
                "ganancia": gan,
                "margen_pct": mg,
            }
        )
    top_utilidad_productos = sorted(top_productos, key=lambda x: x["ganancia"], reverse=True)[:5]

    gastos_mayores = [
        {
            "id_gasto": g.id,
            "concepto": g.concepto,
            "valor": float(g.valor or 0.0),
            "fecha": g.fecha or "",
            "categoria": g.categoria or "Operativo diario",
            "estado": g.estado or "Pagado",
        }
        for g in sorted(gastos_rows, key=lambda x: float(x.valor or 0.0), reverse=True)[:5]
    ]

    res_low = await db.execute(
        select(Producto)
        .where(Producto.estado == "Activo", Producto.stock <= 5)
        .order_by(Producto.stock.asc())
        .limit(10)
    )
    productos_stock_bajo = [
        {
            "codigo": p.codigo,
            "nombre": p.nombre,
            "stock": float(p.stock or 0.0),
            "precio": float(p.precio_venta or 0.0),
            "costo": float(p.precio_costo or 0.0),
        }
        for p in res_low.scalars().all()
    ]

    # 11. Bancos y Valor de Inventario
    res_banco = await db.execute(
        select(
            func.sum(SesionCaja.monto_transferencias_esperado),
            func.sum(SesionCaja.monto_transferencias_verificado),
            func.sum(SesionCaja.diferencia_banco),
        ).where(
            SesionCaja.fecha_apertura >= f_ini,
            SesionCaja.fecha_apertura <= f_fin,
        )
    )
    rb = res_banco.first()
    banco_verificado = float((rb[1] if rb else 0.0) or 0.0)
    flujo_banco_calculado = ventas_transferencia + abonos_transferencia - gastos_transferencia
    dinero_bancos = flujo_banco_calculado if banco_verificado == 0.0 else banco_verificado

    res_val_inv = await db.execute(
        select(func.sum(Producto.stock * func.coalesce(Producto.precio_costo, 0.0))).where(
            Producto.estado == "Activo",
            Producto.stock > 0,
        )
    )
    valor_inventario = float(res_val_inv.scalar() or 0.0)

    conceptos_22 = [
        {"numero": 1, "codigo": "ING-01", "concepto": "1. Ingresos Brutos por Ventas", "valor": ventas_brutas, "tipo": "Ingreso", "descripcion": "Facturación total generada (activas + anuladas)."},
        {"numero": 2, "codigo": "DEV-02", "concepto": "2. Devoluciones y Ventas Anuladas", "valor": -ventas_anuladas, "tipo": "Deducción", "descripcion": "Ventas canceladas o revertidas con retorno a inventario."},
        {"numero": 3, "codigo": "ING-03", "concepto": "3. Ingresos Netos Operacionales", "valor": ventas_netas, "tipo": "Ingreso Neto", "descripcion": "Facturación real efectiva después de cancelaciones."},
        {"numero": 4, "codigo": "COS-04", "concepto": "4. Costo de Mercancía Vendida (COGS)", "valor": -cogs_total, "tipo": "Costo", "descripcion": "Costo real de compra de los productos físicos facturados."},
        {"numero": 5, "codigo": "UTI-05", "concepto": "5. Utilidad Bruta Comercial", "valor": utilidad_bruta, "tipo": "Resultado", "descripcion": "Ganancia antes de descontar gastos operativos."},
        {"numero": 6, "codigo": "MAR-06", "concepto": "6. Margen Bruto Comercial (%)", "valor": margen_bruto_pct, "tipo": "Porcentaje", "descripcion": "Porcentaje de beneficio bruto sobre ingresos netos."},
        {"numero": 7, "codigo": "GAS-07", "concepto": "7. Gastos Operativos Diarios", "valor": -gastos_por_cat.get("Operativo diario", 0.0), "tipo": "Gasto", "descripcion": "Consumibles, insumos menores, transporte y aseo."},
        {"numero": 8, "codigo": "GAS-08", "concepto": "8. Gastos Fijos Periódicos", "valor": -gastos_por_cat.get("Fijo periódico", 0.0), "tipo": "Gasto", "descripcion": "Arriendo, servicios públicos, suscripciones fijas."},
        {"numero": 9, "codigo": "GAS-09", "concepto": "9. Gastos Variables", "valor": -gastos_por_cat.get("Variable", 0.0), "tipo": "Gasto", "descripcion": "Mantenimientos, publicidad, comisiones externas."},
        {"numero": 10, "codigo": "GAS-10", "concepto": "10. Gastos Extraordinarios / Imprevistos", "valor": -gastos_por_cat.get("Extraordinario", 0.0), "tipo": "Gasto", "descripcion": "Reparaciones urgentes o contingencias no habituales."},
        {"numero": 11, "codigo": "GAS-11", "concepto": "11. Total Gastos Operacionales", "valor": -total_gastos, "tipo": "Gasto Total", "descripcion": "Suma de los 4 rubros de gastos en el período."},
        {"numero": 12, "codigo": "UTI-12", "concepto": "12. Utilidad Antes de Nómina y Comisiones", "valor": utilidad_bruta - total_gastos, "tipo": "Resultado", "descripcion": "Beneficio comercial disponible para remuneración laboral."},
        {"numero": 13, "codigo": "NOM-13", "concepto": "13. Gastos de Personal y Comisiones", "valor": -comisiones_totales, "tipo": "Gasto Laboral", "descripcion": "Comisiones sobre servicios y salarios devengados."},
        {"numero": 14, "codigo": "UTI-14", "concepto": "14. Utilidad Operacional Neta Final", "valor": utilidad_operacional_neta, "tipo": "Resultado Final", "descripcion": "Ganancia líquida real del negocio en el período analizado."},
        {"numero": 15, "codigo": "MAR-15", "concepto": "15. Margen Neto Operacional (%)", "valor": margen_neto_pct, "tipo": "Porcentaje", "descripcion": "Rentabilidad neta final sobre las ventas netas."},
        {"numero": 16, "codigo": "FLU-16", "concepto": "16. Ventas Recaudadas en Efectivo", "valor": ventas_efectivo, "tipo": "Flujo Efectivo", "descripcion": "Entrada directa a la gaveta física de caja."},
        {"numero": 17, "codigo": "BAN-17", "concepto": "17. Ventas en Bancos / Transferencias", "valor": ventas_transferencia, "tipo": "Flujo Digital", "descripcion": "Recaudos vía Nequi, Daviplata o transferencias bancarias."},
        {"numero": 18, "codigo": "FIA-18", "concepto": "18. Ventas Otorgadas a Crédito (Fiados)", "valor": ventas_fiado, "tipo": "Cartera", "descripcion": "Ventas facturadas pendientes de pago por clientes (sin ingreso de dinero)."},
        {"numero": 19, "codigo": "ABO-19", "concepto": "19. Recaudos de Cartera (Abonos Recibidos)", "valor": ingresos_abonos_cartera + abonos_transferencia, "tipo": "Flujo Cartera", "descripcion": f"Cobros de fiados: Efectivo ${ingresos_abonos_cartera:,.0f} | Transferencia ${abonos_transferencia:,.0f}."},
        {"numero": 20, "codigo": "SAL-20", "concepto": "20. Saldo Total Cuentas por Cobrar", "valor": saldo_cartera_pendiente, "tipo": "Cartera Global", "descripcion": "Deuda viva acumulada de todos los clientes fiadores."},
        {"numero": 21, "codigo": "CAJ-21", "concepto": "21. Efectivo Físico Esperado en Caja", "valor": efectivo_esperado_caja, "tipo": "Tesorería", "descripcion": "Saldo que debe existir físicamente en gaveta (Base + Efectivo - Egresos)."},
        {"numero": 22, "codigo": "DIF-22", "concepto": "22. Diferencia Acumulada de Arqueos", "valor": diferencia_caja_acumulada, "tipo": "Control", "descripcion": "Suma de sobrantes (+) o faltantes (-) reportados en cierres."},
    ]

    tarjetas_kpi = {
        "A_ventas_netas": ventas_netas,
        "B_costo_ventas": cogs_total,
        "C_utilidad_bruta": utilidad_bruta,
        "D_gastos_operativos": total_gastos,
        "E_utilidad_operacional_neta": utilidad_operacional_neta,
        "F_margen_neto_pct": margen_neto_pct,
        "G_efectivo_en_caja": efectivo_esperado_caja,
        "H_cuentas_por_cobrar": saldo_cartera_pendiente,
        "I_dinero_en_bancos": dinero_bancos,
        "J_valor_inventario": valor_inventario,
    }

    return {
        "periodo": {"inicio": f_ini, "fin": f_fin},
        "kpis": tarjetas_kpi,
        "valor_inventario": valor_inventario,
        "conceptos_22": conceptos_22,
        "ventas_diarias": ventas_diarias,
        "analisis_negocio": {
            "dia_mejor": dia_mejor,
            "dia_peor": dia_peor,
            "gastos_mayores": gastos_mayores,
            "productos_stock_bajo": productos_stock_bajo,
            "top_utilidad_productos": top_utilidad_productos,
            "rentabilidad_bruta_pct": margen_bruto_pct,
            "rentabilidad_neta_pct": margen_neto_pct,
        },
        "resumen_ventas": {
            "ventas_brutas": ventas_brutas,
            "ventas_anuladas": ventas_anuladas,
            "ventas_netas": ventas_netas,
            "cant_activas": cant_activas,
            "cant_anuladas": cant_anuladas,
            "ticket_promedio": ticket_promedio,
            "efectivo": ventas_efectivo,
            "transferencia": ventas_transferencia,
            "fiado": ventas_fiado,
            "pct_efectivo": (ventas_efectivo / ventas_netas * 100.0) if ventas_netas > 0 else 0.0,
            "pct_transferencia": (ventas_transferencia / ventas_netas * 100.0) if ventas_netas > 0 else 0.0,
            "pct_fiado": (ventas_fiado / ventas_netas * 100.0) if ventas_netas > 0 else 0.0,
        },
        "caja_fisica": {
            "base_inicial": apertura_caja,
            "ingresos_ventas": ingresos_ventas_efectivo,
            "abonos_cartera": ingresos_abonos_cartera,
            "egresos_gastos": egresos_caja,
            "retiros": retiros_caja,
            "devoluciones": devoluciones_caja,
            "ajustes": ajustes_caja,
            "efectivo_esperado": efectivo_esperado_caja,
            "diferencia_acumulada": diferencia_caja_acumulada,
        },
        "gastos": {
            "total": total_gastos,
            "por_categoria": gastos_por_cat,
            "pagados": gastos_pagados,
            "pendientes": gastos_pendientes,
        },
        "comisiones_nomina": comisiones_totales,
        "nomina": metricas_nomina,
        "operarios": operarios_stats,
        "top_productos": top_productos,
        "top_deudores": top_deudores,
        "bancos": {
            "ventas_transferencia": ventas_transferencia,
            "abonos_transferencia": abonos_transferencia,
            "gastos_transferencia": gastos_transferencia,
            "verificado_sesiones": banco_verificado,
            "saldo_estimado": dinero_bancos,
        },
    }
