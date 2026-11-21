import unittest
import asyncio
import hashlib
import hmac
import os
from httpx import AsyncClient, ASGITransport
from server.main import app
from server.config import settings
from server.database import SessionLocal
from server.models.usuario import Usuario
from server.middleware.auth import hash_password, verify_and_rehash_password


class TestSeguridadRehash(unittest.TestCase):
    def test_secret_key_segura_y_persistente(self):
        # 1. SECRET_KEY no debe ser la insegura por defecto "supersecretkey"
        self.assertNotEqual(settings.SECRET_KEY, "supersecretkey")
        self.assertGreaterEqual(len(settings.SECRET_KEY), 32)

    def test_rehash_transparente_de_contraseñas(self):
        # 2. Plaintext se valida y genera nuevo hash bcrypt
        pwd = "PruebaSeguraPassword123"
        valido, rehash, nuevo_hash = verify_and_rehash_password(pwd, pwd)
        self.assertTrue(valido)
        self.assertTrue(rehash)
        self.assertTrue(nuevo_hash.startswith("$2b$"))

        # 3. SHA-256 legacy se valida y genera nuevo hash bcrypt
        sha_legacy = hashlib.sha256(pwd.encode("utf-8")).hexdigest()
        valido_sha, rehash_sha, nuevo_hash_sha = verify_and_rehash_password(pwd, sha_legacy)
        self.assertTrue(valido_sha)
        self.assertTrue(rehash_sha)
        self.assertTrue(nuevo_hash_sha.startswith("$2b$"))

        # 4. Hash bcrypt ya migrado no necesita rehash
        valido_bc, rehash_bc, _ = verify_and_rehash_password(pwd, nuevo_hash)
        self.assertTrue(valido_bc)
        self.assertFalse(rehash_bc)

        # 5. Contraseña incorrecta nunca es válida
        valido_bad, rehash_bad, _ = verify_and_rehash_password("PasswordErronea", nuevo_hash)
        self.assertFalse(valido_bad)
        self.assertFalse(rehash_bad)


if __name__ == "__main__":
    unittest.main()
