print("=== VERIFICANDO FINAL DEL ARCHIVO ===")
with open("interface/inicio_sesion.py", "r") as f:
    lines = f.readlines()
print("Últimas 5 líneas de inicio_sesion.py:")
print("".join(lines[-5:]))
