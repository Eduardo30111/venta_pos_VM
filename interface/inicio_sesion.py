#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import os
import builtins
import typing
builtins.Tuple = typing.Tuple
builtins.List = typing.List
builtins.Dict = typing.Dict
builtins.Optional = typing.Optional
builtins.Any = typing.Any
from typing import Tuple, List, Dict, Optional, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# -----------------------------------------------------------------------------
# Punto de entrada Headless para el Servidor FastAPI (`--run-server`)
# Impide abrir ventanas gráficas duplicadas cuando VmPOS.exe o inicio_sesion.py
# es lanzado como servicio o subproceso en segundo plano.
# -----------------------------------------------------------------------------
if "--run-server" in sys.argv:
    _host = "0.0.0.0"
    _port = 8000
    for _i, _a in enumerate(sys.argv):
        if _a == "--host" and _i + 1 < len(sys.argv):
            _host = sys.argv[_i + 1]
        elif _a == "--port" and _i + 1 < len(sys.argv):
            try:
                _port = int(sys.argv[_i + 1])
            except Exception:
                _port = 8000
    import uvicorn
    from server.main import app as _fastapi_app
    uvicorn.run(_fastapi_app, host=_host, port=_port, log_level="info")
    sys.exit(0)

if "--self-test-imports" in sys.argv:
    import importlib
    import traceback
    _root_st = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _intf_st = os.path.join(_root_st, "interface")
    for _p_st in (_root_st, _intf_st):
        if _p_st not in sys.path:
            sys.path.insert(0, _p_st)
    _mods_st = [
        "interface.config",
        "interface.business_manager",
        "interface.network_manager",
        "interface.network_dialog",
        "interface.receipt_manager",
        "interface.generador_codigo_barras",
        "interface.configuracion_menu",
        "interface.ventas_admin_dialog",
        "interface.menu_inicio",
        "interface.ventas_menu",
        "interface.caja_menu",
        "interface.clientes_menu",
        "interface.inventario_menu",
        "interface.gastos_menu",
        "interface.nomina_menu",
        "interface.reportes_menu",
        "interface.contabilidad_menu",
        "interface.turnos_menu",
        "interface.usuarios_menu",
    ]
    for _m_st in _mods_st:
        try:
            importlib.import_module(_m_st)
        except Exception:
            sys.stderr.write(f"[SELF-TEST ERROR] {_m_st}:\n{traceback.format_exc()}\n")
            sys.exit(2)
    sys.exit(0)

import tkinter as tk
from tkinter import ttk, messagebox
import io

try:
    log_file = open("vmpos.log", "a", encoding="utf-8")
except Exception:
    pass


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
    crear_boton, calcular_color_texto_optimo, iniciar_observador_tema,
    ModernCardButton
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

