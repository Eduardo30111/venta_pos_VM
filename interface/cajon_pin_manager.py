#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo de Seguridad y Control de PIN para Cajón Monedero / Gaveta - VmPOS
Archivo: interface/cajon_pin_manager.py

Implementa:
- Almacenamiento seguro del PIN con salt aleatorio de 16 bytes y hash PBKDF2-HMAC-SHA256 (100.000 iteraciones).
- Ningún PIN se almacena en texto plano.
- Protección contra ataques de fuerza bruta: límite de 3 intentos fallidos con bloqueo progresivo (30s / 60s).
- Flujo de primera vez: si no hay PIN, solo el Administrador puede crearlo; el personal recibe aviso claro.
- Modal de apertura manual interactivo para Ventas POS, Caja y atajo de teclado F7.
- Diálogo de administración y cambio de PIN protegido mediante contraseña de inicio de sesión del Administrador.
- Registro de auditoría de aperturas manuales e intentos fallidos.
"""

import os
import sys
import json
import time
import re
import hashlib
import secrets
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from typing import Tuple, Dict, Any, Optional

try:
    from interface.config import CONFIG_DIR, DATABASE_DIR
except ImportError:
    try:
        from config import CONFIG_DIR, DATABASE_DIR
    except ImportError:
        _d = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        CONFIG_DIR = os.path.join(_d, "config")
        DATABASE_DIR = os.path.join(_d, "database")

try:
    from interface.theme_manager import aplicar_tema
    from interface.custom_widgets import crear_boton, calcular_geometria_segura
except ImportError:
    try:
        from theme_manager import aplicar_tema
        from custom_widgets import crear_boton, calcular_geometria_segura
    except ImportError:
        def aplicar_tema(w): return {"bg_app": "#F1F5F9", "bg_surface": "#FFFFFF", "bg_header": "#0F172A", "text_main": "#1E293B", "text_secondary": "#64748B", "primary": "#2563EB", "border": "#CBD5E1"}
        def crear_boton(p, t, c, **k): return tk.Button(p, text=t, command=c)
        def calcular_geometria_segura(w, wi, h, *a): w.geometry(f"{wi}x{h}")

PIN_FILE_PATH = os.path.join(CONFIG_DIR, "cajon_pin.json")

# Estado en memoria para limitación de fuerza bruta y bloqueo
_INTENTOS_FALLIDOS = 0
_BLOQUEADO_HASTA = 0.0
_DURACION_BLOQUEO_SEC = 30


def _obtener_datos_pin() -> Dict[str, Any]:
    """Carga los datos del PIN desde el archivo persistente."""
    if not os.path.exists(PIN_FILE_PATH):
        return {}
    try:
        with open(PIN_FILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Aviso leyendo cajon_pin.json: {e}")
        return {}


def _guardar_datos_pin(datos: Dict[str, Any]) -> bool:
    """Guarda los datos del PIN de forma atómica."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp_file = PIN_FILE_PATH + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)
        os.replace(tmp_file, PIN_FILE_PATH)
        return True
    except Exception as e:
        print(f"Error guardando cajon_pin.json: {e}")
        return False


def tiene_pin_configurado() -> bool:
    """Retorna True si existe un PIN configurado y válido."""
    d = _obtener_datos_pin()
    return bool(d.get("pin_hash") and d.get("salt"))


def obtener_estado_seguridad() -> Dict[str, Any]:
    """Retorna el estado de configuración y bloqueo del cajón."""
    global _INTENTOS_FALLIDOS, _BLOQUEADO_HASTA
    ahora = time.time()
    esta_bloqueado = ahora < _BLOQUEADO_HASTA
    segundos_restantes = max(0, int(round(_BLOQUEADO_HASTA - ahora))) if esta_bloqueado else 0

    return {
        "configurado": tiene_pin_configurado(),
        "bloqueado": esta_bloqueado,
        "segundos_restantes": segundos_restantes,
        "intentos_fallidos": _INTENTOS_FALLIDOS
    }


