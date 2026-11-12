#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivo: interface/sync_manager.py
Gestor de Persistencia y Sincronización Fuera de Línea (Offline-First) para VmPOS.

Garantiza:
1. Persistencia local inmediata en SQLite antes de cualquier llamada de red.
2. Cola transaccional persistente (`cola_sincronizacion`) con UUIDs v4 inmutables.
3. Idempotencia total: previene duplicación de ventas, pagos, abonos y movimientos.
4. Auto-recuperación transparente al restablecerse Internet o la red local.
5. Tolerancia a apagones o cierres forzados de la aplicación sin pérdida de datos.
"""

import os
import sys
import json
import time
import uuid
import sqlite3
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from client.api_client import api

try:
    from interface.database_manager import conectar_db
except ImportError:
    from database_manager import conectar_db

# Estados de sincronización
ESTADO_PENDIENTE = "PENDIENTE"
ESTADO_SINCRONIZANDO = "SINCRONIZANDO"
ESTADO_SINCRONIZADO = "SINCRONIZADO"
ESTADO_ERROR = "ERROR"

# Tipos de operaciones soportadas en la cola
OP_VENTA = "VENTA"
OP_ABONO = "ABONO"
OP_MOV_INVENTARIO = "MOVIMIENTO_INVENTARIO"
OP_GASTO = "GASTO"
OP_LIQ_PROVEEDOR = "LIQUIDACION_PROVEEDOR"
OP_LIQ_NOMINA = "LIQUIDACION_NOMINA"


class SyncManager:
    """Singleton para administración de la cola de sincronización offline."""
    _instance = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(SyncManager, cls).__new__(cls)
                cls._instance._init_manager()
            return cls._instance

    def _init_manager(self):
        self._daemon_iniciado = False
        self._sincronizando_ahora = False
        self._listeners = []
        self._ultimo_sync_ts = 0.0
        self._ultimo_error_sync = ""
        self.asegurar_tabla_cola()

    def asegurar_tabla_cola(self, conn: Optional[sqlite3.Connection] = None):
        """Crea la tabla `cola_sincronizacion` si no existe aún."""
        cerrar_conn = False
        if conn is None:
            conn = conectar_db()
            cerrar_conn = True
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cola_sincronizacion (
                    id TEXT PRIMARY KEY,
                    empresa TEXT NOT NULL DEFAULT 'VmPOS',
                    usuario TEXT NOT NULL DEFAULT 'Administrador',
                    dispositivo TEXT NOT NULL DEFAULT 'CAJA-01',
                    tipo_operacion TEXT NOT NULL,
                    fecha_hora TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    estado_sync TEXT NOT NULL DEFAULT 'PENDIENTE',
                    intentos INTEGER NOT NULL DEFAULT 0,
                    ultimo_error TEXT DEFAULT '',
                    id_local INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_cola_sync_estado ON cola_sincronizacion(estado_sync)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_cola_sync_fecha ON cola_sincronizacion(fecha_hora)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_cola_sync_tipo ON cola_sincronizacion(tipo_operacion)")
            conn.commit()
        except Exception as e:
            print(f"Aviso asegurando tabla cola_sincronizacion: {e}")
        finally:
            if cerrar_conn and conn:
                conn.close()

    def encolar_operacion(
        self,
        tipo_operacion: str,
        payload: Dict[str, Any],
        usuario: str = "Administrador",
        dispositivo: str = "CAJA-01",
        id_local: Optional[int] = None,
        idempotency_key: Optional[str] = None,
        conn: Optional[sqlite3.Connection] = None
    ) -> str:
        """
        Encola una operación en la base de datos local SQLite con estado 'PENDIENTE'.
        Retorna el UUID único de la operación (idempotency_key).
        """
        op_id = (idempotency_key or payload.get("idempotency_key") or str(uuid.uuid4())).strip()
        payload["idempotency_key"] = op_id

        ahora = datetime.now()
        f_hora_iso = ahora.strftime("%Y-%m-%d %H:%M:%S")
        payload_str = json.dumps(payload, ensure_ascii=False)

        empresa_nom = payload.get("empresa") or "VmPOS"

        cerrar_conn = False
        if conn is None:
            conn = conectar_db()
            cerrar_conn = True
        if not conn:
            return op_id

        try:
            self.asegurar_tabla_cola(conn=conn)
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO cola_sincronizacion (
                    id, empresa, usuario, dispositivo, tipo_operacion,
                    fecha_hora, payload_json, estado_sync, intentos,
                    ultimo_error, id_local, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, '', ?, ?, ?)
            """, (
                op_id, empresa_nom, usuario, dispositivo, tipo_operacion,
                f_hora_iso, payload_str, ESTADO_PENDIENTE, id_local,
                f_hora_iso, f_hora_iso
            ))
            conn.commit()
            self._notificar_cambio()
        except Exception as e:
            print(f"Error encolando operación {tipo_operacion} ({op_id}): {e}")
        finally:
            if cerrar_conn and conn:
                conn.close()

        # Intentar disparo en segundo plano si hay red disponible
        self.disparar_sincronizacion_asincrona()
        return op_id

    def marcar_como_sincronizada(self, op_id: str, conn: Optional[sqlite3.Connection] = None) -> bool:
        """Marca una operación como exitosamente sincronizada."""
        cerrar_conn = False
        if conn is None:
            conn = conectar_db()
            cerrar_conn = True
        if not conn:
            return False
        try:
            ahora_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cur = conn.cursor()
            cur.execute("""
                UPDATE cola_sincronizacion
                SET estado_sync = ?, updated_at = ?, ultimo_error = ''
                WHERE id = ?
            """, (ESTADO_SINCRONIZADO, ahora_str, op_id))
            conn.commit()
            self._notificar_cambio()
            return True
        except Exception as e:
            print(f"Aviso actualizando estado sync de {op_id}: {e}")
            return False
        finally:
            if cerrar_conn and conn:
                conn.close()

    def marcar_error_sincronizacion(self, op_id: str, error_msg: str, conn: Optional[sqlite3.Connection] = None):
        """Registra el fallo de un intento de sincronización incrementando el contador."""
        cerrar_conn = False
        if conn is None:
            conn = conectar_db()
            cerrar_conn = True
        if not conn:
            return
        try:
            ahora_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cur = conn.cursor()
            cur.execute("""
                UPDATE cola_sincronizacion
                SET estado_sync = ?, intentos = intentos + 1, ultimo_error = ?, updated_at = ?
                WHERE id = ?
            """, (ESTADO_ERROR, str(error_msg)[:300], ahora_str, op_id))
            conn.commit()
            self._ultimo_error_sync = str(error_msg)
            self._notificar_cambio()
        except Exception:
            pass
        finally:
            if cerrar_conn and conn:
                conn.close()

    def obtener_conteo_pendientes(self, conn: Optional[sqlite3.Connection] = None) -> Dict[str, int]:
        """Retorna el conteo exacto de operaciones según su estado de sincronización."""
        res = {"pendientes": 0, "sincronizados": 0, "errores": 0, "total": 0}
        cerrar_conn = False
        if conn is None:
            conn = conectar_db()
            cerrar_conn = True
        if not conn:
            return res
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT estado_sync, COUNT(id)
                FROM cola_sincronizacion
                GROUP BY estado_sync
            """)
            for estado, conteo in cur.fetchall():
                cnt = int(conteo or 0)
                if estado in (ESTADO_PENDIENTE, ESTADO_SINCRONIZANDO):
                    res["pendientes"] += cnt
                elif estado == ESTADO_SINCRONIZADO:
                    res["sincronizados"] += cnt
                elif estado == ESTADO_ERROR:
                    res["errores"] += cnt
                res["total"] += cnt
            return res
        except Exception:
            return res
        finally:
            if cerrar_conn and conn:
                conn.close()

    def obtener_items_pendientes(self, limite: int = 50, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
        """Obtiene las operaciones pendientes ordenadas cronológicamente (FIFO)."""
        cerrar_conn = False
        if conn is None:
            conn = conectar_db()
            cerrar_conn = True
        if not conn:
            return []
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT id, empresa, usuario, dispositivo, tipo_operacion,
                       fecha_hora, payload_json, estado_sync, intentos,
                       ultimo_error, id_local, created_at, updated_at
                FROM cola_sincronizacion
                WHERE estado_sync IN (?, ?)
                ORDER BY fecha_hora ASC, id ASC
                LIMIT ?
            """, (ESTADO_PENDIENTE, ESTADO_ERROR, limite))
            rows = cur.fetchall()
            items = []
            for r in rows:
                d = dict(r)
                try:
                    d["payload"] = json.loads(d.get("payload_json") or "{}")
                except Exception:
                    d["payload"] = {}
                items.append(d)
            return items
        except Exception as e:
            print(f"Aviso leyendo items pendientes de sincronización: {e}")
            return []
        finally:
            if cerrar_conn and conn:
                conn.close()

    def procesar_cola(self) -> Dict[str, Any]:
        """
        Ejecuta el ciclo de sincronización de la cola:
        1. Verifica salud real del servidor (/api/health).
        2. Despacha cada operación pendiente a su endpoint de destino.
        3. Aplica idempotencia garantizada por el servidor.
        """
        with self._lock:
            if self._sincronizando_ahora:
                return {"status": "en_progreso", "procesados": 0}
            self._sincronizando_ahora = True

        self._notificar_cambio()
        procesados = 0
        exitosos = 0
        fallidos = 0

        try:
            # 1. Comprobar disponibilidad real del servidor
            if not api.esta_disponible(forzar=True):
                # Intentar auto-descubrimiento en LAN antes de suspender
                try:
                    from interface.network_manager import auto_recuperar_conexion_servidor
                    recuperado, nueva_url = auto_recuperar_conexion_servidor()
                    if recuperado:
                        api.base_url = nueva_url
                except Exception:
                    pass

                if not api.esta_disponible(forzar=True):
                    return {"status": "servidor_no_disponible", "procesados": 0}

            items = self.obtener_items_pendientes(limite=30)
            if not items:
                return {"status": "vacio", "procesados": 0}

            for it in items:
                procesados += 1
                op_id = it["id"]
                tipo = it["tipo_operacion"]
                payload = it.get("payload", {})

                exito, err_msg = self._despachar_operacion(op_id, tipo, payload)
                if exito:
                    exitosos += 1
                    self.marcar_como_sincronizada(op_id)
                else:
                    fallidos += 1
                    self.marcar_error_sincronizacion(op_id, err_msg)
                    # Si falla por error de conexión global, pausar el ciclo
                    if "no disponible" in err_msg.lower() or "timeout" in err_msg.lower() or "connect" in err_msg.lower():
                        break

            self._ultimo_sync_ts = time.time()
            return {
                "status": "completado",
                "procesados": procesados,
                "exitosos": exitosos,
                "fallidos": fallidos
            }
        finally:
            with self._lock:
                self._sincronizando_ahora = False
            self._notificar_cambio()

    def _despachar_operacion(self, op_id: str, tipo: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
        """Envía una operación específica a la API central respetando idempotencia."""
        payload["idempotency_key"] = op_id

        try:
            if tipo == OP_VENTA:
                resp = api.post("/ventas", json=payload, timeout=12.0)
                if resp.status_code in (200, 201):
                    return True, ""
                # Si el servidor ya la tenía registrada con esa idempotencia, considerarla exitosa
                if resp.status_code == 409 or "idempotenc" in resp.text.lower() or "duplicad" in resp.text.lower():
                    return True, ""
                # Si el código fue 503/504 es fallo de red
                if getattr(resp, "is_network_error", False):
                    return False, f"Fallo de conexión enviando venta: {resp.text}"
                return False, f"Servidor rechazó venta ({resp.status_code}): {resp.text}"

            elif tipo == OP_ABONO:
                cli_id = payload.get("cliente_id") or 1
                resp = api.post(f"/clientes/{cli_id}/abonos", json=payload, timeout=10.0)
                if resp.status_code in (200, 201):
                    return True, ""
                if getattr(resp, "is_network_error", False):
                    return False, f"Fallo de conexión enviando abono: {resp.text}"
                return False, f"Servidor rechazó abono ({resp.status_code}): {resp.text}"

            elif tipo == OP_GASTO:
                resp = api.post("/gastos", json=payload, timeout=10.0)
                if resp.status_code in (200, 201):
                    return True, ""
                if getattr(resp, "is_network_error", False):
                    return False, f"Fallo de conexión enviando gasto: {resp.text}"
                return False, f"Servidor rechazó gasto ({resp.status_code}): {resp.text}"

            elif tipo == OP_LIQ_PROVEEDOR:
                prov_id = payload.get("proveedor_id")
                resp = api.post(f"/proveedores/{prov_id}/liquidar", json=payload, timeout=10.0)
                if resp.status_code in (200, 201):
                    return True, ""
                if getattr(resp, "is_network_error", False):
                    return False, f"Fallo de conexión liquidando proveedor: {resp.text}"
                return False, f"Servidor rechazó liquidación ({resp.status_code}): {resp.text}"

            elif tipo == OP_LIQ_NOMINA:
                resp = api.post("/nomina/liquidaciones", json=payload, timeout=10.0)
                if resp.status_code in (200, 201):
                    return True, ""
                if getattr(resp, "is_network_error", False):
                    return False, f"Fallo de conexión liquidando nómina: {resp.text}"
                return False, f"Servidor rechazó liquidación de nómina ({resp.status_code}): {resp.text}"

            elif tipo == OP_MOV_INVENTARIO:
                resp = api.post("/inventario/movimientos", json=payload, timeout=10.0)
                if resp.status_code in (200, 201):
                    return True, ""
                if getattr(resp, "is_network_error", False):
                    return False, f"Fallo de conexión en inventario: {resp.text}"
                return False, f"Error en inventario ({resp.status_code}): {resp.text}"

            else:
                return True, f"Tipo de operación desconocido: {tipo} (ignorado)"
        except Exception as e:
            return False, str(e)

    def disparar_sincronizacion_asincrona(self):
        """Inicia una ronda de sincronización en un hilo secundario sin congelar la interfaz."""
        threading.Thread(target=self.procesar_cola, daemon=True, name="VmPOS_SyncWorker").start()

    def iniciar_demonio_sincronizacion(self, intervalo_segundos: int = 15):
        """Inicia el demonio de fondo que intenta sincronizar la cola periódicamente."""
        with self._lock:
            if self._daemon_iniciado:
                return
            self._daemon_iniciado = True

        def _bucle():
            while True:
                try:
                    time.sleep(intervalo_segundos)
                    conteo = self.obtener_conteo_pendientes()
                    if conteo["pendientes"] > 0 or conteo["errores"] > 0:
                        self.procesar_cola()
                except Exception as e:
                    print(f"Aviso en demonio de sincronización: {e}")

        t = threading.Thread(target=_bucle, daemon=True, name="VmPOS_SyncDaemon")
        t.start()

    def agregar_observador(self, callback):
        """Agrega un listener para actualizar indicadores de estado en la UI."""
        if callable(callback) and callback not in self._listeners:
            self._listeners.append(callback)

    def _notificar_cambio(self):
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:
                pass

    def obtener_estado_visual(self) -> Dict[str, Any]:
        """
        Retorna el estado de conectividad e información de cola para la barra superior:
        - estado: 'conectado' | 'red_local' | 'sin_servidor' | 'sincronizando' | 'offline'
        - texto: etiqueta descriptiva
        - color: color hexadecimal WCAG
        - pendientes: cantidad de operaciones pendientes
        """
        conteo = self.obtener_conteo_pendientes()
        n_pend = conteo["pendientes"] + conteo["errores"]

        if self._sincronizando_ahora:
            return {
                "estado": "sincronizando",
                "texto": f"🔄 Sincronizando ({n_pend} pendientes)...",
                "color": "#3B82F6",
                "color_bg": "#EFF6FF",
                "pendientes": n_pend
            }

        servidor_ok = api.esta_disponible()
        if servidor_ok:
            if n_pend > 0:
                return {
                    "estado": "conectado_con_cola",
                    "texto": f"🟢 En Línea • {n_pend} por sincronizar",
                    "color": "#10B981",
                    "color_bg": "#ECFDF5",
                    "pendientes": n_pend
                }
            return {
                "estado": "conectado",
                "texto": "🟢 Conectado al Servidor",
                "color": "#10B981",
                "color_bg": "#ECFDF5",
                "pendientes": 0
            }

        # Servidor no disponible: Modo Offline activo
        if n_pend > 0:
            return {
                "estado": "offline_con_pendientes",
                "texto": f"🟠 Modo Fuera de Línea • {n_pend} pendientes",
                "color": "#D97706",
                "color_bg": "#FFFBEB",
                "pendientes": n_pend
            }

        return {
            "estado": "offline",
            "texto": "🟡 Modo Fuera de Línea",
            "color": "#F59E0B",
            "color_bg": "#FEF3C7",
            "pendientes": 0
        }


# Instancia global singleton
sync_mgr = SyncManager()