def abrir_modal_cambio_password_obligatorio(parent, datos_usuario, on_success):
    modal = tk.Toplevel(parent)
    modal.title("🔒 Primer Acceso — Definir Contraseña")
    t_m = aplicar_tema(modal)
    modal.configure(bg=t_m["bg_surface"])
    calcular_geometria_segura(modal, 480, 420, 420, 360)
    modal.transient(parent)
    modal.grab_set()

    hdr = tk.Frame(modal, bg="#DC2626")
    hdr.pack(fill="x")
    tk.Label(hdr, text="🔒 CAMBIO OBLIGATORIO DE CONTRASEÑA", font=(FONT_FAMILY, 11, "bold"), bg="#DC2626", fg="white").pack(pady=10)

    content = tk.Frame(modal, bg=t_m["bg_surface"], padx=20, pady=15)
    content.pack(fill="both", expand=True)

    tk.Label(
        content,
        text="Has iniciado sesión con la contraseña temporal por defecto ('admin123').\n\n"
             "Por seguridad de los datos y auditoría de tu negocio, debes definir una nueva contraseña personalizada para continuar.",
        font=(FONT_FAMILY, 9),
        bg=t_m["bg_surface"],
        fg=t_m["text_main"],
        justify="left",
        wraplength=420
    ).pack(pady=(0, 15))

    tk.Label(content, text="Nueva Contraseña (mínimo 6 caracteres):", font=(FONT_FAMILY, 9, "bold"), bg=t_m["bg_surface"], fg=t_m["text_main"]).pack(anchor="w")
    pass1_var = tk.StringVar()
    e_p1 = tk.Entry(content, textvariable=pass1_var, show="*", font=(FONT_FAMILY, 10), bg=t_m["input_bg"], fg=t_m["input_fg"], bd=1, relief="solid")
    e_p1.pack(fill="x", pady=(2, 10))

    tk.Label(content, text="Confirmar Nueva Contraseña:", font=(FONT_FAMILY, 9, "bold"), bg=t_m["bg_surface"], fg=t_m["text_main"]).pack(anchor="w")
    pass2_var = tk.StringVar()
    e_p2 = tk.Entry(content, textvariable=pass2_var, show="*", font=(FONT_FAMILY, 10), bg=t_m["input_bg"], fg=t_m["input_fg"], bd=1, relief="solid")
    e_p2.pack(fill="x", pady=(2, 15))

    def confirmar_cambio():
        p1 = pass1_var.get().strip()
        p2 = pass2_var.get().strip()
        try:
            try:
                from interface.usuarios_db import validar_password_fuerte, actualizar_usuario_db
            except ImportError:
                from usuarios_db import validar_password_fuerte, actualizar_usuario_db
        except Exception as e_imp:
            messagebox.showerror("Error Interno", f"No se pudo cargar el validador de seguridad: {e_imp}", parent=modal)
            return

        ok_pwd, msg_pwd = validar_password_fuerte(p1)
        if not ok_pwd:
            messagebox.showerror("Contraseña Insegura", msg_pwd, parent=modal)
            return
        if p1 != p2:
            messagebox.showerror("Contraseñas no coinciden", "Las contraseñas ingresadas no coinciden. Verifícalas.", parent=modal)
            return

        uid = datos_usuario.get("id", 1)
        actualizado_api = False
        actualizado_local = False
        error_api = None

        # 1. Actualizar en API si hay sesión activa con token
        if getattr(api, "token", None):
            try:
                clave_actual = pass_var.get().strip()
                resp_cp = api.post("/auth/change-password", json={
                    "current_password": clave_actual,
                    "new_password": p1,
                })
                if resp_cp.status_code == 200:
                    actualizado_api = True
                else:
                    try:
                        det = resp_cp.json().get("detail", resp_cp.text)
                    except Exception:
                        det = getattr(resp_cp, "text", f"HTTP {resp_cp.status_code}")
                    error_api = f"El servidor rechazó el cambio de contraseña ({resp_cp.status_code}): {det}"
            except Exception as e_api:
                error_api = f"No se pudo comunicar el cambio al servidor: {e_api}"

        # Si estamos autenticados por API y falló la actualización remota, NO continuar
        if getattr(api, "token", None) and not actualizado_api:
            messagebox.showerror("Error en Servidor", error_api or "No se pudo confirmar el cambio de contraseña en el servidor.", parent=modal)
            return

        # 2. Actualizar en SQLite local (mantener consistencia en modo servidor / local)
        try:
            if actualizar_usuario_db(uid, password=p1, requiere_cambio_password=0):
                actualizado_local = True
        except Exception as e_sql:
            print(f"Aviso actualizando SQLite de usuarios: {e_sql}")

        if not actualizado_api and not actualizado_local:
            messagebox.showerror("Error", "No se pudo guardar la nueva contraseña. Intente nuevamente.", parent=modal)
            return

        datos_usuario["requiere_cambio_password"] = False
        pass_var.set(p1)
        messagebox.showinfo("Éxito", "Contraseña personalizada establecida correctamente.\n¡Bienvenido a VmPOS!", parent=modal)
        modal.destroy()
        on_success()

    crear_boton(content, "Establecer Nueva Contraseña", confirmar_cambio, tipo="success", icono="💾", tam_fuente=10).pack(fill="x", pady=6)


