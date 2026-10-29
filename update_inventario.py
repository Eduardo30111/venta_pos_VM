content = '''import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from client.api_client import api

# 💵 Formato de pesos colombianos
def formato_peso(valor):
    if valor is None or valor == "":
        return "$0 COP"
    try:
        val_float = float(valor)
        return f"${val_float:,.0f} COP"
    except:
        return "$0 COP"

def limpiar_precio(texto):
    """Limpia una cadena de texto para extraer un valor numérico flotante."""
    texto = str(texto).replace("$", "").replace("COP", "").replace(",", "").strip()
    try:
        return float(texto)
    except ValueError:
        return 0.0

def guardar_producto(codigo, nombre, precio, costo, stock, tipo_producto="Fisico", proveedor_id=None, descripcion=""):
    try:
        if tipo_producto == "Servicio":
            payload = {
                "codigo": codigo,
                "nombre": nombre,
                "descripcion": descripcion,
                "precio_venta": precio,
                "costo_proveedor": costo,
                "tipo_servicio": "General",
                "genera_comision": False
            }
            resp = api.post("/servicios", json=payload)
        else:
            payload = {
                "codigo": codigo,
                "nombre": nombre,
                "descripcion": descripcion,
                "precio_venta": precio,
                "precio_costo": costo,
                "stock": stock,
                "proveedor_id": proveedor_id
            }
            resp = api.post("/productos", json=payload)
            
        if resp.status_code not in (200, 201):
            detail = resp.text
            try:
                detail = resp.json().get("detail", resp.text)
            except:
                pass
            messagebox.showerror("Error al Guardar", f"El servidor respondió con error ({resp.status_code}):\\n{detail}")
            return False
        return True
    except Exception as e:
        messagebox.showerror("Error de Conexión", f"Error al guardar producto: {e}")
        return False

def actualizar_producto(id_producto, nombre, precio, costo, stock, tipo_producto="Fisico", proveedor_id=None, descripcion=""):
    try:
        if tipo_producto == "Servicio":
            payload = {
                "nombre": nombre,
                "descripcion": descripcion,
                "precio_venta": precio,
                "costo_proveedor": costo,
                "tipo_servicio": "General",
                "genera_comision": False
            }
            resp = api.put(f"/servicios/{id_producto}", json=payload)
        else:
            payload = {
                "nombre": nombre,
                "descripcion": descripcion,
                "precio_venta": precio,
                "precio_costo": costo,
                "stock": stock,
                "proveedor_id": proveedor_id
            }
            resp = api.put(f"/productos/{id_producto}", json=payload)
            
        if resp.status_code not in (200, 204):
            detail = resp.text
            try:
                detail = resp.json().get("detail", resp.text)
            except:
                pass
            messagebox.showerror("Error al Actualizar", f"El servidor respondió con error ({resp.status_code}):\\n{detail}")
            return False
        return True
    except Exception as e:
        messagebox.showerror("Error de Conexión", f"Error al actualizar producto: {e}")
        return False

def eliminar_producto(id_producto, tipo="Fisico"):
    try:
        if tipo == "Servicio":
            resp = api.delete(f"/servicios/{id_producto}")
        else:
            resp = api.delete(f"/productos/{id_producto}")
            
        if resp.status_code not in (200, 204):
            detail = resp.text
            try:
                detail = resp.json().get("detail", resp.text)
            except:
                pass
            messagebox.showerror("Error al Eliminar", f"El servidor respondió con error ({resp.status_code}):\\n{detail}")
            return False
        return True
    except Exception as e:
        messagebox.showerror("Error de Conexión", f"Error al eliminar: {e}")
        return False

def obtener_productos():
    try:
        r_prod = api.get("/productos?size=1000")
        r_serv = api.get("/servicios?size=1000")
        
        productos_data = r_prod.json() if hasattr(r_prod, "json") and r_prod.status_code == 200 else {}
        servicios_data = r_serv.json() if hasattr(r_serv, "json") and r_serv.status_code == 200 else {}
        
        productos = productos_data.get("items", []) if isinstance(productos_data, dict) else (productos_data if isinstance(productos_data, list) else [])
        servicios = servicios_data.get("items", []) if isinstance(servicios_data, dict) else (servicios_data if isinstance(servicios_data, list) else [])
        
        resultados = []
        for p in productos:
            prov_nombre = p.get("proveedor", {}).get("nombre") if p.get("proveedor") else "Ninguno"
            stock_val = p.get("stock", 0)
            try:
                stock_fmt = int(stock_val) if float(stock_val).is_integer() else stock_val
            except:
                stock_fmt = stock_val
            resultados.append((p.get("id"), p.get("codigo"), p.get("nombre"), p.get("precio_venta", 0.0), p.get("precio_costo", 0.0), stock_fmt, "Fisico", prov_nombre))
            
        for s in servicios:
            costo = s.get("costo_proveedor", 0.0)
            resultados.append((s.get("id"), s.get("codigo"), s.get("nombre"), s.get("precio_venta", 0.0), costo, 0, "Servicio", "Ninguno"))
            
        return resultados
    except Exception as e:
        messagebox.showerror("Error", f"Error al obtener catálogo: {e}")
        return []

def obtener_proveedores():
    try:
        r_prov = api.get("/proveedores?size=1000")
        proveedores_data = r_prov.json() if hasattr(r_prov, "json") and r_prov.status_code == 200 else {}
        proveedores = proveedores_data.get("items", []) if isinstance(proveedores_data, dict) else (proveedores_data if isinstance(proveedores_data, list) else [])
        return [(p.get("id"), p.get("nombre")) for p in proveedores]
    except:
        return []

def mostrar_modal_crear_proveedor(combo, prov_var):
    modal = tk.Toplevel()
    modal.title("Nuevo Proveedor")
    modal.geometry("320x220")
    modal.configure(bg="#FFF0F5")
    modal.grab_set()

    tk.Label(modal, text="Nombre del Proveedor:", bg="#FFF0F5", font=("Segoe UI", 10, "bold")).pack(pady=(15, 2))
    entry_nom = tk.Entry(modal, width=30, font=("Segoe UI", 10))
    entry_nom.pack(pady=5)
    
    tk.Label(modal, text="Documento / NIT:", bg="#FFF0F5", font=("Segoe UI", 10)).pack(pady=(5, 2))
    entry_nit = tk.Entry(modal, width=30, font=("Segoe UI", 10))
    entry_nit.pack(pady=5)

    def guardar():
        nombre = entry_nom.get().strip()
        nit = entry_nit.get().strip() or "0"
        if not nombre:
            messagebox.showwarning("Error", "El nombre es obligatorio", parent=modal)
            return
        
        try:
            resp = api.post("/proveedores", json={"nombre": nombre, "documento_nit": nit, "telefono": "", "email": "", "direccion": "", "contacto": ""})
            if resp.status_code in (200, 201):
                messagebox.showinfo("Éxito", f"Proveedor '{nombre}' creado", parent=modal)
                provs = obtener_proveedores()
                nueva_lista = ["Ninguno"] + [f"{p[0]} - {p[1]}" for p in provs]
                combo["values"] = nueva_lista
                # Seleccionar el recién creado
                for p in provs:
                    if p[1] == nombre:
                        prov_var.set(f"{p[0]} - {p[1]}")
                        break
                modal.destroy()
            else:
                messagebox.showerror("Error", f"No se pudo crear el proveedor: {resp.text}", parent=modal)
        except Exception as e:
            messagebox.showerror("Error", f"Fallo al conectar: {e}", parent=modal)

    tk.Button(modal, text="Guardar Proveedor", command=guardar, bg="#4CAF50", fg="white", font=("Segoe UI", 10, "bold"), cursor="hand2").pack(pady=15)

# 🖥️ Interfaz principal
def iniciar_inventario():
    ventana = tk.Tk()
    ventana.title("Inventario - VmPOS")
    ventana.geometry("1020x680")
    ventana.resizable(True, True)
    ventana.configure(bg="#ff9ff3")

    ventana.update_idletasks()
    x = (ventana.winfo_screenwidth() // 2) - (1020 // 2)
    y = (ventana.winfo_screenheight() // 2) - (680 // 2)
    ventana.geometry(f"1020x680+{x}+{y}")

    # 🎨 Header principal
    header_frame = tk.Frame(ventana, bg="#e84393")
    header_frame.pack(fill="x")

    header_left = tk.Frame(header_frame, bg="#e84393")
    header_left.pack(side="left", fill="y", padx=30)

    tk.Label(header_left, text="🎀", font=("Segoe UI Emoji", 28), bg="#e84393", fg="white").pack(side="left", pady=15)
    tk.Label(header_left, text="INVENTARIO", font=("Segoe UI", 24, "bold"), bg="#e84393", fg="white").pack(side="left", padx=(10, 0), pady=18)
    tk.Label(header_left, text="Gestión de Productos y Servicios", font=("Segoe UI", 12), bg="#e84393", fg="#ffd3e8").pack(side="left", padx=(15, 0), pady=20)

    header_right = tk.Frame(header_frame, bg="#e84393")
    header_right.pack(side="right", fill="y", padx=30)

    lbl_fecha = tk.Label(header_right, text="", font=("Segoe UI", 10), bg="#e84393", fg="#ffd3e8")
    lbl_fecha.pack(anchor="e", pady=(12, 2))

    lbl_hora = tk.Label(header_right, text="", font=("Segoe UI", 10), bg="#e84393", fg="#ffd3e8")
    lbl_hora.pack(anchor="e")

    def actualizar_tiempo():
        ahora = datetime.now()
        lbl_fecha.config(text=f"📅 {ahora.strftime('%d/%m/%Y')}")
        lbl_hora.config(text=f"🕐 {ahora.strftime('%H:%M:%S')}")
        ventana.after(1000, actualizar_tiempo)

    actualizar_tiempo()

    main_content = tk.Frame(ventana, bg="#ffeaa7")
    main_content.pack(fill="both", expand=True, padx=20, pady=20)

    def cargar_tabla():
        """Carga los productos en la tabla correspondiente"""
        try:
            for item in tabla.get_children():
                tabla.delete(item)
            for item in tabla_servicios.get_children():
                tabla_servicios.delete(item)
            
            items = obtener_productos()
            for producto in items:
                id_item, codigo, nombre, precio, costo, stock, tipo, prov = producto
                if prov is None: prov = "Ninguno"
                if tipo is None: tipo = "Fisico"
                
                if tipo == "Servicio":
                    # Columnas Servicio: Id, Código, Servicio, Precio, Costo
                    tabla_servicios.insert("", "end", values=(
                        id_item, codigo, nombre, formato_peso(precio), formato_peso(costo)
                    ))
                else:
                    # Columnas Fisico: Id, Código, Producto, Precio, Costo, Stock
                    tabla.insert("", "end", values=(
                        id_item, codigo, nombre, formato_peso(precio), formato_peso(costo), stock
                    ))
        except Exception as e:
            messagebox.showerror("Error", f"Error al cargar tabla: {e}")

    def crear_boton_moderno(parent, texto, icono, color, comando):
        btn_frame = tk.Frame(parent, bg="#ffeaa7")
        btn_frame.pack(fill="x", padx=10, pady=5)

        btn = tk.Button(btn_frame, text=f"{icono}  {texto}",
                        font=("Segoe UI", 12, "bold"), bg=color, fg="white",
                        bd=0, pady=10, cursor="hand2", command=comando,
                        relief="flat", anchor="w", padx=15)
        btn.pack(fill="x")

        color_hover = {
            "#fd79a8": "#e84393",
            "#74b9ff": "#6c5ce7",
            "#55efc4": "#00b894",
            "#ff7675": "#e17055",
            "#a29bfe": "#6c5ce7",
            "#fdcb6e": "#f39c12"
        }.get(color, "#e84393")

        def on_enter(e):
            btn.config(bg=color_hover)
        def on_leave(e):
            btn.config(bg=color)

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        return btn

    def abrir_ventana_registro():
        ventana_registro = tk.Toplevel(ventana)
        ventana_registro.title("Registrar Nuevo Ítem")
        ventana_registro.geometry("450x540")
        ventana_registro.configure(bg="#FFF0F5")
        ventana_registro.transient(ventana)
        ventana_registro.grab_set()

        ventana_registro.update_idletasks()
        x_offset = ventana.winfo_x() + (ventana.winfo_width() // 2) - (450 // 2)
        y_offset = ventana.winfo_y() + (ventana.winfo_height() // 2) - (540 // 2)
        ventana_registro.geometry(f"450x540+{x_offset}+{y_offset}")

        tk.Label(ventana_registro, text="Nuevo Registro", font=("Segoe UI", 14, "bold"), 
                bg="#FFF0F5", fg="#e84393").pack(pady=10)

        campos_frame = tk.Frame(ventana_registro, bg="#FFF0F5")
        campos_frame.pack(pady=10)
        
        # 1. TIPO (Determina automáticamente si estamos en la pestaña de Servicios)
        tab_actual = notebook.index("current")
        tipo_defecto = "Servicio" if tab_actual == 1 else "Fisico"
        
        tk.Label(campos_frame, text="Tipo:", bg="#FFF0F5", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, padx=10, pady=5, sticky="w")
        tipo_var = tk.StringVar(value=tipo_defecto)
        combo_tipo = ttk.Combobox(campos_frame, textvariable=tipo_var, values=["Fisico", "Servicio"], state="readonly", width=33)
        combo_tipo.grid(row=0, column=1, padx=10, pady=5)
        
        def sugerir_codigo(tipo_sel):
            try:
                if tipo_sel == "Servicio":
                    r = api.get("/servicios?size=1000")
                    items = r.json().get("items", []) if r.status_code == 200 else []
                    max_num = 0
                    for s in items:
                        c = s.get("codigo", "")
                        num = c[1:] if str(c).startswith("S") else c
                        if str(num).isdigit():
                            max_num = max(max_num, int(num))
                    return f"S{max_num + 1:05d}"
                else:
                    r = api.get("/productos?size=1000")
                    items = r.json().get("items", []) if r.status_code == 200 else []
                    max_num = 0
                    for p in items:
                        c = p.get("codigo", "")
                        if str(c).isdigit():
                            max_num = max(max_num, int(c))
                    return f"{max_num + 1:05d}"
            except:
                return "S00001" if tipo_sel == "Servicio" else "00001"

        # CÓDIGO
        lbl_codigo = tk.Label(campos_frame, text="Código:", bg="#FFF0F5", font=("Segoe UI", 10))
        lbl_codigo.grid(row=1, column=0, padx=10, pady=5, sticky="w")
        entrada_codigo = tk.Entry(campos_frame, width=35, font=("Segoe UI", 10), bd=1, relief="solid")
        entrada_codigo.insert(0, sugerir_codigo(tipo_defecto))
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
        btn_nuevo_prov = tk.Button(campos_frame, text="➕ Nuevo", command=lambda: mostrar_modal_crear_proveedor(combo_prov, prov_var), cursor="hand2")
        btn_nuevo_prov.grid(row=5, column=2, padx=5, pady=5)
        
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
            tipo_actual = combo_tipo.get()
            if tipo_actual == "Servicio":
                lbl_prov.grid_remove()
                combo_prov.grid_remove()
                btn_nuevo_prov.grid_remove()
                lbl_stock.grid_remove()
                entrada_stock.grid_remove()
                prov_var.set("Ninguno")
                entrada_stock.delete(0, tk.END)
                entrada_stock.insert(0, "0")
                lbl_costo.config(text="Costo:")
            else:
                lbl_prov.grid()
                combo_prov.grid()
                btn_nuevo_prov.grid()
                lbl_stock.grid()
                entrada_stock.grid()
                if combo_prov.get() != "Ninguno":
                    lbl_costo.config(text="Costo/Pago Prov:")
                else:
                    lbl_costo.config(text="Costo:")
            
            # Actualizar sugerencia de código
            cod = sugerir_codigo(tipo_actual)
            entrada_codigo.delete(0, tk.END)
            entrada_codigo.insert(0, cod)

        tipo_var.trace_add("write", actualizar_visibilidad)
        prov_var.trace_add("write", actualizar_visibilidad)
        
        def _on_tipo_select(e):
            combo_tipo.after(50, actualizar_visibilidad)
        def _on_prov_select(e):
            combo_prov.after(50, actualizar_visibilidad)
            
        combo_tipo.bind("<<ComboboxSelected>>", _on_tipo_select)
        combo_prov.bind("<<ComboboxSelected>>", _on_prov_select)
        
        actualizar_visibilidad()

        def registrar():
            codigo = entrada_codigo.get().strip()
            nombre = entrada_nombre.get().strip()
            descripcion = entrada_descripcion.get().strip()
            precio_str = entrada_precio.get().strip()
            costo_str = entrada_costo.get().strip()
            stock_str = entrada_stock.get().strip()

            if not codigo or not nombre or not precio_str:
                messagebox.showwarning("Campos Vacíos", "El código, nombre y precio son obligatorios.", parent=ventana_registro)
                return

            try:
                precio = float(precio_str)
                costo = float(costo_str) if costo_str else 0.0
                tipo = tipo_var.get()
                stock = int(float(stock_str)) if stock_str and tipo == "Fisico" else 0
                
                prov_id = None
                if prov_var.get() != "Ninguno" and tipo == "Fisico":
                    prov_id = int(prov_var.get().split(" - ")[0])
                
                if guardar_producto(codigo, nombre, precio, costo, stock, tipo, prov_id, descripcion):
                    messagebox.showinfo("Éxito", f"'{nombre}' registrado exitosamente.", parent=ventana_registro)
                    ventana_registro.destroy()
                    cargar_tabla()
                    # Cambiar a la pestaña correspondiente
                    if tipo == "Servicio":
                        notebook.select(tab_servicios)
                    else:
                        notebook.select(tab_fisicos)
                
            except ValueError:
                messagebox.showerror("Error", "Introduce valores numéricos válidos para Precio, Costo y Stock.", parent=ventana_registro)

        crear_boton_moderno(ventana_registro, "Guardar", "✅", "#55efc4", registrar).pack(pady=15, padx=20)

    def editar_producto():
        tab_actual = notebook.index("current")
        active_table = tabla if tab_actual == 0 else tabla_servicios
        
        sel = active_table.selection()
        if not sel:
            nombre_tab = "un producto físico" if tab_actual == 0 else "un servicio"
            messagebox.showwarning("Aviso", f"Por favor, haz clic en la fila de {nombre_tab} que deseas editar.")
            return

        seleccionado = sel[0]
        valores = active_table.item(seleccionado)["values"]
        id_producto = valores[0]
        codigo = valores[1]
        nombre = valores[2]
        tipo_producto = "Fisico" if tab_actual == 0 else "Servicio"
        
        try:
            if tipo_producto == "Servicio":
                resp = api.get(f"/servicios/{id_producto}")
                if resp.status_code != 200:
                    messagebox.showerror("Error", f"No se pudo cargar el servicio ({resp.status_code}):\\n{resp.text}")
                    return
                data = resp.json()
                descripcion = data.get("descripcion") or ""
                prov_id_val = None
                precio_val = data.get("precio_venta", 0.0)
                costo_val = data.get("costo_proveedor", 0.0)
                stock_val = 0
            else:
                resp = api.get(f"/productos/{id_producto}")
                if resp.status_code != 200:
                    messagebox.showerror("Error", f"No se pudo cargar el producto ({resp.status_code}):\\n{resp.text}")
                    return
                data = resp.json()
                descripcion = data.get("descripcion") or ""
                prov_id_val = data.get("proveedor_id")
                precio_val = data.get("precio_venta", 0.0)
                costo_val = data.get("precio_costo", 0.0)
                stock_val = data.get("stock", 0)
        except Exception as e:
            messagebox.showerror("Error", f"Error al obtener datos: {e}")
            return

        ventana_edicion = tk.Toplevel(ventana)
        ventana_edicion.title(f"Editar {tipo_producto}")
        ventana_edicion.geometry("450x540")
        ventana_edicion.configure(bg="#FFF0F5")
        ventana_edicion.transient(ventana)
        ventana_edicion.grab_set()

        ventana_edicion.update_idletasks()
        x_offset = ventana.winfo_x() + (ventana.winfo_width() // 2) - (450 // 2)
        y_offset = ventana.winfo_y() + (ventana.winfo_height() // 2) - (540 // 2)
        ventana_edicion.geometry(f"450x540+{x_offset}+{y_offset}")

        tk.Label(ventana_edicion, text=f"Editar {tipo_producto}", font=("Segoe UI", 14, "bold"), bg="#FFF0F5", fg="#e84393").pack(pady=10)

        campos_frame = tk.Frame(ventana_edicion, bg="#FFF0F5")
        campos_frame.pack(pady=10)
        
        # 1. TIPO
        tk.Label(campos_frame, text="Tipo:", bg="#FFF0F5", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, padx=10, pady=5, sticky="w")
        tipo_var = tk.StringVar(value=tipo_producto)
        combo_tipo = ttk.Combobox(campos_frame, textvariable=tipo_var, values=["Fisico", "Servicio"], state="disabled", width=33)
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
        btn_nuevo_prov_ed = tk.Button(campos_frame, text="➕ Nuevo", command=lambda: mostrar_modal_crear_proveedor(combo_prov, prov_var), cursor="hand2")
        btn_nuevo_prov_ed.grid(row=5, column=2, padx=5, pady=5)
        
        # COSTO
        lbl_costo = tk.Label(campos_frame, text="Costo:", bg="#FFF0F5", font=("Segoe UI", 10))
        lbl_costo.grid(row=6, column=0, padx=10, pady=5, sticky="w")
        entrada_costo = tk.Entry(campos_frame, width=35, font=("Segoe UI", 10), bd=1, relief="solid")
        entrada_costo.insert(0, str(costo_val))
        entrada_costo.grid(row=6, column=1, padx=10, pady=5)

        # STOCK
        lbl_stock = tk.Label(campos_frame, text="Stock Actual:", bg="#FFF0F5", font=("Segoe UI", 10))
        lbl_stock.grid(row=7, column=0, padx=10, pady=5, sticky="w")
        entrada_stock = tk.Entry(campos_frame, width=35, font=("Segoe UI", 10), bd=1, relief="solid")
        try:
            stock_clean = int(stock_val) if float(stock_val).is_integer() else stock_val
        except:
            stock_clean = stock_val
        entrada_stock.insert(0, str(stock_clean))
        entrada_stock.grid(row=7, column=1, padx=10, pady=5)

        # Ocultar campos de stock y proveedor si es servicio
        if tipo_producto == "Servicio":
            lbl_prov.grid_remove()
            combo_prov.grid_remove()
            btn_nuevo_prov_ed.grid_remove()
            lbl_stock.grid_remove()
            entrada_stock.grid_remove()

        def guardar():
            nombre_nuevo = entrada_nombre.get().strip()
            descripcion_nueva = entrada_descripcion.get().strip()
            precio_str = entrada_precio.get().strip()
            costo_str = entrada_costo.get().strip()
            stock_str = entrada_stock.get().strip()

            if not nombre_nuevo or not precio_str:
                messagebox.showwarning("Campos Vacíos", "El nombre y precio son obligatorios.", parent=ventana_edicion)
                return

            try:
                precio_nuevo = float(precio_str)
                costo_nuevo = float(costo_str) if costo_str else 0.0
                stock_nuevo = int(float(stock_str)) if stock_str and tipo_producto == "Fisico" else 0
                
                prov_id_nuevo = None
                if prov_var.get() != "Ninguno" and tipo_producto == "Fisico":
                    prov_id_nuevo = int(combo_prov.get().split(" - ")[0])
                
                if actualizar_producto(id_producto, nombre_nuevo, precio_nuevo, costo_nuevo, stock_nuevo, tipo_producto, prov_id_nuevo, descripcion_nueva):
                    messagebox.showinfo("Éxito", f"'{nombre_nuevo}' actualizado exitosamente.", parent=ventana_edicion)
                    ventana_edicion.destroy()
                    cargar_tabla()
            except ValueError:
                messagebox.showerror("Error", "Introduce valores numéricos válidos para Precio, Costo o Stock.", parent=ventana_edicion)

        crear_boton_moderno(ventana_edicion, "Guardar Cambios", "💾", "#55efc4", guardar).pack(pady=15, padx=20)

    def eliminar_producto_seleccionado():
        tab_actual = notebook.index("current")
        active_table = tabla if tab_actual == 0 else tabla_servicios
        
        sel = active_table.selection()
        if not sel:
            nombre_tab = "un producto físico" if tab_actual == 0 else "un servicio"
            messagebox.showwarning("Aviso", f"Por favor, haz clic en la fila de {nombre_tab} que deseas eliminar.")
            return

        seleccionado = sel[0]
        valores = active_table.item(seleccionado)["values"]
        id_producto = valores[0]
        nombre_producto = valores[2]
        tipo_producto = "Fisico" if tab_actual == 0 else "Servicio"

        confirmacion = messagebox.askyesno("Confirmar Eliminación", 
                                         f"¿Estás seguro de que quieres eliminar {tipo_producto.lower()} '{nombre_producto}'?\\nEsta acción no se puede deshacer.", 
                                         icon="warning")
        if confirmacion:
            if eliminar_producto(id_producto, tipo_producto):
                messagebox.showinfo("Eliminado", f"{tipo_producto} '{nombre_producto}' eliminado correctamente.")
                cargar_tabla()

    # Panel lateral de acciones
    panel_acciones = tk.Frame(main_content, bg="white", bd=3, relief="solid")
    panel_acciones.pack(side="left", fill="y", padx=(0, 10), pady=0)

    tk.Label(panel_acciones, text="⚙️ ACCIONES", font=("Segoe UI", 14, "bold"), bg="white", fg="#e84393").pack(pady=20, padx=10)

    crear_boton_moderno(panel_acciones, "Registrar", "➕", "#fd79a8", abrir_ventana_registro)
    crear_boton_moderno(panel_acciones, "Editar", "✏️", "#74b9ff", editar_producto)
    crear_boton_moderno(panel_acciones, "Eliminar", "🗑️", "#ff7675", eliminar_producto_seleccionado)
    crear_boton_moderno(panel_acciones, "Actualizar", "🔄", "#a29bfe", cargar_tabla)

    # Frame de Tablas
    frame_tabla = tk.Frame(main_content, bg="white", bd=3, relief="solid")
    frame_tabla.pack(side="right", fill="both", expand=True, pady=0, padx=0)

    tk.Label(frame_tabla, text="📦 GESTIÓN DE CATÁLOGO", font=("Segoe UI", 14, "bold"), bg="white", fg="#e84393").pack(pady=15)

    style = ttk.Style()
    style.theme_use('clam')
    style.configure("Treeview", background="white", foreground="#2d3436", rowheight=28, fieldbackground="white", font=("Segoe UI", 10))
    style.map("Treeview", background=[('selected', '#fd79a8')], foreground=[('selected', 'white')])
    style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), background="#e84393", foreground="white", relief="flat")
    style.map("Treeview.Heading", background=[('active', '#e84393')])

    notebook = ttk.Notebook(frame_tabla)
    notebook.pack(fill="both", expand=True, padx=20, pady=10)
    
    tab_fisicos = tk.Frame(notebook, bg="white")
    tab_servicios = tk.Frame(notebook, bg="white")
    
    notebook.add(tab_fisicos, text="📦 Productos Físicos")
    notebook.add(tab_servicios, text="🛠️ Servicios")
    
    # 1. TABLA PRODUCTOS FÍSICOS (Con Stock)
    columnas_f = ("Id", "Código", "Producto", "Precio", "Costo", "Stock")
    tabla = ttk.Treeview(tab_fisicos, columns=columnas_f, show="headings", height=15)
    tabla.heading("Id", text="Id")
    tabla.heading("Código", text="Código")
    tabla.heading("Producto", text="Producto")
    tabla.heading("Precio", text="Precio Venta")
    tabla.heading("Costo", text="Costo")
    tabla.heading("Stock", text="Stock")
    tabla.column("Id", width=50, anchor="center")
    tabla.column("Código", width=90, anchor="center")
    tabla.column("Producto", width=220, anchor="w")
    tabla.column("Precio", width=120, anchor="center")
    tabla.column("Costo", width=120, anchor="center")
    tabla.column("Stock", width=80, anchor="center")
    
    scroll_f = ttk.Scrollbar(tab_fisicos, orient="vertical", command=tabla.yview)
    tabla.configure(yscrollcommand=scroll_f.set)
    tabla.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
    scroll_f.pack(side="right", fill="y", pady=10, padx=(0, 10))

    # 2. TABLA SERVICIOS (Sin Stock)
    columnas_s = ("Id", "Código", "Servicio", "Precio", "Costo")
    tabla_servicios = ttk.Treeview(tab_servicios, columns=columnas_s, show="headings", height=15)
    tabla_servicios.heading("Id", text="Id")
    tabla_servicios.heading("Código", text="Código")
    tabla_servicios.heading("Servicio", text="Servicio")
    tabla_servicios.heading("Precio", text="Precio Venta")
    tabla_servicios.heading("Costo", text="Costo Prov.")
    tabla_servicios.column("Id", width=50, anchor="center")
    tabla_servicios.column("Código", width=90, anchor="center")
    tabla_servicios.column("Servicio", width=260, anchor="w")
    tabla_servicios.column("Precio", width=130, anchor="center")
    tabla_servicios.column("Costo", width=130, anchor="center")
    
    scroll_s = ttk.Scrollbar(tab_servicios, orient="vertical", command=tabla_servicios.yview)
    tabla_servicios.configure(yscrollcommand=scroll_s.set)
    tabla_servicios.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
    scroll_s.pack(side="right", fill="y", pady=10, padx=(0, 10))
    
    # Cargar datos iniciales
    cargar_tabla()

    # 🌸 Footer
    footer = tk.Frame(ventana, bg="#e84393")
    footer.pack(fill="x", side="bottom")

    footer_left = tk.Frame(footer, bg="#e84393")
    footer_left.pack(side="left", padx=20, pady=10)

    footer_right = tk.Frame(footer, bg="#e84393")
    footer_right.pack(side="right", padx=20, pady=10)

    tk.Label(footer_left, text="📍 Puerto Colombia • 📞 +573215545788", font=("Segoe UI", 10), bg="#e84393", fg="white").pack()
    tk.Label(footer_right, text="✨ VmPOS v3.1.0 • Sistema Activo 💖", font=("Segoe UI", 10), bg="#e84393", fg="#ffd3e8").pack()

    ventana.mainloop()

if __name__ == "__main__":
    iniciar_inventario()
'''

with open("interface/inventario_menu.py", "w") as f:
    f.write(content)
print("INVENTARIO OVERWRITTEN")
