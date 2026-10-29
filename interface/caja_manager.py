#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivo: interface/caja_manager.py
Manejador centralizado de Control de Caja, Sesiones de Turno y Trazabilidad Financiera.
Regla de oro: Total Facturado != Dinero Real en Caja.
- Solo pagos y abonos en efectivo físico entran a movimientos_caja.
- Transferencias y Fiados no alteran la gaveta física.
"""

import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional
import os
import sys

try:
    from interface.database_manager import conectar_db
except ImportError:
    try:
        from database_manager import conectar_db
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from database_manager import conectar_db


def obtener_sesion_activa(conn: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    """Obtiene la sesión de caja actualmente abierta, o None si no hay ninguna."""
    owns_conn = conn is None
    if conn is None:
        conn = conectar_db()
        if not conn:
            return None
    try:
        prev_factory = conn.row_factory
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM sesiones_caja 
            WHERE estado = 'Abierta' 
            ORDER BY id DESC LIMIT 1
        """)
        row = cur.fetchone()
        conn.row_factory = prev_factory
        if row:
            return dict(row)
        return None
    finally:
        if owns_conn:
            conn.close()


def registrar_movimiento_financiero(
    tipo: str,
    concepto: str,
    monto: float,
    metodo_pago: str = "Efectivo",
    cuenta_afectada: str = "CAJA_FISICA", # 'CAJA_FISICA', 'BANCO_TRANSFERENCIA', 'CARTERA_CLIENTES', 'NINGUNA'
    usuario: str = "Administrador",
    referencia_origen: str = "",
    sesion_id: Optional[int] = None,
    observaciones: str = "",
    estado: str = "Activo",
    conn: Optional[sqlite3.Connection] = None,
    sincronizar_caja: bool = True
) -> int:
    """
    Registra un movimiento en el Libro Mayor Central Multicuenta (movimientos_financieros).
    Tipos permitidos:
    'VENTA_EFECTIVO', 'VENTA_TRANSFERENCIA', 'VENTA_CREDITO',
    'ABONO_EFECTIVO', 'ABONO_TRANSFERENCIA',
    'GASTO_PAGADO', 'PAGO_PROVEEDOR', 'RETIRO_CAJA',
    'INGRESO_EXTRAORDINARIO', 'DEVOLUCION_VENTA', 'AJUSTE_AUTORIZADO', 'APERTURA_CAJA'
    """
    owns_connection = conn is None
    if conn is None:
        conn = conectar_db()
        if not conn:
            raise RuntimeError("No se pudo conectar a la base de datos.")
    try:
        cur = conn.cursor()
        ahora = datetime.now()
        fecha_str = ahora.strftime("%Y-%m-%d")
        hora_str = ahora.strftime("%H:%M:%S")

        if not sesion_id and cuenta_afectada == "CAJA_FISICA":
            activa = obtener_sesion_activa(conn=conn)
            if activa:
                sesion_id = activa["id"]

        cur.execute("""
            INSERT INTO movimientos_financieros (
                fecha, hora, tipo, concepto, monto, metodo_pago,
                cuenta_afectada, usuario, referencia_origen, sesion_caja_id,
                estado, observaciones
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            fecha_str, hora_str, str(tipo), str(concepto), float(monto), str(metodo_pago),
            str(cuenta_afectada), str(usuario), str(referencia_origen or ""), sesion_id,
            str(estado), str(observaciones or "")
        ))
        mov_fin_id = cur.lastrowid

        # Si afecta la gaveta física de caja, sincronizar en movimientos_caja
        if cuenta_afectada == "CAJA_FISICA" and sincronizar_caja:
            tipo_caja_map = {
                "APERTURA_CAJA": "APERTURA",
                "VENTA_EFECTIVO": "VENTA_EFECTIVO",
                "ABONO_EFECTIVO": "ABONO_EFECTIVO",
                "GASTO_PAGADO": "EGRESO",
                "PAGO_PROVEEDOR": "EGRESO",
                "RETIRO_CAJA": "RETIRO",
                "INGRESO_EXTRAORDINARIO": "AJUSTE",
                "DEVOLUCION_VENTA": "DEVOLUCION_VENTA",
                "AJUSTE_AUTORIZADO": "AJUSTE"
            }
            t_caja = tipo_caja_map.get(tipo, "AJUSTE" if "INGRESO" in tipo else "EGRESO")
            registrar_movimiento_caja(
                tipo=t_caja,
                monto=float(monto),
                usuario=usuario,
                referencia_id=str(referencia_origen or mov_fin_id),
                descripcion=concepto,
                sesion_id=sesion_id,
                conn=conn,
                sincronizar_financiero=False
            )

        if owns_connection:
            conn.commit()
        return mov_fin_id
    finally:
        if owns_connection:
            conn.close()


def migrar_movimientos_historicos(conn: Optional[sqlite3.Connection] = None):
    """Puebla movimientos_financieros con datos históricos existentes si la tabla está vacía."""
    owns_conn = conn is None
    if conn is None:
        conn = conectar_db()
        if not conn:
            return
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM movimientos_financieros")
        if cur.fetchone()[0] > 0:
            return # Ya tiene datos, no duplicar

        # 1. Migrar desde movimientos_caja (Efectivo)
        cur.execute("PRAGMA table_info(movimientos_caja)")
        cols_m = [c[1] for c in cur.fetchall()]
        col_s = "sesion_id" if "sesion_id" in cols_m else "sesion_caja_id"
        col_c = "concepto" if "concepto" in cols_m else "descripcion"
        col_r = "id_referencia" if "id_referencia" in cols_m else "referencia_id"

        cur.execute(f"""
            SELECT id, {col_s}, fecha, hora, tipo, monto, usuario, {col_r}, {col_c}
            FROM movimientos_caja
            ORDER BY id ASC
        """)
        for r in cur.fetchall():
            m_id, s_id, f, h, t, val, u, ref, desc = r
            tipo_fin_map = {
                "APERTURA": "APERTURA_CAJA",
                "VENTA_EFECTIVO": "VENTA_EFECTIVO",
                "ABONO_EFECTIVO": "ABONO_EFECTIVO",
                "EGRESO": "GASTO_PAGADO",
                "RETIRO": "RETIRO_CAJA",
                "AJUSTE": "AJUSTE_AUTORIZADO",
                "DEVOLUCION_VENTA": "DEVOLUCION_VENTA"
            }
            tipo_f = tipo_fin_map.get(t, "AJUSTE_AUTORIZADO")
            cur.execute("""
                INSERT INTO movimientos_financieros (
                    fecha, hora, tipo, concepto, monto, metodo_pago,
                    cuenta_afectada, usuario, referencia_origen, sesion_caja_id,
                    estado, observaciones
                ) VALUES (?, ?, ?, ?, ?, 'Efectivo', 'CAJA_FISICA', ?, ?, ?, 'Activo', ?)
            """, (f, h, tipo_f, desc or f"Movimiento {t}", val, u or 'Administrador', str(ref or f"CAJA-{m_id}"), s_id, f"Migrado de movimientos_caja #{m_id}"))

        # 2. Migrar ventas por Transferencia y Fiado no reflejadas en movimientos_caja
        cur.execute("""
            SELECT id_venta, fecha_venta, hora_venta, total_venta, metodo_pago, operario, estado, sesion_caja_id
            FROM ventas
            WHERE metodo_pago IN ('Transferencia', 'Fiado')
            ORDER BY id_venta ASC
        """)
        for r in cur.fetchall():
            v_id, f, h, tot, met, op, est, s_id = r
            cta = "BANCO_TRANSFERENCIA" if met == "Transferencia" else "CARTERA_CLIENTES"
            tipo_f = "VENTA_TRANSFERENCIA" if met == "Transferencia" else "VENTA_CREDITO"
            estado_f = "Anulado" if est == "Anulada" else "Activo"
            cur.execute("""
                INSERT INTO movimientos_financieros (
                    fecha, hora, tipo, concepto, monto, metodo_pago,
                    cuenta_afectada, usuario, referencia_origen, sesion_caja_id,
                    estado, observaciones
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (f, h, tipo_f, f"Venta #{v_id} ({met})", tot, met, cta, op or 'Administrador', f"VENTA-{v_id}", s_id, estado_f, f"Migrado de ventas #{v_id}"))

        # 3. Migrar gastos no en efectivo
        cur.execute("PRAGMA table_info(gastos)")
        cols_g = [c[1] for c in cur.fetchall()]
        if "metodo_pago" in cols_g:
            cur.execute("""
                SELECT id_gasto, fecha, hora, concepto, valor, metodo_pago, estado, usuario
                FROM gastos
                WHERE metodo_pago = 'Transferencia' AND estado = 'Pagado'
                ORDER BY id_gasto ASC
            """)
            for r in cur.fetchall():
                g_id, f, h, conc, val, met, est, u = r
                cur.execute("""
                    INSERT INTO movimientos_financieros (
                        fecha, hora, tipo, concepto, monto, metodo_pago,
                        cuenta_afectada, usuario, referencia_origen, sesion_caja_id,
                        estado, observaciones
                    ) VALUES (?, ?, 'GASTO_PAGADO', ?, ?, 'Transferencia', 'BANCO_TRANSFERENCIA', ?, ?, NULL, 'Activo', ?)
                """, (f, h or '00:00:00', conc or f"Gasto #{g_id}", val, u or 'Administrador', f"GASTO-{g_id}", f"Migrado de gastos #{g_id}"))

        if owns_conn:
            conn.commit()
    finally:
        if owns_conn:
            conn.close()


def registrar_ingreso_autorizado(
    monto: float,
    motivo: str,
    usuario: str = "Administrador",
    sesion_id: Optional[int] = None
) -> int:
    """Registra una adición autorizada de efectivo a la gaveta de caja (e.g. sencillo o base adicional)."""
    if monto <= 0:
        raise ValueError("El monto del ingreso autorizado debe ser mayor a cero.")
    if not motivo or len(motivo.strip()) < 3:
        raise ValueError("Debe indicar un motivo o justificación del ingreso (mínimo 3 caracteres).")
    
    return registrar_movimiento_financiero(
        tipo="INGRESO_EXTRAORDINARIO",
        concepto=f"Ingreso autorizado: {motivo}",
        monto=monto,
        metodo_pago="Efectivo",
        cuenta_afectada="CAJA_FISICA",
        usuario=usuario,
        referencia_origen="INGRESO_MANUAL",
        sesion_id=sesion_id,
        observaciones=motivo
    )


def registrar_abono_cartera(
    cliente_id: int,
    monto: float,
    metodo: str = "Efectivo",
    metodo_pago: Optional[str] = None,
    usuario: str = "Administrador",
    observaciones: str = "",
    notas: Optional[str] = None,
    sesion_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Registra un abono a cartera de fiado de forma atómica.
    - Reduce el saldo_pendiente del cliente en clientes.
    - Registra el movimiento en movimientos_financieros (Efectivo -> CAJA_FISICA, Transferencia -> BANCO_TRANSFERENCIA).
    - Si es Efectivo, incrementa el efectivo esperado de la gaveta de caja.
    - NO registra una nueva venta en ventas (evita doble tributación / doble facturación).
    """
    if metodo_pago:
        metodo = metodo_pago
    if notas and not observaciones:
        observaciones = notas

    if monto <= 0:
        raise ValueError("El monto del abono debe ser mayor a cero.")

    conn = conectar_db()
    if not conn:
        raise RuntimeError("No se pudo conectar a la base de datos.")
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("PRAGMA table_info(clientes)")
        cols_c = [c[1] for c in cur.fetchall()]
        col_id = "id" if "id" in cols_c else "cliente_id"

        cur.execute(f"SELECT * FROM clientes WHERE {col_id} = ?", (cliente_id,))
        cli = cur.fetchone()
        if not cli:
            raise ValueError(f"Cliente #{cliente_id} no encontrado.")

        cli_dict = dict(cli)
        saldo_ant = float(cli_dict.get("saldo_pendiente", 0.0) or 0.0)
        nombre_cli = cli_dict.get("nombre", f"Cliente #{cliente_id}")

        if monto > (saldo_ant + 0.01):
            raise ValueError(f"El abono (${monto:,.0f}) excede el saldo pendiente (${saldo_ant:,.0f}).")

        saldo_nuevo = max(0.0, saldo_ant - monto)
        cur.execute(f"UPDATE clientes SET saldo_pendiente = ? WHERE {col_id} = ?", (saldo_nuevo, cliente_id))

        # Aplicar reducción FIFO al saldo_pendiente de las ventas fiadas de este cliente
        try:
            cur.execute("PRAGMA table_info(ventas)")
            v_cols = [c[1] for c in cur.fetchall()]
            if "saldo_pendiente" not in v_cols:
                cur.execute("ALTER TABLE ventas ADD COLUMN saldo_pendiente REAL DEFAULT 0.0")
            doc_cli = str(cli_dict.get("cedula") or cli_dict.get("documento") or "").strip()
            cur.execute("""
                SELECT id_venta, total_venta, saldo_pendiente
                FROM ventas
                WHERE metodo_pago = 'Fiado'
                  AND (estado IS NULL OR estado != 'Anulada')
                  AND (documento_cliente = ? OR documento_cliente = ? OR LOWER(documento_cliente) = LOWER(?))
                ORDER BY fecha_venta ASC, id_venta ASC
            """, (doc_cli, str(cliente_id), str(nombre_cli)))
            ventas_fiadas = cur.fetchall()
            remanente_ab = float(monto)
            for vf in ventas_fiadas:
                if remanente_ab <= 0.001:
                    break
                vid = vf["id_venta"]
                sp_actual = vf["saldo_pendiente"]
                sp_val = float(sp_actual) if (sp_actual is not None and float(sp_actual) > 0) else float(vf["total_venta"] or 0.0)
                if sp_val <= 0.001:
                    continue
                descuento_v = min(remanente_ab, sp_val)
                nuevo_sp_v = round(max(0.0, sp_val - descuento_v), 2)
                cur.execute("UPDATE ventas SET saldo_pendiente = ? WHERE id_venta = ?", (nuevo_sp_v, vid))
                remanente_ab = round(remanente_ab - descuento_v, 2)
        except Exception as e_fifo:
            print(f"Aviso aplicando FIFO en abono de ventas fiadas: {e_fifo}")

        conn.commit()
        cuenta = "CAJA_FISICA" if metodo == "Efectivo" else "BANCO_TRANSFERENCIA"
        tipo_mov = "ABONO_EFECTIVO" if metodo == "Efectivo" else "ABONO_TRANSFERENCIA"

        mov_id = registrar_movimiento_financiero(
            tipo=tipo_mov,
            concepto=f"Abono a deuda cliente: {nombre_cli}",
            monto=monto,
            metodo_pago=metodo,
            cuenta_afectada=cuenta,
            usuario=usuario,
            referencia_origen=f"CLIENTE-{cliente_id}",
            sesion_id=sesion_id,
            observaciones=observaciones,
            conn=conn,
            sincronizar_caja=(metodo == "Efectivo")
        )

        conn.commit()
        return {
            "ok": True,
            "exito": True,
            "movimiento_id": mov_id,
            "cliente_id": cliente_id,
            "nombre": nombre_cli,
            "saldo_anterior": saldo_ant,
            "monto_abonado": monto,
            "saldo_nuevo": saldo_nuevo,
            "nuevo_saldo": saldo_nuevo,
            "metodo": metodo
        }
    finally:
        conn.close()


def obtener_cierres_anteriores(limit: int = 50) -> List[Dict[str, Any]]:
    """Consulta el historial inmutable de turnos de caja cerrados."""
    conn = conectar_db()
    if not conn:
        return []
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(sesiones_caja)")
        cols_s = [c[1] for c in cur.fetchall()]
        col_esp = "monto_esperado_efectivo" if "monto_esperado_efectivo" in cols_s else "monto_esperado"
        col_base = "monto_base" if "monto_base" in cols_s else "monto_inicial"

        cur.execute(f"""
            SELECT 
                id, fecha_apertura, hora_apertura, usuario_apertura,
                COALESCE({col_base}, 0.0) as base_inicial,
                fecha_cierre, hora_cierre, usuario_cierre,
                COALESCE({col_esp}, 0.0) as monto_esperado,
                COALESCE(monto_real_contado, 0.0) as monto_real_contado,
                COALESCE(diferencia, 0.0) as diferencia,
                COALESCE(observaciones, '') as observaciones,
                COALESCE(monto_transferencias_esperado, 0.0) as transferencias_esperadas,
                COALESCE(monto_transferencias_verificado, 0.0) as transferencias_verificadas,
                COALESCE(diferencia_banco, 0.0) as diferencia_banco,
                COALESCE(estado_banco, 'Pendiente') as estado_banco
            FROM sesiones_caja
            WHERE estado = 'Cerrada'
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def abrir_sesion_caja(
    usuario: str = "Administrador",
    monto_inicial: float = 0.0,
    terminal: str = "Terminal-1",
    monto_base: Optional[float] = None,
    conn: Optional[sqlite3.Connection] = None
) -> int:
    """Abre un nuevo turno de caja con una base inicial de efectivo."""
    if monto_base is not None:
        monto_inicial = monto_base
    owns_conn = conn is None
    if conn is None:
        conn = conectar_db()
        if not conn:
            raise RuntimeError("No se pudo conectar a la base de datos.")
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM sesiones_caja WHERE estado = 'Abierta' LIMIT 1")
        row = cur.fetchone()
        if row:
            return row[0]

        ahora = datetime.now()
        fecha_str = ahora.strftime("%Y-%m-%d")
        hora_str = ahora.strftime("%H:%M:%S")

        cur.execute("PRAGMA table_info(sesiones_caja)")
        cols_s = [c[1] for c in cur.fetchall()]
        col_monto = "monto_base" if "monto_base" in cols_s else "monto_inicial"

        cur.execute(f"""
            INSERT INTO sesiones_caja (
                fecha_apertura, hora_apertura, usuario_apertura, {col_monto}, estado
            ) VALUES (?, ?, ?, ?, 'Abierta')
        """, (fecha_str, hora_str, usuario, float(monto_inicial)))
        sesion_id = cur.lastrowid

        # Registrar movimiento de apertura en libro mayor de caja física
        cur.execute("PRAGMA table_info(movimientos_caja)")
        cols_m = [c[1] for c in cur.fetchall()]
        col_sesion = "sesion_id" if "sesion_id" in cols_m else "sesion_caja_id"
        col_concepto = "concepto" if "concepto" in cols_m else "descripcion"

        if "terminal" in cols_m:
            cur.execute(f"""
                INSERT INTO movimientos_caja (
                    {col_sesion}, fecha, hora, tipo, monto, usuario, terminal, {col_concepto}
                ) VALUES (?, ?, ?, 'APERTURA', ?, ?, ?, 'Apertura de turno con base inicial')
            """, (sesion_id, fecha_str, hora_str, float(monto_inicial), usuario, terminal))
        else:
            cur.execute(f"""
                INSERT INTO movimientos_caja (
                    {col_sesion}, fecha, hora, tipo, monto, usuario, {col_concepto}
                ) VALUES (?, ?, ?, 'APERTURA', ?, ?, 'Apertura de turno con base inicial')
            """, (sesion_id, fecha_str, hora_str, float(monto_inicial), usuario))

        # Registrar en libro mayor central multicuenta
        try:
            cur.execute("""
                INSERT INTO movimientos_financieros (
                    fecha, hora, tipo, concepto, monto, metodo_pago,
                    cuenta_afectada, usuario, referencia_origen, sesion_caja_id,
                    estado, observaciones
                ) VALUES (?, ?, 'APERTURA_CAJA', 'Apertura de turno con base inicial', ?, 'Efectivo',
                          'CAJA_FISICA', ?, ?, ?, 'Activo', 'Base inicial de gaveta')
            """, (fecha_str, hora_str, float(monto_inicial), usuario, f"SESION-{sesion_id}", sesion_id))
        except Exception:
            pass

        if owns_conn:
            conn.commit()
        return sesion_id
    finally:
        if owns_conn:
            conn.close()


def registrar_movimiento_caja(
    tipo: str,
    monto: float = 0.0,
    usuario: str = "Administrador",
    terminal: str = "Terminal-1",
    referencia_id: Optional[str] = None,
    descripcion: str = "",
    sesion_id: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
    concepto: Optional[str] = None,
    id_referencia: Optional[Any] = None,
    sincronizar_financiero: bool = True
) -> int:
    """
    Registra un movimiento en el libro mayor de caja física.
    Tipos permitidos:
    'APERTURA', 'VENTA_EFECTIVO', 'ABONO_EFECTIVO', 'EGRESO', 'RETIRO', 'AJUSTE', 'DEVOLUCION_VENTA', 'CIERRE'
    """
    if concepto and not descripcion:
        descripcion = concepto
    if id_referencia is not None and not referencia_id:
        referencia_id = str(id_referencia)

    owns_connection = conn is None
    if conn is None:
        conn = conectar_db()
        if not conn:
            raise RuntimeError("No se pudo conectar a la base de datos.")
    try:
        cur = conn.cursor()
        if not sesion_id:
            activa = obtener_sesion_activa(conn=conn)
            if activa:
                sesion_id = activa["id"]
            else:
                sesion_id = abrir_sesion_caja(usuario=usuario, monto_inicial=0.0, terminal=terminal, conn=conn)

        ahora = datetime.now()
        fecha_str = ahora.strftime("%Y-%m-%d")
        hora_str = ahora.strftime("%H:%M:%S")

        cur.execute("PRAGMA table_info(movimientos_caja)")
        cols_m = [c[1] for c in cur.fetchall()]
        col_sesion = "sesion_id" if "sesion_id" in cols_m else "sesion_caja_id"
        col_concepto = "concepto" if "concepto" in cols_m else "descripcion"
        col_ref = "id_referencia" if "id_referencia" in cols_m else "referencia_id"

        if "terminal" in cols_m:
            cur.execute(f"""
                INSERT INTO movimientos_caja (
                    {col_sesion}, fecha, hora, tipo, monto, usuario, terminal, {col_ref}, {col_concepto}
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (sesion_id, fecha_str, hora_str, tipo, float(monto), usuario, terminal, str(referencia_id or ""), descripcion))
        else:
            cur.execute(f"""
                INSERT INTO movimientos_caja (
                    {col_sesion}, fecha, hora, tipo, monto, usuario, {col_ref}, {col_concepto}
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (sesion_id, fecha_str, hora_str, tipo, float(monto), usuario, str(referencia_id or ""), descripcion))

        mov_id = cur.lastrowid

        # Sincronización en movimientos_financieros si fue llamada directamente
        if sincronizar_financiero and tipo != "CIERRE":
            tipo_fin_map = {
                "APERTURA": "APERTURA_CAJA",
                "VENTA_EFECTIVO": "VENTA_EFECTIVO",
                "ABONO_EFECTIVO": "ABONO_EFECTIVO",
                "EGRESO": "GASTO_PAGADO",
                "RETIRO": "RETIRO_CAJA",
                "AJUSTE": "AJUSTE_AUTORIZADO",
                "DEVOLUCION_VENTA": "DEVOLUCION_VENTA"
            }
            tipo_f = tipo_fin_map.get(tipo, "AJUSTE_AUTORIZADO")
            try:
                cur.execute("""
                    INSERT INTO movimientos_financieros (
                        fecha, hora, tipo, concepto, monto, metodo_pago,
                        cuenta_afectada, usuario, referencia_origen, sesion_caja_id,
                        estado, observaciones
                    ) VALUES (?, ?, ?, ?, ?, 'Efectivo', 'CAJA_FISICA', ?, ?, ?, 'Activo', ?)
                """, (
                    fecha_str, hora_str, tipo_f, descripcion or f"Movimiento {tipo}",
                    float(monto), usuario, str(referencia_id or mov_id),
                    sesion_id, f"Sincronizado desde caja física #{mov_id}"
                ))
            except Exception:
                pass

        if owns_connection:
            conn.commit()
        return mov_id
    finally:
        if owns_connection:
            conn.close()


def calcular_arqueo_sesion(sesion_id: int) -> Dict[str, Any]:
    """Calcula el balance y efectivo esperado de una sesión de caja específica."""
    conn = conectar_db()
    if not conn:
        return {}
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Datos de la sesión
        cur.execute("SELECT * FROM sesiones_caja WHERE id = ?", (sesion_id,))
        sesion = cur.fetchone()
        if not sesion:
            return {}

        sesion_dict = dict(sesion)
        monto_inicial = float(sesion_dict.get("monto_inicial", sesion_dict.get("monto_base", 0.0)) or 0.0)

        # Movimientos de caja física
        cur.execute("PRAGMA table_info(movimientos_caja)")
        cols_m = [c[1] for c in cur.fetchall()]
        col_sesion = "sesion_id" if "sesion_id" in cols_m else "sesion_caja_id"

        cur.execute(f"""
            SELECT tipo, SUM(monto) as total
            FROM movimientos_caja
            WHERE {col_sesion} = ?
            GROUP BY tipo
        """, (sesion_id,))
        movs = {r["tipo"]: float(r["total"] or 0.0) for r in cur.fetchall()}

        ventas_efectivo = movs.get("VENTA_EFECTIVO", 0.0)
        abonos_efectivo = movs.get("ABONO_EFECTIVO", 0.0)
        egresos = movs.get("EGRESO", 0.0)
        retiros = movs.get("RETIRO", 0.0)
        devoluciones = movs.get("DEVOLUCION_VENTA", 0.0)
        ajustes = movs.get("AJUSTE", 0.0)

        # Efectivo esperado físico en gaveta
        efectivo_esperado = monto_inicial + ventas_efectivo + abonos_efectivo - egresos - retiros - devoluciones + ajustes

        # Ventas por otros métodos durante esta sesión
        cur.execute("""
            SELECT metodo_pago, SUM(total_venta) as total, COUNT(id_venta) as cant
            FROM ventas
            WHERE (sesion_caja_id = ? OR (fecha_venta = ? AND estado != 'Anulada'))
              AND estado != 'Anulada'
            GROUP BY metodo_pago
        """, (sesion_id, sesion_dict["fecha_apertura"]))
        ventas_metodos = {r["metodo_pago"]: {"total": float(r["total"] or 0.0), "cant": int(r["cant"])} for r in cur.fetchall()}

        transf_info = ventas_metodos.get("Transferencia", {"total": 0.0, "cant": 0})
        fiado_info = ventas_metodos.get("Fiado", {"total": 0.0, "cant": 0})
        efectivo_ventas_info = ventas_metodos.get("Efectivo", {"total": ventas_efectivo, "cant": 0})

        # Abonos y gastos bancarios por transferencia en esta sesión
        abonos_transferencia = 0.0
        gastos_transferencia = 0.0
        try:
            cur.execute("""
                SELECT tipo, COALESCE(SUM(monto), 0.0) as total
                FROM movimientos_financieros
                WHERE (sesion_caja_id = ? OR fecha = ?)
                  AND cuenta_afectada = 'BANCO_TRANSFERENCIA'
                  AND estado != 'Anulado'
                GROUP BY tipo
            """, (sesion_id, sesion_dict["fecha_apertura"]))
            b_movs = {r["tipo"]: float(r["total"]) for r in cur.fetchall()}
            abonos_transferencia = b_movs.get("ABONO_TRANSFERENCIA", 0.0)
            gastos_transferencia = b_movs.get("GASTO_PAGADO", 0.0)
        except Exception:
            pass

        # Saldo global de cartera y fiados
        cur.execute("SELECT COALESCE(SUM(saldo_pendiente), 0.0) as saldo_cartera FROM clientes WHERE saldo_pendiente > 0")
        saldo_cartera_total = float(cur.fetchone()["saldo_cartera"] or 0.0)

        total_ventas_facturadas = efectivo_ventas_info["total"] + transf_info["total"] + fiado_info["total"]
        entradas_efectivo = ventas_efectivo + abonos_efectivo + (ajustes if ajustes > 0 else 0.0)
        salidas_efectivo = egresos + retiros + devoluciones + (abs(ajustes) if ajustes < 0 else 0.0)
        transferencias_esperadas = transf_info["total"] + abonos_transferencia - gastos_transferencia

        return {
            "sesion": sesion_dict,
            "monto_inicial": monto_inicial,
            "monto_base": monto_inicial,
            "entradas_efectivo": entradas_efectivo,
            "salidas_efectivo": salidas_efectivo,
            "ventas_efectivo": ventas_efectivo,
            "abonos_efectivo": abonos_efectivo,
            "ingresos_autorizados": (ajustes if ajustes > 0 else 0.0),
            "egresos": egresos,
            "retiros": retiros,
            "devoluciones": devoluciones,
            "ajustes": ajustes,
            "efectivo_esperado": efectivo_esperado,
            "monto_esperado_efectivo": efectivo_esperado,
            "monto_esperado": efectivo_esperado,
            "ventas_transferencia": transf_info["total"],
            "abonos_transferencia": abonos_transferencia,
            "gastos_transferencia": gastos_transferencia,
            "transferencias_esperadas": transferencias_esperadas,
            "total_transferencia": transf_info["total"],
            "ventas_fiado": fiado_info["total"],
            "total_ventas_facturadas": total_ventas_facturadas,
            "saldo_cartera_total": saldo_cartera_total
        }
    finally:
        conn.close()


def cerrar_sesion_caja(
    sesion_id: int,
    usuario: str = "Administrador",
    monto_real_contado: Optional[float] = None,
    observaciones: str = "",
    monto_real_efectivo: Optional[float] = None,
    terminal: str = "Terminal-1",
    monto_transferencias_verificado: Optional[float] = None
) -> Dict[str, Any]:
    """Cierra formalmente el turno de caja, registrando el arqueo y la diferencia (faltante/sobrante)."""
    if monto_real_contado is None:
        monto_real_contado = monto_real_efectivo if monto_real_efectivo is not None else 0.0

    arqueo = calcular_arqueo_sesion(sesion_id)
    if not arqueo:
        raise ValueError(f"No se encontró la sesión de caja {sesion_id}")

    efectivo_esperado = arqueo["efectivo_esperado"]
    diferencia = float(monto_real_contado) - efectivo_esperado
    transf_esperadas = arqueo.get("transferencias_esperadas", arqueo.get("ventas_transferencia", 0.0))

    transf_verificadas = monto_transferencias_verificado if monto_transferencias_verificado is not None else transf_esperadas
    dif_banco = float(transf_verificadas) - transf_esperadas
    estado_banco = "Verificada" if abs(dif_banco) < 0.01 else "Con diferencia"

    conn = conectar_db()
    if not conn:
        raise RuntimeError("No se pudo conectar a la base de datos.")
    try:
        cur = conn.cursor()
        ahora = datetime.now()
        fecha_str = ahora.strftime("%Y-%m-%d")
        hora_str = ahora.strftime("%H:%M:%S")

        cur.execute("PRAGMA table_info(sesiones_caja)")
        cols_s = [c[1] for c in cur.fetchall()]
        col_esp = "monto_esperado_efectivo" if "monto_esperado_efectivo" in cols_s else "monto_esperado"

        cur.execute(f"""
            UPDATE sesiones_caja SET
                estado = 'Cerrada',
                fecha_cierre = ?,
                hora_cierre = ?,
                usuario_cierre = ?,
                {col_esp} = ?,
                monto_real_contado = ?,
                diferencia = ?,
                observaciones = ?,
                monto_transferencias_esperado = ?,
                monto_transferencias_verificado = ?,
                diferencia_banco = ?,
                estado_banco = ?
            WHERE id = ?
        """, (
            fecha_str, hora_str, usuario,
            efectivo_esperado, float(monto_real_contado), diferencia,
            observaciones,
            transf_esperadas, float(transf_verificadas), dif_banco, estado_banco,
            sesion_id
        ))

        # Registrar movimiento de cierre
        cur.execute("PRAGMA table_info(movimientos_caja)")
        cols_m = [c[1] for c in cur.fetchall()]
        col_sesion = "sesion_id" if "sesion_id" in cols_m else "sesion_caja_id"
        col_concepto = "concepto" if "concepto" in cols_m else "descripcion"

        if "terminal" in cols_m:
            cur.execute(f"""
                INSERT INTO movimientos_caja (
                    {col_sesion}, fecha, hora, tipo, monto, usuario, terminal, {col_concepto}
                ) VALUES (?, ?, ?, 'CIERRE', ?, ?, 'Terminal-1', ?)
            """, (sesion_id, fecha_str, hora_str, float(monto_real_contado), usuario, f"Cierre de caja. Diferencia: {diferencia:+,.0f} COP"))
        else:
            cur.execute(f"""
                INSERT INTO movimientos_caja (
                    {col_sesion}, fecha, hora, tipo, monto, usuario, {col_concepto}
                ) VALUES (?, ?, ?, 'CIERRE', ?, ?, ?)
            """, (sesion_id, fecha_str, hora_str, float(monto_real_contado), usuario, f"Cierre de caja. Diferencia: {diferencia:+,.0f} COP"))

        conn.commit()
        tipo_dif = "Cuadrada" if abs(diferencia) < 0.01 else ("Faltante" if diferencia < 0 else "Sobrante")
        estado_cierre = "CUADRADA" if abs(diferencia) < 0.01 else ("CON_FALTANTE" if diferencia < 0 else "CON_SOBRANTE")
        return {
            "sesion_id": sesion_id,
            "efectivo_esperado": efectivo_esperado,
            "monto_esperado": efectivo_esperado,
            "monto_real_contado": monto_real_contado,
            "monto_real_efectivo": monto_real_contado,
            "diferencia": diferencia,
            "diferencia_efectivo": diferencia,
            "estado": "Cerrada",
            "tipo_diferencia": tipo_dif,
            "estado_cierre": estado_cierre
        }
    finally:
        conn.close()


def anular_venta_completa(
    id_venta: int,
    usuario_admin: str = "Administrador",
    motivo: str = "Anulación administrativa",
    terminal: str = "Terminal-1",
    usuario: Optional[str] = None
) -> Dict[str, Any]:
    """
    Anula una venta con reversión atómica de inventario, caja/fiado, comisiones y registro en auditoría.
    PROHIBIDO hacer DELETE FROM ventas.
    """
    if usuario:
        usuario_admin = usuario

    if not motivo or len(motivo.strip()) < 3:
        raise ValueError("El motivo de anulación es obligatorio (mínimo 3 caracteres).")

    conn = conectar_db()
    if not conn:
        raise RuntimeError("No se pudo conectar a la base de datos.")
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 1. Obtener la venta
        cur.execute("SELECT * FROM ventas WHERE id_venta = ?", (id_venta,))
        venta = cur.fetchone()
        if not venta:
            raise ValueError(f"No existe la venta #{id_venta}")

        venta_dict = dict(venta)
        if venta_dict.get("estado") == "Anulada":
            raise ValueError(f"La venta #{id_venta} ya se encuentra anulada.")

        ahora = datetime.now()
        fecha_str = ahora.strftime("%Y-%m-%d")
        hora_str = ahora.strftime("%H:%M:%S")
        total_venta = float(venta_dict["total_venta"])
        metodo_pago = venta_dict.get("metodo_pago", "Efectivo")
        doc_cliente = venta_dict.get("documento_cliente", "")
        operario = venta_dict.get("operario", "")

        # 2. Revertir inventario de los productos de la venta
        cur.execute("SELECT * FROM detalle_ventas WHERE id_venta = ?", (id_venta,))
        detalles = [dict(r) for r in cur.fetchall()]

        ahora_dt = datetime.now()
        f_hoy = ahora_dt.strftime("%Y-%m-%d")
        h_hoy = ahora_dt.strftime("%H:%M:%S")

        for item in detalles:
            cod = item.get("codigo_producto", item.get("codigo"))
            cant = int(item.get("cantidad", 1))
            nom_it = item.get("nombre_producto", item.get("nombre", cod))
            costo_it = float(item.get("costo_unitario", 0.0) or 0.0)
            if cod:
                cur.execute("SELECT * FROM productos WHERE codigo = ?", (cod,))
                p = cur.fetchone()
                if p:
                    p_dict = dict(p)
                    tipo = p_dict.get("tipo_producto", p_dict.get("tipo", "Producto"))
                    if tipo != "Servicio":
                        sv_ant = float(p_dict.get("stock_vitrina", 0.0) or 0.0)
                        sb_ant = float(p_dict.get("stock_bodega", 0.0) or 0.0)
                        st_ant = float(p_dict.get("stock", 0.0) or 0.0)
                        if sb_ant == 0.0 and sv_ant == 0.0 and st_ant > 0:
                            sb_ant = st_ant
                        u_med = str(p_dict.get("unidad_medida", "Unidad") or "Unidad")
                        sv_des = sv_ant + cant
                        st_des = sb_ant + sv_des
                        cur.execute("UPDATE productos SET stock_bodega = ?, stock_vitrina = ?, stock = ? WHERE codigo = ?", (sb_ant, sv_des, st_des, cod))

                        # Registrar en Kárdex
                        usuario_kardex = usuario or "Administrador"
                        try:
                            cur.execute("""
                                INSERT INTO movimientos_inventario (
                                    fecha, hora, producto_id, codigo_producto, nombre_producto,
                                    tipo_movimiento, cantidad, unidad_medida, ubicacion_origen,
                                    ubicacion_destino, stock_origen_ant, stock_origen_des,
                                    stock_destino_ant, stock_destino_des, costo_unitario, valor_total,
                                    referencia, usuario, observaciones, estado
                                ) VALUES (?, ?, ?, ?, ?, 'DEVOLUCION_VENTA', ?, ?, 'CLIENTE', 'VITRINA', 0, 0, ?, ?, ?, ?, ?, ?, ?, 'Completado')
                            """, (
                                f_hoy, h_hoy, p_dict["id"], cod, nom_it,
                                cant, u_med, sv_ant, sv_des, costo_it, costo_it * cant,
                                f"ANULACION-VENTA-{id_venta}", usuario_kardex, f"Anulación de venta #{id_venta}: {motivo}"
                            ))
                        except Exception as e_kardex:
                            print(f"Aviso registrando devolución kárdex: {e_kardex}")

        # 3. Reversión de impacto financiero
        # Solo impactar la gaveta física si la venta original ingresó a una sesión de caja
        venta_sesion_id = venta_dict.get("sesion_caja_id")
        activa = obtener_sesion_activa()
        sesion_id = (activa["id"] if activa else venta_sesion_id) if venta_sesion_id else None

        if metodo_pago == "Efectivo":
            # Devolución de dinero de la gaveta de caja física
            if sesion_id:
                cur.execute("PRAGMA table_info(movimientos_caja)")
                cols_m = [c[1] for c in cur.fetchall()]
                col_sesion = "sesion_id" if "sesion_id" in cols_m else "sesion_caja_id"
                col_concepto = "concepto" if "concepto" in cols_m else "descripcion"
                col_ref = "id_referencia" if "id_referencia" in cols_m else "referencia_id"

                if "terminal" in cols_m:
                    cur.execute(f"""
                        INSERT INTO movimientos_caja (
                            {col_sesion}, fecha, hora, tipo, monto, usuario, terminal, {col_ref}, {col_concepto}
                        ) VALUES (?, ?, ?, 'DEVOLUCION_VENTA', ?, ?, ?, ?, ?)
                    """, (
                        sesion_id, fecha_str, hora_str, total_venta, usuario_admin, terminal,
                        str(id_venta), f"Devolución en efectivo por anulación de Venta #{id_venta}: {motivo}"
                    ))
                else:
                    cur.execute(f"""
                        INSERT INTO movimientos_caja (
                            {col_sesion}, fecha, hora, tipo, monto, usuario, {col_ref}, {col_concepto}
                        ) VALUES (?, ?, ?, 'DEVOLUCION_VENTA', ?, ?, ?, ?)
                    """, (
                        sesion_id, fecha_str, hora_str, total_venta, usuario_admin,
                        str(id_venta), f"Devolución en efectivo por anulación de Venta #{id_venta}: {motivo}"
                    ))

            try:
                cur.execute("""
                    INSERT INTO movimientos_financieros (
                        fecha, hora, tipo, concepto, monto, metodo_pago,
                        cuenta_afectada, usuario, referencia_origen, sesion_caja_id,
                        estado, observaciones
                    ) VALUES (?, ?, 'DEVOLUCION_VENTA', ?, ?, 'Efectivo', 'CAJA_FISICA', ?, ?, ?, 'Activo', ?)
                """, (
                    fecha_str, hora_str, f"Devolución en efectivo Venta #{id_venta}: {motivo}",
                    total_venta, usuario_admin, f"VENTA-{id_venta}", sesion_id, motivo
                ))
            except Exception:
                pass

        elif metodo_pago == "Transferencia":
            try:
                cur.execute("""
                    INSERT INTO movimientos_financieros (
                        fecha, hora, tipo, concepto, monto, metodo_pago,
                        cuenta_afectada, usuario, referencia_origen, sesion_caja_id,
                        estado, observaciones
                    ) VALUES (?, ?, 'DEVOLUCION_VENTA', ?, ?, 'Transferencia', 'BANCO_TRANSFERENCIA', ?, ?, ?, 'Activo', ?)
                """, (
                    fecha_str, hora_str, f"Reversión recaudo transferencia Venta #{id_venta}: {motivo}",
                    total_venta, usuario_admin, f"VENTA-{id_venta}", sesion_id, motivo
                ))
            except Exception:
                pass

        elif metodo_pago == "Fiado":
            # Revertir saldo pendiente del cliente
            if doc_cliente:
                cur.execute("PRAGMA table_info(clientes)")
                cols_c = [c[1] for c in cur.fetchall()]
                col_doc = "documento" if "documento" in cols_c else "cedula"
                cur.execute(f"""
                    UPDATE clientes 
                    SET saldo_pendiente = MAX(0.0, saldo_pendiente - ?) 
                    WHERE {col_doc} = ?
                """, (total_venta, doc_cliente))

            try:
                cur.execute("""
                    INSERT INTO movimientos_financieros (
                        fecha, hora, tipo, concepto, monto, metodo_pago,
                        cuenta_afectada, usuario, referencia_origen, sesion_caja_id,
                        estado, observaciones
                    ) VALUES (?, ?, 'AJUSTE_AUTORIZADO', ?, ?, 'Fiado', 'CARTERA_CLIENTES', ?, ?, ?, 'Activo', ?)
                """, (
                    fecha_str, hora_str, f"Anulación crédito Venta #{id_venta}: {motivo}",
                    total_venta, usuario_admin, f"VENTA-{id_venta}", sesion_id, motivo
                ))
            except Exception:
                pass

        # Marcar movimientos originales de la venta como Anulados
        try:
            cur.execute("""
                UPDATE movimientos_financieros 
                SET estado = 'Anulado', observaciones = observaciones || ' | Venta anulada: ' || ?
                WHERE referencia_origen = ?
            """, (motivo, f"VENTA-{id_venta}"))
        except Exception:
            pass

        # 4. Actualizar estado de la venta (y limpiar saldo_pendiente si era Fiado)
        cur.execute("PRAGMA table_info(ventas)")
        v_cols_an = [c[1] for c in cur.fetchall()]
        if "saldo_pendiente" in v_cols_an:
            cur.execute("""
                UPDATE ventas SET
                    estado = 'Anulada',
                    saldo_pendiente = 0.0,
                    motivo_anulacion = ?,
                    anulado_por = ?,
                    fecha_anulacion = ?
                WHERE id_venta = ?
            """, (motivo, usuario_admin, f"{fecha_str} {hora_str}", id_venta))
        else:
            cur.execute("""
                UPDATE ventas SET
                    estado = 'Anulada',
                    motivo_anulacion = ?,
                    anulado_por = ?,
                    fecha_anulacion = ?
                WHERE id_venta = ?
            """, (motivo, usuario_admin, f"{fecha_str} {hora_str}", id_venta))

        # 5. Registrar en auditoría
        cur.execute("PRAGMA table_info(auditoria_ventas)")
        cols_a = [c[1] for c in cur.fetchall()]
        if "terminal" in cols_a:
            cur.execute("""
                INSERT INTO auditoria_ventas (
                    id_venta, numero_venta, accion, usuario, fecha, hora, terminal, motivo, valor_anterior, valor_nuevo, detalles_json
                ) VALUES (?, ?, 'ANULACION', ?, ?, ?, ?, ?, ?, 0.0, ?)
            """, (
                id_venta, f"V-{id_venta:06d}", usuario_admin, fecha_str, hora_str, terminal,
                motivo, total_venta, str(detalles)
            ))
        else:
            cur.execute("""
                INSERT INTO auditoria_ventas (
                    id_venta, accion, usuario, fecha, hora, motivo, detalles_json, valor_anterior, valor_nuevo
                ) VALUES (?, 'ANULACION', ?, ?, ?, ?, ?, ?, 0.0)
            """, (
                id_venta, usuario_admin, fecha_str, hora_str, motivo, str(detalles), total_venta
            ))

        # 6. Revertir cuentas por pagar a proveedores vinculadas a servicios de la venta
        try:
            try:
                from proveedores_manager import revertir_cxp_por_venta_anulada
            except ImportError:
                from interface.proveedores_manager import revertir_cxp_por_venta_anulada
            revertir_cxp_por_venta_anulada(
                id_venta=id_venta,
                motivo=motivo,
                usuario_admin=usuario_admin,
                conn=conn
            )
        except Exception as e_rev_cxp:
            print(f"Aviso revirtiendo cuentas por pagar a proveedor en anulación: {e_rev_cxp}")

        conn.commit()

        # 7. Revertir devengos de nómina y comisiones de forma trazable e idempotente
        try:
            try:
                from nomina_manager import revertir_devengos_por_venta_anulada
            except ImportError:
                from interface.nomina_manager import revertir_devengos_por_venta_anulada
            revertir_devengos_por_venta_anulada(
                id_venta=id_venta,
                usuario_responsable=usuario_admin,
                motivo=motivo
            )
        except Exception as e_rev_nom:
            print(f"Aviso revirtiendo devengos de nómina en anulación: {e_rev_nom}")

        return {
            "ok": True,
            "exito": True,
            "success": True,
            "id_venta": id_venta,
            "total_anulado": total_venta,
            "metodo_pago": metodo_pago,
            "motivo": motivo,
            "usuario": usuario_admin
        }
    finally:
        conn.close()


def editar_venta_completa(
    id_venta: int,
    usuario_admin: str = "Administrador",
    nuevo_metodo: str = "Efectivo",
    nuevos_items: Optional[List[Dict[str, Any]]] = None,
    motivo: str = "Edición administrativa",
    terminal: str = "Terminal-1",
    usuario: Optional[str] = None
) -> Dict[str, Any]:
    """
    Edita una venta con cálculo atómico de diferencias (delta inventario, delta caja/fiado) y auditoría completa.
    """
    if usuario:
        usuario_admin = usuario
    if nuevos_items is None:
        nuevos_items = []

    if not motivo or len(motivo.strip()) < 3:
        raise ValueError("El motivo de edición es obligatorio (mínimo 3 caracteres).")

    conn = conectar_db()
    if not conn:
        raise RuntimeError("No se pudo conectar a la base de datos.")
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 1. Obtener venta original
        cur.execute("SELECT * FROM ventas WHERE id_venta = ?", (id_venta,))
        venta = cur.fetchone()
        if not venta:
            raise ValueError(f"No existe la venta #{id_venta}")

        venta_dict = dict(venta)
        if venta_dict.get("estado") == "Anulada":
            raise ValueError(f"No se puede editar la venta #{id_venta} porque está anulada.")

        total_anterior = float(venta_dict["total_venta"])
        metodo_anterior = venta_dict.get("metodo_pago", "Efectivo")
        doc_cliente = venta_dict.get("documento_cliente", "")

        # 2. Calcular nuevo total
        nuevo_total = sum(float(item.get("precio_unitario", item.get("precio", 0.0))) * int(item.get("cantidad", 1)) for item in nuevos_items)
        delta_monto = nuevo_total - total_anterior

        # 3. Obtener items anteriores para calcular delta de stock
        cur.execute("SELECT * FROM detalle_ventas WHERE id_venta = ?", (id_venta,))
        items_anteriores = {r["codigo_producto"]: dict(r) for r in cur.fetchall()}

        # Revertir stock anterior de productos físicos a Vitrina
        for cod, old_item in items_anteriores.items():
            cur.execute("SELECT * FROM productos WHERE codigo = ?", (cod,))
            p = cur.fetchone()
            if p:
                p_dict = dict(p)
                tipo = p_dict.get("tipo_producto", p_dict.get("tipo", "Producto"))
                if tipo != "Servicio":
                    sv_ant = float(p_dict.get("stock_vitrina", 0.0) or 0.0)
                    sb_ant = float(p_dict.get("stock_bodega", 0.0) or 0.0)
                    sv_des = sv_ant + old_item["cantidad"]
                    cur.execute("UPDATE productos SET stock_vitrina = ?, stock = ? WHERE codigo = ?", (sv_des, sb_ant + sv_des, cod))

        # Borrar detalles anteriores y reinsertar nuevos
        cur.execute("DELETE FROM detalle_ventas WHERE id_venta = ?", (id_venta,))
        for it in nuevos_items:
            cod = it.get("codigo_producto", it.get("codigo"))
            cant = int(it.get("cantidad", 1))
            pu = float(it.get("precio_unitario", it.get("precio", 0.0)))
            sub = float(it.get("subtotal", pu * cant))
            nombre = it.get("nombre_producto", it.get("nombre", cod))

            # Consultar producto para tipo y costo
            cur.execute("SELECT * FROM productos WHERE codigo = ?", (cod,))
            p = cur.fetchone()
            p_dict = dict(p) if p else {}
            tipo = p_dict.get("tipo_producto", p_dict.get("tipo", "Producto"))
            costo_unit = float(p_dict.get("costo", 0.0) or 0.0) if tipo != "Servicio" else 0.0

            cur.execute("""
                INSERT INTO detalle_ventas (
                    id_venta, codigo_producto, nombre_producto, precio_unitario, cantidad, subtotal, costo_unitario
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (id_venta, cod, nombre, pu, cant, sub, costo_unit))

            # Descontar stock nuevo de Vitrina
            if p and tipo != "Servicio":
                sv_ant = float(p_dict.get("stock_vitrina", 0.0) or 0.0)
                sb_ant = float(p_dict.get("stock_bodega", 0.0) or 0.0)
                sv_des = max(0.0, sv_ant - cant)
                cur.execute("UPDATE productos SET stock_vitrina = ?, stock = ? WHERE codigo = ?", (sv_des, sb_ant + sv_des, cod))

        ahora = datetime.now()
        fecha_str = ahora.strftime("%Y-%m-%d")
        hora_str = ahora.strftime("%H:%M:%S")

        # 4. Ajustar el impacto neto en caja física y cartera.
        efectivo_anterior = total_anterior if metodo_anterior == "Efectivo" else 0.0
        efectivo_nuevo = nuevo_total if nuevo_metodo == "Efectivo" else 0.0
        delta_efectivo = efectivo_nuevo - efectivo_anterior
        if abs(delta_efectivo) > 0.01:
            activa = obtener_sesion_activa()
            sesion_id = activa["id"] if activa else venta_dict.get("sesion_caja_id")
            if sesion_id:
                cur.execute("PRAGMA table_info(movimientos_caja)")
                cols_m = [c[1] for c in cur.fetchall()]
                col_sesion = "sesion_id" if "sesion_id" in cols_m else "sesion_caja_id"
                col_concepto = "concepto" if "concepto" in cols_m else "descripcion"
                col_ref = "id_referencia" if "id_referencia" in cols_m else "referencia_id"

                if "terminal" in cols_m:
                    cur.execute(f"""
                        INSERT INTO movimientos_caja (
                            {col_sesion}, fecha, hora, tipo, monto, usuario, terminal, {col_ref}, {col_concepto}
                        ) VALUES (?, ?, ?, 'AJUSTE', ?, ?, ?, ?, ?)
                    """, (
                        sesion_id, fecha_str, hora_str, delta_efectivo, usuario_admin, terminal,
                        str(id_venta), f"Ajuste efectivo por edición de Venta #{id_venta}: {motivo}"
                    ))
                else:
                    cur.execute(f"""
                        INSERT INTO movimientos_caja (
                            {col_sesion}, fecha, hora, tipo, monto, usuario, {col_ref}, {col_concepto}
                        ) VALUES (?, ?, ?, 'AJUSTE', ?, ?, ?, ?)
                    """, (
                        sesion_id, fecha_str, hora_str, delta_efectivo, usuario_admin,
                        str(id_venta), f"Ajuste efectivo por edición de Venta #{id_venta}: {motivo}"
                    ))

        fiado_anterior = total_anterior if metodo_anterior == "Fiado" else 0.0
        fiado_nuevo = nuevo_total if nuevo_metodo == "Fiado" else 0.0
        delta_fiado = fiado_nuevo - fiado_anterior
        if abs(delta_fiado) > 0.01 and doc_cliente:
            cur.execute("PRAGMA table_info(clientes)")
            cols_c = [c[1] for c in cur.fetchall()]
            col_doc = "documento" if "documento" in cols_c else "cedula"
            cur.execute(f"""
                UPDATE clientes 
                SET saldo_pendiente = MAX(0.0, saldo_pendiente + ?) 
                WHERE {col_doc} = ?
            """, (delta_fiado, doc_cliente))

        # 5. Actualizar venta
        cur.execute("""
            UPDATE ventas SET
                total_venta = ?,
                metodo_pago = ?,
                estado = 'Modificada',
                modificado_por = ?,
                fecha_modificacion = ?
            WHERE id_venta = ?
        """, (nuevo_total, nuevo_metodo, usuario_admin, f"{fecha_str} {hora_str}", id_venta))

        # 6. Registrar en auditoría
        cur.execute("PRAGMA table_info(auditoria_ventas)")
        cols_a = [c[1] for c in cur.fetchall()]
        if "terminal" in cols_a:
            cur.execute("""
                INSERT INTO auditoria_ventas (
                    id_venta, numero_venta, accion, usuario, fecha, hora, terminal, motivo, valor_anterior, valor_nuevo, detalles_json
                ) VALUES (?, ?, 'EDICION', ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                id_venta, f"V-{id_venta:06d}", usuario_admin, fecha_str, hora_str, terminal,
                motivo, total_anterior, nuevo_total, str(nuevos_items)
            ))
        else:
            cur.execute("""
                INSERT INTO auditoria_ventas (
                    id_venta, accion, usuario, fecha, hora, motivo, detalles_json, valor_anterior, valor_nuevo
                ) VALUES (?, 'EDICION', ?, ?, ?, ?, ?, ?, ?)
            """, (
                id_venta, usuario_admin, fecha_str, hora_str, motivo, str(nuevos_items), total_anterior, nuevo_total
            ))

        conn.commit()
        return {
            "ok": True,
            "success": True,
            "id_venta": id_venta,
            "total_anterior": total_anterior,
            "nuevo_total": nuevo_total,
            "delta_monto": delta_monto,
            "motivo": motivo
        }
    finally:
        conn.close()


def obtener_resumen_financiero(
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    fecha: Optional[str] = None
) -> Dict[str, Any]:
    """
    Fuente ÚNICA de verdad para Dashboard, Reportes y Cierre Contable.
    Calcula ventas activas, anuladas, desglose por métodos de pago, caja física, operarios y conciliación.
    """
    if fecha:
        fecha_inicio = fecha
        fecha_fin = fecha
    if not fecha_inicio:
        fecha_inicio = datetime.now().strftime("%Y-%m-%d")
    if not fecha_fin:
        fecha_fin = fecha_inicio

    conn = conectar_db()
    if not conn:
        return {}
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 1. Ventas activas en el período
        cur.execute("""
            SELECT 
                COALESCE(SUM(total_venta), 0.0) as total_ventas,
                COUNT(id_venta) as cant_ventas
            FROM ventas
            WHERE fecha_venta BETWEEN ? AND ?
              AND estado != 'Anulada'
        """, (fecha_inicio, fecha_fin))
        r_activas = cur.fetchone()
        total_ventas = float(r_activas["total_ventas"] or 0.0)
        cant_ventas = int(r_activas["cant_ventas"] or 0)
        ticket_promedio = (total_ventas / cant_ventas) if cant_ventas > 0 else 0.0

        # 2. Ventas anuladas
        cur.execute("""
            SELECT 
                COALESCE(SUM(total_venta), 0.0) as total_anuladas,
                COUNT(id_venta) as cant_anuladas
            FROM ventas
            WHERE fecha_venta BETWEEN ? AND ?
              AND estado = 'Anulada'
        """, (fecha_inicio, fecha_fin))
        r_anuladas = cur.fetchone()
        total_anuladas = float(r_anuladas["total_anuladas"] or 0.0)
        cant_anuladas = int(r_anuladas["cant_anuladas"] or 0)

        # 3. Desglose exacto por método de pago (solo activas)
        cur.execute("""
            SELECT metodo_pago, COALESCE(SUM(total_venta), 0.0) as total, COUNT(id_venta) as cant
            FROM ventas
            WHERE fecha_venta BETWEEN ? AND ?
              AND estado != 'Anulada'
            GROUP BY metodo_pago
        """, (fecha_inicio, fecha_fin))
        metodos_map = {r["metodo_pago"]: {"total": float(r["total"]), "cant": int(r["cant"])} for r in cur.fetchall()}

        efectivo_ventas = metodos_map.get("Efectivo", {"total": 0.0, "cant": 0})["total"]
        transferencia_ventas = metodos_map.get("Transferencia", {"total": 0.0, "cant": 0})["total"]
        fiado_ventas = metodos_map.get("Fiado", {"total": 0.0, "cant": 0})["total"]

        # 4. Control de Caja Física (movimientos registrados)
        cur.execute("""
            SELECT tipo, COALESCE(SUM(monto), 0.0) as total
            FROM movimientos_caja
            WHERE fecha BETWEEN ? AND ?
            GROUP BY tipo
        """, (fecha_inicio, fecha_fin))
        movs_caja = {r["tipo"]: float(r["total"]) for r in cur.fetchall()}

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

        # 5. Cuentas por Cobrar (Deuda global actual de clientes)
        cur.execute("SELECT COALESCE(SUM(saldo_pendiente), 0.0) as total_deuda FROM clientes")
        r_deuda = cur.fetchone()
        deuda_total_clientes = float(r_deuda["total_deuda"] or 0.0)

        # 6. Desglose detallado por Operario
        cur.execute("""
            SELECT 
                operario,
                COALESCE(SUM(total_venta), 0.0) as total_vendido,
                COUNT(id_venta) as cant_ventas,
                COALESCE(SUM(CASE WHEN metodo_pago = 'Efectivo' THEN total_venta ELSE 0 END), 0.0) as efectivo,
                COALESCE(SUM(CASE WHEN metodo_pago = 'Transferencia' THEN total_venta ELSE 0 END), 0.0) as transferencia,
                COALESCE(SUM(CASE WHEN metodo_pago = 'Fiado' THEN total_venta ELSE 0 END), 0.0) as fiado
            FROM ventas
            WHERE fecha_venta BETWEEN ? AND ?
              AND estado != 'Anulada'
            GROUP BY operario
            ORDER BY total_vendido DESC
        """, (fecha_inicio, fecha_fin))
        operarios_list = [dict(r) for r in cur.fetchall()]

        # 7. Conciliación y Detección de Inconsistencias
        suma_metodos = efectivo_ventas + transferencia_ventas + fiado_ventas
        diferencia_metodos = total_ventas - suma_metodos
        hay_inconsistencia_ventas = abs(diferencia_metodos) > 0.01

        return {
            "ventas_totales_facturadas": total_ventas,
            "cantidad_ventas": cant_ventas,
            "ganancia_neta_estimada": max(0.0, total_ventas - egresos_caja),
            "periodo": {"inicio": fecha_inicio, "fin": fecha_fin},
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
            "cartera": {
                "total_deuda_clientes": deuda_total_clientes
            },
            "operarios": operarios_list,
        }
    finally:
        conn.close()


def procesar_gastos_recurrentes() -> int:
    """
    Motor contable de gastos recurrentes (arriendos, servicios, suscripciones, etc.).
    Verifica las reglas de recurrencia activas y genera las obligaciones pendientes
    para el periodo actual sin duplicar en caso de reinicios de la aplicación.
    Retorna el número de nuevos gastos generados.
    """
    conn = conectar_db()
    if not conn:
        return 0
    nuevos = 0
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # Verificar que existan las tablas
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gastos_recurrentes'")
        if not cur.fetchone():
            return 0

        cur.execute("SELECT * FROM gastos_recurrentes WHERE activo = 1")
        recurrentes = cur.fetchall()
        
        hoy = datetime.now()
        fecha_hoy_str = hoy.strftime("%Y-%m-%d")
        hora_hoy_str = hoy.strftime("%H:%M:%S")

        for r in recurrentes:
            r_dict = dict(r)
            frecuencia = (r_dict.get("frecuencia") or "Mensual").strip()
            id_rec = r_dict["id"]
            
            # Determinar la clave de periodo
            if frecuencia == "Diaria":
                periodo_key = hoy.strftime("%Y-%m-%d")
            elif frecuencia == "Semanal":
                periodo_key = f"{hoy.year}-W{hoy.isocalendar()[1]:02d}"
            elif frecuencia == "Quincenal":
                q = 1 if hoy.day <= 15 else 2
                periodo_key = f"{hoy.strftime('%Y-%m')}-Q{q}"
            elif frecuencia == "Anual":
                periodo_key = str(hoy.year)
            else:  # Mensual por defecto
                periodo_key = hoy.strftime("%Y-%m")

            ultimo_gen = r_dict.get("ultimo_periodo_generado") or ""
            if ultimo_gen == periodo_key:
                continue  # Ya generado en este periodo

            # Calcular fecha de vencimiento estimada
            dia_corte = int(r_dict.get("dia_corte") or 1)
            dia_corte = max(1, min(dia_corte, 28))
            try:
                vencimiento = hoy.replace(day=dia_corte).strftime("%Y-%m-%d")
            except Exception:
                vencimiento = fecha_hoy_str

            # Verificar si ya existe en gastos por precaución
            cur.execute("""
                SELECT id_gasto FROM gastos 
                WHERE es_recurrente = 1 AND recurrencia_id = ? 
                  AND (observaciones LIKE ? OR fecha_vencimiento LIKE ?)
            """, (id_rec, f"%Periodo {periodo_key}%", f"%{periodo_key}%"))
            if cur.fetchone():
                cur.execute("UPDATE gastos_recurrentes SET ultimo_periodo_generado = ? WHERE id = ?", (periodo_key, id_rec))
                continue

            # Insertar como obligación PENDIENTE (no afecta gaveta de caja hasta que se pague)
            obs = f"Gasto generado automáticamente ({frecuencia}) - Periodo {periodo_key}"
            cur.execute("""
                INSERT INTO gastos (
                    concepto, valor, fecha, hora, metodo_pago, categoria, clasificacion,
                    descripcion, fecha_vencimiento, fecha_pago, frecuencia, estado,
                    usuario, proveedor, comprobante, observaciones, es_recurrente, recurrencia_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 'Pendiente', 'Sistema', ?, '', ?, 1, ?)
            """, (
                r_dict.get("concepto", "Gasto Recurrente"),
                float(r_dict.get("valor", 0.0)),
                fecha_hoy_str,
                hora_hoy_str,
                r_dict.get("metodo_pago_defecto", "Efectivo"),
                r_dict.get("categoria", "Fijo periódico"),
                r_dict.get("clasificacion", "Fijo periódico"),
                r_dict.get("descripcion", ""),
                vencimiento,
                frecuencia,
                r_dict.get("proveedor", ""),
                obs,
                id_rec
            ))
            
            cur.execute("UPDATE gastos_recurrentes SET ultimo_periodo_generado = ? WHERE id = ?", (periodo_key, id_rec))
            nuevos += 1

        conn.commit()
        return nuevos
    except Exception as e:
        print(f"[ERROR] procesar_gastos_recurrentes: {e}", file=sys.stderr)
        return 0
    finally:
        conn.close()


def pagar_gasto(
    id_gasto: int,
    metodo_pago: str = "Efectivo",
    usuario: str = "Administrador",
    comprobante: str = "",
    terminal: str = "Terminal-1"
) -> Dict[str, Any]:
    """
    Liquida contablemente un gasto en estado 'Pendiente' o 'Vencido'.
    Si se paga en 'Efectivo', genera el movimiento 'EGRESO' en movimientos_caja para descontar
    el dinero real de la gaveta de caja física de la sesión activa.
    """
    conn = conectar_db()
    if not conn:
        raise RuntimeError("No se pudo conectar a la base de datos.")
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("SELECT * FROM gastos WHERE id_gasto = ?", (id_gasto,))
        g = cur.fetchone()
        if not g:
            raise ValueError(f"No existe el gasto #{id_gasto}")

        g_dict = dict(g)
        if g_dict.get("estado") == "Pagado":
            raise ValueError(f"El gasto #{id_gasto} ya fue pagado previamente.")
        if g_dict.get("estado") == "Anulado":
            raise ValueError(f"El gasto #{id_gasto} está anulado.")

        monto = float(g_dict.get("valor", 0.0))
        concepto = g_dict.get("concepto", "Gasto")
        ahora = datetime.now()
        fecha_str = ahora.strftime("%Y-%m-%d")
        hora_str = ahora.strftime("%H:%M:%S")

        # Actualizar gasto
        cur.execute("""
            UPDATE gastos SET
                estado = 'Pagado',
                metodo_pago = ?,
                fecha_pago = ?,
                usuario = ?,
                comprobante = CASE WHEN ? != '' THEN ? ELSE comprobante END
            WHERE id_gasto = ?
        """, (metodo_pago, f"{fecha_str} {hora_str}", usuario, comprobante, comprobante, id_gasto))

        # Si el método de pago es Efectivo, registrar egreso en caja física
        movimiento_caja_id = None
        if metodo_pago == "Efectivo":
            movimiento_caja_id = registrar_movimiento_caja(
                tipo="EGRESO",
                monto=monto,
                usuario=usuario,
                terminal=terminal,
                referencia_id=str(id_gasto),
                descripcion=f"Pago de Gasto #{id_gasto}: {concepto}",
                conn=conn
            )
        elif metodo_pago == "Transferencia":
            registrar_movimiento_financiero(
                tipo="GASTO_PAGADO",
                concepto=f"Pago bancario Gasto #{id_gasto}: {concepto}",
                monto=monto,
                metodo_pago="Transferencia",
                cuenta_afectada="BANCO_TRANSFERENCIA",
                usuario=usuario,
                referencia_origen=f"GASTO-{id_gasto}",
                conn=conn,
                sincronizar_caja=False
            )

        conn.commit()
        return {
            "ok": True,
            "id_gasto": id_gasto,
            "concepto": concepto,
            "monto": monto,
            "metodo_pago": metodo_pago,
            "movimiento_caja_id": movimiento_caja_id,
            "fecha_pago": f"{fecha_str} {hora_str}"
        }
    finally:
        conn.close()


def calcular_metricas_contables(
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None
) -> Dict[str, Any]:
    """
    Cálculo contable exhaustivo y riguroso para la empresa.
    Calcula los 22 conceptos contables oficiales, los 9 indicadores de tarjetas KPI (A a I),
    análisis de costo histórico (COGS), gastos por 4 categorías, flujo de efectivo y cartera.
    """
    hoy_str = datetime.now().strftime("%Y-%m-%d")
    if not fecha_inicio:
        fecha_inicio = hoy_str
    if not fecha_fin:
        fecha_fin = fecha_inicio

    conn = conectar_db()
    if not conn:
        return {}
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 1. Ventas brutas y activas
        cur.execute("""
            SELECT 
                COALESCE(SUM(total_venta), 0.0) as total_activas,
                COUNT(id_venta) as cant_activas
            FROM ventas
            WHERE fecha_venta BETWEEN ? AND ?
              AND estado != 'Anulada'
        """, (fecha_inicio, fecha_fin))
        r_act = cur.fetchone()
        ventas_activas = float(r_act["total_activas"] or 0.0)
        cant_activas = int(r_act["cant_activas"] or 0)

        # 2. Devoluciones y anulaciones
        cur.execute("""
            SELECT 
                COALESCE(SUM(total_venta), 0.0) as total_anuladas,
                COUNT(id_venta) as cant_anuladas
            FROM ventas
            WHERE fecha_venta BETWEEN ? AND ?
              AND estado = 'Anulada'
        """, (fecha_inicio, fecha_fin))
        r_anu = cur.fetchone()
        ventas_anuladas = float(r_anu["total_anuladas"] or 0.0)
        cant_anuladas = int(r_anu["cant_anuladas"] or 0)

        ventas_brutas = ventas_activas + ventas_anuladas
        ventas_netas = ventas_activas
        ticket_promedio = (ventas_netas / cant_activas) if cant_activas > 0 else 0.0

        # 3. Métodos de pago en ventas netas
        cur.execute("""
            SELECT metodo_pago, COALESCE(SUM(total_venta), 0.0) as total, COUNT(id_venta) as cant
            FROM ventas
            WHERE fecha_venta BETWEEN ? AND ?
              AND estado != 'Anulada'
            GROUP BY metodo_pago
        """, (fecha_inicio, fecha_fin))
        map_metodos = {r["metodo_pago"]: float(r["total"]) for r in cur.fetchall()}
        ventas_efectivo = map_metodos.get("Efectivo", 0.0)
        ventas_transferencia = map_metodos.get("Transferencia", 0.0)
        ventas_fiado = map_metodos.get("Fiado", 0.0)

        # 4. Costo de Mercancía Vendida (COGS) usando costo histórico en detalle_ventas
        cur.execute("PRAGMA table_info(detalle_ventas)")
        dv_cols = [c[1] for c in cur.fetchall()]
        tiene_costo_unit = "costo_unitario" in dv_cols

        cur.execute("PRAGMA table_info(productos)")
        p_cols = [c[1] for c in cur.fetchall()]
        col_tipo = "tipo_producto" if "tipo_producto" in p_cols else ("tipo" if "tipo" in p_cols else None)
        filtro_no_servicio = f"AND COALESCE(p.{col_tipo}, 'Producto') != 'Servicio'" if col_tipo else ""

        if tiene_costo_unit:
            cur.execute(f"""
                SELECT 
                    COALESCE(SUM(dv.cantidad * COALESCE(dv.costo_unitario, p.costo, 0.0)), 0.0) as cogs_total
                FROM detalle_ventas dv
                JOIN ventas v ON dv.id_venta = v.id_venta
                LEFT JOIN productos p ON dv.codigo_producto = p.codigo
                WHERE v.fecha_venta BETWEEN ? AND ?
                  AND v.estado != 'Anulada'
                  {filtro_no_servicio}
            """, (fecha_inicio, fecha_fin))
        else:
            cur.execute(f"""
                SELECT 
                    COALESCE(SUM(dv.cantidad * COALESCE(p.costo, 0.0)), 0.0) as cogs_total
                FROM detalle_ventas dv
                JOIN ventas v ON dv.id_venta = v.id_venta
                LEFT JOIN productos p ON dv.codigo_producto = p.codigo
                WHERE v.fecha_venta BETWEEN ? AND ?
                  AND v.estado != 'Anulada'
                  {filtro_no_servicio}
            """, (fecha_inicio, fecha_fin))
        cogs_total = float(cur.fetchone()["cogs_total"] or 0.0)
        utilidad_bruta = max(0.0, ventas_netas - cogs_total)
        margen_bruto_pct = (utilidad_bruta / ventas_netas * 100.0) if ventas_netas > 0 else 0.0

        # 5. Gastos Operativos desglosados en las 4 categorías
        cur.execute("PRAGMA table_info(gastos)")
        g_cols = [c[1] for c in cur.fetchall()]
        col_cat = "categoria" if "categoria" in g_cols else ("clasificacion" if "clasificacion" in g_cols else None)

        gastos_por_cat = {
            "Operativo diario": 0.0,
            "Fijo periódico": 0.0,
            "Variable": 0.0,
            "Extraordinario": 0.0
        }
        gastos_pagados = 0.0
        gastos_pendientes = 0.0

        if col_cat:
            cur.execute(f"""
                SELECT 
                    {col_cat} as cat,
                    estado,
                    COALESCE(SUM(valor), 0.0) as subtotal
                FROM gastos
                WHERE fecha BETWEEN ? AND ?
                  AND estado != 'Anulado'
                GROUP BY {col_cat}, estado
            """, (fecha_inicio, fecha_fin))
            for row in cur.fetchall():
                cat_name = row["cat"] or "Operativo diario"
                est = row["estado"] or "Pagado"
                val = float(row["subtotal"] or 0.0)
                
                # Clasificar en categorías estándar
                if "fijo" in cat_name.lower():
                    cat_std = "Fijo periódico"
                elif "variable" in cat_name.lower():
                    cat_std = "Variable"
                elif "extraordinario" in cat_name.lower() or "imprevisto" in cat_name.lower():
                    cat_std = "Extraordinario"
                else:
                    cat_std = "Operativo diario"

                gastos_por_cat[cat_std] = gastos_por_cat.get(cat_std, 0.0) + val
                if est == "Pagado":
                    gastos_pagados += val
                else:
                    gastos_pendientes += val
        else:
            cur.execute("""
                SELECT COALESCE(SUM(valor), 0.0) as subtotal 
                FROM gastos 
                WHERE fecha BETWEEN ? AND ?
            """, (fecha_inicio, fecha_fin))
            total_g = float(cur.fetchone()["subtotal"] or 0.0)
            gastos_por_cat["Operativo diario"] = total_g
            gastos_pagados = total_g

        total_gastos = sum(gastos_por_cat.values())

        # 6. Comisiones / Nómina devengada en el período (Integración con nomina_manager)
        comisiones_totales = 0.0
        metricas_nomina = {
            "gasto_personal_devengado": 0.0,
            "salarios_devengados": 0.0,
            "comisiones_devengadas": 0.0,
            "ajustes_devengados": 0.0,
            "pagos_nomina_realizados": 0.0,
            "pagos_efectivo": 0.0,
            "pagos_transferencia": 0.0,
            "obligaciones_pendientes": 0.0
        }
        try:
            try:
                from nomina_manager import obtener_metricas_nomina_contabilidad
            except ImportError:
                from interface.nomina_manager import obtener_metricas_nomina_contabilidad
            metricas_nomina = obtener_metricas_nomina_contabilidad(fecha_inicio, fecha_fin)
            comisiones_totales = float(metricas_nomina.get("gasto_personal_devengado") or 0.0)
        except Exception as e_nom_m:
            print(f"Aviso consultando métricas de nómina: {e_nom_m}")

        # Fallback para ventas históricas previas sin registros en nomina_devengos
        if comisiones_totales == 0.0:
            try:
                from interface.config import DB_USUARIOS_PATH
                ruta_u_fb = os.environ.get("VMPOS_DB_USUARIOS") or DB_USUARIOS_PATH
                conn_u = sqlite3.connect(ruta_u_fb)
                conn_u.row_factory = sqlite3.Row
                cur_u = conn_u.cursor()
                cur_u.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='nomina_devengos'")
                tiene_tabla_dev = (cur_u.fetchone()[0] or 0) > 0
                hay_dev_registrados = False
                if tiene_tabla_dev:
                    cur_u.execute("SELECT COUNT(*) FROM nomina_devengos WHERE fecha BETWEEN ? AND ?", (fecha_inicio, fecha_fin))
                    hay_dev_registrados = (cur_u.fetchone()[0] or 0) > 0

                if not hay_dev_registrados:
                    cur_u.execute("SELECT usuario, comision_porcentaje FROM usuarios WHERE comision_porcentaje > 0")
                    comis_map = {u["usuario"]: float(u["comision_porcentaje"]) for u in cur_u.fetchall()}
                    filtro_servicio = f"AND COALESCE(p.{col_tipo}, '') = 'Servicio'" if col_tipo else "AND 1=0"
                    cur.execute(f"""
                        SELECT v.operario, dv.subtotal
                        FROM detalle_ventas dv
                        JOIN ventas v ON dv.id_venta = v.id_venta
                        JOIN productos p ON dv.codigo_producto = p.codigo
                        WHERE v.fecha_venta BETWEEN ? AND ?
                          AND v.estado != 'Anulada'
                          {filtro_servicio}
                    """, (fecha_inicio, fecha_fin))
                    for item in cur.fetchall():
                        op = item["operario"]
                        sub = float(item["subtotal"] or 0.0)
                        pct = comis_map.get(op, 0.0)
                        if pct > 0:
                            comisiones_totales += sub * (pct / 100.0)
                    metricas_nomina["gasto_personal_devengado"] = round(comisiones_totales, 2)
                    metricas_nomina["comisiones_devengadas"] = round(comisiones_totales, 2)
                conn_u.close()
            except Exception:
                pass

        comisiones_totales = max(0.0, float(comisiones_totales))

        # 7. Utilidad Operacional Neta
        utilidad_operacional_neta = utilidad_bruta - total_gastos - comisiones_totales
        margen_neto_pct = (utilidad_operacional_neta / ventas_netas * 100.0) if ventas_netas > 0 else 0.0

        # 8. Flujo de Caja Física (movimientos registrados)
        cur.execute("""
            SELECT tipo, COALESCE(SUM(monto), 0.0) as total
            FROM movimientos_caja
            WHERE fecha BETWEEN ? AND ?
            GROUP BY tipo
        """, (fecha_inicio, fecha_fin))
        movs = {r["tipo"]: float(r["total"]) for r in cur.fetchall()}
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

        # 9. Diferencia de Caja acumulada (Sobrantes / Faltantes)
        cur.execute("""
            SELECT COALESCE(SUM(diferencia), 0.0) as dif_total
            FROM sesiones_caja
            WHERE fecha_cierre IS NOT NULL
              AND fecha_apertura BETWEEN ? AND ?
        """, (fecha_inicio, fecha_fin))
        r_dif = cur.fetchone()
        diferencia_caja_acumulada = float(r_dif["dif_total"] or 0.0)

        # 10. Cartera y Deudores
        cur.execute("SELECT COALESCE(SUM(saldo_pendiente), 0.0) as deuda_total FROM clientes")
        saldo_cartera_pendiente = float(cur.fetchone()["deuda_total"] or 0.0)

        cur.execute("PRAGMA table_info(clientes)")
        cols_cl = [c[1] for c in cur.fetchall()]
        col_doc_cl = "documento" if "documento" in cols_cl else "cedula"
        cur.execute(f"""
            SELECT {col_doc_cl} as cedula, nombre, telefono, saldo_pendiente
            FROM clientes
            WHERE saldo_pendiente > 0
            ORDER BY saldo_pendiente DESC
            LIMIT 15
        """)
        top_deudores = [dict(r) for r in cur.fetchall()]

        # 11. Rendimiento detallado por Operario
        cur.execute("""
            SELECT 
                operario,
                COALESCE(SUM(total_venta), 0.0) as total_vendido,
                COUNT(id_venta) as cant_ventas,
                COALESCE(SUM(CASE WHEN metodo_pago = 'Efectivo' THEN total_venta ELSE 0 END), 0.0) as efectivo,
                COALESCE(SUM(CASE WHEN metodo_pago = 'Transferencia' THEN total_venta ELSE 0 END), 0.0) as transferencia,
                COALESCE(SUM(CASE WHEN metodo_pago = 'Fiado' THEN total_venta ELSE 0 END), 0.0) as fiado
            FROM ventas
            WHERE fecha_venta BETWEEN ? AND ?
              AND estado != 'Anulada'
            GROUP BY operario
            ORDER BY total_vendido DESC
        """, (fecha_inicio, fecha_fin))
        operarios_stats = [dict(r) for r in cur.fetchall()]

        # 12. Top 15 productos más vendidos y su margen
        cur.execute("""
            SELECT 
                dv.codigo_producto,
                dv.nombre_producto,
                SUM(dv.cantidad) as total_unidades,
                SUM(dv.subtotal) as total_facturado,
                COALESCE(SUM(dv.cantidad * COALESCE(dv.costo_unitario, p.costo, 0.0)), 0.0) as costo_total
            FROM detalle_ventas dv
            JOIN ventas v ON dv.id_venta = v.id_venta
            LEFT JOIN productos p ON dv.codigo_producto = p.codigo
            WHERE v.fecha_venta BETWEEN ? AND ?
              AND v.estado != 'Anulada'
            GROUP BY dv.codigo_producto, dv.nombre_producto
            ORDER BY total_facturado DESC
            LIMIT 15
        """, (fecha_inicio, fecha_fin))
        top_productos = []
        for r in cur.fetchall():
            tf = float(r["total_facturado"] or 0.0)
            ct = float(r["costo_total"] or 0.0)
            gan = tf - ct
            mg = (gan / tf * 100.0) if tf > 0 else 0.0
            top_productos.append({
                "codigo": r["codigo_producto"],
                "nombre": r["nombre_producto"],
                "unidades": int(r["total_unidades"] or 0),
                "facturado": tf,
                "costo": ct,
                "ganancia": gan,
                "margen_pct": mg
            })

        # 13. Ventas diarias en el período (evolución diaria)
        cur.execute("""
            SELECT fecha_venta, COALESCE(SUM(total_venta), 0.0) as total, COUNT(id_venta) as cant
            FROM ventas
            WHERE fecha_venta BETWEEN ? AND ?
              AND estado != 'Anulada'
            GROUP BY fecha_venta
            ORDER BY fecha_venta ASC
        """, (fecha_inicio, fecha_fin))
        ventas_diarias = []
        for r in cur.fetchall():
            f_str = r["fecha_venta"]
            try:
                dt_obj = datetime.strptime(f_str, "%Y-%m-%d")
                d_label = dt_obj.strftime("%d %b")
            except Exception:
                d_label = f_str[-5:]
            ventas_diarias.append({
                "fecha": f_str,
                "dia_label": d_label,
                "total": float(r["total"] or 0.0),
                "cantidad": int(r["cant"] or 0)
            })

        # Días destacados
        dia_mejor = max(ventas_diarias, key=lambda x: x["total"]) if ventas_diarias else None
        dia_peor = min(ventas_diarias, key=lambda x: x["total"]) if len(ventas_diarias) >= 2 else None

        # Gastos mayores individuales
        cur.execute("""
            SELECT id_gasto, concepto, valor, fecha, COALESCE(categoria, 'Operativo diario') as categoria, estado
            FROM gastos
            WHERE fecha BETWEEN ? AND ?
              AND estado != 'Anulado'
            ORDER BY valor DESC
            LIMIT 5
        """, (fecha_inicio, fecha_fin))
        gastos_mayores = [dict(r) for r in cur.fetchall()]

        # Productos con inventario bajo
        cur.execute("PRAGMA table_info(productos)")
        cols_p_info = [c[1] for c in cur.fetchall()]
        col_tipo_prod = "tipo_producto" if "tipo_producto" in cols_p_info else ("tipo" if "tipo" in cols_p_info else None)
        filtro_fisico = f"AND COALESCE({col_tipo_prod}, 'Producto') != 'Servicio'" if col_tipo_prod else ""
        cur.execute(f"""
            SELECT codigo, nombre, stock, precio, COALESCE(costo, 0.0) as costo
            FROM productos
            WHERE stock <= 5
              {filtro_fisico}
            ORDER BY stock ASC
            LIMIT 10
        """)
        productos_stock_bajo = [dict(r) for r in cur.fetchall()]

        # Top productos por mayor ganancia bruta
        top_utilidad_productos = sorted(top_productos, key=lambda x: x["ganancia"], reverse=True)[:5]

        # 14. Bancos y transferencias verificadas
        cur.execute("""
            SELECT 
                COALESCE(SUM(monto_transferencias_esperado), 0.0) as transf_esperadas,
                COALESCE(SUM(monto_transferencias_verificado), 0.0) as transf_verificadas,
                COALESCE(SUM(diferencia_banco), 0.0) as dif_banco
            FROM sesiones_caja
            WHERE fecha_apertura BETWEEN ? AND ?
        """, (fecha_inicio, fecha_fin))
        r_banco = cur.fetchone()
        banco_verificado = float(r_banco["transf_verificadas"] or 0.0)
        dinero_bancos = ventas_transferencia if banco_verificado == 0.0 else banco_verificado

        # 14.b Valor Total del Inventario Físico a Costo
        cur.execute("""
            SELECT COALESCE(SUM(stock * COALESCE(costo, 0.0)), 0.0) as val_inv
            FROM productos
            WHERE stock > 0
        """)
        valor_inventario = float(cur.fetchone()["val_inv"] or 0.0)

        # 15. Listado completo de 22 conceptos contables oficiales
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
            {"numero": 13, "codigo": "NOM-13", "concepto": "13. Gastos de Personal y Comisiones", "valor": -comisiones_totales, "tipo": "Gasto Laboral", "descripcion": "Comisiones sobre servicios devengadas por operarios."},
            {"numero": 14, "codigo": "UTI-14", "concepto": "14. Utilidad Operacional Neta Final", "valor": utilidad_operacional_neta, "tipo": "Resultado Final", "descripcion": "Ganancia líquida real del negocio en el período analizado."},
            {"numero": 15, "codigo": "MAR-15", "concepto": "15. Margen Neto Operacional (%)", "valor": margen_neto_pct, "tipo": "Porcentaje", "descripcion": "Rentabilidad neta final sobre las ventas netas."},
            {"numero": 16, "codigo": "FLU-16", "concepto": "16. Ventas Recaudadas en Efectivo", "valor": ventas_efectivo, "tipo": "Flujo Efectivo", "descripcion": "Entrada directa a la gaveta física de caja."},
            {"numero": 17, "codigo": "BAN-17", "concepto": "17. Ventas en Bancos / Transferencias", "valor": ventas_transferencia, "tipo": "Flujo Digital", "descripcion": "Recaudos vía Nequi, Daviplata o transferencias bancarias."},
            {"numero": 18, "codigo": "FIA-18", "concepto": "18. Ventas Otorgadas a Crédito (Fiados)", "valor": ventas_fiado, "tipo": "Cartera", "descripcion": "Ventas facturadas pendientes de pago por clientes."},
            {"numero": 19, "codigo": "ABO-19", "concepto": "19. Recaudos de Cartera (Abonos en Efectivo)", "valor": ingresos_abonos_cartera, "tipo": "Flujo Efectivo", "descripcion": "Cobros de fiados anteriores que entran a caja física."},
            {"numero": 20, "codigo": "SAL-20", "concepto": "20. Saldo Total Cuentas por Cobrar", "valor": saldo_cartera_pendiente, "tipo": "Cartera Global", "descripcion": "Deuda viva acumulada de todos los clientes fiadores."},
            {"numero": 21, "codigo": "CAJ-21", "concepto": "21. Efectivo Físico Esperado en Caja", "valor": efectivo_esperado_caja, "tipo": "Tesorería", "descripcion": "Saldo que debe existir físicamente en gaveta (Base + Efectivo - Egresos)."},
            {"numero": 22, "codigo": "DIF-22", "concepto": "22. Diferencia Acumulada de Arqueos", "valor": diferencia_caja_acumulada, "tipo": "Control", "descripcion": "Suma de sobrantes (+) o faltantes (-) reportados en cierres."}
        ]

        # 16. Tarjetas KPI Oficiales (A a J)
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
            "periodo": {"inicio": fecha_inicio, "fin": fecha_fin},
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
                "rentabilidad_neta_pct": margen_neto_pct
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
                "verificado_sesiones": banco_verificado,
                "saldo_estimado": dinero_bancos
            }
        }
    finally:
        conn.close()


