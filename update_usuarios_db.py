with open("interface/usuarios_db.py", "r") as f:
    content = f.read()

# Fix crear_tablas_iniciales
content = content.replace("""            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                rol TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'Activo',
                ultimo_acceso DATETIME,
                fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
                fecha_modificacion DATETIME DEFAULT CURRENT_TIMESTAMP
            )""", """            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                rol TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'Activo',
                ultimo_acceso DATETIME,
                fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
                fecha_modificacion DATETIME DEFAULT CURRENT_TIMESTAMP,
                nombre TEXT DEFAULT '',
                apellidos TEXT DEFAULT '',
                tipo_nomina TEXT DEFAULT 'Porcentual',
                salario_diario REAL DEFAULT 0.0,
                comision_porcentaje REAL DEFAULT 0.0,
                comisiones_acumuladas REAL DEFAULT 0.0,
                solicitud_liquidacion DATETIME
            )""")

with open("interface/usuarios_db.py", "w") as f:
    f.write(content)
