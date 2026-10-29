with open("interface/nomina_menu.py", "r") as f:
    content = f.read()

import re

# Update Tree definition
content = content.replace('cols_emp = ("ID", "Empleado", "Comisión Acumulada")', 'cols_emp = ("ID", "Empleado", "Rol", "Tipo Nómina", "Acumulado", "Salario Base")')
content = content.replace('tree_emp.column(c, width=150, anchor="center")', 'tree_emp.column(c, width=120, anchor="center")')

# Update cargar_empleados
old_cargar = '''        cur.execute("SELECT id, usuario, comisiones_acumuladas FROM usuarios WHERE rol IN ('empleado', 'vendedor')")
        for r in cur.fetchall():
            tree_emp.insert("", "end", values=(r[0], r[1], f"${(r[2] or 0.0):,.2f}"))'''
new_cargar = '''        cur.execute("SELECT id, nombre, apellidos, usuario, rol, tipo_nomina, salario_diario, comisiones_acumuladas FROM usuarios WHERE rol IN ('Operario', 'Vendedor')")
        for r in cur.fetchall():
            nombre_completo = f"{r[1]} {r[2]}".strip()
            if not nombre_completo: nombre_completo = r[3]
            acum = r[7] or 0.0
            sal = r[6] or 0.0
            tree_emp.insert("", "end", values=(r[0], nombre_completo, r[4], r[5], f"${acum:,.2f}", f"${sal:,.2f}"))'''
content = content.replace(old_cargar, new_cargar)

# Update liquidar_empleado
old_liquidar = '''        val = tree_emp.item(item, "values")
        id_emp, nombre, saldo_str = int(val[0]), val[1], val[2]
        saldo = float(saldo_str.replace("$", "").replace(",", ""))
        
        if saldo <= 0:
            messagebox.showwarning("Sin fondos", "El empleado no tiene comisión acumulada para liquidar.")
            return
            
        if messagebox.askyesno("Liquidar", f"¿Liquidar nómina de {nombre} por ${saldo:,.2f}?"):'''

new_liquidar = '''        val = tree_emp.item(item, "values")
        id_emp = int(val[0])
        nombre = val[1]
        tipo_nom = val[3]
        acum_str = val[4]
        sal_str = val[5]
        
        acumulado = float(acum_str.replace("$", "").replace(",", ""))
        salario = float(sal_str.replace("$", "").replace(",", ""))
        
        saldo = 0.0
        
        if tipo_nom == "Fija":
            from tkinter.simpledialog import askinteger
            dias = askinteger("Días Trabajados", f"Ingrese los días a pagar para {nombre} (Diario: ${salario:,.2f}):", minvalue=1, maxvalue=31)
            if not dias: return
            saldo = dias * salario
        else:
            saldo = acumulado
            
        if saldo <= 0:
            messagebox.showwarning("Sin fondos", "El empleado no tiene saldo para liquidar.")
            return
            
        if messagebox.askyesno("Liquidar", f"¿Liquidar nómina de {nombre} por ${saldo:,.2f}?"):'''
content = content.replace(old_liquidar, new_liquidar)

with open("interface/nomina_menu.py", "w") as f:
    f.write(content)
