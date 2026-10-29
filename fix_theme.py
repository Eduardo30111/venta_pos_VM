with open("interface/inicio_sesion.py", "r") as f:
    lines = f.readlines()

with open("interface/inicio_sesion.py", "w") as f:
    for line in lines:
        if "theme_use('clam')" in line:
            f.write("# " + line)
        else:
            f.write(line)
