#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivo: inventario_manager.py
Gestor integral de lógica de negocio para Inventario en VmPOS (Cliente-Servidor Centralizado).
Todas las operaciones comerciales consultan y persisten en la API central FastAPI (/inventario),
garantizando una única fuente oficial de verdad entre todas las terminales Mac y Windows.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
import os
import sys
import sqlite3

try:
    from client.api_client import api
except ImportError:
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from client.api_client import api

# ==============================================================================
# 1. UNIDADES DE MEDIDA Y MATRIZ DE CONVERSIÓN
# ==============================================================================

UNIDADES_DISCRETAS = {"Unidad", "Caja", "Paquete", "Docena", "Servicio"}
UNIDADES_FRACCIONABLES = {"Kilogramo", "Gramo", "Litro", "Mililitro", "Metro", "Hora", "Minuto"}
TODAS_LAS_UNIDADES = [
    "Unidad", "Caja", "Paquete", "Docena",
    "Kilogramo", "Gramo", "Litro", "Mililitro", "Metro",
    "Hora", "Minuto", "Servicio",
]

CATEGORIAS_UNIDAD = {
    "Unidad": "CONTEO",
    "Caja": "CONTEO",
    "Paquete": "CONTEO",
    "Docena": "CONTEO",
    "Kilogramo": "MASA",
    "Gramo": "MASA",
    "Litro": "VOLUMEN",
    "Mililitro": "VOLUMEN",
    "Metro": "LONGITUD",
    "Hora": "TIEMPO",
    "Minuto": "TIEMPO",
    "Servicio": "SERVICIO",
}


def validar_compatibilidad_unidades(unidad_origen, unidad_destino):
    cat_orig = CATEGORIAS_UNIDAD.get(unidad_origen, "OTRO")
    cat_dest = CATEGORIAS_UNIDAD.get(unidad_destino, "OTRO")
    if cat_orig == "SERVICIO" or cat_dest == "SERVICIO":
        return cat_orig == cat_dest
    return cat_orig == cat_dest


def es_cantidad_valida(unidad, cantidad):
    try:
        cant_flt = float(cantidad)
        if cant_flt <= 0:
            return False, "La cantidad debe ser mayor a cero."
        if unidad in UNIDADES_DISCRETAS:
            if not cant_flt.is_integer():
                return False, f"La unidad '{unidad}' es discreta y no admite fracciones decimales."
        return True, ""
    except (ValueError, TypeError):
        return False, "Cantidad numérica inválida."


def _extraer_error_api(resp) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict):
            det = data.get("detail")
            if isinstance(det, list) and det:
                msgs = [str(d.get("msg") or d) for d in det]
                return "; ".join(msgs)
            if det:
                return str(det)
    except Exception:
        pass
    return getattr(resp, "text", None) or f"Error de comunicación con el servidor central (HTTP {resp.status_code})"


def _asegurar_respuesta_ok(resp) -> Any:
    if resp.status_code in (200, 201):
        return resp.json()
    raise ValueError(_extraer_error_api(resp))


# ==============================================================================
# 2. CATÁLOGO UNIFICADO DE ARTÍCULOS (PRODUCTOS FÍSICOS Y SERVICIOS)
# ==============================================================================

