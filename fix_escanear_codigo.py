import re

with open("interface/ventas_menu.py", "r") as f:
    content = f.read()

old_escanear = '''    def escanear_codigo(self):
        """Escanea un código de barras y agrega el producto"""
        codigo = self.codigo_entrada.get().strip()
        if not codigo:
            return
        producto = next((p for p in self.productos_inventario if str(p[0]) == codigo or str(p[0]).zfill(5) == codigo), None)
        if producto and producto[2] > 0:
            self.agregar_producto(producto[0], producto[1], producto[3])
            self.codigo_entrada.set("")
            self.entry_codigo.focus()
        else:
            messagebox.showerror("No encontrado", "Producto no existe o sin stock")
            self.codigo_entrada.set("")'''

new_escanear = '''    def escanear_codigo(self):
        """Escanea un código de barras y agrega el producto"""
        codigo = self.codigo_entrada.get().strip()
        if not codigo:
            return
        producto = next((p for p in self.productos_inventario if str(p[0]) == codigo or str(p[0]).zfill(5) == codigo.zfill(5)), None)
        
        if producto:
            # producto[2] es stock, producto[4] es tipo_producto
            if producto[2] > 0 or producto[4] == "Servicio":
                self.agregar_producto(producto[0], producto[1], producto[3])
                self.codigo_entrada.set("")
                self.entry_codigo.focus()
            else:
                messagebox.showerror("Sin stock", "El producto no tiene stock disponible", parent=self.ventana)
                self.codigo_entrada.set("")
        else:
            messagebox.showerror("No encontrado", "El código del producto no existe", parent=self.ventana)
            self.codigo_entrada.set("")'''

content = content.replace(old_escanear, new_escanear)

with open("interface/ventas_menu.py", "w") as f:
    f.write(content)
