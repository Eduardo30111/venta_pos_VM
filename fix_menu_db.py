with open("interface/menu_inicio.py", "r") as f:
    content = f.read()
content = content.replace("from usuarios_db import conectar_usuarios_db\n                    conn = conectar_usuarios_db()", "conn = _conectar_db()")
with open("interface/menu_inicio.py", "w") as f:
    f.write(content)