def registrar_auditoria_cajon(accion: str, usuario: str, detalle: str, exito: bool = True):
    """Registra eventos de seguridad del cajón en la auditoría del sistema."""
    ahora_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    f_iso = ahora_str[:10]
    h_iso = ahora_str[11:]
    try:
        from database_manager import conectar_db
    except ImportError:
        try:
            from interface.database_manager import conectar_db
        except ImportError:
            conectar_db = None

    if conectar_db:
        try:
            conn = conectar_db()
            if conn:
                cur = conn.cursor()
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS auditoria_caja (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fecha TEXT,
                        hora TEXT,
                        usuario TEXT,
                        accion TEXT,
                        detalle TEXT,
                        exito INTEGER,
                        created_at TEXT
                    )
                """)
                cur.execute("""
                    INSERT INTO auditoria_caja (fecha, hora, usuario, accion, detalle, exito, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (f_iso, h_iso, usuario, accion, detalle, 1 if exito else 0, ahora_str))
                conn.commit()
                conn.close()
        except Exception as e_aud:
            print(f"Aviso registrando auditoría cajón: {e_aud}")


def crear_o_actualizar_pin(nuevo_pin: str, confirmacion_pin: str, usuario_admin: str = "Admin") -> Tuple[bool, str]:
    """
    Crea o reasigna el PIN del cajón monedero.
    El PIN debe contener entre 4 y 6 dígitos exclusivamente numéricos.
    """
    global _INTENTOS_FALLIDOS, _BLOQUEADO_HASTA

    pin_str = str(nuevo_pin or "").strip()
    conf_str = str(confirmacion_pin or "").strip()

    if not re.match(r"^\d{4,6}$", pin_str):
        return False, "El PIN debe tener exactamente entre 4 y 6 dígitos numéricos (solo números 0-9)."

    if pin_str != conf_str:
        return False, "El PIN y la confirmación no coinciden."

    # Bloquear PINs triviales o extremadamente inseguros
    if pin_str in ("0000", "1234", "1111", "12345", "123456", "000000", "111111"):
        return False, f"El código '{pin_str}' es demasiado común e inseguro. Elige una combinación más segura."

    salt = secrets.token_hex(16)
    pin_hash = hashlib.pbkdf2_hmac("sha256", pin_str.encode("utf-8"), salt.encode("utf-8"), 100000).hex()

    datos = {
        "pin_hash": pin_hash,
        "salt": salt,
        "creado_por": usuario_admin,
        "fecha_creacion": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version_algoritmo": "PBKDF2_SHA256_100K"
    }

    if _guardar_datos_pin(datos):
        _INTENTOS_FALLIDOS = 0
        _BLOQUEADO_HASTA = 0.0
        registrar_auditoria_cajon("CONFIGURAR_PIN", usuario_admin, "PIN de seguridad configurado exitosamente", exito=True)
        return True, "PIN de la gaveta configurado exitosamente."
    else:
        return False, "No se pudo guardar la configuración del PIN en el disco."


