#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import os
import tkinter as tk
from tkinter import ttk, messagebox
import io

try:
    log_file = open("vmpos.log", "a", encoding="utf-8")
except Exception:
    pass

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# -----------------------------------------------------------------------------
# Enrutador de submódulos para aplicaciones empaquetadas (PyInstaller / VmPOS.exe)
# Si VmPOS es invocado con la ruta de un script como argumento, despachar
# inmediatamente al submódulo correspondiente sin mostrar la ventana de login.
# -----------------------------------------------------------------------------
if len(sys.argv) > 1:
    _arg1 = os.path.basename(sys.argv[1]).lower()
    _mapeo_modulos = {
        "ventas_menu.py": ("interface.ventas_menu", "iniciar_ventas"),
        "inventario_menu.py": ("interface.inventario_menu", "iniciar_inventario"),
        "caja_menu.py": ("interface.caja_menu", "iniciar_control_caja"),
        "usuarios_menu.py": ("interface.usuarios_menu", "iniciar_usuarios"),
        "clientes_menu.py": ("interface.clientes_menu", "iniciar_clientes"),
        "gastos_menu.py": ("interface.gastos_menu", "iniciar_gastos"),
        "contabilidad_menu.py": ("interface.contabilidad_menu", "iniciar_contabilidad"),
        "nomina_menu.py": ("interface.nomina_menu", "iniciar_nomina"),
        "turnos_menu.py": ("interface.turnos_menu", "iniciar_control_turnos"),
        "generador_codigo_barras.py": ("interface.generador_codigo_barras", "iniciar_generador_codigo_barras"),
        "ventas_admin_dialog.py": ("interface.ventas_admin_dialog", "abrir_gestion_ventas"),
    }
    if _arg1 in _mapeo_modulos:
        _mod_str, _func_str = _mapeo_modulos[_arg1]
        try:
            import importlib
            _mod = importlib.import_module(_mod_str)
            if hasattr(_mod, _func_str):
                sys.argv.pop(1)
                _fn = getattr(_mod, _func_str)
                _fn()
                sys.exit(0)
        except Exception as _e_dispatch:
            print(f"Error despachando submódulo {_arg1}: {_e_dispatch}")

from client.api_client import api
from interface.theme_manager import (
    theme_mgr, aplicar_tema, calcular_geometria_segura,
    crear_boton, calcular_color_texto_optimo, iniciar_observador_tema
)
from interface.business_manager import business_mgr
try:
    from session_manager import session_mgr
except ImportError:
    from interface.session_manager import session_mgr
try:
    from PIL import Image, ImageTk
    PIL_DISPONIBLE = True
except ImportError:
    PIL_DISPONIBLE = False

# Tipografía adaptativa multiplataforma (macOS / Windows / Linux)
FONT_FAMILY = "Helvetica Neue" if sys.platform == "darwin" else "Segoe UI"
FONT_EMOJI = "Apple Color Emoji" if sys.platform == "darwin" else "Segoe UI Emoji"

def _iniciar_flujo_principal(datos_usuario, usuario_actual):
    ventana.destroy()
    try:
        from interface.menu_inicio import iniciar_dashboard
        iniciar_dashboard(usuario_actual, datos_usuario)
    except Exception as e:
        messagebox.showerror("Error", f"Fallo al abrir dashboard: {e}")

