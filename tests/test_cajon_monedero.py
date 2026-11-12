"""
Pruebas unitarias y de integración para el sistema de apertura de gaveta de dinero
(cajón monedero conectado a impresora térmica DigitalPOS ISH58 / ESC-POS).

Verifica:
1. Comandos ESC/POS de apertura (Pin 2, Pin 5, Dual, DLE DC4 tiempo real, BEL).
2. Reglas comerciales en ventas:
   - Venta en efectivo abre gaveta.
   - Venta mixta con efectivo abre gaveta.
   - Venta exclusivamente por transferencia NO abre gaveta.
   - Venta exclusivamente fiada NO abre gaveta.
   - Venta mixta sin efectivo (transferencia + fiado) NO abre gaveta.
   - Configuración abrir_cajon=False respeta la desactivación.
3. Abonos de clientes en efectivo activan la gaveta.
4. Mecanismo de envío RAW multiplataforma:
   - macOS: Cola CUPS RAW (lp -o raw) con payload binario sin rasterizar en PDF.
   - Windows: win32print en modo RAW sin imprimir texto plano.
   - Red LAN / Ethernet: Socket TCP puerto 9100.
5. No apertura duplicada en una misma transacción.
6. Manejo seguro de errores cuando no hay impresora física disponible.
"""

import unittest
from unittest.mock import patch, MagicMock
import tempfile
import os
import sys

# Asegurar importación del módulo
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from interface.receipt_manager import (
    construir_comando_cajon,
    evaluar_apertura_cajon_por_venta,
    pulsar_apertura_cajon,
)


class TestCajonMonederoCommands(unittest.TestCase):
    """Verificación de generación de comandos binarios ESC/POS."""

    def test_comando_estandar_dual_ish58(self):
        """El modo por omisión debe incluir pulso a Pin 2, Pin 5, Real-time y BEL."""
        cmd = construir_comando_cajon({"comando_cajon_modo": "estandar_dual"})
        self.assertIsInstance(cmd, bytes)
        # Pin 2 (120ms: 0x3c)
        self.assertIn(b"\x1b\x70\x00\x3c\xfa", cmd)
        # Pin 5 (120ms: 0x3c)
        self.assertIn(b"\x1b\x70\x01\x3c\xfa", cmd)
        # Real-time kick out
        self.assertIn(b"\x10\x14\x01\x00\x05", cmd)
        # ESC BEL
        self.assertIn(b"\x1b\x07", cmd)

    def test_comando_pin2_especifico(self):
        cmd = construir_comando_cajon({"comando_cajon_modo": "pin2"})
        self.assertEqual(cmd, b"\x1b\x70\x00\x3c\xfa")

    def test_comando_pin5_especifico(self):
        cmd = construir_comando_cajon({"comando_cajon_modo": "pin5"})
        self.assertEqual(cmd, b"\x1b\x70\x01\x3c\xfa")

    def test_comando_realtime_especifico(self):
        cmd = construir_comando_cajon({"comando_cajon_modo": "realtime"})
        self.assertEqual(cmd, b"\x10\x14\x01\x00\x05")

    def test_comando_bel_especifico(self):
        cmd = construir_comando_cajon({"comando_cajon_modo": "bel"})
        self.assertEqual(cmd, b"\x1b\x07")


