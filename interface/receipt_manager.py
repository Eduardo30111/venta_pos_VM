#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor Unificado de Facturación, Vista Previa, PDF e Impresión Térmica/A4 - VmPOS
Archivo: interface/receipt_manager.py

Responsabilidades:
- Construcción unificada de comprobantes/facturas en formatos:
  * Térmico 58 mm (32 columnas)
  * Térmico 80 mm (48 columnas)
  * Página completa A4 (210 × 297 mm)
- Renderizado de logo institucional en vista previa UI, en PDF (ReportLab) y en
  impresoras térmicas ESC/POS (conversión a bitmap monocromático 1-bit GS v 0).
- Preservación e inmutabilidad del snapshot histórico del negocio en cada venta
  registrada en SQLite (`ventas.datos_negocio_json`).
- Detección real de impresoras del sistema (CUPS/lpstat en macOS/Linux, win32print/PowerShell
  en Windows y dispositivos USB ESC/POS directos).
- Generación de página de prueba («Imprimir prueba») con caracteres en español,
  logo, bordes de ancho de papel y corte automático opcional.
"""

import os
import sys
import json
import time
import shutil
import sqlite3
import tempfile
import textwrap
import subprocess
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from PIL import Image, ImageTk, ImageOps
    PIL_DISPONIBLE = True
except ImportError:
    PIL_DISPONIBLE = False

try:
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.lib import colors
    REPORTLAB_DISPONIBLE = True
except ImportError:
    REPORTLAB_DISPONIBLE = False

try:
    from business_manager import business_mgr, BASE_DIR
except ImportError:
    from interface.business_manager import business_mgr, BASE_DIR

try:
    from theme_manager import aplicar_tema, calcular_geometria_segura, crear_boton
except ImportError:
    from interface.theme_manager import aplicar_tema, calcular_geometria_segura, crear_boton


# Configuraciones USB conocidas para impresoras térmicas ESC/POS directas
USB_THERMAL_CONFIGS = [
    {"vid": 0x0FE6, "pid": 0x811E, "in_ep": 0x82, "out_ep": 0x01, "model": "DIG ISH58 / XP-58"},
    {"vid": 0x0FE6, "pid": 0x811F, "in_ep": 0x82, "out_ep": 0x01, "model": "DIG ISH58"},
    {"vid": 0x0FE6, "pid": 0x811D, "in_ep": 0x82, "out_ep": 0x01, "model": "DIG ISH58"},
    {"vid": 0x1FC9, "pid": 0x2016, "in_ep": 0x82, "out_ep": 0x01, "model": "XP-58 / POS58"},
    {"vid": 0x04B8, "pid": 0x0E28, "in_ep": 0x82, "out_ep": 0x01, "model": "Epson TM-T20"},
    {"vid": 0x04B8, "pid": 0x0202, "in_ep": 0x82, "out_ep": 0x01, "model": "Epson TM-T88"},
    {"vid": 0x0416, "pid": 0x5011, "in_ep": 0x82, "out_ep": 0x01, "model": "Gprinter GP-58"},
    {"vid": 0x0483, "pid": 0x5743, "in_ep": 0x82, "out_ep": 0x01, "model": "POS Thermal USB"},
    {"vid": 0x1504, "pid": 0x0006, "in_ep": 0x81, "out_ep": 0x02, "model": "Bixolon Thermal"}
]


def formato_moneda_cop(valor):
    """Formatea un número como moneda pesos ($ 12.345) sin decimales."""
    try:
        num = float(valor or 0.0)
        signo = "-" if num < 0 else ""
        entero = int(round(abs(num)))
        return f"{signo}$ {entero:,}".replace(",", ".")
    except Exception:
        return "$ 0"


def asegurar_columnas_factura_ventas(conn=None):
    """
    Asegura que las tablas `ventas` y `detalle_ventas` tengan las columnas necesarias
    para almacenar el snapshot histórico del negocio, número de comprobante, recibido/cambio
    y desglose por ítem.
    """
    cerrar = False
    try:
        if conn is None:
            try:
                from database_manager import conectar_db
            except ImportError:
                from interface.database_manager import conectar_db
            conn = conectar_db()
            cerrar = True
        if not conn:
            return False

        cur = conn.cursor()
        cur.execute("PRAGMA table_info(ventas)")
        v_cols = {c[1] for c in cur.fetchall()}

        nuevas_ventas = [
            ("numero_factura", "TEXT DEFAULT ''"),
            ("recibido", "REAL DEFAULT 0.0"),
            ("cambio", "REAL DEFAULT 0.0"),
            ("descuento_total", "REAL DEFAULT 0.0"),
            ("impuesto_total", "REAL DEFAULT 0.0"),
            ("datos_negocio_json", "TEXT DEFAULT ''"),
            ("datos_cliente_json", "TEXT DEFAULT ''")
        ]
        for col, tipo in nuevas_ventas:
            if col not in v_cols:
                try:
                    cur.execute(f"ALTER TABLE ventas ADD COLUMN {col} {tipo}")
                except Exception:
                    pass

        cur.execute("PRAGMA table_info(detalle_ventas)")
        d_cols = {c[1] for c in cur.fetchall()}
        nuevas_det = [
            ("unidad_medida", "TEXT DEFAULT 'Und'"),
            ("descuento", "REAL DEFAULT 0.0"),
            ("impuesto_pct", "REAL DEFAULT 0.0"),
            ("impuesto_monto", "REAL DEFAULT 0.0")
        ]
        for col, tipo in nuevas_det:
            if col not in d_cols:
                try:
                    cur.execute(f"ALTER TABLE detalle_ventas ADD COLUMN {col} {tipo}")
                except Exception:
                    pass

        if cerrar:
            conn.commit()
            conn.close()
        return True
    except Exception as e:
        print(f"Aviso asegurando columnas de factura en ventas.db: {e}")
        if cerrar and conn:
            try:
                conn.close()
            except Exception:
                pass
        return False


def guardar_snapshot_venta_sqlite(
    id_venta,
    numero_factura="",
    recibido=0.0,
    cambio=0.0,
    descuento_total=0.0,
    impuesto_total=0.0,
    snapshot_negocio=None,
    datos_cliente=None,
    conn=None
):
    """Guarda en la fila de `ventas` el snapshot de identidad del negocio y metadatos de cobro."""
    if not id_venta:
        return False
    cerrar = False
    try:
        if conn is None:
            try:
                from database_manager import conectar_db
            except ImportError:
                from interface.database_manager import conectar_db
            conn = conectar_db()
            cerrar = True
        if not conn:
            return False

        asegurar_columnas_factura_ventas(conn=conn)
        snap = snapshot_negocio if isinstance(snapshot_negocio, dict) else business_mgr.obtener_snapshot_factura()
        cli_snap = datos_cliente if isinstance(datos_cliente, dict) else {}

        num_fac = str(numero_factura or "").strip()
        if not num_fac:
            pref = snap.get("prefijo_comprobante", "") or "FAC-"
            num_fac = f"{pref}{int(id_venta):05d}"

        cur = conn.cursor()
        cur.execute("PRAGMA table_info(ventas)")
        cols_v = [c[1] for c in cur.fetchall()]
        pk_col = "id_venta" if "id_venta" in cols_v else "id"

        cur.execute(f"""
            UPDATE ventas
            SET numero_factura = COALESCE(NULLIF(?, ''), numero_factura),
                recibido = ?,
                cambio = ?,
                descuento_total = ?,
                impuesto_total = ?,
                datos_negocio_json = CASE
                    WHEN datos_negocio_json IS NULL OR datos_negocio_json = '' THEN ?
                    ELSE datos_negocio_json
                END,
                datos_cliente_json = CASE
                    WHEN datos_cliente_json IS NULL OR datos_cliente_json = '' THEN ?
                    ELSE datos_cliente_json
                END
            WHERE {pk_col} = ?
        """, (
            num_fac,
            float(recibido or 0.0),
            float(cambio or 0.0),
            float(descuento_total or 0.0),
            float(impuesto_total or 0.0),
            json.dumps(snap, ensure_ascii=False),
            json.dumps(cli_snap, ensure_ascii=False),
            int(id_venta)
        ))
        if cerrar:
            conn.commit()
            conn.close()
        return True
    except Exception as e:
        print(f"Aviso guardando snapshot en venta #{id_venta}: {e}")
        if cerrar and conn:
            try:
                conn.close()
            except Exception:
                pass
        return False


def reconstruir_datos_venta_historica(id_venta):
    """
    Reconstruye todos los datos de una venta histórica desde SQLite,
    respetando el snapshot de identidad del negocio con el que fue emitida.
    """
    try:
        try:
            from database_manager import conectar_db
        except ImportError:
            from interface.database_manager import conectar_db
        conn = conectar_db()
        if not conn:
            return None
        asegurar_columnas_factura_ventas(conn=conn)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("PRAGMA table_info(ventas)")
        cols_v = [c[1] for c in cur.fetchall()]
        pk_col = "id_venta" if "id_venta" in cols_v else "id"

        cur.execute(f"SELECT * FROM ventas WHERE {pk_col} = ?", (int(id_venta),))
        v_row = cur.fetchone()
        if not v_row:
            conn.close()
            return None

        v = dict(v_row)

        cur.execute("PRAGMA table_info(detalle_ventas)")
        cols_d = [c[1] for c in cur.fetchall()]
        fk_col = "id_venta" if "id_venta" in cols_d else "venta_id"
        order_col = "id_detalle" if "id_detalle" in cols_d else ("id" if "id" in cols_d else "rowid")
        cur.execute(f"SELECT * FROM detalle_ventas WHERE {fk_col} = ? ORDER BY {order_col} ASC", (int(id_venta),))
        det_rows = [dict(r) for r in cur.fetchall()]

        pagos_rows = []
        try:
            cur.execute("PRAGMA table_info(pagos_venta)")
            cols_p = [c[1] for c in cur.fetchall()]
            fk_p = "id_venta" if "id_venta" in cols_p else "venta_id"
            order_p = "id_pago" if "id_pago" in cols_p else ("id" if "id" in cols_p else "rowid")
            cur.execute(f"SELECT metodo_pago, monto, referencia FROM pagos_venta WHERE {fk_p} = ? ORDER BY {order_p} ASC", (int(id_venta),))
            pagos_rows = [dict(r) for r in cur.fetchall()]
        except Exception:
            pass

        # Datos del cliente si hay cliente_id o documento
        cliente_info = {
            "nombre": v.get("documento_cliente") or "Consumidor Final",
            "documento": v.get("documento_cliente") or "",
            "telefono": "",
            "direccion": ""
        }
        if v.get("datos_cliente_json"):
            try:
                c_json = json.loads(v["datos_cliente_json"])
                if isinstance(c_json, dict) and c_json:
                    cliente_info.update(c_json)
            except Exception:
                pass

        if v.get("cliente_id"):
            try:
                cur.execute("SELECT nombre, cedula, telefono, direccion FROM clientes WHERE id = ?", (v["cliente_id"],))
                cr = cur.fetchone()
                if cr:
                    cliente_info["nombre"] = cr["nombre"] or cliente_info["nombre"]
                    cliente_info["documento"] = cr["cedula"] or cliente_info["documento"]
                    cliente_info["telefono"] = cr["telefono"] or ""
                    cliente_info["direccion"] = cr["direccion"] or ""
            except Exception:
                pass
        elif v.get("documento_cliente") and v.get("documento_cliente") != "Consumidor Final":
            try:
                cur.execute(
                    "SELECT nombre, cedula, telefono, direccion FROM clientes WHERE cedula = ? OR LOWER(nombre) = LOWER(?)",
                    (v["documento_cliente"], v["documento_cliente"])
                )
                cr = cur.fetchone()
                if cr:
                    cliente_info["nombre"] = cr["nombre"] or cliente_info["nombre"]
                    cliente_info["documento"] = cr["cedula"] or cliente_info["documento"]
                    cliente_info["telefono"] = cr["telefono"] or ""
                    cliente_info["direccion"] = cr["direccion"] or ""
            except Exception:
                pass

        conn.close()

        # Snapshot histórico del negocio
        snapshot_negocio = None
        if v.get("datos_negocio_json"):
            try:
                parsed = json.loads(v["datos_negocio_json"])
                if isinstance(parsed, dict) and parsed.get("nombre_negocio"):
                    snapshot_negocio = parsed
            except Exception:
                pass

        items = []
        for d in det_rows:
            items.append({
                "codigo": d.get("codigo_producto") or "",
                "nombre": d.get("nombre_producto") or "Producto",
                "cantidad": d.get("cantidad") or 1,
                "unidad": d.get("unidad_medida") or "Und",
                "precio_unitario": float(d.get("precio_unitario") or 0.0),
                "descuento": float(d.get("descuento") or 0.0),
                "impuesto_pct": float(d.get("impuesto_pct") or 0.0),
                "impuesto_monto": float(d.get("impuesto_monto") or 0.0),
                "subtotal": float(d.get("subtotal") or 0.0)
            })

        total_venta = float(v.get("total_venta") or 0.0)
        metodo_pago = v.get("metodo_pago") or "Efectivo"
        recibido = float(v.get("recibido") or 0.0)
        if recibido <= 0 and metodo_pago != "Fiado":
            recibido = total_venta
        cambio = float(v.get("cambio") or max(0.0, recibido - total_venta))
        saldo_pendiente = float(v.get("saldo_pendiente") or (total_venta if metodo_pago == "Fiado" else 0.0))

        num_factura = v.get("numero_factura") or f"FAC-{int(id_venta):05d}"

        datos = {
            "id_venta": int(id_venta),
            "factura": num_factura,
            "fecha": v.get("fecha_venta") or "",
            "hora": v.get("hora_venta") or "",
            "vendedor": v.get("operario") or "Administrador",
            "estado": v.get("estado") or "Completada",
            "cliente": cliente_info.get("nombre") or "Consumidor Final",
            "cliente_documento": cliente_info.get("documento") or "",
            "cliente_telefono": cliente_info.get("telefono") or "",
            "cliente_direccion": cliente_info.get("direccion") or "",
            "items": items,
            "total": total_venta,
            "descuento_total": float(v.get("descuento_total") or 0.0),
            "impuesto_total": float(v.get("impuesto_total") or 0.0),
            "metodo_pago": metodo_pago,
            "pagos": pagos_rows,
            "recibido": recibido,
            "cambio": cambio,
            "saldo_pendiente": saldo_pendiente,
            "snapshot_negocio": snapshot_negocio
        }
        return normalizar_datos_factura(datos)
    except Exception as e:
        print(f"Error reconstruyendo venta histórica #{id_venta}: {e}")
        return None


def normalizar_datos_factura(datos_venta):
    """
    Normaliza cualquier estructura de entrada (`datos_venta` de caja, venta histórica o prueba)
    a un diccionario estándar listo para texto, vista previa, PDF o ESC/POS.
    """
    datos = dict(datos_venta or {})

    # 1. Identidad del negocio: priorizar snapshot histórico si viene incluido en la venta
    snap = datos.get("snapshot_negocio") or datos.get("negocio")
    if not isinstance(snap, dict) or not snap:
        if datos.get("datos_negocio_json"):
            try:
                snap = json.loads(datos["datos_negocio_json"])
            except Exception:
                snap = None

    if isinstance(snap, dict) and snap.get("nombre_negocio"):
        negocio = dict(snap)
    else:
        # Usar configuración actual en vivo de BusinessManager, permitiendo overrides explícitos en datos_venta
        actual = business_mgr.obtener_snapshot_factura()
        negocio = dict(actual)
        for k in (
            "nombre_negocio", "razon_social", "subtitulo_negocio", "tipo_documento_fiscal",
            "nit", "regimen_fiscal", "direccion", "ciudad", "telefono", "email",
            "eslogan", "encabezado_recibo", "tipo_comprobante", "prefijo_comprobante", "logo_path"
        ):
            if k in datos and datos[k] is not None and str(datos[k]).strip() != "":
                negocio[k] = datos[k]
            elif k == "subtitulo_negocio" and "subtitulo" in datos and datos["subtitulo"] is not None:
                negocio["subtitulo_negocio"] = datos["subtitulo"]

    # Resolver rutas de logo a rutas absolutas existentes
    negocio["logo_path"] = business_mgr._resolver_ruta_logo(negocio.get("logo_path", ""))
    negocio["logo_thermal_path"] = business_mgr._resolver_ruta_logo(negocio.get("logo_thermal_path", ""))
    if negocio["logo_path"] and not negocio["logo_thermal_path"]:
        negocio["logo_thermal_path"] = business_mgr.logo_thermal_path

    # 2. Normalizar lista de ítems
    items_norm = []
    raw_items = datos.get("items") or datos.get("detalles") or []
    if not raw_items and datos.get("productos"):
        # Compatibilidad con tuplas antiguas (nombre, precio, cantidad)
        for prod in datos["productos"]:
            if isinstance(prod, (list, tuple)) and len(prod) >= 3:
                nom, pre, cant = prod[0], float(prod[1] or 0), float(prod[2] or 1)
                items_norm.append({
                    "codigo": "",
                    "nombre": str(nom),
                    "cantidad": int(cant) if float(cant).is_integer() else cant,
                    "unidad": "Und",
                    "precio_unitario": pre,
                    "descuento": 0.0,
                    "impuesto_pct": 0.0,
                    "impuesto_monto": 0.0,
                    "subtotal": pre * cant
                })
            elif isinstance(prod, dict):
                raw_items.append(prod)

    for it in raw_items:
        if not isinstance(it, dict):
            continue
        cant = float(it.get("cantidad", 1) or 1)
        cant_fmt = int(cant) if cant.is_integer() else round(cant, 2)
        precio_u = float(it.get("precio_unitario", it.get("precio_vendido", it.get("precio", 0.0))) or 0.0)
        desc = float(it.get("descuento", 0.0) or 0.0)
        imp_pct = float(it.get("impuesto_pct", it.get("iva_pct", 0.0)) or 0.0)
        sub_bruto = precio_u * cant
        sub_neto = float(it.get("subtotal", sub_bruto - desc) or (sub_bruto - desc))
        imp_monto = float(it.get("impuesto_monto", 0.0) or 0.0)
        if imp_pct > 0 and imp_monto == 0.0:
            imp_monto = round(sub_neto - (sub_neto / (1.0 + imp_pct / 100.0)), 2)

        items_norm.append({
            "codigo": str(it.get("codigo", it.get("item_codigo", "")) or "").strip(),
            "nombre": str(it.get("nombre", it.get("item_nombre", "Producto")) or "Producto").strip(),
            "cantidad": cant_fmt,
            "unidad": str(it.get("unidad", it.get("unidad_medida", "Und")) or "Und").strip(),
            "precio_unitario": precio_u,
            "descuento": desc,
            "impuesto_pct": imp_pct,
            "impuesto_monto": imp_monto,
            "subtotal": sub_neto
        })

    subtotal_items = sum(i["subtotal"] + i["descuento"] for i in items_norm)
    desc_items = sum(i["descuento"] for i in items_norm)
    imp_items = sum(i["impuesto_monto"] for i in items_norm)

    descuento_total = float(datos.get("descuento_total", datos.get("descuento", desc_items)) or desc_items)
    impuesto_total = float(datos.get("impuesto_total", datos.get("impuestos", imp_items)) or imp_items)
    total = float(datos.get("total", max(0.0, subtotal_items - descuento_total)) or 0.0)
    subtotal_base = max(0.0, subtotal_items - imp_items) if imp_items > 0 else subtotal_items

    metodo_pago = str(datos.get("metodo_pago", "Efectivo") or "Efectivo").strip()
    es_credito = metodo_pago.lower() in ("fiado", "crédito", "credito")
    recibido = float(datos.get("recibido", 0.0 if es_credito else total) or 0.0)
    cambio = float(datos.get("cambio", max(0.0, recibido - total) if not es_credito else 0.0) or 0.0)
    saldo_pendiente = float(
        datos.get("saldo_pendiente", max(0.0, total - recibido) if es_credito else 0.0) or 0.0
    )

    pagos = datos.get("pagos") or []
    if not pagos:
        pagos = [{
            "metodo_pago": metodo_pago,
            "monto": recibido if es_credito and recibido > 0 else total,
            "referencia": ""
        }]

    # Número de documento / factura
    id_venta = datos.get("id_venta")
    prefijo = str(negocio.get("prefijo_comprobante", "") or "").strip()
    factura_str = str(datos.get("factura", "") or "").strip()
    if not factura_str:
        if id_venta:
            factura_str = f"{prefijo or 'POS-'}{int(id_venta):05d}"
        else:
            factura_str = f"{prefijo or 'POS-'}00001"
    elif prefijo and not factura_str.startswith(prefijo) and factura_str.isdigit():
        factura_str = f"{prefijo}{int(factura_str):05d}"

    fecha_str = str(datos.get("fecha", "") or datetime.now().strftime("%Y-%m-%d")).strip()
    hora_str = str(datos.get("hora", "") or datetime.now().strftime("%H:%M:%S")).strip()

    cliente_nom = str(datos.get("cliente", "") or "").strip() or "Consumidor Final"
    cliente_doc = str(datos.get("cliente_documento", "") or "").strip()
    if cliente_nom != "Consumidor Final" and not cliente_doc and cliente_nom.replace("-", "").isdigit():
        cliente_doc = cliente_nom

    return {
        "negocio": negocio,
        "snapshot_negocio": negocio,
        "id_venta": id_venta,
        "factura": factura_str,
        "fecha": fecha_str,
        "hora": hora_str,
        "estado": str(datos.get("estado", "Completada") or "Completada"),
        "vendedor": str(datos.get("vendedor", "Administrador") or "Administrador").strip(),
        "cliente_nombre": cliente_nom,
        "cliente_documento": cliente_doc,
        "cliente_telefono": str(datos.get("cliente_telefono", "") or "").strip(),
        "cliente_direccion": str(datos.get("cliente_direccion", "") or "").strip(),
        "items": items_norm,
        "subtotal_base": subtotal_base,
        "subtotal_bruto": subtotal_items,
        "descuento_total": descuento_total,
        "impuesto_total": impuesto_total,
        "total": total,
        "metodo_pago": metodo_pago,
        "pagos": pagos,
        "recibido": recibido,
        "cambio": cambio,
        "es_credito": es_credito,
        "saldo_pendiente": saldo_pendiente,
        "es_prueba": bool(datos.get("es_prueba", False))
    }


def construir_datos_factura_prueba():
    """Construye un payload de factura de prueba realista con caracteres en español."""
    snap = business_mgr.obtener_snapshot_factura()
    return normalizar_datos_factura({
        "id_venta": 9999,
        "factura": f"{snap.get('prefijo_comprobante') or 'PRUEBA-'}0001",
        "fecha": datetime.now().strftime("%Y-%m-%d"),
        "hora": datetime.now().strftime("%H:%M:%S"),
        "vendedor": "Operador de Prueba (Ñandú)",
        "cliente": "Cliente de Prueba S.A.S. (José María Ñañez)",
        "cliente_documento": "900.123.456-7",
        "cliente_telefono": "+57 300 000 0000",
        "cliente_direccion": "Calle 72 # 45-10, Edición Águila",
        "items": [
            {
                "codigo": "P001",
                "nombre": "Artículo Estándar con Tildes: Café, Azúcar y Ñame",
                "cantidad": 2,
                "unidad": "Und",
                "precio_unitario": 12500,
                "descuento": 1000,
                "impuesto_pct": 19.0,
                "subtotal": 24000
            },
            {
                "codigo": "S002",
                "nombre": "Descripción larga de servicio técnico especializado para verificar ajuste de línea sin cortes",
                "cantidad": 1,
                "unidad": "Serv",
                "precio_unitario": 35000,
                "descuento": 0,
                "impuesto_pct": 0.0,
                "subtotal": 35000
            }
        ],
        "descuento_total": 1000,
        "total": 59000,
        "metodo_pago": "Efectivo",
        "recibido": 60000,
        "cambio": 1000,
        "es_prueba": True,
        "snapshot_negocio": snap
    })


# =============================================================================
# RENDERIZADOR DE TEXTO MULTI-FORMATO (58mm, 80mm, A4)
# =============================================================================
def generar_texto_factura(datos_venta, formato=None, config_impresora=None):
    """
    Genera la representación en texto plano perfectamente alineada según el formato:
    - 58mm -> 32 caracteres por línea
    - 80mm -> 48 caracteres por línea
    - A4   -> 76 caracteres por línea
    """
    norm = normalizar_datos_factura(datos_venta)
    neg = norm["negocio"]
    cfg = dict(business_mgr.obtener_config_impresora())
    if isinstance(config_impresora, dict):
        cfg.update(config_impresora)

    fmt = str(formato or cfg.get("formato_papel", "58mm")).strip()
    if fmt == "80mm":
        ancho = 48
    elif fmt == "A4":
        ancho = 76
    else:
        fmt = "58mm"
        ancho = 32

    alin = str(cfg.get("alineacion_encabezado", "center") or "center").lower()

    def alinear_encabezado(linea):
        linea = str(linea).strip()
        if not linea:
            return []
        envueltas = textwrap.wrap(linea, width=ancho) or [linea[:ancho]]
        if alin == "left":
            return envueltas
        return [l.center(ancho) for l in envueltas]

    def fila_par(izq, der, sep=" "):
        izq = str(izq)
        der = str(der)
        espacio_disp = ancho - len(der) - 1
        if espacio_disp < 4:
            return [izq[:ancho], der.rjust(ancho)]
        if len(izq) > espacio_disp:
            lineas_izq = textwrap.wrap(izq, width=espacio_disp)
            res = lineas_izq[:-1]
            ult = lineas_izq[-1]
            relleno = sep * max(1, ancho - len(ult) - len(der))
            res.append(f"{ult}{relleno}{der}")
            return res
        relleno = sep * max(1, ancho - len(izq) - len(der))
        return [f"{izq}{relleno}{der}"]

    lineas = []
    sep_doble = "=" * ancho
    sep_simple = "-" * ancho

    # Encabezado del negocio
    nombre_comercial = neg.get("nombre_negocio", "VmPOS").strip()
    if nombre_comercial:
        lineas.extend(alinear_encabezado(nombre_comercial.upper()))

    if cfg.get("mostrar_razon_social", True):
        razon = neg.get("razon_social", "").strip()
        subt = neg.get("subtitulo_negocio", "").strip()
        if razon:
            lineas.extend(alinear_encabezado(razon))
        if subt and subt.lower() != razon.lower() and subt.lower() != nombre_comercial.lower():
            lineas.extend(alinear_encabezado(subt))

    if cfg.get("mostrar_nit", True) and neg.get("nit"):
        tdoc = neg.get("tipo_documento_fiscal", "NIT").strip() or "NIT"
        lineas.extend(alinear_encabezado(f"{tdoc}: {neg['nit']}"))

    if cfg.get("mostrar_regimen", True) and neg.get("regimen_fiscal"):
        lineas.extend(alinear_encabezado(neg["regimen_fiscal"]))

    if cfg.get("mostrar_direccion", True):
        dir_txt = neg.get("direccion", "").strip()
        ciu_txt = neg.get("ciudad", "").strip()
        if dir_txt and ciu_txt and ciu_txt.lower() not in dir_txt.lower():
            lineas.extend(alinear_encabezado(f"{dir_txt} - {ciu_txt}"))
        elif dir_txt or ciu_txt:
            lineas.extend(alinear_encabezado(dir_txt or ciu_txt))

    if cfg.get("mostrar_telefono", True) and neg.get("telefono"):
        lineas.extend(alinear_encabezado(f"Tel: {neg['telefono']}"))

    if cfg.get("mostrar_email", False) and neg.get("email"):
        lineas.extend(alinear_encabezado(neg["email"]))

    if neg.get("encabezado_recibo"):
        lineas.extend(alinear_encabezado(neg["encabezado_recibo"]))

    lineas.append(sep_doble)

    # Tipo y número de comprobante
    tipo_comp = neg.get("tipo_comprobante", "RECIBO DE VENTA").strip() or "RECIBO DE VENTA"
    if norm.get("es_prueba"):
        lineas.extend(alinear_encabezado("*** IMPRESIÓN DE PRUEBA ***"))
    lineas.extend(alinear_encabezado(f"{tipo_comp} No. {norm['factura']}"))
    if norm.get("estado") and norm["estado"].lower() != "completada":
        lineas.extend(alinear_encabezado(f"ESTADO: {norm['estado'].upper()}"))

    lineas.append(sep_simple)

    # Metadatos de fecha, cliente y vendedor
    fecha_hora = f"{norm['fecha']} {norm['hora']}".strip()
    lineas.extend(fila_par("Fecha:", fecha_hora))
    if norm.get("id_venta"):
        lineas.extend(fila_par("ID Venta:", f"#{norm['id_venta']}"))

    if cfg.get("mostrar_vendedor", True) and norm.get("vendedor"):
        lineas.extend(fila_par("Atendido por:", norm["vendedor"]))

    if cfg.get("mostrar_cliente", True):
        cli_nom = norm.get("cliente_nombre", "Consumidor Final")
        lineas.extend(fila_par("Cliente:", cli_nom))
        if norm.get("cliente_documento") and norm["cliente_documento"] != cli_nom:
            lineas.extend(fila_par("Doc/NIT:", norm["cliente_documento"]))
        if norm.get("cliente_telefono"):
            lineas.extend(fila_par("Tel Cliente:", norm["cliente_telefono"]))
        if norm.get("cliente_direccion"):
            lineas.extend(fila_par("Dir Cliente:", norm["cliente_direccion"]))

    lineas.append(sep_simple)

    # Detalle de productos / servicios según ancho del formato
    if fmt == "58mm":
        lineas.append("DESCRIPCIÓN")
        lineas.extend(fila_par("CANT x VR.UNIT", "SUBTOTAL"))
        lineas.append(sep_simple)
        for it in norm["items"]:
            nom_item = f"{it['codigo']} {it['nombre']}".strip() if it.get("codigo") else it["nombre"]
            for ln in textwrap.wrap(nom_item, width=ancho) or [nom_item[:ancho]]:
                lineas.append(ln)
            cant_str = f"{it['cantidad']} {it.get('unidad', 'Und')} x {formato_moneda_cop(it['precio_unitario'])}"
            sub_str = formato_moneda_cop(it["subtotal"])
            lineas.extend(fila_par(f"  {cant_str}", sub_str))
            if it.get("descuento", 0) > 0:
                lineas.extend(fila_par("  Descuento ítem:", f"-{formato_moneda_cop(it['descuento'])}"))
            if it.get("impuesto_pct", 0) > 0:
                lineas.extend(fila_par(f"  IVA ({it['impuesto_pct']:g}% incl.):", formato_moneda_cop(it["impuesto_monto"])))
    elif fmt == "80mm":
        lineas.extend(fila_par("CANT  DESCRIPCIÓN / PRECIO UNIT.", "SUBTOTAL"))
        lineas.append(sep_simple)
        for it in norm["items"]:
            nom_item = f"[{it['codigo']}] {it['nombre']}".strip() if it.get("codigo") else it["nombre"]
            for ln in textwrap.wrap(nom_item, width=ancho) or [nom_item[:ancho]]:
                lineas.append(ln)
            izq_det = f"  {it['cantidad']} {it.get('unidad', 'Und')} x {formato_moneda_cop(it['precio_unitario'])}"
            if it.get("descuento", 0) > 0:
                izq_det += f" (Desc -{formato_moneda_cop(it['descuento'])})"
            lineas.extend(fila_par(izq_det, formato_moneda_cop(it["subtotal"])))
            if it.get("impuesto_pct", 0) > 0:
                lineas.extend(fila_par(f"  IVA ({it['impuesto_pct']:g}%):", formato_moneda_cop(it["impuesto_monto"])))
    else:
        # Formato A4 (76 columnas)
        enc_tabla = f"{'CÓD':<8} {'DESCRIPCIÓN':<30} {'CANT':>6} {'VR.UNIT':>13} {'SUBTOTAL':>15}"
        lineas.append(enc_tabla[:ancho])
        lineas.append(sep_simple)
        for it in norm["items"]:
            cod_s = (it.get("codigo") or "-")[:8]
            partes_nom = textwrap.wrap(it["nombre"], width=30) or [it["nombre"][:30]]
            cant_s = f"{it['cantidad']}"[:6]
            pu_s = formato_moneda_cop(it["precio_unitario"])[:13]
            sub_s = formato_moneda_cop(it["subtotal"])[:15]
            lineas.append(f"{cod_s:<8} {partes_nom[0]:<30} {cant_s:>6} {pu_s:>13} {sub_s:>15}")
            for extra_nom in partes_nom[1:]:
                lineas.append(f"{'':<8} {extra_nom:<30}")
            if it.get("descuento", 0) > 0 or it.get("impuesto_pct", 0) > 0:
                det_extra = []
                if it.get("descuento", 0) > 0:
                    det_extra.append(f"Desc: -{formato_moneda_cop(it['descuento'])}")
                if it.get("impuesto_pct", 0) > 0:
                    det_extra.append(f"IVA {it['impuesto_pct']:g}%: {formato_moneda_cop(it['impuesto_monto'])}")
                lineas.append(f"{'':<8} ({', '.join(det_extra)})")

    lineas.append(sep_simple)

    # Totales
    if norm["descuento_total"] > 0 or norm["impuesto_total"] > 0:
        lineas.extend(fila_par("SUBTOTAL:", formato_moneda_cop(norm["subtotal_bruto"])))
    if norm["descuento_total"] > 0:
        lineas.extend(fila_par("DESCUENTO TOTAL:", f"-{formato_moneda_cop(norm['descuento_total'])}"))
    if norm["impuesto_total"] > 0:
        lineas.extend(fila_par("IMPUESTOS / IVA:", formato_moneda_cop(norm["impuesto_total"])))

    lineas.extend(fila_par("TOTAL A PAGAR:", formato_moneda_cop(norm["total"])))
    lineas.append(sep_simple)

    # Medios de pago, recibido, cambio y saldo pendiente (crédito)
    lineas.extend(fila_par("Medio de pago:", norm["metodo_pago"]))
    if len(norm.get("pagos", [])) > 1:
        for pg in norm["pagos"]:
            m_pg = pg.get("metodo_pago", pg.get("metodo", "Pago"))
            v_pg = float(pg.get("monto", 0.0) or 0.0)
            lineas.extend(fila_par(f"  • {m_pg}:", formato_moneda_cop(v_pg)))

    if norm["es_credito"] or norm["saldo_pendiente"] > 0:
        abono = max(0.0, norm["total"] - norm["saldo_pendiente"])
        lineas.extend(fila_par("Abono recibido:", formato_moneda_cop(abono)))
        lineas.extend(fila_par("SALDO PENDIENTE:", formato_moneda_cop(norm["saldo_pendiente"])))
    else:
        lineas.extend(fila_par("Valor recibido:", formato_moneda_cop(norm["recibido"])))
        lineas.extend(fila_par("Cambio / Vuelto:", formato_moneda_cop(norm["cambio"])))

    # Bloque de verificación de caracteres en español cuando es Impresión de Prueba
    if norm.get("es_prueba"):
        lineas.append(sep_simple)
        lineas.extend(alinear_encabezado("PRUEBA DE CARACTERES ESPAÑOL:"))
        lineas.extend(alinear_encabezado("á é í ó ú Á É Í Ó Ú ñ Ñ ü Ü ¿ ¡ $"))
        lineas.extend(alinear_encabezado(f"Formato: {fmt} ({ancho} col)"))
        lineas.append("<" + "-" * (ancho - 2) + ">")

    # Pie de factura / eslogan
    tiene_pie = False
    if cfg.get("mostrar_eslogan", True) and neg.get("eslogan"):
        lineas.append(sep_simple)
        tiene_pie = True
        lineas.extend(alinear_encabezado(neg["eslogan"]))

    if cfg.get("pie_factura_extra"):
        if not tiene_pie:
            lineas.append(sep_simple)
            tiene_pie = True
        lineas.extend(alinear_encabezado(cfg["pie_factura_extra"]))

    lineas.append(sep_doble)
    return "\n".join(lineas)


# =============================================================================
# GENERADOR NATIVO DE PDF (58mm, 80mm, A4) CON REPORTLAB
# =============================================================================
def generar_pdf_factura(datos_venta, ruta_salida=None, formato=None, config_impresora=None):
    """
    Genera un archivo PDF fiel al formato elegido ('58mm', '80mm' o 'A4'),
    incluyendo el logo institucional (si existe y está activo), caracteres en español
    y todos los datos fiscales/comerciales configurados.
    Retorna (exito: bool, ruta_pdf_o_mensaje_error: str)
    """
    if not REPORTLAB_DISPONIBLE:
        return False, "La librería ReportLab no está disponible para generar PDF."

    norm = normalizar_datos_factura(datos_venta)
    neg = norm["negocio"]
    cfg = dict(business_mgr.obtener_config_impresora())
    if isinstance(config_impresora, dict):
        cfg.update(config_impresora)

    fmt = str(formato or cfg.get("formato_papel", "58mm")).strip()
    if fmt not in ("58mm", "80mm", "A4"):
        fmt = "58mm"

    if not ruta_salida:
        carpeta_pdfs = os.path.join(BASE_DIR, "facturas_pdf")
        os.makedirs(carpeta_pdfs, exist_ok=True)
        num_limpio = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in str(norm["factura"]))
        ruta_salida = os.path.join(carpeta_pdfs, f"Comprobante_{num_limpio}_{fmt}.pdf")
    else:
        os.makedirs(os.path.dirname(os.path.abspath(ruta_salida)), exist_ok=True)

    try:
        if fmt == "A4":
            _renderizar_pdf_a4(norm, neg, cfg, ruta_salida)
        else:
            _renderizar_pdf_termico(norm, neg, cfg, ruta_salida, fmt)
        return True, ruta_salida
    except Exception as e:
        return False, f"Error al generar el PDF ({fmt}): {e}"


def _renderizar_pdf_termico(norm, neg, cfg, ruta_salida, fmt):
    """Renderiza un PDF de tirilla térmica continua (58mm u 80mm) con logo y texto."""
    ancho_mm = 58.0 if fmt == "58mm" else 80.0
    margen_mm = max(1.0, min(8.0, float(cfg.get("margen_mm", 2) or 2)))
    ancho_pt = ancho_mm * mm
    margen_pt = margen_mm * mm

    tam_fuente_cfg = str(cfg.get("tamano_fuente", "normal")).lower()
    if fmt == "58mm":
        font_size = 7.2 if tam_fuente_cfg == "pequena" else (8.4 if tam_fuente_cfg == "grande" else 7.8)
    else:
        font_size = 8.0 if tam_fuente_cfg == "pequena" else (9.5 if tam_fuente_cfg == "grande" else 8.8)

    densidad_cfg = str(cfg.get("densidad", "normal")).lower()
    interlineado = font_size * (1.12 if densidad_cfg == "compacta" else (1.35 if densidad_cfg == "amplia" else 1.22))

    texto_completo = generar_texto_factura(norm, formato=fmt, config_impresora=cfg)
    lineas = texto_completo.splitlines()

    # Calcular alto del logo si aplica
    logo_path = neg.get("logo_path", "")
    mostrar_logo = bool(cfg.get("mostrar_logo", True)) and bool(logo_path) and os.path.isfile(logo_path)
    alto_logo_pt = 0.0
    ancho_logo_pt = 0.0
    if mostrar_logo and PIL_DISPONIBLE:
        try:
            with Image.open(logo_path) as im:
                w_px, h_px = im.size
                max_w_pt = min(ancho_pt - 2 * margen_pt, (36 * mm if fmt == "58mm" else 48 * mm))
                max_h_pt = 24 * mm if fmt == "58mm" else 30 * mm
                escala = min(max_w_pt / max(1, w_px), max_h_pt / max(1, h_px))
                ancho_logo_pt = w_px * escala
                alto_logo_pt = h_px * escala
        except Exception:
            mostrar_logo = False

    alto_texto_pt = (len(lineas) + 3) * interlineado
    alto_total_pt = max(90 * mm, margen_pt * 2 + alto_logo_pt + (10 if mostrar_logo else 0) + alto_texto_pt + 15)

    c = rl_canvas.Canvas(ruta_salida, pagesize=(ancho_pt, alto_total_pt))
    c.setTitle(f"{neg.get('tipo_comprobante', 'Recibo')} {norm['factura']}")

    y = alto_total_pt - margen_pt - 6

    if mostrar_logo and ancho_logo_pt > 0 and alto_logo_pt > 0:
        try:
            if str(cfg.get("alineacion_encabezado", "center")).lower() == "left":
                x_logo = margen_pt
            else:
                x_logo = (ancho_pt - ancho_logo_pt) / 2.0
            y -= alto_logo_pt
            # Componer sobre blanco para evitar fondos transparentes negros en visores PDF
            with Image.open(logo_path) as im_src:
                if im_src.mode in ("RGBA", "LA") or (im_src.mode == "P" and "transparency" in im_src.info):
                    rgba = im_src.convert("RGBA")
                    bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                    im_flat = Image.alpha_composite(bg, rgba).convert("RGB")
                else:
                    im_flat = im_src.convert("RGB")
                c.drawImage(ImageReader(im_flat), x_logo, y, width=ancho_logo_pt, height=alto_logo_pt, preserveAspectRatio=True)
            y -= 8
        except Exception as e_img:
            print(f"Aviso dibujando logo en PDF térmico: {e_img}")

    c.setFont("Courier", font_size)
    for idx, ln in enumerate(lineas):
        y -= interlineado
        # Resaltar en negrita el nombre del negocio y el TOTAL A PAGAR
        if idx == 0 or "TOTAL A PAGAR:" in ln or "SALDO PENDIENTE:" in ln or norm.get("factura", "") in ln:
            c.setFont("Courier-Bold", font_size)
        else:
            c.setFont("Courier", font_size)
        c.drawString(margen_pt, y, ln)

    c.showPage()
    c.save()


def _renderizar_pdf_a4(norm, neg, cfg, ruta_salida):
    """Renderiza un PDF empresarial de página completa en formato A4."""
    ancho_p, alto_p = A4
    margen_mm = max(8.0, min(25.0, float(cfg.get("margen_mm", 12) or 12)))
    margen = margen_mm * mm
    ancho_util = ancho_p - 2 * margen

    c = rl_canvas.Canvas(ruta_salida, pagesize=A4)
    c.setTitle(f"{neg.get('tipo_comprobante', 'Comprobante')} {norm['factura']}")

    y = alto_p - margen

    # 1. Logo y Encabezado Empresarial
    logo_path = neg.get("logo_path", "")
    mostrar_logo = bool(cfg.get("mostrar_logo", True)) and bool(logo_path) and os.path.isfile(logo_path)
    x_texto_emp = margen

    if mostrar_logo and PIL_DISPONIBLE:
        try:
            with Image.open(logo_path) as im_src:
                w_px, h_px = im_src.size
                max_w, max_h = 42 * mm, 26 * mm
                esc = min(max_w / max(1, w_px), max_h / max(1, h_px))
                lw, lh = w_px * esc, h_px * esc
                if im_src.mode in ("RGBA", "LA") or (im_src.mode == "P" and "transparency" in im_src.info):
                    rgba = im_src.convert("RGBA")
                    bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                    im_flat = Image.alpha_composite(bg, rgba).convert("RGB")
                else:
                    im_flat = im_src.convert("RGB")
                c.drawImage(ImageReader(im_flat), margen, y - lh, width=lw, height=lh, preserveAspectRatio=True)
                x_texto_emp = margen + lw + 6 * mm
        except Exception:
            pass

    # Recuadro derecho del número de comprobante
    caja_w = 68 * mm
    caja_h = 26 * mm
    caja_x = ancho_p - margen - caja_w
    caja_y = y - caja_h
    c.setStrokeColor(colors.HexColor("#CBD5E1"))
    c.setFillColor(colors.HexColor("#F8FAFC"))
    c.roundRect(caja_x, caja_y, caja_w, caja_h, 4, stroke=1, fill=1)

    c.setFillColor(colors.HexColor("#0F172A"))
    c.setFont("Helvetica-Bold", 9)
    tipo_comp = (neg.get("tipo_comprobante") or "RECIBO DE VENTA").upper()
    c.drawCentredString(caja_x + caja_w / 2, caja_y + caja_h - 11, tipo_comp[:28])

    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.HexColor("#BE185D"))
    c.drawCentredString(caja_x + caja_w / 2, caja_y + caja_h - 26, f"No. {norm['factura']}")

    c.setFont("Helvetica", 8.5)
    c.setFillColor(colors.HexColor("#334155"))
    c.drawCentredString(caja_x + caja_w / 2, caja_y + 8, f"Fecha: {norm['fecha']}  {norm['hora']}")

    # Textos de identidad del negocio a la izquierda
    y_emp = y - 11
    c.setFillColor(colors.HexColor("#0F172A"))
    c.setFont("Helvetica-Bold", 14)
    c.drawString(x_texto_emp, y_emp, (neg.get("nombre_negocio") or "VmPOS")[:45])
    y_emp -= 13

    c.setFont("Helvetica", 9.5)
    c.setFillColor(colors.HexColor("#334155"))
    if cfg.get("mostrar_razon_social", True):
        razon = neg.get("razon_social", "").strip()
        subt = neg.get("subtitulo_negocio", "").strip()
        linea_rs = razon or subt
        if linea_rs:
            c.drawString(x_texto_emp, y_emp, linea_rs[:60])
            y_emp -= 11

    if cfg.get("mostrar_nit", True) and neg.get("nit"):
        tdoc = neg.get("tipo_documento_fiscal", "NIT")
        reg = f"  •  {neg['regimen_fiscal']}" if (cfg.get("mostrar_regimen", True) and neg.get("regimen_fiscal")) else ""
        c.drawString(x_texto_emp, y_emp, f"{tdoc}: {neg['nit']}{reg}"[:65])
        y_emp -= 11

    if cfg.get("mostrar_direccion", True):
        dir_c = neg.get("direccion", "").strip()
        ciu_c = neg.get("ciudad", "").strip()
        ub = f"{dir_c}, {ciu_c}" if (dir_c and ciu_c and ciu_c.lower() not in dir_c.lower()) else (dir_c or ciu_c)
        if ub:
            c.drawString(x_texto_emp, y_emp, ub[:65])
            y_emp -= 11

    if cfg.get("mostrar_telefono", True) and neg.get("telefono"):
        tel_str = f"Tel: {neg['telefono']}"
        if cfg.get("mostrar_email", False) and neg.get("email"):
            tel_str += f"  •  {neg['email']}"
        c.drawString(x_texto_emp, y_emp, tel_str[:65])
        y_emp -= 11

    y = min(caja_y, y_emp) - 8 * mm

    # 2. Bloque de Datos del Cliente y Vendedor
    c.setStrokeColor(colors.HexColor("#CBD5E1"))
    c.setFillColor(colors.HexColor("#F8FAFC"))
    c.roundRect(margen, y - 18 * mm, ancho_util, 18 * mm, 4, stroke=1, fill=1)

    c.setFillColor(colors.HexColor("#0F172A"))
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(margen + 8, y - 12, "CLIENTE:")
    c.drawString(margen + 8, y - 25, "DOCUMENTO / NIT:")
    c.drawString(margen + 8, y - 38, "DIRECCIÓN / TEL:")

    c.setFont("Helvetica", 8.5)
    c.drawString(margen + 95, y - 12, (norm.get("cliente_nombre") or "Consumidor Final")[:45])
    c.drawString(margen + 95, y - 25, (norm.get("cliente_documento") or "N/A")[:35])
    dir_cli = norm.get("cliente_direccion") or ""
    tel_cli = norm.get("cliente_telefono") or ""
    contacto_cli = f"{dir_cli} {('Tel: ' + tel_cli) if tel_cli else ''}".strip() or "N/A"
    c.drawString(margen + 95, y - 38, contacto_cli[:50])

    col_der_x = margen + ancho_util * 0.58
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(col_der_x, y - 12, "VENDEDOR:")
    c.drawString(col_der_x, y - 25, "MEDIO DE PAGO:")
    c.drawString(col_der_x, y - 38, "ESTADO:")

    c.setFont("Helvetica", 8.5)
    c.drawString(col_der_x + 82, y - 12, (norm.get("vendedor") or "Administrador")[:30])
    c.drawString(col_der_x + 82, y - 25, (norm.get("metodo_pago") or "Efectivo")[:30])
    c.drawString(col_der_x + 82, y - 38, (norm.get("estado") or "Completada")[:30])

    y -= 23 * mm

    # 3. Tabla de Productos y Servicios
    def dibujar_encabezado_tabla(pos_y):
        c.setFillColor(colors.HexColor("#1E293B"))
        c.rect(margen, pos_y - 18, ancho_util, 18, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(margen + 6, pos_y - 12, "CÓDIGO")
        c.drawString(margen + 58, pos_y - 12, "DESCRIPCIÓN")
        c.drawRightString(margen + ancho_util - 185, pos_y - 12, "CANT.")
        c.drawRightString(margen + ancho_util - 125, pos_y - 12, "VR. UNIT.")
        c.drawRightString(margen + ancho_util - 70, pos_y - 12, "DESC.")
        c.drawRightString(margen + ancho_util - 6, pos_y - 12, "SUBTOTAL")
        return pos_y - 20

    y = dibujar_encabezado_tabla(y)
    c.setFillColor(colors.HexColor("#0F172A"))

    for idx, it in enumerate(norm["items"]):
        lineas_desc = textwrap.wrap(it["nombre"], width=46) or [it["nombre"]]
        alto_fila = max(16, len(lineas_desc) * 11 + 5)

        if y - alto_fila < margen + 48 * mm:
            c.showPage()
            y = alto_p - margen
            y = dibujar_encabezado_tabla(y)

        if idx % 2 == 1:
            c.setFillColor(colors.HexColor("#F8FAFC"))
            c.rect(margen, y - alto_fila + 2, ancho_util, alto_fila, stroke=0, fill=1)

        c.setFillColor(colors.HexColor("#0F172A"))
        c.setFont("Helvetica", 8.5)
        c.drawString(margen + 6, y - 10, (it.get("codigo") or "-")[:10])
        for li_idx, ln_d in enumerate(lineas_desc):
            c.drawString(margen + 58, y - 10 - (li_idx * 11), ln_d)

        cant_txt = f"{it['cantidad']} {it.get('unidad', 'Und')}"
        c.drawRightString(margen + ancho_util - 185, y - 10, cant_txt)
        c.drawRightString(margen + ancho_util - 125, y - 10, formato_moneda_cop(it["precio_unitario"]))
        c.drawRightString(margen + ancho_util - 70, y - 10, formato_moneda_cop(it.get("descuento", 0)))
        c.setFont("Helvetica-Bold", 8.5)
        c.drawRightString(margen + ancho_util - 6, y - 10, formato_moneda_cop(it["subtotal"]))

        c.setStrokeColor(colors.HexColor("#E2E8F0"))
        c.line(margen, y - alto_fila + 2, margen + ancho_util, y - alto_fila + 2)
        y -= alto_fila

    y -= 6 * mm

    # 4. Bloque de Totales y Pagos
    tot_w = 78 * mm
    tot_x = margen + ancho_util - tot_w
    filas_tot = [
        ("Subtotal:", formato_moneda_cop(norm["subtotal_bruto"]), False),
        ("Descuentos:", f"-{formato_moneda_cop(norm['descuento_total'])}", False),
        ("Impuestos / IVA:", formato_moneda_cop(norm["impuesto_total"]), False),
        ("TOTAL A PAGAR:", formato_moneda_cop(norm["total"]), True)
    ]
    if norm["es_credito"] or norm["saldo_pendiente"] > 0:
        abono = max(0.0, norm["total"] - norm["saldo_pendiente"])
        filas_tot.append(("Abono recibido:", formato_moneda_cop(abono), False))
        filas_tot.append(("SALDO PENDIENTE:", formato_moneda_cop(norm["saldo_pendiente"]), True))
    else:
        filas_tot.append(("Valor recibido:", formato_moneda_cop(norm["recibido"]), False))
        filas_tot.append(("Cambio / Vuelto:", formato_moneda_cop(norm["cambio"]), False))

    for etq, val_s, es_bold in filas_tot:
        if es_bold:
            c.setFillColor(colors.HexColor("#FDF2F8"))
            c.rect(tot_x, y - 14, tot_w, 16, stroke=0, fill=1)
            c.setFillColor(colors.HexColor("#9D174D"))
            c.setFont("Helvetica-Bold", 10)
        else:
            c.setFillColor(colors.HexColor("#334155"))
            c.setFont("Helvetica", 9)
        c.drawString(tot_x + 6, y - 10, etq)
        c.drawRightString(tot_x + tot_w - 6, y - 10, val_s)
        y -= 16

    # Pie de página / Eslogan
    y_pie = margen + 12 * mm
    c.setStrokeColor(colors.HexColor("#CBD5E1"))
    c.line(margen, y_pie + 12, margen + ancho_util, y_pie + 12)
    c.setFillColor(colors.HexColor("#475569"))
    c.setFont("Helvetica-Oblique", 9)
    if cfg.get("mostrar_eslogan", True) and neg.get("eslogan"):
        c.drawCentredString(ancho_p / 2, y_pie, neg["eslogan"][:100])
    if cfg.get("pie_factura_extra"):
        c.setFont("Helvetica", 8)
        c.drawCentredString(ancho_p / 2, y_pie - 11, cfg["pie_factura_extra"][:110])

    c.showPage()
    c.save()


# =============================================================================
# DETECCIÓN REAL DE IMPRESORAS E IMPRESIÓN FÍSICA (ESC/POS + SISTEMA)
# =============================================================================
def detectar_impresoras_disponibles():
    """
    Detecta impresoras instaladas en el sistema operativo (CUPS en macOS/Linux,
    win32print/PowerShell en Windows) e impresoras térmicas USB directas.
    Retorna lista de nombres descriptivos.
    """
    impresoras = ["Predeterminada del sistema", "USB Térmica Directa (ESC/POS)"]

    # 1. Detectar dispositivos USB térmicos directos
    try:
        import usb.core
        for cfg in USB_THERMAL_CONFIGS:
            dev = usb.core.find(idVendor=cfg["vid"], idProduct=cfg["pid"])
            if dev is not None:
                etiqueta = f"USB Directa: {cfg.get('model', 'Térmica')} ({cfg['vid']:04x}:{cfg['pid']:04x})"
                if etiqueta not in impresoras:
                    impresoras.append(etiqueta)
    except Exception:
        pass

    # 2. Detectar colas de impresión del Sistema Operativo
    if sys.platform.startswith("win"):
        try:
            import win32print
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            for p in win32print.EnumPrinters(flags):
                nombre_p = p[2]
                if nombre_p and nombre_p not in impresoras:
                    impresoras.append(nombre_p)
        except Exception:
            try:
                out = subprocess.check_output(
                    ["powershell", "-NoProfile", "-Command", "Get-Printer | Select-Object -ExpandProperty Name"],
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                    text=True
                )
                for ln in out.splitlines():
                    ln = ln.strip()
                    if ln and ln not in impresoras:
                        impresoras.append(ln)
            except Exception:
                pass
    else:
        # macOS / Linux (CUPS lpstat)
        try:
            out = subprocess.check_output(["lpstat", "-a"], stderr=subprocess.DEVNULL, timeout=3, text=True)
            for ln in out.splitlines():
                partes = ln.strip().split()
                if partes:
                    nombre_p = partes[0].strip()
                    if nombre_p and nombre_p not in impresoras:
                        impresoras.append(nombre_p)
        except Exception:
            pass

    return impresoras


def _imagen_a_escpos_raster(ruta_logo, max_width_dots=256):
    """
    Convierte una imagen de logo en comando binario ESC/POS `GS v 0` (raster bit image)
    1-bit monocromático centrado para impresoras térmicas de 58mm o 80mm.
    """
    if not PIL_DISPONIBLE or not ruta_logo or not os.path.isfile(ruta_logo):
        return b""
    try:
        with Image.open(ruta_logo) as img:
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                rgba = img.convert("RGBA")
                fondo = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                comp = Image.alpha_composite(fondo, rgba).convert("RGB")
            else:
                comp = img.convert("RGB")

            inv = ImageOps.invert(comp.convert("L"))
            bbox = inv.getbbox()
            if bbox:
                comp = comp.crop(bbox)

            comp.thumbnail((max_width_dots, 140), Image.Resampling.LANCZOS)
            ancho_aligned = ((comp.width + 7) // 8) * 8
            alto = comp.height
            lienzo = Image.new("L", (ancho_aligned, alto), 255)
            lienzo.paste(comp.convert("L"), ((ancho_aligned - comp.width) // 2, 0))

            # En ESC/POS raster: bit 1 = punto negro impreso, bit 0 = blanco.
            # En PIL mode '1' tras invertir: blanco (255) -> negro impreso.
            invertida_bw = ImageOps.invert(lienzo).point(lambda x: 255 if x > 90 else 0, mode="1")
            raw_bytes = invertida_bw.tobytes()

            bytes_por_fila = ancho_aligned // 8
            xL = bytes_por_fila & 0xFF
            xH = (bytes_por_fila >> 8) & 0xFF
            yL = alto & 0xFF
            yH = (alto >> 8) & 0xFF

            # Centrar imagen (ESC a 1) + GS v 0 + alimentar 1 línea
            cmd = b"\x1b\x61\x01" + bytes([0x1D, 0x76, 0x30, 0x00, xL, xH, yL, yH]) + raw_bytes + b"\n\x1b\x61\x00"
            return cmd
    except Exception as e:
        print(f"Aviso convirtiendo logo a raster ESC/POS: {e}")
        return b""


def _codificar_texto_escpos(texto):
    """
    Codifica texto con caracteres en español (á, é, í, ó, ú, ñ, Ñ, ¿, ¡, $)
    usando cp858/cp850 (estándar latinoamericano en impresoras térmicas ESC/POS).
    """
    # Seleccionar tabla de caracteres PC858 / PC850 (ESC t 19 o ESC t 2)
    prefijo_codepage = b"\x1b\x74\x02"
    try:
        return prefijo_codepage + texto.encode("cp850", errors="replace")
    except Exception:
        return texto.encode("cp437", errors="replace")


def _imprimir_por_usb_escpos(norm, cfg):
    """Intenta imprimir directamente en una impresora térmica USB vía pyusb."""
    try:
        import usb.core
        import usb.util
    except ImportError:
        return False, "Librería pyusb no disponible."

    dispositivo = None
    out_ep = 0x01

    # Verificar si el usuario configuró VID/PID específico
    vid_cfg = str(cfg.get("usb_vendor_id", "")).strip()
    pid_cfg = str(cfg.get("usb_product_id", "")).strip()
    if vid_cfg and pid_cfg:
        try:
            v_int = int(vid_cfg, 16) if vid_cfg.startswith("0x") else int(vid_cfg)
            p_int = int(pid_cfg, 16) if pid_cfg.startswith("0x") else int(pid_cfg)
            dispositivo = usb.core.find(idVendor=v_int, idProduct=p_int)
        except Exception:
            dispositivo = None

    if dispositivo is None:
        try:
            for ucfg in USB_THERMAL_CONFIGS:
                dev = usb.core.find(idVendor=ucfg["vid"], idProduct=ucfg["pid"])
                if dev is not None:
                    dispositivo = dev
                    out_ep = ucfg.get("out_ep", 0x01)
                    break
        except Exception as e_find:
            return False, f"Backend USB no disponible en el sistema ({e_find})."

    if dispositivo is None:
        return False, "No se detectó impresora térmica USB directa conectada."

    try:
        try:
            if dispositivo.is_kernel_driver_active(0):
                dispositivo.detach_kernel_driver(0)
        except Exception:
            pass
        try:
            dispositivo.set_configuration()
        except Exception:
            pass

        fmt = str(cfg.get("formato_papel", "58mm"))
        if fmt not in ("58mm", "80mm"):
            fmt = "58mm"

        neg = norm["negocio"]
        logo_bytes = b""
        if cfg.get("mostrar_logo", True) and neg.get("logo_path"):
            max_dots = 240 if fmt == "58mm" else 360
            logo_bytes = _imagen_a_escpos_raster(neg["logo_path"], max_width_dots=max_dots)

        texto = generar_texto_factura(norm, formato=fmt, config_impresora=cfg)
        cuerpo_bytes = _codificar_texto_escpos(texto + "\n\n\n\n")

        corte_bytes = b"\x1d\x56\x42\x00" if cfg.get("corte_automatico", True) else b""
        cajon_bytes = b"\x1b\x70\x00\x19\xfa" if cfg.get("abrir_cajon", False) else b""

        payload = b"\x1b\x40" + logo_bytes + cuerpo_bytes + corte_bytes
        copias = max(1, min(10, int(cfg.get("copias", 1) or 1)))

        for i in range(copias):
            bloque = (cajon_bytes + payload) if i == 0 else payload
            # Enviar en fragmentos de 1024 bytes para no saturar el buffer USB
            for offset in range(0, len(bloque), 1024):
                dispositivo.write(out_ep, bloque[offset:offset + 1024], timeout=4000)

        return True, f"Impreso correctamente por USB ESC/POS ({copias} copia(s))."
    except Exception as e:
        return False, f"Error comunicando con impresora USB ESC/POS: {e}"


def _imprimir_por_sistema_os(norm, cfg):
    """
    Imprime utilizando la cola del sistema operativo (CUPS `lp` en macOS/Linux
    o `win32print` / PDF en Windows) respetando el formato (58mm, 80mm, A4) y copias.
    """
    fmt = str(cfg.get("formato_papel", "58mm")).strip()
    impresora_sel = str(cfg.get("impresora_nombre", "Predeterminada del sistema")).strip()
    copias = max(1, min(10, int(cfg.get("copias", 1) or 1)))

    # Generar PDF temporal en el formato exacto
    fd, temp_pdf = tempfile.mkstemp(prefix=f"vmpos_print_{fmt}_", suffix=".pdf")
    os.close(fd)
    ok_pdf, res_pdf = generar_pdf_factura(norm, ruta_salida=temp_pdf, formato=fmt, config_impresora=cfg)
    if not ok_pdf:
        return False, res_pdf

    if not sys.platform.startswith("win"):
        # Verificar que exista al menos una impresora configurada en CUPS
        try:
            out_p = subprocess.check_output(["lpstat", "-a"], stderr=subprocess.DEVNULL, timeout=3, text=True).strip()
        except Exception:
            out_p = ""

        if not out_p:
            try:
                os.remove(temp_pdf)
            except Exception:
                pass
            return False, "No hay impresoras instaladas ni conectadas en la cola del sistema (CUPS)."

        cmd = ["lp", "-n", str(copias)]
        if impresora_sel and impresora_sel not in ("Predeterminada del sistema", "USB Térmica Directa (ESC/POS)") and not impresora_sel.startswith("USB Directa:"):
            cmd.extend(["-d", impresora_sel])

        if fmt == "58mm":
            cmd.extend(["-o", "media=Custom.58x210mm", "-o", "fit-to-page"])
        elif fmt == "80mm":
            cmd.extend(["-o", "media=Custom.80x210mm", "-o", "fit-to-page"])
        else:
            cmd.extend(["-o", "media=A4", "-o", "fit-to-page"])

        cmd.append(temp_pdf)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            try:
                os.remove(temp_pdf)
            except Exception:
                pass
            if proc.returncode == 0:
                return True, f"Enviado a la impresora del sistema ({fmt}, {copias} copia(s))."
            return False, f"La cola de impresión rechazó el trabajo: {proc.stderr.strip() or proc.stdout.strip()}"
        except Exception as e:
            return False, f"No se pudo enviar a la impresora del sistema: {e}"
    else:
        # Windows: usar win32print RAW para térmicas o ShellExecute para PDF
        try:
            import win32print
            nombre_dest = impresora_sel
            if not nombre_dest or nombre_dest in ("Predeterminada del sistema", "USB Térmica Directa (ESC/POS)"):
                nombre_dest = win32print.GetDefaultPrinter()
            if not nombre_dest:
                return False, "No hay impresora predeterminada configurada en Windows."

            if fmt in ("58mm", "80mm"):
                neg = norm["negocio"]
                logo_b = b""
                if cfg.get("mostrar_logo", True) and neg.get("logo_path"):
                    logo_b = _imagen_a_escpos_raster(neg["logo_path"], max_width_dots=240 if fmt == "58mm" else 360)
                txt_b = _codificar_texto_escpos(generar_texto_factura(norm, formato=fmt, config_impresora=cfg) + "\n\n\n\n")
                corte_b = b"\x1d\x56\x42\x00" if cfg.get("corte_automatico", True) else b""
                raw_payload = b"\x1b\x40" + logo_b + txt_b + corte_b

                hPrinter = win32print.OpenPrinter(nombre_dest)
                try:
                    for _ in range(copias):
                        hJob = win32print.StartDocPrinter(hPrinter, 1, (f"Comprobante {norm['factura']}", None, "RAW"))
                        win32print.StartPagePrinter(hPrinter)
                        win32print.WritePrinter(hPrinter, raw_payload)
                        win32print.EndPagePrinter(hPrinter)
                        win32print.EndDocPrinter(hPrinter)
                finally:
                    win32print.ClosePrinter(hPrinter)
                return True, f"Impreso en '{nombre_dest}' ({fmt}, {copias} copia(s))."
            else:
                import win32api
                for _ in range(copias):
                    win32api.ShellExecute(0, "print", temp_pdf, f'/d:"{nombre_dest}"', ".", 0)
                return True, f"Enviado documento A4 a '{nombre_dest}'."
        except Exception as e:
            return False, f"No se pudo imprimir en Windows: {e}"


def imprimir_factura_unificada(datos_venta, config_override=None):
    """
    Punto de entrada único para imprimir cualquier factura o comprobante.
    Intenta el método configurado ('auto', 'escpos_usb', 'sistema', 'solo_pdf')
    y retorna siempre (exito: bool, mensaje: str).
    Nunca finge éxito si no hay impresora conectada.
    """
    norm = normalizar_datos_factura(datos_venta)
    cfg = dict(business_mgr.obtener_config_impresora())
    if isinstance(config_override, dict):
        cfg.update(config_override)

    metodo = str(cfg.get("metodo_impresion", "auto") or "auto").lower()
    fmt = str(cfg.get("formato_papel", "58mm") or "58mm")
    imp_sel = str(cfg.get("impresora_nombre", "") or "")

    if metodo == "solo_pdf":
        return generar_pdf_factura(norm, formato=fmt, config_impresora=cfg)

    if metodo == "escpos_usb" or imp_sel.startswith("USB"):
        return _imprimir_por_usb_escpos(norm, cfg)

    if metodo == "sistema" or fmt == "A4":
        return _imprimir_por_sistema_os(norm, cfg)

    # Modo 'auto': para 58mm/80mm probar primero USB ESC/POS directo; si no hay, probar cola del SO
    ok_usb, msg_usb = _imprimir_por_usb_escpos(norm, cfg)
    if ok_usb:
        return True, msg_usb

    ok_sys, msg_sys = _imprimir_por_sistema_os(norm, cfg)
    if ok_sys:
        return True, msg_sys

    return False, (
        "No se detectó ninguna impresora física conectada ni cola activa en el sistema.\n"
        f"• USB ESC/POS: {msg_usb}\n"
        f"• Sistema Operativo: {msg_sys}\n\n"
        "Puedes guardar o exportar el comprobante en PDF desde la vista previa."
    )


def imprimir_prueba_configuracion(config_override=None):
    """
    Genera y envía una página de prueba con los datos actuales del negocio,
    logo, caracteres en español y formato seleccionado.
    Retorna (exito: bool, mensaje: str, datos_prueba: dict)
    """
    datos_prueba = construir_datos_factura_prueba()
    exito, mensaje = imprimir_factura_unificada(datos_prueba, config_override=config_override)
    return exito, mensaje, datos_prueba


# =============================================================================
# DIÁLOGO INTERACTIVO DE VISTA PREVIA, IMPRESIÓN Y EXPORTACIÓN A PDF
# =============================================================================
def mostrar_dialogo_factura(
    parent,
    datos_venta,
    modo_confirmacion_venta=False,
    on_confirmar_venta=None,
    config_override=None
):
    """
    Muestra la ventana de vista previa del comprobante (con logo real, selector en vivo
    de formato 58mm / 80mm / A4, exportación a PDF e impresión).
    - Si `modo_confirmacion_venta=True`, muestra los botones para confirmar y registrar la venta.
    - Si `modo_confirmacion_venta=False`, funciona como visor/reimpresor (para historial o prueba).
    """
    business_mgr.recargar()
    norm = normalizar_datos_factura(datos_venta)
    neg = norm["negocio"]

    cfg = dict(business_mgr.obtener_config_impresora())
    if isinstance(config_override, dict):
        cfg.update(config_override)

    dlg = tk.Toplevel(parent) if parent else tk.Tk()
    titulo_ventana = "🧾 Vista Previa y Confirmación de Comprobante" if modo_confirmacion_venta else f"🧾 Comprobante {norm['factura']} — Vista Previa / Reimpresión"
    dlg.title(titulo_ventana)
    if parent:
        dlg.transient(parent)
        dlg.grab_set()

    t = aplicar_tema(dlg)
    dlg.configure(bg=t["bg_app"])
    calcular_geometria_segura(dlg, 720, 760, min_w=580, min_h=600)

    # Header con el color corporativo configurado
    color_hdr = business_mgr.color_barra or t["bg_header"]
    hdr = tk.Frame(dlg, bg=color_hdr, height=52)
    hdr.pack(fill="x", side="top")
    hdr.pack_propagate(False)

    tk.Label(
        hdr,
        text=f"🧾 {neg.get('tipo_comprobante', 'RECIBO DE VENTA')} — {norm['factura']}",
        font=("Segoe UI", 12, "bold"),
        bg=color_hdr,
        fg="white"
    ).pack(side="left", padx=16)

    # Barra de herramientas de formato (58mm, 80mm, A4) y PDF
    toolbar = tk.Frame(dlg, bg=t["bg_card"], relief="solid", bd=1, padx=12, pady=8)
    toolbar.pack(fill="x", padx=14, pady=(10, 6))

    tk.Label(
        toolbar,
        text="Formato de vista / PDF:",
        font=("Segoe UI", 9, "bold"),
        bg=t["bg_card"],
        fg=t["text_main"]
    ).pack(side="left", padx=(0, 6))

    var_formato = tk.StringVar(master=dlg, value=str(cfg.get("formato_papel", "58mm")))
    cb_fmt = ttk.Combobox(
        toolbar,
        textvariable=var_formato,
        values=["58mm", "80mm", "A4"],
        state="readonly",
        width=10
    )
    cb_fmt.pack(side="left", padx=(0, 12))

    lbl_info_imp = tk.Label(
        toolbar,
        text=f"🖨️ Impresora: {cfg.get('impresora_nombre', 'Predeterminada')}",
        font=("Segoe UI", 9),
        bg=t["bg_card"],
        fg=t["text_sec"]
    )
    lbl_info_imp.pack(side="left", padx=6)

    def accion_exportar_pdf():
        fmt_actual = var_formato.get()
        cfg_local = dict(cfg)
        cfg_local["formato_papel"] = fmt_actual
        num_limpio = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in str(norm["factura"]))
        ruta_sugerida = f"Comprobante_{num_limpio}_{fmt_actual}.pdf"
        ruta_dest = filedialog.asksaveasfilename(
            parent=dlg,
            title="Guardar comprobante en PDF",
            initialfile=ruta_sugerida,
            defaultextension=".pdf",
            filetypes=[("Archivo PDF", "*.pdf")]
        )
        if not ruta_dest:
            return
        ok, msg = generar_pdf_factura(norm, ruta_salida=ruta_dest, formato=fmt_actual, config_impresora=cfg_local)
        if ok:
            messagebox.showinfo("PDF Generado", f"El comprobante se exportó correctamente en formato {fmt_actual}:\n\n{msg}", parent=dlg)
        else:
            messagebox.showerror("Error PDF", msg, parent=dlg)

    crear_boton(
        toolbar,
        text="📄 Exportar PDF",
        command=accion_exportar_pdf,
        tipo="info",
        tam_fuente=9
    ).pack(side="right", padx=4)

    # Contenedor central simulando hoja/tirilla de papel blanco
    paper_outer = tk.Frame(dlg, bg=t["bg_app"])
    paper_outer.pack(fill="both", expand=True, padx=14, pady=4)

    paper_card = tk.Frame(paper_outer, bg="#FFFFFF", relief="solid", bd=1, padx=14, pady=10)
    paper_card.pack(fill="both", expand=True)

    # Logo real en la parte superior del comprobante si está activo
    lbl_logo_preview = tk.Label(paper_card, bg="#FFFFFF")
    logo_path = neg.get("logo_path", "")
    if cfg.get("mostrar_logo", True) and logo_path and os.path.isfile(logo_path) and PIL_DISPONIBLE:
        try:
            with Image.open(logo_path) as im_l:
                im_l.load()
                if im_l.mode in ("RGBA", "LA") or (im_l.mode == "P" and "transparency" in im_l.info):
                    rgba = im_l.convert("RGBA")
                    bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                    im_disp = Image.alpha_composite(bg, rgba).convert("RGB")
                else:
                    im_disp = im_l.convert("RGB")
                im_disp.thumbnail((150, 75), Image.Resampling.LANCZOS)
                tk_img = ImageTk.PhotoImage(im_disp, master=dlg)
                lbl_logo_preview.configure(image=tk_img)
                lbl_logo_preview.image = tk_img
                lbl_logo_preview.pack(pady=(2, 6))
        except Exception as e_lp:
            print(f"Aviso cargando logo en vista previa: {e_lp}")

    txt_frame = tk.Frame(paper_card, bg="#FFFFFF")
    txt_frame.pack(fill="both", expand=True)

    sc_y = ttk.Scrollbar(txt_frame, orient="vertical")
    sc_y.pack(side="right", fill="y")

    texto_widget = tk.Text(
        txt_frame,
        font=("Courier New", 10),
        bg="#FFFFFF",
        fg="#0F172A",
        relief="flat",
        bd=0,
        yscrollcommand=sc_y.set,
        wrap="none"
    )
    texto_widget.pack(side="left", fill="both", expand=True)
    sc_y.config(command=texto_widget.yview)
    texto_widget.tag_configure("centrado", justify="center")
    texto_widget.tag_configure("izquierda", justify="left")

    def renderizar_vista(*_):
        fmt_sel = var_formato.get()
        cfg_local = dict(cfg)
        cfg_local["formato_papel"] = fmt_sel
        contenido = generar_texto_factura(norm, formato=fmt_sel, config_impresora=cfg_local)
        texto_widget.config(state="normal")
        texto_widget.delete("1.0", "end")
        tag_uso = "centrado" if fmt_sel in ("58mm", "80mm") else "izquierda"
        texto_widget.insert("end", contenido, tag_uso)
        texto_widget.config(state="disabled")

    var_formato.trace_add("write", renderizar_vista)
    renderizar_vista()

    # Pie de botones de acción
    acciones = tk.Frame(dlg, bg=t["bg_app"], pady=10)
    acciones.pack(fill="x", padx=14, side="bottom")

    if modo_confirmacion_venta and callable(on_confirmar_venta):
        def confirmar_con_impresion():
            fmt_sel = var_formato.get()
            dlg.destroy()
            on_confirmar_venta(imprimir=True, formato_seleccionado=fmt_sel)

        def confirmar_sin_impresion():
            fmt_sel = var_formato.get()
            dlg.destroy()
            on_confirmar_venta(imprimir=False, formato_seleccionado=fmt_sel)

        crear_boton(
            acciones,
            text="🖨️ Imprimir y Registrar Venta",
            command=confirmar_con_impresion,
            tipo="success",
            tam_fuente=10
        ).pack(side="right", padx=4)

        crear_boton(
            acciones,
            text="✅ Registrar sin Imprimir",
            command=confirmar_sin_impresion,
            tipo="primary",
            tam_fuente=10
        ).pack(side="right", padx=4)

        crear_boton(
            acciones,
            text="✖ Cancelar",
            command=dlg.destroy,
            tipo="secondary",
            tam_fuente=10
        ).pack(side="left", padx=4)
    else:
        def accion_imprimir_ahora():
            cfg_local = dict(cfg)
            cfg_local["formato_papel"] = var_formato.get()
            ok, msg = imprimir_factura_unificada(norm, config_override=cfg_local)
            if ok:
                messagebox.showinfo("Impresión Exitosa", msg, parent=dlg)
            else:
                 messagebox.showwarning("Impresora no disponible", msg, parent=dlg)

        crear_boton(
            acciones,
            text="🖨️ Imprimir Comprobante",
            command=accion_imprimir_ahora,
            tipo="success",
            tam_fuente=10
        ).pack(side="right", padx=4)

        crear_boton(
            acciones,
            text="✖ Cerrar",
            command=dlg.destroy,
            tipo="secondary",
            tam_fuente=10
        ).pack(side="left", padx=4)

    return dlg