def mostrar_alerta_bonita(titulo, mensaje, tipo="error"):
    alerta = tk.Toplevel()
    session_mgr.registrar_ventana(alerta)
    alerta.title("Notificación")
    t_alert = aplicar_tema(alerta)
    calcular_geometria_segura(alerta, 420, 300, min_w=360, min_h=240)
    alerta.configure(bg=t_alert["bg_app"])
    alerta.resizable(False, False)
    alerta.grab_set()
    
    color_header = "#DC2626" if tipo == "error" else "#047857"
    icono = "❌" if tipo == "error" else "✅"
    
    main_f = tk.Frame(alerta, bg=t_alert["bg_surface"], bd=1, relief="solid")
    main_f.pack(fill="both", expand=True, padx=15, pady=15)
    
    header = tk.Frame(main_f, bg=color_header, height=75)
    header.pack(fill="x")
    header.pack_propagate(False)
    tk.Label(header, text=icono, font=(FONT_EMOJI, 26), bg=color_header, fg="#FFFFFF").pack(pady=(8, 2))
    tk.Label(header, text=titulo, font=(FONT_FAMILY, 12, "bold"), bg=color_header, fg="#FFFFFF").pack()
    
    content = tk.Frame(main_f, bg=t_alert["bg_surface"])
    content.pack(fill="both", expand=True, pady=10, padx=15)
    tk.Label(content, text=mensaje, font=(FONT_FAMILY, 10), bg=t_alert["bg_surface"], fg=t_alert["text_primary"], justify="center", wraplength=340).pack(expand=True)
    
    btn_box = tk.Frame(main_f, bg=t_alert["bg_surface"])
    btn_box.pack(pady=10)
    crear_boton(btn_box, text="CONTINUAR", bg_color=t_alert["accent"], fg_color="#FFFFFF", command=alerta.destroy).pack()

def abrir_configuracion_red():
    try:
        from interface.network_dialog import abrir_dialogo_red
    except ImportError:
        from network_dialog import abrir_dialogo_red
    abrir_dialogo_red(parent=ventana)

def validar_usuario(event=None):
    usuario = usuario_var.get().strip()
    clave = pass_var.get().strip()
    
    if not usuario or not clave:
        mostrar_alerta_bonita("Campos vacíos", "Por favor ingresa usuario y contraseña", "error")
        return

    success, message = api.login(usuario, clave)
    if not success:
        msg_str = str(message or "")
        if "conexión" in msg_str.lower() or "servidor" in msg_str.lower() or "503" in msg_str:
            # Fallback transparente a base de datos SQLite local de usuarios
            try:
                try:
                    from interface.usuarios_db import obtener_usuario_por_credenciales
                except ImportError:
                    from usuarios_db import obtener_usuario_por_credenciales
                
                u_local = obtener_usuario_por_credenciales(usuario, clave)
                if u_local:
                    nom_comp = f"{u_local.get('nombre', '')} {u_local.get('apellidos', '')}".strip()
                    usuario_actual = nom_comp if nom_comp else str(u_local.get('usuario', 'Usuario')).capitalize()
                    mostrar_alerta_bonita("¡Bienvenida! ✨", f"Hola {usuario_actual}!\n\nAcceso concedido como {u_local.get('rol', 'Usuario')}\n(Modo Local)", "success")
                    ventana.after(1000, lambda: _iniciar_flujo_principal(u_local, usuario_actual))
                    return
            except Exception as e_local:
                print(f"Advertencia: no se pudo verificar localmente: {e_local}")

            abrir = messagebox.askyesno(
                "Servidor No Disponible",
                f"{msg_str}\n\n"
                f"URL actual: {api.base_url}\n\n"
                "No se pudo conectar al servidor ni se encontraron credenciales locales válidas.\n"
                "¿Deseas abrir la Configuración de Red para verificar la IP y Puerto del Servidor?"
            )
            if abrir:
                abrir_configuracion_red()
            return
        mostrar_alerta_bonita("Error", message, "error")
        return

    resp = api.get("/auth/me")
    if resp.status_code == 200:
        datos_usuario = resp.json()
        nom_comp = f"{datos_usuario.get('nombre', '')} {datos_usuario.get('apellidos', '')}".strip()
        usuario_actual = nom_comp if nom_comp else str(datos_usuario.get('usuario', 'Usuario')).capitalize()
        os.environ["VMPOS_TOKEN"] = api.token
        try:
            from interface.nomina_manager import sincronizar_usuario_desde_dict
            sincronizar_usuario_desde_dict(datos_usuario)
        except Exception:
            try:
                from nomina_manager import sincronizar_usuario_desde_dict
                sincronizar_usuario_desde_dict(datos_usuario)
            except Exception:
                pass

        mostrar_alerta_bonita("¡Bienvenida! ✨", f"Hola {usuario_actual}!\n\nAcceso concedido como {datos_usuario['rol']}\nIniciando sistema...", "success")
        ventana.after(1500, lambda: _iniciar_flujo_principal(datos_usuario, usuario_actual))
    else:
        mostrar_alerta_bonita("Error", "No se pudo cargar el perfil del usuario", "error")

