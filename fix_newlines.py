with open("interface/usuarios_menu.py", "r") as f:
    text = f.read()

# Replace any broken multiline string literal
text = text.replace('f"Error del servidor ({resp.status_code}):\n{detail}"', 'f"Error del servidor ({resp.status_code}): " + str(detail)')
text = text.replace('f"Error de conexión:\n{e}"', 'f"Error de conexión: " + str(e)')

with open("interface/usuarios_menu.py", "w") as f:
    f.write(text)

