#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo de Gestión Integral de Proveedores, Servicios Tercerizados, Cuentas por Pagar y Liquidaciones - VmPOS
Archivo: interface/proveedores_manager.py

Garantiza:
1. Diferenciación estricta entre servicios propios (100% ingreso negocio) y servicios de proveedores
   (generan cuenta por pagar al proveedor descontando la comisión acordada).
2. Cálculo exacto y trazable de comisión y saldo por pagar:
   - comisión = precio_real_de_venta * porcentaje_comisión / 100
   - importe_por_pagar_al_proveedor = precio_real_de_venta - comisión
3. Registro atómico e inmutable de cuentas por pagar vinculado a cada venta.
4. Liquidaciones totales y abonos parciales con afectación contable a Caja o Banco según el medio de pago.
5. Historial permanente de ventas y liquidaciones (nunca se borra al llegar a saldo $0).
6. Separación absoluta entre cuentas por pagar a proveedores y la nómina de empleados.
7. Protección contra doble clic o ejecuciones duplicadas de pagos.
"""

import os
import sys
import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from interface.database_manager import conectar_db, inicializar_base_datos
except ImportError:
    try:
        from database_manager import conectar_db, inicializar_base_datos
    except ImportError:
        _root = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, _root)
        from database_manager import conectar_db, inicializar_base_datos

# Candado en memoria para evitar dobles pagos simultáneos por interfaz
_PAGOS_EN_PROCESO = set()


def inicializar_tablas_proveedores(conn: Optional[sqlite3.Connection] = None) -> bool:
    """Asegura la creación de tablas e índices para cuentas por pagar y liquidaciones de proveedores."""
    res = inicializar_base_datos()
    try:
        sincronizar_cxp_ventas_anuladas(conn=conn)
    except Exception as e:
        print(f"Aviso en sincronización inicial de cxp proveedores: {e}")
    return res


def recalcular_saldo_proveedor(proveedor_id: int, conn: Optional[sqlite3.Connection] = None) -> Dict[str, float]:
    """
    Recalcula los acumulados y saldos pendientes de un proveedor basándose en sus registros
    de cuentas por pagar y liquidaciones efectivas.
    """
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    try:
        cur = conn.cursor()
        # Sumar saldos de cuentas por pagar no anuladas
        cur.execute("""
            SELECT 
                COALESCE(SUM(precio_venta), 0.0),
                COALESCE(SUM(monto_comision), 0.0),
                COALESCE(SUM(monto_pagado), 0.0),
                COALESCE(SUM(saldo_pendiente), 0.0)
            FROM cuentas_por_pagar_proveedores
            WHERE proveedor_id = ? AND estado != 'Anulada'
        """, (proveedor_id,))
        row = cur.fetchone()
        tot_v = float(row[0] or 0.0)
        tot_c = float(row[1] or 0.0)
        tot_p = float(row[2] or 0.0)
        saldo_p = float(row[3] or 0.0)

        # Actualizar tabla proveedores
        cur.execute("""
            UPDATE proveedores
            SET saldo_acumulado = ?,
                total_ventas = ?,
                total_comisiones = ?,
                total_pagado = ?
            WHERE id = ?
        """, (saldo_p, tot_v, tot_c, tot_p, proveedor_id))

        if cerrar_conn:
            conn.commit()

        return {
            "saldo_pendiente": saldo_p,
            "total_ventas": tot_v,
            "total_comisiones": tot_c,
            "total_pagado": tot_p
        }
    finally:
        if cerrar_conn and conn:
            conn.close()


def registrar_cxp_servicio_venta(
    id_venta: int,
    detalle_item: Dict[str, Any],
    operario_nombre: str = "Administrador",
    numero_venta: str = "",
    fecha_str: Optional[str] = None,
    hora_str: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> Optional[Dict[str, Any]]:
    """
    Evalúa si un ítem vendido corresponde a un servicio con proveedor habitual.
    Si es así, calcula la comisión y registra la cuenta por pagar vinculada a la venta.
    
    Reglas:
    - Si el servicio es propio (sin proveedor): no genera cuenta por pagar.
    - Si la comisión acordada está vacía o es 0%: monto_por_pagar = precio_venta (comisión = 0).
    - Si la comisión está entre 0 y 100%:
      comisión = precio_real * porcentaje / 100
      monto_por_pagar = precio_real - comisión
    """
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    try:
        cur = conn.cursor()
        ahora = datetime.now()
        f_str = fecha_str or ahora.strftime("%Y-%m-%d")
        h_str = hora_str or ahora.strftime("%H:%M:%S")
        num_v = numero_venta or f"V-{id_venta:05d}"

        cod = str(detalle_item.get("codigo_producto", detalle_item.get("item_codigo", detalle_item.get("codigo", "")))).strip()
        nom = str(detalle_item.get("nombre_producto", detalle_item.get("item_nombre", detalle_item.get("nombre", "")))).strip()
        cant = int(detalle_item.get("cantidad", 1) or 1)
        subtotal_real = float(detalle_item.get("subtotal", 0.0) or 0.0)
        if subtotal_real <= 0:
            p_unit = float(detalle_item.get("precio_vendido", detalle_item.get("precio_unitario", detalle_item.get("precio", 0.0))) or 0.0)
            subtotal_real = p_unit * cant

        # Consultar datos maestros del producto/servicio en la base de datos
        cur.execute("""
            SELECT p.tipo_producto, p.proveedor_id, COALESCE(p.porcentaje_comision, 0.0), prov.nombre
            FROM productos p
            LEFT JOIN proveedores prov ON p.proveedor_id = prov.id
            WHERE p.codigo = ? OR p.codigo = ?
        """, (cod, cod.zfill(5)))
        p_row = cur.fetchone()

        if not p_row:
            return None

        tipo_prod = str(p_row[0] or "Fisico").strip()
        prov_id = p_row[1]
        porcentaje_com = float(p_row[2] or 0.0)
        prov_nom = str(p_row[3] or "").strip()

        # Solo aplica a servicios que tengan un proveedor asignado
        if tipo_prod != "Servicio" or not prov_id or prov_id <= 0:
            return None

        # Si el proveedor no tiene nombre en la relación, buscar directamente
        if not prov_nom:
            cur.execute("SELECT nombre FROM proveedores WHERE id = ?", (prov_id,))
            p_nom_row = cur.fetchone()
            prov_nom = str(p_nom_row[0] if p_nom_row else f"Proveedor #{prov_id}")

        # Validar porcentaje de comisión (0 a 100%)
        porcentaje_com = max(0.0, min(100.0, porcentaje_com))

        # Fórmulas requeridas:
        # comisión = precio_real_de_venta * porcentaje_comisión / 100
        # importe_por_pagar_al_proveedor = precio_real_de_venta - comisión
        monto_comision = round(subtotal_real * (porcentaje_com / 100.0), 2)
        monto_por_pagar = round(subtotal_real - monto_comision, 2)

        # Evitar registros duplicados para la misma venta y código de servicio
        cur.execute("""
            SELECT id FROM cuentas_por_pagar_proveedores
            WHERE id_venta = ? AND codigo_servicio = ?
        """, (id_venta, cod))
        existente = cur.fetchone()
        if existente:
            return None

        estado_inicial = "Pagada" if monto_por_pagar <= 0.0 else "Pendiente"

        cur.execute("""
            INSERT INTO cuentas_por_pagar_proveedores (
                proveedor_id, proveedor_nombre, id_venta, numero_venta,
                codigo_servicio, nombre_servicio, precio_venta, porcentaje_comision,
                monto_comision, monto_por_pagar, monto_pagado, saldo_pendiente,
                estado, fecha, hora, usuario
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, ?, ?, ?, ?, ?)
        """, (
            prov_id, prov_nom, id_venta, num_v,
            cod, nom, subtotal_real, porcentaje_com,
            monto_comision, monto_por_pagar, monto_por_pagar,
            estado_inicial, f_str, h_str, operario_nombre
        ))
        cxp_id = cur.lastrowid

        # Recalcular saldos del proveedor inmediatamente
        recalcular_saldo_proveedor(prov_id, conn=conn)

        if cerrar_conn:
            conn.commit()

        return {
            "id": cxp_id,
            "cxp_id": cxp_id,
            "proveedor_id": prov_id,
            "proveedor_nombre": prov_nom,
            "precio_venta": subtotal_real,
            "porcentaje_comision": porcentaje_com,
            "monto_comision": monto_comision,
            "monto_por_pagar": monto_por_pagar
        }
    finally:
        if cerrar_conn and conn:
            conn.close()


def revertir_cxp_por_venta_anulada(
    id_venta: int,
    motivo: str = "Anulación de venta",
    usuario_admin: str = "Administrador",
    conn: Optional[sqlite3.Connection] = None,
    *args,
    **kwargs
) -> Dict[str, Any]:
    """
    Anula de forma atómica y trazable las cuentas por pagar vinculadas a una venta anulada:
    1. Localiza todos los registros en cuentas_por_pagar_proveedores asociados a id_venta.
    2. Para cada registro no anulado:
       - Marca estado = 'Anulada'.
       - Pone saldo_pendiente = 0.0.
    3. Recalcula inmediatamente el saldo acumulado y acumulados de cada proveedor afectado.
    """
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, proveedor_id, proveedor_nombre, precio_venta, monto_por_pagar, monto_pagado, saldo_pendiente, estado
            FROM cuentas_por_pagar_proveedores
            WHERE id_venta = ? AND estado != 'Anulada'
        """, (id_venta,))
        rows = cur.fetchall()

        if not rows:
            return {
                "ok": True,
                "exito": True,
                "id_venta": id_venta,
                "afectados": 0,
                "detalles": [],
                "proveedores": []
            }

        proveedores_afectados = set()
        detalles_anulados = []

        for r in rows:
            c_id = r[0]
            prov_id = r[1]
            prov_nom = r[2]
            precio_v = float(r[3] or 0.0)
            monto_por_pagar = float(r[4] or 0.0)
            monto_pagado = float(r[5] or 0.0)
            saldo_pendiente = float(r[6] or 0.0)
            estado_anterior = str(r[7] or "")

            proveedores_afectados.add(prov_id)
            detalles_anulados.append({
                "cxp_id": c_id,
                "proveedor_id": prov_id,
                "proveedor_nombre": prov_nom,
                "precio_venta": precio_v,
                "monto_por_pagar": monto_por_pagar,
                "monto_pagado": monto_pagado,
                "saldo_pendiente": saldo_pendiente,
                "estado_anterior": estado_anterior
            })

            cur.execute("""
                UPDATE cuentas_por_pagar_proveedores
                SET estado = 'Anulada',
                    saldo_pendiente = 0.0
                WHERE id = ?
            """, (c_id,))

        for prov_id in proveedores_afectados:
            recalcular_saldo_proveedor(prov_id, conn=conn)

        if cerrar_conn:
            conn.commit()

        return {
            "ok": True,
            "exito": True,
            "id_venta": id_venta,
            "afectados": len(detalles_anulados),
            "detalles": detalles_anulados,
            "proveedores": list(proveedores_afectados)
        }
    except Exception as e:
        if cerrar_conn and conn:
            conn.rollback()
        raise e
    finally:
        if cerrar_conn and conn:
            conn.close()


