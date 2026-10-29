with open("interface/inicio_sesion.py", "r") as f:
    content = f.read()

content = content.replace("try:\n#     style.theme_use('clam')\nexcept:\n    pass", "")

with open("interface/inicio_sesion.py", "w") as f:
    f.write(content)
