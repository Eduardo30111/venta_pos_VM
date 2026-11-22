#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pantalla de carga optimizada para Sistema VM
Archivo: interface/pantalla_carga.py
"""

import tkinter as tk
import math
import threading
import subprocess
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from interface.theme_manager import theme_mgr, aplicar_tema

# Configuración de rutas para PyInstaller
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Tipografía adaptativa multiplataforma (macOS / Windows / Linux)
FONT_FAMILY = "Helvetica Neue" if sys.platform == "darwin" else "Segoe UI"
FONT_EMOJI = "Apple Color Emoji" if sys.platform == "darwin" else "Segoe UI Emoji"

# Variable de control de sesión para asegurar una única reproducción por inicio de sesión
_ULTIMA_VOZ_REPRODUCIDA = None

def generar_saludo_bienvenida(nombre):
    """
    Genera el saludo de bienvenida dinámico respetando concordancia de género:
    'Bienvenido, [nombre]' o 'Bienvenida, [nombre]'.
    """
    if not nombre or not str(nombre).strip():
        return "Bienvenido"
    
    nombre_limpio = str(nombre).strip()
    partes = nombre_limpio.split()
    primer_nombre = partes[0].capitalize() if partes else "Usuario"
    
    # Excepciones masculinas comunes que terminan en 'a'
    nombres_masculinos_en_a = {
        "joshua", "luca", "luka", "noah", "sasha", "bautista", "elias", "matias", 
        "borja", "ventura", "ezra", "isaias", "jeremias"
    }
    nombre_lower = primer_nombre.lower()
    
    # Detección femenina: terminaciones en 'a', 'ia', 'th'
    es_femenino = (
        (nombre_lower.endswith("a") or nombre_lower.endswith("ia") or nombre_lower.endswith("th"))
        and nombre_lower not in nombres_masculinos_en_a
    )
    
    prefijo = "Bienvenida" if es_femenino else "Bienvenido"
    return f"{prefijo}, {primer_nombre}"

def _reproducir_macos(mensaje):
    """Reproducción nativa en macOS utilizando /usr/bin/say sin dependencias."""
    voces_preferidas = ["Paulina", "Mónica", "Eddy (Español (México))", "Flo (Español (España))"]
    for voz in voces_preferidas:
        try:
            res = subprocess.run(
                ["say", "-v", voz, mensaje],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=6
            )
            if res.returncode == 0:
                return True
        except Exception:
            continue
    try:
        res = subprocess.run(
            ["say", mensaje],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=6
        )
        return res.returncode == 0
    except Exception:
        return False

def _reproducir_pyttsx3(mensaje):
    """Reproducción con pyttsx3 si la librería está disponible en el entorno."""
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty('rate', 165)
        engine.setProperty('volume', 0.9)
        try:
            voices = engine.getProperty('voices')
            for v in voices:
                v_desc = (getattr(v, 'name', '') + ' ' + getattr(v, 'id', '')).lower()
                if any(k in v_desc for k in ['spanish', 'español', 'es-es', 'es-mx', 'sabina', 'helena', 'raul', 'pablo']):
                    engine.setProperty('voice', v.id)
                    break
        except Exception:
            pass
        engine.say(mensaje)
        engine.runAndWait()
        return True
    except Exception:
        return False

def _reproducir_windows_powershell(mensaje):
    """Reproducción nativa en Windows sin dependencias mediante PowerShell SAPI/System.Speech."""
    mensaje_seguro = mensaje.replace("'", "''").replace('"', '').replace(';', ',')
    try:
        cmd_speech = (
            f"Add-Type -AssemblyName System.Speech; "
            f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.Rate = 0; "
            f"$s.Speak('{mensaje_seguro}')"
        )
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", cmd_speech],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8
        )
        if res.returncode == 0:
            return True
    except Exception:
        pass

    try:
        cmd_sapi = f"$v = New-Object -ComObject SAPI.SpVoice; $v.Speak('{mensaje_seguro}')"
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", cmd_sapi],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8
        )
        return res.returncode == 0
    except Exception:
        return False

def _reproducir_linux(mensaje):
    """Reproducción nativa en Linux mediante spd-say o espeak."""
    for cmd in [["spd-say", "-l", "es", mensaje], ["espeak", "-v", "es", mensaje]]:
        try:
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            if res.returncode == 0:
                return True
        except Exception:
            continue
    return False

def reproducir_bienvenida_asincrona(nombre, forzar=False):
    """
    Reproduce el mensaje de bienvenida por voz en un hilo daemon secundario.
    - No bloquea la interfaz de usuario.
    - Se ejecuta exactamente una sola vez por cada inicio de sesión.
    - Es 100% tolerante a fallos: si no hay audio o falla el sintetizador,
      el sistema continúa normalmente sin arrojar errores.
    """
    global _ULTIMA_VOZ_REPRODUCIDA
    saludo = generar_saludo_bienvenida(nombre)
    clave_sesion = f"{saludo}_{os.getpid()}"
    if not forzar and _ULTIMA_VOZ_REPRODUCIDA == clave_sesion:
        return
    _ULTIMA_VOZ_REPRODUCIDA = clave_sesion

    def _hilo_tts():
        try:
            if sys.platform == "darwin":
                if _reproducir_macos(saludo):
                    return
                _reproducir_pyttsx3(saludo)
            elif sys.platform.startswith("win"):
                if _reproducir_pyttsx3(saludo):
                    return
                _reproducir_windows_powershell(saludo)
            else:
                if _reproducir_pyttsx3(saludo):
                    return
                _reproducir_linux(saludo)
        except Exception as e:
            print(f"Aviso TTS: {e}")

    threading.Thread(target=_hilo_tts, daemon=True, name="VmPOS-TTS-Bienvenida").start()

def mostrar_carga(nombre="Usuario", usuario_info=None, parent=None, on_complete=None):
    """
    Muestra la pantalla de carga original de VmPOS con animaciones y bienvenida por voz.
    Args:
        nombre (str): Nombre del usuario (se usará como fallback si no hay usuario_info)
        usuario_info (dict): Información completa del usuario (con claves 'usuario', 'nombre', 'rol')
        parent (tk.Widget): Ventana padre si existe, para integrarse cleanly como Toplevel
        on_complete (callable): Callback a ejecutar al finalizar la pantalla de carga y cerrarse la ventana.
    """
    # Determinar el nombre real del usuario de forma dinámica
    nombre_real = ""
    if usuario_info and isinstance(usuario_info, dict):
        nombre_real = usuario_info.get('nombre') or usuario_info.get('usuario') or ""
    if not nombre_real:
        nombre_real = nombre or "Usuario"
    nombre_real = str(nombre_real).strip().capitalize()

    # Iniciar la bienvenida por voz en segundo plano (no bloqueante)
    reproducir_bienvenida_asincrona(nombre_real)

    t = theme_mgr.get_theme_tokens()
    if parent is not None:
        ventana = tk.Toplevel(parent)
        es_toplevel = True
    elif tk._default_root is not None:
        ventana = tk.Toplevel(tk._default_root)
        es_toplevel = True
    else:
        ventana = tk.Tk()
        es_toplevel = False
    ventana.title(f"VmPOS - Bienvenido {nombre_real} ✨")
    ventana.geometry("550x350")
    ventana.configure(bg=t["accent"])
    ventana.resizable(False, False)
    ventana.overrideredirect(True)  # Sin barra de título para carga más elegante
    
    # Centrar ventana en pantalla
    ventana.update_idletasks()
    x = (ventana.winfo_screenwidth() // 2) - (550 // 2)
    y = (ventana.winfo_screenheight() // 2) - (350 // 2)
    ventana.geometry(f"550x350+{x}+{y}")

    # Elevar al frente
    ventana.lift()
    try:
        ventana.attributes('-topmost', True)
        ventana.after(150, lambda: ventana.attributes('-topmost', False) if ventana.winfo_exists() else None)
    except Exception:
        pass

    # Marco principal con borde
    main_frame = tk.Frame(ventana, bg=t["bg_surface"], width=530, height=330)
    main_frame.place(relx=0.5, rely=0.5, anchor="center")

    # Header compacto
    header_frame = tk.Frame(main_frame, bg=t["accent"], height=60)
    header_frame.pack(fill="x")

    # Iconos animados del header
    icons_frame = tk.Frame(header_frame, bg=t["accent"])
    icons_frame.pack(expand=True)

    icons = ["🌸", "💖", "✨"]
    icon_labels = []
    
    for i, icon in enumerate(icons):
        label = tk.Label(icons_frame, text=icon, font=(FONT_EMOJI, 16), 
                         bg=t["accent"], fg="white")
        label.grid(row=0, column=i, padx=20, pady=15)
        icon_labels.append(label)

    # Información del usuario
    user_info_frame = tk.Frame(main_frame, bg=t["bg_surface"])
    user_info_frame.pack(pady=15)

    if usuario_info and isinstance(usuario_info, dict):
        nombre_usuario = usuario_info.get('nombre') or usuario_info.get('usuario') or nombre_real
        permisos_usuario = (
            usuario_info.get('rol_completo')
            or usuario_info.get('rol')
            or usuario_info.get('permisos')
            or 'Usuario'
        )

        tk.Label(user_info_frame, text=f"¡Hola {str(nombre_usuario).strip().capitalize()}! 👋", 
                 font=(FONT_FAMILY, 20, "bold"), bg=t["bg_surface"], fg=t["accent"]).pack()
        
        tk.Label(user_info_frame, text=f"Rol: {str(permisos_usuario).strip().capitalize()}", 
                 font=(FONT_FAMILY, 12), bg=t["bg_surface"], fg=t["text_primary"]).pack()
        
        tk.Label(user_info_frame, text="Iniciando VmPOS...", 
                 font=(FONT_FAMILY, 14), bg=t["bg_surface"], fg=t["text_secondary"]).pack(pady=(5, 0))
    else:
        tk.Label(user_info_frame, text=f"¡Hola {nombre_real}! 👋", 
                 font=(FONT_FAMILY, 20, "bold"), bg=t["bg_surface"], fg=t["accent"]).pack()
        
        tk.Label(user_info_frame, text="Iniciando VmPOS...", 
                 font=(FONT_FAMILY, 14), bg=t["bg_surface"], fg=t["text_secondary"]).pack(pady=(10, 0))

    # Loader circular
    loader_frame = tk.Frame(main_frame, bg=t["bg_surface"], width=100, height=100)
    loader_frame.pack(pady=15)

    canvas = tk.Canvas(loader_frame, width=80, height=80, bg=t["bg_surface"], 
                       highlightthickness=0)
    canvas.place(relx=0.5, rely=0.5, anchor="center")

    # Círculos del loader
    circles = []
    center_x, center_y = 40, 40
    radius = 25
    
    for i in range(8):
        angle = i * (360 / 8)
        x = center_x + radius * math.cos(math.radians(angle))
        y = center_y + radius * math.sin(math.radians(angle))
        
        circle = canvas.create_oval(x-3, y-3, x+3, y+3, 
                                     fill=t["border"], outline="", width=0)
        circles.append(circle)

    # Barra de progreso
    progress_frame = tk.Frame(main_frame, bg=t["bg_surface"])
    progress_frame.pack(pady=10, padx=40, fill="x")

    progress_bg = tk.Frame(progress_frame, bg=t["border"], height=4)
    progress_bg.pack(fill="x")

    progress_bar = tk.Frame(progress_bg, bg=t["accent"], height=4, width=0)
    progress_bar.pack(side="left")

    # Estado de carga
    status_label = tk.Label(main_frame, text="Preparando...", 
                            font=(FONT_FAMILY, 11), bg=t["bg_surface"], fg=t["text_primary"])
    status_label.pack(pady=5)

    # Footer compacto
    footer_frame = tk.Frame(main_frame, bg=t["accent"], height=40)
    footer_frame.pack(side="bottom", fill="x")

    try:
        from business_manager import business_mgr
    except ImportError:
        from interface.business_manager import business_mgr
    business_mgr.recargar()
    txt_footer_carga = f"{business_mgr.nombre} • {business_mgr.subtitulo}" if business_mgr.subtitulo else business_mgr.nombre
    tk.Label(footer_frame, text=txt_footer_carga, 
             font=(FONT_FAMILY, 10, "bold"), bg=t["accent"], fg="white").pack(pady=10)

    # Variables de animación
    progress_width = 0
    max_width = 470
    
    # Mensajes de estado
    status_messages = [
        "Iniciando... 🚀",
        "Cargando datos... 📊", 
        "Preparando interfaz... 🖥️",
        "Sistema listo... ✨"
    ]

    def animar_iconos(indice=0):
        """Animación pulsante de iconos"""
        try:
            for i, label in enumerate(icon_labels):
                if i == indice % len(icon_labels):
                    label.config(font=(FONT_EMOJI, 20))
                else:
                    label.config(font=(FONT_EMOJI, 16))
            
            if ventana.winfo_exists():
                ventana.after(400, lambda: animar_iconos(indice + 1))
        except tk.TclError:
            pass

    total_cycles = 20
    
    def animar_loader(indice=0, ciclos=0):
        nonlocal progress_width
        
        try:
            if ciclos < total_cycles and ventana.winfo_exists():
                # Animar círculos del loader
                for i, circle in enumerate(circles):
                    if i == indice:
                        canvas.itemconfig(circle, fill=t["accent"])
                    elif i == (indice - 1) % 8:
                        canvas.itemconfig(circle, fill="#8B5CF6")
                    else:
                        canvas.itemconfig(circle, fill=t["border"])
                
                # Animar barra de progreso
                progress_width = (ciclos / (total_cycles - 1)) * max_width
                progress_bar.config(width=int(progress_width))
                
                # Cambiar mensaje de estado
                message_index = min(ciclos // (total_cycles // len(status_messages)), len(status_messages) - 1)
                status_label.config(text=status_messages[message_index])
                
                try:
                    ventana.update_idletasks()
                except Exception:
                    pass
                ventana.after(50, lambda: animar_loader((indice + 1) % 8, ciclos + 1))
            elif ventana.winfo_exists():
                # Finalizar
                status_label.config(text="¡Listo! 🎉")
                progress_bar.config(width=max_width, bg="#10B981")
                try:
                    ventana.update_idletasks()
                except Exception:
                    pass
                ventana.after(200, _finalizar_carga)
        except tk.TclError:
            pass

    _finalizado = False

    def _finalizar_carga():
        nonlocal _finalizado
        if _finalizado:
            return
        _finalizado = True
        try:
            if ventana.winfo_exists():
                ventana.destroy()
        except Exception:
            pass
        if on_complete:
            try:
                on_complete()
            except Exception as e_cb:
                print(f"Error en callback tras pantalla de carga: {e_cb}")

    # Iniciar animaciones
    ventana.after(100, animar_iconos)
    ventana.after(100, animar_loader)
    
    # Auto-cerrar de seguridad
    ventana.after(3000, lambda: _finalizar_carga() if not _finalizado else None)
    
    if on_complete is not None:
        # En modo con callback (asíncrono), la animación se ejecuta en el loop de eventos activo
        return ventana

    if es_toplevel:
        # Si es Toplevel sin callback (modo síncrono en tests), esperar al cierre con wait_window
        try:
            (parent or tk._default_root).wait_window(ventana)
        except tk.TclError:
            pass
    else:
        # Si es tk.Tk independiente (ejecución directa de script), ejecutar su propio mainloop
        try:
            ventana.mainloop()
        except tk.TclError:
            pass
    
    return ventana

# Función de prueba
if __name__ == "__main__":
    usuario_test = {
        'nombre': 'Eduardo',
        'usuario': 'eduardo',
        'permisos': 'administrador',
        'rol_completo': 'Administrador'
    }
    mostrar_carga("Eduardo", usuario_test)
