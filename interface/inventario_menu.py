#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivo: inventario_menu.py
Módulo de Gestión Profesional de Inventario de VmPOS.
Organizado en 6 secciones principales:
1. Catálogo de Artículos (Fuente única para Físicos y Servicios)
2. Bodega (Almacenamiento, valorización a costo y compras)
3. Vitrina (Punto de venta mostrador y alertas de reposición)
4. Traslados entre Ubicaciones (Proceso atómico Bodega <-> Vitrina)
5. Entradas y Compras (Recepción formal con conversión de unidades)
6. Movimientos e Historial (Kárdex completo inmutable)
"""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import sys
import os

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
    from business_manager import business_mgr
except ImportError:
    from interface.business_manager import business_mgr

try:
    from interface.inventario_manager import (
        obtener_catalogo, obtener_articulo_por_codigo, sugerir_proximo_codigo,
        crear_articulo, actualizar_articulo, cambiar_estado_articulo,
        obtener_existencias_bodega, obtener_existencias_vitrina,
        ejecutar_traslado, registrar_compra_entrada, registrar_ajuste_inventario,
        obtener_kardex, obtener_historial_traslados, obtener_historial_compras,
        obtener_alertas_inventario, obtener_resumen_indicadores,
        TODAS_LAS_UNIDADES, UNIDADES_DISCRETAS
    )
    from interface.database_manager import conectar_db
except ImportError:
    from inventario_manager import (
        obtener_catalogo, obtener_articulo_por_codigo, sugerir_proximo_codigo,
        crear_articulo, actualizar_articulo, cambiar_estado_articulo,
        obtener_existencias_bodega, obtener_existencias_vitrina,
        ejecutar_traslado, registrar_compra_entrada, registrar_ajuste_inventario,
        obtener_kardex, obtener_historial_traslados, obtener_historial_compras,
        obtener_alertas_inventario, obtener_resumen_indicadores,
        TODAS_LAS_UNIDADES, UNIDADES_DISCRETAS
    )
    from database_manager import conectar_db

# 💵 Formateadores
def formato_peso(valor):
    if valor is None or valor == "":
        return "$0 COP"
    try:
        val_float = float(valor)
        return f"${val_float:,.0f} COP"
    except Exception:
        return "$0 COP"

def formato_cant(val, unidad=""):
    try:
        f = float(val)
        txt = f"{int(f)}" if f.is_integer() else f"{f:,.2f}"
        return f"{txt} {unidad}".strip()
    except Exception:
        return f"{val} {unidad}".strip()

def obtener_proveedores_locales():
    """Consulta proveedores de SQLite local."""
    conn = conectar_db()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, nombre FROM proveedores ORDER BY nombre ASC")
        return cur.fetchall()
    except Exception:
        return []
    finally:
        conn.close()

def modal_crear_proveedor_rapido(parent_win, combo_widget=None, var_widget=None):
    """Crea un proveedor rápidamente desde un modal."""
    modal = tk.Toplevel(parent_win)
    modal.title("Nuevo Proveedor")
    t = aplicar_tema(modal)
    calcular_geometria_segura(modal, 420, 260, 360, 220)
    modal.configure(bg=t["bg_surface"])
    modal.transient(parent_win)
    modal.grab_set()

    body = tk.Frame(modal, bg=t["bg_surface"], padx=20, pady=15)
    body.pack(fill="both", expand=True)

    tk.Label(body, text="Nombre del Proveedor:", font=("Segoe UI", 10, "bold"),
             bg=t["bg_surface"], fg=t["text_main"]).pack(anchor="w", pady=(0, 2))
    e_nom = tk.Entry(body, font=("Segoe UI", 10), bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_insert"])
    e_nom.pack(fill="x", pady=(0, 6))
    e_nom.focus_set()

    tk.Label(body, text="NIT / Documento:", font=("Segoe UI", 9, "bold"),
             bg=t["bg_surface"], fg=t["text_main"]).pack(anchor="w", pady=(0, 2))
    e_nit = tk.Entry(body, font=("Segoe UI", 10), bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_insert"])
    e_nit.pack(fill="x", pady=(0, 6))

    tk.Label(body, text="Teléfono / Contacto:", font=("Segoe UI", 9, "bold"),
             bg=t["bg_surface"], fg=t["text_main"]).pack(anchor="w", pady=(0, 2))
    e_tel = tk.Entry(body, font=("Segoe UI", 10), bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_insert"])
    e_tel.pack(fill="x", pady=(0, 12))

    def guardar():
        nom = e_nom.get().strip()
        nit = e_nit.get().strip()
        tel = e_tel.get().strip()
        if not nom:
            messagebox.showwarning("Aviso", "El nombre del proveedor es obligatorio.", parent=modal)
            return
        conn = conectar_db()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("INSERT INTO proveedores (nombre, documento_nit, telefono) VALUES (?, ?, ?)", (nom, nit, tel))
                conn.commit()
                nuevo_id = cur.lastrowid
                conn.close()
                messagebox.showinfo("Éxito", f"Proveedor '{nom}' creado exitosamente.", parent=modal)
                if combo_widget and var_widget:
                    provs = obtener_proveedores_locales()
                    cur_vals = list(combo_widget.cget("values") or [])
                    lista = [f"{p[0]} - {p[1]}" for p in provs]
                    if "Ninguno" in cur_vals:
                        lista = ["Ninguno"] + lista
                    combo_widget["values"] = lista
                    var_widget.set(f"{nuevo_id} - {nom}")
                modal.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo guardar proveedor: {e}", parent=modal)

    footer = tk.Frame(modal, bg=t["bg_surface_alt"], bd=1, relief="ridge", padx=10, pady=8)
    footer.pack(fill="x", side="bottom")
    crear_boton(footer, "Cancelar", modal.destroy, tipo="secondary", tam_fuente=9).pack(side="right", padx=5)
    crear_boton(footer, "Guardar Proveedor", guardar, tipo="success", icono="💾", tam_fuente=9).pack(side="right", padx=5)
    e_tel.bind("<Return>", lambda ev: guardar())
    e_nom.bind("<Return>", lambda ev: e_nit.focus_set())
    e_nit.bind("<Return>", lambda ev: e_tel.focus_set())

# ==============================================================================
# APLICACIÓN PRINCIPAL DE INVENTARIO
# ==============================================================================

def iniciar_inventario(usuario_actual="Administrador", parent_pid=""):
    ventana = tk.Tk()
    parent_pid = parent_pid or os.environ.get("VMPOS_PARENT_PID", "")
    session_mgr.iniciar_vigilante_padre(ventana, parent_pid=parent_pid)
    iniciar_observador_tema(ventana)

    ventana.title(f"Inventario Profesional - {business_mgr.nombre}")
    t = aplicar_tema(ventana)
    calcular_geometria_segura(ventana, 1260, 780, 1020, 620)
    ventana.configure(bg=t["bg_app"])

    # 🎨 HEADER SUPERIOR CON RESUMEN RÁPIDO
    header = tk.Frame(ventana, bg=t["bg_header"], padx=20, pady=10)
    header.pack(fill="x")

    h_left = tk.Frame(header, bg=t["bg_header"])
    h_left.pack(side="left", fill="y")

    tk.Label(h_left, text="📦", font=("Segoe UI Emoji", 26), bg=t["bg_header"], fg="white").pack(side="left", padx=(0, 10))
    h_titles = tk.Frame(h_left, bg=t["bg_header"])
    h_titles.pack(side="left", fill="y")
    tk.Label(h_titles, text="CONTROL DE INVENTARIO Y BODEGA", font=("Segoe UI", 16, "bold"),
             bg=t["bg_header"], fg=t["text_header"]).pack(anchor="w")
    tk.Label(h_titles, text="Catálogo Unificado • Bodega • Vitrina • Traslados Atómicos • Kárdex",
             font=("Segoe UI", 10), bg=t["bg_header"], fg=t["text_header_sub"]).pack(anchor="w")

    h_right = tk.Frame(header, bg=t["bg_header"])
    h_right.pack(side="right", fill="y")

    def alternar_tema():
        theme_mgr.alternar_tema()
        ventana.destroy()
        iniciar_inventario(usuario_actual, parent_pid=parent_pid)

    btn_tema_txt = "☀️ Modo Claro" if theme_mgr.es_oscuro() else "🌙 Modo Oscuro"
    crear_boton(h_right, btn_tema_txt, alternar_tema, tipo="secondary", tam_fuente=8, padx=8, pady=2).pack(anchor="e", pady=(0, 4))

    lbl_reloj = tk.Label(h_right, text="", font=("Segoe UI", 10), bg=t["bg_header"], fg=t["text_header_sub"])
    lbl_reloj.pack(anchor="e")

    def actualizar_reloj():
        if ventana.winfo_exists():
            ahora = datetime.now()
            lbl_reloj.config(text=f"👤 {usuario_actual}  |  📅 {ahora.strftime('%d/%m/%Y %H:%M:%S')}")
            tid = ventana.after(1000, actualizar_reloj)
            session_mgr.registrar_timer(ventana, tid)
    actualizar_reloj()

    # 📊 BARRA DE KPI GLOBALES (Colores validados WCAG 2.1 AA >= 4.5:1)
    kpi_bar = tk.Frame(ventana, bg=t["bg_surface"], bd=1, relief="solid", padx=15, pady=8)
    kpi_bar.pack(fill="x", padx=15, pady=(10, 5))

    c_bodega = "#0284C7" if not theme_mgr.es_oscuro() else "#38BDF8"
    c_vitrina = "#047857" if not theme_mgr.es_oscuro() else "#34D399"
    c_val_total = "#7C3AED" if not theme_mgr.es_oscuro() else "#A78BFA"
    c_alertas = "#DC2626" if not theme_mgr.es_oscuro() else "#F87171"

    lbl_kpi_total_art = tk.Label(kpi_bar, text="Artículos: 0", font=("Segoe UI", 10, "bold"), bg=t["bg_surface"], fg=t["text_main"])
    lbl_kpi_total_art.pack(side="left", padx=12)

    lbl_kpi_bodega = tk.Label(kpi_bar, text="Bodega: 0 und ($0)", font=("Segoe UI", 10, "bold"), bg=t["bg_surface"], fg=c_bodega)
    lbl_kpi_bodega.pack(side="left", padx=12)

    lbl_kpi_vitrina = tk.Label(kpi_bar, text="Vitrina: 0 und ($0)", font=("Segoe UI", 10, "bold"), bg=t["bg_surface"], fg=c_vitrina)
    lbl_kpi_vitrina.pack(side="left", padx=12)

    lbl_kpi_val_total = tk.Label(kpi_bar, text="Total Inventario a Costo: $0", font=("Segoe UI", 10, "bold"), bg=t["bg_surface"], fg=c_val_total)
    lbl_kpi_val_total.pack(side="left", padx=12)

    lbl_kpi_alertas = tk.Label(kpi_bar, text="Alertas: 0", font=("Segoe UI", 10, "bold"), bg=t["bg_surface"], fg=c_alertas)
    lbl_kpi_alertas.pack(side="right", padx=12)

    def refrescar_kpis():
        try:
            res = obtener_resumen_indicadores()
            u_b = res.get("unidades_bodega", 0)
            v_b = res.get("valor_bodega_costo", 0)
            u_v = res.get("unidades_vitrina", 0)
            v_v = res.get("valor_vitrina_costo", 0)
            v_tot = res.get("valor_inventario_total", 0)
            tot_art = res.get("total_articulos", 0)
            n_alt = res.get("total_alertas", 0)

            lbl_kpi_total_art.config(text=f"📋 Catálogo: {tot_art} ítems")
            lbl_kpi_bodega.config(text=f"🏭 Bodega: {formato_cant(u_b)} ({formato_peso(v_b)})")
            lbl_kpi_vitrina.config(text=f"🏪 Vitrina: {formato_cant(u_v)} ({formato_peso(v_v)})")
            lbl_kpi_val_total.config(text=f"📦 Valor Total Costo: {formato_peso(v_tot)}")
            lbl_kpi_alertas.config(text=f"🔔 Alertas: {n_alt}")
            lbl_kpi_alertas.config(fg="#EF4444" if n_alt > 0 else "#10B981")
        except Exception as e:
            print(f"Error refrescando KPIs: {e}")

    # 📑 CONTENEDOR PRINCIPAL CON NOTEBOOK (6 SECCIONES)
    main_frame = tk.Frame(ventana, bg=t["bg_app"], padx=15, pady=5)
    main_frame.pack(fill="both", expand=True)

    notebook = ttk.Notebook(main_frame)
    notebook.pack(fill="both", expand=True)

    tab_catalogo = tk.Frame(notebook, bg=t["bg_surface"])
    tab_bodega = tk.Frame(notebook, bg=t["bg_surface"])
    tab_vitrina = tk.Frame(notebook, bg=t["bg_surface"])
    tab_traslados = tk.Frame(notebook, bg=t["bg_surface"])
    tab_compras = tk.Frame(notebook, bg=t["bg_surface"])
    tab_kardex = tk.Frame(notebook, bg=t["bg_surface"])

    notebook.add(tab_catalogo, text="📋 Catálogo de Artículos")
    notebook.add(tab_bodega, text="🏭 Bodega (Depósito)")
    notebook.add(tab_vitrina, text="🏪 Vitrina (Punto de Venta)")
    notebook.add(tab_traslados, text="🔄 Traslados Internos")
    notebook.add(tab_compras, text="📥 Entradas y Compras")
    notebook.add(tab_kardex, text="📜 Kárdex e Historial")

    # ==========================================================================
    # SECCIÓN 1: CATÁLOGO DE ARTÍCULOS
    # ==========================================================================
    bar_cat = tk.Frame(tab_catalogo, bg=t["bg_surface"], padx=15, pady=10)
    bar_cat.pack(fill="x")

    tk.Label(bar_cat, text="Buscar:", font=("Segoe UI", 10, "bold"), bg=t["bg_surface"], fg=t["text_main"]).pack(side="left", padx=(0, 5))
    var_filtro_cat = tk.StringVar()
    e_filtro_cat = tk.Entry(bar_cat, textvariable=var_filtro_cat, width=25, font=("Segoe UI", 10),
                            bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_insert"])
    e_filtro_cat.pack(side="left", padx=(0, 15))

    tk.Label(bar_cat, text="Tipo:", font=("Segoe UI", 10, "bold"), bg=t["bg_surface"], fg=t["text_main"]).pack(side="left", padx=(0, 5))
    var_tipo_cat = tk.StringVar(value="Todos")
    cb_tipo_cat = ttk.Combobox(bar_cat, textvariable=var_tipo_cat, values=["Todos", "Fisico", "Servicio"], state="readonly", width=12)
    cb_tipo_cat.pack(side="left", padx=(0, 15))

    def cargar_tabla_catalogo():
        for r in tree_cat.get_children():
            tree_cat.delete(r)
        items = obtener_catalogo(
            filtro=var_filtro_cat.get().strip(),
            tipo=var_tipo_cat.get()
        )
        for it in items:
            p_id = it["id"]
            cod = it["codigo"]
            nom = it["nombre"]
            tipo_p = it["tipo_producto"]
            cat = it["categoria"] or "General"
            u_med = it["unidad_medida"] or "Unidad"
            precio_v = formato_peso(it["precio"])
            costo_u = formato_peso(it["costo"])
            if tipo_p == "Servicio":
                st_b = "—"
                st_v = "—"
                st_tot = "— (Servicio)"
            else:
                st_b = formato_cant(it["stock_bodega"])
                st_v = formato_cant(it["stock_vitrina"])
                st_tot = formato_cant(it["stock"], u_med)
            est = it["estado"] or "Activo"

            tree_cat.insert("", "end", values=(
                p_id, cod, nom, tipo_p, cat, u_med, precio_v, costo_u, st_b, st_v, st_tot, est
            ))
        refrescar_kpis()

    var_filtro_cat.trace_add("write", lambda *a: cargar_tabla_catalogo())
    cb_tipo_cat.bind("<<ComboboxSelected>>", lambda e: cargar_tabla_catalogo())

    # Botones Catálogo
    def abrir_modal_articulo(articulo_existente=None, on_creado_callback=None, ubicacion_destino=None):
        modal = tk.Toplevel(ventana)
        es_edicion = articulo_existente is not None
        if es_edicion:
            tit_win = "Editar Artículo"
            tit_head = "✏️ Editar Artículo"
        elif ubicacion_destino == "BODEGA":
            tit_win = "Nuevo Artículo - Bodega"
            tit_head = "📦 Registrar Nuevo Artículo (Destino: Bodega)"
        elif ubicacion_destino == "VITRINA":
            tit_win = "Nuevo Artículo - Vitrina"
            tit_head = "🏬 Registrar Nuevo Artículo (Destino: Vitrina)"
        else:
            tit_win = "Nuevo Artículo en Catálogo"
            tit_head = "✨ Registrar Nuevo Artículo"

        modal.title(tit_win)
        t_mod = aplicar_tema(modal)
        calcular_geometria_segura(modal, 580, 680, 480, 480)
        modal.configure(bg=t_mod["bg_surface"])
        modal.transient(ventana)
        modal.grab_set()

        header_m = tk.Frame(modal, bg=t_mod["bg_surface"], padx=20, pady=10)
        header_m.pack(fill="x")
        tk.Label(header_m, text=tit_head,
                 font=("Segoe UI", 13, "bold"), bg=t_mod["bg_surface"], fg=t_mod["text_main"]).pack(anchor="w")

        # Barra inferior fija con botones (siempre visible independientemente del tamaño de pantalla o scroll)
        f_footer = tk.Frame(modal, bg=t_mod["bg_surface_alt"], bd=1, relief="ridge", padx=15, pady=10)
        f_footer.pack(fill="x", side="bottom")

        sc = ScrollableContainer(modal, bg=t_mod["bg_surface"])
        sc.pack(fill="both", expand=True, padx=15, pady=5)
        f_fields = tk.Frame(sc.content_frame, bg=t_mod["bg_surface"])
        f_fields.pack(fill="both", expand=True, padx=10, pady=5)

        row_idx = 0
        # Tipo
        tk.Label(f_fields, text="Tipo de Artículo:", font=("Segoe UI", 9, "bold"), bg=t_mod["bg_surface"], fg=t_mod["text_main"]).grid(row=row_idx, column=0, sticky="w", pady=4)
        var_tipo = tk.StringVar(value=articulo_existente["tipo_producto"] if es_edicion else "Fisico")
        cb_tipo = ttk.Combobox(f_fields, textvariable=var_tipo, values=["Fisico", "Servicio"], state="disabled" if es_edicion else "readonly", width=30)
        cb_tipo.grid(row=row_idx, column=1, sticky="w", pady=4, padx=5)

        row_idx += 1
        # Código
        tk.Label(f_fields, text="Código SKU:", font=("Segoe UI", 9, "bold"), bg=t_mod["bg_surface"], fg=t_mod["text_main"]).grid(row=row_idx, column=0, sticky="w", pady=4)
        cod_sug = articulo_existente["codigo"] if es_edicion else sugerir_proximo_codigo(var_tipo.get())
        e_cod = tk.Entry(f_fields, font=("Segoe UI", 10), width=32, bg=t_mod["input_bg"], fg=t_mod["input_fg"], insertbackground=t_mod["input_insert"])
        e_cod.insert(0, cod_sug)
        if es_edicion:
            e_cod.config(state="readonly")
        e_cod.grid(row=row_idx, column=1, sticky="w", pady=4, padx=5)

        row_idx += 1
        # Código de barras
        tk.Label(f_fields, text="Código de Barras (opcional):", font=("Segoe UI", 9), bg=t_mod["bg_surface"], fg=t_mod["text_main"]).grid(row=row_idx, column=0, sticky="w", pady=4)
        e_bar = tk.Entry(f_fields, font=("Segoe UI", 10), width=32, bg=t_mod["input_bg"], fg=t_mod["input_fg"], insertbackground=t_mod["input_insert"])
        if es_edicion and articulo_existente.get("codigo_barras"):
            e_bar.insert(0, str(articulo_existente.get("codigo_barras", "")))
        e_bar.grid(row=row_idx, column=1, sticky="w", pady=4, padx=5)

        row_idx += 1
        # Nombre
        tk.Label(f_fields, text="Nombre del Artículo:", font=("Segoe UI", 9, "bold"), bg=t_mod["bg_surface"], fg=t_mod["text_main"]).grid(row=row_idx, column=0, sticky="w", pady=4)
        e_nom = tk.Entry(f_fields, font=("Segoe UI", 10), width=32, bg=t_mod["input_bg"], fg=t_mod["input_fg"], insertbackground=t_mod["input_insert"])
        if es_edicion:
            e_nom.insert(0, str(articulo_existente.get("nombre", "")))
        e_nom.grid(row=row_idx, column=1, sticky="w", pady=4, padx=5)

        row_idx += 1
        # Categoría
        tk.Label(f_fields, text="Categoría:", font=("Segoe UI", 9), bg=t_mod["bg_surface"], fg=t_mod["text_main"]).grid(row=row_idx, column=0, sticky="w", pady=4)
        var_cat = tk.StringVar(value=articulo_existente.get("categoria", "General") if es_edicion else "General")
        e_cat = tk.Entry(f_fields, textvariable=var_cat, font=("Segoe UI", 10), width=32, bg=t_mod["input_bg"], fg=t_mod["input_fg"], insertbackground=t_mod["input_insert"])
        e_cat.grid(row=row_idx, column=1, sticky="w", pady=4, padx=5)

        row_idx += 1
        # Unidad de medida
        tk.Label(f_fields, text="Unidad de Medida Base:", font=("Segoe UI", 9), bg=t_mod["bg_surface"], fg=t_mod["text_main"]).grid(row=row_idx, column=0, sticky="w", pady=4)
        var_u = tk.StringVar(value=articulo_existente.get("unidad_medida", "Unidad") if es_edicion else "Unidad")
        cb_u = ttk.Combobox(f_fields, textvariable=var_u, values=TODAS_LAS_UNIDADES, state="readonly", width=30)
        cb_u.grid(row=row_idx, column=1, sticky="w", pady=4, padx=5)

        row_idx += 1
        # Precio de Venta
        tk.Label(f_fields, text="Precio de Venta:", font=("Segoe UI", 9, "bold"), bg=t_mod["bg_surface"], fg=t_mod["text_main"]).grid(row=row_idx, column=0, sticky="w", pady=4)
        e_precio = CurrencyEntry(f_fields, initial_value=articulo_existente.get("precio", 0.0) if es_edicion else 0.0,
                                 show_symbol=True, width=32, font=("Segoe UI", 10), bg=t_mod["input_bg"], fg=t_mod["input_fg"], insertbackground=t_mod["input_insert"])
        e_precio.grid(row=row_idx, column=1, sticky="w", pady=4, padx=5)

        row_idx += 1
        # Casilla «Precios varios» (dinámico en venta para servicios / recargas)
        var_precios_varios = tk.BooleanVar(value=bool(articulo_existente.get("precio_variable", False)) if es_edicion and articulo_existente else False)
        chk_precios_varios = tk.Checkbutton(
            f_fields,
            text="Precios varios (Permitir ingresar precio al vender en caja, ej: recargas)",
            variable=var_precios_varios,
            font=("Segoe UI", 9),
            bg=t_mod["bg_surface"],
            fg=t_mod["text_main"],
            activebackground=t_mod["bg_surface"],
            activeforeground=t_mod["text_main"],
            selectcolor=t_mod["input_bg"],
            cursor="hand2"
        )
        chk_precios_varios.grid(row=row_idx, column=1, sticky="w", pady=2, padx=5)

        row_idx += 1
        # Costo de adquisición
        tk.Label(f_fields, text="Costo de Adquisición / Directo:", font=("Segoe UI", 9, "bold"), bg=t_mod["bg_surface"], fg=t_mod["text_main"]).grid(row=row_idx, column=0, sticky="w", pady=4)
        e_costo = CurrencyEntry(f_fields, initial_value=articulo_existente.get("costo", 0.0) if es_edicion else 0.0,
                                show_symbol=True, width=32, font=("Segoe UI", 10), bg=t_mod["input_bg"], fg=t_mod["input_fg"], insertbackground=t_mod["input_insert"])
        e_costo.grid(row=row_idx, column=1, sticky="w", pady=4, padx=5)

        row_idx += 1
        # Proveedor
        tk.Label(f_fields, text="Proveedor Habitual:", font=("Segoe UI", 9), bg=t_mod["bg_surface"], fg=t_mod["text_main"]).grid(row=row_idx, column=0, sticky="w", pady=4)
        provs = obtener_proveedores_locales()
        lista_prov = ["Ninguno"] + [f"{p[0]} - {p[1]}" for p in provs]
        prov_actual = "Ninguno"
        if es_edicion and articulo_existente.get("proveedor_id"):
            for p in provs:
                if p[0] == articulo_existente["proveedor_id"]:
                    prov_actual = f"{p[0]} - {p[1]}"
                    break
        var_prov = tk.StringVar(value=prov_actual)
        cb_prov = ttk.Combobox(f_fields, textvariable=var_prov, values=lista_prov, state="readonly", width=25)
        cb_prov.grid(row=row_idx, column=1, sticky="w", pady=4, padx=5)
        crear_boton(f_fields, "+", lambda: modal_crear_proveedor_rapido(modal, cb_prov, var_prov),
                    tipo="secondary", tam_fuente=8, padx=6, pady=2).grid(row=row_idx, column=2, sticky="w", padx=2)

        row_idx += 1
        # Comisión acordada con el proveedor habitual
        lbl_comision = tk.Label(f_fields, text="Comisión Acordada (%):", font=("Segoe UI", 9, "bold"), bg=t_mod["bg_surface"], fg=t_mod["text_main"])
        lbl_comision.grid(row=row_idx, column=0, sticky="w", pady=4)

        com_init = float(articulo_existente.get("porcentaje_comision", 0.0) or 0.0) if es_edicion else 0.0
        var_comision = tk.StringVar(value=f"{com_init:g}" if com_init > 0 else "")
        f_comision_box = tk.Frame(f_fields, bg=t_mod["bg_surface"])
        f_comision_box.grid(row=row_idx, column=1, sticky="w", pady=4, padx=5)

        e_comision = tk.Entry(f_comision_box, textvariable=var_comision, font=("Segoe UI", 10), width=8, bg=t_mod["input_bg"], fg=t_mod["input_fg"], insertbackground=t_mod["input_insert"])
        e_comision.pack(side="left")
        lbl_pct = tk.Label(f_comision_box, text="%", font=("Segoe UI", 9, "bold"), bg=t_mod["bg_surface"], fg=t_mod["text_main"])
        lbl_pct.pack(side="left", padx=2)
        lbl_com_hint = tk.Label(f_comision_box, text="(Opcional, 0 a 100%. Ej: 10 para 10%)", font=("Segoe UI", 8, "italic"), bg=t_mod["bg_surface"], fg=t_mod["text_muted"])
        lbl_com_hint.pack(side="left", padx=(6, 0))

        # Campos específicos para productos físicos
        row_idx += 1
        lbl_sb = tk.Label(f_fields, text="Stock Inicial Bodega:", font=("Segoe UI", 9), bg=t_mod["bg_surface"], fg=t_mod["text_main"])
        lbl_sb.grid(row=row_idx, column=0, sticky="w", pady=4)
        e_sb = tk.Entry(f_fields, font=("Segoe UI", 10), width=32, bg=t_mod["input_bg"], fg=t_mod["input_fg"], insertbackground=t_mod["input_insert"])
        e_sb.insert(0, str(int(articulo_existente.get("stock_bodega", 0))) if es_edicion else "0")
        if es_edicion:
            e_sb.config(state="readonly")
        e_sb.grid(row=row_idx, column=1, sticky="w", pady=4, padx=5)

        row_idx += 1
        lbl_sv = tk.Label(f_fields, text="Stock Inicial Vitrina:", font=("Segoe UI", 9), bg=t_mod["bg_surface"], fg=t_mod["text_main"])
        lbl_sv.grid(row=row_idx, column=0, sticky="w", pady=4)
        e_sv = tk.Entry(f_fields, font=("Segoe UI", 10), width=32, bg=t_mod["input_bg"], fg=t_mod["input_fg"], insertbackground=t_mod["input_insert"])
        e_sv.insert(0, str(int(articulo_existente.get("stock_vitrina", 0))) if es_edicion else "0")
        if es_edicion:
            e_sv.config(state="readonly")
        e_sv.grid(row=row_idx, column=1, sticky="w", pady=4, padx=5)

        row_idx += 1
        lbl_smb = tk.Label(f_fields, text="Stock Mínimo Bodega:", font=("Segoe UI", 9), bg=t_mod["bg_surface"], fg=t_mod["text_main"])
        lbl_smb.grid(row=row_idx, column=0, sticky="w", pady=4)
        e_smb = tk.Entry(f_fields, font=("Segoe UI", 10), width=32, bg=t_mod["input_bg"], fg=t_mod["input_fg"], insertbackground=t_mod["input_insert"])
        e_smb.insert(0, str(int(articulo_existente.get("stock_minimo_bodega", 5))) if es_edicion else "5")
        e_smb.grid(row=row_idx, column=1, sticky="w", pady=4, padx=5)

        row_idx += 1
        lbl_smv = tk.Label(f_fields, text="Stock Mínimo Vitrina:", font=("Segoe UI", 9), bg=t_mod["bg_surface"], fg=t_mod["text_main"])
        lbl_smv.grid(row=row_idx, column=0, sticky="w", pady=4)
        e_smv = tk.Entry(f_fields, font=("Segoe UI", 10), width=32, bg=t_mod["input_bg"], fg=t_mod["input_fg"], insertbackground=t_mod["input_insert"])
        e_smv.insert(0, str(int(articulo_existente.get("stock_minimo_vitrina", 3))) if es_edicion else "3")
        e_smv.grid(row=row_idx, column=1, sticky="w", pady=4, padx=5)

        def actualizar_campos_segun_tipo(*a):
            t_sel = var_tipo.get()
            if t_sel == "Servicio":
                lbl_sb.grid_remove()
                e_sb.grid_remove()
                lbl_sv.grid_remove()
                e_sv.grid_remove()
                lbl_smb.grid_remove()
                e_smb.grid_remove()
                lbl_smv.grid_remove()
                e_smv.grid_remove()
            else:
                lbl_sb.grid()
                e_sb.grid()
                lbl_sv.grid()
                e_sv.grid()
                lbl_smb.grid()
                e_smb.grid()
                lbl_smv.grid()
                e_smv.grid()
            if not es_edicion:
                e_cod.delete(0, tk.END)
                e_cod.insert(0, sugerir_proximo_codigo(t_sel))

        def actualizar_campos_proveedor(*a):
            p_val = var_prov.get()
            tiene_prov = bool(p_val and p_val != "Ninguno")
            if tiene_prov:
                lbl_comision.grid()
                f_comision_box.grid()
            else:
                lbl_comision.grid_remove()
                f_comision_box.grid_remove()

        var_tipo.trace_add("write", actualizar_campos_segun_tipo)
        var_prov.trace_add("write", actualizar_campos_proveedor)
        actualizar_campos_segun_tipo()
        actualizar_campos_proveedor()

        def guardar_datos():
            cod = e_cod.get().strip()
            nom = e_nom.get().strip()
            t_art = var_tipo.get()
            p_venta = float(e_precio.get_value())
            c_adq = float(e_costo.get_value())
            c_bar = e_bar.get().strip()
            categoria = var_cat.get().strip() or "General"
            u_base = var_u.get().strip() or "Unidad"

            prov_id_val = None
            if var_prov.get() != "Ninguno":
                try:
                    prov_id_val = int(var_prov.get().split(" - ")[0])
                except Exception:
                    prov_id_val = None

            if not cod or not nom:
                messagebox.showwarning("Campos Requeridos", "El código y el nombre del artículo son obligatorios.", parent=modal)
                return

            # Validar comisión de proveedor
            porc_comision = 0.0
            if prov_id_val:
                c_str = var_comision.get().strip().replace("%", "")
                if c_str:
                    try:
                        porc_comision = float(c_str)
                    except ValueError:
                        messagebox.showwarning("Comisión Inválida", "El porcentaje de comisión debe ser un número válido entre 0 y 100.", parent=modal)
                        return
                    if porc_comision < 0 or porc_comision > 100:
                        messagebox.showwarning("Comisión Fuera de Rango", "El porcentaje de comisión debe estar entre 0% y 100%.", parent=modal)
                        return
            else:
                porc_comision = 0.0

            try:
                if es_edicion:
                    sm_b = float(e_smb.get().strip() or 5.0)
                    sm_v = float(e_smv.get().strip() or 3.0)
                    datos_up = {
                        "nombre": nom,
                        "precio": p_venta,
                        "costo": c_adq,
                        "categoria": categoria,
                        "codigo_barras": c_bar,
                        "unidad_medida": u_base,
                        "proveedor_id": prov_id_val,
                        "precio_variable": 1 if var_precios_varios.get() else 0,
                        "porcentaje_comision": porc_comision,
                        "stock_minimo_bodega": sm_b,
                        "stock_minimo_vitrina": sm_v,
                        "estado": articulo_existente.get("estado", "Activo")
                    }
                    actualizar_articulo(articulo_existente["id"], datos_up)
                    messagebox.showinfo("Éxito", f"Artículo '{nom}' actualizado correctamente.", parent=modal)
                else:
                    st_b = float(e_sb.get().strip() or 0.0) if t_art == "Fisico" else 0.0
                    st_v = float(e_sv.get().strip() or 0.0) if t_art == "Fisico" else 0.0
                    sm_b = float(e_smb.get().strip() or 5.0) if t_art == "Fisico" else 0.0
                    sm_v = float(e_smv.get().strip() or 3.0) if t_art == "Fisico" else 0.0

                    datos_ins = {
                        "codigo": cod,
                        "nombre": nom,
                        "tipo_producto": t_art,
                        "precio": p_venta,
                        "costo": c_adq,
                        "categoria": categoria,
                        "codigo_barras": c_bar,
                        "unidad_medida": u_base,
                        "proveedor_id": prov_id_val,
                        "precio_variable": 1 if var_precios_varios.get() else 0,
                        "porcentaje_comision": porc_comision,
                        "stock_bodega": st_b,
                        "stock_vitrina": st_v,
                        "stock_minimo_bodega": sm_b,
                        "stock_minimo_vitrina": sm_v,
                        "estado": "Activo"
                    }
                    creado = crear_articulo(datos_ins, usuario=usuario_actual)
                    messagebox.showinfo("Éxito", f"Artículo '{nom}' registrado exitosamente en el catálogo.", parent=modal)

                modal.destroy()
                try:
                    cargar_tabla_catalogo()
                except Exception:
                    pass
                try:
                    cargar_tabla_bodega()
                except Exception:
                    pass
                try:
                    cargar_tabla_vitrina()
                except Exception:
                    pass
                if not es_edicion and on_creado_callback:
                    on_creado_callback(creado or datos_ins)
            except Exception as ex:
                messagebox.showerror("Error", f"No se pudo guardar el artículo:\n{ex}", parent=modal)

        crear_boton(f_footer, "Cancelar", modal.destroy, tipo="secondary", tam_fuente=9).pack(side="right", padx=5)
        crear_boton(f_footer, "Guardar Cambios" if es_edicion else "Registrar Artículo", guardar_datos, tipo="success", icono="💾", tam_fuente=9).pack(side="right", padx=5)

    def editar_articulo_seleccionado():
        sel = tree_cat.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Seleccione una fila del catálogo para editar.", parent=ventana)
            return
        vals = tree_cat.item(sel[0])["values"]
        cod = str(vals[1])
        art = obtener_articulo_por_codigo(cod)
        if art:
            abrir_modal_articulo(art)

    def alternar_estado_seleccionado():
        sel = tree_cat.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Seleccione un artículo de la tabla.", parent=ventana)
            return
        vals = tree_cat.item(sel[0])["values"]
        p_id = vals[0]
        nom = vals[2]
        est_actual = vals[11]
        nuevo_est = "Inactivo" if est_actual == "Activo" else "Activo"
        if messagebox.askyesno("Confirmar", f"¿Desea cambiar el estado de '{nom}' a '{nuevo_est}'?", parent=ventana):
            cambiar_estado_articulo(p_id, nuevo_est)
            cargar_tabla_catalogo()

    crear_boton(bar_cat, "Actualizar", cargar_tabla_catalogo, tipo="secondary", icono="🔄", tam_fuente=9).pack(side="right", padx=4)
    crear_boton(bar_cat, "Activar/Inactivar", alternar_estado_seleccionado, tipo="secondary", icono="⚡", tam_fuente=9).pack(side="right", padx=4)
    crear_boton(bar_cat, "Editar", editar_articulo_seleccionado, tipo="primary", icono="✏️", tam_fuente=9).pack(side="right", padx=4)
    crear_boton(bar_cat, "Nuevo Artículo", lambda: abrir_modal_articulo(None), tipo="success", icono="➕", tam_fuente=9).pack(side="right", padx=4)

    # Tabla Catálogo
    frame_tree_cat = tk.Frame(tab_catalogo, bg=t["bg_surface"])
    frame_tree_cat.pack(fill="both", expand=True, padx=15, pady=(0, 15))

    cols_cat = ("ID", "Código SKU", "Nombre", "Tipo", "Categoría", "Unidad", "Precio Venta", "Costo Directo", "En Bodega", "En Vitrina", "Stock Total", "Estado")
    tree_cat = ttk.Treeview(frame_tree_cat, columns=cols_cat, show="headings", selectmode="browse")
    for c in cols_cat:
        tree_cat.heading(c, text=c)
    tree_cat.column("ID", width=45, anchor="center")
    tree_cat.column("Código SKU", width=95, anchor="center")
    tree_cat.column("Nombre", width=220, anchor="w")
    tree_cat.column("Tipo", width=80, anchor="center")
    tree_cat.column("Categoría", width=110, anchor="w")
    tree_cat.column("Unidad", width=75, anchor="center")
    tree_cat.column("Precio Venta", width=105, anchor="e")
    tree_cat.column("Costo Directo", width=105, anchor="e")
    tree_cat.column("En Bodega", width=85, anchor="center")
    tree_cat.column("En Vitrina", width=85, anchor="center")
    tree_cat.column("Stock Total", width=100, anchor="center")
    tree_cat.column("Estado", width=75, anchor="center")

    sc_cat_y = ttk.Scrollbar(frame_tree_cat, orient="vertical", command=tree_cat.yview)
    sc_cat_x = ttk.Scrollbar(frame_tree_cat, orient="horizontal", command=tree_cat.xview)
    tree_cat.configure(yscrollcommand=sc_cat_y.set, xscrollcommand=sc_cat_x.set)
    tree_cat.grid(row=0, column=0, sticky="nsew")
    sc_cat_y.grid(row=0, column=1, sticky="ns")
    sc_cat_x.grid(row=1, column=0, sticky="ew")
    frame_tree_cat.rowconfigure(0, weight=1)
    frame_tree_cat.columnconfigure(0, weight=1)

    # ==========================================================================
    # SECCIÓN 2: BODEGA (DEPÓSITO)
    # ==========================================================================
    bar_bod = tk.Frame(tab_bodega, bg=t["bg_surface"], padx=15, pady=10)
    bar_bod.pack(fill="x")

    tk.Label(bar_bod, text="Buscar en Bodega:", font=("Segoe UI", 10, "bold"), bg=t["bg_surface"], fg=t["text_main"]).pack(side="left", padx=(0, 5))
    var_filtro_bod = tk.StringVar()
    e_filtro_bod = tk.Entry(bar_bod, textvariable=var_filtro_bod, width=25, font=("Segoe UI", 10),
                            bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_insert"])
    e_filtro_bod.pack(side="left", padx=(0, 15))

    def cargar_tabla_bodega():
        for r in tree_bod.get_children():
            tree_bod.delete(r)
        items = obtener_existencias_bodega(filtro=var_filtro_bod.get().strip())
        for it in items:
            tree_bod.insert("", "end", values=(
                it["codigo"], it["nombre"], it["categoria"], it["unidad_medida"],
                formato_cant(it["stock_bodega"]),
                formato_cant(it["stock_minimo_bodega"]),
                formato_peso(it["costo"]),
                formato_peso(it["valor_total_bodega"]),
                it["alerta_bodega"]
            ))
        refrescar_kpis()

    var_filtro_bod.trace_add("write", lambda *a: cargar_tabla_bodega())

    def abrir_traslado_desde_bodega():
        sel = tree_bod.selection()
        cod_pre = None
        if sel:
            cod_pre = str(tree_bod.item(sel[0])["values"][0])
        notebook.select(tab_traslados)
        if cod_pre:
            cb_tras_prod.set(cod_pre)
            var_tras_origen.set("BODEGA")
            var_tras_destino.set("VITRINA")
            actualizar_info_traslado()

    def abrir_modal_ajuste(ubicacion_fija):
        modal = tk.Toplevel(ventana)
        modal.title(f"Ajuste de Conteo Físico - {ubicacion_fija}")
        t_mod = aplicar_tema(modal)
        calcular_geometria_segura(modal, 480, 420, 400, 340)
        modal.configure(bg=t_mod["bg_surface"])
        modal.transient(ventana)
        modal.grab_set()

        f_foot = tk.Frame(modal, bg=t_mod["bg_surface_alt"], bd=1, relief="ridge", padx=15, pady=8)
        f_foot.pack(fill="x", side="bottom")
        crear_boton(f_foot, "Cancelar", modal.destroy, tipo="secondary", tam_fuente=9).pack(side="right", padx=5)
        crear_boton(f_foot, "Aplicar Ajuste", lambda: confirmar_ajuste(), tipo="warning", icono="⚖️", tam_fuente=9).pack(side="right", padx=5)

        f_aj = tk.Frame(modal, bg=t_mod["bg_surface"], padx=20, pady=15)
        f_aj.pack(fill="both", expand=True)

        tk.Label(f_aj, text=f"⚖️ Conteo Físico en {ubicacion_fija}", font=("Segoe UI", 13, "bold"),
                 bg=t_mod["bg_surface"], fg=t_mod["text_main"]).pack(anchor="w", pady=(0, 10))

        tk.Label(f_aj, text="Seleccione Artículo Físico:", font=("Segoe UI", 9, "bold"),
                 bg=t_mod["bg_surface"], fg=t_mod["text_main"]).pack(anchor="w", pady=(5, 2))
        articulos = obtener_catalogo(tipo="Fisico", solo_activos=True)
        lista_arts = [f"{a['codigo']} - {a['nombre']}" for a in articulos]
        var_art_aj = tk.StringVar()
        cb_art_aj = ttk.Combobox(f_aj, textvariable=var_art_aj, values=lista_arts, state="readonly", width=40)
        cb_art_aj.pack(fill="x", pady=(0, 10))

        lbl_saldo_actual = tk.Label(f_aj, text="Stock registrado en sistema: —", font=("Segoe UI", 10),
                                    bg=t_mod["bg_surface"], fg=t_mod["text_muted"])
        lbl_saldo_actual.pack(anchor="w", pady=(0, 10))

        tk.Label(f_aj, text="Cantidad Real Contada (Física):", font=("Segoe UI", 9, "bold"),
                 bg=t_mod["bg_surface"], fg=t_mod["text_main"]).pack(anchor="w", pady=(5, 2))
        e_conteo = tk.Entry(f_aj, font=("Segoe UI", 11), bg=t_mod["input_bg"], fg=t_mod["input_fg"], insertbackground=t_mod["input_insert"])
        e_conteo.pack(fill="x", pady=(0, 10))

        tk.Label(f_aj, text="Motivo / Observación del Ajuste:", font=("Segoe UI", 9),
                 bg=t_mod["bg_surface"], fg=t_mod["text_main"]).pack(anchor="w", pady=(5, 2))
        e_motivo = tk.Entry(f_aj, font=("Segoe UI", 10), bg=t_mod["input_bg"], fg=t_mod["input_fg"], insertbackground=t_mod["input_insert"])
        e_motivo.pack(fill="x", pady=(0, 15))

        def on_art_aj_sel(e=None):
            sel_txt = var_art_aj.get()
            if sel_txt:
                cod = sel_txt.split(" - ")[0]
                art = obtener_articulo_por_codigo(cod)
                if art:
                    st_val = art["stock_bodega"] if ubicacion_fija == "BODEGA" else art["stock_vitrina"]
                    lbl_saldo_actual.config(text=f"Stock registrado en {ubicacion_fija}: {formato_cant(st_val, art['unidad_medida'])}")
                    e_conteo.delete(0, tk.END)
                    e_conteo.insert(0, str(int(st_val) if st_val.is_integer() else st_val))

        cb_art_aj.bind("<<ComboboxSelected>>", on_art_aj_sel)

        def confirmar_ajuste():
            sel_txt = var_art_aj.get()
            if not sel_txt:
                messagebox.showwarning("Aviso", "Seleccione un artículo.", parent=modal)
                return
            cod = sel_txt.split(" - ")[0]
            val_txt = e_conteo.get().strip()
            mot = e_motivo.get().strip()
            try:
                c_flt = float(val_txt)
                res = registrar_ajuste_inventario(cod, ubicacion_fija, c_flt, usuario=usuario_actual, motivo=mot)
                if "mensaje" in res:
                    messagebox.showinfo("Sin Cambios", res["mensaje"], parent=modal)
                else:
                    messagebox.showinfo("Éxito", f"Ajuste aplicado correctamente.\nNuevo stock en {ubicacion_fija}: {res['stock_nuevo']}", parent=modal)
                modal.destroy()
                cargar_tabla_bodega()
                cargar_tabla_vitrina()
                cargar_tabla_kardex()
            except Exception as ex:
                messagebox.showerror("Error", f"Fallo al aplicar ajuste:\n{ex}", parent=modal)

    crear_boton(bar_bod, "Actualizar", cargar_tabla_bodega, tipo="secondary", icono="🔄", tam_fuente=9).pack(side="right", padx=4)
    crear_boton(bar_bod, "Ajuste Conteo Físico", lambda: abrir_modal_ajuste("BODEGA"), tipo="warning", icono="⚖️", tam_fuente=9).pack(side="right", padx=4)
    crear_boton(bar_bod, "Trasladar a Vitrina", abrir_traslado_desde_bodega, tipo="secondary", icono="🚚", tam_fuente=9).pack(side="right", padx=4)
    crear_boton(bar_bod, "Entrada / Compra", lambda: abrir_modal_nueva_compra(), tipo="success", icono="📥", tam_fuente=9).pack(side="right", padx=4)
    crear_boton(bar_bod, "Nuevo Artículo en Bodega", lambda: abrir_modal_articulo(ubicacion_destino="BODEGA"), tipo="primary", icono="➕", tam_fuente=9).pack(side="right", padx=4)

    frame_tree_bod = tk.Frame(tab_bodega, bg=t["bg_surface"])
    frame_tree_bod.pack(fill="both", expand=True, padx=15, pady=(0, 15))

    cols_bod = ("Código SKU", "Artículo", "Categoría", "Unidad", "Stock en Bodega", "Stock Mínimo", "Costo Unitario", "Valor Total a Costo", "Estado Alerta")
    tree_bod = ttk.Treeview(frame_tree_bod, columns=cols_bod, show="headings", selectmode="browse")
    for c in cols_bod:
        tree_bod.heading(c, text=c)
    tree_bod.column("Código SKU", width=95, anchor="center")
    tree_bod.column("Artículo", width=240, anchor="w")
    tree_bod.column("Categoría", width=120, anchor="w")
    tree_bod.column("Unidad", width=80, anchor="center")
    tree_bod.column("Stock en Bodega", width=110, anchor="center")
    tree_bod.column("Stock Mínimo", width=100, anchor="center")
    tree_bod.column("Costo Unitario", width=110, anchor="e")
    tree_bod.column("Valor Total a Costo", width=130, anchor="e")
    tree_bod.column("Estado Alerta", width=140, anchor="center")

    sc_bod_y = ttk.Scrollbar(frame_tree_bod, orient="vertical", command=tree_bod.yview)
    tree_bod.configure(yscrollcommand=sc_bod_y.set)
    tree_bod.grid(row=0, column=0, sticky="nsew")
    sc_bod_y.grid(row=0, column=1, sticky="ns")
    frame_tree_bod.rowconfigure(0, weight=1)
    frame_tree_bod.columnconfigure(0, weight=1)

    # ==========================================================================
    # SECCIÓN 3: VITRINA (PUNTO DE VENTA)
    # ==========================================================================
    bar_vit = tk.Frame(tab_vitrina, bg=t["bg_surface"], padx=15, pady=10)
    bar_vit.pack(fill="x")

    tk.Label(bar_vit, text="Buscar en Vitrina:", font=("Segoe UI", 10, "bold"), bg=t["bg_surface"], fg=t["text_main"]).pack(side="left", padx=(0, 5))
    var_filtro_vit = tk.StringVar()
    e_filtro_vit = tk.Entry(bar_vit, textvariable=var_filtro_vit, width=25, font=("Segoe UI", 10),
                            bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_insert"])
    e_filtro_vit.pack(side="left", padx=(0, 15))

    def cargar_tabla_vitrina():
        for r in tree_vit.get_children():
            tree_vit.delete(r)
        items = obtener_existencias_vitrina(filtro=var_filtro_vit.get().strip())
        for it in items:
            tree_vit.insert("", "end", values=(
                it["codigo"], it["nombre"], it["categoria"], it["unidad_medida"],
                formato_cant(it["stock_vitrina"]),
                formato_cant(it["stock_minimo_vitrina"]),
                formato_peso(it["precio"]),
                formato_peso(it["valor_venta_vitrina"]),
                formato_cant(it["stock_bodega"]),
                it["alerta_vitrina"]
            ))
        refrescar_kpis()

    var_filtro_vit.trace_add("write", lambda *a: cargar_tabla_vitrina())

    def solicitar_reposicion_vitrina():
        sel = tree_vit.selection()
        cod_pre = None
        if sel:
            cod_pre = str(tree_vit.item(sel[0])["values"][0])
        notebook.select(tab_traslados)
        if cod_pre:
            cb_tras_prod.set(cod_pre)
            var_tras_origen.set("BODEGA")
            var_tras_destino.set("VITRINA")
            actualizar_info_traslado()

    crear_boton(bar_vit, "Actualizar", cargar_tabla_vitrina, tipo="secondary", icono="🔄", tam_fuente=9).pack(side="right", padx=4)
    crear_boton(bar_vit, "Ajuste Conteo Vitrina", lambda: abrir_modal_ajuste("VITRINA"), tipo="warning", icono="⚖️", tam_fuente=9).pack(side="right", padx=4)
    crear_boton(bar_vit, "Solicitar Reposición (Bodega -> Vitrina)", solicitar_reposicion_vitrina, tipo="primary", icono="📥", tam_fuente=9).pack(side="right", padx=4)

    frame_tree_vit = tk.Frame(tab_vitrina, bg=t["bg_surface"])
    frame_tree_vit.pack(fill="both", expand=True, padx=15, pady=(0, 15))

    cols_vit = ("Código SKU", "Artículo", "Categoría", "Unidad", "Stock en Vitrina", "Stock Mínimo", "Precio Venta", "Valor Total Venta", "Disponible en Bodega", "Estado Disponibilidad")
    tree_vit = ttk.Treeview(frame_tree_vit, columns=cols_vit, show="headings", selectmode="browse")
    for c in cols_vit:
        tree_vit.heading(c, text=c)
    tree_vit.column("Código SKU", width=95, anchor="center")
    tree_vit.column("Artículo", width=220, anchor="w")
    tree_vit.column("Categoría", width=110, anchor="w")
    tree_vit.column("Unidad", width=75, anchor="center")
    tree_vit.column("Stock en Vitrina", width=110, anchor="center")
    tree_vit.column("Stock Mínimo", width=100, anchor="center")
    tree_vit.column("Precio Venta", width=105, anchor="e")
    tree_vit.column("Valor Total Venta", width=120, anchor="e")
    tree_vit.column("Disponible en Bodega", width=130, anchor="center")
    tree_vit.column("Estado Disponibilidad", width=150, anchor="center")

    sc_vit_y = ttk.Scrollbar(frame_tree_vit, orient="vertical", command=tree_vit.yview)
    tree_vit.configure(yscrollcommand=sc_vit_y.set)
    tree_vit.grid(row=0, column=0, sticky="nsew")
    sc_vit_y.grid(row=0, column=1, sticky="ns")
    frame_tree_vit.rowconfigure(0, weight=1)
    frame_tree_vit.columnconfigure(0, weight=1)

    # ==========================================================================
    # SECCIÓN 4: TRASLADOS ENTRE UBICACIONES (PROCESO ATÓMICO)
    # ==========================================================================
    f_tras_main = tk.Frame(tab_traslados, bg=t["bg_surface"], padx=20, pady=15)
    f_tras_main.pack(fill="both", expand=True)

    # Panel Izquierdo: Formulario de traslado
    f_tras_form = tk.LabelFrame(f_tras_main, text=" 🚚 Nuevo Traslado de Mercancía ", font=("Segoe UI", 11, "bold"),
                                bg=t["bg_surface"], fg=t["text_main"], padx=15, pady=15)
    f_tras_form.pack(side="left", fill="y", padx=(0, 15))

    tk.Label(f_tras_form, text="Artículo a Trasladar:", font=("Segoe UI", 9, "bold"),
             bg=t["bg_surface"], fg=t["text_main"]).pack(anchor="w", pady=(0, 2))
    var_tras_prod = tk.StringVar()
    cb_tras_prod = ttk.Combobox(f_tras_form, textvariable=var_tras_prod, state="readonly", width=34)
    cb_tras_prod.pack(fill="x", pady=(0, 10))

    # Origen y Destino
    f_orig_dest = tk.Frame(f_tras_form, bg=t["bg_surface"])
    f_orig_dest.pack(fill="x", pady=(0, 10))

    f_or = tk.Frame(f_orig_dest, bg=t["bg_surface"])
    f_or.pack(side="left", fill="x", expand=True, padx=(0, 5))
    tk.Label(f_or, text="Ubicación Origen:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_main"]).pack(anchor="w")
    var_tras_origen = tk.StringVar(value="BODEGA")
    cb_tras_origen = ttk.Combobox(f_or, textvariable=var_tras_origen, values=["BODEGA", "VITRINA"], state="readonly", width=14)
    cb_tras_origen.pack(fill="x", pady=2)

    f_de = tk.Frame(f_orig_dest, bg=t["bg_surface"])
    f_de.pack(side="right", fill="x", expand=True, padx=(5, 0))
    tk.Label(f_de, text="Ubicación Destino:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_main"]).pack(anchor="w")
    var_tras_destino = tk.StringVar(value="VITRINA")
    cb_tras_destino = ttk.Combobox(f_de, textvariable=var_tras_destino, values=["VITRINA", "BODEGA"], state="readonly", width=14)
    cb_tras_destino.pack(fill="x", pady=2)

    # Indicador dinámico de existencias
    f_box_saldos = tk.Frame(f_tras_form, bg=t["bg_surface_alt"], bd=1, relief="solid", padx=10, pady=10)
    f_box_saldos.pack(fill="x", pady=(0, 12))

    lbl_saldo_origen = tk.Label(f_box_saldos, text="Disponible en Origen: 0 und", font=("Segoe UI", 9, "bold"),
                                bg=t["bg_surface_alt"], fg="#3B82F6")
    lbl_saldo_origen.pack(anchor="w")
    lbl_saldo_destino = tk.Label(f_box_saldos, text="Disponible en Destino: 0 und", font=("Segoe UI", 9),
                                 bg=t["bg_surface_alt"], fg=t["text_muted"])
    lbl_saldo_destino.pack(anchor="w")
    lbl_proyeccion = tk.Label(f_box_saldos, text="Proyección post-traslado: —", font=("Segoe UI", 9, "italic"),
                              bg=t["bg_surface_alt"], fg="#10B981")
    lbl_proyeccion.pack(anchor="w", pady=(4, 0))

    tk.Label(f_tras_form, text="Cantidad a Trasladar:", font=("Segoe UI", 9, "bold"),
             bg=t["bg_surface"], fg=t["text_main"]).pack(anchor="w", pady=(0, 2))
    e_tras_cant = tk.Entry(f_tras_form, font=("Segoe UI", 11), bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_insert"])
    e_tras_cant.pack(fill="x", pady=(0, 10))

    tk.Label(f_tras_form, text="Observaciones / Motivo:", font=("Segoe UI", 9),
             bg=t["bg_surface"], fg=t["text_main"]).pack(anchor="w", pady=(0, 2))
    e_tras_obs = tk.Entry(f_tras_form, font=("Segoe UI", 10), bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_insert"])
    e_tras_obs.pack(fill="x", pady=(0, 15))

    def actualizar_info_traslado(*a):
        sel_txt = var_tras_prod.get()
        if not sel_txt:
            return
        cod = sel_txt.split(" - ")[0]
        art = obtener_articulo_por_codigo(cod)
        if not art:
            return
        orig = var_tras_origen.get()
        dest = var_tras_destino.get()
        u = art["unidad_medida"] or "Unidad"

        st_or = art["stock_bodega"] if orig == "BODEGA" else art["stock_vitrina"]
        st_de = art["stock_vitrina"] if dest == "VITRINA" else art["stock_bodega"]

        lbl_saldo_origen.config(text=f"Disponible en {orig}: {formato_cant(st_or, u)}")
        lbl_saldo_destino.config(text=f"Disponible en {dest}: {formato_cant(st_de, u)}")

        # Calcular proyección
        cant_txt = e_tras_cant.get().strip()
        try:
            c_flt = float(cant_txt)
            if c_flt > 0:
                p_or = st_or - c_flt
                p_de = st_de + c_flt
                lbl_proyeccion.config(text=f"Proyección: {orig} ({p_or:g}) -> {dest} ({p_de:g})")
                lbl_proyeccion.config(fg="#10B981" if p_or >= 0 else "#EF4444")
            else:
                lbl_proyeccion.config(text="Proyección post-traslado: —", fg=t["text_muted"])
        except Exception:
            lbl_proyeccion.config(text="Proyección post-traslado: —", fg=t["text_muted"])

    cb_tras_prod.bind("<<ComboboxSelected>>", actualizar_info_traslado)
    cb_tras_origen.bind("<<ComboboxSelected>>", actualizar_info_traslado)
    cb_tras_destino.bind("<<ComboboxSelected>>", actualizar_info_traslado)
    e_tras_cant.bind("<KeyRelease>", actualizar_info_traslado)

    def ejecutar_traslado_click():
        sel_txt = var_tras_prod.get()
        if not sel_txt:
            messagebox.showwarning("Aviso", "Seleccione un producto a trasladar.", parent=ventana)
            return
        cod = sel_txt.split(" - ")[0]
        orig = var_tras_origen.get()
        dest = var_tras_destino.get()
        cant_str = e_tras_cant.get().strip()
        obs = e_tras_obs.get().strip()

        try:
            res = ejecutar_traslado(cod, orig, dest, cant_str, usuario=usuario_actual, observaciones=obs)
            messagebox.showinfo(
                "Traslado Completado",
                f"✅ Traslado {res['numero_traslado']} ejecutado exitosamente.\n\n"
                f"Artículo: {res['producto']}\n"
                f"Movimiento: {res['cantidad']:g} und ({orig} -> {dest})\n"
                f"Saldo final en Bodega: {res['stock_bodega']:g}\n"
                f"Saldo final en Vitrina: {res['stock_vitrina']:g}",
                parent=ventana
            )
            e_tras_cant.delete(0, tk.END)
            e_tras_obs.delete(0, tk.END)
            actualizar_info_traslado()
            cargar_tabla_bodega()
            cargar_tabla_vitrina()
            cargar_tabla_traslados()
            cargar_tabla_kardex()
        except Exception as ex:
            messagebox.showerror("Error en Traslado", str(ex), parent=ventana)

    crear_boton(f_tras_form, "Ejecutar Traslado Atómico", ejecutar_traslado_click,
                tipo="success", icono="🚀", tam_fuente=10).pack(fill="x", ipady=4)

    # Panel Derecho: Historial de Traslados
    f_tras_hist = tk.LabelFrame(f_tras_main, text=" 📜 Historial de Traslados Registrados ", font=("Segoe UI", 11, "bold"),
                                bg=t["bg_surface"], fg=t["text_main"], padx=10, pady=10)
    f_tras_hist.pack(side="right", fill="both", expand=True)

    cols_th = ("Nº Traslado", "Fecha", "Hora", "SKU", "Artículo", "Origen", "Destino", "Cantidad", "Usuario", "Estado")
    tree_th = ttk.Treeview(f_tras_hist, columns=cols_th, show="headings", selectmode="browse")
    for c in cols_th:
        tree_th.heading(c, text=c)
    tree_th.column("Nº Traslado", width=90, anchor="center")
    tree_th.column("Fecha", width=85, anchor="center")
    tree_th.column("Hora", width=75, anchor="center")
    tree_th.column("SKU", width=75, anchor="center")
    tree_th.column("Artículo", width=180, anchor="w")
    tree_th.column("Origen", width=75, anchor="center")
    tree_th.column("Destino", width=75, anchor="center")
    tree_th.column("Cantidad", width=75, anchor="center")
    tree_th.column("Usuario", width=95, anchor="center")
    tree_th.column("Estado", width=85, anchor="center")

    sc_th_y = ttk.Scrollbar(f_tras_hist, orient="vertical", command=tree_th.yview)
    tree_th.configure(yscrollcommand=sc_th_y.set)
    tree_th.pack(side="left", fill="both", expand=True)
    sc_th_y.pack(side="right", fill="y")

    def cargar_tabla_traslados():
        for r in tree_th.get_children():
            tree_th.delete(r)
        lista = obtener_historial_traslados(limit=100)
        for t_item in lista:
            tree_th.insert("", "end", values=(
                t_item["numero_traslado"], t_item["fecha"], t_item["hora"],
                t_item["codigo_producto"], t_item["nombre_producto"],
                t_item["ubicacion_origen"], t_item["ubicacion_destino"],
                formato_cant(t_item["cantidad"]), t_item["usuario"], t_item["estado"]
            ))
        # Actualizar combo de productos de traslado
        prods_f = obtener_catalogo(tipo="Fisico", solo_activos=True)
        cb_tras_prod["values"] = [f"{p['codigo']} - {p['nombre']}" for p in prods_f]

    # ==========================================================================
    # SECCIÓN 5: ENTRADAS Y COMPRAS DE MERCANCÍA (CONVERSIÓN DE PRESENTACIONES)
    # ==========================================================================
    bar_cmp = tk.Frame(tab_compras, bg=t["bg_surface"], padx=15, pady=10)
    bar_cmp.pack(fill="x")

    tk.Label(bar_cmp, text="📥 Recepción de Compras de Mercancía a Proveedores", font=("Segoe UI", 12, "bold"),
             bg=t["bg_surface"], fg=t["text_main"]).pack(side="left")

    def abrir_modal_nueva_compra():
        modal = tk.Toplevel(ventana)
        modal.title("Registrar Entrada / Compra de Mercancía")
        t_mod = aplicar_tema(modal)
        calcular_geometria_segura(modal, 780, 640, 680, 500)
        modal.configure(bg=t_mod["bg_surface"])
        modal.transient(ventana)
        modal.grab_set()

        f_top = tk.Frame(modal, bg=t_mod["bg_surface"], padx=20, pady=10)
        f_top.pack(fill="x")

        # Proveedor con botón de creación rápida
        tk.Label(f_top, text="Proveedor:", font=("Segoe UI", 9, "bold"), bg=t_mod["bg_surface"], fg=t_mod["text_main"]).grid(row=0, column=0, sticky="w", pady=4)
        f_prov_box = tk.Frame(f_top, bg=t_mod["bg_surface"])
        f_prov_box.grid(row=0, column=1, sticky="w", pady=4, padx=5)

        p_list = obtener_proveedores_locales()
        var_cp_prov = tk.StringVar(value=f"{p_list[0][0]} - {p_list[0][1]}" if p_list else "Ninguno")
        cb_cp_prov = ttk.Combobox(f_prov_box, textvariable=var_cp_prov, values=[f"{p[0]} - {p[1]}" for p in p_list] or ["Ninguno"], state="readonly", width=22)
        cb_cp_prov.pack(side="left")

        def crear_prov_compra():
            modal_crear_proveedor_rapido(modal, combo_widget=cb_cp_prov, var_widget=var_cp_prov)

        crear_boton(f_prov_box, "+", crear_prov_compra, tipo="success", icono="➕", tam_fuente=8, padx=6, pady=2, tooltip="Crear nuevo proveedor").pack(side="left", padx=(4, 0))

        # Documento Factura
        tk.Label(f_top, text="Nº Factura / Remisión:", font=("Segoe UI", 9, "bold"), bg=t_mod["bg_surface"], fg=t_mod["text_main"]).grid(row=0, column=2, sticky="w", pady=4, padx=(15, 0))
        e_cp_fac = tk.Entry(f_top, font=("Segoe UI", 10), width=20, bg=t_mod["input_bg"], fg=t_mod["input_fg"], insertbackground=t_mod["input_insert"])
        e_cp_fac.grid(row=0, column=3, sticky="w", pady=4, padx=5)

        # Ubicación receptora
        tk.Label(f_top, text="Ingresar a:", font=("Segoe UI", 9, "bold"), bg=t_mod["bg_surface"], fg=t_mod["text_main"]).grid(row=1, column=0, sticky="w", pady=4)
        var_cp_dest = tk.StringVar(value="BODEGA")
        cb_cp_dest = ttk.Combobox(f_top, textvariable=var_cp_dest, values=["BODEGA", "VITRINA"], state="readonly", width=22)
        cb_cp_dest.grid(row=1, column=1, sticky="w", pady=4, padx=5)

        # Panel de ingreso de ítems
        f_add_item = tk.LabelFrame(modal, text=" 📦 Agregar Artículo a la Entrada ", font=("Segoe UI", 10, "bold"),
                                   bg=t_mod["bg_surface"], fg=t_mod["text_main"], padx=15, pady=8)
        f_add_item.pack(fill="x", padx=20, pady=5)

        # Fila 1: Artículo, botón Nuevo y Presentación
        f_ai_r1 = tk.Frame(f_add_item, bg=t_mod["bg_surface"])
        f_ai_r1.pack(fill="x", pady=2)

        tk.Label(f_ai_r1, text="Artículo:", font=("Segoe UI", 9, "bold"), bg=t_mod["bg_surface"], fg=t_mod["text_main"]).pack(side="left", padx=(0, 5))
        var_ai_prod = tk.StringVar()
        cb_ai_prod = ttk.Combobox(f_ai_r1, textvariable=var_ai_prod, state="readonly", width=30)
        cb_ai_prod.pack(side="left", padx=(0, 5))

        def crear_articulo_desde_compra():
            def on_creado(nuevo_art):
                recargar_combo_articulos(nuevo_art.get("codigo"))
            abrir_modal_articulo(articulo_existente=None, on_creado_callback=on_creado, ubicacion_destino=var_cp_dest.get())

        crear_boton(f_ai_r1, "Nuevo", crear_articulo_desde_compra, tipo="success", icono="➕", tam_fuente=8, padx=6, pady=2, tooltip="Crear nuevo artículo en catálogo").pack(side="left", padx=(0, 15))

        tk.Label(f_ai_r1, text="Presentación:", font=("Segoe UI", 9), bg=t_mod["bg_surface"], fg=t_mod["text_main"]).pack(side="left", padx=(0, 5))
        var_ai_unid = tk.StringVar(value="Unidad")
        cb_ai_unid = ttk.Combobox(f_ai_r1, textvariable=var_ai_unid, values=["Caja", "Paquete", "Docena", "Unidad", "Kilogramo", "Litro", "Metro"], state="readonly", width=12)
        cb_ai_unid.pack(side="left")

        # Fila 2: Factor, Cantidad y Costo
        f_ai_r2 = tk.Frame(f_add_item, bg=t_mod["bg_surface"])
        f_ai_r2.pack(fill="x", pady=4)

        tk.Label(f_ai_r2, text="Contenido por Empaque (Factor):", font=("Segoe UI", 9), bg=t_mod["bg_surface"], fg=t_mod["text_main"]).pack(side="left", padx=(0, 4))
        e_ai_factor = tk.Entry(f_ai_r2, width=7, font=("Segoe UI", 10), bg=t_mod["input_bg"], fg=t_mod["input_fg"], insertbackground=t_mod["input_insert"])
        e_ai_factor.insert(0, "1")
        e_ai_factor.pack(side="left", padx=(0, 12))

        tk.Label(f_ai_r2, text="Cant. Empaques:", font=("Segoe UI", 9), bg=t_mod["bg_surface"], fg=t_mod["text_main"]).pack(side="left", padx=(0, 4))
        e_ai_cant = tk.Entry(f_ai_r2, width=7, font=("Segoe UI", 10), bg=t_mod["input_bg"], fg=t_mod["input_fg"], insertbackground=t_mod["input_insert"])
        e_ai_cant.insert(0, "1")
        e_ai_cant.pack(side="left", padx=(0, 12))

        tk.Label(f_ai_r2, text="Costo por Empaque:", font=("Segoe UI", 9), bg=t_mod["bg_surface"], fg=t_mod["text_main"]).pack(side="left", padx=(0, 4))
        e_ai_costo = CurrencyEntry(f_ai_r2, initial_value=0, show_symbol=True, width=15, font=("Segoe UI", 10),
                                   bg=t_mod["input_bg"], fg=t_mod["input_fg"], insertbackground=t_mod["input_insert"])
        e_ai_costo.pack(side="left")

        # Fila 3: Resultado de cálculo y botón prominente de AGREGAR A LA ENTRADA
        f_ai_r3 = tk.Frame(f_add_item, bg=t_mod["bg_surface"])
        f_ai_r3.pack(fill="x", pady=(4, 2))

        lbl_ai_res = tk.Label(f_ai_r3, text="Resultado: 1 unidades que ingresan a costo de $0 c/u", font=("Segoe UI", 9, "bold"),
                              bg=t_mod["bg_surface"], fg="#3B82F6")
        lbl_ai_res.pack(side="left", anchor="w")

        def actualizar_calculo_item(*a):
            try:
                fac = float(e_ai_factor.get().strip() or 1.0)
                cant = float(e_ai_cant.get().strip() or 1.0)
                cost_emp = float(e_ai_costo.get_value())
                tot_u = fac * cant
                c_u = cost_emp / fac if fac > 0 else cost_emp
                lbl_ai_res.config(text=f"Resultado: {tot_u:g} unidades que ingresan a costo de {formato_peso(c_u)} c/u (Subtotal: {formato_peso(cant * cost_emp)})")
            except Exception:
                lbl_ai_res.config(text="Resultado: —")

        def on_producto_seleccionado(event=None):
            sel_art = var_ai_prod.get()
            if not sel_art:
                return
            cod = sel_art.split(" - ")[0].strip()
            art = obtener_articulo_por_codigo(cod)
            if art:
                if float(e_ai_costo.get_value()) == 0.0 and art.get("costo"):
                    e_ai_costo.set_value(art["costo"])
                u = art.get("unidad_medida", "Unidad")
                if u in cb_ai_unid["values"]:
                    var_ai_unid.set(u)
                    if u in ("Unidad", "Kilogramo", "Litro", "Metro"):
                        e_ai_factor.delete(0, tk.END)
                        e_ai_factor.insert(0, "1")
            actualizar_calculo_item()

        def recargar_combo_articulos(codigo_sel=None):
            prods = obtener_catalogo(tipo="Fisico", solo_activos=True)
            vals = [f"{p['codigo']} - {p['nombre']}" for p in prods]
            cb_ai_prod["values"] = vals
            if codigo_sel:
                for v in vals:
                    if v.startswith(f"{codigo_sel} -"):
                        var_ai_prod.set(v)
                        on_producto_seleccionado()
                        break
            elif vals and (not var_ai_prod.get() or var_ai_prod.get() not in vals):
                var_ai_prod.set(vals[0])
                on_producto_seleccionado()
            elif not vals:
                var_ai_prod.set("")
                lbl_ai_res.config(text="💡 No hay artículos en catálogo. Presione '➕ Nuevo' para registrar el primero.")
            actualizar_calculo_item()

        cb_ai_prod.bind("<<ComboboxSelected>>", on_producto_seleccionado)
        e_ai_factor.bind("<KeyRelease>", actualizar_calculo_item)
        e_ai_cant.bind("<KeyRelease>", actualizar_calculo_item)
        e_ai_costo.bind("<KeyRelease>", actualizar_calculo_item)
        recargar_combo_articulos()

        items_en_compra = []

        # Barra inferior fija con total y botones de confirmación
        f_foot_cp = tk.Frame(modal, bg=t_mod["bg_surface_alt"], bd=1, relief="ridge", padx=15, pady=8)
        f_foot_cp.pack(fill="x", side="bottom")

        lbl_total_compra = tk.Label(modal, text="TOTAL ENTRADA: $0 COP", font=("Segoe UI", 12, "bold"),
                                    bg=t_mod["bg_surface"], fg="#10B981")
        lbl_total_compra.pack(side="bottom", anchor="e", padx=25, pady=5)

        # Tabla temporal de ítems a recibir (ocupa el espacio restante)
        f_grid_items = tk.Frame(modal, bg=t_mod["bg_surface"], padx=20, pady=5)
        f_grid_items.pack(fill="both", expand=True)

        cols_ci = ("Código", "Artículo", "Empaque", "Factor", "Cant. Empaques", "Unidades Base", "Costo Empaque", "Costo Unitario", "Subtotal")
        tree_ci = ttk.Treeview(f_grid_items, columns=cols_ci, show="headings", selectmode="browse")
        for c in cols_ci:
            tree_ci.heading(c, text=c)
        tree_ci.column("Código", width=75, anchor="center")
        tree_ci.column("Artículo", width=180, anchor="w")
        tree_ci.column("Empaque", width=75, anchor="center")
        tree_ci.column("Factor", width=60, anchor="center")
        tree_ci.column("Cant. Empaques", width=95, anchor="center")
        tree_ci.column("Unidades Base", width=95, anchor="center")
        tree_ci.column("Costo Empaque", width=105, anchor="e")
        tree_ci.column("Costo Unitario", width=105, anchor="e")
        tree_ci.column("Subtotal", width=110, anchor="e")

        sc_ci_y = ttk.Scrollbar(f_grid_items, orient="vertical", command=tree_ci.yview)
        tree_ci.configure(yscrollcommand=sc_ci_y.set)
        tree_ci.pack(side="left", fill="both", expand=True)
        sc_ci_y.pack(side="right", fill="y")

        def quitar_item_tabla():
            sel = tree_ci.selection()
            if not sel:
                messagebox.showwarning("Aviso", "Seleccione una fila de la tabla para quitarla.", parent=modal)
                return
            idx = tree_ci.index(sel[0])
            tree_ci.delete(sel[0])
            if 0 <= idx < len(items_en_compra):
                items_en_compra.pop(idx)
            tot = sum(it["subtotal"] for it in items_en_compra)
            lbl_total_compra.config(text=f"TOTAL ENTRADA: {formato_peso(tot)}")

        f_table_actions = tk.Frame(modal, bg=t_mod["bg_surface"], padx=20)
        f_table_actions.pack(fill="x")
        crear_boton(f_table_actions, "Quitar Ítem", quitar_item_tabla, tipo="secondary", icono="🗑️", tam_fuente=8, padx=6, pady=2).pack(side="left")

        def agregar_item_tabla():
            sel_art = var_ai_prod.get()
            if not sel_art:
                messagebox.showwarning("Aviso", "Seleccione un artículo.", parent=modal)
                cb_ai_prod.focus_set()
                return
            cod = sel_art.split(" - ")[0].strip()
            art = obtener_articulo_por_codigo(cod)
            if not art:
                messagebox.showwarning("Aviso", f"No se encontró el artículo '{cod}'.", parent=modal)
                return

            try:
                fac = float(e_ai_factor.get().strip() or 1.0)
                cant = float(e_ai_cant.get().strip() or 1.0)
                cost_emp = float(e_ai_costo.get_value())
                if fac <= 0 or cant <= 0 or cost_emp <= 0:
                    messagebox.showwarning("Valores Inválidos", "El factor, cantidad y costo deben ser mayores a cero.", parent=modal)
                    return
                unid_base_tot = fac * cant
                c_unit = cost_emp / fac
                sub = cant * cost_emp

                item_obj = {
                    "producto_id": art["id"],
                    "codigo": cod,
                    "nombre": art["nombre"],
                    "unidad_compra": var_ai_unid.get(),
                    "factor_conversion": fac,
                    "cantidad_comprada": cant,
                    "cantidad_unidades": unid_base_tot,
                    "costo_unidad_compra": cost_emp,
                    "costo_unitario_convertido": c_unit,
                    "subtotal": sub
                }
                items_en_compra.append(item_obj)
                tree_ci.insert("", "end", values=(
                    cod, art["nombre"], item_obj["unidad_compra"], f"{fac:g}",
                    f"{cant:g}", f"{unid_base_tot:g}", formato_peso(cost_emp),
                    formato_peso(c_unit), formato_peso(sub)
                ))
                tot = sum(it["subtotal"] for it in items_en_compra)
                lbl_total_compra.config(text=f"TOTAL ENTRADA: {formato_peso(tot)}")
                lbl_ai_res.config(text=f"✅ Agregado: {cant:g} {var_ai_unid.get()} de {art['nombre']} ({formato_peso(sub)})")
                # Resetear campos para agilizar el ingreso del siguiente artículo
                e_ai_cant.delete(0, tk.END)
                e_ai_cant.insert(0, "1")
                e_ai_costo.set_value(0)
                cb_ai_prod.focus_set()
            except Exception as ex:
                messagebox.showerror("Error", str(ex), parent=modal)

        # Botón prominente en la fila 3 de f_add_item (siempre visible)
        crear_boton(f_ai_r3, "Agregar a la Entrada", agregar_item_tabla, tipo="primary", icono="➕", tam_fuente=9, padx=12, pady=3).pack(side="right")

        # Vincular tecla Enter para agregar automáticamente
        e_ai_factor.bind("<Return>", lambda e: agregar_item_tabla())
        e_ai_cant.bind("<Return>", lambda e: agregar_item_tabla())
        e_ai_costo.bind("<Return>", lambda e: agregar_item_tabla())

        def guardar_compra():
            # Si no hay ítems pero hay datos válidos en el formulario superior, auto-agregar
            if not items_en_compra:
                sel_art = var_ai_prod.get()
                cost_emp = float(e_ai_costo.get_value())
                cant = float(e_ai_cant.get().strip() or 0.0)
                if sel_art and cost_emp > 0 and cant > 0:
                    agregar_item_tabla()

            if not items_en_compra:
                messagebox.showwarning("Aviso", "Agregue al menos un ítem a la entrada pulsando '➕ Agregar a la Entrada'.", parent=modal)
                return

            prov_txt = var_cp_prov.get()
            prov_id = None
            prov_nom = "Proveedor General"
            if prov_txt != "Ninguno":
                try:
                    prov_id = int(prov_txt.split(" - ")[0])
                    prov_nom = prov_txt.split(" - ")[1]
                except Exception:
                    pass
            doc_fac = e_cp_fac.get().strip()
            dest = var_cp_dest.get()

            try:
                res = registrar_compra_entrada(
                    proveedor_id=prov_id,
                    proveedor_nombre=prov_nom,
                    doc_referencia=doc_fac,
                    items=items_en_compra,
                    ubicacion_destino=dest,
                    usuario=usuario_actual
                )
                messagebox.showinfo("Éxito", f"✅ Entrada de mercancía {res['numero_compra']} registrada correctamente.\nTotal: {formato_peso(res['total'])}", parent=modal)
                modal.destroy()
                try:
                    cargar_tabla_bodega()
                except Exception:
                    pass
                try:
                    cargar_tabla_vitrina()
                except Exception:
                    pass
                try:
                    cargar_tabla_catalogo()
                except Exception:
                    pass
                try:
                    cargar_tabla_compras()
                except Exception:
                    pass
                try:
                    cargar_tabla_kardex()
                except Exception:
                    pass
            except Exception as ex:
                messagebox.showerror("Error al Guardar", str(ex), parent=modal)

        crear_boton(f_foot_cp, "Cancelar", modal.destroy, tipo="secondary", tam_fuente=9).pack(side="right", padx=5)
        crear_boton(f_foot_cp, "Confirmar Entrada de Mercancía", guardar_compra, tipo="success", icono="💾", tam_fuente=10).pack(side="right", padx=5)

    crear_boton(bar_cmp, "Registrar Nueva Entrada / Compra", abrir_modal_nueva_compra, tipo="success", icono="➕", tam_fuente=9).pack(side="right")

    frame_tree_cmp = tk.Frame(tab_compras, bg=t["bg_surface"])
    frame_tree_cmp.pack(fill="both", expand=True, padx=15, pady=(0, 15))

    cols_cmp = ("Nº Entrada", "Fecha", "Hora", "Proveedor", "Doc. Factura", "Destino", "Total Compra", "Ítems", "Usuario", "Estado")
    tree_cmp = ttk.Treeview(frame_tree_cmp, columns=cols_cmp, show="headings", selectmode="browse")
    for c in cols_cmp:
        tree_cmp.heading(c, text=c)
    tree_cmp.column("Nº Entrada", width=95, anchor="center")
    tree_cmp.column("Fecha", width=85, anchor="center")
    tree_cmp.column("Hora", width=75, anchor="center")
    tree_cmp.column("Proveedor", width=180, anchor="w")
    tree_cmp.column("Doc. Factura", width=110, anchor="center")
    tree_cmp.column("Destino", width=85, anchor="center")
    tree_cmp.column("Total Compra", width=120, anchor="e")
    tree_cmp.column("Ítems", width=65, anchor="center")
    tree_cmp.column("Usuario", width=95, anchor="center")
    tree_cmp.column("Estado", width=85, anchor="center")

    sc_cmp_y = ttk.Scrollbar(frame_tree_cmp, orient="vertical", command=tree_cmp.yview)
    tree_cmp.configure(yscrollcommand=sc_cmp_y.set)
    tree_cmp.pack(side="left", fill="both", expand=True)
    sc_cmp_y.pack(side="right", fill="y")

    def cargar_tabla_compras():
        for r in tree_cmp.get_children():
            tree_cmp.delete(r)
        lista = obtener_historial_compras(limit=100)
        for c_item in lista:
            tree_cmp.insert("", "end", values=(
                c_item["numero_compra"], c_item["fecha"], c_item["hora"],
                c_item["proveedor_nombre"], c_item["documento_referencia"] or "—",
                c_item["ubicacion_destino"], formato_peso(c_item["total_compra"]),
                c_item["cantidad_items"], c_item["usuario"], c_item["estado"]
            ))

    # ==========================================================================
    # SECCIÓN 6: KÁRDEX E HISTORIAL DE MOVIMIENTOS
    # ==========================================================================
    bar_kdx = tk.Frame(tab_kardex, bg=t["bg_surface"], padx=15, pady=10)
    bar_kdx.pack(fill="x")

    tk.Label(bar_kdx, text="Buscar:", font=("Segoe UI", 10, "bold"), bg=t["bg_surface"], fg=t["text_main"]).pack(side="left", padx=(0, 5))
    var_filtro_kdx = tk.StringVar()
    e_filtro_kdx = tk.Entry(bar_kdx, textvariable=var_filtro_kdx, width=22, font=("Segoe UI", 10),
                            bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_insert"])
    e_filtro_kdx.pack(side="left", padx=(0, 15))

    tk.Label(bar_kdx, text="Tipo de Movimiento:", font=("Segoe UI", 10, "bold"), bg=t["bg_surface"], fg=t["text_main"]).pack(side="left", padx=(0, 5))
    var_tipo_kdx = tk.StringVar(value="Todos")
    tipos_mov_list = ["Todos", "ENTRADA_COMPRA", "ENTRADA_INICIAL", "TRASLADO_BODEGA_A_VITRINA", "TRASLADO_VITRINA_A_BODEGA", "VENTA", "DEVOLUCION_VENTA", "AJUSTE_POSITIVO", "AJUSTE_NEGATIVO"]
    cb_tipo_kdx = ttk.Combobox(bar_kdx, textvariable=var_tipo_kdx, values=tipos_mov_list, state="readonly", width=22)
    cb_tipo_kdx.pack(side="left", padx=(0, 15))

    def cargar_tabla_kardex():
        for r in tree_kdx.get_children():
            tree_kdx.delete(r)
        items = obtener_kardex(
            filtro_codigo=var_filtro_kdx.get().strip(),
            tipo_movimiento=var_tipo_kdx.get()
        )
        for m in items:
            tree_kdx.insert("", "end", values=(
                m["id"], m["fecha"], m["hora"], m["tipo_movimiento"],
                m["codigo_producto"], m["nombre_producto"],
                formato_cant(m["cantidad"], m["unidad_medida"]),
                f"{m['ubicacion_origen']} ➔ {m['ubicacion_destino']}",
                formato_peso(m["costo_unitario"]),
                formato_peso(m["valor_total"]),
                m["referencia"], m["usuario"], m["observaciones"]
            ))

    var_filtro_kdx.trace_add("write", lambda *a: cargar_tabla_kardex())
    cb_tipo_kdx.bind("<<ComboboxSelected>>", lambda e: cargar_tabla_kardex())
    crear_boton(bar_kdx, "Actualizar", cargar_tabla_kardex, tipo="secondary", icono="🔄", tam_fuente=9).pack(side="right")

    frame_tree_kdx = tk.Frame(tab_kardex, bg=t["bg_surface"])
    frame_tree_kdx.pack(fill="both", expand=True, padx=15, pady=(0, 15))

    cols_kdx = ("ID", "Fecha", "Hora", "Tipo Movimiento", "SKU", "Artículo", "Cantidad", "Trayectoria", "Costo Unit.", "Valor Total", "Referencia", "Usuario", "Observaciones")
    tree_kdx = ttk.Treeview(frame_tree_kdx, columns=cols_kdx, show="headings", selectmode="browse")
    for c in cols_kdx:
        tree_kdx.heading(c, text=c)
    tree_kdx.column("ID", width=45, anchor="center")
    tree_kdx.column("Fecha", width=80, anchor="center")
    tree_kdx.column("Hora", width=70, anchor="center")
    tree_kdx.column("Tipo Movimiento", width=170, anchor="center")
    tree_kdx.column("SKU", width=75, anchor="center")
    tree_kdx.column("Artículo", width=180, anchor="w")
    tree_kdx.column("Cantidad", width=95, anchor="center")
    tree_kdx.column("Trayectoria", width=160, anchor="center")
    tree_kdx.column("Costo Unit.", width=95, anchor="e")
    tree_kdx.column("Valor Total", width=105, anchor="e")
    tree_kdx.column("Referencia", width=120, anchor="center")
    tree_kdx.column("Usuario", width=95, anchor="center")
    tree_kdx.column("Observaciones", width=220, anchor="w")

    sc_kdx_y = ttk.Scrollbar(frame_tree_kdx, orient="vertical", command=tree_kdx.yview)
    sc_kdx_x = ttk.Scrollbar(frame_tree_kdx, orient="horizontal", command=tree_kdx.xview)
    tree_kdx.configure(yscrollcommand=sc_kdx_y.set, xscrollcommand=sc_kdx_x.set)
    tree_kdx.grid(row=0, column=0, sticky="nsew")
    sc_kdx_y.grid(row=0, column=1, sticky="ns")
    sc_kdx_x.grid(row=1, column=0, sticky="ew")
    frame_tree_kdx.rowconfigure(0, weight=1)
    frame_tree_kdx.columnconfigure(0, weight=1)

    # Cargar datos iniciales en todas las vistas
    cargar_tabla_catalogo()
    cargar_tabla_bodega()
    cargar_tabla_vitrina()
    cargar_tabla_traslados()
    cargar_tabla_compras()
    cargar_tabla_kardex()

    # Footer
    footer = tk.Frame(ventana, bg=t["bg_footer"], padx=20, pady=8)
    footer.pack(fill="x", side="bottom")
    tk.Label(footer, text=business_mgr.obtener_texto_ubicacion_contacto(), font=("Segoe UI", 9), bg=t["bg_footer"], fg=t["text_header"]).pack(side="left")
    tk.Label(footer, text=f"✨ {business_mgr.nombre} • Inventario Centralizado Conectado a Caja y Ventas", font=("Segoe UI", 9), bg=t["bg_footer"], fg=t["text_header_sub"]).pack(side="right")

    ventana.mainloop()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Gestión de Inventario VmPOS")
    parser.add_argument("--usuario", default="")
    parser.add_argument("--parent_pid", default="")
    if "-h" in sys.argv or "--help" in sys.argv:
        parser.print_help()
        sys.exit(0)
    args, _ = parser.parse_known_args()

    usuario = args.usuario or os.environ.get("VMPOS_USUARIO", "Administrador")
    parent_pid = args.parent_pid or os.environ.get("VMPOS_PARENT_PID", "")
    iniciar_inventario(usuario_actual=usuario, parent_pid=parent_pid)
