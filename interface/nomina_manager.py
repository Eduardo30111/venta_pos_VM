#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor Central de Nómina, Asistencia, Comisiones, Cartera de Empleados e Integración Contable - VmPOS.

Garantiza:
1. Trazabilidad e idempotencia en asistencia y generación de salario diario.
   - Regla específica para Vendedoras: marcar asistencia al abrir el POS NO genera el salario diario;
     el salario diario elegible se genera únicamente con la primera venta válida del día, una sola vez por jornada.
   - Reabrir el programa o registrar múltiples ventas el mismo día jamás duplica asistencia, salario ni comisiones.
2. Cálculo y control de comisiones por venta/ítem con llave única (`codigo_unico`), evitando duplicación
   y excluyendo ventas anuladas o conceptos no autorizados (ej. fiados no autorizados).
3. Integración contable en 3 eventos separados:
   - A. Devengo de nómina (`DEVENGO_NOMINA`): reconoce la obligación sin descontar efectivo de caja.
   - B. Pago de nómina (`PAGO_NOMINA`): registra el pago total, parcial o anticipo; si es en Efectivo afecta
     Control de Caja (`movimientos_caja`) una sola vez; si es por Transferencia afecta `BANCO_TRANSFERENCIA`.
   - C. Ajuste o reverso (`AJUSTE_NOMINA` / `REVERSO_ANULACION`): corrige o revierte trazablemente con responsable y motivo,
     sin alterar silenciosamente períodos ya cerrados/liquidados.
4. Consultas exactas y separadas para:
   - Resumen de Ventas y Recaudo del Empleado (`Por cobrar`, `Total pagado (Clientes)`, `Recaudado hoy`).
   - Resumen de Nómina y Comisiones del Empleado (`Salario diario`, `Comisiones`, `Total devengado`, `Total pagado (Nómina)`, `Por cobrar (Nómina)`).
