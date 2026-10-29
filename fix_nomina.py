with open("interface/nomina_menu.py", "r") as f:
    content = f.read()

content = content.replace("from database_manager import conectar_db", "from database_manager import conectar_db\nfrom usuarios_db import conectar_usuarios_db")

# In cargar_empleados:
content = content.replace('''    def cargar_empleados():
        for i in tree_emp.get_children(): tree_emp.delete(i)
        conn = conectar_db()
        if not conn: return
        cur = conn.cursor()
        cur.execute("SELECT id, usuario, comisiones_acumuladas FROM usuarios WHERE rol='empleado'")''',
'''    def cargar_empleados():
        for i in tree_emp.get_children(): tree_emp.delete(i)
        conn = conectar_usuarios_db()
        if not conn: return
        cur = conn.cursor()
        cur.execute("SELECT id, usuario, comisiones_acumuladas FROM usuarios WHERE rol IN ('empleado', 'vendedor')")''')

# In liquidar_empleado:
content = content.replace('''            cur.execute("UPDATE usuarios SET comisiones_acumuladas=0, solicitud_liquidacion=NULL WHERE id=?", (id_emp,))''',
'''            # Actualizar en usuarios.db
            conn_usr = conectar_usuarios_db()
            cur_usr = conn_usr.cursor()
            cur_usr.execute("UPDATE usuarios SET comisiones_acumuladas=0, solicitud_liquidacion=NULL WHERE id=?", (id_emp,))
            conn_usr.commit()
            conn_usr.close()
            ''')

with open("interface/nomina_menu.py", "w") as f:
    f.write(content)