def limpiar_campos(event=None):
    usuario_var.set("")
    pass_var.set("")
    entry_user.focus()

ventana = tk.Tk()
business_mgr.recargar()
titulo_login = f"{business_mgr.nombre} — {business_mgr.subtitulo}" if business_mgr.subtitulo else f"{business_mgr.nombre} — Inicio de Sesión"
ventana.title(titulo_login)

t = aplicar_tema(ventana)
calcular_geometria_segura(ventana, 920, 560, min_w=780, min_h=490)
ventana.resizable(True, True)
ventana.configure(bg=t["bg_app"])

def crear_etiqueta(parent, text="", font=None, bg=None, fg=None, **kwargs):
    """Crea una etiqueta ttk.Label nativa, inmune al bug de texto invisible en macOS."""
    kw = {"text": text}
    if font:
        kw["font"] = font
    if fg:
        kw["foreground"] = fg
    if bg:
        kw["background"] = bg
    for k in ["anchor", "justify", "wraplength", "image"]:
        if k in kwargs:
            kw[k] = kwargs[k]
    return ttk.Label(parent, **kw)

# Color de acento / identidad corporativa configurada
COLOR_LOGIN = business_mgr.color_login or t["accent"]
FG_LOGIN = calcular_color_texto_optimo(COLOR_LOGIN)

main_frame = tk.Frame(ventana, bg=t["bg_app"])
main_frame.pack(fill="both", expand=True, padx=12, pady=12)
main_frame.rowconfigure(0, weight=1)
main_frame.columnconfigure(0, weight=1, minsize=320)
main_frame.columnconfigure(1, weight=1, minsize=320)

# Panel Izquierdo Promocional / Institucional
left_frame = tk.Frame(main_frame, bg=t["bg_card"], relief="solid", bd=1)
left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

header_frame = tk.Frame(left_frame, bg=COLOR_LOGIN, height=52)
header_frame.pack(fill="x")
header_frame.pack_propagate(False)
crear_etiqueta(header_frame, text="🏪 🧾 📦 💳 📊", font=(FONT_EMOJI, 16), bg=COLOR_LOGIN, fg=FG_LOGIN).pack(pady=10)

# Logo y Título Institucional
if PIL_DISPONIBLE and business_mgr.logo_path and os.path.exists(business_mgr.logo_path):
    try:
        with Image.open(business_mgr.logo_path) as raw_img:
            raw_img.load()
            im_copy = raw_img.copy()
            im_copy.thumbnail((220, 70))
            logo_tk = ImageTk.PhotoImage(im_copy, master=ventana)
        lbl_logo = crear_etiqueta(left_frame, image=logo_tk, bg=t["bg_card"])
        lbl_logo.image = logo_tk
        lbl_logo.pack(pady=(10, 2))
    except Exception as e:
        print(f"Aviso al cargar logo en inicio de sesion: {e}")

crear_etiqueta(left_frame, text=business_mgr.nombre, font=(FONT_FAMILY, 22, "bold"), bg=t["bg_card"], fg=COLOR_LOGIN, wraplength=320).pack(pady=(6, 2))

