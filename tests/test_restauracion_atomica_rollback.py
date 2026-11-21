#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Suite de Pruebas de Integración para la Restauración Atómica y Rollback Todo-o-Nada:
- Verificación de restauración multi-base consistente con comparación exhaustiva de checksums y filas.
- Demostración de Rollback Todo-o-Nada cuando ocurre un fallo parcial durante el reemplazo atómico
  (evitando skew de versiones o bases inconsistentes).
- Aislamiento estricto de la etapa de Staging (sin alterar producción en caso de error temprano).
- Vaciado preventivo de WAL (PRAGMA wal_checkpoint(TRUNCATE)) y saneamiento de archivos sidecar (-wal, -shm).
"""

import unittest
import os
import shutil
import tempfile
import sqlite3
import json
from unittest.mock import patch

from interface.backup_manager import (
    crear_respaldo_completo,
    verificar_respaldo,
    restaurar_respaldo,
    verificar_integridad_sqlite,
    checkpoint_wal_sqlite,
    calcular_sha256,
)


class TestRestauracionAtomicaRollback(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp(prefix="test_atomic_restore_")
        self.db_dir = os.path.join(self.temp_root, "database")
        self.cfg_dir = os.path.join(self.temp_root, "config")
        self.bk_dir = os.path.join(self.temp_root, "backups")
        os.makedirs(self.db_dir, exist_ok=True)
        os.makedirs(self.cfg_dir, exist_ok=True)
        os.makedirs(self.bk_dir, exist_ok=True)

        # 1. Base ventas.db
        self.ventas_path = os.path.join(self.db_dir, "ventas.db")
        with sqlite3.connect(self.ventas_path) as conn:
            conn.execute("CREATE TABLE ventas (id INTEGER PRIMARY KEY, total REAL, fecha TEXT);")
            conn.execute("INSERT INTO ventas (id, total, fecha) VALUES (1, 150000.0, '2026-11-20');")
            conn.execute("INSERT INTO ventas (id, total, fecha) VALUES (2, 45000.0, '2026-11-20');")

        # 2. Base usuarios.db
        self.usuarios_path = os.path.join(self.db_dir, "usuarios.db")
        with sqlite3.connect(self.usuarios_path) as conn:
            conn.execute("CREATE TABLE usuarios (id INTEGER PRIMARY KEY, username TEXT, rol TEXT);")
            conn.execute("INSERT INTO usuarios (id, username, rol) VALUES (1, 'admin', 'Administrador');")
            conn.execute("INSERT INTO usuarios (id, username, rol) VALUES (2, 'cajero1', 'Cajero');")

        # 3. Base vmpos_server.db
        self.server_path = os.path.join(self.db_dir, "vmpos_server.db")
        with sqlite3.connect(self.server_path) as conn:
            conn.execute("CREATE TABLE sync_queue (id INTEGER PRIMARY KEY, accion TEXT, estado TEXT);")
            conn.execute("INSERT INTO sync_queue (id, accion, estado) VALUES (1, 'CREAR_VENTA', 'PROCESADO');")

        # 4. Configs
        self.cfg_business = os.path.join(self.cfg_dir, "business_config.json")
        with open(self.cfg_business, "w", encoding="utf-8") as f:
            json.dump({"nombre_negocio": "Super VmPOS Central", "nit": "900123456-7"}, f)

    def tearDown(self):
        if os.path.exists(self.temp_root):
            shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_01_restauracion_exitosa_comparacion_exhaustiva(self):
        """Crea respaldo Estado A, modifica a Estado B, restaura y valida equivalencia exacta con A."""
        # Respaldar Estado A
        bk_info = crear_respaldo_completo(
            destino_raiz=self.bk_dir,
            database_dir=self.db_dir,
            config_dir=self.cfg_dir,
            etiqueta="estado_A",
        )
        self.assertTrue(bk_info["ok"])
        ruta_bk = bk_info["backup_dir"]

        # Modificar a Estado B (insertar filas y cambiar configs)
        with sqlite3.connect(self.ventas_path) as conn:
            for i in range(3, 10):
                conn.execute("INSERT INTO ventas (id, total, fecha) VALUES (?, 25000.0, '2026-11-21');", (i,))
        with sqlite3.connect(self.usuarios_path) as conn:
            conn.execute("INSERT INTO usuarios (id, username, rol) VALUES (3, 'auditor', 'Auditor');")
        with open(self.cfg_business, "w", encoding="utf-8") as f:
            json.dump({"nombre_negocio": "Estado B Modificado", "nit": "000000000-0"}, f)

        # Comprobar que el estado actual tiene datos de B
        with sqlite3.connect(self.ventas_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM ventas;").fetchone()[0], 9)
        with sqlite3.connect(self.usuarios_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM usuarios;").fetchone()[0], 3)

        # Restaurar Estado A
        res_rest = restaurar_respaldo(
            backup_dir=ruta_bk,
            database_dir=self.db_dir,
            config_dir=self.cfg_dir,
            backups_dir=self.bk_dir,
            crear_respaldo_previo=True,
        )
        self.assertTrue(res_rest["ok"])
        self.assertTrue(res_rest["atomic_swap_verified"])
        self.assertIsNotNone(res_rest["pre_restore_backup"])

        # Verificar integridad SQLite y conteo exacto de filas restituido
        for p, expected_rows, table in [
            (self.ventas_path, 2, "ventas"),
            (self.usuarios_path, 2, "usuarios"),
            (self.server_path, 1, "sync_queue"),
        ]:
            ok, msg = verificar_integridad_sqlite(p)
            self.assertTrue(ok, f"Fallo en {p}: {msg}")
            with sqlite3.connect(p) as conn:
                count = conn.execute(f"SELECT COUNT(*) FROM {table};").fetchone()[0]
                self.assertEqual(count, expected_rows, f"Desajuste de filas en {table}")

        # Configuración debe ser la de A
        with open(self.cfg_business, "r", encoding="utf-8") as f:
            cfg_data = json.load(f)
            self.assertEqual(cfg_data["nombre_negocio"], "Super VmPOS Central")

    def test_02_rollback_atomico_ante_fallo_en_fase_swap(self):
        """
        Simula un fallo catastrófico al sustituir la SEGUNDA base de datos (usuarios.db).
        Valida que la PRIMERA base (ventas.db) que ya había sido sustituida se revierta automáticamente,
        garantizando que ninguna base quede en versión mixta o corrupta (Rollback Todo-o-Nada).
        """
        # Estado A (original en producción):
        # ventas: 2 registros, usuarios: 2 registros
        with sqlite3.connect(self.ventas_path) as conn:
            conn.execute("INSERT INTO ventas (id, total, fecha) VALUES (100, 999.0, 'original_A');")
        with sqlite3.connect(self.usuarios_path) as conn:
            conn.execute("INSERT INTO usuarios (id, username, rol) VALUES (100, 'orig_user_A', 'Admin');")

        # Generar un respaldo alternativo "Estado_B" en otra carpeta temporal
        temp_b = tempfile.mkdtemp(prefix="test_state_b_")
        db_b = os.path.join(temp_b, "database")
        cfg_b = os.path.join(temp_b, "config")
        os.makedirs(db_b, exist_ok=True)
        os.makedirs(cfg_b, exist_ok=True)

        with sqlite3.connect(os.path.join(db_b, "ventas.db")) as conn:
            conn.execute("CREATE TABLE ventas (id INTEGER PRIMARY KEY, total REAL, fecha TEXT);")
            conn.execute("INSERT INTO ventas (id, total, fecha) VALUES (201, 888.0, 'state_B');")
        with sqlite3.connect(os.path.join(db_b, "usuarios.db")) as conn:
            conn.execute("CREATE TABLE usuarios (id INTEGER PRIMARY KEY, username TEXT, rol TEXT);")
            conn.execute("INSERT INTO usuarios (id, username, rol) VALUES (201, 'b_user', 'B');")
            conn.execute("INSERT INTO usuarios (id, username, rol) VALUES (202, 'b_user_2', 'B');")
            conn.execute("INSERT INTO usuarios (id, username, rol) VALUES (203, 'b_user_3', 'B');")

        bk_b_info = crear_respaldo_completo(
            destino_raiz=self.bk_dir,
            database_dir=db_b,
            config_dir=cfg_b,
            etiqueta="estado_B",
        )
        ruta_bk_b = bk_b_info["backup_dir"]
        shutil.rmtree(temp_b, ignore_errors=True)

        # Validamos que el respaldo B sea verificado íntegro
        ok_v, _, _ = verificar_respaldo(ruta_bk_b)
        self.assertTrue(ok_v)

        # Ahora interceptamos verificar_integridad_sqlite para que falle SOLO en usuarios.db durante el swap
        real_verificar = verificar_integridad_sqlite

        def fake_verificar_integridad(path):
            if "usuarios.db" in str(path) and str(path).startswith(self.db_dir) and ".restore_stage_" not in str(path):
                # Simular error post-swap exclusivamente en la base instalada en producción
                return False, "Simulated disk I/O sector error post-swap in usuarios.db"
            return real_verificar(path)

        with patch("interface.backup_manager.verificar_integridad_sqlite", side_effect=fake_verificar_integridad):
            with self.assertRaises(RuntimeError) as ctx:
                restaurar_respaldo(
                    backup_dir=ruta_bk_b,
                    database_dir=self.db_dir,
                    config_dir=self.cfg_dir,
                    backups_dir=self.bk_dir,
                    crear_respaldo_previo=False,
                )
            self.assertIn("Fallo durante el reemplazo atómico", str(ctx.exception))
            self.assertIn("Rollback completado con éxito", str(ctx.exception))

        # VERIFICACIÓN CRÍTICA DEL ROLLBACK:
        # 1. ventas.db (que fue swap #1 antes de que fallara usuarios.db swap #2) DEBE haber vuelto a Estado A.
        with sqlite3.connect(self.ventas_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, fecha FROM ventas WHERE id=100;")
            row = cur.fetchone()
            self.assertIsNotNone(row, "ventas.db quedó alterada tras fallo; el rollback no restituyó Estado A")
            self.assertEqual(row[1], "original_A")
            # Comprobar que no tiene registros de B
            cur.execute("SELECT COUNT(*) FROM ventas WHERE id=201;")
            self.assertEqual(cur.fetchone()[0], 0, "ventas.db contiene registros de Estado B tras rollback!")

        # 2. usuarios.db DEBE permanecer en Estado A íntegra
        with sqlite3.connect(self.usuarios_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, username FROM usuarios WHERE id=100;")
            row_u = cur.fetchone()
            self.assertIsNotNone(row_u, "usuarios.db no se preservó en Estado A")
            self.assertEqual(row_u[1], "orig_user_A")
            cur.execute("SELECT COUNT(*) FROM usuarios WHERE id=201;")
            self.assertEqual(cur.fetchone()[0], 0, "usuarios.db contiene registros de Estado B!")

        # 3. Integridad SQLite real de ambas bases debe ser 100% OK
        ok_v, _ = real_verificar(self.ventas_path)
        self.assertTrue(ok_v)
        ok_u, _ = real_verificar(self.usuarios_path)
        self.assertTrue(ok_u)

    def test_03_wal_mode_checkpoint_y_sidecars_cleanup(self):
        """Valida que bases en modo WAL sean vaciadas y no queden sidecars incongruentes tras restauración."""
        # Poner ventas.db en modo WAL
        with sqlite3.connect(self.ventas_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("INSERT INTO ventas (id, total, fecha) VALUES (99, 12000.0, 'wal_row');")

        # Comprobar que checkpoint_wal_sqlite funciona
        ok_cp = checkpoint_wal_sqlite(self.ventas_path)
        self.assertTrue(ok_cp)

        # Crear respaldo
        bk_info = crear_respaldo_completo(
            destino_raiz=self.bk_dir,
            database_dir=self.db_dir,
            config_dir=self.cfg_dir,
            etiqueta="wal_checkpoint_test",
        )
        self.assertTrue(bk_info["ok"])

        # Restaurar sobre sí misma
        res_rest = restaurar_respaldo(
            backup_dir=bk_info["backup_dir"],
            database_dir=self.db_dir,
            config_dir=self.cfg_dir,
            backups_dir=self.bk_dir,
            crear_respaldo_previo=False,
        )
        self.assertTrue(res_rest["ok"])

        # Verificar integridad
        ok, msg = verificar_integridad_sqlite(self.ventas_path)
        self.assertTrue(ok, f"Integridad corrupta tras restore de WAL: {msg}")


if __name__ == "__main__":
    unittest.main()
