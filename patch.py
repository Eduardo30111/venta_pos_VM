import re

with open("interface/inicio_sesion.py", "r") as f:
    content = f.read()

new_validar_usuario = """
def validar_usuario(event=None):
    usuario = usuario_var.get().strip()
    clave = pass_var.get().strip()
    
    if not usuario or not clave:
        messagebox.showwarning("Campos vacíos", "Por favor ingresa usuario y contraseña")
        return

    # Usar la nueva API
    success, message = api.login(usuario, clave)
    
    if not success:
        messagebox.showerror("Error", message)
        return

    # Obtener datos del perfil
    resp = api.get("/auth/me")
    if resp.status_code == 200:
        datos_usuario = resp.json()
        usuario_actual = datos_usuario['nombre'].capitalize()
        os.environ["VMPOS_TOKEN"] = api.token

        mostrar_alerta_bonita(
            "¡Bienvenida! ✨",
            f"Hola {usuario_actual}!\\n\\nAcceso concedido como {datos_usuario['rol']}\\nIniciando sistema...",
            "success"
        )
        
        ventana.after(1500, lambda: _iniciar_flujo_principal(datos_usuario, usuario_actual))
    else:
        messagebox.showerror("Error", "No se pudo cargar el perfil del usuario")
"""

content = re.sub(r'def validar_usuario\(event=None\):.*?def limpiar_campos', new_validar_usuario + '\ndef limpiar_campos', content, flags=re.DOTALL)

with open("interface/inicio_sesion.py", "w") as f:
    f.write(content)
