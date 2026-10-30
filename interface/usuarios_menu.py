# -*- coding: utf-8 -*-
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
from interface.theme_manager import (
    theme_mgr, aplicar_tema, calcular_geometria_segura,
    crear_boton, ScrollableContainer, calcular_color_texto_optimo,
    iniciar_observador_tema
)
try:
    from session_manager import session_mgr
except ImportError:
    from interface.session_manager import session_mgr

# Variables globales
entradas = {}
tabla = None
ventana_usuarios = None
rol_var = None
estado_var = None
tipo_nomina_var = None
salario_diario_var = None
id_usuario_seleccionado = None

def _sincronizar_local_nomina(user_dict, forzar_config=True):
    """Sincroniza el usuario creado/editado con usuarios.db para Nómina y Comisiones."""
    try:
        from interface.nomina_manager import sincronizar_usuario_desde_dict
        sincronizar_usuario_desde_dict(user_dict, forzar_config=forzar_config)
    except Exception:
        try:
            from nomina_manager import sincronizar_usuario_desde_dict
            sincronizar_usuario_desde_dict(user_dict, forzar_config=forzar_config)
        except Exception as e_sync:
            print(f"Aviso sincronizando usuario local: {e_sync}")

def obtener_usuarios():
    """Obtiene la lista de usuarios desde la API REST y sincroniza con usuarios.db"""
    try:
        resp = api.get("/usuarios?size=1000")
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("items", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            for it in items:
                _sincronizar_local_nomina(it, forzar_config=False)
            return items
        else:
            return []
    except Exception as e:
        print(f"Error al obtener usuarios: {e}")
        return []

def insertar_usuario(usuario, password, rol, estado, comision=0.0, nombre="", apellidos="", tipo_nom="Porcentual", salario=0.0, documento=""):
    """Crea un nuevo usuario a través de la API REST y lo sincroniza en usuarios.db"""
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
            _sincronizar_local_nomina(payload, forzar_config=True)
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
    """Actualiza un usuario a través de la API REST y lo sincroniza en usuarios.db"""
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
            _sincronizar_local_nomina(payload, forzar_config=True)
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
        fecha_registro = u.get("fecha_registro", "")
        if isinstance(fecha_registro, str) and fecha_registro:
            try:
                fecha_obj = datetime.fromisoformat(fecha_registro.replace("Z", "+00:00"))
                fecha_formateada = fecha_obj.strftime("%d/%m/%Y %H:%M")
            except:
                fecha_formateada = fecha_registro[:16]
        else:
            fecha_formateada = "No disponible"

        ultimo_acceso = u.get("ultimo_acceso")
        if ultimo_acceso:
            try:
                fecha_obj = datetime.fromisoformat(str(ultimo_acceso).replace("Z", "+00:00"))
                ultimo_acceso = fecha_obj.strftime("%d/%m/%Y %H:%M")
            except:
                ultimo_acceso = str(ultimo_acceso)[:16]
        else:
            ultimo_acceso = "Nunca"

        nombre_completo = f"{u.get('nombre', '')} {u.get('apellidos', '')}".strip() or u.get("usuario")
        remun = f"{u.get('tipo_remuneracion', 'Porcentual')}"
        if u.get("tipo_remuneracion") == "Fija":
            remun += f" (${u.get('salario_diario', 0):,.0f})"
        else:
            remun += f" ({u.get('porcentaje_comision', 0):.1f}%)"

        valores = (
            u["id"],
            u["usuario"],
            nombre_completo,
            u.get("documento") or "Sin doc",
            u["rol"],
            remun,
            u.get("estado", "Activo"),
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
        valores = tabla.item(item_seleccionado, "values")
        if not valores:
            return

        id_usuario_seleccionado = int(valores[0])

        limpiar_campos(reset_id=False)

        usuarios = obtener_usuarios()
        for u in usuarios:
            if u["id"] == id_usuario_seleccionado:
                entradas["Usuario"].insert(0, u.get("usuario", ""))
                entradas["Nombre"].insert(0, u.get("nombre", ""))
                entradas["Apellidos"].insert(0, u.get("apellidos", ""))
                entradas["Documento"].insert(0, u.get("documento") or "")

                rol_var.set(u.get("rol", "Vendedor"))
                estado_var.set(u.get("estado", "Activo"))

                tipo_nom = u.get("tipo_remuneracion", "Porcentual")
                tipo_nomina_var.set(tipo_nom)

                if tipo_nom == "Fija":
                    salario_diario_var.set(str(int(u.get("salario_diario", 0))))
                else:
                    salario_diario_var.set(str(u.get("porcentaje_comision", 0)))
                break
    except Exception as e:
        print(f"Error al seleccionar usuario: {e}")

def guardar_usuario():
    """Guarda o actualiza un usuario"""
    global id_usuario_seleccionado

    usuario = entradas["Usuario"].get().strip()
    password = entradas["Password"].get().strip()
    nombre = entradas["Nombre"].get().strip()
    apellidos = entradas["Apellidos"].get().strip()
    documento = entradas["Documento"].get().strip()

    rol = rol_var.get()
    estado = estado_var.get()
    tipo_nom = tipo_nomina_var.get()

    try:
        valor_nom = float(salario_diario_var.get().replace("$", "").replace(",", "").strip() or 0)
    except ValueError:
        valor_nom = 0.0

    if tipo_nom == "Porcentual" and valor_nom > 100.0:
        tipo_nom = "Fija"
        tipo_nomina_var.set("Fija")

    salario = valor_nom if tipo_nom == "Fija" else 0.0
    comision = valor_nom if tipo_nom == "Porcentual" else 0.0

    if not usuario:
        messagebox.showerror("Error", "El campo Usuario es obligatorio.", parent=ventana_usuarios)
        entradas["Usuario"].focus()
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
                entradas["Password"].focus()
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

    usuario_seleccionado = entradas["Usuario"].get()

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
    usuario = entradas["Usuario"].get().strip()
    password = entradas["Password"].get().strip()

    if not usuario or not password:
        messagebox.showwarning("Advertencia", "Ingresa usuario y contraseña en los campos para probar.", parent=ventana_usuarios)
        return

    try:
        test_client_resp = api.post("/auth/login", json={"usuario": usuario, "password": password, "terminal_id": 1})
        if test_client_resp.status_code == 200:
            messagebox.showinfo("Login Exitoso", f"✅ Las credenciales de '{usuario}' son VÁLIDAS.", parent=ventana_usuarios)
        else:
            messagebox.showerror("Login Fallido", f"❌ Credenciales incorrectas o usuario inactivo.\nStatus: {test_client_resp.status_code}", parent=ventana_usuarios)
    except Exception as e:
        messagebox.showerror("Error", f"Error al probar login: {e}", parent=ventana_usuarios)

def iniciar_usuarios(parent_pid="", parent=None):
    """Inicializa la ventana de gestión de usuarios"""
    global tabla, entradas, ventana_usuarios, rol_var, estado_var, tipo_nomina_var, salario_diario_var

    try:
        if parent:
            ventana_usuarios = tk.Toplevel(parent)
        else:
            ventana_usuarios = tk.Tk()
        parent_pid = parent_pid or os.environ.get("VMPOS_PARENT_PID", "")
        session_mgr.iniciar_vigilante_padre(ventana_usuarios, parent_pid=parent_pid)
        iniciar_observador_tema(ventana_usuarios)

        ventana_usuarios.title("👥 Gestión de Usuarios - VmPOS")
        
        t = aplicar_tema(ventana_usuarios)
        calcular_geometria_segura(ventana_usuarios, 1100, 720, min_w=880, min_h=540)
        ventana_usuarios.configure(bg=t["bg_app"])

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Treeview", background=t["table_bg"], foreground=t["table_fg"], rowheight=26, fieldbackground=t["table_field_bg"], font=("Segoe UI", 9))
        style.map("Treeview", background=[("selected", t["btn_primary_bg"])], foreground=[("selected", "white")])
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), background=t["table_header_bg"], foreground=t["table_header_fg"], relief="flat")
        style.map("Treeview.Heading", background=[("active", t["btn_primary_bg"])])

        header_frame = tk.Frame(ventana_usuarios, bg=t["btn_primary_bg"])
        header_frame.pack(fill="x")

        fg_h = calcular_color_texto_optimo(t["btn_primary_bg"])
        tk.Label(header_frame, text="👥 GESTIÓN DE USUARIOS Y PERMISOS", font=("Segoe UI", 15, "bold"), bg=t["btn_primary_bg"], fg=fg_h).pack(pady=8)

        main_frame = tk.Frame(ventana_usuarios, bg=t["bg_app"])
        main_frame.pack(fill="both", expand=True, padx=15, pady=5)

        form_frame = tk.LabelFrame(main_frame, text="✨ Ficha de Usuario", font=("Segoe UI", 10, "bold"),
                                   bg=t["bg_surface"], fg=t["btn_primary_bg"], padx=12, pady=8, relief="solid", bd=1)
        form_frame.pack(fill="x", padx=5, pady=3)

        roles = ["Administrador", "Vendedor", "Operario"]
        estados = ["Activo", "Inactivo"]

        rol_var = tk.StringVar(value="Vendedor")
        estado_var = tk.StringVar(value="Activo")
        tipo_nomina_var = tk.StringVar(value="Porcentual")
        salario_diario_var = tk.StringVar(value="0")

        tk.Label(form_frame, text="👤 Usuario:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=0, column=0, padx=5, pady=3, sticky="w")
        entrada_usuario = tk.Entry(form_frame, font=("Segoe UI", 9), width=24, bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_fg"], bd=1, relief="solid")
        entrada_usuario.grid(row=0, column=1, padx=5, pady=3, sticky="w")
        entradas["Usuario"] = entrada_usuario

        tk.Label(form_frame, text="🔒 Contraseña:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=0, column=2, padx=(15, 5), pady=3, sticky="w")
        entrada_password = tk.Entry(form_frame, font=("Segoe UI", 9), width=24, bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_fg"], bd=1, relief="solid", show="*")
        entrada_password.grid(row=0, column=3, padx=5, pady=3, sticky="w")
        entradas["Password"] = entrada_password

        tk.Label(form_frame, text="📛 Nombre:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=1, column=0, padx=5, pady=3, sticky="w")
        entrada_nombre = tk.Entry(form_frame, font=("Segoe UI", 9), width=24, bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_fg"], bd=1, relief="solid")
        entrada_nombre.grid(row=1, column=1, padx=5, pady=3, sticky="w")
        entradas["Nombre"] = entrada_nombre

        tk.Label(form_frame, text="📛 Apellidos:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=1, column=2, padx=(15, 5), pady=3, sticky="w")
        entrada_apellidos = tk.Entry(form_frame, font=("Segoe UI", 9), width=24, bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_fg"], bd=1, relief="solid")
        entrada_apellidos.grid(row=1, column=3, padx=5, pady=3, sticky="w")
        entradas["Apellidos"] = entrada_apellidos

        tk.Label(form_frame, text="🪪 Documento/NIT:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=2, column=0, padx=5, pady=3, sticky="w")
        entrada_doc = tk.Entry(form_frame, font=("Segoe UI", 9), width=24, bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_fg"], bd=1, relief="solid")
        entrada_doc.grid(row=2, column=1, padx=5, pady=3, sticky="w")
        entradas["Documento"] = entrada_doc

        tk.Label(form_frame, text="👑 Rol:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=2, column=2, padx=(15, 5), pady=3, sticky="w")
        combo_rol = ttk.Combobox(form_frame, textvariable=rol_var, values=roles, state="readonly", width=22, font=("Segoe UI", 9))
        combo_rol.grid(row=2, column=3, padx=5, pady=3, sticky="w")

        lbl_tipo_nomina = tk.Label(form_frame, text="📄 Remuneración:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"])
        lbl_tipo_nomina.grid(row=3, column=0, padx=5, pady=3, sticky="w")
        combo_tipo_nomina = ttk.Combobox(form_frame, textvariable=tipo_nomina_var, values=["Porcentual", "Fija"], state="readonly", width=22, font=("Segoe UI", 9))
        combo_tipo_nomina.grid(row=3, column=1, padx=5, pady=3, sticky="w")

        lbl_valor_nomina = tk.Label(form_frame, text="💰 Comisión (%):", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"])
        lbl_valor_nomina.grid(row=3, column=2, padx=(15, 5), pady=3, sticky="w")
        entrada_valor_nomina = tk.Entry(form_frame, textvariable=salario_diario_var, font=("Segoe UI", 9), width=24, bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_fg"], bd=1, relief="solid")
        entrada_valor_nomina.grid(row=3, column=3, padx=5, pady=3, sticky="w")

        tk.Label(form_frame, text="📊 Estado:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=4, column=0, padx=5, pady=3, sticky="w")
        combo_estado = ttk.Combobox(form_frame, textvariable=estado_var, values=estados, state="readonly", width=22, font=("Segoe UI", 9))
        combo_estado.grid(row=4, column=1, padx=5, pady=3, sticky="w")

        def on_tipo_nomina_change(*args):
            if combo_tipo_nomina.get() == "Fija":
                lbl_valor_nomina.config(text="💰 Salario Diario ($ COP):")
            else:
                lbl_valor_nomina.config(text="💰 Comisión (%):")

        tipo_nomina_var.trace_add("write", on_tipo_nomina_change)
        combo_tipo_nomina.bind("<<ComboboxSelected>>", lambda e: combo_tipo_nomina.after(50, on_tipo_nomina_change))

        botones_frame = tk.Frame(form_frame, bg=t["bg_surface"])
        botones_frame.grid(row=5, column=0, columnspan=4, pady=(8, 3))

        btn_guardar = crear_boton(botones_frame, text="💾 Guardar Usuario", command=guardar_usuario, tipo="success", font=("Segoe UI", 9, "bold"), padx=10, pady=5)
        btn_guardar.pack(side="left", padx=4)

        btn_eliminar = crear_boton(botones_frame, text="🗑️ Eliminar", command=eliminar_usuario, tipo="danger", font=("Segoe UI", 9, "bold"), padx=10, pady=5)
        btn_eliminar.pack(side="left", padx=4)

        btn_limpiar = crear_boton(botones_frame, text="🧹 Limpiar Campos", command=lambda: limpiar_campos(reset_id=True), tipo="secondary", font=("Segoe UI", 9, "bold"), padx=10, pady=5)
        btn_limpiar.pack(side="left", padx=4)

        btn_login = crear_boton(botones_frame, text="🔑 Probar Login", command=probar_login, tipo="purple", font=("Segoe UI", 9, "bold"), padx=10, pady=5)
        btn_login.pack(side="left", padx=4)

        btn_refrescar = crear_boton(botones_frame, text="🔄 Refrescar", command=actualizar_tabla, tipo="primary", font=("Segoe UI", 9, "bold"), padx=10, pady=5)
        btn_refrescar.pack(side="left", padx=4)

        # Frame de tabla responsiva con dual scrollbars
        tabla_frame = tk.LabelFrame(main_frame, text="📋 Lista de Usuarios", font=("Segoe UI", 10, "bold"), bg=t["bg_surface"], fg=t["btn_primary_bg"], padx=6, pady=6, relief="solid", bd=1)
        tabla_frame.pack(fill="both", expand=True, padx=5, pady=3)
        tabla_frame.rowconfigure(0, weight=1)
        tabla_frame.columnconfigure(0, weight=1)

        columnas = ("ID", "Usuario", "Nombre", "Documento", "Rol", "Remuneración", "Estado", "Último Acceso", "Registro")
        tabla = ttk.Treeview(tabla_frame, columns=columnas, show="headings")

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
            tabla.column(col, width=anchos.get(col, 100), minwidth=60, anchor="center")

        scroll_y = ttk.Scrollbar(tabla_frame, orient="vertical", command=tabla.yview)
        scroll_x = ttk.Scrollbar(tabla_frame, orient="horizontal", command=tabla.xview)
        tabla.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        
        tabla.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")

        tabla.bind("<<TreeviewSelect>>", seleccionar_usuario)

        footer = tk.Frame(ventana_usuarios, bg=t["btn_primary_bg"])
        footer.pack(fill="x", side="bottom")

        try:
            from business_manager import business_mgr as _bm_u
        except ImportError:
            from interface.business_manager import business_mgr as _bm_u
        _bm_u.recargar()
        tk.Label(footer, text=f"{_bm_u.obtener_texto_ubicacion_contacto()}  |  {_bm_u.nombre}", font=("Segoe UI", 9), bg=t["btn_primary_bg"], fg=fg_h).pack(pady=6)

        actualizar_tabla()
        if not parent:
            ventana_usuarios.mainloop()
        return ventana_usuarios
    except Exception as e:
        import traceback
        err_trace = traceback.format_exc()
        print(f"Error fatal iniciando usuarios_menu: {err_trace}")
        try:
            with open("vmpos.log", "a", encoding="utf-8") as f_err:
                f_err.write(f"\n[ERROR usuarios_menu] {err_trace}\n")
        except Exception:
            pass
        messagebox.showerror("Error al abrir Usuarios", f"No se pudo inicializar el módulo de usuarios:\n{e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Usuarios y Permisos VmPOS")
    parser.add_argument("--parent_pid", default="")
    if "-h" in sys.argv or "--help" in sys.argv:
        parser.print_help()
        sys.exit(0)
    args, _ = parser.parse_known_args()
    parent_pid = args.parent_pid or os.environ.get("VMPOS_PARENT_PID", "")
    iniciar_usuarios(parent_pid=parent_pid)
