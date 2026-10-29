import tkinter as tk
from tkinter import ttk, messagebox
import sys
import os
import argparse
from datetime import datetime, timezone

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


# Paleta base de colores
COLOR_PRIMARIO = "#DB2777"      # Rosa/Fucsia VmPOS
COLOR_DISPONIBLE = "#10B981"    # Verde
COLOR_EN_TURNO = "#2563EB"      # Azul
COLOR_OCUPADO = "#D97706"       # Ámbar
COLOR_ALMUERZO = "#EA580C"      # Naranja
COLOR_PAUSADO = "#64748B"       # Gris Pizarra
COLOR_ALERTA = "#DC2626"        # Rojo alerta

STATE_COLORS = {
    "DISPONIBLE": (COLOR_DISPONIBLE, "#ECFDF5", "🟢"),
    "EN_TURNO": (COLOR_EN_TURNO, "#EFF6FF", "🔵"),
    "EN_TURNO_SUGERIDO": (COLOR_EN_TURNO, "#EFF6FF", "🔵"),
    "ATENDIENDO": ("#7C3AED", "#F5F3FF", "🟣"),
    "OCUPADO": (COLOR_OCUPADO, "#FFFBEB", "🟡"),
    "ALMUERZO": (COLOR_ALMUERZO, "#FFF7ED", "🟠"),
    "PAUSADO": (COLOR_PAUSADO, "#F8FAFC", "⚪"),
    "FUERA_DE_TURNO": ("#334155", "#F1F5F9", "⚫"),
    "SALTADO": (COLOR_ALERTA, "#FEF2F2", "⏭️")
}

