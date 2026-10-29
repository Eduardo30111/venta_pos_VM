with open("interface/menu_inicio.py", "r") as f:
    content = f.read()

# We need to clean up _actualizar_estadisticas_empleado
import re
new_content = re.sub(
    r'conn_usr\.close\(\).*?conn = _conectar_db\(\).*?cur = conn\.cursor\(\).*?row = cur\.fetchone\(\).*?if row:.*?self\.lbl_emp_comision\.config\(text=f"\$\{row\[0\]:,\.2f\}"\)',
    'conn_usr.close()\n            conn = _conectar_db()\n            cur = conn.cursor()',
    content,
    flags=re.DOTALL
)

with open("interface/menu_inicio.py", "w") as f:
    f.write(new_content)
