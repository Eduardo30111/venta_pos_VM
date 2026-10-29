import sqlite3
from interface.config import DB_USUARIOS_PATH

conn = sqlite3.connect(DB_USUARIOS_PATH)
conn.execute("""
CREATE TABLE IF NOT EXISTS asistencia (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL,
    fecha TEXT NOT NULL,
    estado TEXT NOT NULL
)
""")
conn.commit()
conn.close()
