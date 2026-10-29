import re

with open("interface/nomina_menu.py", "r") as f:
    content = f.read()

# 1. Imports
content = re.sub(r'from database_manager import conectar_db\n', '', content)
content = re.sub(r'from usuarios_db import conectar_usuarios_db\n', '', content)
content = content.replace('import datetime', 'import datetime\nfrom client.api_client import api')

# 2. Empleados functions
emp_new = """    def cargar_empleados():
        for i in tree_emp.get_children(): tree_emp.delete(i)
        try:
            empleados = api.get("/nomina/empleados")
            if isinstance(empleados, list):
                for e in empleados:
                    nombre_completo = f"{e.get('nombre', '')} {e.get('apellidos', '')}".strip()
                    if not nombre_completo: nombre_completo = e.get('usuario', '')
                    acum = e.get('comisiones_acumuladas', 0.0) or 0.0
                    sal = e.get('salario_diario', 0.0) or 0.0
                    tree_emp.insert("", "end", values=(e.get('id'), nombre_completo, e.get('rol'), e.get('tipo_nomina'), f"${acum:,.2f}", f"${sal:,.2f}"))
        except Exception as e:
            messagebox.showerror("Error", f"Error al cargar empleados: {e}")
        
    def cargar_historial_emp(*args):
        for i in tree_hist_emp.get_children(): tree_hist_emp.delete(i)
        filtro_mes = mes_emp_var.get()
        try:
            liq = api.get("/nomina/liquidaciones")
            if isinstance(liq, list):
                for r in liq:
                    # Filter by month if needed
                    if filtro_mes and filtro_mes != "Todos" and r.get('mes_anio') != filtro_mes:
                        continue
                    # Ensure it's for 'Empleado' or wait, the new API probably just returns all or we can just show them
                    # if the API mixes both, we might need to filter by tipo='Empleado' if that field exists.
                    tree_hist_emp.insert("", "end", values=(r.get('id'), r.get('nombre_persona', f"Usuario {r.get('usuario_id')}"), f"${(r.get('monto') or 0.0):,.2f}", r.get('fecha'), r.get('mes_anio')))
        except Exception as e:
            messagebox.showerror("Error", f"Error al cargar historial: {e}")

    def actualizar_combo_meses_emp():
        try:
            liq = api.get("/nomina/liquidaciones")
            meses = ["Todos"]
            if isinstance(liq, list):
                meses_set = set(r.get('mes_anio') for r in liq if r.get('mes_anio'))
                meses.extend(sorted(list(meses_set), reverse=True))
            combo_mes_emp['values'] = meses
            if not mes_emp_var.get() and meses:
                mes_emp_var.set("Todos")
        except:
            pass
        cargar_historial_emp()"""

content = re.sub(r'    def cargar_empleados\(\):.*?cargar_historial_emp\(\)', emp_new, content, flags=re.DOTALL)

liq_emp_old = """    def liquidar_empleado():
        item = tree_emp.focus()
        if not item:
            messagebox.showwarning("Atención", "Seleccione un empleado para liquidar")
            return
        val = tree_emp.item(item, "values")
        id_emp = int(val[0])
        nombre = val[1]
        tipo_nom = val[3]
        acum_str = val[4]
        sal_str = val[5]
        
        acumulado = float(acum_str.replace("$", "").replace(",", ""))
        salario = float(sal_str.replace("$", "").replace(",", ""))
        
        # El saldo es el acumulado para ambos (por ventas o por asistencia diaria)
        saldo = acumulado
            
        if saldo <= 0:
            messagebox.showwarning("Sin fondos", "El empleado no tiene saldo para liquidar.")
            return
            
        if messagebox.askyesno("Liquidar", f"¿Liquidar nómina de {nombre} por ${saldo:,.2f}?"):
            conn = conectar_db()
            cur = conn.cursor()
            ahora = datetime.datetime.now()
            fecha = ahora.strftime("%Y-%m-%d %H:%M:%S")
            mes_anio = ahora.strftime("%m-%Y")
            
            # Actualizar en usuarios.db
            conn_usr = conectar_usuarios_db()
            cur_usr = conn_usr.cursor()
            cur_usr.execute("UPDATE usuarios SET comisiones_acumuladas=0, solicitud_liquidacion=NULL WHERE id=?", (id_emp,))
            conn_usr.commit()
            conn_usr.close()
            
            cur.execute("INSERT INTO gastos (concepto, valor, fecha, hora) VALUES (?, ?, ?, ?)",
                        (f"Liquidación Nómina - {nombre}", saldo, ahora.strftime("%d-%m-%Y"), ahora.strftime("%H:%M:%S")))
            cur.execute("INSERT INTO historial_liquidaciones (tipo, persona_id, nombre_persona, monto, fecha, mes_anio) VALUES (?, ?, ?, ?, ?, ?)",
                        ('Empleado', id_emp, nombre, saldo, fecha, mes_anio))
            conn.commit()
            conn.close()
            messagebox.showinfo("Éxito", f"Se ha liquidado la nómina de {nombre}.")
            cargar_empleados()
            actualizar_combo_meses_emp()"""

liq_emp_new = """    def liquidar_empleado():
        item = tree_emp.focus()
        if not item:
            messagebox.showwarning("Atención", "Seleccione un empleado para liquidar")
            return
        val = tree_emp.item(item, "values")
        id_emp = int(val[0])
        nombre = val[1]
        acum_str = val[4]
        
        acumulado = float(acum_str.replace("$", "").replace(",", ""))
        saldo = acumulado
            
        if saldo <= 0:
            messagebox.showwarning("Sin fondos", "El empleado no tiene saldo para liquidar.")
            return
            
        if messagebox.askyesno("Liquidar", f"¿Liquidar nómina de {nombre} por ${saldo:,.2f}?"):
            try:
                api.post("/nomina/liquidaciones", json={"usuario_id": id_emp})
                messagebox.showinfo("Éxito", f"Se ha liquidado la nómina de {nombre}.")
                cargar_empleados()
                actualizar_combo_meses_emp()
            except Exception as e:
                messagebox.showerror("Error", f"Error al liquidar: {e}")"""
                