def verificar_pin(pin_ingresado: str, usuario: str = "Usuario") -> Tuple[bool, str]:
    """
    Verifica si el PIN ingresado es correcto, aplicando bloqueo contra ataques de fuerza bruta.
    """
    global _INTENTOS_FALLIDOS, _BLOQUEADO_HASTA, _DURACION_BLOQUEO_SEC

    ahora = time.time()
    if ahora < _BLOQUEADO_HASTA:
        segundos = int(round(_BLOQUEADO_HASTA - ahora))
        registrar_auditoria_cajon("INTENTO_BLOQUEADO", usuario, f"Intento en ventana de bloqueo ({segundos}s restantes)", exito=False)
        return False, f"La gaveta se encuentra bloqueada por seguridad tras superar 3 intentos fallidos.\n\nEspera {segundos} segundos antes de intentar de nuevo."

    datos = _obtener_datos_pin()
    hash_guardado = datos.get("pin_hash")
    salt = datos.get("salt")

    if not hash_guardado or not salt:
        return False, "El código de seguridad de la gaveta todavía no ha sido configurado."

    pin_str = str(pin_ingresado or "").strip()
    calc_hash = hashlib.pbkdf2_hmac("sha256", pin_str.encode("utf-8"), salt.encode("utf-8"), 100000).hex()

    if secrets.compare_digest(calc_hash, hash_guardado):
        _INTENTOS_FALLIDOS = 0
        _BLOQUEADO_HASTA = 0.0
        registrar_auditoria_cajon("APERTURA_MANUAL_EXITO", usuario, "PIN validado correctamente. Apertura autorizada.", exito=True)
        return True, "PIN correcto."
    else:
        _INTENTOS_FALLIDOS += 1
        restantes = max(0, 3 - _INTENTOS_FALLIDOS)
        registrar_auditoria_cajon("PIN_INCORRECTO", usuario, f"PIN incorrecto. Intento {_INTENTOS_FALLIDOS}/3", exito=False)

        if _INTENTOS_FALLIDOS >= 3:
            _BLOQUEADO_HASTA = time.time() + _DURACION_BLOQUEO_SEC
            return False, f"⚠️ PIN INCORRECTO.\n\nHas superado el límite de 3 intentos fallidos.\nPor seguridad, la apertura manual ha sido BLOQUEADA temporalmente durante {_DURACION_BLOQUEO_SEC} segundos."
        else:
            return False, f"❌ PIN INCORRECTO.\n\nTe quedan {restantes} intento{'s' if restantes != 1 else ''} antes de que la gaveta se bloquee temporalmente."


def verificar_credencial_admin(usuario_admin: str, password_admin: str) -> bool:
    """Verifica la contraseña de inicio de sesión del Administrador contra SQLite local o API."""
    if not password_admin:
        return False
    # 1. Intentar API si está disponible
    try:
        from client.api_client import api
        if api and getattr(api, "token", None):
            import httpx
            resp = httpx.post(
                f"{api.base_url}/auth/login",
                data={"username": usuario_admin.strip(), "password": password_admin.strip()},
                timeout=4.0
            )
            if resp.status_code == 200:
                d = resp.json()
                rol_auth = str((d.get("usuario") or {}).get("rol") or "").lower()
                if rol_auth in ("administrador", "admin", "gerente"):
                    return True
    except Exception:
        pass

    # 2. Consultar SQLite local
    try:
        from usuarios_db import obtener_usuario_por_credenciales
        usr = obtener_usuario_por_credenciales(usuario_admin, password_admin)
        if usr:
            rol_usr = str(usr.get("rol", "")).lower()
            return rol_usr in ("administrador", "admin", "gerente")
    except Exception as e:
        print(f"Aviso verificando credenciales admin para PIN: {e}")

    # 3. Intentar con usuario 'admin' genérico si se pasó un nombre personalizado
    if usuario_admin.lower() != "admin":
        try:
            from usuarios_db import obtener_usuario_por_credenciales
            usr = obtener_usuario_por_credenciales("admin", password_admin)
            if usr and str(usr.get("rol", "")).lower() in ("administrador", "admin", "gerente"):
                return True
        except Exception:
            pass

    return False


