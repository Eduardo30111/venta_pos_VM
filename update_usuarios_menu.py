content = '''# -*- coding: utf-8 -*-
"""
Archivo: usuarios_menu.py
Interfaz de gestión de usuarios para VmPOS conectada a la API REST centralizada.
Alineado con el Modelo de Datos de implementation_plan.md
"""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import sys, os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from client.api_client import api

# 🌐 Variables globales
entradas = {}
tabla = None
ventana_usuarios = None
rol_var = None
estado_var = None
tipo_nomina_var = None
salario_diario_var = None
id_usuario_seleccionado = None

def obtener_usuarios():
    """Obtiene la lista de usuarios desde la API REST"""
    try:
        resp = api.get("/usuarios?size=1000")
        if resp.status_code == 200:
            data = resp.json()
            return data.get("items", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        else:
            return []
    except Exception as e:
        print(f"Error al obtener usuarios: {e}")
        return []

def insertar_usuario(usuario, password, rol, estado, comision=0.0, nombre="", apellidos="", tipo_nom="Porcentual", salario=0.0, documento=""):
    """Crea un nuevo usuario a través de la API REST"""
    payload = {
        "usuario": usuario,
        "password": password,
        "rol": rol,
        "estado": estado,
        "nombre": nombre or "",
        "apellidos": apellidos or "",
        "documento": documento or None,
        "tipo_remuneracion": tipo_nom or "Porcentual",
        "salario_diario": float(salario) if salario else 0.0,
        "porcentaje_comision": float(comision) if comision else 0.0
    }
    try:
        resp = api.post("/usuarios", json=payload)
        if resp.status_code in (200, 201):
            return True, "Usuario creado exitosamente"
        else:
            detail = resp.text
            try:
                detail = resp.json().get("detail", resp.text)
            except:
                pass
            return False, f"Error del servidor ({resp.status_code}):\n{detail}"
    except Exception as e:
        return False, f"Error de conexión:\n{e}"

def actualizar_usuario_db(id_usuario, usuario, rol, estado, password=None, comision=0.0, nombre="", apellidos="", tipo_nom="Porcentual", salario=0.0, documento=""):
    """Actualiza un usuario a través de la API REST"""
    payload = {
        "usuario": usuario,
        "rol": rol,
        "estado": estado,
        "nombre": nombre or "",
        "apellidos": apellidos or "",
        "documento": documento or None,
        "tipo_remuneracion": tipo_nom or "Porcentual",
        "salario_diario": float(salario) if salario else 0.0,
        "porcentaje_comision": float(comision) if comision else 0.0
    }
    if password:
        payload["password"] = password

    try:
        resp = api.put(f"/usuarios/{id_usuario}", json=payload)
        if resp.status_code in (200, 204):
            return True, "Usuario actualizado exitosamente"
        else:
            detail = resp.text
            try:
                detail = resp.json().get("detail", resp.text)
            except:
                pass
            return False, f"Error del servidor ({resp.status_code}):\n{detail}"
    except Exception as e:
        return False, f"Error de conexión:\n{e}"

def eliminar_usuario_db(id_usuario):
    """Elimina un usuario a través de la API REST"""
    try:
        resp = api.delete(f"/usuarios/{id_usuario}")
        if resp.status_code in (200, 204):
            return True, "Usuario eliminado correctamente"
        else:
            detail = resp.text
            try:
                detail = resp.json().get("detail", resp.text)
            except:
                pass
            return False, f"Error del servidor ({resp.status_code}):\n{detail}"
    except Exception as e:
        return False, f"Error de conexión:\n{e}"

def actualizar_tabla():
    """Actualiza la tabla con los datos más recientes de la API"""
    global tabla
    if not tabla:
        return

    for item in tabla.get_children():
        tabla.delete(item)

    usuarios = obtener_usuarios()
    for u in usuarios:
        fecha_registro = u.get('fecha_registro', '')
        if isinstance(fecha_registro, str) and fecha_registro:
            try:
                fecha_obj = datetime.fromisoformat(fecha_registro.replace('Z', '+00:00'))
                fecha_formateada = fecha_obj.strftime("%d/%m/%Y %H:%M")
            except:
                fecha_formateada = fecha_registro[:16]
        else:
            fecha_formateada = "No disponible"

        ultimo_acceso = u.get('ultimo_acceso')
        if ultimo_acceso:
            try:
                fecha_obj = datetime.fromisoformat(str(ultimo_acceso).replace('Z', '+00:00'))
                ultimo_acceso = fecha_obj.strftime("%d/%m/%Y %H:%M")
            except:
                ultimo_acceso = str(ultimo_acceso)[:16]
        else:
            ultimo_acceso = "Nunca"

        nombre_completo = f"{u.get('nombre', '')} {u.get('apellidos', '')}".strip() or u.get('usuario')
        remun = f"{u.get('tipo_remuneracion', 'Porcentual')}"
        if u.get('tipo_remuneracion') == 'Fija':
            remun += f" (${u.get('salario_diario', 0):,.0f})"
        else:
            remun += f" ({u.get('porcentaje_comision', 0):.1f}%)"

        valores = (
            u['id'],
            u['usuario'],
            nombre_completo,
            u.get('documento') or "Sin doc",
            u['rol'],
            remun,
            u.get('estado', 'Activo'),
            ultimo_acceso,
            fecha_formateada
        )
        tabla.insert("", "end", values=valores)

def seleccionar_usuario(event):
    """Carga los datos del usuario seleccionado en los campos del formulario"""
    global id_usuario_seleccionado, rol_var, estado_var, tipo_nomina_var, salario_diario_var

    sel = tabla.selection()
    if not sel:
        return

    item_seleccionado = sel[0]
    try:
        valores = tabla.item(item_seleccionado, 'values')
        if not valores:
            return

        id_usuario_seleccionado = int(valores[0])

        limpiar_campos(reset_id=False)

        usuarios = obtener_usuarios()
        for u in usuarios:
            if u['id'] == id_usuario_seleccionado:
                entradas['Usuario'].insert(0, u.get('usuario', ''))
                entradas['Nombre'].insert(0, u.get('nombre', ''))
                entradas['Apellidos'].insert(0, u.get('apellidos', ''))
                entradas['Documento'].insert(0, u.get('documento') or '')

                rol_var.set(u.get('rol', 'Vendedor'))
                estado_var.set(u.get('estado', 'Activo'))

                tipo_nom = u.get('tipo_remuneracion', 'Porcentual')
                tipo_nomina_var.set(tipo_nom)

                if tipo_nom == 'Fija':
                    salario_diario_var.set(str(int(u.get('salario_diario', 0))))
                else:
                    salario_diario_var.set(str(u.get('porcentaje_comision', 0)))
                break
    except Exception as e:
        print(f"Error al seleccionar usuario: {e}")

def guardar_usuario():
    """Guarda o actualiza un usuario"""
    global id_usuario_seleccionado

    usuario = entradas['Usuario'].get().strip()
    password = entradas['Password'].get().strip()
    nombre = entradas['Nombre'].get().strip()
    apellidos = entradas['Apellidos'].get().strip()
    documento = entradas['Documento'].get().strip()

    rol = rol_var.get()
    estado = estado_var.get()
    tipo_nom = tipo_nomina_var.get()

    try:
        valor_nom = float(salario_diario_var.get().replace("$", "").replace(",", "").strip() or 0)
    except ValueError:
        valor_nom = 0.0

    salario = valor_nom if tipo_nom == "Fija" else 0.0
    comision = valor_nom if tipo_nom == "Porcentual" else 0.0

    if not usuario:
        messagebox.showerror("Error", "El campo Usuario es obligatorio.", parent=ventana_usuarios)
        entradas['Usuario'].focus()
        return
    if rol == "Seleccionar" or not rol:
        messagebox.showerror("Error", "Debes seleccionar un rol válido (Administrador, Vendedor, Operario).", parent=ventana_usuarios)
        return
    if estado == "Seleccionar" or not estado:
        messagebox.showerror("Error", "Debes seleccionar un estado.", parent=ventana_usuarios)
        return

    try:
        if id_usuario_seleccionado:
            ok, msg = actualizar_usuario_db(
                id_usuario_seleccionado,
                usuario=usuario,
                rol=rol,
                estado=estado,
                password=password if password else None,
                comision=comision,
                nombre=nombre,
                apellidos=apellidos,
                tipo_nom=tipo_nom,
                salario=salario,
                documento=documento
            )
            if ok:
                messagebox.showinfo("Éxito", f"Usuario '{usuario}' actualizado correctamente.", parent=ventana_usuarios)
                limpiar_campos()
                actualizar_tabla()
            else:
                messagebox.showerror("Error", msg, parent=ventana_usuarios)
        else:
            if not password:
                messagebox.showerror("Error", "La contraseña es obligatoria para un nuevo usuario.", parent=ventana_usuarios)
                entradas['Password'].focus()
                return

            ok, msg = insertar_usuario(
                usuario, password, rol, estado, comision, nombre, apellidos, tipo_nom, salario, documento
            )
            if ok:
                messagebox.showinfo("Éxito", f"Usuario '{usuario}' registrado correctamente.", parent=ventana_usuarios)
                limpiar_campos()
                actualizar_tabla()
            else:
                messagebox.showerror("Error", msg, parent=ventana_usuarios)
    except Exception as e:
        messagebox.showerror("Error", f"Ocurrió un error inesperado:\n{e}", parent=ventana_usuarios)

def eliminar_usuario():
    """Elimina el usuario seleccionado"""
    global id_usuario_seleccionado

    if not id_usuario_seleccionado:
        messagebox.showwarning("Advertencia", "Por favor, selecciona un usuario de la tabla para eliminar.", parent=ventana_usuarios)
        return

    usuario_seleccionado = entradas['Usuario'].get()

    respuesta = messagebox.askyesno(
        "Confirmar Eliminación",
        f"¿Estás seguro de que quieres eliminar al usuario '{usuario_seleccionado}'?\nEsta acción no se puede deshacer.",
        parent=ventana_usuarios
    )

    if not respuesta:
        return

    ok, msg = eliminar_usuario_db(id_usuario_seleccionado)
    if ok:
        messagebox.showinfo("Éxito", f"Usuario '{usuario_seleccionado}' eliminado correctamente.", parent=ventana_usuarios)
        limpiar_campos()
        actualizar_tabla()
    else:
        messagebox.showerror("Error", msg, parent=ventana_usuarios)

def limpiar_campos(reset_id=True):
    """Limpia los campos del formulario"""
    global id_usuario_seleccionado
    if reset_id:
        id_usuario_seleccionado = None

    for campo in ["Usuario", "Password", "Nombre", "Apellidos", "Documento"]:
        if campo in entradas:
            entradas[campo].delete(0, tk.END)

    if reset_id:
        if rol_var:
            rol_var.set("Vendedor")
        if estado_var:
            estado_var.set("Activo")
        if tipo_nomina_var:
            tipo_nomina_var.set("Porcentual")
        if salario_diario_var:
            salario_diario_var.set("0")

def probar_login():
    """Prueba si las credenciales son válidas directamente con la API"""
    usuario = entradas['Usuario'].get().strip()
    password = entradas['Password'].get().strip()

    if not usuario or not password:
        messagebox.showwarning("Advertencia", "Ingresa usuario y contraseña en los campos para probar.", parent=ventana_usuarios)
        return

    try:
        # Intento de login temporal
        test_client_resp = api.post("/auth/login", json={"usuario": usuario, "password": password, "terminal_id": 1})
        if test_client_resp.status_code == 200:
            messagebox.showinfo("Login Exitoso", f"✅ Las credenciales de '{usuario}' son VÁLIDAS.", parent=ventana_usuarios)
        else:
            messagebox.showerror("Login Fallido", f"❌ Credenciales incorrectas o usuario inactivo.\nStatus: {test_client_resp.status_code}", parent=ventana_usuarios)
    except Exception as e:
        messagebox.showerror("Error", f"Error al probar login: {e}", parent=ventana_usuarios)

def iniciar_usuarios():
    """Inicializa la ventana de gestión de usuarios"""
    global tabla, entradas, ventana_usuarios, rol_var, estado_var, tipo_nomina_var, salario_diario_var

    ventana_usuarios = tk.Tk()
    ventana_usuarios.title("👥 Gestión de Usuarios - VmPOS")
    ventana_usuarios.geometry("1100x750")
    ventana_usuarios.resizable(True, True)
    ventana_usuarios.configure(bg="#FFE4F1")

    # Centrar ventana
    ventana_usuarios.update_idletasks()
    x = (ventana_usuarios.winfo_screenwidth() // 2) - (1100 // 2)
    y = (ventana_usuarios.winfo_screenheight() // 2) - (750 // 2)
    ventana_usuarios.geometry(f"1100x750+{x}+{y}")

    # Estilos
    style = ttk.Style()
    style.theme_use('clam')
    style.configure("Treeview", background="#FFFFFF", foreground="#2d3436", rowheight=26, fieldbackground="#FFFFFF", font=("Segoe UI", 10))
    style.map('Treeview', background=[('selected', '#fd79a8')], foreground=[('selected', 'white')])
    style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), background="#e84393", foreground="white", relief="flat")
    style.map("Treeview.Heading", background=[('active', '#e84393')])

    # Header principal
    header_frame = tk.Frame(ventana_usuarios, bg="#e84393", height=70)
    header_frame.pack(fill="x")

    tk.Label(header_frame, text="👥 GESTIÓN DE USUARIOS Y PERMISOS", font=("Segoe UI", 18, "bold"), bg="#e84393", fg="white").pack(pady=15)

    main_frame = tk.Frame(ventana_usuarios, bg="#FFE4F1")
    main_frame.pack(fill="both", expand=True, padx=20, pady=10)

    # Formulario
    form_frame = tk.LabelFrame(main_frame, text="✨ Ficha de Usuario", font=("Segoe UI", 11, "bold"),
                               bg="#FFDDEE", fg="#C71585", padx=15, pady=12, relief="solid", bd=1)
    form_frame.pack(fill="x", padx=10, pady=5)

    roles = ["Administrador", "Vendedor", "Operario"]
    estados = ["Activo", "Inactivo"]

    rol_var = tk.StringVar(value="Vendedor")
    estado_var = tk.StringVar(value="Activo")
    tipo_nomina_var = tk.StringVar(value="Porcentual")
    salario_diario_var = tk.StringVar(value="0")

    # Fila 0: Usuario & Contraseña
    tk.Label(form_frame, text="👤 Usuario:", font=("Segoe UI", 10, "bold"), bg="#FFDDEE", fg="#C71585").grid(row=0, column=0, padx=5, pady=6, sticky="w")
    entrada_usuario = tk.Entry(form_frame, font=("Segoe UI", 10), width=25, bg="#FFFFFF", bd=1, relief="solid")
    entrada_usuario.grid(row=0, column=1, padx=5, pady=6, sticky="w")
    entradas['Usuario'] = entrada_usuario

    tk.Label(form_frame, text="🔒 Contraseña:", font=("Segoe UI", 10, "bold"), bg="#FFDDEE", fg="#C71585").grid(row=0, column=2, padx=(20, 5), pady=6, sticky="w")
    entrada_password = tk.Entry(form_frame, font=("Segoe UI", 10), width=25, bg="#FFFFFF", bd=1, relief="solid", show="*")
    entrada_password.grid(row=0, column=3, padx=5, pady=6, sticky="w")
    entradas['Password'] = entrada_password

    # Fila 1: Nombre & Apellidos
    tk.Label(form_frame, text="📛 Nombre:", font=("Segoe UI", 10, "bold"), bg="#FFDDEE", fg="#C71585").grid(row=1, column=0, padx=5, pady=6, sticky="w")
    entrada_nombre = tk.Entry(form_frame, font=("Segoe UI", 10), width=25, bg="#FFFFFF", bd=1, relief="solid")
    entrada_nombre.grid(row=1, column=1, padx=5, pady=6, sticky="w")
    entradas['Nombre'] = entrada_nombre

    tk.Label(form_frame, text="📛 Apellidos:", font=("Segoe UI", 10, "bold"), bg="#FFDDEE", fg="#C71585").grid(row=1, column=2, padx=(20, 5), pady=6, sticky="w")
    entrada_apellidos = tk.Entry(form_frame, font=("Segoe UI", 10), width=25, bg="#FFFFFF", bd=1, relief="solid")
    entrada_apellidos.grid(row=1, column=3, padx=5, pady=6, sticky="w")
    entradas['Apellidos'] = entrada_apellidos

    # Fila 2: Documento & Rol
    tk.Label(form_frame, text="🪪 Documento/NIT:", font=("Segoe UI", 10, "bold"), bg="#FFDDEE", fg="#C71585").grid(row=2, column=0, padx=5, pady=6, sticky="w")
    entrada_doc = tk.Entry(form_frame, font=("Segoe UI", 10), width=25, bg="#FFFFFF", bd=1, relief="solid")
    entrada_doc.grid(row=2, column=1, padx=5, pady=6, sticky="w")
    entradas['Documento'] = entrada_doc

    tk.Label(form_frame, text="👑 Rol:", font=("Segoe UI", 10, "bold"), bg="#FFDDEE", fg="#C71585").grid(row=2, column=2, padx=(20, 5), pady=6, sticky="w")
    combo_rol = ttk.Combobox(form_frame, textvariable=rol_var, values=roles, state="readonly", width=23, font=("Segoe UI", 10))
    combo_rol.grid(row=2, column=3, padx=5, pady=6, sticky="w")

    # Fila 3: Tipo Remuneración & Valor
    lbl_tipo_nomina = tk.Label(form_frame, text="📄 Remuneración:", font=("Segoe UI", 10, "bold"), bg="#FFDDEE", fg="#C71585")
    lbl_tipo_nomina.grid(row=3, column=0, padx=5, pady=6, sticky="w")
    combo_tipo_nomina = ttk.Combobox(form_frame, textvariable=tipo_nomina_var, values=["Porcentual", "Fija"], state="readonly", width=23, font=("Segoe UI", 10))
    combo_tipo_nomina.grid(row=3, column=1, padx=5, pady=6, sticky="w")

    lbl_valor_nomina = tk.Label(form_frame, text="💰 Comisión (%):", font=("Segoe UI", 10, "bold"), bg="#FFDDEE", fg="#C71585")
    lbl_valor_nomina.grid(row=3, column=2, padx=(20, 5), pady=6, sticky="w")
    entrada_valor_nomina = tk.Entry(form_frame, textvariable=salario_diario_var, font=("Segoe UI", 10), width=25, bg="#FFFFFF", bd=1, relief="solid")
    entrada_valor_nomina.grid(row=3, column=3, padx=5, pady=6, sticky="w")

    # Fila 4: Estado
    tk.Label(form_frame, text="📊 Estado:", font=("Segoe UI", 10, "bold"), bg="#FFDDEE", fg="#C71585").grid(row=4, column=0, padx=5, pady=6, sticky="w")
    combo_estado = ttk.Combobox(form_frame, textvariable=estado_var, values=estados, state="readonly", width=23, font=("Segoe UI", 10))
    combo_estado.grid(row=4, column=1, padx=5, pady=6, sticky="w")

    def on_tipo_nomina_change(*args):
        if combo_tipo_nomina.get() == "Fija":
            lbl_valor_nomina.config(text="💰 Salario Diario ($ COP):")
        else:
            lbl_valor_nomina.config(text="💰 Comisión (%):")

    tipo_nomina_var.trace_add("write", on_tipo_nomina_change)
    combo_tipo_nomina.bind("<<ComboboxSelected>>", lambda e: combo_tipo_nomina.after(50, on_tipo_nomina_change))

    # Botones
    botones_frame = tk.Frame(form_frame, bg="#FFDDEE")
    botones_frame.grid(row=5, column=0, columnspan=4, pady=(15, 5))

    btn_guardar = tk.Button(botones_frame, text="💾 Guardar Usuario", command=guardar_usuario, bg="#55efc4", fg="#2d3436", font=("Segoe UI", 10, "bold"), relief="flat", padx=12, pady=6, cursor="hand2")
    btn_guardar.pack(side="left", padx=6)

    btn_eliminar = tk.Button(botones_frame, text="🗑️ Eliminar", command=eliminar_usuario, bg="#ff7675", fg="white", font=("Segoe UI", 10, "bold"), relief="flat", padx=12, pady=6, cursor="hand2")
    btn_eliminar.pack(side="left", padx=6)

    btn_limpiar = tk.Button(botones_frame, text="🧹 Limpiar Campos", command=lambda: limpiar_campos(reset_id=True), bg="#74b9ff", fg="white", font=("Segoe UI", 10, "bold"), relief="flat", padx=12, pady=6, cursor="hand2")
    btn_limpiar.pack(side="left", padx=6)

    btn_login = tk.Button(botones_frame, text="🔑 Probar Login", command=probar_login, bg="#a29bfe", fg="white", font=("Segoe UI", 10, "bold"), relief="flat", padx=12, pady=6, cursor="hand2")
    btn_login.pack(side="left", padx=6)

    btn_refrescar = tk.Button(botones_frame, text="🔄 Refrescar", command=actualizar_tabla, bg="#fdcb6e", fg="#2d3436", font=("Segoe UI", 10, "bold"), relief="flat", padx=12, pady=6, cursor="hand2")
    btn_refrescar.pack(side="left", padx=6)

    # Tabla
    tabla_frame = tk.LabelFrame(main_frame, text="📋 Lista de Usuarios", font=("Segoe UI", 11, "bold"), bg="#FFE4F1", fg="#C71585", padx=10, pady=10, relief="solid", bd=1)
    tabla_frame.pack(fill="both", expand=True, padx=10, pady=5)

    columnas = ("ID", "Usuario", "Nombre", "Documento", "Rol", "Remuneración", "Estado", "Último Acceso", "Registro")
    tabla = ttk.Treeview(tabla_frame, columns=columnas, show="headings", height=12)

    anchos = {
        "ID": 45,
        "Usuario": 110,
        "Nombre": 180,
        "Documento": 110,
        "Rol": 110,
        "Remuneración": 150,
        "Estado": 85,
        "Último Acceso": 130,
        "Registro": 130
    }

    for col in columnas:
        tabla.heading(col, text=col)
        tabla.column(col, width=anchos.get(col, 100), anchor="center")

    scroll_y = ttk.Scrollbar(tabla_frame, orient="vertical", command=tabla.yview)
    tabla.configure(yscrollcommand=scroll_y.set)
    tabla.pack(side="left", fill="both", expand=True, padx=(0, 2), pady=2)
    scroll_y.pack(side="right", fill="y", pady=2)

    tabla.bind("<<TreeviewSelect>>", seleccionar_usuario)

    # Footer
    footer = tk.Frame(ventana_usuarios, bg="#e84393", height=40)
    footer.pack(fill="x", side="bottom")

    tk.Label(footer, text="📍 Puerto Colombia • 📞 +573215545788  |  VmPOS v3.1.0", font=("Segoe UI", 9), bg="#e84393", fg="white").pack(pady=8)

    actualizar_tabla()
    ventana_usuarios.mainloop()

if __name__ == "__main__":
    iniciar_usuarios()
'''

with open("interface/usuarios_menu.py", "w") as f:
    f.write(content)
print("USUARIOS MENU REWRITTEN")