def abrir_modal_activacion_primer_administrador(parent, on_success=None):
    modal = tk.Toplevel(parent)
    modal.title("🚀 Activación Inicial de VmPOS — Crear Administrador")
    t_m = aplicar_tema(modal)
    modal.configure(bg=t_m["bg_surface"])
    calcular_geometria_segura(modal, 480, 520, 420, 440)
    modal.transient(parent)
    modal.grab_set()

    hdr = tk.Frame(modal, bg=t_m["accent"])
    hdr.pack(fill="x")
    tk.Label(hdr, text="🚀 ACTIVACIÓN INICIAL DE VmPOS", font=(FONT_FAMILY, 11, "bold"), bg=t_m["accent"], fg="white").pack(pady=(10, 2))
    tk.Label(hdr, text="Configure el Administrador Maestro de su Negocio", font=(FONT_FAMILY, 9), bg=t_m["accent"], fg="white").pack(pady=(0, 10))

    content = tk.Frame(modal, bg=t_m["bg_surface"], padx=25, pady=15)
    content.pack(fill="both", expand=True)

    tk.Label(
        content,
        text="¡Bienvenido a VmPOS! Para garantizar la seguridad de su información contable y ventas, debe registrar las credenciales maestras del administrador.\n\n"
             "No se permiten contraseñas predeterminadas ni accesos universales.",
        font=(FONT_FAMILY, 9),
        bg=t_m["bg_surface"],
        fg=t_m["text_main"],
        justify="left",
        wraplength=420
    ).pack(pady=(0, 15))

    tk.Label(content, text="Nombre del Administrador:", font=(FONT_FAMILY, 9, "bold"), bg=t_m["bg_surface"], fg=t_m["text_main"]).pack(anchor="w")
    nom_var = tk.StringVar(value="Administrador")
    e_nom = tk.Entry(content, textvariable=nom_var, font=(FONT_FAMILY, 10), bg=t_m["input_bg"], fg=t_m["input_fg"], bd=1, relief="solid")
    e_nom.pack(fill="x", pady=(2, 8))

    tk.Label(content, text="Usuario de Acceso:", font=(FONT_FAMILY, 9, "bold"), bg=t_m["bg_surface"], fg=t_m["text_main"]).pack(anchor="w")
    usr_var = tk.StringVar(value="admin")
    e_usr = tk.Entry(content, textvariable=usr_var, font=(FONT_FAMILY, 10), bg=t_m["input_bg"], fg=t_m["input_fg"], bd=1, relief="solid")
    e_usr.pack(fill="x", pady=(2, 8))

    tk.Label(content, text="Contraseña Personalizada (mínimo 6 caracteres):", font=(FONT_FAMILY, 9, "bold"), bg=t_m["bg_surface"], fg=t_m["text_main"]).pack(anchor="w")
    p1_var = tk.StringVar()
    e_p1 = tk.Entry(content, textvariable=p1_var, show="*", font=(FONT_FAMILY, 10), bg=t_m["input_bg"], fg=t_m["input_fg"], bd=1, relief="solid")
    e_p1.pack(fill="x", pady=(2, 8))

    tk.Label(content, text="Confirmar Contraseña:", font=(FONT_FAMILY, 9, "bold"), bg=t_m["bg_surface"], fg=t_m["text_main"]).pack(anchor="w")
    p2_var = tk.StringVar()
    e_p2 = tk.Entry(content, textvariable=p2_var, show="*", font=(FONT_FAMILY, 10), bg=t_m["input_bg"], fg=t_m["input_fg"], bd=1, relief="solid")
    e_p2.pack(fill="x", pady=(2, 12))

    def activar():
        nom = nom_var.get().strip() or "Administrador"
        usr = usr_var.get().strip()
        pw1 = p1_var.get().strip()
        pw2 = p2_var.get().strip()

        if len(usr) < 3:
            messagebox.showerror("Usuario Inválido", "El nombre de usuario debe tener al menos 3 caracteres.", parent=modal)
            return
        try:
            try:
                from interface.usuarios_db import crear_administrador_inicial, validar_password_fuerte
            except ImportError:
                from usuarios_db import crear_administrador_inicial, validar_password_fuerte
        except Exception as e_imp:
            messagebox.showerror("Error Interno", f"No se pudo cargar la librería de usuarios: {e_imp}", parent=modal)
            return

        ok_pwd, msg_pwd = validar_password_fuerte(pw1)
        if not ok_pwd:
            messagebox.showerror("Contraseña Insegura", msg_pwd, parent=modal)
            return
        if pw1 != pw2:
            messagebox.showerror("Contraseñas no coinciden", "Las contraseñas ingresadas no coinciden.", parent=modal)
            return

        # 1. Provisionar en SQLite local (operación estrictamente única con bloqueo BEGIN IMMEDIATE)
        try:
            crear_administrador_inicial(usr, pw1, nombre=nom)
        except Exception as e_reg:
            messagebox.showerror("Error al Crear Administrador", str(e_reg), parent=modal)
            return

        # 2. Provisionar también en el servidor central si está accesible (endpoint one-time)
        try:
            resp_bs = api.post("/auth/bootstrap-admin", json={
                "usuario": usr,
                "password": pw1,
                "nombre": nom,
            })
            if resp_bs.status_code not in (200, 201, 403):
                print(f"Aviso bootstrap-admin servidor ({resp_bs.status_code}): {resp_bs.text}")
        except Exception as e_bs:
            print(f"Aviso sincronizando bootstrap-admin con servidor: {e_bs}")

        usuario_var.set(usr)
        pass_var.set(pw1)
        messagebox.showinfo("¡Activación Exitosa!", f"Administrador '{usr}' configurado correctamente.\nYa puede iniciar sesión en VmPOS.", parent=modal)
        modal.destroy()
        if on_success:
            on_success()

    crear_boton(content, "Activar Sistema y Guardar Administrador", activar, tipo="success", icono="🚀", tam_fuente=10).pack(fill="x", pady=6)


