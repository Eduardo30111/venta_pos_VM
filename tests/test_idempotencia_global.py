import unittest
import asyncio
import os
from httpx import AsyncClient, ASGITransport
from server.main import app
from tests.test_helpers import init_isolated_test_db, cleanup_isolated_test_db


class TestIdempotenciaGlobal(unittest.TestCase):
    test_db = f"/tmp/test_idempotencia_global_{os.getpid()}.db"

    @classmethod
    def setUpClass(cls):
        asyncio.run(init_isolated_test_db(cls.test_db))
        cls.transport = ASGITransport(app=app)

    @classmethod
    def tearDownClass(cls):
        asyncio.run(cleanup_isolated_test_db(cls.test_db))

    def test_idempotencia_compras_y_ajustes(self):
        async def _test():
            async with AsyncClient(transport=self.transport, base_url="http://test") as client:
                # 1. Login
                login_res = await client.post(
                    "/auth/login",
                    json={"usuario": "admin", "password": "123456", "terminal_id": 1}
                )
                self.assertEqual(login_res.status_code, 200, f"Login failed: {login_res.text}")
                token = login_res.json()["access_token"]
                headers = {"Authorization": f"Bearer {token}"}

                # 2. Test Idempotencia en Compras (10 llamadas idénticas con misma idempotency_key)
                idem_key_compra = "test-compra-idem-99999"
                compra_payload = {
                    "proveedor_id": 1,
                    "proveedor_nombre": "Proveedor Test Idempotencia",
                    "ubicacion_destino": "BODEGA",
                    "doc_referencia": "FAC-TEST-IDEM-01",
                    "idempotency_key": idem_key_compra,
                    "items": [{
                        "codigo": "00001",
                        "nombre": "Cuaderno 100 Hojas Norma Pro",
                        "unidad_compra": "Paquete",
                        "factor_conversion": 500.0,
                        "cantidad_comprada": 1.0,
                        "costo_unidad_compra": 15000.0
                    }]
                }

                # Primera llamada: debe registrar la compra con HTTP 200/201
                r1 = await client.post("/inventario/compras", json=compra_payload, headers=headers)
                self.assertIn(r1.status_code, (200, 201), f"Primera compra falló: {r1.text}")
                d1 = r1.json()
                num_compra = d1["numero_compra"]

                # 9 llamadas consecutivas con la misma idempotency_key: deben retornar repetido sin error 500
                for i in range(2, 11):
                    r_rep = await client.post("/inventario/compras", json=compra_payload, headers=headers)
                    self.assertEqual(r_rep.status_code, 200, f"Reintento {i} de compra falló: {r_rep.text}")
                    d_rep = r_rep.json()
                    self.assertEqual(d_rep["numero_compra"], num_compra)
                    self.assertTrue(d_rep.get("repetido", False) or d_rep["compra_id"] == d1["compra_id"])

                # 3. Test Idempotencia en Ajustes de Inventario
                idem_key_ajuste = "test-ajuste-idem-88888"
                ajuste_payload = {
                    "codigo_o_id": "00001",
                    "ubicacion": "BODEGA",
                    "conteo_fisico": 1500.0,
                    "motivo": "Ajuste físico de verificación",
                    "idempotency_key": idem_key_ajuste
                }

                r_aj1 = await client.post("/inventario/ajustes", json=ajuste_payload, headers=headers)
                self.assertIn(r_aj1.status_code, (200, 201), f"Primer ajuste falló: {r_aj1.text}")
                d_aj1 = r_aj1.json()

                # Reintentos con la misma clave
                for j in range(2, 6):
                    r_aj_rep = await client.post("/inventario/ajustes", json=ajuste_payload, headers=headers)
                    self.assertEqual(r_aj_rep.status_code, 200, f"Reintento {j} de ajuste falló: {r_aj_rep.text}")
                    d_aj_rep = r_aj_rep.json()
                    self.assertTrue(d_aj_rep.get("repetido", False) or "mensaje" in d_aj_rep or d_aj_rep.get("stock_nuevo") == 1500.0)

        asyncio.run(_test())


if __name__ == "__main__":
    unittest.main()
