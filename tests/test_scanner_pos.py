"""
Test suite for POS USB Barcode Scanner functionality in interface/ventas_menu.py
Validates:
1. Continuous scanning without clicking the search box
2. Same-product quantity incrementing and total calculations
3. Multi-product consecutive scanning
4. Non-existent product barcode error handling
5. Preservation of customer document field (entry_doc) during scans
6. Post-edit scanning focus recovery
7. Payment dialog protection against scanner burst keystrokes
8. Scanners without Return key suffix (85ms timeout)
9. Hardware bounce suppression (< 220ms duplicate reads)
"""

import sys
import os
import time
import unittest
import tkinter as tk
from unittest.mock import MagicMock, patch

# Add workspace root to sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import interface.ventas_menu as vm_module
from interface.ventas_menu import App


class FakeKeyEvent:
    def __init__(self, keysym, char=""):
        self.keysym = keysym
        self.char = char


class TestScannerPOS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()
        # Mock messageboxes globally to prevent modal blocking during unit tests
        cls.patch_warn = patch.object(vm_module.messagebox, "showwarning", MagicMock())
        cls.patch_err = patch.object(vm_module.messagebox, "showerror", MagicMock())
        cls.patch_info = patch.object(vm_module.messagebox, "showinfo", MagicMock())
        cls.mock_warn = cls.patch_warn.start()
        cls.mock_err = cls.patch_err.start()
        cls.mock_info = cls.patch_info.start()

    @classmethod
    def tearDownClass(cls):
        cls.patch_warn.stop()
        cls.patch_err.stop()
        cls.patch_info.stop()
        try:
            cls.root.destroy()
        except Exception:
            pass

    def setUp(self):
        self.mock_warn.reset_mock()
        self.mock_err.reset_mock()
        self.mock_info.reset_mock()

        self.win = tk.Toplevel(self.root)
        self.win.withdraw()

        # Create test instance with mock session/api
        with patch.object(App, "actualizar_indicadores_empleado_pos", lambda self: None), \
             patch.object(App, "actualizar_estado_caja", lambda self: None), \
             patch.object(App, "actualizar_ventas_operarios", lambda self: None), \
             patch.object(App, "actualizar_hora", lambda self: None), \
             patch.object(App, "conectar_impresora_async", lambda self: None), \
             patch("interface.inventario_manager.obtener_articulo_por_codigo", return_value=None):
            self.app = App(self.win, user_id="1", rol="Administrador", usuario_nombre="Admin Test")
            self.app.puede_procesar_venta = True
            self.app.caja_abierta = True

        # Populate sample inventory catalog
        # Format: (cod, nom, stock_vitrina, precio, tipo, prov_id, p_id, costo, es_var, stock_bodega, cod_barras)
        self.app.productos_inventario = [
            ("00001", "Cuaderno 100H", 20, 3500.0, "Fisico", 1, 101, 2000.0, False, 50, "7701234567890"),
            ("00002", "Lapicero Negro", 50, 1200.0, "Fisico", 1, 102, 600.0, False, 100, "7709876543210"),
            ("00003", "Borrador de Nata", 15, 800.0, "Fisico", 1, 103, 300.0, False, 30, "7705555555555"),
            ("00004", "Fotocopia B/N", 9999, 200.0, "Servicio", None, 104, 50.0, False, 0, "S00004"),
            ("00005", "Producto Agotado", 0, 5000.0, "Fisico", 1, 105, 3000.0, False, 0, "7700000000000"),
            ("00006", "Solo Bodega", 0, 8000.0, "Fisico", 1, 106, 5000.0, False, 25, "7701111111111"),
        ]

        # Reset cart and inputs
        self.app.limpiar_formulario()

    def tearDown(self):
        try:
            self.win.destroy()
        except Exception:
            pass

    def simulate_scanner_burst(self, barcode, send_enter=True, inter_char_delay=0.005):
        """Simulates rapid keyboard wedge transmission of a barcode scanner."""
        self.app._scanner_last_time = time.time() - 1.0  # Gap before burst
        for char in barcode:
            ev = FakeKeyEvent(keysym=char, char=char)
            self.app._on_global_key_event(ev)
            time.sleep(inter_char_delay)

        if send_enter:
            ev_enter = FakeKeyEvent(keysym="Return", char="\r")
            res = self.app._on_global_key_event(ev_enter)
            return res
        return None

    # Test 1: Abrir ventas y escanear un producto: debe agregarse automáticamente
    def test_01_escanear_un_producto_automatico(self):
        """Prueba 1: Escanear un código de barras agrega el producto al carrito automáticamente."""
        self.app.entry_codigo.focus_set()
        self.app.codigo_entrada.set("7701234567890")
        
        self.simulate_scanner_burst("7701234567890", send_enter=True)
        self.win.update()

        items = self.app.tabla.get_children()
        self.assertEqual(len(items), 1, "Debe haber exactamente 1 producto en el carrito.")
        
        row_vals = self.app.tabla.item(items[0])["values"]
        self.assertEqual(row_vals[0], "Cuaderno 100H")
        self.assertEqual(int(row_vals[2]), 1, "La cantidad inicial debe ser 1.")
        self.assertEqual(self.app.total_general.get(), 3500.0, "El total debe ser 3500.")
        self.assertEqual(self.app.codigo_entrada.get(), "", "El campo de código debe limpiarse tras el escaneo.")

    # Test 2: Escanear el mismo producto tres veces: debe quedar con cantidad 3
    def test_02_escanear_mismo_producto_tres_veces(self):
        """Prueba 2: Escanear el mismo producto 3 veces incrementa la cantidad a 3 y actualiza el total."""
        # Scan 1
        self.app.entry_codigo.focus_set()
        self.app.codigo_entrada.set("7701234567890")
        self.simulate_scanner_burst("7701234567890", send_enter=True)
        time.sleep(0.25)  # Wait past hardware debounce window (220ms)

        # Scan 2
        self.app.codigo_entrada.set("7701234567890")
        self.simulate_scanner_burst("7701234567890", send_enter=True)
        time.sleep(0.25)

        # Scan 3
        self.app.codigo_entrada.set("7701234567890")
        self.simulate_scanner_burst("7701234567890", send_enter=True)
        self.win.update()

        items = self.app.tabla.get_children()
        self.assertEqual(len(items), 1, "No deben crearse filas duplicadas para el mismo producto.")
        
        row_vals = self.app.tabla.item(items[0])["values"]
        self.assertEqual(int(row_vals[2]), 3, "La cantidad debe ser 3.")
        self.assertEqual(self.app.total_general.get(), 10500.0, "El total debe ser 3 * 3500 = 10,500 COP.")

    # Test 3: Escanear tres productos diferentes consecutivamente: deben aparecer los tres
    def test_03_escanear_tres_productos_diferentes_consecutivos(self):
        """Prueba 3: Escanear 3 productos distintos sin hacer clic intermedio agrega los 3 al carrito."""
        barcodes = ["7701234567890", "7709876543210", "7705555555555"]
        expected_names = ["Cuaderno 100H", "Lapicero Negro", "Borrador de Nata"]
        expected_total = 3500.0 + 1200.0 + 800.0  # 5,500 COP

        for bc in barcodes:
            self.app.codigo_entrada.set(bc)
            self.simulate_scanner_burst(bc, send_enter=True)
            time.sleep(0.05)

        self.win.update()
        items = self.app.tabla.get_children()
        self.assertEqual(len(items), 3, "Deben haber 3 productos distintos en el carrito.")

        cart_names = [self.app.tabla.item(i)["values"][0] for i in items]
        self.assertEqual(cart_names, expected_names)
        self.assertEqual(self.app.total_general.get(), expected_total)

    # Test 4: Escanear un código inexistente: debe mostrar aviso y no agregar producto incorrecto
    def test_04_escanear_codigo_inexistente(self):
        """Prueba 4: Un código de barras no registrado muestra aviso y no altera el carrito."""
        self.app.codigo_entrada.set("9999999999999")
        self.simulate_scanner_burst("9999999999999", send_enter=True)
        self.win.update()

        self.mock_warn.assert_called_once()
        args, kwargs = self.mock_warn.call_args
        self.assertIn("no registrado", args[0].lower())
        self.assertEqual(len(self.app.tabla.get_children()), 0, "El carrito debe permanecer vacío.")
        self.assertEqual(self.app.codigo_entrada.get(), "", "El campo debe quedar limpio.")

    # Test 5: Escanear después de seleccionar un cliente / con texto en entry_doc
    def test_05_escanear_con_texto_en_documento_cliente(self):
        """Prueba 5: Escanear cuando el cursor está en el documento del cliente NO corrompe dicho documento."""
        self.app.documento.set("1020304050")
        self.app.entry_doc.focus_set()
        self.app.entry_doc.delete(0, tk.END)
        self.app.entry_doc.insert(0, "1020304050")

        burst_code = "7701234567890"
        self.app.entry_doc.insert(tk.END, burst_code)  # What a USB scanner keyboard wedge does
        
        self.simulate_scanner_burst(burst_code, send_enter=True)
        self.win.update()

        # Check customer document is restored and UNCORRUPTED
        self.assertEqual(self.app.documento.get(), "1020304050", "El documento del cliente debe permanecer intacto.")
        self.assertEqual(self.app.entry_doc.get(), "1020304050", "El widget entry_doc debe tener solo la cédula original.")
        
        # Check product was correctly identified and added to cart
        items = self.app.tabla.get_children()
        self.assertEqual(len(items), 1, "El producto debe haberse agregado al carrito a pesar del foco en doc.")
        self.assertEqual(self.app.tabla.item(items[0])["values"][0], "Cuaderno 100H")

    # Test 6: Escanear después de cambiar cantidades o precios
    def test_06_escanear_despues_de_modificar_carrito(self):
        """Prueba 6: Escanear tras editar un ítem del carrito sigue funcionando sin clics adicionales."""
        # Add product 1
        self.app.codigo_entrada.set("7701234567890")
        self.simulate_scanner_burst("7701234567890", send_enter=True)
        self.win.update()

        # Modify item quantity directly
        items = self.app.tabla.get_children()
        item_id = items[0]
        self.app.tabla.item(item_id, values=("Cuaderno 100H", "$ 3.500 COP", 5, "$ 17.500 COP"))
        self.app.actualizar_total()
        self.assertEqual(self.app.total_general.get(), 17500.0)

        # Immediate scan of product 2
        time.sleep(0.25)
        self.app.codigo_entrada.set("7709876543210")
        self.simulate_scanner_burst("7709876543210", send_enter=True)
        self.win.update()

        items_after = self.app.tabla.get_children()
        self.assertEqual(len(items_after), 2, "Debe agregarse el segundo producto tras la edición.")
        self.assertEqual(self.app.total_general.get(), 17500.0 + 1200.0, "El total general debe sumar ambos productos.")

    # Test 7: Escanear cuando la ventana de cobro / pago esté abierta
    def test_07_escanear_con_ventana_pago_abierta_no_modifica_pago(self):
        """Prueba 7: Si la ventana de cobro está abierta, un escaneo accidental no corrompe los campos de pago."""
        self.app.codigo_entrada.set("7701234567890")
        self.simulate_scanner_burst("7701234567890", send_enter=True)
        self.win.update()

        self.app._dialogo_pago_activo = True
        dummy_entry = tk.Entry(self.win)
        dummy_entry.pack()
        dummy_entry.insert(0, "50000")
        dummy_entry.focus_set()

        res = self.simulate_scanner_burst("7709876543210", send_enter=True)
        self.win.update()

        self.assertEqual(dummy_entry.get(), "50000", "El valor del pago no debe haber sido alterado por el escáner.")
        
        items = self.app.tabla.get_children()
        self.assertEqual(len(items), 1, "No debe haberse agregado ningún producto nuevo mientras se cobraba.")

        self.app._dialogo_pago_activo = False
        dummy_entry.destroy()

    # Test 8: Escáner sin tecla Enter (Timeout 85ms)
    def test_08_escanear_sin_tecla_enter_procesa_por_timeout(self):
        """Prueba 8: Un escáner configurado sin tecla Enter final procesa el código tras el fin de la ráfaga."""
        self.app.entry_codigo.focus_set()
        self.simulate_scanner_burst("7701234567890", send_enter=False)
        
        # Fast forward scanner burst completion
        self.app._on_scanner_burst_sin_enter()
        self.win.update()

        items = self.app.tabla.get_children()
        self.assertEqual(len(items), 1, "El producto debe agregarse incluso sin tecla Return al final.")
        self.assertEqual(self.app.tabla.item(items[0])["values"][0], "Cuaderno 100H")

    # Test 9: Debounce contra rebote de hardware (< 220ms)
    def test_09_debounce_hardware_rebote(self):
        """Prueba 9: Dos lecturas del mismo código en menos de 220ms no duplican el producto."""
        self.app.entry_codigo.focus_set()
        self.app.codigo_entrada.set("7701234567890")
        self.simulate_scanner_burst("7701234567890", send_enter=True)
        self.win.update()

        # Immediate bounce 50ms later with exact same code
        time.sleep(0.05)
        self.app.codigo_entrada.set("7701234567890")
        self.simulate_scanner_burst("7701234567890", send_enter=True)
        self.win.update()

        items = self.app.tabla.get_children()
        self.assertEqual(len(items), 1)
        row_vals = self.app.tabla.item(items[0])["values"]
        self.assertEqual(int(row_vals[2]), 1, "La cantidad no debe duplicarse por rebote de hardware.")


if __name__ == "__main__":
    unittest.main()
