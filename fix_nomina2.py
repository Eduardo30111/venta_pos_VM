with open("interface/nomina_menu.py", "r") as f:
    content = f.read()

content = content.replace("f\"${r[2]:,.2f}\"", "f\"${(r[2] or 0.0):,.2f}\"")
with open("interface/nomina_menu.py", "w") as f:
    f.write(content)
