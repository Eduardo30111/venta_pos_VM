import unittest
import sqlite3
import os
import shutil
from interface.usuarios_db import (
    hash_password,
    verificar_password,
    obtener_usuario_por_credenciales,
)


class TestSeguridadUsuariosDB(unittest.TestCase):
    def setUp(self):
        self.test_db = "database/test_usuarios_seg.db"
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        conn = sqlite3.connect(self.test_db)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                rol TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'Activo',
                ultimo_acceso DATETIME,
                fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
                fecha_modificacion DATETIME DEFAULT CURRENT_TIMESTAMP,
                comision_porcentaje REAL DEFAULT 0.0,
                comisiones_acumuladas REAL DEFAULT 0.0
            )
        """)
        # Insert 1 bcrypt user, 1 legacy sha256 user, 1 legacy plaintext user
        pwd_bcrypt = hash_password("secreto_bcrypt")
        import hashlib
        pwd_sha256 = hashlib.sha256("secreto_sha".encode()).hexdigest()
        pwd_plano = "secreto_plano"

        cur.execute("INSERT INTO usuarios (usuario, password, rol, estado) VALUES (?, ?, 'Admin', 'Activo')", ("u_bcrypt", pwd_bcrypt))
        cur.execute("INSERT INTO usuarios (usuario, password, rol, estado) VALUES (?, ?, 'Cajero', 'Activo')", ("u_sha", pwd_sha256))
        cur.execute("INSERT INTO usuarios (usuario, password, rol, estado) VALUES (?, ?, 'Operario', 'Activo')", ("u_plano", pwd_plano))
        conn.commit()
        conn.close()

    def tearDown(self):
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def test_verificacion_y_rehash_automatico(self):
        import interface.usuarios_db as udb
        orig_path = udb.DATABASE_PATH
        udb.DATABASE_PATH = self.test_db
        try:
            # 1. Login bcrypt
            res1 = obtener_usuario_por_credenciales("u_bcrypt", "secreto_bcrypt")
            self.assertIsNotNone(res1)
            self.assertEqual(res1["usuario"], "u_bcrypt")

            # 2. Login sha256 -> verifica y rehashea a bcrypt
            res2 = obtener_usuario_por_credenciales("u_sha", "secreto_sha")
            self.assertIsNotNone(res2)
            self.assertEqual(res2["usuario"], "u_sha")
            # Comprobar que en base de datos ahora es bcrypt
            conn = sqlite3.connect(self.test_db)
            cur = conn.cursor()
            cur.execute("SELECT password FROM usuarios WHERE usuario = 'u_sha'")
            p_nuevo = cur.fetchone()[0]
            self.assertTrue(p_nuevo.startswith("$2b$") or p_nuevo.startswith("$2a$"), f"No se rehasheó: {p_nuevo}")

            # 3. Login plano -> verifica y rehashea a bcrypt
            res3 = obtener_usuario_por_credenciales("u_plano", "secreto_plano")
            self.assertIsNotNone(res3)
            cur.execute("SELECT password FROM usuarios WHERE usuario = 'u_plano'")
            p_plano_nuevo = cur.fetchone()[0]
            self.assertTrue(p_plano_nuevo.startswith("$2b$") or p_plano_nuevo.startswith("$2a$"), f"No se rehasheó: {p_plano_nuevo}")
            conn.close()

            # 4. Password incorrecta falla limpiamente
            res4 = obtener_usuario_por_credenciales("u_bcrypt", "password_mala")
            self.assertIsNone(res4)
        finally:
            udb.DATABASE_PATH = orig_path


if __name__ == "__main__":
    unittest.main()