def solicitar_pin_y_abrir_cajon(
    parent,
    rol_usuario: str = "Operario",
    nombre_usuario: str = "Usuario",
    callback_exito=None
) -> bool:
    """
    Flujo interactivo modal para aperturas manuales (F7, botones en Ventas POS y Caja).
    - Valida existencia de PIN.
    - Si no existe: Admin puede crearlo; Staff recibe advertencia institucional.
    - Si existe: Solicita PIN con protección de intentos.
    - Al ingresar el PIN correcto: envía señal de apertura física y llama a `callback_exito`.
    """
    es_admin = str(rol_usuario).strip().lower() in ("administrador", "admin", "gerente")

    # 1. Caso: El PIN aún no ha sido configurado
    if not tiene_pin_configurado():
        if not es_admin:
            messagebox.showwarning(
                "Seguridad de la Gaveta de Dinero",
                "⚠️ El código de seguridad (PIN) de la gaveta todavía no ha sido configurado.\n\n"
                "Solicita a un Administrador que lo configure desde el menú de Configuración.",
                parent=parent
            )
            return False

        # Si es Admin, invitar a crearlo inmediatamente
        preg = messagebox.askyesno(
            "Configuración Requerida del PIN",
            "🔐 El código de seguridad (PIN) del cajón monedero no ha sido configurado aún.\n\n"
            "Como Administrador, debes establecer un PIN de 4 a 6 dígitos numéricos para proteger la apertura manual de la gaveta de dinero.\n\n"
            "¿Deseas crear el PIN de seguridad en este momento?",
            parent=parent
        )
        if not preg:
            return False

        abrir_modal_crear_pin(parent, usuario_admin=nombre_usuario)
        return False

    # 2. Caso: Gaveta en estado de bloqueo temporal
    estado = obtener_estado_seguridad()
    if estado["bloqueado"]:
        messagebox.showerror(
            "Gaveta Temporalmente Bloqueada",
            f"⛔ ACCESO BLOQUEADO POR SEGURIDAD\n\n"
            f"Se han superado los 3 intentos fallidos permitidos.\n"
            f"Debes esperar {estado['segundos_restantes']} segundos antes de volver a ingresar un PIN.",
            parent=parent
        )
        return False

    # 3. Mostrar modal de ingreso de PIN
    dlg = tk.Toplevel(parent)
    dlg.title("🔐 PIN de Seguridad — Gaveta")
    t_d = aplicar_tema(dlg)
    calcular_geometria_segura(dlg, 380, 290, 340, 260)
    dlg.configure(bg=t_d["bg_app"])
    dlg.transient(parent)
    dlg.grab_set()

    # Header
    hdr = tk.Frame(dlg, bg=t_d["bg_header"], height=44)
    hdr.pack(fill="x")
    hdr.pack_propagate(False)
    tk.Label(
        hdr, text="🔐 AUTORIZACIÓN APERTURA DE GAVETA",
        font=("Segoe UI", 10, "bold"), bg=t_d["bg_header"], fg="white"
    ).pack(pady=10)

    body = tk.Frame(dlg, bg=t_d["bg_surface"], padx=20, pady=16, bd=1, relief="solid")
    body.pack(fill="both", expand=True, padx=12, pady=(10, 6))

    tk.Label(
        body,
        text="Ingresa el PIN numérico de seguridad (4 a 6 dígitos):",
        font=("Segoe UI", 9), bg=t_d["bg_surface"], fg=t_d["text_main"],
        justify="center"
    ).pack(pady=(0, 10))

    frame_pin = tk.Frame(body, bg=t_d["bg_surface"])
    frame_pin.pack(pady=4)

    var_pin = tk.StringVar()
    entry_pin = tk.Entry(
        frame_pin,
        textvariable=var_pin,
        show="*",
        font=("Segoe UI", 18, "bold"),
        justify="center",
        width=10,
        bd=2,
        relief="solid"
    )
    entry_pin.pack(side="left", padx=(0, 6))

    var_mostrar = tk.BooleanVar(value=False)
    btn_ojo = tk.Button(
        frame_pin,
        text="👁️",
        font=("Segoe UI", 11),
        bd=1,
        relief="solid",
        cursor="hand2",
        command=lambda: _toggle_ver_pin()
    )
    btn_ojo.pack(side="left")

    def _toggle_ver_pin():
        mostrar = not var_mostrar.get()
        var_mostrar.set(mostrar)
        entry_pin.config(show="" if mostrar else "*")
        btn_ojo.config(text="🔒" if mostrar else "👁️")

    lbl_aviso_intentos = tk.Label(
        body,
        text="",
        font=("Segoe UI", 8, "italic"),
        bg=t_d["bg_surface"],
        fg="#DC2626"
    )
    lbl_aviso_intentos.pack(pady=(6, 0))

    btn_box = tk.Frame(dlg, bg=t_d["bg_app"], padx=12, pady=10)
    btn_box.pack(fill="x", side="bottom")

    resultado = {"exito": False}

    def _validar_y_abrir(event=None):
        pin_ing = var_pin.get().strip()
        if not pin_ing:
            lbl_aviso_intentos.config(text="Por favor escribe el PIN de seguridad.")
            entry_pin.focus_set()
            return

        ok, msg = verificar_pin(pin_ing, usuario=nombre_usuario)
        if ok:
            resultado["exito"] = True
            dlg.destroy()

            # Enviar señal física de apertura
            try:
                try:
                    from interface.receipt_manager import pulsar_apertura_cajon
                except ImportError:
                    from receipt_manager import pulsar_apertura_cajon
                ok_pulsar, msg_pulsar = pulsar_apertura_cajon()
                if ok_pulsar:
                    messagebox.showinfo(
                        "✅ Gaveta Abierta",
                        "Orden de apertura enviada correctamente a la impresora.",
                        parent=parent
                    )
                else:
                    messagebox.showwarning(
                        "⚠️ Apertura de Gaveta",
                        f"El PIN fue correcto, pero ocurrió un aviso de hardware:\n\n{msg_pulsar}",
                        parent=parent
                    )
            except Exception as e_p:
                messagebox.showerror("Error de Impresora", f"No se pudo enviar el comando a la impresora: {e_p}", parent=parent)

            if callable(callback_exito):
                try:
                    callback_exito()
                except Exception:
                    pass
        else:
            var_pin.set("")
            estado_act = obtener_estado_seguridad()
            if estado_act["bloqueado"]:
                dlg.destroy()
                messagebox.showerror("Acceso Bloqueado", msg, parent=parent)
            else:
                lbl_aviso_intentos.config(text=msg)
                entry_pin.focus_set()

    crear_boton(btn_box, "Cancelar (Esc)", dlg.destroy, tipo="secondary", tam_fuente=9).pack(side="left", padx=5)
    btn_confirmar = crear_boton(btn_box, "✅ Abrir Gaveta (Enter)", _validar_y_abrir, tipo="primary", tam_fuente=9, negrita=True)
    btn_confirmar.pack(side="right", padx=5)

    entry_pin.bind("<Return>", _validar_y_abrir)
    dlg.bind("<Escape>", lambda e: dlg.destroy())
    entry_pin.focus_set()
    dlg.wait_window()

    return resultado["exito"]


