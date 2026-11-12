#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivo: interface/ventas_admin_dialog.py
Módulo de Supervisión, Edición y Anulación de Ventas con Auditoría 100% para Administrador.
- Prohibición estricta de DELETE físico.
- Anulación con reversión atómica de inventario, finanzas y comisiones.
- Edición con cálculo de diferencias y trazabilidad en auditoria_ventas.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timedelta, date
import os
import sys

try:
    from theme_manager import (
        theme_mgr, aplicar_tema, calcular_geometria_segura,
        crear_boton, ScrollableContainer, calcular_color_texto_optimo,
        iniciar_observador_tema
    )
except ImportError:
    from interface.theme_manager import (
        theme_mgr, aplicar_tema, calcular_geometria_segura,
        crear_boton, ScrollableContainer, calcular_color_texto_optimo,
        iniciar_observador_tema
    )

try:
    from session_manager import session_mgr
except ImportError:
    from interface.session_manager import session_mgr

try:
    from components.currency_entry import CurrencyEntry, formatear_cop
except ImportError:
    from interface.components.currency_entry import CurrencyEntry, formatear_cop

try:
    from caja_manager import anular_venta_completa, editar_venta_completa
    from database_manager import conectar_db
except ImportError:
    from interface.caja_manager import anular_venta_completa, editar_venta_completa
    from interface.database_manager import conectar_db

try:
    from client.api_client import api
except ImportError:
    try:
        from interface.network_manager import api
    except ImportError:
        api = None


def _normalizar_fecha(txt):
    """Normaliza formatos de fecha DD/MM/YYYY o YYYY-MM-DD a YYYY-MM-DD."""
    if not txt:
        return ""
    txt = txt.strip()
    if "/" in txt:
        partes = txt.split("/")
        if len(partes) == 3 and len(partes[2]) == 4:
            return f"{partes[2]}-{partes[1].zfill(2)}-{partes[0].zfill(2)}"
    elif "-" in txt:
        partes = txt.split("-")
        if len(partes) == 3:
            if len(partes[0]) == 4:
                return f"{partes[0]}-{partes[1].zfill(2)}-{partes[2].zfill(2)}"
            elif len(partes[2]) == 4:
                return f"{partes[2]}-{partes[1].zfill(2)}-{partes[0].zfill(2)}"
    return txt


