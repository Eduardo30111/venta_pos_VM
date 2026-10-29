with open("interface/inicio_sesion.py", "r") as f:
    lines = f.readlines()

with open("interface/inicio_sesion.py", "w") as f:
    for line in lines:
        if "sys.stdout = " in line or "sys.stderr = " in line:
            f.write(f"# {line}")
        else:
            f.write(line)