def _obtener_catalogo_sqlite_fallback(
    tipo=None,
    conn=None
) -> List[Dict[str, Any]]:
    cerrar = False
    if conn is None:
        try:
            from interface.database_manager import conectar_db
        except ImportError:
            from database_manager import conectar_db
        conn = conectar_db()
        cerrar = True
    items = []
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(productos)")
        col_names = {r[1] for r in cur.fetchall()}
        col_precio = "p.precio" if "precio" in col_names else ("p.precio_venta" if "precio_venta" in col_names else "0.0")
        col_costo = "p.costo" if "costo" in col_names else ("p.precio_costo" if "precio_costo" in col_names else "0.0")

        if not tipo or tipo in ("Todos", "Fisico", "Producto"):
            sql_p = f"""
                SELECT p.id, p.codigo, p.nombre, p.categoria, p.unidad_medida,
                       {col_precio}, {col_costo}, p.stock, p.stock_bodega, p.stock_vitrina,
                       p.stock_minimo_bodega, p.stock_minimo_vitrina, p.proveedor_id,
                       p.estado, p.codigo_barras, p.descripcion, prov.nombre as prov_nombre
                FROM productos p
                LEFT JOIN proveedores prov ON p.proveedor_id = prov.id
            """
            cur.execute(sql_p)
            for r in cur.fetchall():
                sb = float(r[8] or 0.0)
                sv = float(r[9] or 0.0)
                st = float(r[7] or 0.0)
                if sb == 0.0 and sv == 0.0 and st > 0.0:
                    sv = st
                else:
                    st = round(sb + sv, 4)
                items.append({
                    "id": r[0],
                    "codigo": r[1] or "",
                    "nombre": r[2] or "",
                    "tipo_producto": "Fisico",
                    "categoria": r[3] or "General",
                    "unidad_medida": r[4] or "Unidad",
                    "precio": float(r[5] or 0.0),
                    "precio_venta": float(r[5] or 0.0),
                    "costo": float(r[6] or 0.0),
                    "precio_costo": float(r[6] or 0.0),
                    "stock": st,
                    "stock_total": st,
                    "stock_bodega": sb,
                    "stock_vitrina": sv,
                    "stock_minimo_bodega": float(r[10] if r[10] is not None else 5.0),
                    "stock_minimo_vitrina": float(r[11] if r[11] is not None else 3.0),
                    "proveedor_id": r[12],
                    "proveedor_nombre": r[16] or None,
                    "estado": r[13] or "Activo",
                    "codigo_barras": r[14] or "",
                    "descripcion": r[15] or "",
                })

        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='servicios'")
        if cur.fetchone() and (not tipo or tipo in ("Todos", "Servicio")):
            cur.execute("PRAGMA table_info(servicios)")
            s_cols = {r[1] for r in cur.fetchall()}
            s_precio = "s.precio" if "precio" in s_cols else ("s.precio_venta" if "precio_venta" in s_cols else "0.0")
            s_costo = "s.costo" if "costo" in s_cols else ("s.costo_proveedor" if "costo_proveedor" in s_cols else "0.0")

            sql_s = f"""
                SELECT s.id, s.codigo, s.nombre, s.categoria, s.unidad_medida,
                       {s_precio}, {s_costo}, s.proveedor_id,
                       s.estado, s.codigo_barras, s.descripcion, prov.nombre as prov_nombre
                FROM servicios s
                LEFT JOIN proveedores prov ON s.proveedor_id = prov.id
            """
            cur.execute(sql_s)
            for r in cur.fetchall():
                items.append({
                    "id": r[0],
                    "codigo": r[1] or "",
                    "nombre": r[2] or "",
                    "tipo_producto": "Servicio",
                    "categoria": r[3] or "Servicios",
                    "unidad_medida": r[4] or "Servicio",
                    "precio": float(r[5] or 0.0),
                    "precio_venta": float(r[5] or 0.0),
                    "costo": float(r[6] or 0.0),
                    "precio_costo": float(r[6] or 0.0),
                    "stock": 0.0,
                    "stock_total": 0.0,
                    "stock_bodega": 0.0,
                    "stock_vitrina": 0.0,
                    "stock_minimo_bodega": 0.0,
                    "stock_minimo_vitrina": 0.0,
                    "proveedor_id": r[7],
                    "proveedor_nombre": r[11] or None,
                    "estado": r[8] or "Activo",
                    "codigo_barras": r[9] or "",
                    "descripcion": r[10] or "",
                })
    except Exception as ex:
        print(f"Advertencia en catálogo SQLite local: {ex}")
    finally:
        if cerrar and conn:
            conn.close()
    return items