class TurnosMenuApp:
    def __init__(self, root, user_id=None, rol="operario", nombre_usuario="", parent_pid=""):
        self.root = root
        self.parent_pid = parent_pid or os.environ.get("VMPOS_PARENT_PID", "")
        session_mgr.iniciar_vigilante_padre(self.root, parent_pid=self.parent_pid)
        iniciar_observador_tema(self.root)

        self.user_id = int(user_id) if user_id else None
        self.rol = (rol or "operario").lower()
        self.es_admin = self.rol in ["admin", "administrador", "gerente"]
        self.nombre_usuario = nombre_usuario or ("Administrador" if self.es_admin else "Operario")

        self.root.title(f"⏱️ Control del Turno - VmPOS ({'Supervisión Admin' if self.es_admin else 'Panel Operario'})")
        
        self.t = aplicar_tema(self.root)
        calcular_geometria_segura(self.root, 1180 if self.es_admin else 960, 740 if self.es_admin else 680, min_w=820, min_h=520)
        self.root.configure(bg=self.t["bg_app"])

        self.datos_estado = None
        self.segundos_timer_local = 0
        self._timer_after_id = None
        self._poll_after_id = None
        self._alerta_sonada = False

        self._configurar_estilos()
        self._construir_ui()
        self.refrescar_datos()
        self._iniciar_timers()

        self.root.protocol("WM_DELETE_WINDOW", self._al_cerrar)

    def _configurar_estilos(self):
        self.style = ttk.Style()
        try:
            self.style.theme_use('clam')
        except Exception:
            pass

        self.style.configure("Turnos.TNotebook", background=self.t["bg_app"], borderwidth=0)
        self.style.configure("Turnos.TNotebook.Tab", font=("Segoe UI", 10, "bold"), padding=[14, 6], background=self.t["bg_card"], foreground=self.t["text_primary"])
        self.style.map("Turnos.TNotebook.Tab", background=[("selected", self.t["primary"])], foreground=[("selected", "white")])

        self.style.configure("Treeview", background=self.t["tree_bg"], foreground=self.t["tree_fg"], fieldbackground=self.t["tree_field_bg"], rowheight=26, font=("Segoe UI", 9))
        self.style.configure("Treeview.Heading", background=self.t["tree_heading_bg"], foreground=self.t["tree_heading_fg"], font=('Segoe UI', 9, 'bold'), relief="flat")
        self.style.map("Treeview", background=[("selected", self.t["primary"])], foreground=[("selected", "#FFFFFF")])

    def _construir_ui(self):
        # Header principal
        header_frame = tk.Frame(self.root, bg=self.t["primary"], height=60)
        header_frame.pack(fill="x")
        header_frame.pack_propagate(False)

        fg_h = calcular_color_texto_optimo(self.t["primary"])

        titulo_texto = "👑 SUPERVISIÓN Y CONTROL DE TURNOS (ADMINISTRADOR)" if self.es_admin else "⏱️ CONTROL DEL TURNO • MI TURNO Y COLA"
        tk.Label(header_frame, text=titulo_texto, font=("Segoe UI", 14, "bold"), bg=self.t["primary"], fg=fg_h).pack(side="left", padx=20, pady=12)

        info_user_frame = tk.Frame(header_frame, bg=self.t["primary"])
        info_user_frame.pack(side="right", padx=20)

        self.lbl_conexion = tk.Label(info_user_frame, text="🟢 Conectado", font=("Segoe UI", 9, "bold"), bg="#047857", fg="#FFFFFF", padx=8, pady=2)
        self.lbl_conexion.pack(side="right", padx=(10, 0))

        tk.Label(info_user_frame, text=f"👤 {self.nombre_usuario} ({self.rol.capitalize()})", font=("Segoe UI", 10), bg=self.t["primary"], fg=fg_h).pack(side="right")

        # Contenedor central
        self.main_container = tk.Frame(self.root, bg=self.t["bg_app"])
        self.main_container.pack(fill="both", expand=True, padx=15, pady=10)

        if self.es_admin:
            self._construir_ui_admin(self.main_container)
        else:
            self._construir_ui_operario(self.main_container)

    # =========================================================================
    #   VISTA DEL OPERARIO (MI TURNO)
    # =========================================================================

    def _construir_ui_operario(self, parent):
        # Card principal: Mi Estado en Turno
        self.card_mi_turno = tk.Frame(parent, bg=self.t["bg_surface"], bd=1, relief="solid", highlightbackground=self.t["border"], highlightthickness=1)
        self.card_mi_turno.pack(fill="x", pady=(0, 10), padx=5)

        top_bar_card = tk.Frame(self.card_mi_turno, bg=self.t["bg_card"], height=32)
        top_bar_card.pack(fill="x")
        top_bar_card.pack_propagate(False)
        tk.Label(top_bar_card, text="⭐ INFORMACIÓN DE MI TURNO DE ATENCIÓN", font=("Segoe UI", 10, "bold"), bg=self.t["bg_card"], fg=self.t["text_primary"]).pack(side="left", padx=12, pady=5)

        body_card = tk.Frame(self.card_mi_turno, bg=self.t["bg_surface"], padx=15, pady=15)
        body_card.pack(fill="x")

        # Columna 1: Badge de Estado y Posición
        c1 = tk.Frame(body_card, bg=self.t["bg_surface"])
        c1.pack(side="left", fill="y", padx=(0, 20))

        tk.Label(c1, text="MI ESTADO ACTUAL:", font=("Segoe UI", 9, "bold"), bg=self.t["bg_surface"], fg=self.t["text_muted"]).pack(anchor="w")
        self.lbl_mi_estado_badge = tk.Label(c1, text="🟢 DISPONIBLE", font=("Segoe UI", 13, "bold"), bg="#ECFDF5", fg=COLOR_DISPONIBLE, padx=12, pady=6, bd=1, relief="solid")
        self.lbl_mi_estado_badge.pack(anchor="w", pady=(4, 8))

        self.lbl_mi_posicion = tk.Label(c1, text="Posición en Cola: #--", font=("Segoe UI", 10, "bold"), bg=self.t["bg_surface"], fg=self.t["text_primary"])
        self.lbl_mi_posicion.pack(anchor="w")

        self.lbl_turno_actual = tk.Label(c1, text="Ahora atiende: --", font=("Segoe UI", 10, "bold"), bg=self.t["bg_surface"], fg=COLOR_EN_TURNO)
        self.lbl_turno_actual.pack(anchor="w", pady=(4, 0))

        # Columna 2: Cronómetro y Tiempo
        c2 = tk.Frame(body_card, bg=self.t["bg_surface"])
        c2.pack(side="left", fill="y", padx=20)

        tk.Label(c2, text="TIEMPO EN TURNO ACTUAL:", font=("Segoe UI", 9, "bold"), bg=self.t["bg_surface"], fg=self.t["text_muted"]).pack(anchor="w")
        self.lbl_mi_timer = tk.Label(c2, text="00:00:00", font=("Segoe UI", 22, "bold"), bg=self.t["bg_surface"], fg=COLOR_EN_TURNO)
        self.lbl_mi_timer.pack(anchor="w", pady=(0, 2))

        self.lbl_mi_ultima_atencion = tk.Label(c2, text="Última atención: --", font=("Segoe UI", 9), bg=self.t["bg_surface"], fg=self.t["text_muted"])
        self.lbl_mi_ultima_atencion.pack(anchor="w")

        # Columna 3: Estadísticas del día
        c3 = tk.Frame(body_card, bg=self.t["bg_surface"])
        c3.pack(side="left", fill="y", padx=20)

        tk.Label(c3, text="MIS ATENCIONES HOY:", font=("Segoe UI", 9, "bold"), bg=self.t["bg_surface"], fg=self.t["text_muted"]).pack(anchor="w")
        stats_sub = tk.Frame(c3, bg=self.t["bg_surface"])
        stats_sub.pack(anchor="w", pady=(4, 0))

        self.lbl_cnt_total = tk.Label(stats_sub, text="0", font=("Segoe UI", 16, "bold"), bg="#EFF6FF", fg=COLOR_EN_TURNO, padx=10, pady=2)
        self.lbl_cnt_total.pack(side="left", padx=(0, 10))
        tk.Label(stats_sub, text="Total\nAtendidos", font=("Segoe UI", 8), bg=self.t["bg_surface"], fg=self.t["text_muted"]).pack(side="left", padx=(0, 15))

        self.lbl_cnt_normales = tk.Label(stats_sub, text="0", font=("Segoe UI", 13, "bold"), bg=self.t["bg_card"], fg=self.t["text_primary"], padx=8, pady=2)
        self.lbl_cnt_normales.pack(side="left", padx=(0, 5))
        tk.Label(stats_sub, text="Normales", font=("Segoe UI", 8), bg=self.t["bg_surface"], fg=self.t["text_muted"]).pack(side="left", padx=(0, 15))

        self.lbl_cnt_especiales = tk.Label(stats_sub, text="0", font=("Segoe UI", 13, "bold"), bg="#FFFBEB", fg=COLOR_OCUPADO, padx=8, pady=2)
        self.lbl_cnt_especiales.pack(side="left", padx=(0, 5))
        tk.Label(stats_sub, text="Especiales", font=("Segoe UI", 8), bg=self.t["bg_surface"], fg=self.t["text_muted"]).pack(side="left")

        # Botones de Acción para el Operario
        actions_bar = tk.Frame(self.card_mi_turno, bg=self.t["bg_card"], padx=15, pady=10)
        actions_bar.pack(fill="x")

        self.btn_almuerzo = crear_boton(
            actions_bar, text="🍱 ME VOY A ALMORZAR", font=("Segoe UI", 10, "bold"),
            bg="#EA580C", fg="white", hover_bg="#C2410C", padx=15, pady=6,
            command=self._accion_almuerzo
        )
        self.btn_almuerzo.pack(side="left", padx=(0, 10))

        self.btn_toggle_ocupado = crear_boton(
            actions_bar, text="🟡 MARCAR OCUPADO", font=("Segoe UI", 10, "bold"),
            bg="#D97706", fg="white", hover_bg="#B45309", padx=15, pady=6,
            command=self._toggle_disponibilidad
        )
        self.btn_toggle_ocupado.pack(side="left", padx=(0, 10))

        btn_refresh = crear_boton(
            actions_bar, text="🔄 Refrescar", font=("Segoe UI", 10),
            bg=self.t["btn_secondary_bg"], fg=self.t["btn_secondary_fg"],
            hover_bg=self.t["btn_secondary_hover"], padx=12, pady=6, command=self.refrescar_datos
        )
        btn_refresh.pack(side="right")

        # Sección: Cola Completa del Día (Visibilidad Circular)
        cola_container = tk.Frame(parent, bg=self.t["bg_surface"], bd=1, relief="solid", highlightbackground=self.t["border"], highlightthickness=1)
        cola_container.pack(fill="both", expand=True, padx=5, pady=(5, 0))

        cola_head = tk.Frame(cola_container, bg=self.t["bg_card"], height=32)
        cola_head.pack(fill="x")
        cola_head.pack_propagate(False)
        tk.Label(cola_head, text="👥 COLA DE ATENCIÓN DE HOY (ORDEN CIRCULAR)", font=("Segoe UI", 10, "bold"), bg=self.t["bg_card"], fg=self.t["text_primary"]).pack(side="left", padx=12, pady=5)

        # Tabla de Cola Operario
        cols = ("pos", "operario", "estado", "normales", "especiales", "total", "ultima")
        self.tree_op_cola = ttk.Treeview(cola_container, columns=cols, show="headings", selectmode="browse")
        self.tree_op_cola.heading("pos", text="#")
        self.tree_op_cola.heading("operario", text="Operario")
        self.tree_op_cola.heading("estado", text="Estado Actual")
        self.tree_op_cola.heading("normales", text="Normales")
        self.tree_op_cola.heading("especiales", text="Especiales")
        self.tree_op_cola.heading("total", text="Total Atendidos")
        self.tree_op_cola.heading("ultima", text="Última Atención")

        self.tree_op_cola.column("pos", width=45, anchor="center")
        self.tree_op_cola.column("operario", width=220, anchor="w")
        self.tree_op_cola.column("estado", width=140, anchor="center")
        self.tree_op_cola.column("normales", width=90, anchor="center")
        self.tree_op_cola.column("especiales", width=90, anchor="center")
        self.tree_op_cola.column("total", width=110, anchor="center")
        self.tree_op_cola.column("ultima", width=140, anchor="center")

        scroll_op = ttk.Scrollbar(cola_container, orient="vertical", command=self.tree_op_cola.yview)
        self.tree_op_cola.configure(yscrollcommand=scroll_op.set)
        scroll_op.pack(side="right", fill="y")
        self.tree_op_cola.pack(fill="both", expand=True, padx=5, pady=5)

    # =========================================================================
    #   VISTA DEL ADMINISTRADOR (SUPERVISIÓN Y CONTROL)
    # =========================================================================

    def _construir_ui_admin(self, parent):
        # Spotlight: Turno Actual
        self.spotlight_frame = tk.Frame(parent, bg=self.t["bg_surface"], bd=1, relief="solid", highlightbackground=self.t["border"], highlightthickness=1)
        self.spotlight_frame.pack(fill="x", pady=(0, 8))

        spot_head = tk.Frame(self.spotlight_frame, bg=self.t["bg_card"], height=30)
        spot_head.pack(fill="x")
        spot_head.pack_propagate(False)
        tk.Label(spot_head, text="🎯 OPERARIO EN TURNO ACTUAL", font=("Segoe UI", 9, "bold"), bg=self.t["bg_card"], fg=self.t["text_primary"]).pack(side="left", padx=12, pady=4)

        self.lbl_alerta_spot = tk.Label(spot_head, text="", font=("Segoe UI", 9, "bold"), bg=self.t["bg_card"], fg=COLOR_ALERTA)
        self.lbl_alerta_spot.pack(side="right", padx=12)

        spot_body = tk.Frame(self.spotlight_frame, bg=self.t["bg_surface"], padx=15, pady=10)
        spot_body.pack(fill="x")

        self.lbl_spot_operario = tk.Label(spot_body, text="Cargando operario...", font=("Segoe UI", 16, "bold"), bg=self.t["bg_surface"], fg=self.t["text_primary"])
        self.lbl_spot_operario.pack(side="left", padx=(0, 15))

        self.lbl_spot_badge = tk.Label(spot_body, text="🔵 EN TURNO", font=("Segoe UI", 11, "bold"), bg="#EFF6FF", fg=COLOR_EN_TURNO, padx=10, pady=4, bd=1, relief="solid")
        self.lbl_spot_badge.pack(side="left", padx=(0, 20))

        tk.Label(spot_body, text="Tiempo en Turno:", font=("Segoe UI", 9), bg=self.t["bg_surface"], fg=self.t["text_muted"]).pack(side="left", padx=(10, 5))
        self.lbl_spot_timer = tk.Label(spot_body, text="00:00:00", font=("Segoe UI", 14, "bold"), bg=self.t["bg_surface"], fg=COLOR_EN_TURNO)
        self.lbl_spot_timer.pack(side="left", padx=(0, 20))

        self.lbl_spot_stats = tk.Label(spot_body, text="Atenciones hoy: --", font=("Segoe UI", 9), bg=self.t["bg_surface"], fg=self.t["text_primary"])
        self.lbl_spot_stats.pack(side="left")

        # Barra de Acciones Administrativas
        admin_actions = tk.Frame(parent, bg=self.t["bg_app"])
        admin_actions.pack(fill="x", pady=(0, 8))

        btn_especial = crear_boton(
            admin_actions, text="⭐ TURNO ESPECIAL", font=("Segoe UI", 9, "bold"),
            bg="#7C3AED", fg="white", hover_bg="#6D28D9", padx=10, pady=5,
            command=self._modal_asignar_especial
        )
        btn_especial.pack(side="left", padx=(0, 6))

        btn_saltar = crear_boton(
            admin_actions, text="⏭️ SALTAR TURNO", font=("Segoe UI", 9, "bold"),
            bg="#EA580C", fg="white", hover_bg="#C2410C", padx=10, pady=5,
            command=self._modal_saltar_turno
        )
        btn_saltar.pack(side="left", padx=(0, 6))

        btn_reubicar = crear_boton(
            admin_actions, text="🔄 REUBICAR", font=("Segoe UI", 9, "bold"),
            bg="#0284C7", fg="white", hover_bg="#0369A1", padx=10, pady=5,
            command=self._modal_reubicar
        )
        btn_reubicar.pack(side="left", padx=(0, 6))

        btn_manual = crear_boton(
            admin_actions, text="👤 ASIGNAR MANUAL", font=("Segoe UI", 9, "bold"),
            bg="#0D9488", fg="white", hover_bg="#0F766E", padx=10, pady=5,
            command=self._modal_asignar_manual
        )
        btn_manual.pack(side="left", padx=(0, 6))

        btn_cerrar_ciclo = crear_boton(
            admin_actions, text="🏁 CERRAR JORNADA", font=("Segoe UI", 9, "bold"),
            bg=self.t["text_muted"], fg="white", hover_bg="#334155", padx=10, pady=5,
            command=self._confirmar_cerrar_ciclo
        )
        btn_cerrar_ciclo.pack(side="right")

        btn_admin_ref = crear_boton(
            admin_actions, text="🔄 Refrescar", font=("Segoe UI", 9),
            bg=self.t["btn_secondary_bg"], fg=self.t["btn_secondary_fg"],
            hover_bg=self.t["btn_secondary_hover"], padx=10, pady=5, command=self.refrescar_datos
        )
        btn_admin_ref.pack(side="right", padx=(0, 6))

        # Notebook de pestañas
        self.notebook_admin = ttk.Notebook(parent, style="Turnos.TNotebook")
        self.notebook_admin.pack(fill="both", expand=True)

        self.tab_cola = tk.Frame(self.notebook_admin, bg=self.t["bg_surface"])
        self.tab_almuerzos = tk.Frame(self.notebook_admin, bg=self.t["bg_surface"])
        self.tab_historial = tk.Frame(self.notebook_admin, bg=self.t["bg_surface"])
        self.tab_resumen = tk.Frame(self.notebook_admin, bg=self.t["bg_surface"])

        self.notebook_admin.add(self.tab_cola, text="📋 Cola de Atención")
        self.notebook_admin.add(self.tab_almuerzos, text="🍱 Control de Almuerzos")
        self.notebook_admin.add(self.tab_historial, text="📜 Historial y Trazabilidad")
        self.notebook_admin.add(self.tab_resumen, text="📊 Resumen y Cierre")

        self._construir_tab_cola(self.tab_cola)
        self._construir_tab_almuerzos(self.tab_almuerzos)
        self._construir_tab_historial(self.tab_historial)
        self._construir_tab_resumen(self.tab_resumen)

    def _construir_tab_cola(self, parent):
        cols = ("pos", "id", "operario", "estado", "normales", "especiales", "total", "tiempo_turno", "ultima")
        self.tree_admin_cola = ttk.Treeview(parent, columns=cols, show="headings", selectmode="browse")
        self.tree_admin_cola.heading("pos", text="#")
        self.tree_admin_cola.heading("id", text="ID")
        self.tree_admin_cola.heading("operario", text="Operario")
        self.tree_admin_cola.heading("estado", text="Estado")
        self.tree_admin_cola.heading("normales", text="Normales")
        self.tree_admin_cola.heading("especiales", text="Especiales")
        self.tree_admin_cola.heading("total", text="Total Atendidos")
        self.tree_admin_cola.heading("tiempo_turno", text="Tiempo en Turno")
        self.tree_admin_cola.heading("ultima", text="Última Atención")

        self.tree_admin_cola.column("pos", width=40, anchor="center")
        self.tree_admin_cola.column("id", width=50, anchor="center")
        self.tree_admin_cola.column("operario", width=220, anchor="w")
        self.tree_admin_cola.column("estado", width=130, anchor="center")
        self.tree_admin_cola.column("normales", width=85, anchor="center")
        self.tree_admin_cola.column("especiales", width=85, anchor="center")
        self.tree_admin_cola.column("total", width=105, anchor="center")
        self.tree_admin_cola.column("tiempo_turno", width=120, anchor="center")
        self.tree_admin_cola.column("ultima", width=140, anchor="center")

        scroll = ttk.Scrollbar(parent, orient="vertical", command=self.tree_admin_cola.yview)
        self.tree_admin_cola.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree_admin_cola.pack(fill="both", expand=True, padx=4, pady=4)

    def _construir_tab_almuerzos(self, parent):
        cols = ("operario", "salida", "regreso", "duracion", "estado")
        self.tree_almuerzos = ttk.Treeview(parent, columns=cols, show="headings", selectmode="browse")
        self.tree_almuerzos.heading("operario", text="Operario")
        self.tree_almuerzos.heading("salida", text="Hora Salida")
        self.tree_almuerzos.heading("regreso", text="Hora Regreso")
        self.tree_almuerzos.heading("duracion", text="Duración")
        self.tree_almuerzos.heading("estado", text="Estado")

        self.tree_almuerzos.column("operario", width=220, anchor="w")
        self.tree_almuerzos.column("salida", width=140, anchor="center")
        self.tree_almuerzos.column("regreso", width=140, anchor="center")
        self.tree_almuerzos.column("duracion", width=120, anchor="center")
        self.tree_almuerzos.column("estado", width=120, anchor="center")

        scroll = ttk.Scrollbar(parent, orient="vertical", command=self.tree_almuerzos.yview)
        self.tree_almuerzos.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree_almuerzos.pack(fill="both", expand=True, padx=4, pady=4)

    def _construir_tab_historial(self, parent):
        cols = ("hora", "evento", "operario", "autor", "motivo")
        self.tree_historial = ttk.Treeview(parent, columns=cols, show="headings", selectmode="browse")
        self.tree_historial.heading("hora", text="Fecha / Hora")
        self.tree_historial.heading("evento", text="Tipo Evento")
        self.tree_historial.heading("operario", text="Operario Afectado")
        self.tree_historial.heading("autor", text="Ejecutado Por")
        self.tree_historial.heading("motivo", text="Motivo / Detalle")

        self.tree_historial.column("hora", width=140, anchor="center")
        self.tree_historial.column("evento", width=160, anchor="center")
        self.tree_historial.column("operario", width=180, anchor="w")
        self.tree_historial.column("autor", width=150, anchor="w")
        self.tree_historial.column("motivo", width=340, anchor="w")

        scroll = ttk.Scrollbar(parent, orient="vertical", command=self.tree_historial.yview)
        self.tree_historial.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree_historial.pack(fill="both", expand=True, padx=4, pady=4)

    def _construir_tab_resumen(self, parent):
        top_res = tk.Frame(parent, bg=self.t["bg_surface"], padx=10, pady=8)
        top_res.pack(fill="x")

        self.lbl_resumen_totales = tk.Label(top_res, text="Consolidando datos del día...", font=("Segoe UI", 10, "bold"), bg=self.t["bg_surface"], fg=self.t["text_primary"])
        self.lbl_resumen_totales.pack(side="left")

        btn_act_res = crear_boton(
            top_res, text="🔄 Actualizar Resumen", font=("Segoe UI", 9),
            bg=self.t["btn_secondary_bg"], fg=self.t["btn_secondary_fg"],
            hover_bg=self.t["btn_secondary_hover"], padx=8, pady=3, command=self._cargar_resumen_dia
        )
        btn_act_res.pack(side="right")

        cols = ("operario", "estado", "normales", "especiales", "saltados", "almuerzos", "mins_almuerzo", "total", "ultima")
        self.tree_resumen = ttk.Treeview(parent, columns=cols, show="headings", selectmode="browse")
        self.tree_resumen.heading("operario", text="Operario")
        self.tree_resumen.heading("estado", text="Estado Actual")
        self.tree_resumen.heading("normales", text="Normales")
        self.tree_resumen.heading("especiales", text="Especiales")
        self.tree_resumen.heading("saltados", text="Saltados")
        self.tree_resumen.heading("almuerzos", text="Almuerzos")
        self.tree_resumen.heading("mins_almuerzo", text="Tiempo Almuerzo")
        self.tree_resumen.heading("total", text="Total Atendidos")
        self.tree_resumen.heading("ultima", text="Última Atención")

        self.tree_resumen.column("operario", width=200, anchor="w")
        self.tree_resumen.column("estado", width=110, anchor="center")
        self.tree_resumen.column("normales", width=80, anchor="center")
        self.tree_resumen.column("especiales", width=80, anchor="center")
        self.tree_resumen.column("saltados", width=80, anchor="center")
        self.tree_resumen.column("almuerzos", width=80, anchor="center")
        self.tree_resumen.column("mins_almuerzo", width=120, anchor="center")
        self.tree_resumen.column("total", width=105, anchor="center")
        self.tree_resumen.column("ultima", width=130, anchor="center")

        scroll = ttk.Scrollbar(parent, orient="vertical", command=self.tree_resumen.yview)
        self.tree_resumen.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree_resumen.pack(fill="both", expand=True, padx=4, pady=4)

    # =========================================================================
    #   SINCRONIZACIÓN Y TIMERS
    # =========================================================================

    def _iniciar_timers(self):
        # Timer local por segundo para actualizar cronómetro visual sin saturar el servidor
        self._segundo_tic()
        # Polling del servidor cada 2.5 segundos
        self._programar_poll()

    def _segundo_tic(self):
        self.segundos_timer_local += 1
        fmt = self._formato_tiempo(self.segundos_timer_local)

        if not self.es_admin and hasattr(self, "lbl_mi_timer") and self.lbl_mi_timer:
            if getattr(self, "mi_estado_actual", "") == "EN_TURNO":
                self.lbl_mi_timer.config(text=fmt)
        elif self.es_admin and hasattr(self, "lbl_spot_timer") and self.lbl_spot_timer:
            self.lbl_spot_timer.config(text=fmt)

        self._timer_after_id = self.root.after(1000, self._segundo_tic)
        session_mgr.registrar_timer(self.root, self._timer_after_id)

    def _programar_poll(self):
        self.refrescar_datos(silencioso=True)
        self._poll_after_id = self.root.after(2500, self._programar_poll)
        session_mgr.registrar_timer(self.root, self._poll_after_id)

    def _formato_tiempo(self, segs):
        if segs < 0:
            segs = 0
        h = segs // 3600
        m = (segs % 3600) // 60
        s = segs % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _al_cerrar(self):
        session_mgr.cancelar_timers(self.root)
        if self._timer_after_id:
            try:
                self.root.after_cancel(self._timer_after_id)
            except Exception:
                pass
        if self._poll_after_id:
            try:
                self.root.after_cancel(self._poll_after_id)
            except Exception:
                pass
        self.root.destroy()

    # =========================================================================
    #   PETICIONES API Y ACTUALIZACIÓN DE DATOS
    # =========================================================================

    def refrescar_datos(self, silencioso=False):
        try:
            resp = api.get("/turnos/estado-actual")
            if resp.status_code == 200:
                self.lbl_conexion.config(text="🟢 Conectado", bg="#10B981")
                self.datos_estado = resp.json()
                self._actualizar_ui_con_datos(self.datos_estado)
            elif resp.status_code == 404:
                # Si no hay ciclo, intentar abrirlo
                api.post("/turnos/abrir-ciclo")
            else:
                self.lbl_conexion.config(text="⚠️ Error Servidor", bg="#DC2626")
        except Exception as e:
            self.lbl_conexion.config(text="⚠️ Reconectando...", bg="#D97706")
            if not silencioso:
                print(f"Error al conectar con servidor de turnos: {e}")

    def _actualizar_ui_con_datos(self, data):
        ciclo = data.get("ciclo")
        turno_actual = data.get("turno_actual")
        cola = data.get("cola", [])
        mi_turno = data.get("mi_turno")

        # 1. Si es operario, actualizar vista de operario
        if not self.es_admin:
            if turno_actual and turno_actual.get("usuario_id"):
                turno_nombre = turno_actual.get("nombre_operario", "--")
                turno_estado = turno_actual.get("estado", "EN_TURNO").replace("_", " ")
                self.lbl_turno_actual.config(text=f"Ahora atiende: {turno_nombre} ({turno_estado})")
            else:
                self.lbl_turno_actual.config(text="Ahora atiende: nadie")

            if mi_turno:
                self.mi_estado_actual = mi_turno.get("estado", "DISPONIBLE")
                st_color, st_bg, st_ico = STATE_COLORS.get(self.mi_estado_actual, (self.t["text_primary"], "#F1F5F9", "⚪"))
                self.lbl_mi_estado_badge.config(text=f"{st_ico} {self.mi_estado_actual}", fg=st_color, bg=st_bg)
                self.lbl_mi_posicion.config(text=f"Posición en Cola: #{mi_turno.get('posicion', '--')}")

                self.segundos_timer_local = mi_turno.get("tiempo_en_turno_segundos", 0)
                self.lbl_mi_timer.config(text=self._formato_tiempo(self.segundos_timer_local))

                ult = mi_turno.get("ultima_atencion")
                ult_str = ult.split("T")[1][:8] if ult and "T" in ult else (ult or "--")
                self.lbl_mi_ultima_atencion.config(text=f"Última atención: {ult_str}")

                self.lbl_cnt_total.config(text=str(mi_turno.get("total_turnos", 0)))
                self.lbl_cnt_normales.config(text=str(mi_turno.get("turnos_normales", 0)))
                self.lbl_cnt_especiales.config(text=str(mi_turno.get("turnos_especiales", 0)))

                # Botón de almuerzo según estado
                if self.mi_estado_actual == "ALMUERZO":
                    self.btn_almuerzo.config(text="🚀 LLEGUÉ (REGRESÉ)", bg="#10B981", fg="#0F172A", activebackground="#059669", activeforeground="#FFFFFF")
                    self.btn_toggle_ocupado.config(state="disabled")
                else:
                    self.btn_almuerzo.config(text="🍱 ME VOY A ALMORZAR", bg="#EA580C", fg="#FFFFFF", activebackground="#C2410C", activeforeground="#FFFFFF")
                    self.btn_toggle_ocupado.config(state="normal")
                    if self.mi_estado_actual == "OCUPADO":
                        self.btn_toggle_ocupado.config(text="🟢 MARCAR DISPONIBLE", bg="#10B981", fg="#0F172A", activebackground="#059669", activeforeground="#FFFFFF")
                    else:
                        self.btn_toggle_ocupado.config(text="🟡 MARCAR OCUPADO", bg="#D97706", fg="#FFFFFF", activebackground="#B45309", activeforeground="#FFFFFF")

            # Cargar tabla cola de operario
            self.tree_op_cola.delete(*self.tree_op_cola.get_children())
            for item in cola:
                if str(item.get("rol", "")).lower() != "operario":
                    continue
                st = item.get("estado", "")
                st_ico = STATE_COLORS.get(st, (None, None, "⚪"))[2]
                ult = item.get("ultima_atencion")
                ult_str = ult.split("T")[1][:8] if ult and "T" in ult else (ult or "--")
                es_yo = " (Tú)" if self.user_id and item.get("usuario_id") == self.user_id else ""
                self.tree_op_cola.insert("", "end", values=(
                    item.get("posicion"),
                    f"{item.get('nombre_operario')}{es_yo}",
                    f"{st_ico} {st}",
                    item.get("turnos_normales", 0),
                    item.get("turnos_especiales", 0),
                    item.get("total_turnos", 0),
                    ult_str
                ))

        # 2. Si es admin, actualizar vista de admin
        if self.es_admin:
            if turno_actual and turno_actual.get("usuario_id"):
                nom = turno_actual.get("nombre_operario", "Desconocido")
                st = turno_actual.get("estado", "EN_TURNO")
                st_color, st_bg, st_ico = STATE_COLORS.get(st, (COLOR_EN_TURNO, "#EFF6FF", "🔵"))
                self.lbl_spot_operario.config(text=f"#{turno_actual.get('posicion', '')} {nom}")
                self.lbl_spot_badge.config(text=f"{st_ico} {st}", fg=st_color, bg=st_bg)

                self.segundos_timer_local = turno_actual.get("tiempo_en_turno_segundos", 0)
                self.lbl_spot_timer.config(text=self._formato_tiempo(self.segundos_timer_local))

                if turno_actual.get("tiempo_elevado", False):
                    self.lbl_alerta_spot.config(text="⚠️ TIEMPO DE TURNO ELEVADO (>15m)")
                    self.lbl_spot_timer.config(fg=COLOR_ALERTA)
                else:
                    self.lbl_alerta_spot.config(text="")
                    self.lbl_spot_timer.config(fg=COLOR_EN_TURNO)

                tot = turno_actual.get("total_turnos", 0)
                norm = turno_actual.get("turnos_normales", 0)
                esp = turno_actual.get("turnos_especiales", 0)
                self.lbl_spot_stats.config(text=f"Total: {tot}  (Normales: {norm} | Especiales: {esp})")
            else:
                self.lbl_spot_operario.config(text="Ningún operario en turno activo")
                self.lbl_spot_badge.config(text="⚪ INACTIVO", fg=COLOR_PAUSADO, bg="#F1F5F9")
                self.lbl_spot_timer.config(text="00:00:00", fg=self.t["text_muted"])
                self.lbl_alerta_spot.config(text="")
                self.lbl_spot_stats.config(text="Cola vacía o todos ocupados/almuerzo")

            # Cargar tabla admin cola
            self.tree_admin_cola.delete(*self.tree_admin_cola.get_children())
            for item in cola:
                if str(item.get("rol", "")).lower() != "operario":
                    continue
                st = item.get("estado", "")
                st_ico = STATE_COLORS.get(st, (None, None, "⚪"))[2]
                ult = item.get("ultima_atencion")
                ult_str = ult.split("T")[1][:8] if ult and "T" in ult else (ult or "--")
                segs = item.get("tiempo_en_turno_segundos", 0)
                t_str = self._formato_tiempo(segs) if st == "EN_TURNO" else "--"
                self.tree_admin_cola.insert("", "end", values=(
                    item.get("posicion"),
                    item.get("usuario_id"),
                    item.get("nombre_operario"),
                    f"{st_ico} {st}",
                    item.get("turnos_normales", 0),
                    item.get("turnos_especiales", 0),
                    item.get("total_turnos", 0),
                    t_str,
                    ult_str
                ))

            # Actualizar pestaña activa si corresponde
            tab_activa = self.notebook_admin.tab(self.notebook_admin.select(), "text")
            if "Historial" in tab_activa:
                self._cargar_historial()
            elif "Almuerzos" in tab_activa:
                self._cargar_almuerzos(cola)

    # =========================================================================
    #   ACCIONES DEL OPERARIO
    # =========================================================================

    def _accion_almuerzo(self):
        if getattr(self, "mi_estado_actual", "") == "ALMUERZO":
            # Regresar de almuerzo
            try:
                resp = api.post("/turnos/almuerzo/finalizar")
                if resp.status_code == 200:
                    data = resp.json()
                    dur = data.get("duracion_minutos", 0.0)
                    messagebox.showinfo("✅ Regreso de Almuerzo", f"¡Bienvenido/a de regreso!\n\nDuración total: {dur:.1f} minutos.\nHas vuelto al estado DISPONIBLE.", parent=self.root)
                    self.refrescar_datos()
                else:
                    err = resp.json().get("detail", resp.text)
                    messagebox.showerror("Error", err, parent=self.root)
            except Exception as e:
                messagebox.showerror("Error de Conexión", str(e), parent=self.root)
        else:
            # Ir a almuerzo
            confirma = messagebox.askyesno("🍱 Confirmar Salida a Almuerzo",
                                          "¿Confirmas que vas a salir a almorzar?\n\nMientras estés en almuerzo no recibirás turnos normales.",
                                          parent=self.root)
            if not confirma:
                return
            try:
                resp = api.post("/turnos/almuerzo/iniciar")
                if resp.status_code == 200:
                    messagebox.showinfo("🍱 Buen Provecho", "Salida a almuerzo registrada exitosamente.\n\nCuando regreses, presiona el botón 'LLEGUÉ'.", parent=self.root)
                    self.refrescar_datos()
                else:
                    err = resp.json().get("detail", resp.text)
                    messagebox.showerror("Error", err, parent=self.root)
            except Exception as e:
                messagebox.showerror("Error de Conexión", str(e), parent=self.root)

    def _toggle_disponibilidad(self):
        nuevo_est = "DISPONIBLE" if getattr(self, "mi_estado_actual", "") == "OCUPADO" else "OCUPADO"
        try:
            resp = api.post("/turnos/disponibilidad", json={"estado": nuevo_est, "motivo": f"Cambio por operario a {nuevo_est}"})
            if resp.status_code == 200:
                self.refrescar_datos()
            else:
                err = resp.json().get("detail", resp.text)
                messagebox.showerror("Error", err, parent=self.root)
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=self.root)

    # =========================================================================
    #   ACCIONES DEL ADMINISTRADOR
    # =========================================================================

    def _obtener_op_seleccionado_cola(self):
        sel = self.tree_admin_cola.selection()
        if not sel:
            return None, None
        vals = self.tree_admin_cola.item(sel[0], "values")
        uid = int(vals[1])
        nombre = vals[2]
        return uid, nombre

    def _modal_asignar_especial(self):
        cola = self.datos_estado.get("cola", []) if self.datos_estado else []
        if not cola:
            messagebox.showwarning("Cola Vacía", "No hay operarios en el ciclo de hoy.", parent=self.root)
            return

        modal = tk.Toplevel(self.root)
        modal.title("⭐ Asignar Turno Especial a Operario")
        t_m = aplicar_tema(modal)
        calcular_geometria_segura(modal, 480, 360, modal_padre=self.root)
        modal.resizable(False, False)
        modal.configure(bg=t_m["bg_app"])
        modal.transient(self.root)
        modal.grab_set()

        tk.Label(modal, text="⭐ ASIGNACIÓN DE TURNO ESPECIAL", font=("Segoe UI", 12, "bold"), bg=t_m["bg_app"], fg="#7C3AED").pack(pady=12)

        f_body = tk.Frame(modal, bg=t_m["bg_surface"], padx=15, pady=12, bd=1, relief="solid", highlightbackground=t_m["border"], highlightthickness=1)
        f_body.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        tk.Label(f_body, text="Seleccionar Operario:", font=("Segoe UI", 9, "bold"), bg=t_m["bg_surface"], fg=t_m["text_primary"]).pack(anchor="w", pady=(0, 2))
        op_map = {f"#{c['posicion']} - {c['nombre_operario']} (ID: {c['usuario_id']})": c['usuario_id'] for c in cola}
        combo_op = ttk.Combobox(f_body, values=list(op_map.keys()), state="readonly")
        combo_op.pack(fill="x", pady=(0, 10))
        if list(op_map.keys()):
            combo_op.current(0)

        tk.Label(f_body, text="Motivo Obligatorio:", font=("Segoe UI", 9, "bold"), bg=t_m["bg_surface"], fg=t_m["text_primary"]).pack(anchor="w", pady=(0, 2))
        txt_motivo = tk.Entry(f_body, font=("Segoe UI", 10), bg=t_m["input_bg"], fg=t_m["input_fg"], insertbackground=t_m["input_fg"])
        txt_motivo.insert(0, "Cliente solicita específicamente al operario")
        txt_motivo.pack(fill="x", pady=(0, 10))

        tk.Label(f_body, text="ℹ️ El turno especial sumará al operario pero NO alterará la cola normal.", font=("Segoe UI", 8), bg=t_m["bg_surface"], fg=t_m["text_muted"]).pack(anchor="w")

        def _guardar():
            sel_str = combo_op.get()
            uid = op_map.get(sel_str)
            motivo = txt_motivo.get().strip()
            if not uid:
                messagebox.showwarning("Faltan Datos", "Seleccione un operario.", parent=modal)
                return
            if len(motivo) < 5:
                messagebox.showwarning("Motivo Obligatorio", "Ingrese un motivo claro (mínimo 5 caracteres).", parent=modal)
                return
            try:
                resp = api.post("/turnos/asignar-especial", json={"usuario_id": uid, "motivo": motivo})
                if resp.status_code == 200:
                    messagebox.showinfo("Éxito", "Turno especial registrado en auditoría y autorizado.", parent=modal)
                    modal.destroy()
                    self.refrescar_datos()
                else:
                    err = resp.json().get("detail", resp.text)
                    messagebox.showerror("Error", err, parent=modal)
            except Exception as ex:
                messagebox.showerror("Error", str(ex), parent=modal)

        f_btns = tk.Frame(f_body, bg=t_m["bg_surface"])
        f_btns.pack(fill="x", pady=(10, 0))
        crear_boton(f_btns, text="Cancelar", command=modal.destroy, bg=t_m["btn_secondary_bg"], fg=t_m["btn_secondary_fg"], hover_bg=t_m["btn_secondary_hover"], padx=10, pady=5).pack(side="left")
        crear_boton(f_btns, text="⭐ ASIGNAR ESPECIAL", command=_guardar, bg="#7C3AED", fg="white", hover_bg="#6D28D9", font=("Segoe UI", 9, "bold"), padx=12, pady=5).pack(side="right")

    def _modal_saltar_turno(self):
        cola = self.datos_estado.get("cola", []) if self.datos_estado else []
        if not cola:
            messagebox.showwarning("Cola Vacía", "No hay operarios en la cola.", parent=self.root)
            return

        modal = tk.Toplevel(self.root)
        modal.title("⏭️ Saltar Turno")
        t_m = aplicar_tema(modal)
        calcular_geometria_segura(modal, 470, 340, modal_padre=self.root)
        modal.resizable(False, False)
        modal.configure(bg=t_m["bg_app"])
        modal.transient(self.root)
        modal.grab_set()

        tk.Label(modal, text="⏭️ SALTAR TURNO DE ATENCIÓN", font=("Segoe UI", 12, "bold"), bg=t_m["bg_app"], fg=COLOR_ALERTA).pack(pady=12)

        f_body = tk.Frame(modal, bg=t_m["bg_surface"], padx=15, pady=12, bd=1, relief="solid", highlightbackground=t_m["border"], highlightthickness=1)
        f_body.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        tk.Label(f_body, text="Operario a Saltar:", font=("Segoe UI", 9, "bold"), bg=t_m["bg_surface"], fg=t_m["text_primary"]).pack(anchor="w")
        op_map = {f"#{c['posicion']} - {c['nombre_operario']} ({c['estado']})": c['usuario_id'] for c in cola}
        combo_op = ttk.Combobox(f_body, values=list(op_map.keys()), state="readonly")
        combo_op.pack(fill="x", pady=(2, 10))

        # Seleccionar por defecto el que está EN_TURNO
        idx_default = 0
        for i, c in enumerate(cola):
            if c.get("estado") == "EN_TURNO":
                idx_default = i
                break
        if list(op_map.keys()):
            combo_op.current(idx_default)

        tk.Label(f_body, text="Motivo Obligatorio del Salto:", font=("Segoe UI", 9, "bold"), bg=t_m["bg_surface"], fg=t_m["text_primary"]).pack(anchor="w")
        motivos_sugeridos = [
            "Operario ocupado con otra tarea",
            "Operario ausente temporalmente de su puesto",
            "Cliente atendido directamente por otro operario",
            "Problema técnico en la terminal",
            "Otro (Especifique)"
        ]
        combo_motivo = ttk.Combobox(f_body, values=motivos_sugeridos)
        combo_motivo.pack(fill="x", pady=(2, 10))
        combo_motivo.set("Operario ocupado con otra tarea")

        def _guardar():
            uid = op_map.get(combo_op.get())
            motivo = combo_motivo.get().strip()
            if not uid:
                messagebox.showwarning("Faltan Datos", "Seleccione el operario.", parent=modal)
                return
            if len(motivo) < 5:
                messagebox.showwarning("Motivo Obligatorio", "Ingrese un motivo claro del salto.", parent=modal)
                return
            try:
                resp = api.post("/turnos/saltar", json={"usuario_id": uid, "motivo": motivo})
                if resp.status_code == 200:
                    messagebox.showinfo("Éxito", "Turno saltado y registrado en el historial de auditoría.", parent=modal)
                    modal.destroy()
                    self.refrescar_datos()
                else:
                    err = resp.json().get("detail", resp.text)
                    messagebox.showerror("Error", err, parent=modal)
            except Exception as ex:
                messagebox.showerror("Error", str(ex), parent=modal)

        f_btns = tk.Frame(f_body, bg=t_m["bg_surface"])
        f_btns.pack(fill="x", pady=(10, 0))
        crear_boton(f_btns, text="Cancelar", command=modal.destroy, bg=t_m["btn_secondary_bg"], fg=t_m["btn_secondary_fg"], hover_bg=t_m["btn_secondary_hover"], padx=10, pady=5).pack(side="left")
        crear_boton(f_btns, text="⏭️ CONFIRMAR SALTO", command=_guardar, bg=COLOR_ALERTA, fg="white", hover_bg="#B91C1C", font=("Segoe UI", 9, "bold"), padx=12, pady=5).pack(side="right")

    def _modal_reubicar(self):
        cola = self.datos_estado.get("cola", []) if self.datos_estado else []
        if not cola:
            messagebox.showwarning("Cola Vacía", "No hay operarios en la cola.", parent=self.root)
            return

        modal = tk.Toplevel(self.root)
        modal.title("🔄 Reubicar Posición en Cola")
        t_m = aplicar_tema(modal)
        calcular_geometria_segura(modal, 470, 360, modal_padre=self.root)
        modal.resizable(False, False)
        modal.configure(bg=t_m["bg_app"])
        modal.transient(self.root)
        modal.grab_set()

        tk.Label(modal, text="🔄 REUBICAR OPERARIO EN LA COLA", font=("Segoe UI", 12, "bold"), bg=t_m["bg_app"], fg="#0284C7").pack(pady=12)

        f_body = tk.Frame(modal, bg=t_m["bg_surface"], padx=15, pady=12, bd=1, relief="solid", highlightbackground=t_m["border"], highlightthickness=1)
        f_body.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        tk.Label(f_body, text="Operario a Mover:", font=("Segoe UI", 9, "bold"), bg=t_m["bg_surface"], fg=t_m["text_primary"]).pack(anchor="w")
        op_map = {f"#{c['posicion']} - {c['nombre_operario']}": c['usuario_id'] for c in cola}
        combo_op = ttk.Combobox(f_body, values=list(op_map.keys()), state="readonly")
        combo_op.pack(fill="x", pady=(2, 8))
        if list(op_map.keys()):
            combo_op.current(0)

        tk.Label(f_body, text=f"Nueva Posición Deseada (1 a {len(cola)}):", font=("Segoe UI", 9, "bold"), bg=t_m["bg_surface"], fg=t_m["text_primary"]).pack(anchor="w")
        pos_vals = [str(i) for i in range(1, len(cola) + 1)]
        combo_pos = ttk.Combobox(f_body, values=pos_vals, state="readonly")
        combo_pos.pack(fill="x", pady=(2, 8))
        combo_pos.current(len(pos_vals) - 1)

        tk.Label(f_body, text="Motivo Obligatorio de Reubicación:", font=("Segoe UI", 9, "bold"), bg=t_m["bg_surface"], fg=t_m["text_primary"]).pack(anchor="w")
        entry_motivo = tk.Entry(f_body, font=("Segoe UI", 10), bg=t_m["input_bg"], fg=t_m["input_fg"], insertbackground=t_m["input_fg"])
        entry_motivo.insert(0, "Ajuste operativo autorizado por administración")
        entry_motivo.pack(fill="x", pady=(2, 10))

        def _guardar():
            uid = op_map.get(combo_op.get())
            n_pos = int(combo_pos.get()) if combo_pos.get().isdigit() else None
            motivo = entry_motivo.get().strip()
            if not uid or not n_pos:
                messagebox.showwarning("Faltan Datos", "Complete los campos.", parent=modal)
                return
            if len(motivo) < 5:
                messagebox.showwarning("Motivo Obligatorio", "Ingrese un motivo claro (mínimo 5 caracteres).", parent=modal)
                return
            try:
                resp = api.post("/turnos/reubicar", json={"usuario_id": uid, "nueva_posicion": n_pos, "motivo": motivo})
                if resp.status_code == 200:
                    messagebox.showinfo("Éxito", "Operario reubicado y auditado exitosamente.", parent=modal)
                    modal.destroy()
                    self.refrescar_datos()
                else:
                    err = resp.json().get("detail", resp.text)
                    messagebox.showerror("Error", err, parent=modal)
            except Exception as ex:
                messagebox.showerror("Error", str(ex), parent=modal)

        f_btns = tk.Frame(f_body, bg=t_m["bg_surface"])
        f_btns.pack(fill="x", pady=(10, 0))
        crear_boton(f_btns, text="Cancelar", command=modal.destroy, bg=t_m["btn_secondary_bg"], fg=t_m["btn_secondary_fg"], hover_bg=t_m["btn_secondary_hover"], padx=10, pady=5).pack(side="left")
        crear_boton(f_btns, text="🔄 REUBICAR", command=_guardar, bg="#0284C7", fg="white", hover_bg="#0369A1", font=("Segoe UI", 9, "bold"), padx=12, pady=5).pack(side="right")

    def _modal_asignar_manual(self):
        cola = self.datos_estado.get("cola", []) if self.datos_estado else []
        if not cola:
            messagebox.showwarning("Cola Vacía", "No hay operarios en la cola.", parent=self.root)
            return

        modal = tk.Toplevel(self.root)
        modal.title("👤 Asignación Manual Extraordinaria")
        t_m = aplicar_tema(modal)
        calcular_geometria_segura(modal, 470, 340, modal_padre=self.root)
        modal.resizable(False, False)
        modal.configure(bg=t_m["bg_app"])
        modal.transient(self.root)
        modal.grab_set()

        tk.Label(modal, text="👤 ASIGNACIÓN MANUAL EXTRAORDINARIA", font=("Segoe UI", 11, "bold"), bg=t_m["bg_app"], fg="#0D9488").pack(pady=12)

        f_body = tk.Frame(modal, bg=t_m["bg_surface"], padx=15, pady=12, bd=1, relief="solid", highlightbackground=t_m["border"], highlightthickness=1)
        f_body.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        tk.Label(f_body, text="Operario a Asignar EN TURNO:", font=("Segoe UI", 9, "bold"), bg=t_m["bg_surface"], fg=t_m["text_primary"]).pack(anchor="w")
        op_map = {f"#{c['posicion']} - {c['nombre_operario']}": c['usuario_id'] for c in cola}
        combo_op = ttk.Combobox(f_body, values=list(op_map.keys()), state="readonly")
        combo_op.pack(fill="x", pady=(2, 8))
        if list(op_map.keys()):
            combo_op.current(0)

        tk.Label(f_body, text="Motivo Obligatorio (Justificación):", font=("Segoe UI", 9, "bold"), bg=t_m["bg_surface"], fg=t_m["text_primary"]).pack(anchor="w")
        entry_motivo = tk.Entry(f_body, font=("Segoe UI", 10), bg=t_m["input_bg"], fg=t_m["input_fg"], insertbackground=t_m["input_fg"])
        entry_motivo.pack(fill="x", pady=(2, 10))

        def _guardar():
            uid = op_map.get(combo_op.get())
            motivo = entry_motivo.get().strip()
            if not uid:
                messagebox.showwarning("Faltan Datos", "Seleccione un operario.", parent=modal)
                return
            if len(motivo) < 5:
                messagebox.showwarning("Motivo Obligatorio", "Ingrese la justificación de la asignación manual.", parent=modal)
                return
            try:
                resp = api.post("/turnos/asignar-manual", json={"usuario_id": uid, "motivo": motivo})
                if resp.status_code == 200:
                    messagebox.showinfo("Éxito", "Turno asignado manualmente y auditado.", parent=modal)
                    modal.destroy()
                    self.refrescar_datos()
                else:
                    err = resp.json().get("detail", resp.text)
                    messagebox.showerror("Error", err, parent=modal)
            except Exception as ex:
                messagebox.showerror("Error", str(ex), parent=modal)

        f_btns = tk.Frame(f_body, bg=t_m["bg_surface"])
        f_btns.pack(fill="x", pady=(10, 0))
        crear_boton(f_btns, text="Cancelar", command=modal.destroy, bg=t_m["btn_secondary_bg"], fg=t_m["btn_secondary_fg"], hover_bg=t_m["btn_secondary_hover"], padx=10, pady=5).pack(side="left")
        crear_boton(f_btns, text="👤 CONFIRMAR ASIGNACIÓN", command=_guardar, bg="#0D9488", fg="white", hover_bg="#0F766E", font=("Segoe UI", 9, "bold"), padx=12, pady=5).pack(side="right")

    def _confirmar_cerrar_ciclo(self):
        confirma = messagebox.askyesno("🏁 Cierre de Jornada",
                                      "¿Confirmas que deseas cerrar formalmente la jornada de turnos de hoy?\n\nLos contadores se consolidarán y ningún operario quedará activo en turno.",
                                      parent=self.root)
        if not confirma:
            return
        try:
            resp = api.post("/turnos/cerrar-ciclo")
            if resp.status_code == 200:
                messagebox.showinfo("Jornada Cerrada", "El ciclo comercial de turnos ha sido cerrado exitosamente.", parent=self.root)
                self.refrescar_datos()
            else:
                err = resp.json().get("detail", resp.text)
                messagebox.showerror("Error", err, parent=self.root)
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=self.root)

    # =========================================================================
    #   CARGA DE PESTAÑAS ADMINISTRATIVAS (HISTORIAL, RESUMEN, ALMUERZOS)
    # =========================================================================

    def _cargar_almuerzos(self, cola):
        # Muestra operarios en estado ALMUERZO y su duración
        self.tree_almuerzos.delete(*self.tree_almuerzos.get_children())
        for c in cola:
            if c.get("estado") == "ALMUERZO":
                self.tree_almuerzos.insert("", "end", values=(
                    c.get("nombre_operario"),
                    "En almuerzo",
                    "--",
                    "--",
                    "🟠 En Curso"
                ))

    def _cargar_historial(self):
        try:
            resp = api.get("/turnos/historial")
            if resp.status_code == 200:
                eventos = resp.json()
                self.tree_historial.delete(*self.tree_historial.get_children())
                for ev in eventos:
                    dt = ev.get("created_at", "")
                    dt_str = dt.replace("T", " ")[:19] if dt else ""
                    self.tree_historial.insert("", "end", values=(
                        dt_str,
                        ev.get("tipo_evento"),
                        ev.get("usuario_nombre") or "--",
                        ev.get("autor_nombre") or "Sistema",
                        ev.get("motivo") or "--"
                    ))
        except Exception as e:
            print(f"Error cargando historial: {e}")

    def _cargar_resumen_dia(self):
        try:
            resp = api.get("/turnos/resumen-dia")
            if resp.status_code == 200:
                resumen = resp.json()
                tot_at = resumen.get("total_atenciones", 0)
                tot_norm = resumen.get("total_normales", 0)
                tot_esp = resumen.get("total_especiales", 0)
                tot_salt = resumen.get("total_saltados", 0)

                self.lbl_resumen_totales.config(
                    text=f"Total Atenciones: {tot_at}  |  Normales: {tot_norm}  |  Especiales: {tot_esp}  |  Saltados: {tot_salt}"
                )

                self.tree_resumen.delete(*self.tree_resumen.get_children())
                for op in resumen.get("operarios", []):
                    ult = op.get("ultima_atencion")
                    ult_str = ult.split("T")[1][:8] if ult and "T" in ult else (ult or "--")
                    self.tree_resumen.insert("", "end", values=(
                        op.get("usuario_nombre"),
                        op.get("estado_actual"),
                        op.get("normales"),
                        op.get("especiales"),
                        op.get("saltados"),
                        op.get("almuerzos"),
                        f"{op.get('minutos_almuerzo', 0.0):.1f} min",
                        op.get("total_atendidos"),
                        ult_str
                    ))
        except Exception as e:
            print(f"Error cargando resumen: {e}")


