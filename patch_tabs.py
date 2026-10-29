import re

with open("interface/inventario_menu.py", "r") as f:
    code = f.read()

# 1. Modificar cargar_tabla
old_cargar = """    def cargar_tabla():
        \"\"\"Carga los productos en la tabla\"\"\"
        try:
            for item in tabla.get_children():
                tabla.delete(item)
            productos = obtener_productos()
            for producto in productos:
                id, codigo, nombre, precio, costo, stock, tipo, prov = producto
                if prov is None: prov = "Ninguno"
                if tipo is None: tipo = "Fisico"
                tabla.insert("", "end", values=(
                    id, codigo, nombre, formato_peso(precio), formato_peso(costo), stock, tipo, prov
                ))
        except Exception as e:
            messagebox.showerror("Error", f"Error al cargar tabla: {e}")"""

new_cargar = """    def cargar_tabla():
        \"\"\"Carga los productos en la tabla dividida\"\"\"
        try:
            for item in tabla.get_children(): tabla.delete(item)
            for item in tabla_servicios.get_children(): tabla_servicios.delete(item)
            
            productos = obtener_productos()
            for producto in productos:
                id, codigo, nombre, precio, costo, stock, tipo, prov = producto
                if prov is None: prov = "Ninguno"
                if tipo is None: tipo = "Fisico"
                
                # Valores completos siempre para no romper el resto del codigo
                valores = (id, codigo, nombre, formato_peso(precio), formato_peso(costo), stock, tipo, prov)
                
                if tipo == "Servicio":
                    tabla_servicios.insert("", "end", values=valores)
                else:
                    tabla.insert("", "end", values=valores)
        except Exception as e:
            messagebox.showerror("Error", f"Error al cargar tabla: {e}")"""

code = code.replace(old_cargar, new_cargar)

# 2. Modificar editar_producto
old_editar = """    def editar_producto():
        seleccionado = tabla.focus()
        if not seleccionado:
            messagebox.showwarning("Aviso", "Selecciona un producto para editar.")
            return

        valores = tabla.item(seleccionado)["values"]"""

new_editar = """    def editar_producto():
        active_table = tabla if notebook.index("current") == 0 else tabla_servicios
        seleccionado = active_table.focus()
        if not seleccionado:
            messagebox.showwarning("Aviso", "Selecciona un producto/servicio para editar.")
            return

        valores = active_table.item(seleccionado)["values"]"""
code = code.replace(old_editar, new_editar)

# 3. Modificar eliminar_producto
old_eliminar = """    def eliminar_producto_seleccionado():
        seleccionado = tabla.focus()
        if not seleccionado:
            messagebox.showwarning("Aviso", "Selecciona un producto para eliminar.")
            return

        valores = tabla.item(seleccionado)["values"]"""

new_eliminar = """    def eliminar_producto_seleccionado():
        active_table = tabla if notebook.index("current") == 0 else tabla_servicios
        seleccionado = active_table.focus()
        if not seleccionado:
            messagebox.showwarning("Aviso", "Selecciona un producto/servicio para eliminar.")
            return

        valores = active_table.item(seleccionado)["values"]"""
code = code.replace(old_eliminar, new_eliminar)

# 4. Modificar la creación de la tabla visual en la parte de abajo
old_gui = """    columnas = ("Id", "Código", "Producto", "Precio", "Costo", "Stock")
    tabla = ttk.Treeview(frame_tabla, columns=columnas, show="headings", height=15)
    
    style = ttk.Style()
    style.theme_use('clam')
    style.configure("Treeview",
                    background="white",
                    foreground="#2d3436",
                    rowheight=25,
                    fieldbackground="white",
                    font=("Segoe UI", 10))
    style.map("Treeview",
              background=[('selected', '#fd79a8')],
              foreground=[('selected', 'white')])

    style.configure("Treeview.Heading",
                    font=("Segoe UI", 10, "bold"),
                    background="#e84393",
                    foreground="white",
                    relief="flat")
    style.map("Treeview.Heading",
              background=[('active', '#e84393')])

    tabla.heading("Id", text="Id")
    tabla.heading("Código", text="Código")
    tabla.heading("Producto", text="Producto")
    tabla.heading("Precio", text="Precio")
    tabla.heading("Costo", text="Costo")
    tabla.heading("Stock", text="Stock")

    tabla.column("Id", width=40, anchor="center")
    tabla.column("Código", width=100, anchor="center")
    tabla.column("Producto", width=200, anchor="w")
    tabla.column("Precio", width=120, anchor="center")
    tabla.column("Costo", width=120, anchor="center")
    tabla.column("Stock", width=80, anchor="center")

    tabla.pack(fill="both", expand=True, padx=20, pady=10)"""

new_gui = """    global notebook, tabla, tabla_servicios
    style = ttk.Style()
    style.theme_use('clam')
    style.configure("Treeview", background="white", foreground="#2d3436", rowheight=25, fieldbackground="white", font=("Segoe UI", 10))
    style.map("Treeview", background=[('selected', '#fd79a8')], foreground=[('selected', 'white')])
    style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), background="#e84393", foreground="white", relief="flat")
    style.map("Treeview.Heading", background=[('active', '#e84393')])

    notebook = ttk.Notebook(frame_tabla)
    notebook.pack(fill="both", expand=True, padx=20, pady=10)
    
    tab_fisicos = tk.Frame(notebook, bg="white")
    tab_servicios = tk.Frame(notebook, bg="white")
    
    notebook.add(tab_fisicos, text="📦 Productos Físicos")
    notebook.add(tab_servicios, text="🛠️ Servicios")
    
    columnas_f = ("Id", "Código", "Producto", "Precio", "Costo", "Stock")
    tabla = ttk.Treeview(tab_fisicos, columns=columnas_f, show="headings", height=15)
    tabla.heading("Id", text="Id")
    tabla.heading("Código", text="Código")
    tabla.heading("Producto", text="Producto")
    tabla.heading("Precio", text="Precio")
    tabla.heading("Costo", text="Costo")
    tabla.heading("Stock", text="Stock")
    tabla.column("Id", width=40, anchor="center")
    tabla.column("Código", width=100, anchor="center")
    tabla.column("Producto", width=200, anchor="w")
    tabla.column("Precio", width=120, anchor="center")
    tabla.column("Costo", width=120, anchor="center")
    tabla.column("Stock", width=80, anchor="center")
    tabla.pack(fill="both", expand=True, padx=10, pady=10)

    columnas_s = ("Id", "Código", "Servicio", "Precio", "Costo")
    tabla_servicios = ttk.Treeview(tab_servicios, columns=columnas_s, show="headings", height=15)
    tabla_servicios.heading("Id", text="Id")
    tabla_servicios.heading("Código", text="Código")
    tabla_servicios.heading("Servicio", text="Servicio")
    tabla_servicios.heading("Precio", text="Precio")
    tabla_servicios.heading("Costo", text="Costo")
    tabla_servicios.column("Id", width=40, anchor="center")
    tabla_servicios.column("Código", width=100, anchor="center")
    tabla_servicios.column("Servicio", width=200, anchor="w")
    tabla_servicios.column("Precio", width=120, anchor="center")
    tabla_servicios.column("Costo", width=120, anchor="center")
    tabla_servicios.pack(fill="both", expand=True, padx=10, pady=10)"""

code = code.replace(old_gui, new_gui)

with open("interface/inventario_menu.py", "w") as f:
    f.write(code)

print("TABS IMPLEMENTADOS CORRECTAMENTE")