if business_mgr.subtitulo:
    crear_etiqueta(left_frame, text=business_mgr.subtitulo.upper(), font=(FONT_FAMILY, 10, "bold"), bg=t["bg_card"], fg=t["text_primary"], wraplength=320).pack()

eslogan_txt = business_mgr.obtener("eslogan", "")
if eslogan_txt:
    crear_etiqueta(left_frame, text=eslogan_txt, font=(FONT_FAMILY, 9, "italic"), bg=t["bg_card"], fg=t["text_secondary"], wraplength=320).pack(pady=(2, 6))

tk.Frame(left_frame, bg=t["border"], height=1).pack(fill="x", padx=25, pady=6)

detalles_institucionales = []
if business_mgr.razon_social and business_mgr.razon_social != business_mgr.subtitulo:
    detalles_institucionales.append(f"🏢 {business_mgr.razon_social}")
if business_mgr.nit:
    detalles_institucionales.append(f"🪪 {business_mgr.tipo_documento_fiscal}: {business_mgr.nit}")
if business_mgr.direccion or business_mgr.ciudad:
    ub_str = f"{business_mgr.direccion}, {business_mgr.ciudad}".strip(", ")
    detalles_institucionales.append(f"📍 {ub_str}")
if business_mgr.telefono:
    detalles_institucionales.append(f"📞 Teléfono: {business_mgr.telefono}")

if not detalles_institucionales:
    detalles_institucionales = [
        "🧾 Facturación POS e impresión térmica / A4",
        "📦 Control de inventario y movimientos en tiempo real",
        "💰 Gestión de caja, cartera y contabilidad integrada",
        "👥 Control de personal, comisiones y nómina"
    ]

for s in detalles_institucionales[:4]:
    crear_etiqueta(left_frame, text=s, font=(FONT_FAMILY, 9), bg=t["bg_card"], fg=t["text_primary"], anchor="w", wraplength=300, justify="left").pack(fill="x", padx=25, pady=2)

tk.Frame(left_frame, bg=t["bg_card"]).pack(expand=True, fill="both")

contact_frame = tk.Frame(left_frame, bg=COLOR_LOGIN, height=30)
contact_frame.pack(fill="x", side="bottom")
contact_frame.pack_propagate(False)
crear_etiqueta(contact_frame, text=business_mgr.obtener_texto_ubicacion_contacto(), font=(FONT_FAMILY, 8, "bold"), bg=COLOR_LOGIN, fg=FG_LOGIN).pack(pady=6)

# Panel Derecho de Inicio de Sesión
right_frame = tk.Frame(main_frame, bg=t["bg_surface"], relief="solid", bd=1)
right_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

login_header = tk.Frame(right_frame, bg=COLOR_LOGIN, height=52)
login_header.pack(fill="x")
login_header.pack_propagate(False)

# Selector rápido de tema en cabecera
def toggle_theme():
    if sys.platform == "darwin":
        try:
            if tk.TkVersion < 8.6:
                messagebox.showinfo("Tema", "En macOS con la versión del sistema de Tkinter, el modo visual está fijado en Modo Claro de alto contraste para garantizar la legibilidad del texto.")
                return
        except Exception:
            pass
    nuevo = "claro" if theme_mgr.es_oscuro() else "oscuro"
    theme_mgr.cambiar_tema(nuevo)
    messagebox.showinfo("Tema", f"Tema cambiado a {nuevo.upper()}.\nReinicie la aplicación para reflejar todos los estilos.")

fg_btn_h = "#0F172A" if sys.platform == "darwin" else FG_LOGIN
btn_theme_login = tk.Button(login_header, text="🌙/☀️", command=toggle_theme,
                            font=(FONT_FAMILY, 9, "bold"), bg=COLOR_LOGIN, fg=fg_btn_h,
                            relief="flat", cursor="hand2", padx=6, pady=2)
btn_theme_login.pack(side="right", padx=(4, 10), pady=10)

