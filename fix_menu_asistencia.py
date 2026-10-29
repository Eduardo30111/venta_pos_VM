import re

with open("interface/menu_inicio.py", "r") as f:
    content = f.read()

new_method = '''
    def _verificar_asistencia(self):
        try:
            if self.rol_usuario in ["admin", "gerente", "administrador"]:
                from usuarios_db import conectar_usuarios_db
                import datetime
                hoy = datetime.date.today().strftime('%Y-%m-%d')
                
                conn = conectar_usuarios_db()
                cur = conn.cursor()
                
                # Check if there are employees/vendors
                cur.execute("SELECT COUNT(*) FROM usuarios WHERE rol IN ('Operario', 'Vendedor') AND estado='Activo'")
                if cur.fetchone()[0] > 0:
                    # Check if attendance is marked for today
                    cur.execute("SELECT COUNT(*) FROM asistencia WHERE fecha=?", (hoy,))
                    if cur.fetchone()[0] == 0:
                        self.after(2000, lambda: messagebox.showinfo(
                            "Recordatorio de Asistencia", 
                            "¡Hola! Recuerda comprobar la asistencia del personal hoy para cargar sus nóminas diarias.",
                            parent=self
                        ))
                conn.close()
        except Exception as e:
            print("Error verificando asistencia:", e)

    def _actualizar_estadisticas(self):'''

content = content.replace("    def _actualizar_estadisticas(self):", new_method)

# Add call in __init__
init_old = '''        # Actualizar estadísticas cada 30 segundos
        self._actualizar_estadisticas()'''
init_new = '''        # Actualizar estadísticas cada 30 segundos
        self._actualizar_estadisticas()
        
        # Verificar asistencia diaria
        self._verificar_asistencia()'''
content = content.replace(init_old, init_new)

with open("interface/menu_inicio.py", "w") as f:
    f.write(content)
