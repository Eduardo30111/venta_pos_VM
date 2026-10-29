with open("interface/usuarios_menu.py", "r") as f:
    content = f.read()

import re

# We will replace from "def limpiar_campos():" up to "def probar_login():"
pattern = r'def limpiar_campos\(\):.*?def probar_login\(\):'

new_methods = '''def limpiar_campos():
    """
    Limpia todos los campos de entrada y restablece la selección.
    """
    global id_usuario_seleccionado
    id_usuario_seleccionado = None
    
    # Limpiar campos de texto
    for campo in ["Usuario", "Password", "Nombre", "Apellidos"]:
        if campo in entradas:
            entradas[campo].delete(0, tk.END)
    
    # Restablecer comboboxes
    if rol_var:
        rol_var.set("Seleccionar")
    if estado_var:
        estado_var.set("Seleccionar")
    if tipo_nomina_var:
        tipo_nomina_var.set("Porcentual")
    if salario_diario_var:
        salario_diario_var.set("0")
        
    print("🧹 Campos limpiados. Listo para registrar nuevo usuario.")

def probar_login():'''

content = re.sub(pattern, new_methods, content, flags=re.DOTALL)


# Now fix guardar_usuario
pattern2 = r'def guardar_usuario\(\):.*?def eliminar_usuario\(\):'

new_guardar = '''def guardar_usuario():
    """
    Guarda o actualiza un usuario en la base de datos.
    """
    global id_usuario_seleccionado
    
    usuario = entradas['Usuario'].get().strip()
    password = entradas['Password'].get().strip()
    nombre = entradas['Nombre'].get().strip() if 'Nombre' in entradas else ""
    apellidos = entradas['Apellidos'].get().strip() if 'Apellidos' in entradas else ""
    
    rol = rol_var.get()
    estado = estado_var.get()
    tipo_nom = tipo_nomina_var.get()
    
    try:
        valor_nom = float(salario_diario_var.get())
    except ValueError:
        valor_nom = 0.0
        
    salario = valor_nom if tipo_nom == "Fija" else 0.0
    comision = valor_nom if tipo_nom == "Porcentual" else 0.0
    
    if not usuario:
        messagebox.showerror("Error", "El campo Usuario es obligatorio.")
        entradas['Usuario'].focus()
        return
    if rol == "Seleccionar" or not rol:
        messagebox.showerror("Error", "Debes seleccionar un rol.")
        return
    if estado == "Seleccionar" or not estado:
        messagebox.showerror("Error", "Debes seleccionar un estado.")
        return
    
    try:
        if id_usuario_seleccionado:
            print(f"🔄 Actualizando usuario con ID: {id_usuario_seleccionado}")
            resultado = actualizar_usuario_db(
                id_usuario_seleccionado, 
                usuario=usuario, 
                rol=rol, 
                estado=estado, 
                password=password if password else None,
                comision_porcentaje=comision,
                nombre=nombre,
                apellidos=apellidos,
                tipo_nomina=tipo_nom,
                salario_diario=salario
            )
            if resultado:
                messagebox.showinfo("Éxito", f"Usuario '{usuario}' actualizado correctamente.")
            else:
                messagebox.showerror("Error", "No se pudo actualizar el usuario.")
        else:
            if not password:
                messagebox.showerror("Error", "La contraseña es obligatoria para un nuevo usuario.")
                entradas['Password'].focus()
                return
            print(f"➕ Creando nuevo usuario: {usuario}")
            resultado = insertar_usuario(usuario, password, rol, estado, comision, nombre, apellidos, tipo_nom, salario)
            if resultado:
                messagebox.showinfo("Éxito", f"Usuario '{usuario}' creado correctamente.")
            else:
                messagebox.showerror("Error", f"No se pudo crear el usuario. Es posible que ya exista.")
        limpiar_campos()
        actualizar_tabla()
    except Exception as e:
        print(f"❌ Error al guardar usuario: {e}")
        messagebox.showerror("Error de base de datos", f"Ocurrió un error al guardar el usuario:\n{e}")

def eliminar_usuario():'''

content = re.sub(pattern2, new_guardar, content, flags=re.DOTALL)

# Now fix seleccionar_usuario
pattern3 = r'def seleccionar_usuario\(event\):.*?def guardar_usuario\(\):'

new_selec = '''def seleccionar_usuario(event):
    """
    Carga los datos del usuario seleccionado en los campos de edición.
    """
    global id_usuario_seleccionado

    item_seleccionado = tabla.focus()
    if not item_seleccionado:
        return
    
    try:
        valores = tabla.item(item_seleccionado, 'values')
        if not valores: return
        
        id_usuario_seleccionado = int(valores[0])
        
        # We clean first to make sure fields are empty
        for campo in ["Usuario", "Password", "Nombre", "Apellidos"]:
            if campo in entradas:
                entradas[campo].delete(0, tk.END)
                
        entradas['Usuario'].insert(0, valores[1])
        
        rol_var.set(valores[2])
        estado_var.set(valores[3])
        
        # As table has ("ID", "Usuario", "Rol", "Estado", "Último Acceso", "Fecha Registro")
        # We need to query DB to get Nombre, Apellidos, Tipo_nomina, Salario
        usuarios_db = obtener_usuarios()
        for u in usuarios_db:
            if u['id'] == id_usuario_seleccionado:
                if 'Nombre' in entradas and u.get('nombre'):
                    entradas['Nombre'].insert(0, u['nombre'])
                if 'Apellidos' in entradas and u.get('apellidos'):
                    entradas['Apellidos'].insert(0, u['apellidos'])
                    
                tipo_nom = u.get('tipo_nomina', 'Porcentual')
                tipo_nomina_var.set(tipo_nom)
                
                if tipo_nom == 'Fija':
                    salario_diario_var.set(str(u.get('salario_diario', 0.0)))
                else:
                    salario_diario_var.set(str(u.get('comision_porcentaje', 0.0)))
                break
        
        print(f"👤 Usuario seleccionado: {valores[1]} (ID: {id_usuario_seleccionado})")
    except Exception as e:
        print(f"❌ Error al seleccionar usuario: {e}")

def guardar_usuario():'''

content = re.sub(pattern3, new_selec, content, flags=re.DOTALL)

with open("interface/usuarios_menu.py", "w") as f:
    f.write(content)
