with open("interface/usuarios_db.py", "r") as f:
    content = f.read()

# Replace insertar_usuario
old_insertar = '''def insertar_usuario(usuario, password, rol, estado="Activo", comision_porcentaje=0.0):
    """
    Inserta un nuevo usuario en la base de datos.
    
    Args:
        usuario (str): Nombre de usuario
        password (str): Contraseña en texto plano
        rol (str): Rol del usuario (Administrador, Gerente, Vendedor, Empleado)
        estado (str): Estado del usuario (Activo, Inactivo)
        comision_porcentaje (float): Porcentaje de comisión para Empleados
    
    Returns:
        bool: True si se insertó correctamente, False si ya existe
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # Verificar si el usuario ya existe
        cursor.execute("SELECT id FROM usuarios WHERE usuario = ?", (usuario,))
        if cursor.fetchone():
            print(f"⚠️ El usuario '{usuario}' ya existe.")
            conn.close()
            return False
        
        # Insertar nuevo usuario
        password_hash = hash_password(password)
        cursor.execute(\'\'\'
            INSERT INTO usuarios (usuario, password, rol, estado, fecha_registro, fecha_modificacion, comision_porcentaje, comisiones_acumuladas)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        \'\'\', (usuario, password_hash, rol, estado, datetime.now(), datetime.now(), comision_porcentaje))'''

new_insertar = '''def insertar_usuario(usuario, password, rol, estado="Activo", comision_porcentaje=0.0, nombre="", apellidos="", tipo_nomina="Porcentual", salario_diario=0.0):
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # Verificar si el usuario ya existe
        cursor.execute("SELECT id FROM usuarios WHERE usuario = ?", (usuario,))
        if cursor.fetchone():
            print(f"⚠️ El usuario '{usuario}' ya existe.")
            conn.close()
            return False
        
        # Insertar nuevo usuario
        password_hash = hash_password(password)
        cursor.execute(\'\'\'
            INSERT INTO usuarios (usuario, password, rol, estado, fecha_registro, fecha_modificacion, comision_porcentaje, comisiones_acumuladas, nombre, apellidos, tipo_nomina, salario_diario)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
        \'\'\', (usuario, password_hash, rol, estado, datetime.now(), datetime.now(), comision_porcentaje, nombre, apellidos, tipo_nomina, salario_diario))'''

content = content.replace(old_insertar, new_insertar)

# Replace obtener_usuarios
old_obtener = '''        cursor.execute(\'\'\'
            SELECT id, usuario, rol, estado, ultimo_acceso, fecha_registro, comision_porcentaje, comisiones_acumuladas, solicitud_liquidacion
            FROM usuarios
        \'\'\')
        
        usuarios = []
        for row in cursor.fetchall():
            usuarios.append({
                'id': row[0],
                'usuario': row[1],
                'rol': row[2],
                'estado': row[3],
                'ultimo_acceso': row[4],
                'fecha_registro': row[5],
                'comision_porcentaje': row[6],
                'comisiones_acumuladas': row[7],
                'solicitud_liquidacion': row[8]
            })'''

new_obtener = '''        cursor.execute(\'\'\'
            SELECT id, usuario, rol, estado, ultimo_acceso, fecha_registro, comision_porcentaje, comisiones_acumuladas, solicitud_liquidacion, nombre, apellidos, tipo_nomina, salario_diario
            FROM usuarios
        \'\'\')
        
        usuarios = []
        for row in cursor.fetchall():
            usuarios.append({
                'id': row[0],
                'usuario': row[1],
                'rol': row[2],
                'estado': row[3],
                'ultimo_acceso': row[4],
                'fecha_registro': row[5],
                'comision_porcentaje': row[6],
                'comisiones_acumuladas': row[7],
                'solicitud_liquidacion': row[8],
                'nombre': row[9],
                'apellidos': row[10],
                'tipo_nomina': row[11],
                'salario_diario': row[12]
            })'''

content = content.replace(old_obtener, new_obtener)

# Replace actualizar_usuario_db
old_actualizar = '''def actualizar_usuario_db(id_usuario, usuario=None, rol=None, estado=None, password=None, comision_porcentaje=None):'''
new_actualizar = '''def actualizar_usuario_db(id_usuario, usuario=None, rol=None, estado=None, password=None, comision_porcentaje=None, nombre=None, apellidos=None, tipo_nomina=None, salario_diario=None):'''

content = content.replace(old_actualizar, new_actualizar)

# Within actualizar_usuario_db, add the new fields
old_actualizar_logic = '''        if comision_porcentaje is not None:
            campos_actualizar.append("comision_porcentaje = ?")
            valores.append(comision_porcentaje)
        
        # Siempre actualizar fecha de modificación
        campos_actualizar.append("fecha_modificacion = ?")
        valores.append(datetime.now())'''

new_actualizar_logic = '''        if comision_porcentaje is not None:
            campos_actualizar.append("comision_porcentaje = ?")
            valores.append(comision_porcentaje)

        if nombre is not None:
            campos_actualizar.append("nombre = ?")
            valores.append(nombre)
        if apellidos is not None:
            campos_actualizar.append("apellidos = ?")
            valores.append(apellidos)
        if tipo_nomina is not None:
            campos_actualizar.append("tipo_nomina = ?")
            valores.append(tipo_nomina)
        if salario_diario is not None:
            campos_actualizar.append("salario_diario = ?")
            valores.append(salario_diario)
        
        # Siempre actualizar fecha de modificación
        campos_actualizar.append("fecha_modificacion = ?")
        valores.append(datetime.now())'''

content = content.replace(old_actualizar_logic, new_actualizar_logic)

with open("interface/usuarios_db.py", "w") as f:
    f.write(content)
