import sqlite3
from interface.config import DB_VENTAS_PATH

conn = sqlite3.connect(DB_VENTAS_PATH)
try:
    conn.execute("ALTER TABLE productos ADD COLUMN descripcion TEXT DEFAULT ''")
except: pass
conn.commit()
conn.close()
