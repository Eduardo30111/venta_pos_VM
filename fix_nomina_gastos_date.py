import re

with open("interface/nomina_menu.py", "r") as f:
    content = f.read()

# Fix liquidar_empleado
content = content.replace(
    'cur.execute("INSERT INTO gastos (concepto, valor, fecha, hora) VALUES (?, ?, ?, ?)",\n                        (f"Liquidación Nómina - {nombre}", saldo, ahora.strftime("%Y-%m-%d"), ahora.strftime("%H:%M:%S")))',
    'cur.execute("INSERT INTO gastos (concepto, valor, fecha, hora) VALUES (?, ?, ?, ?)",\n                        (f"Liquidación Nómina - {nombre}", saldo, ahora.strftime("%d-%m-%Y"), ahora.strftime("%H:%M:%S")))'
)

# Fix liquidar_proveedor
content = content.replace(
    'cur.execute("INSERT INTO gastos (concepto, valor, fecha, hora) VALUES (?, ?, ?, ?)",\n                        (f"Pago a Proveedor - {nombre}", saldo, ahora.strftime("%Y-%m-%d"), ahora.strftime("%H:%M:%S")))',
    'cur.execute("INSERT INTO gastos (concepto, valor, fecha, hora) VALUES (?, ?, ?, ?)",\n                        (f"Pago a Proveedor - {nombre}", saldo, ahora.strftime("%d-%m-%Y"), ahora.strftime("%H:%M:%S")))'
)

with open("interface/nomina_menu.py", "w") as f:
    f.write(content)
