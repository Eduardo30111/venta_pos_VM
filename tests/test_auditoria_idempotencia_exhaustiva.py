import unittest
import asyncio
import time
from httpx import AsyncClient, ASGITransport
from server.main import app
from server.database import SessionLocal


class TestAuditoriaIdempotenciaExhaustiva(unittest.TestCase):
    def setUp(self):
        self.transport = ASGITransport(app=app)

    def test_concurrencia_idempotencia_exhaustiva(self):
        async def _run():
            async with AsyncClient(transport=self.transport, base_url="http://test") as client:
                # Login admin
                l_res = await client.post("/auth/login", json={"usuario": "admin", "password": "123456", "terminal_id": 1})
                self.assertEqual(l_res.status_code, 200)
                token = l_res.json()["access_token"]
                headers = {"Authorization": f"Bearer {token}"}
                ts = int(time.time() * 1000)

                # 1. COMPRAS: 10 peticiones concurrentes simultaneas
                idem_cmp = f"idem-concurrente-cmp-{ts}"
                payload_cmp = {
                    "proveedor_id": 1,
                    "proveedor_nombre": "Proveedor Concurrente",
                    "ubicacion_destino": "BODEGA",
                    "doc_referencia": "FAC-CONC-01",
                    "idempotency_key": idem_cmp,
                    "items": [{
                        "codigo": "00001",
                        "nombre": "Cuaderno 100 Hojas Norma Pro",
                        "unidad_compra": "Paquete",
                        "factor_conversion": 10.0,
                        "cantidad_comprada": 2.0,
                        "costo_unidad_compra": 5000.0
                    }]
                }
                tareas_cmp = [client.post("/inventario/compras", json=payload_cmp, headers=headers) for _ in range(10)]
                respuestas_cmp = await asyncio.gather(*tareas_cmp)
                status_cmp = [r.status_code for r in respuestas_cmp]
                print(f"COMPRAS Concurrentes -> Statuses: {status_cmp}")
                self.assertTrue(all(s in (200, 201) for s in status_cmp), f"Errores en compras concurrentes: {status_cmp}")
                numeros_compra = {r.json()["numero_compra"] for r in respuestas_cmp}
                self.assertEqual(len(numeros_compra), 1, f"Se crearon múltiples números de compra: {numeros_compra}")

                # 2. GASTOS: 10 peticiones concurrentes simultáneas
                idem_gasto = f"idem-concurrente-gasto-{ts}"
                payload_gasto = {
                    "categoria": "Servicios",
                    "concepto": "Pago de energía eléctrica",
                    "valor": 45000.0,
                    "metodo_pago": "Efectivo",
                    "idempotency_key": idem_gasto
                }
                tareas_gasto = [client.post("/gastos", json=payload_gasto, headers=headers) for _ in range(10)]
                respuestas_gasto = await asyncio.gather(*tareas_gasto)
                status_gasto = [r.status_code for r in respuestas_gasto]
                print(f"GASTOS Concurrentes -> Statuses: {status_gasto}")
                self.assertTrue(all(s in (200, 201) for s in status_gasto))
                ids_gasto = {r.json()["id"] for r in respuestas_gasto}
                self.assertEqual(len(ids_gasto), 1, f"Se crearon múltiples gastos: {ids_gasto}")

                # 3. TRASLADOS: 10 peticiones concurrentes simultáneas
                idem_tras = f"idem-concurrente-tras-{ts}"
                payload_tras = {
                    "codigo_o_id": "00001",
                    "origen": "BODEGA",
                    "destino": "VITRINA",
                    "cantidad": 5.0,
                    "idempotency_key": idem_tras
                }
                tareas_tras = [client.post("/inventario/traslados", json=payload_tras, headers=headers) for _ in range(10)]
                respuestas_tras = await asyncio.gather(*tareas_tras)
                status_tras = [r.status_code for r in respuestas_tras]
                print(f"TRASLADOS Concurrentes -> Statuses: {status_tras}")
                self.assertTrue(all(s in (200, 201) for s in status_tras))
                nums_tras = {r.json()["numero_traslado"] for r in respuestas_tras}
                self.assertEqual(len(nums_tras), 1, f"Se crearon múltiples traslados: {nums_tras}")

                # 4. AJUSTES: 10 peticiones concurrentes simultáneas
                idem_aj = f"idem-concurrente-aj-{ts}"
                payload_aj = {
                    "codigo_o_id": "00001",
                    "ubicacion": "BODEGA",
                    "conteo_fisico": 600.0,
                    "idempotency_key": idem_aj
                }
                tareas_aj = [client.post("/inventario/ajustes", json=payload_aj, headers=headers) for _ in range(10)]
                respuestas_aj = await asyncio.gather(*tareas_aj)
                status_aj = [r.status_code for r in respuestas_aj]
                print(f"AJUSTES Concurrentes -> Statuses: {status_aj}")
                self.assertTrue(all(s in (200, 201) for s in status_aj))

                # 5. VENTAS: 10 peticiones concurrentes simultáneas
                idem_vta = f"idem-concurrente-vta-{ts}"
                payload_vta = {
                    "tipo": "Venta Normal",
                    "subtotal": 5800.0,
                    "total": 5800.0,
                    "idempotency_key": idem_vta,
                    "detalles": [{
                        "producto_id": 1,
                        "codigo_producto": "00001",
                        "nombre_producto": "Cuaderno 100 Hojas Norma Pro",
                        "cantidad": 1.0,
                        "precio_unitario": 5800.0,
                        "subtotal": 5800.0
                    }],
                    "pagos": [{
                        "metodo": "Efectivo",
                        "monto": 5800.0,
                        "recibido": 10000.0,
                        "cambio": 4200.0
                    }]
                }
                tareas_vta = [client.post("/ventas", json=payload_vta, headers=headers) for _ in range(10)]
                respuestas_vta = await asyncio.gather(*tareas_vta)
                status_vta = [r.status_code for r in respuestas_vta]
                print(f"VENTAS Concurrentes -> Statuses: {status_vta}")
                self.assertTrue(all(s in (200, 201) for s in status_vta))
                ids_vta = {r.json()["id"] for r in respuestas_vta}
                self.assertEqual(len(ids_vta), 1, f"Se crearon múltiples ventas: {ids_vta}")

                # 6. ANULACION: 10 peticiones concurrentes para anular la venta recién creada
                vta_id = list(ids_vta)[0]
                tareas_anular = [client.post(f"/ventas/{vta_id}/anular", json={"motivo": "Prueba de anulación concurrente"}, headers=headers) for _ in range(10)]
                respuestas_anular = await asyncio.gather(*tareas_anular)
                status_anular = [r.status_code for r in respuestas_anular]
                print(f"ANULACIONES Concurrentes -> Statuses: {status_anular}")
                # Exactamente una debe ser exitosa (200) y las otras 9 deben ser 400 (ya anulada) sin ningún 500
                exitos_anular = status_anular.count(200)
                rechazos_anular = status_anular.count(400)
                self.assertEqual(exitos_anular, 1, f"Debió anularse exactamente 1 vez pero hubo {exitos_anular} éxitos")
                self.assertEqual(rechazos_anular, 9, f"Debieron rechazarse 9 peticiones pero fueron {rechazos_anular}")
                self.assertNotIn(500, status_anular, "Aparecieron errores 500 en anulación concurrente")

                # 7. CAJA: 10 peticiones concurrentes simultáneas de movimiento de caja
                idem_caja = f"idem-concurrente-caja-{ts}"
                payload_caja = {
                    "tipo": "INGRESO_EXTRAORDINARIO",
                    "monto": 25000.0,
                    "descripcion": "Ingreso extra para prueba concurrente",
                    "idempotency_key": idem_caja
                }
                tareas_caja = [client.post("/caja/movimientos", json=payload_caja, headers=headers) for _ in range(10)]
                respuestas_caja = await asyncio.gather(*tareas_caja)
                status_caja = [r.status_code for r in respuestas_caja]
                print(f"CAJA Concurrentes -> Statuses: {status_caja}")
                self.assertTrue(all(s in (200, 201) for s in status_caja))
                ids_caja = {r.json()["id"] for r in respuestas_caja}
                self.assertEqual(len(ids_caja), 1, f"Se crearon múltiples movimientos de caja: {ids_caja}")

                # 8. LIQUIDACION PROVEEDOR: 10 peticiones concurrentes simultáneas
                idem_liq_prov = f"idem-concurrente-liqprov-{ts}"
                payload_liq_prov = {
                    "monto": 5.0,
                    "metodo_pago": "Efectivo",
                    "proveedor_nombre": "Omara Sierra",
                    "idempotency_key": idem_liq_prov
                }
                tareas_liq_prov = [client.post("/proveedores/1/liquidar", json=payload_liq_prov, headers=headers) for _ in range(10)]
                respuestas_liq_prov = await asyncio.gather(*tareas_liq_prov)
                status_liq_prov = [r.status_code for r in respuestas_liq_prov]
                print(f"LIQ PROV Concurrentes -> Statuses: {status_liq_prov}")
                self.assertTrue(all(s in (200, 201) for s in status_liq_prov))
                ids_liq_prov = {r.json()["liquidacion_id"] for r in respuestas_liq_prov}
                self.assertEqual(len(ids_liq_prov), 1, f"Se crearon múltiples liquidaciones de proveedor: {ids_liq_prov}")

                # 9. LIQUIDACION NOMINA: 10 peticiones concurrentes simultáneas
                idem_nom = f"idem-concurrente-nom-{ts}"
                payload_nom = {
                    "usuario_id": 1,
                    "idempotency_key": idem_nom,
                    "observaciones": "Liquidación de prueba concurrente"
                }
                tareas_nom = [client.post("/nomina/liquidaciones", json=payload_nom, headers=headers) for _ in range(10)]
                respuestas_nom = await asyncio.gather(*tareas_nom)
                status_nom = [r.status_code for r in respuestas_nom]
                print(f"NOMINA Concurrentes -> Statuses: {status_nom}")
                self.assertTrue(all(s in (200, 201) for s in status_nom))
                ids_nom = {r.json()["id"] for r in respuestas_nom}
                self.assertEqual(len(ids_nom), 1, f"Se crearon múltiples liquidaciones de nómina: {ids_nom}")

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
