import re

with open("interface/usuarios_menu.py", "r") as f:
    content = f.read()

# 1. Update form variables and roles
content = content.replace('roles = ["Administrador", "Gerente", "Vendedor", "Empleado"]', 
                          'roles = ["Admin", "Gerente", "Vendedor", "Operario"]')
content = content.replace('comision_var = tk.StringVar(value="0")',
                          'comision_var = tk.StringVar(value="0")\n    tipo_nomina_var = tk.StringVar(value="Porcentual")\n    salario_diario_var = tk.StringVar(value="0")')

# 2. Add form fields (Name, Last Name) before Rol
new_form = """    # Campo Nombre
    tk.Label(form_frame, text="📛 Nombre:", font=("Segoe UI", 11, "bold"), 
             bg="#FFDDEE", fg="#C71585").grid(row=2, column=0, padx=5, pady=8, sticky="w")
    entrada_nombre = tk.Entry(form_frame, font=("Segoe UI", 11), width=35, bg="#FFFFFF", fg="#C71585", bd=1, relief="solid")
    entrada_nombre.grid(row=2, column=1, padx=5, pady=8, sticky="w")
    entradas['Nombre'] = entrada_nombre

    # Campo Apellidos
    tk.Label(form_frame, text="📛 Apellidos:", font=("Segoe UI", 11, "bold"), 
             bg="#FFDDEE", fg="#C71585").grid(row=3, column=0, padx=5, pady=8, sticky="w")
    entrada_apellidos = tk.Entry(form_frame, font=("Segoe UI", 11), width=35, bg="#FFFFFF", fg="#C71585", bd=1, relief="solid")
    entrada_apellidos.grid(row=3, column=1, padx=5, pady=8, sticky="w")
    entradas['Apellidos'] = entrada_apellidos
    
    # Campo Rol
    tk.Label(form_frame, text="👑 Rol:", font=("Segoe UI", 11, "bold"), 
             bg="#FFDDEE", fg="#C71585").grid(row=4, column=0, padx=5, pady=8, sticky="w")
    combo_rol = ttk.Combobox(form_frame, textvariable=rol_var, values=roles, 
                             state="readonly", width=32, font=("Segoe UI", 11))
    combo_rol.grid(row=4, column=1, padx=5, pady=8, sticky="w")

    # Campo Tipo Nomina
    lbl_tipo_nomina = tk.Label(form_frame, text="📄 Tipo Nómina:", font=("Segoe UI", 11, "bold"), bg="#FFDDEE", fg="#C71585")
    combo_tipo_nomina = ttk.Combobox(form_frame, textvariable=tipo_nomina_var, values=["Fija", "Porcentual"], state="readonly", width=15, font=("Segoe UI", 11))

    # Campo Comisión / Salario
    lbl_valor_nomina = tk.Label(form_frame, text="💰 Valor:", font=("Segoe UI", 11, "bold"), bg="#FFDDEE", fg="#C71585")
    entrada_valor_nomina = tk.Entry(form_frame, textvariable=salario_diario_var, font=("Segoe UI", 11), width=10, bg="#FFFFFF", fg="#C71585", bd=1, relief="solid")

    def on_rol_change(*args):
        if rol_var.get() in ["Vendedor", "Operario"]:
            lbl_tipo_nomina.grid(row=4, column=2, padx=5, pady=8, sticky="w")
            combo_tipo_nomina.grid(row=4, column=3, padx=5, pady=8, sticky="w")
            lbl_valor_nomina.grid(row=5, column=2, padx=5, pady=8, sticky="w")
            entrada_valor_nomina.grid(row=5, column=3, padx=5, pady=8, sticky="w")
        else:
            lbl_tipo_nomina.grid_remove()
            combo_tipo_nomina.grid_remove()
            lbl_valor_nomina.grid_remove()
            entrada_valor_nomina.grid_remove()
            tipo_nomina_var.set("Porcentual")
            salario_diario_var.set("0")
            
    def on_tipo_nomina_change(*args):
        if tipo_nomina_var.get() == "Fija":
            lbl_valor_nomina.config(text="💰 Salario Diario ($):")
        else:
            lbl_valor_nomina.config(text="💰 Porcentaje (%):")

    rol_var.trace_add("write", on_rol_change)
    tipo_nomina_var.trace_add("write", on_tipo_nomina_change)
    
    # Campo Estado
    tk.Label(form_frame, text="📊 Estado:", font=("Segoe UI", 11, "bold"), 
             bg="#FFDDEE", fg="#C71585").grid(row=5, column=0, padx=5, pady=8, sticky="w")
    combo_estado = ttk.Combobox(form_frame, textvariable=estado_var, values=estados,"""

# We need to replace the block
content = re.sub(
    r'# Campo Rol.*?combo_estado = ttk\.Combobox\(form_frame, textvariable=estado_var, values=estados,',
    new_form,
    content,
    flags=re.DOTALL
)

