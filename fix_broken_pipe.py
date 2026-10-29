import re

with open("interface/inicio_sesion.py", "r") as f:
    content = f.read()

# Add standard output redirection at the very top of inicio_sesion.py
redirect_code = '''import sys
import os
import io

# Redirigir stdout y stderr para evitar [Errno 32] Broken pipe en macOS
try:
    log_file = open("vmpos.log", "a", encoding="utf-8")
    sys.stdout = log_file
    sys.stderr = log_file
except Exception:
    class DevNull(io.TextIOBase):
        def write(self, msg): pass
    sys.stdout = DevNull()
    sys.stderr = DevNull()

'''

if "Redirigir stdout" not in content:
    content = content.replace("import tkinter as tk", redirect_code + "import tkinter as tk")

with open("interface/inicio_sesion.py", "w") as f:
    f.write(content)
