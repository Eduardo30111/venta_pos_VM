import re

with open("interface/ventas_menu.py", "r") as f:
    content = f.read()

# Using regex to properly catch and replace the block
pattern = r'        else:\n            # Verificar que hay stock para agregar el primer producto\n            if stock_disponible <= 0:\n                messagebox\.showwarning\("Sin stock", f"El producto \'{nombre}\' no tiene stock disponible"\)\n                return'

new_block = '''        else:
            # Verificar que hay stock para agregar el primer producto
            if tipo_prod != "Servicio" and stock_disponible <= 0:
                messagebox.showwarning("Sin stock", f"El producto '{nombre}' no tiene stock disponible", parent=self.ventana)
                return'''

content = content.replace('''        else:
            # Verificar que hay stock para agregar el primer producto
            if stock_disponible <= 0:
                messagebox.showwarning("Sin stock", f"El producto '{nombre}' no tiene stock disponible")
                return''', new_block)

with open("interface/ventas_menu.py", "w") as f:
    f.write(content)