btn_net_login = tk.Button(login_header, text="🌐 Red", command=abrir_configuracion_red,
                          font=(FONT_FAMILY, 9, "bold"), bg=COLOR_LOGIN, fg=fg_btn_h,
                          relief="flat", cursor="hand2", padx=6, pady=2)
btn_net_login.pack(side="right", padx=(0, 4), pady=10)

login_header_center = tk.Frame(login_header, bg=COLOR_LOGIN)
login_header_center.pack(side="left", padx=15, pady=10)

crear_etiqueta(login_header_center, text="🔐", font=(FONT_EMOJI, 16), bg=COLOR_LOGIN, fg=FG_LOGIN).pack(side="left")
crear_etiqueta(login_header_center, text="ACCESO AL SISTEMA", font=(FONT_FAMILY, 12, "bold"), bg=COLOR_LOGIN, fg=FG_LOGIN).pack(side="left", padx=(8, 0))

login_content = tk.Frame(right_frame, bg=t["bg_surface"])
login_content.pack(expand=True, fill="both", padx=35, pady=16)

crear_etiqueta(login_content, text="Inicia sesión para continuar ✨", font=(FONT_FAMILY, 10), bg=t["bg_surface"], fg=t["text_secondary"]).pack(pady=(0, 14))

usuario_var = tk.StringVar()
pass_var = tk.StringVar()

crear_etiqueta(login_content, text="👤 USUARIO", font=(FONT_FAMILY, 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"], anchor="w").pack(fill="x", pady=(0, 3))
entry_user = ttk.Entry(login_content, textvariable=usuario_var, font=(FONT_FAMILY, 11))
entry_user.pack(fill="x", ipady=3, pady=(0, 12))

crear_etiqueta(login_content, text="🔒 CONTRASEÑA", font=(FONT_FAMILY, 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"], anchor="w").pack(fill="x", pady=(0, 3))
entry_pass = ttk.Entry(login_content, textvariable=pass_var, font=(FONT_FAMILY, 11), show="*")
entry_pass.pack(fill="x", ipady=3, pady=(0, 16))

btn_login = crear_boton(login_content, "🚀 INICIAR SESIÓN", comando=validar_usuario,
                        tam_fuente=11, negrita=True, bg_color=COLOR_LOGIN, fg_color=FG_LOGIN)
btn_login.pack(fill="x", pady=(0, 8))

btn_clear = crear_boton(login_content, "🧹 LIMPIAR", comando=limpiar_campos,
                        tam_fuente=10, negrita=True, bg_color=t["btn_secondary_bg"], fg_color=t["btn_secondary_fg"])
btn_clear.pack(fill="x", pady=(0, 8))

btn_red_link = tk.Button(
    login_content,
    text="🌐 Configurar Servidor / Conexión de Red",
    font=(FONT_FAMILY, 9, "underline"),
    bg=t["bg_surface"],
    fg=COLOR_LOGIN if COLOR_LOGIN != "#FFFFFF" else t["accent"],
    bd=0,
    cursor="hand2",
    activebackground=t["bg_surface"],
    command=abrir_configuracion_red
)
btn_red_link.pack(fill="x", pady=(4, 0))

ventana.bind("<Return>", validar_usuario)
ventana.bind("<Escape>", limpiar_campos)
entry_user.focus()

def forzar_repintado_mac():
    try:
        ventana.update_idletasks()
        ventana.update()
        w = ventana.winfo_width()
        h = ventana.winfo_height()
        if w > 10 and h > 10:
            ventana.geometry(f"{w+1}x{h}")
            ventana.update_idletasks()
            ventana.geometry(f"{w}x{h}")
        ventana.lift()
        ventana.focus_force()
    except Exception:
        pass

if __name__ == "__main__":
    if sys.platform == "darwin":
        ventana.after(50, forzar_repintado_mac)
        ventana.after(200, forzar_repintado_mac)
    ventana.mainloop()