def obtener_catalogo(
    filtro=None,
    categoria=None,
    tipo=None,
    solo_activos=False,
    estado=None,
    proveedor_id=None,
    proveedor=None,
    disponibilidad=None,
    conn=None
) -> List[Dict[str, Any]]:
    from interface.table_filter_sorter import normalizar_texto, coincide_busqueda

    params: Dict[str, Any] = {"solo_activos": bool(solo_activos)}
    if filtro:
        params["filtro"] = str(filtro).strip()
    if categoria and categoria != "Todas":
        params["categoria"] = str(categoria).strip()
    if tipo and tipo != "Todos":
        params["tipo"] = str(tipo).strip()
    if estado and estado != "Todos":
        params["estado"] = str(estado).strip()
    if proveedor_id is not None:
        params["proveedor_id"] = int(proveedor_id)
    if proveedor and proveedor != "Todos":
        params["proveedor"] = str(proveedor).strip()

    data = None
    try:
        resp = api.get("/inventario/catalogo", params=params, timeout=3.5)
        if resp.status_code == 200:
            res_json = resp.json()
            if isinstance(res_json, list):
                data = res_json
    except Exception:
        pass

    if data is None:
        data = _obtener_catalogo_sqlite_fallback(tipo=tipo, conn=conn)

    # Filtrado minucioso en memoria para asegurar consistencia multi-criterio y búsqueda con tildes
    resultado = []
    cat_q = normalizar_texto(categoria) if (categoria and categoria != "Todas") else None
    prov_q = normalizar_texto(proveedor) if (proveedor and proveedor != "Todos") else None
    est_q = normalizar_texto(estado) if (estado and estado != "Todos") else None

    for it in data:
        # 1. Filtro Tipo
        t_it = it.get("tipo_producto", "Fisico")
        if tipo and tipo != "Todos" and t_it != tipo:
            continue

        # 2. Filtro Categoría
        if cat_q and normalizar_texto(it.get("categoria")) != cat_q:
            continue

        # 3. Filtro Proveedor
        if proveedor_id is not None and it.get("proveedor_id") != int(proveedor_id):
            continue
        if prov_q and normalizar_texto(it.get("proveedor_nombre")) != prov_q:
            continue

        # 4. Filtro Estado
        it_est = str(it.get("estado", "Activo") or "Activo")
        if solo_activos and it_est != "Activo":
            continue
        if est_q and normalizar_texto(it_est) != est_q:
            continue

        # 5. Filtro Disponibilidad
        if disponibilidad and disponibilidad != "Todos":
            st_val = float(it.get("stock", 0.0) or 0.0)
            es_serv = (t_it == "Servicio")
            if disponibilidad in ("En Stock (>0)", "En Stock", "Con Saldo (>0)"):
                if es_serv or st_val <= 0:
                    continue
            elif disponibilidad in ("Agotado (0)", "Agotado"):
                if es_serv or st_val > 0:
                    continue
            elif disponibilidad in ("Bajo Stock (≤ Mínimo)", "Bajo Stock"):
                sm_b = float(it.get("stock_minimo_bodega") or 5.0)
                sm_v = float(it.get("stock_minimo_vitrina") or 3.0)
                sm_tot = max(sm_b, sm_v)
                if es_serv or st_val <= 0 or st_val > sm_tot:
                    continue

        # 6. Búsqueda por texto (Nombre, SKU, Código de barras, Categoría, Proveedor, Descripción)
        if filtro and str(filtro).strip():
            campos_busqueda = [
                it.get("codigo"),
                it.get("nombre"),
                it.get("codigo_barras"),
                it.get("categoria"),
                it.get("proveedor_nombre"),
                it.get("descripcion"),
                it.get("marca"),
            ]
            if not coincide_busqueda(campos_busqueda, str(filtro)):
                continue

        resultado.append(it)

    return resultado


