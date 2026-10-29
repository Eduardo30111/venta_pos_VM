import re
with open("interface/menu_inicio.py", "r") as f:
    content = f.read()

# Replace the Popen line to capture stderr to debug_nomina.txt
new_popen = """
                with open('debug_nomina.txt', 'w') as f:
                    subprocess.Popen([sys.executable, script_path], stdout=f, stderr=f)
"""
content = content.replace("                subprocess.Popen([sys.executable, script_path])", new_popen)

with open("interface/menu_inicio.py", "w") as f:
    f.write(content)
