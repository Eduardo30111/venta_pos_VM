import re

with open("interface/inventario_menu.py", "r") as f:
    content = f.read()

# I need to match everything from "def abrir_ventana_registro():" to "def eliminar_producto_seleccionado():"
# excluding "def eliminar_producto_seleccionado():"

pattern = r'    def abrir_ventana_registro\(\):.*?def eliminar_producto_seleccionado\(\):'

replacement = '''    def abrir_ventana_registro():
        ventana_registro = tk.Toplevel(ventana)
        ventana_registro.title("Registrar nuevo producto")
        ventana_registro.geometry("420x520")
        ventana_registro.configure(bg="#FFF0F5")
        ventana_registro.transient(ventana)
        ventana_registro.grab_set()

        ventana_registro.update_idletasks()
        x_offset = ventana.winfo_x() + (ventana.winfo_width() // 2) - (420 // 2)
        y_offset = ventana.winfo_y() + (ventana.winfo_height() // 2) - (520 // 2)
        ventana_registro.geometry(f"420x520+{x_offset}+{y_offset}")

        tk.Label(ventana_registro, text="Nuevo Registro", font=("Segoe UI", 14, "bold"), 
                bg="#FFF0F5", fg="#e84393").pack(pady=10)

        campos_frame = tk.Frame(ventana_registro, bg="#FFF0F5")
        campos_frame.pack(pady=10)
        
        # 1. TIPO
        tk.Label(campos_frame, text="Tipo:", bg="#FFF0F5", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, padx=10, pady=5, sticky="w")
        tipo_var = tk.StringVar(value="Fisico")
        combo_tipo = ttk.Combobox(campos_frame, textvariable=tipo_var, values=["Fisico", "Servicio"], state="readonly", width=33)
        combo_tipo.grid(row=0, column=1, padx=10, pady=5)
        
        # Generar codigo secuencial
        conn = conectar_db()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT codigo FROM productos")
            max_num = 0
            for row in cur.fetchall():
                if row[0].isdigit():
                    max_num = max(max_num, int(row[0]))
            next_cod = f"{max_num + 1:05d}"
            conn.close()
        else:
            next_cod = "00001"

        # CÓDIGO
        lbl_codigo = tk.Label(campos_frame, text="Código:", bg="#FFF0F5", font=("Segoe UI", 10))
        lbl_codigo.grid(row=1, column=0, padx=10, pady=5, sticky="w")
        entrada_codigo = tk.Entry(campos_frame, width=35, font=("Segoe UI", 10), bd=1, relief="solid")
        entrada_codigo.insert(0, next_cod)
        entrada_codigo.grid(row=1, column=1, padx=10, pady=5)

        # NOMBRE
        lbl_nombre = tk.Label(campos_frame, text="Nombre:", bg="#FFF0F5", font=("Segoe UI", 10))
        lbl_nombre.grid(row=2, column=0, padx=10, pady=5, sticky="w")
        entrada_nombre = tk.Entry(campos_frame, width=35, font=("Segoe UI", 10), bd=1, relief="solid")
        entrada_nombre.grid(row=2, column=1, padx=10, pady=5)
        
        # DESCRIPCIÓN
        lbl_descripcion = tk.Label(campos_frame, text="Descripción:", bg="#FFF0F5", font=("Segoe UI", 10))
        lbl_descripcion.grid(row=3, column=0, padx=10, pady=5, sticky="w")
        entrada_descripcion = tk.Entry(campos_frame, width=35, font=("Segoe UI", 10), bd=1, relief="solid")
        entrada_descripcion.grid(row=3, column=1, padx=10, pady=5)

        # PRECIO
        lbl_precio = tk.Label(campos_frame, text="Precio Venta:", bg="#FFF0F5", font=("Segoe UI", 10))
        lbl_precio.grid(row=4, column=0, padx=10, pady=5, sticky="w")
        entrada_precio = tk.Entry(campos_frame, width=35, font=("Segoe UI", 10), bd=1, relief="solid")
        entrada_precio.grid(row=4, column=1, padx=10, pady=5)

        # PROVEEDOR
        lbl_prov = tk.Label(campos_frame, text="Proveedor:", bg="#FFF0F5", font=("Segoe UI", 10))
        lbl_prov.grid(row=5, column=0, padx=10, pady=5, sticky="w")
        proveedores = obtener_proveedores()
        lista_prov = ["Ninguno"] + [f"{p[0]} - {p[1]}" for p in proveedores]
        prov_var = tk.StringVar(value="Ninguno")
        combo_prov = ttk.Combobox(campos_frame, textvariable=prov_var, values=lista_prov, state="readonly", width=33)
        combo_prov.grid(row=5, column=1, padx=10, pady=5)
        
        # COSTO
        lbl_costo = tk.Label(campos_frame, text="Costo:", bg="#FFF0F5", font=("Segoe UI", 10))
        lbl_costo.grid(row=6, column=0, padx=10, pady=5, sticky="w")
        entrada_costo = tk.Entry(campos_frame, width=35, font=("Segoe UI", 10), bd=1, relief="solid")
        entrada_costo.grid(row=6, column=1, padx=10, pady=5)

        # STOCK
        lbl_stock = tk.Label(campos_frame, text="Stock Inicial:", bg="#FFF0F5", font=("Segoe UI", 10))
        lbl_stock.grid(row=7, column=0, padx=10, pady=5, sticky="w")
        entrada_stock = tk.Entry(campos_frame, width=35, font=("Segoe UI", 10), bd=1, relief="solid")
        entrada_stock.grid(row=7, column=1, padx=10, pady=5)

        def actualizar_visibilidad(*args):
            if tipo_var.get() == "Servicio":
                lbl_prov.grid_remove()
                combo_prov.grid_remove()
                lbl_costo.grid_remove()
                entrada_costo.grid_remove()
                lbl_stock.grid_remove()
                entrada_stock.grid_remove()
                prov_var.set("Ninguno")
                entrada_costo.delete(0, tk.END)
                entrada_costo.insert(0, "0")
                entrada_stock.delete(0, tk.END)
                entrada_stock.insert(0, "0")
            else:
                lbl_prov.grid()
                combo_prov.grid()
                lbl_costo.grid()
                entrada_costo.grid()
                lbl_stock.grid()
                entrada_stock.grid()
                
            if prov_var.get() != "Ninguno" and tipo_var.get() == "Fisico":
                lbl_costo.config(text="Costo/Pago Prov:")
            else:
                lbl_costo.config(text="Costo:")

        tipo_var.trace_add("write", actualizar_visibilidad)
        prov_var.trace_add("write", actualizar_visibilidad)
        actualizar_visibilidad()

        def registrar():
            codigo = entrada_codigo.get().strip()
            nombre = entrada_nombre.get().strip()
            descripcion = entrada_descripcion.get().strip()
            precio_str = entrada_precio.get().strip()
            costo_str = entrada_costo.get().strip()
            stock_str = entrada_stock.get().strip()

            if not codigo or not nombre or not precio_str:
                messagebox.showwarning("Campos vacíos", "El código, nombre y precio son obligatorios.", parent=ventana_registro)
                return

            try:
                precio = float(precio_str)
                costo = float(costo_str) if costo_str else 0.0
                stock = int(stock_str) if stock_str else 0
                
                codigo_formateado = codigo.zfill(5)
                tipo = tipo_var.get()
                prov_id = None
                if prov_var.get() != "Ninguno" and tipo == "Fisico":
                    prov_id = int(prov_var.get().split(" - ")[0])
                
                if guardar_producto(codigo_formateado, nombre, precio, costo, stock, tipo, prov_id, descripcion):
                    messagebox.showinfo("Éxito", "Producto registrado exitosamente.", parent=ventana_registro)
                    ventana_registro.destroy()
                    cargar_tabla()
                
            except ValueError:
                messagebox.showerror("Error", "Introduce valores numéricos válidos para Precio, Costo y Stock.", parent=ventana_registro)

        crear_boton_moderno(ventana_registro, "Guardar", "✅", "#55efc4", registrar).pack(pady=15, padx=20)

    def editar_producto():
        seleccionado = tabla.focus()
        if not seleccionado:
            messagebox.showwarning("Aviso", "Selecciona un producto para editar.")
            return

        valores = tabla.item(seleccionado)["values"]
        id_producto = valores[0]
        codigo = valores[1]
        nombre = valores[2]
        
        # OBTENER DATOS COMPLETOS DE BD PARA DESCRIPCION (YA QUE NO ESTA EN TABLA)
        conn = conectar_db()
        cur = conn.cursor()
        cur.execute("SELECT descripcion, tipo_producto, proveedor_id, precio, costo, stock FROM productos WHERE id=?", (id_producto,))
        row = cur.fetchone()
        conn.close()
        if not row: return
        
        descripcion = row[0] or ""
        tipo_val = row[1] or "Fisico"
        prov_id_val = row[2]
        precio_val = row[3]
        costo_val = row[4]
        stock_val = row[5]

        ventana_edicion = tk.Toplevel(ventana)
        ventana_edicion.title("Editar producto")
        ventana_edicion.geometry("420x520")
        ventana_edicion.configure(bg="#FFF0F5")
        ventana_edicion.transient(ventana)
        ventana_edicion.grab_set()

        ventana_edicion.update_idletasks()
        x_offset = ventana.winfo_x() + (ventana.winfo_width() // 2) - (420 // 2)
        y_offset = ventana.winfo_y() + (ventana.winfo_height() // 2) - (520 // 2)
        ventana_edicion.geometry(f"420x520+{x_offset}+{y_offset}")

        tk.Label(ventana_edicion, text="Editar Producto", font=("Segoe UI", 14, "bold"), bg="#FFF0F5", fg="#e84393").pack(pady=10)

        campos_frame = tk.Frame(ventana_edicion, bg="#FFF0F5")
        campos_frame.pack(pady=10)
        
        # 1. TIPO
        tk.Label(campos_frame, text="Tipo:", bg="#FFF0F5", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, padx=10, pady=5, sticky="w")
        tipo_var = tk.StringVar(value=tipo_val)
        combo_tipo = ttk.Combobox(campos_frame, textvariable=tipo_var, values=["Fisico", "Servicio"], state="readonly", width=33)
        combo_tipo.grid(row=0, column=1, padx=10, pady=5)

        # CÓDIGO
        lbl_codigo = tk.Label(campos_frame, text="Código:", bg="#FFF0F5", font=("Segoe UI", 10))
        lbl_codigo.grid(row=1, column=0, padx=10, pady=5, sticky="w")
        entrada_codigo = tk.Entry(campos_frame, width=35, font=("Segoe UI", 10), bd=1, relief="solid")
        entrada_codigo.insert(0, codigo)
        entrada_codigo.config(state="readonly")
        entrada_codigo.grid(row=1, column=1, padx=10, pady=5)

        # NOMBRE
        lbl_nombre = tk.Label(campos_frame, text="Nombre:", bg="#FFF0F5", font=("Segoe UI", 10))
        lbl_nombre.grid(row=2, column=0, padx=10, pady=5, sticky="w")
        entrada_nombre = tk.Entry(campos_frame, width=35, font=("Segoe UI", 10), bd=1, relief="solid")
        entrada_nombre.insert(0, nombre)
        entrada_nombre.grid(row=2, column=1, padx=10, pady=5)
        
        # DESCRIPCIÓN
        lbl_descripcion = tk.Label(campos_frame, text="Descripción:", bg="#FFF0F5", font=("Segoe UI", 10))
        lbl_descripcion.grid(row=3, column=0, padx=10, pady=5, sticky="w")
        entrada_descripcion = tk.Entry(campos_frame, width=35, font=("Segoe UI", 10), bd=1, relief="solid")
        entrada_descripcion.insert(0, descripcion)
        entrada_descripcion.grid(row=3, column=1, padx=10, pady=5)

        # PRECIO
        lbl_precio = tk.Label(campos_frame, text="Precio Venta:", bg="#FFF0F5", font=("Segoe UI", 10))
        lbl_precio.grid(row=4, column=0, padx=10, pady=5, sticky="w")
        entrada_precio = tk.Entry(campos_frame, width=35, font=("Segoe UI", 10), bd=1, relief="solid")
        entrada_precio.insert(0, str(precio_val))
        entrada_precio.grid(row=4, column=1, padx=10, pady=5)

        # PROVEEDOR
        lbl_prov = tk.Label(campos_frame, text="Proveedor:", bg="#FFF0F5", font=("Segoe UI", 10))
        lbl_prov.grid(row=5, column=0, padx=10, pady=5, sticky="w")
        proveedores = obtener_proveedores()
        lista_prov = ["Ninguno"] + [f"{p[0]} - {p[1]}" for p in proveedores]
        
        prov_var_val = "Ninguno"
        if prov_id_val:
            for p in proveedores:
                if p[0] == prov_id_val:
                    prov_var_val = f"{p[0]} - {p[1]}"
                    break
                    
        prov_var = tk.StringVar(value=prov_var_val)
        combo_prov = ttk.Combobox(campos_frame, textvariable=prov_var, values=lista_prov, state="readonly", width=33)
        combo_prov.grid(row=5, column=1, padx=10, pady=5)
        
        # COSTO
        lbl_costo = tk.Label(campos_frame, text="Costo:", bg="#FFF0F5", font=("Segoe UI", 10))
        lbl_costo.grid(row=6, column=0, padx=10, pady=5, sticky="w")
        entrada_costo = tk.Entry(campos_frame, width=35, font=("Segoe UI", 10), bd=1, relief="solid")
        entrada_costo.insert(0, str(costo_val))
        entrada_costo.grid(row=6, column=1, padx=10, pady=5)

        # STOCK
        lbl_stock = tk.Label(campos_frame, text="Stock Inicial:", bg="#FFF0F5", font=("Segoe UI", 10))
        lbl_stock.grid(row=7, column=0, padx=10, pady=5, sticky="w")
        entrada_stock = tk.Entry(campos_frame, width=35, font=("Segoe UI", 10), bd=1, relief="solid")
        entrada_stock.insert(0, str(stock_val))
        entrada_stock.grid(row=7, column=1, padx=10, pady=5)

        def actualizar_visibilidad(*args):
            if tipo_var.get() == "Servicio":
                lbl_prov.grid_remove()
                combo_prov.grid_remove()
                lbl_costo.grid_remove()
                entrada_costo.grid_remove()
                lbl_stock.grid_remove()
                entrada_stock.grid_remove()
            else:
                lbl_prov.grid()
                combo_prov.grid()
                lbl_costo.grid()
                entrada_costo.grid()
                lbl_stock.grid()
                entrada_stock.grid()
                
            if prov_var.get() != "Ninguno" and tipo_var.get() == "Fisico":
                lbl_costo.config(text="Costo/Pago Prov:")
            else:
                lbl_costo.config(text="Costo:")

        tipo_var.trace_add("write", actualizar_visibilidad)
        prov_var.trace_add("write", actualizar_visibilidad)
        actualizar_visibilidad()

        def guardar():
            nombre_nuevo = entrada_nombre.get().strip()
            descripcion = entrada_descripcion.get().strip()
            precio_str = entrada_precio.get().strip()
            costo_str = entrada_costo.get().strip()
            stock_str = entrada_stock.get().strip()

            if not nombre_nuevo or not precio_str:
                messagebox.showwarning("Campos vacíos", "El nombre y precio son obligatorios.", parent=ventana_edicion)
                return

            try:
                precio_nuevo = float(precio_str)
                costo_nuevo = float(costo_str) if costo_str else 0.0
                stock_nuevo = int(stock_str) if stock_str else 0
                
                tipo_nuevo = tipo_var.get()
                prov_id_nuevo = None
                if prov_var.get() != "Ninguno" and tipo_nuevo == "Fisico":
                    prov_id_nuevo = int(prov_var.get().split(" - ")[0])
                
                if actualizar_producto(id_producto, nombre_nuevo, precio_nuevo, costo_nuevo, stock_nuevo, tipo_nuevo, prov_id_nuevo, descripcion):
                    messagebox.showinfo("Éxito", "Producto actualizado exitosamente.", parent=ventana_edicion)
                    ventana_edicion.destroy()
                    cargar_tabla()
            except ValueError:
                messagebox.showerror("Error", "Introduce valores numéricos válidos.", parent=ventana_edicion)

        crear_boton_moderno(ventana_edicion, "Guardar Cambios", "💾", "#55efc4", guardar).pack(pady=15, padx=20)

    def eliminar_producto_seleccionado():'''

new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)

with open("interface/inventario_menu.py", "w") as f:
    f.write(new_content)
