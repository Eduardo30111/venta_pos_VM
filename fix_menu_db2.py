import re

with open("interface/menu_inicio.py", "r") as f:
    lines = f.readlines()

new_lines = []
for i, line in enumerate(lines):
    if "cursor.execute(\"SELECT comisiones_acumuladas FROM usuarios" in line:
        # Reemplazar la conexion anterior
        # lines[i-2] es conn = _conectar_db() o similar
        new_lines[-2] = new_lines[-2].replace("_conectar_db", "conectar_usuarios_db")
        # Asegurarse de importar conectar_usuarios_db
        new_lines.insert(-2, " "*16 + "from usuarios_db import conectar_usuarios_db\n")
    if "cur.execute(\"SELECT comisiones_acumuladas FROM usuarios" in line:
        new_lines[-3] = new_lines[-3].replace("_conectar_db", "conectar_usuarios_db")
        new_lines.insert(-3, " "*12 + "from usuarios_db import conectar_usuarios_db\n")
        
    new_lines.append(line)

with open("interface/menu_inicio.py", "w") as f:
    f.writelines(new_lines)