# 3. Update guardar_usuario to collect these
new_guardar = '''
        nombre = entradas.get('Nombre').get() if entradas.get('Nombre') else ""
        apellidos = entradas.get('Apellidos').get() if entradas.get('Apellidos') else ""
        tipo_nom = tipo_nomina_var.get()
        valor_nom_str = salario_diario_var.get()
        
        try:
            valor_nom = float(valor_nom_str) if valor_nom_str.strip() else 0.0
        except ValueError:
            messagebox.showwarning("Valor Inválido", "El valor de nómina debe ser un número")
            return
            
        salario = valor_nom if tipo_nom == "Fija" else 0.0
        comision = valor_nom if tipo_nom == "Porcentual" else 0.0

        if not usuario or not rol or not estado:
            messagebox.showwarning("Campos Requeridos", "Los campos Usuario, Rol y Estado son obligatorios")
            return
            
        if hasattr(guardar_usuario, "id_usuario_editar") and guardar_usuario.id_usuario_editar:
            # Modo edición
            if actualizar_usuario_db(guardar_usuario.id_usuario_editar, usuario, rol, estado, password, comision, nombre, apellidos, tipo_nom, salario):
                messagebox.showinfo("Éxito", f"Usuario '{usuario}' actualizado correctamente")
            else:
                messagebox.showerror("Error", "No se pudo actualizar el usuario")
            guardar_usuario.id_usuario_editar = None
        else:
            # Modo nuevo
            if not password:
                messagebox.showwarning("Campos Requeridos", "La contraseña es obligatoria para nuevos usuarios")
                return
            
            if insertar_usuario(usuario, password, rol, estado, comision, nombre, apellidos, tipo_nom, salario):
                messagebox.showinfo("Éxito", f"Usuario '{usuario}' creado correctamente")
            else:
                messagebox.showerror("Error", "El usuario ya existe o hubo un error al guardarlo")
        
        limpiar_campos()
        actualizar_tabla()
'''

content = re.sub(
    r'comision_str = comision_var\.get\(\).*?actualizar_tabla\(\)',
    new_guardar.strip(),
    content,
    flags=re.DOTALL
)

# 4. In seleccionar_usuario
new_seleccionar = '''    def seleccionar_usuario(event):
        item = tree_usuarios.focus()
        if not item: return
        
        valores = tree_usuarios.item(item, "values")
        if not valores: return
        
        limpiar_campos()
        
        guardar_usuario.id_usuario_editar = valores[0]
        entradas['Usuario'].insert(0, valores[1])
        # [2] is Rol, [3] is Estado, [4] is Nombre, [5] is Apellidos, [6] is Tipo Nomina, [7] is Valor
        rol_var.set(valores[2])
        estado_var.set(valores[3])
        
        if 'Nombre' in entradas: entradas['Nombre'].insert(0, valores[4])
        if 'Apellidos' in entradas: entradas['Apellidos'].insert(0, valores[5])
        
        tipo_nomina_var.set(valores[6])
        if valores[6] == "Fija":
            salario_diario_var.set(valores[7])
        else:
            salario_diario_var.set(valores[7]) # It's percentage or salary
'''

content = re.sub(
    r'def seleccionar_usuario\(event\):.*?comision_var\.set\(valores\[6\]\)',
    new_seleccionar.strip(),
    content,
    flags=re.DOTALL
)

# 5. columns in tree_usuarios
old_columns = '''columns = ("ID", "Usuario", "Rol", "Estado", "Último Acceso", "Registro", "Comisión %")'''
new_columns = '''columns = ("ID", "Usuario", "Rol", "Estado", "Nombre", "Apellidos", "Tipo Nómina", "Valor")'''
content = content.replace(old_columns, new_columns)

old_actualizar_tabla = '''        for user in usuarios:
            comision_texto = f"{user.get('comision_porcentaje', 0)}%" if user.get('rol') == 'Empleado' else "N/A"
            tree_usuarios.insert("", "end", values=(
                user.get('id', ''),
                user.get('usuario', ''),
                user.get('rol', ''),
                user.get('estado', ''),
                user.get('ultimo_acceso', 'Nunca'),
                user.get('fecha_registro', ''),
                comision_texto
            ))'''
new_actualizar_tabla = '''        for user in usuarios:
            tipo = user.get('tipo_nomina', 'Porcentual')
            if tipo == "Fija":
                valor = user.get('salario_diario', 0.0)
            else:
                valor = user.get('comision_porcentaje', 0.0)
                
            tree_usuarios.insert("", "end", values=(
                user.get('id', ''),
                user.get('usuario', ''),
                user.get('rol', ''),
                user.get('estado', ''),
                user.get('nombre', ''),
                user.get('apellidos', ''),
                tipo,
                valor
            ))'''
content = content.replace(old_actualizar_tabla, new_actualizar_tabla)

with open("interface/usuarios_menu.py", "w") as f:
    f.write(content)
