with open("interface/usuarios_menu.py", "r") as f:
    text = f.read()

# Fix literal linebreaks inside strings
text = text.replace('f"Ocurrió un error inesperado:\n{e}"', 'f"Ocurrió un error inesperado: {e}"')
text = text.replace("f\"¿Estás seguro de que quieres eliminar al usuario '{usuario_seleccionado}'?\nEsta acción no se puede deshacer.\"", "f\"¿Estás seguro de que quieres eliminar al usuario '{usuario_seleccionado}'? Esta acción no se puede deshacer.\"")
text = text.replace('f"No se pudo cargar el servicio ({resp.status_code}):\n{resp.text}"', 'f"No se pudo cargar el servicio ({resp.status_code}): {resp.text}"')
text = text.replace('f"No se pudo cargar el producto ({resp.status_code}):\n{resp.text}"', 'f"No se pudo cargar el producto ({resp.status_code}): {resp.text}"')
text = text.replace('f"❌ Credenciales incorrectas o usuario inactivo.\nStatus: {test_client_resp.status_code}"', 'f"❌ Credenciales incorrectas o usuario inactivo. Status: {test_client_resp.status_code}"')

# Catch any remaining broken quotes
lines = text.splitlines()
fixed = []
i = 0
while i < len(lines):
    line = lines[i]
    if line.rstrip().endswith('f"Ocurrió un error inesperado:'):
        fixed.append('        messagebox.showerror("Error", f"Ocurrió un error inesperado: {e}", parent=ventana_usuarios)')
        i += 2
        continue
    if '¿Estás seguro de que quieres eliminar al usuario' in line and line.rstrip().endswith("'?"):
        fixed.append("        f\"¿Estás seguro de que quieres eliminar al usuario '{usuario_seleccionado}'? Esta acción no se puede deshacer.\",")
        i += 2
        continue
    if 'Credenciales incorrectas o usuario inactivo.' in line and not line.rstrip().endswith('"'):
        fixed.append('            messagebox.showerror("Login Fallido", f"❌ Credenciales incorrectas o usuario inactivo. Status: {test_client_resp.status_code}", parent=ventana_usuarios)')
        i += 2
        continue
    if 'f"Error del servidor ({resp.status_code}):' in line and not line.rstrip().endswith('"'):
        fixed.append('            return False, f"Error del servidor ({resp.status_code}): {detail}"')
        i += 2
        continue
    if 'f"Error de conexión:' in line and not line.rstrip().endswith('"'):
        fixed.append('        return False, f"Error de conexión: {e}"')
        i += 2
        continue
    fixed.append(line)
    i += 1

with open("interface/usuarios_menu.py", "w") as f:
    f.write("\n".join(fixed) + "\n")

print("FIX SCRIPT COMPLETED")
