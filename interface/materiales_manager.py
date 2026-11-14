#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivo: materiales_manager.py
Gestor integral de inventario de materiales, presentaciones, bodegas,
inventarios individuales de operarios/administrador y consumos en ventas para VmPOS.
"""

from datetime import datetime
import json
import os
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    from interface.database_manager import conectar_db
except ImportError:
    from database_manager import conectar_db

try:
    from interface.config import DB_USUARIOS_PATH
except ImportError:
    try:
        from config import DB_USUARIOS_PATH
    except ImportError:
        DB_USUARIOS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "usuarios.db")


# ==============================================================================
# 1. CONSULTA DE TRABAJADORES (OPERARIOS Y ADMINISTRADOR)
# ==============================================================================

def obtener_trabajadores_para_materiales() -> List[Dict[str, Any]]:
    """
    Retorna la lista de usuarios activos que pueden recibir o consumir materiales:
    Operarios, Administradores y Vendedores.
    """
    trabajadores = []
    try:
        conn = sqlite3.connect(DB_USUARIOS_PATH, timeout=5.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT id, usuario, rol, nombre, apellidos, estado
            FROM usuarios
            WHERE estado = 'Activo'
            ORDER BY CASE WHEN rol = 'Administrador' THEN 0 WHEN rol = 'Operario' THEN 1 ELSE 2 END, usuario ASC
        """)
        for r in cur.fetchall():
            nom_comp = f"{r['nombre'] or ''} {r['apellidos'] or ''}".strip()
            display = f"{r['usuario']} ({nom_comp})" if nom_comp else r['usuario']
            trabajadores.append({
                "id": r["id"],
                "usuario": r["usuario"],
                "rol": r["rol"],
                "nombre_completo": nom_comp or r["usuario"],
                "display": display
            })
        conn.close()
    except Exception as e:
        print(f"Aviso al obtener usuarios para materiales: {e}")
        # Fallback siempre incluye a Administrador
        trabajadores = [{"id": 1, "usuario": "Administrador", "rol": "Administrador", "nombre_completo": "Administrador", "display": "Administrador"}]
    return trabajadores


# ==============================================================================
# 2. CATÁLOGO DE MATERIALES E INSUMOS
# ==============================================================================

def obtener_materiales_catalogo(filtro: str = "") -> List[Dict[str, Any]]:
    """
    Retorna los productos físicos o materiales configurados en el catálogo.
    """
    materiales = []
    conn = conectar_db()
    if not conn:
        return []
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        query = """
            SELECT id, codigo, nombre, tipo_producto, unidad_medida, stock_bodega, stock_vitrina, stock,
                   costo, precio, COALESCE(es_material, 0) as es_material,
                   COALESCE(presentacion_defecto, 'Paquete') as presentacion_defecto,
                   COALESCE(factor_conversion_defecto, 1.0) as factor_conversion_defecto,
                   COALESCE(unidad_consumo_defecto, 'Unidad') as unidad_consumo_defecto
            FROM productos
            WHERE estado = 'Activo' AND tipo_producto != 'Servicio'
        """
        params = []
        if filtro and filtro.strip():
            f = f"%{filtro.strip().lower()}%"
            query += " AND (LOWER(codigo) LIKE ? OR LOWER(nombre) LIKE ?)"
            params.extend([f, f])
        query += " ORDER BY es_material DESC, nombre ASC"

        cur.execute(query, params)
        for r in cur.fetchall():
            materiales.append(dict(r))
    finally:
        conn.close()
    return materiales


def marcar_producto_como_material(producto_id: int, es_material: bool = True, presentacion: str = "Paquete", factor: float = 1.0, unidad_consumo: str = "Unidad") -> bool:
    """Configura un producto como material con su presentación y factor de conversión."""
    conn = conectar_db()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE productos SET
                es_material = ?,
                presentacion_defecto = ?,
                factor_conversion_defecto = ?,
                unidad_consumo_defecto = ?
            WHERE id = ?
        """, (1 if es_material else 0, presentacion, float(factor), unidad_consumo, producto_id))
        conn.commit()
        return True
    finally:
        conn.close()


# ==============================================================================
# 3. CONFIGURACIÓN DE PRESENTACIONES Y FACTORES DE CONVERSIÓN
# ==============================================================================

def obtener_presentaciones_material(producto_id: int) -> List[Dict[str, Any]]:
    """Obtiene las presentaciones de compra registradas para un producto/material."""
    presentaciones = []
    conn = conectar_db()
    if not conn:
        return []
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT id, producto_id, codigo_producto, nombre_presentacion, unidad_compra,
                   cantidad_unidades_base, unidad_consumo, costo_defecto, codigo_barras, activo
            FROM presentaciones_producto
            WHERE producto_id = ? AND activo = 1
            ORDER BY nombre_presentacion ASC
        """, (producto_id,))
        for r in cur.fetchall():
            presentaciones.append(dict(r))
    finally:
        conn.close()
    return presentaciones


def guardar_presentacion_material(
    producto_id: int,
    codigo_producto: str,
    nombre_presentacion: str,
    unidad_compra: str = "Paquete",
    cantidad_unidades_base: float = 1.0,
    unidad_consumo: str = "Unidad",
    costo_defecto: float = 0.0,
    codigo_barras: str = ""
) -> int:
    """Guarda o actualiza una presentación con factor de equivalencia (Ej: Paquete x500 hojas)."""
    conn = conectar_db()
    if not conn:
        raise RuntimeError("No se pudo conectar a la base de datos.")
    try:
        cur = conn.cursor()
        ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("""
            INSERT INTO presentaciones_producto (
                producto_id, codigo_producto, nombre_presentacion, unidad_compra,
                cantidad_unidades_base, unidad_consumo, costo_defecto, codigo_barras,
                activo, fecha_creacion
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """, (
            producto_id, codigo_producto, nombre_presentacion, unidad_compra,
            float(cantidad_unidades_base), unidad_consumo, float(costo_defecto),
            codigo_barras, ahora
        ))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# ==============================================================================
