#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivo: interface/network_dialog.py
Ventana interactiva de configuración de red y servidor multi-caja para VmPOS.
Permite visualizar la IP del servidor y conectar terminales clientes con un clic.
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

try:
    from interface.network_manager import (
        obtener_ips_locales,
        verificar_puerto_abierto,
        probar_conexion,
        obtener_config_red,
        guardar_config_red,
        iniciar_servidor_segundo_plano,
        detener_servidor_segundo_plano
    )
except ImportError:
    from network_manager import (
        obtener_ips_locales,
        verificar_puerto_abierto,
        probar_conexion,
        obtener_config_red,
        guardar_config_red,
        iniciar_servidor_segundo_plano,
        detener_servidor_segundo_plano
    )

try:
    from interface.theme_manager import aplicar_tema, calcular_color_texto_optimo, crear_boton
except ImportError:
    try:
        from theme_manager import aplicar_tema, calcular_color_texto_optimo, crear_boton
    except ImportError:
        def aplicar_tema(v): return {"bg_app": "#F1F5F9", "bg_surface": "#FFFFFF", "bg_card": "#FFFFFF", "accent": "#4F46E5", "text_primary": "#0F172A", "text_secondary": "#64748B", "border": "#E2E8F0"}
        def calcular_color_texto_optimo(c): return "#FFFFFF"
        def crear_boton(p, **kw): return tk.Button(p, **kw)


