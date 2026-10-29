with open("interface/menu_inicio.py", "r") as f:
    content = f.read()

import re

# Fix _actualizar_comision_empleado
content = content.replace('''                from usuarios_db import conectar_usuarios_db
                    conn = conectar_usuarios_db()
                    cursor = conn.cursor()
                    cursor.execute("SELECT comisiones_acumuladas FROM usuarios WHERE id = ?", (id_usuario,))''', 
'''                    from usuarios_db import conectar_usuarios_db
                    conn = conectar_usuarios_db()
                    cursor = conn.cursor()
                    cursor.execute("SELECT comisiones_acumuladas FROM usuarios WHERE id = ?", (id_usuario,))''')

# Fix _actualizar_estadisticas_empleado
content = content.replace('''            conn = _conectar_db()
            from usuarios_db import conectar_usuarios_db
            cur = conn.cursor()
            
            # Comisión actual
            cur.execute("SELECT comisiones_acumuladas FROM usuarios WHERE id=?", (id_usuario,))''',
'''            from usuarios_db import conectar_usuarios_db
            conn_usr = conectar_usuarios_db()
            cur_usr = conn_usr.cursor()
            
            # Comisión actual
            cur_usr.execute("SELECT comisiones_acumuladas FROM usuarios WHERE id=?", (id_usuario,))
            row = cur_usr.fetchone()
            if row:
                self.lbl_emp_comision.config(text=f"${row[0]:,.2f}")
            conn_usr.close()

            # Volver a abrir ventas.db para el resto si hace falta
            conn = _conectar_db()
            cur = conn.cursor()''')

with open("interface/menu_inicio.py", "w") as f:
    f.write(content)
