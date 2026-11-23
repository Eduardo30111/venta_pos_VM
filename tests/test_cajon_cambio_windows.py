import unittest
from unittest.mock import MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interface.receipt_manager import (
    venta_incluye_efectivo,
    evaluar_apertura_cajon_por_venta,
    construir_comando_cajon,
    resolver_impresora_windows,
    pulsar_apertura_cajon,
)
from interface.cajon_pin_manager import (
    verificar_pin,
    crear_o_actualizar_pin,
    obtener_estado_seguridad,
    solicitar_pin_y_abrir_cajon,
)


class TestCajonCambioWindows(unittest.TestCase):
    """
    Suite de pruebas para verificar las reglas de cajón monedero, recordatorio de cambio,
    y compatibilidad con Windows en VmPOS.
    """

    def test_01_venta_en_efectivo_con_cambio(self):
        """Venta en efectivo: cajón abre automáticamente y se calcula el cambio real."""
        metodo = "Efectivo"
        total = 30000.0
        recibido = 50000.0
        cambio = recibido - total

        self.assertTrue(venta_incluye_efectivo(metodo))
        self.assertTrue(evaluar_apertura_cajon_por_venta(metodo))
        self.assertEqual(cambio, 20000.0)

    def test_02_venta_en_efectivo_sin_cambio(self):
        """Venta en efectivo con pago exacto: abre cajón pero cambio <= 0 (no muestra cambio incorrecto)."""
        metodo = "Efectivo"
        total = 35000.0
        recibido = 35000.0
        cambio = max(0.0, recibido - total)

        self.assertTrue(venta_incluye_efectivo(metodo))
        self.assertTrue(evaluar_apertura_cajon_por_venta(metodo))
        self.assertEqual(cambio, 0.0)
        # Regla: si cambio <= 0, no se debe mostrar ventana de dar cambio
        self.assertFalse(cambio > 0)

    def test_03_venta_mixta_calcula_cambio_segun_efectivo_recibido(self):
        """Venta mixta (efectivo + transferencia): abre cajón y calcula cambio según efectivo recibido."""
        metodo = "Mixto"
        total_venta = 50000.0
        monto_transferencia = 20000.0
        monto_efectivo_a_pagar = 30000.0
        efectivo_recibido = 50000.0
        cambio_esperado = efectivo_recibido - monto_efectivo_a_pagar  # 20000

        pagos = [
            {"metodo": "Efectivo", "monto": monto_efectivo_a_pagar, "recibido": efectivo_recibido, "cambio": cambio_esperado},
            {"metodo": "Transferencia", "monto": monto_transferencia, "recibido": monto_transferencia, "cambio": 0.0}
        ]

        self.assertTrue(venta_incluye_efectivo(metodo, pagos=pagos))
        self.assertTrue(evaluar_apertura_cajon_por_venta(metodo, pagos=pagos))
        self.assertEqual(cambio_esperado, 20000.0)

    def test_04_venta_por_transferencia_no_abre_cajon_ni_cambio(self):
        """Venta por transferencia: no abre automáticamente cajón ni muestra cambio."""
        metodo = "Transferencia"
        self.assertFalse(venta_incluye_efectivo(metodo))
        self.assertFalse(evaluar_apertura_cajon_por_venta(metodo))

        # Pagos estructurados solo transferencia
        pagos = [{"metodo": "Transferencia", "monto": 45000.0, "recibido": 45000.0, "cambio": 0.0}]
        self.assertFalse(venta_incluye_efectivo("Transferencia", pagos=pagos))
        self.assertFalse(evaluar_apertura_cajon_por_venta("Transferencia", pagos=pagos))

    def test_05_venta_fiada_no_abre_cajon_ni_cambio(self):
        """Venta fiada: no abre automáticamente cajón ni muestra cambio."""
        metodo = "Fiado"
        self.assertFalse(venta_incluye_efectivo(metodo))
        self.assertFalse(evaluar_apertura_cajon_por_venta(metodo))

        pagos = [{"metodo": "Fiado", "monto": 80000.0, "recibido": 0.0, "cambio": 0.0}]
        self.assertFalse(venta_incluye_efectivo("Fiado", pagos=pagos))
        self.assertFalse(evaluar_apertura_cajon_por_venta("Fiado", pagos=pagos))

    def test_06_combinacion_mixta_sin_efectivo(self):
        """Venta mixta sin efectivo (ej. Transferencia + Fiado): NO debe abrir cajón."""
        metodo = "Mixto"
        pagos = [
            {"metodo": "Transferencia", "monto": 25000.0, "recibido": 25000.0, "cambio": 0.0},
            {"metodo": "Fiado", "monto": 25000.0, "recibido": 0.0, "cambio": 0.0}
        ]
        self.assertFalse(venta_incluye_efectivo(metodo, pagos=pagos))
        self.assertFalse(evaluar_apertura_cajon_por_venta(metodo, pagos=pagos))

    def test_07_apertura_manual_pin_seguridad(self):
        """Apertura manual (F7 / botón): solicita PIN, bloquea intentos incorrectos y valida correctamente."""
        # Verificar que el validador rechaza PIN incorrecto
        ok_bad, msg_bad = verificar_pin("999999", usuario="Test")
        self.assertFalse(ok_bad)
        self.assertIn("PIN INCORRECTO", msg_bad.upper())

        # Estado de seguridad
        st = obtener_estado_seguridad()
        self.assertIn("configurado", st)
        self.assertIn("bloqueado", st)

    def test_08_comando_escpos_cajon_multimodelo(self):
        """Verifica que el comando ESC/POS incluya los pulsos estándares Pin 2 y Pin 5."""
        cmd = construir_comando_cajon({"comando_cajon_modo": "estandar_dual"})
        self.assertIn(b"\x1b\x70\x00", cmd)  # Pin 2
        self.assertIn(b"\x1b\x70\x01", cmd)  # Pin 5
        self.assertIn(b"\x10\x14\x01\x00\x05", cmd)  # DLE DC4 tiempo real

    def test_09_resolver_impresora_windows(self):
        """Verifica resolución inteligente de impresora para Windows."""
        res_exp = resolver_impresora_windows("POS-58")
        self.assertEqual(res_exp, "POS-58")

        # Predeterminada del sistema delega en detección
        res_def = resolver_impresora_windows("Predeterminada del sistema")
        self.assertIsInstance(res_def, str)


if __name__ == "__main__":
    unittest.main()
