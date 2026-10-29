import re

with open("interface/usuarios_menu.py", "r") as f:
    content = f.read()

pattern = r'combo_rol\.bind\("<<ComboboxSelected>>", on_rol_change\)\n    combo_tipo_nomina\.bind\("<<ComboboxSelected>>", on_tipo_nomina_change\)'

replacement = '''def _delayed_rol_change(e):
        combo_rol.after(50, on_rol_change)
    def _delayed_tipo_nomina_change(e):
        combo_tipo_nomina.after(50, on_tipo_nomina_change)
        
    combo_rol.bind("<<ComboboxSelected>>", _delayed_rol_change)
    combo_tipo_nomina.bind("<<ComboboxSelected>>", _delayed_tipo_nomina_change)'''

content = re.sub(pattern, replacement, content)

with open("interface/usuarios_menu.py", "w") as f:
    f.write(content)