def generar_alertas_recomendaciones(
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None
) -> List[Dict[str, str]]:
    """
    Motor inteligente de 10 alertas y recomendaciones comerciales basadas en el desempeño real.
    Devuelve lista de objetos: {tipo: 'alerta'|'advertencia'|'positivo'|'info', titulo, mensaje, accion}
    """
    metricas = calcular_metricas_contables(fecha_inicio, fecha_fin)
    if not metricas:
        return []

    alertas = []
    kpis = metricas["kpis"]
    ventas = metricas["resumen_ventas"]
    gastos = metricas["gastos"]
    operarios = metricas["operarios"]
    caja = metricas["caja_fisica"]
    v_netas = ventas["ventas_netas"]

    # 1. Margen Bruto
    mb = (kpis["C_utilidad_bruta"] / v_netas * 100.0) if v_netas > 0 else 0.0
    if v_netas > 0:
        if mb < 25.0:
            alertas.append({
                "tipo": "alerta",
                "titulo": "Margen Bruto Crítico (<25%)",
                "mensaje": f"El margen bruto comercial es de {mb:.1f}%. El costo de adquisición está consumiendo más del 75% de las ventas.",
                "accion": "Ajustar precios de venta o renegociar de inmediato condiciones y costos de compra con proveedores."
            })
        elif mb >= 40.0:
            alertas.append({
                "tipo": "positivo",
                "titulo": "Margen Comercial Fuerte (>=40%)",
                "mensaje": f"Margen bruto saludable de {mb:.1f}%. La estructura de precios de los productos es sólida.",
                "accion": "Mantener la estrategia actual y considerar combos o promociones para productos de menor rotación."
            })

    # 2. Control de Gastos vs Utilidad Bruta
    ub = kpis["C_utilidad_bruta"]
    tg = gastos["total"]
    if ub > 0:
        ratio_gastos = (tg / ub) * 100.0
        if ratio_gastos > 45.0:
            alertas.append({
                "tipo": "advertencia",
                "titulo": "Gastos Operativos Elevados",
                "mensaje": f"Los gastos del período (${tg:,.0f}) consumen el {ratio_gastos:.1f}% de la utilidad bruta generada.",
                "accion": "Revisar los gastos clasificados como 'Variables' y 'Operativos diarios' para recortar fugas de dinero."
            })

    # 3. Exposición de Cartera y Fiados
    v_fiado = ventas["fiado"]
    if v_netas > 0:
        pct_fiado = (v_fiado / v_netas) * 100.0
        if pct_fiado > 20.0:
            alertas.append({
                "tipo": "advertencia",
                "titulo": "Alta Exposición a Ventas Fiadas (>20%)",
                "mensaje": f"El {pct_fiado:.1f}% de las ventas de este período se hicieron a crédito (${v_fiado:,.0f}).",
                "accion": "Fijar topes máximos de fiado por cliente y priorizar la cobranza de saldos vencidos."
            })

    # 4. Concentración de Métodos de Pago y Custodia de Efectivo
    pct_efectivo = ventas["pct_efectivo"]
    if v_netas > 0 and pct_efectivo > 85.0:
        alertas.append({
            "tipo": "info",
            "titulo": "Alta Concentración de Efectivo Físico (>85%)",
            "mensaje": f"El {pct_efectivo:.1f}% de los ingresos ingresan en efectivo. Representa riesgo de seguridad y arqueo.",
            "accion": "Incentivar pagos vía QR bancario (Nequi, Daviplata o Bancolombia) para reducir volumen de efectivo en caja."
        })

    # 5. Análisis de Productividad de Operarios
    if len(operarios) >= 2:
        top_op = operarios[0]
        bot_op = operarios[-1]
        tot_vend = sum(o["total_vendido"] for o in operarios)
        if tot_vend > 0:
            pct_top = (top_op["total_vendido"] / tot_vend) * 100.0
            alertas.append({
                "tipo": "info",
                "titulo": f"Operario Líder: {top_op['operario']}",
                "mensaje": f"Generó el {pct_top:.1f}% de la facturación (${top_op['total_vendido']:,.0f}) con {top_op['cant_ventas']} ventas.",
                "accion": f"Evaluar las técnicas de venta de {top_op['operario']} para capacitar a {bot_op['operario']}."
            })

    # 6. Alerta de Gastos Pendientes o Vencidos
    if gastos["pendientes"] > 0:
        alertas.append({
            "tipo": "alerta",
            "titulo": "Obligaciones y Gastos Pendientes de Pago",
            "mensaje": f"Hay ${gastos['pendientes']:,.0f} en gastos devengados aún no liquidados.",
            "accion": "Ir a 'Control de Gastos' para programar los pagos y evitar corte de servicios o recargos."
        })

    # 7. Control de Faltantes de Caja
    dif_caja = caja["diferencia_acumulada"]
    if dif_caja < -500:
        alertas.append({
            "tipo": "alerta",
            "titulo": "Faltante Detectado en Cierres de Caja",
            "mensaje": f"Se registra un faltante acumulado de ${abs(dif_caja):,.0f} en los arqueos del período.",
            "accion": "Auditar los recibos de egreso y verificar si hay entregas de efectivo no reportadas."
        })
    elif dif_caja > 500:
        alertas.append({
            "tipo": "info",
            "titulo": "Sobrante de Caja en Cierres",
            "mensaje": f"Se registra un sobrante neto acumulado de ${dif_caja:,.0f} en los arqueos.",
            "accion": "Verificar si hubo ventas cobradas sin registrar en el sistema."
        })

    # 8. Rotación de Productos Top
    top_p = metricas["top_productos"]
    if top_p:
        lider_prod = top_p[0]
        alertas.append({
            "tipo": "positivo",
            "titulo": f"Producto Estrella: {lider_prod['nombre']}",
            "mensaje": f"Líder en ventas con {lider_prod['unidades']} unidades (${lider_prod['facturado']:,.0f}), margen {lider_prod['margen_pct']:.1f}%.",
            "accion": "Garantizar existencias suficientes con los proveedores para evitar quiebres de stock."
        })

    # 9. Ticket Promedio de Venta
    tp = ventas["ticket_promedio"]
    if tp > 0:
        alertas.append({
            "tipo": "info",
            "titulo": f"Ticket Promedio: ${tp:,.0f}",
            "mensaje": f"Cada cliente gasta en promedio ${tp:,.0f} por compra en el período.",
            "accion": "Implementar ventas sugeridas al momento del cobro para elevar el valor del ticket."
        })

    # 10. Flujo de Caja y Solvencia Inmediata
    flujo_disp = caja["efectivo_esperado"]
    if v_netas == 0 and flujo_disp == 0:
        alertas.append({
            "tipo": "info",
            "titulo": "Período sin movimiento operativo",
            "mensaje": "No se registran ventas ni saldo de caja en el período consultado para evaluar solvencia.",
            "accion": "Consulta un período con actividad comercial para ver diagnósticos financieros detallados."
        })
    elif flujo_disp < gastos["pendientes"]:
        alertas.append({
            "tipo": "advertencia",
            "titulo": "Riesgo de Liquidez a Corto Plazo",
            "mensaje": f"El efectivo en caja (${flujo_disp:,.0f}) es inferior a las obligaciones pendientes (${gastos['pendientes']:,.0f}).",
            "accion": "Acelerar la cobranza de clientes con fiados vigentes para fondear la caja."
        })
    elif flujo_disp > 0:
        alertas.append({
            "tipo": "positivo",
            "titulo": "Flujo de Caja Saludable",
            "mensaje": f"El efectivo disponible (${flujo_disp:,.0f}) cubre satisfactoriamente los compromisos inmediatos.",
            "accion": "Mantener el fondo de reserva para imprevistos operativos."
        })

    return alertas