def iniciar_control_turnos(user_id=None, rol="operario", nombre_usuario="", ventana_padre=None, parent_pid=""):
    if ventana_padre:
        top = tk.Toplevel(ventana_padre)
        app = TurnosMenuApp(top, user_id=user_id, rol=rol, nombre_usuario=nombre_usuario, parent_pid=parent_pid)
        return top, app
    else:
        root = tk.Tk()
        app = TurnosMenuApp(root, user_id=user_id, rol=rol, nombre_usuario=nombre_usuario, parent_pid=parent_pid)
        root.mainloop()
        return root, app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Módulo de Control del Turno - VmPOS")
    parser.add_argument("--user_id", type=int, default=None, help="ID de usuario logueado")
    parser.add_argument("--rol", type=str, default="operario", help="Rol de usuario (operario/administrador)")
    parser.add_argument("--nombre", type=str, default="", help="Nombre completo de usuario")
    parser.add_argument("--parent_pid", type=str, default="", help="PID del proceso padre")
    if "-h" in sys.argv or "--help" in sys.argv:
        parser.print_help()
        sys.exit(0)
    args, _ = parser.parse_known_args()

    parent_pid = args.parent_pid or os.environ.get("VMPOS_PARENT_PID", "")
    iniciar_control_turnos(user_id=args.user_id, rol=args.rol, nombre_usuario=args.nombre, parent_pid=parent_pid)