def sincronizar_cxp_ventas_anuladas(conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """
    Rutina de reconciliación automática:
    Detecta cuentas por pagar donde la venta asociada ya está en estado 'Anulada' en la tabla ventas,
    pero la cuenta por pagar todavía no se ha marcado como 'Anulada'.
    Las anula y recalcula el saldo de los proveedores.
    """
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT cxp.id_venta
            FROM cuentas_por_pagar_proveedores cxp
            JOIN ventas v ON cxp.id_venta = v.id_venta
            WHERE v.estado = 'Anulada' AND cxp.estado != 'Anulada'
        """)
        ventas_anuladas = [r[0] for r in cur.fetchall()]

        total_cuentas = 0
        for vid in ventas_anuladas:
            res = revertir_cxp_por_venta_anulada(
                id_venta=vid,
                motivo="Sincronización por venta anulada",
                conn=conn
            )
            total_cuentas += res.get("afectados", 0)

        if cerrar_conn:
            conn.commit()

        return {
            "ok": True,
            "exito": True,
            "ventas_reconciliadas": len(ventas_anuladas),
            "cuentas_anuladas": total_cuentas
        }
    except Exception as e:
        if cerrar_conn and conn:
            conn.rollback()
        raise e
    finally:
        if cerrar_conn and conn:
            conn.close()


def obtener_resumen_proveedores(
    filtro: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    solo_activos: bool = False,
    *args,
    **kwargs
) -> List[Dict[str, Any]]:
    """
    Retorna la lista de proveedores con sus métricas acumuladas:
    - ID, Nombre, NIT, Teléfono
    - Saldo Pendiente real
    - Total de Ventas asociadas
    - Total de Comisiones descontadas
    - Total Liquidado / Pagado
    """
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    try:
        cur = conn.cursor()
        try:
            sincronizar_cxp_ventas_anuladas(conn=conn)
        except Exception as e_sync:
            print(f"Aviso en sincronizar_cxp_ventas_anuladas: {e_sync}")

        query = """
            SELECT 
                p.id, 
                p.nombre, 
                COALESCE(p.documento_nit, '') as nit,
                COALESCE(p.telefono, '') as telefono,
                COALESCE(p.saldo_acumulado, 0.0) as saldo_acumulado,
                COALESCE(p.total_ventas, 0.0) as total_ventas,
                COALESCE(p.total_comisiones, 0.0) as total_comisiones,
                COALESCE(p.total_pagado, 0.0) as total_pagado
            FROM proveedores p
            WHERE 1=1
        """
        params = []
        cur.execute("PRAGMA table_info(proveedores)")
        p_cols = {c[1] for c in cur.fetchall()}
        if solo_activos:
            if "estado" in p_cols:
                query += " AND (p.estado = 'Activo' OR p.estado IS NULL)"
            elif "activo" in p_cols:
                query += " AND (p.activo = 1 OR p.activo IS NULL)"

        if filtro:
            termino = f"%{str(filtro).strip().lower()}%"
            query += " AND (LOWER(p.nombre) LIKE ? OR LOWER(COALESCE(p.documento_nit, '')) LIKE ? OR LOWER(COALESCE(p.telefono, '')) LIKE ?)"
            params.extend([termino, termino, termino])

        query += " ORDER BY p.nombre ASC"
        cur.execute(query, params)
        rows = cur.fetchall()

        resultado = []
        for r in rows:
            p_id = r[0]
            # Validar y asegurar recálculo exacto
            rec = recalcular_saldo_proveedor(p_id, conn=conn)
            resultado.append({
                "id": p_id,
                "nombre": r[1],
                "documento_nit": r[2],
                "telefono": r[3],
                "saldo_pendiente": rec["saldo_pendiente"],
                "total_ventas": rec["total_ventas"],
                "total_comisiones": rec["total_comisiones"],
                "total_pagado": rec["total_pagado"]
            })
        return resultado
    finally:
        if cerrar_conn and conn:
            conn.close()


def obtener_detalle_cuentas_proveedor(
    proveedor_id: int,
    solo_pendientes: bool = False,
    conn: Optional[sqlite3.Connection] = None
) -> List[Dict[str, Any]]:
    """
    Retorna el desglose de todas las ventas de servicios vinculadas a un proveedor específico.
    Permite auditar fecha, referencia de venta, servicio, precio real, comisión y saldo restante.
    """
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        query = """
            SELECT 
                id, proveedor_id, proveedor_nombre, id_venta, numero_venta,
                codigo_servicio, nombre_servicio, precio_venta, porcentaje_comision,
                monto_comision, monto_por_pagar, monto_pagado, saldo_pendiente,
                estado, fecha, hora, usuario
            FROM cuentas_por_pagar_proveedores
            WHERE proveedor_id = ?
        """
        params = [proveedor_id]
        if solo_pendientes:
            query += " AND estado = 'Pendiente' AND saldo_pendiente > 0"
        query += " ORDER BY id DESC"
        cur.execute(query, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        if cerrar_conn and conn:
            conn.close()


def obtener_historial_liquidaciones_proveedor(
    proveedor_id: Optional[int] = None,
    mes_anio: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> List[Dict[str, Any]]:
    """
    Retorna el historial inmutable de pagos y liquidaciones realizadas a proveedores.
    Este historial se conserva de forma permanente aun cuando el saldo del proveedor llegue a $0.
    """
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        query = """
            SELECT 
                id, numero_recibo, proveedor_id, proveedor_nombre,
                monto_liquidado, saldo_anterior, saldo_restante,
                tipo_pago, metodo_pago, referencia, fecha, hora,
                mes_anio, usuario, observaciones, estado
            FROM liquidaciones_proveedores
            WHERE 1=1
        """
        params = []
        if proveedor_id:
            query += " AND proveedor_id = ?"
            params.append(proveedor_id)
        if mes_anio and mes_anio != "Todos":
            query += " AND mes_anio = ?"
            params.append(mes_anio)

        query += " ORDER BY id DESC"
        cur.execute(query, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        if cerrar_conn and conn:
            conn.close()


def liquidar_proveedor_db(
    proveedor_id: int,
    monto: Optional[float] = None,
    metodo_pago: str = "Efectivo",
    referencia: str = "",
    usuario: str = "Administrador",
    observaciones: str = "",
    sesion_caja_id: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Registra el pago real (total o abono parcial) a un proveedor:
    1. Valida que el monto sea positivo y no exceda el saldo pendiente actual.
    2. Aplica el pago en orden FIFO a las cuentas por pagar pendientes.
    3. Registra la liquidación permanente en liquidaciones_proveedores e historial_liquidaciones.
    4. Registra el gasto contable en gastos y el egreso financiero en movimientos_caja / movimientos_financieros.
    5. Actualiza el saldo pendiente del proveedor.
    6. Garantiza idempotencia y bloqueo frente a clics repetidos.
    """
    global _PAGOS_EN_PROCESO

    # Soportar alias de parámetros para máxima compatibilidad
    if monto is None:
        monto = kwargs.get("monto_abono", 0.0)
    if not referencia:
        referencia = kwargs.get("referencia_comprobante", "")
    if usuario == "Administrador" and "usuario_nombre" in kwargs:
        usuario = kwargs["usuario_nombre"]
    if not observaciones:
        observaciones = kwargs.get("notas", "")

    if proveedor_id in _PAGOS_EN_PROCESO:
        return {
            "exito": False,
            "ok": False,
            "mensaje": "Ya existe una liquidación en proceso para este proveedor. Por favor espere."
        }

    _PAGOS_EN_PROCESO.add(proveedor_id)
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    try:
        cur = conn.cursor()

        # 1. Validar proveedor y saldo pendiente
        cur.execute("SELECT id, nombre, COALESCE(saldo_acumulado, 0.0) FROM proveedores WHERE id = ?", (proveedor_id,))
        prov_row = cur.fetchone()
        if not prov_row:
            return {
                "exito": False,
                "ok": False,
                "mensaje": f"Proveedor con ID {proveedor_id} no encontrado."
            }

        prov_nom = str(prov_row[1])
        saldo_actual = float(prov_row[2] or 0.0)

        # Recálculo fresco para máxima consistencia
        rec = recalcular_saldo_proveedor(proveedor_id, conn=conn)
        saldo_actual = rec["saldo_pendiente"]

        try:
            monto_flt = round(float(monto or 0.0), 2)
        except (ValueError, TypeError):
            monto_flt = 0.0

        if monto_flt <= 0:
            return {
                "exito": False,
                "ok": False,
                "mensaje": "El monto a liquidar debe ser estrictamente mayor a 0."
            }
        if monto_flt > (saldo_actual + 0.01):
            return {
                "exito": False,
                "ok": False,
                "mensaje": f"El monto a pagar (${monto_flt:,.0f}) es superior al saldo pendiente actual (${saldo_actual:,.0f})."
            }

        # Determinar tipo de pago (Total o Abono Parcial)
        saldo_restante = max(0.0, round(saldo_actual - monto_flt, 2))
        tipo_pago = "Total" if saldo_restante == 0.0 else "Abono Parcial"

        ahora = datetime.now()
        fecha_str = ahora.strftime("%Y-%m-%d")
        hora_str = ahora.strftime("%H:%M:%S")
        mes_anio = ahora.strftime("%m-%Y")

        # Generar número correlativo de recibo
        cur.execute("SELECT COUNT(id) FROM liquidaciones_proveedores")
        conteo = cur.fetchone()[0] or 0
        numero_recibo = f"LIQ-PROV-{conteo + 1:05d}"

        # 2. Distribuir el pago entre las cuentas por pagar pendientes (FIFO)
        cur.execute("""
            SELECT id, monto_por_pagar, monto_pagado, saldo_pendiente
            FROM cuentas_por_pagar_proveedores
            WHERE proveedor_id = ? AND estado != 'Pagada' AND estado != 'Anulada'
            ORDER BY id ASC
        """, (proveedor_id,))
        cuentas_pendientes = cur.fetchall()

        monto_por_distribuir = monto_flt
        for c_id, c_tot, c_pag, c_saldo in cuentas_pendientes:
            if monto_por_distribuir <= 0:
                break
            c_saldo_flt = float(c_saldo)
            if c_saldo_flt <= 0:
                continue

            abono_cuenta = min(monto_por_distribuir, c_saldo_flt)
            nuevo_pagado = round(float(c_pag) + abono_cuenta, 2)
            nuevo_saldo = round(c_saldo_flt - abono_cuenta, 2)
            nuevo_estado = "Pagada" if nuevo_saldo == 0.0 else "Abonada"

            cur.execute("""
                UPDATE cuentas_por_pagar_proveedores
                SET monto_pagado = ?, saldo_pendiente = ?, estado = ?
                WHERE id = ?
            """, (nuevo_pagado, nuevo_saldo, nuevo_estado, c_id))

            monto_por_distribuir = round(monto_por_distribuir - abono_cuenta, 2)

        # 3. Registrar en liquidaciones_proveedores
        cur.execute("""
            INSERT INTO liquidaciones_proveedores (
                numero_recibo, proveedor_id, proveedor_nombre, monto_liquidado,
                saldo_anterior, saldo_restante, tipo_pago, metodo_pago, referencia,
                fecha, hora, mes_anio, usuario, observaciones, estado
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Aplicada')
        """, (
            numero_recibo, proveedor_id, prov_nom, monto_flt,
            saldo_actual, saldo_restante, tipo_pago, metodo_pago,
            referencia, fecha_str, hora_str, mes_anio, usuario, observaciones
        ))
        id_liq = cur.lastrowid

        # 4. Registrar en historial_liquidaciones (compatibilidad con nómina histórica)
        try:
            cur.execute("""
                INSERT INTO historial_liquidaciones (
                    tipo, persona_id, nombre_persona, monto, fecha, mes_anio
                ) VALUES ('Proveedor', ?, ?, ?, ?, ?)
            """, (proveedor_id, prov_nom, monto_flt, f"{fecha_str} {hora_str}", mes_anio))
        except Exception as e_hist:
            print(f"Aviso registrando en historial_liquidaciones: {e_hist}")

        # 5. Registrar en gastos de contabilidad (Categoría Proveedores)
        try:
            cur.execute("""
                INSERT INTO gastos (
                    concepto, valor, fecha, hora, metodo_pago, categoria, clasificacion,
                    descripcion, estado, usuario, proveedor, comprobante, observaciones
                ) VALUES (?, ?, ?, ?, ?, 'Proveedores', 'Cuentas por Pagar', ?, 'Pagado', ?, ?, ?, ?)
            """, (
                f"Pago a Proveedor - {prov_nom}",
                monto_flt,
                fecha_str,
                hora_str,
                metodo_pago,
                f"Liquidación de servicios/comisiones {tipo_pago}",
                usuario,
                prov_nom,
                numero_recibo,
                observaciones or referencia
            ))
        except Exception as e_gasto:
            print(f"Aviso registrando gasto de proveedor: {e_gasto}")

        # 6. Integración contable con Caja y Bancos
        cuenta_afectada = "CAJA_FISICA" if metodo_pago == "Efectivo" else "BANCO_TRANSFERENCIA"
        try:
            # Obtener sesión de caja abierta si no fue provista y el pago es en efectivo
            s_caja_id = sesion_caja_id
            if not s_caja_id and metodo_pago == "Efectivo":
                cur.execute("SELECT id FROM sesiones_caja WHERE estado = 'Abierta' ORDER BY id DESC LIMIT 1")
                s_row = cur.fetchone()
                if s_row:
                    s_caja_id = s_row[0]
                else:
                    cur.execute("SELECT id FROM sesiones_caja ORDER BY id DESC LIMIT 1")
                    s_last = cur.fetchone()
                    if s_last:
                        s_caja_id = s_last[0]
                    else:
                        cur.execute(
                            "INSERT INTO sesiones_caja (fecha_apertura, hora_apertura, usuario_apertura, estado) VALUES (?, ?, ?, 'Abierta')",
                            (fecha_str, hora_str, usuario)
                        )
                        s_caja_id = cur.lastrowid

            # Registrar en movimientos_financieros
            cur.execute("""
                INSERT INTO movimientos_financieros (
                    fecha, hora, tipo, concepto, monto, metodo_pago,
                    cuenta_afectada, usuario, referencia_origen, sesion_caja_id, estado, observaciones
                ) VALUES (?, ?, 'EGRESO_PROVEEDOR', ?, ?, ?, ?, ?, ?, ?, 'Activo', ?)
            """, (
                fecha_str, hora_str, f"Pago a Proveedor {prov_nom} ({numero_recibo})",
                monto_flt, metodo_pago, cuenta_afectada, usuario,
                numero_recibo, s_caja_id, observaciones
            ))

            # Si es en Efectivo y hay sesión de caja abierta, registrar egreso en movimientos_caja
            if metodo_pago == "Efectivo" and s_caja_id:
                cur.execute("""
                    INSERT INTO movimientos_caja (
                        sesion_caja_id, fecha, hora, tipo, monto, usuario,
                        terminal, referencia_id, descripcion
                    ) VALUES (?, ?, ?, 'EGRESO', ?, ?, 'Terminal-1', ?, ?)
                """, (
                    s_caja_id, fecha_str, hora_str, monto_flt, usuario,
                    numero_recibo, f"Pago a proveedor: {prov_nom}"
                ))
        except Exception as e_caja:
            print(f"Aviso registrando movimiento de caja/financiero: {e_caja}")

        # 7. Actualizar saldo acumulado del proveedor
        recalcular_saldo_proveedor(proveedor_id, conn=conn)

        if cerrar_conn:
            conn.commit()

        return {
            "exito": True,
            "ok": True,
            "id": id_liq,
            "id_liquidacion": id_liq,
            "numero_recibo": numero_recibo,
            "proveedor_id": proveedor_id,
            "proveedor_nombre": prov_nom,
            "monto_pagado": monto_flt,
            "monto_liquidado": monto_flt,
            "saldo_anterior": saldo_actual,
            "saldo_restante": saldo_restante,
            "cuentas_afectadas": len(cuentas_pendientes),
            "tipo_pago": tipo_pago,
            "metodo_pago": metodo_pago,
            "fecha": fecha_str,
            "hora": hora_str
        }
    except Exception as exc:
        if conn and cerrar_conn:
            conn.rollback()
        return {
            "exito": False,
            "ok": False,
            "mensaje": f"Error inesperado al liquidar proveedor: {str(exc)}"
        }
    finally:
        _PAGOS_EN_PROCESO.discard(proveedor_id)
        if cerrar_conn and conn:
            conn.close()


def revertir_liquidacion_proveedor_db(
    liquidacion_id: int,
    motivo: str = "Ajuste de liquidación",
    usuario: str = "Administrador",
    conn: Optional[sqlite3.Connection] = None,
    *args,
    **kwargs
) -> Dict[str, Any]:
    """
    Procedimiento controlado de reversión de una liquidación histórica a proveedor.
    Restaura las cuentas por pagar que fueron afectadas y genera el movimiento de contrapartida.
    """
    if "usuario_nombre" in kwargs and usuario == "Administrador":
        usuario = kwargs["usuario_nombre"]
    if "motivo_reversion" in kwargs and motivo == "Ajuste de liquidación":
        motivo = kwargs["motivo_reversion"]

    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, numero_recibo, proveedor_id, proveedor_nombre, monto_liquidado,
                   metodo_pago, estado
            FROM liquidaciones_proveedores
            WHERE id = ?
        """, (liquidacion_id,))
        liq_row = cur.fetchone()
        if not liq_row:
            return {
                "ok": False,
                "exito": False,
                "success": False,
                "mensaje": f"Liquidación con ID {liquidacion_id} no encontrada."
            }

        if liq_row[6] == "Revertida":
            return {
                "ok": False,
                "exito": False,
                "success": False,
                "mensaje": "Esta liquidación ya fue revertida previamente."
            }

        prov_id = liq_row[2]
        prov_nom = liq_row[3]
        monto_flt = float(liq_row[4])
        metodo = str(liq_row[5])
        recibo = str(liq_row[1])

        # Marcar liquidación como revertida
        cur.execute("""
            UPDATE liquidaciones_proveedores
            SET estado = 'Revertida',
                observaciones = COALESCE(observaciones, '') || ' | Revertida por ' || ? || ': ' || ?
            WHERE id = ?
        """, (usuario, motivo, liquidacion_id))

        # Reabrir cuentas por pagar del proveedor afectadas en orden inverso (LIFO)
        cur.execute("""
            SELECT id, monto_por_pagar, monto_pagado, saldo_pendiente, id_venta
            FROM cuentas_por_pagar_proveedores
            WHERE proveedor_id = ? AND monto_pagado > 0
            ORDER BY id DESC
        """, (prov_id,))
        cuentas_pagadas = cur.fetchall()

        monto_a_restaurar = monto_flt
        for c_id, c_tot, c_pag, c_saldo, c_id_venta in cuentas_pagadas:
            if monto_a_restaurar <= 0:
                break
            c_pag_flt = float(c_pag)
            restaurar_en_cuenta = min(monto_a_restaurar, c_pag_flt)
            nuevo_pagado = round(c_pag_flt - restaurar_en_cuenta, 2)
            nuevo_saldo = round(float(c_saldo) + restaurar_en_cuenta, 2)

            # Si la venta origen fue anulada, la cuenta por pagar debe quedar en Anulada con saldo 0
            cur.execute("SELECT estado FROM ventas WHERE id_venta = ?", (c_id_venta,))
            v_row = cur.fetchone()
            if v_row and str(v_row[0]).strip().lower() == "anulada":
                nuevo_estado = "Anulada"
                nuevo_saldo = 0.0
            else:
                nuevo_estado = "Pendiente" if nuevo_pagado == 0.0 else "Abonada"

            cur.execute("""
                UPDATE cuentas_por_pagar_proveedores
                SET monto_pagado = ?, saldo_pendiente = ?, estado = ?
                WHERE id = ?
            """, (nuevo_pagado, nuevo_saldo, nuevo_estado, c_id))

            monto_a_restaurar = round(monto_a_restaurar - restaurar_en_cuenta, 2)

        # Registrar contrapartida en movimientos financieros
        ahora = datetime.now()
        f_str = ahora.strftime("%Y-%m-%d")
        h_str = ahora.strftime("%H:%M:%S")
        cuenta_afectada = "CAJA_FISICA" if metodo == "Efectivo" else "BANCO_TRANSFERENCIA"

        cur.execute("""
            INSERT INTO movimientos_financieros (
                fecha, hora, tipo, concepto, monto, metodo_pago,
                cuenta_afectada, usuario, referencia_origen, estado, observaciones
            ) VALUES (?, ?, 'REVERSO_PAGO_PROVEEDOR', ?, ?, ?, ?, ?, ?, 'Activo', ?)
        """, (
            f_str, h_str, f"Reverso pago proveedor {prov_nom} ({recibo})",
            monto_flt, metodo, cuenta_afectada, usuario,
            recibo, f"Motivo: {motivo}"
        ))

        # Marcar gasto contable como Anulado si existe
        try:
            cur.execute("""
                UPDATE gastos
                SET estado = 'Anulado',
                    observaciones = COALESCE(observaciones, '') || ' | Revertido por ' || ?
                WHERE comprobante = ?
            """, (usuario, recibo))
        except Exception as e_gasto:
            print(f"Aviso actualizando gasto de liquidación revertida: {e_gasto}")

        # Recalcular saldos del proveedor
        rec = recalcular_saldo_proveedor(prov_id, conn=conn)

        if cerrar_conn:
            conn.commit()

        return {
            "ok": True,
            "exito": True,
            "success": True,
            "liquidacion_id": liquidacion_id,
            "proveedor_id": prov_id,
            "monto_revertido": monto_flt,
            "nuevo_saldo": rec["saldo_pendiente"]
        }
    except Exception as ex:
        if conn and cerrar_conn:
            conn.rollback()
        return {
            "ok": False,
            "exito": False,
            "success": False,
            "mensaje": str(ex),
            "error": str(ex)
        }
    finally:
        if cerrar_conn and conn:
            conn.close()
