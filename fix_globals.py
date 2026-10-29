with open("interface/usuarios_menu.py", "r") as f:
    content = f.read()

# Fix in iniciar_usuarios
old_global_iniciar = "global rol_var, estado_var, comision_var"
new_global_iniciar = "global rol_var, estado_var, comision_var, tipo_nomina_var, salario_diario_var"
content = content.replace(old_global_iniciar, new_global_iniciar)

# Fix in limpiar_campos
old_global_limpiar = "global id_usuario_seleccionado"
new_global_limpiar = "global id_usuario_seleccionado, rol_var, estado_var, tipo_nomina_var, salario_diario_var"
content = content.replace(old_global_limpiar, new_global_limpiar)

# Fix in guardar_usuario
old_global_guardar = "global id_usuario_seleccionado"
new_global_guardar = "global id_usuario_seleccionado, rol_var, estado_var, tipo_nomina_var, salario_diario_var"
content = content.replace(old_global_guardar, new_global_guardar)

# Fix in seleccionar_usuario
old_global_selec = "global id_usuario_seleccionado"
new_global_selec = "global id_usuario_seleccionado, rol_var, estado_var, tipo_nomina_var, salario_diario_var"
content = content.replace(old_global_selec, new_global_selec)

with open("interface/usuarios_menu.py", "w") as f:
    f.write(content)
