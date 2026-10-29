with open("interface/inicio_sesion.py", "r") as f:
    lines = f.readlines()

with open("interface/inicio_sesion.py", "w") as f:
    for line in lines:
        if "f\"Hola {usuario_actual}!" in line:
            f.write('            f"Hola {usuario_actual}!\\n\\nAcceso concedido como {datos_usuario[\'rol\']}\\nIniciando sistema...",\n')
        else:
            f.write(line)
