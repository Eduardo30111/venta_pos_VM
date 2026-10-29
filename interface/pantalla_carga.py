#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pantalla de carga optimizada para Sistema VM
Archivo: interface/pantalla_carga.py
"""

import tkinter as tk
import math
import threading
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from interface.theme_manager import theme_mgr, aplicar_tema

# Configuración de rutas para PyInstaller
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Importación opcional de pyttsx3 con manejo de errores
try:
    import pyttsx3
    TTS_DISPONIBLE = True
except ImportError:
    print("Warning: pyttsx3 no disponible, la voz estará deshabilitada")
    TTS_DISPONIBLE = False

def mostrar_carga(nombre="Usuario", usuario_info=None):
    """
    Muestra una pantalla de carga optimizada (más rápida)
    Args:
        nombre (str): Nombre del usuario (se usará como fallback si no hay usuario_info)
        usuario_info (dict): Información completa del usuario (con claves 'usuario' y 'permisos')
    """
    
    # Determinar el nombre real del usuario
    if usuario_info and 'usuario' in usuario_info:
        nombre_real = usuario_info['usuario']
    else:
        nombre_real = nombre
    
    def reproducir_bienvenida():
        """Reproduce mensaje de bienvenida en hilo separado (opcional)"""
        if not TTS_DISPONIBLE:
            return
            
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty('rate', 170)  # Más rápido
            engine.setProperty('volume', 0.8)  # Volumen más bajo
            mensaje = f"Bienvenido {nombre_real}, sistema listo"
            engine.say(mensaje)
            engine.runAndWait()
        except Exception as e:
            print(f"Error en TTS: {e}")
            pass  # Si hay problemas con TTS, continúa sin sonido

    # Iniciar TTS en hilo separado para no bloquear la UI
    threading.Thread(target=reproducir_bienvenida, daemon=True).start()

    t = theme_mgr.get_theme_tokens()
    ventana = tk.Tk()
    ventana.title(f"VmPOS - Bienvenido {nombre_real} ✨")
    ventana.geometry("550x350")  # Tamaño reducido
    ventana.configure(bg=t["accent"])
    ventana.resizable(False, False)
    ventana.overrideredirect(True)  # Sin barra de título para carga más elegante
    
    # Centrar ventana
    ventana.update_idletasks()
    x = (ventana.winfo_screenwidth() // 2) - (550 // 2)
    y = (ventana.winfo_screenheight() // 2) - (350 // 2)
    ventana.geometry(f"550x350+{x}+{y}")

    # Marco principal con borde
    main_frame = tk.Frame(ventana, bg=t["bg_surface"], width=530, height=330)
    main_frame.place(relx=0.5, rely=0.5, anchor="center")

    # Header compacto
    header_frame = tk.Frame(main_frame, bg=t["accent"], height=60)
    header_frame.pack(fill="x")

    # Iconos animados del header (reducidos)
    icons_frame = tk.Frame(header_frame, bg=t["accent"])
    icons_frame.pack(expand=True)

    icons = ["🌸", "💖", "✨"]  # Menos iconos para mayor velocidad
    icon_labels = []
    
    for i, icon in enumerate(icons):
        label = tk.Label(icons_frame, text=icon, font=("Segoe UI Emoji", 16), 
                         bg=t["accent"], fg="white")
        label.grid(row=0, column=i, padx=20, pady=15)
        icon_labels.append(label)

    # Información del usuario
    user_info_frame = tk.Frame(main_frame, bg=t["bg_surface"])
    user_info_frame.pack(pady=15)

    if usuario_info:
        nombre_usuario = usuario_info.get('usuario', nombre_real)
        permisos_usuario = usuario_info.get('rol_completo', usuario_info.get('permisos', 'No definido'))

        tk.Label(user_info_frame, text=f"¡Hola {nombre_usuario.capitalize()}! 👋", 
                 font=("Segoe UI", 20, "bold"), bg=t["bg_surface"], fg=t["accent"]).pack()
        
        tk.Label(user_info_frame, text=f"Rol: {permisos_usuario}", 
                 font=("Segoe UI", 12), bg=t["bg_surface"], fg=t["text_primary"]).pack()
        
        tk.Label(user_info_frame, text="Iniciando VmPOS...", 
                 font=("Segoe UI", 14), bg=t["bg_surface"], fg=t["text_secondary"]).pack(pady=(5, 0))
    else:
        tk.Label(user_info_frame, text=f"¡Hola {nombre_real}! 👋", 
                 font=("Segoe UI", 20, "bold"), bg=t["bg_surface"], fg=t["accent"]).pack()
        
        tk.Label(user_info_frame, text="Iniciando VmPOS...", 
                 font=("Segoe UI", 14), bg=t["bg_surface"], fg=t["text_secondary"]).pack(pady=(10, 0))

    # Loader circular más pequeño y rápido
    loader_frame = tk.Frame(main_frame, bg=t["bg_surface"], width=100, height=100)
    loader_frame.pack(pady=15)

    canvas = tk.Canvas(loader_frame, width=80, height=80, bg=t["bg_surface"], 
                       highlightthickness=0)
    canvas.place(relx=0.5, rely=0.5, anchor="center")

    # Círculos del loader (menos para mejor rendimiento)
    circles = []
    center_x, center_y = 40, 40
    radius = 25
    
    for i in range(8):  # Reducido de 12 a 8
        angle = i * (360 / 8)
        x = center_x + radius * math.cos(math.radians(angle))
        y = center_y + radius * math.sin(math.radians(angle))
        
        circle = canvas.create_oval(x-3, y-3, x+3, y+3, 
                                     fill=t["border"], outline="", width=0)
        circles.append(circle)

    # Barra de progreso más pequeña
    progress_frame = tk.Frame(main_frame, bg=t["bg_surface"])
    progress_frame.pack(pady=10, padx=40, fill="x")

    progress_bg = tk.Frame(progress_frame, bg=t["border"], height=4)
    progress_bg.pack(fill="x")

    progress_bar = tk.Frame(progress_bg, bg=t["accent"], height=4, width=0)
    progress_bar.pack(side="left")

    # Estado de carga
    status_label = tk.Label(main_frame, text="Preparando...", 
                            font=("Segoe UI", 11), bg=t["bg_surface"], fg=t["text_primary"])
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
             font=("Segoe UI", 10, "bold"), bg=t["accent"], fg="white").pack(pady=10)

    # Variables de animación (optimizadas)
    progress_width = 0
    max_width = 470  # Ancho máximo ajustado
    
    # Mensajes de estado reducidos
    status_messages = [
        "Iniciando... 🚀",
        "Cargando datos... 📊", 
        "Preparando interfaz... 🖥️",
        "Sistema listo... ✨"
    ]

    def animar_iconos(indice=0):
        """Animación de iconos más rápida"""
        try:
            for i, label in enumerate(icon_labels):
                if i == indice % len(icon_labels):
                    label.config(font=("Segoe UI Emoji", 20))
                else:
                    label.config(font=("Segoe UI Emoji", 16))
            
            if ventana.winfo_exists():
                ventana.after(400, lambda: animar_iconos(indice + 1))
        except tk.TclError:
            # La ventana ya fue destruida
            pass

    # Animación mucho más rápida
    total_cycles = 20  # Reducido drásticamente de 48 a 20
    
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
                
                ventana.update()
                ventana.after(50, lambda: animar_loader((indice + 1) % 8, ciclos + 1))  # Muy rápido
            elif ventana.winfo_exists():
                # Finalizar
                status_label.config(text="¡Listo! 🎉")
                progress_bar.config(width=max_width, bg="#10B981")
                ventana.update()
                ventana.after(200, ventana.destroy)  # Cerrar rápidamente
        except tk.TclError:
            # La ventana ya fue destruida
            pass

    # Iniciar animaciones
    ventana.after(100, animar_iconos)
    ventana.after(100, animar_loader)
    
    # Auto-cerrar por seguridad (por si algo falla)
    ventana.after(3000, lambda: ventana.destroy() if ventana.winfo_exists() else None)
    
    try:
        ventana.mainloop()
    except tk.TclError:
        # La ventana ya fue destruida
        pass
    
    # Retornar referencia a la ventana para compatibilidad
    return ventana

# Función de prueba
if __name__ == "__main__":
    # Simular información de usuario
    usuario_test = {
        'usuario': 'Ana',
        'permisos': 'administrador',
        'rol_completo': 'Administrador'
    }
    mostrar_carga("Ana", usuario_test)