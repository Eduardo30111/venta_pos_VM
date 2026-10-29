with open("interface/inicio_sesion.py", "r") as f:
    content = f.read()

# 1. Quitar el color de fondo a la ventana base
content = content.replace('ventana.configure(bg="#F8BBD0")', '# Fix Mac: ventana.configure(bg="#F8BBD0")')

# 2. Quitar el update_idletasks temprano que confunde el compositor de Mac
content = content.replace('ventana.update_idletasks()', '# Fix Mac: ventana.update_idletasks()')

# 3. Forzar un repintado un milisegundo después de abrir (fuerza a Mac a renderizar los botones)
content = content.replace('if __name__ == "__main__":', 'def forzar_repintado_mac():\n    ventana.update_idletasks()\n    ventana.update()\n\nif __name__ == "__main__":\n    ventana.after(100, forzar_repintado_mac)')

with open("interface/inicio_sesion.py", "w") as f:
    f.write(content)
