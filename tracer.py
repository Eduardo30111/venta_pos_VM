import sys

with open("interface/inicio_sesion.py", "r") as f:
    content = f.read()

# Insertar prints de depuración
content = content.replace("import tkinter as tk", "print('Paso 1: Cargando Tkinter')\nimport tkinter as tk")
content = content.replace("from client.api_client import api", "print('Paso 2: Cargando cliente API')\nfrom client.api_client import api")
content = content.replace("inicializar_sistema()", "print('Paso 3: Inicializando sistema')\ninicializar_sistema()")
content = content.replace("ventana = tk.Tk()", "print('Paso 4: Creando ventana')\nventana = tk.Tk()")
content = content.replace("main_frame = tk.Frame", "print('Paso 5: Dibujando frames')\nmain_frame = tk.Frame")
content = content.replace("if __name__ == \"__main__\":", "print('Paso 6: Lanzando loop principal')\nif __name__ == '__main__':")

with open("interface/inicio_sesion.py", "w") as f:
    f.write(content)
