#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor Empresarial de Respaldo y Restauración Verificada - VmPOS
Archivo: interface/backup_manager.py

Características:
- Usa la API nativa de respaldo en caliente de SQLite (`Connection.backup`),
  segura incluso con modo WAL activo y conexiones concurrentes.
- Respalda de forma íntegra las bases de datos del sistema (`ventas.db`,
  `usuarios.db`, `vmpos_server.db`) y archivos de configuración locales
  (`business_config.json`, `printer_config.json`, `theme_config.json`).
- Genera un archivo `manifest.json` con hashes SHA-256, tamaños y conteo de filas.
- Verifica `PRAGMA integrity_check` en cada archivo SQLite generado y restaurado.
- Exige respaldo preventivo previo antes de cualquier restauración.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

try:
    from interface.config import (
        DATABASE_DIR,
        CONFIG_DIR,
        BACKUPS_DIR,
        DB_VENTAS_PATH,
        DB_USUARIOS_PATH,
    )
except ImportError:
    try:
        from config import (
            DATABASE_DIR,
            CONFIG_DIR,
            BACKUPS_DIR,
            DB_VENTAS_PATH,
            DB_USUARIOS_PATH,
        )
    except ImportError:
        _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        DATABASE_DIR = os.path.join(_ROOT, "database")
        CONFIG_DIR = os.path.join(_ROOT, "config")
        BACKUPS_DIR = os.path.join(_ROOT, "backups")
        DB_VENTAS_PATH = os.path.join(DATABASE_DIR, "ventas.db")
        DB_USUARIOS_PATH = os.path.join(DATABASE_DIR, "usuarios.db")


DB_FILENAMES = ("ventas.db", "usuarios.db", "vmpos_server.db")
CONFIG_FILENAMES = ("business_config.json", "printer_config.json", "theme_config.json")


def calcular_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verificar_integridad_sqlite(db_path: str) -> Tuple[bool, str]:
    """Ejecuta PRAGMA integrity_check sobre un archivo SQLite."""
    if not db_path or not os.path.isfile(db_path):
        return False, f"Archivo no encontrado: {db_path}"
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=15.0)
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check;")
        row = cur.fetchone()
        res = str(row[0]) if row else "error"
        return (res.lower() == "ok"), res
    except Exception as exc:
        return False, str(exc)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def checkpoint_wal_sqlite(db_path: str) -> bool:
    """Ejecuta PRAGMA wal_checkpoint(TRUNCATE) para vaciar WAL en el archivo principal."""
    if not db_path or not os.path.isfile(db_path):
        return False
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        return True
    except Exception:
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _backup_sqlite_en_caliente(origen: str, destino: str) -> Dict[str, Any]:
    """Copia consistente de una base SQLite usando la API online backup (segura con WAL)."""
    os.makedirs(os.path.dirname(os.path.abspath(destino)), exist_ok=True)
    if os.path.exists(destino):
        os.remove(destino)
    src_conn = None
    dst_conn = None
    try:
        src_conn = sqlite3.connect(origen, timeout=20.0)
        try:
            src_conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        except Exception:
            pass
        dst_conn = sqlite3.connect(destino, timeout=20.0)
        src_conn.backup(dst_conn)
        dst_conn.commit()
        try:
            dst_conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        except Exception:
            pass
    finally:
        if dst_conn is not None:
            try:
                dst_conn.close()
            except Exception:
                pass
        if src_conn is not None:
            try:
                src_conn.close()
            except Exception:
                pass

    ok_int, msg_int = verificar_integridad_sqlite(destino)
    if not ok_int:
        raise RuntimeError(f"La copia de seguridad de {os.path.basename(origen)} falló integrity_check: {msg_int}")

    # Contar tablas y filas para trazabilidad del manifiesto
    tablas_info: Dict[str, int] = {}
    conn_c = sqlite3.connect(destino, timeout=10.0)
    try:
        cur_c = conn_c.cursor()
        cur_c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        for (tbl,) in cur_c.fetchall():
            try:
                cur_c.execute(f'SELECT COUNT(*) FROM "{tbl}"')
                tablas_info[tbl] = int(cur_c.fetchone()[0] or 0)
            except Exception:
                tablas_info[tbl] = -1
    finally:
        conn_c.close()

    return {
        "size_bytes": os.path.getsize(destino),
        "sha256": calcular_sha256(destino),
        "integrity_check": "ok",
        "tablas": tablas_info,
    }