# 4. INVENTARIO INDIVIDUAL DE OPERARIOS Y ADMINISTRADOR
# ==============================================================================

def obtener_inventario_operario(usuario_nombre: str) -> List[Dict[str, Any]]:
    """
    Retorna todos los materiales asignados y saldos disponibles para un usuario determinado.
    """
    items = []
    conn = conectar_db()
    if not conn:
        return []
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT io.id, io.usuario_nombre, io.rol, io.producto_id, io.codigo_producto,
                   io.nombre_producto, io.unidad_medida, io.stock_disponible,
                   io.total_recibido, io.total_consumido, io.total_desperdiciado, io.total_devuelto,
                   io.ultimo_movimiento, io.fecha_actualizacion,
                   p.costo as costo_unitario, p.stock_bodega
            FROM inventario_operarios io
            JOIN productos p ON p.id = io.producto_id
            WHERE io.usuario_nombre = ?
            ORDER BY io.nombre_producto ASC
        """, (usuario_nombre,))
        for r in cur.fetchall():
            items.append(dict(r))
    finally:
        conn.close()
    return items


def obtener_saldo_material_usuario(usuario_nombre: str, producto_id: int) -> float:
    """Retorna las existencias físicas disponibles de un material para un usuario específico."""
    conn = conectar_db()
    if not conn:
        return 0.0
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COALESCE(stock_disponible, 0.0)
            FROM inventario_operarios
            WHERE usuario_nombre = ? AND producto_id = ?
        """, (usuario_nombre, producto_id))
        r = cur.fetchone()
        return float(r[0]) if r else 0.0
    finally:
        conn.close()