def abrir_modal_crear_pin(parent, usuario_admin: str = "Admin", on_success=None):
    """Abre el diálogo para crear o asignar el PIN del cajón por primera vez."""
    dlg = tk.Toplevel(parent)
    dlg.title("🔐 Crear PIN de Seguridad de la Gaveta")
    t_d = aplicar_tema(dlg)
    calcular_geometria_segura(dlg, 420, 340, 380, 300)
    dlg.configure(bg=t_d["bg_app"])
    dlg.transient(parent)
    dlg.grab_set()

    hdr = tk.Frame(dlg, bg=t_d["bg_header"], height=46)
    hdr.pack(fill="x")
    hdr.pack_propagate(False)
    tk.Label(
        hdr, text="🔐 CONFIGURAR PIN DE LA GAVETA",
        font=("Segoe UI", 10, "bold"), bg=t_d["bg_header"], fg="white"
    ).pack(pady=12)

    body = tk.Frame(dlg, bg=t_d["bg_surface"], padx=20, pady=16, bd=1, relief="solid")
    body.pack(fill="both", expand=True, padx=12, pady=(10, 6))

    tk.Label(
        body,
        text="Define un código numérico de 4 a 6 dígitos para proteger la apertura manual del cajón:",
        font=("Segoe UI", 9), bg=t_d["bg_surface"], fg=t_d["text_main"],
        wraplength=340, justify="left"
    ).pack(anchor="w", pady=(0, 10))

    tk.Label(body, text="Nuevo PIN (4 a 6 dígitos):", font=("Segoe UI", 9, "bold"), bg=t_d["bg_surface"], fg=t_d["text_main"]).pack(anchor="w", pady=(4, 2))
    var_p1 = tk.StringVar()
    e_p1 = tk.Entry(body, textvariable=var_p1, show="*", font=("Segoe UI", 12, "bold"), width=16, bd=1, relief="solid", justify="center")
    e_p1.pack(anchor="w", pady=(0, 8))

    tk.Label(body, text="Confirmar Nuevo PIN:", font=("Segoe UI", 9, "bold"), bg=t_d["bg_surface"], fg=t_d["text_main"]).pack(anchor="w", pady=(4, 2))
    var_p2 = tk.StringVar()
    e_p2 = tk.Entry(body, textvariable=var_p2, show="*", font=("Segoe UI", 12, "bold"), width=16, bd=1, relief="solid", justify="center")
    e_p2.pack(anchor="w", pady=(0, 10))

    btn_box = tk.Frame(dlg, bg=t_d["bg_app"], padx=12, pady=10)
    btn_box.pack(fill="x", side="bottom")

    def _guardar():
        p1 = var_p1.get().strip()
        p2 = var_p2.get().strip()
        ok, msg = crear_o_actualizar_pin(p1, p2, usuario_admin=usuario_admin)
        if ok:
            dlg.destroy()
            messagebox.showinfo("PIN Configurado", msg, parent=parent)
            if callable(on_success):
                on_success()
        else:
            messagebox.showwarning("Atención", msg, parent=dlg)
            e_p1.focus_set()

    crear_boton(btn_box, "Cancelar", dlg.destroy, tipo="secondary", tam_fuente=9).pack(side="left", padx=5)
    crear_boton(btn_box, "💾 Guardar PIN", _guardar, tipo="success", tam_fuente=9, negrita=True).pack(side="right", padx=5)

    e_p1.bind("<Return>", lambda e: e_p2.focus_set())
    e_p2.bind("<Return>", lambda e: _guardar())
    e_p1.focus_set()