def abrir_gestion_ventas(parent=None, usuario_actual="Administrador", parent_pid=""):
    """Abre la ventana administrativa de gestión, anulación y edición de ventas."""
    dialog = tk.Toplevel(parent) if parent else tk.Tk()
    parent_pid = parent_pid or os.environ.get("VMPOS_PARENT_PID", "")
    session_mgr.iniciar_vigilante_padre(dialog, parent_pid=parent_pid)
    iniciar_observador_tema(dialog)

    dialog.title("🛡️ Gestión y Auditoría de Ventas - Panel Administrador")
    t = aplicar_tema(dialog)
    calcular_geometria_segura(dialog, 1150, 720, min_w=940, min_h=560)
    dialog.configure(bg=t["bg_app"])

    # Header
    header = tk.Frame(dialog, bg=t["accent"], height=48)
    header.pack(fill="x", side="top")
    header.pack_propagate(False)

    fg_h = calcular_color_texto_optimo(t["accent"])
    tk.Label(
        header, text="🛡️ SUPERVISIÓN Y CONTROL DE VENTAS (AUDITORÍA & ANULACIONES)",
        font=("Segoe UI", 12, "bold"), bg=t["accent"], fg=fg_h
    ).pack(side="left", padx=15)

    # Footer
    footer = tk.Frame(dialog, bg=t["bg_surface"], height=48, relief="solid", bd=1)
    footer.pack(fill="x", side="bottom")
    footer.pack_propagate(False)

    crear_boton(footer, "✖ Cerrar", dialog.destroy, tipo="secondary").pack(side="right", padx=15, pady=8)

    # Barra de Filtros
    filter_bar = tk.Frame(dialog, bg=t["bg_card"], relief="solid", bd=1, padx=12, pady=8)
    filter_bar.pack(fill="x", padx=12, pady=(10, 6))

    # 1. Búsqueda por texto (Factura, operario, cliente, ID)
    tk.Label(filter_bar, text="🔍 Buscar:", font=("Segoe UI", 9, "bold"), bg=t["bg_card"], fg=t["text_main"]).pack(side="left", padx=(0, 4))
    var_busq = tk.StringVar()
    e_busq = tk.Entry(filter_bar, textvariable=var_busq, font=("Segoe UI", 10), width=16, bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_insert"], relief="solid", bd=1)
    e_busq.pack(side="left", padx=(0, 8))

    # 2. Estado
    tk.Label(filter_bar, text="Estado:", font=("Segoe UI", 9, "bold"), bg=t["bg_card"], fg=t["text_main"]).pack(side="left", padx=(2, 4))
    var_estado = tk.StringVar(value="Todos")
    cb_estado = ttk.Combobox(filter_bar, textvariable=var_estado, values=["Todos", "Completada", "Anulada", "Modificada"], state="readonly", width=11)
    cb_estado.pack(side="left", padx=(0, 8))

    # 3. Período / Fecha (Hoy, Ayer, Antes de ayer, o por fecha)
    tk.Label(filter_bar, text="📅 Período:", font=("Segoe UI", 9, "bold"), bg=t["bg_card"], fg=t["text_main"]).pack(side="left", padx=(2, 4))
    var_periodo = tk.StringVar(value="Hoy")
    cb_periodo = ttk.Combobox(
        filter_bar,
        textvariable=var_periodo,
        values=["Hoy", "Ayer", "Antes de ayer", "Por fecha", "Todas las fechas"],
        state="readonly",
        width=14
    )
    cb_periodo.pack(side="left", padx=(0, 4))

    var_fecha = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
    e_fecha = tk.Entry(
        filter_bar,
        textvariable=var_fecha,
        font=("Segoe UI", 10),
        width=11,
        bg=t["input_bg"],
        fg=t["input_fg"],
        insertbackground=t["input_insert"],
        relief="solid",
        bd=1
    )
    e_fecha.pack(side="left", padx=(0, 6))

    btn_filtrar = crear_boton(filter_bar, "Filtrar", lambda: cargar_ventas(), tipo="primary", icono="🔍", tam_fuente=9)
    btn_filtrar.pack(side="left", padx=(2, 6))

    # Botones directos de acceso rápido: Hoy, Ayer, Antier, Todas
    f_rapido = tk.Frame(filter_bar, bg=t["bg_card"])
    f_rapido.pack(side="left", padx=(2, 0))

    def _seleccionar_periodo(op):
        var_periodo.set(op)
        if op == "Hoy":
            var_fecha.set(datetime.now().strftime("%Y-%m-%d"))
        elif op == "Ayer":
            var_fecha.set((datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"))
        elif op == "Antes de ayer":
            var_fecha.set((datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"))
        elif op == "Todas las fechas":
            var_fecha.set("")
        cargar_ventas()

    crear_boton(f_rapido, "Hoy", lambda: _seleccionar_periodo("Hoy"), tipo="secondary", tam_fuente=8, pady=2, padx=5).pack(side="left", padx=1)
    crear_boton(f_rapido, "Ayer", lambda: _seleccionar_periodo("Ayer"), tipo="secondary", tam_fuente=8, pady=2, padx=5).pack(side="left", padx=1)
    crear_boton(f_rapido, "Antier", lambda: _seleccionar_periodo("Antes de ayer"), tipo="secondary", tam_fuente=8, pady=2, padx=5).pack(side="left", padx=1)
    crear_boton(f_rapido, "Todas", lambda: _seleccionar_periodo("Todas las fechas"), tipo="secondary", tam_fuente=8, pady=2, padx=5).pack(side="left", padx=1)

    # Resumen de ventas encontradas (conteo y total dinero)
    lbl_resumen_ventas = tk.Label(filter_bar, text="", font=("Segoe UI", 9, "bold"), bg=t["bg_card"], fg=t["accent"])
    lbl_resumen_ventas.pack(side="right", padx=10)

    def _on_combo_periodo():
        op = var_periodo.get()
        if op == "Hoy":
            var_fecha.set(datetime.now().strftime("%Y-%m-%d"))
            cargar_ventas()
        elif op == "Ayer":
            var_fecha.set((datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"))
            cargar_ventas()
        elif op == "Antes de ayer":
            var_fecha.set((datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"))
            cargar_ventas()
        elif op == "Todas las fechas":
            var_fecha.set("")
            cargar_ventas()
        elif op == "Por fecha":
            e_fecha.focus()
            e_fecha.select_range(0, tk.END)

    cb_periodo.bind("<<ComboboxSelected>>", lambda e: _on_combo_periodo())
    cb_estado.bind("<<ComboboxSelected>>", lambda e: cargar_ventas())
    e_busq.bind("<Return>", lambda e: cargar_ventas())
    e_fecha.bind("<Return>", lambda e: cargar_ventas())

    # Cuerpo principal con Split
    body = tk.Frame(dialog, bg=t["bg_app"])
    body.pack(fill="both", expand=True, padx=12, pady=6)

    # Tabla de Ventas
    t_frame = tk.Frame(body, bg=t["bg_card"], relief="solid", bd=1)
    t_frame.pack(side="left", fill="both", expand=True, padx=(0, 8))

    cols = ("ID", "Factura", "Fecha", "Hora", "Operario", "Cliente", "Método", "Total", "Estado")
    tree = ttk.Treeview(t_frame, columns=cols, show="headings")
    tree.pack(fill="both", expand=True, side="left", padx=2, pady=2)

    sc_y = ttk.Scrollbar(t_frame, orient="vertical", command=tree.yview)
    sc_y.pack(side="right", fill="y")
    tree.configure(yscrollcommand=sc_y.set)

    widths = [45, 80, 85, 75, 110, 110, 95, 95, 85]
    for i, c in enumerate(cols):
        tree.heading(c, text=c)
        tree.column(c, width=widths[i], anchor="center" if i not in (4, 5) else "w")

    tree.tag_configure("Anulada", foreground="#DC2626", font=("Segoe UI", 9, "italic"))
    tree.tag_configure("Completada", foreground=t["text_main"])
    tree.tag_configure("Modificada", foreground="#2563EB", font=("Segoe UI", 9, "bold"))

    # Panel lateral de acciones y detalles
    side_panel = tk.Frame(body, bg=t["bg_card"], relief="solid", bd=1, width=320)
    side_panel.pack(side="right", fill="y")
    side_panel.pack_propagate(False)

    tk.Label(side_panel, text="⚙️ ACCIONES ADMINISTRATIVAS", font=("Segoe UI", 10, "bold"), bg=t["bg_card"], fg=t["text_main"]).pack(pady=(12, 6))

    btn_ver_factura = crear_boton(side_panel, "🧾 Ver / Reimprimir / PDF", lambda: abrir_comprobante_historico(), tipo="primary", icono="🧾", tam_fuente=10)
    btn_ver_factura.pack(fill="x", padx=15, pady=4)

    btn_anular = crear_boton(side_panel, "🚫 Anular Venta", lambda: abrir_modal_anular(), tipo="danger", icono="❌", tam_fuente=10)
    btn_anular.pack(fill="x", padx=15, pady=4)

    btn_editar = crear_boton(side_panel, "✏️ Editar Venta", lambda: abrir_modal_editar(), tipo="warning", icono="✏️", tam_fuente=10)
    btn_editar.pack(fill="x", padx=15, pady=4)

    btn_auditoria = crear_boton(side_panel, "📜 Ver Auditoría de Cambios", lambda: abrir_modal_auditoria(), tipo="secondary", icono="📋", tam_fuente=10)
    btn_auditoria.pack(fill="x", padx=15, pady=4)

    # Detalle de la venta seleccionada
    tk.Label(side_panel, text="📦 DETALLE DE ITEMS", font=("Segoe UI", 9, "bold"), bg=t["bg_card"], fg=t["text_main"]).pack(pady=(15, 4))
    
    cols_det = ("Producto", "Cant", "Subtotal")
    tree_det = ttk.Treeview(side_panel, columns=cols_det, show="headings", height=8)
    tree_det.pack(fill="x", padx=10, pady=4)
    tree_det.heading("Producto", text="Producto")
    tree_det.heading("Cant", text="Cant")
    tree_det.heading("Subtotal", text="Subtotal")
    tree_det.column("Producto", width=150, anchor="w")
    tree_det.column("Cant", width=40, anchor="center")
    tree_det.column("Subtotal", width=80, anchor="e")

    lbl_info_anulacion = tk.Label(side_panel, text="", font=("Segoe UI", 8), bg=t["bg_card"], fg="#DC2626", justify="left", wraplength=290)
    lbl_info_anulacion.pack(fill="x", padx=10, pady=8)

    def obtener_venta_seleccionada():
        sel = tree.focus()
        if not sel:
            messagebox.showwarning("Atención", "Por favor selecciona una venta de la lista.", parent=dialog)
            return None
        item = tree.item(sel)
        return item["values"]

    def abrir_comprobante_historico():
        vals = obtener_venta_seleccionada()
        if not vals:
            return
        id_venta = vals[0]
        try:
            from receipt_manager import reconstruir_datos_venta_historica, mostrar_dialogo_factura
        except ImportError:
            from interface.receipt_manager import reconstruir_datos_venta_historica, mostrar_dialogo_factura

        datos = reconstruir_datos_venta_historica(id_venta)
        if not datos:
            messagebox.showerror("Error", f"No se pudieron reconstruir los datos de la venta #{id_venta}.", parent=dialog)
            return
        mostrar_dialogo_factura(dialog, datos, modo_confirmacion_venta=False)

    def cargar_detalles_seleccion(event=None):
        for it in tree_det.get_children():
            tree_det.delete(it)
        lbl_info_anulacion.config(text="")

        sel = tree.focus()
        if not sel:
            return
        vals = tree.item(sel)["values"]
        id_venta = vals[0]
        estado = vals[8]

        detalles_cargados = False
        if api is not None:
            try:
                resp = api.get(f"/ventas/{id_venta}", timeout=2.5)
                if resp.status_code == 200:
                    v_data = resp.json()
                    for d in v_data.get("detalles") or []:
                        tree_det.insert("", "end", values=(
                            d.get("item_nombre") or "Producto",
                            d.get("cantidad", 1),
                            f"${float(d.get('subtotal', 0.0)):,.0f}"
                        ))
                    if estado == "Anulada" and v_data.get("motivo_anulacion"):
                        lbl_info_anulacion.config(
                            text=f"🚫 ANULADA por {v_data.get('anulado_por', 'Admin')} el {v_data.get('fecha_anulacion', '')}\nMotivo: {v_data.get('motivo_anulacion')}"
                        )
                    detalles_cargados = True
            except Exception:
                detalles_cargados = False

        if not detalles_cargados:
            conn = conectar_db()
            if conn:
                conn.row_factory = __import__("sqlite3").Row
                cur = conn.cursor()
                cur.execute("SELECT nombre_producto, cantidad, subtotal FROM detalle_ventas WHERE id_venta = ?", (id_venta,))
                for r in cur.fetchall():
                    tree_det.insert("", "end", values=(r["nombre_producto"], r["cantidad"], f"${r['subtotal']:,.0f}"))

                if estado == "Anulada":
                    cur.execute("SELECT motivo_anulacion, anulado_por, fecha_anulacion FROM ventas WHERE id_venta = ?", (id_venta,))
                    v_row = cur.fetchone()
                    if v_row and v_row["motivo_anulacion"]:
                        lbl_info_anulacion.config(
                            text=f"🚫 ANULADA por {v_row['anulado_por']} el {v_row['fecha_anulacion']}\nMotivo: {v_row['motivo_anulacion']}"
                        )
                conn.close()

    tree.bind("<<TreeviewSelect>>", cargar_detalles_seleccion)

    def cargar_ventas():
        for it in tree.get_children():
            tree.delete(it)
        for it in tree_det.get_children():
            tree_det.delete(it)
        lbl_info_anulacion.config(text="")

        filtro_txt = var_busq.get().strip().lower()
        filtro_est = var_estado.get()

        p_sel = var_periodo.get()
        f_raw = var_fecha.get().strip()
        fecha_filtro = ""

        if p_sel == "Hoy":
            fecha_filtro = datetime.now().strftime("%Y-%m-%d")
        elif p_sel == "Ayer":
            fecha_filtro = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        elif p_sel == "Antes de ayer":
            fecha_filtro = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
        elif p_sel == "Todas las fechas":
            fecha_filtro = ""
        else:
            fecha_filtro = _normalizar_fecha(f_raw)

        ventas_totales_sum = 0.0
        ventas_contador = 0

        ventas_cargadas = False
        if api is not None:
            try:
                params_api = {"limit": 500}
                if filtro_est != "Todos":
                    params_api["estado"] = filtro_est
                if filtro_txt:
                    params_api["busqueda"] = filtro_txt
                if fecha_filtro:
                    params_api["fecha_inicio"] = fecha_filtro
                    params_api["fecha_fin"] = fecha_filtro

                resp = api.get("/ventas", params=params_api, timeout=3.0)
                if resp.status_code == 200:
                    v_list = resp.json()
                    for v in v_list:
                        id_v = v.get("id")
                        fac = v.get("numero") or f"V-{id_v:06d}"
                        f_v = v.get("fecha") or (v.get("created_at", "")[:10] if v.get("created_at") else "")
                        h_v = v.get("hora") or (v.get("created_at", "")[11:19] if v.get("created_at") else "")
                        op = v.get("operario_nombre") or "Administrador"
                        doc = v.get("cliente_documento") or "Consumidor Final"
                        pags = v.get("pagos") or []
                        met = pags[0].get("metodo") if pags else "Efectivo"
                        tot = float(v.get("total") or 0.0)
                        est = v.get("estado") or "Completada"

                        ventas_totales_sum += tot
                        ventas_contador += 1

                        tree.insert("", "end", values=(
                            id_v, fac, f_v, h_v,
                            op, doc, met,
                            f"${tot:,.0f}", est
                        ), tags=(est,))
                    ventas_cargadas = True
            except Exception as e_api:
                print(f"Aviso consultando ventas desde servidor: {e_api}")

        if not ventas_cargadas:
            conn = conectar_db()
            if not conn:
                return
            try:
                conn.row_factory = __import__("sqlite3").Row
                cur = conn.cursor()

                query = "SELECT id_venta, fecha_venta, hora_venta, documento_cliente, total_venta, metodo_pago, operario, estado FROM ventas"
                where_clauses = []
                params = []

                if filtro_est != "Todos":
                    where_clauses.append("estado = ?")
                    params.append(filtro_est)

                if fecha_filtro:
                    where_clauses.append("(fecha_venta = ? OR fecha_venta LIKE ?)")
                    params.extend([fecha_filtro, f"{fecha_filtro}%"])

                if where_clauses:
                    query += " WHERE " + " AND ".join(where_clauses)
                query += " ORDER BY id_venta DESC LIMIT 500"

                cur.execute(query, params)
                for r in cur.fetchall():
                    doc = str(r["documento_cliente"] or "")
                    op = str(r["operario"] or "")
                    id_v = r["id_venta"]
                    fac = f"V-{id_v:06d}"
                    est = r["estado"] or "Completada"

                    if filtro_txt:
                        if (filtro_txt not in str(id_v).lower() and
                            filtro_txt not in fac.lower() and
                            filtro_txt not in doc.lower() and
                            filtro_txt not in op.lower()):
                            continue

                    tot_item = float(r['total_venta'] or 0.0)
                    ventas_totales_sum += tot_item
                    ventas_contador += 1

                    tree.insert("", "end", values=(
                        id_v, fac, r["fecha_venta"], r["hora_venta"],
                        op, doc, r["metodo_pago"] or "Efectivo",
                        f"${tot_item:,.0f}", est
                    ), tags=(est,))
            finally:
                conn.close()

        lbl_resumen_ventas.config(text=f"📊 {ventas_contador} ventas | ${ventas_totales_sum:,.0f} COP")

    def abrir_modal_anular():
        vals = obtener_venta_seleccionada()
        if not vals:
            return
        id_venta = vals[0]
        estado = vals[8]
        if estado == "Anulada":
            messagebox.showwarning("Atención", "Esta venta ya se encuentra anulada.", parent=dialog)
            return

        modal = tk.Toplevel(dialog)
        modal.title(f"🚫 Anular Venta #{id_venta}")
        t_m = aplicar_tema(modal)
        calcular_geometria_segura(modal, 480, 320, 400, 260)
        modal.configure(bg=t_m["bg_surface"])
        modal.transient(dialog)
        modal.grab_set()

        tk.Label(modal, text=f"🚫 ANULAR VENTA #{id_venta} ({vals[1]})", font=("Segoe UI", 12, "bold"), bg=t_m["bg_surface"], fg="#DC2626").pack(pady=10)
        tk.Label(modal, text=f"Total: {vals[7]} | Método: {vals[6]} | Operario: {vals[4]}", font=("Segoe UI", 9), bg=t_m["bg_surface"], fg=t_m["text_muted"]).pack(pady=2)

        tk.Label(
            modal,
            text="⚠️ Esta acción devolverá los productos físicos al stock,\nrevertirá el dinero/deuda correspondiente y registrará auditoría.",
            font=("Segoe UI", 9, "italic"), bg="#FEE2E2", fg="#991B1B", padx=8, pady=4
        ).pack(fill="x", padx=20, pady=8)

        tk.Label(modal, text="Motivo de Anulación (obligatorio):", font=("Segoe UI", 9, "bold"), bg=t_m["bg_surface"], fg=t_m["text_main"]).pack(anchor="w", padx=20, pady=(6, 2))
        e_motivo = tk.Entry(modal, font=("Segoe UI", 10), bg=t_m["input_bg"], fg=t_m["input_fg"], insertbackground=t_m["input_insert"], relief="solid", bd=1)
        e_motivo.pack(fill="x", padx=20, pady=(0, 12))
        e_motivo.focus()

        def confirmar():
            motivo = e_motivo.get().strip()
            if not motivo or len(motivo) < 3:
                messagebox.showwarning("Campo Obligatorio", "Debes ingresar el motivo de la anulación (mínimo 3 caracteres).", parent=modal)
                return

            try:
                res = anular_venta_completa(
                    id_venta=id_venta,
                    usuario_admin=usuario_actual,
                    motivo=motivo
                )
                modal.destroy()
                cargar_ventas()
                messagebox.showinfo("Venta Anulada", f"La venta #{id_venta} fue anulada exitosamente.\nStock y balances revertidos.", parent=dialog)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo anular la venta: {e}", parent=modal)

        btn_box = tk.Frame(modal, bg=t_m["bg_surface"])
        btn_box.pack(side="bottom", fill="x", padx=20, pady=12)
        crear_boton(btn_box, "Cancelar", modal.destroy, tipo="secondary").pack(side="right", padx=5)
        crear_boton(btn_box, "Confirmar Anulación", confirmar, tipo="danger").pack(side="right", padx=5)

    def abrir_modal_editar():
        vals = obtener_venta_seleccionada()
        if not vals:
            return
        id_venta = vals[0]
        estado = vals[8]
        if estado == "Anulada":
            messagebox.showwarning("Atención", "No se puede editar una venta anulada.", parent=dialog)
            return

        modal = tk.Toplevel(dialog)
        modal.title(f"✏️ Editar Venta #{id_venta}")
        t_m = aplicar_tema(modal)
        calcular_geometria_segura(modal, 600, 480, 500, 400)
        modal.configure(bg=t_m["bg_surface"])
        modal.transient(dialog)
        modal.grab_set()

        tk.Label(modal, text=f"✏️ EDITAR VENTA #{id_venta} ({vals[1]})", font=("Segoe UI", 12, "bold"), bg=t_m["bg_surface"], fg="#2563EB").pack(pady=10)

        # Cargar items actuales de la venta (API centralizada primero, luego SQLite local)
        items_venta = []
        if api is not None:
            try:
                resp = api.get(f"/ventas/{id_venta}")
                if resp.status_code == 200:
                    v_info = resp.json()
                    raw_items = v_info.get("detalles") or v_info.get("items") or []
                    for it in raw_items:
                        items_venta.append({
                            "codigo_producto": it.get("item_codigo") or it.get("codigo_producto") or it.get("codigo") or "",
                            "nombre_producto": it.get("item_nombre") or it.get("nombre_producto") or it.get("nombre") or "",
                            "precio_unitario": float(it.get("precio_vendido") or it.get("precio_unitario") or it.get("precio") or 0.0),
                            "cantidad": float(it.get("cantidad") or it.get("cant") or 1.0)
                        })
            except Exception as e_api_v:
                print(f"Aviso al cargar ítems de venta #{id_venta} desde API: {e_api_v}")

        if not items_venta:
            conn = conectar_db()
            if conn:
                conn.row_factory = __import__("sqlite3").Row
                cur = conn.cursor()
                cur.execute("SELECT * FROM detalle_ventas WHERE id_venta = ?", (id_venta,))
                items_venta = [dict(r) for r in cur.fetchall()]
                conn.close()

        # Selector de método
        met_frame = tk.Frame(modal, bg=t_m["bg_surface"])
        met_frame.pack(fill="x", padx=20, pady=4)
        tk.Label(met_frame, text="Método de Pago:", font=("Segoe UI", 9, "bold"), bg=t_m["bg_surface"], fg=t_m["text_main"]).pack(side="left", padx=(0, 6))
        var_nuevo_metodo = tk.StringVar(value=vals[6])
        cb_m = ttk.Combobox(met_frame, textvariable=var_nuevo_metodo, values=["Efectivo", "Transferencia", "Fiado"], state="readonly", width=14)
        cb_m.pack(side="left")

        # Lista de items editables
        items_frame = tk.LabelFrame(modal, text=" Items de la Venta ", font=("Segoe UI", 9, "bold"), bg=t_m["bg_card"], fg=t_m["text_main"], padx=10, pady=6)
        items_frame.pack(fill="both", expand=True, padx=20, pady=6)

        entries_items = []
        for it in items_venta:
            row_i = tk.Frame(items_frame, bg=t_m["bg_card"])
            row_i.pack(fill="x", pady=3)
            nom_it = str(it.get("nombre_producto") or it.get("item_nombre") or it.get("nombre") or "Producto")
            tk.Label(row_i, text=nom_it[:22], font=("Segoe UI", 9), bg=t_m["bg_card"], fg=t_m["text_main"], width=22, anchor="w").pack(side="left")
            tk.Label(row_i, text="Cant:", font=("Segoe UI", 8), bg=t_m["bg_card"], fg=t_m["text_muted"]).pack(side="left", padx=2)
            e_c = tk.Spinbox(row_i, from_=1, to=999, width=5, font=("Segoe UI", 9))
            e_c.delete(0, "end")
            c_val = it.get("cantidad", 1.0)
            try:
                c_flt = float(c_val)
                c_str = str(int(c_flt) if c_flt.is_integer() else c_flt)
            except Exception:
                c_str = str(c_val)
            e_c.insert(0, c_str)
            e_c.pack(side="left", padx=4)

            tk.Label(row_i, text="Precio:", font=("Segoe UI", 8), bg=t_m["bg_card"], fg=t_m["text_muted"]).pack(side="left", padx=2)
            pu_val = float(it.get("precio_unitario") or it.get("precio_vendido") or it.get("precio") or 0.0)
            e_p = CurrencyEntry(row_i, initial_value=pu_val, show_symbol=True, width=12, font=("Segoe UI", 9))
            e_p.pack(side="left", padx=4)

            entries_items.append({"item": it, "entry_cant": e_c, "entry_precio": e_p})

        tk.Label(modal, text="Motivo de la Edición (obligatorio):", font=("Segoe UI", 9, "bold"), bg=t_m["bg_surface"], fg=t_m["text_main"]).pack(anchor="w", padx=20, pady=(6, 2))
        e_motivo_ed = tk.Entry(modal, font=("Segoe UI", 10), bg=t_m["input_bg"], fg=t_m["input_fg"], insertbackground=t_m["input_insert"], relief="solid", bd=1)
        e_motivo_ed.pack(fill="x", padx=20, pady=(0, 10))

        def confirmar_edicion():
            motivo = e_motivo_ed.get().strip()
            if not motivo or len(motivo) < 3:
                messagebox.showwarning("Atención", "Debes ingresar el motivo de la edición (mínimo 3 caracteres).", parent=modal)
                e_motivo_ed.focus_set()
                return

            nuevos_items = []
            for row in entries_items:
                it_orig = row["item"]
                # 1. Obtener y validar cantidad (soporta float, int, y strings con decimales)
                try:
                    c_raw = float(str(row["entry_cant"].get()).strip() or 1.0)
                except Exception:
                    messagebox.showwarning("Cantidad Inválida", f"Por favor ingrese una cantidad numérica válida para '{it_orig.get('nombre_producto', 'el producto')}'.", parent=modal)
                    row["entry_cant"].focus_set()
                    return

                if c_raw <= 0:
                    messagebox.showwarning("Cantidad Inválida", "La cantidad debe ser mayor a cero.", parent=modal)
                    row["entry_cant"].focus_set()
                    return

                cant = int(c_raw) if c_raw.is_integer() else round(c_raw, 3)

                # 2. Obtener y validar precio
                try:
                    pu = float(row["entry_precio"].get_value())
                except Exception:
                    pu = float(it_orig.get("precio_unitario") or it_orig.get("precio_vendido") or it_orig.get("precio") or 0.0)

                if pu < 0:
                    messagebox.showwarning("Precio Inválido", "El precio unitario no puede ser negativo.", parent=modal)
                    return

                cod_prod = str(it_orig.get("codigo_producto") or it_orig.get("item_codigo") or it_orig.get("codigo") or "").strip()
                nom_prod = str(it_orig.get("nombre_producto") or it_orig.get("item_nombre") or it_orig.get("nombre") or cod_prod or "Servicio").strip()

                nuevos_items.append({
                    "codigo_producto": cod_prod,
                    "nombre_producto": nom_prod,
                    "precio_unitario": pu,
                    "cantidad": cant
                })

            if not nuevos_items:
                messagebox.showwarning("Atención", "La venta debe conservar al menos un ítem.", parent=modal)
                return

            try:
                res = editar_venta_completa(
                    id_venta=id_venta,
                    usuario_admin=usuario_actual,
                    nuevo_metodo=var_nuevo_metodo.get(),
                    nuevos_items=nuevos_items,
                    motivo=motivo
                )
                modal.destroy()
                cargar_ventas()
                tot_nuevo = res.get("nuevo_total", res.get("total", 0.0))
                messagebox.showinfo("Venta Modificada", f"Venta #{id_venta} actualizada exitosamente.\nNuevo total: ${tot_nuevo:,.0f} COP.", parent=dialog)
            except Exception as e:
                messagebox.showerror("Error al Editar Venta", f"No se pudo guardar la modificación:\n{e}", parent=modal)

        btn_box_ed = tk.Frame(modal, bg=t_m["bg_surface"])
        btn_box_ed.pack(side="bottom", fill="x", padx=20, pady=12)
        crear_boton(btn_box_ed, "Cancelar", modal.destroy, tipo="secondary").pack(side="right", padx=5)
        crear_boton(btn_box_ed, "Guardar Cambios", confirmar_edicion, tipo="success").pack(side="right", padx=5)

    def abrir_modal_auditoria():
        vals = obtener_venta_seleccionada()
        if not vals:
            return
        id_venta = vals[0]

        modal = tk.Toplevel(dialog)
        modal.title(f"📜 Auditoría de Venta #{id_venta}")
        t_m = aplicar_tema(modal)
        calcular_geometria_segura(modal, 700, 420, 550, 320)
        modal.configure(bg=t_m["bg_surface"])
        modal.transient(dialog)
        modal.grab_set()

        tk.Label(modal, text=f"📜 HISTORIAL DE AUDITORÍA - VENTA #{id_venta} ({vals[1]})", font=("Segoe UI", 11, "bold"), bg=t_m["bg_surface"], fg=t_m["text_main"]).pack(pady=10)

        cols_a = ("ID", "Acción", "Usuario", "Fecha", "Hora", "Motivo", "Anterior", "Nuevo")
        tree_a = ttk.Treeview(modal, columns=cols_a, show="headings")
        tree_a.pack(fill="both", expand=True, padx=15, pady=6)

        for c in cols_a:
            tree_a.heading(c, text=c)
            tree_a.column(c, width=75, anchor="center")
        tree_a.column("Motivo", width=180, anchor="w")

        cargado_api = False
        if api is not None:
            try:
                resp = api.get(f"/ventas/{id_venta}/auditoria")
                if resp.status_code == 200:
                    raw_logs = resp.json()
                    for lg in raw_logs:
                        vn = lg.get("valor_nuevo") or {}
                        va = lg.get("valor_anterior") or {}
                        m_n = vn.get("nuevo_total", vn.get("total", 0.0)) if isinstance(vn, dict) else 0.0
                        m_a = va.get("total_anterior", va.get("total", 0.0)) if isinstance(va, dict) else 0.0
                        tree_a.insert("", "end", values=(
                            lg.get("id"),
                            lg.get("accion") or lg.get("evento", "Edición"),
                            lg.get("usuario_nombre") or lg.get("usuario", "Admin"),
                            lg.get("fecha", ""),
                            lg.get("hora", ""),
                            lg.get("motivo", ""),
                            f"${float(m_a):,.0f}",
                            f"${float(m_n):,.0f}"
                        ))
                    cargado_api = True
            except Exception as e_aud_api:
                print(f"Aviso al cargar auditoría vía API: {e_aud_api}")

        if not cargado_api:
            conn = conectar_db()
            if conn:
                conn.row_factory = __import__("sqlite3").Row
                cur = conn.cursor()
                cur.execute("""
                    SELECT id, accion, usuario, fecha, hora, motivo, valor_anterior, valor_nuevo
                    FROM auditoria_ventas
                    WHERE id_venta = ?
                    ORDER BY id DESC
                """, (id_venta,))
                for r in cur.fetchall():
                    tree_a.insert("", "end", values=(
                        r["id"], r["accion"], r["usuario"], r["fecha"], r["hora"],
                        r["motivo"], f"${float(r['valor_anterior'] or 0):,.0f}", f"${float(r['valor_nuevo'] or 0):,.0f}"
                    ))
                conn.close()

        crear_boton(modal, "Cerrar", modal.destroy, tipo="secondary").pack(pady=10)

    cargar_ventas()
    if not parent:
        dialog.mainloop()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Gestión y Auditoría de Ventas VmPOS")
    parser.add_argument("--usuario", default="Administrador")
    parser.add_argument("--parent_pid", default="")
    if "-h" in sys.argv or "--help" in sys.argv:
        parser.print_help()
        sys.exit(0)
    args, _ = parser.parse_known_args()
    parent_pid = args.parent_pid or os.environ.get("VMPOS_PARENT_PID", "")
    abrir_gestion_ventas(usuario_actual=args.usuario, parent_pid=parent_pid)