"""

import os
import sys
import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from config import DB_USUARIOS_PATH, DB_VENTAS_PATH
except ImportError:
    from interface.config import DB_USUARIOS_PATH, DB_VENTAS_PATH

try:
    from database_manager import conectar_db as _conectar_ventas_db
except ImportError:
    from interface.database_manager import conectar_db as _conectar_ventas_db

try:
    from usuarios_db import conectar_usuarios_db as _conectar_usuarios_db
except ImportError:
    from interface.usuarios_db import conectar_usuarios_db as _conectar_usuarios_db


def conectar_usuarios_db(db_path: Optional[str] = None) -> Optional[sqlite3.Connection]:
    """Conecta a usuarios.db respetando variable de entorno VMPOS_DB_USUARIOS para pruebas."""
    ruta = db_path or os.environ.get("VMPOS_DB_USUARIOS") or DB_USUARIOS_PATH
    try:
        conn = sqlite3.connect(ruta)
        return conn
    except Exception as e:
        print(f"Error conectando a usuarios.db ({ruta}): {e}")
        return None


def conectar_ventas_db(db_path: Optional[str] = None) -> Optional[sqlite3.Connection]:
    """Conecta a ventas.db respetando variable de entorno VMPOS_DB_VENTAS para pruebas."""
    ruta = db_path or os.environ.get("VMPOS_DB_VENTAS") or DB_VENTAS_PATH
    return _conectar_ventas_db(ruta)


def inicializar_tablas_nomina() -> bool:
    """
    Asegura de forma no destructiva todas las tablas y columnas requeridas en usuarios.db y ventas.db.
    """
    conn_u = conectar_usuarios_db()
    if not conn_u:
        return False
    try:
        cur = conn_u.cursor()

        # 1. Tabla usuarios (asegurar columnas de configuración de nómina y elegibilidad)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT UNIQUE NOT NULL,
                password TEXT DEFAULT '',
                contrasena TEXT DEFAULT '',
                nombre TEXT DEFAULT '',
                apellidos TEXT DEFAULT '',
                edad INTEGER,
                telefono TEXT,
                rol TEXT NOT NULL,
                estado TEXT DEFAULT 'Activo',
                comision_porcentaje REAL DEFAULT 0.0,
                comisiones_acumuladas REAL DEFAULT 0.0,
                tipo_nomina TEXT DEFAULT 'Porcentual',
                salario_diario REAL DEFAULT 0.0
            )
        """)

        for col_def in [
            "password TEXT DEFAULT ''",
            "estado TEXT DEFAULT 'Activo'",
            "comision_porcentaje REAL DEFAULT 0.0",
            "comisiones_acumuladas REAL DEFAULT 0.0",
            "tipo_nomina TEXT DEFAULT 'Porcentual'",
            "salario_diario REAL DEFAULT 0.0",
            "regla_devengo TEXT DEFAULT 'Auto'",
            "comision_productos INTEGER DEFAULT 1",
            "comision_servicios INTEGER DEFAULT 1",
            "comision_fiados INTEGER DEFAULT 0",
            "solicitud_liquidacion INTEGER DEFAULT 0",
            "fecha_solicitud_liq TEXT DEFAULT NULL"
        ]:
            try:
                cur.execute(f"ALTER TABLE usuarios ADD COLUMN {col_def}")
            except sqlite3.OperationalError:
                pass

        # 2. Tabla asistencia (con trazabilidad de jornada y primera venta)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS asistencia (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                fecha TEXT NOT NULL,
                estado TEXT NOT NULL
            )
        """)
        for col_def in [
            "hora_registro TEXT DEFAULT NULL",
            "usuario_nombre TEXT DEFAULT ''",
            "rol TEXT DEFAULT ''",
            "primera_venta_id INTEGER DEFAULT NULL",
            "salario_generado INTEGER DEFAULT 0",
            "monto_salario_generado REAL DEFAULT 0.0",
            "responsable TEXT DEFAULT 'Sistema'",
            "observaciones TEXT DEFAULT ''"
        ]:
            try:
                cur.execute(f"ALTER TABLE asistencia ADD COLUMN {col_def}")
            except sqlite3.OperationalError:
                pass

        # Limpiar duplicados preexistentes en asistencia conservando el registro más completo por (usuario_id, fecha)
        try:
            cur.execute("""
                DELETE FROM asistencia
                WHERE id NOT IN (
                    SELECT MAX(id)
                    FROM asistencia
                    GROUP BY usuario_id, fecha
                )
            """)
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_asistencia_usr_fecha ON asistencia(usuario_id, fecha)")
        except Exception:
            pass

        # 3. Tabla nomina_devengos (Conceptos generados: salarios diarios, comisiones, ajustes, reversos)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nomina_devengos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo_unico TEXT UNIQUE NOT NULL,
                usuario_id INTEGER NOT NULL,
                usuario_nombre TEXT NOT NULL,
                rol TEXT DEFAULT '',
                fecha TEXT NOT NULL,
                hora TEXT NOT NULL,
                periodo TEXT NOT NULL,
                tipo_concepto TEXT NOT NULL, -- 'SALARIO_DIARIO', 'COMISION_VENTA', 'AJUSTE_POSITIVO', 'AJUSTE_NEGATIVO', 'REVERSO_ANULACION'
                concepto TEXT NOT NULL,
                monto REAL NOT NULL,
                monto_pagado REAL DEFAULT 0.0,
                referencia_origen TEXT DEFAULT '',
                id_venta INTEGER DEFAULT NULL,
                id_detalle_venta INTEGER DEFAULT NULL,
                tipo_item TEXT DEFAULT '',
                item_nombre TEXT DEFAULT '',
                base_calculo REAL DEFAULT 0.0,
                porcentaje_aplicado REAL DEFAULT 0.0,
                estado TEXT NOT NULL DEFAULT 'Pendiente', -- 'Pendiente', 'Parcial', 'Liquidado', 'Anulado'
                liquidacion_id INTEGER DEFAULT NULL,
                responsable TEXT DEFAULT 'Sistema',
                motivo TEXT DEFAULT ''
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_dev_usr_fecha ON nomina_devengos(usuario_id, fecha)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_dev_estado ON nomina_devengos(estado)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_dev_venta ON nomina_devengos(id_venta)")

        # 4. Tabla nomina_pagos (Liquidaciones totales, pagos parciales y anticipos)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nomina_pagos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo_pago TEXT UNIQUE NOT NULL,
                usuario_id INTEGER NOT NULL,
                usuario_nombre TEXT NOT NULL,
                rol TEXT DEFAULT '',
                fecha_pago TEXT NOT NULL,
                hora_pago TEXT NOT NULL,
                periodo TEXT NOT NULL,
                tipo_operacion TEXT NOT NULL, -- 'LIQUIDACION_TOTAL', 'PAGO_PARCIAL', 'ANTICIPO'
                salario_pagado REAL DEFAULT 0.0,
                comisiones_pagadas REAL DEFAULT 0.0,
                ajustes_aplicados REAL DEFAULT 0.0,
                monto_pagado REAL NOT NULL,
                saldo_pendiente_antes REAL DEFAULT 0.0,
                saldo_pendiente_despues REAL DEFAULT 0.0,
                metodo_pago TEXT NOT NULL DEFAULT 'Efectivo',
                cuenta_afectada TEXT NOT NULL DEFAULT 'CAJA_FISICA',
                sesion_caja_id INTEGER DEFAULT NULL,
                movimiento_caja_id INTEGER DEFAULT NULL,
                movimiento_financiero_id INTEGER DEFAULT NULL,
                responsable TEXT NOT NULL DEFAULT 'Administrador',
                comprobante TEXT DEFAULT '',
                observaciones TEXT DEFAULT '',
                estado TEXT NOT NULL DEFAULT 'Completado'
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pag_usr_fecha ON nomina_pagos(usuario_id, fecha_pago)")

        conn_u.commit()
    except Exception as e:
        print(f"Error inicializando tablas en usuarios.db: {e}")
        return False
    finally:
        conn_u.close()

    # 5. Asegurar columnas de control de cartera por venta en ventas.db
    conn_v = conectar_ventas_db()
    if conn_v:
        try:
            cur_v = conn_v.cursor()
            for col_def in [
                "cliente_id INTEGER DEFAULT NULL",
                "saldo_pendiente REAL DEFAULT 0.0"
            ]:
                try:
                    cur_v.execute(f"ALTER TABLE ventas ADD COLUMN {col_def}")
                except sqlite3.OperationalError:
                    pass

            # Inicializar saldo_pendiente en ventas fiadas históricas que aún no lo tengan asignado
            cur_v.execute("""
                UPDATE ventas
                SET saldo_pendiente = total_venta
                WHERE metodo_pago = 'Fiado'
                  AND estado != 'Anulada'
                  AND (saldo_pendiente IS NULL OR saldo_pendiente = 0.0)
                  AND EXISTS (
                      SELECT 1 FROM clientes c
                      WHERE (c.cedula = ventas.documento_cliente OR CAST(c.id AS TEXT) = ventas.documento_cliente)
                        AND c.saldo_pendiente > 0
                  )
            """)
            conn_v.commit()
        except Exception as e_v:
            print(f"Aviso asegurando columnas en ventas.db: {e_v}")
        finally:
            conn_v.close()

    return True


def sincronizar_usuario_desde_dict(
    u: Dict[str, Any],
    conn_u: Optional[sqlite3.Connection] = None,
    forzar_config: bool = False
) -> Optional[int]:
    """
    Sincroniza un diccionario de usuario (proveniente de la API PostgreSQL o formulario de Usuarios)
    hacia la tabla `usuarios` de `usuarios.db` sin duplicar registros.
    """
    if not u or not isinstance(u, dict):
        return None
    owns_conn = conn_u is None
    if conn_u is None:
        inicializar_tablas_nomina()
        conn_u = conectar_usuarios_db()
    if not conn_u:
        return None
    try:
        conn_u.row_factory = sqlite3.Row
        cur = conn_u.cursor()

        u_login = str(u.get("usuario") or "").strip()
        u_nombre = str(u.get("nombre") or "").strip()
        u_apellidos = str(u.get("apellidos") or "").strip()
        nom_completo = f"{u_nombre} {u_apellidos}".strip()
        if not u_login and nom_completo:
            u_login = nom_completo
        if not u_login:
            return None

        u_rol = str(u.get("rol") or "Vendedor").strip()
        u_estado = str(u.get("estado") or "Activo").strip()
        u_tipo = str(u.get("tipo_remuneracion") or u.get("tipo_nomina") or "Porcentual").strip()
        u_salario = float(u.get("salario_diario") or 0.0)
        raw_com = u.get("porcentaje_comision") if u.get("porcentaje_comision") is not None else u.get("comision_porcentaje")
        u_comision = float(raw_com or 0.0)

        # Si ingresaron un valor en pesos (> 100) dejando el selector en 'Porcentual', normalizar a 'Fija'
        if u_tipo == "Porcentual" and u_salario == 0.0 and u_comision > 100.0:
            u_tipo = "Fija"
            u_salario = u_comision
            u_comision = 0.0

        cur.execute("""
            SELECT * FROM usuarios
            WHERE LOWER(usuario) = LOWER(?)
               OR (? != '' AND LOWER(usuario) = LOWER(?))
               OR (? != '' AND LOWER(TRIM(COALESCE(nombre, '') || ' ' || COALESCE(apellidos, ''))) = LOWER(?))
            LIMIT 1
        """, (u_login, nom_completo, nom_completo, nom_completo, nom_completo))
        row = cur.fetchone()

        if not row:
            # Si es un empleado nuevo (vendedor/operario) sin tarifa configurada aún (0 y 0),
            # heredar el salario diario base de su mismo rol en usuarios.db (ej. $50,000 COP para Vendedor)
            if u_rol.lower() in ("vendedor", "vendedora", "operario", "operador") and u_salario == 0.0 and u_comision == 0.0:
                cur.execute(
                    "SELECT tipo_nomina, salario_diario, comision_porcentaje FROM usuarios WHERE LOWER(rol) = LOWER(?) AND (salario_diario > 0 OR comision_porcentaje > 0) ORDER BY id ASC LIMIT 1",
                    (u_rol,)
                )
                ref_row = cur.fetchone()
                if ref_row:
                    u_tipo = str(ref_row[0] or "Fija")
                    u_salario = float(ref_row[1] or 0.0)
                    u_comision = float(ref_row[2] or 0.0)
                elif u_rol.lower() in ("vendedor", "vendedora"):
                    u_tipo = "Fija"
                    u_salario = 50000.0

            regla_def = "PRIMERA_VENTA" if es_rol_vendedor(u_rol) else "ASISTENCIA_DIRECTA"
            cur.execute("""
                INSERT INTO usuarios (
                    usuario, password, nombre, apellidos, rol, estado,
                    tipo_nomina, salario_diario, comision_porcentaje, regla_devengo,
                    comision_productos, comision_servicios, comision_fiados
                ) VALUES (?, '', ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, 0)
            """, (
                u_login, u_nombre, u_apellidos, u_rol, u_estado,
                u_tipo, u_salario, u_comision, regla_def
            ))
            uid_new = cur.lastrowid
            conn_u.commit()
            return int(uid_new)
        else:
            existing = dict(row)
            uid_ex = int(existing["id"])
            nuevo_nombre = u_nombre if u_nombre else (existing.get("nombre") or "")
            nuevo_apellidos = u_apellidos if u_apellidos else (existing.get("apellidos") or "")
            nuevo_rol = u_rol if u_rol else (existing.get("rol") or "Vendedor")
            nuevo_estado = u_estado if u_estado else (existing.get("estado") or "Activo")

            ex_tipo = str(existing.get("tipo_nomina") or "Porcentual")
            ex_sal = float(existing.get("salario_diario") or 0.0)
            ex_com = float(existing.get("comision_porcentaje") or 0.0)

            if forzar_config or u_salario > 0.0 or u_comision > 0.0:
                ex_tipo = u_tipo
                ex_sal = u_salario
                ex_com = u_comision

            cur.execute("""
                UPDATE usuarios
                SET nombre = ?,
                    apellidos = ?,
                    rol = ?,
                    estado = ?,
                    tipo_nomina = ?,
                    salario_diario = ?,
                    comision_porcentaje = ?
                WHERE id = ?
            """, (
                nuevo_nombre, nuevo_apellidos, nuevo_rol, nuevo_estado,
                ex_tipo, ex_sal, ex_com, uid_ex
            ))

            # Si el salario diario cambió y hoy tiene un devengo SAL pendiente, sincronizar el monto
            if ex_tipo in ("Fija", "Mixta") and ex_sal > 0.0:
                hoy_str = datetime.now().strftime("%Y-%m-%d")
                cod_sal_hoy = f"SAL-{uid_ex}-{hoy_str}"
                cur.execute("SELECT id, monto, estado FROM nomina_devengos WHERE codigo_unico = ?", (cod_sal_hoy,))
                dev_hoy = cur.fetchone()
                if dev_hoy and str(dev_hoy["estado"]) == "Pendiente" and abs(float(dev_hoy["monto"] or 0.0) - ex_sal) > 0.01:
                    cur.execute(
                        "UPDATE nomina_devengos SET monto = ?, base_calculo = ? WHERE id = ?",
                        (ex_sal, ex_sal, int(dev_hoy["id"]))
                    )
                    cur.execute(
                        "UPDATE asistencia SET monto_salario_generado = ? WHERE usuario_id = ? AND fecha = ?",
                        (ex_sal, uid_ex, hoy_str)
                    )
                    conn_v_sync = conectar_ventas_db()
                    if conn_v_sync:
                        try:
                            conn_v_sync.execute(
                                "UPDATE movimientos_financieros SET monto = ? WHERE referencia_origen = ? AND tipo = 'DEVENGO_NOMINA'",
                                (ex_sal, cod_sal_hoy)
                            )
                            conn_v_sync.commit()
                        except Exception:
                            pass
                        finally:
                            conn_v_sync.close()

            conn_u.commit()
            return uid_ex
    except Exception as e:
        print(f"Aviso sincronizando usuario a usuarios.db: {e}")
        return None
    finally:
        if owns_conn:
            conn_u.close()


def sincronizar_usuarios_con_api(conn_u: Optional[sqlite3.Connection] = None) -> int:
    """
    Sincroniza los usuarios registrados en el servidor FastAPI (PostgreSQL) y los operarios
    activos de `ventas.db` hacia `usuarios.db` para que Nómina y Ventas operen siempre sobre
    la misma base de empleados.
    No se ejecuta cuando `VMPOS_DB_USUARIOS` está definido (entorno de pruebas aisladas).
    """
    if os.environ.get("VMPOS_DB_USUARIOS"):
        return 0

    owns_conn = conn_u is None
    if conn_u is None:
        inicializar_tablas_nomina()
        conn_u = conectar_usuarios_db()
    if not conn_u:
        return 0

    sincronizados = 0
    try:
        items_api: List[Dict[str, Any]] = []
        try:
            from client.api_client import api
            if getattr(api, "token", None):
                resp = api.get("/usuarios?size=1000")
                if resp.status_code == 200:
                    data = resp.json()
                    items_api = data.get("items", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                if not items_api:
                    resp_me = api.get("/auth/me")
                    if resp_me.status_code == 200 and isinstance(resp_me.json(), dict):
                        items_api = [resp_me.json()]
        except Exception:
            pass

        for u_dict in items_api:
            uid_s = sincronizar_usuario_desde_dict(u_dict, conn_u=conn_u, forzar_config=False)
            if uid_s:
                sincronizados += 1
    except Exception as e:
        print(f"Aviso en sincronizar_usuarios_con_api: {e}")
    finally:
        if owns_conn:
            conn_u.close()
    return sincronizados


def resolver_usuario(
    usuario_id: Optional[int] = None,
    usuario_nombre: Optional[str] = None,
    rol: Optional[str] = None,
    conn_u: Optional[sqlite3.Connection] = None
) -> Optional[Dict[str, Any]]:
    """
    Busca y devuelve el diccionario completo del empleado en usuarios.db.
    Prioriza coincidencia exacta por nombre/usuario cuando ambos se suministran (para evitar
    colisiones entre IDs de PostgreSQL e IDs de SQLite) y sincroniza con la API si no existe aún.
    Jamás asigna por error otro empleado del mismo rol.
    """
    owns_conn = conn_u is None
    if conn_u is None:
        inicializar_tablas_nomina()
        conn_u = conectar_usuarios_db()
    if not conn_u:
        return None
    try:
        conn_u.row_factory = sqlite3.Row
        cur = conn_u.cursor()
        row = None
        nom_clean = str(usuario_nombre).strip() if usuario_nombre else ""

        def _buscar_local() -> Optional[sqlite3.Row]:
            r_loc = None
            if nom_clean:
                cur.execute("""
                    SELECT * FROM usuarios
                    WHERE LOWER(usuario) = LOWER(?)
                       OR LOWER(nombre) = LOWER(?)
                       OR LOWER(TRIM(COALESCE(nombre, '') || ' ' || COALESCE(apellidos, ''))) = LOWER(?)
                    LIMIT 1
                """, (nom_clean, nom_clean, nom_clean))
                r_loc = cur.fetchone()
            if not r_loc and usuario_id is not None:
                cur.execute("SELECT * FROM usuarios WHERE id = ?", (int(usuario_id),))
                cand = cur.fetchone()
                if cand:
                    if not nom_clean:
                        r_loc = cand
                    else:
                        c_usr = str(cand["usuario"] or "").strip().lower()
                        c_nom = str(cand["nombre"] or "").strip().lower()
                        c_full = f"{cand['nombre'] or ''} {cand['apellidos'] or ''}".strip().lower()
                        if nom_clean.lower() in (c_usr, c_nom, c_full):
                            r_loc = cand
            return r_loc

        row = _buscar_local()

        # Si no se encontró localmente y estamos en entorno real, sincronizar desde API
        if not row and not os.environ.get("VMPOS_DB_USUARIOS"):
            sincronizar_usuarios_con_api(conn_u=conn_u)
            row = _buscar_local()

            # Si aún no existe (ej. modo offline o creado con otro token) y tenemos un nombre válido de empleado
            if not row and nom_clean and nom_clean.lower() not in (
                "admin", "administrador", "admin principal", "sistema", "usuario", "consumidor final"
            ):
                rol_norm = str(rol or "").strip().lower()
                es_emp_rol = rol_norm in ("vendedor", "vendedora", "operario", "operador", "empleado")
                tiene_venta_local = False
                if not es_emp_rol:
                    conn_v = conectar_ventas_db()
                    if conn_v:
                        try:
                            cur_v = conn_v.cursor()
                            cur_v.execute(
                                "SELECT 1 FROM ventas WHERE LOWER(TRIM(operario)) = LOWER(?) LIMIT 1",
                                (nom_clean,)
                            )
                            tiene_venta_local = cur_v.fetchone() is not None
                        except Exception:
                            pass
                        finally:
                            conn_v.close()
                if es_emp_rol or tiene_venta_local:
                    partes = nom_clean.split(" ", 1)
                    nom_p = partes[0]
                    ape_p = partes[1] if len(partes) > 1 else ""
                    sincronizar_usuario_desde_dict({
                        "usuario": nom_clean,
                        "nombre": nom_p,
                        "apellidos": ape_p,
                        "rol": rol.capitalize() if rol_norm in ("vendedor", "vendedora", "operario") else "Vendedor",
                        "estado": "Activo"
                    }, conn_u=conn_u)
                    row = _buscar_local()

        return dict(row) if row else None
    finally:
        if owns_conn:
            conn_u.close()


def es_rol_vendedor(rol: str, regla_devengo: str = "Auto") -> bool:
    """
    Determina si el empleado se rige por la regla de vendedora:
    el salario diario se devenga únicamente al registrar la primera venta válida del día.
    """
    regla = (regla_devengo or "Auto").strip().upper()
    if regla in ("PRIMERA VENTA", "PRIMERA_VENTA"):
        return True
    if regla in ("ASISTENCIA", "ASISTENCIA_DIRECTA"):
        return False
    rol_norm = (rol or "").strip().lower()
    return rol_norm in ("vendedor", "vendedora")


def recalcular_saldo_empleado(usuario_id: int, conn_u: Optional[sqlite3.Connection] = None) -> Dict[str, float]:
    """
    Calcula a partir de las tablas reales (nomina_devengos y nomina_pagos) los totales del empleado
    y sincroniza `usuarios.comisiones_acumuladas` con el saldo pendiente real.
    """
    owns_conn = conn_u is None
    if conn_u is None:
        conn_u = conectar_usuarios_db()
    if not conn_u:
        return {
            "salarios_generados": 0.0,
            "salario_devengado": 0.0,
            "comisiones_generadas": 0.0,
            "comisiones_devengadas": 0.0,
            "ajustes_netos": 0.0,
            "total_devengado": 0.0,
            "total_pagado": 0.0,
            "anticipos": 0.0,
            "saldo_pendiente": 0.0
        }
    try:
        cur = conn_u.cursor()
        cur.execute("""
            SELECT tipo_concepto, COALESCE(SUM(monto), 0.0)
            FROM nomina_devengos
            WHERE usuario_id = ? AND estado NOT IN ('Anulado', 'REVERTIDO', 'Revertido')
            GROUP BY tipo_concepto
        """, (int(usuario_id),))
        por_tipo = {r[0]: float(r[1] or 0.0) for r in cur.fetchall()}

        salarios_gen = por_tipo.get("SALARIO_DIARIO", 0.0)
        comisiones_gen = por_tipo.get("COMISION_VENTA", 0.0)
        ajustes_pos = por_tipo.get("AJUSTE_POSITIVO", 0.0)
        ajustes_neg = por_tipo.get("AJUSTE_NEGATIVO", 0.0)  # Ya se guarda con signo negativo o se resta
        reversos = por_tipo.get("REVERSO_ANULACION", 0.0)

        # Normalizar signo de ajustes negativos/reversos por seguridad
        if ajustes_neg > 0:
            ajustes_neg = -ajustes_neg
        if reversos > 0:
            reversos = -reversos

        ajustes_netos = ajustes_pos + ajustes_neg + reversos
        total_devengado = salarios_gen + comisiones_gen + ajustes_netos

        cur.execute("""
            SELECT tipo_operacion, COALESCE(SUM(monto_pagado), 0.0)
            FROM nomina_pagos
            WHERE usuario_id = ? AND estado != 'Anulado'
            GROUP BY tipo_operacion
        """, (int(usuario_id),))
        pagos_tipo = {r[0]: float(r[1] or 0.0) for r in cur.fetchall()}

        anticipos = pagos_tipo.get("ANTICIPO", 0.0)
        total_pagado = sum(pagos_tipo.values())

        saldo_pendiente = round(total_devengado - total_pagado, 2)

        cur.execute(
            "UPDATE usuarios SET comisiones_acumuladas = ? WHERE id = ?",
            (max(0.0, saldo_pendiente), int(usuario_id))
        )
        conn_u.commit()

        return {
            "salarios_generados": round(salarios_gen, 2),
            "salario_devengado": round(salarios_gen, 2),
            "comisiones_generadas": round(comisiones_gen, 2),
            "comisiones_devengadas": round(comisiones_gen, 2),
            "ajustes_netos": round(ajustes_netos, 2),
            "total_devengado": round(total_devengado, 2),
            "total_pagado": round(total_pagado, 2),
            "anticipos": round(anticipos, 2),
            "saldo_pendiente": saldo_pendiente
        }
    finally:
        if owns_conn:
            conn_u.close()


def _registrar_evento_contable_devengo(
    fecha_str: str,
    hora_str: str,
    concepto: str,
    monto: float,
    usuario_responsable: str,
    referencia_origen: str,
    observaciones: str = ""
) -> Optional[int]:
    """
    Evento A (Fase 5): Devengo de nómina.
    Reconoce la obligación laboral en `movimientos_financieros` con cuenta_afectada='PASIVO_NOMINA'.
    NO produce salida de efectivo ni descuenta dinero de Caja Física ni de Bancos.
    Es idempotente por `referencia_origen`.
    """
    if abs(monto) < 0.01:
        return None
    conn_v = conectar_ventas_db()
    if not conn_v:
        return None
    try:
        cur_v = conn_v.cursor()
        cur_v.execute(
            "SELECT id FROM movimientos_financieros WHERE referencia_origen = ? AND tipo IN ('DEVENGO_NOMINA', 'AJUSTE_NOMINA') AND estado != 'Anulado'",
            (referencia_origen,)
        )
        existente = cur_v.fetchone()
        if existente:
            return existente[0]

        tipo_ev = "DEVENGO_NOMINA" if monto > 0 else "AJUSTE_NOMINA"
        cur_v.execute("""
            INSERT INTO movimientos_financieros (
                fecha, hora, tipo, concepto, monto, metodo_pago,
                cuenta_afectada, usuario, referencia_origen, sesion_caja_id,
                estado, observaciones
            ) VALUES (?, ?, ?, ?, ?, 'Devengo Contable', 'PASIVO_NOMINA', ?, ?, NULL, 'Activo', ?)
        """, (
            fecha_str, hora_str, tipo_ev, concepto, float(monto),
            usuario_responsable, referencia_origen, observaciones or "Reconocimiento contable de obligación laboral"
        ))
        mov_id = cur_v.lastrowid
        conn_v.commit()
        return mov_id
    except Exception as e:
        print(f"Aviso registrando devengo contable: {e}")
        return None
    finally:
        conn_v.close()


# ==============================================================================
# FASE 3: REGLAS DE ASISTENCIA Y NÓMINA DIARIA
# ==============================================================================

def registrar_asistencia_jornada(
    usuario_id: Optional[int] = None,
    usuario_nombre: Optional[str] = None,
    rol: Optional[str] = None,
    fecha: Optional[str] = None,
    estado_solicitado: str = "Presente",
    origen: str = "APERTURA_POS",
    responsable: str = "Sistema",
    id_venta_origen: Optional[int] = None
) -> Dict[str, Any]:
    """
    Registra o actualiza la asistencia de un empleado de forma idempotente para una fecha dada.

    REGLA ESPECÍFICA PARA VENDEDORAS (`es_rol_vendedor == True`):
    - Si `origen` es `'APERTURA_POS'` o `'ADMIN_MANUAL'` y aún NO tiene una venta válida en el día (`id_venta_origen is None`):
      - Se registra la asistencia con estado `'Asistencia Marcada (Sin Venta)'` (si estaba en Presente/Apertura).
      - `salario_generado = 0` -> NO se genera el salario diario antes de la primera venta válida.
    - Cuando registra su primera venta válida del día (`origen == 'PRIMERA_VENTA'` o `id_venta_origen is not None`):
      - Se confirma el estado `'Presente'`.
      - Si su `tipo_nomina` es `'Fija'` o `'Mixta'` y `salario_diario > 0`, se genera UNA SOLA VEZ el devengo
        `SAL-{uid}-{fecha}` por `salario_diario`.
      - Ventas posteriores o reaperturas del programa en la misma fecha jamás duplican asistencia ni salario.

    REGLA PARA OPERARIOS Y DEMÁS EMPLEADOS (`es_rol_vendedor == False`):
    - Conservan su comportamiento actual: al marcarse `'Presente'`, si su `tipo_nomina` es `'Fija'` o `'Mixta'`
      y `salario_diario > 0`, generan su salario diario una única vez en la jornada (`SAL-{uid}-{fecha}`).
    """
    inicializar_tablas_nomina()
    ahora = datetime.now()
    fecha_str = fecha or ahora.strftime("%Y-%m-%d")
    hora_str = ahora.strftime("%H:%M:%S")
    periodo_str = fecha_str[:7]

    conn_u = conectar_usuarios_db()
    if not conn_u:
        return {"ok": False, "exito": False, "error": "No se pudo conectar a usuarios.db"}

    try:
        conn_u.row_factory = sqlite3.Row
        cur = conn_u.cursor()

        emp = resolver_usuario(usuario_id=usuario_id, usuario_nombre=usuario_nombre, rol=rol, conn_u=conn_u)
        if not emp:
            return {"ok": False, "exito": False, "error": "Empleado no encontrado"}

        uid = int(emp["id"])
        uname = str(emp["usuario"])
        rol_emp = str(emp.get("rol") or rol or "operario")
        tipo_nomina = str(emp.get("tipo_nomina") or "Porcentual")
        salario_diario = float(emp.get("salario_diario") or 0.0)
        regla_dev = str(emp.get("regla_devengo") or "Auto")
        es_vendedora = es_rol_vendedor(rol_emp, regla_dev)

        # Consultar si ya existe asistencia para (uid, fecha_str)
        cur.execute("SELECT * FROM asistencia WHERE usuario_id = ? AND fecha = ?", (uid, fecha_str))
        asist_row = cur.fetchone()
        asist_actual = dict(asist_row) if asist_row else None

        # Verificar si la vendedora ya tiene una venta válida en esa fecha
        venta_valida_id = id_venta_origen
        if es_vendedora and venta_valida_id is None and estado_solicitado in ("Presente", "Asistencia Marcada (Sin Venta)"):
            conn_v = conectar_ventas_db()
            if conn_v:
                try:
                    cur_v = conn_v.cursor()
                    nom_completo = f"{emp.get('nombre', '')} {emp.get('apellidos', '')}".strip()
                    cur_v.execute("""
                        SELECT id_venta FROM ventas
                        WHERE fecha_venta = ?
                          AND (estado IS NULL OR estado != 'Anulada')
                          AND (LOWER(operario) = LOWER(?) OR LOWER(operario) = LOWER(?) OR LOWER(operario) = LOWER(?))
                        ORDER BY id_venta ASC LIMIT 1
                    """, (fecha_str, uname, str(emp.get("nombre", "")), nom_completo))
                    v_row = cur_v.fetchone()
                    if v_row:
                        venta_valida_id = int(v_row[0])
                except Exception:
                    pass
                finally:
                    conn_v.close()

        # Determinar estado efectivo y si es elegible para devengar salario diario ahora
        if estado_solicitado in ("Ausente", "Permiso", "Incapacidad"):
            estado_final = estado_solicitado
            elegible_salario = False
        elif es_vendedora:
            if venta_valida_id is not None:
                estado_final = "Presente"
                elegible_salario = (tipo_nomina in ("Fija", "Mixta") and salario_diario > 0)
            else:
                # Si ya estaba confirmada como Presente con venta previa, preservarlo
                if asist_actual and asist_actual.get("primera_venta_id"):
                    estado_final = "Presente"
                    venta_valida_id = asist_actual.get("primera_venta_id")
                    elegible_salario = (tipo_nomina in ("Fija", "Mixta") and salario_diario > 0)
                else:
                    estado_final = "Asistencia Marcada (Sin Venta)"
                    elegible_salario = False
        else:
            # Operario u otro empleado
            if origen == "APERTURA_POS" and asist_actual:
                # Si ya tenía registro hoy al reabrir el POS, no alterar ni duplicar
                estado_final = asist_actual["estado"]
                elegible_salario = (estado_final == "Presente" and tipo_nomina in ("Fija", "Mixta") and salario_diario > 0)
            else:
                estado_final = "Presente" if estado_solicitado == "Presente" else estado_solicitado
                elegible_salario = (estado_final == "Presente" and tipo_nomina in ("Fija", "Mixta") and salario_diario > 0)

        # Insertar o actualizar registro de asistencia sin duplicar
        if not asist_actual:
            obs = (
                f"Confirmada con Venta #{venta_valida_id}"
                if venta_valida_id
                else ("Asistencia en apertura POS (pendiente 1ª venta)" if es_vendedora else f"Registro ({origen})")
            )
            cur.execute("""
                INSERT INTO asistencia (
                    usuario_id, usuario_nombre, rol, fecha, hora_registro, estado,
                    primera_venta_id, salario_generado, monto_salario_generado, responsable, observaciones
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0.0, ?, ?)
            """, (uid, uname, rol_emp, fecha_str, hora_str, estado_final, venta_valida_id, responsable, obs))
            asistencia_id = cur.lastrowid
            ya_generado = False
        else:
            asistencia_id = asist_actual["id"]
            ya_generado = bool(asist_actual.get("salario_generado", 0))
            primera_v = asist_actual.get("primera_venta_id") or venta_valida_id
            obs = asist_actual.get("observaciones") or ""
            if venta_valida_id and not asist_actual.get("primera_venta_id"):
                obs = f"Confirmada con 1ª Venta #{venta_valida_id}"
            cur.execute("""
                UPDATE asistencia
                SET estado = ?,
                    primera_venta_id = ?,
                    usuario_nombre = COALESCE(NULLIF(usuario_nombre, ''), ?),
                    rol = COALESCE(NULLIF(rol, ''), ?),
                    observaciones = ?
                WHERE id = ?
            """, (estado_final, primera_v, uname, rol_emp, obs, asistencia_id))

        # Generar devengo de salario diario SI Y SOLO SI es elegible y NO se ha generado en esta fecha
        codigo_sal = f"SAL-{uid}-{fecha_str}"
        cur.execute("SELECT id, estado FROM nomina_devengos WHERE codigo_unico = ?", (codigo_sal,))
        dev_existente = cur.fetchone()

        salario_recien_generado = False
        monto_devengado_hoy = 0.0

        if elegible_salario and not ya_generado and not dev_existente:
            ref_origen = f"VENTA-{venta_valida_id}" if venta_valida_id else f"JORNADA-{asistencia_id}"
            concepto_txt = (
                f"Salario diario por jornada ({fecha_str}) - Confirmado en 1ª Venta #{venta_valida_id}"
                if venta_valida_id
                else f"Salario diario por jornada de asistencia ({fecha_str})"
            )
            cur.execute("""
                INSERT INTO nomina_devengos (
                    codigo_unico, usuario_id, usuario_nombre, rol, fecha, hora, periodo,
                    tipo_concepto, concepto, monto, monto_pagado, referencia_origen,
                    id_venta, tipo_item, item_nombre, base_calculo, porcentaje_aplicado,
                    estado, responsable, motivo
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'SALARIO_DIARIO', ?, ?, 0.0, ?, ?, 'Jornada', 'Salario Diario', ?, 100.0, 'Pendiente', ?, ?)
            """, (
                codigo_sal, uid, uname, rol_emp, fecha_str, hora_str, periodo_str,
                concepto_txt, salario_diario, ref_origen, venta_valida_id,
                salario_diario, responsable, f"Devengo automático según modalidad {tipo_nomina}"
            ))
            cur.execute("""
                UPDATE asistencia
                SET salario_generado = 1, monto_salario_generado = ?
                WHERE id = ?
            """, (salario_diario, asistencia_id))
            salario_recien_generado = True
            monto_devengado_hoy = salario_diario

        conn_u.commit()
        saldos = recalcular_saldo_empleado(uid, conn_u=conn_u)
        conn_u.commit()

        # Registrar devengo contable en movimientos_financieros (sin afectar caja física)
        if salario_recien_generado and monto_devengado_hoy > 0:
            _registrar_evento_contable_devengo(
                fecha_str=fecha_str,
                hora_str=hora_str,
                concepto=f"Devengo salario diario - {uname} ({fecha_str})",
                monto=monto_devengado_hoy,
                usuario_responsable=responsable,
                referencia_origen=codigo_sal,
                observaciones=f"Jornada #{asistencia_id}"
            )

        monto_sal_final = monto_devengado_hoy if salario_recien_generado else (
            float(asist_actual.get("monto_salario_generado", 0.0)) if asist_actual else 0.0
        )
        sal_gen_bool = bool(salario_recien_generado or ya_generado)

        return {
            "ok": True,
            "exito": True,
            "asistencia_id": asistencia_id,
            "usuario_id": uid,
            "usuario": uname,
            "rol": rol_emp,
            "es_vendedora": es_vendedora,
            "fecha": fecha_str,
            "estado": estado_final,
            "primera_venta_id": venta_valida_id,
            "salario_recien_generado": salario_recien_generado,
            "salario_generado": sal_gen_bool,
            "monto_salario_generado": monto_sal_final,
            "monto_salario": monto_sal_final,
            "saldo_pendiente_total": saldos["saldo_pendiente"]
        }
    except Exception as e:
        print(f"Error en registrar_asistencia_jornada: {e}")
        return {"ok": False, "exito": False, "error": str(e)}
    finally:
        conn_u.close()


# ==============================================================================
# FASE 4: CÁLCULO DE COMISIONES Y REGISTRO DE PRIMERA VENTA
# ==============================================================================

def procesar_venta_nomina_y_comisiones(
    id_venta: int,
    operario_nombre: str = "",
    total_venta: float = 0.0,
    metodo_pago: str = "Efectivo",
    detalles_payload: Optional[List[Dict[str, Any]]] = None,
    detalles_venta: Optional[List[Dict[str, Any]]] = None,
    usuario_id: Optional[int] = None,
    fecha: Optional[str] = None,
    fecha_venta: Optional[str] = None
) -> Dict[str, Any]:
    """
    Se ejecuta al completar una venta válida:
    1. Confirma la asistencia de la jornada del empleado/vendedora y genera el salario diario
       SOLO si es la primera venta válida del día y corresponde a su modalidad de nómina (`Fija` o `Mixta`).
    2. Calcula las comisiones aplicables según el porcentaje y reglas del empleado:
       - No calcula comisiones sobre ventas anuladas.
       - Si es una venta `Fiado` y el empleado tiene `comision_fiados == 0`, no devenga comisión sobre fiado no autorizado.
       - Respeta `comision_productos` y `comision_servicios`.
       - Registra cada comisión con llave única `COM-{id_venta}-{idx}-{uid}` para impedir duplicaciones.
    """
    inicializar_tablas_nomina()
    ahora = datetime.now()
    fecha_str = fecha or fecha_venta or ahora.strftime("%Y-%m-%d")
    hora_str = ahora.strftime("%H:%M:%S")
    periodo_str = fecha_str[:7]
    lista_detalles = detalles_payload if detalles_payload is not None else (detalles_venta or [])

    # 1. Confirmar asistencia y evaluar primera venta del día para salario diario
    res_asist = registrar_asistencia_jornada(
        usuario_id=usuario_id,
        usuario_nombre=operario_nombre,
        fecha=fecha_str,
        estado_solicitado="Presente",
        origen="PRIMERA_VENTA",
        responsable=operario_nombre or "Sistema",
        id_venta_origen=id_venta
    )
    if not res_asist.get("ok"):
        return res_asist

    uid = res_asist["usuario_id"]
    uname = res_asist["usuario"]
    rol = res_asist["rol"]

    conn_u = conectar_usuarios_db()
    if not conn_u:
        return res_asist

    comision_total_venta = 0.0
    items_comisionados = 0

    try:
        conn_u.row_factory = sqlite3.Row
        cur = conn_u.cursor()
        cur.execute("SELECT * FROM usuarios WHERE id = ?", (uid,))
        emp = dict(cur.fetchone())

        tipo_nomina = str(emp.get("tipo_nomina") or "Porcentual")
        porc_com = float(emp.get("comision_porcentaje") or 0.0)
        permite_prod = bool(int(emp.get("comision_productos", 1) if emp.get("comision_productos") is not None else 1))
        permite_serv = bool(int(emp.get("comision_servicios", 1) if emp.get("comision_servicios") is not None else 1))
        permite_fiado = bool(int(emp.get("comision_fiados", 0) if emp.get("comision_fiados") is not None else 0))

        # Verificar si el empleado devenga comisiones porcentuales
        aplica_comision = porc_com > 0 and tipo_nomina in ("Porcentual", "Porcentaje", "Mixta", "Fija")
        if str(metodo_pago).strip() == "Fiado" and not permite_fiado:
            aplica_comision = False

        if aplica_comision and lista_detalles:
            for idx, det in enumerate(lista_detalles, start=1):
                tipo_it = str(det.get("tipo_item", det.get("tipo_producto", "Producto")) or "Producto")
                es_servicio = "serv" in tipo_it.lower()
                if es_servicio and not permite_serv:
                    continue
                if not es_servicio and not permite_prod:
                    continue

                sub = float(det.get("subtotal", 0.0) or 0.0)
                if sub <= 0:
                    pre = float(det.get("precio_vendido", det.get("precio_unitario", det.get("precio", 0.0))) or 0.0)
                    cant = int(det.get("cantidad", 1) or 1)
                    sub = pre * cant

                if sub <= 0:
                    continue

                # Base de comisión: sobre el valor de la venta del ítem elegible (estándar comercial de VmPOS)
                base_calc = sub
                monto_com = round(base_calc * (porc_com / 100.0), 2)
                if monto_com <= 0:
                    continue

                id_det = det.get("id_detalle") or idx
                codigo_com = f"COM-{id_venta}-{idx}-{uid}"
                item_nom = str(det.get("item_nombre", det.get("nombre_producto", det.get("nombre", "Artículo"))))

                cur.execute("SELECT id FROM nomina_devengos WHERE codigo_unico = ?", (codigo_com,))
                if cur.fetchone():
                    continue  # Ya registrado, evita duplicación

                cur.execute("""
                    INSERT INTO nomina_devengos (
                        codigo_unico, usuario_id, usuario_nombre, rol, fecha, hora, periodo,
                        tipo_concepto, concepto, monto, monto_pagado, referencia_origen,
                        id_venta, id_detalle_venta, tipo_item, item_nombre,
                        base_calculo, porcentaje_aplicado, estado, responsable, motivo
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'COMISION_VENTA', ?, ?, 0.0, ?, ?, ?, ?, ?, ?, ?, 'Pendiente', ?, ?)
                """, (
                    codigo_com, uid, uname, rol, fecha_str, hora_str, periodo_str,
                    f"Comisión ({porc_com:g}%) Venta #{id_venta} - {item_nom}",
                    monto_com, f"VENTA-{id_venta}",
                    id_venta, int(id_det), "Servicio" if es_servicio else "Producto", item_nom,
                    base_calc, porc_com, operario_nombre, f"Comisión de venta ({metodo_pago})"
                ))
                comision_total_venta += monto_com
                items_comisionados += 1

        conn_u.commit()
        saldos = recalcular_saldo_empleado(uid, conn_u=conn_u)
        conn_u.commit()

        if comision_total_venta > 0:
            _registrar_evento_contable_devengo(
                fecha_str=fecha_str,
                hora_str=hora_str,
                concepto=f"Devengo comisiones Venta #{id_venta} - {uname}",
                monto=comision_total_venta,
                usuario_responsable=operario_nombre,
                referencia_origen=f"COM-VENTA-{id_venta}-{uid}",
                observaciones=f"{items_comisionados} ítem(s) comisionados"
            )

        msg_partes = []
        if res_asist.get("salario_recien_generado"):
            sal_m = res_asist.get("monto_salario_generado", 0.0)
            msg_partes.append(f"📅 ¡Asistencia confirmada con tu 1ª venta de hoy! Salario diario generado: ${sal_m:,.0f} COP")
        if comision_total_venta > 0:
            msg_partes.append(f"💰 Comisión generada en esta venta: ${comision_total_venta:,.0f} COP")

        return {
            "ok": True,
            "exito": True,
            "usuario_id": uid,
            "usuario": uname,
            "asistencia_id": res_asist.get("asistencia_id"),
            "estado_asistencia": res_asist.get("estado"),
            "asistencia_confirmada": bool(res_asist.get("salario_recien_generado")),
            "salario_recien_generado": res_asist.get("salario_recien_generado", False),
            "monto_salario_generado": res_asist.get("monto_salario_generado", 0.0),
            "salario_generado": res_asist.get("monto_salario_generado", 0.0) if res_asist.get("salario_recien_generado") else 0.0,
            "comision_generada": round(comision_total_venta, 2),
            "items_comisionados": items_comisionados,
            "saldo_pendiente_total": saldos["saldo_pendiente"],
            "mensaje": "\n".join(msg_partes) if msg_partes else None
        }
    except Exception as e:
        print(f"Error en procesar_venta_nomina_y_comisiones: {e}")
        return {"ok": False, "exito": False, "error": str(e)}
    finally:
        conn_u.close()


def revertir_devengos_por_venta_anulada(
    id_venta: int,
    usuario_responsable: str = "Administrador",
    motivo: str = "Anulación de venta"
) -> Dict[str, Any]:
    """
    Maneja de forma explícita y trazable las ventas anuladas (Fases 3, 4 y 5):
    - NUNCA borra registros históricos (`DELETE` prohibido).
    - Para comisiones asociadas a `id_venta`:
      - Si el devengo está `'Pendiente'`, lo marca como `'REVERTIDO'` con referencia al motivo.
      - Si el devengo ya fue `'Liquidado'` o `'Parcial'` en un período cerrado, NO altera silenciosamente
        el pago pasado, sino que inserta un registro `'REVERSO_ANULACION'` (negativo) auditable en la fecha actual.
    - Si `id_venta` fue la `primera_venta_id` que originó el salario diario de una vendedora ese día:
      - Verifica si existen otras ventas activas de la vendedora en esa misma fecha.
      - Si existe otra venta activa ese día, reasigna `primera_venta_id` a esa venta y conserva el salario diario.
      - Si NO quedó ninguna venta válida en esa fecha, anula/revierte trazablemente el salario diario de esa jornada.
    """
    inicializar_tablas_nomina()
    ahora = datetime.now()
    fecha_str = ahora.strftime("%Y-%m-%d")
    hora_str = ahora.strftime("%H:%M:%S")
    periodo_str = fecha_str[:7]

    conn_u = conectar_usuarios_db()
    if not conn_u:
        return {"ok": False, "exito": False, "error": "No se pudo conectar a usuarios.db"}

    try:
        conn_u.row_factory = sqlite3.Row
        cur = conn_u.cursor()

        cur.execute(
            "SELECT * FROM nomina_devengos WHERE id_venta = ? AND estado NOT IN ('Anulado', 'REVERTIDO', 'Revertido')",
            (int(id_venta),)
        )
        devengos = [dict(r) for r in cur.fetchall()]
        usuarios_afectados = set()
        total_revertido = 0.0

        for d in devengos:
            uid = int(d["usuario_id"])
            usuarios_afectados.add(uid)
            tipo_c = d["tipo_concepto"]
            monto_orig = float(d["monto"] or 0.0)

            # Si es SALARIO_DIARIO originado por la primera venta, comprobar si hay otra venta activa ese día
            if tipo_c == "SALARIO_DIARIO":
                fecha_jornada = d["fecha"]
                uname = d["usuario_nombre"]
                otra_venta_id = None
                conn_v = conectar_ventas_db()
                if conn_v:
                    try:
                        cur_v = conn_v.cursor()
                        cur_v.execute("""
                            SELECT id_venta FROM ventas
                            WHERE fecha_venta = ?
                              AND id_venta != ?
                              AND (estado IS NULL OR estado != 'Anulada')
                              AND LOWER(operario) = LOWER(?)
                            ORDER BY id_venta ASC LIMIT 1
                        """, (fecha_jornada, int(id_venta), uname))
                        ov = cur_v.fetchone()
                        if ov:
                            otra_venta_id = int(ov[0])
                    finally:
                        conn_v.close()

                if otra_venta_id is not None:
                    # Reasignar primera venta a la siguiente venta válida del día y conservar salario diario
                    cur.execute(
                        "UPDATE asistencia SET primera_venta_id = ?, observaciones = ? WHERE usuario_id = ? AND fecha = ?",
                        (otra_venta_id, f"Reasignada 1ª venta a #{otra_venta_id} tras anular #{id_venta}", uid, fecha_jornada)
                    )
                    cur.execute(
                        "UPDATE nomina_devengos SET id_venta = ?, referencia_origen = ? WHERE id = ?",
                        (otra_venta_id, f"VENTA-{otra_venta_id}", d["id"])
                    )
                    continue
                else:
                    # No quedaron ventas válidas ese día para la vendedora
                    cur.execute(
                        "UPDATE asistencia SET estado = 'Asistencia Marcada (Sin Venta)', primera_venta_id = NULL, salario_generado = 0, monto_salario_generado = 0.0, observaciones = ? WHERE usuario_id = ? AND fecha = ?",
                        (f"Venta #{id_venta} anulada ({motivo}); sin ventas activas en el día", uid, fecha_jornada)
                    )

            if d["estado"] == "Pendiente" and float(d.get("monto_pagado") or 0.0) == 0.0:
                cur.execute("""
                    UPDATE nomina_devengos
                    SET estado = 'REVERTIDO',
                        motivo = COALESCE(motivo, '') || ' | Revertido por anulación Venta #' || ? || ': ' || ?
                    WHERE id = ?
                """, (int(id_venta), motivo, d["id"]))
                total_revertido += monto_orig
            else:
                # Ya fue liquidado o pagado parcialmente: crear registro explícito de REVERSO_ANULACION sin tocar el período cerrado
                cod_rev = f"REV-{d['codigo_unico']}"
                cur.execute("SELECT id FROM nomina_devengos WHERE codigo_unico = ?", (cod_rev,))
                if not cur.fetchone():
                    cur.execute("""
                        INSERT INTO nomina_devengos (
                            codigo_unico, usuario_id, usuario_nombre, rol, fecha, hora, periodo,
                            tipo_concepto, concepto, monto, monto_pagado, referencia_origen,
                            id_venta, id_detalle_venta, tipo_item, item_nombre,
                            base_calculo, porcentaje_aplicado, estado, responsable, motivo
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'REVERSO_ANULACION', ?, ?, 0.0, ?, ?, ?, ?, ?, ?, ?, 'REVERTIDO', ?, ?)
                    """, (
                        cod_rev, uid, d["usuario_nombre"], d.get("rol", ""), fecha_str, hora_str, periodo_str,
                        f"Reverso por anulación de Venta #{id_venta} ({d['concepto']})",
                        -abs(monto_orig), f"ANULACION-VENTA-{id_venta}",
                        int(id_venta), d.get("id_detalle_venta"), d.get("tipo_item", "Reverso"), d.get("item_nombre", ""),
                        float(d.get("base_calculo") or 0.0), float(d.get("porcentaje_aplicado") or 0.0),
                        usuario_responsable, motivo
                    ))
                    total_revertido += monto_orig

        conn_u.commit()
        for uid in usuarios_afectados:
            recalcular_saldo_empleado(uid, conn_u=conn_u)
        conn_u.commit()

        if total_revertido > 0:
            _registrar_evento_contable_devengo(
                fecha_str=fecha_str,
                hora_str=hora_str,
                concepto=f"Reverso devengo nómina/comisión por anulación Venta #{id_venta}",
                monto=-abs(total_revertido),
                usuario_responsable=usuario_responsable,
                referencia_origen=f"REV-NOM-VENTA-{id_venta}",
                observaciones=motivo
            )

        return {"ok": True, "exito": True, "total_revertido": round(total_revertido, 2), "usuarios_afectados": list(usuarios_afectados)}
    except Exception as e:
        print(f"Error en revertir_devengos_por_venta_anulada: {e}")
        return {"ok": False, "exito": False, "error": str(e)}
    finally:
        conn_u.close()


# ==============================================================================
# FASE 5: PAGOS DE NÓMINA (TOTAL, PARCIAL, ANTICIPO) Y AJUSTES AUDITADOS
# ==============================================================================

def registrar_ajuste_nomina(
    usuario_id: int,
    monto: float,
    tipo_ajuste: str = "AJUSTE_POSITIVO",
    es_positivo: Optional[bool] = None,
    motivo: str = "",
    responsable: str = "Administrador",
    fecha: Optional[str] = None
) -> Dict[str, Any]:
    """
    Evento C (Fase 5): Registra un ajuste positivo (bonificación/reconocimiento) o negativo (descuento/reverso)
    con trazabilidad de responsable, fecha y motivo obligatorio.
    """
    inicializar_tablas_nomina()
    if abs(float(monto or 0.0)) < 0.01:
        return {"ok": False, "exito": False, "mensaje": "El importe del ajuste debe ser mayor a cero."}
    if not motivo or len(motivo.strip()) < 3:
        return {"ok": False, "exito": False, "mensaje": "Debe especificar un motivo válido para el ajuste (mínimo 3 caracteres)."}

    ahora = datetime.now()
    fecha_str = fecha or ahora.strftime("%Y-%m-%d")
    hora_str = ahora.strftime("%H:%M:%S")
    periodo_str = fecha_str[:7]

    if es_positivo is not None:
        es_negativo = not bool(es_positivo)
    else:
        es_negativo = tipo_ajuste in ("AJUSTE_NEGATIVO", "REVERSO_ANULACION", "DESCUENTO") or float(monto) < 0

    tipo_norm = "AJUSTE_NEGATIVO" if es_negativo else "AJUSTE_POSITIVO"
    monto_firmado = -abs(float(monto)) if es_negativo else abs(float(monto))

    conn_u = conectar_usuarios_db()
    if not conn_u:
        return {"ok": False, "exito": False, "mensaje": "No se pudo conectar a usuarios.db"}

    try:
        emp = resolver_usuario(usuario_id=usuario_id, conn_u=conn_u)
        if not emp:
            return {"ok": False, "exito": False, "mensaje": f"No se encontró el empleado #{usuario_id}"}

        uid = int(emp["id"])
        uname = str(emp["usuario"])
        rol = str(emp.get("rol") or "")
        codigo_aj = f"AJU-{uid}-{ahora.strftime('%Y%m%d%H%M%S%f')}"

        cur = conn_u.cursor()
        cur.execute("""
            INSERT INTO nomina_devengos (
                codigo_unico, usuario_id, usuario_nombre, rol, fecha, hora, periodo,
                tipo_concepto, concepto, monto, monto_pagado, referencia_origen,
                tipo_item, item_nombre, base_calculo, porcentaje_aplicado,
                estado, responsable, motivo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, 'AJUSTE_ADMIN', 'Ajuste', ?, ?, 0.0, 'Pendiente', ?, ?)
        """, (
            codigo_aj, uid, uname, rol, fecha_str, hora_str, periodo_str,
            tipo_norm, f"{'Descuento/Ajuste (-)' if es_negativo else 'Bonificación/Ajuste (+)'}: {motivo}",
            monto_firmado, motivo, abs(monto_firmado), responsable, motivo
        ))
        ajuste_id = cur.lastrowid
        conn_u.commit()
        saldos = recalcular_saldo_empleado(uid, conn_u=conn_u)
        conn_u.commit()

        _registrar_evento_contable_devengo(
            fecha_str=fecha_str,
            hora_str=hora_str,
            concepto=f"Ajuste de nómina ({uname}): {motivo}",
            monto=monto_firmado,
            usuario_responsable=responsable,
            referencia_origen=codigo_aj,
            observaciones=motivo
        )

        return {
            "ok": True,
            "exito": True,
            "ajuste_id": ajuste_id,
            "codigo": codigo_aj,
            "usuario_id": uid,
            "usuario": uname,
            "monto": monto_firmado,
            "saldos": saldos,
            "mensaje": f"Ajuste ({tipo_norm}) registrado por ${abs(monto_firmado):,.0f} COP."
        }
    except Exception as e:
        return {"ok": False, "exito": False, "mensaje": str(e)}
    finally:
        conn_u.close()


def registrar_pago_nomina(
    usuario_id: int,
    monto_pagado: float,
    metodo_pago: str = "Efectivo",
    tipo_operacion: str = "LIQUIDACION_TOTAL",
    tipo_pago: Optional[str] = None,
    periodo_inicio: Optional[str] = None,
    periodo_fin: Optional[str] = None,
    responsable: str = "Administrador",
    comprobante: str = "",
    observaciones: str = "",
    fecha_pago: Optional[str] = None,
    sesion_caja_id: Optional[int] = None,
    permitir_caja_cerrada: bool = True
) -> Dict[str, Any]:
    """
    Evento B (Fase 5): Registra un pago de nómina (liquidación total, pago parcial o anticipo).
    - Distingue claramente valores devengados, valores pagados, anticipos y saldo pendiente.
    - Si `metodo_pago == 'Efectivo'`:
      - Registra UNA SOLA SALIDA en `Control de Caja` (`movimientos_caja` tipo `'EGRESO'`) y sincroniza
        con `movimientos_financieros` (`cuenta_afectada = 'CAJA_FISICA'`, `tipo = 'GASTO_PAGADO'`).
    - Si `metodo_pago == 'Transferencia'`:
      - Registra el movimiento en `movimientos_financieros` (`cuenta_afectada = 'BANCO_TRANSFERENCIA'`,
        `tipo = 'GASTO_PAGADO'`) sin descontar efectivo físico de la gaveta.
    - Actualiza el estado de los devengos cubiertos (`Liquidado` o `Parcial`) en orden FIFO.
    """
    inicializar_tablas_nomina()
    monto_pagado = round(float(monto_pagado or 0.0), 2)
    if monto_pagado <= 0:
        return {"ok": False, "exito": False, "mensaje": "El monto a pagar debe ser mayor a cero."}

    tipo_op_solicitado = tipo_pago or tipo_operacion or "LIQUIDACION_TOTAL"
    metodo_norm = "Transferencia" if "transf" in str(metodo_pago).lower() else "Efectivo"
    cuenta_afectada = "BANCO_TRANSFERENCIA" if metodo_norm == "Transferencia" else "CAJA_FISICA"

    try:
        from caja_manager import registrar_movimiento_caja, registrar_movimiento_financiero, obtener_sesion_activa
    except ImportError:
        from interface.caja_manager import registrar_movimiento_caja, registrar_movimiento_financiero, obtener_sesion_activa

    if metodo_norm == "Efectivo" and not permitir_caja_cerrada:
        conn_check = conectar_ventas_db()
        if conn_check:
            try:
                activa_chk = obtener_sesion_activa(conn=conn_check)
                if not activa_chk:
                    return {
                        "ok": False,
                        "exito": False,
                        "mensaje": "No hay una sesión de caja abierta. Abra la caja antes de pagar nómina en Efectivo, o elija Transferencia."
                    }
            finally:
                conn_check.close()

    ahora = datetime.now()
    fecha_str = fecha_pago or ahora.strftime("%Y-%m-%d")
    hora_str = ahora.strftime("%H:%M:%S")
    if periodo_inicio and periodo_fin:
        periodo_str = f"{periodo_inicio} a {periodo_fin}" if periodo_inicio != periodo_fin else periodo_inicio[:7]
    else:
        periodo_str = fecha_str[:7]

    conn_u = conectar_usuarios_db()
    if not conn_u:
        return {"ok": False, "exito": False, "mensaje": "No se pudo conectar a usuarios.db"}

    try:
        conn_u.row_factory = sqlite3.Row
        cur_u = conn_u.cursor()

        emp = resolver_usuario(usuario_id=usuario_id, conn_u=conn_u)
        if not emp:
            return {"ok": False, "exito": False, "mensaje": f"Empleado #{usuario_id} no encontrado."}

        uid = int(emp["id"])
        uname = str(emp["usuario"])
        rol = str(emp.get("rol") or "")

        saldos_antes = recalcular_saldo_empleado(uid, conn_u=conn_u)
        saldo_antes = float(saldos_antes["saldo_pendiente"])

        # Determinar tipo de operación real según el saldo pendiente
        if tipo_op_solicitado == "ANTICIPO" or saldo_antes <= 0.0:
            tipo_op_final = "ANTICIPO"
        elif monto_pagado < (saldo_antes - 0.01):
            tipo_op_final = "PAGO_PARCIAL"
        else:
            tipo_op_final = "LIQUIDACION_TOTAL"

        codigo_pago = f"PAG-NOM-{uid}-{ahora.strftime('%Y%m%d%H%M%S%f')}"

        # Distribuir el monto pagado sobre los devengos pendientes (FIFO)
        cur_u.execute("""
            SELECT * FROM nomina_devengos
            WHERE usuario_id = ? AND estado IN ('Pendiente', 'Parcial') AND monto > 0
            ORDER BY fecha ASC, id ASC
        """, (uid,))
        pendientes = [dict(r) for r in cur_u.fetchall()]

        remanente = monto_pagado
        sal_cubierto = 0.0
        com_cubierta = 0.0
        aju_cubierto = 0.0
        ids_tocados = []

        for dev in pendientes:
            if remanente <= 0.001:
                break
            monto_dev = float(dev["monto"] or 0.0)
            pagado_prev = float(dev.get("monto_pagado") or 0.0)
            falta_dev = max(0.0, monto_dev - pagado_prev)
            if falta_dev <= 0.001:
                continue

            abono_dev = min(remanente, falta_dev)
            nuevo_pagado = round(pagado_prev + abono_dev, 2)
            nuevo_estado = "Liquidado" if abs(monto_dev - nuevo_pagado) <= 0.01 else "Parcial"

            cur_u.execute("""
                UPDATE nomina_devengos
                SET monto_pagado = ?, estado = ?
                WHERE id = ?
            """, (nuevo_pagado, nuevo_estado, dev["id"]))
            ids_tocados.append(dev["id"])

            tc = dev["tipo_concepto"]
            if tc == "SALARIO_DIARIO":
                sal_cubierto += abono_dev
            elif tc == "COMISION_VENTA":
                com_cubierta += abono_dev
            else:
                aju_cubierto += abono_dev

            remanente = round(remanente - abono_dev, 2)

        saldo_despues = round(saldo_antes - monto_pagado, 2)

        # Insertar registro en nomina_pagos
        cur_u.execute("""
            INSERT INTO nomina_pagos (
                codigo_pago, usuario_id, usuario_nombre, rol, fecha_pago, hora_pago, periodo,
                tipo_operacion, salario_pagado, comisiones_pagadas, ajustes_aplicados,
                monto_pagado, saldo_pendiente_antes, saldo_pendiente_despues,
                metodo_pago, cuenta_afectada, sesion_caja_id, responsable,
                comprobante, observaciones, estado
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Completado')
        """, (
            codigo_pago, uid, uname, rol, fecha_str, hora_str, periodo_str,
            tipo_op_final, round(sal_cubierto, 2), round(com_cubierta, 2), round(aju_cubierto, 2),
            monto_pagado, saldo_antes, saldo_despues,
            metodo_norm, cuenta_afectada, sesion_caja_id, responsable,
            comprobante or "", observaciones or f"Pago de nómina ({tipo_op_final})",
        ))
        pago_id = cur_u.lastrowid

        if ids_tocados:
            placeholders = ",".join("?" for _ in ids_tocados)
            cur_u.execute(
                f"UPDATE nomina_devengos SET liquidacion_id = ? WHERE id IN ({placeholders})",
                [pago_id] + ids_tocados
            )

        # Limpiar bandera de solicitud de liquidación si quedó al día
        if saldo_despues <= 0.01:
            cur_u.execute("UPDATE usuarios SET solicitud_liquidacion = NULL WHERE id = ?", (uid,))

        conn_u.commit()
        saldos_finales = recalcular_saldo_empleado(uid, conn_u=conn_u)
        conn_u.commit()

        # Impacto en Control de Caja y Contabilidad (ventas.db) - UNA SOLA VEZ
        mov_caja_id = None
        mov_fin_id = None

        conn_v = conectar_ventas_db()
        if conn_v:
            try:
                cur_v = conn_v.cursor()
                # Guardar también en historial_liquidaciones para compatibilidad con reportes existentes
                cur_v.execute("""
                    INSERT INTO historial_liquidaciones (
                        tipo, persona_id, nombre_persona, monto, fecha, mes_anio
                    ) VALUES ('Empleado', ?, ?, ?, ?, ?)
                """, (uid, uname, monto_pagado, f"{fecha_str} {hora_str}", fecha_str[:7]))

                desc_mov = f"Pago de nómina ({tipo_op_final}) a {uname}"
                if observaciones:
                    desc_mov += f" - {observaciones}"

                if metodo_norm == "Efectivo":
                    # Registrar en caja física (afecta efectivo esperado una sola vez y sincroniza con movimientos_financieros)
                    mov_caja_id = registrar_movimiento_caja(
                        tipo="EGRESO",
                        monto=monto_pagado,
                        usuario=responsable,
                        referencia_id=codigo_pago,
                        descripcion=desc_mov,
                        sesion_id=sesion_caja_id,
                        conn=conn_v,
                        sincronizar_financiero=True
                    )
                    cur_v.execute(
                        "SELECT id, sesion_caja_id FROM movimientos_financieros WHERE referencia_origen = ? ORDER BY id DESC LIMIT 1",
                        (codigo_pago,)
                    )
                    rf = cur_v.fetchone()
                    if rf:
                        mov_fin_id = rf[0]
                        sesion_caja_id = rf[1]
                else:
                    # Pago por Transferencia: afecta BANCO_TRANSFERENCIA, NO afecta gaveta física
                    activa = obtener_sesion_activa(conn=conn_v)
                    ses_id = sesion_caja_id or (activa["id"] if activa else None)
                    mov_fin_id = registrar_movimiento_financiero(
                        tipo="GASTO_PAGADO",
                        concepto=desc_mov,
                        monto=monto_pagado,
                        metodo_pago="Transferencia",
                        cuenta_afectada="BANCO_TRANSFERENCIA",
                        usuario=responsable,
                        referencia_origen=codigo_pago,
                        sesion_id=ses_id,
                        observaciones=observaciones or "Pago de nómina por transferencia bancaria",
                        conn=conn_v,
                        sincronizar_caja=False
                    )
                    sesion_caja_id = ses_id

                conn_v.commit()
            finally:
                conn_v.close()

        # Actualizar referencias contables en nomina_pagos
        cur_u.execute("""
            UPDATE nomina_pagos
            SET sesion_caja_id = ?, movimiento_caja_id = ?, movimiento_financiero_id = ?
            WHERE id = ?
        """, (sesion_caja_id, mov_caja_id, mov_fin_id, pago_id))
        conn_u.commit()

        return {
            "ok": True,
            "exito": True,
            "pago_id": pago_id,
            "codigo_pago": codigo_pago,
            "usuario_id": uid,
            "usuario": uname,
            "tipo_operacion": tipo_op_final,
            "tipo_pago": tipo_op_final,
            "monto_pagado": monto_pagado,
            "metodo_pago": metodo_norm,
            "cuenta_afectada": cuenta_afectada,
            "saldo_pendiente_antes": saldo_antes,
            "saldo_pendiente_despues": saldos_finales["saldo_pendiente"],
            "saldo_restante": saldos_finales["saldo_pendiente"],
            "movimiento_caja_id": mov_caja_id,
            "movimiento_financiero_id": mov_fin_id,
            "mensaje": f"Pago de nómina ({tipo_op_final}) registrado por ${monto_pagado:,.0f} COP."
        }
    except Exception as e:
        return {"ok": False, "exito": False, "mensaje": str(e)}
    finally:
        conn_u.close()


# ==============================================================================
# FASE 6: RESUMEN DE VENTAS Y RECAUDO DEL EMPLEADO («Por cobrar», «Total pagado», «Recaudado hoy»)
# ==============================================================================

def obtener_resumen_ventas_y_recaudo_empleado(
    usuario_id: Optional[int] = None,
    usuario_nombre: Optional[str] = None,
    rol_solicitante: str = "vendedor",
    rol: Optional[str] = None,
    fecha_referencia: Optional[str] = None,
    fecha: Optional[str] = None,
    fecha_inicio_periodo: Optional[str] = None,
    fecha_fin_periodo: Optional[str] = None
) -> Dict[str, Any]:
    """
    Calcula con precisión y separación de conceptos los indicadores de la Fase 6 y Fase 7 para un empleado:

    INDICADORES DE VENTAS Y CARTERA DE CLIENTES (asociados al empleado):
    1. `por_cobrar_clientes` («Por cobrar»):
       Saldo pendiente de cobro de las ventas a crédito (`Fiado`) realizadas/asignadas al empleado
       que aún no han sido pagadas por los clientes.
    2. `total_pagado_clientes` («Total pagado - Clientes»):
       Total de pagos de clientes efectivamente recibidos (Efectivo + Transferencia + Abonos de cartera)
       sobre las ventas del empleado en el período consultado.
    3. `recaudado_hoy` («Recaudado hoy»):
       Suma de los pagos de clientes efectivamente recibidos durante el día (`fecha_referencia`):
       - Ventas de contado en `Efectivo` del día + Ventas en `Transferencia` del día + `Abonos` de clientes recibidos hoy.
       - EXCLUYE estrictamente las ventas fiadas pendientes (no entra dinero en el momento del fiado).
       - Cuando entra un abono hoy, aumenta `recaudado_hoy` y disminuye `por_cobrar_clientes` sin crear otra venta.

    INDICADORES DE NÓMINA Y COMISIONES DEL EMPLEADO (independientes de los pagos de clientes):
    4. `nomina_por_cobrar`: Saldo pendiente que el negocio debe al empleado (`Total devengado - Total pagado`).
    5. `nomina_total_pagado`: Total recibido por el empleado por concepto de pagos de nómina/liquidaciones/anticipos.
    6. `nomina_devengado_hoy`: Salario diario + comisiones generadas por el empleado hoy.
    """
    inicializar_tablas_nomina()
    hoy_str = fecha_referencia or fecha or datetime.now().strftime("%Y-%m-%d")
    f_ini = fecha_inicio_periodo or f"{hoy_str[:7]}-01"
    f_fin = fecha_fin_periodo or hoy_str
    rol_efectivo = rol or rol_solicitante or "vendedor"

    emp = resolver_usuario(usuario_id=usuario_id, usuario_nombre=usuario_nombre, rol=rol_efectivo)
    if not emp:
        return {
            "ok": False,
            "por_cobrar_clientes": 0.0,
            "total_pagado_clientes": 0.0,
            "recaudado_hoy": 0.0,
            "recaudado_efectivo_hoy": 0.0,
            "recaudado_transferencia_hoy": 0.0,
            "ventas_hoy_cantidad": 0,
            "ventas_hoy_facturado": 0.0,
            "fiado_hoy": 0.0,
            "abonos_hoy": 0.0,
            "nomina_por_cobrar": 0.0,
            "nomina_total_pagado": 0.0,
            "nomina_devengado_hoy": 0.0,
            "nomina_total_devengado": 0.0,
            "asistencia_estado": "Sin registro",
            "salario_diario_generado_hoy": False
        }

    uid = int(emp["id"])
    uname = str(emp["usuario"])
    unombre_pila = str(emp.get("nombre") or uname).strip()
    unombre_completo = f"{emp.get('nombre', '')} {emp.get('apellidos', '')}".strip()
    aliases = list({uname.lower(), unombre_pila.lower(), unombre_completo.lower()})

    # 1. Consultar ventas y recaudos de clientes en ventas.db
    por_cobrar_clientes = 0.0
    total_pagado_clientes = 0.0
    recaudado_hoy = 0.0
    ventas_hoy_cant = 0
    ventas_hoy_facturado = 0.0
    efectivo_hoy = 0.0
    transferencia_hoy = 0.0
    fiado_hoy = 0.0
    abonos_hoy = 0.0
    abonos_periodo = 0.0

    conn_v = conectar_ventas_db()
    if conn_v:
        try:
            conn_v.row_factory = sqlite3.Row
            cur_v = conn_v.cursor()

            placeholders_op = ",".join("?" for _ in aliases)

            # A. Ventas del día de hoy asignadas al empleado
            cur_v.execute(f"""
                SELECT metodo_pago, COUNT(id_venta) as cant, COALESCE(SUM(total_venta), 0.0) as total
                FROM ventas
                WHERE fecha_venta = ?
                  AND (estado IS NULL OR estado != 'Anulada')
                  AND LOWER(TRIM(COALESCE(operario, ''))) IN ({placeholders_op})
                GROUP BY metodo_pago
            """, [hoy_str] + aliases)
            for r in cur_v.fetchall():
                mp = str(r["metodo_pago"] or "Efectivo")
                c = int(r["cant"] or 0)
                t = float(r["total"] or 0.0)
                ventas_hoy_cant += c
                ventas_hoy_facturado += t
                if mp == "Efectivo":
                    efectivo_hoy += t
                elif mp == "Transferencia":
                    transferencia_hoy += t
                elif mp == "Fiado":
                    fiado_hoy += t

            # B. Ventas del período cobradas de contado (Efectivo + Transferencia)
            cur_v.execute(f"""
                SELECT metodo_pago, COALESCE(SUM(total_venta), 0.0) as total
                FROM ventas
                WHERE fecha_venta BETWEEN ? AND ?
                  AND (estado IS NULL OR estado != 'Anulada')
                  AND metodo_pago IN ('Efectivo', 'Transferencia')
                  AND LOWER(TRIM(COALESCE(operario, ''))) IN ({placeholders_op})
                GROUP BY metodo_pago
            """, [f_ini, f_fin] + aliases)
            contado_periodo = sum(float(r["total"] or 0.0) for r in cur_v.fetchall())

            # C. Cartera por cobrar («Por cobrar») de ventas Fiadas asociadas al empleado
            # Se concilia con el saldo pendiente de cada venta fiada y el saldo vivo de los clientes
            cur_v.execute(f"""
                SELECT v.id_venta, v.documento_cliente, v.total_venta, v.saldo_pendiente,
                       c.id as cli_id, c.saldo_pendiente as cli_saldo
                FROM ventas v
                LEFT JOIN clientes c
                  ON (c.cedula = v.documento_cliente OR CAST(c.id AS TEXT) = v.documento_cliente OR LOWER(c.nombre) = LOWER(v.documento_cliente))
                WHERE v.metodo_pago = 'Fiado'
                  AND (v.estado IS NULL OR v.estado != 'Anulada')
                  AND LOWER(TRIM(COALESCE(v.operario, ''))) IN ({placeholders_op})
            """, aliases)
            fiados_rows = cur_v.fetchall()

            # Calcular saldo por cobrar real por cliente / venta
            saldos_por_cliente: Dict[Any, float] = {}
            fiado_bruto_por_cliente: Dict[Any, float] = {}
            for fr in fiados_rows:
                key_cli = fr["cli_id"] if fr["cli_id"] is not None else fr["documento_cliente"]
                sp_venta = fr["saldo_pendiente"]
                tv = float(fr["total_venta"] or 0.0)
                val_pend = float(sp_venta) if (sp_venta is not None and float(sp_venta) >= 0.0) else tv
                fiado_bruto_por_cliente[key_cli] = fiado_bruto_por_cliente.get(key_cli, 0.0) + val_pend
                if fr["cli_saldo"] is not None:
                    saldos_por_cliente[key_cli] = float(fr["cli_saldo"] or 0.0)

            for key_cli, suma_ventas_pend in fiado_bruto_por_cliente.items():
                if key_cli in saldos_por_cliente:
                    por_cobrar_clientes += min(suma_ventas_pend, saldos_por_cliente[key_cli])
                else:
                    por_cobrar_clientes += suma_ventas_pend

            # D. Abonos recibidos hoy y en el período (registrados por el empleado o sobre clientes de sus ventas fiadas)
            clientes_refs = [f"CLIENTE-{cid}" for cid in saldos_por_cliente.keys() if isinstance(cid, int)]
            cond_abono = f"LOWER(TRIM(COALESCE(usuario, ''))) IN ({placeholders_op})"
            params_ab_base: List[Any] = list(aliases)
            if clientes_refs:
                ph_refs = ",".join("?" for _ in clientes_refs)
                cond_abono = f"({cond_abono} OR referencia_origen IN ({ph_refs}))"
                params_ab_base.extend(clientes_refs)

            cur_v.execute(f"""
                SELECT COALESCE(SUM(monto), 0.0)
                FROM movimientos_financieros
                WHERE fecha = ?
                  AND tipo IN ('ABONO_EFECTIVO', 'ABONO_TRANSFERENCIA')
                  AND estado != 'Anulado'
                  AND {cond_abono}
            """, [hoy_str] + params_ab_base)
            abonos_hoy = float(cur_v.fetchone()[0] or 0.0)

            cur_v.execute(f"""
                SELECT COALESCE(SUM(monto), 0.0)
                FROM movimientos_financieros
                WHERE fecha BETWEEN ? AND ?
                  AND tipo IN ('ABONO_EFECTIVO', 'ABONO_TRANSFERENCIA')
                  AND estado != 'Anulado'
                  AND {cond_abono}
            """, [f_ini, f_fin] + params_ab_base)
            abonos_periodo = float(cur_v.fetchone()[0] or 0.0)

            # E. Recaudado hoy = Pagos efectivamente recibidos hoy (Efectivo + Transferencia + Abonos de hoy)
            # NUNCA incluye ventas fiadas pendientes.
            recaudado_hoy = round(efectivo_hoy + transferencia_hoy + abonos_hoy, 2)

            # F. Total pagado (Clientes) = Total efectivamente pagado por clientes en el período
            total_pagado_clientes = round(contado_periodo + abonos_periodo, 2)

        finally:
            conn_v.close()

    if ventas_hoy_cant > 0 and not os.environ.get("VMPOS_DB_USUARIOS"):
        try:
            conciliar_ventas_existentes(hoy_str)
        except Exception:
            pass

    # 2. Consultar indicadores de Nómina y Comisiones del empleado en usuarios.db
    saldos_nom = recalcular_saldo_empleado(uid)
    devengado_hoy = 0.0
    salario_periodo = 0.0
    comisiones_periodo = 0.0
    ajustes_periodo = 0.0
    pagado_periodo = 0.0
    asistencia_estado = "Sin registro"
    salario_diario_generado_hoy = False

    conn_u = conectar_usuarios_db()
    if conn_u:
        try:
            cur_u = conn_u.cursor()
            cur_u.execute("""
                SELECT estado, salario_generado
                FROM asistencia
                WHERE usuario_id = ? AND fecha = ?
            """, (uid, hoy_str))
            arow = cur_u.fetchone()
            if arow:
                asistencia_estado = str(arow[0] or "Presente")
                salario_diario_generado_hoy = bool(arow[1])

            cur_u.execute("""
                SELECT COALESCE(SUM(monto), 0.0)
                FROM nomina_devengos
                WHERE usuario_id = ? AND fecha = ? AND estado NOT IN ('Anulado', 'REVERTIDO', 'Revertido')
            """, (uid, hoy_str))
            devengado_hoy = float(cur_u.fetchone()[0] or 0.0)

            cur_u.execute("""
                SELECT tipo_concepto, COALESCE(SUM(monto), 0.0)
                FROM nomina_devengos
                WHERE usuario_id = ? AND fecha BETWEEN ? AND ? AND estado NOT IN ('Anulado', 'REVERTIDO', 'Revertido')
                GROUP BY tipo_concepto
            """, (uid, f_ini, f_fin))
            map_per = {r[0]: float(r[1] or 0.0) for r in cur_u.fetchall()}
            salario_periodo = map_per.get("SALARIO_DIARIO", 0.0)
            comisiones_periodo = map_per.get("COMISION_VENTA", 0.0)
            ajustes_periodo = (
                map_per.get("AJUSTE_POSITIVO", 0.0)
                + map_per.get("AJUSTE_NEGATIVO", 0.0)
                + map_per.get("REVERSO_ANULACION", 0.0)
            )

            cur_u.execute("""
                SELECT COALESCE(SUM(monto_pagado), 0.0)
                FROM nomina_pagos
                WHERE usuario_id = ? AND fecha_pago BETWEEN ? AND ? AND estado != 'Anulado'
            """, (uid, f_ini, f_fin))
            pagado_periodo = float(cur_u.fetchone()[0] or 0.0)
        finally:
            conn_u.close()

    return {
        "ok": True,
        "usuario_id": uid,
        "usuario": uname,
        "rol": str(emp.get("rol") or ""),
        "fecha_referencia": hoy_str,
        "periodo": {"inicio": f_ini, "fin": f_fin},
        # Indicadores de Ventas y Cartera de Clientes (Fase 6)
        "por_cobrar_clientes": round(por_cobrar_clientes, 2),
        "total_pagado_clientes": round(total_pagado_clientes, 2),
        "recaudado_hoy": round(recaudado_hoy, 2),
        "efectivo_hoy": round(efectivo_hoy, 2),
        "transferencia_hoy": round(transferencia_hoy, 2),
        "recaudado_efectivo_hoy": round(efectivo_hoy, 2),
        "recaudado_transferencia_hoy": round(transferencia_hoy, 2),
        "fiado_hoy": round(fiado_hoy, 2),
        "abonos_hoy": round(abonos_hoy, 2),
        "ventas_hoy_cantidad": ventas_hoy_cant,
        "ventas_hoy_facturado": round(ventas_hoy_facturado, 2),
        # Indicadores de Nómina y Comisiones del Empleado (Fase 7)
        "nomina_salario_periodo": round(salario_periodo, 2),
        "nomina_comisiones_periodo": round(comisiones_periodo, 2),
        "nomina_ajustes_periodo": round(ajustes_periodo, 2),
        "nomina_devengado_hoy": round(devengado_hoy, 2),
        "nomina_total_devengado": saldos_nom["total_devengado"],
        "nomina_total_pagado": saldos_nom["total_pagado"],
        "nomina_pagado_periodo": round(pagado_periodo, 2),
        "nomina_por_cobrar": saldos_nom["saldo_pendiente"],
        "asistencia_estado": asistencia_estado,
        "salario_diario_generado_hoy": salario_diario_generado_hoy
    }


def obtener_detalle_nomina_empleado(
    usuario_id: Optional[int] = None,
    usuario_nombre: Optional[str] = None,
    rol_solicitante: str = "vendedor",
    id_solicitante: Optional[int] = None,
    solicitante_id: Optional[int] = None,
    solicitante_rol: Optional[str] = None,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None
) -> Dict[str, Any]:
    """
    Devuelve toda la información detallada para el módulo del empleado (Fase 7) y del administrador (Fase 2),
    aplicando control estricto de permisos por rol (Escenario 14):
    - Si `rol_solicitante` no es administrador/gerente y `id_solicitante != usuario_id`, bloquea el acceso.
    """
    rol_efectivo = solicitante_rol if solicitante_rol is not None else rol_solicitante
    id_sol_efectivo = solicitante_id if solicitante_id is not None else id_solicitante
    rol_norm = (rol_efectivo or "").strip().lower()
    es_admin = rol_norm in ("admin", "administrador", "gerente")
    if not es_admin and id_sol_efectivo is not None and usuario_id is not None and int(id_sol_efectivo) != int(usuario_id):
        raise PermissionError("Acceso denegado: un empleado solo puede consultar su propia información de nómina y ventas.")

    inicializar_tablas_nomina()
    emp_init = resolver_usuario(usuario_id=usuario_id, usuario_nombre=usuario_nombre)
    if not emp_init:
        return {"ok": False, "error": "Empleado no encontrado"}

    uid = int(emp_init["id"])
    # Si no se pasó usuario_id explícito pero sí id_solicitante, verificar coincidencia contra el ID resuelto
    if not es_admin and usuario_id is None and id_sol_efectivo is not None and int(id_sol_efectivo) != uid:
        raise PermissionError("Acceso denegado: un empleado solo puede consultar su propia información de nómina y ventas.")

    # Conciliar resumen y posibles ventas pendientes del día antes de abrir lectura de saldos e historiales
    resumen = obtener_resumen_ventas_y_recaudo_empleado(
        usuario_id=uid,
        usuario_nombre=emp_init.get("usuario") or usuario_nombre,
        rol_solicitante=rol_efectivo,
        fecha_inicio_periodo=fecha_inicio,
        fecha_fin_periodo=fecha_fin
    )

    conn_u = conectar_usuarios_db()
    if not conn_u:
        return {"ok": False, "error": "Sin conexión a usuarios.db"}

    try:
        conn_u.row_factory = sqlite3.Row
        cur = conn_u.cursor()

        emp = resolver_usuario(usuario_id=uid, conn_u=conn_u) or emp_init
        saldos = recalcular_saldo_empleado(uid, conn_u=conn_u)

        # Filtro opcional de fechas
        filtro_f_asist = ""
        filtro_f_dev = ""
        filtro_f_pag = ""
        params_a: List[Any] = [uid]
        params_d: List[Any] = [uid]
        params_p: List[Any] = [uid]

        if fecha_inicio and fecha_fin:
            filtro_f_asist = " AND fecha BETWEEN ? AND ?"
            filtro_f_dev = " AND fecha BETWEEN ? AND ?"
            filtro_f_pag = " AND fecha_pago BETWEEN ? AND ?"
            params_a.extend([fecha_inicio, fecha_fin])
            params_d.extend([fecha_inicio, fecha_fin])
            params_p.extend([fecha_inicio, fecha_fin])

        # 1. Historial de pagos recibidos
        cur.execute(f"""
            SELECT * FROM nomina_pagos
            WHERE usuario_id = ? {filtro_f_pag}
            ORDER BY fecha_pago DESC, id DESC
        """, params_p)
        pagos = []
        for r in cur.fetchall():
            d_p = dict(r)
            d_p["fecha"] = d_p.get("fecha_pago", "")
            d_p["hora"] = d_p.get("hora_pago", "")
            d_p["tipo_pago"] = d_p.get("tipo_operacion", "LIQUIDACION_TOTAL")
            d_p["periodo_inicio"] = d_p.get("periodo", "")
            d_p["periodo_fin"] = ""
            d_p["saldo_restante"] = d_p.get("saldo_pendiente_despues", 0.0)
            pagos.append(d_p)

        # 2. Detalle de jornadas y asistencias
        cur.execute(f"""
            SELECT * FROM asistencia
            WHERE usuario_id = ? {filtro_f_asist}
            ORDER BY fecha DESC, id DESC
        """, params_a)
        jornadas = [dict(r) for r in cur.fetchall()]

        # 3. Detalle de ventas con comisión, salarios y ajustes
        cur.execute(f"""
            SELECT * FROM nomina_devengos
            WHERE usuario_id = ? {filtro_f_dev}
            ORDER BY fecha DESC, id DESC
        """, params_d)
        devengos = []
        for r in cur.fetchall():
            d_dev = dict(r)
            d_dev["tipo"] = d_dev.get("tipo_concepto", "")
            d_dev["valor_base"] = d_dev.get("base_calculo", 0.0)
            d_dev["porcentaje"] = d_dev.get("porcentaje_aplicado", 0.0)
            if str(d_dev.get("estado", "")).upper() in ("ANULADO", "REVERTIDO"):
                d_dev["estado"] = "REVERTIDO"
            devengos.append(d_dev)

        comisiones_detalle = [d for d in devengos if d["tipo_concepto"] == "COMISION_VENTA"]
        ajustes_detalle = [d for d in devengos if d["tipo_concepto"] in ("AJUSTE_POSITIVO", "AJUSTE_NEGATIVO", "REVERSO_ANULACION")]

        return {
            "ok": True,
            "empleado": {
                "id": uid,
                "usuario": emp["usuario"],
                "nombre_completo": f"{emp.get('nombre', '')} {emp.get('apellidos', '')}".strip() or emp["usuario"],
                "rol": emp.get("rol", ""),
                "tipo_nomina": emp.get("tipo_nomina", "Porcentual"),
                "salario_diario": float(emp.get("salario_diario") or 0.0),
                "comision_porcentaje": float(emp.get("comision_porcentaje") or 0.0),
                "regla_devengo": emp.get("regla_devengo") or ("PRIMERA_VENTA" if es_rol_vendedor(emp.get("rol", "")) else "ASISTENCIA_DIRECTA")
            },
            "saldos": saldos,
            "total_salario_diario": saldos["salarios_generados"],
            "total_comisiones": saldos["comisiones_generadas"],
            "total_ajustes": saldos["ajustes_netos"],
            "total_devengado": saldos["total_devengado"],
            "total_pagado": saldos["total_pagado"],
            "por_cobrar": saldos["saldo_pendiente"],
            "resumen": resumen,
            "historial_pagos": pagos,
            "detalle_jornadas": jornadas,
            "detalle_devengos": devengos,
            "detalle_comisiones": comisiones_detalle,
            "detalle_ajustes": ajustes_detalle
        }
    finally:
        conn_u.close()


def obtener_metricas_nomina_contabilidad(fecha_inicio: str, fecha_fin: str) -> Dict[str, Any]:
    """
    Provee a Contabilidad (`caja_manager.calcular_metricas_contables`) las cifras exactas y conciliadas
    del período sin duplicaciones ni gastos negativos:
    - `gasto_personal_devengado`: Total de salarios diarios + comisiones + ajustes netos reconocidos en el período.
    - `pagos_nomina_realizados`: Dinero efectivamente pagado a empleados en el período.
    - `obligaciones_nomina_pendientes`: Saldo pasivo total que el negocio adeuda a los empleados.
    """
    inicializar_tablas_nomina()
    conn_u = conectar_usuarios_db()
    if not conn_u:
        return {
            "gasto_personal_devengado": 0.0,
            "gasto_nomina_devengada": 0.0,
            "salarios_devengados": 0.0,
            "comisiones_devengadas": 0.0,
            "ajustes_devengados": 0.0,
            "pagos_nomina_realizados": 0.0,
            "nomina_pagada": 0.0,
            "pagos_efectivo": 0.0,
            "pagado_efectivo": 0.0,
            "pagos_transferencia": 0.0,
            "pagado_transferencia": 0.0,
            "obligaciones_pendientes": 0.0,
            "pasivo_nomina_pendiente": 0.0
        }
    try:
        cur = conn_u.cursor()
        cur.execute("""
            SELECT tipo_concepto, COALESCE(SUM(monto), 0.0)
            FROM nomina_devengos
            WHERE fecha BETWEEN ? AND ? AND estado NOT IN ('Anulado', 'REVERTIDO', 'Revertido')
            GROUP BY tipo_concepto
        """, (fecha_inicio, fecha_fin))
        dev_map = {r[0]: float(r[1] or 0.0) for r in cur.fetchall()}

        salarios_dev = dev_map.get("SALARIO_DIARIO", 0.0)
        comisiones_dev = dev_map.get("COMISION_VENTA", 0.0)
        ajustes_dev = (
            dev_map.get("AJUSTE_POSITIVO", 0.0)
            + dev_map.get("AJUSTE_NEGATIVO", 0.0)
            + dev_map.get("REVERSO_ANULACION", 0.0)
        )
        gasto_personal = max(0.0, salarios_dev + comisiones_dev + ajustes_dev)

        cur.execute("""
            SELECT metodo_pago, COALESCE(SUM(monto_pagado), 0.0)
            FROM nomina_pagos
            WHERE fecha_pago BETWEEN ? AND ? AND estado != 'Anulado'
            GROUP BY metodo_pago
        """, (fecha_inicio, fecha_fin))
        pag_map = {r[0]: float(r[1] or 0.0) for r in cur.fetchall()}
        pagos_ef = pag_map.get("Efectivo", 0.0)
        pagos_tr = pag_map.get("Transferencia", 0.0)
        pagos_tot = pagos_ef + pagos_tr

        # Saldo global pendiente de pago a todos los empleados
        cur.execute("SELECT id FROM usuarios")
        uids = [r[0] for r in cur.fetchall()]
        obligacion_total = 0.0
        for u_id in uids:
            s = recalcular_saldo_empleado(u_id, conn_u=conn_u)
            if s["saldo_pendiente"] > 0:
                obligacion_total += s["saldo_pendiente"]

        return {
            "gasto_personal_devengado": round(gasto_personal, 2),
            "gasto_nomina_devengada": round(gasto_personal, 2),
            "salarios_devengados": round(salarios_dev, 2),
            "comisiones_devengadas": round(comisiones_dev, 2),
            "ajustes_devengados": round(ajustes_dev, 2),
            "pagos_nomina_realizados": round(pagos_tot, 2),
            "nomina_pagada": round(pagos_tot, 2),
            "pagos_efectivo": round(pagos_ef, 2),
            "pagado_efectivo": round(pagos_ef, 2),
            "pagos_transferencia": round(pagos_tr, 2),
            "pagado_transferencia": round(pagos_tr, 2),
            "obligaciones_pendientes": round(obligacion_total, 2),
            "pasivo_nomina_pendiente": round(obligacion_total, 2)
        }
    finally:
        conn_u.close()


# ==============================================================================
# FUNCIONES DE ADMINISTRACIÓN, CONSULTA Y SOLICITUDES PARA LA UI
# ==============================================================================

def conciliar_ventas_existentes(fecha_referencia: Optional[str] = None) -> int:
    """
    Reconcilia de manera idempotente las ventas registradas en `ventas.db` para la fecha indicada
    (por defecto hoy) asegurando que si un vendedor realizó ventas antes de sincronizarse su perfil
    local o tras actualizar su esquema salarial, se confirme su asistencia y se generen sus devengos
    de jornada y comisiones sin duplicación.
    No se ejecuta cuando `VMPOS_DB_USUARIOS` está definido (entorno de pruebas aisladas).
    """
    if os.environ.get("VMPOS_DB_USUARIOS"):
        return 0

    sincronizar_usuarios_con_api()

    hoy_str = fecha_referencia or datetime.now().strftime("%Y-%m-%d")
    conn_v = conectar_ventas_db()
    if not conn_v:
        return 0

    procesadas = 0
    try:
        cur_v = conn_v.cursor()
        cur_v.execute("""
            SELECT id_venta, fecha_venta, hora_venta, total_venta, metodo_pago, operario
            FROM ventas
            WHERE fecha_venta = ?
              AND (estado IS NULL OR estado != 'Anulada')
            ORDER BY id_venta ASC
        """, (hoy_str,))
        ventas_rows = cur_v.fetchall()

        for v_row in ventas_rows:
            id_v = int(v_row[0])
            f_v = str(v_row[1] or hoy_str)
            tot_v = float(v_row[3] or 0.0)
            met_v = str(v_row[4] or "Efectivo")
            op_v = str(v_row[5] or "").strip()
            if not op_v or op_v.lower() in (
                "admin", "administrador", "admin principal", "sistema", "usuario", "consumidor final"
            ):
                continue

            emp = resolver_usuario(usuario_nombre=op_v)
            if not emp:
                continue
            if str(emp.get("rol", "")).strip().lower() in ("admin", "administrador", "gerente"):
                continue

            # Obtener ítems de detalle_ventas enriquecidos con su tipo de producto/servicio
            cur_v.execute("""
                SELECT dv.id_detalle, dv.codigo_producto, dv.nombre_producto,
                       dv.precio_unitario, dv.cantidad, dv.subtotal
                FROM detalle_ventas dv
                WHERE dv.id_venta = ?
                ORDER BY dv.id_detalle ASC
            """, (id_v,))
            det_rows = cur_v.fetchall()
            detalles_v = []
            for d_r in det_rows:
                cod_p = str(d_r[1] or "").strip()
                tipo_p = "Servicio" if cod_p.upper().startswith("S") else "Producto"
                detalles_v.append({
                    "id_detalle": int(d_r[0]),
                    "item_id": 0,
                    "item_tipo": tipo_p,
                    "item_nombre": str(d_r[2] or "Ítem"),
                    "precio_vendido": float(d_r[3] or 0.0),
                    "cantidad": int(d_r[4] or 1),
                    "subtotal": float(d_r[5] or 0.0)
                })

            res_p = procesar_venta_nomina_y_comisiones(
                id_venta=id_v,
                operario_nombre=op_v,
                usuario_id=int(emp["id"]),
                total_venta=tot_v,
                metodo_pago=met_v,
                detalles_payload=detalles_v,
                fecha=f_v
            )
            if res_p.get("ok"):
                procesadas += 1
    except Exception as e:
        print(f"Aviso en conciliar_ventas_existentes: {e}")
    finally:
        conn_v.close()
    return procesadas


def obtener_empleados_configuracion(incluir_inactivos: bool = True) -> List[Dict[str, Any]]:
    """
    Devuelve la lista de empleados (excluyendo administradores puros salvo que tengan devengos)
    con su configuración de remuneración y sus saldos acumulados conciliados en tiempo real.
    """
    inicializar_tablas_nomina()
    if not os.environ.get("VMPOS_DB_USUARIOS"):
        sincronizar_usuarios_con_api()
        conciliar_ventas_existentes()

    conn_u = conectar_usuarios_db()
    if not conn_u:
        return []
    try:
        conn_u.row_factory = sqlite3.Row
        cur = conn_u.cursor()
        if incluir_inactivos:
            cur.execute("SELECT * FROM usuarios WHERE LOWER(rol) NOT IN ('admin', 'administrador') ORDER BY id ASC")
        else:
            cur.execute("SELECT * FROM usuarios WHERE LOWER(rol) NOT IN ('admin', 'administrador') AND COALESCE(estado, 'Activo') = 'Activo' ORDER BY id ASC")
        rows = [dict(r) for r in cur.fetchall()]
        resultado = []
        for r in rows:
            uid = int(r["id"])
            saldos = recalcular_saldo_empleado(uid, conn_u=conn_u)
            nom_comp = f"{r.get('nombre', '')} {r.get('apellidos', '')}".strip() or r.get("usuario", "")
            rol_u = str(r.get("rol") or "Vendedor")
            regla_raw = str(r.get("regla_devengo") or "Auto")
            if regla_raw in ("Auto", "", "None"):
                regla_norm = "PRIMERA_VENTA" if es_rol_vendedor(rol_u) else "ASISTENCIA_DIRECTA"
            else:
                regla_norm = regla_raw

            sol_val = r.get("solicitud_liquidacion")
            sol_activa = bool(sol_val and str(sol_val) not in ("0", "None", ""))

            resultado.append({
                "id": uid,
                "usuario": r.get("usuario", ""),
                "nombre": r.get("nombre", ""),
                "apellidos": r.get("apellidos", ""),
                "nombre_completo": nom_comp,
                "rol": rol_u,
                "estado": r.get("estado") or "Activo",
                "tipo_nomina": r.get("tipo_nomina") or "Porcentual",
                "salario_diario": float(r.get("salario_diario") or 0.0),
                "comision_porcentaje": float(r.get("comision_porcentaje") or 0.0),
                "regla_devengo": regla_norm,
                "comision_productos": int(r.get("comision_productos", 1) if r.get("comision_productos") is not None else 1),
                "comision_servicios": int(r.get("comision_servicios", 1) if r.get("comision_servicios") is not None else 1),
                "comision_fiados": int(r.get("comision_fiados", 0) if r.get("comision_fiados") is not None else 0),
                "total_salario_diario": saldos["salarios_generados"],
                "total_comisiones": saldos["comisiones_generadas"],
                "total_ajustes": saldos["ajustes_netos"],
                "total_devengado": saldos["total_devengado"],
                "total_pagado": saldos["total_pagado"],
                "saldo_pendiente": saldos["saldo_pendiente"],
                "solicitud_activa": sol_activa,
                "solicitud_liquidacion": sol_val
            })
        conn_u.commit()
        return resultado
    finally:
        conn_u.close()


def actualizar_configuracion_empleado(
    usuario_id: int,
    tipo_nomina: str,
    salario_diario: float,
    comision_porcentaje: float,
    regla_devengo: str = "PRIMERA_VENTA",
    comision_productos: int = 1,
    comision_servicios: int = 1,
    comision_fiados: int = 0,
    estado: str = "Activo"
) -> bool:
    """Actualiza la configuración de nómina y elegibilidad de comisiones de un empleado y la sincroniza con la API."""
    inicializar_tablas_nomina()
    conn_u = conectar_usuarios_db()
    if not conn_u:
        return False
    u_login = ""
    try:
        conn_u.row_factory = sqlite3.Row
        cur = conn_u.cursor()
        cur.execute("SELECT usuario, nombre, apellidos FROM usuarios WHERE id = ?", (int(usuario_id),))
        r_u = cur.fetchone()
        if r_u:
            u_login = str(r_u["usuario"] or "")

        cur.execute("""
            UPDATE usuarios
            SET tipo_nomina = ?,
                salario_diario = ?,
                comision_porcentaje = ?,
                regla_devengo = ?,
                comision_productos = ?,
                comision_servicios = ?,
                comision_fiados = ?,
                estado = ?
            WHERE id = ?
        """, (
            str(tipo_nomina),
            float(salario_diario or 0.0),
            float(comision_porcentaje or 0.0),
            str(regla_devengo or "PRIMERA_VENTA"),
            int(comision_productos),
            int(comision_servicios),
            int(comision_fiados),
            str(estado or "Activo"),
            int(usuario_id)
        ))

        # Si hoy ya tenía un salario diario 'Pendiente' y se modificó salario_diario, actualizarlo
        hoy_str = datetime.now().strftime("%Y-%m-%d")
        cod_sal_hoy = f"SAL-{int(usuario_id)}-{hoy_str}"
        if str(tipo_nomina) in ("Fija", "Mixta") and float(salario_diario or 0.0) > 0:
            cur.execute(
                "SELECT id, estado FROM nomina_devengos WHERE codigo_unico = ?",
                (cod_sal_hoy,)
            )
            dev_hoy = cur.fetchone()
            if dev_hoy and str(dev_hoy["estado"]) == "Pendiente":
                cur.execute(
                    "UPDATE nomina_devengos SET monto = ?, base_calculo = ? WHERE id = ?",
                    (float(salario_diario), float(salario_diario), int(dev_hoy["id"]))
                )
                cur.execute(
                    "UPDATE asistencia SET monto_salario_generado = ? WHERE usuario_id = ? AND fecha = ?",
                    (float(salario_diario), int(usuario_id), hoy_str)
                )
                conn_v_sync = conectar_ventas_db()
                if conn_v_sync:
                    try:
                        conn_v_sync.execute(
                            "UPDATE movimientos_financieros SET monto = ? WHERE referencia_origen = ? AND tipo = 'DEVENGO_NOMINA'",
                            (float(salario_diario), cod_sal_hoy)
                        )
                        conn_v_sync.commit()
                    except Exception:
                        pass
                    finally:
                        conn_v_sync.close()

        conn_u.commit()
    except Exception as e:
        print(f"Error actualizando configuración de empleado #{usuario_id}: {e}")
        conn_u.close()
        return False
    conn_u.close()

    # Sincronizar hacia API PostgreSQL si está disponible y no estamos en pruebas aisladas
    if not os.environ.get("VMPOS_DB_USUARIOS"):
        try:
            from client.api_client import api
            if getattr(api, "token", None) and u_login:
                resp = api.get("/usuarios?size=1000")
                if resp.status_code == 200:
                    items = resp.json().get("items", []) if isinstance(resp.json(), dict) else []
                    for it in items:
                        it_usr = str(it.get("usuario") or "").strip().lower()
                        it_full = f"{it.get('nombre', '')} {it.get('apellidos', '')}".strip().lower()
                        if u_login.lower() in (it_usr, it_full):
                            api.put(f"/usuarios/{it['id']}", json={
                                "tipo_remuneracion": str(tipo_nomina),
                                "salario_diario": float(salario_diario or 0.0),
                                "porcentaje_comision": float(comision_porcentaje or 0.0),
                                "estado": str(estado or "Activo")
                            })
                            break
        except Exception:
            pass
        try:
            conciliar_ventas_existentes()
        except Exception:
            pass

    return True


def obtener_asistencias_jornadas(
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    usuario_id: Optional[int] = None,
    rol: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Consulta el historial de asistencias y jornadas con filtros opcionales."""
    inicializar_tablas_nomina()
    conn_u = conectar_usuarios_db()
    if not conn_u:
        return []
    try:
        conn_u.row_factory = sqlite3.Row
        cur = conn_u.cursor()
        conds = ["1=1"]
        params: List[Any] = []
        if fecha_inicio and fecha_fin:
            conds.append("a.fecha BETWEEN ? AND ?")
            params.extend([fecha_inicio, fecha_fin])
        elif fecha_inicio:
            conds.append("a.fecha >= ?")
            params.append(fecha_inicio)
        elif fecha_fin:
            conds.append("a.fecha <= ?")
            params.append(fecha_fin)
        if usuario_id is not None:
            conds.append("a.usuario_id = ?")
            params.append(int(usuario_id))
        if rol and rol != "Todos":
            conds.append("LOWER(COALESCE(NULLIF(a.rol, ''), u.rol)) = LOWER(?)")
            params.append(rol.strip())

        where_sql = " AND ".join(conds)
        cur.execute(f"""
            SELECT a.*,
                   COALESCE(NULLIF(TRIM(u.nombre || ' ' || COALESCE(u.apellidos, '')), ''), u.usuario, a.usuario_nombre) as emp_nombre,
                   COALESCE(NULLIF(a.rol, ''), u.rol) as emp_rol
            FROM asistencia a
            LEFT JOIN usuarios u ON a.usuario_id = u.id
            WHERE {where_sql}
            ORDER BY a.fecha DESC, a.id DESC
        """, params)
        res = []
        for r in cur.fetchall():
            d = dict(r)
            d["usuario_nombre"] = d.get("emp_nombre") or d.get("usuario_nombre") or f"ID #{d.get('usuario_id')}"
            d["rol"] = d.get("emp_rol") or d.get("rol") or ""
            res.append(d)
        return res
    finally:
        conn_u.close()


def obtener_historial_pagos_nomina(
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    usuario_id: Optional[int] = None,
    rol: Optional[str] = None,
    mes_anio: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Consulta el historial de pagos, liquidaciones y anticipos realizados."""
    inicializar_tablas_nomina()
    conn_u = conectar_usuarios_db()
    if not conn_u:
        return []
    try:
        conn_u.row_factory = sqlite3.Row
        cur = conn_u.cursor()
        conds = ["p.estado != 'Anulado'"]
        params: List[Any] = []
        if fecha_inicio and fecha_fin:
            conds.append("p.fecha_pago BETWEEN ? AND ?")
            params.extend([fecha_inicio, fecha_fin])
        if usuario_id is not None:
            conds.append("p.usuario_id = ?")
            params.append(int(usuario_id))
        if rol and rol != "Todos":
            conds.append("LOWER(COALESCE(NULLIF(p.rol, ''), u.rol)) = LOWER(?)")
            params.append(rol.strip())
        if mes_anio and mes_anio != "Todos":
            conds.append("SUBSTR(p.fecha_pago, 1, 7) = ?")
            params.append(mes_anio.strip())

        where_sql = " AND ".join(conds)
        cur.execute(f"""
            SELECT p.*,
                   COALESCE(NULLIF(TRIM(u.nombre || ' ' || COALESCE(u.apellidos, '')), ''), u.usuario, p.usuario_nombre) as emp_nombre,
                   COALESCE(NULLIF(p.rol, ''), u.rol) as emp_rol
            FROM nomina_pagos p
            LEFT JOIN usuarios u ON p.usuario_id = u.id
            WHERE {where_sql}
            ORDER BY p.fecha_pago DESC, p.id DESC
        """, params)
        res = []
        for r in cur.fetchall():
            d = dict(r)
            d["usuario_nombre"] = d.get("emp_nombre") or d.get("usuario_nombre") or ""
            d["rol"] = d.get("emp_rol") or d.get("rol") or ""
            d["fecha"] = d.get("fecha_pago", "")
            d["hora"] = d.get("hora_pago", "")
            d["tipo_pago"] = d.get("tipo_operacion", "LIQUIDACION_TOTAL")
            d["mes_anio"] = str(d.get("fecha_pago", ""))[:7]
            d["periodo_inicio"] = d.get("periodo", "")
            d["periodo_fin"] = ""
            d["saldo_restante"] = d.get("saldo_pendiente_despues", 0.0)
            res.append(d)
        return res
    finally:
        conn_u.close()


def obtener_devengos_nomina(
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    usuario_id: Optional[int] = None,
    rol: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Consulta el detalle auditable de devengos (salarios diarios, comisiones, ajustes y reversos)."""
    inicializar_tablas_nomina()
    conn_u = conectar_usuarios_db()
    if not conn_u:
        return []
    try:
        conn_u.row_factory = sqlite3.Row
        cur = conn_u.cursor()
        conds = ["1=1"]
        params: List[Any] = []
        if fecha_inicio and fecha_fin:
            conds.append("d.fecha BETWEEN ? AND ?")
            params.extend([fecha_inicio, fecha_fin])
        if usuario_id is not None:
            conds.append("d.usuario_id = ?")
            params.append(int(usuario_id))
        if rol and rol != "Todos":
            conds.append("LOWER(COALESCE(NULLIF(d.rol, ''), u.rol)) = LOWER(?)")
            params.append(rol.strip())

        where_sql = " AND ".join(conds)
        cur.execute(f"""
            SELECT d.*,
                   COALESCE(NULLIF(TRIM(u.nombre || ' ' || COALESCE(u.apellidos, '')), ''), u.usuario, d.usuario_nombre) as emp_nombre,
                   COALESCE(NULLIF(d.rol, ''), u.rol) as emp_rol
            FROM nomina_devengos d
            LEFT JOIN usuarios u ON d.usuario_id = u.id
            WHERE {where_sql}
            ORDER BY d.fecha DESC, d.id DESC
        """, params)
        res = []
        for r in cur.fetchall():
            d = dict(r)
            d["usuario_nombre"] = d.get("emp_nombre") or d.get("usuario_nombre") or ""
            d["rol"] = d.get("emp_rol") or d.get("rol") or ""
            d["tipo"] = d.get("tipo_concepto", "")
            d["valor_base"] = d.get("base_calculo", 0.0)
            d["porcentaje"] = d.get("porcentaje_aplicado", 0.0)
            res.append(d)
        return res
    finally:
        conn_u.close()


def solicitar_liquidacion_empleado(
    usuario_id: Optional[int] = None,
    usuario_nombre: Optional[str] = None
) -> Dict[str, Any]:
    """Marca la solicitud de liquidación del empleado si posee saldo pendiente positivo."""
    inicializar_tablas_nomina()
    if not os.environ.get("VMPOS_DB_USUARIOS"):
        try:
            conciliar_ventas_existentes()
        except Exception:
            pass
    conn_u = conectar_usuarios_db()
    if not conn_u:
        return {"ok": False, "exito": False, "saldo_pendiente": 0.0, "mensaje": "Sin conexión a usuarios.db"}
    try:
        emp = resolver_usuario(usuario_id=usuario_id, usuario_nombre=usuario_nombre, conn_u=conn_u)
        if not emp:
            return {"ok": False, "exito": False, "saldo_pendiente": 0.0, "mensaje": "Empleado no encontrado."}
        uid = int(emp["id"])
        saldos = recalcular_saldo_empleado(uid, conn_u=conn_u)
        if saldos["saldo_pendiente"] <= 0:
            return {
                "ok": False,
                "exito": False,
                "usuario_id": uid,
                "saldo_pendiente": 0.0,
                "mensaje": "No tienes saldo pendiente por cobrar para solicitar liquidación."
            }
        ahora_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = conn_u.cursor()
        cur.execute(
            "UPDATE usuarios SET solicitud_liquidacion = ?, fecha_solicitud_liq = ? WHERE id = ?",
            (ahora_str, ahora_str, uid)
        )
        conn_u.commit()
        return {
            "ok": True,
            "exito": True,
            "usuario_id": uid,
            "saldo_pendiente": saldos["saldo_pendiente"],
            "mensaje": f"Solicitud enviada por un saldo pendiente de ${saldos['saldo_pendiente']:,.0f} COP."
        }
    finally:
        conn_u.close()


def obtener_solicitudes_liquidacion_pendientes() -> List[Dict[str, Any]]:
    """Devuelve los empleados activos que han solicitado liquidación y tienen saldo pendiente."""
    empleados = obtener_empleados_configuracion(incluir_inactivos=False)
    return [e for e in empleados if e.get("solicitud_activa") and float(e.get("saldo_pendiente", 0.0)) > 0]