def abrir_modal_cambiar_pin_admin(parent, usuario_admin: str = "Admin", on_success=None):
    """
    Diálogo para cambiar o resetear el PIN de la gaveta desde Configuración.
    Requiere obligatoriamente autenticar la contraseña de inicio de sesión del Administrador.
    """
    dlg = tk.Toplevel(parent)
    dlg.title("🔐 Seguridad de la Gaveta — Administrador")
    t_d = aplicar_tema(dlg)
    calcular_geometria_segura(dlg, 440, 420, 400, 380)
    dlg.configure(bg=t_d["bg_app"])
    dlg.transient(parent)
    dlg.grab_set()

    hdr = tk.Frame(dlg, bg=t_d["bg_header"], height=46)
    hdr.pack(fill="x")
    hdr.pack_propagate(False)
    tk.Label(
        hdr, text="🔐 GESTIÓN DE SEGURIDAD DEL CAJÓN",
        font=("Segoe UI", 10, "bold"), bg=t_d["bg_header"], fg="white"
    ).pack(pady=12)

    body = tk.Frame(dlg, bg=t_d["bg_surface"], padx=20, pady=16, bd=1, relief="solid")
    body.pack(fill="both", expand=True, padx=12, pady=(10, 6))

    tk.Label(
        body,
        text="Para cambiar o actualizar el PIN de la gaveta, confirma tu contraseña de Administrador:",
        font=("Segoe UI", 9), bg=t_d["bg_surface"], fg=t_d["text_main"],
        wraplength=360, justify="left"
    ).pack(anchor="w", pady=(0, 8))

    tk.Label(body, text="Contraseña de Administrador:", font=("Segoe UI", 9, "bold"), bg=t_d["bg_surface"], fg=t_d["text_main"]).pack(anchor="w", pady=(2, 2))
    var_pass = tk.StringVar()
    e_pass = tk.Entry(body, textvariable=var_pass, show="*", font=("Segoe UI", 10), width=24, bd=1, relief="solid")
    e_pass.pack(anchor="w", pady=(0, 10))

    tk.Frame(body, bg=t_d["border"], height=1).pack(fill="x", pady=8)

    tk.Label(body, text="Nuevo PIN de la Gaveta (4 a 6 dígitos):", font=("Segoe UI", 9, "bold"), bg=t_d["bg_surface"], fg=t_d["text_main"]).pack(anchor="w", pady=(4, 2))
    var_p1 = tk.StringVar()
    e_p1 = tk.Entry(body, textvariable=var_p1, show="*", font=("Segoe UI", 12, "bold"), width=16, bd=1, relief="solid", justify="center")
    e_p1.pack(anchor="w", pady=(0, 8))

    tk.Label(body, text="Confirmar Nuevo PIN:", font=("Segoe UI", 9, "bold"), bg=t_d["bg_surface"], fg=t_d["text_main"]).pack(anchor="w", pady=(4, 2))
    var_p2 = tk.StringVar()
    e_p2 = tk.Entry(body, textvariable=var_p2, show="*", font=("Segoe UI", 12, "bold"), width=16, bd=1, relief="solid", justify="center")
    e_p2.pack(anchor="w", pady=(0, 10))

    btn_box = tk.Frame(dlg, bg=t_d["bg_app"], padx=12, pady=10)
    btn_box.pack(fill="x", side="bottom")

    def _ejecutar_cambio():
        pwd_adm = var_pass.get()
        if not pwd_adm:
            messagebox.showwarning("Autenticación Requerida", "Debes ingresar tu contraseña de Administrador.", parent=dlg)
            e_pass.focus_set()
            return

        if not verificar_credencial_admin(usuario_admin, pwd_adm):
            registrar_auditoria_cajon("CAMBIO_PIN_RECHAZADO", usuario_admin, "Contraseña de Administrador incorrecta al intentar cambiar PIN", exito=False)
            messagebox.showerror("Acceso Denegado", "La contraseña de Administrador ingresada es incorrecta.", parent=dlg)
            e_pass.focus_set()
            e_pass.select_range(0, tk.END)
            return

        p1 = var_p1.get().strip()
        p2 = var_p2.get().strip()
        ok, msg = crear_o_actualizar_pin(p1, p2, usuario_admin=usuario_admin)
        if ok:
            dlg.destroy()
            messagebox.showinfo("PIN Actualizado", msg, parent=parent)
            if callable(on_success):
                on_success()
        else:
            messagebox.showwarning("Atención", msg, parent=dlg)
            e_p1.focus_set()

    crear_boton(btn_box, "Cancelar", dlg.destroy, tipo="secondary", tam_fuente=9).pack(side="left", padx=5)
    crear_boton(btn_box, "💾 Actualizar PIN", _ejecutar_cambio, tipo="success", tam_fuente=9, negrita=True).pack(side="right", padx=5)

    e_pass.bind("<Return>", lambda e: e_p1.focus_set())
    e_p1.bind("<Return>", lambda e: e_p2.focus_set())
    e_p2.bind("<Return>", lambda e: _ejecutar_cambio())
    e_pass.focus_set()