def _iniciar_flujo_principal(datos_usuario, usuario_actual):
    clave_ingresada = pass_var.get().strip()
    requiere_cambio = bool(
        datos_usuario.get("requiere_cambio_password") or 
        (clave_ingresada == "admin123")
    )
    if requiere_cambio:
        abrir_modal_cambio_password_obligatorio(
            ventana,
            datos_usuario,
            lambda: _iniciar_flujo_principal_ejecutar(datos_usuario, usuario_actual)
        )
    else:
        _iniciar_flujo_principal_ejecutar(datos_usuario, usuario_actual)

def _iniciar_flujo_principal_ejecutar(datos_usuario, usuario_actual):
    session_mgr.registrar_login_window(ventana)
    try:
        ventana.withdraw()
    except Exception:
        pass

    def _abrir_dashboard_seguro():
        try:
            logger.info("Iniciando creación y despliegue del Dashboard principal para usuario: %s", usuario_actual)
            from interface.menu_inicio import iniciar_dashboard
            app = iniciar_dashboard(usuario_actual, datos_usuario, login_window=ventana)
            if app:
                session_mgr.registrar_ventana(app)
                try:
                    if hasattr(app, "state") and app.state() == "iconic":
                        app.state("normal")
                    app.deiconify()
                    app.lift()
                    app.focus_force()
                except Exception:
                    pass
                logger.info("Dashboard principal de VmPOS desplegado y activo con éxito.")
                return app
            else:
                raise RuntimeError("iniciar_dashboard retornó None sin lanzar excepción.")
        except Exception as e:
            import traceback
            err_detallado = traceback.format_exc()
            logger.critical("Fallo crítico abriendo dashboard para %s: %s", usuario_actual, err_detallado)
            try:
                from interface.config import LOGS_DIR
                os.makedirs(LOGS_DIR, exist_ok=True)
                with open(os.path.join(LOGS_DIR, "dashboard_error.log"), "a", encoding="utf-8") as _ef:
                    _ef.write(f"--- ERROR AL ABRIR DASHBOARD ({datetime.now()}) ---\n")
                    _ef.write(err_detallado + "\n\n")
            except Exception:
                pass
            try:
                ventana.deiconify()
                ventana.lift()
                ventana.focus_force()
            except Exception:
                pass
            messagebox.showerror(
                "Error al Iniciar el Menú Principal",
                f"Ocurrió un error al cargar el menú principal de VmPOS:\n\n{e}\n\n"
                f"La pantalla de inicio de sesión ha sido restaurada para que pueda reintentar.\n"
                f"Se generó un registro técnico detallado en logs/dashboard_error.log."
            )
            return None

    # Mostrar la pantalla de carga original con animación y bienvenida por voz
    try:
        from interface.pantalla_carga import mostrar_carga
    except ImportError:
        try:
            from pantalla_carga import mostrar_carga
        except ImportError:
            mostrar_carga = None

    if mostrar_carga:
        try:
            datos_usuario['ventana_carga'] = mostrar_carga(
                nombre=usuario_actual,
                usuario_info=datos_usuario,
                parent=ventana,
                on_complete=_abrir_dashboard_seguro
            )
        except Exception as e_carga:
            logger.warning("Aviso al mostrar pantalla de carga: %s. Abriendo dashboard directamente.", e_carga)
            _abrir_dashboard_seguro()
    else:
        _abrir_dashboard_seguro()

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
    abrir_dialogo_red(parent=ventana, on_saved=lambda _cfg: recargar_identidad_login())


