import re

with open("interface/usuarios_menu.py", "r") as f:
    content = f.read()

# Make sure all messageboxes have parent=ventana_usuarios
content = re.sub(
    r'messagebox\.showerror\("Error", (.*?)\)',
    r'messagebox.showerror("Error", \1, parent=ventana_usuarios)',
    content
)
content = re.sub(
    r'messagebox\.showinfo\("Éxito", (.*?)\)',
    r'messagebox.showinfo("Éxito", \1, parent=ventana_usuarios)',
    content
)
# Make sure we don't duplicate parent=ventana_usuarios if it already exists
content = content.replace(", parent=ventana_usuarios, parent=ventana_usuarios)", ", parent=ventana_usuarios)")

with open("interface/usuarios_menu.py", "w") as f:
    f.write(content)
