with open("interface/inicio_sesion.py", "r") as f:
    lines = f.readlines()

# Eliminar líneas 282 y 283
del lines[281:283]

with open("interface/inicio_sesion.py", "w") as f:
    f.writelines(lines)