def validar_usuario(event=None):
    usuario = usuario_var.get().strip()
    clave = pass_var.get().strip()
    
    if not usuario or not clave:
        messagebox.showwarning("Campos vacíos", "Por favor ingresa usuario y contraseña")
        return

    # Usar la nueva API
    success, message = api.login(usuario, clave)
    
    if not success:
        # Modo Offline Fallback: Si el servidor central no responde o está en subproceso, autenticar contra SQLite local
        msg_str = str(message).lower()
        if "no disponible" in msg_str or "conexión" in msg_str or "timeout" in msg_str or "httpx" in msg_str:
            try:
                try:
                    from interface.usuarios_db import obtener_usuario_por_credenciales
                except ImportError:
                    from usuarios_db import obtener_usuario_por_credenciales
                
                u_local = obtener_usuario_por_credenciales(usuario, clave)
                if u_local:
                    rol_local = str(u_local.get("rol") or "Operario")
                    perm_default = "administrador" if rol_local.strip().lower() in ("administrador", "admin", "gerente") else "operario"
                    datos_usuario = {
                        "id": u_local["id"],
                        "usuario": u_local["usuario"],
                        "nombre": u_local.get("nombre") or u_local["usuario"],
                        "rol": rol_local,
                        "permisos": u_local.get("permisos") or perm_default,
                        "requiere_cambio_password": bool(u_local.get("requiere_cambio_password", False))
                    }
                    usuario_actual = datos_usuario["nombre"].capitalize()
                    mostrar_alerta_bonita(
                        "¡Bienvenida! ✨ (Modo Local)",
                        f"Hola {usuario_actual}!\n\nAcceso local verificado como {datos_usuario['rol']}\nIniciando sistema...",
                        "success"
                    )
                    ventana.after(1500, lambda: _iniciar_flujo_principal(datos_usuario, usuario_actual))
                    return
            except Exception as e_off:
                print(f"Aviso en login offline: {e_off}")

        messagebox.showerror("Error", message)
        return

    # Obtener datos del perfil
    resp = api.get("/auth/me")
    if resp.status_code == 200:
        datos_usuario = resp.json()
        usuario_actual = datos_usuario['nombre'].capitalize()
        os.environ["VMPOS_TOKEN"] = api.token

        mostrar_alerta_bonita(
            "¡Bienvenida! ✨",
            f"Hola {usuario_actual}!\n\nAcceso concedido como {datos_usuario['rol']}\nIniciando sistema...",
            "success"
        )
        
        ventana.after(1500, lambda: _iniciar_flujo_principal(datos_usuario, usuario_actual))
    else:
        messagebox.showerror("Error", "No se pudo cargar el perfil del usuario")

def limpiar_campos(event=None):
    usuario_var.set("")
    pass_var.set("")
    if 'entry_pass' in globals() and entry_pass.winfo_exists():
        entry_pass.config(show="*")
    if 'lbl_toggle_pass' in globals() and lbl_toggle_pass.winfo_exists():
        lbl_toggle_pass.config(text="👁️ Mostrar contraseña")
    entry_user.focus()

ventana = tk.Tk()
business_mgr.recargar()
titulo_login = f"{business_mgr.nombre} — {business_mgr.subtitulo} (v4.1.2)" if business_mgr.subtitulo else f"{business_mgr.nombre} — Inicio de Sesión (v4.1.2)"
ventana.title(titulo_login)

t = aplicar_tema(ventana)
calcular_geometria_segura(ventana, 920, 560, min_w=780, min_h=490)
ventana.resizable(True, True)
ventana.configure(bg=t["bg_app"])

def crear_etiqueta(parent, text="", font=None, bg=None, fg=None, **kwargs):
    """Crea una etiqueta tk.Label con colores explícitos para garantizar contraste en macOS y Windows."""
    kw = {"text": text}
    if font:
        kw["font"] = font
    color_bg = bg
    if color_bg is None:
        try:
            color_bg = parent.cget("bg")
        except Exception:
            color_bg = t["bg_surface"]
    kw["bg"] = color_bg
    kw["fg"] = fg if fg is not None else t["text_primary"]
    for k in ["anchor", "justify", "wraplength", "image"]:
        if k in kwargs:
            kw[k] = kwargs[k]
    return tk.Label(parent, **kw)

# Color de acento / identidad corporativa configurada
COLOR_LOGIN = business_mgr.color_login or t["accent"]
if not COLOR_LOGIN or COLOR_LOGIN.strip().upper() in ("#FFFFFF", "#FFF", "WHITE"):
    COLOR_LOGIN = "#1E40AF"
FG_LOGIN = calcular_color_texto_optimo(COLOR_LOGIN)

main_frame = tk.Frame(ventana, bg=t["bg_app"])
main_frame.pack(fill="both", expand=True, padx=12, pady=12)
main_frame.rowconfigure(0, weight=1)
main_frame.columnconfigure(0, weight=1, minsize=320)
main_frame.columnconfigure(1, weight=1, minsize=320)

# Panel Izquierdo Promocional / Institucional
left_frame = tk.Frame(main_frame, bg=t["bg_card"], relief="solid", bd=1)
left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))


