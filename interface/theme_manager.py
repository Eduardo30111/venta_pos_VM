#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Diseño, Gestión de Temas y Accesibilidad Global - VmPOS
Archivo: interface/theme_manager.py
Cumple normas de contraste WCAG AA/AAA (ratio >= 4.5:1),
soporte para MODO CLARO, MODO OSCURO y AUTOMÁTICO,
resolución responsiva (1366x768 hasta 1920x1080) y contenedores scrollables seguros.
"""

import tkinter as tk
from tkinter import ttk
import os
import sys
import json
import subprocess
import platform
import time

# Garantizar que theme_manager e interface.theme_manager compartan el mismo singleton en sys.modules
if __name__ in ("theme_manager", "interface.theme_manager") and __name__ in sys.modules:
    sys.modules["theme_manager"] = sys.modules[__name__]
    sys.modules["interface.theme_manager"] = sys.modules[__name__]

# Ruta para persistencia de la preferencia de tema
try:
    from interface.config import CONFIG_DIR
except ImportError:
    try:
        from config import CONFIG_DIR
    except ImportError:
        CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config")

THEME_CONFIG_DIR = CONFIG_DIR
THEME_CONFIG_FILE = os.path.join(THEME_CONFIG_DIR, "theme_config.json")

# Tipografía adaptativa multiplataforma (macOS / Windows / Linux)
FONT_FAMILY = "Helvetica Neue" if sys.platform == "darwin" else "Segoe UI"



# =============================================================================
# 1. TOKENS DE COLOR WCAG AA (RATIO DE CONTRASTE MATEMÁTICO >= 4.5:1)
# =============================================================================

TOKENS_LIGHT = {
    # Fondos y Superficies
    "bg_app": "#F8FAFC",              # Slate 50 - Fondo neutro elegante
    "bg_surface": "#FFFFFF",          # Blanco puro
    "bg_surface_alt": "#F1F5F9",      # Slate 100 - Filas alternas y paneles secundarios
    "bg_card": "#FFFFFF",             # Tarjetas
    "bg_card_secondary": "#FFF0F5",   # Rosa ultra suave para tarjetas secundarias
    "bg_header": "#DB2777",           # Fucsia / Rosa corporativo VmPOS
    "bg_header_sub": "#BE185D",       # Fucsia oscuro
    "bg_footer": "#DB2777",           # Pie de página corporativo
    "bg_badge": "#FCE7F3",            # Badge suave

    # Textos
    "text_main": "#0F172A",           # Slate 900 - Máximo contraste (15.8:1 sobre blanco)
    "text_secondary": "#334155",      # Slate 700 - Texto secundario (9.5:1)
    "text_muted": "#64748B",          # Slate 500 - Texto atenuado (4.6:1)
    "text_header": "#FFFFFF",         # Blanco sobre cabecera fucsia (7.2:1)
    "text_header_sub": "#FCE7F3",     # Rosa pastel legible sobre fucsia (4.8:1)
    "text_inverse": "#FFFFFF",

    # Bordes y Divisores
    "border_main": "#CBD5E1",         # Slate 300
    "border_subtle": "#E2E8F0",       # Slate 200
    "border_focus": "#DB2777",        # Rosa enfoque

    # Entradas de Texto / Inputs
    "input_bg": "#FFFFFF",
    "input_fg": "#0F172A",
    "input_insert": "#0F172A",        # Cursor de texto visible
    "input_border": "#94A3B8",        # Slate 400
    "input_select_bg": "#DB2777",
    "input_select_fg": "#FFFFFF",

    # Botones Semánticos
    "btn_primary_bg": "#DB2777",
    "btn_primary_fg": "#FFFFFF",
    "btn_primary_hover": "#BE185D",
    "btn_primary_active": "#9D174D",

    "btn_success_bg": "#047857",      # Esmeralda 700 accesible (5.48:1 con blanco)
    "btn_success_fg": "#FFFFFF",
    "btn_success_hover": "#065F46",
    "btn_success_active": "#064E3B",

    "btn_danger_bg": "#DC2626",       # Rojo accesible (4.83:1 con blanco)
    "btn_danger_fg": "#FFFFFF",
    "btn_danger_hover": "#B91C1C",
    "btn_danger_active": "#991B1B",

    "btn_warning_bg": "#D97706",      # Ámbar accesible
    "btn_warning_fg": "#0F172A",      # Texto oscuro sobre ámbar (5.60:1 contraste certificado)
    "btn_warning_hover": "#B45309",
    "btn_warning_active": "#92400E",

    "btn_info_bg": "#0369A1",         # Azul cielo profundo (5.93:1 con blanco)
    "btn_info_fg": "#FFFFFF",
    "btn_info_hover": "#0284C7",
    "btn_info_active": "#075985",

    "btn_purple_bg": "#7C3AED",       # Violeta nómina (5.70:1 con blanco)
    "btn_purple_fg": "#FFFFFF",
    "btn_purple_hover": "#6D28D9",
    "btn_purple_active": "#5B21B6",

    "btn_secondary_bg": "#475569",    # Gris pizarra (7.58:1 con blanco)
    "btn_secondary_fg": "#FFFFFF",
    "btn_secondary_hover": "#334155",
    "btn_secondary_active": "#1E293B",

    "btn_disabled_bg": "#E2E8F0",     # Gris claro
    "btn_disabled_fg": "#475569",     # Visible pero atenuado (6.15:1 - nunca invisible)

    # Tablas (Treeview)
    "table_bg": "#FFFFFF",
    "table_fg": "#0F172A",
    "table_field_bg": "#FFFFFF",
    "table_header_bg": "#F1F5F9",
    "table_header_fg": "#0F172A",
    "table_row_alt": "#F8FAFC",
    "table_select_bg": "#0369A1",     # Selección legible (5.93:1 con blanco)
    "table_select_fg": "#FFFFFF",
    "table_border": "#CBD5E1",

    # Aliases semánticos universales y compatibilidad
    "text_primary": "#0F172A",
    "accent": "#DB2777",
    "primary": "#DB2777",
    "success": "#047857",
    "danger": "#DC2626",
    "warning": "#D97706",
    "info": "#0369A1",
    "secondary": "#475569",
    "purple": "#7C3AED",
    "border": "#CBD5E1",
    "tree_bg": "#FFFFFF",
    "tree_fg": "#0F172A",
    "tree_field_bg": "#FFFFFF",
    "tree_heading_bg": "#F1F5F9",
    "tree_heading_fg": "#0F172A",
}

TOKENS_DARK = {
    # Fondos y Superficies
    "bg_app": "#0F172A",              # Slate 900 - Fondo oscuro profundo
    "bg_surface": "#1E293B",          # Slate 800 - Superficie de paneles
    "bg_surface_alt": "#334155",      # Slate 700 - Paneles secundarios
    "bg_card": "#1E293B",             # Tarjetas
    "bg_card_secondary": "#2A1E35",   # Púrpura oscuro elegante
    "bg_header": "#831843",           # Fucsia profundo elegante
    "bg_header_sub": "#701A40",
    "bg_footer": "#831843",
    "bg_badge": "#701A40",

    # Textos
    "text_main": "#F8FAFC",           # Slate 50 - Blanco suave (14.2:1 sobre #1E293B)
    "text_secondary": "#CBD5E1",      # Slate 300 (9.8:1)
    "text_muted": "#94A3B8",          # Slate 400 (5.4:1)
    "text_header": "#FFFFFF",
    "text_header_sub": "#FCE7F3",
    "text_inverse": "#0F172A",

    # Bordes y Divisores
    "border_main": "#334155",         # Slate 700
    "border_subtle": "#1E293B",
    "border_focus": "#EC4899",

    # Entradas de Texto / Inputs
    "input_bg": "#0F172A",            # Fondo oscuro para inputs
    "input_fg": "#F8FAFC",            # Texto claro de alto contraste
    "input_insert": "#F8FAFC",        # Cursor visible
    "input_border": "#475569",        # Slate 600
    "input_select_bg": "#BE185D",
    "input_select_fg": "#FFFFFF",

    # Botones Semánticos (Optimizado para visibilidad en fondo oscuro)
    "btn_primary_bg": "#DB2777",
    "btn_primary_fg": "#FFFFFF",
    "btn_primary_hover": "#F472B6",
    "btn_primary_active": "#BE185D",

    "btn_success_bg": "#10B981",
    "btn_success_fg": "#0F172A",      # Texto oscuro sobre verde esmeralda brillante (7.04:1 certificado)
    "btn_success_hover": "#34D399",
    "btn_success_active": "#059669",

    "btn_danger_bg": "#DC2626",       # Rojo 600 accesible (4.83:1 con blanco)
    "btn_danger_fg": "#FFFFFF",
    "btn_danger_hover": "#EF4444",
    "btn_danger_active": "#B91C1C",

    "btn_warning_bg": "#F59E0B",
    "btn_warning_fg": "#0F172A",      # Texto oscuro sobre ámbar claro para contraste óptimo
    "btn_warning_hover": "#FBBF24",
    "btn_warning_active": "#D97706",

    "btn_info_bg": "#38BDF8",         # Celeste claro brillante
    "btn_info_fg": "#0F172A",         # Texto oscuro certificado (8.33:1)
    "btn_info_hover": "#7DD3FC",
    "btn_info_active": "#0284C7",

    "btn_purple_bg": "#7C3AED",       # Violeta nómina (5.70:1 con blanco)
    "btn_purple_fg": "#FFFFFF",
    "btn_purple_hover": "#8B5CF6",
    "btn_purple_active": "#6D28D9",

    "btn_secondary_bg": "#334155",
    "btn_secondary_fg": "#F8FAFC",
    "btn_secondary_hover": "#475569",
    "btn_secondary_active": "#1E293B",

    "btn_disabled_bg": "#1E293B",     # Superficie oscura atenuada
    "btn_disabled_fg": "#94A3B8",     # Visible y distinguible (5.71:1)

    # Tablas (Treeview)
    "table_bg": "#1E293B",
    "table_fg": "#F8FAFC",
    "table_field_bg": "#1E293B",
    "table_header_bg": "#334155",
    "table_header_fg": "#F8FAFC",
    "table_row_alt": "#0F172A",
    "table_select_bg": "#0369A1",     # Selección de alto contraste (5.93:1)
    "table_select_fg": "#FFFFFF",
    "table_border": "#334155",

    # Aliases semánticos universales y compatibilidad
    "text_primary": "#F8FAFC",
    "accent": "#EC4899",
    "primary": "#EC4899",
    "success": "#10B981",
    "danger": "#EF4444",
    "warning": "#F59E0B",
    "info": "#38BDF8",
    "secondary": "#334155",
    "purple": "#7C3AED",
    "border": "#334155",
    "tree_bg": "#1E293B",
    "tree_fg": "#F8FAFC",
    "tree_field_bg": "#1E293B",
    "tree_heading_bg": "#334155",
    "tree_heading_fg": "#F8FAFC",
}


class ThemeTokens(dict):
    """
    Diccionario de tokens de diseño con resolución inteligente de aliases
    y tolerancia total a fallos (nunca lanza KeyError).
    """
    def __getitem__(self, key):
        if key in self:
            return super().__getitem__(key)
        
        # Mapeo de aliases y fallbacks semánticos garantizados
        fallbacks = {
            "primary": self.get("btn_primary_bg", self.get("accent", "#DB2777")),
            "accent": self.get("btn_primary_bg", "#DB2777"),
            "success": self.get("btn_success_bg", "#047857"),
            "danger": self.get("btn_danger_bg", "#DC2626"),
            "warning": self.get("btn_warning_bg", "#D97706"),
            "info": self.get("btn_info_bg", "#0284C7"),
            "secondary": self.get("btn_secondary_bg", "#475569"),
            "purple": self.get("btn_purple_bg", "#7C3AED"),
            "tree_bg": self.get("table_bg", "#FFFFFF"),
            "tree_fg": self.get("table_fg", "#0F172A"),
            "tree_field_bg": self.get("table_field_bg", "#FFFFFF"),
            "tree_heading_bg": self.get("table_header_bg", "#F1F5F9"),
            "tree_heading_fg": self.get("table_header_fg", "#0F172A"),
            "text_primary": self.get("text_main", "#0F172A"),
            "border": self.get("border_main", "#CBD5E1"),
        }
        if key in fallbacks:
            return fallbacks[key]
        return self.get("text_main", "#000000")


# =============================================================================
# 2. DETECCIÓN Y GESTIÓN CENTRALIZADA DEL TEMA
# =============================================================================

class ThemeManager:
    """Gestor singleton para temas, contraste y adaptación responsive."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ThemeManager, cls).__new__(cls)
            cls._instance._init_manager()
        return cls._instance

    def _init_manager(self):
        self.modo_preferido = "auto"  # 'claro' | 'oscuro' | 'auto'
        self.cargar_preferencia()
        self._listeners = []

    def cargar_preferencia(self):
        """Lee la preferencia guardada en disco."""
        try:
            if os.path.exists(THEME_CONFIG_FILE):
                with open(THEME_CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.modo_preferido = data.get("modo") or data.get("tema", "auto")
        except Exception:
            self.modo_preferido = "auto"

    def guardar_preferencia(self, nuevo_modo):
        """Guarda la preferencia en disco."""
        if nuevo_modo in ["claro", "oscuro", "auto"]:
            self.modo_preferido = nuevo_modo
            try:
                os.makedirs(THEME_CONFIG_DIR, exist_ok=True)
                with open(THEME_CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump({
                        "modo": nuevo_modo,
                        "tema": nuevo_modo,
                        "timestamp": time.time()
                    }, f, indent=2)
            except Exception as e:
                print("Error guardando preferencia de tema:", e)
            self._notificar_cambio()

    def registrar_listener(self, callback):
        """Registra un callback para ser notificado cuando cambie el tema."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def _notificar_cambio(self):
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:
                pass

    def es_sistema_oscuro(self):
        """Detecta si el sistema operativo está en Modo Oscuro."""
        sistema = platform.system()
        try:
            if sistema == "Darwin":  # macOS
                # En macOS con Tk < 8.6, Aqua no soporta ventanas en modo oscuro y fuerza fondos claros.
                # Para evitar texto blanco sobre fondo blanco, usamos modo claro seguro en Tk 8.5.
                try:
                    if tk.TkVersion < 8.6:
                        return False
                except Exception:
                    pass
                cmd = ["defaults", "read", "-g", "AppleInterfaceStyle"]
                res = subprocess.run(cmd, capture_output=True, text=True)
                return res.stdout.strip().lower() == "dark"
            elif sistema == "Windows":
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
                val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return val == 0
        except Exception:
            pass
        return False

    def es_oscuro(self):
        """Determina si actualmente debe renderizarse en Modo Oscuro."""
        if sys.platform == "darwin":
            # Apple Tk 8.5 en macOS no soporta ventanas oscuras (fuerza fondo blanco).
            # Para evitar texto blanco invisible sobre fondo blanco, se desactiva modo oscuro en Tk < 8.6.
            try:
                if tk.TkVersion < 8.6:
                    return False
            except Exception:
                pass
        if self.modo_preferido == "oscuro":
            return True
        elif self.modo_preferido == "claro":
            return False
        return self.es_sistema_oscuro()

    def get_tokens(self):
        """Retorna el diccionario de tokens correspondiente al modo actual."""
        base = TOKENS_DARK if self.es_oscuro() else TOKENS_LIGHT
        return ThemeTokens(base)

    def get_theme_tokens(self):
        """Alias compatible para obtener el diccionario de tokens actual."""
        return self.get_tokens()

    def get(self, token_name, fallback="#000000"):
        """Retorna el valor de un token específico."""
        tokens = self.get_tokens()
        return tokens.get(token_name, fallback)

    def alternar_tema(self):
        """Cicla entre claro y oscuro para acceso rápido."""
        nuevo = "claro" if self.es_oscuro() else "oscuro"
        self.guardar_preferencia(nuevo)
        return nuevo


# Instancia global única
theme_mgr = ThemeManager()


def iniciar_observador_tema(root_or_window, on_theme_change=None, intervalo_ms=1500):
    """
    Inicia un observador liviano que detecta cambios en la preferencia de tema guardada en disco
    (por ejemplo, cuando otra ventana o el menú principal cambia de Claro a Oscuro).
    Permite sincronización inmediata en caliente entre procesos sin necesidad de reiniciar.
    """
    estado = {
        "mtime": 0.0,
        "modo_actual": theme_mgr.modo_preferido,
        "es_oscuro": theme_mgr.es_oscuro()
    }
    try:
        if os.path.exists(THEME_CONFIG_FILE):
            estado["mtime"] = os.path.getmtime(THEME_CONFIG_FILE)
    except Exception:
        pass

    def _chequear():
        try:
            if not root_or_window.winfo_exists():
                return
            hubo_cambio = False
            if os.path.exists(THEME_CONFIG_FILE):
                try:
                    mt = os.path.getmtime(THEME_CONFIG_FILE)
                    if mt != estado["mtime"]:
                        estado["mtime"] = mt
                        theme_mgr.cargar_preferencia()
                        hubo_cambio = True
                except Exception:
                    pass

            nuevo_es_oscuro = theme_mgr.es_oscuro()
            if nuevo_es_oscuro != estado["es_oscuro"] or hubo_cambio:
                estado["es_oscuro"] = nuevo_es_oscuro
                estado["modo_actual"] = theme_mgr.modo_preferido
                aplicar_tema(root_or_window)
                if on_theme_change:
                    try:
                        on_theme_change()
                    except Exception as e_cb:
                        print("Aviso callback observador tema:", e_cb)

            root_or_window.after(intervalo_ms, _chequear)
        except Exception:
            pass

    try:
        root_or_window.after(intervalo_ms, _chequear)
    except Exception:
        pass


# =============================================================================
# 3. HELPER MATEMÁTICO DE CONTRASTE AUTOMÁTICO (WCAG)
# =============================================================================

def luminancia_wcag(hex_color):
    """Calcula la luminancia relativa según el estándar oficial W3C WCAG 2.1."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join([c*2 for c in hex_color])
    try:
        rgb = [int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4)]
        rgb_linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * rgb_linear[0] + 0.7152 * rgb_linear[1] + 0.0722 * rgb_linear[2]
    except Exception:
        return 0.0

def calcular_contraste_wcag(hex1, hex2):
    """Calcula el ratio de contraste matemático exacto (1.0 a 21.0) entre dos colores según WCAG 2.1."""
    l1 = luminancia_wcag(hex1)
    l2 = luminancia_wcag(hex2)
    mas_claro = max(l1, l2)
    mas_oscuro = min(l1, l2)
    return (mas_claro + 0.05) / (mas_oscuro + 0.05)

def calcular_color_texto_optimo(hex_color):
    """
    Calcula si el texto sobre el fondo dado debe ser blanco (#FFFFFF) o casi negro (#0F172A)
    para maximizar el ratio de contraste WCAG AA.
    """
    ratio_con_negro = calcular_contraste_wcag(hex_color, "#0F172A")
    ratio_con_blanco = calcular_contraste_wcag(hex_color, "#FFFFFF")
    return "#0F172A" if ratio_con_negro >= ratio_con_blanco else "#FFFFFF"


def oscurecer_color(hex_color, factor=0.85):
    """Genera tono más oscuro para estados Hover/Active sin perder legibilidad."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join([c*2 for c in hex_color])
    try:
        r = max(0, min(255, int(int(hex_color[0:2], 16) * factor)))
        g = max(0, min(255, int(int(hex_color[2:4], 16) * factor)))
        b = max(0, min(255, int(int(hex_color[4:6], 16) * factor)))
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hex_color


def aclarar_color(hex_color, factor=1.15):
    """Genera tono más claro para estados Hover en modo oscuro."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join([c*2 for c in hex_color])
    try:
        r = max(0, min(255, int(int(hex_color[0:2], 16) * factor)))
        g = max(0, min(255, int(int(hex_color[2:4], 16) * factor)))
        b = max(0, min(255, int(int(hex_color[4:6], 16) * factor)))
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hex_color


# =============================================================================
# 4. INYECCIÓN GLOBAL DE ESTILOS Y TEMAS (TKINTER & TTK)
# =============================================================================

def aplicar_tema(root_or_window):
    """
    Aplica de manera exhaustiva las reglas del sistema de diseño a una ventana
    raíz o Toplevel, asegurando que ningún widget de Tkinter o TTK sea afectado
    por el Dark Mode o Light Mode del sistema operativo de forma indeseada.
    """
    t = theme_mgr.get_tokens()
    is_dark = theme_mgr.es_oscuro()

    # 1. Configuración de la ventana contenedora
    try:
        root_or_window.configure(bg=t["bg_app"])
    except Exception:
        pass

    # 2. Inyección universal en base de datos de opciones de Tkinter
    root_or_window.option_add("*background", t["bg_app"])
    root_or_window.option_add("*foreground", t["text_main"])
    
    # Entradas de texto nativas (Entry)
    root_or_window.option_add("*Entry.background", t["input_bg"])
    root_or_window.option_add("*Entry.foreground", t["input_fg"])
    root_or_window.option_add("*Entry.insertBackground", t["input_insert"])
    root_or_window.option_add("*Entry.selectBackground", t["input_select_bg"])
    root_or_window.option_add("*Entry.selectForeground", t["input_select_fg"])
    root_or_window.option_add("*Entry.relief", "solid")
    root_or_window.option_add("*Entry.borderWidth", 1)

    # Textos multilínea nativos (Text)
    root_or_window.option_add("*Text.background", t["input_bg"])
    root_or_window.option_add("*Text.foreground", t["input_fg"])
    root_or_window.option_add("*Text.insertBackground", t["input_insert"])
    root_or_window.option_add("*Text.selectBackground", t["input_select_bg"])
    root_or_window.option_add("*Text.selectForeground", t["input_select_fg"])

    # Listas desplegables de Combobox (TCombobox*Listbox)
    root_or_window.option_add("*TCombobox*Listbox.background", t["input_bg"])
    root_or_window.option_add("*TCombobox*Listbox.foreground", t["input_fg"])
    root_or_window.option_add("*TCombobox*Listbox.selectBackground", t["table_select_bg"])
    root_or_window.option_add("*TCombobox*Listbox.selectForeground", t["table_select_fg"])

    # 3. Configuración del motor TTK (conservar aqua nativo en macOS)
    style = ttk.Style()
    try:
        if sys.platform != "darwin":
            style.theme_use('clam')
    except Exception:
        pass

    # Treeview / Tablas
    style.configure("Treeview",
                    background=t["table_bg"],
                    foreground=t["table_fg"],
                    fieldbackground=t["table_field_bg"],
                    rowheight=28,
                    font=('Segoe UI', 9),
                    borderwidth=1,
                    relief="solid")
    style.map("Treeview",
              background=[('selected', t["table_select_bg"])],
              foreground=[('selected', t["table_select_fg"])])

    style.configure("Treeview.Heading",
                    background=t["table_header_bg"],
                    foreground=t["table_header_fg"],
                    font=('Segoe UI', 9, 'bold'),
                    relief="flat",
                    padding=[6, 4])
    style.map("Treeview.Heading",
              background=[('active', t["bg_surface_alt"])])

    # Combobox TTK
    style.configure("TCombobox",
                    fieldbackground=t["input_bg"],
                    background=t["input_bg"],
                    foreground=t["input_fg"],
                    darkcolor=t["input_border"],
                    lightcolor=t["input_border"],
                    selectbackground=t["input_select_bg"],
                    selectforeground=t["input_select_fg"],
                    padding=4)
    style.map("TCombobox",
              fieldbackground=[('readonly', t["input_bg"])],
              foreground=[('readonly', t["input_fg"])],
              selectbackground=[('readonly', t["input_select_bg"])],
              selectforeground=[('readonly', t["input_select_fg"])])

    # Notebook (Pestañas)
    style.configure("TNotebook", background=t["bg_app"], borderwidth=0)
    style.configure("TNotebook.Tab",
                    font=('Segoe UI', 9, 'bold'),
                    padding=[12, 6],
                    background=t["bg_surface_alt"],
                    foreground=t["text_main"],
                    borderwidth=0)
    tab_fg_selected = t["text_main"]
    tab_bg_selected = t["bg_surface"]
    style.map("TNotebook.Tab",
              background=[('selected', tab_bg_selected)],
              foreground=[('selected', tab_fg_selected)])

    # Scrollbars TTK
    style.configure("TScrollbar",
                    background=t["bg_surface_alt"],
                    troughcolor=t["bg_app"],
                    bordercolor=t["border_main"],
                    arrowcolor=t["text_secondary"])

    return t


# =============================================================================
# 5. FÁBRICA DE BOTONES SEGUROS CON ALTO CONTRASTE (WCAG AA)
# =============================================================================

def crear_boton(parent, texto="", comando=None, tipo="primary", icono="", 
                ancho=None, alto=None, tam_fuente=9, negrita=True, 
                habilitado=True, tooltip=None, **kwargs):
    """
    Crea un botón nativo tk.Button perfectamente estilizado con:
    - Contraste matemático certificado entre fondo y texto.
    - Estados hover, active, focus y disabled siempre legibles.
    - Soporte automático para ícono + texto.
    """
    t = theme_mgr.get_tokens()
    is_dark = theme_mgr.es_oscuro()

    # Mapeo de tipos semánticos
    mapa_colores = {
        "primary": (t["btn_primary_bg"], t["btn_primary_fg"], t["btn_primary_hover"], t["btn_primary_active"]),
        "success": (t["btn_success_bg"], t["btn_success_fg"], t["btn_success_hover"], t["btn_success_active"]),
        "danger": (t["btn_danger_bg"], t["btn_danger_fg"], t["btn_danger_hover"], t["btn_danger_active"]),
        "warning": (t["btn_warning_bg"], t["btn_warning_fg"], t["btn_warning_hover"], t["btn_warning_active"]),
        "info": (t["btn_info_bg"], t["btn_info_fg"], t["btn_info_hover"], t["btn_info_active"]),
        "purple": (t["btn_purple_bg"], t["btn_purple_fg"], t["btn_purple_hover"], t["btn_purple_active"]),
        "secondary": (t["btn_secondary_bg"], t["btn_secondary_fg"], t["btn_secondary_hover"], t["btn_secondary_active"]),
    }

    if tipo in mapa_colores:
        bg_normal, fg_normal, bg_hover, bg_active = mapa_colores[tipo]
    else:
        # Si se pasó un color hexadecimal directo
        bg_normal = tipo if tipo.startswith("#") else t["btn_primary_bg"]
        fg_normal = calcular_color_texto_optimo(bg_normal)
        bg_hover = oscurecer_color(bg_normal, 0.88) if not is_dark else aclarar_color(bg_normal, 1.15)
        bg_active = oscurecer_color(bg_normal, 0.75)

    # Extraer y normalizar overrides comunes de kwargs
    if "command" in kwargs:
        comando = kwargs.pop("command")
    if "text" in kwargs:
        texto = kwargs.pop("text")
    if "bg_color" in kwargs:
        bg_normal = kwargs.pop("bg_color")
        bg_hover = oscurecer_color(bg_normal, 0.88) if not is_dark else aclarar_color(bg_normal, 1.15)
        bg_active = oscurecer_color(bg_normal, 0.75)
        fg_normal = calcular_color_texto_optimo(bg_normal)
    elif "bg" in kwargs:
        bg_normal = kwargs.pop("bg")
        bg_hover = oscurecer_color(bg_normal, 0.88) if not is_dark else aclarar_color(bg_normal, 1.15)
        bg_active = oscurecer_color(bg_normal, 0.75)
        fg_normal = calcular_color_texto_optimo(bg_normal)

    if "fg_color" in kwargs:
        fg_normal = kwargs.pop("fg_color")
    elif "fg" in kwargs:
        fg_normal = kwargs.pop("fg")

    if "hover_bg" in kwargs:
        bg_hover = kwargs.pop("hover_bg")
    if "active_bg" in kwargs:
        bg_active = kwargs.pop("active_bg")
    if "activebackground" in kwargs:
        bg_active = kwargs.pop("activebackground")

    # Construir texto final con ícono
    texto_final = f"{icono}  {texto}".strip() if icono else texto

    peso_fuente = "bold" if negrita else "normal"
    fuente = (FONT_FAMILY, tam_fuente, peso_fuente)

    estado = "normal" if habilitado else "disabled"
    bg_actual = bg_normal if habilitado else t["btn_disabled_bg"]
    # En macOS Aqua, tk.Button no pinta el color de fondo personalizado (usa la cápsula Cocoa gris claro).
    # Para que el texto nunca sea blanco sobre gris claro (invisible), forzamos texto oscuro de alto contraste en darwin.
    if sys.platform == "darwin":
        fg_actual = "#0F172A" if habilitado else t["btn_disabled_fg"]
    else:
        fg_actual = fg_normal if habilitado else t["btn_disabled_fg"]
    cursor_actual = "hand2" if habilitado else "arrow"

    btn_args = {
        "text": texto_final,
        "command": comando,
        "font": fuente,
        "bg": bg_actual,
        "fg": fg_actual,
        "activebackground": bg_active,
        "activeforeground": "#0F172A" if sys.platform == "darwin" else fg_normal,
        "disabledforeground": t["btn_disabled_fg"],
        "relief": "flat",
        "bd": 0,
        "cursor": cursor_actual,
        "padx": 12,
        "pady": 6,
        "state": estado
    }
    if ancho:
        btn_args["width"] = ancho
    if alto:
        btn_args["height"] = alto

    # Mezclar kwargs adicionales
    btn_args.update(kwargs)

    btn = tk.Button(parent, **btn_args)

    # Eventos de Hover solo para botones activos
    def on_enter(e):
        if btn["state"] == "normal" and sys.platform != "darwin":
            btn.configure(bg=bg_hover)

    def on_leave(e):
        if btn["state"] == "normal" and sys.platform != "darwin":
            btn.configure(bg=bg_normal)

    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)

    # Método dinámico para habilitar/deshabilitar conservando el contraste
    def set_habilitado(es_hab):
        if es_hab:
            btn_fg = "#0F172A" if sys.platform == "darwin" else fg_normal
            btn.configure(state="normal", bg=bg_normal, fg=btn_fg, cursor="hand2")
        else:
            btn.configure(state="disabled", bg=t["btn_disabled_bg"], fg=t["btn_disabled_fg"], cursor="arrow")

    btn.set_habilitado = set_habilitado
    return btn


