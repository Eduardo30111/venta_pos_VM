import re

with open("interface/ventas_menu.py", "r") as f:
    content = f.read()

# Fix in buscar_producto -> seleccionar()
old_selec = '''                if stock > 0:
                    self.agregar_producto(codigo, nombre, precio)
                    ventana.destroy()
                else:
                    messagebox.showwarning("Sin stock", "Producto sin stock disponible")'''

new_selec = '''                tipo_prod = "Fisico"
                for p in self.productos_inventario:
                    if str(p[0]) == str(codigo) or str(p[0]).zfill(5) == str(codigo).zfill(5):
                        tipo_prod = p[4]
                        break
                        
                if stock > 0 or tipo_prod == "Servicio":
                    self.agregar_producto(codigo, nombre, precio)
                    ventana.destroy()
                else:
                    messagebox.showwarning("Sin stock", "Producto sin stock disponible", parent=ventana)'''
content = content.replace(old_selec, new_selec)

# Fix in agregar_producto
old_stock_chk = '''        stock_disponible = 0
        for p in self.productos_inventario:
            if str(p[0]) == str(codigo) or str(p[0]).zfill(5) == str(codigo).zfill(5):
                stock_disponible = p[2]
                break
        
        print(f"DEBUG: Código {codigo}, Stock disponible: {stock_disponible}")
        
        # BUSCAR SI YA EXISTE EN EL CARRITO - MEJORADO
        cantidad_actual = 0
        item_existente = None
        
        for item in self.tabla.get_children():
            valores = self.tabla.item(item)["values"]
            if len(valores) >= 4:
                # Buscar por nombre del producto para mayor compatibilidad
                if str(valores[0]).strip().lower() == str(nombre).strip().lower():
                    cantidad_actual = int(valores[2])
                    item_existente = item
                    print(f"DEBUG: Producto encontrado en carrito - Cantidad actual: {cantidad_actual}")
                    break

        # Verificar si se puede agregar una unidad más
        if cantidad_actual + 1 > stock_disponible:
            messagebox.showwarning("Stock insuficiente", 
                                 f"Stock disponible: {stock_disponible}\\n" +
                                 f"Ya tienes {cantidad_actual} en el carrito")
            return'''

new_stock_chk = '''        stock_disponible = 0
        tipo_prod = "Fisico"
        for p in self.productos_inventario:
            if str(p[0]) == str(codigo) or str(p[0]).zfill(5) == str(codigo).zfill(5):
                stock_disponible = p[2]
                tipo_prod = p[4]
                break
        
        print(f"DEBUG: Código {codigo}, Stock disponible: {stock_disponible}, Tipo: {tipo_prod}")
        
        # BUSCAR SI YA EXISTE EN EL CARRITO - MEJORADO
        cantidad_actual = 0
        item_existente = None
        
        for item in self.tabla.get_children():
            valores = self.tabla.item(item)["values"]
            if len(valores) >= 4:
                # Buscar por nombre del producto para mayor compatibilidad
                if str(valores[0]).strip().lower() == str(nombre).strip().lower():
                    cantidad_actual = int(valores[2])
                    item_existente = item
                    print(f"DEBUG: Producto encontrado en carrito - Cantidad actual: {cantidad_actual}")
                    break

        # Verificar si se puede agregar una unidad más (solo si NO es servicio)
        if tipo_prod != "Servicio" and (cantidad_actual + 1 > stock_disponible):
            messagebox.showwarning("Stock insuficiente", 
                                 f"Stock disponible: {stock_disponible}\\n" +
                                 f"Ya tienes {cantidad_actual} en el carrito")
            return'''
content = content.replace(old_stock_chk, new_stock_chk)

# Also fix the `stock_disponible <= 0` check further down
old_stock2 = '''        else:
            # Verificar que hay stock para agregar el primer producto
            if stock_disponible <= 0:
                messagebox.showwarning("Stock", "Producto agotado")
                return'''
new_stock2 = '''        else:
            # Verificar que hay stock para agregar el primer producto
            if tipo_prod != "Servicio" and stock_disponible <= 0:
                messagebox.showwarning("Stock", "Producto agotado")
                return'''
content = content.replace(old_stock2, new_stock2)

with open("interface/ventas_menu.py", "w") as f:
    f.write(content)
