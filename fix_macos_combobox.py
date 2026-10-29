import re

# Fix inventario_menu.py
with open("interface/inventario_menu.py", "r") as f:
    content = f.read()

content = content.replace('if tipo_var.get() == "Servicio":', 'if combo_tipo.get() == "Servicio":')
content = content.replace('if prov_var.get() != "Ninguno" and tipo_var.get() == "Fisico":', 'if combo_prov.get() != "Ninguno" and combo_tipo.get() == "Fisico":')
content = content.replace('tipo_nuevo = tipo_var.get()', 'tipo_nuevo = combo_tipo.get()')
content = content.replace('prov_id_nuevo = int(prov_var.get().split(" - ")[0])', 'prov_id_nuevo = int(combo_prov.get().split(" - ")[0])')

with open("interface/inventario_menu.py", "w") as f:
    f.write(content)


# Fix usuarios_menu.py
with open("interface/usuarios_menu.py", "r") as f:
    content = f.read()

content = content.replace('if rol_var.get() in ["Vendedor", "Operario"]:', 'if combo_rol.get() in ["Vendedor", "Operario"]:')
content = content.replace('if tipo_nomina_var.get() == "Fija":', 'if combo_tipo_nomina.get() == "Fija":')
content = content.replace('rol = rol_var.get()', 'rol = combo_rol.get()')
content = content.replace('estado = estado_var.get()', 'estado = combo_estado.get()')
content = content.replace('tipo_nom = tipo_nomina_var.get()', 'tipo_nom = combo_tipo_nomina.get()')

with open("interface/usuarios_menu.py", "w") as f:
    f.write(content)
