import re

# Fix gastos_menu.py
with open("interface/gastos_menu.py", "r") as f:
    gcode = f.read()

g_broken = """def conectar_db():
    return True
        cursor = conn.cursor()
        return True
    except Exception as e:
        messagebox.showerror("Error de conexión", f"No se pudo conectar a la base de datos:\\n{e}")
        return False"""
g_fixed = """def conectar_db():
    return True"""
gcode = gcode.replace(g_broken, g_fixed)
with open("interface/gastos_menu.py", "w") as f:
    f.write(gcode)

# Fix clientes_menu.py
with open("interface/clientes_menu.py", "r") as f:
    ccode = f.read()

c_broken = """c_data = response.json()
            clientes = c_data.get("items", []) if isinstance(c_data, dict) else (c_data if isinstance(c_data, list) else [])"""
c_fixed = """c_data = response.json()
                clientes = c_data.get("items", []) if isinstance(c_data, dict) else (c_data if isinstance(c_data, list) else [])"""
ccode = ccode.replace(c_broken, c_fixed)
with open("interface/clientes_menu.py", "w") as f:
    f.write(ccode)

print("CORRECCIONES APLICADAS")
