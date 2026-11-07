import json
import os
import sqlite3
from datetime import datetime
from typing import Dict, Any, List
from sqlalchemy.future import select
from sqlalchemy import func

from .. import database as db_mod
from ..models.producto import Producto
from ..models.servicio import Servicio
from ..models.proveedor import Proveedor
from ..models.cliente import Cliente
from ..models.venta import Venta, Pago
from ..models.finanzas import CuentaPorCobrar, Abono, MovimientoCuentaCliente


def _resolver_rutas_auditoria():
    try:
        from interface.config import DB_VENTAS_PATH, LOGS_DIR
        return DB_VENTAS_PATH, LOGS_DIR
    except Exception:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(root, "database", "ventas.db"), os.path.join(root, "logs")


async def sincronizar_y_auditar_datos_historicos() -> Dict[str, Any]:
    """
    1. Migra de forma aditiva (sin borrar nada) proveedores, productos y servicios
       existentes en la SQLite local del equipo servidor hacia la base central si aún no existen.
    2. Audita datos históricos en la base central y en la SQLite local histórica, detectando:
       - Ventas FIADO sin CuentaPorCobrar asociada.
       - Ventas FIADO sin cliente válido (ambiguas — NUNCA se inventan ni asignan deudas).
       - Posibles ventas duplicadas (mismo total, usuario/operario, método y minuto).
       - Diferencias entre saldo pendiente y movimientos contables registrados.
    3. Guarda el informe trazable en `<LOGS_DIR>/informe_integridad_datos.json`.
    """
    db_ventas_local, logs_dir = _resolver_rutas_auditoria()
    os.makedirs(logs_dir, exist_ok=True)
    ruta_informe = os.path.join(logs_dir, "informe_integridad_datos.json")

    informe: Dict[str, Any] = {
        "generado_en": datetime.now().isoformat(),
        "politica_aplicada": (
            "Cero borrado de ventas, clientes o inventario. "
            "No se asignan deudas automáticamente cuando falta evidencia inequívoca de cliente_id."
        ),
        "migracion_aditiva_catalogo": {
            "proveedores_migrados": 0,
            "productos_migrados": 0,
            "servicios_migrados": 0,
        },
        "central_db": {
            "ventas_fiado_sin_cxc_ambiguas": [],
            "ventas_fiado_reparadas_con_evidencia_exacta": [],
            "ventas_sin_cliente_valido": [],
            "posibles_ventas_duplicadas": [],
            "diferencias_saldo_vs_movimientos": [],
        },
        "sqlite_local_historica": {
            "ruta": db_ventas_local,
            "existe": os.path.exists(db_ventas_local),
            "ventas_fiado_historicas_sin_cxc_central": [],
            "posibles_ventas_duplicadas_locales": [],
        },
    }

    # ------------------------------------------------------------------
    # PASO 1: Migración aditiva de proveedores y catálogo desde ventas.db
    # (solo si existen registros en el servidor local que aún no están en central)
    # ------------------------------------------------------------------
    if os.path.exists(db_ventas_local):
        try:
            conn = sqlite3.connect(db_ventas_local, timeout=5)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tablas = {r[0] for r in cur.fetchall()}

            async with db_mod.SessionLocal() as session:
                prov_map_local_to_central: Dict[int, int] = {}
                if "proveedores" in tablas:
                    cur.execute("SELECT * FROM proveedores")
                    for pr in cur.fetchall():
                        pd = dict(pr)
                        nom = str(pd.get("nombre") or "").strip()
                        if not nom:
                            continue
                        ex_p = (
                            await session.execute(select(Proveedor).where(Proveedor.nombre.ilike(nom)))
                        ).scalars().first()
                        if not ex_p:
                            ex_p = Proveedor(
                                nombre=nom,
                                documento_nit=str(pd.get("nit_documento") or pd.get("documento_nit") or ""),
                                telefono=str(pd.get("telefono") or ""),
                                email=str(pd.get("correo") or pd.get("email") or ""),
                                direccion=str(pd.get("direccion") or ""),
                                contacto=str(pd.get("contacto") or ""),
                                estado="Activo" if pd.get("activo", 1) in (1, True, "Activo") else "Inactivo",
                            )
                            session.add(ex_p)
                            await session.flush()
                            informe["migracion_aditiva_catalogo"]["proveedores_migrados"] += 1
                        if pd.get("id") is not None:
                            prov_map_local_to_central[int(pd["id"])] = ex_p.id

                if "productos" in tablas:
                    cur.execute("SELECT * FROM productos")
                    for row in cur.fetchall():
                        d = dict(row)
                        cod = str(d.get("codigo") or "").strip()
                        nom = str(d.get("nombre") or "").strip()
                        if not cod or not nom:
                            continue
                        tipo = str(d.get("tipo_producto") or d.get("tipo") or "Producto").strip()
                        prov_local_id = d.get("proveedor_id")
                        prov_central_id = (
                            prov_map_local_to_central.get(int(prov_local_id))
                            if prov_local_id is not None
                            else None
                        )
                        activo_flag = d.get("activo", 1)
                        estado_str = "Activo" if activo_flag in (1, True, "1", "Activo") else "Inactivo"

                        if tipo.lower() == "servicio":
                            ex_s = (
                                await session.execute(select(Servicio).where(Servicio.codigo == cod))
                            ).scalars().first()
                            if not ex_s:
                                session.add(
                                    Servicio(
                                        codigo=cod,
                                        codigo_barras=str(d.get("codigo_barras") or "").strip() or None,
                                        nombre=nom,
                                        descripcion=str(d.get("descripcion") or ""),
                                        categoria=str(d.get("categoria") or "Servicios"),
                                        marca=str(d.get("marca") or ""),
                                        unidad_medida=str(d.get("unidad_medida") or "Servicio"),
                                        precio_venta=float(d.get("precio") or 0.0),
                                        costo_proveedor=float(d.get("costo") or 0.0),
                                        precio_variable=bool(d.get("precio_variable") or False),
                                        proveedor_id=prov_central_id,
                                        porcentaje_comision=float(d.get("porcentaje_comision") or 0.0),
                                        genera_comision=prov_central_id is None,
                                        estado=estado_str,
                                    )
                                )
                                informe["migracion_aditiva_catalogo"]["servicios_migrados"] += 1
                        else:
                            ex_pr = (
                                await session.execute(select(Producto).where(Producto.codigo == cod))
                            ).scalars().first()
                            if not ex_pr:
                                sb = float(d.get("stock_bodega") or 0.0)
                                sv = float(d.get("stock_vitrina") or 0.0)
                                st = float(d.get("stock") or 0.0)
                                if sb == 0.0 and sv == 0.0 and st > 0.0:
                                    sv = st
                                session.add(
                                    Producto(
                                        codigo=cod,
                                        codigo_barras=str(d.get("codigo_barras") or "").strip() or None,
                                        nombre=nom,
                                        descripcion=str(d.get("descripcion") or ""),
                                        categoria=str(d.get("categoria") or "General"),
                                        marca=str(d.get("marca") or ""),
                                        unidad_medida=str(d.get("unidad_medida") or "Unidad"),
                                        precio_costo=float(d.get("costo") or 0.0),
                                        precio_venta=float(d.get("precio") or 0.0),
                                        precio_mayorista=0.0,
                                        stock_bodega=sb,
                                        stock_vitrina=sv,
                                        stock=round(sb + sv, 4),
                                        stock_minimo=float(d.get("stock_minimo") or 5.0),
                                        stock_minimo_bodega=float(d.get("stock_minimo_bodega") or 5.0),
                                        stock_minimo_vitrina=float(d.get("stock_minimo_vitrina") or 2.0),
                                        precio_variable=bool(d.get("precio_variable") or False),
                                        proveedor_id=prov_central_id,
                                        porcentaje_comision=float(d.get("porcentaje_comision") or 0.0),
                                        estado=estado_str,
                                    )
                                )
                                informe["migracion_aditiva_catalogo"]["productos_migrados"] += 1

                await session.commit()

            # Auditar ventas históricas locales en ventas.db (SOLO LECTURA, sin inventar deudas)
            if "ventas" in tablas:
                cur.execute("SELECT * FROM ventas ORDER BY id_venta ASC")
                ventas_locales = [dict(r) for r in cur.fetchall()]
                vistas_firma: Dict[str, List[int]] = {}
                for vl in ventas_locales:
                    vid = vl.get("id_venta")
                    mp = str(vl.get("metodo_pago") or "")
                    est = str(vl.get("estado") or "Completada")
                    doc = str(vl.get("documento_cliente") or "").strip()
                    cli_id_loc = vl.get("cliente_id")
                    tot = float(vl.get("total_venta") or 0.0)
                    f_v = str(vl.get("fecha_venta") or "")
                    h_v = str(vl.get("hora_venta") or "")[:5]  # HH:MM
                    op = str(vl.get("operario") or "")

                    if mp.lower() == "fiado" and est != "Anulada":
                        informe["sqlite_local_historica"]["ventas_fiado_historicas_sin_cxc_central"].append(
                            {
                                "id_venta_local": vid,
                                "fecha_venta": f_v,
                                "hora_venta": vl.get("hora_venta"),
                                "total_venta": tot,
                                "documento_cliente": doc,
                                "cliente_id_local": cli_id_loc,
                                "operario": op,
                                "accion_aplicada": (
                                    "NINGUNA (conservada intacta en ventas.db y respaldo; "
                                    "no se crea deuda automática por falta de vínculo transaccional verificado)"
                                ),
                            }
                        )

                    if est != "Anulada":
                        firma = f"{f_v}|{h_v}|{op}|{mp}|{tot:.2f}"
                        vistas_firma.setdefault(firma, []).append(vid)

                for firma, ids in vistas_firma.items():
                    if len(ids) > 1:
                        informe["sqlite_local_historica"]["posibles_ventas_duplicadas_locales"].append(
                            {"firma_minuto_operario_monto": firma, "ids_venta_local": ids}
                        )

            conn.close()
        except Exception as e_loc:
            informe["sqlite_local_historica"]["error_lectura"] = str(e_loc)

    # ------------------------------------------------------------------
    # PASO 2: Auditoría de integridad sobre la base central (vmpos_server.db / PostgreSQL)
    # ------------------------------------------------------------------
    try:
        async with db_mod.SessionLocal() as session:
            clientes_res = await session.execute(select(Cliente))
            clientes_map = {c.id: c for c in clientes_res.scalars().all()}

            ventas_res = await session.execute(select(Venta).order_by(Venta.id.asc()))
            ventas_central = ventas_res.scalars().all()

            firmas_central: Dict[str, List[int]] = {}
            for v in ventas_central:
                if v.estado == "Anulada":
                    continue

                pags_res = await session.execute(select(Pago).where(Pago.venta_id == v.id))
                pags = pags_res.scalars().all()
                monto_fiado = round(
                    sum(float(p.monto or 0.0) for p in pags if (p.metodo or "").strip().lower() == "fiado"),
                    2,
                )

                if v.cliente_id and v.cliente_id not in clientes_map:
                    informe["central_db"]["ventas_sin_cliente_valido"].append(
                        {
                            "venta_id": v.id,
                            "numero": v.numero,
                            "cliente_id_inexistente": v.cliente_id,
                            "total": v.total,
                        }
                    )

                if monto_fiado > 0 and v.estado == "Completada":
                    cxc_res = await session.execute(
                        select(CuentaPorCobrar).where(CuentaPorCobrar.venta_id == v.id)
                    )
                    cxc = cxc_res.scalars().first()
                    if not cxc:
                        informe["central_db"]["ventas_fiado_sin_cxc_ambiguas"].append(
                            {
                                "venta_id": v.id,
                                "numero": v.numero,
                                "cliente_id": v.cliente_id,
                                "cliente_documento": v.cliente_documento,
                                "monto_fiado": monto_fiado,
                                "accion_aplicada": "Reportada para revisión manual sin alterar saldos automáticamente",
                            }
                        )

                f_s = v.fecha or (v.created_at.strftime("%Y-%m-%d") if v.created_at else "")
                h_s = (v.hora or (v.created_at.strftime("%H:%M:%S") if v.created_at else ""))[:5]
                firma = f"{f_s}|{h_s}|{v.usuario_id}|{v.total:.2f}"
                firmas_central.setdefault(firma, []).append(v.id)

            for firma, ids in firmas_central.items():
                if len(ids) > 1:
                    informe["central_db"]["posibles_ventas_duplicadas"].append(
                        {"firma_minuto_usuario_monto": firma, "venta_ids": ids}
                    )

            # Verificar consistencia entre saldo CuentaPorCobrar y último MovimientoCuentaCliente por cliente
            for cid, cli in clientes_map.items():
                res_s = await session.execute(
                    select(func.sum(CuentaPorCobrar.saldo_pendiente)).where(
                        CuentaPorCobrar.cliente_id == cid,
                        CuentaPorCobrar.estado == "Pendiente",
                    )
                )
                saldo_cxc = round(float(res_s.scalar() or 0.0), 2)

                res_ult_mov = await session.execute(
                    select(MovimientoCuentaCliente)
                    .where(MovimientoCuentaCliente.cliente_id == cid)
                    .order_by(MovimientoCuentaCliente.id.desc())
                    .limit(1)
                )
                ult_mov = res_ult_mov.scalars().first()
                saldo_ledger = round(float(ult_mov.saldo_nuevo), 2) if ult_mov else 0.0

                if abs(saldo_cxc - saldo_ledger) > 0.02:
                    informe["central_db"]["diferencias_saldo_vs_movimientos"].append(
                        {
                            "cliente_id": cid,
                            "documento": cli.documento,
                            "nombre": cli.nombre,
                            "saldo_cuentas_por_cobrar": saldo_cxc,
                            "ultimo_saldo_libro_movimientos": saldo_ledger,
                            "diferencia": round(saldo_cxc - saldo_ledger, 2),
                        }
                    )
    except Exception as e_cen:
        informe["central_db"]["error_auditoria"] = str(e_cen)

    try:
        with open(ruta_informe, "w", encoding="utf-8") as fh:
            json.dump(informe, fh, indent=2, ensure_ascii=False, default=str)
    except Exception as e_wr:
        print(f"Aviso escribiendo informe_integridad_datos.json: {e_wr}")

    return informe