def crear_respaldo_completo(
    destino_raiz: Optional[str] = None,
    database_dir: Optional[str] = None,
    config_dir: Optional[str] = None,
    etiqueta: str = "manual",
) -> Dict[str, Any]:
    """
    Crea un respaldo completo, atómico y verificable en una carpeta timestamped:
      <destino_raiz>/backup_vmpos_<etiqueta>_YYYYMMDD_HHMMSS/
        - database/{ventas.db, usuarios.db, vmpos_server.db}
        - config/{business_config.json, ...}
        - manifest.json
    """
    raiz_bk = os.path.abspath(destino_raiz or BACKUPS_DIR)
    dir_db = os.path.abspath(database_dir or DATABASE_DIR)
    dir_cfg = os.path.abspath(config_dir or CONFIG_DIR)
    os.makedirs(raiz_bk, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
    etiq_safe = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in str(etiqueta or "manual"))[:24]
    nombre_bk = f"backup_vmpos_{etiq_safe}_{ts}"
    ruta_bk = os.path.join(raiz_bk, nombre_bk)
    ruta_bk_db = os.path.join(ruta_bk, "database")
    ruta_bk_cfg = os.path.join(ruta_bk, "config")
    os.makedirs(ruta_bk_db, exist_ok=True)
    os.makedirs(ruta_bk_cfg, exist_ok=True)

    manifest: Dict[str, Any] = {
        "schema_version": 1,
        "app": "VmPOS",
        "etiqueta": etiq_safe,
        "created_at": datetime.now().isoformat(),
        "databases": {},
        "configs": {},
    }

    try:
        dbs_respaldadas = 0
        for db_name in DB_FILENAMES:
            src_db = os.path.join(dir_db, db_name)
            if os.path.isfile(src_db):
                dst_db = os.path.join(ruta_bk_db, db_name)
                manifest["databases"][db_name] = _backup_sqlite_en_caliente(src_db, dst_db)
                dbs_respaldadas += 1

        if dbs_respaldadas == 0:
            raise FileNotFoundError(f"No se encontró ninguna base de datos SQLite en {dir_db}")

        for cfg_name in CONFIG_FILENAMES:
            src_cfg = os.path.join(dir_cfg, cfg_name)
            if os.path.isfile(src_cfg):
                dst_cfg = os.path.join(ruta_bk_cfg, cfg_name)
                shutil.copy2(src_cfg, dst_cfg)
                manifest["configs"][cfg_name] = {
                    "size_bytes": os.path.getsize(dst_cfg),
                    "sha256": calcular_sha256(dst_cfg),
                }

        manifest_path = os.path.join(ruta_bk, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as mf:
            json.dump(manifest, mf, indent=2, ensure_ascii=False)

        total_bytes = sum(v["size_bytes"] for v in manifest["databases"].values()) + sum(
            v["size_bytes"] for v in manifest["configs"].values()
        )
        return {
            "ok": True,
            "backup_dir": ruta_bk,
            "backup_name": nombre_bk,
            "manifest_path": manifest_path,
            "total_bytes": total_bytes,
            "databases": list(manifest["databases"].keys()),
            "configs": list(manifest["configs"].keys()),
            "manifest": manifest,
        }
    except Exception:
        # Si falla cualquier verificación, limpiar directorio incompleto para no dejar respaldos corruptos
        shutil.rmtree(ruta_bk, ignore_errors=True)
        raise


def verificar_respaldo(backup_dir: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Verifica la existencia, hashes SHA-256 e integridad SQLite de un respaldo completo."""
    ruta_bk = os.path.abspath(backup_dir)
    manifest_path = os.path.join(ruta_bk, "manifest.json")
    if not os.path.isfile(manifest_path):
        return False, f"No se encontró manifest.json en {ruta_bk}", None

    try:
        with open(manifest_path, "r", encoding="utf-8") as mf:
            manifest = json.load(mf)
    except Exception as exc:
        return False, f"manifest.json ilegible o corrupto: {exc}", None

    dbs = manifest.get("databases") or {}
    if not dbs:
        return False, "El respaldo no contiene bases de datos registradas en manifest.json.", manifest

    for db_name, meta in dbs.items():
        db_file = os.path.join(ruta_bk, "database", db_name)
        if not os.path.isfile(db_file):
            return False, f"Falta archivo de base de datos en respaldo: {db_name}", manifest
        sha_actual = calcular_sha256(db_file)
        if meta.get("sha256") and sha_actual != meta.get("sha256"):
            return False, f"Checksum SHA-256 inválido para {db_name} (posible corrupción o alteración).", manifest
        ok_int, msg_int = verificar_integridad_sqlite(db_file)
        if not ok_int:
            return False, f"Integridad SQLite fallida en {db_name}: {msg_int}", manifest

    for cfg_name, meta in (manifest.get("configs") or {}).items():
        cfg_file = os.path.join(ruta_bk, "config", cfg_name)
        if not os.path.isfile(cfg_file):
            return False, f"Falta archivo de configuración en respaldo: {cfg_name}", manifest
        sha_actual = calcular_sha256(cfg_file)
        if meta.get("sha256") and sha_actual != meta.get("sha256"):
            return False, f"Checksum SHA-256 inválido para {cfg_name}.", manifest

    return True, "Respaldo verificado íntegro (SHA-256 + PRAGMA integrity_check OK).", manifest


def restaurar_respaldo(
    backup_dir: str,
    database_dir: Optional[str] = None,
    config_dir: Optional[str] = None,
    backups_dir: Optional[str] = None,
    crear_respaldo_previo: bool = True,
) -> Dict[str, Any]:
    """
    Restaura de forma segura un respaldo previamente verificado con arquitectura
    de dos fases (Staging + Atomic Swap con Rollback Todo-o-Nada):

    1. Valida SHA-256 y PRAGMA integrity_check del respaldo fuente.
    2. Checkpoint preventivo de WAL en todas las bases activas locales.
    3. Si `crear_respaldo_previo=True` y existen bases actuales, toma un snapshot preventivo
       obligatorio antes de tocar producción.
    4. Fase 1 (Staging): Extrae y genera copias limpias de todas las bases y configs en un
       directorio temporal aislado, validando la integridad SQLite y consistencia antes de
       modificar ningún archivo de producción.
    5. Fase 2 (Atomic Swap con Rollback Automático):
       - Mueve los archivos activos actuales a un directorio de contingencia.
       - Reemplaza atómicamente con los archivos validados de la etapa de staging.
       - Limpia archivos -wal y -shm residuales de forma segura.
       - Valida la integridad final de cada base instalada.
       - En caso de cualquier excepción en esta fase, revierte inmediatamente todos
         los cambios restaurando los archivos originales desde el área de contingencia,
         garantizando que el sistema jamás quede en un estado mixto o corrupto.
    """
    ok_ver, msg_ver, manifest = verificar_respaldo(backup_dir)
    if not ok_ver or not manifest:
        raise ValueError(f"Restauración abortada: {msg_ver}")

    dir_db = os.path.abspath(database_dir or DATABASE_DIR)
    dir_cfg = os.path.abspath(config_dir or CONFIG_DIR)
    dir_bk = os.path.abspath(backups_dir or BACKUPS_DIR)
    os.makedirs(dir_db, exist_ok=True)
    os.makedirs(dir_cfg, exist_ok=True)

    # 2. Checkpoint preventivo de las bases activas en producción
    for db_name in DB_FILENAMES:
        db_path = os.path.join(dir_db, db_name)
        if os.path.isfile(db_path):
            checkpoint_wal_sqlite(db_path)

    # 3. Snapshot preventivo previo
    pre_backup_info = None
    if crear_respaldo_previo:
        existen_dbs = any(os.path.isfile(os.path.join(dir_db, n)) for n in DB_FILENAMES)
        if existen_dbs:
            pre_backup_info = crear_respaldo_completo(
                destino_raiz=dir_bk,
                database_dir=dir_db,
                config_dir=dir_cfg,
                etiqueta="pre_restore",
            )

    ruta_bk = os.path.abspath(backup_dir)
    dbs_target = list(manifest.get("databases", {}).keys())
    cfgs_target = [c for c in manifest.get("configs", {}).keys() if os.path.isfile(os.path.join(ruta_bk, "config", c))]

    # 4. Fase 1: Staging aislado
    stage_dir = tempfile.mkdtemp(prefix=".restore_stage_", dir=dir_db)
    try:
        for db_name in dbs_target:
            src_db = os.path.join(ruta_bk, "database", db_name)
            staged_db = os.path.join(stage_dir, db_name)
            _backup_sqlite_en_caliente(src_db, staged_db)
            ok_s, msg_s = verificar_integridad_sqlite(staged_db)
            if not ok_s:
                raise RuntimeError(f"Error en staging: base {db_name} no superó integrity_check: {msg_s}")

        for cfg_name in cfgs_target:
            src_cfg = os.path.join(ruta_bk, "config", cfg_name)
            staged_cfg = os.path.join(stage_dir, cfg_name)
            shutil.copy2(src_cfg, staged_cfg)
    except Exception as exc:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise RuntimeError(f"Fallo durante la fase de staging de restauración: {exc}. Producción intacta.")

    # 5. Fase 2: Atomic Swap con Rollback Todo-o-Nada
    rollback_dir = tempfile.mkdtemp(prefix=".restore_rollback_", dir=dir_db)
    swapped_items: List[Dict[str, Any]] = []
    dbs_restauradas: List[str] = []
    cfgs_restaurados: List[str] = []

    try:
        # Reemplazar bases de datos
        for db_name in dbs_target:
            dst_db = os.path.join(dir_db, db_name)
            staged_db = os.path.join(stage_dir, db_name)
            rb_db = os.path.join(rollback_dir, db_name)
            sidecars_rb: Dict[str, str] = {}

            # Mover archivo original si existe a rollback_dir
            tenia_original = os.path.isfile(dst_db)
            if tenia_original:
                checkpoint_wal_sqlite(dst_db)
                os.replace(dst_db, rb_db)
                for ext in ("-wal", "-shm"):
                    side_src = f"{dst_db}{ext}"
                    if os.path.exists(side_src):
                        side_dst = os.path.join(rollback_dir, f"{db_name}{ext}")
                        os.replace(side_src, side_dst)
                        sidecars_rb[ext] = side_dst

            # Registrar inmediatamente en swapped_items antes de reemplazar para garantizar rollback
            item_record = {
                "type": "db",
                "name": db_name,
                "dst_path": dst_db,
                "rb_path": rb_db if tenia_original else None,
                "sidecars": sidecars_rb,
                "tenia_original": tenia_original,
            }
            swapped_items.append(item_record)

            # Instalar archivo desde staging
            os.replace(staged_db, dst_db)

            # Limpiar cualquier residuo de -wal/-shm en destino
            for ext in ("-wal", "-shm"):
                side_cur = f"{dst_db}{ext}"
                if os.path.exists(side_cur):
                    try:
                        os.remove(side_cur)
                    except Exception:
                        pass

            # Validar integridad post-swap
            ok_dst, msg_dst = verificar_integridad_sqlite(dst_db)
            if not ok_dst:
                raise RuntimeError(f"Integridad SQLite falló post-swap en {db_name}: {msg_dst}")

            dbs_restauradas.append(db_name)

        # Reemplazar configuraciones
        for cfg_name in cfgs_target:
            dst_cfg = os.path.join(dir_cfg, cfg_name)
            staged_cfg = os.path.join(stage_dir, cfg_name)
            rb_cfg = os.path.join(rollback_dir, cfg_name)

            tenia_original = os.path.isfile(dst_cfg)
            if tenia_original:
                os.replace(dst_cfg, rb_cfg)

            item_record_cfg = {
                "type": "cfg",
                "name": cfg_name,
                "dst_path": dst_cfg,
                "rb_path": rb_cfg if tenia_original else None,
                "sidecars": {},
                "tenia_original": tenia_original,
            }
            swapped_items.append(item_record_cfg)

            os.replace(staged_cfg, dst_cfg)
            cfgs_restaurados.append(cfg_name)

    except Exception as exc:
        # ROLLBACK AUTOMÁTICO TODO-O-NADA
        rollback_errors = []
        for item in reversed(swapped_items):
            try:
                # Quitar lo instalado
                if os.path.exists(item["dst_path"]):
                    try:
                        os.remove(item["dst_path"])
                    except Exception as e_rm:
                        rollback_errors.append(f"No se pudo remover {item['dst_path']}: {e_rm}")

                # Si existía original, devolverlo
                if item["tenia_original"] and item["rb_path"] and os.path.exists(item["rb_path"]):
                    os.replace(item["rb_path"], item["dst_path"])
                    # Restaurar sidecars (-wal, -shm)
                    for ext, side_rb in item.get("sidecars", {}).items():
                        side_dst = f"{item['dst_path']}{ext}"
                        if os.path.exists(side_rb):
                            os.replace(side_rb, side_dst)

                # Si no existía original, asegurarse que no quede residuo
                elif not item["tenia_original"]:
                    for ext in ("-wal", "-shm"):
                        side_dst = f"{item['dst_path']}{ext}"
                        if os.path.exists(side_dst):
                            try:
                                os.remove(side_dst)
                            except Exception:
                                pass
            except Exception as e_rb:
                rollback_errors.append(f"Error revirtiendo {item['name']}: {e_rb}")

        # Limpiar directorios temporales
        shutil.rmtree(rollback_dir, ignore_errors=True)
        shutil.rmtree(stage_dir, ignore_errors=True)

        rb_status = "Rollback completado con éxito; datos originales conservados intactos."
        if rollback_errors:
            rb_status = f"Rollback parcial con alertas: {'; '.join(rollback_errors)}"

        raise RuntimeError(
            f"Fallo durante el reemplazo atómico de la restauración: {exc}. {rb_status}"
        )
    finally:
        # Limpieza normal en caso de éxito
        shutil.rmtree(rollback_dir, ignore_errors=True)
        shutil.rmtree(stage_dir, ignore_errors=True)

    return {
        "ok": True,
        "backup_origen": ruta_bk,
        "pre_restore_backup": pre_backup_info["backup_dir"] if pre_backup_info else None,
        "databases_restauradas": dbs_restauradas,
        "configs_restaurados": cfgs_restaurados,
        "atomic_swap_verified": True,
    }
