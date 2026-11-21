#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Suite de Pruebas Unitarias y de Integración para el Motor de Respaldo y Restauración Verificada:
- Creación de respaldo en caliente (SQLite Online Backup API + manifest.json).
- Verificación exhaustiva de integridad (SHA-256 + PRAGMA integrity_check).
- Detección estricta de alteraciones, archivos truncados o corruptos.
- Restauración atómica con respaldo preventivo de seguridad.
"""

import unittest
import os
import shutil
import tempfile
import sqlite3
import json

from interface.backup_manager import (
    crear_respaldo_completo,
    verificar_respaldo,
    restaurar_respaldo,
    verificar_integridad_sqlite,
    calcular_sha256,
)


class TestBackupYRestauracion(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp(prefix="test_backup_mgr_")
        self.db_dir = os.path.join(self.temp_root, "database")
        self.cfg_dir = os.path.join(self.temp_root, "config")
        self.bk_dir = os.path.join(self.temp_root, "backups")
        os.makedirs(self.db_dir, exist_ok=True)
        os.makedirs(self.cfg_dir, exist_ok=True)
        os.makedirs(self.bk_dir, exist_ok=True)

        # Crear base de datos simulada ventas.db
        self.ventas_path = os.path.join(self.db_dir, "ventas.db")
        conn_v = sqlite3.connect(self.ventas_path)
        cur_v = conn_v.cursor()
        cur_v.execute("CREATE TABLE ventas (id INTEGER PRIMARY KEY, total REAL, fecha TEXT)")
        cur_v.execute("INSERT INTO ventas (id, total, fecha) VALUES (1, 150000.0, '2026-11-21')")
        cur_v.execute("INSERT INTO ventas (id, total, fecha) VALUES (2, 45000.0, '2026-11-21')")
        conn_v.commit()
        conn_v.close()

        # Crear base de datos simulada usuarios.db
        self.usuarios_path = os.path.join(self.db_dir, "usuarios.db")
        conn_u = sqlite3.connect(self.usuarios_path)
        cur_u = conn_u.cursor()
        cur_u.execute("CREATE TABLE usuarios (id INTEGER PRIMARY KEY, usuario TEXT, rol TEXT)")
        cur_u.execute("INSERT INTO usuarios (id, usuario, rol) VALUES (1, 'admin', 'Administrador')")
        conn_u.commit()
        conn_u.close()

        # Crear archivo de configuración simulado
        self.cfg_path = os.path.join(self.cfg_dir, "business_config.json")
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            json.dump({"nombre_negocio": "VmPOS Papelería Modelo", "nit": "900999888-1"}, f)

    def tearDown(self):
        if os.path.exists(self.temp_root):
            shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_01_crear_y_verificar_respaldo_completo(self):
        """Valida que crear_respaldo_completo genere el manifiesto y hashes válidos."""
        res = crear_respaldo_completo(
            destino_raiz=self.bk_dir,
            database_dir=self.db_dir,
            config_dir=self.cfg_dir,
            etiqueta="test_ok"
        )
        self.assertTrue(res["ok"])
        ruta_bk = res["backup_dir"]
        self.assertTrue(os.path.isdir(ruta_bk))
        self.assertTrue(os.path.isfile(os.path.join(ruta_bk, "manifest.json")))
        self.assertIn("ventas.db", res["databases"])
        self.assertIn("usuarios.db", res["databases"])
        self.assertIn("business_config.json", res["configs"])

        # Verificar integridad del respaldo creado
        ok, msg, manifest = verificar_respaldo(ruta_bk)
        self.assertTrue(ok, f"Fallo al verificar respaldo: {msg}")
        self.assertIn("ventas.db", manifest["databases"])
        self.assertEqual(manifest["databases"]["ventas.db"]["tablas"]["ventas"], 2)

    def test_02_deteccion_respaldo_alterado_o_corrupto(self):
        """Valida que verificar_respaldo detecte manipulación de archivos o corrupción."""
        res = crear_respaldo_completo(
            destino_raiz=self.bk_dir,
            database_dir=self.db_dir,
            config_dir=self.cfg_dir,
            etiqueta="test_alterado"
        )
        ruta_bk = res["backup_dir"]

        # 1. Modificar un byte de ventas.db en el respaldo para simular corrupción
        bk_ventas = os.path.join(ruta_bk, "database", "ventas.db")
        with open(bk_ventas, "r+b") as f:
            f.seek(50)
            f.write(b"\xFF\xFF")

        ok, msg, _ = verificar_respaldo(ruta_bk)
        self.assertFalse(ok)
        self.assertIn("Checksum SHA-256 inválido", msg)

        # 2. Restauración debe rechazar un respaldo corrupto
        with self.assertRaises(ValueError) as ctx:
            restaurar_respaldo(
                backup_dir=ruta_bk,
                database_dir=self.db_dir,
                config_dir=self.cfg_dir,
                backups_dir=self.bk_dir
            )
        self.assertIn("Restauración abortada", str(ctx.exception))

    def test_03_restaurar_con_respaldo_preventivo(self):
        """Valida que la restauración tome un respaldo preventivo y restituya los datos originales."""
        # 1. Crear respaldo inicial (Estado 1: 2 ventas)
        res_bk = crear_respaldo_completo(
            destino_raiz=self.bk_dir,
            database_dir=self.db_dir,
            config_dir=self.cfg_dir,
            etiqueta="punto_restauracion"
        )
        ruta_bk_original = res_bk["backup_dir"]

        # 2. Alterar la base activa (Estado 2: insertar 5 ventas más y alterar configuración)
        conn = sqlite3.connect(self.ventas_path)
        for i in range(3, 8):
            conn.execute("INSERT INTO ventas (id, total, fecha) VALUES (?, 10000.0, '2026-11-21')", (i,))
        conn.commit()
        conn.close()

        # Verificar que la base activa ahora tiene 7 ventas
        conn_check = sqlite3.connect(self.ventas_path)
        count_actual = conn_check.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
        conn_check.close()
        self.assertEqual(count_actual, 7)

        # 3. Restaurar respaldo original con crear_respaldo_previo=True
        res_rest = restaurar_respaldo(
            backup_dir=ruta_bk_original,
            database_dir=self.db_dir,
            config_dir=self.cfg_dir,
            backups_dir=self.bk_dir,
            crear_respaldo_previo=True
        )
        self.assertTrue(res_rest["ok"])
        self.assertIsNotNone(res_rest["pre_restore_backup"])
        self.assertTrue(os.path.isdir(res_rest["pre_restore_backup"]))

        # 4. Verificar que la base activa restaurada volvió exactamente a 2 ventas
        conn_rest = sqlite3.connect(self.ventas_path)
        count_rest = conn_rest.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
        conn_rest.close()
        self.assertEqual(count_rest, 2)

        # 5. Comprobar que PRAGMA integrity_check sobre la base restaurada sea OK
        ok_int, msg_int = verificar_integridad_sqlite(self.ventas_path)
        self.assertTrue(ok_int, f"Integridad corrupta tras restauración: {msg_int}")


if __name__ == "__main__":
    unittest.main()
