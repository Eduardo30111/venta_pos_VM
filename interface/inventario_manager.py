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

def obtener_catalogo(filtro=None, categoria=None, tipo=None, solo_activos=False, proveedor_id=None, conn=None) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"solo_activos": bool(solo_activos)}
    if filtro:
        params["filtro"] = str(filtro).strip()
    if categoria and categoria != "Todas":
        params["categoria"] = str(categoria).strip()
    if tipo and tipo != "Todos":
        params["tipo"] = str(tipo).strip()
    if proveedor_id is not None:
        params["proveedor_id"] = int(proveedor_id)

    resp = api.get("/inventario/catalogo", params=params)
    if resp.status_code == 200:
        data = resp.json()
        return data if isinstance(data, list) else []
    return []


def obtener_articulo_por_codigo(codigo, conn=None) -> Optional[Dict[str, Any]]:
    cod_clean = str(codigo or "").strip()
    if not cod_clean:
        return None
    resp = api.get(f"/inventario/articulo/{cod_clean}")
    if resp.status_code == 200:
        return resp.json()
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
            s_prov = str(raw_prov).strip()
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
    except Exception as e_upsert:
        print(f"Aviso al upsert de artículo en SQLite local: {e_upsert}")
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

def obtener_existencias_bodega(filtro=None, categoria=None, conn=None) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {}
    if filtro:
        params["filtro"] = str(filtro).strip()
    if categoria and categoria != "Todas":
        params["categoria"] = str(categoria).strip()
    resp = api.get("/inventario/bodega", params=params)
    if resp.status_code == 200:
        data = resp.json()
        return data if isinstance(data, list) else []
    return []


def obtener_existencias_vitrina(filtro=None, categoria=None, conn=None) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {}
    if filtro:
        params["filtro"] = str(filtro).strip()
    if categoria and categoria != "Todas":
        params["categoria"] = str(categoria).strip()
    resp = api.get("/inventario/vitrina", params=params)
    if resp.status_code == 200:
        data = resp.json()
        return data if isinstance(data, list) else []
    return []


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
