with open("interface/menu_inicio.py", "r") as f:
    lines = f.readlines()

new_lines = []
skip = False
for i, line in enumerate(lines):
    if "def _abrir_nomina(self):" in line:
        skip = True
    if skip and "def _abrir_control_gastos(self):" in line:
        skip = False
        new_lines.append(line)
        continue
    if skip and '"""Abre el módulo de control de gastos."""' in line:
        skip = False
    
    if not skip:
        new_lines.append(line)

with open("interface/menu_inicio.py", "w") as f:
    f.writelines(new_lines)
