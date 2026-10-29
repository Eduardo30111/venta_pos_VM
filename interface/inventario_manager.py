#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivo: inventario_manager.py
Gestor integral de lógica de negocio para Inventario en VmPOS.
Administra: Catálogo unificado, Bodega, Vitrina, Traslados atómicos,
Compras con conversión de unidades, Ajustes físicos, Kárdex y Alertas.
"""

import sqlite3
from datetime import datetime
import os
import sys

try:
    from interface.database_manager import conectar_db, inicializar_base_datos
except ImportError:
    try:
        from database_manager import conectar_db, inicializar_base_datos
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from database_manager import conectar_db, inicializar_base_datos

# ==============================================================================
# 1. UNIDADES DE MEDIDA Y MATRIZ DE CONVERSIÓN
# ==============================================================================

UNIDADES_DISCRETAS = {"Unidad", "Caja", "Paquete", "Docena", "Servicio"}
UNIDADES_FRACCIONABLES = {"Kilogramo", "Gramo", "Litro", "Mililitro", "Metro", "Hora", "Minuto"}
TODAS_LAS_UNIDADES = [
    "Unidad", "Caja", "Paquete", "Docena",
    "Kilogramo", "Gramo", "Litro", "Mililitro", "Metro",
    "Hora", "Minuto", "Servicio"
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
    "Servicio": "SERVICIO"
}

def validar_compatibilidad_unidades(unidad_origen, unidad_destino):
    """
    Verifica que dos unidades de medida pertenezcan a la misma categoría dimensional.
    No permite convertir, por ejemplo, Horas a Kilogramos.
    """
    cat_orig = CATEGORIAS_UNIDAD.get(unidad_origen, "OTRO")
    cat_dest = CATEGORIAS_UNIDAD.get(unidad_destino, "OTRO")
    if cat_orig == "SERVICIO" or cat_dest == "SERVICIO":
        return cat_orig == cat_dest
    return cat_orig == cat_dest

def es_cantidad_valida(unidad, cantidad):
    """
    Verifica que las unidades discretas no tengan decimales fraccionarios.
    """
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

# ==============================================================================
# 2. CATÁLOGO UNIFICADO DE ARTÍCULOS (PRODUCTOS FÍSICOS Y SERVICIOS)
# ==============================================================================

def obtener_catalogo(filtro=None, categoria=None, tipo=None, solo_activos=False, conn=None):
    """
    Consulta el catálogo completo unificado de artículos.
    """
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        query = """
            SELECT p.id, p.codigo, p.nombre, p.tipo_producto, p.categoria, p.marca,
                   p.codigo_barras, p.unidad_medida, p.precio, p.costo, p.stock,
                   COALESCE(p.stock_bodega, 0.0) as stock_bodega,
                   COALESCE(p.stock_vitrina, 0.0) as stock_vitrina,
                   COALESCE(p.stock_minimo_bodega, 5.0) as stock_minimo_bodega,
                   COALESCE(p.stock_minimo_vitrina, 3.0) as stock_minimo_vitrina,
                   p.proveedor_id, prov.nombre as proveedor_nombre,
                   COALESCE(p.precio_variable, 0) as precio_variable,
                   COALESCE(p.porcentaje_comision, 0.0) as porcentaje_comision,
                   p.descripcion, COALESCE(p.estado, 'Activo') as estado,
                   p.fecha_creacion, p.fecha_modificacion
            FROM productos p
            LEFT JOIN proveedores prov ON p.proveedor_id = prov.id
            WHERE 1=1
        """
        params = []

        if solo_activos:
            query += " AND COALESCE(p.estado, 'Activo') = 'Activo'"
        if tipo and tipo != "Todos":
            query += " AND p.tipo_producto = ?"
            params.append(tipo)
        if categoria and categoria != "Todas":
            query += " AND p.categoria = ?"
            params.append(categoria)
        if filtro:
            termino = f"%{str(filtro).strip().lower()}%"
            query += " AND (LOWER(p.codigo) LIKE ? OR LOWER(p.nombre) LIKE ? OR LOWER(COALESCE(p.codigo_barras, '')) LIKE ?)"
            params.extend([termino, termino, termino])

        query += " ORDER BY p.nombre ASC"
        cur.execute(query, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        if cerrar_conn and conn:
            conn.close()

def obtener_articulo_por_codigo(codigo, conn=None):
    """Obtiene un producto o servicio por su código único."""
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT p.*, prov.nombre as proveedor_nombre
            FROM productos p
            LEFT JOIN proveedores prov ON p.proveedor_id = prov.id
            WHERE p.codigo = ? OR p.codigo = ?
        """, (str(codigo).strip(), str(codigo).strip().zfill(5)))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if cerrar_conn and conn:
            conn.close()

def sugerir_proximo_codigo(tipo="Fisico", conn=None):
    """Genera una sugerencia de código correlativo único."""
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True
    try:
        cur = conn.cursor()
        cur.execute("SELECT codigo FROM productos")
        codigos = [r[0] for r in cur.fetchall() if r[0]]
        max_num = 0
        prefix = "S" if tipo == "Servicio" else ""
        for c in codigos:
            c_str = str(c).strip()
            if prefix and c_str.startswith(prefix):
                num_part = c_str[len(prefix):]
                if num_part.isdigit():
                    max_num = max(max_num, int(num_part))
            elif not prefix and c_str.isdigit():
                max_num = max(max_num, int(c_str))
        if prefix:
            return f"{prefix}{max_num + 1:05d}"
        else:
            return f"{max_num + 1:05d}"
    finally:
        if cerrar_conn and conn:
            conn.close()

