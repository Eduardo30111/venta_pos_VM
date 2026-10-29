import re

with open("interface/inventario_menu.py", "r") as f:
    content = f.read()

# In abrir_ventana_registro and editar_producto:
pattern = r'tipo_var\.trace_add\("write", actualizar_visibilidad\)\n        prov_var\.trace_add\("write", actualizar_visibilidad\)\n        actualizar_visibilidad\(\)'

replacement = '''tipo_var.trace_add("write", actualizar_visibilidad)
        prov_var.trace_add("write", actualizar_visibilidad)
        
        # Mac fixes
        def _on_tipo_select(e):
            combo_tipo.after(50, actualizar_visibilidad)
        def _on_prov_select(e):
            combo_prov.after(50, actualizar_visibilidad)
            
        combo_tipo.bind("<<ComboboxSelected>>", _on_tipo_select)
        combo_prov.bind("<<ComboboxSelected>>", _on_prov_select)
        
        actualizar_visibilidad()'''

content = re.sub(pattern, replacement, content)

with open("interface/inventario_menu.py", "w") as f:
    f.write(content)
