#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivo: interface/caja_menu.py
Módulo de Control de Caja, Sesiones de Turno y Arqueo Físico para VmPOS.
- Apertura de caja con base inicial en efectivo.
- Monitoreo en tiempo real del efectivo físico esperado en gaveta:
  Efectivo esperado = base inicial + entradas de efectivo - salidas de efectivo.
- Separación visual clara: Transferencias Bancarias y Cuentas por Cobrar.
- 6 Acciones directas:
  1) Abrir turno.
  2) Registrar ingreso autorizado.
  3) Registrar gasto o egreso.
  4) Registrar retiro de efectivo.
  5) Realizar cierre y arqueo (conteo físico, diferencia, conciliación bancaria).
  6) Consultar cierres anteriores (historial inmutable).
"""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import os
import sys

try:
    from theme_manager import theme_mgr, aplicar_tema, calcular_geometria_segura, crear_boton, ScrollableContainer
except ImportError:
    from interface.theme_manager import theme_mgr, aplicar_tema, calcular_geometria_segura, crear_boton, ScrollableContainer

try:
    from components.currency_entry import CurrencyEntry, formatear_cop
except ImportError:
    from interface.components.currency_entry import CurrencyEntry, formatear_cop

try:
    from caja_manager import (
        obtener_sesion_activa, abrir_sesion_caja, registrar_movimiento_caja,
        registrar_ingreso_autorizado, registrar_movimiento_financiero,
        calcular_arqueo_sesion, cerrar_sesion_caja, obtener_cierres_anteriores
    )
    from database_manager import conectar_db
except ImportError:
    from interface.caja_manager import (
        obtener_sesion_activa, abrir_sesion_caja, registrar_movimiento_caja,
        registrar_ingreso_autorizado, registrar_movimiento_financiero,
        calcular_arqueo_sesion, cerrar_sesion_caja, obtener_cierres_anteriores
    )
    from interface.database_manager import conectar_db


def iniciar_control_caja(usuario_actual="Administrador", rol_actual="Administrador", parent_pid=""):
    """Inicia la interfaz gráfica de Control de Caja y Arqueo Físico."""
    ventana = tk.Tk()
    try:
        from session_manager import session_mgr
    except ImportError:
        from interface.session_manager import session_mgr
    session_mgr.iniciar_vigilante_padre(ventana, parent_pid=parent_pid)

    try:
        from theme_manager import iniciar_observador_tema
    except ImportError:
        from interface.theme_manager import iniciar_observador_tema
    iniciar_observador_tema(ventana)

    ventana.title("💵 Control de Caja, Arqueo y Tesorería - VmPOS")
    t = aplicar_tema(ventana)
    calcular_geometria_segura(ventana, 1140, 740, min_w=950, min_h=580)
    ventana.configure(bg=t["bg_app"])

    # HEADER
    header = tk.Frame(ventana, bg=t["primary"], height=54)
    header.pack(fill="x", side="top")
    header.pack_propagate(False)

    fg_h = calcular_color_texto_optimo(t["primary"])

    h_left = tk.Frame(header, bg=t["primary"])
    h_left.pack(side="left", padx=15)
    tk.Label(h_left, text="💵", font=("Segoe UI Emoji", 20), bg=t["primary"], fg=fg_h).pack(side="left", padx=(0, 8))
    tk.Label(
        h_left, text="CONTROL DE CAJA, ARQUEO Y TESORERÍA",
        font=("Segoe UI", 13, "bold"), bg=t["primary"], fg=fg_h
    ).pack(side="left")

    lbl_estado_badge = tk.Label(
        header, text="ESTADO: ...", font=("Segoe UI", 10, "bold"),
        bg="#047857", fg="#FFFFFF", padx=12, pady=4, relief="flat"
    )
    lbl_estado_badge.pack(side="right", padx=15)

    lbl_user_badge = tk.Label(
        header, text=f"👤 {usuario_actual} ({rol_actual})",
        font=("Segoe UI", 9, "bold"), bg=t["primary"], fg=fg_h
    )
    lbl_user_badge.pack(side="right", padx=(0, 10))

    # FOOTER
    footer = tk.Frame(ventana, bg=t["bg_surface"], height=48, relief="solid", bd=1)
    footer.pack(fill="x", side="bottom")
    footer.pack_propagate(False)

    crear_boton(footer, "✖ Cerrar Ventana", ventana.destroy, tipo="secondary", tam_fuente=9).pack(side="right", padx=15, pady=8)
    btn_sinc = crear_boton(footer, "🔄 Actualizar Datos", lambda: refrescar_vista(), tipo="primary", icono="🔄", tam_fuente=9)
    btn_sinc.pack(side="right", padx=5, pady=8)

    lbl_footer_status = tk.Label(footer, text="Sistema en línea • Trazabilidad activa", font=("Segoe UI", 9), bg=t["bg_surface"], fg=t["text_muted"])
    lbl_footer_status.pack(side="left", padx=15)

    # BODY
    body = tk.Frame(ventana, bg=t["bg_app"])
    body.pack(fill="both", expand=True, padx=14, pady=10)

    # =========================================================================
    # 1. TARJETAS SUPERIORES (5 CARDS DE TESORERÍA)
    # =========================================================================
    cards_frame = tk.Frame(body, bg=t["bg_app"])
    cards_frame.pack(fill="x", pady=(0, 10))
    for i in range(5):
        cards_frame.columnconfigure(i, weight=1)

    def _crear_card(parent, col, titulo, icono, color_accent):
        card = tk.Frame(parent, bg=t["bg_card"], relief="solid", bd=1, highlightbackground=t["border"], highlightthickness=1)
        card.grid(row=0, column=col, padx=4, sticky="nsew")
        top_c = tk.Frame(card, bg=t["bg_card"])
        top_c.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(top_c, text=f"{icono} {titulo}", font=("Segoe UI", 8, "bold"), bg=t["bg_card"], fg=t["text_muted"]).pack(side="left")
        lbl_val = tk.Label(card, text="$ 0 COP", font=("Segoe UI", 12, "bold"), bg=t["bg_card"], fg=color_accent)
        lbl_val.pack(anchor="w", padx=8, pady=(2, 6))
        return lbl_val

    card_base = _crear_card(cards_frame, 0, "BASE INICIAL", "🏁", t["text_main"])
    card_entradas = _crear_card(cards_frame, 1, "ENTRADAS EFECTIVO", "📈", "#16a34a")
    card_salidas = _crear_card(cards_frame, 2, "SALIDAS EFECTIVO", "📉", "#dc2626")
    card_esperado = _crear_card(cards_frame, 3, "EFECTIVO ESPERADO", "💰", "#2563eb")
    card_estado = _crear_card(cards_frame, 4, "ESTADO DEL TURNO", "🛡️", "#059669")

    # =========================================================================
    # 2. SEPARACIÓN VISUAL: TRANSFERENCIAS BANCARIAS Y CUENTAS POR COBRAR
    # =========================================================================
    sec_separadas = tk.Frame(body, bg=t["bg_app"])
    sec_separadas.pack(fill="x", pady=(0, 10))
    sec_separadas.columnconfigure(0, weight=1)
    sec_separadas.columnconfigure(1, weight=1)

    # Bloque Transferencias
    box_transf = tk.Frame(sec_separadas, bg="#EFF6FF", relief="solid", bd=1, padx=12, pady=6)
    box_transf.grid(row=0, column=0, padx=(0, 5), sticky="nsew")
    tk.Label(
        box_transf, text="💳 RECAUDOS POR TRANSFERENCIA (DIGITAL)",
        font=("Segoe UI", 9, "bold"), bg="#EFF6FF", fg="#1E40AF"
    ).pack(anchor="w")
    lbl_transf_info = tk.Label(
        box_transf,
        text="Ventas Transferencia: $ 0 | Abonos Transferencia: $ 0\n⚠️ Recaudos digitales en cuentas bancarias — No entran a gaveta física",
        font=("Segoe UI", 8), bg="#EFF6FF", fg="#1E3A8A", justify="left"
    )
    lbl_transf_info.pack(anchor="w", pady=(2, 0))

    # Bloque Cuentas por Cobrar
    box_fiados = tk.Frame(sec_separadas, bg="#FEF3C7", relief="solid", bd=1, padx=12, pady=6)
    box_fiados.grid(row=0, column=1, padx=(5, 0), sticky="nsew")
    tk.Label(
        box_fiados, text="📝 CUENTAS POR COBRAR (CARTERA / FIADOS)",
        font=("Segoe UI", 9, "bold"), bg="#FEF3C7", fg="#92400E"
    ).pack(anchor="w")
    lbl_fiados_info = tk.Label(
        box_fiados,
        text="Fiados del Turno: $ 0 | Deuda Total de Clientes: $ 0\n⚠️ Mercancía entregada a crédito — Pendiente de cobro",
        font=("Segoe UI", 8), bg="#FEF3C7", fg="#78350F", justify="left"
    )
    lbl_fiados_info.pack(anchor="w", pady=(2, 0))

    # =========================================================================
    # 3. PANEL CENTRAL: ACCIONES (IZQUIERDA) + TABLA DE MOVIMIENTOS (DERECHA)
    # =========================================================================
    main_split = tk.Frame(body, bg=t["bg_app"])
    main_split.pack(fill="both", expand=True)

    # Panel lateral de Acciones
    acciones_panel = tk.Frame(main_split, bg=t["bg_card"], relief="solid", bd=1, width=280)
    acciones_panel.pack(side="left", fill="y", padx=(0, 10))
    acciones_panel.pack_propagate(False)

    tk.Label(
        acciones_panel, text="⚙️ ACCIONES DE CAJA",
        font=("Segoe UI", 10, "bold"), bg=t["bg_card"], fg=t["text_main"]
    ).pack(pady=(10, 8))

    btn_abrir_caja = crear_boton(acciones_panel, "🟢 Abrir Turno", lambda: modal_abrir_caja(), tipo="success", icono="🔓", tam_fuente=9)
    btn_abrir_caja.pack(fill="x", padx=12, pady=4)

    btn_ingreso = crear_boton(acciones_panel, "📥 Registrar Ingreso Autorizado", lambda: modal_ingreso_autorizado(), tipo="primary", icono="➕", tam_fuente=9)
    btn_ingreso.pack(fill="x", padx=12, pady=4)

    btn_egreso = crear_boton(acciones_panel, "💸 Registrar Gasto / Egreso", lambda: modal_egreso_retiro("EGRESO"), tipo="warning", icono="📉", tam_fuente=9)
    btn_egreso.pack(fill="x", padx=12, pady=4)

    btn_retiro = crear_boton(acciones_panel, "🏦 Registrar Retiro Efectivo", lambda: modal_egreso_retiro("RETIRO"), tipo="warning", icono="📤", tam_fuente=9)
    btn_retiro.pack(fill="x", padx=12, pady=4)

    btn_cerrar_caja = crear_boton(acciones_panel, "🔒 Realizar Cierre y Arqueo", lambda: modal_cierre_caja(), tipo="danger", icono="🔐", tam_fuente=9)
    btn_cerrar_caja.pack(fill="x", padx=12, pady=8)

    sep_acc = tk.Frame(acciones_panel, bg=t["border"], height=1)
    sep_acc.pack(fill="x", padx=12, pady=6)

    btn_historial = crear_boton(acciones_panel, "📜 Consultar Cierres Anteriores", lambda: modal_historial_cierres(), tipo="secondary", icono="📑", tam_fuente=9)
    btn_historial.pack(fill="x", padx=12, pady=4)

    lbl_sesion_info = tk.Label(
        acciones_panel, text="Sin turno activo",
        font=("Segoe UI", 8), bg=t["bg_card"], fg=t["text_muted"], justify="center"
    )
    lbl_sesion_info.pack(side="bottom", pady=10)

    # Panel Derecho: Tabla de Movimientos
    tabla_container = tk.Frame(main_split, bg=t["bg_card"], relief="solid", bd=1)
    tabla_container.pack(side="right", fill="both", expand=True)

    header_t = tk.Frame(tabla_container, bg=t["bg_header"], height=34)
    header_t.pack(fill="x")
    header_t.pack_propagate(False)

    tk.Label(
        header_t, text="📋 LIBRO DE MOVIMIENTOS DE LA CAJA",
        font=("Segoe UI", 9, "bold"), bg=t["bg_header"], fg="white"
    ).pack(side="left", padx=10)

    # Filtro de tipo en la cabecera de la tabla
    filtro_var = tk.StringVar(value="Todos")
    def on_filtro_change(*_):
        refrescar_tabla()

    cb_filtro = ttk.Combobox(header_t, textvariable=filtro_var, values=["Todos", "Solo Entradas", "Solo Salidas", "Solo Efectivo"], state="readonly", width=14, font=("Segoe UI", 8))
    cb_filtro.pack(side="right", padx=10, pady=4)
    cb_filtro.bind("<<ComboboxSelected>>", on_filtro_change)
    tk.Label(header_t, text="Filtrar:", font=("Segoe UI", 8), bg=t["bg_header"], fg="white").pack(side="right")

    cols = ("ID", "Hora", "Tipo", "Monto", "Cuenta", "Usuario", "Descripción")
    tree = ttk.Treeview(tabla_container, columns=cols, show="headings")
    tree.pack(fill="both", expand=True, side="left", padx=2, pady=2)

    sc = ttk.Scrollbar(tabla_container, orient="vertical", command=tree.yview)
    sc.pack(side="right", fill="y")
    tree.configure(yscrollcommand=sc.set)

    tree.heading("ID", text="#")
    tree.heading("Hora", text="Hora")
    tree.heading("Tipo", text="Tipo Movimiento")
    tree.heading("Monto", text="Monto ($)")
    tree.heading("Cuenta", text="Cuenta Afectada")
    tree.heading("Usuario", text="Usuario")
    tree.heading("Descripción", text="Concepto / Observaciones")

    tree.column("ID", width=45, anchor="center")
    tree.column("Hora", width=70, anchor="center")
    tree.column("Tipo", width=130, anchor="center")
    tree.column("Monto", width=105, anchor="e")
    tree.column("Cuenta", width=110, anchor="center")
    tree.column("Usuario", width=95, anchor="center")
    tree.column("Descripción", width=260, anchor="w")

    sesion_actual_id = [None]
    movimientos_cache = []

    def refrescar_tabla():
        filtro = filtro_var.get()
        for it in tree.get_children():
            tree.delete(it)

        for m in movimientos_cache:
            tipo_m = m.get("tipo", "")
            signo = "+" if tipo_m in ("APERTURA", "APERTURA_CAJA", "VENTA_EFECTIVO", "ABONO_EFECTIVO", "INGRESO_EXTRAORDINARIO", "AJUSTE") else "-"
            cta = m.get("cuenta", "CAJA_FISICA")

            if filtro == "Solo Entradas" and signo != "+":
                continue
            if filtro == "Solo Salidas" and signo != "-":
                continue
            if filtro == "Solo Efectivo" and "BANCO" in cta:
                continue

            color_tag = "entrada" if signo == "+" else "salida"
            tree.insert("", "end", values=(
                m.get("id"),
                m.get("hora"),
                tipo_m,
                f"{signo}${m.get('monto', 0):,.0f}",
                cta,
                m.get("usuario"),
                m.get("descripcion")
            ), tags=(color_tag,))

        tree.tag_configure("entrada", foreground="#16a34a")
        tree.tag_configure("salida", foreground="#dc2626")

    def refrescar_vista():
        activa = obtener_sesion_activa()
        movimientos_cache.clear()

        if not activa:
            lbl_estado_badge.config(text="CAJA CERRADA", bg="#DC2626")
            card_estado.config(text="CERRADA", fg="#DC2626")
            btn_abrir_caja.config(state="normal")
            btn_ingreso.config(state="disabled")
            btn_egreso.config(state="disabled")
            btn_retiro.config(state="disabled")
            btn_cerrar_caja.config(state="disabled")
            card_base.config(text="$ 0 COP")
            card_entradas.config(text="$ 0 COP")
            card_salidas.config(text="$ 0 COP")
            card_esperado.config(text="$ 0 COP")
            lbl_transf_info.config(text="Ventas Transferencia: $ 0 | Abonos: $ 0\n(Caja cerrada actualmente)")
            lbl_fiados_info.config(text="Fiados del Turno: $ 0 | Cartera Total: $ 0\n(Caja cerrada actualmente)")
            lbl_sesion_info.config(text="Sin turno activo.\nPresiona 'Abrir Turno' para iniciar.")
            sesion_actual_id[0] = None
            refrescar_tabla()
            return

        sesion_actual_id[0] = activa["id"]
        lbl_estado_badge.config(text=f"CAJA ABIERTA (#{activa['id']})", bg="#059669")
        card_estado.config(text=f"ABIERTA (#{activa['id']})", fg="#059669")
        btn_abrir_caja.config(state="disabled")
        btn_ingreso.config(state="normal")
        btn_egreso.config(state="normal")
        btn_retiro.config(state="normal")
        btn_cerrar_caja.config(state="normal")

        arq = calcular_arqueo_sesion(activa["id"])
        base = arq.get("monto_inicial", 0.0)
        entradas = arq.get("entradas_efectivo", 0.0)
        salidas = arq.get("salidas_efectivo", 0.0)
        esperado = arq.get("efectivo_esperado", 0.0)

        card_base.config(text=f"${base:,.0f} COP")
        card_entradas.config(text=f"+${entradas:,.0f} COP")
        card_salidas.config(text=f"-${salidas:,.0f} COP")
        card_esperado.config(text=f"${esperado:,.0f} COP")

        v_transf = arq.get("ventas_transferencia", 0.0)
        a_transf = arq.get("abonos_transferencia", 0.0)
        g_transf = arq.get("gastos_transferencia", 0.0)
        tot_transf = arq.get("transferencias_esperadas", v_transf + a_transf - g_transf)

        v_fiado = arq.get("ventas_fiado", 0.0)
        saldo_cartera = arq.get("saldo_cartera_total", 0.0)

        lbl_transf_info.config(
            text=f"Ventas: ${v_transf:,.0f} | Abonos: ${a_transf:,.0f} | Pagos Banco: -${g_transf:,.0f} | Total: ${tot_transf:,.0f}\n"
                 f"ℹ️ Recaudos digitales en cuentas bancarias — No entran a la gaveta física"
        )

        lbl_fiados_info.config(
            text=f"Fiados del Turno: ${v_fiado:,.0f} | Saldo Total Cartera Deudora: ${saldo_cartera:,.0f}\n"
                 f"ℹ️ Mercancía entregada a crédito — Pendiente de cobro"
        )

        lbl_sesion_info.config(
            text=f"Turno #{activa['id']} • {activa.get('fecha_apertura')} {activa.get('hora_apertura')}\n"
                 f"Responsable: {activa.get('usuario_apertura', 'Administrador')}"
        )

        # Cargar movimientos desde movimientos_financieros / movimientos_caja
        conn = conectar_db()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, hora, tipo, monto, cuenta_afectada, usuario, concepto
                FROM movimientos_financieros
                WHERE sesion_caja_id = ? OR fecha = ?
                ORDER BY id DESC
            """, (activa["id"], activa.get("fecha_apertura")))
            rows = cur.fetchall()

            if not rows:
                # Fallback a movimientos_caja
                cur.execute("""
                    SELECT id, hora, tipo, monto, 'CAJA_FISICA', usuario, descripcion
                    FROM movimientos_caja
                    WHERE sesion_caja_id = ?
                    ORDER BY id DESC
                """, (activa["id"],))
                rows = cur.fetchall()

            for r in rows:
                movimientos_cache.append({
                    "id": r[0],
                    "hora": r[1],
                    "tipo": r[2],
                    "monto": float(r[3] or 0.0),
                    "cuenta": r[4],
                    "usuario": r[5],
                    "descripcion": r[6]
                })
            conn.close()

        refrescar_tabla()

    # =========================================================================
    # MODAL 1: ABRIR TURNO DE CAJA
    # =========================================================================
    def modal_abrir_caja():
        dlg = tk.Toplevel(ventana)
        dlg.title("🟢 Apertura de Turno de Caja")
        t_dlg = aplicar_tema(dlg)
        calcular_geometria_segura(dlg, 420, 270, 360, 220)
        dlg.configure(bg=t_dlg["bg_surface"])
        dlg.transient(ventana)
        dlg.grab_set()

        tk.Label(dlg, text="🟢 APERTURA DE TURNO DE CAJA", font=("Segoe UI", 12, "bold"), bg=t_dlg["bg_surface"], fg=t_dlg["text_main"]).pack(pady=12)
        tk.Label(dlg, text="Ingrese el monto base inicial en efectivo para la gaveta:", font=("Segoe UI", 9), bg=t_dlg["bg_surface"], fg=t_dlg["text_muted"]).pack(pady=4)

        entry_base = CurrencyEntry(dlg, initial_value=0, show_symbol=True, font=("Segoe UI", 14, "bold"), width=16, bg=t_dlg["input_bg"], fg=t_dlg["input_fg"], insertbackground=t_dlg["input_insert"], relief="solid", bd=1)
        entry_base.pack(pady=10)
        entry_base.focus()

        def confirmar():
            base_val = entry_base.get_value()
            try:
                abrir_sesion_caja(usuario=usuario_actual, monto_inicial=base_val)
                dlg.destroy()
                refrescar_vista()
                messagebox.showinfo("Caja Abierta", f"Turno de caja abierto exitosamente con base de ${base_val:,.0f} COP.", parent=ventana)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo abrir la caja: {e}", parent=dlg)

        btn_f = tk.Frame(dlg, bg=t_dlg["bg_surface"])
        btn_f.pack(side="bottom", fill="x", padx=15, pady=12)
        crear_boton(btn_f, "Cancelar", dlg.destroy, tipo="secondary", tam_fuente=9).pack(side="right", padx=5)
        crear_boton(btn_f, "Confirmar Apertura", confirmar, tipo="success", tam_fuente=9).pack(side="right", padx=5)

    # =========================================================================
    # MODAL 2: REGISTRAR INGRESO AUTORIZADO (SENCILLO / APORTE)
    # =========================================================================
    def modal_ingreso_autorizado():
        if not sesion_actual_id[0]:
            messagebox.showwarning("Atención", "No hay un turno de caja abierto.", parent=ventana)
            return

        dlg = tk.Toplevel(ventana)
        dlg.title("📥 Registrar Ingreso Autorizado de Efectivo")
        t_dlg = aplicar_tema(dlg)
        calcular_geometria_segura(dlg, 440, 320, 380, 260)
        dlg.configure(bg=t_dlg["bg_surface"])
        dlg.transient(ventana)
        dlg.grab_set()

        tk.Label(dlg, text="📥 INGRESO AUTORIZADO DE EFECTIVO", font=("Segoe UI", 11, "bold"), bg=t_dlg["bg_surface"], fg="#16a34a").pack(pady=12)

        tk.Label(dlg, text="Monto a ingresar en gaveta:", font=("Segoe UI", 9, "bold"), bg=t_dlg["bg_surface"], fg=t_dlg["text_main"]).pack(anchor="w", padx=25, pady=(4, 2))
        entry_monto = CurrencyEntry(dlg, initial_value=0, show_symbol=True, font=("Segoe UI", 12, "bold"), width=20, bg=t_dlg["input_bg"], fg=t_dlg["input_fg"], insertbackground=t_dlg["input_insert"], relief="solid", bd=1)
        entry_monto.pack(padx=25, pady=(0, 8), fill="x")
        entry_monto.focus()

        tk.Label(dlg, text="Motivo / Justificación (obligatorio):", font=("Segoe UI", 9, "bold"), bg=t_dlg["bg_surface"], fg=t_dlg["text_main"]).pack(anchor="w", padx=25, pady=(4, 2))
        entry_motivo = tk.Entry(dlg, font=("Segoe UI", 10), bg=t_dlg["input_bg"], fg=t_dlg["input_fg"], insertbackground=t_dlg["input_insert"], relief="solid", bd=1)
        entry_motivo.pack(padx=25, pady=(0, 12), fill="x")
        entry_motivo.insert(0, "Adición de sencillo / cambio")

        def confirmar():
            val = entry_monto.get_value()
            motivo = entry_motivo.get().strip()
            if val <= 0:
                messagebox.showwarning("Atención", "El monto debe ser mayor a cero.", parent=dlg)
                return
            if not motivo or len(motivo) < 3:
                messagebox.showwarning("Atención", "Debe ingresar un motivo válido (mínimo 3 caracteres).", parent=dlg)
                return

            try:
                registrar_ingreso_autorizado(
                    monto=val,
                    motivo=motivo,
                    usuario=usuario_actual,
                    sesion_id=sesion_actual_id[0]
                )
                dlg.destroy()
                refrescar_vista()
                messagebox.showinfo("Éxito", f"Ingreso autorizado por ${val:,.0f} COP registrado en caja.", parent=ventana)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo registrar el ingreso: {e}", parent=dlg)

        btn_f = tk.Frame(dlg, bg=t_dlg["bg_surface"])
        btn_f.pack(side="bottom", fill="x", padx=20, pady=12)
        crear_boton(btn_f, "Cancelar", dlg.destroy, tipo="secondary", tam_fuente=9).pack(side="right", padx=5)
        crear_boton(btn_f, "Guardar Ingreso", confirmar, tipo="success", tam_fuente=9).pack(side="right", padx=5)

    # =========================================================================
    # MODAL 3: REGISTRAR GASTO / EGRESO O RETIRO DE EFECTIVO
    # =========================================================================
    def modal_egreso_retiro(tipo):
        if not sesion_actual_id[0]:
            messagebox.showwarning("Atención", "No hay un turno de caja abierto.", parent=ventana)
            return

        dlg = tk.Toplevel(ventana)
        titulo = "💸 REGISTRAR EGRESO DE CAJA" if tipo == "EGRESO" else "🏦 REGISTRAR RETIRO DE EFECTIVO"
        dlg.title(titulo)
        t_dlg = aplicar_tema(dlg)
        calcular_geometria_segura(dlg, 440, 320, 380, 260)
        dlg.configure(bg=t_dlg["bg_surface"])
        dlg.transient(ventana)
        dlg.grab_set()

        tk.Label(dlg, text=titulo, font=("Segoe UI", 11, "bold"), bg=t_dlg["bg_surface"], fg="#DC2626").pack(pady=12)

        tk.Label(dlg, text="Monto a retirar/pagar:", font=("Segoe UI", 9, "bold"), bg=t_dlg["bg_surface"], fg=t_dlg["text_main"]).pack(anchor="w", padx=25, pady=(4, 2))
        entry_m = CurrencyEntry(dlg, initial_value=0, show_symbol=True, font=("Segoe UI", 12, "bold"), width=20, bg=t_dlg["input_bg"], fg=t_dlg["input_fg"], insertbackground=t_dlg["input_insert"], relief="solid", bd=1)
        entry_m.pack(padx=25, pady=(0, 8), fill="x")
        entry_m.focus()

        tk.Label(dlg, text="Motivo / Justificación (obligatorio):", font=("Segoe UI", 9, "bold"), bg=t_dlg["bg_surface"], fg=t_dlg["text_main"]).pack(anchor="w", padx=25, pady=(4, 2))
        entry_obs = tk.Entry(dlg, font=("Segoe UI", 10), bg=t_dlg["input_bg"], fg=t_dlg["input_fg"], insertbackground=t_dlg["input_insert"], relief="solid", bd=1)
        entry_obs.pack(padx=25, pady=(0, 12), fill="x")

        def confirmar():
            val = entry_m.get_value()
            obs = entry_obs.get().strip()
            if val <= 0:
                messagebox.showwarning("Atención", "El monto debe ser mayor a cero.", parent=dlg)
                return
            if not obs or len(obs) < 3:
                messagebox.showwarning("Atención", "Debe ingresar un motivo (mínimo 3 letras).", parent=dlg)
                return

            try:
                tipo_fin = "GASTO_PAGADO" if tipo == "EGRESO" else "RETIRO_CAJA"
                registrar_movimiento_financiero(
                    tipo=tipo_fin,
                    concepto=f"{tipo}: {obs}",
                    monto=val,
                    metodo_pago="Efectivo",
                    cuenta_afectada="CAJA_FISICA",
                    usuario=usuario_actual,
                    referencia_origen="OPERACION_MANUAL",
                    sesion_id=sesion_actual_id[0],
                    observaciones=obs
                )
                dlg.destroy()
                refrescar_vista()
                messagebox.showinfo("Operación Exitosa", f"Movimiento de {tipo} por ${val:,.0f} registrado.", parent=ventana)
            except Exception as e:
                messagebox.showerror("Error", f"Error al registrar movimiento: {e}", parent=dlg)

        btn_f = tk.Frame(dlg, bg=t_dlg["bg_surface"])
        btn_f.pack(side="bottom", fill="x", padx=20, pady=12)
        crear_boton(btn_f, "Cancelar", dlg.destroy, tipo="secondary", tam_fuente=9).pack(side="right", padx=5)
        crear_boton(btn_f, "Guardar Salida", confirmar, tipo="danger", tam_fuente=9).pack(side="right", padx=5)

    # =========================================================================
    # MODAL 4: REALIZAR CIERRE Y ARQUEO FÍSICO
    # =========================================================================
    def modal_cierre_caja():
        if not sesion_actual_id[0]:
            messagebox.showwarning("Atención", "No hay un turno de caja abierto.", parent=ventana)
            return

        arq = calcular_arqueo_sesion(sesion_actual_id[0])
        esperado_efectivo = arq.get("efectivo_esperado", 0.0)
        esperado_transf = arq.get("transferencias_esperadas", arq.get("ventas_transferencia", 0.0))

        dlg = tk.Toplevel(ventana)
        dlg.title("🔒 Cierre de Turno y Arqueo de Caja")
        t_dlg = aplicar_tema(dlg)
        calcular_geometria_segura(dlg, 540, 560, 480, 480)
        dlg.configure(bg=t_dlg["bg_surface"])
        dlg.transient(ventana)
        dlg.grab_set()

        tk.Label(dlg, text="🔒 ARQUEO Y CIERRE DE TURNO", font=("Segoe UI", 12, "bold"), bg=t_dlg["bg_surface"], fg=t_dlg["text_main"]).pack(pady=10)

        # BLOQUE A: EFECTIVO EN GAVETA
        box_efectivo = tk.LabelFrame(dlg, text=" Bloque A: Efectivo Físico en Gaveta ", font=("Segoe UI", 9, "bold"), bg=t_dlg["bg_surface"], fg=t_dlg["text_main"], padx=12, pady=6)
        box_efectivo.pack(fill="x", padx=16, pady=4)

        tk.Label(box_efectivo, text=f"• Base Inicial: ${arq.get('monto_inicial', 0):,.0f} COP", font=("Segoe UI", 8), bg=t_dlg["bg_surface"], fg=t_dlg["text_muted"]).pack(anchor="w")
        tk.Label(box_efectivo, text=f"• (+) Entradas Efectivo: +${arq.get('entradas_efectivo', 0):,.0f} COP", font=("Segoe UI", 8), bg=t_dlg["bg_surface"], fg="#16a34a").pack(anchor="w")
        tk.Label(box_efectivo, text=f"• (-) Salidas Efectivo: -${arq.get('salidas_efectivo', 0):,.0f} COP", font=("Segoe UI", 8), bg=t_dlg["bg_surface"], fg="#dc2626").pack(anchor="w")
        tk.Label(box_efectivo, text=f"EFECTIVO ESPERADO EN GAVETA: ${esperado_efectivo:,.0f} COP", font=("Segoe UI", 10, "bold"), bg=t_dlg["bg_surface"], fg="#2563eb").pack(anchor="w", pady=(4, 2))

        tk.Label(box_efectivo, text="Dinero físico contado por el cajero/administrador:", font=("Segoe UI", 9, "bold"), bg=t_dlg["bg_surface"], fg=t_dlg["text_main"]).pack(anchor="w", pady=(4, 2))

        lbl_dif_efectivo = tk.Label(box_efectivo, text="Diferencia: $ 0 COP (✅ CAJA CUADRADA)", font=("Segoe UI", 10, "bold"), bg=t_dlg["bg_surface"], fg="#16a34a")

        def al_cambiar_contado(val_contado):
            dif = val_contado - esperado_efectivo
            if abs(dif) < 0.01:
                lbl_dif_efectivo.config(text="Diferencia: $ 0 COP (✅ CAJA CUADRADA)", fg="#16a34a")
            elif dif < 0:
                lbl_dif_efectivo.config(text=f"Diferencia: -${abs(dif):,.0f} COP (🚨 FALTANTE EN CAJA)", fg="#dc2626")
            else:
                lbl_dif_efectivo.config(text=f"Diferencia: +${dif:,.0f} COP (⚠️ SOBRANTE EN CAJA)", fg="#2563eb")

        entry_contado = CurrencyEntry(
            box_efectivo,
            initial_value=esperado_efectivo,
            show_symbol=True,
            on_change=al_cambiar_contado,
            font=("Segoe UI", 12, "bold"),
            width=18,
            bg=t_dlg["input_bg"],
            fg=t_dlg["input_fg"],
            insertbackground=t_dlg["input_insert"],
            relief="solid",
            bd=1
        )
        entry_contado.pack(anchor="w", fill="x", pady=2)
        lbl_dif_efectivo.pack(anchor="w", pady=(2, 4))
        al_cambiar_contado(int(round(esperado_efectivo)))

        # BLOQUE B: CONCILIACIÓN BANCARIA (TRANSFERENCIAS)
        box_banco = tk.LabelFrame(dlg, text=" Bloque B: Conciliación de Transferencias Bancarias ", font=("Segoe UI", 9, "bold"), bg=t_dlg["bg_surface"], fg=t_dlg["text_main"], padx=12, pady=6)
        box_banco.pack(fill="x", padx=16, pady=4)

        tk.Label(box_banco, text=f"• Transferencias Esperadas del Turno: ${esperado_transf:,.0f} COP", font=("Segoe UI", 9, "bold"), bg=t_dlg["bg_surface"], fg="#1E40AF").pack(anchor="w")
        tk.Label(box_banco, text="Monto verificado en extractos bancarios / app digital:", font=("Segoe UI", 8), bg=t_dlg["bg_surface"], fg=t_dlg["text_muted"]).pack(anchor="w", pady=(2, 2))

        entry_transf_verif = CurrencyEntry(
            box_banco,
            initial_value=esperado_transf,
            show_symbol=True,
            font=("Segoe UI", 11, "bold"),
            width=18,
            bg=t_dlg["input_bg"],
            fg=t_dlg["input_fg"],
            insertbackground=t_dlg["input_insert"],
            relief="solid",
            bd=1
        )
        entry_transf_verif.pack(anchor="w", fill="x", pady=2)

        # OBSERVACIONES
        tk.Label(dlg, text="Observaciones / Motivo de diferencias (opcional):", font=("Segoe UI", 8, "bold"), bg=t_dlg["bg_surface"], fg=t_dlg["text_main"]).pack(anchor="w", padx=18, pady=(4, 2))
        entry_cierre_obs = tk.Entry(dlg, font=("Segoe UI", 9), bg=t_dlg["input_bg"], fg=t_dlg["input_fg"], insertbackground=t_dlg["input_insert"], relief="solid", bd=1)
        entry_cierre_obs.pack(padx=18, pady=(0, 8), fill="x")

        def confirmar_cierre():
            contado = entry_contado.get_value()
            verif_banco = entry_transf_verif.get_value()
            obs = entry_cierre_obs.get().strip()
            dif_ef = contado - esperado_efectivo
            dif_bk = verif_banco - esperado_transf

            conf = messagebox.askyesno(
                "Confirmar Cierre de Caja",
                f"¿Confirmas el cierre definitivo del turno #{sesion_actual_id[0]}?\n\n"
                f"💵 EFECTIVO GAVETA:\n"
                f"   Esperado:  ${esperado_efectivo:,.0f} COP\n"
                f"   Contado:   ${contado:,.0f} COP\n"
                f"   Diferencia: ${dif_ef:+,.0f} COP\n\n"
                f"💳 BANCOS / TRANSFERENCIAS:\n"
                f"   Esperado:   ${esperado_transf:,.0f} COP\n"
                f"   Verificado: ${verif_banco:,.0f} COP\n"
                f"   Diferencia: ${dif_bk:+,.0f} COP",
                parent=dlg
            )
            if not conf:
                return

            try:
                res = cerrar_sesion_caja(
                    sesion_id=sesion_actual_id[0],
                    usuario=usuario_actual,
                    monto_real_contado=contado,
                    observaciones=obs,
                    monto_transferencias_verificado=verif_banco
                )
                dlg.destroy()
                refrescar_vista()
                messagebox.showinfo(
                    "Cierre Exitoso",
                    f"Turno de caja cerrado exitosamente.\n\n"
                    f"Estado Efectivo: {res['tipo_diferencia']} (${res['diferencia']:+,.0f} COP)\n"
                    f"Estado Bancos:   {res.get('estado_banco', 'Verificada')}",
                    parent=ventana
                )
            except Exception as e:
                messagebox.showerror("Error", f"Error al cerrar caja: {e}", parent=dlg)

        btn_f = tk.Frame(dlg, bg=t_dlg["bg_surface"])
        btn_f.pack(side="bottom", fill="x", padx=16, pady=10)
        crear_boton(btn_f, "Cancelar", dlg.destroy, tipo="secondary", tam_fuente=9).pack(side="right", padx=5)
        crear_boton(btn_f, "🔒 Confirmar Cierre", confirmar_cierre, tipo="danger", tam_fuente=9).pack(side="right", padx=5)

    # =========================================================================
    # MODAL 5: CONSULTAR CIERRES ANTERIORES (HISTORIAL INMUTABLE)
    # =========================================================================
    def modal_historial_cierres():
        dlg_h = tk.Toplevel(ventana)
        dlg_h.title("📜 Historial de Cierres de Turno Anteriores")
        t_h = aplicar_tema(dlg_h)
        calcular_geometria_segura(dlg_h, 920, 520, 750, 420)
        dlg_h.configure(bg=t_h["bg_surface"])
        dlg_h.transient(ventana)
        dlg_h.grab_set()

        top_h = tk.Frame(dlg_h, bg=t_h["primary"], height=40)
        top_h.pack(fill="x")
        top_h.pack_propagate(False)
        tk.Label(top_h, text="📜 HISTORIAL DE CIERRES Y ARQUEOS INMUTABLES", font=("Segoe UI", 11, "bold"), bg=t_h["primary"], fg="white").pack(side="left", padx=15)

        t_frame = tk.Frame(dlg_h, bg=t_h["bg_card"], relief="solid", bd=1)
        t_frame.pack(fill="both", expand=True, padx=14, pady=10)

        cols_h = ("ID", "Apertura", "Cierre", "Usuario", "Base", "Esp. Efectivo", "Contado", "Dif. Efectivo", "Esp. Banco", "Verif. Banco", "Observaciones")
        tree_h = ttk.Treeview(t_frame, columns=cols_h, show="headings")
        tree_h.pack(fill="both", expand=True, side="left")

        sc_h = ttk.Scrollbar(t_frame, orient="vertical", command=tree_h.yview)
        sc_h.pack(side="right", fill="y")
        tree_h.configure(yscrollcommand=sc_h.set)

        tree_h.heading("ID", text="#")
        tree_h.heading("Apertura", text="Fecha Apertura")
        tree_h.heading("Cierre", text="Fecha Cierre")
        tree_h.heading("Usuario", text="Responsable")
        tree_h.heading("Base", text="Base ($)")
        tree_h.heading("Esp. Efectivo", text="Esp. Efectivo")
        tree_h.heading("Contado", text="Contado")
        tree_h.heading("Dif. Efectivo", text="Dif. Efectivo")
        tree_h.heading("Esp. Banco", text="Esp. Banco")
        tree_h.heading("Verif. Banco", text="Verif. Banco")
        tree_h.heading("Observaciones", text="Observaciones")

        tree_h.column("ID", width=40, anchor="center")
        tree_h.column("Apertura", width=105, anchor="center")
        tree_h.column("Cierre", width=105, anchor="center")
        tree_h.column("Usuario", width=90, anchor="center")
        tree_h.column("Base", width=80, anchor="e")
        tree_h.column("Esp. Efectivo", width=90, anchor="e")
        tree_h.column("Contado", width=90, anchor="e")
        tree_h.column("Dif. Efectivo", width=90, anchor="e")
        tree_h.column("Esp. Banco", width=85, anchor="e")
        tree_h.column("Verif. Banco", width=85, anchor="e")
        tree_h.column("Observaciones", width=140, anchor="w")

        cierres = obtener_cierres_anteriores(limit=60)
        for c in cierres:
            dif = c.get("diferencia", 0.0)
            signo = "+" if dif > 0 else ("-" if dif < 0 else "")
            f_ap = f"{c.get('fecha_apertura', '')} {c.get('hora_apertura', '')[:5]}"
            f_ci = f"{c.get('fecha_cierre', '')} {c.get('hora_cierre', '')[:5]}"
            tag = "cuadrada" if abs(dif) < 0.01 else ("faltante" if dif < 0 else "sobrante")

            tree_h.insert("", "end", values=(
                c.get("id"),
                f_ap,
                f_ci,
                c.get("usuario_cierre") or c.get("usuario_apertura"),
                f"${c.get('base_inicial', 0):,.0f}",
                f"${c.get('monto_esperado', 0):,.0f}",
                f"${c.get('monto_real_contado', 0):,.0f}",
                f"{signo}${abs(dif):,.0f}",
                f"${c.get('transferencias_esperadas', 0):,.0f}",
                f"${c.get('transferencias_verificadas', 0):,.0f}",
                c.get("observaciones", "")
            ), tags=(tag,))

        tree_h.tag_configure("cuadrada", foreground="#16a34a")
        tree_h.tag_configure("faltante", foreground="#dc2626")
        tree_h.tag_configure("sobrante", foreground="#2563eb")

        bot_f = tk.Frame(dlg_h, bg=t_h["bg_surface"])
        bot_f.pack(fill="x", padx=14, pady=8)
        crear_boton(bot_f, "Cerrar", dlg_h.destroy, tipo="secondary", tam_fuente=9).pack(side="right")
        tk.Label(bot_f, text=f"Total de turnos cerrados consultados: {len(cierres)}", font=("Segoe UI", 9), bg=t_h["bg_surface"], fg=t_h["text_muted"]).pack(side="left")

    refrescar_vista()
    ventana.mainloop()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Control de Caja y Arqueo VmPOS")
    parser.add_argument("--usuario", default="")
    parser.add_argument("--rol", default="")
    parser.add_argument("--user_id", default="")
    parser.add_argument("--parent_pid", default="")
    if "-h" in sys.argv or "--help" in sys.argv:
        parser.print_help()
        sys.exit(0)
    args, _ = parser.parse_known_args()

    usuario = args.usuario or os.environ.get("VMPOS_USUARIO", "")
    rol = args.rol or os.environ.get("VMPOS_ROL", "")
    parent_pid = args.parent_pid or os.environ.get("VMPOS_PARENT_PID", "")

    if not usuario or not rol:
        try:
            me = api.get("/auth/me")
            if me.status_code == 200:
                d = me.json()
                usuario = usuario or d.get("nombre") or d.get("usuario", "Administrador")
                rol = rol or d.get("rol", "Administrador")
        except Exception:
            pass

    usuario = usuario or "Administrador"
    rol = rol or "Administrador"
    iniciar_control_caja(usuario_actual=usuario, rol_actual=rol, parent_pid=parent_pid)