def crear_articulo(datos, usuario="Administrador", conn=None):
    """
    Crea un nuevo artículo (producto físico o servicio) en el catálogo.
    Garantiza unicidad de código y registra movimiento inicial si hay existencias.
    """
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    try:
        codigo = str(datos.get("codigo", "")).strip()
        nombre = str(datos.get("nombre", "")).strip()
        tipo = str(datos.get("tipo_producto", "Fisico")).strip()
        precio = float(datos.get("precio", 0.0))
        costo = float(datos.get("costo", 0.0))
        categoria = str(datos.get("categoria", "General")).strip() or "General"
        marca = str(datos.get("marca", "")).strip()
        codigo_barras = str(datos.get("codigo_barras", "")).strip()
        unidad_medida = str(datos.get("unidad_medida", "Unidad")).strip() or "Unidad"
        descripcion = str(datos.get("descripcion", "")).strip()
        proveedor_id = datos.get("proveedor_id")
        estado = str(datos.get("estado", "Activo")).strip()
        precio_variable = 1 if datos.get("precio_variable") else 0
        try:
            porcentaje_comision = max(0.0, min(100.0, float(datos.get("porcentaje_comision", 0.0) or 0.0)))
        except (ValueError, TypeError):
            porcentaje_comision = 0.0

        if not codigo:
            raise ValueError("El código SKU es obligatorio.")
        if not nombre:
            raise ValueError("El nombre del artículo es obligatorio.")
        if tipo != "Servicio" and precio < 0:
            raise ValueError("El precio de venta no puede ser negativo.")

        cur = conn.cursor()
        # Validar duplicados de código
        cur.execute("SELECT id FROM productos WHERE codigo = ?", (codigo,))
        if cur.fetchone():
            raise ValueError(f"Ya existe un artículo con el código '{codigo}'. Los códigos deben ser únicos.")

        # Manejo de existencias iniciales por ubicación
        if tipo == "Servicio":
            stock_bodega = 0.0
            stock_vitrina = 0.0
            stock_min_bodega = 0.0
            stock_min_vitrina = 0.0
        else:
            stock_bodega = float(datos.get("stock_bodega", 0.0))
            stock_vitrina = float(datos.get("stock_vitrina", 0.0))
            stock_min_bodega = float(datos.get("stock_minimo_bodega", 5.0))
            stock_min_vitrina = float(datos.get("stock_minimo_vitrina", 3.0))

        stock_total = stock_bodega + stock_vitrina
        ahora = datetime.now()
        fecha_str = ahora.strftime("%Y-%m-%d")
        hora_str = ahora.strftime("%H:%M:%S")

        cur.execute("""
            INSERT INTO productos (
                codigo, nombre, precio, costo, stock, tipo_producto,
                proveedor_id, descripcion, stock_bodega, stock_vitrina,
                stock_minimo_bodega, stock_minimo_vitrina, categoria,
                marca, codigo_barras, unidad_medida, estado,
                precio_variable, porcentaje_comision,
                fecha_creacion, fecha_modificacion
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            codigo, nombre, precio, costo, stock_total, tipo,
            proveedor_id, descripcion, stock_bodega, stock_vitrina,
            stock_min_bodega, stock_min_vitrina, categoria,
            marca, codigo_barras, unidad_medida, estado,
            precio_variable, porcentaje_comision,
            f"{fecha_str} {hora_str}", f"{fecha_str} {hora_str}"
        ))
        producto_id = cur.lastrowid

        # Si ingresa con stock inicial físico, registrar en Kárdex
        if tipo == "Fisico" and stock_total > 0:
            if stock_bodega > 0:
                cur.execute("""
                    INSERT INTO movimientos_inventario (
                        fecha, hora, producto_id, codigo_producto, nombre_producto,
                        tipo_movimiento, cantidad, unidad_medida, ubicacion_origen,
                        ubicacion_destino, stock_origen_ant, stock_origen_des,
                        stock_destino_ant, stock_destino_des, costo_unitario, valor_total,
                        referencia, usuario, observaciones, estado
                    ) VALUES (?, ?, ?, ?, ?, 'ENTRADA_INICIAL', ?, ?, 'PROVEEDOR', 'BODEGA', 0, 0, 0, ?, ?, ?, 'ALTA-CATALOGO', ?, 'Stock inicial de apertura en Bodega', 'Completado')
                """, (fecha_str, hora_str, producto_id, codigo, nombre, stock_bodega, unidad_medida, stock_bodega, costo, stock_bodega * costo, usuario))

            if stock_vitrina > 0:
                cur.execute("""
                    INSERT INTO movimientos_inventario (
                        fecha, hora, producto_id, codigo_producto, nombre_producto,
                        tipo_movimiento, cantidad, unidad_medida, ubicacion_origen,
                        ubicacion_destino, stock_origen_ant, stock_origen_des,
                        stock_destino_ant, stock_destino_des, costo_unitario, valor_total,
                        referencia, usuario, observaciones, estado
                    ) VALUES (?, ?, ?, ?, ?, 'ENTRADA_INICIAL', ?, ?, 'PROVEEDOR', 'VITRINA', 0, 0, 0, ?, ?, ?, 'ALTA-CATALOGO', ?, 'Stock inicial de apertura en Vitrina', 'Completado')
                """, (fecha_str, hora_str, producto_id, codigo, nombre, stock_vitrina, unidad_medida, stock_vitrina, costo, stock_vitrina * costo, usuario))

        conn.commit()
        return {"id": producto_id, "codigo": codigo, "nombre": nombre}
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if cerrar_conn and conn:
            conn.close()

def actualizar_articulo(id_o_codigo, datos, conn=None):
    """Actualiza los datos y metadatos de un artículo existente."""
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    try:
        cur = conn.cursor()
        nombre = str(datos.get("nombre", "")).strip()
        precio = float(datos.get("precio", 0.0))
        costo = float(datos.get("costo", 0.0))
        categoria = str(datos.get("categoria", "General")).strip()
        marca = str(datos.get("marca", "")).strip()
        codigo_barras = str(datos.get("codigo_barras", "")).strip()
        unidad_medida = str(datos.get("unidad_medida", "Unidad")).strip()
        descripcion = str(datos.get("descripcion", "")).strip()
        proveedor_id = datos.get("proveedor_id")
        estado = str(datos.get("estado", "Activo")).strip()
        stock_min_bodega = float(datos.get("stock_minimo_bodega", 5.0))
        stock_min_vitrina = float(datos.get("stock_minimo_vitrina", 3.0))
        precio_variable = 1 if datos.get("precio_variable") else 0
        try:
            porcentaje_comision = max(0.0, min(100.0, float(datos.get("porcentaje_comision", 0.0) or 0.0)))
        except (ValueError, TypeError):
            porcentaje_comision = 0.0

        ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cur.execute("""
            UPDATE productos
            SET nombre = ?, precio = ?, costo = ?, categoria = ?, marca = ?,
                codigo_barras = ?, unidad_medida = ?, descripcion = ?,
                proveedor_id = ?, estado = ?, stock_minimo_bodega = ?,
                stock_minimo_vitrina = ?, precio_variable = ?, porcentaje_comision = ?,
                fecha_modificacion = ?
            WHERE id = ? OR codigo = ?
        """, (
            nombre, precio, costo, categoria, marca, codigo_barras,
            unidad_medida, descripcion, proveedor_id, estado,
            stock_min_bodega, stock_min_vitrina, precio_variable, porcentaje_comision, ahora,
            id_o_codigo, str(id_o_codigo)
        ))
        conn.commit()
        return True
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if cerrar_conn and conn:
            conn.close()

def cambiar_estado_articulo(id_o_codigo, nuevo_estado, conn=None):
    """Activa o inactiva un producto o servicio."""
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True
    try:
        cur = conn.cursor()
        ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("""
            UPDATE productos 
            SET estado = ?, fecha_modificacion = ?
            WHERE id = ? OR codigo = ?
        """, (nuevo_estado, ahora, id_o_codigo, str(id_o_codigo)))
        conn.commit()
        return True
    finally:
        if cerrar_conn and conn:
            conn.close()

# ==============================================================================
# 3. GESTIÓN DE BODEGA Y VITRINA
# ==============================================================================

def obtener_existencias_bodega(filtro=None, categoria=None, conn=None):
    """Retorna listado de mercancía almacenada en Bodega con valorización."""
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        query = """
            SELECT p.id, p.codigo, p.nombre, p.categoria, p.unidad_medida,
                   COALESCE(p.stock_bodega, 0.0) as stock_bodega,
                   COALESCE(p.stock_minimo_bodega, 5.0) as stock_minimo_bodega,
                   COALESCE(p.costo, 0.0) as costo,
                   (COALESCE(p.stock_bodega, 0.0) * COALESCE(p.costo, 0.0)) as valor_total_bodega,
                   prov.nombre as proveedor_nombre,
                   COALESCE(p.estado, 'Activo') as estado
            FROM productos p
            LEFT JOIN proveedores prov ON p.proveedor_id = prov.id
            WHERE p.tipo_producto = 'Fisico'
        """
        params = []
        if categoria and categoria != "Todas":
            query += " AND p.categoria = ?"
            params.append(categoria)
        if filtro:
            termino = f"%{str(filtro).strip().lower()}%"
            query += " AND (LOWER(p.codigo) LIKE ? OR LOWER(p.nombre) LIKE ?)"
            params.extend([termino, termino])

        query += " ORDER BY p.nombre ASC"
        cur.execute(query, params)
        rows = cur.fetchall()

        resultados = []
        for r in rows:
            d = dict(r)
            sb = d["stock_bodega"]
            sm = d["stock_minimo_bodega"]
            if sb <= 0:
                d["alerta_bodega"] = "Agotado en Bodega"
                d["badge_color"] = "#EF4444"
            elif sb <= sm:
                d["alerta_bodega"] = "Stock Bajo Bodega"
                d["badge_color"] = "#F59E0B"
            else:
                d["alerta_bodega"] = "Normal"
                d["badge_color"] = "#10B981"
            resultados.append(d)
        return resultados
    finally:
        if cerrar_conn and conn:
            conn.close()

def obtener_existencias_vitrina(filtro=None, categoria=None, conn=None):
    """Retorna listado de mercancía disponible físicamente para la venta en Vitrina."""
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        query = """
            SELECT p.id, p.codigo, p.nombre, p.categoria, p.unidad_medida,
                   COALESCE(p.stock_vitrina, 0.0) as stock_vitrina,
                   COALESCE(p.stock_minimo_vitrina, 3.0) as stock_minimo_vitrina,
                   COALESCE(p.stock_bodega, 0.0) as stock_bodega,
                   p.precio, COALESCE(p.costo, 0.0) as costo,
                   (COALESCE(p.stock_vitrina, 0.0) * p.precio) as valor_venta_vitrina,
                   COALESCE(p.estado, 'Activo') as estado
            FROM productos p
            WHERE p.tipo_producto = 'Fisico'
        """
        params = []
        if categoria and categoria != "Todas":
            query += " AND p.categoria = ?"
            params.append(categoria)
        if filtro:
            termino = f"%{str(filtro).strip().lower()}%"
            query += " AND (LOWER(p.codigo) LIKE ? OR LOWER(p.nombre) LIKE ?)"
            params.extend([termino, termino])

        query += " ORDER BY p.nombre ASC"
        cur.execute(query, params)
        rows = cur.fetchall()

        resultados = []
        for r in rows:
            d = dict(r)
            sv = d["stock_vitrina"]
            sm = d["stock_minimo_vitrina"]
            sb = d["stock_bodega"]
            if sv <= 0:
                if sb > 0:
                    d["alerta_vitrina"] = "Agotado (Hay en Bodega)"
                    d["badge_color"] = "#3B82F6"
                else:
                    d["alerta_vitrina"] = "Agotado Global"
                    d["badge_color"] = "#EF4444"
            elif sv <= sm:
                d["alerta_vitrina"] = "Reponer Vitrina"
                d["badge_color"] = "#F59E0B"
            else:
                d["alerta_vitrina"] = "Disponible"
                d["badge_color"] = "#10B981"
            resultados.append(d)
        return resultados
    finally:
        if cerrar_conn and conn:
            conn.close()

# ==============================================================================
# 4. TRASLADOS ENTRE BODEGA Y VITRINA (PROCESO ATÓMICO)
# ==============================================================================

def ejecutar_traslado(codigo_o_id, origen, destino, cantidad, usuario="Administrador", observaciones="", conn=None):
    """
    Ejecuta un traslado de mercancía entre Bodega y Vitrina.
    Reglas estrictas:
    - Cantidad > 0.
    - Origen != Destino.
    - Origen y Destino válidos ('BODEGA', 'VITRINA').
    - Stock suficiente en la ubicación de origen.
    - Movimiento 100% atómico con rollback si hay error.
    - NO genera venta, compra, gasto ni utilidad. El costo total del inventario permanece inalterado.
    - Registra en traslados_inventario y movimientos_inventario.
    """
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    try:
        origen = str(origen).strip().upper()
        destino = str(destino).strip().upper()

        if origen not in ("BODEGA", "VITRINA"):
            raise ValueError(f"Ubicación de origen inválida: '{origen}'. Debe ser BODEGA o VITRINA.")
        if destino not in ("BODEGA", "VITRINA"):
            raise ValueError(f"Ubicación de destino inválida: '{destino}'. Debe ser BODEGA o VITRINA.")
        if origen == destino:
            raise ValueError("La ubicación de origen y destino deben ser diferentes.")

        try:
            cant_float = float(cantidad)
        except (ValueError, TypeError):
            raise ValueError("La cantidad a trasladar debe ser un número válido.")

        if cant_float <= 0:
            raise ValueError("La cantidad a trasladar debe ser mayor que cero.")

        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Obtener datos del producto con bloqueo o verificación
        cur.execute("""
            SELECT id, codigo, nombre, tipo_producto, unidad_medida, costo,
                   COALESCE(stock_bodega, 0.0) as stock_bodega,
                   COALESCE(stock_vitrina, 0.0) as stock_vitrina,
                   COALESCE(stock, 0.0) as stock
            FROM productos
            WHERE id = ? OR codigo = ?
        """, (codigo_o_id, str(codigo_o_id)))
        prod = cur.fetchone()

        if not prod:
            raise ValueError(f"No se encontró el artículo con identificador '{codigo_o_id}'.")

        if prod["tipo_producto"] == "Servicio":
            raise ValueError("Los servicios no tienen existencias físicas y no pueden ser trasladados.")

        unidad = prod["unidad_medida"] or "Unidad"
        valido, msg = es_cantidad_valida(unidad, cant_float)
        if not valido:
            raise ValueError(msg)

        sb_ant = float(prod["stock_bodega"])
        sv_ant = float(prod["stock_vitrina"])
        costo_u = float(prod["costo"] or 0.0)
        prod_id = prod["id"]
        cod_prod = prod["codigo"]
        nom_prod = prod["nombre"]

        # Validar existencias suficientes en el origen
        if origen == "BODEGA":
            if sb_ant < cant_float:
                raise ValueError(
                    f"Existencias insuficientes en Bodega para '{nom_prod}'.\n"
                    f"Disponible en Bodega: {sb_ant:g} {unidad}\n"
                    f"Solicitado: {cant_float:g} {unidad}"
                )
            sb_des = sb_ant - cant_float
            sv_des = sv_ant + cant_float
            stock_origen_ant = sb_ant
            stock_origen_des = sb_des
            stock_destino_ant = sv_ant
            stock_destino_des = sv_des
            tipo_mov = "TRASLADO_BODEGA_A_VITRINA"
        else: # Origen es VITRINA
            if sv_ant < cant_float:
                raise ValueError(
                    f"Existencias insuficientes en Vitrina para '{nom_prod}'.\n"
                    f"Disponible en Vitrina: {sv_ant:g} {unidad}\n"
                    f"Solicitado: {cant_float:g} {unidad}"
                )
            sv_des = sv_ant - cant_float
            sb_des = sb_ant + cant_float
            stock_origen_ant = sv_ant
            stock_origen_des = sv_des
            stock_destino_ant = sb_ant
            stock_destino_des = sb_des
            tipo_mov = "TRASLADO_VITRINA_A_BODEGA"

        # Generar número correlativo de traslado único
        cur.execute("SELECT COUNT(*) FROM traslados_inventario")
        total_traslados = cur.fetchone()[0]
        num_traslado = f"TR-{total_traslados + 1:05d}"

        ahora = datetime.now()
        fecha_str = ahora.strftime("%Y-%m-%d")
        hora_str = ahora.strftime("%H:%M:%S")

        # 1. Actualizar existencias en la tabla productos
        stock_total_nuevo = sb_des + sv_des
        cur.execute("""
            UPDATE productos
            SET stock_bodega = ?, stock_vitrina = ?, stock = ?, fecha_modificacion = ?
            WHERE id = ?
        """, (sb_des, sv_des, stock_total_nuevo, f"{fecha_str} {hora_str}", prod_id))

        # 2. Registrar en traslados_inventario
        cur.execute("""
            INSERT INTO traslados_inventario (
                numero_traslado, fecha, hora, producto_id, codigo_producto,
                nombre_producto, ubicacion_origen, ubicacion_destino,
                cantidad, usuario, estado, observaciones
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Completado', ?)
        """, (
            num_traslado, fecha_str, hora_str, prod_id, cod_prod,
            nom_prod, origen, destino, cant_float, usuario, observaciones
        ))

        # 3. Registrar en movimientos_inventario (Kárdex)
        cur.execute("""
            INSERT INTO movimientos_inventario (
                fecha, hora, producto_id, codigo_producto, nombre_producto,
                tipo_movimiento, cantidad, unidad_medida, ubicacion_origen,
                ubicacion_destino, stock_origen_ant, stock_origen_des,
                stock_destino_ant, stock_destino_des, costo_unitario, valor_total,
                referencia, usuario, observaciones, estado
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Completado')
        """, (
            fecha_str, hora_str, prod_id, cod_prod, nom_prod,
            tipo_mov, cant_float, unidad, origen, destino,
            stock_origen_ant, stock_origen_des, stock_destino_ant, stock_destino_des,
            costo_u, cant_float * costo_u, num_traslado, usuario,
            observaciones or f"Traslado de {cant_float:g} {unidad} de {origen} a {destino}"
        ))

        conn.commit()
        return {
            "numero_traslado": num_traslado,
            "producto": nom_prod,
            "codigo": cod_prod,
            "origen": origen,
            "destino": destino,
            "cantidad": cant_float,
            "stock_bodega": sb_des,
            "stock_vitrina": sv_des,
            "stock_total": stock_total_nuevo
        }
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if cerrar_conn and conn:
            conn.close()

# ==============================================================================
# 5. COMPRAS Y ENTRADAS DE MERCANCÍA (CONVERSIÓN DE PRESENTACIONES)
# ==============================================================================

def registrar_compra_entrada(proveedor_id, proveedor_nombre, doc_referencia, items,
                             ubicacion_destino="BODEGA", usuario="Administrador", observaciones="", conn=None):
    """
    Registra una recepción o compra formal de mercancía.
    Permite comprar en presentaciones (ej. Cajas de 100 libretas a $200.000)
    e ingresar las unidades base convertidas (200 libretas a costo $2.000 c/u).
    Contabilidad: NO se contabiliza como gasto operativo; es un incremento de activo.
    """
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    try:
        if not items:
            raise ValueError("Debe incluir al menos un artículo en la entrada de mercancía.")

        ubicacion_destino = str(ubicacion_destino).strip().upper()
        if ubicacion_destino not in ("BODEGA", "VITRINA"):
            ubicacion_destino = "BODEGA"

        cur = conn.cursor()

        # Generar número correlativo de compra
        cur.execute("SELECT COUNT(*) FROM compras_inventario")
        total_compras = cur.fetchone()[0]
        num_compra = f"CMP-{total_compras + 1:05d}"

        ahora = datetime.now()
        fecha_str = ahora.strftime("%Y-%m-%d")
        hora_str = ahora.strftime("%H:%M:%S")

        total_compra = sum(float(it.get("subtotal", 0.0)) for it in items)

        # 1. Cabecera de compra
        cur.execute("""
            INSERT INTO compras_inventario (
                numero_compra, fecha, hora, proveedor_id, proveedor_nombre,
                documento_referencia, ubicacion_destino, total_compra,
                usuario, observaciones, estado
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Recibida')
        """, (
            num_compra, fecha_str, hora_str, proveedor_id, proveedor_nombre,
            doc_referencia, ubicacion_destino, total_compra, usuario, observaciones
        ))
        compra_id = cur.lastrowid

        # 2. Detalle y afectación de inventario
        for item in items:
            codigo = str(item.get("codigo", "")).strip()
            # Buscar producto
            cur.execute("""
                SELECT id, codigo, nombre, tipo_producto, unidad_medida, costo,
                       COALESCE(stock_bodega, 0.0) as stock_bodega,
                       COALESCE(stock_vitrina, 0.0) as stock_vitrina,
                       COALESCE(stock, 0.0) as stock
                FROM productos WHERE codigo = ? OR id = ?
            """, (codigo, item.get("producto_id")))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Artículo con código '{codigo}' no encontrado en el catálogo.")

            prod_id = row[0]
            prod_cod = row[1]
            prod_nom = row[2]
            tipo_p = row[3]
            unidad_base = row[4] or "Unidad"
            costo_ant = float(row[5] or 0.0)
            sb_ant = float(row[6])
            sv_ant = float(row[7])

            if tipo_p == "Servicio":
                raise ValueError(f"El ítem '{prod_nom}' es un servicio y no puede recibir inventario físico.")

            unidad_compra = str(item.get("unidad_compra", unidad_base)).strip()
            factor_conv = float(item.get("factor_conversion", 1.0))
            if factor_conv <= 0:
                factor_conv = 1.0

            cant_comprada = float(item.get("cantidad_comprada", 1.0))
            costo_presentacion = float(item.get("costo_unidad_compra", 0.0))

            # Conversión matemática exacta
            unidades_reales = cant_comprada * factor_conv
            costo_unitario_convertido = costo_presentacion / factor_conv if factor_conv > 0 else costo_presentacion
            subtotal_item = cant_comprada * costo_presentacion

            # 2.a Guardar en detalle_compras
            cur.execute("""
                INSERT INTO detalle_compras (
                    compra_id, producto_id, codigo_producto, nombre_producto,
                    unidad_compra, factor_conversion, cantidad_comprada,
                    cantidad_unidades, costo_unidad_compra, costo_unitario_convertido,
                    subtotal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                compra_id, prod_id, prod_cod, prod_nom, unidad_compra,
                factor_conv, cant_comprada, unidades_reales,
                costo_presentacion, costo_unitario_convertido, subtotal_item
            ))

            # 2.b Actualizar existencias en la ubicación destino
            if ubicacion_destino == "BODEGA":
                sb_des = sb_ant + unidades_reales
                sv_des = sv_ant
                st_orig_ant = 0.0
                st_orig_des = 0.0
                st_dest_ant = sb_ant
                st_dest_des = sb_des
            else:
                sb_des = sb_ant
                sv_des = sv_ant + unidades_reales
                st_orig_ant = 0.0
                st_orig_des = 0.0
                st_dest_ant = sv_ant
                st_dest_des = sv_des

            nuevo_stock_total = sb_des + sv_des

            # Actualización de costo en catálogo: si ya había existencias, costo promedio ponderado
            # Nuevo costo = ((stock_anterior * costo_anterior) + (unidades_nuevas * costo_nuevo)) / nuevo_stock_total
            if nuevo_stock_total > 0 and costo_unitario_convertido > 0:
                costo_ponderado = (
                    (row[8] * costo_ant) + (unidades_reales * costo_unitario_convertido)
                ) / nuevo_stock_total
            else:
                costo_ponderado = costo_unitario_convertido or costo_ant

            cur.execute("""
                UPDATE productos
                SET stock_bodega = ?, stock_vitrina = ?, stock = ?, costo = ?, fecha_modificacion = ?
                WHERE id = ?
            """, (sb_des, sv_des, nuevo_stock_total, costo_ponderado, f"{fecha_str} {hora_str}", prod_id))

            # 2.c Registrar en movimientos_inventario (Kárdex)
            cur.execute("""
                INSERT INTO movimientos_inventario (
                    fecha, hora, producto_id, codigo_producto, nombre_producto,
                    tipo_movimiento, cantidad, unidad_medida, ubicacion_origen,
                    ubicacion_destino, stock_origen_ant, stock_origen_des,
                    stock_destino_ant, stock_destino_des, costo_unitario, valor_total,
                    referencia, usuario, observaciones, estado
                ) VALUES (?, ?, ?, ?, ?, 'ENTRADA_COMPRA', ?, ?, 'PROVEEDOR', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Completado')
            """, (
                fecha_str, hora_str, prod_id, prod_cod, prod_nom,
                unidades_reales, unidad_base, ubicacion_destino,
                st_orig_ant, st_orig_des, st_dest_ant, st_dest_des,
                costo_unitario_convertido, subtotal_item, num_compra, usuario,
                f"Entrada por compra {num_compra} ({cant_comprada:g} {unidad_compra} x {factor_conv:g} = {unidades_reales:g} {unidad_base})"
            ))

        conn.commit()
        return {"numero_compra": num_compra, "compra_id": compra_id, "total": total_compra}
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if cerrar_conn and conn:
            conn.close()

# ==============================================================================
# 6. AJUSTES DE INVENTARIO Y CONTEOS FÍSICOS
# ==============================================================================

def registrar_ajuste_inventario(codigo_o_id, ubicacion, conteo_fisico, usuario="Administrador", motivo="", conn=None):
    """
    Registra un ajuste por conteo físico o corrección autorizada de inventario.
    Genera el movimiento AJUSTE_POSITIVO o AJUSTE_NEGATIVO correspondiente en Kárdex.
    """
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    try:
        ubicacion = str(ubicacion).strip().upper()
        if ubicacion not in ("BODEGA", "VITRINA"):
            raise ValueError("La ubicación a ajustar debe ser BODEGA o VITRINA.")

        try:
            conteo_flt = float(conteo_fisico)
        except (ValueError, TypeError):
            raise ValueError("El conteo físico debe ser un valor numérico.")

        if conteo_flt < 0:
            raise ValueError("El conteo físico no puede ser negativo.")

        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("""
            SELECT id, codigo, nombre, tipo_producto, unidad_medida, costo,
                   COALESCE(stock_bodega, 0.0) as stock_bodega,
                   COALESCE(stock_vitrina, 0.0) as stock_vitrina
            FROM productos WHERE id = ? OR codigo = ?
        """, (codigo_o_id, str(codigo_o_id)))
        prod = cur.fetchone()

        if not prod:
            raise ValueError(f"No se encontró el artículo con identificador '{codigo_o_id}'.")

        if prod["tipo_producto"] == "Servicio":
            raise ValueError("Los servicios no tienen existencias físicas.")

        prod_id = prod["id"]
        prod_cod = prod["codigo"]
        prod_nom = prod["nombre"]
        costo_u = float(prod["costo"] or 0.0)
        unidad = prod["unidad_medida"] or "Unidad"

        sb_ant = float(prod["stock_bodega"])
        sv_ant = float(prod["stock_vitrina"])

        stock_actual_ub = sb_ant if ubicacion == "BODEGA" else sv_ant
        delta = conteo_flt - stock_actual_ub

        if abs(delta) < 0.0001:
            return {"mensaje": "El conteo físico coincide exactamente con el sistema. No se requirió ajuste."}

        tipo_mov = "AJUSTE_POSITIVO" if delta > 0 else "AJUSTE_NEGATIVO"
        cant_ajuste = abs(delta)

        if ubicacion == "BODEGA":
            sb_des = conteo_flt
            sv_des = sv_ant
        else:
            sb_des = sb_ant
            sv_des = conteo_flt

        stock_total_nuevo = sb_des + sv_des
        ahora = datetime.now()
        fecha_str = ahora.strftime("%Y-%m-%d")
        hora_str = ahora.strftime("%H:%M:%S")

        cur.execute("""
            UPDATE productos
            SET stock_bodega = ?, stock_vitrina = ?, stock = ?, fecha_modificacion = ?
            WHERE id = ?
        """, (sb_des, sv_des, stock_total_nuevo, f"{fecha_str} {hora_str}", prod_id))

        cur.execute("""
            INSERT INTO movimientos_inventario (
                fecha, hora, producto_id, codigo_producto, nombre_producto,
                tipo_movimiento, cantidad, unidad_medida, ubicacion_origen,
                ubicacion_destino, stock_origen_ant, stock_origen_des,
                stock_destino_ant, stock_destino_des, costo_unitario, valor_total,
                referencia, usuario, observaciones, estado
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'AJUSTE-FISICO', ?, ?, 'Completado')
        """, (
            fecha_str, hora_str, prod_id, prod_cod, prod_nom,
            tipo_mov, cant_ajuste, unidad,
            ubicacion if delta < 0 else "NINGUNA",
            ubicacion if delta > 0 else "NINGUNA",
            stock_actual_ub, conteo_flt,
            stock_actual_ub, conteo_flt,
            costo_u, cant_ajuste * costo_u, usuario,
            motivo or f"Ajuste en {ubicacion}: {stock_actual_ub:g} -> {conteo_flt:g} {unidad}"
        ))

        conn.commit()
        return {
            "producto": prod_nom,
            "ubicacion": ubicacion,
            "stock_anterior": stock_actual_ub,
            "stock_nuevo": conteo_flt,
            "diferencia": delta,
            "tipo_ajuste": tipo_mov
        }
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if cerrar_conn and conn:
            conn.close()

# ==============================================================================
# 7. KÁRDEX E HISTORIAL DE MOVIMIENTOS
# ==============================================================================

def obtener_kardex(filtro_codigo=None, tipo_movimiento=None, fecha_inicio=None, fecha_fin=None, limit=200, conn=None):
    """
    Retorna el historial inmutable de movimientos de inventario ordenado cronológicamente.
    """
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        query = """
            SELECT m.*, p.categoria
            FROM movimientos_inventario m
            LEFT JOIN productos p ON m.producto_id = p.id
            WHERE 1=1
        """
        params = []

        if filtro_codigo:
            term = f"%{str(filtro_codigo).strip().lower()}%"
            query += " AND (LOWER(m.codigo_producto) LIKE ? OR LOWER(m.nombre_producto) LIKE ? OR LOWER(m.referencia) LIKE ?)"
            params.extend([term, term, term])

        if tipo_movimiento and tipo_movimiento != "Todos":
            query += " AND m.tipo_movimiento = ?"
            params.append(tipo_movimiento)

        if fecha_inicio:
            query += " AND m.fecha >= ?"
            params.append(fecha_inicio)
        if fecha_fin:
            query += " AND m.fecha <= ?"
            params.append(fecha_fin)

        query += " ORDER BY m.id DESC LIMIT ?"
        params.append(limit)

        cur.execute(query, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        if cerrar_conn and conn:
            conn.close()

def obtener_historial_traslados(limit=100, conn=None):
    """Retorna los traslados registrados ordenados de más reciente a más antiguo."""
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT t.*, p.unidad_medida, p.costo
            FROM traslados_inventario t
            LEFT JOIN productos p ON t.producto_id = p.id
            ORDER BY t.id DESC LIMIT ?
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        if cerrar_conn and conn:
            conn.close()

def obtener_historial_compras(limit=100, conn=None):
    """Retorna compras registradas."""
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT c.*, COUNT(d.id) as cantidad_items
            FROM compras_inventario c
            LEFT JOIN detalle_compras d ON c.id = d.compra_id
            GROUP BY c.id
            ORDER BY c.id DESC LIMIT ?
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        if cerrar_conn and conn:
            conn.close()

# ==============================================================================
# 8. ALERTAS E INDICADORES EN TIEMPO REAL
# ==============================================================================

def obtener_alertas_inventario(conn=None):
    """
    Retorna listas de alertas activas:
    - Stock bajo en vitrina
    - Stock bajo en bodega
    - Agotados globales
    """
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("""
            SELECT codigo, nombre, categoria, stock_vitrina, stock_minimo_vitrina,
                   stock_bodega, stock_minimo_bodega, stock, unidad_medida
            FROM productos
            WHERE tipo_producto = 'Fisico' AND COALESCE(estado, 'Activo') = 'Activo'
        """)
        items = cur.fetchall()

        bajo_vitrina = []
        bajo_bodega = []
        agotados_globales = []

        for row in items:
            it = dict(row)
            sv = float(it["stock_vitrina"])
            sm_v = float(it["stock_minimo_vitrina"])
            sb = float(it["stock_bodega"])
            sm_b = float(it["stock_minimo_bodega"])
            st = float(it["stock"])

            if st <= 0:
                agotados_globales.append(it)
            else:
                if sv <= sm_v:
                    bajo_vitrina.append(it)
                if sb <= sm_b:
                    bajo_bodega.append(it)

        return {
            "bajo_vitrina": bajo_vitrina,
            "bajo_bodega": bajo_bodega,
            "agotados_globales": agotados_globales,
            "total_alertas": len(bajo_vitrina) + len(bajo_bodega) + len(agotados_globales)
        }
    finally:
        if cerrar_conn and conn:
            conn.close()

def obtener_resumen_indicadores(conn=None):
    """
    Calcula todos los indicadores ejecutivos del inventario:
    - Valor total a costo
    - Existencias totales por ubicación
    - Totales por tipo de artículo
    """
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Totales generales de productos
        cur.execute("""
            SELECT 
                COUNT(*) as total_articulos,
                SUM(CASE WHEN tipo_producto = 'Fisico' THEN 1 ELSE 0 END) as total_fisicos,
                SUM(CASE WHEN tipo_producto = 'Servicio' THEN 1 ELSE 0 END) as total_servicios,
                COALESCE(SUM(CASE WHEN tipo_producto = 'Fisico' THEN stock_bodega ELSE 0 END), 0.0) as unidades_bodega,
                COALESCE(SUM(CASE WHEN tipo_producto = 'Fisico' THEN stock_vitrina ELSE 0 END), 0.0) as unidades_vitrina,
                COALESCE(SUM(CASE WHEN tipo_producto = 'Fisico' THEN stock ELSE 0 END), 0.0) as unidades_totales,
                COALESCE(SUM(CASE WHEN tipo_producto = 'Fisico' THEN stock_bodega * COALESCE(costo, 0.0) ELSE 0 END), 0.0) as valor_bodega_costo,
                COALESCE(SUM(CASE WHEN tipo_producto = 'Fisico' THEN stock_vitrina * COALESCE(costo, 0.0) ELSE 0 END), 0.0) as valor_vitrina_costo,
                COALESCE(SUM(CASE WHEN tipo_producto = 'Fisico' THEN stock_vitrina * COALESCE(precio, 0.0) ELSE 0 END), 0.0) as valor_vitrina_venta,
                COALESCE(SUM(CASE WHEN tipo_producto = 'Fisico' THEN stock * COALESCE(costo, 0.0) ELSE 0 END), 0.0) as valor_inventario_total
            FROM productos
            WHERE COALESCE(estado, 'Activo') = 'Activo'
        """)
        row = cur.fetchone()
        resumen = dict(row) if row else {}

        # Alertas
        alertas = obtener_alertas_inventario(conn=conn)
        resumen.update({
            "alertas_bajo_vitrina": len(alertas["bajo_vitrina"]),
            "alertas_bajo_bodega": len(alertas["bajo_bodega"]),
            "alertas_agotados": len(alertas["agotados_globales"]),
            "total_alertas": alertas["total_alertas"]
        })
        return resumen
    finally:
        if cerrar_conn and conn:
            conn.close()

if __name__ == "__main__":
    inicializar_base_datos()
    ind = obtener_resumen_indicadores()
    print("Resumen de Inventario VmPOS:")
    for k, v in ind.items():
        print(f"  {k}: {v}")
