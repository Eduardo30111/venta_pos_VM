import re

with open("interface/inventario_menu.py", "r") as f:
    content = f.read()

old_hide = '''            if combo_tipo.get() == "Servicio":
                lbl_prov.grid_remove()
                combo_prov.grid_remove()
                lbl_costo.grid_remove()
                entrada_costo.grid_remove()
                lbl_stock.grid_remove()
                entrada_stock.grid_remove()
                prov_var.set("Ninguno")
                entrada_costo.delete(0, tk.END)
                entrada_costo.insert(0, "0")
                entrada_stock.delete(0, tk.END)
                entrada_stock.insert(0, "0")
            else:
                lbl_prov.grid()
                combo_prov.grid()
                lbl_costo.grid()
                entrada_costo.grid()
                lbl_stock.grid()
                entrada_stock.grid()'''

new_hide = '''            if combo_tipo.get() == "Servicio":
                lbl_prov.grid_remove()
                combo_prov.grid_remove()
                lbl_stock.grid_remove()
                entrada_stock.grid_remove()
                prov_var.set("Ninguno")
                entrada_stock.delete(0, tk.END)
                entrada_stock.insert(0, "0")
            else:
                lbl_prov.grid()
                combo_prov.grid()
                lbl_stock.grid()
                entrada_stock.grid()'''

content = content.replace(old_hide, new_hide)

# Do the same for the second block (editar_producto)
old_hide2 = '''            if combo_tipo.get() == "Servicio":
                lbl_prov.grid_remove()
                combo_prov.grid_remove()
                lbl_costo.grid_remove()
                entrada_costo.grid_remove()
                lbl_stock.grid_remove()
                entrada_stock.grid_remove()
            else:
                lbl_prov.grid()
                combo_prov.grid()
                lbl_costo.grid()
                entrada_costo.grid()
                lbl_stock.grid()
                entrada_stock.grid()'''

new_hide2 = '''            if combo_tipo.get() == "Servicio":
                lbl_prov.grid_remove()
                combo_prov.grid_remove()
                lbl_stock.grid_remove()
                entrada_stock.grid_remove()
            else:
                lbl_prov.grid()
                combo_prov.grid()
                lbl_stock.grid()
                entrada_stock.grid()'''

content = content.replace(old_hide2, new_hide2)

with open("interface/inventario_menu.py", "w") as f:
    f.write(content)
