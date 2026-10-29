import re

with open("interface/usuarios_menu.py", "r") as f:
    content = f.read()

# Add bindings for comboboxes right after the traces
pattern = r'tipo_nomina_var\.trace_add\("write", on_tipo_nomina_change\)'
replacement = '''tipo_nomina_var.trace_add("write", on_tipo_nomina_change)
    
    # Asegurar que los cambios manuales en combobox también disparen la UI
    combo_rol.bind("<<ComboboxSelected>>", on_rol_change)
    combo_tipo_nomina.bind("<<ComboboxSelected>>", on_tipo_nomina_change)'''

content = re.sub(pattern, replacement, content)

with open("interface/usuarios_menu.py", "w") as f:
    f.write(content)