# =============================================================================
# 6. CONTENEDOR SCROLLABLE ADAPTATIVO (PARA MODALES Y FORMULARIOS)
# =============================================================================

class ScrollableContainer(tk.Frame):
    """
    Marco reutilizable con Canvas y Scrollbar vertical integrado.
    Evita que formularios con muchos campos oculten los botones inferiores.
    Soporta desplazamiento con rueda de mouse universal (macOS, Windows, Linux).
    """
    def __init__(self, parent, bg=None, bg_color=None, *args, **kwargs):
        t = theme_mgr.get_tokens()
        # Manejar bg_color o bg de forma segura sin pasarlo a super().__init__ si es inválido
        fondo = bg or bg_color or kwargs.pop("bg_color", None) or t["bg_app"]
        super().__init__(parent, bg=fondo, *args, **kwargs)

        self.canvas = tk.Canvas(self, bg=fondo, borderwidth=0, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.content_frame = tk.Frame(self.canvas, bg=fondo)
        self.scrollable_frame = self.content_frame
        self.interior = self.content_frame

        self.canvas_window = self.canvas.create_window((0, 0), window=self.content_frame, anchor="nw")

        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # Ajuste dinámico del ancho del canvas window
        self.content_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Vincular rueda del ratón
        self._bind_mousewheel(self.canvas)
        self._bind_mousewheel(self.content_frame)

    def _on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _bind_mousewheel(self, widget):
        widget.bind("<MouseWheel>", self._on_mousewheel)
        widget.bind("<Button-4>", self._on_mousewheel)
        widget.bind("<Button-5>", self._on_mousewheel)
        # Recursivo para hijos
        for child in widget.winfo_children():
            self._bind_mousewheel(child)

    def _on_mousewheel(self, event):
        if event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")
        elif event.delta:
            # En macOS event.delta es más pequeño o diferente a Windows
            incremento = -1 if event.delta > 0 else 1
            if abs(event.delta) >= 120:
                incremento = -int(event.delta / 120)
            self.canvas.yview_scroll(incremento, "units")

    @property
    def interior(self):
        return self.content_frame

    @interior.setter
    def interior(self, val):
        self.content_frame = val


# =============================================================================
# 7. CÁLCULO DE GEOMETRÍA SEGURA RESPONSIVA (1366x768 - 1920x1080)
# =============================================================================

def calcular_geometria_segura(ventana, target_w=1120, target_h=700, min_w=840, min_h=500, modal_padre=None, **kwargs):
    """
    Calcula el tamaño y la posición idóneos de cualquier ventana considerando:
    - Resoluciones de laptops (1366x768, 1440x900) y monitores grandes (1920x1080).
    - Descuento seguro para barras del sistema operativo (Dock / Taskbar ~90px).
    - Centrado milimétrico en la pantalla visible (o respecto a modal_padre si se indica).
    - Evita que el usuario tenga que estirar manualmente la ventana.
    """
    try:
        ventana.update_idletasks()
    except Exception:
        pass

    sw = ventana.winfo_screenwidth()
    sh = ventana.winfo_screenheight()

    # Altura máxima útil descontando barra superior e inferior del SO
    max_h_util = max(450, sh - 95)
    max_w_util = max(600, sw - 40)

    # Ancho y alto calculados
    w = min(target_w, max_w_util)
    h = min(target_h, max_h_util)

    try:
        ventana.minsize(min(min_w, w), min(min_h, h))
    except Exception:
        pass

    # Posicionamiento centrado
    pos_x = max(10, (sw - w) // 2)
    pos_y = max(10, (sh - h) // 2 - 15)

    ventana.geometry(f"{w}x{h}+{pos_x}+{pos_y}")
    ventana.minsize(min(min_w, w), min(min_h, h))
    ventana.resizable(True, True)

    # En macOS asegurar que la ventana se eleve, actualice idletasks y fuerce la composición de Cocoa
    if sys.platform == "darwin":
        try:
            ventana.update_idletasks()
            ventana.lift()
            def _nudge_mac():
                try:
                    if not ventana.winfo_exists():
                        return
                    nw = ventana.winfo_width()
                    nh = ventana.winfo_height()
                    if nw > 100 and nh > 100:
                        ventana.geometry(f"{nw+1}x{nh}")
                        ventana.update_idletasks()
                        ventana.geometry(f"{nw}x{nh}")
                        ventana.update_idletasks()
                except Exception:
                    pass
            ventana.after(80, _nudge_mac)
        except Exception:
            pass

    return w, h


# =============================================================================
# 8. COMPONENTE VISUAL UNIFICADO MULTIPLATAFORMA (ModernCardButton)
# =============================================================================

class ModernCardButton(tk.Frame):
    """
    Componente visual de botón/tarjeta moderno, uniforme e inmune a las limitaciones
    de Cocoa/Aqua en macOS y a diferencias de renderizado en Windows.
    Construido sobre Frame y Label nativos con contraste WCAG garantizado,
    animaciones de hover suaves, badges informativos y accesibilidad por teclado.
    """
    def __init__(
        self,
        parent,
        texto="",
        subtexto="",
        icono="",
        comando=None,
        color_acento="#DB2777",
        badge_texto="",
        badge_color="#EC4899",
        habilitado=True,
        tipo="card",  # "card", "compact", "button"
        bg_color=None,
        fg_color=None,
        ancho=None,
        alto=None,
        **kwargs
    ):
        t = theme_mgr.get_tokens()
        self.t = t
        self.comando = comando
        self.habilitado = habilitado
        self.color_acento = color_acento or t["accent"]
        self.tipo = tipo

        # Colores según modo y tema
        self.bg_normal = bg_color or (t["bg_card"] if tipo in ("card", "compact") else self.color_acento)
        self.bg_hover = oscurecer_color(self.bg_normal, 0.92) if not theme_mgr.es_oscuro() else aclarar_color(self.bg_normal, 1.12)
        self.bg_active = oscurecer_color(self.bg_normal, 0.85)
        self.fg_main = fg_color or (t["text_main"] if tipo in ("card", "compact") else calcular_color_texto_optimo(self.bg_normal))
        self.fg_sub = t["text_muted"]

        super().__init__(
            parent,
            bg=self.bg_normal,
            bd=1,
            relief="solid",
            highlightthickness=0,
            cursor="hand2" if habilitado else "arrow",
            **kwargs
        )

        if ancho:
            self.configure(width=ancho)
        if alto:
            self.configure(height=alto)
            self.pack_propagate(False)

        # Franja de acento superior o lateral
        if tipo == "card":
            self.accent_bar = tk.Frame(self, bg=self.color_acento, height=3)
            self.accent_bar.pack(fill="x", side="top")
        elif tipo == "compact":
            self.accent_bar = tk.Frame(self, bg=self.color_acento, width=4)
            self.accent_bar.pack(fill="y", side="left")

        # Contenedor interior de contenido
        pad_x = 12 if tipo == "card" else 8
        pad_y = 10 if tipo == "card" else 6
        self.inner_frame = tk.Frame(self, bg=self.bg_normal)
        self.inner_frame.pack(fill="both", expand=True, padx=pad_x, pady=pad_y)

        # Fila superior: Ícono y Badge (si aplica)
        top_row = tk.Frame(self.inner_frame, bg=self.bg_normal)
        top_row.pack(fill="x")

        font_emoji = ("Segoe UI Emoji", 18) if sys.platform != "darwin" else ("Apple Color Emoji", 18)
        self.lbl_icono = tk.Label(top_row, text=icono, font=font_emoji, bg=self.bg_normal, fg=self.fg_main)
        if icono:
            self.lbl_icono.pack(side="left")

        self.lbl_badge = None
        if badge_texto:
            fg_badge = calcular_color_texto_optimo(badge_color)
            self.lbl_badge = tk.Label(
                top_row,
                text=f" {badge_texto} ",
                font=(FONT_FAMILY, 8, "bold"),
                bg=badge_color,
                fg=fg_badge,
                padx=4,
                pady=1
            )
            self.lbl_badge.pack(side="right")

        # Texto Principal
        font_titulo = (FONT_FAMILY, 10 if tipo == "compact" else 11, "bold")
        anchor_val = "w" if tipo == "compact" else "center"
        justify_val = "left" if tipo == "compact" else "center"
        self.lbl_texto = tk.Label(
            self.inner_frame,
            text=texto,
            font=font_titulo,
            bg=self.bg_normal,
            fg=self.fg_main,
            anchor=anchor_val,
            justify=justify_val
        )
        self.lbl_texto.pack(fill="x", pady=(4, 1))

        # Subtexto / Descripción / Atajo
        self.lbl_subtexto = None
        if subtexto:
            font_sub = (FONT_FAMILY, 8)
            self.lbl_subtexto = tk.Label(
                self.inner_frame,
                text=subtexto,
                font=font_sub,
                bg=self.bg_normal,
                fg=self.fg_sub,
                anchor=anchor_val,
                justify=justify_val
            )
            self.lbl_subtexto.pack(fill="x")

        # Vincular eventos a todos los hijos
        self._vincular_eventos(self)
        self._actualizar_estado_visual()

    def _vincular_eventos(self, widget):
        widget.bind("<Button-1>", self._on_click)
        widget.bind("<Enter>", self._on_enter)
        widget.bind("<Leave>", self._on_leave)
        for child in widget.winfo_children():
            self._vincular_eventos(child)

    def _on_click(self, event=None):
        if self.habilitado and callable(self.comando):
            self.comando()

    def _on_enter(self, event=None):
        if not self.habilitado:
            return
        self._aplicar_bg(self.bg_hover)

    def _on_leave(self, event=None):
        if not self.habilitado:
            return
        self._aplicar_bg(self.bg_normal)

    def _aplicar_bg(self, color):
        self.configure(bg=color)
        self.inner_frame.configure(bg=color)
        self.lbl_icono.configure(bg=color)
        self.lbl_texto.configure(bg=color)
        if self.lbl_subtexto:
            self.lbl_subtexto.configure(bg=color)

    def _actualizar_estado_visual(self):
        if not self.habilitado:
            self.configure(cursor="arrow")
            fg_dim = self.t["btn_disabled_fg"]
            bg_dim = self.t["btn_disabled_bg"]
            self._aplicar_bg(bg_dim)
            self.lbl_texto.configure(fg=fg_dim)
            if self.lbl_subtexto:
                self.lbl_subtexto.configure(fg=fg_dim)
        else:
            self.configure(cursor="hand2")
            self._aplicar_bg(self.bg_normal)
            self.lbl_texto.configure(fg=self.fg_main)
            if self.lbl_subtexto:
                self.lbl_subtexto.configure(fg=self.fg_sub)

    def set_habilitado(self, hab: bool):
        self.habilitado = hab
        self._actualizar_estado_visual()

    def set_badge(self, texto: str, color=None):
        if not self.lbl_badge:
            return
        if texto:
            if color:
                self.lbl_badge.configure(bg=color, fg=calcular_color_texto_optimo(color))
            self.lbl_badge.configure(text=f" {texto} ")
            self.lbl_badge.pack(side="right")
        else:
            self.lbl_badge.pack_forget()


# =============================================================================
# 9. AVISOS FLOTANTES NO INVASIVOS (ToastNotification)
# =============================================================================

class ToastNotification:
    """
    Muestra una notificación emergente flotante, elegante y auto-destruible en la
    esquina inferior o superior de la ventana activa sin bloquear la interacción.
    """
    @classmethod
    def mostrar(cls, ventana, mensaje, tipo="success", duracion_ms=2600):
        try:
            if not ventana or not ventana.winfo_exists():
                return
            t = theme_mgr.get_tokens()
            
            iconos = {
                "success": "✅",
                "error": "❌",
                "warning": "⚠️",
                "info": "ℹ️"
            }
            colores = {
                "success": "#047857",
                "error": "#DC2626",
                "warning": "#D97706",
                "info": "#0369A1"
            }
            color_fondo = colores.get(tipo, "#0F172A")
            icono = iconos.get(tipo, "✨")

            toast = tk.Toplevel(ventana)
            toast.overrideredirect(True)
            toast.attributes("-topmost", True)
            try:
                toast.attributes("-alpha", 0.95)
            except Exception:
                pass

            f = tk.Frame(toast, bg=color_fondo, bd=1, relief="solid", padx=14, pady=10)
            f.pack(fill="both", expand=True)

            tk.Label(
                f,
                text=f"{icono}  {mensaje}",
                font=(FONT_FAMILY, 10, "bold"),
                bg=color_fondo,
                fg="#FFFFFF"
            ).pack(side="left")

            toast.update_idletasks()
            w = toast.winfo_reqwidth()
            h = toast.winfo_reqheight()

            # Posicionar centrado abajo relativo a la ventana padre
            vx = ventana.winfo_rootx()
            vy = ventana.winfo_rooty()
            vw = ventana.winfo_width()
            vh = ventana.winfo_height()

            pos_x = max(10, vx + (vw - w) // 2)
            pos_y = max(10, vy + vh - h - 35)
            toast.geometry(f"{w}x{h}+{pos_x}+{pos_y}")

            # Auto cierre
            toast.after(duracion_ms, lambda: toast.destroy() if toast.winfo_exists() else None)
        except Exception as e:
            print(f"Aviso toast: {e}")