def _renderizar_panel_institucional():
    """Construye o refresca dinámicamente el panel institucional izquierdo con los datos actuales de business_mgr."""
    for child in left_frame.winfo_children():
        try:
            child.destroy()
        except Exception:
            pass

    c_login = business_mgr.color_login or t["accent"]
    if not c_login or c_login.strip().upper() in ("#FFFFFF", "#FFF", "WHITE"):
        c_login = "#1E40AF"
    fg_login = calcular_color_texto_optimo(c_login)

    header_frame = tk.Frame(left_frame, bg=c_login, height=52)
    header_frame.pack(fill="x")
    header_frame.pack_propagate(False)
    crear_etiqueta(header_frame, text="🏪 🧾 📦 💳 📊", font=(FONT_EMOJI, 16), bg=c_login, fg=fg_login).pack(pady=10)

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

    crear_etiqueta(left_frame, text=business_mgr.nombre, font=(FONT_FAMILY, 22, "bold"), bg=t["bg_card"], fg=c_login, wraplength=320).pack(pady=(6, 2))

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

    contact_frame = tk.Frame(left_frame, bg=c_login, height=30)
    contact_frame.pack(fill="x", side="bottom")
    contact_frame.pack_propagate(False)
    crear_etiqueta(contact_frame, text=business_mgr.obtener_texto_ubicacion_contacto(), font=(FONT_FAMILY, 8, "bold"), bg=c_login, fg=fg_login).pack(pady=6)


_renderizar_panel_institucional()

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

btn_theme_login = tk.Button(login_header, text="🌙/☀️", command=toggle_theme,
                            font=(FONT_FAMILY, 9, "bold"), bg=COLOR_LOGIN, fg=FG_LOGIN,
                            activebackground=COLOR_LOGIN, activeforeground=FG_LOGIN,
                            highlightbackground=COLOR_LOGIN,
                            relief="flat", cursor="hand2", padx=6, pady=2)
btn_theme_login.pack(side="right", padx=(4, 10), pady=10)

btn_net_login = tk.Button(login_header, text="🌐 Red", command=abrir_configuracion_red,
                          font=(FONT_FAMILY, 9, "bold"), bg=COLOR_LOGIN, fg=FG_LOGIN,
                          activebackground=COLOR_LOGIN, activeforeground=FG_LOGIN,
                          highlightbackground=COLOR_LOGIN,
                          relief="flat", cursor="hand2", padx=6, pady=2)
btn_net_login.pack(side="right", padx=(0, 4), pady=10)

login_header_center = tk.Frame(login_header, bg=COLOR_LOGIN)
login_header_center.pack(side="left", padx=15, pady=10)

lbl_lock_icon = crear_etiqueta(login_header_center, text="🔐", font=(FONT_EMOJI, 16), bg=COLOR_LOGIN, fg=FG_LOGIN)
lbl_lock_icon.pack(side="left")
lbl_acceso_txt = crear_etiqueta(login_header_center, text="ACCESO AL SISTEMA", font=(FONT_FAMILY, 12, "bold"), bg=COLOR_LOGIN, fg=FG_LOGIN)
lbl_acceso_txt.pack(side="left", padx=(8, 0))

login_content = tk.Frame(right_frame, bg=t["bg_surface"])
login_content.pack(expand=True, fill="both", padx=35, pady=16)

crear_etiqueta(login_content, text="Inicia sesión para continuar ✨", font=(FONT_FAMILY, 10), bg=t["bg_surface"], fg=t["text_secondary"]).pack(pady=(0, 14))

usuario_var = tk.StringVar()
pass_var = tk.StringVar()

