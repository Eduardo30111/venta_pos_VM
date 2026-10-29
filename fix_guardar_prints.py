import re

with open("interface/usuarios_menu.py", "r") as f:
    content = f.read()

old_guardar = '''    if not usuario:
        messagebox.showerror("Error", "El campo Usuario es obligatorio.")
        entradas['Usuario'].focus()
        return
    if rol == "Seleccionar" or not rol:
        messagebox.showerror("Error", "Debes seleccionar un rol.")
        return
    if estado == "Seleccionar" or not estado:
        messagebox.showerror("Error", "Debes seleccionar un estado.")
        return'''

new_guardar = '''    print(f"INTENTO GUARDAR: usu='{usuario}' pass='{password}' rol='{rol}' est='{estado}' tipo='{tipo_nom}' id={id_usuario_seleccionado}")
    if not usuario:
        print("Abortando: Usuario vacío")
        messagebox.showerror("Error", "El campo Usuario es obligatorio.", parent=ventana_usuarios)
        entradas['Usuario'].focus()
        return
    if rol == "Seleccionar" or not rol:
        print("Abortando: Rol vacío")
        messagebox.showerror("Error", "Debes seleccionar un rol.", parent=ventana_usuarios)
        return
    if estado == "Seleccionar" or not estado:
        print("Abortando: Estado vacío")
        messagebox.showerror("Error", "Debes seleccionar un estado.", parent=ventana_usuarios)
        return'''

content = content.replace(old_guardar, new_guardar)

old_pw = '''            if not password:
                messagebox.showerror("Error", "La contraseña es obligatoria para un nuevo usuario.")
                entradas['Password'].focus()
                return'''

new_pw = '''            if not password:
                print("Abortando: Contraseña vacía para nuevo usuario")
                messagebox.showerror("Error", "La contraseña es obligatoria para un nuevo usuario.", parent=ventana_usuarios)
                entradas['Password'].focus()
                return'''

content = content.replace(old_pw, new_pw)

with open("interface/usuarios_menu.py", "w") as f:
    f.write(content)