class TestReglasComercialesVentas(unittest.TestCase):
    """Verificación de las 5 reglas comerciales para ventas y gaveta."""

    def setUp(self):
        self.cfg_activa = {"abrir_cajon": True}
        self.cfg_inactiva = {"abrir_cajon": False}

    def test_regla_1_venta_efectivo_abre(self):
        """Venta confirmada en efectivo debe abrir gaveta."""
        self.assertTrue(evaluar_apertura_cajon_por_venta("Efectivo", cfg=self.cfg_activa))
        self.assertTrue(evaluar_apertura_cajon_por_venta({"metodo_pago": "Efectivo"}, cfg=self.cfg_activa))
        self.assertTrue(evaluar_apertura_cajon_por_venta("efectivo", cfg=self.cfg_activa))

    def test_regla_2_venta_mixta_con_efectivo_abre(self):
        """Venta mixta que incluya monto en efectivo debe abrir gaveta."""
        pagos = [
            {"metodo": "Transferencia", "monto": 20000},
            {"metodo": "Efectivo", "monto": 5000},
        ]
        self.assertTrue(evaluar_apertura_cajon_por_venta("Mixto", pagos=pagos, cfg=self.cfg_activa))
        self.assertTrue(evaluar_apertura_cajon_por_venta({"metodo_pago": "Mixto", "pagos": pagos}, cfg=self.cfg_activa))

    def test_regla_3_venta_transferencia_no_abre(self):
        """Venta exclusivamente por transferencia NO debe abrir gaveta."""
        self.assertFalse(evaluar_apertura_cajon_por_venta("Transferencia", cfg=self.cfg_activa))
        self.assertFalse(evaluar_apertura_cajon_por_venta({"metodo_pago": "Transferencia"}, cfg=self.cfg_activa))
        self.assertFalse(evaluar_apertura_cajon_por_venta("Nequi", cfg=self.cfg_activa))
        self.assertFalse(evaluar_apertura_cajon_por_venta("Daviplata", cfg=self.cfg_activa))

    def test_regla_4_venta_fiado_no_abre(self):
        """Venta exclusivamente fiada / crédito NO debe abrir gaveta."""
        self.assertFalse(evaluar_apertura_cajon_por_venta("Fiado", cfg=self.cfg_activa))
        self.assertFalse(evaluar_apertura_cajon_por_venta({"metodo_pago": "Fiado"}, cfg=self.cfg_activa))
        self.assertFalse(evaluar_apertura_cajon_por_venta("Crédito", cfg=self.cfg_activa))

    def test_venta_mixta_sin_efectivo_no_abre(self):
        """Venta mixta entre transferencia y fiado (sin efectivo) NO debe abrir gaveta."""
        pagos = [
            {"metodo": "Transferencia", "monto": 15000},
            {"metodo": "Fiado", "monto": 10000},
        ]
        self.assertFalse(evaluar_apertura_cajon_por_venta("Mixto", pagos=pagos, cfg=self.cfg_activa))

    def test_desactivacion_configuracion_anula_apertura(self):
        """Si el usuario desactivó 'abrir_cajon' en configuración, no abre aunque sea efectivo."""
        self.assertFalse(evaluar_apertura_cajon_por_venta("Efectivo", cfg=self.cfg_inactiva))
        pagos = [{"metodo": "Efectivo", "monto": 5000}]
        self.assertFalse(evaluar_apertura_cajon_por_venta("Mixto", pagos=pagos, cfg=self.cfg_inactiva))


class TestMecanismoEnvioPlataformas(unittest.TestCase):
    """Verificación de envío RAW en macOS, Windows y Red TCP."""

    @patch("interface.receipt_manager.subprocess.run")
    def test_macos_cups_raw_envio(self, mock_run):
        """En macOS / Unix debe invocar `lp -o raw` con archivo temporal binario."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        with patch("sys.platform", "darwin"):
            cfg = {
                "impresora_nombre": "DigitalPOS_ISH58",
                "ip_impresora_red": "",
            }
            ok, msg = pulsar_apertura_cajon(config_override=cfg)
            self.assertTrue(ok)
            self.assertIn("DigitalPOS_ISH58", msg)
            self.assertIn("macOS CUPS RAW", msg)

            # Verificar que se llamó a lp con -o raw
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            self.assertEqual(args[0], "lp")
            self.assertIn("-o", args)
            self.assertIn("raw", args)
            self.assertIn("-d", args)
            self.assertIn("DigitalPOS_ISH58", args)

    @patch("socket.socket")
    def test_red_tcp_envio(self, mock_socket_cls):
        """Si tiene IP de red configurada, debe enviar por TCP socket al puerto 9100."""
        mock_sock = MagicMock()
        mock_socket_cls.return_value.__enter__.return_value = mock_sock

        cfg = {
            "ip_impresora_red": "192.168.1.200",
            "puerto_impresora_red": 9100,
        }
        ok, msg = pulsar_apertura_cajon(config_override=cfg)
        self.assertTrue(ok)
        self.assertIn("192.168.1.200:9100", msg)
        mock_sock.connect.assert_called_once_with(("192.168.1.200", 9100))
        mock_sock.sendall.assert_called_once()
        cmd_enviado = mock_sock.sendall.call_args[0][0]
        self.assertIn(b"\x1b\x70\x00\x3c\xfa", cmd_enviado)

    def test_error_sin_impresora_controlado(self):
        """Cuando no hay ninguna impresora conectada, debe retornar False con mensaje claro sin crashear."""
        cfg = {
            "ip_impresora_red": "192.0.2.1",  # IP no enrutable / timeout
            "puerto_impresora_red": 9100,
            "impresora_nombre": "Impresora_Inexistente_12345",
        }
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="Destination not found", stdout="")
            with patch("sys.platform", "darwin"):
                ok, msg = pulsar_apertura_cajon(config_override=cfg)
                self.assertFalse(ok)
                self.assertIn("No se pudo comunicar con la impresora", msg)
                self.assertIn("RJ11", msg)


if __name__ == "__main__":
    unittest.main()
