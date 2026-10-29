import re

with open('interface/inventario_menu.py', 'r') as f:
    code = f.read()

# Inyectar función de crear proveedor
func_crear_proveedor = """
def mostrar_modal_crear_proveedor(combo, prov_var):
    modal = tk.Toplevel()
    modal.title("Nuevo Proveedor")
    modal.geometry("300x200")
    modal.grab_set()

    tk.Label(modal, text="Nombre del Proveedor:").pack(pady=10)
    entry_nom = tk.Entry(modal, width=30)
    entry_nom.pack(pady=5)
    
    tk.Label(modal, text="Documento/NIT:").pack(pady=5)
    entry_nit = tk.Entry(modal, width=30)
    entry_nit.pack(pady=5)

    def guardar():
        nombre = entry_nom.get().strip()
        nit = entry_nit.get().strip() or "0"
        if not nombre:
            messagebox.showwarning("Error", "Nombre obligatorio", parent=modal)
            return
        
        try:
            resp = api.post("/proveedores", json={"nombre": nombre, "documento_nit": nit, "telefono": "", "email": "", "direccion": "", "contacto": ""})
            messagebox.showinfo("Exito", "Proveedor creado", parent=modal)
            # Actualizar combos
            provs = obtener_proveedores()
            nueva_lista = ["Ninguno"] + [f"{p[0]} - {p[1]}" for p in provs]
            combo['values'] = nueva_lista
            
            # Buscar el ID nuevo si podemos, o dejarlo en Ninguno
            modal.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"Fallo al crear: {e}", parent=modal)

    tk.Button(modal, text="Guardar Proveedor", command=guardar, bg="#4CAF50", fg="white").pack(pady=15)
"""

if "mostrar_modal_crear_proveedor" not in code:
    code = code.replace("def abrir_ventana_nuevo():", func_crear_proveedor + "\ndef abrir_ventana_nuevo():")

# En abrir_ventana_nuevo, buscar: combo_prov.grid(row=5, column=1, padx=10, pady=5)
# Y agregar un botón al lado en la column 2
btn_add1 = """combo_prov.grid(row=5, column=1, padx=10, pady=5)
        btn_add_prov = tk.Button(campos_frame, text="➕ Nuevo", command=lambda: mostrar_modal_crear_proveedor(combo_prov, prov_var), cursor="hand2")
        btn_add_prov.grid(row=5, column=2, padx=5, pady=5)"""

code = code.replace('combo_prov.grid(row=5, column=1, padx=10, pady=5)', btn_add1, 1)

# En edicion, buscar de nuevo combo_prov.grid y reemplazar
btn_add2 = """combo_prov.grid(row=5, column=1, padx=10, pady=5)
        btn_add_prov2 = tk.Button(campos_frame, text="➕ Nuevo", command=lambda: mostrar_modal_crear_proveedor(combo_prov, prov_var), cursor="hand2")
        btn_add_prov2.grid(row=5, column=2, padx=5, pady=5)"""

code = code.replace('combo_prov.grid(row=5, column=1, padx=10, pady=5)', btn_add2)

with open('interface/inventario_menu.py', 'w') as f:
    f.write(code)
print("PATCH APLICADO")
