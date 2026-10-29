import re
import os

# 1. Parchear modelos y schemas de Servicio en el servidor
schema_path = "server/schemas/inventario.py"
# buscar donde esta ServicioCreate
for p in os.listdir("server/schemas"):
    if p.endswith(".py"):
        with open(f"server/schemas/{p}", "r") as f:
            if "class ServicioBase" in f.read():
                schema_path = f"server/schemas/{p}"
                break

with open(schema_path, "r") as f:
    scode = f.read()
scode = scode.replace("categoria_id: int", "categoria_id: Optional[int] = None")
with open(schema_path, "w") as f:
    f.write(scode)

model_path = "server/models/servicio.py"
with open(model_path, "r") as f:
    mcode = f.read()
mcode = mcode.replace('categoria_id = Column(Integer, ForeignKey("categorias.id"), nullable=False)', 'categoria_id = Column(Integer, ForeignKey("categorias.id"), nullable=True)')
with open(model_path, "w") as f:
    f.write(mcode)

# 2. Parchear Inventario UI
with open("interface/inventario_menu.py", "r") as f:
    icode = f.read()

# Eliminar
e_old = """        valores = active_table.item(seleccionado)["values"]
        id_producto = valores[0]
        nombre_producto = valores[2]

        confirmacion = messagebox.askyesno("Confirmar Eliminación", 
                                         f"¿Estás seguro de que quieres eliminar '{nombre_producto}'?", 
                                         icon="warning")
        tipo_producto = valores[6]"""
e_new = """        valores = active_table.item(seleccionado)["values"]
        id_producto = valores[0]
        nombre_producto = valores[2]
        tipo_producto = "Fisico" if notebook.index("current") == 0 else "Servicio"

        confirmacion = messagebox.askyesno("Confirmar Eliminación", 
                                         f"¿Estás seguro de que quieres eliminar '{nombre_producto}'?", 
                                         icon="warning")"""
icode = icode.replace(e_old, e_new)

# Editar - Aca vamos a rehacer el bloque porque tiene muchas referencias a valores[...]
# Lo mas facil es usar regex para reemplazar todo el inicio de editar_producto
ed_old_pattern = r'def editar_producto\(\):(.*?)try:\s+if tipo_producto == "Servicio":'
ed_new = """def editar_producto():
        active_table = tabla if notebook.index("current") == 0 else tabla_servicios
        seleccionado = active_table.focus()
        if not seleccionado:
            messagebox.showwarning("Aviso", "Selecciona un producto/servicio para editar.")
            return

        valores = active_table.item(seleccionado)["values"]
        id_producto = valores[0]
        codigo = valores[1]
        nombre = valores[2]
        tipo_producto = "Fisico" if notebook.index("current") == 0 else "Servicio"
        
        try:
            if tipo_producto == "Servicio":"""
icode = re.sub(ed_old_pattern, ed_new, icode, flags=re.DOTALL)

with open("interface/inventario_menu.py", "w") as f:
    f.write(icode)

print("PARCHE FINAL APLICADO")