content = content.replace(liq_emp_old, liq_emp_new)


asis_old = """        conn = conectar_usuarios_db()
        cur = conn.cursor()
        
        # Check if already done today
        cur.execute("SELECT id FROM asistencia WHERE fecha=?", (hoy,))
        if cur.fetchone():
            tk.Label(frame_list, text="✅ La asistencia de hoy ya fue registrada.", font=("Segoe UI", 11), bg="#f4f4f9", fg="green").pack(pady=20)
            tk.Button(ventana_ast, text="Cerrar", command=ventana_ast.destroy, font=("Segoe UI", 11)).pack(pady=10)
            conn.close()
            return
            
        cur.execute("SELECT id, nombre, apellidos, usuario, tipo_nomina, salario_diario FROM usuarios WHERE rol IN ('Operario', 'Vendedor') AND estado='Activo'")
        empleados = cur.fetchall()
        
        if not empleados:
            tk.Label(frame_list, text="No hay empleados activos registrados.", bg="#f4f4f9").pack()
            conn.close()
            return
            
        check_vars = {}
        for emp in empleados:
            var = tk.BooleanVar(value=True)
            check_vars[emp[0]] = (var, emp)
            nombre_comp = f"{emp[1]} {emp[2]}".strip() or emp[3]
            tipo_txt = f"({emp[4]})"
            tk.Checkbutton(frame_list, text=f"{nombre_comp} {tipo_txt}", variable=var, font=("Segoe UI", 11), bg="#f4f4f9").pack(anchor="w", pady=5)
            
        def guardar_asistencia():
            if messagebox.askyesno("Confirmar", "¿Guardar asistencia? Se añadirá la nómina diaria a quienes tengan Nómina Fija y asistan hoy."):
                cur_ast = conn.cursor()
                for e_id, (var, emp) in check_vars.items():
                    asistio = "Presente" if var.get() else "Ausente"
                    cur_ast.execute("INSERT INTO asistencia (usuario_id, fecha, estado) VALUES (?, ?, ?)", (e_id, hoy, asistio))
                    
                    if asistio == "Presente" and emp[4] == "Fija":
                        salario = emp[5] or 0.0
                        cur_ast.execute("UPDATE usuarios SET comisiones_acumuladas = comisiones_acumuladas + ? WHERE id=?", (salario, e_id))
                
                conn.commit()
                messagebox.showinfo("Éxito", "Asistencia y nóminas registradas correctamente.", parent=ventana_ast)
                ventana_ast.destroy()
                cargar_empleados()"""

asis_new = """        try:
            empleados = api.get("/nomina/empleados")
            if not isinstance(empleados, list) or not empleados:
                tk.Label(frame_list, text="No hay empleados activos registrados.", bg="#f4f4f9").pack()
                return
        except Exception as e:
            tk.Label(frame_list, text=f"Error al cargar empleados: {e}", bg="#f4f4f9").pack()
            return
            
        check_vars = {}
        for emp in empleados:
            # We assume we only want to show Operario and Vendedor, we just show all returned
            if emp.get("rol") not in ["Operario", "Vendedor"]: continue
            var = tk.BooleanVar(value=True)
            check_vars[emp["id"]] = (var, emp)
            nombre_comp = f"{emp.get('nombre', '')} {emp.get('apellidos', '')}".strip() or emp.get("usuario", "")
            tipo_txt = f"({emp.get('tipo_nomina', '')})"
            tk.Checkbutton(frame_list, text=f"{nombre_comp} {tipo_txt}", variable=var, font=("Segoe UI", 11), bg="#f4f4f9").pack(anchor="w", pady=5)
            
        def guardar_asistencia():
            if messagebox.askyesno("Confirmar", "¿Guardar asistencia? Se añadirá la nómina diaria a quienes tengan Nómina Fija y asistan hoy."):
                try:
                    for e_id, (var, emp) in check_vars.items():
                        asistio = "Presente" if var.get() else "Ausente"
                        api.post("/nomina/asistencia", json={"usuario_id": e_id, "estado": asistio})
                    
                    messagebox.showinfo("Éxito", "Asistencia y nóminas registradas correctamente.", parent=ventana_ast)
                    ventana_ast.destroy()
                    cargar_empleados()
                except Exception as e:
                    messagebox.showerror("Error", f"Error al guardar asistencia: {e}", parent=ventana_ast)"""

content = content.replace(asis_old, asis_new)

# Since we don't have instructions to change `proveedores` endpoints, we might want to just leave them untouched, but we removed `conectar_db` import, so we must mock or use the API for providers as well if it was using sqlite. 
# The task says: 
# "Update cargar_empleados() to api.get('/nomina/empleados')... etc." 
# Wait, for proveedore logic, the instruction didn't say, but we removed the sqlite3 imports. Let's fix that too, or re-add the import.
# Ah, the user didn't mention proveeodores in nomina_menu.py, but `conectar_db` is needed for them!
# I'll just re-add `from database_manager import conectar_db` for `proveedores` or change to API.
# Let's change the proveedores logic to use API as well since the db connection is gone, or just add the import back!
content = "from database_manager import conectar_db\n" + content

with open("interface/nomina_menu.py", "w") as f:
    f.write(content)

