import sqlite3
from interface.config import DB_USUARIOS_PATH

def migrar():
    conn = sqlite3.connect(DB_USUARIOS_PATH)
    cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE usuarios ADD COLUMN nombre TEXT DEFAULT ''")
    except: pass
    try:
        cur.execute("ALTER TABLE usuarios ADD COLUMN apellidos TEXT DEFAULT ''")
    except: pass
    try:
        cur.execute("ALTER TABLE usuarios ADD COLUMN tipo_nomina TEXT DEFAULT 'Porcentual'")
    except: pass
    try:
        cur.execute("ALTER TABLE usuarios ADD COLUMN salario_diario REAL DEFAULT 0.0")
    except: pass
    
    # Actualizar roles antiguos
    cur.execute("UPDATE usuarios SET rol = 'Admin' WHERE rol = 'Administrador'")
    cur.execute("UPDATE usuarios SET rol = 'Operario' WHERE rol = 'Empleado'")
    
    conn.commit()
    conn.close()
    print("Migración completada.")

if __name__ == '__main__':
    migrar()
