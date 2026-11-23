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
    from client.api_client import api
except ImportError:
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    try:
        from client.api_client import api
    except ImportError:
        api = None

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

# Caché en memoria para persistencia de proveedores ante caídas de red o desconexiones
_MEMORIA_PROVEEDORES_CACHE: List[Dict[str, Any]] = []


def normalizar_fecha(txt: Optional[str]) -> Optional[str]:
    """
    Normaliza formatos de fecha DD/MM/YYYY, YYYY-MM-DD, DD-MM-YYYY, YYYY/MM/DD a YYYY-MM-DD.
    Garantiza una fecha ISO válida para almacenamiento y consultas SQL.
    Retorna None si la fecha no es válida.
    """
    if not txt:
        return None
    txt = str(txt).strip()
    if len(txt) >= 10 and txt[10:11] in (" ", "T"):
        txt = txt[:10].strip()

    candidata = None
    if "/" in txt:
        partes = txt.split("/")
        if len(partes) == 3:
            if len(partes[2]) == 4:
                candidata = f"{partes[2]}-{partes[1].zfill(2)}-{partes[0].zfill(2)}"
            elif len(partes[0]) == 4:
                candidata = f"{partes[0]}-{partes[1].zfill(2)}-{partes[2].zfill(2)}"
    elif "-" in txt:
        partes = txt.split("-")
        if len(partes) == 3:
            if len(partes[0]) == 4:
                candidata = f"{partes[0]}-{partes[1].zfill(2)}-{partes[2].zfill(2)}"
            elif len(partes[2]) == 4:
                candidata = f"{partes[2]}-{partes[1].zfill(2)}-{partes[0].zfill(2)}"

    if candidata:
        try:
            dt = datetime.strptime(candidata, "%Y-%m-%d")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return None

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(txt[:10], fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def normalizar_hora(hora_str: str) -> str:
    """Normaliza hora a formato HH:MM:SS de 24 horas."""
    if not hora_str:
        return datetime.now().strftime("%H:%M:%S")
    h = str(hora_str).strip()
    try:
        for fmt in ("%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p"):
            try:
                dt = datetime.strptime(h, fmt)
                return dt.strftime("%H:%M:%S")
            except ValueError:
                continue
    except Exception:
        pass
    if len(h) == 5 and ":" in h:
        return f"{h}:00"
    return h[:8] if len(h) >= 8 else datetime.now().strftime("%H:%M:%S")


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

    if not conn:
        return list(_MEMORIA_PROVEEDORES_CACHE)

    try:
        cur = conn.cursor()
        # Obtener nombre y datos actuales del proveedor
        cur.execute("SELECT id, nombre, COALESCE(saldo_acumulado, 0.0) FROM proveedores WHERE id = ?", (proveedor_id,))
        p_row = cur.fetchone()
        p_nom = str(p_row[1]).strip() if p_row and p_row[1] else ""

        # Sumar saldos de cuentas por pagar no anuladas con coincidencia flexible de ID y nombre
        cur.execute("""
            SELECT 
                COUNT(id),
                COALESCE(SUM(CASE WHEN estado != 'Anulada' THEN precio_venta ELSE 0.0 END), 0.0),
                COALESCE(SUM(CASE WHEN estado != 'Anulada' THEN monto_comision ELSE 0.0 END), 0.0),
                COALESCE(SUM(CASE WHEN estado != 'Anulada' THEN monto_pagado ELSE 0.0 END), 0.0),
                COALESCE(SUM(CASE WHEN estado != 'Anulada' THEN saldo_pendiente ELSE 0.0 END), 0.0)
            FROM cuentas_por_pagar_proveedores
            WHERE (proveedor_id = ? OR CAST(proveedor_id AS TEXT) = ? OR CAST(proveedor_id AS TEXT) LIKE ? OR ((proveedor_id IS NULL OR proveedor_id = 0 OR proveedor_id = '') AND LOWER(proveedor_nombre) = LOWER(?)))
        """, (proveedor_id, str(proveedor_id), f"{proveedor_id} - %", p_nom))
        row = cur.fetchone()
        conteo_cxp = row[0] or 0
        tot_v = float(row[1] or 0.0)
        tot_c = float(row[2] or 0.0)
        tot_p = float(row[3] or 0.0)
        saldo_p = float(row[4] or 0.0)

        # Si la API del servidor central está disponible, es la fuente autoritativa en modo cliente/servidor
        if api is not None and api.esta_disponible():
            try:
                resp = api.get(f"/proveedores/{proveedor_id}", timeout=3.0)
                if resp.status_code == 200:
                    d_api = resp.json()
                    saldo_p = float(d_api.get("saldo_acumulado") or d_api.get("saldo_pendiente") or 0.0)
                    tot_v = float(d_api.get("total_ventas") or 0.0)
                    tot_c = float(d_api.get("total_comisiones") or 0.0)
                    tot_p = float(d_api.get("total_pagado") or 0.0)
                    # Si el servidor reporta saldo cero o liquidado, sincronizar estado local para erradicar saldos fantasmas
                    if saldo_p <= 0.009:
                        cur.execute("""
                            UPDATE cuentas_por_pagar_proveedores
                            SET saldo_pendiente = 0.0, estado = 'Pagada'
                            WHERE (proveedor_id = ? OR CAST(proveedor_id AS TEXT) = ? OR ((proveedor_id IS NULL OR proveedor_id = 0) AND LOWER(proveedor_nombre) = LOWER(?)))
                              AND estado != 'Anulada'
                        """, (proveedor_id, str(proveedor_id), p_nom))
            except Exception:
                pass
        elif conteo_cxp == 0 and p_row and float(p_row[2] or 0.0) > 0:
            # Modo Offline: si el proveedor no tiene cuentas por pagar registradas pero ya tenía saldo acumulado previo (saldo legacy), descontar liquidaciones
            try:
                cur.execute("""
                    SELECT COALESCE(SUM(monto_liquidado), 0.0)
                    FROM liquidaciones_proveedores
                    WHERE (proveedor_id = ? OR CAST(proveedor_id AS TEXT) = ? OR ((proveedor_id IS NULL OR proveedor_id = 0) AND LOWER(proveedor_nombre) = LOWER(?)))
                      AND estado != 'Anulada'
                """, (proveedor_id, str(proveedor_id), p_nom))
                tot_liq = float(cur.fetchone()[0] or 0.0)
                tot_p = max(tot_p, tot_liq)
                saldo_p = max(0.0, round(float(p_row[2]) - tot_liq, 2))
            except Exception:
                saldo_p = float(p_row[2])

        # Actualizar tabla proveedores
        cur.execute("PRAGMA table_info(proveedores)")
        cols_p = [c[1] for c in cur.fetchall()]
        if "total_ventas" in cols_p:
            cur.execute("""
                UPDATE proveedores
                SET saldo_acumulado = ?,
                    total_ventas = ?,
                    total_comisiones = ?,
                    total_pagado = ?
                WHERE id = ?
            """, (saldo_p, tot_v, tot_c, tot_p, proveedor_id))
        else:
            cur.execute("""
                UPDATE proveedores
                SET saldo_acumulado = ?
                WHERE id = ?
            """, (saldo_p, proveedor_id))

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

    if not conn:
        return list(_MEMORIA_PROVEEDORES_CACHE)

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

        item_id = detalle_item.get("item_id") or detalle_item.get("producto_id")
        p_row = None
        if item_id:
            cur.execute("""
                SELECT p.tipo_producto, p.proveedor_id, COALESCE(p.porcentaje_comision, 0.0), prov.nombre, COALESCE(p.costo, 0.0)
                FROM productos p
                LEFT JOIN proveedores prov ON (prov.id = p.proveedor_id OR prov.id = CAST(p.proveedor_id AS INTEGER))
                WHERE p.id = ?
            """, (item_id,))
            p_row = cur.fetchone()

        if not p_row and cod:
            cur.execute("""
                SELECT p.tipo_producto, p.proveedor_id, COALESCE(p.porcentaje_comision, 0.0), prov.nombre, COALESCE(p.costo, 0.0)
                FROM productos p
                LEFT JOIN proveedores prov ON (prov.id = p.proveedor_id OR prov.id = CAST(p.proveedor_id AS INTEGER))
                WHERE p.codigo = ? OR p.codigo = ? OR p.codigo_barras = ?
            """, (cod, cod.zfill(5), cod))
            p_row = cur.fetchone()

        if not p_row and nom:
            cur.execute("""
                SELECT p.tipo_producto, p.proveedor_id, COALESCE(p.porcentaje_comision, 0.0), prov.nombre, COALESCE(p.costo, 0.0)
                FROM productos p
                LEFT JOIN proveedores prov ON (prov.id = p.proveedor_id OR prov.id = CAST(p.proveedor_id AS INTEGER))
                WHERE LOWER(p.nombre) = LOWER(?)
            """, (nom,))
            p_row = cur.fetchone()

        if not p_row:
            # Si no está en BD local pero viene explícito en el payload
            raw_prov = detalle_item.get("proveedor_id")
            if raw_prov:
                try:
                    prov_id = int(str(raw_prov).split('-')[0].strip())
                    costo_p = float(detalle_item.get("costo_unitario") or detalle_item.get("costo") or 0.0)
                    pct_p = float(detalle_item.get("porcentaje_comision") or 0.0)
                    cur.execute("SELECT nombre FROM proveedores WHERE id = ?", (prov_id,))
                    p_nom_r = cur.fetchone()
                    prov_nom = str(p_nom_r[0] if p_nom_r else f"Proveedor #{prov_id}")
                    p_row = ("Fisico", prov_id, pct_p, prov_nom, costo_p)
                except Exception:
                    pass

        if not p_row:
            return None

        tipo_prod = str(p_row[0] or "Fisico").strip() if p_row else str(detalle_item.get("tipo_item") or "Fisico")
        prov_id_raw = p_row[1] if p_row else None
        prov_id = None
        if prov_id_raw is not None:
            try:
                prov_id = int(str(prov_id_raw).split('-')[0].strip())
            except Exception:
                prov_id = None
        porcentaje_com = float(p_row[2] or 0.0) if p_row else 0.0
        prov_nom = str(p_row[3] or "").strip() if p_row else ""
        costo_prod = float(p_row[4] or 0.0) if p_row else 0.0

        # Si en BD local no tenía proveedor_id asignado pero en el ítem vendido sí viene:
        if (not prov_id or prov_id <= 0) and detalle_item.get("proveedor_id"):
            try:
                raw_prov = detalle_item.get("proveedor_id")
                prov_id = int(str(raw_prov).split('-')[0].strip())
            except (ValueError, TypeError, Exception):
                prov_id = None

        if porcentaje_com <= 0 and detalle_item.get("porcentaje_comision"):
            try:
                porcentaje_com = float(detalle_item.get("porcentaje_comision"))
            except (ValueError, TypeError):
                pass

        if costo_prod <= 0 and (detalle_item.get("costo_unitario") or detalle_item.get("costo")):
            try:
                costo_prod = float(detalle_item.get("costo_unitario") or detalle_item.get("costo") or 0.0)
            except (ValueError, TypeError):
                pass

        # Aplica a cualquier producto o servicio que tenga un proveedor asignado
        if not prov_id or prov_id <= 0:
            return None

        # Si el proveedor no tiene nombre en la relación, buscar directamente
        if not prov_nom or prov_nom.startswith("Proveedor #"):
            cur.execute("SELECT nombre FROM proveedores WHERE id = ?", (prov_id,))
            p_nom_row = cur.fetchone()
            prov_nom = str(p_nom_row[0] if p_nom_row else f"Proveedor #{prov_id}")

        # Sincronizar el proveedor hacia productos en SQLite si estaba vacío
        if prov_id and cod:
            try:
                cur.execute("""
                    UPDATE productos 
                    SET proveedor_id = ? 
                    WHERE (codigo = ? OR id = ?) AND (proveedor_id IS NULL OR proveedor_id = '')
                """, (prov_id, cod, item_id or 0))
            except Exception:
                pass

        # Validar porcentaje de comisión (0 a 100%)
        porcentaje_com = max(0.0, min(100.0, porcentaje_com))

        # Cálculo de obligación a pagar al proveedor:
        # Prioridad 1: Costo unitario fijo pactado por unidad vendida (ej. Omara Sierra $12,000 COP)
        costo_unitario_efectivo = costo_prod
        if costo_unitario_efectivo <= 0:
            costo_unitario_efectivo = float(detalle_item.get("costo_unitario") or detalle_item.get("costo") or 0.0)

        if costo_unitario_efectivo > 0:
            monto_por_pagar = round(costo_unitario_efectivo * cant, 2)
            monto_comision = round(max(0.0, subtotal_real - monto_por_pagar), 2)
        elif porcentaje_com > 0:
            monto_comision = round(subtotal_real * (porcentaje_com / 100.0), 2)
            monto_por_pagar = round(max(0.0, subtotal_real - monto_comision), 2)
        else:
            monto_por_pagar = subtotal_real
            monto_comision = 0.0

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

    if not conn:
        return list(_MEMORIA_PROVEEDORES_CACHE)

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


def ajustar_cxp_por_edicion_venta(
    id_venta: int,
    nuevos_detalles: List[Dict[str, Any]],
    motivo: str = "Edición / Devolución parcial de venta",
    conn: Optional[sqlite3.Connection] = None
) -> Dict[str, Any]:
    """
    Ajusta proporcionalmente las obligaciones a proveedores cuando una venta es editada
    o se realiza una devolución parcial (ej. 5 unidades vendidas, 2 devueltas -> 3 unidades).
    - Preserva los montos ya pagados/liquidados al proveedor.
    - Recalcula el saldo_pendiente y el saldo_acumulado del proveedor de forma atómica.
    """
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    if not conn:
        return list(_MEMORIA_PROVEEDORES_CACHE)

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, proveedor_id, codigo_servicio, nombre_servicio,
                   monto_por_pagar, monto_pagado, saldo_pendiente, estado
            FROM cuentas_por_pagar_proveedores
            WHERE id_venta = ? AND estado != 'Anulada'
        """, (id_venta,))
        cxp_existentes = cur.fetchall()

        # Mapear nuevos detalles por código/nombre
        mapa_nuevos = {}
        for d in nuevos_detalles:
            k_cod = str(d.get("codigo_producto", d.get("item_codigo", d.get("codigo", "")))).strip()
            k_nom = str(d.get("nombre_producto", d.get("item_nombre", d.get("nombre", "")))).strip().lower()
            if k_cod:
                mapa_nuevos[k_cod] = d
            if k_nom:
                mapa_nuevos[k_nom] = d

        provs_afectados = set()
        ajustados = 0

        for c_id, p_id, c_cod, c_nom, m_pagar, m_pagado, s_pend, estado in cxp_existentes:
            c_cod_s = str(c_cod or "").strip()
            c_nom_s = str(c_nom or "").strip().lower()

            item_nuevo = mapa_nuevos.get(c_cod_s) or mapa_nuevos.get(c_nom_s)

            if item_nuevo is None:
                # El ítem fue devuelto en su totalidad
                cur.execute("""
                    UPDATE cuentas_por_pagar_proveedores
                    SET estado = 'Anulada',
                        saldo_pendiente = 0.0
                    WHERE id = ?
                """, (c_id,))
                provs_afectados.add(p_id)
                ajustados += 1
            else:
                # El ítem continúa, recalcular por la nueva cantidad
                nueva_cant = float(item_nuevo.get("cantidad", 1) or 1)
                costo_u = float(item_nuevo.get("costo_unitario", item_nuevo.get("costo", 0.0)) or 0.0)
                subtot_n = float(item_nuevo.get("subtotal", 0.0) or 0.0)

                if costo_u <= 0:
                    # Buscar costo en productos
                    cur.execute("SELECT COALESCE(costo, 0.0), COALESCE(porcentaje_comision, 0.0) FROM productos WHERE codigo = ?", (c_cod_s,))
                    p_info = cur.fetchone()
                    if p_info:
                        costo_u = float(p_info[0] or 0.0)
                        pct_c = float(p_info[1] or 0.0)
                    else:
                        pct_c = 0.0
                else:
                    pct_c = float(item_nuevo.get("porcentaje_comision", 0.0) or 0.0)

                if costo_u > 0:
                    nuevo_monto_pagar = round(costo_u * nueva_cant, 2)
                    nuevo_monto_com = max(0.0, round(subtot_n - nuevo_monto_pagar, 2))
                elif pct_c > 0:
                    nuevo_monto_com = round(subtot_n * (pct_c / 100.0), 2)
                    nuevo_monto_pagar = max(0.0, round(subtot_n - nuevo_monto_com, 2))
                else:
                    nuevo_monto_pagar = subtot_n
                    nuevo_monto_com = 0.0

                m_pagado_flt = float(m_pagado or 0.0)
                nuevo_saldo_pend = max(0.0, round(nuevo_monto_pagar - m_pagado_flt, 2))
                nuevo_estado = "Pagada" if nuevo_saldo_pend <= 0.0 else ("Abonada" if m_pagado_flt > 0 else "Pendiente")

                cur.execute("""
                    UPDATE cuentas_por_pagar_proveedores
                    SET precio_venta = ?,
                        monto_por_pagar = ?,
                        monto_comision = ?,
                        saldo_pendiente = ?,
                        estado = ?
                    WHERE id = ?
                """, (subtot_n, nuevo_monto_pagar, nuevo_monto_com, nuevo_saldo_pend, nuevo_estado, c_id))
                provs_afectados.add(p_id)
                ajustados += 1

        for pid in provs_afectados:
            recalcular_saldo_proveedor(pid, conn=conn)

        if cerrar_conn:
            conn.commit()

        return {
            "ok": True,
            "id_venta": id_venta,
            "ajustados": ajustados,
            "proveedores": list(provs_afectados)
        }
    except Exception as e:
        if cerrar_conn and conn:
            conn.rollback()
        raise e
    finally:
        if cerrar_conn and conn:
            conn.close()


def sincronizar_cxp_retroactivas(conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """
    Sincronización retroactiva completa de cuentas por pagar:
    1. Escanea detalle_ventas cruzado con ventas y productos/servicios.
    2. Identifica cualquier venta de un producto o servicio que pertenezca a un proveedor
       pero cuya cuenta por pagar no esté registrada en cuentas_por_pagar_proveedores.
    3. Si la venta está Anulada, crea el registro en estado 'Anulada' (saldo_pendiente = 0.0).
       Si la venta está activa/completada, crea el registro en estado 'Pendiente'.
    4. Sincroniza estados de cuentas existentes cuya venta figure como 'Anulada'.
    5. Recalcula los saldos de todos los proveedores afectados.
    """
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    if not conn:
        return list(_MEMORIA_PROVEEDORES_CACHE)

    try:
        cur = conn.cursor()
        
        # 1. Reconciliar cuentas existentes vinculadas a ventas anuladas
        try:
            sincronizar_cxp_ventas_anuladas(conn=conn)
        except Exception as e_anc:
            print(f"Aviso en reconciliación anuladas: {e_anc}")

        # 2. Localizar ítems de ventas con proveedor asignado sin registro en CXP
        cur.execute("PRAGMA table_info(detalle_ventas)")
        dv_cols = [c[1] for c in cur.fetchall()]
        col_id_v = "id_venta" if "id_venta" in dv_cols else "venta_id"
        col_cod = "codigo_producto" if "codigo_producto" in dv_cols else "codigo"
        col_nom = "nombre_producto" if "nombre_producto" in dv_cols else "nombre"
        col_sub = "subtotal" if "subtotal" in dv_cols else "total"
        col_cant = "cantidad" if "cantidad" in dv_cols else "cant"

        query_faltantes = f"""
            SELECT 
                dv.{col_id_v},
                COALESCE(v.fecha_venta, ''),
                COALESCE(v.hora_venta, '00:00:00'),
                COALESCE(v.estado, 'Completada'),
                COALESCE(v.operario, 'Administrador'),
                dv.{col_cod},
                dv.{col_nom},
                dv.{col_cant},
                dv.{col_sub},
                COALESCE(p.proveedor_id, ''),
                COALESCE(p.costo, 0.0),
                COALESCE(pr.nombre, 'Proveedor'),
                COALESCE(p.porcentaje_comision, 0.0)
            FROM detalle_ventas dv
            JOIN ventas v ON dv.{col_id_v} = v.id_venta
            LEFT JOIN productos p ON (LOWER(p.codigo) = LOWER(dv.{col_cod}) OR LOWER(p.nombre) = LOWER(dv.{col_nom}))
            LEFT JOIN proveedores pr ON (pr.id = p.proveedor_id OR pr.id = CAST(p.proveedor_id AS INTEGER) OR LOWER(pr.nombre) = LOWER(p.proveedor_id))
            WHERE p.proveedor_id IS NOT NULL
              AND p.proveedor_id != ''
              AND NOT EXISTS (
                  SELECT 1 FROM cuentas_por_pagar_proveedores cxp
                  WHERE cxp.id_venta = dv.{col_id_v}
                    AND (cxp.codigo_servicio = dv.{col_cod} OR cxp.nombre_servicio = dv.{col_nom})
              )
        """
        cur.execute(query_faltantes)
        faltantes = cur.fetchall()

        creadas = 0
        provs_afectados = set()

        for r in faltantes:
            v_id = r[0]
            f_v = str(r[1] or "")
            h_v = str(r[2] or "00:00:00")
            v_estado = str(r[3] or "Completada")
            op_v = str(r[4] or "Administrador")
            it_cod = str(r[5] or "")
            it_nom = str(r[6] or "")
            it_cant = float(r[7] or 1.0)
            it_sub = float(r[8] or 0.0)
            prov_id_raw = r[9]
            costo_unit = float(r[10] or 0.0)
            prov_nom = str(r[11] or "")
            pct_com = float(r[12] or 0.0)

            try:
                prov_id = int(str(prov_id_raw).split("-")[0].strip())
            except Exception:
                continue

            provs_afectados.add(prov_id)
            num_v = f"V-{v_id:05d}"

            if costo_unit > 0:
                monto_pagar = costo_unit * it_cant
                monto_com = max(0.0, it_sub - monto_pagar)
            elif pct_com > 0:
                monto_com = it_sub * (pct_com / 100.0)
                monto_pagar = max(0.0, it_sub - monto_com)
            else:
                monto_com = 0.0
                monto_pagar = it_sub

            if v_estado == "Anulada":
                estado_cxp = "Anulada"
                saldo_pend = 0.0
            else:
                estado_cxp = "Pendiente"
                saldo_pend = monto_pagar

            cur.execute("""
                INSERT INTO cuentas_por_pagar_proveedores (
                    proveedor_id, proveedor_nombre, id_venta, numero_venta,
                    codigo_servicio, nombre_servicio, precio_venta, porcentaje_comision,
                    monto_comision, monto_por_pagar, monto_pagado, saldo_pendiente,
                    estado, fecha, hora, usuario
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, ?, ?, ?, ?, ?)
            """, (
                prov_id, prov_nom, v_id, num_v,
                it_cod, it_nom, it_sub, pct_com,
                monto_com, monto_pagar, saldo_pend,
                estado_cxp, f_v, h_v, op_v
            ))
            creadas += 1

        for pid in provs_afectados:
            recalcular_saldo_proveedor(pid, conn=conn)

        if cerrar_conn:
            conn.commit()

        return {"ok": True, "creadas": creadas, "proveedores_actualizados": len(provs_afectados)}
    except Exception as e:
        if cerrar_conn and conn:
            conn.rollback()
        return {"ok": False, "error": str(e)}
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

    if not conn:
        return list(_MEMORIA_PROVEEDORES_CACHE)

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
    global _MEMORIA_PROVEEDORES_CACHE
    if conn is None and api is not None:
        try:
            params = {}
            if filtro:
                params["search"] = filtro
            if solo_activos:
                params["activo"] = "true"
            resp = api.get("/proveedores", params=params, timeout=4.0)
            if resp.status_code == 200:
                provs = resp.json()
                res = []
                for p in provs:
                    saldo_val = float(p.get("saldo_acumulado") or p.get("saldo_pendiente") or 0.0)
                    doc_nit = p.get("documento_nit") or p.get("nit") or ""
                    res.append({
                        "id": p.get("id"),
                        "nombre": p.get("nombre") or "",
                        "nit": doc_nit,
                        "documento_nit": doc_nit,
                        "telefono": p.get("telefono") or "",
                        "saldo_acumulado": saldo_val,
                        "saldo_pendiente": saldo_val,
                        "total_ventas": float(p.get("total_ventas") or 0.0),
                        "total_comisiones": float(p.get("total_comisiones") or 0.0),
                        "total_pagado": float(p.get("total_pagado") or 0.0),
                        "estado": p.get("estado") or "Activo",
                    })

                # Reconciliar con cuentas por pagar de SQLite local para reflejar ventas pendientes de inmediato
                try:
                    sincronizar_cxp_retroactivas()
                    conn_loc = conectar_db()
                    if conn_loc:
                        cur_loc = conn_loc.cursor()
                        for item in res:
                            pid = item.get("id")
                            if pid:
                                cur_loc.execute("""
                                    SELECT 
                                        COALESCE(SUM(precio_venta), 0.0),
                                        COALESCE(SUM(monto_comision), 0.0),
                                        COALESCE(SUM(monto_pagado), 0.0),
                                        COALESCE(SUM(saldo_pendiente), 0.0)
                                    FROM cuentas_por_pagar_proveedores
                                    WHERE proveedor_id = ? AND estado != 'Anulada'
                                """, (pid,))
                                cxp_r = cur_loc.fetchone()
                                if cxp_r and float(cxp_r[3] or 0.0) > 0:
                                    loc_v = float(cxp_r[0] or 0.0)
                                    loc_c = float(cxp_r[1] or 0.0)
                                    loc_p = float(cxp_r[2] or 0.0)
                                    loc_s = float(cxp_r[3] or 0.0)
                                    if item["saldo_pendiente"] <= 0 or loc_s > item["saldo_pendiente"]:
                                        item["saldo_pendiente"] = loc_s
                                        item["saldo_acumulado"] = loc_s
                                        item["total_ventas"] = max(item["total_ventas"], loc_v)
                                        item["total_comisiones"] = max(item["total_comisiones"], loc_c)
                                        item["total_pagado"] = max(item["total_pagado"], loc_p)
                                # Asegurar que el proveedor esté registrado localmente en proveedores
                                try:
                                    cur_loc.execute("""
                                        INSERT OR REPLACE INTO proveedores (id, nombre, nit, telefono, saldo_acumulado, estado)
                                        VALUES (?, ?, ?, ?, ?, ?)
                                    """, (pid, item["nombre"], item.get("nit") or "", item.get("telefono") or "", item["saldo_acumulado"], item.get("estado", "Activo")))
                                except Exception:
                                    pass
                        conn_loc.commit()
                        conn_loc.close()
                except Exception as e_rec:
                    print(f"Aviso reconciliando saldos locales con API: {e_rec}")

                if res:
                    _MEMORIA_PROVEEDORES_CACHE = list(res)
                return res
        except Exception:
            pass

    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    if not conn:
        return list(_MEMORIA_PROVEEDORES_CACHE)

    try:
        cur = conn.cursor()
        try:
            sincronizar_cxp_retroactivas(conn=conn)
        except Exception as e_sync:
            print(f"Aviso en sincronizar_cxp_retroactivas: {e_sync}")

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
                "nit": r[2],
                "telefono": r[3],
                "saldo_pendiente": rec["saldo_pendiente"],
                "saldo_acumulado": rec["saldo_pendiente"],
                "total_ventas": rec["total_ventas"],
                "total_comisiones": rec["total_comisiones"],
                "total_pagado": rec["total_pagado"]
            })
        if not resultado and _MEMORIA_PROVEEDORES_CACHE:
            return list(_MEMORIA_PROVEEDORES_CACHE)
        if resultado:
            _MEMORIA_PROVEEDORES_CACHE = list(resultado)
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
    Combina registros del servidor central con los de SQLite local para garantizar que nunca
    aparezca en blanco si existen ventas o deudas registradas en cualquiera de los dos orígenes.
    """
    items_api = []
    if conn is None and api is not None:
        try:
            params = {}
            if solo_pendientes:
                params["estado"] = "Pendiente"
            resp = api.get(f"/proveedores/{proveedor_id}/cxp", params=params, timeout=5.0)
            if resp.status_code == 200:
                raw_cxp = resp.json()
                for c in raw_cxp:
                    m_pagar = float(c.get("monto_por_pagar") or c.get("monto_proveedor") or c.get("monto") or c.get("precio_venta") or 0.0)
                    m_pagado = float(c.get("monto_pagado") or 0.0)
                    est = str(c.get("estado", "Pendiente"))
                    if est.lower() == "pagada":
                        s_pend = 0.0
                        if m_pagado <= 0:
                            m_pagado = m_pagar
                    else:
                        s_pend = float(c.get("saldo_pendiente") if c.get("saldo_pendiente") is not None else max(0.0, m_pagar - m_pagado))
                    if solo_pendientes and (s_pend <= 0.009 or est.lower() == "pagada"):
                        continue
                    items_api.append({
                        "id": c.get("id"),
                        "proveedor_id": c.get("proveedor_id"),
                        "proveedor_nombre": c.get("proveedor_nombre", ""),
                        "id_venta": c.get("id_venta") or c.get("venta_id"),
                        "numero_venta": c.get("numero_venta") or (f"V-{c.get('id_venta') or c.get('venta_id') or 0:05d}"),
                        "codigo_servicio": c.get("codigo_servicio", ""),
                        "nombre_servicio": c.get("nombre_servicio") or c.get("concepto") or "Artículo",
                        "precio_venta": float(c.get("precio_venta") or 0.0),
                        "porcentaje_comision": float(c.get("porcentaje_comision") or 0.0),
                        "monto_comision": float(c.get("monto_comision") or 0.0),
                        "monto_por_pagar": m_pagar,
                        "monto_pagado": m_pagado,
                        "saldo_pendiente": s_pend,
                        "estado": c.get("estado", "Pendiente"),
                        "fecha": c.get("fecha") or c.get("fecha_venta", ""),
                        "fecha_venta": c.get("fecha_venta") or c.get("fecha", ""),
                        "hora": c.get("hora", ""),
                        "usuario": c.get("usuario", "Administrador")
                    })
        except Exception as e_api:
            print(f"Aviso consultando CXP vía API: {e_api}")

    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    try:
        try:
            sincronizar_cxp_retroactivas(conn=conn)
        except Exception as e_retro:
            print(f"Aviso sincronizando cxp retroactivas: {e_retro}")

        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Obtener nombre de proveedor para coincidencia flexible
        cur.execute("SELECT nombre FROM proveedores WHERE id = ?", (proveedor_id,))
        p_row = cur.fetchone()
        p_nom = str(p_row[0]).strip() if p_row and p_row[0] else ""

        query = """
            SELECT 
                id, proveedor_id, proveedor_nombre, id_venta, numero_venta,
                codigo_servicio, nombre_servicio, precio_venta, porcentaje_comision,
                monto_comision, monto_por_pagar, monto_pagado, saldo_pendiente,
                estado, fecha, hora, usuario
            FROM cuentas_por_pagar_proveedores
            WHERE (proveedor_id = ? OR CAST(proveedor_id AS TEXT) = ? OR CAST(proveedor_id AS TEXT) LIKE ? OR ((proveedor_id IS NULL OR proveedor_id = 0 OR proveedor_id = '') AND LOWER(proveedor_nombre) = LOWER(?)))
        """
        params = [proveedor_id, str(proveedor_id), f"{proveedor_id} - %", p_nom]
        if solo_pendientes:
            query += " AND estado = 'Pendiente' AND saldo_pendiente > 0"
        query += " ORDER BY id DESC"
        cur.execute(query, params)
        rows = cur.fetchall()
        items_locales = [dict(r) for r in rows]

        if not items_api:
            return items_locales

        # Fusionar items_api con items_locales evitando duplicados por (id_venta, codigo_servicio)
        claves_api = set()
        for it in items_api:
            v_ref = str(it.get("id_venta") or it.get("numero_venta") or "")
            c_ref = str(it.get("codigo_servicio") or it.get("nombre_servicio") or "").lower()
            if v_ref:
                claves_api.add((v_ref, c_ref))

        resultado = list(items_api)
        for loc in items_locales:
            v_ref = str(loc.get("id_venta") or loc.get("numero_venta") or "")
            c_ref = str(loc.get("codigo_servicio") or loc.get("nombre_servicio") or "").lower()
            if (v_ref, c_ref) not in claves_api:
                resultado.append(loc)

        return resultado
    finally:
        if cerrar_conn and conn:
            conn.close()
        if cerrar_conn and conn:
            conn.close()


def obtener_historial_liquidaciones_proveedor(
    proveedor_id: Optional[int] = None,
    mes_anio: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    fecha_especifica: Optional[str] = None,
    **kwargs
) -> List[Dict[str, Any]]:
    """
    Retorna el historial inmutable de pagos y liquidaciones realizadas a proveedores.
    Este historial se conserva de forma permanente aun cuando el saldo del proveedor llegue a $0.
    """
    if fecha_especifica is None and "fecha" in kwargs:
        fecha_especifica = kwargs.get("fecha")

    if conn is None and api is not None:
        try:
            params = {}
            if proveedor_id:
                params["proveedor_id"] = proveedor_id
            if fecha_especifica:
                params["fecha"] = fecha_especifica
            if fecha_inicio:
                params["fecha_inicio"] = fecha_inicio
            if fecha_fin:
                params["fecha_fin"] = fecha_fin
            if mes_anio and mes_anio != "Todos":
                params["mes_anio"] = mes_anio

            url_api = f"/proveedores/{proveedor_id}/liquidaciones" if proveedor_id else "/proveedores/liquidaciones"
            resp = api.get(url_api, params=params, timeout=5.0)
            if resp.status_code == 200:
                raw_l = resp.json()
                items = []
                for l in raw_l:
                    f_val = l.get("fecha") or l.get("fecha_pago") or ""
                    m_a = f_val[:7] if len(f_val) >= 7 else ""
                    # Filtro en memoria por si el backend remoto es versión previa
                    if fecha_especifica and f_val[:10] != fecha_especifica:
                        continue
                    if fecha_inicio and fecha_fin and not (fecha_inicio <= f_val[:10] <= fecha_fin):
                        continue
                    if mes_anio and mes_anio != "Todos":
                        m_norm = mes_anio
                        if len(m_norm) == 7 and m_norm[2] == "-":
                            m_norm = f"{m_norm[3:]}-{m_norm[:2]}"
                        if m_a != m_norm and mes_anio not in f_val:
                            continue

                    rec_num = l.get("numero_recibo") or f"LP-{l.get('id', 0):04d}"
                    u_nom = l.get("usuario") or l.get("usuario_nombre") or "Administrador"
                    ref_str = l.get("referencia") or l.get("referencia_comprobante") or l.get("comprobante") or ""
                    monto_val = float(l.get("monto_pagado") or l.get("monto_liquidado") or 0.0)

                    items.append({
                        "id": l.get("id"),
                        "numero_recibo": rec_num,
                        "proveedor_id": l.get("proveedor_id"),
                        "proveedor_nombre": l.get("proveedor_nombre", ""),
                        "monto_liquidado": monto_val,
                        "monto_pagado": monto_val,
                        "saldo_anterior": float(l.get("saldo_anterior") or 0.0),
                        "saldo_restante": float(l.get("saldo_restante") or 0.0),
                        "tipo_pago": l.get("tipo_pago", "Total"),
                        "metodo_pago": l.get("metodo_pago", "Efectivo"),
                        "referencia": ref_str,
                        "referencia_comprobante": ref_str,
                        "comprobante": ref_str,
                        "fecha": f_val,
                        "fecha_pago": f_val,
                        "hora": l.get("hora", ""),
                        "mes_anio": m_a,
                        "usuario": u_nom,
                        "usuario_nombre": u_nom,
                        "observaciones": l.get("observaciones", ""),
                        "estado": l.get("estado", "Aplicado")
                    })
                if items or proveedor_id or fecha_especifica or (fecha_inicio and fecha_fin):
                    return items
        except Exception as e_api:
            print(f"Aviso consultando liquidaciones vía API: {e_api}")

    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    try:
        try:
            sincronizar_cxp_retroactivas(conn=conn)
        except Exception as e_retro:
            print(f"Aviso sincronizando cxp retroactivas: {e_retro}")

        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("PRAGMA table_info(liquidaciones_proveedores)")
        cols_lp = {c[1] for c in cur.fetchall()}
        col_fecha_reg = "COALESCE(fecha_registro, created_at, fecha) as fecha_registro" if "fecha_registro" in cols_lp else ("created_at as fecha_registro" if "created_at" in cols_lp else "fecha as fecha_registro")
        col_dinero_mas = "COALESCE(dinero_de_mas, 0.0) as dinero_de_mas" if "dinero_de_mas" in cols_lp else "0.0 as dinero_de_mas"
        col_monto_aj = "COALESCE(monto_ajustado, monto_liquidado) as monto_ajustado" if "monto_ajustado" in cols_lp else "monto_liquidado as monto_ajustado"
        col_created_at = "created_at" if "created_at" in cols_lp else "fecha as created_at"

        query = f"""
            SELECT 
                id, numero_recibo, proveedor_id, proveedor_nombre,
                monto_liquidado, saldo_anterior, saldo_restante,
                tipo_pago, metodo_pago, referencia, fecha, hora,
                mes_anio, usuario, observaciones, estado,
                {col_fecha_reg},
                {col_dinero_mas},
                {col_monto_aj},
                {col_created_at}
            FROM liquidaciones_proveedores
            WHERE 1=1
        """
        params = []
        if proveedor_id:
            query += " AND (proveedor_id = ? OR CAST(proveedor_id AS TEXT) = ?)"
            params.extend([proveedor_id, str(proveedor_id)])
        if fecha_especifica:
            query += " AND (fecha = ? OR fecha LIKE ? OR SUBSTR(fecha, 1, 10) = ?)"
            params.extend([fecha_especifica, f"{fecha_especifica}%", fecha_especifica])
        elif fecha_inicio and fecha_fin:
            query += " AND SUBSTR(fecha, 1, 10) BETWEEN ? AND ?"
            params.extend([fecha_inicio, fecha_fin])
        elif fecha_inicio:
            query += " AND SUBSTR(fecha, 1, 10) >= ?"
            params.append(fecha_inicio)
        elif fecha_fin:
            query += " AND SUBSTR(fecha, 1, 10) <= ?"
            params.append(fecha_fin)

        if mes_anio and mes_anio != "Todos":
            m_norm = mes_anio
            if len(m_norm) == 7 and m_norm[2] == "-":
                m_norm = f"{m_norm[3:]}-{m_norm[:2]}"
            query += " AND (mes_anio = ? OR mes_anio = ? OR fecha LIKE ? OR fecha LIKE ?)"
            params.extend([mes_anio, m_norm, f"{m_norm}%", f"%{mes_anio}%"])

        query += " ORDER BY id DESC"
        cur.execute(query, params)
        rows = cur.fetchall()
        res_items = []
        for r in rows:
            d = dict(r)
            f_val = d.get("fecha") or ""
            u_nom = d.get("usuario") or "Administrador"
            ref_str = d.get("referencia") or ""
            m_val = float(d.get("monto_liquidado") or 0.0)
            dinero_sobrante = float(d.get("dinero_de_mas") or 0.0)
            m_neto = max(0.0, round(m_val - dinero_sobrante, 2))
            d["fecha_pago"] = f_val
            d["fecha_movimiento"] = f_val
            d["usuario_nombre"] = u_nom
            d["referencia_comprobante"] = ref_str
            d["comprobante"] = ref_str
            d["monto_pagado"] = m_val
            d["monto_neto"] = m_neto
            d["dinero_de_mas"] = dinero_sobrante
            d["monto_ajustado"] = float(d.get("monto_ajustado") or m_neto)
            d["fecha_registro"] = str(d.get("fecha_registro") or d.get("created_at") or f_val)
            res_items.append(d)
        return res_items
    finally:
        if cerrar_conn and conn:
            conn.close()


def _sincronizar_liquidacion_local_sqlite(cur, proveedor_id: int, monto_flt: float, metodo_pago: str, referencia: str, usuario: str, observaciones: str, numero_recibo: str):
    """Aplica el impacto de una liquidación procesada en servidor dentro de la base de datos local SQLite."""
    try:
        cur.execute("SELECT id, nombre, COALESCE(saldo_acumulado, 0.0) FROM proveedores WHERE id = ?", (proveedor_id,))
        p_r = cur.fetchone()
        prov_nom = p_r[1] if p_r else "Proveedor"

        cur.execute("""
            SELECT id, monto_por_pagar, monto_pagado, saldo_pendiente
            FROM cuentas_por_pagar_proveedores
            WHERE (proveedor_id = ? OR CAST(proveedor_id AS TEXT) = ? OR CAST(proveedor_id AS TEXT) LIKE ? OR ((proveedor_id IS NULL OR proveedor_id = 0 OR proveedor_id = '') AND LOWER(proveedor_nombre) = LOWER(?)))
              AND estado != 'Pagada' AND estado != 'Anulada'
            ORDER BY id ASC
        """, (proveedor_id, str(proveedor_id), f"{proveedor_id} - %", prov_nom))
        cuentas = cur.fetchall()

        remanente = monto_flt
        for c_id, c_tot, c_pag, c_saldo in cuentas:
            if remanente <= 0.001:
                break
            ab = min(remanente, float(c_saldo))
            n_pag = round(float(c_pag) + ab, 2)
            n_sal = round(float(c_saldo) - ab, 2)
            n_est = "Pagada" if n_sal <= 0.009 else "Abonada"
            cur.execute("UPDATE cuentas_por_pagar_proveedores SET monto_pagado = ?, saldo_pendiente = ?, estado = ? WHERE id = ?", (n_pag, n_sal, n_est, c_id))
            remanente = round(remanente - ab, 2)

        ahora = datetime.now()
        f_s = ahora.strftime("%Y-%m-%d")
        h_s = ahora.strftime("%H:%M:%S")
        m_a = ahora.strftime("%m-%Y")

        cur.execute("""
            INSERT OR IGNORE INTO liquidaciones_proveedores (
                numero_recibo, proveedor_id, proveedor_nombre, monto_liquidado,
                saldo_anterior, saldo_restante, tipo_pago, metodo_pago, referencia,
                fecha, hora, mes_anio, usuario, observaciones, estado
            ) VALUES (?, ?, ?, ?, 0.0, 0.0, 'Total', ?, ?, ?, ?, ?, ?, ?, 'Aplicada')
        """, (numero_recibo, proveedor_id, prov_nom, monto_flt, metodo_pago, referencia, f_s, h_s, m_a, usuario, observaciones))

        # Actualizar inmediatamente acumulados en la tabla proveedores de SQLite
        cur.execute("SELECT COALESCE(saldo_acumulado, 0.0), COALESCE(total_pagado, 0.0) FROM proveedores WHERE id = ?", (proveedor_id,))
        row_p = cur.fetchone()
        if row_p:
            s_act, p_act = float(row_p[0] or 0.0), float(row_p[1] or 0.0)
            s_nuevo = max(0.0, round(s_act - monto_flt, 2))
            p_nuevo = round(p_act + monto_flt, 2)
            cur.execute("UPDATE proveedores SET saldo_acumulado = ?, total_pagado = ? WHERE id = ?", (s_nuevo, p_nuevo, proveedor_id))
    except Exception as e_sl:
        print(f"Aviso en _sincronizar_liquidacion_local_sqlite: {e_sl}")


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
        monto = kwargs.get("monto_abono") or kwargs.get("monto_liquidado") or kwargs.get("valor") or 0.0
    if not referencia:
        referencia = kwargs.get("referencia_comprobante", "")
    if usuario == "Administrador" and "usuario_nombre" in kwargs:
        usuario = kwargs["usuario_nombre"]
    elif usuario == "Administrador" and "cajero" in kwargs:
        usuario = kwargs["cajero"]
    if not observaciones:
        observaciones = kwargs.get("notas", "")

    prov_nom_arg = (
        kwargs.get("proveedor_nombre") or
        kwargs.get("nombre_proveedor") or
        kwargs.get("nombre") or
        kwargs.get("proveedor") or
        ""
    ).strip()
    doc_nit_arg = (
        kwargs.get("documento_nit") or
        kwargs.get("nit") or
        kwargs.get("documento") or
        ""
    ).strip()
    try:
        saldo_esperado_arg = float(
            kwargs.get("saldo_pendiente") or
            kwargs.get("saldo_actual") or
            kwargs.get("saldo_acumulado") or
            0.0
        )
    except Exception:
        saldo_esperado_arg = 0.0

    if conn is None and api is not None:
        import uuid
        idem_prov = kwargs.get("idempotency_key") or f"LIQ-PROV-{proveedor_id}-{uuid.uuid4()}"
        endpoints_to_try = [
            f"/proveedores/{proveedor_id}/liquidar",
        ]
        ultimo_error_api = None
        for ep in endpoints_to_try:
            try:
                resp = api.post(
                    ep,
                    json={
                        "monto": float(monto) if (monto is not None and float(monto) > 0) else None,
                        "metodo_pago": metodo_pago,
                        "comprobante": referencia or "",
                        "referencia": referencia or "",
                        "observaciones": observaciones or "",
                        "sesion_caja_id": sesion_caja_id,
                        "proveedor_nombre": prov_nom_arg,
                        "documento_nit": doc_nit_arg,
                        "idempotency_key": idem_prov,
                    },
                    timeout=7.0,
                )
                if resp.status_code in (200, 201):
                    res_api = resp.json()
                    res_api["exito"] = True
                    res_api["ok"] = True
                    monto_real_api = float(res_api.get("total_pagado") or res_api.get("monto_pagado") or monto or 0.0)
                    res_api["monto_pagado"] = monto_real_api
                    res_api["saldo_restante"] = float(res_api.get("saldo_restante", 0.0))
                    recibo_sv = res_api.get("numero_recibo") or f"LQ-{res_api.get('liquidacion_id', res_api.get('gasto_id', 1)):05d}"
                    res_api["numero_recibo"] = recibo_sv
                    try:
                        conn_loc = conectar_db()
                        cur_loc = conn_loc.cursor()
                        _sincronizar_liquidacion_local_sqlite(cur_loc, proveedor_id, monto_real_api, metodo_pago, referencia, usuario, observaciones, recibo_sv)
                        conn_loc.commit()
                        conn_loc.close()
                    except Exception:
                        pass
                    return res_api
                else:
                    try:
                        det = resp.json().get("detail", resp.text)
                    except Exception:
                        det = resp.text
                    ultimo_error_api = det
                    # Ante rechazo explícito de validación/negocio/permisos (4xx), NO reintentar otro endpoint
                    if 400 <= resp.status_code < 500:
                        break
            except Exception as e_api_post:
                ultimo_error_api = str(e_api_post)

        # Si estamos en modo cliente conectado al servidor central, no recurrir a base de datos local vacía
        es_cliente = False
        try:
            from interface.network_manager import obtener_config_red
            cfg_n = obtener_config_red()
            es_cliente = (cfg_n.get("modo") == "cliente")
        except Exception:
            try:
                from network_manager import obtener_config_red
                cfg_n = obtener_config_red()
                es_cliente = (cfg_n.get("modo") == "cliente")
            except Exception:
                pass
        if not es_cliente and hasattr(api, "es_modo_cliente"):
            try:
                es_cliente = bool(api.es_modo_cliente())
            except Exception:
                pass

        if es_cliente:
            # Si el error indica que ya no tiene saldo pendiente por liquidar, informar con éxito
            if ultimo_error_api and "no tiene" in str(ultimo_error_api).lower():
                return {
                    "exito": True,
                    "ok": True,
                    "numero_recibo": f"LQ-PROV-{proveedor_id:04d}",
                    "monto_pagado": float(monto or 0.0),
                    "saldo_restante": 0.0,
                    "cuentas_afectadas": 0,
                    "mensaje": "El proveedor ya se encuentra a paz y salvo."
                }
            # Si el servidor devolvió un error explícito de validación o rechazo, respetarlo.
            # Pero si fue error de conexión/offline/timeout, permitir funcionamiento offline local continuo:
            err_str = str(ultimo_error_api or "").lower()
            es_error_conexion = any(k in err_str for k in ["no disponible", "timeout", "refused", "connection", "falló al conectar", "offline", "unreachable", "timed out", "connect"])
            if not es_error_conexion and ultimo_error_api:
                return {
                    "exito": False,
                    "ok": False,
                    "mensaje": f"El servidor central reportó: {ultimo_error_api}"
                }
            # Servidor no disponible o modo offline: continúa la ejecución en SQLite local y encolamiento a sync_mgr

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

    if not conn:
        return list(_MEMORIA_PROVEEDORES_CACHE)

    try:
        cur = conn.cursor()

        # 1. Validar proveedor y saldo pendiente (con búsqueda flexible por ID y por Nombre)
        cur.execute("SELECT id, nombre, COALESCE(saldo_acumulado, 0.0) FROM proveedores WHERE id = ?", (proveedor_id,))
        prov_row = cur.fetchone()
        if not prov_row and prov_nom_arg:
            cur.execute("SELECT id, nombre, COALESCE(saldo_acumulado, 0.0) FROM proveedores WHERE LOWER(nombre) = LOWER(?)", (prov_nom_arg,))
            prov_row = cur.fetchone()
        if not prov_row:
            cur.execute("SELECT id, nombre, COALESCE(saldo_acumulado, 0.0) FROM proveedores WHERE CAST(id AS TEXT) = ? OR nombre LIKE ?", (str(proveedor_id), f"%{proveedor_id}%"))
            prov_row = cur.fetchone()

        if not prov_row:
            cur.execute("SELECT DISTINCT proveedor_nombre FROM cuentas_por_pagar_proveedores WHERE proveedor_id = ? OR CAST(proveedor_id AS TEXT) = ?", (proveedor_id, str(proveedor_id)))
            nom_row = cur.fetchone()
            prov_nom_fb = prov_nom_arg or (nom_row[0] if nom_row else f"Proveedor #{proveedor_id}")
            try:
                cur.execute("PRAGMA table_info(proveedores)")
                cols_prov_db = [c[1] for c in cur.fetchall()]
                cols_ins = ["id", "nombre", "saldo_acumulado"]
                vals_ins = [proveedor_id, prov_nom_fb, max(saldo_esperado_arg, float(monto or 0.0))]
                if "documento_nit" in cols_prov_db:
                    cols_ins.append("documento_nit")
                    vals_ins.append(doc_nit_arg)
                if "estado" in cols_prov_db:
                    cols_ins.append("estado")
                    vals_ins.append("Activo")
                placeholders = ", ".join(["?"] * len(cols_ins))
                cur.execute(f"INSERT OR REPLACE INTO proveedores ({', '.join(cols_ins)}) VALUES ({placeholders})", vals_ins)
                conn.commit()
                cur.execute("SELECT id, nombre, COALESCE(saldo_acumulado, 0.0) FROM proveedores WHERE id = ?", (proveedor_id,))
                prov_row = cur.fetchone()
            except Exception as e_p_prov:
                print(f"Aviso auto-aprovisionando proveedor en liquidación: {e_p_prov}")

        # Garantizar que prov_row nunca sea nulo si se conoce el nombre o ID del proveedor
        if not prov_row:
            prov_nom_fb = prov_nom_arg or f"Proveedor #{proveedor_id}"
            prov_row = (proveedor_id, prov_nom_fb, max(saldo_esperado_arg, float(monto or 0.0)))

        prov_nom = str(prov_row[1])
        saldo_actual = float(prov_row[2] or 0.0)

        # Recálculo fresco para máxima consistencia
        rec = recalcular_saldo_proveedor(proveedor_id, conn=conn)
        saldo_calc = float(rec.get("saldo_pendiente") or 0.0)
        saldo_actual = max(saldo_actual, saldo_calc, saldo_esperado_arg)

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

        f_mov = kwargs.get("fecha_movimiento") or kwargs.get("fecha") or kwargs.get("fecha_operativa") or kwargs.get("fecha_real")
        h_mov = kwargs.get("hora_movimiento") or kwargs.get("hora") or kwargs.get("hora_operativa") or kwargs.get("hora_real")

        ahora = datetime.now()
        fecha_registro = ahora.strftime("%Y-%m-%d %H:%M:%S")
        fecha_str = (normalizar_fecha(f_mov) if f_mov else None) or ahora.strftime("%Y-%m-%d")
        hora_str = (normalizar_hora(h_mov) if h_mov else None) or ahora.strftime("%H:%M:%S")
        mes_anio = f"{fecha_str[5:7]}-{fecha_str[:4]}"

        # Generar número correlativo de recibo
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM liquidaciones_proveedores")
        max_id = cur.fetchone()[0] or 0
        numero_recibo = f"LIQ-PROV-{max_id + 1:05d}"

        # 2. Distribuir el pago entre las cuentas por pagar pendientes (FIFO)
        cur.execute("""
            SELECT id, monto_por_pagar, monto_pagado, saldo_pendiente
            FROM cuentas_por_pagar_proveedores
            WHERE (proveedor_id = ? OR CAST(proveedor_id AS TEXT) = ? OR CAST(proveedor_id AS TEXT) LIKE ? OR ((proveedor_id IS NULL OR proveedor_id = 0 OR proveedor_id = '') AND LOWER(proveedor_nombre) = LOWER(?)))
              AND estado != 'Pagada' AND estado != 'Anulada'
            ORDER BY id ASC
        """, (proveedor_id, str(proveedor_id), f"{proveedor_id} - %", prov_nom))
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

        # 3. Registrar en liquidaciones_proveedores con fecha contable y fecha de registro
        cur.execute("PRAGMA table_info(liquidaciones_proveedores)")
        cols_lp_set = {c[1] for c in cur.fetchall()}
        
        cols_liq = [
            "numero_recibo", "proveedor_id", "proveedor_nombre", "monto_liquidado",
            "saldo_anterior", "saldo_restante", "tipo_pago", "metodo_pago", "referencia",
            "fecha", "hora", "mes_anio", "usuario", "observaciones", "estado"
        ]
        vals_liq = [
            numero_recibo, proveedor_id, prov_nom, monto_flt,
            saldo_actual, saldo_restante, tipo_pago, metodo_pago,
            referencia, fecha_str, hora_str, mes_anio, usuario, observaciones, 'Aplicada'
        ]
        if "fecha_registro" in cols_lp_set:
            cols_liq.append("fecha_registro")
            vals_liq.append(fecha_registro)
        if "dinero_de_mas" in cols_lp_set:
            cols_liq.append("dinero_de_mas")
            vals_liq.append(0.0)
        if "monto_ajustado" in cols_lp_set:
            cols_liq.append("monto_ajustado")
            vals_liq.append(monto_flt)
        if "created_at" in cols_lp_set:
            cols_liq.append("created_at")
            vals_liq.append(fecha_registro)

        placeholders_liq = ", ".join(["?"] * len(cols_liq))
        cur.execute(f"""
            INSERT INTO liquidaciones_proveedores ({", ".join(cols_liq)})
            VALUES ({placeholders_liq})
        """, vals_liq)
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
                    descripcion, estado, usuario, proveedor, comprobante, observaciones,
                    fecha_pago, fecha_registro
                ) VALUES (?, ?, ?, ?, ?, 'Proveedores', 'Cuentas por Pagar', ?, 'Pagado', ?, ?, ?, ?, ?, ?)
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
                observaciones or referencia,
                f"{fecha_str} {hora_str}",
                fecha_registro
            ))
        except Exception as e_gasto:
            print(f"Aviso registrando gasto de proveedor: {e_gasto}")

        # 6. Integración contable con Caja y Bancos
        cuenta_afectada = "CAJA_FISICA" if metodo_pago == "Efectivo" else "BANCO_TRANSFERENCIA"
        try:
            # Obtener sesión de caja abierta si no fue provista y el pago es en efectivo
            s_caja_id = sesion_caja_id
            if not s_caja_id and metodo_pago == "Efectivo":
                cur.execute("SELECT id FROM sesiones_caja WHERE fecha_apertura = ? ORDER BY id DESC LIMIT 1", (fecha_str,))
                s_row = cur.fetchone()
                if s_row:
                    s_caja_id = s_row[0]
                else:
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
                        terminal, referencia_id, descripcion, created_at
                    ) VALUES (?, ?, ?, 'EGRESO', ?, ?, 'Terminal-1', ?, ?, ?)
                """, (
                    s_caja_id, fecha_str, hora_str, monto_flt, usuario,
                    numero_recibo, f"Pago a proveedor: {prov_nom}", fecha_registro
                ))
        except Exception as e_caja:
            print(f"Aviso registrando movimiento de caja/financiero: {e_caja}")

        # 7. Actualizar saldo acumulado del proveedor
        recalcular_saldo_proveedor(proveedor_id, conn=conn)

        # 8. Encolar en la cola transaccional persistente si se guardó en local SQLite
        try:
            from interface.sync_manager import sync_mgr
            sync_mgr.encolar_operacion(
                tipo_operacion="LIQUIDACION_PROVEEDOR",
                payload={
                    "proveedor_id": proveedor_id,
                    "proveedor_nombre": prov_nom,
                    "documento_nit": doc_nit_arg,
                    "monto": monto_flt,
                    "metodo_pago": metodo_pago,
                    "referencia": referencia,
                    "observaciones": observaciones,
                    "numero_recibo": numero_recibo,
                    "fecha": fecha_str,
                    "hora": hora_str,
                    "fecha_movimiento": fecha_str,
                    "fecha_registro": fecha_registro,
                },
                usuario=usuario,
                id_local=str(id_liq),
                conn=conn
            )
        except Exception as e_q:
            print(f"Aviso encolando liquidación de proveedor para sincronización: {e_q}")

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
            "hora": hora_str,
            "fecha_movimiento": fecha_str,
            "hora_movimiento": hora_str,
            "fecha_registro": fecha_registro
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


def _row_a_dict_liq(row) -> Dict[str, Any]:
    return {
        "id": row[0],
        "numero_recibo": row[1],
        "proveedor_id": row[2],
        "proveedor_nombre": row[3],
        "monto_liquidado": float(row[4] or 0.0),
        "fecha": str(row[5] or ""),
        "hora": str(row[6] or ""),
        "metodo_pago": str(row[7] or "Efectivo"),
        "estado": str(row[8] or "Aplicada"),
        "dinero_de_mas": float(row[9] or 0.0),
        "monto_ajustado": float(row[10] or row[4] or 0.0),
        "fecha_registro": str(row[11] or row[5] or ""),
    }


def buscar_liquidacion_proveedor_flexible(
    identificador: Any,
    proveedor_id: Optional[int] = None,
    proveedor_nombre: Optional[str] = None,
    monto: Optional[float] = None,
    fecha: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> Optional[Dict[str, Any]]:
    """
    Busca una liquidación de proveedor de forma robusta y flexible en SQLite:
    1. Por ID entero directo (si el identificador es entero o cadena numérica).
    2. Por coincidencia exacta de número de recibo (LP-XXXX, LQ-XXXXX, LIQ-PROV-XXXX, etc.).
    3. Normalizando prefijos y extrayendo dígitos (ej: 'LP-0007' busca también 'LQ-00007', id=7, '%0007').
    4. Por contexto operacional (proveedor + monto aproximado + fecha).
    5. Fallback a historial_liquidaciones para registros históricos previos.
    """
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    if not conn:
        return None

    try:
        cur = conn.cursor()
        cols_sql = """
            SELECT id, numero_recibo, proveedor_id, proveedor_nombre, monto_liquidado,
                   fecha, hora, metodo_pago, estado,
                   COALESCE(dinero_de_mas, 0.0) as dinero_de_mas,
                   COALESCE(monto_ajustado, monto_liquidado) as monto_ajustado,
                   COALESCE(fecha_registro, created_at, fecha) as fecha_registro
            FROM liquidaciones_proveedores
        """
        id_str = str(identificador or "").strip()

        # 1. Búsqueda directa por ID numérico si es dígito
        if id_str.isdigit():
            cur.execute(f"{cols_sql} WHERE id = ?", (int(id_str),))
            row = cur.fetchone()
            if row:
                return _row_a_dict_liq(row)

        # 2. Coincidencia exacta por número de recibo
        if id_str:
            cur.execute(f"{cols_sql} WHERE numero_recibo = ?", (id_str,))
            row = cur.fetchone()
            if row:
                return _row_a_dict_liq(row)

        # 3. Normalización de dígitos y variantes LP- / LQ- / LIQ-PROV-
        import re
        digitos = re.findall(r'\d+', id_str)
        if digitos:
            d_val = digitos[-1]
            try:
                n_val = int(d_val)
            except Exception:
                n_val = 0
            v_lp = f"LP-{n_val:04d}"
            v_lq = f"LQ-{n_val:05d}"
            cur.execute(f"""
                {cols_sql}
                WHERE id = ? 
                   OR numero_recibo = ? 
                   OR numero_recibo = ? 
                   OR numero_recibo LIKE ?
                   OR numero_recibo LIKE ?
                ORDER BY id DESC LIMIT 1
            """, (n_val, v_lp, v_lq, f"%{d_val}", f"%-{n_val}"))
            row = cur.fetchone()
            if row:
                return _row_a_dict_liq(row)

        # 4. Búsqueda contextual por proveedor y monto
        if (proveedor_id or proveedor_nombre) and monto is not None:
            m_flt = float(monto)
            filtros = ["ABS(monto_liquidado - ?) < 0.05"]
            p_args = [m_flt]
            if proveedor_id:
                filtros.append("(proveedor_id = ? OR CAST(proveedor_id AS TEXT) = ?)")
                p_args.extend([proveedor_id, str(proveedor_id)])
            if proveedor_nombre:
                filtros.append("LOWER(proveedor_nombre) = LOWER(?)")
                p_args.append(proveedor_nombre.strip())
            if fecha:
                f_c = fecha.strip()[:10]
                filtros.append("(fecha = ? OR fecha LIKE ?)")
                p_args.extend([f_c, f"{f_c}%"])

            w_clause = " AND ".join(filtros)
            cur.execute(f"{cols_sql} WHERE {w_clause} ORDER BY id DESC LIMIT 1", p_args)
            row = cur.fetchone()
            if row:
                return _row_a_dict_liq(row)

        # 5. Fallback a historial_liquidaciones si no está en liquidaciones_proveedores
        try:
            cur.execute("PRAGMA table_info(historial_liquidaciones)")
            cols_h = [c[1] for c in cur.fetchall()]
            if cols_h:
                if id_str.isdigit():
                    cur.execute("SELECT id, tipo, tipo_id, proveedor, monto, fecha, mes_anio FROM historial_liquidaciones WHERE id = ? ORDER BY id DESC LIMIT 1", (int(id_str),))
                    h_row = cur.fetchone()
                    if h_row:
                        f_h = str(h_row[5] or "")
                        f_p = f_h[:10]
                        h_p = f_h[11:19] if len(f_h) > 10 else "12:00:00"
                        return {
                            "id": h_row[0],
                            "numero_recibo": f"LP-{h_row[0]:04d}",
                            "proveedor_id": h_row[2],
                            "proveedor_nombre": h_row[3],
                            "monto_liquidado": float(h_row[4] or 0.0),
                            "fecha": f_p,
                            "hora": h_p,
                            "metodo_pago": "Efectivo",
                            "estado": "Aplicada",
                            "dinero_de_mas": 0.0,
                            "monto_ajustado": float(h_row[4] or 0.0),
                            "fecha_registro": f_h
                        }
        except Exception:
            pass

        return None
    finally:
        if cerrar_conn and conn:
            conn.close()


def revertir_liquidacion_proveedor_db(
    liquidacion_id: Any,
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

    if not conn:
        return list(_MEMORIA_PROVEEDORES_CACHE)

    try:
        cur = conn.cursor()
        liq = buscar_liquidacion_proveedor_flexible(identificador=liquidacion_id, conn=conn)
        if not liq:
            return {
                "ok": False,
                "exito": False,
                "success": False,
                "mensaje": f"Liquidación con ID {liquidacion_id} no encontrada."
            }

        if liq.get("estado") == "Revertida":
            return {
                "ok": False,
                "exito": False,
                "success": False,
                "mensaje": "Esta liquidación ya fue revertida previamente."
            }

        id_real = liq["id"]
        prov_id = liq["proveedor_id"]
        prov_nom = liq["proveedor_nombre"]
        monto_flt = float(liq["monto_liquidado"] or 0.0)
        metodo = str(liq["metodo_pago"] or "Efectivo")
        recibo = str(liq["numero_recibo"] or f"LQ-{id_real:05d}")

        # Marcar liquidación como revertida
        cur.execute("""
            UPDATE liquidaciones_proveedores
            SET estado = 'Revertida',
                observaciones = COALESCE(observaciones, '') || ' | Revertida por ' || ? || ': ' || ?
            WHERE id = ?
        """, (usuario, motivo, id_real))

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


def _fmt_cop(val: float) -> str:
    """Formatea valores monetarios a estándar COP."""
    try:
        return f"${float(val or 0.0):,.0f} COP"
    except Exception:
        return "$0 COP"


def _aplicar_cambio_fecha_sqlite(
    conn: sqlite3.Connection,
    liquidacion_id: Any,
    f_normalizada: str,
    h_normalizada: str,
    motivo: str,
    usuario: str,
    numero_recibo: Optional[str] = None,
    proveedor_id: Optional[int] = None,
    proveedor_nombre: Optional[str] = None,
    monto: Optional[float] = None
) -> Dict[str, Any]:
    liq = buscar_liquidacion_proveedor_flexible(
        identificador=liquidacion_id or numero_recibo,
        proveedor_id=proveedor_id,
        proveedor_nombre=proveedor_nombre,
        monto=monto,
        conn=conn
    )
    if not liq:
        return {"exito": False, "ok": False, "mensaje": f"Liquidación #{liquidacion_id} no encontrada."}

    id_real = liq["id"]
    recibo = liq["numero_recibo"] or (f"LQ-{id_real:05d}" if isinstance(id_real, int) else str(id_real))
    prov_id = liq["proveedor_id"]
    prov_nom = liq["proveedor_nombre"]
    monto_flt = float(liq["monto_liquidado"] or 0.0)
    fecha_ant = str(liq["fecha"] or "")
    hora_ant = str(liq["hora"] or "")
    metodo = str(liq["metodo_pago"] or "Efectivo")
    estado = str(liq["estado"] or "Aplicada")
    fecha_reg = str(liq["fecha_registro"] or fecha_ant)

    if estado == "Revertida":
        return {
            "exito": False,
            "ok": False,
            "mensaje": "No se puede modificar la fecha de una liquidación que ha sido revertida."
        }

    if f_normalizada == fecha_ant and h_normalizada == hora_ant:
        return {
            "exito": True,
            "ok": True,
            "mensaje": f"La liquidación {recibo} ya tenía la fecha {f_normalizada} y hora {h_normalizada}."
        }

    nuevo_mes_anio = f"{f_normalizada[5:7]}-{f_normalizada[:4]}"
    ahora_aud = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.cursor()

    # 1. Actualizar liquidaciones_proveedores
    cur.execute("""
        UPDATE liquidaciones_proveedores
        SET fecha = ?, hora = ?, mes_anio = ?,
            observaciones = COALESCE(observaciones, '') || ' | ' || ?
        WHERE id = ?
    """, (
        f_normalizada, h_normalizada, nuevo_mes_anio,
        f"[Fecha contable cambiada de {fecha_ant} a {f_normalizada} por {usuario}: {motivo}]",
        id_real
    ))

    # 2. Actualizar gastos contables (trasladar afectación al nuevo día)
    try:
        cur.execute("""
            UPDATE gastos
            SET fecha = ?, hora = ?, fecha_pago = ?,
                observaciones = COALESCE(observaciones, '') || ' | ' || ?
            WHERE (comprobante = ? OR comprobante = ? OR comprobante LIKE ? OR comprobante LIKE ?)
              AND (proveedor = ? OR proveedor IS NULL OR proveedor = '')
        """, (
            f_normalizada, h_normalizada, f"{f_normalizada} {h_normalizada}",
            f"[Fecha contable cambiada de {fecha_ant} a {f_normalizada} por {usuario}: {motivo}]",
            recibo, f"LQ-{id_real:05d}", f"%{recibo}%", f"%{id_real}%", prov_nom
        ))
    except Exception as e_g:
        print(f"Aviso actualizando gastos: {e_g}")

    # 3. Actualizar historial_liquidaciones para compatibilidad
    try:
        cur.execute("""
            UPDATE historial_liquidaciones
            SET fecha = ?, mes_anio = ?
            WHERE (id = ? OR persona_id = ? OR CAST(tipo_id AS TEXT) = ?)
              AND (proveedor = ? OR nombre_persona = ?)
        """, (f"{f_normalizada} {h_normalizada}", nuevo_mes_anio, id_real, prov_id, str(id_real), prov_nom, prov_nom))
    except Exception as e_hl:
        pass

    # 4. Actualizar movimientos financieros y de caja
    try:
        cur.execute("""
            UPDATE movimientos_financieros
            SET fecha = ?, hora = ?,
                observaciones = COALESCE(observaciones, '') || ' | ' || ?
            WHERE referencia_origen = ? OR referencia_origen = ?
        """, (f_normalizada, h_normalizada, f"[Trasladado de {fecha_ant} a {f_normalizada}: {motivo}]", recibo, f"LQ-{id_real:05d}"))

        cur.execute("""
            UPDATE movimientos_caja
            SET fecha = ?, hora = ?,
                descripcion = COALESCE(descripcion, '') || ' | ' || ?
            WHERE referencia_id = ? OR referencia_id = ?
        """, (f_normalizada, h_normalizada, f"[Trasladado de {fecha_ant} a {f_normalizada}]", recibo, f"LQ-{id_real:05d}"))
    except Exception as e_mov:
        pass

    # 5. Actualizar ajustes de dinero de más si existen vinculados a esta liquidación
    try:
        cur.execute("""
            UPDATE ajustes_liquidaciones_proveedores
            SET fecha_movimiento = ?, hora_movimiento = ?
            WHERE liquidacion_id = ? OR numero_recibo = ?
        """, (f_normalizada, h_normalizada, id_real, recibo))
    except Exception as e_aj_up:
        pass

    # 6. Auditoría explícita
    try:
        cur.execute("""
            INSERT INTO auditoria_liquidaciones (
                liquidacion_id, numero_recibo, proveedor_id, proveedor_nombre,
                accion, fecha_anterior, fecha_nueva, monto, usuario, motivo, fecha_registro
            ) VALUES (?, ?, ?, ?, 'EDITAR_FECHA', ?, ?, ?, ?, ?, ?)
        """, (
            id_real, recibo, prov_id, prov_nom,
            f"{fecha_ant} {hora_ant}", f"{f_normalizada} {h_normalizada}",
            monto_flt, usuario, motivo, ahora_aud
        ))

        cur.execute("""
            INSERT INTO auditoria_caja (fecha, hora, usuario, accion, detalle, exito, created_at)
            VALUES (?, ?, ?, 'MODIFICAR_FECHA_LIQUIDACION', ?, 1, ?)
        """, (
            datetime.now().strftime("%Y-%m-%d"),
            datetime.now().strftime("%H:%M:%S"),
            usuario,
            f"Liquidación {recibo} ({prov_nom}, {_fmt_cop(monto_flt)}): Trasladada de {fecha_ant} a {f_normalizada}. Motivo: {motivo}",
            ahora_aud
        ))
    except Exception as e_aud:
        pass

    # 7. Sincronización en red
    try:
        from interface.sync_manager import sync_mgr
        sync_mgr.encolar_operacion(
            tipo_operacion="MODIFICAR_FECHA_LIQUIDACION_PROVEEDOR",
            payload={
                "liquidacion_id": id_real,
                "numero_recibo": recibo,
                "proveedor_id": prov_id,
                "fecha_anterior": fecha_ant,
                "nueva_fecha": f_normalizada,
                "nueva_hora": h_normalizada,
                "motivo": motivo,
                "usuario": usuario,
            },
            usuario=usuario,
            id_local=str(id_real),
            conn=conn
        )
    except Exception as e_sync:
        pass

    return {
        "exito": True,
        "ok": True,
        "liquidacion_id": id_real,
        "numero_recibo": recibo,
        "proveedor_id": prov_id,
        "proveedor_nombre": prov_nom,
        "monto": monto_flt,
        "fecha_anterior": fecha_ant,
        "nueva_fecha": f_normalizada,
        "nueva_hora": h_normalizada,
        "fecha_registro": fecha_reg,
        "mensaje": f"Liquidación {recibo} actualizada exitosamente. Afectación trasladada del {fecha_ant} al {f_normalizada}."
    }


def actualizar_fecha_liquidacion_proveedor_db(
    liquidacion_id: Any,
    nueva_fecha: str,
    nueva_hora: Optional[str] = None,
    motivo: str = "Corrección de fecha operativa",
    usuario: str = "Administrador",
    conn: Optional[sqlite3.Connection] = None,
    numero_recibo: Optional[str] = None,
    proveedor_id: Optional[int] = None,
    proveedor_nombre: Optional[str] = None,
    monto: Optional[float] = None
) -> Dict[str, Any]:
    """
    Modifica la fecha contable/operativa de una liquidación o abono a proveedor:
    1. Si está conectado al servidor API, actualiza centralmente vía HTTP.
    2. Actualiza la fecha contable en liquidaciones_proveedores sin crear duplicados ni alterar montos.
    3. Traslada la afectación en gastos, movimientos_financieros y movimientos_caja a la nueva fecha.
    4. Conserva intacta la fecha de registro original (fecha_registro / created_at) para auditoría.
    5. Registra evento de auditoría detallado con fecha anterior, nueva, usuario y motivo.
    6. Respeta y preserva la integridad de cualquier cierre de caja previo.
    """
    f_normalizada = normalizar_fecha(nueva_fecha)
    h_normalizada = normalizar_hora(nueva_hora) if nueva_hora else "12:00:00"
    if not f_normalizada:
        return {"exito": False, "ok": False, "mensaje": "La nueva fecha ingresada no es válida."}

    # 1. Si el API central está disponible y no se forzó conexión local explícita
    if conn is None and api is not None:
        try:
            if api.esta_disponible():
                target_api_id = str(numero_recibo or liquidacion_id).strip()
                resp = api.post(
                    f"/proveedores/liquidaciones/{target_api_id}/editar-fecha",
                    json={
                        "nueva_fecha": f_normalizada,
                        "nueva_hora": h_normalizada,
                        "motivo": motivo,
                    },
                    timeout=7.0
                )
                if resp.status_code == 200:
                    res_api = resp.json()
                    res_api["exito"] = True
                    res_api["ok"] = True
                    try:
                        conn_loc = conectar_db()
                        _aplicar_cambio_fecha_sqlite(
                            conn=conn_loc,
                            liquidacion_id=liquidacion_id,
                            f_normalizada=f_normalizada,
                            h_normalizada=h_normalizada,
                            motivo=motivo,
                            usuario=usuario,
                            numero_recibo=numero_recibo,
                            proveedor_id=proveedor_id,
                            proveedor_nombre=proveedor_nombre,
                            monto=monto
                        )
                        conn_loc.commit()
                        conn_loc.close()
                    except Exception as e_loc_sync:
                        print(f"Aviso replicando cambio de fecha local: {e_loc_sync}")
                    return res_api
                elif 400 <= resp.status_code < 500:
                    det = resp.json().get("detail", resp.text) if hasattr(resp, "json") else resp.text
                    return {"exito": False, "ok": False, "mensaje": det}
        except Exception as e_api:
            print(f"Aviso actualizando fecha en API: {e_api}")

    # 2. Modo local SQLite
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    if not conn:
        return {"exito": False, "ok": False, "mensaje": "No se pudo conectar a la base de datos."}

    try:
        res = _aplicar_cambio_fecha_sqlite(
            conn=conn,
            liquidacion_id=liquidacion_id,
            f_normalizada=f_normalizada,
            h_normalizada=h_normalizada,
            motivo=motivo,
            usuario=usuario,
            numero_recibo=numero_recibo,
            proveedor_id=proveedor_id,
            proveedor_nombre=proveedor_nombre,
            monto=monto
        )
        if cerrar_conn and res.get("exito"):
            conn.commit()
        return res
    except Exception as ex:
        if conn and cerrar_conn:
            conn.rollback()
        return {"exito": False, "ok": False, "mensaje": f"Error modificando fecha: {ex}"}
    finally:
        if cerrar_conn and conn:
            conn.close()


def _aplicar_dinero_de_mas_sqlite(
    conn: sqlite3.Connection,
    liquidacion_id: Any,
    monto_sobrante_flt: float,
    motivo: str,
    usuario: str,
    fecha_movimiento: Optional[str] = None,
    hora_movimiento: Optional[str] = None,
    numero_recibo: Optional[str] = None,
    proveedor_id: Optional[int] = None,
    proveedor_nombre: Optional[str] = None
) -> Dict[str, Any]:
    liq = buscar_liquidacion_proveedor_flexible(
        identificador=liquidacion_id or numero_recibo,
        proveedor_id=proveedor_id,
        proveedor_nombre=proveedor_nombre,
        conn=conn
    )
    if not liq:
        return {"exito": False, "ok": False, "mensaje": f"Liquidación #{liquidacion_id} no encontrada."}

    id_real = liq["id"]
    recibo = liq["numero_recibo"] or (f"LQ-{id_real:05d}" if isinstance(id_real, int) else str(id_real))
    prov_id = liq["proveedor_id"]
    prov_nom = liq["proveedor_nombre"]
    monto_liquidado = float(liq["monto_liquidado"] or 0.0)
    fecha_orig = str(liq["fecha"] or "")
    hora_orig = str(liq["hora"] or "")
    metodo = str(liq["metodo_pago"] or "Efectivo")
    estado = str(liq["estado"] or "Aplicada")
    dinero_mas_previo = float(liq["dinero_de_mas"] or 0.0)

    if estado == "Revertida":
        return {
            "exito": False,
            "ok": False,
            "mensaje": "No se puede corregir dinero de más sobre una liquidación que ha sido revertida."
        }

    max_corregible = round(monto_liquidado - dinero_mas_previo, 2)
    if monto_sobrante_flt > max_corregible + 0.001:
        return {
            "exito": False,
            "ok": False,
            "mensaje": f"El monto de dinero de más (${monto_sobrante_flt:,.0f}) supera el valor corregible disponible (${max_corregible:,.0f}) de la liquidación {recibo}."
        }

    f_contable = normalizar_fecha(fecha_movimiento or fecha_orig)
    h_contable = normalizar_hora(hora_movimiento or hora_orig)
    ahora_dt = datetime.now()
    fecha_registro_ajuste = ahora_dt.strftime("%Y-%m-%d %H:%M:%S")

    cur = conn.cursor()
    cur.execute("SELECT COUNT(id) FROM ajustes_liquidaciones_proveedores")
    conteo_aj = cur.fetchone()[0] or 0
    numero_ajuste = f"AJ-SOB-{conteo_aj + 1:05d}"

    nuevo_dinero_mas = round(dinero_mas_previo + monto_sobrante_flt, 2)
    nuevo_monto_ajustado = max(0.0, round(monto_liquidado - nuevo_dinero_mas, 2))

    # 1. Registrar en tabla ajustes_liquidaciones_proveedores
    cur.execute("""
        INSERT INTO ajustes_liquidaciones_proveedores (
            numero_ajuste, liquidacion_id, numero_recibo, proveedor_id, proveedor_nombre,
            monto_ajuste, fecha_movimiento, hora_movimiento, fecha_registro,
            usuario, motivo, estado, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Aplicado', ?)
    """, (
        numero_ajuste, id_real, recibo, prov_id, prov_nom,
        monto_sobrante_flt, f_contable, h_contable, fecha_registro_ajuste,
        usuario, motivo, fecha_registro_ajuste
    ))
    id_ajuste = cur.lastrowid

    # 2. Actualizar registro en liquidaciones_proveedores
    cur.execute("""
        UPDATE liquidaciones_proveedores
        SET dinero_de_mas = ?,
            monto_ajustado = ?,
            observaciones = COALESCE(observaciones, '') || ' | ' || ?
        WHERE id = ?
    """, (
        nuevo_dinero_mas, nuevo_monto_ajustado,
        f"[Dinero de Más -${monto_sobrante_flt:,.0f} ({numero_ajuste}) por {usuario}: {motivo}]",
        id_real
    ))

    # 3. Registrar contra-asiento en gastos
    try:
        cur.execute("""
            INSERT INTO gastos (
                concepto, valor, fecha, hora, metodo_pago, categoria, clasificacion,
                descripcion, estado, usuario, proveedor, comprobante, observaciones,
                fecha_pago, fecha_registro
            ) VALUES (?, ?, ?, ?, ?, 'Proveedores', 'Cuentas por Pagar', ?, 'Pagado', ?, ?, ?, ?, ?, ?)
        """, (
            f"Ajuste Dinero de Más - {prov_nom} ({recibo})",
            -monto_sobrante_flt,
            f_contable,
            h_contable,
            metodo,
            f"Corrección contable dinero sobrante liquidación {recibo}. Ajuste {numero_ajuste}",
            usuario,
            prov_nom,
            numero_ajuste,
            f"Motivo: {motivo} | Liquidación Ref: {recibo}",
            f"{f_contable} {h_contable}",
            fecha_registro_ajuste
        ))
    except Exception as e_g_aj:
        print(f"Aviso registrando contra-asiento en gastos: {e_g_aj}")

    # 4. Ajustar dinero en caja física si fue efectivo
    cuenta_af = "CAJA_FISICA" if metodo == "Efectivo" else "BANCO_TRANSFERENCIA"
    try:
        if metodo == "Efectivo":
            cur.execute("SELECT id FROM sesiones_caja WHERE fecha_apertura = ? ORDER BY id DESC LIMIT 1", (f_contable,))
            s_r = cur.fetchone()
            s_id = s_r[0] if s_r else None
            if not s_id:
                cur.execute("SELECT id FROM sesiones_caja WHERE estado = 'Abierta' ORDER BY id DESC LIMIT 1")
                s_r = cur.fetchone()
                s_id = s_r[0] if s_r else 1

            cur.execute("""
                INSERT INTO movimientos_caja (
                    sesion_caja_id, fecha, hora, tipo, monto, usuario,
                    terminal, referencia_id, descripcion, created_at
                ) VALUES (?, ?, ?, 'AJUSTE', ?, ?, 'Terminal-1', ?, ?, ?)
            """, (
                s_id, f_contable, h_contable, monto_sobrante_flt, usuario,
                numero_ajuste, f"Ajuste dinero de más sobre {recibo}: {prov_nom}", fecha_registro_ajuste
            ))

        cur.execute("""
            INSERT INTO movimientos_financieros (
                fecha, hora, tipo, concepto, monto, metodo_pago,
                cuenta_afectada, usuario, referencia_origen, estado, observaciones
            ) VALUES (?, ?, 'AJUSTE_SOBRANTE_PROVEEDOR', ?, ?, ?, ?, ?, ?, 'Activo', ?)
        """, (
            f_contable, h_contable, f"Ajuste dinero de más proveedor {prov_nom} ({numero_ajuste})",
            monto_sobrante_flt, metodo, cuenta_af, usuario,
            numero_ajuste, f"Liquidación: {recibo}. Motivo: {motivo}"
        ))
    except Exception as e_fin_aj:
        print(f"Aviso registrando ajuste en caja/financiero: {e_fin_aj}")

    # 5. Reabrir cuentas por pagar asociadas en orden LIFO
    try:
        cur.execute("""
            SELECT id, monto_por_pagar, monto_pagado, saldo_pendiente
            FROM cuentas_por_pagar_proveedores
            WHERE (proveedor_id = ? OR CAST(proveedor_id AS TEXT) = ? OR LOWER(proveedor_nombre) = LOWER(?))
              AND monto_pagado > 0
            ORDER BY id DESC
        """, (prov_id, str(prov_id), prov_nom))
        cuentas_pagadas = cur.fetchall()

        remanente_restaurar = monto_sobrante_flt
        for c_id, c_tot, c_pag, c_saldo in cuentas_pagadas:
            if remanente_restaurar <= 0.001:
                break
            c_pag_flt = float(c_pag)
            restaurar_en_cuenta = min(remanente_restaurar, c_pag_flt)
            nuevo_pagado = round(c_pag_flt - restaurar_en_cuenta, 2)
            nuevo_saldo = round(float(c_saldo) + restaurar_en_cuenta, 2)
            nuevo_estado = "Pendiente" if nuevo_pagado == 0.0 else "Abonada"

            cur.execute("""
                UPDATE cuentas_por_pagar_proveedores
                SET monto_pagado = ?, saldo_pendiente = ?, estado = ?
                WHERE id = ?
            """, (nuevo_pagado, nuevo_saldo, nuevo_estado, c_id))

            remanente_restaurar = round(remanente_restaurar - restaurar_en_cuenta, 2)
    except Exception as e_cxp_r:
        print(f"Aviso restaurando cxp proveedores: {e_cxp_r}")

    # 6. Recalcular saldos del proveedor
    rec = recalcular_saldo_proveedor(prov_id, conn=conn)

    # 7. Registrar auditoría
    try:
        cur.execute("""
            INSERT INTO auditoria_liquidaciones (
                liquidacion_id, numero_recibo, proveedor_id, proveedor_nombre,
                accion, fecha_anterior, fecha_nueva, monto, usuario, motivo, fecha_registro
            ) VALUES (?, ?, ?, ?, 'DINERO_DE_MAS', ?, ?, ?, ?, ?, ?)
        """, (
            id_real, recibo, prov_id, prov_nom,
            f"Monto Original: {_fmt_cop(monto_liquidado)}",
            f"Ajuste Sobrante: -{_fmt_cop(monto_sobrante_flt)} (Neto: {_fmt_cop(nuevo_monto_ajustado)})",
            monto_sobrante_flt, usuario, motivo, fecha_registro_ajuste
        ))

        cur.execute("""
            INSERT INTO auditoria_caja (fecha, hora, usuario, accion, detalle, exito, created_at)
            VALUES (?, ?, ?, 'CORRECCION_DINERO_DE_MAS', ?, 1, ?)
        """, (
            ahora_dt.strftime("%Y-%m-%d"),
            ahora_dt.strftime("%H:%M:%S"),
            usuario,
            f"Ajuste {numero_ajuste} sobre {recibo} ({prov_nom}): Dinero de más {_fmt_cop(monto_sobrante_flt)}. Fecha contable: {f_contable}. Motivo: {motivo}",
            fecha_registro_ajuste
        ))
    except Exception as e_aud_aj:
        print(f"Aviso registrando auditoría de dinero de más: {e_aud_aj}")

    # 8. Sincronización en red
    try:
        from interface.sync_manager import sync_mgr
        sync_mgr.encolar_operacion(
            tipo_operacion="DINERO_DE_MAS_PROVEEDOR",
            payload={
                "ajuste_id": id_ajuste,
                "numero_ajuste": numero_ajuste,
                "liquidacion_id": id_real,
                "numero_recibo": recibo,
                "proveedor_id": prov_id,
                "monto_ajuste": monto_sobrante_flt,
                "fecha_movimiento": f_contable,
                "hora_movimiento": h_contable,
                "motivo": motivo,
                "usuario": usuario,
            },
            usuario=usuario,
            id_local=str(id_ajuste),
            conn=conn
        )
    except Exception as e_sync_aj:
        print(f"Aviso encolando sync de dinero de más: {e_sync_aj}")

    return {
        "exito": True,
        "ok": True,
        "numero_ajuste": numero_ajuste,
        "liquidacion_id": id_real,
        "numero_recibo": recibo,
        "proveedor_id": prov_id,
        "proveedor_nombre": prov_nom,
        "monto_ajuste": monto_sobrante_flt,
        "monto_sobrante": monto_sobrante_flt,
        "dinero_de_mas_total": nuevo_dinero_mas,
        "monto_neto": nuevo_monto_ajustado,
        "monto_ajustado_restante": nuevo_monto_ajustado,
        "nuevo_saldo_proveedor": rec.get("saldo_pendiente", 0.0),
        "saldo_proveedor_restante": rec.get("saldo_pendiente", 0.0),
        "fecha_contable": f_contable,
        "fecha_movimiento": f_contable,
        "mensaje": f"Corrección por dinero de más registrada con éxito ({numero_ajuste}). Se descontaron {_fmt_cop(monto_sobrante_flt)} del día {f_contable}."
    }


def registrar_dinero_de_mas_proveedor_db(
    liquidacion_id: Any,
    monto_sobrante: float,
    motivo: str,
    usuario: str = "Administrador",
    fecha_movimiento: Optional[str] = None,
    hora_movimiento: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    numero_recibo: Optional[str] = None,
    proveedor_id: Optional[int] = None,
    proveedor_nombre: Optional[str] = None
) -> Dict[str, Any]:
    """
    Registra una corrección controlada por DINERO DE MÁS (sobrante registrado erróneamente):
    1. Si está conectado al servidor API, registra la corrección en el endpoint central.
    2. Valida que el monto sea positivo y no supere el valor corregible de la liquidación.
    3. Registra el ajuste trazable en 'ajustes_liquidaciones_proveedores' sin borrar el movimiento original.
    4. Aplica contra-asiento en 'gastos' con valor negativo (-monto_sobrante) en la fecha contable del movimiento.
    5. Si fue pagado en Efectivo, genera el 'AJUSTE' de efectivo en caja para reponer el dinero.
    6. Reabre las cuentas por pagar del proveedor para restituir el saldo no liquidado realmente.
    7. Actualiza los saldos del proveedor mediante 'recalcular_saldo_proveedor'.
    8. Guarda auditoría inmutable de la corrección.
    """
    try:
        monto_sobrante_flt = round(float(monto_sobrante or 0.0), 2)
    except (ValueError, TypeError):
        monto_sobrante_flt = 0.0

    if monto_sobrante_flt <= 0:
        return {
            "exito": False,
            "ok": False,
            "mensaje": "El monto de dinero de más debe ser un valor numérico estrictamente mayor a 0."
        }

    f_mov_val = normalizar_fecha(fecha_movimiento) if fecha_movimiento else None
    h_mov_val = normalizar_hora(hora_movimiento) if hora_movimiento else None

    # 1. Si el API central está disponible y no se forzó conexión local explícita
    if conn is None and api is not None:
        try:
            if api.esta_disponible():
                target_api_id = str(numero_recibo or liquidacion_id).strip()
                resp = api.post(
                    f"/proveedores/liquidaciones/{target_api_id}/dinero-de-mas",
                    json={
                        "monto_sobrante": monto_sobrante_flt,
                        "motivo": motivo,
                        "fecha_movimiento": f_mov_val,
                        "hora_movimiento": h_mov_val,
                    },
                    timeout=7.0
                )
                if resp.status_code == 200:
                    res_api = resp.json()
                    res_api["exito"] = True
                    res_api["ok"] = True
                    try:
                        conn_loc = conectar_db()
                        _aplicar_dinero_de_mas_sqlite(
                            conn=conn_loc,
                            liquidacion_id=liquidacion_id,
                            monto_sobrante_flt=monto_sobrante_flt,
                            motivo=motivo,
                            usuario=usuario,
                            fecha_movimiento=f_mov_val,
                            hora_movimiento=h_mov_val,
                            numero_recibo=numero_recibo,
                            proveedor_id=proveedor_id,
                            proveedor_nombre=proveedor_nombre
                        )
                        conn_loc.commit()
                        conn_loc.close()
                    except Exception as e_loc_sync:
                        print(f"Aviso replicando dinero de más local: {e_loc_sync}")
                    return res_api
                elif 400 <= resp.status_code < 500:
                    det = resp.json().get("detail", resp.text) if hasattr(resp, "json") else resp.text
                    return {"exito": False, "ok": False, "mensaje": det}
        except Exception as e_api:
            print(f"Aviso registrando dinero de más en API: {e_api}")

    # 2. Modo local SQLite
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True

    if not conn:
        return {"exito": False, "ok": False, "mensaje": "No se pudo conectar a la base de datos."}

    try:
        res = _aplicar_dinero_de_mas_sqlite(
            conn=conn,
            liquidacion_id=liquidacion_id,
            monto_sobrante_flt=monto_sobrante_flt,
            motivo=motivo,
            usuario=usuario,
            fecha_movimiento=f_mov_val,
            hora_movimiento=h_mov_val,
            numero_recibo=numero_recibo,
            proveedor_id=proveedor_id,
            proveedor_nombre=proveedor_nombre
        )
        if cerrar_conn and res.get("exito"):
            conn.commit()
        return res
    except Exception as ex:
        if conn and cerrar_conn:
            conn.rollback()
        return {"exito": False, "ok": False, "mensaje": f"Error registrando dinero de más: {ex}"}
    finally:
        if cerrar_conn and conn:
            conn.close()


def obtener_historial_ajustes_proveedor(
    proveedor_id: Optional[int] = None,
    liquidacion_id: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None
) -> List[Dict[str, Any]]:
    """Consulta el historial de correcciones por dinero de más."""
    cerrar_conn = False
    if conn is None:
        conn = conectar_db()
        cerrar_conn = True
    if not conn:
        return []
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        query = """
            SELECT id, numero_ajuste, liquidacion_id, numero_recibo, proveedor_id,
                   proveedor_nombre, monto_ajuste, fecha_movimiento, hora_movimiento,
                   fecha_registro, usuario, motivo, estado, created_at
            FROM ajustes_liquidaciones_proveedores
            WHERE 1=1
        """
        params = []
        if liquidacion_id:
            query += " AND liquidacion_id = ?"
            params.append(liquidacion_id)
        if proveedor_id:
            query += " AND proveedor_id = ?"
            params.append(proveedor_id)
        query += " ORDER BY id DESC"
        cur.execute(query, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        if cerrar_conn and conn:
            conn.close()