def obtener_resumen_todos_operarios(filtro_usuario: Optional[str] = None, filtro_texto: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retorna la matriz completa de inventario individual de todos los trabajadores para el Administrador.
    """
    items = []
    conn = conectar_db()
    if not conn:
        return []
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        query = """
            SELECT io.id, io.usuario_nombre, io.rol, io.producto_id, io.codigo_producto,
                   io.nombre_producto, io.unidad_medida, io.stock_disponible,
                   io.total_recibido, io.total_consumido, io.total_desperdiciado, io.total_devuelto,
                   io.ultimo_movimiento, io.fecha_actualizacion,
                   p.stock_bodega, p.costo as costo_unitario
            FROM inventario_operarios io
            LEFT JOIN productos p ON p.id = io.producto_id
            WHERE 1=1
        """
        params = []
        if filtro_usuario and filtro_usuario != "Todos":
            query += " AND io.usuario_nombre = ?"
            params.append(filtro_usuario)
        if filtro_texto and filtro_texto.strip():
            ft = f"%{filtro_texto.strip().lower()}%"
            query += " AND (LOWER(io.nombre_producto) LIKE ? OR LOWER(io.codigo_producto) LIKE ? OR LOWER(io.usuario_nombre) LIKE ?)"
            params.extend([ft, ft, ft])
        query += " ORDER BY io.usuario_nombre ASC, io.nombre_producto ASC"

        cur.execute(query, params)
        for r in cur.fetchall():
            items.append(dict(r))
    finally:
        conn.close()
    return items


# ==============================================================================
# 5. TRASLADOS INTERNOS: BODEGA -> OPERARIO / ADMINISTRADOR
# ==============================================================================

def trasladar_bodega_a_operario(
    producto_id: int,
    usuario_destino: str,
    cantidad_unidades: Optional[float] = None,
    usuario_responsable: str = "Administrador",
    observaciones: str = "",
    cantidad: Optional[float] = None,
    usuario_admin: Optional[str] = None,
    motivo: Optional[str] = None
) -> Dict[str, Any]:
    """
    Traslada materiales desde Bodega al inventario individual de un operario o administrador.
    - Descuenta del stock_bodega en productos.
    - Incrementa el stock_disponible y total_recibido en inventario_operarios.
    - Registra el movimiento en traslados_inventario y kárdex (movimientos_inventario).
    - No genera ventas, ingresos ni gastos contables.
    """
    if cantidad_unidades is None and cantidad is not None:
        cantidad_unidades = float(cantidad)
    elif cantidad_unidades is None:
        cantidad_unidades = 0.0

    if usuario_admin:
        usuario_responsable = usuario_admin
    if motivo:
        observaciones = f"{observaciones} {motivo}".strip()

    if cantidad_unidades <= 0:
        raise ValueError("La cantidad a trasladar debe ser mayor a cero.")

    conn = conectar_db()
    if not conn:
        raise RuntimeError("No se pudo conectar a la base de datos.")

    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 1. Verificar producto y stock disponible en Bodega
        cur.execute("SELECT id, codigo, nombre, unidad_medida, stock_bodega, stock_vitrina, stock, costo FROM productos WHERE id = ?", (producto_id,))
        prod = cur.fetchone()
        if not prod:
            raise ValueError(f"No se encontró el producto con ID {producto_id}.")

        stock_bodega_ant = float(prod["stock_bodega"] or 0.0)
        if stock_bodega_ant < cantidad_unidades:
            raise ValueError(
                f"Stock insuficiente en Bodega para '{prod['nombre']}'.\n"
                f"Disponible en bodega: {stock_bodega_ant:g} {prod['unidad_medida']}.\n"
                f"Cantidad solicitada: {cantidad_unidades:g} {prod['unidad_medida']}."
            )

        stock_bodega_des = stock_bodega_ant - cantidad_unidades
        stock_total_des = stock_bodega_des + float(prod["stock_vitrina"] or 0.0)
        ahora = datetime.now()
        f_str = ahora.strftime("%Y-%m-%d")
        h_str = ahora.strftime("%H:%M:%S")

        # 2. Descontar de Bodega en productos
        cur.execute("""
            UPDATE productos SET
                stock_bodega = ?,
                stock = ?,
                fecha_modificacion = ?
            WHERE id = ?
        """, (stock_bodega_des, stock_total_des, f"{f_str} {h_str}", producto_id))

        # 3. Obtener o crear registro en inventario_operarios
        cur.execute("""
            SELECT id, stock_disponible, total_recibido
            FROM inventario_operarios
            WHERE usuario_nombre = ? AND producto_id = ?
        """, (usuario_destino, producto_id))
        inv_op = cur.fetchone()

        stock_op_ant = 0.0
        if inv_op:
            stock_op_ant = float(inv_op["stock_disponible"] or 0.0)
            stock_op_des = stock_op_ant + cantidad_unidades
            tot_recibido_des = float(inv_op["total_recibido"] or 0.0) + cantidad_unidades
            cur.execute("""
                UPDATE inventario_operarios SET
                    stock_disponible = ?,
                    total_recibido = ?,
                    ultimo_movimiento = 'TRASLADO_BODEGA',
                    fecha_actualizacion = ?
                WHERE id = ?
            """, (stock_op_des, tot_recibido_des, f"{f_str} {h_str}", inv_op["id"]))
        else:
            stock_op_des = cantidad_unidades
            # Consultar rol del usuario
            rol_u = "Administrador" if usuario_destino.lower() in ("admin", "administrador") else "Operario"
            try:
                conn_u = sqlite3.connect(DB_USUARIOS_PATH, timeout=3.0)
                cur_u = conn_u.cursor()
                cur_u.execute("SELECT id, rol FROM usuarios WHERE usuario = ?", (usuario_destino,))
                row_u = cur_u.fetchone()
                if row_u:
                    rol_u = row_u[1]
                conn_u.close()
            except Exception:
                pass

            cur.execute("""
                INSERT INTO inventario_operarios (
                    usuario_nombre, rol, producto_id, codigo_producto,
                    nombre_producto, unidad_medida, stock_disponible,
                    total_recibido, total_consumido, total_desperdiciado,
                    total_devuelto, ultimo_movimiento, fecha_actualizacion
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0.0, 0.0, 0.0, 'TRASLADO_BODEGA', ?)
            """, (
                usuario_destino, rol_u, producto_id, prod["codigo"],
                prod["nombre"], prod["unidad_medida"], cantidad_unidades,
                cantidad_unidades, f"{f_str} {h_str}"
            ))

        # 4. Registrar en traslados_inventario
        num_traslado = f"TR-MAT-{int(time.time()*1000)}"
        ubic_dest = f"OPERARIO:{usuario_destino}" if rol_u != "Administrador" else f"ADMIN:{usuario_destino}"
        obs_completa = f"Entregó: {usuario_responsable} -> Recibió: {usuario_destino}. {observaciones}".strip()

        cur.execute("""
            INSERT INTO traslados_inventario (
                numero_traslado, fecha, hora, producto_id, codigo_producto,
                nombre_producto, ubicacion_origen, ubicacion_destino,
                cantidad, usuario, estado, observaciones
            ) VALUES (?, ?, ?, ?, ?, ?, 'BODEGA', ?, ?, ?, 'Completado', ?)
        """, (
            num_traslado, f_str, h_str, producto_id, prod["codigo"],
            prod["nombre"], ubic_dest, cantidad_unidades, usuario_responsable, obs_completa
        ))

        # 5. Registrar en movimientos_inventario (Kárdex permanente)
        cur.execute("""
            INSERT INTO movimientos_inventario (
                fecha, hora, producto_id, codigo_producto, nombre_producto,
                tipo_movimiento, cantidad, unidad_medida, ubicacion_origen,
                ubicacion_destino, stock_origen_ant, stock_origen_des,
                stock_destino_ant, stock_destino_des, costo_unitario,
                valor_total, referencia, usuario, observaciones, estado
            ) VALUES (?, ?, ?, ?, ?, 'TRASLADO_BODEGA_A_OPERARIO', ?, ?, 'BODEGA', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Completado')
        """, (
            f_str, h_str, producto_id, prod["codigo"], prod["nombre"],
            cantidad_unidades, prod["unidad_medida"], ubic_dest,
            stock_bodega_ant, stock_bodega_des, stock_op_ant, stock_op_des,
            float(prod["costo"] or 0.0), round(cantidad_unidades * float(prod["costo"] or 0.0), 2),
            num_traslado, usuario_responsable, obs_completa
        ))

        conn.commit()
        return {
            "ok": True,
            "numero_traslado": num_traslado,
            "producto": prod["nombre"],
            "usuario_destino": usuario_destino,
            "cantidad": cantidad_unidades,
            "unidad": prod["unidad_medida"],
            "saldo_bodega_restante": stock_bodega_des,
            "saldo_operario_nuevo": stock_op_des,
            "saldo_nuevo_operario": stock_op_des
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ==============================================================================
# 6. DEVOLUCIÓN DE MATERIALES: OPERARIO / ADMINISTRADOR -> BODEGA
# ==============================================================================

def devolver_operario_a_bodega(
    producto_id: int,
    usuario_origen: Optional[str] = None,
    cantidad_unidades: Optional[float] = None,
    usuario_responsable: str = "Administrador",
    observaciones: str = "",
    usuario_operario: Optional[str] = None,
    cantidad: Optional[float] = None,
    motivo: Optional[str] = None
) -> Dict[str, Any]:
    """
    Devuelve material desde el inventario del trabajador de regreso a Bodega.
    - Descuenta de stock_disponible e incrementa total_devuelto en inventario_operarios.
    - Incrementa stock_bodega y stock en productos.
    - Registra en kárdex (DEVOLUCION_OPERARIO_A_BODEGA).
    """
    if usuario_origen is None and usuario_operario is not None:
        usuario_origen = usuario_operario
    elif usuario_origen is None:
        usuario_origen = "Operario"

    if cantidad_unidades is None and cantidad is not None:
        cantidad_unidades = float(cantidad)
    elif cantidad_unidades is None:
        cantidad_unidades = 0.0

    if motivo:
        observaciones = f"{observaciones} {motivo}".strip()

    if cantidad_unidades <= 0:
        raise ValueError("La cantidad a devolver debe ser mayor a cero.")

    conn = conectar_db()
    if not conn:
        raise RuntimeError("No se pudo conectar a la base de datos.")

    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 1. Verificar existencia y saldo del operario
        cur.execute("""
            SELECT id, stock_disponible, total_devuelto, nombre_producto, codigo_producto, unidad_medida
            FROM inventario_operarios
            WHERE usuario_nombre = ? AND producto_id = ?
        """, (usuario_origen, producto_id))
        inv_op = cur.fetchone()
        if not inv_op:
            raise ValueError(f"El usuario '{usuario_origen}' no posee registro de inventario para este material.")

        saldo_op_ant = float(inv_op["stock_disponible"] or 0.0)
        if saldo_op_ant < cantidad_unidades:
            raise ValueError(
                f"El trabajador '{usuario_origen}' solo tiene {saldo_op_ant:g} {inv_op['unidad_medida']} disponibles.\n"
                f"No puede devolver {cantidad_unidades:g}."
            )

        saldo_op_des = saldo_op_ant - cantidad_unidades
        tot_dev_des = float(inv_op["total_devuelto"] or 0.0) + cantidad_unidades
        ahora = datetime.now()
        f_str = ahora.strftime("%Y-%m-%d")
        h_str = ahora.strftime("%H:%M:%S")

        # 2. Actualizar inventario de operario
        cur.execute("""
            UPDATE inventario_operarios SET
                stock_disponible = ?,
                total_devuelto = ?,
                ultimo_movimiento = 'DEVOLUCION_A_BODEGA',
                fecha_actualizacion = ?
            WHERE id = ?
        """, (saldo_op_des, tot_dev_des, f"{f_str} {h_str}", inv_op["id"]))

        # 3. Sumar a stock_bodega en productos
        cur.execute("SELECT stock_bodega, stock_vitrina, stock, costo FROM productos WHERE id = ?", (producto_id,))
        p = cur.fetchone()
        stock_b_ant = float(p["stock_bodega"] or 0.0)
        stock_b_des = stock_b_ant + cantidad_unidades
        stock_tot_des = stock_b_des + float(p["stock_vitrina"] or 0.0)

        cur.execute("""
            UPDATE productos SET
                stock_bodega = ?,
                stock = ?,
                fecha_modificacion = ?
            WHERE id = ?
        """, (stock_b_des, stock_tot_des, f"{f_str} {h_str}", producto_id))

        # 4. Registrar en kárdex
        ubic_orig = f"OPERARIO:{usuario_origen}"
        num_ref = f"DEV-MAT-{int(time.time()*1000)}"
        obs_dev = f"Devolución autorizada de {usuario_origen} hacia Bodega. {observaciones}".strip()

        cur.execute("""
            INSERT INTO movimientos_inventario (
                fecha, hora, producto_id, codigo_producto, nombre_producto,
                tipo_movimiento, cantidad, unidad_medida, ubicacion_origen,
                ubicacion_destino, stock_origen_ant, stock_origen_des,
                stock_destino_ant, stock_destino_des, costo_unitario,
                valor_total, referencia, usuario, observaciones, estado
            ) VALUES (?, ?, ?, ?, ?, 'DEVOLUCION_OPERARIO_A_BODEGA', ?, ?, ?, 'BODEGA', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Completado')
        """, (
            f_str, h_str, producto_id, inv_op["codigo_producto"], inv_op["nombre_producto"],
            cantidad_unidades, inv_op["unidad_medida"], ubic_orig,
            saldo_op_ant, saldo_op_des, stock_b_ant, stock_b_des,
            float(p["costo"] or 0.0), round(cantidad_unidades * float(p["costo"] or 0.0), 2),
            num_ref, usuario_responsable, obs_dev
        ))

        conn.commit()
        return {
            "ok": True,
            "referencia": num_ref,
            "producto": inv_op["nombre_producto"],
            "usuario_origen": usuario_origen,
            "cantidad_devuelta": cantidad_unidades,
            "nuevo_saldo_operario": saldo_op_des,
            "nuevo_saldo_bodega": stock_b_des
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ==============================================================================
# 7. REGISTRO DE DESPERDICIO / MERMA DE MATERIALES
# ==============================================================================

def registrar_desperdicio_material(
    producto_id: int,
    usuario_origen: Optional[str] = None,
    cantidad_unidades: Optional[float] = None,
    motivo: str = "Material dañado/prueba de impresión",
    usuario_responsable: str = "Administrador",
    usuario_operario: Optional[str] = None,
    cantidad: Optional[float] = None,
    usuario_registra: Optional[str] = None,
    maquina: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Registra desperdicio o merma imputada al trabajador.
    - Descuenta del stock_disponible e incrementa total_desperdiciado.
    - Registra en kárdex (DESPERDICIO).
    """
    if usuario_origen is None and usuario_operario is not None:
        usuario_origen = usuario_operario
    elif usuario_origen is None:
        usuario_origen = "Operario"

    if cantidad_unidades is None and cantidad is not None:
        cantidad_unidades = float(cantidad)
    elif cantidad_unidades is None:
        cantidad_unidades = 0.0

    if usuario_registra:
        usuario_responsable = usuario_registra

    if maquina:
        motivo = f"{motivo} [Máquina: {maquina}]"

    if cantidad_unidades <= 0:
        raise ValueError("La cantidad de desperdicio debe ser mayor a cero.")

    conn = conectar_db()
    if not conn:
        raise RuntimeError("No se pudo conectar a la base de datos.")

    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("""
            SELECT id, stock_disponible, total_desperdiciado, nombre_producto, codigo_producto, unidad_medida
            FROM inventario_operarios
            WHERE usuario_nombre = ? AND producto_id = ?
        """, (usuario_origen, producto_id))
        inv_op = cur.fetchone()
        if not inv_op:
            raise ValueError(f"El usuario '{usuario_origen}' no posee registro para este material.")

        saldo_op_ant = float(inv_op["stock_disponible"] or 0.0)
        if saldo_op_ant < cantidad_unidades:
            raise ValueError(
                f"El trabajador '{usuario_origen}' solo tiene {saldo_op_ant:g} {inv_op['unidad_medida']} disponibles.\n"
                f"No puede reportar desperdicio por {cantidad_unidades:g}."
            )

        saldo_op_des = saldo_op_ant - cantidad_unidades
        tot_desp_des = float(inv_op["total_desperdiciado"] or 0.0) + cantidad_unidades
        ahora = datetime.now()
        f_str = ahora.strftime("%Y-%m-%d")
        h_str = ahora.strftime("%H:%M:%S")

        cur.execute("""
            UPDATE inventario_operarios SET
                stock_disponible = ?,
                total_desperdiciado = ?,
                ultimo_movimiento = 'DESPERDICIO',
                fecha_actualizacion = ?
            WHERE id = ?
        """, (saldo_op_des, tot_desp_des, f"{f_str} {h_str}", inv_op["id"]))

        # Obtener costo del producto
        cur.execute("SELECT costo FROM productos WHERE id = ?", (producto_id,))
        p = cur.fetchone()
        costo_u = float(p["costo"] or 0.0) if p else 0.0

        ref_desp = f"DSP-MAT-{int(time.time()*1000)}"
        cur.execute("""
            INSERT INTO movimientos_inventario (
                fecha, hora, producto_id, codigo_producto, nombre_producto,
                tipo_movimiento, cantidad, unidad_medida, ubicacion_origen,
                ubicacion_destino, stock_origen_ant, stock_origen_des,
                stock_destino_ant, stock_destino_des, costo_unitario,
                valor_total, referencia, usuario, observaciones, estado
            ) VALUES (?, ?, ?, ?, ?, 'DESPERDICIO', ?, ?, ?, 'DESPERDICIO', ?, ?, 0.0, 0.0, ?, ?, ?, ?, ?, 'Completado')
        """, (
            f_str, h_str, producto_id, inv_op["codigo_producto"], inv_op["nombre_producto"],
            cantidad_unidades, inv_op["unidad_medida"], f"OPERARIO:{usuario_origen}",
            saldo_op_ant, saldo_op_des, costo_u, round(cantidad_unidades * costo_u, 2),
            ref_desp, usuario_responsable, f"Desperdicio de {usuario_origen}: {motivo}"
        ))

        conn.commit()
        return {
            "ok": True,
            "referencia": ref_desp,
            "producto": inv_op["nombre_producto"],
            "usuario": usuario_origen,
            "cantidad_desperdiciada": cantidad_unidades,
            "saldo_restante": saldo_op_des
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ==============================================================================
# 8. CONSUMO EN VENTAS Y TRABAJOS (CARGAR MATERIAL)
# ==============================================================================

def descontar_materiales_venta(
    venta_id: int,
    numero_factura: str,
    usuario_operario: str,
    items_materiales: List[Dict[str, Any]],
    conn: Optional[sqlite3.Connection] = None,
    observaciones: str = "",
    **kwargs
) -> Dict[str, Any]:
    """
    Descuenta de forma atómica e idempotente los materiales utilizados en una venta.
    items_materiales: [
        {"producto_id": 1, "codigo": "0001", "nombre": "Papel Normal", "cantidad": 20.0, "unidad": "Hoja"},
        ...
    ]
    - Valida saldos individuales del usuario responsable (operario o admin).
    - Descuenta stock_disponible e incrementa total_consumido.
    - Registra en consumos_materiales_venta y movimientos_inventario.
    - Idempotente: si ya existen consumos para venta_id, no se duplican.
    """
    if not items_materiales:
        return {"ok": True, "consumos": [], "total_descontados": 0}

    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    if not conn:
        raise RuntimeError("No se pudo conectar a la base de datos.")

    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Idempotencia: Verificar si ya existen consumos para esta venta_id
        cur.execute("SELECT COUNT(*) FROM consumos_materiales_venta WHERE venta_id = ?", (venta_id,))
        if cur.fetchone()[0] > 0:
            return {"ok": True, "aviso": "Consumos ya aplicados previamente para esta venta", "venta_id": venta_id, "total_descontados": 0}

        ahora = datetime.now()
        f_str = ahora.strftime("%Y-%m-%d")
        h_str = ahora.strftime("%H:%M:%S")

        # 1. Validar existencias de todos los ítems antes de aplicar cambios
        for it in items_materiales:
            pid = int(it.get("producto_id") or it.get("id") or 0)
            cant_req = float(it.get("cantidad") or 0.0)
            if cant_req <= 0:
                continue

            cur.execute("""
                SELECT stock_disponible, nombre_producto, unidad_medida
                FROM inventario_operarios
                WHERE usuario_nombre = ? AND producto_id = ?
            """, (usuario_operario, pid))
            row_inv = cur.fetchone()
            disponible = float(row_inv["stock_disponible"] or 0.0) if row_inv else 0.0
            nom_m = it.get("nombre") or (row_inv["nombre_producto"] if row_inv else f"Material #{pid}")

            if disponible < cant_req:
                return {
                    "ok": False,
                    "mensaje": (
                        f"Saldo insuficiente para el trabajador '{usuario_operario}'.\n"
                        f"Material: {nom_m}\n"
                        f"Disponible en su inventario: {disponible:g}\n"
                        f"Requerido para la venta: {cant_req:g}"
                    ),
                    "disponible": disponible,
                    "requerido": cant_req
                }

        # 2. Descontar inventario individual y registrar en consumos_materiales_venta
        consumos_aplicados = []
        for it in items_materiales:
            pid = int(it.get("producto_id") or it.get("id") or 0)
            cant_req = float(it.get("cantidad") or 0.0)
            if cant_req <= 0:
                continue

            cur.execute("""
                SELECT id, stock_disponible, total_consumido, codigo_producto, nombre_producto, unidad_medida
                FROM inventario_operarios
                WHERE usuario_nombre = ? AND producto_id = ?
            """, (usuario_operario, pid))
            inv_row = cur.fetchone()

            saldo_ant = float(inv_row["stock_disponible"] or 0.0)
            saldo_des = saldo_ant - cant_req
            tot_cons_des = float(inv_row["total_consumido"] or 0.0) + cant_req

            cur.execute("""
                UPDATE inventario_operarios SET
                    stock_disponible = ?,
                    total_consumido = ?,
                    ultimo_movimiento = 'CONSUMO_VENTA',
                    fecha_actualizacion = ?
                WHERE id = ?
            """, (saldo_des, tot_cons_des, f"{f_str} {h_str}", inv_row["id"]))

            # Obtener costo del producto
            cur.execute("SELECT costo FROM productos WHERE id = ?", (pid,))
            p_cost = cur.fetchone()
            costo_u = float(p_cost["costo"] or 0.0) if p_cost else 0.0
            costo_tot = round(cant_req * costo_u, 2)

            cur.execute("""
                INSERT INTO consumos_materiales_venta (
                    venta_id, numero_factura, usuario_responsable,
                    producto_id, codigo_producto, nombre_producto,
                    cantidad_consumida, unidad_medida, saldo_anterior,
                    saldo_restante, costo_unitario, costo_total,
                    fecha, hora, estado, observaciones
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Aplicado', ?)
            """, (
                venta_id, numero_factura or f"V-{venta_id}", usuario_operario,
                pid, inv_row["codigo_producto"], inv_row["nombre_producto"],
                cant_req, inv_row["unidad_medida"], saldo_ant,
                saldo_des, costo_u, costo_tot,
                f_str, h_str, observaciones or f"Consumido en venta #{venta_id}"
            ))

            # Registrar en Kárdex
            cur.execute("""
                INSERT INTO movimientos_inventario (
                    fecha, hora, producto_id, codigo_producto, nombre_producto,
                    tipo_movimiento, cantidad, unidad_medida, ubicacion_origen,
                    ubicacion_destino, stock_origen_ant, stock_origen_des,
                    stock_destino_ant, stock_destino_des, costo_unitario,
                    valor_total, referencia, usuario, observaciones, estado
                ) VALUES (?, ?, ?, ?, ?, 'CONSUMO_VENTA', ?, ?, ?, ?, ?, ?, 0.0, 0.0, ?, ?, ?, ?, ?, 'Completado')
            """, (
                f_str, h_str, pid, inv_row["codigo_producto"], inv_row["nombre_producto"],
                cant_req, inv_row["unidad_medida"], f"OPERARIO:{usuario_operario}",
                f"VENTA:{venta_id}", saldo_ant, saldo_des, costo_u, costo_tot,
                f"VENTA-{venta_id}", usuario_operario, f"Consumo de material para factura {numero_factura or venta_id}"
            ))

            consumos_aplicados.append({
                "producto_id": pid,
                "nombre": inv_row["nombre_producto"],
                "cantidad": cant_req,
                "saldo_restante": saldo_des
            })

        if cerrar_conn:
            conn.commit()

        return {
            "ok": True,
            "venta_id": venta_id,
            "usuario": usuario_operario,
            "total_descontados": len(consumos_aplicados),
            "consumos": consumos_aplicados
        }
    except Exception:
        if cerrar_conn:
            conn.rollback()
        raise
    finally:
        if cerrar_conn and conn:
            conn.close()


def obtener_consumos_de_venta(venta_id: int) -> List[Dict[str, Any]]:
    """Consulta los materiales cargados a una venta específica."""
    consumos = []
    conn = conectar_db()
    if not conn:
        return []
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT id, venta_id, numero_factura, usuario_responsable,
                   producto_id, codigo_producto, nombre_producto,
                   cantidad_consumida, unidad_medida, saldo_anterior,
                   saldo_restante, costo_unitario, costo_total, fecha, hora, estado
            FROM consumos_materiales_venta
            WHERE venta_id = ?
            ORDER BY id ASC
        """, (venta_id,))
        for r in cur.fetchall():
            consumos.append(dict(r))
    finally:
        conn.close()
    return consumos


# ==============================================================================
# 9. GESTIÓN DE CONSUMOS ANTE ANULACIÓN DE VENTA
# ==============================================================================

def gestionar_consumo_anulacion_venta(
    venta_id: int,
    reincorporar_a_inventario: bool = False,
    usuario_responsable: str = "Administrador",
    motivo: str = "",
    accion: Optional[str] = None,
    usuario_admin: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Gestiona los materiales cuando se anula una venta.
    - Si reincorporar_a_inventario=True (o accion='devolver'): devuelve el material al inventario del operario.
    - Si reincorporar_a_inventario=False (o accion='desperdicio'): el material se da por perdido/utilizado (desperdicio).
    Conserva la trazabilidad e historial inmutable.
    """
    if usuario_admin:
        usuario_responsable = usuario_admin
    if accion is not None:
        reincorporar_a_inventario = (accion.lower() in ("devolver", "reincorporar", "reintegrar"))
    conn = conectar_db()
    if not conn:
        raise RuntimeError("No se pudo conectar a la base de datos.")

    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("""
            SELECT id, usuario_responsable, producto_id, codigo_producto,
                   nombre_producto, cantidad_consumida, unidad_medida, costo_unitario
            FROM consumos_materiales_venta
            WHERE venta_id = ? AND estado = 'Aplicado'
        """, (venta_id,))
        consumos = [dict(r) for r in cur.fetchall()]

        if not consumos:
            return {"aviso": "No existen consumos de materiales aplicados para esta venta.", "venta_id": venta_id}

        ahora = datetime.now()
        f_str = ahora.strftime("%Y-%m-%d")
        h_str = ahora.strftime("%H:%M:%S")

        for c in consumos:
            op_user = c["usuario_responsable"]
            pid = c["producto_id"]
            cant = float(c["cantidad_consumida"])

            if reincorporar_a_inventario:
                # Devolver al saldo disponible del trabajador
                cur.execute("""
                    UPDATE inventario_operarios SET
                        stock_disponible = stock_disponible + ?,
                        total_consumido = MAX(0.0, total_consumido - ?),
                        ultimo_movimiento = 'REVERSION_VENTA_ANULADA',
                        fecha_actualizacion = ?
                    WHERE usuario_nombre = ? AND producto_id = ?
                """, (cant, cant, f"{f_str} {h_str}", op_user, pid))

                cur.execute("UPDATE consumos_materiales_venta SET estado = 'Anulado_Revertido' WHERE id = ?", (c["id"],))

                # Registrar movimiento kárdex
                cur.execute("""
                    INSERT INTO movimientos_inventario (
                        fecha, hora, producto_id, codigo_producto, nombre_producto,
                        tipo_movimiento, cantidad, unidad_medida, ubicacion_origen,
                        ubicacion_destino, stock_origen_ant, stock_origen_des,
                        stock_destino_ant, stock_destino_des, costo_unitario,
                        valor_total, referencia, usuario, observaciones, estado
                    ) VALUES (?, ?, ?, ?, ?, 'REVERSION_CONSUMO_ANULACION', ?, ?, ?, ?, 0.0, 0.0, 0.0, 0.0, ?, ?, ?, ?, ?, 'Completado')
                """, (
                    f_str, h_str, pid, c["codigo_producto"], c["nombre_producto"],
                    cant, c["unidad_medida"], f"VENTA_ANULADA:{venta_id}", f"OPERARIO:{op_user}",
                    float(c["costo_unitario"] or 0.0), round(cant * float(c["costo_unitario"] or 0.0), 2),
                    f"REV-VENTA-{venta_id}", usuario_responsable, f"Reincorporación de material por anulación de factura: {motivo}"
                ))
            else:
                # No se reincorpora: se registra como desperdicio/pérdida real
                cur.execute("""
                    UPDATE inventario_operarios SET
                        total_consumido = MAX(0.0, total_consumido - ?),
                        total_desperdiciado = total_desperdiciado + ?,
                        ultimo_movimiento = 'DESPERDICIO_VENTA_ANULADA',
                        fecha_actualizacion = ?
                    WHERE usuario_nombre = ? AND producto_id = ?
                """, (cant, cant, f"{f_str} {h_str}", op_user, pid))

                cur.execute("UPDATE consumos_materiales_venta SET estado = 'Anulado_Desperdicio' WHERE id = ?", (c["id"],))

                cur.execute("""
                    INSERT INTO movimientos_inventario (
                        fecha, hora, producto_id, codigo_producto, nombre_producto,
                        tipo_movimiento, cantidad, unidad_medida, ubicacion_origen,
                        ubicacion_destino, stock_origen_ant, stock_origen_des,
                        stock_destino_ant, stock_destino_des, costo_unitario,
                        valor_total, referencia, usuario, observaciones, estado
                    ) VALUES (?, ?, ?, ?, ?, 'DESPERDICIO_POR_ANULACION', ?, ?, ?, 'DESPERDICIO', 0.0, 0.0, 0.0, 0.0, ?, ?, ?, ?, ?, 'Completado')
                """, (
                    f_str, h_str, pid, c["codigo_producto"], c["nombre_producto"],
                    cant, c["unidad_medida"], f"OPERARIO:{op_user}",
                    float(c["costo_unitario"] or 0.0), round(cant * float(c["costo_unitario"] or 0.0), 2),
                    f"DSP-VENTA-{venta_id}", usuario_responsable, f"Material consumido no recuperable por anulación de venta #{venta_id}: {motivo}"
                ))

        conn.commit()
        return {
            "ok": True,
            "venta_id": venta_id,
            "reincorporado": reincorporar_a_inventario,
            "items_procesados": len(consumos)
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ==============================================================================
# 10. HISTORIAL KÁRDEX Y REPORTES DE MATERIALES
# ==============================================================================

def obtener_historial_materiales(
    filtro_usuario: Optional[str] = None,
    filtro_material: Optional[str] = None,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    limit: int = 300
) -> List[Dict[str, Any]]:
    """Consulta enriquecida de movimientos de materiales con filtros múltiples."""
    movs = []
    conn = conectar_db()
    if not conn:
        return []
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        query = """
            SELECT id, fecha, hora, producto_id, codigo_producto, nombre_producto,
                   tipo_movimiento, cantidad, unidad_medida, ubicacion_origen,
                   ubicacion_destino, stock_origen_ant, stock_origen_des,
                   stock_destino_ant, stock_destino_des, costo_unitario,
                   valor_total, referencia, usuario, observaciones, estado
            FROM movimientos_inventario
            WHERE tipo_movimiento IN (
                'ENTRADA_COMPRA', 'RECEPCION_COMPRA',
                'TRASLADO_BODEGA_A_OPERARIO', 'TRASLADO_BODEGA_A_VITRINA', 'TRASLADO_VITRINA_A_BODEGA',
                'DEVOLUCION_OPERARIO_A_BODEGA', 'CONSUMO_VENTA',
                'DESPERDICIO', 'DESPERDICIO_OPERARIO', 'DESPERDICIO_POR_ANULACION',
                'REVERSION_CONSUMO_ANULACION', 'AJUSTE_POSITIVO', 'AJUSTE_NEGATIVO'
            )
        """
        params = []
        if filtro_usuario and filtro_usuario != "Todos":
            query += " AND (usuario = ? OR ubicacion_destino LIKE ? OR ubicacion_origen LIKE ?)"
            params.extend([filtro_usuario, f"%{filtro_usuario}%", f"%{filtro_usuario}%"])

        if filtro_material and filtro_material.strip():
            fm = f"%{filtro_material.strip().lower()}%"
            query += " AND (LOWER(nombre_producto) LIKE ? OR LOWER(codigo_producto) LIKE ?)"
            params.extend([fm, fm])

        if fecha_inicio:
            query += " AND fecha >= ?"
            params.append(fecha_inicio)

        if fecha_fin:
            query += " AND fecha <= ?"
            params.append(fecha_fin)

        query += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))

        cur.execute(query, params)
        for r in cur.fetchall():
            movs.append(dict(r))
    finally:
        conn.close()
    return movs


def obtener_kpis_materiales() -> Dict[str, Any]:
    """Retorna totales globales de existencias de materiales para tarjetas resumen."""
    conn = conectar_db()
    if not conn:
        return {}
    try:
        cur = conn.cursor()
        # Total en Bodega de productos físicos
        cur.execute("SELECT COALESCE(SUM(stock_bodega), 0.0), COALESCE(SUM(stock_vitrina), 0.0) FROM productos WHERE tipo_producto != 'Servicio'")
        r_bod = cur.fetchone()
        tot_bodega = float(r_bod[0]) if r_bod else 0.0
        tot_vitrina = float(r_bod[1]) if r_bod else 0.0

        # Totales en manos de operarios
        cur.execute("""
            SELECT COALESCE(SUM(stock_disponible), 0.0),
                   COALESCE(SUM(total_recibido), 0.0),
                   COALESCE(SUM(total_consumido), 0.0),
                   COALESCE(SUM(total_desperdiciado), 0.0),
                   COALESCE(SUM(total_devuelto), 0.0)
            FROM inventario_operarios
        """)
        r_op = cur.fetchone()
        tot_op_disponible = float(r_op[0]) if r_op else 0.0
        tot_op_recibido = float(r_op[1]) if r_op else 0.0
        tot_op_consumido = float(r_op[2]) if r_op else 0.0
        tot_op_desperdiciado = float(r_op[3]) if r_op else 0.0
        tot_op_devuelto = float(r_op[4]) if r_op else 0.0

        return {
            "total_bodega": tot_bodega,
            "total_vitrina": tot_vitrina,
            "total_operarios_disponible": tot_op_disponible,
            "total_operarios_recibido": tot_op_recibido,
            "total_operarios_consumido": tot_op_consumido,
            "total_operarios_desperdiciado": tot_op_desperdiciado,
            "total_operarios_devuelto": tot_op_devuelto,
            "total_asignado": tot_op_recibido,
            "total_consumido": tot_op_consumido,
            "total_desperdiciado": tot_op_desperdiciado,
            "total_devuelto": tot_op_devuelto
        }
    finally:
        conn.close()
