import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, date, timedelta
import os
import sys

# Agregar ruta base para importar client
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from client.api_client import api
from interface.business_manager import business_mgr

try:
    from theme_manager import (
        theme_mgr, aplicar_tema, calcular_geometria_segura,
        calcular_color_texto_optimo, crear_boton, ScrollableContainer,
        iniciar_observador_tema
    )
except ImportError:
    from interface.theme_manager import (
        theme_mgr, aplicar_tema, calcular_geometria_segura,
        calcular_color_texto_optimo, crear_boton, ScrollableContainer,
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
    from caja_manager import registrar_movimiento_caja, registrar_abono_cartera
except ImportError:
    from interface.caja_manager import registrar_movimiento_caja, registrar_abono_cartera

def iniciar_clientes(parent_pid="", parent=None):
    if parent:
        ventana = tk.Toplevel(parent)
    else:
        ventana = tk.Tk()
    parent_pid = parent_pid or os.environ.get("VMPOS_PARENT_PID", "")
    session_mgr.iniciar_vigilante_padre(ventana, parent_pid=parent_pid)
    iniciar_observador_tema(ventana)

    ventana.title(f"💎 Clientes y Cuentas por Cobrar - {business_mgr.nombre}")
    
    t = aplicar_tema(ventana)
    calcular_geometria_segura(ventana, 1140, 720, 920, 560)
    ventana.resizable(True, True)
    ventana.configure(bg=t["bg_app"])

    # Variables de estado
    filtro_tipo_var = tk.StringVar(value="todos") # todos | compras | fiados
    filtro_fecha_var = tk.StringVar(value="Hoy")   # Hoy | Ayer | Esta semana | Este mes | Rango personalizado
    fecha_desde_custom = None
    fecha_hasta_custom = None
    search_var = tk.StringVar()

    # Cache de clientes cargados
    clientes_cache = []

    # =========================================================================
    # 1. HEADER
    # =========================================================================
    header_frame = tk.Frame(ventana, bg=t["bg_header"])
    header_frame.pack(fill="x")

    fg_h = calcular_color_texto_optimo(t["bg_header"])

    header_left = tk.Frame(header_frame, bg=t["bg_header"])
    header_left.pack(side="left", padx=16, pady=8)
    tk.Label(header_left, text="💎", font=("Segoe UI Emoji", 20), bg=t["bg_header"], fg=fg_h).pack(side="left")
    tk.Label(header_left, text="GESTIÓN DE CLIENTES Y CARTERA", font=("Segoe UI", 15, "bold"), bg=t["bg_header"], fg=t["text_header"]).pack(side="left", padx=8)

    header_right = tk.Frame(header_frame, bg=t["bg_header"])
    header_right.pack(side="right", padx=16, pady=8)

    def alternar_tema_clientes():
        theme_mgr.alternar_tema()
        ventana.destroy()
        iniciar_clientes(parent_pid=parent_pid)

    btn_theme_txt = "☀️ Modo Claro" if theme_mgr.es_oscuro() else "🌙 Modo Oscuro"
    crear_boton(header_right, btn_theme_txt, alternar_tema_clientes, tipo="secondary", tam_fuente=8, padx=8, pady=2).pack(side="right", padx=(8, 0))

    lbl_tiempo = tk.Label(header_right, text="", font=("Segoe UI", 10, "bold"), bg=t["bg_header"], fg=t["text_header_sub"])
    lbl_tiempo.pack(side="right")

    def actualizar_reloj():
        try:
            if ventana.winfo_exists():
                ahora = datetime.now()
                lbl_tiempo.config(text=f"📅 {ahora.strftime('%d-%m-%Y')}  ⏰ {ahora.strftime('%H:%M:%S')}")
                tid = ventana.after(1000, actualizar_reloj)
                session_mgr.registrar_timer(ventana, tid)
        except Exception:
            pass

    actualizar_reloj()

    # =========================================================================
    # 2. FILTROS SUPERIORES: BUSCADOR, SEGMENTO (TODOS/COMPRAS/FIADOS) Y FECHAS
    # =========================================================================
    filter_bar = tk.Frame(ventana, bg=t["bg_surface_alt"], relief="groove", bd=1)
    filter_bar.pack(fill="x", pady=6, padx=14)

    # Buscador incremental
    search_box = tk.Frame(filter_bar, bg=t["bg_surface_alt"])
    search_box.pack(side="left", padx=8, pady=6)

    tk.Label(search_box, text="🔍 Buscar:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface_alt"], fg=t["text_main"]).pack(side="left", padx=(0, 4))
    entry_busqueda = tk.Entry(search_box, textvariable=search_var, font=("Segoe UI", 9), width=24, bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_insert"], bd=1, relief="solid")
    entry_busqueda.pack(side="left", padx=2)

    def on_search_change(*args):
        # Búsqueda local reactiva sobre la caché para máxima fluidez
        filtrar_tabla_local()

    search_var.trace_add("write", on_search_change)

    # Segmented buttons: [ TODOS ] [ COMPRAS ] [ FIADOS ]
    seg_box = tk.Frame(filter_bar, bg=t["bg_surface_alt"])
    seg_box.pack(side="left", padx=12, pady=6)

    tk.Label(seg_box, text="Mostrar:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface_alt"], fg=t["text_main"]).pack(side="left", padx=(0, 6))

    btn_seg_todos = tk.Button(seg_box, text="TODOS", font=("Segoe UI", 9, "bold"), bd=0, padx=10, pady=3, cursor="hand2")
    btn_seg_compras = tk.Button(seg_box, text="COMPRAS", font=("Segoe UI", 9, "bold"), bd=0, padx=10, pady=3, cursor="hand2")
    btn_seg_fiados = tk.Button(seg_box, text="FIADOS", font=("Segoe UI", 9, "bold"), bd=0, padx=10, pady=3, cursor="hand2")

    btn_seg_todos.pack(side="left", padx=1)
    btn_seg_compras.pack(side="left", padx=1)
    btn_seg_fiados.pack(side="left", padx=1)

    def actualizar_botones_segmento():
        curr = filtro_tipo_var.get()
        btn_seg_todos.config(bg=t["btn_primary_bg"] if curr == "todos" else t["bg_surface"], fg=t["btn_primary_fg"] if curr == "todos" else t["text_main"])
        btn_seg_compras.config(bg=t["btn_primary_bg"] if curr == "compras" else t["bg_surface"], fg=t["btn_primary_fg"] if curr == "compras" else t["text_main"])
        btn_seg_fiados.config(bg=t["btn_primary_bg"] if curr == "fiados" else t["bg_surface"], fg=t["btn_primary_fg"] if curr == "fiados" else t["text_main"])

    def set_filtro_tipo(val):
        filtro_tipo_var.set(val)
        actualizar_botones_segmento()
        cargar_datos_servidor()

    btn_seg_todos.config(command=lambda: set_filtro_tipo("todos"))
    btn_seg_compras.config(command=lambda: set_filtro_tipo("compras"))
    btn_seg_fiados.config(command=lambda: set_filtro_tipo("fiados"))
    actualizar_botones_segmento()

    # Selector de fecha (Default HOY en cada sesión)
    date_box = tk.Frame(filter_bar, bg=t["bg_surface_alt"])
    date_box.pack(side="left", padx=12, pady=6)

    tk.Label(date_box, text="📅 Fecha:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface_alt"], fg=t["text_main"]).pack(side="left", padx=(0, 4))
    cb_fecha = ttk.Combobox(date_box, textvariable=filtro_fecha_var, values=["Hoy", "Ayer", "Esta semana", "Este mes", "Rango personalizado", "Todo el Historial"], state="readonly", width=17, font=("Segoe UI", 9))
    cb_fecha.pack(side="left", padx=2)

    def on_date_change(event=None):
        val = filtro_fecha_var.get()
        if val == "Rango personalizado":
            abrir_modal_rango_personalizado()
        else:
            cargar_datos_servidor()

    cb_fecha.bind("<<ComboboxSelected>>", on_date_change)

    # Botón Destacado: [ 💰 FIADOS ]
    btn_fiados_destacado = crear_boton(
        filter_bar, 
        "GESTIÓN FIADOS", 
        lambda: abrir_modal_fiados(),
        tipo="success",
        icono="💰",
        tam_fuente=9
    )
    btn_fiados_destacado.pack(side="right", padx=10, pady=5)

    # =========================================================================
    # 3. TARJETAS DE RESUMEN
    # =========================================================================
    stats_frame = tk.Frame(ventana, bg=t["bg_app"])
    stats_frame.pack(fill="x", pady=3, padx=14)

    def crear_stat_card(parent, icono, titulo, var_val, color):
        card = tk.Frame(parent, bg=t["bg_card"], relief="solid", bd=1, padx=12, pady=5)
        card.pack(side="left", padx=5, fill="y")
        tk.Label(card, text=icono, font=("Segoe UI Emoji", 15), bg=t["bg_card"], fg=t["text_main"]).pack(side="left", padx=(0, 6))
        txt_f = tk.Frame(card, bg=t["bg_card"])
        txt_f.pack(side="left")
        tk.Label(txt_f, text=titulo, font=("Segoe UI", 8, "bold"), bg=t["bg_card"], fg=t["text_muted"]).pack(anchor="w")
        tk.Label(txt_f, textvariable=var_val, font=("Segoe UI", 11, "bold"), bg=t["bg_card"], fg=color).pack(anchor="w")
        return card

    total_clientes_var = tk.StringVar(value="0")
    compras_periodo_var = tk.StringVar(value="$0")
    clientes_fiado_var = tk.StringVar(value="0")
    deuda_total_var = tk.StringVar(value="$0")

    crear_stat_card(stats_frame, "👥", "Clientes", total_clientes_var, t["btn_primary_bg"])
    crear_stat_card(stats_frame, "🛍️", "Compras del Periodo", compras_periodo_var, t["btn_success_bg"])
    crear_stat_card(stats_frame, "💳", "Con Fiado", clientes_fiado_var, t["btn_purple_bg"])
    crear_stat_card(stats_frame, "⚠️", "Deuda Total Pendiente", deuda_total_var, t["btn_danger_bg"])

    # =========================================================================
    # 4. TABLA PRINCIPAL
    # =========================================================================
    table_frame = tk.Frame(ventana, bg=t["bg_app"])
    table_frame.pack(fill="both", expand=True, padx=14, pady=5)

    table_container = tk.Frame(table_frame, bg=t["bg_surface"], relief="solid", bd=1)
    table_container.pack(fill="both", expand=True)
    table_container.rowconfigure(0, weight=1)
    table_container.columnconfigure(0, weight=1)

    # Columnas principales con operario/vendedor
    columnas = ("NOMBRE", "TELEFONO", "OPERARIO", "FIADO", "DEUDA_TOTAL")
    tabla = ttk.Treeview(table_container, columns=columnas, show="headings")

    tabla.heading("NOMBRE", text="NOMBRE DEL CLIENTE")
    tabla.heading("TELEFONO", text="TELÉFONO")
    tabla.heading("OPERARIO", text="OPERARIO / VENDEDOR")
    tabla.heading("FIADO", text="FIADO")
    tabla.heading("DEUDA_TOTAL", text="DEUDA TOTAL")

    tabla.column("NOMBRE", width=280, minwidth=160, anchor="w")
    tabla.column("TELEFONO", width=130, minwidth=100, anchor="center")
    tabla.column("OPERARIO", width=180, minwidth=130, anchor="center")
    tabla.column("FIADO", width=90, minwidth=70, anchor="center")
    tabla.column("DEUDA_TOTAL", width=150, minwidth=100, anchor="e")

    v_scroll = ttk.Scrollbar(table_container, orient="vertical", command=tabla.yview)
    h_scroll = ttk.Scrollbar(table_container, orient="horizontal", command=tabla.xview)
    tabla.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

    tabla.grid(row=0, column=0, sticky="nsew")
    v_scroll.grid(row=0, column=1, sticky="ns")
    h_scroll.grid(row=1, column=0, sticky="ew")

    tabla.tag_configure("even", background=t["table_bg"])
    tabla.tag_configure("odd", background=t["table_row_alt"])
    tabla.tag_configure("deudor", foreground=t["btn_danger_bg"], font=("Segoe UI", 9, "bold"))

    # Map item id de la tabla a dict cliente
    item_to_cliente_map = {}

    def get_cliente_seleccionado():
        sel = tabla.selection()
        if not sel:
            return None
        return item_to_cliente_map.get(sel[0])

    # =========================================================================
    # CARGA DE DATOS DEL SERVIDOR Y FILTRADO LOCAL
    # =========================================================================
    def cargar_datos_servidor():
        nonlocal clientes_cache
        params = {}
        tipo = filtro_tipo_var.get()
        if tipo in ("compras", "fiados"):
            params["filtro_tipo"] = tipo

        f_val = filtro_fecha_var.get()
        if f_val == "Hoy":
            params["fecha_filtro"] = "hoy"
        elif f_val == "Ayer":
            params["fecha_filtro"] = "ayer"
        elif f_val == "Esta semana":
            params["fecha_filtro"] = "esta_semana"
        elif f_val == "Este mes":
            params["fecha_filtro"] = "este_mes"
        elif f_val == "Rango personalizado" and fecha_desde_custom and fecha_hasta_custom:
            params["fecha_filtro"] = "personalizado"
            params["fecha_desde"] = str(fecha_desde_custom)
            params["fecha_hasta"] = str(fecha_hasta_custom)

        try:
            resp = api.get("/clientes", params=params)
            if resp.status_code == 200:
                clientes_cache = resp.json()
                filtrar_tabla_local()
            else:
                messagebox.showerror("Error", f"Error al consultar clientes: {resp.status_code}")
        except Exception as e:
            messagebox.showerror("Error de Conexión", f"No se pudo conectar con el servidor: {e}")

    def filtrar_tabla_local():
        item_to_cliente_map.clear()
        tabla.delete(*tabla.get_children())

        busq = search_var.get().strip().lower()
        
        tot_clientes = 0
        tot_compras = 0.0
        tot_con_fiado = 0
        tot_deuda = 0.0

        for c in clientes_cache:
            nombre = str(c.get("nombre", "") or "")
            doc = str(c.get("documento", "") or "")
            tel = str(c.get("telefono", "") or "")
            operario = str(c.get("operario_venta") or c.get("vendedor") or "—")
            
            if busq:
                if busq not in nombre.lower() and busq not in doc.lower() and busq not in tel.lower() and busq not in operario.lower():
                    continue

            tot_clientes += 1
            tot_compras += float(c.get("total_compras", 0) or 0)
            deuda = float(c.get("deuda_total", 0) or 0)
            tot_deuda += deuda

            permite_fiado = bool(c.get("permite_fiado", False))
            if permite_fiado or deuda > 0:
                tot_con_fiado += 1
                fiado_str = "✅ Sí"
            else:
                fiado_str = "No"

            deuda_str = f"${deuda:,.0f} COP" if deuda > 0 else "$0 COP"

            tag = "even" if len(tabla.get_children()) % 2 == 0 else "odd"
            tags = [tag]
            if deuda > 0:
                tags.append("deudor")

            item_id = tabla.insert("", "end", values=(
                nombre,
                tel if tel else "—",
                operario,
                fiado_str,
                deuda_str
            ), tags=tuple(tags))
            item_to_cliente_map[item_id] = c


        total_clientes_var.set(str(tot_clientes))
        compras_periodo_var.set(f"${tot_compras:,.0f}")
        clientes_fiado_var.set(str(tot_con_fiado))
        deuda_total_var.set(f"${tot_deuda:,.0f}")

    # =========================================================================
    # 5. MODALES Y DIÁLOGOS ESPECÍFICOS
    # =========================================================================

    # Modal Rango Personalizado
    def abrir_modal_rango_personalizado():
        nonlocal fecha_desde_custom, fecha_hasta_custom
        dlg = tk.Toplevel(ventana)
        dlg.title("📅 Seleccionar Rango de Fechas")
        t_dlg = aplicar_tema(dlg)
        dlg.configure(bg=t_dlg["bg_surface"])
        dlg.transient(ventana)
        dlg.grab_set()

        calcular_geometria_segura(dlg, 400, 240, 340, 200)

        tk.Label(dlg, text="📅 Rango Personalizado", font=("Segoe UI", 12, "bold"), bg=t_dlg["bg_surface"], fg=t_dlg["text_main"]).pack(pady=10)

        f_frame = tk.Frame(dlg, bg=t_dlg["bg_surface"])
        f_frame.pack(pady=5)

        tk.Label(f_frame, text="Desde (AAAA-MM-DD):", font=("Segoe UI", 9, "bold"), bg=t_dlg["bg_surface"], fg=t_dlg["text_main"]).grid(row=0, column=0, pady=5, sticky="w")
        e_desde = tk.Entry(f_frame, font=("Segoe UI", 10), width=15, bg=t_dlg["input_bg"], fg=t_dlg["input_fg"], insertbackground=t_dlg["input_insert"])
        e_desde.grid(row=0, column=1, padx=5, pady=5)
        e_desde.insert(0, str(fecha_desde_custom or date.today() - timedelta(days=7)))

        tk.Label(f_frame, text="Hasta (AAAA-MM-DD):", font=("Segoe UI", 9, "bold"), bg=t_dlg["bg_surface"], fg=t_dlg["text_main"]).grid(row=1, column=0, pady=5, sticky="w")
        e_hasta = tk.Entry(f_frame, font=("Segoe UI", 10), width=15, bg=t_dlg["input_bg"], fg=t_dlg["input_fg"], insertbackground=t_dlg["input_insert"])
        e_hasta.grid(row=1, column=1, padx=5, pady=5)
        e_hasta.insert(0, str(fecha_hasta_custom or date.today()))

        def aplicar():
            nonlocal fecha_desde_custom, fecha_hasta_custom
            try:
                d1 = datetime.strptime(e_desde.get().strip(), "%Y-%m-%d").date()
                d2 = datetime.strptime(e_hasta.get().strip(), "%Y-%m-%d").date()
                if d1 > d2:
                    messagebox.showerror("Error", "La fecha 'Desde' no puede ser posterior a 'Hasta'", parent=dlg)
                    return
                fecha_desde_custom = d1
                fecha_hasta_custom = d2
                dlg.destroy()
                cargar_datos_servidor()
            except ValueError:
                messagebox.showerror("Error", "Formato de fecha inválido. Utilice AAAA-MM-DD", parent=dlg)

        btn_f = tk.Frame(dlg, bg=t_dlg["bg_surface"])
        btn_f.pack(pady=15)
        crear_boton(btn_f, "Cancelar", dlg.destroy, tipo="secondary", tam_fuente=9).pack(side="left", padx=5)
        crear_boton(btn_f, "Aplicar Rango", aplicar, tipo="primary", tam_fuente=9).pack(side="left", padx=5)

    # Modal GESTIÓN DE FIADOS
    def abrir_modal_fiados():
        dlg_f = tk.Toplevel(ventana)
        dlg_f.title("💰 Gestión Especializada de Fiados y Cuentas por Cobrar")
        t_f = aplicar_tema(dlg_f)
        dlg_f.configure(bg=t_f["bg_app"])
        dlg_f.transient(ventana)
        dlg_f.grab_set()

        calcular_geometria_segura(dlg_f, 1080, 680, 860, 500)

        # Header
        h_f = tk.Frame(dlg_f, bg=t_f["bg_header"])
        h_f.pack(fill="x")
        tk.Label(h_f, text="💰 CARTERA DE CUENTAS POR COBRAR (FIADOS)", font=("Segoe UI", 13, "bold"), bg=t_f["bg_header"], fg="white").pack(side="left", padx=16, pady=10)

        # Barra superior de acciones
        bar_f = tk.Frame(dlg_f, bg=t_f["bg_surface_alt"], bd=1, relief="groove")
        bar_f.pack(fill="x", padx=12, pady=6)

        search_fiado_var = tk.StringVar()
        tk.Label(bar_f, text="🔍 Buscar:", font=("Segoe UI", 9, "bold"), bg=t_f["bg_surface_alt"], fg=t_f["text_main"]).pack(side="left", padx=8, pady=6)
        e_sf = tk.Entry(bar_f, textvariable=search_fiado_var, font=("Segoe UI", 9), width=24, bg=t_f["input_bg"], fg=t_f["input_fg"], insertbackground=t_f["input_insert"], bd=1, relief="solid")
        e_sf.pack(side="left", padx=4, pady=6)

        btn_ref_f = crear_boton(bar_f, "Actualizar", lambda: cargar_fiados(), tipo="secondary", icono="🔄", tam_fuente=9)
        btn_ref_f.pack(side="right", padx=6, pady=6)

        btn_abonar_f = crear_boton(bar_f, "VER / ABONAR", lambda: abonar_desde_fiados(), tipo="info", icono="💵", tam_fuente=9)
        btn_abonar_f.pack(side="right", padx=6, pady=6)

        btn_nuevo_f = crear_boton(bar_f, "NUEVO FIADO", lambda: abrir_modal_nuevo_fiado(parent_win=dlg_f, on_success=lambda: cargar_fiados()), tipo="success", icono="➕", tam_fuente=9)
        btn_nuevo_f.pack(side="right", padx=6, pady=6)

        # Tabla de Fiados
        table_f_box = tk.Frame(dlg_f, bg=t_f["bg_surface"], bd=1, relief="solid")
        table_f_box.pack(fill="both", expand=True, padx=12, pady=6)
        table_f_box.rowconfigure(0, weight=1)
        table_f_box.columnconfigure(0, weight=1)

        cols_f = ("DOC", "NOMBRE", "TEL", "OPERARIO", "TOTAL_FIADO", "TOTAL_ABONADO", "DEUDA_ACTUAL", "ULTIMO_ABONO", "ESTADO")
        t_fiados = ttk.Treeview(table_f_box, columns=cols_f, show="headings")

        t_fiados.heading("DOC", text="DOCUMENTO")
        t_fiados.heading("NOMBRE", text="NOMBRE")
        t_fiados.heading("TEL", text="TELÉFONO")
        t_fiados.heading("OPERARIO", text="OPERARIO / VENDEDOR")
        t_fiados.heading("TOTAL_FIADO", text="TOTAL FIADO")
        t_fiados.heading("TOTAL_ABONADO", text="TOTAL ABONADO")
        t_fiados.heading("DEUDA_ACTUAL", text="DEUDA ACTUAL")
        t_fiados.heading("ULTIMO_ABONO", text="ÚLTIMO ABONO")
        t_fiados.heading("ESTADO", text="ESTADO")

        t_fiados.column("DOC", width=100, anchor="center")
        t_fiados.column("NOMBRE", width=190, anchor="w")
        t_fiados.column("TEL", width=110, anchor="center")
        t_fiados.column("OPERARIO", width=160, anchor="center")
        t_fiados.column("TOTAL_FIADO", width=110, anchor="e")
        t_fiados.column("TOTAL_ABONADO", width=110, anchor="e")
        t_fiados.column("DEUDA_ACTUAL", width=120, anchor="e")
        t_fiados.column("ULTIMO_ABONO", width=120, anchor="center")
        t_fiados.column("ESTADO", width=100, anchor="center")

        vs_f = ttk.Scrollbar(table_f_box, orient="vertical", command=t_fiados.yview)
        hs_f = ttk.Scrollbar(table_f_box, orient="horizontal", command=t_fiados.xview)
        t_fiados.configure(yscrollcommand=vs_f.set, xscrollcommand=hs_f.set)

        t_fiados.grid(row=0, column=0, sticky="nsew")
        vs_f.grid(row=0, column=1, sticky="ns")
        hs_f.grid(row=1, column=0, sticky="ew")

        t_fiados.tag_configure("even", background=t_f["table_bg"])
        t_fiados.tag_configure("odd", background=t_f["table_row_alt"])
        t_fiados.tag_configure("pendiente", foreground=t_f["btn_danger_bg"], font=("Segoe UI", 9, "bold"))
        t_fiados.tag_configure("pagado", foreground=t_f["btn_info_bg"])
        t_fiados.tag_configure("aldia", foreground=t_f["btn_success_bg"])

        fiados_raw_cache = []
        item_to_fiado_map = {}

        def cargar_fiados():
            nonlocal fiados_raw_cache
            try:
                r = api.get("/clientes/fiados/resumen")
                if r.status_code == 200:
                    fiados_raw_cache = r.json()
                    filtrar_fiados_local()
                else:
                    messagebox.showerror("Error", f"Error al cargar cartera: {r.status_code}", parent=dlg_f)
            except Exception as e:
                messagebox.showerror("Error", f"Error de red: {e}", parent=dlg_f)

        def filtrar_fiados_local(*args):
            item_to_fiado_map.clear()
            t_fiados.delete(*t_fiados.get_children())
            b = search_fiado_var.get().strip().lower()

            for item in fiados_raw_cache:
                doc = str(item.get("documento", "") or "")
                nom = str(item.get("nombre", "") or "")
                tel = str(item.get("telefono", "") or "")
                op_f = str(item.get("operario_venta") or item.get("vendedor") or "—")
                if b and (b not in doc.lower() and b not in nom.lower() and b not in tel.lower() and b not in op_f.lower()):
                    continue

                tf = float(item.get("total_fiado", 0) or 0)
                ta = float(item.get("total_abonado", 0) or 0)
                da = float(item.get("deuda_actual", 0) or 0)
                ult = item.get("ultimo_abono")
                ult_str = str(ult)[:10] if ult else "—"
                est = str(item.get("estado", "AL DÍA"))

                tag_row = "even" if len(t_fiados.get_children()) % 2 == 0 else "odd"
                tags = [tag_row]
                if est == "PENDIENTE":
                    tags.append("pendiente")
                elif est == "PAGADO":
                    tags.append("pagado")
                else:
                    tags.append("aldia")

                iid = t_fiados.insert("", "end", values=(
                    doc,
                    nom,
                    tel if tel else "—",
                    op_f,
                    f"${tf:,.0f}",
                    f"${ta:,.0f}",
                    f"${da:,.0f}",
                    ult_str,
                    est
                ), tags=tuple(tags))
                item_to_fiado_map[iid] = item


        search_fiado_var.trace_add("write", filtrar_fiados_local)

        def abonar_desde_fiados():
            sel = t_fiados.selection()
            if not sel:
                messagebox.showwarning("Selección requerida", "Por favor selecciona un cliente de la lista.", parent=dlg_f)
                return
            cli_info = item_to_fiado_map.get(sel[0])
            if cli_info:
                abrir_modal_abonar(cli_info["cliente_id"], parent_win=dlg_f, on_abono_hecho=lambda: (cargar_fiados(), cargar_datos_servidor()))

        t_fiados.bind("<Double-1>", lambda e: abonar_desde_fiados())
        cargar_fiados()

    # Modal NUEVO FIADO con PRE-CHEQUEO
    def abrir_modal_nuevo_fiado(parent_win=None, on_success=None):
        parent = parent_win or ventana
        modal_nf = tk.Toplevel(parent)
        modal_nf.title("➕ Registrar Cliente para Fiado (Antiduplicados)")
        t_nf = aplicar_tema(modal_nf)
        modal_nf.configure(bg=t_nf["bg_surface"])
        modal_nf.transient(parent)
        modal_nf.grab_set()

        calcular_geometria_segura(modal_nf, 520, 620, 440, 420)

        # 1. Header fijo
        tk.Label(modal_nf, text="➕ NUEVO CLIENTE PARA CRÉDITO / FIADO", font=("Segoe UI", 12, "bold"), bg=t_nf["bg_surface"], fg=t_nf["text_main"]).pack(pady=10)

        # 2. Footer de acción fijo
        footer_nf = tk.Frame(modal_nf, bg=t_nf["bg_surface_alt"], bd=1, relief="ridge")
        footer_nf.pack(side="bottom", fill="x", padx=15, pady=10)

        # 3. Contenedor central scrollable
        sc_nf = ScrollableContainer(modal_nf, bg=t_nf["bg_surface"])
        sc_nf.pack(fill="both", expand=True, padx=10, pady=5)

        # Paso 1: Pre-chequeo
        step1_frame = tk.LabelFrame(sc_nf.content_frame, text=" 1. Pre-chequeo de Identidad (Evita duplicados) ", font=("Segoe UI", 9, "bold"), bg=t_nf["bg_surface"], fg=t_nf["text_main"], padx=10, pady=8)
        step1_frame.pack(fill="x", padx=10, pady=5)

        precheck_var = tk.StringVar()
        tk.Label(step1_frame, text="Buscar Doc / Tel / Nombre:", font=("Segoe UI", 9), bg=t_nf["bg_surface"], fg=t_nf["text_main"]).pack(anchor="w")
        
        pre_box = tk.Frame(step1_frame, bg=t_nf["bg_surface"])
        pre_box.pack(fill="x", pady=4)
        e_pre = tk.Entry(pre_box, textvariable=precheck_var, font=("Segoe UI", 10), bg=t_nf["input_bg"], fg=t_nf["input_fg"], insertbackground=t_nf["input_insert"], bd=1, relief="solid")
        e_pre.pack(side="left", fill="x", expand=True, padx=(0, 6))

        lbl_status_pre = tk.Label(step1_frame, text="", font=("Segoe UI", 9), bg=t_nf["bg_surface"])
        lbl_status_pre.pack(anchor="w", pady=2)

        # Paso 2: Formulario
        step2_frame = tk.LabelFrame(sc_nf.content_frame, text=" 2. Datos del Cliente ", font=("Segoe UI", 9, "bold"), bg=t_nf["bg_surface"], fg=t_nf["text_main"], padx=10, pady=8)
        step2_frame.pack(fill="both", expand=True, padx=10, pady=5)

        tk.Label(step2_frame, text="Documento / Cédula (*):", font=("Segoe UI", 9, "bold"), bg=t_nf["bg_surface"], fg=t_nf["text_main"]).grid(row=0, column=0, sticky="w", pady=3)
        e_doc = tk.Entry(step2_frame, font=("Segoe UI", 9), bg=t_nf["input_bg"], fg=t_nf["input_fg"], insertbackground=t_nf["input_insert"], bd=1, relief="solid")
        e_doc.grid(row=0, column=1, sticky="ew", pady=3, padx=5)

        tk.Label(step2_frame, text="Nombre Completo (*):", font=("Segoe UI", 9, "bold"), bg=t_nf["bg_surface"], fg=t_nf["text_main"]).grid(row=1, column=0, sticky="w", pady=3)
        e_nom = tk.Entry(step2_frame, font=("Segoe UI", 9), bg=t_nf["input_bg"], fg=t_nf["input_fg"], insertbackground=t_nf["input_insert"], bd=1, relief="solid")
        e_nom.grid(row=1, column=1, sticky="ew", pady=3, padx=5)

        tk.Label(step2_frame, text="Teléfono:", font=("Segoe UI", 9), bg=t_nf["bg_surface"], fg=t_nf["text_main"]).grid(row=2, column=0, sticky="w", pady=3)
        e_tel = tk.Entry(step2_frame, font=("Segoe UI", 9), bg=t_nf["input_bg"], fg=t_nf["input_fg"], insertbackground=t_nf["input_insert"], bd=1, relief="solid")
        e_tel.grid(row=2, column=1, sticky="ew", pady=3, padx=5)

        tk.Label(step2_frame, text="Dirección:", font=("Segoe UI", 9), bg=t_nf["bg_surface"], fg=t_nf["text_main"]).grid(row=3, column=0, sticky="w", pady=3)
        e_dir = tk.Entry(step2_frame, font=("Segoe UI", 9), bg=t_nf["input_bg"], fg=t_nf["input_fg"], insertbackground=t_nf["input_insert"], bd=1, relief="solid")
        e_dir.grid(row=3, column=1, sticky="ew", pady=3, padx=5)

        tk.Label(step2_frame, text="Límite de Crédito ($):", font=("Segoe UI", 9), bg=t_nf["bg_surface"], fg=t_nf["text_main"]).grid(row=4, column=0, sticky="w", pady=3)
        e_lim = tk.Entry(step2_frame, font=("Segoe UI", 9), bg=t_nf["input_bg"], fg=t_nf["input_fg"], insertbackground=t_nf["input_insert"], bd=1, relief="solid")
        e_lim.grid(row=4, column=1, sticky="ew", pady=3, padx=5)
        e_lim.insert(0, "0")

        permite_var = tk.BooleanVar(value=True)
        chk_fiado = tk.Checkbutton(step2_frame, text="Habilitar Crédito / Fiado", variable=permite_var, font=("Segoe UI", 9, "bold"), bg=t_nf["bg_surface"], fg=t_nf["text_main"], selectcolor=t_nf["input_bg"], activebackground=t_nf["bg_surface"])
        chk_fiado.grid(row=5, column=0, columnspan=2, sticky="w", pady=6)
        step2_frame.columnconfigure(1, weight=1)

        def ejecutar_precheck():
            q = precheck_var.get().strip()
            if not q:
                return
            try:
                res = api.get("/clientes/buscar-precheck", params={"q": q})
                if res.status_code == 200:
                    data = res.json()
                    if data.get("existe"):
                        cli = data["cliente"]
                        lbl_status_pre.config(
                            text=f"⚠️ Cliente YA existe: {cli['nombre']} (Doc: {cli['documento']})\nDeuda actual: ${cli['saldo_pendiente']:,.0f}",
                            fg=t_nf["btn_danger_bg"]
                        )
                        # Rellenar
                        e_doc.delete(0, "end")
                        e_doc.insert(0, cli["documento"])
                        e_nom.delete(0, "end")
                        e_nom.insert(0, cli["nombre"])
                        e_tel.delete(0, "end")
                        e_tel.insert(0, cli.get("telefono") or "")
                        e_dir.delete(0, "end")
                        e_dir.insert(0, cli.get("direccion") or "")
                        permite_var.set(bool(cli.get("permite_fiado", True)))
                    else:
                        lbl_status_pre.config(text="✅ Cliente no encontrado. Puede crearlo a continuación.", fg=t_nf["btn_success_bg"])
                        # Si era un documento numérico, colocarlo
                        if q.isdigit() and len(q) >= 5:
                            e_doc.delete(0, "end")
                            e_doc.insert(0, q)
            except Exception as e:
                lbl_status_pre.config(text=f"Error en consulta: {e}", fg=t_nf["btn_danger_bg"])

        btn_verificar = crear_boton(pre_box, "Verificar", ejecutar_precheck, tipo="info", icono="🔍", tam_fuente=9)
        btn_verificar.pack(side="right")

        def guardar_nuevo_fiado():
            doc = e_doc.get().strip()
            nom = e_nom.get().strip()
            tel = e_tel.get().strip()
            direc = e_dir.get().strip()
            try:
                lim = float(e_lim.get().strip() or 0.0)
            except ValueError:
                messagebox.showerror("Error", "El límite de crédito debe ser un número válido", parent=modal_nf)
                return

            if not doc or not nom:
                messagebox.showerror("Error", "Documento y Nombre son campos obligatorios", parent=modal_nf)
                return

            payload = {
                "documento": doc,
                "nombre": nom,
                "telefono": tel,
                "direccion": direc,
                "permite_fiado": permite_var.get(),
                "limite_credito": lim,
                "estado": "Activo"
            }

            try:
                resp = api.post("/clientes", json=payload)
                if resp.status_code in (200, 201):
                    messagebox.showinfo("Éxito", f"Cliente '{nom}' registrado correctamente para fiado.", parent=modal_nf)
                    modal_nf.destroy()
                    if on_success:
                        on_success()
                    cargar_datos_servidor()
                elif resp.status_code == 400:
                    detail = resp.json().get("detail", "Error al crear cliente")
                    messagebox.showerror("Aviso", detail, parent=modal_nf)
                else:
                    messagebox.showerror("Error", f"Error {resp.status_code}: {resp.text}", parent=modal_nf)
            except Exception as e:
                messagebox.showerror("Error", f"Error de conexión: {e}", parent=modal_nf)

        crear_boton(footer_nf, "Cancelar", modal_nf.destroy, tipo="secondary", icono="❌", tam_fuente=9).pack(side="right", padx=5, pady=4)
        crear_boton(footer_nf, "Guardar Cliente Fiado", guardar_nuevo_fiado, tipo="success", icono="💾", tam_fuente=9).pack(side="right", padx=5, pady=4)

    # Modal VER / ABONAR
    def abrir_modal_abonar(cliente_id, parent_win=None, on_abono_hecho=None):
        parent = parent_win or ventana
        modal_ab = tk.Toplevel(parent)
        modal_ab.title("💵 Cuenta de Fiados, Libro Mayor y Registro de Abono")
        t_ab = aplicar_tema(modal_ab)
        modal_ab.configure(bg=t_ab["bg_app"])
        modal_ab.transient(parent)
        modal_ab.grab_set()

        calcular_geometria_segura(modal_ab, 920, 680, 780, 520)

        # Datos detalle del cliente
        detalle_data = {}

        # Header
        hdr_ab = tk.Frame(modal_ab, bg=t_ab["bg_header"])
        hdr_ab.pack(fill="x")
        lbl_titulo_ab = tk.Label(hdr_ab, text="💵 CUENTA CORRIENTE Y GESTIÓN DE ABONOS", font=("Segoe UI", 12, "bold"), bg=t_ab["bg_header"], fg="white")
        lbl_titulo_ab.pack(side="left", padx=16, pady=8)

        # Footer fijo al fondo
        ftr_ab = tk.Frame(modal_ab, bg=t_ab["bg_surface_alt"], bd=1, relief="ridge")
        ftr_ab.pack(fill="x", side="bottom", padx=14, pady=8)
        crear_boton(ftr_ab, "Cerrar", modal_ab.destroy, tipo="secondary", tam_fuente=9).pack(side="right", padx=5, pady=4)

        # Panel de Resumen Financiero
        summary_panel = tk.Frame(modal_ab, bg=t_ab["bg_card"], relief="solid", bd=1)
        summary_panel.pack(fill="x", padx=14, pady=8)

        lbl_nombre_cli = tk.Label(summary_panel, text="Cliente: ...", font=("Segoe UI", 11, "bold"), bg=t_ab["bg_card"], fg=t_ab["text_main"])
        lbl_nombre_cli.pack(anchor="w", padx=12, pady=(6, 2))

        cards_sub = tk.Frame(summary_panel, bg=t_ab["bg_card"])
        cards_sub.pack(fill="x", padx=12, pady=(2, 8))

        lbl_tot_fiado = tk.Label(cards_sub, text="Total Fiado: $0", font=("Segoe UI", 10), bg=t_ab["bg_card"], fg=t_ab["text_muted"])
        lbl_tot_fiado.pack(side="left", padx=(0, 20))

        lbl_tot_abonado = tk.Label(cards_sub, text="Total Abonado: $0", font=("Segoe UI", 10), bg=t_ab["bg_card"], fg=t_ab["btn_success_bg"])
        lbl_tot_abonado.pack(side="left", padx=20)

        lbl_saldo_actual = tk.Label(cards_sub, text="DEUDA ACTUAL: $0 COP", font=("Segoe UI", 12, "bold"), bg=t_ab["bg_card"], fg=t_ab["btn_danger_bg"])
        lbl_saldo_actual.pack(side="right", padx=10)

        # Notebook / Tabs para Libro Mayor y Cuentas Pendientes
        nb_frame = tk.Frame(modal_ab, bg=t_ab["bg_app"])
        nb_frame.pack(fill="both", expand=True, padx=14, pady=4)

        tk.Label(nb_frame, text="📖 Historial de Movimientos Contables (Libro Mayor Inmutable):", font=("Segoe UI", 9, "bold"), bg=t_ab["bg_app"], fg=t_ab["text_main"]).pack(anchor="w", pady=(0, 2))

        # Tabla de movimientos
        mov_container = tk.Frame(nb_frame, bg=t_ab["bg_surface"], bd=1, relief="solid")
        mov_container.pack(fill="both", expand=True)
        mov_container.rowconfigure(0, weight=1)
        mov_container.columnconfigure(0, weight=1)

        cols_mov = ("FECHA", "TIPO", "VENTA", "MONTO", "SALDO_ANT", "SALDO_NUEVO", "METODO", "USUARIO")
        t_movs = ttk.Treeview(mov_container, columns=cols_mov, show="headings")

        t_movs.heading("FECHA", text="FECHA / HORA")
        t_movs.heading("TIPO", text="TIPO MOV.")
        t_movs.heading("VENTA", text="VENTA / REF")
        t_movs.heading("MONTO", text="VALOR")
        t_movs.heading("SALDO_ANT", text="SALDO ANTERIOR")
        t_movs.heading("SALDO_NUEVO", text="SALDO NUEVO")
        t_movs.heading("METODO", text="MÉTODO")
        t_movs.heading("USUARIO", text="REGISTRADO POR")

        t_movs.column("FECHA", width=140, anchor="center")
        t_movs.column("TIPO", width=90, anchor="center")
        t_movs.column("VENTA", width=100, anchor="center")
        t_movs.column("MONTO", width=110, anchor="e")
        t_movs.column("SALDO_ANT", width=120, anchor="e")
        t_movs.column("SALDO_NUEVO", width=120, anchor="e")
        t_movs.column("METODO", width=100, anchor="center")
        t_movs.column("USUARIO", width=120, anchor="w")

        vs_m = ttk.Scrollbar(mov_container, orient="vertical", command=t_movs.yview)
        hs_m = ttk.Scrollbar(mov_container, orient="horizontal", command=t_movs.xview)
        t_movs.configure(yscrollcommand=vs_m.set, xscrollcommand=hs_m.set)

        t_movs.grid(row=0, column=0, sticky="nsew")
        vs_m.grid(row=0, column=1, sticky="ns")
        hs_m.grid(row=1, column=0, sticky="ew")

        t_movs.tag_configure("FIADO", foreground=t_ab["btn_danger_bg"])
        t_movs.tag_configure("ABONO", foreground=t_ab["btn_success_bg"], font=("Segoe UI", 9, "bold"))
        t_movs.tag_configure("ANULACION", foreground=t_ab["btn_purple_bg"])
        t_movs.tag_configure("AJUSTE_MANUAL", foreground=t_ab["btn_warning_bg"])

        # Sección de Registro de Abono
        abono_box = tk.LabelFrame(modal_ab, text=" ➕ Registrar Nuevo Abono ", font=("Segoe UI", 9, "bold"), bg=t_ab["bg_surface"], fg=t_ab["text_main"], padx=12, pady=6)
        abono_box.pack(fill="x", padx=14, pady=6)

        abono_row = tk.Frame(abono_box, bg=t_ab["bg_surface"])
        abono_row.pack(fill="x")

        tk.Label(abono_row, text="Valor Abono ($):", font=("Segoe UI", 9, "bold"), bg=t_ab["bg_surface"], fg=t_ab["text_main"]).pack(side="left", padx=(0, 4))
        e_monto = CurrencyEntry(
            abono_row,
            initial_value=0,
            show_symbol=True,
            font=("Segoe UI", 11, "bold"),
            width=14,
            bg=t_ab["input_bg"],
            fg=t_ab["input_fg"],
            insertbackground=t_ab["input_insert"],
            bd=1,
            relief="solid"
        )
        e_monto.pack(side="left", padx=4)

        tk.Label(abono_row, text="Método:", font=("Segoe UI", 9, "bold"), bg=t_ab["bg_surface"], fg=t_ab["text_main"]).pack(side="left", padx=(12, 4))
        metodo_var = tk.StringVar(value="Efectivo")
        cb_metodo = ttk.Combobox(abono_row, textvariable=metodo_var, values=["Efectivo", "Transferencia"], state="readonly", width=14, font=("Segoe UI", 9))
        cb_metodo.pack(side="left", padx=4)

        tk.Label(abono_row, text="Observación:", font=("Segoe UI", 9), bg=t_ab["bg_surface"], fg=t_ab["text_main"]).pack(side="left", padx=(12, 4))
        obs_var = tk.StringVar()
        e_obs = tk.Entry(abono_row, textvariable=obs_var, font=("Segoe UI", 9), width=20, bg=t_ab["input_bg"], fg=t_ab["input_fg"], insertbackground=t_ab["input_insert"], bd=1, relief="solid")
        e_obs.pack(side="left", padx=4)

        def refrescar_detalle():
            nonlocal detalle_data
            try:
                r = api.get(f"/clientes/{cliente_id}/deuda-detalle")
                if r.status_code == 200:
                    detalle_data = r.json()
                    c_info = detalle_data.get("cliente", {})
                    lbl_nombre_cli.config(text=f"Cliente: {c_info.get('nombre', '')} | Doc: {c_info.get('documento', '')} | Tel: {c_info.get('telefono', '—')}")
                    
                    tf = float(detalle_data.get("total_fiado", 0) or 0)
                    ta = float(detalle_data.get("total_abonado", 0) or 0)
                    da = float(detalle_data.get("deuda_actual", 0) or 0)

                    lbl_tot_fiado.config(text=f"Total Fiado: ${tf:,.0f}")
                    lbl_tot_abonado.config(text=f"Total Abonado: ${ta:,.0f}")
                    lbl_saldo_actual.config(text=f"DEUDA ACTUAL: ${da:,.0f} COP")

                    t_movs.delete(*t_movs.get_children())
                    for mov in detalle_data.get("movimientos", []):
                        f_str = str(mov.get("created_at", ""))[:19].replace("T", " ")
                        tipo_m = mov.get("tipo", "")
                        monto_m = float(mov.get("monto", 0) or 0)
                        s_ant = float(mov.get("saldo_anterior", 0) or 0)
                        s_post = float(mov.get("saldo_nuevo", 0) or 0)
                        v_num = mov.get("numero_venta") or "—"
                        met = mov.get("metodo_pago") or "—"
                        u_nom = mov.get("usuario_nombre") or ""

                        signo = "+" if tipo_m in ("FIADO",) else ("-" if tipo_m in ("ABONO", "ANULACION") else "")
                        t_movs.insert("", "end", values=(
                            f_str,
                            tipo_m,
                            v_num,
                            f"{signo}${monto_m:,.0f}",
                            f"${s_ant:,.0f}",
                            f"${s_post:,.0f}",
                            met,
                            u_nom
                        ), tags=(tipo_m,))
                else:
                    messagebox.showerror("Error", f"Error al cargar detalle: {r.status_code}", parent=modal_ab)
            except Exception as e:
                messagebox.showerror("Error", f"Error de red: {e}", parent=modal_ab)

        def intentar_registrar_abono():
            monto = e_monto.get_value()
            if monto <= 0:
                messagebox.showerror("Monto Inválido", "El monto de abono debe ser mayor a cero.", parent=modal_ab)
                return

            deuda_actual = float(detalle_data.get("deuda_actual", 0) or 0)
            if monto > deuda_actual:
                messagebox.showerror(
                    "Error de Validación",
                    f"El abono (${monto:,.0f}) no puede ser superior al saldo pendiente (${deuda_actual:,.0f}).",
                    parent=modal_ab
                )
                return

            metodo = metodo_var.get()
            c_info = detalle_data.get("cliente", {})
            saldo_nuevo = deuda_actual - monto

            # Submodal de confirmación
            conf = tk.Toplevel(modal_ab)
            conf.title("Confirmar Registro de Abono")
            t_conf = aplicar_tema(conf)
            conf.configure(bg=t_conf["bg_surface"])
            conf.transient(modal_ab)
            conf.grab_set()

            calcular_geometria_segura(conf, 400, 280, 360, 240)

            tk.Label(conf, text="⚠️ CONFIRMAR ABONO", font=("Segoe UI", 12, "bold"), bg=t_conf["bg_surface"], fg=t_conf["text_main"]).pack(pady=10)

            c_frame = tk.Frame(conf, bg=t_conf["bg_card"], relief="solid", bd=1, padx=14, pady=10)
            c_frame.pack(fill="both", expand=True, padx=15, pady=5)

            tk.Label(c_frame, text=f"Cliente: {c_info.get('nombre')}", font=("Segoe UI", 9, "bold"), bg=t_conf["bg_card"], fg=t_conf["text_main"]).pack(anchor="w", pady=2)
            tk.Label(c_frame, text=f"Saldo anterior: ${deuda_actual:,.0f} COP", font=("Segoe UI", 9), bg=t_conf["bg_card"], fg=t_conf["text_muted"]).pack(anchor="w", pady=2)
            tk.Label(c_frame, text=f"Valor Abono: ${monto:,.0f} COP", font=("Segoe UI", 10, "bold"), bg=t_conf["bg_card"], fg=t_conf["btn_success_bg"]).pack(anchor="w", pady=2)
            tk.Label(c_frame, text=f"Nuevo Saldo: ${saldo_nuevo:,.0f} COP", font=("Segoe UI", 10, "bold"), bg=t_conf["bg_card"], fg=t_conf["btn_danger_bg"]).pack(anchor="w", pady=2)
            tk.Label(c_frame, text=f"Método de Pago: {metodo}", font=("Segoe UI", 9), bg=t_conf["bg_card"], fg=t_conf["text_main"]).pack(anchor="w", pady=2)

            def confirmar_final():
                try:
                    # 1. Registrar abono de forma atómica en SQLite y libro mayor multicuenta
                    res_ab = registrar_abono_cartera(
                        cliente_id=cliente_id,
                        monto=monto,
                        metodo=metodo,
                        usuario="Administrador",
                        observaciones=obs_var.get().strip() or f"Abono por {metodo}"
                    )
                    
                    # 2. Sincronizar con servidor API si está disponible
                    try:
                        payload = {
                            "monto": monto,
                            "metodo": metodo,
                            "observacion": obs_var.get().strip() or None
                        }
                        api.post(f"/clientes/{cliente_id}/abonos", json=payload)
                    except Exception:
                        pass

                    conf.destroy()
                    messagebox.showinfo(
                        "Abono Exitoso",
                        f"Abono de ${monto:,.0f} COP registrado correctamente.\nNuevo saldo: ${res_ab['saldo_nuevo']:,.0f} COP",
                        parent=modal_ab
                    )
                    e_monto.clear()
                    obs_var.set("")
                    refrescar_detalle()
                    if on_abono_hecho:
                        on_abono_hecho()
                except Exception as ex:
                    messagebox.showerror("Error", f"Error registrando abono: {ex}", parent=conf)

            c_btn_f = tk.Frame(conf, bg=t_conf["bg_surface"])
            c_btn_f.pack(pady=10)
            crear_boton(c_btn_f, "Cancelar", conf.destroy, tipo="secondary", tam_fuente=9).pack(side="left", padx=5)
            crear_boton(c_btn_f, "CONFIRMAR ABONO", confirmar_final, tipo="success", tam_fuente=9).pack(side="left", padx=5)

        btn_proc_abono = crear_boton(abono_row, "REGISTRAR ABONO", intentar_registrar_abono, tipo="success", icono="💾", tam_fuente=9)
        btn_proc_abono.pack(side="right", padx=6)

        refrescar_detalle()

    # Modal VER DETALLE INTEGRAL DEL CLIENTE
    def abrir_modal_ver_detalle(cliente_id):
        modal_det = tk.Toplevel(ventana)
        modal_det.title("📋 Ficha y Compras del Cliente")
        t_det = aplicar_tema(modal_det)
        modal_det.configure(bg=t_det["bg_app"])
        modal_det.transient(ventana)
        modal_det.grab_set()

        calcular_geometria_segura(modal_det, 960, 680, 800, 500)

        hdr_d = tk.Frame(modal_det, bg=t_det["bg_header"])
        hdr_d.pack(fill="x")
        tk.Label(hdr_d, text="📋 DETALLE GENERAL Y COMPRAS DEL CLIENTE", font=("Segoe UI", 12, "bold"), bg=t_det["bg_header"], fg="white").pack(side="left", padx=16, pady=8)

        # Footer fijo al fondo
        ftr_d = tk.Frame(modal_det, bg=t_det["bg_surface_alt"], bd=1, relief="ridge")
        ftr_d.pack(fill="x", side="bottom", padx=14, pady=8)

        def ir_a_abonar():
            modal_det.destroy()
            abrir_modal_abonar(cliente_id, on_abono_hecho=lambda: cargar_datos_servidor())

        crear_boton(ftr_d, "Ver Historial y Abonar", ir_a_abonar, tipo="info", icono="💵", tam_fuente=9).pack(side="left", padx=10, pady=4)
        crear_boton(ftr_d, "Cerrar", modal_det.destroy, tipo="secondary", tam_fuente=9).pack(side="right", padx=5, pady=4)

        # Resumen superior
        info_panel = tk.Frame(modal_det, bg=t_det["bg_card"], relief="solid", bd=1)
        info_panel.pack(fill="x", padx=14, pady=8)

        lbl_info_cli = tk.Label(info_panel, text="Cargando información...", font=("Segoe UI", 10), bg=t_det["bg_card"], fg=t_det["text_main"], justify="left")
        lbl_info_cli.pack(anchor="w", padx=14, pady=8)

        # Tabla compras del cliente
        table_d_box = tk.Frame(modal_det, bg=t_det["bg_surface"], bd=1, relief="solid")
        table_d_box.pack(fill="both", expand=True, padx=14, pady=4)
        table_d_box.rowconfigure(0, weight=1)
        table_d_box.columnconfigure(0, weight=1)

        cols_c = ("ID", "NUMERO", "FECHA", "HORA", "TOTAL", "METODO", "VENDEDOR", "ESTADO")
        t_compras = ttk.Treeview(table_d_box, columns=cols_c, show="headings")

        t_compras.heading("ID", text="ID")
        t_compras.heading("NUMERO", text="N° FACTURA")
        t_compras.heading("FECHA", text="FECHA")
        t_compras.heading("HORA", text="HORA")
        t_compras.heading("TOTAL", text="TOTAL VENTA")
        t_compras.heading("METODO", text="MÉTODO PAGO")
        t_compras.heading("VENDEDOR", text="VENDEDOR / OPERARIO")
        t_compras.heading("ESTADO", text="ESTADO")

        t_compras.column("ID", width=45, anchor="center")
        t_compras.column("NUMERO", width=120, anchor="center")
        t_compras.column("FECHA", width=100, anchor="center")
        t_compras.column("HORA", width=80, anchor="center")
        t_compras.column("TOTAL", width=120, anchor="e")
        t_compras.column("METODO", width=110, anchor="center")
        t_compras.column("VENDEDOR", width=150, anchor="w")
        t_compras.column("ESTADO", width=90, anchor="center")

        vs_c = ttk.Scrollbar(table_d_box, orient="vertical", command=t_compras.yview)
        hs_c = ttk.Scrollbar(table_d_box, orient="horizontal", command=t_compras.xview)
        t_compras.configure(yscrollcommand=vs_c.set, xscrollcommand=hs_c.set)

        t_compras.grid(row=0, column=0, sticky="nsew")
        vs_c.grid(row=0, column=1, sticky="ns")
        hs_c.grid(row=1, column=0, sticky="ew")

        # Cargar datos cliente y compras
        try:
            r_cli = api.get(f"/clientes/{cliente_id}")
            r_dd = api.get(f"/clientes/{cliente_id}/deuda-detalle")
            if r_cli.status_code == 200:
                cli = r_cli.json()
                dd = r_dd.json() if r_dd.status_code == 200 else {}
                txt = (
                    f"Cliente: {cli.get('nombre')}    |    Documento: {cli.get('documento')}    |    Teléfono: {cli.get('telefono') or '—'}\n"
                    f"Permite Fiado: {'Sí' if cli.get('permite_fiado') else 'No'}    |    Límite Crédito: ${cli.get('limite_credito', 0):,.0f}    |    Estado: {cli.get('estado')}\n"
                    f"Total Compras: ${dd.get('total_compras', 0):,.0f}    |    Total Fiado: ${dd.get('total_fiado', 0):,.0f}    |    Total Abonado: ${dd.get('total_abonado', 0):,.0f}    |    Deuda Actual: ${dd.get('deuda_actual', 0):,.0f}"
                )
                lbl_info_cli.config(text=txt)

            r_comp = api.get(f"/clientes/{cliente_id}/compras")
            if r_comp.status_code == 200:
                compras = r_comp.json()
                for c in compras:
                    t_compras.insert("", "end", values=(
                        c.get("id"),
                        c.get("numero"),
                        c.get("fecha"),
                        c.get("hora"),
                        f"${c.get('total', 0):,.0f}",
                        c.get("metodo_pago"),
                        c.get("vendedor"),
                        c.get("estado")
                    ))
        except Exception as ex:
            messagebox.showerror("Error", f"Error al consultar detalle: {ex}", parent=modal_det)

    # Modal Crear / Editar Cliente
    def abrir_modal_cliente(cliente_data=None):
        es_edit = cliente_data is not None
        modal_c = tk.Toplevel(ventana)
        modal_c.title("✏️ Editar Cliente" if es_edit else "👤 Nuevo Cliente")
        t_c = aplicar_tema(modal_c)
        modal_c.configure(bg=t_c["bg_surface"])
        modal_c.transient(ventana)
        modal_c.grab_set()

        calcular_geometria_segura(modal_c, 460, 420, 400, 350)

        titulo = "✏️ EDITAR CLIENTE" if es_edit else "👤 REGISTRAR NUEVO CLIENTE"
        tk.Label(modal_c, text=titulo, font=("Segoe UI", 12, "bold"), bg=t_c["bg_surface"], fg=t_c["text_main"]).pack(pady=10)

        # Footer fijo al fondo
        footer_mc = tk.Frame(modal_c, bg=t_c["bg_surface_alt"], bd=1, relief="ridge")
        footer_mc.pack(side="bottom", fill="x", padx=15, pady=10)

        f_body = tk.Frame(modal_c, bg=t_c["bg_surface"], padx=20)
        f_body.pack(fill="both", expand=True)

        tk.Label(f_body, text="Documento / Cédula (*):", font=("Segoe UI", 9, "bold"), bg=t_c["bg_surface"], fg=t_c["text_main"]).grid(row=0, column=0, sticky="w", pady=4)
        e_doc = tk.Entry(f_body, font=("Segoe UI", 9), bg=t_c["input_bg"], fg=t_c["input_fg"], insertbackground=t_c["input_insert"], bd=1, relief="solid")
        e_doc.grid(row=0, column=1, sticky="ew", pady=4, padx=5)

        tk.Label(f_body, text="Nombre Completo (*):", font=("Segoe UI", 9, "bold"), bg=t_c["bg_surface"], fg=t_c["text_main"]).grid(row=1, column=0, sticky="w", pady=4)
        e_nom = tk.Entry(f_body, font=("Segoe UI", 9), bg=t_c["input_bg"], fg=t_c["input_fg"], insertbackground=t_c["input_insert"], bd=1, relief="solid")
        e_nom.grid(row=1, column=1, sticky="ew", pady=4, padx=5)

        tk.Label(f_body, text="Teléfono:", font=("Segoe UI", 9), bg=t_c["bg_surface"], fg=t_c["text_main"]).grid(row=2, column=0, sticky="w", pady=4)
        e_tel = tk.Entry(f_body, font=("Segoe UI", 9), bg=t_c["input_bg"], fg=t_c["input_fg"], insertbackground=t_c["input_insert"], bd=1, relief="solid")
        e_tel.grid(row=2, column=1, sticky="ew", pady=4, padx=5)

        tk.Label(f_body, text="Dirección:", font=("Segoe UI", 9), bg=t_c["bg_surface"], fg=t_c["text_main"]).grid(row=3, column=0, sticky="w", pady=4)
        e_dir = tk.Entry(f_body, font=("Segoe UI", 9), bg=t_c["input_bg"], fg=t_c["input_fg"], insertbackground=t_c["input_insert"], bd=1, relief="solid")
        e_dir.grid(row=3, column=1, sticky="ew", pady=4, padx=5)

        tk.Label(f_body, text="Límite Crédito ($):", font=("Segoe UI", 9), bg=t_c["bg_surface"], fg=t_c["text_main"]).grid(row=4, column=0, sticky="w", pady=4)
        e_lim = tk.Entry(f_body, font=("Segoe UI", 9), bg=t_c["input_bg"], fg=t_c["input_fg"], insertbackground=t_c["input_insert"], bd=1, relief="solid")
        e_lim.grid(row=4, column=1, sticky="ew", pady=4, padx=5)

        permite_var = tk.BooleanVar(value=False)
        chk_fiado = tk.Checkbutton(f_body, text="Permitir Crédito (Fiado)", variable=permite_var, font=("Segoe UI", 9, "bold"), bg=t_c["bg_surface"], fg=t_c["text_main"], selectcolor=t_c["input_bg"], activebackground=t_c["bg_surface"])
        chk_fiado.grid(row=5, column=0, columnspan=2, sticky="w", pady=8)

        f_body.columnconfigure(1, weight=1)

        if es_edit:
            e_doc.insert(0, cliente_data.get("documento") or "")
            e_nom.insert(0, cliente_data.get("nombre") or "")
            e_tel.insert(0, cliente_data.get("telefono") or "")
            e_dir.insert(0, cliente_data.get("direccion") or "")
            e_lim.insert(0, str(cliente_data.get("limite_credito", 0.0) or 0.0))
            permite_var.set(bool(cliente_data.get("permite_fiado", False)))
        else:
            e_lim.insert(0, "0")

        def guardar():
            doc = e_doc.get().strip()
            nom = e_nom.get().strip()
            tel = e_tel.get().strip()
            direc = e_dir.get().strip()
            try:
                lim = float(e_lim.get().strip() or 0.0)
            except ValueError:
                messagebox.showerror("Error", "Límite de crédito inválido", parent=modal_c)
                return

            if not doc or not nom:
                messagebox.showerror("Error", "Documento y Nombre son campos requeridos", parent=modal_c)
                return

            payload = {
                "documento": doc,
                "nombre": nom,
                "telefono": tel,
                "direccion": direc,
                "permite_fiado": permite_var.get(),
                "limite_credito": lim
            }

            try:
                if es_edit:
                    cid = cliente_data["id"]
                    resp = api.put(f"/clientes/{cid}", json=payload)
                else:
                    payload["estado"] = "Activo"
                    resp = api.post("/clientes", json=payload)

                if resp.status_code in (200, 201):
                    modal_c.destroy()
                    messagebox.showinfo("Éxito", "Cliente guardado exitosamente", parent=ventana)
                    cargar_datos_servidor()
                elif resp.status_code == 400:
                    detail = resp.json().get("detail", "Error al guardar")
                    messagebox.showerror("Aviso", detail, parent=modal_c)
                else:
                    messagebox.showerror("Error", f"Error {resp.status_code}: {resp.text}", parent=modal_c)
            except Exception as e:
                messagebox.showerror("Error", f"Error de red: {e}", parent=modal_c)

        crear_boton(footer_mc, "Cancelar", modal_c.destroy, tipo="secondary", icono="❌", tam_fuente=9).pack(side="right", padx=5, pady=4)
        crear_boton(footer_mc, "Guardar", guardar, tipo="success", icono="💾", tam_fuente=9).pack(side="right", padx=5, pady=4)

    # Eliminar cliente
    def eliminar_cliente_ui():
        cli = get_cliente_seleccionado()
        if not cli:
            messagebox.showwarning("Selección requerida", "Por favor selecciona un cliente de la lista.")
            return

        cid = cli["id"]
        nom = cli["nombre"]

        if messagebox.askyesno("Confirmar Eliminación", f"¿Desea desactivar al cliente '{nom}'?\n(No se eliminará el historial financiero previo)"):
            try:
                resp = api.delete(f"/clientes/{cid}")
                if resp.status_code == 200:
                    messagebox.showinfo("Éxito", f"Cliente '{nom}' desactivado correctamente.")
                    cargar_datos_servidor()
                else:
                    detail = resp.json().get("detail", "No se pudo desactivar")
                    messagebox.showerror("Error", detail)
            except Exception as e:
                messagebox.showerror("Error", f"Error de conexión: {e}")

    # Doble clic en tabla principal abre el detalle
    def on_doble_clic(event):
        cli = get_cliente_seleccionado()
        if cli:
            abrir_modal_ver_detalle(cli["id"])

    tabla.bind("<Double-1>", on_doble_clic)

    # =========================================================================
    # 6. BARRA INFERIOR DE ACCIONES
    # =========================================================================
    bottom_bar = tk.Frame(ventana, bg=t["bg_app"])
    bottom_bar.pack(fill="x", padx=14, pady=6)

    btn_actions = tk.Frame(bottom_bar, bg=t["bg_app"])
    btn_actions.pack(side="left")

    def on_nuevo_clic():
        abrir_modal_cliente()

    def on_editar_clic():
        cli = get_cliente_seleccionado()
        if not cli:
            messagebox.showwarning("Selección requerida", "Selecciona un cliente para editar.")
            return
        abrir_modal_cliente(cli)

    def on_detalle_clic():
        cli = get_cliente_seleccionado()
        if not cli:
            messagebox.showwarning("Selección requerida", "Selecciona un cliente para ver su detalle.")
            return
        abrir_modal_ver_detalle(cli["id"])

    def on_abonar_directo():
        cli = get_cliente_seleccionado()
        if not cli:
            messagebox.showwarning("Selección requerida", "Selecciona un cliente para gestionar su deuda.")
            return
        abrir_modal_abonar(cli["id"], on_abono_hecho=lambda: cargar_datos_servidor())

    acciones = [
        ("Nuevo Cliente", t["btn_primary_bg"], on_nuevo_clic, "👤"),
        ("Editar Cliente", t["btn_purple_bg"], on_editar_clic, "✏️"),
        ("Ver Detalle / Compras", t["btn_info_bg"], on_detalle_clic, "📋"),
        ("Gestionar Deuda / Abonar", t["btn_success_bg"], on_abonar_directo, "💵"),
        ("Desactivar", t["btn_danger_bg"], eliminar_cliente_ui, "🗑️"),
        ("Actualizar", t["btn_secondary_bg"], lambda: cargar_datos_servidor(), "🔄")
    ]

    for txt, col, cmd, ico in acciones:
        b = crear_boton(btn_actions, txt, cmd, tipo=col, icono=ico, tam_fuente=9)
        b.pack(side="left", padx=4)

    # Footer
    footer = tk.Frame(ventana, bg=t["bg_footer"])
    footer.pack(fill="x", side="bottom")
    fg_f = calcular_color_texto_optimo(t["bg_footer"])
    tk.Label(footer, text=f"✨ {business_mgr.nombre} - Sistema Integral de Clientes, Cuentas por Cobrar y Trazabilidad Financiera 🌸", font=("Segoe UI", 9, "italic"), bg=t["bg_footer"], fg=fg_f).pack(pady=4)

    # Carga inicial (inicia siempre en HOY por defecto)
    cargar_datos_servidor()

    if not parent:
        ventana.mainloop()
    return ventana

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Clientes y Cartera VmPOS")
    parser.add_argument("--parent_pid", default="")
    if "-h" in sys.argv or "--help" in sys.argv:
        parser.print_help()
        sys.exit(0)
    args, _ = parser.parse_known_args()
    parent_pid = args.parent_pid or os.environ.get("VMPOS_PARENT_PID", "")
    iniciar_clientes(parent_pid=parent_pid)