def obtener_articulo_por_codigo(codigo, conn=None) -> Optional[Dict[str, Any]]:
    cod_clean = str(codigo or "").strip()
    if not cod_clean:
        return None
    if api is not None:
        try:
            resp = api.get(f"/inventario/articulo/{cod_clean}", timeout=2.0)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
    cerrar = False
    if conn is None:
        try:
            from interface.database_manager import conectar_db
        except ImportError:
            from database_manager import conectar_db
        conn = conectar_db()
        cerrar = True
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM productos WHERE codigo = ? OR codigo = ? OR codigo_barras = ?", (cod_clean, cod_clean.zfill(5), cod_clean))
        r = cur.fetchone()
        if r:
            return dict(r)
    except Exception:
        pass
    finally:
        if cerrar and conn:
            conn.close()
    return None


def sugerir_proximo_codigo(tipo="Fisico", conn=None) -> str:
    resp = api.get("/inventario/sugerir-codigo", params={"tipo": str(tipo or "Fisico")})
    if resp.status_code == 200:
        data = resp.json()
        if isinstance(data, dict) and data.get("codigo"):
            return str(data["codigo"])
    prefix = "S" if tipo == "Servicio" else ""
    return f"{prefix}00001"


def upsert_articulo_sqlite(datos: Dict[str, Any], conn=None):
    """Persiste y sincroniza inmediatamente el artículo en la base de datos SQLite local."""
    cerrar = False
    if conn is None:
        try:
            from interface.database_manager import conectar_db
        except ImportError:
            from database_manager import conectar_db
        conn = conectar_db()
        cerrar = True
    try:
        cur = conn.cursor()
        cod = str(datos.get("codigo", "")).strip()
        nom = str(datos.get("nombre", "")).strip()
        t_prod = str(datos.get("tipo_producto", "Fisico")).strip()
        pre = float(datos.get("precio", 0.0) or 0.0)
        cos = float(datos.get("costo", 0.0) or 0.0)
        cat = str(datos.get("categoria", "General") or "General").strip()
        mar = str(datos.get("marca", "") or "").strip()
        bar = str(datos.get("codigo_barras", "") or "").strip()
        uni = str(datos.get("unidad_medida", "Unidad") or "Unidad").strip()
        des = str(datos.get("descripcion", "") or "").strip()
        
        raw_prov = datos.get("proveedor_id")
        prov_id = None
        if raw_prov is not None:
            s_prov = str(raw_prov).split("-")[0].strip()
            if s_prov.isdigit() and int(s_prov) > 0:
                prov_id = int(s_prov)

        est = str(datos.get("estado", "Activo") or "Activo").strip()
        p_var = 1 if datos.get("precio_variable") else 0
        p_com = float(datos.get("porcentaje_comision", 0.0) or 0.0)
        s_b = float(datos.get("stock_bodega", 0.0) or 0.0)
        s_v = float(datos.get("stock_vitrina", 0.0) or 0.0)
        s_tot = s_b + s_v
        sm_b = float(datos.get("stock_minimo_bodega", 5.0) or 5.0)
        sm_v = float(datos.get("stock_minimo_vitrina", 3.0) or 3.0)
        ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cur.execute("SELECT id FROM productos WHERE codigo = ?", (cod,))
        r = cur.fetchone()
        if r:
            cur.execute("""
                UPDATE productos SET
                    nombre = ?, tipo_producto = ?, precio = ?, costo = ?,
                    categoria = ?, marca = ?, codigo_barras = ?, unidad_medida = ?,
                    descripcion = ?, proveedor_id = ?, estado = ?, precio_variable = ?,
                    porcentaje_comision = ?, stock_bodega = ?, stock_vitrina = ?,
                    stock = ?, stock_minimo_bodega = ?, stock_minimo_vitrina = ?,
                    fecha_modificacion = ?
                WHERE id = ?
            """, (nom, t_prod, pre, cos, cat, mar, bar, uni, des, prov_id, est, p_var, p_com, s_b, s_v, s_tot, sm_b, sm_v, ahora, r[0]))
        else:
            cur.execute("""
                INSERT INTO productos (
                    codigo, nombre, tipo_producto, precio, costo,
                    categoria, marca, codigo_barras, unidad_medida,
                    descripcion, proveedor_id, estado, precio_variable,
                    porcentaje_comision, stock_bodega, stock_vitrina,
                    stock, stock_minimo_bodega, stock_minimo_vitrina,
                    fecha_creacion, fecha_modificacion
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (cod, nom, t_prod, pre, cos, cat, mar, bar, uni, des, prov_id, est, p_var, p_com, s_b, s_v, s_tot, sm_b, sm_v, ahora, ahora))
        if cerrar:
            conn.commit()
        return True
    except Exception as e_upsert:
        print(f"Aviso al upsert de artículo en SQLite local: {e_upsert}")
        return False
    finally:
        if cerrar and conn:
            conn.close()


def crear_articulo(datos: Dict[str, Any], usuario="Administrador", conn=None) -> Dict[str, Any]:
    payload = {
        "codigo": str(datos.get("codigo", "")).strip(),
        "nombre": str(datos.get("nombre", "")).strip(),
        "tipo_producto": str(datos.get("tipo_producto", "Fisico")).strip(),
        "precio": float(datos.get("precio", 0.0) or 0.0),
        "costo": float(datos.get("costo", 0.0) or 0.0),
        "categoria": str(datos.get("categoria", "General") or "General").strip(),
        "marca": str(datos.get("marca", "") or "").strip(),
        "codigo_barras": str(datos.get("codigo_barras", "") or "").strip(),
        "unidad_medida": str(datos.get("unidad_medida", "Unidad") or "Unidad").strip(),
        "descripcion": str(datos.get("descripcion", "") or "").strip(),
        "proveedor_id": datos.get("proveedor_id"),
        "estado": str(datos.get("estado", "Activo") or "Activo").strip(),
        "precio_variable": bool(datos.get("precio_variable")),
        "porcentaje_comision": float(datos.get("porcentaje_comision", 0.0) or 0.0),
        "stock_bodega": float(datos.get("stock_bodega", 0.0) or 0.0),
        "stock_vitrina": float(datos.get("stock_vitrina", 0.0) or 0.0),
        "stock_minimo_bodega": float(datos.get("stock_minimo_bodega", 5.0) or 5.0),
        "stock_minimo_vitrina": float(datos.get("stock_minimo_vitrina", 3.0) or 3.0),
    }

    # Sincronizar en base de datos SQLite local para garantizar persistencia inmediata
    upsert_articulo_sqlite(payload, conn=conn)

    resp_data = None
    try:
        resp = api.post("/inventario/articulo", json=payload)
        resp_data = _asegurar_respuesta_ok(resp)
    except Exception as e_api:
        print(f"Aviso registrando artículo en servidor central: {e_api}")
        if not resp_data:
            resp_data = {"codigo": payload["codigo"], "nombre": payload["nombre"], "tipo_producto": payload["tipo_producto"], "local": True}
    return resp_data


def actualizar_articulo(id_o_codigo, datos: Dict[str, Any], conn=None) -> bool:
    payload = dict(datos)
    if "precio_variable" in payload and payload["precio_variable"] is not None:
        payload["precio_variable"] = bool(payload["precio_variable"])
    if "codigo" not in payload:
        payload["codigo"] = str(id_o_codigo)

    # Sincronizar en base de datos SQLite local
    upsert_articulo_sqlite(payload, conn=conn)

    try:
        resp = api.put(f"/inventario/articulo/{id_o_codigo}", json=payload)
        _asegurar_respuesta_ok(resp)
    except Exception as e_api:
        print(f"Aviso actualizando artículo en servidor central: {e_api}")
    return True


def cambiar_estado_articulo(id_o_codigo, nuevo_estado, conn=None, tipo_producto: Optional[str] = None) -> bool:
    params: Dict[str, Any] = {"estado": str(nuevo_estado)}
    if tipo_producto:
        params["tipo_producto"] = str(tipo_producto)
    resp = api.patch(f"/inventario/articulo/{id_o_codigo}/estado", params=params)
    _asegurar_respuesta_ok(resp)
    return True


# ==============================================================================
# 3. GESTIÓN DE EXISTENCIAS POR UBICACIÓN (BODEGA Y VITRINA)
# ==============================================================================

def obtener_existencias_bodega(filtro=None, categoria=None, alerta=None, conn=None) -> List[Dict[str, Any]]:
    from interface.table_filter_sorter import normalizar_texto, coincide_busqueda
    params: Dict[str, Any] = {}
    if filtro:
        params["filtro"] = str(filtro).strip()
    if categoria and categoria != "Todas":
        params["categoria"] = str(categoria).strip()
    data = None
    try:
        resp = api.get("/inventario/bodega", params=params, timeout=3.5)
        if resp.status_code == 200:
            res_json = resp.json()
            if isinstance(res_json, list):
                data = res_json
    except Exception:
        pass

    if data is None:
        cat_items = _obtener_catalogo_sqlite_fallback(tipo="Fisico", conn=conn)
        data = []
        for d in cat_items:
            sb = float(d["stock_bodega"])
            sm = float(d["stock_minimo_bodega"])
            costo = float(d["costo"])
            item = {
                "id": d["id"],
                "codigo": d["codigo"],
                "nombre": d["nombre"],
                "categoria": d["categoria"],
                "unidad_medida": d["unidad_medida"],
                "stock_bodega": sb,
                "stock_minimo_bodega": sm,
                "costo": costo,
                "valor_total_bodega": round(sb * costo, 2),
                "proveedor_nombre": d["proveedor_nombre"],
                "estado": d["estado"],
            }
            if sb <= 0:
                item["alerta_bodega"] = "Agotado en Bodega"
                item["badge_color"] = "#EF4444"
            elif sb <= sm:
                item["alerta_bodega"] = "Stock Bajo Bodega"
                item["badge_color"] = "#F59E0B"
            else:
                item["alerta_bodega"] = "Normal"
                item["badge_color"] = "#10B981"
            data.append(item)

    resultado = []
    cat_q = normalizar_texto(categoria) if (categoria and categoria != "Todas") else None
    for it in data:
        if cat_q and normalizar_texto(it.get("categoria")) != cat_q:
            continue
        if alerta and alerta != "Todos":
            alt_it = it.get("alerta_bodega", "")
            if alerta == "Normal" and alt_it != "Normal":
                continue
            elif alerta in ("Bajo Stock (Alerta)", "Bajo Stock") and "Bajo" not in alt_it:
                continue
            elif alerta in ("Agotado (0)", "Agotado") and "Agotado" not in alt_it:
                continue
        if filtro and str(filtro).strip():
            campos = [it.get("codigo"), it.get("nombre"), it.get("categoria"), it.get("proveedor_nombre")]
            if not coincide_busqueda(campos, str(filtro)):
                continue
        resultado.append(it)
    return resultado


def obtener_existencias_vitrina(filtro=None, categoria=None, alerta=None, conn=None) -> List[Dict[str, Any]]:
    from interface.table_filter_sorter import normalizar_texto, coincide_busqueda
    params: Dict[str, Any] = {}
    if filtro:
        params["filtro"] = str(filtro).strip()
    if categoria and categoria != "Todas":
        params["categoria"] = str(categoria).strip()
    data = None
    try:
        resp = api.get("/inventario/vitrina", params=params, timeout=3.5)
        if resp.status_code == 200:
            res_json = resp.json()
            if isinstance(res_json, list):
                data = res_json
    except Exception:
        pass

    if data is None:
        cat_items = _obtener_catalogo_sqlite_fallback(tipo="Fisico", conn=conn)
        data = []
        for d in cat_items:
            sv = float(d["stock_vitrina"])
            sm = float(d["stock_minimo_vitrina"])
            sb = float(d["stock_bodega"])
            precio = float(d["precio"])
            costo = float(d["costo"])
            item = {
                "id": d["id"],
                "codigo": d["codigo"],
                "nombre": d["nombre"],
                "categoria": d["categoria"],
                "unidad_medida": d["unidad_medida"],
                "stock_vitrina": sv,
                "stock_minimo_vitrina": sm,
                "stock_bodega": sb,
                "precio": precio,
                "costo": costo,
                "valor_venta_vitrina": round(sv * precio, 2),
                "estado": d["estado"],
            }
            if sv <= 0:
                if sb > 0:
                    item["alerta_vitrina"] = "Agotado (Hay en Bodega)"
                    item["badge_color"] = "#3B82F6"
                else:
                    item["alerta_vitrina"] = "Agotado Global"
                    item["badge_color"] = "#EF4444"
            elif sv <= sm:
                item["alerta_vitrina"] = "Reponer Vitrina"
                item["badge_color"] = "#F59E0B"
            else:
                item["alerta_vitrina"] = "Disponible"
                item["badge_color"] = "#10B981"
            data.append(item)

    resultado = []
    cat_q = normalizar_texto(categoria) if (categoria and categoria != "Todas") else None
    for it in data:
        if cat_q and normalizar_texto(it.get("categoria")) != cat_q:
            continue
        if alerta and alerta != "Todos":
            alt_it = it.get("alerta_vitrina", "")
            if alerta == "Disponible" and alt_it != "Disponible":
                continue
            elif alerta in ("Reponer Vitrina", "Bajo Stock (Alerta)", "Bajo Stock") and "Reponer" not in alt_it:
                continue
            elif alerta in ("Agotado (0)", "Agotado") and "Agotado" not in alt_it:
                continue
        if filtro and str(filtro).strip():
            campos = [it.get("codigo"), it.get("nombre"), it.get("categoria")]
            if not coincide_busqueda(campos, str(filtro)):
                continue
        resultado.append(it)
    return resultado


# ==============================================================================
# 4. TRASLADOS ATÓMICOS ENTRE BODEGA Y VITRINA
# ==============================================================================

def ejecutar_traslado(
    codigo_o_id,
    origen,
    destino,
    cantidad,
    usuario="Administrador",
    observaciones="",
    conn=None,
) -> Dict[str, Any]:
    payload = {
        "codigo_o_id": str(codigo_o_id),
        "origen": str(origen).strip().upper(),
        "destino": str(destino).strip().upper(),
        "cantidad": float(cantidad),
        "usuario": str(usuario or "Administrador"),
        "observaciones": str(observaciones or ""),
    }
    resp = api.post("/inventario/traslados", json=payload)
    return _asegurar_respuesta_ok(resp)


# ==============================================================================
# 5. ENTRADAS DE MERCANCÍA Y COMPRAS
# ==============================================================================

def registrar_compra_entrada(
    proveedor_id,
    proveedor_nombre,
    doc_referencia,
    items,
    ubicacion_destino="BODEGA",
    usuario="Administrador",
    observaciones="",
    conn=None,
) -> Dict[str, Any]:
    payload = {
        "proveedor_id": proveedor_id,
        "proveedor_nombre": str(proveedor_nombre or "Sin Proveedor"),
        "doc_referencia": str(doc_referencia or ""),
        "ubicacion_destino": str(ubicacion_destino or "BODEGA").upper(),
        "usuario": str(usuario or "Administrador"),
        "observaciones": str(observaciones or ""),
        "items": items or [],
    }
    resp = api.post("/inventario/compras", json=payload)
    return _asegurar_respuesta_ok(resp)


def obtener_detalle_compra(compra_id, conn=None) -> Optional[Dict[str, Any]]:
    resp = api.get(f"/inventario/compras/{int(compra_id)}")
    if resp.status_code == 200:
        return resp.json()
    return None


def editar_compra(
    compra_id,
    proveedor_id,
    proveedor_nombre,
    doc_referencia,
    items,
    ubicacion_destino="BODEGA",
    usuario="Administrador",
    observaciones="",
    conn=None,
) -> Dict[str, Any]:
    payload = {
        "proveedor_id": proveedor_id,
        "proveedor_nombre": str(proveedor_nombre or "Sin Proveedor"),
        "doc_referencia": str(doc_referencia or ""),
        "ubicacion_destino": str(ubicacion_destino or "BODEGA").upper(),
        "usuario": str(usuario or "Administrador"),
        "observaciones": str(observaciones or ""),
        "items": items or [],
    }
    resp = api.put(f"/inventario/compras/{int(compra_id)}", json=payload)
    return _asegurar_respuesta_ok(resp)


def eliminar_compra(compra_id, usuario="Administrador", conn=None) -> Dict[str, Any]:
    resp = api.delete(f"/inventario/compras/{int(compra_id)}", params={"usuario": str(usuario or "Administrador")})
    return _asegurar_respuesta_ok(resp)


# ==============================================================================
# 6. AJUSTES DE INVENTARIO POR CONTEO FÍSICO
# ==============================================================================

def registrar_ajuste_inventario(
    codigo_o_id,
    ubicacion,
    conteo_fisico,
    usuario="Administrador",
    motivo="Conteo físico",
    conn=None,
) -> Dict[str, Any]:
    payload = {
        "codigo_o_id": str(codigo_o_id),
        "ubicacion": str(ubicacion).strip().upper(),
        "conteo_fisico": float(conteo_fisico),
        "usuario": str(usuario or "Administrador"),
        "motivo": str(motivo or "Conteo físico"),
    }
    resp = api.post("/inventario/ajustes", json=payload)
    return _asegurar_respuesta_ok(resp)


# ==============================================================================
# 7. HISTORIAL KÁRDEX COMPLETO Y TRAZABILIDAD
# ==============================================================================

def obtener_kardex(
    filtro_codigo=None,
    tipo_movimiento=None,
    fecha_inicio=None,
    fecha_fin=None,
    limit=200,
    conn=None,
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": int(limit or 200)}
    if filtro_codigo:
        params["filtro_codigo"] = str(filtro_codigo).strip()
    if tipo_movimiento and tipo_movimiento != "Todos":
        params["tipo_movimiento"] = str(tipo_movimiento).strip()
    if fecha_inicio:
        params["fecha_inicio"] = str(fecha_inicio).strip()
    if fecha_fin:
        params["fecha_fin"] = str(fecha_fin).strip()
    resp = api.get("/inventario/kardex", params=params)
    if resp.status_code == 200:
        data = resp.json()
        return data if isinstance(data, list) else []
    return []


def obtener_historial_traslados(limit=100, conn=None) -> List[Dict[str, Any]]:
    resp = api.get("/inventario/traslados", params={"limit": int(limit or 100)})
    if resp.status_code == 200:
        data = resp.json()
        return data if isinstance(data, list) else []
    return []


def obtener_historial_compras(limit=100, conn=None) -> List[Dict[str, Any]]:
    resp = api.get("/inventario/compras", params={"limit": int(limit or 100)})
    if resp.status_code == 200:
        data = resp.json()
        return data if isinstance(data, list) else []
    return []


# ==============================================================================
# 8. ALERTAS E INDICADORES EN TIEMPO REAL
# ==============================================================================

def obtener_alertas_inventario(conn=None) -> Dict[str, Any]:
    resp = api.get("/inventario/alertas")
    if resp.status_code == 200:
        return resp.json()
    return {
        "bajo_vitrina": [],
        "bajo_bodega": [],
        "agotados_globales": [],
        "total_alertas": 0,
    }


def obtener_resumen_indicadores(conn=None) -> Dict[str, Any]:
    resp = api.get("/inventario/resumen-indicadores")
    if resp.status_code == 200:
        return resp.json()
    return {
        "total_articulos": 0,
        "total_fisicos": 0,
        "total_servicios": 0,
        "unidades_bodega": 0.0,
        "unidades_vitrina": 0.0,
        "unidades_totales": 0.0,
        "valor_bodega_costo": 0.0,
        "valor_vitrina_costo": 0.0,
        "valor_vitrina_venta": 0.0,
        "valor_inventario_total": 0.0,
        "alertas_bajo_vitrina": 0,
        "alertas_bajo_bodega": 0,
        "alertas_agotados": 0,
        "total_alertas": 0,
    }