crear_etiqueta(login_content, text="👤 USUARIO", font=(FONT_FAMILY, 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"], anchor="w").pack(fill="x", pady=(0, 3))
entry_user = tk.Entry(
    login_content,
    textvariable=usuario_var,
    font=(FONT_FAMILY, 11),
    bg=t["input_bg"],
    fg=t["input_fg"],
    insertbackground=t["input_insert"],
    relief="solid",
    bd=1
)
entry_user.pack(fill="x", ipady=4, pady=(0, 12))

pass_header = tk.Frame(login_content, bg=t["bg_surface"])
pass_header.pack(fill="x", pady=(0, 3))

crear_etiqueta(pass_header, text="🔒 CONTRASEÑA", font=(FONT_FAMILY, 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"], anchor="w").pack(side="left")

def alternar_mostrar_contrasena(event=None):
    """Alterna la visibilidad de la contraseña escrita sin alterar el contenido del campo."""
    if entry_pass.cget("show") == "*":
        entry_pass.config(show="")
        lbl_toggle_pass.config(text="👁️ Ocultar contraseña")
    else:
        entry_pass.config(show="*")
        lbl_toggle_pass.config(text="👁️ Mostrar contraseña")

lbl_toggle_pass = tk.Label(
    pass_header,
    text="👁️ Mostrar contraseña",
    font=(FONT_FAMILY, 8, "underline"),
    bg=t["bg_surface"],
    fg=COLOR_LOGIN if COLOR_LOGIN != "#FFFFFF" else t["accent"],
    cursor="hand2"
)
lbl_toggle_pass.pack(side="right")
lbl_toggle_pass.bind("<Button-1>", alternar_mostrar_contrasena)

entry_pass = tk.Entry(
    login_content,
    textvariable=pass_var,
    font=(FONT_FAMILY, 11),
    show="*",
    bg=t["input_bg"],
    fg=t["input_fg"],
    insertbackground=t["input_insert"],
    relief="solid",
    bd=1
)
entry_pass.pack(fill="x", ipady=4, pady=(0, 16))

btn_login = crear_boton(
    login_content,
    "🚀 INICIAR SESIÓN",
    comando=validar_usuario,
    tam_fuente=11,
    negrita=True,
    bg_color=COLOR_LOGIN,
    fg_color=FG_LOGIN
)
btn_login.pack(fill="x", pady=(0, 8))

btn_clear = crear_boton(
    login_content,
    "🧹 LIMPIAR CAMPOS",
    comando=limpiar_campos,
    tam_fuente=10,
    negrita=True,
    bg_color=t["btn_secondary_bg"],
    fg_color=t["btn_secondary_fg"]
)
btn_clear.pack(fill="x", pady=(0, 8))

btn_red_link = tk.Button(
    login_content,
    text="🌐 Configurar Servidor / Conexión de Red",
    font=(FONT_FAMILY, 9, "underline"),
    bg=t["bg_surface"],
    fg=COLOR_LOGIN if COLOR_LOGIN != "#FFFFFF" else t["accent"],
    activebackground=t["bg_surface"],
    activeforeground=COLOR_LOGIN,
    highlightbackground=t["bg_surface"],
    bd=0,
    cursor="hand2",
    command=abrir_configuracion_red
)
btn_red_link.pack(fill="x", pady=(4, 0))


import threading

def recargar_identidad_login():
    """Refresca en vivo el título, logo, datos comerciales y colores de la ventana de Login."""
    if threading.current_thread() is not threading.main_thread():
        try:
            if ventana.winfo_exists():
                ventana.after(0, recargar_identidad_login)
        except Exception:
            pass
        return
    if not ventana.winfo_exists():
        return
    try:
        nuevo_titulo = f"{business_mgr.nombre} — {business_mgr.subtitulo} (v4.1.2)" if business_mgr.subtitulo else f"{business_mgr.nombre} — Inicio de Sesión (v4.1.2)"
        ventana.title(nuevo_titulo)
        _renderizar_panel_institucional()
        c_login = business_mgr.color_login or t["accent"]
        if not c_login or c_login.strip().upper() in ("#FFFFFF", "#FFF", "WHITE"):
            c_login = "#1E40AF"
        fg_login = calcular_color_texto_optimo(c_login)
        login_header.configure(bg=c_login)
        login_header_center.configure(bg=c_login)
        lbl_lock_icon.configure(bg=c_login, fg=fg_login)
        lbl_acceso_txt.configure(bg=c_login, fg=fg_login)
        btn_theme_login.configure(bg=c_login, fg=fg_login, activebackground=c_login, activeforeground=fg_login, highlightbackground=c_login)
        btn_net_login.configure(bg=c_login, fg=fg_login, activebackground=c_login, activeforeground=fg_login, highlightbackground=c_login)
        btn_login.configure(bg=c_login, fg=fg_login)
        btn_red_link.configure(fg=c_login if c_login != "#FFFFFF" else t["accent"], activeforeground=c_login)
        if 'lbl_toggle_pass' in globals() and lbl_toggle_pass.winfo_exists():
            lbl_toggle_pass.configure(bg=t["bg_surface"], fg=c_login if c_login != "#FFFFFF" else t["accent"])
    except Exception as e_ref:
        print(f"Aviso refrescando identidad en login: {e_ref}")


business_mgr.agregar_listener(recargar_identidad_login)

ventana.bind("<Return>", validar_usuario)
ventana.bind("<Escape>", limpiar_campos)
entry_user.focus()

def limpiar_para_nuevo_login():
    """Restaura los campos de login listos para la autenticación de un nuevo usuario in-process."""
    try:
        if 'entry_pass' in globals() and entry_pass.winfo_exists():
            entry_pass.delete(0, tk.END)
            entry_pass.config(show="*")
        if 'lbl_toggle_pass' in globals() and lbl_toggle_pass.winfo_exists():
            lbl_toggle_pass.config(text="👁️ Mostrar contraseña")
        if 'entry_user' in globals() and entry_user.winfo_exists():
            entry_user.delete(0, tk.END)
            entry_user.focus_set()
        if 'lbl_status' in globals() and lbl_status.winfo_exists():
            lbl_status.config(text="")
        if 'btn_login' in globals() and btn_login.winfo_exists():
            btn_login.config(state="normal")
    except Exception:
        pass

ventana.limpiar_para_nuevo_login = limpiar_para_nuevo_login
session_mgr.registrar_login_window(ventana)

def forzar_repintado_mac(event=None):
    """
    Fuerza a macOS Cocoa a componer el buffer de dibujo de Tkinter.
    En macOS Aqua, al mapear una ventana Tkinter nueva, AppKit a veces solo renderiza
    los NSButton nativos mientras que los Frames y Labels de Tkinter permanecen sin exponer
    hasta que se produce un cambio de geometría.
    """
    if sys.platform != "darwin":
        return
    try:
        if not ventana.winfo_exists():
            return
        ventana.update_idletasks()
        w = ventana.winfo_width()
        h = ventana.winfo_height()
        if w > 100 and h > 100:
            ventana.geometry(f"{w+1}x{h}")
            ventana.update_idletasks()
            ventana.geometry(f"{w}x{h}")
            ventana.update_idletasks()
        ventana.lift()
        ventana.focus_force()
    except Exception:
        pass

if sys.platform == "darwin":
    ventana.bind("<Map>", lambda e: ventana.after(80, forzar_repintado_mac))


def _autoarrancar_o_sincronizar_red():
    try:
        from interface.network_manager import obtener_config_red, verificar_salud_servidor, iniciar_servidor_segundo_plano
        cfg = obtener_config_red()
        modo = cfg.get("modo", "servidor")
        puerto = int(cfg.get("servidor_puerto", 8000))
        if modo == "servidor":
            ok_salud, _, _, _ = verificar_salud_servidor("127.0.0.1", puerto=puerto, timeout=0.8)
            if not ok_salud:
                iniciar_servidor_segundo_plano()
        else:
            ip_srv = cfg.get("servidor_ip", "127.0.0.1")
            if business_mgr.sincronizar_desde_servidor(ip=ip_srv, puerto=puerto, notificar=False):
                if ventana.winfo_exists():
                    ventana.after(0, recargar_identidad_login)
    except Exception as e_srv:
        print(f"Aviso en sincronización inicial de red: {e_srv}")


if __name__ == "__main__":
    threading.Thread(target=_autoarrancar_o_sincronizar_red, daemon=True).start()
    # Verificación fail-closed de activación inicial (solo en nodo servidor / standalone)
    try:
        try:
            from interface.network_manager import obtener_config_red
        except ImportError:
            from network_manager import obtener_config_red
        _cfg_red_init = obtener_config_red()
        _modo_red_init = str(_cfg_red_init.get("modo", "servidor")).strip().lower()
    except Exception:
        _modo_red_init = "servidor"

    if _modo_red_init != "cliente":
        try:
            try:
                from interface.usuarios_db import hay_administrador, crear_tablas_iniciales
            except ImportError:
                from usuarios_db import hay_administrador, crear_tablas_iniciales
            crear_tablas_iniciales()
            if not hay_administrador():
                ventana.after(350, lambda: abrir_modal_activacion_primer_administrador(ventana))
        except Exception as e_act:
            # Fail-closed: ante fallo de base de datos, informar error explícito y NUNCA abrir activación
            print(f"ERROR CRÍTICO verificando base de datos de usuarios: {e_act}")
            ventana.after(
                350,
                lambda msg=str(e_act): messagebox.showerror(
                    "Error de Base de Datos de Usuarios",
                    f"No fue posible verificar la integridad de la base de datos de usuarios.\n\n"
                    f"Detalle: {msg}\n\n"
                    f"Por seguridad, la activación inicial permanece bloqueada hasta restaurar la base de datos."
                ),
            )

    if sys.platform == "darwin":
        try:
            ventana.update_idletasks()
            ventana.after(100, forzar_repintado_mac)
            ventana.after(300, forzar_repintado_mac)
        except Exception:
            pass
    ventana.lift()
    ventana.focus_force()
    ventana.mainloop()
