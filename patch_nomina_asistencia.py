import re

with open("interface/nomina_menu.py", "r") as f:
    content = f.read()

# 1. Simplify liquidar_empleado to just use acumulado (since attendance handles daily addition)
old_liquidar = '''        saldo = 0.0
        
        if tipo_nom == "Fija":
            from tkinter.simpledialog import askinteger
            dias = askinteger("Días Trabajados", f"Ingrese los días a pagar para {nombre} (Diario: ${salario:,.2f}):", minvalue=1, maxvalue=31)
            if not dias: return
            saldo = dias * salario
        else:
            saldo = acumulado'''

new_liquidar = '''        # El saldo es el acumulado para ambos (por ventas o por asistencia diaria)
        saldo = acumulado'''

content = content.replace(old_liquidar, new_liquidar)

# 2. Add abrir_asistencia and button
asistencia_code = '''    def abrir_asistencia():
        ventana_ast = tk.Toplevel(ventana)
        ventana_ast.title("Control de Asistencia")
        ventana_ast.geometry("400x500")
        ventana_ast.configure(bg="#f4f4f9")
        ventana_ast.transient(ventana)
        ventana_ast.grab_set()

        import datetime
        hoy = datetime.date.today().strftime('%Y-%m-%d')
        
        tk.Label(ventana_ast, text=f"Asistencia - {hoy}", font=("Segoe UI", 14, "bold"), bg="#f4f4f9", fg="#333").pack(pady=15)
        
        frame_list = tk.Frame(ventana_ast, bg="#f4f4f9")
        frame_list.pack(fill="both", expand=True, padx=20, pady=10)
        
        conn = conectar_usuarios_db()
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
                cargar_empleados()
                
        tk.Button(ventana_ast, text="💾 Guardar Asistencia", command=guardar_asistencia, bg="#3b5998", fg="white", font=("Segoe UI", 11, "bold")).pack(pady=20)

    tk.Button(emp_left, text="💸 Liquidar Seleccionado", command=liquidar_empleado, bg="#4CAF50", fg="white", font=("Segoe UI", 11, "bold")).pack(pady=5)
    tk.Button(emp_left, text="📅 Control Asistencia", command=abrir_asistencia, bg="#3b5998", fg="white", font=("Segoe UI", 11, "bold")).pack(pady=5)
'''

# Find the button and replace it
content = re.sub(r'    tk\.Button\(emp_left, text="💸 Liquidar Seleccionado".*?\.pack\(pady=10\)', asistencia_code, content)

with open("interface/nomina_menu.py", "w") as f:
    f.write(content)