class NetworkDialog:
    def __init__(self, parent=None, on_saved=None):
        self.parent = parent
        self.on_saved = on_saved

        if parent:
            self.dialog = tk.Toplevel(parent)
            self.dialog.transient(parent)
        else:
            self.dialog = tk.Tk()

        self.dialog.title("VmPOS — Configuración de Red y Servidor Multi-Caja")
        self.dialog.geometry("640x660")
        self.dialog.minsize(580, 580)

        # Cargar tema
        self.t = aplicar_tema(self.dialog)
        self.dialog.configure(bg=self.t["bg_app"])

        # Cargar configuración actual
        self.config_actual = obtener_config_red()

        # Variables Tkinter
        self.modo_var = tk.StringVar(master=self.dialog, value=self.config_actual.get("modo", "servidor"))
        self.servidor_ip_var = tk.StringVar(master=self.dialog, value=str(self.config_actual.get("servidor_ip", "127.0.0.1")))
        self.servidor_puerto_var = tk.StringVar(master=self.dialog, value=str(self.config_actual.get("servidor_puerto", 8000)))
        self.terminal_id_var = tk.StringVar(master=self.dialog, value=str(self.config_actual.get("terminal_id", 1)))
        self.terminal_nombre_var = tk.StringVar(master=self.dialog, value=str(self.config_actual.get("terminal_nombre", "CAJA-01")))

        self.estado_servidor_var = tk.StringVar(master=self.dialog, value="Comprobando...")
        self.resultado_prueba_var = tk.StringVar(master=self.dialog, value="")
        self.color_resultado_var = tk.StringVar(master=self.dialog, value=self.t["text_secondary"])

        self._construir_ui()
        self._actualizar_vista_modo()
        self._verificar_estado_servidor_async()

        # Centrar ventana
        self.dialog.update_idletasks()
        try:
            x = (self.dialog.winfo_screenwidth() - self.dialog.winfo_reqwidth()) // 2
            y = (self.dialog.winfo_screenheight() - self.dialog.winfo_reqheight()) // 2
            self.dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

        if parent:
            self.dialog.grab_set()

    def _construir_ui(self):
        # 1. Encabezado
        header_frame = tk.Frame(self.dialog, bg=self.t["accent"], height=70)
        header_frame.pack(fill="x")
        header_frame.pack_propagate(False)

        fg_header = calcular_color_texto_optimo(self.t["accent"])
        lbl_titulo = tk.Label(
            header_frame,
            text="🌐 Configuración de Red y Cajas Conectadas",
            font=("Segoe UI", 14, "bold"),
            bg=self.t["accent"],
            fg=fg_header
        )
        lbl_titulo.pack(pady=(12, 2))

        lbl_sub = tk.Label(
            header_frame,
            text="Conecta varias computadoras para compartir el mismo inventario y ventas",
            font=("Segoe UI", 9),
            bg=self.t["accent"],
            fg=fg_header
        )
        lbl_sub.pack()

        # Contenedor con scroll si es necesario
        content = tk.Frame(self.dialog, bg=self.t["bg_app"], padx=20, pady=15)
        content.pack(fill="both", expand=True)

        # 2. Selector de Modo: Servidor vs Cliente
        selector_card = tk.LabelFrame(
            content,
            text=" ¿Qué función cumple esta computadora? ",
            font=("Segoe UI", 10, "bold"),
            bg=self.t["bg_card"],
            fg=self.t["text_primary"],
            padx=15,
            pady=12,
            relief="solid",
            bd=1
        )
        selector_card.pack(fill="x", pady=(0, 15))

        rb_servidor = tk.Radiobutton(
            selector_card,
            text="🖥️ Esta computadora es el SERVIDOR (Caja Principal)",
            value="servidor",
            variable=self.modo_var,
            font=("Segoe UI", 10, "bold"),
            bg=self.t["bg_card"],
            fg=self.t["text_primary"],
            activebackground=self.t["bg_card"],
            command=self._actualizar_vista_modo
        )
        rb_servidor.pack(anchor="w", pady=4)

        lbl_desc_servidor = tk.Label(
            selector_card,
            text="Guarda la base de datos central. Las otras computadoras se conectarán a esta.",
            font=("Segoe UI", 8),
            bg=self.t["bg_card"],
            fg=self.t["text_secondary"]
        )
        lbl_desc_servidor.pack(anchor="w", padx=25, pady=(0, 8))

        rb_cliente = tk.Radiobutton(
            selector_card,
            text="💻 Esta computadora es una CAJA SECUNDARIA (Cliente)",
            value="cliente",
            variable=self.modo_var,
            font=("Segoe UI", 10, "bold"),
            bg=self.t["bg_card"],
            fg=self.t["text_primary"],
            activebackground=self.t["bg_card"],
            command=self._actualizar_vista_modo
        )
        rb_cliente.pack(anchor="w", pady=4)

        lbl_desc_cliente = tk.Label(
            selector_card,
            text="Se conecta por WiFi o red local a la computadora Servidor.",
            font=("Segoe UI", 8),
            bg=self.t["bg_card"],
            fg=self.t["text_secondary"]
        )
        lbl_desc_cliente.pack(anchor="w", padx=25)

        # 3. Contenedor Dinámico para Servidor o Cliente
        self.frame_servidor = tk.LabelFrame(
            content,
            text=" Datos para compartir con las otras computadoras ",
            font=("Segoe UI", 10, "bold"),
            bg=self.t["bg_card"],
            fg=self.t["text_primary"],
            padx=15,
            pady=12,
            relief="solid",
            bd=1
        )

        self.frame_cliente = tk.LabelFrame(
            content,
            text=" Conexión con la Computadora Servidor ",
            font=("Segoe UI", 10, "bold"),
            bg=self.t["bg_card"],
            fg=self.t["text_primary"],
            padx=15,
            pady=12,
            relief="solid",
            bd=1
        )

        self._construir_vista_servidor()
        self._construir_vista_cliente()

        # 4. Botones de acción inferiores
        btn_bar = tk.Frame(self.dialog, bg=self.t["bg_app"], pady=12, padx=20)
        btn_bar.pack(fill="x", side="bottom")

        crear_boton(
            btn_bar,
            text="💾 Guardar y Conectar",
            bg_color="#10B981",
            fg_color="white",
            font=("Segoe UI", 10, "bold"),
            command=self._guardar_y_conectar,
            padx=18,
            pady=6
        ).pack(side="right", padx=(8, 0))

        crear_boton(
            btn_bar,
            text="Cancelar",
            bg_color=self.t["bg_surface"],
            fg_color=self.t["text_primary"],
            font=("Segoe UI", 10),
            command=self.dialog.destroy,
            padx=14,
            pady=6
        ).pack(side="right")

    def _construir_vista_servidor(self):
        # Muestra la IP local destacada
        ips = obtener_ips_locales()
        ip_destacada = ips[0] if ips else "127.0.0.1"

        f_ip = tk.Frame(self.frame_servidor, bg=self.t["bg_card"])
        f_ip.pack(fill="x", pady=6)

        tk.Label(
            f_ip,
            text="Dirección IP de esta máquina:",
            font=("Segoe UI", 9, "bold"),
            bg=self.t["bg_card"],
            fg=self.t["text_primary"]
        ).pack(anchor="w")

        f_ip_box = tk.Frame(f_ip, bg="#E2E8F0", padx=8, pady=6, bd=1, relief="solid")
        f_ip_box.pack(fill="x", pady=4)

        self.lbl_ip_valor = tk.Label(
            f_ip_box,
            text=ip_destacada,
            font=("Segoe UI", 14, "bold"),
            bg="#E2E8F0",
            fg="#1E293B"
        )
        self.lbl_ip_valor.pack(side="left", padx=5)

        btn_copiar = tk.Button(
            f_ip_box,
            text="📋 Copiar IP",
            font=("Segoe UI", 9),
            bg="white",
            relief="groove",
            command=lambda: self._copiar_al_portapapeles(ip_destacada)
        )
        btn_copiar.pack(side="right", padx=5)

        # Puerto del servidor
        f_puerto = tk.Frame(self.frame_servidor, bg=self.t["bg_card"])
        f_puerto.pack(fill="x", pady=6)

        tk.Label(
            f_puerto,
            text="Puerto de comunicación:",
            font=("Segoe UI", 9, "bold"),
            bg=self.t["bg_card"],
            fg=self.t["text_primary"]
        ).pack(anchor="w")

        entry_p = tk.Entry(
            f_puerto,
            textvariable=self.servidor_puerto_var,
            font=("Segoe UI", 10),
            width=10,
            relief="solid",
            bd=1
        )
        entry_p.pack(anchor="w", pady=2)

        # Estado del servicio
        f_estado = tk.Frame(self.frame_servidor, bg=self.t["bg_card"])
        f_estado.pack(fill="x", pady=8)

        tk.Label(
            f_estado,
            text="Estado del Servicio Central:",
            font=("Segoe UI", 9, "bold"),
            bg=self.t["bg_card"],
            fg=self.t["text_primary"]
        ).pack(anchor="w")

        f_status_row = tk.Frame(f_estado, bg=self.t["bg_card"])
        f_status_row.pack(fill="x", pady=2)

        self.lbl_status = tk.Label(
            f_status_row,
            textvariable=self.estado_servidor_var,
            font=("Segoe UI", 9, "bold"),
            bg=self.t["bg_card"],
            fg="#64748B"
        )
        self.lbl_status.pack(side="left")

        btn_check = tk.Button(
            f_status_row,
            text="🔄 Actualizar Estado",
            font=("Segoe UI", 8),
            command=self._verificar_estado_servidor_async
        )
        btn_check.pack(side="right")

        # Mensaje de ayuda / instrucción
        msg_card = tk.Frame(self.frame_servidor, bg="#FEF3C7", padx=10, pady=10, bd=1, relief="solid")
        msg_card.pack(fill="x", pady=10)

        tk.Label(
            msg_card,
            text=f"💡 Instrucción para las otras computadoras:\n"
                 f"1. Abre VmPOS en las otras máquinas.\n"
                 f"2. Entra a esta misma ventana y selecciona 'Caja Secundaria'.\n"
                 f"3. Escribe la IP: {ip_destacada} y Puerto: {self.servidor_puerto_var.get()}.\n"
                 f"4. Presiona 'Probar Conexión' y 'Guardar'.",
            font=("Segoe UI", 9),
            bg="#FEF3C7",
            fg="#92400E",
            justify="left"
        ).pack(anchor="w")

    def _construir_vista_cliente(self):
        # IP del Servidor
        f_ip = tk.Frame(self.frame_cliente, bg=self.t["bg_card"])
        f_ip.pack(fill="x", pady=4)

        tk.Label(
            f_ip,
            text="Dirección IP de la Computadora Servidor:",
            font=("Segoe UI", 9, "bold"),
            bg=self.t["bg_card"],
            fg=self.t["text_primary"]
        ).pack(anchor="w")

        entry_ip = tk.Entry(
            f_ip,
            textvariable=self.servidor_ip_var,
            font=("Segoe UI", 11),
            relief="solid",
            bd=1
        )
        entry_ip.pack(fill="x", pady=2)

        tk.Label(
            f_ip,
            text="Ejemplo: 192.168.1.50 (la IP que muestra la PC Servidor en pantalla)",
            font=("Segoe UI", 8),
            bg=self.t["bg_card"],
            fg=self.t["text_secondary"]
        ).pack(anchor="w")

        # Puerto del Servidor
        f_p = tk.Frame(self.frame_cliente, bg=self.t["bg_card"])
        f_p.pack(fill="x", pady=4)

        tk.Label(
            f_p,
            text="Puerto:",
            font=("Segoe UI", 9, "bold"),
            bg=self.t["bg_card"],
            fg=self.t["text_primary"]
        ).pack(anchor="w")

        entry_p = tk.Entry(
            f_p,
            textvariable=self.servidor_puerto_var,
            font=("Segoe UI", 10),
            width=10,
            relief="solid",
            bd=1
        )
        entry_p.pack(anchor="w", pady=2)

        # Nombre y número de esta caja
        f_caja = tk.Frame(self.frame_cliente, bg=self.t["bg_card"])
        f_caja.pack(fill="x", pady=4)

        f_col1 = tk.Frame(f_caja, bg=self.t["bg_card"])
        f_col1.pack(side="left", fill="x", expand=True, padx=(0, 6))

        tk.Label(
            f_col1,
            text="Nombre de esta Caja:",
            font=("Segoe UI", 9, "bold"),
            bg=self.t["bg_card"],
            fg=self.t["text_primary"]
        ).pack(anchor="w")

        entry_nom = tk.Entry(
            f_col1,
            textvariable=self.terminal_nombre_var,
            font=("Segoe UI", 10),
            relief="solid",
            bd=1
        )
        entry_nom.pack(fill="x", pady=2)

        f_col2 = tk.Frame(f_caja, bg=self.t["bg_card"])
        f_col2.pack(side="left", fill="x", expand=True, padx=(6, 0))

        tk.Label(
            f_col2,
            text="Número / ID de Caja:",
            font=("Segoe UI", 9, "bold"),
            bg=self.t["bg_card"],
            fg=self.t["text_primary"]
        ).pack(anchor="w")

        cb_id = ttk.Combobox(
            f_col2,
            textvariable=self.terminal_id_var,
            values=["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"],
            state="readonly",
            font=("Segoe UI", 10)
        )
        cb_id.pack(fill="x", pady=2)

        # Botón de Prueba de Conexión
        f_btn_test = tk.Frame(self.frame_cliente, bg=self.t["bg_card"])
        f_btn_test.pack(fill="x", pady=10)

        self.btn_probar = crear_boton(
            f_btn_test,
            text="🔍 Probar Conexión con el Servidor",
            bg_color=self.t["accent"],
            fg_color="white",
            font=("Segoe UI", 9, "bold"),
            command=self._ejecutar_prueba_conexion,
            padx=12,
            pady=5
        )
        self.btn_probar.pack(anchor="w")

        # Cartel con resultado de prueba
        self.lbl_resultado = tk.Label(
            self.frame_cliente,
            textvariable=self.resultado_prueba_var,
            font=("Segoe UI", 9, "bold"),
            bg=self.t["bg_card"],
            fg=self.color_resultado_var.get(),
            wraplength=520,
            justify="left"
        )
        self.lbl_resultado.pack(anchor="w", pady=4)

    def _actualizar_vista_modo(self):
        modo = self.modo_var.get()
        if modo == "servidor":
            self.frame_cliente.pack_forget()
            self.frame_servidor.pack(fill="both", expand=True, pady=(0, 10))
            # Ajustar valores a localhost o IP local
            ips = obtener_ips_locales()
            self.servidor_ip_var.set(ips[0] if ips else "127.0.0.1")
        else:
            self.frame_servidor.pack_forget()
            self.frame_cliente.pack(fill="both", expand=True, pady=(0, 10))

    def _copiar_al_portapapeles(self, texto):
        try:
            self.dialog.clipboard_clear()
            self.dialog.clipboard_append(texto)
            messagebox.showinfo("Copiado", f"Dirección IP {texto} copiada al portapapeles.")
        except Exception:
            pass

    def _verificar_estado_servidor_async(self):
        def _check():
            self.estado_servidor_var.set("⏳ Comprobando servicio...")
            puerto = int(self.servidor_puerto_var.get() or 8000)
            activo = verificar_puerto_abierto("127.0.0.1", puerto, timeout=0.8)
            if activo:
                self.estado_servidor_var.set(f"🟢 Servidor ACTIVO (Escuchando en el puerto {puerto})")
                self.lbl_status.config(fg="#10B981")
            else:
                self.estado_servidor_var.set(f"🟡 Servidor no detectado en el puerto local {puerto}")
                self.lbl_status.config(fg="#F59E0B")

        threading.Thread(target=_check, daemon=True).start()

    def _ejecutar_prueba_conexion(self):
        ip = self.servidor_ip_var.get().strip()
        puerto = int(self.servidor_puerto_var.get() or 8000)

        self.resultado_prueba_var.set("⏳ Probando conexión con el servidor...")
        self.lbl_resultado.config(fg="#64748B")
        self.btn_probar.config(state="disabled")

        def _test():
            ok, msg, ms = probar_conexion(ip, puerto, timeout=3.5)
            def _update():
                self.btn_probar.config(state="normal")
                if ok:
                    self.resultado_prueba_var.set(f"✅ ¡Conexión Exitosa! Servidor en línea (Latencia: {ms} ms)")
                    self.lbl_resultado.config(fg="#10B981")
                else:
                    self.resultado_prueba_var.set(f"❌ {msg}")
                    self.lbl_resultado.config(fg="#EF4444")
            self.dialog.after(0, _update)

        threading.Thread(target=_test, daemon=True).start()

    def _guardar_y_conectar(self):
        modo = self.modo_var.get()
        ip = self.servidor_ip_var.get().strip()
        puerto = int(self.servidor_puerto_var.get().strip() or 8000)
        t_id = int(self.terminal_id_var.get().strip() or 1)
        t_nombre = self.terminal_nombre_var.get().strip() or f"CAJA-{t_id:02d}"

        if not ip:
            messagebox.showerror("Error", "Debes ingresar una dirección IP válida.")
            return

        nueva_config = {
            "modo": modo,
            "servidor_ip": ip,
            "servidor_puerto": puerto,
            "terminal_id": t_id,
            "terminal_nombre": t_nombre
        }

        ok = guardar_config_red(nueva_config)
        if ok:
            messagebox.showinfo(
                "Configuración Guardada",
                f"La configuración de red ha sido guardada exitosamente.\n\n"
                f"Modo: {modo.upper()}\n"
                f"Servidor: http://{ip}:{puerto}\n"
                f"Terminal: {t_nombre} (ID: {t_id})\n\n"
                "La aplicación se conectará automáticamente a esta dirección."
            )
            if callable(self.on_saved):
                try:
                    self.on_saved(nueva_config)
                except Exception:
                    pass
            self.dialog.destroy()
        else:
            messagebox.showerror("Error", "No se pudo guardar la configuración de red.")


def abrir_dialogo_red(parent=None, on_saved=None):
    """Abre el diálogo de configuración de red."""
    return NetworkDialog(parent=parent, on_saved=on_saved)


if __name__ == "__main__":
    app = NetworkDialog()
    app.dialog.mainloop()
