with open("interface/inicio_sesion.py", "r") as f:
    content = f.read()

content = content.replace("def print('Paso 3: Inicializando sistema')\ninicializar_sistema():", "def inicializar_sistema():")

with open("interface/inicio_sesion.py", "w") as f:
    f.write(content)
