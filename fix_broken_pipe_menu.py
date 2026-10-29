import re

with open("interface/menu_inicio.py", "r") as f:
    content = f.read()

redirect_code = '''import sys
import io

if not hasattr(sys.stdout, "name") or sys.stdout.name != "vmpos.log":
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

if "Redirigir stdout" not in content and "sys.stdout = log_file" not in content:
    content = content.replace("import tkinter as tk", redirect_code + "import tkinter as tk")

with open("interface/menu_inicio.py", "w") as f:
    f.write(content)
