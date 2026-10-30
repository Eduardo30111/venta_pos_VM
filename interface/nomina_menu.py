import tkinter as tk
from tkinter import ttk, messagebox
import datetime
import sys
import os

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

try:
    from interface.nomina_manager import (
        inicializar_tablas_nomina,
        obtener_empleados_configuracion,
        actualizar_configuracion_empleado,
        registrar_asistencia_jornada,
        registrar_pago_nomina,
        registrar_ajuste_nomina,
        obtener_asistencias_jornadas,
        obtener_historial_pagos_nomina,
        obtener_devengos_nomina,
        obtener_metricas_nomina_contabilidad
    )
except ImportError:
    from nomina_manager import (
        inicializar_tablas_nomina,
        obtener_empleados_configuracion,
        actualizar_configuracion_empleado,
        registrar_asistencia_jornada,
        registrar_pago_nomina,
        registrar_ajuste_nomina,
        obtener_asistencias_jornadas,
        obtener_historial_pagos_nomina,
        obtener_devengos_nomina,
        obtener_metricas_nomina_contabilidad
    )

try:
    from interface.database_manager import conectar_db
except ImportError:
    from database_manager import conectar_db

try:
    from interface.proveedores_manager import (
        inicializar_tablas_proveedores,
        recalcular_saldo_proveedor,
        obtener_resumen_proveedores,
        obtener_detalle_cuentas_proveedor,
        obtener_historial_liquidaciones_proveedor,
        liquidar_proveedor_db,
        revertir_liquidacion_proveedor_db
    )
except ImportError:
    from proveedores_manager import (
        inicializar_tablas_proveedores,
        recalcular_saldo_proveedor,
        obtener_resumen_proveedores,
        obtener_detalle_cuentas_proveedor,
        obtener_historial_liquidaciones_proveedor,
        liquidar_proveedor_db,
        revertir_liquidacion_proveedor_db
    )


def _fmt_cop(valor):
    try:
        return f"${float(valor or 0.0):,.0f} COP"
    except Exception:
        return "$0 COP"


def iniciar_nomina(parent_pid="", parent=None):
    inicializar_tablas_nomina()
    inicializar_tablas_proveedores()

    if parent:
        ventana = tk.Toplevel(parent)
    else:
        ventana = tk.Tk()
    parent_pid = parent_pid or os.environ.get("VMPOS_PARENT_PID", "")
    session_mgr.iniciar_vigilante_padre(ventana, parent_pid=parent_pid)
    iniciar_observador_tema(ventana)

    ventana.title("💸 Nómina, Comisiones y Proveedores - VmPOS")

    t = aplicar_tema(ventana)
    calcular_geometria_segura(ventana, 1240, 760, min_w=960, min_h=580)
    ventana.configure(bg=t["bg_app"])

    # Header
    header = tk.Frame(ventana, bg=t["primary"])
    header.pack(fill="x")
    fg_h = calcular_color_texto_optimo(t["primary"])
    tk.Label(
        header,
        text="💸 MÓDULO DE NÓMINA, COMISIONES, TESORERÍA Y PROVEEDORES",
        font=("Segoe UI", 14, "bold"),
        bg=t["primary"],
        fg=fg_h
    ).pack(side="left", padx=20, pady=10)

    # Barra superior de métricas contables de nómina (Mes actual)
    hoy_iso = datetime.date.today().strftime("%Y-%m-%d")
    inicio_mes_iso = datetime.date.today().replace(day=1).strftime("%Y-%m-%d")

    kpi_bar = tk.Frame(ventana, bg=t["bg_app"])
    kpi_bar.pack(fill="x", padx=15, pady=(8, 2))

    def _crear_kpi_top(titulo, color_borde):
        c = tk.Frame(kpi_bar, bg=t["bg_surface"], bd=1, relief="solid")
        c.pack(side="left", fill="both", expand=True, padx=4)
        tk.Frame(c, bg=color_borde, height=3).pack(fill="x")
        tk.Label(c, text=titulo, font=("Segoe UI", 8, "bold"), bg=t["bg_surface"], fg=t["text_muted"]).pack(pady=(4, 0))
        lbl = tk.Label(c, text="$0 COP", font=("Segoe UI", 12, "bold"), bg=t["bg_surface"], fg=t["text_primary"])
        lbl.pack(pady=(1, 4))
        return lbl

    lbl_kpi_devengado = _crear_kpi_top("📈 Nómina Devengada (Mes)", "#4F46E5")
    lbl_kpi_pagado_ef = _crear_kpi_top("💵 Pagado en Efectivo (Caja)", "#059669")
    lbl_kpi_pagado_tr = _crear_kpi_top("🏦 Pagado por Transferencia", "#0284C7")
    lbl_kpi_pasivo = _crear_kpi_top("⚖️ Pasivo Pendiente Nómina", "#D97706")

    def actualizar_kpis_globales():
        try:
            m = obtener_metricas_nomina_contabilidad(inicio_mes_iso, hoy_iso)
            lbl_kpi_devengado.config(text=_fmt_cop(m.get("gasto_nomina_devengada", 0.0)))
            lbl_kpi_pagado_ef.config(text=_fmt_cop(m.get("pagado_efectivo", 0.0)))
            lbl_kpi_pagado_tr.config(text=_fmt_cop(m.get("pagado_transferencia", 0.0)))
            lbl_kpi_pasivo.config(text=_fmt_cop(m.get("pasivo_nomina_pendiente", 0.0)))
        except Exception as e_k:
            print("Aviso actualizando KPIs globales de nómina:", e_k)

    # Main container
    main_frame = tk.Frame(ventana, bg=t["bg_app"])
    main_frame.pack(fill="both", expand=True, padx=15, pady=8)

    # Notebook Styles
    style = ttk.Style()
    try:
        style.theme_use('clam')
    except Exception:
        pass
    style.configure("TNotebook", background=t["bg_app"], borderwidth=0)
    style.configure("TNotebook.Tab", font=("Segoe UI", 9, "bold"), padding=[10, 5], background=t["bg_card"], foreground=t["text_primary"])
    style.map("TNotebook.Tab", background=[("selected", t["primary"])], foreground=[("selected", "white")])
    style.configure("Treeview", background=t["tree_bg"], foreground=t["tree_fg"], fieldbackground=t["tree_field_bg"], rowheight=26, font=("Segoe UI", 9))
    style.configure("Treeview.Heading", background=t["tree_heading_bg"], foreground=t["tree_heading_fg"], font=('Segoe UI', 9, 'bold'), relief="flat")
    style.map("Treeview", background=[("selected", t["primary"])], foreground=[("selected", "#FFFFFF")])

    notebook = ttk.Notebook(main_frame)
    notebook.pack(fill="both", expand=True)

    tab_config = tk.Frame(notebook, bg=t["bg_surface"])
    tab_asistencia = tk.Frame(notebook, bg=t["bg_surface"])
    tab_liquidaciones = tk.Frame(notebook, bg=t["bg_surface"])
    tab_historial = tk.Frame(notebook, bg=t["bg_surface"])
    tab_proveedores = tk.Frame(notebook, bg=t["bg_surface"])

    notebook.add(tab_liquidaciones, text=" 💸 1. Liquidaciones, Pagos y Ajustes ")
    notebook.add(tab_config, text=" 👥 2. Empleados y Configuración ")
    notebook.add(tab_asistencia, text=" 📅 3. Asistencia y Jornadas ")
    notebook.add(tab_historial, text=" 📊 4. Historial e Informes ")
    notebook.add(tab_proveedores, text=" 📦 5. Pagos Proveedores ")

    # =========================================================================
    # SECCIÓN 1 (TAB): LIQUIDACIONES, PAGOS Y AJUSTES (FASE 2 & FASE 5)
    # =========================================================================
    liq_top_bar = tk.Frame(tab_liquidaciones, bg=t["bg_surface"])
    liq_top_bar.pack(fill="x", padx=10, pady=(8, 4))

    tk.Label(
        liq_top_bar,
        text="Saldos Devengados, Pagos y Liquidaciones por Empleado",
        font=("Segoe UI", 12, "bold"),
        bg=t["bg_surface"],
        fg=t["primary"]
    ).pack(side="left")

    tk.Label(liq_top_bar, text="Rol:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).pack(side="left", padx=(20, 4))
    filtro_rol_liq_var = tk.StringVar(value="Todos")
    combo_rol_liq = ttk.Combobox(liq_top_bar, textvariable=filtro_rol_liq_var, values=["Todos", "Vendedor", "Operario"], state="readonly", width=12)
    combo_rol_liq.pack(side="left", padx=2)

    tk.Label(liq_top_bar, text="Estado:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).pack(side="left", padx=(12, 4))
    filtro_est_liq_var = tk.StringVar(value="Todos")
    combo_est_liq = ttk.Combobox(
        liq_top_bar,
        textvariable=filtro_est_liq_var,
        values=["Todos", "Con saldo pendiente", "Solicitud activa", "Al día"],
        state="readonly",
        width=18
    )
    combo_est_liq.pack(side="left", padx=2)

    tree_emp_container = tk.Frame(tab_liquidaciones, bg=t["bg_surface"])
    tree_emp_container.pack(fill="both", expand=True, padx=10, pady=4)
    tree_emp_container.rowconfigure(0, weight=1)
    tree_emp_container.columnconfigure(0, weight=1)

    cols_emp = (
        "ID", "Empleado", "Rol", "Esquema",
        "Salario Diario Acum.", "Comisiones Acum.", "Ajustes",
        "Total Devengado", "Total Pagado", "Saldo Pendiente", "Solicitud"
    )
    tree_emp = ttk.Treeview(tree_emp_container, columns=cols_emp, show="headings", selectmode="browse")
    anchos_emp = {
        "ID": 45, "Empleado": 150, "Rol": 85, "Esquema": 120,
        "Salario Diario Acum.": 120, "Comisiones Acum.": 120, "Ajustes": 95,
        "Total Devengado": 120, "Total Pagado": 115, "Saldo Pendiente": 125, "Solicitud": 115
    }
    for c in cols_emp:
        tree_emp.heading(c, text=c)
        tree_emp.column(c, width=anchos_emp.get(c, 100), minwidth=45, anchor="center")

    scroll_emp_y = ttk.Scrollbar(tree_emp_container, orient="vertical", command=tree_emp.yview)
    scroll_emp_x = ttk.Scrollbar(tree_emp_container, orient="horizontal", command=tree_emp.xview)
    tree_emp.configure(yscrollcommand=scroll_emp_y.set, xscrollcommand=scroll_emp_x.set)
    tree_emp.grid(row=0, column=0, sticky="nsew")
    scroll_emp_y.grid(row=0, column=1, sticky="ns")
    scroll_emp_x.grid(row=1, column=0, sticky="ew")

    liq_actions_bar = tk.Frame(tab_liquidaciones, bg=t["bg_surface"])
    liq_actions_bar.pack(fill="x", padx=10, pady=8)

    # =========================================================================
    # SECCIÓN 2 (TAB): EMPLEADOS Y CONFIGURACIÓN
    # =========================================================================
    cfg_top_bar = tk.Frame(tab_config, bg=t["bg_surface"])
    cfg_top_bar.pack(fill="x", padx=10, pady=(8, 4))
    tk.Label(
        cfg_top_bar,
        text="Configuración de Esquemas de Remuneración, Reglas de Devengo y Comisiones",
        font=("Segoe UI", 12, "bold"),
        bg=t["bg_surface"],
        fg=t["primary"]
    ).pack(side="left")

    cfg_tree_container = tk.Frame(tab_config, bg=t["bg_surface"])
    cfg_tree_container.pack(fill="both", expand=True, padx=10, pady=4)
    cfg_tree_container.rowconfigure(0, weight=1)
    cfg_tree_container.columnconfigure(0, weight=1)

    cols_cfg = (
        "ID", "Usuario", "Nombre Completo", "Rol", "Estado",
        "Tipo Remuneración", "Salario Diario", "% Comisión",
        "Regla Salario Diario", "Com. Productos", "Com. Servicios", "Com. Fiados"
    )
    tree_cfg = ttk.Treeview(cfg_tree_container, columns=cols_cfg, show="headings", selectmode="browse")
    anchos_cfg = {
        "ID": 45, "Usuario": 95, "Nombre Completo": 150, "Rol": 85, "Estado": 75,
        "Tipo Remuneración": 115, "Salario Diario": 110, "% Comisión": 85,
        "Regla Salario Diario": 135, "Com. Productos": 95, "Com. Servicios": 95, "Com. Fiados": 90
    }
    for c in cols_cfg:
        tree_cfg.heading(c, text=c)
        tree_cfg.column(c, width=anchos_cfg.get(c, 95), anchor="center")

    sc_cfg_y = ttk.Scrollbar(cfg_tree_container, orient="vertical", command=tree_cfg.yview)
    sc_cfg_x = ttk.Scrollbar(cfg_tree_container, orient="horizontal", command=tree_cfg.xview)
    tree_cfg.configure(yscrollcommand=sc_cfg_y.set, xscrollcommand=sc_cfg_x.set)
    tree_cfg.grid(row=0, column=0, sticky="nsew")
    sc_cfg_y.grid(row=0, column=1, sticky="ns")
    sc_cfg_x.grid(row=1, column=0, sticky="ew")

    cfg_btn_bar = tk.Frame(tab_config, bg=t["bg_surface"])
    cfg_btn_bar.pack(fill="x", padx=10, pady=8)

    # =========================================================================
    # SECCIÓN 3 (TAB): ASISTENCIA Y JORNADAS (FASE 3)
    # =========================================================================
    ast_top_bar = tk.Frame(tab_asistencia, bg=t["bg_surface"])
    ast_top_bar.pack(fill="x", padx=10, pady=(8, 4))

    tk.Label(ast_top_bar, text="Desde:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).pack(side="left", padx=(0, 4))
    ast_desde_var = tk.StringVar(value=inicio_mes_iso)
    tk.Entry(ast_top_bar, textvariable=ast_desde_var, width=11, font=("Segoe UI", 9)).pack(side="left", padx=2)

    tk.Label(ast_top_bar, text="Hasta:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).pack(side="left", padx=(8, 4))
    ast_hasta_var = tk.StringVar(value=hoy_iso)
    tk.Entry(ast_top_bar, textvariable=ast_hasta_var, width=11, font=("Segoe UI", 9)).pack(side="left", padx=2)

    tk.Label(ast_top_bar, text="Rol:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).pack(side="left", padx=(8, 4))
    ast_rol_var = tk.StringVar(value="Todos")
    combo_ast_rol = ttk.Combobox(ast_top_bar, textvariable=ast_rol_var, values=["Todos", "Vendedor", "Operario"], state="readonly", width=12)
    combo_ast_rol.pack(side="left", padx=2)

    ast_tree_container = tk.Frame(tab_asistencia, bg=t["bg_surface"])
    ast_tree_container.pack(fill="both", expand=True, padx=10, pady=4)
    ast_tree_container.rowconfigure(0, weight=1)
    ast_tree_container.columnconfigure(0, weight=1)

    cols_ast = (
        "ID", "Fecha", "Hora Apertura", "Empleado", "Rol",
        "Estado Asistencia", "1ra Venta #", "Salario Diario Generado",
        "Monto Salario", "Responsable", "Observaciones"
    )
    tree_ast = ttk.Treeview(ast_tree_container, columns=cols_ast, show="headings", selectmode="browse")
    anchos_ast = {
        "ID": 45, "Fecha": 95, "Hora Apertura": 95, "Empleado": 145, "Rol": 85,
        "Estado Asistencia": 175, "1ra Venta #": 85, "Salario Diario Generado": 135,
        "Monto Salario": 115, "Responsable": 105, "Observaciones": 210
    }
    for c in cols_ast:
        tree_ast.heading(c, text=c)
        tree_ast.column(c, width=anchos_ast.get(c, 100), anchor="center")

    sc_ast_y = ttk.Scrollbar(ast_tree_container, orient="vertical", command=tree_ast.yview)
    sc_ast_x = ttk.Scrollbar(ast_tree_container, orient="horizontal", command=tree_ast.xview)
    tree_ast.configure(yscrollcommand=sc_ast_y.set, xscrollcommand=sc_ast_x.set)
    tree_ast.grid(row=0, column=0, sticky="nsew")
    sc_ast_y.grid(row=0, column=1, sticky="ns")
    sc_ast_x.grid(row=1, column=0, sticky="ew")

    ast_btn_bar = tk.Frame(tab_asistencia, bg=t["bg_surface"])
    ast_btn_bar.pack(fill="x", padx=10, pady=8)

    # =========================================================================
    # SECCIÓN 4 (TAB): HISTORIAL E INFORMES (PAGOS Y DEVENGOS)
    # =========================================================================
    hist_top_bar = tk.Frame(tab_historial, bg=t["bg_surface"])
    hist_top_bar.pack(fill="x", padx=10, pady=(8, 4))

    tk.Label(hist_top_bar, text="Desde:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).pack(side="left", padx=(0, 4))
    hist_desde_var = tk.StringVar(value=inicio_mes_iso)
    tk.Entry(hist_top_bar, textvariable=hist_desde_var, width=11, font=("Segoe UI", 9)).pack(side="left", padx=2)

    tk.Label(hist_top_bar, text="Hasta:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).pack(side="left", padx=(8, 4))
    hist_hasta_var = tk.StringVar(value=hoy_iso)
    tk.Entry(hist_top_bar, textvariable=hist_hasta_var, width=11, font=("Segoe UI", 9)).pack(side="left", padx=2)

    tk.Label(hist_top_bar, text="Rol:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).pack(side="left", padx=(8, 4))
    hist_rol_var = tk.StringVar(value="Todos")
    combo_hist_rol = ttk.Combobox(hist_top_bar, textvariable=hist_rol_var, values=["Todos", "Vendedor", "Operario"], state="readonly", width=12)
    combo_hist_rol.pack(side="left", padx=2)

    tk.Label(hist_top_bar, text="Mes/Año:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).pack(side="left", padx=(8, 4))
    mes_emp_var = tk.StringVar(value="Todos")
    combo_mes_emp = ttk.Combobox(hist_top_bar, textvariable=mes_emp_var, state="readonly", width=12, font=("Segoe UI", 9))
    combo_mes_emp.pack(side="left", padx=2)

    sub_nb_hist = ttk.Notebook(tab_historial)
    sub_nb_hist.pack(fill="both", expand=True, padx=10, pady=4)

    sub_pagos = tk.Frame(sub_nb_hist, bg=t["bg_surface"])
    sub_devengos = tk.Frame(sub_nb_hist, bg=t["bg_surface"])
    sub_nb_hist.add(sub_pagos, text=" 🧾 Historial de Pagos, Liquidaciones y Anticipos ")
    sub_nb_hist.add(sub_devengos, text=" 📋 Detalle Auditable de Devengos, Comisiones y Ajustes ")

    # Tabla Historial de Pagos
    cols_hist_emp = (
        "Nº Pago", "Fecha/Hora", "Empleado", "Rol", "Tipo Pago",
        "Método", "Cuenta Afectada", "Período", "Monto Pagado",
        "Saldo Restante", "Responsable", "Observaciones"
    )
    tree_hist_emp = ttk.Treeview(sub_pagos, columns=cols_hist_emp, show="headings", selectmode="browse")
    anchos_hp = {
        "Nº Pago": 65, "Fecha/Hora": 130, "Empleado": 135, "Rol": 80, "Tipo Pago": 125,
        "Método": 95, "Cuenta Afectada": 130, "Período": 115, "Monto Pagado": 115,
        "Saldo Restante": 115, "Responsable": 100, "Observaciones": 180
    }
    for c in cols_hist_emp:
        tree_hist_emp.heading(c, text=c)
        tree_hist_emp.column(c, width=anchos_hp.get(c, 100), anchor="center")

    sc_hp_y = ttk.Scrollbar(sub_pagos, orient="vertical", command=tree_hist_emp.yview)
    tree_hist_emp.configure(yscrollcommand=sc_hp_y.set)
    tree_hist_emp.pack(side="left", fill="both", expand=True)
    sc_hp_y.pack(side="right", fill="y")

    # Tabla Detalle de Devengos y Comisiones
    cols_dev = (
        "ID", "Fecha", "Empleado", "Rol", "Categoría",
        "Venta #", "Concepto / Ítem", "Base", "%", "Monto", "Estado", "Responsable"
    )
    tree_dev = ttk.Treeview(sub_devengos, columns=cols_dev, show="headings", selectmode="browse")
    anchos_dv = {
        "ID": 50, "Fecha": 95, "Empleado": 135, "Rol": 80, "Categoría": 130,
        "Venta #": 75, "Concepto / Ítem": 210, "Base": 100, "%": 55,
        "Monto": 110, "Estado": 90, "Responsable": 100
    }
    for c in cols_dev:
        tree_dev.heading(c, text=c)
        tree_dev.column(c, width=anchos_dv.get(c, 95), anchor="center")

    sc_dv_y = ttk.Scrollbar(sub_devengos, orient="vertical", command=tree_dev.yview)
    tree_dev.configure(yscrollcommand=sc_dv_y.set)
    tree_dev.pack(side="left", fill="both", expand=True)
    sc_dv_y.pack(side="right", fill="y")

    # =========================================================================
    # FUNCIONES DE CARGA Y SINCRONIZACIÓN DE DATOS
    # =========================================================================
    empleados_cache = {}

    def cargar_empleados(*args):
        selected_id = None
        sel = tree_emp.selection()
        if sel:
            try:
                selected_id = tree_emp.item(sel[0], "values")[0]
            except Exception:
                pass

        selected_cfg_id = None
        sel_c = tree_cfg.selection()
        if sel_c:
            try:
                selected_cfg_id = tree_cfg.item(sel_c[0], "values")[0]
            except Exception:
                pass

        for i in tree_emp.get_children():
            tree_emp.delete(i)
        for i in tree_cfg.get_children():
            tree_cfg.delete(i)

        empleados = obtener_empleados_configuracion(incluir_inactivos=True)
        empleados_cache.clear()
        for e in empleados:
            empleados_cache[int(e["id"])] = e

        rol_f = filtro_rol_liq_var.get()
        est_f = filtro_est_liq_var.get()

        for e in empleados:
            uid = int(e["id"])
            nom_comp = e.get("nombre_completo") or e.get("usuario")
            rol_e = e.get("rol", "Vendedor")
            estado_e = e.get("estado", "Activo")
            t_nom = e.get("tipo_nomina", "Porcentual")
            sal_d = float(e.get("salario_diario", 0.0))
            porc_c = float(e.get("comision_porcentaje", 0.0))
            regla_d = e.get("regla_devengo", "PRIMERA_VENTA")

            # Insertar en tabla de Configuración (Tab 2)
            cfg_item_id = tree_cfg.insert(
                "", "end",
                values=(
                    uid,
                    e.get("usuario", ""),
                    nom_comp,
                    rol_e,
                    estado_e,
                    t_nom,
                    _fmt_cop(sal_d),
                    f"{porc_c:.1f}%",
                    regla_d,
                    "✅ Sí" if e.get("comision_productos", 1) else "❌ No",
                    "✅ Sí" if e.get("comision_servicios", 1) else "❌ No",
                    "✅ Sí" if e.get("comision_fiados", 0) else "❌ No"
                )
            )
            if selected_cfg_id is not None and str(uid) == str(selected_cfg_id):
                tree_cfg.selection_set(cfg_item_id)
                tree_cfg.focus(cfg_item_id)

            # Filtros para Tab 1 (Liquidaciones)
            if estado_e != "Activo":
                continue
            if rol_f != "Todos" and rol_e.lower() != rol_f.lower():
                continue

            saldo_pend = float(e.get("saldo_pendiente", 0.0))
            sol_activa = bool(e.get("solicitud_activa", False))

            if est_f == "Con saldo pendiente" and saldo_pend <= 0:
                continue
            if est_f == "Solicitud activa" and not sol_activa:
                continue
            if est_f == "Al día" and saldo_pend > 0:
                continue

            if t_nom == "Fija":
                esq_txt = f"Fijo ({_fmt_cop(sal_d)}/día)"
            elif t_nom == "Mixta":
                esq_txt = f"Mixto ({_fmt_cop(sal_d)} + {porc_c:.0f}%)"
            else:
                esq_txt = f"Comisión ({porc_c:.0f}%)"

            sol_txt = "🔔 Solicitada" if sol_activa else "No solicitada"
            tag = "activo" if sol_activa else ("pendiente" if saldo_pend > 0 else "normal")

            item_id = tree_emp.insert(
                "", "end",
                values=(
                    uid,
                    nom_comp,
                    rol_e,
                    esq_txt,
                    _fmt_cop(e.get("total_salario_diario", 0.0)),
                    _fmt_cop(e.get("total_comisiones", 0.0)),
                    _fmt_cop(e.get("total_ajustes", 0.0)),
                    _fmt_cop(e.get("total_devengado", 0.0)),
                    _fmt_cop(e.get("total_pagado", 0.0)),
                    _fmt_cop(saldo_pend),
                    sol_txt
                ),
                tags=(tag,)
            )
            if selected_id is not None and str(uid) == str(selected_id):
                tree_emp.selection_set(item_id)
                tree_emp.focus(item_id)

        if not tree_emp.selection():
            hijos_emp = tree_emp.get_children()
            if hijos_emp:
                tree_emp.selection_set(hijos_emp[0])
                tree_emp.focus(hijos_emp[0])

        if not tree_cfg.selection():
            hijos_cfg = tree_cfg.get_children()
            if hijos_cfg:
                tree_cfg.selection_set(hijos_cfg[0])
                tree_cfg.focus(hijos_cfg[0])

        tree_emp.tag_configure("activo", background="#d4edda", foreground="#155724")
        tree_emp.tag_configure("pendiente", background="#fff3cd", foreground="#856404")
        tree_emp.tag_configure("normal", background=t["tree_bg"], foreground=t["tree_fg"])
        actualizar_kpis_globales()

    combo_rol_liq.bind("<<ComboboxSelected>>", cargar_empleados)
    combo_est_liq.bind("<<ComboboxSelected>>", cargar_empleados)

    def cargar_asistencias(*args):
        for i in tree_ast.get_children():
            tree_ast.delete(i)
        registros = obtener_asistencias_jornadas(
            fecha_inicio=ast_desde_var.get().strip() or None,
            fecha_fin=ast_hasta_var.get().strip() or None,
            rol=ast_rol_var.get()
        )
        for r in registros:
            pv = f"#{r['primera_venta_id']}" if r.get("primera_venta_id") else "—"
            sg = "✅ Sí" if r.get("salario_generado") else "⏳ No"
            tree_ast.insert(
                "", "end",
                values=(
                    r.get("id"),
                    r.get("fecha"),
                    r.get("hora_registro") or "—",
                    r.get("usuario_nombre"),
                    r.get("rol"),
                    r.get("estado"),
                    pv,
                    sg,
                    _fmt_cop(r.get("monto_salario_generado", 0.0)),
                    r.get("responsable") or "Sistema",
                    r.get("observaciones") or ""
                )
            )

    combo_ast_rol.bind("<<ComboboxSelected>>", cargar_asistencias)
    crear_boton(
        ast_top_bar, text="🔍 Filtrar Jornadas", command=cargar_asistencias,
        bg=t["primary"], fg="white", font=("Segoe UI", 9, "bold"), padx=10, pady=3
    ).pack(side="left", padx=8)

    def cargar_historial_emp(*args):
        for i in tree_hist_emp.get_children():
            tree_hist_emp.delete(i)
        for i in tree_dev.get_children():
            tree_dev.delete(i)

        f_ini = hist_desde_var.get().strip() or None
        f_fin = hist_hasta_var.get().strip() or None
        rol_h = hist_rol_var.get()
        mes_f = mes_emp_var.get()

        pagos = obtener_historial_pagos_nomina(
            fecha_inicio=f_ini,
            fecha_fin=f_fin,
            rol=rol_h,
            mes_anio=mes_f if mes_f and mes_f != "Todos" else None
        )
        for p in pagos:
            periodo_str = f"{p.get('periodo_inicio', '')} a {p.get('periodo_fin', '')}".strip(" a ") or p.get("mes_anio", "")
            tree_hist_emp.insert(
                "", "end",
                values=(
                    f"#{int(p.get('id', 0)):03d}",
                    f"{p.get('fecha', '')} {p.get('hora', '')}".strip(),
                    p.get("usuario_nombre", ""),
                    p.get("rol", ""),
                    p.get("tipo_pago", "LIQUIDACION_TOTAL"),
                    p.get("metodo_pago", "Efectivo"),
                    p.get("cuenta_afectada", "CAJA_FISICA"),
                    periodo_str,
                    _fmt_cop(p.get("monto_pagado", 0.0)),
                    _fmt_cop(p.get("saldo_restante", 0.0)),
                    p.get("responsable", "Administrador"),
                    p.get("observaciones", "")
                )
            )

        devengos = obtener_devengos_nomina(
            fecha_inicio=f_ini,
            fecha_fin=f_fin,
            rol=rol_h
        )
        for d in devengos:
            v_str = f"#{d['id_venta']}" if d.get("id_venta") else "—"
            porc_s = f"{float(d.get('porcentaje', 0.0)):.1f}%" if float(d.get("porcentaje", 0.0)) > 0 else "—"
            tree_dev.insert(
                "", "end",
                values=(
                    d.get("id"),
                    d.get("fecha"),
                    d.get("usuario_nombre", ""),
                    d.get("rol", ""),
                    d.get("tipo", ""),
                    v_str,
                    d.get("concepto", ""),
                    _fmt_cop(d.get("valor_base", 0.0)),
                    porc_s,
                    _fmt_cop(d.get("monto", 0.0)),
                    d.get("estado", "PENDIENTE"),
                    d.get("responsable", "Sistema")
                )
            )

    def actualizar_combo_meses_emp():
        pagos_all = obtener_historial_pagos_nomina()
        meses_set = {p.get("mes_anio") for p in pagos_all if p.get("mes_anio")}
        meses = ["Todos"] + sorted(list(meses_set), reverse=True)
        combo_mes_emp["values"] = meses
        if not mes_emp_var.get() or mes_emp_var.get() not in meses:
            mes_emp_var.set("Todos")
        cargar_historial_emp()

    combo_mes_emp.bind("<<ComboboxSelected>>", cargar_historial_emp)
    combo_hist_rol.bind("<<ComboboxSelected>>", cargar_historial_emp)
    crear_boton(
        hist_top_bar, text="🔍 Consultar Historial", command=cargar_historial_emp,
        bg=t["primary"], fg="white", font=("Segoe UI", 9, "bold"), padx=10, pady=3
    ).pack(side="left", padx=8)

    # =========================================================================
    # MODALES DE OPERACIÓN: LIQUIDACIÓN/PAGO, AJUSTE, CONFIGURACIÓN, ASISTENCIA
    # =========================================================================
    def modal_registrar_pago():
        sel = tree_emp.selection()
        item = sel[0] if sel else tree_emp.focus()
        if not item:
            messagebox.showwarning("Atención", "Seleccione un empleado de la tabla para registrar un pago o liquidación.", parent=ventana)
            return

        val = tree_emp.item(item, "values")
        id_emp = int(val[0])
        emp = empleados_cache.get(id_emp, {})
        nombre = emp.get("nombre_completo") or val[1]
        saldo_pend = float(emp.get("saldo_pendiente", 0.0))

        dlg = tk.Toplevel(ventana)
        dlg.title(f"💸 Registrar Pago / Liquidación — {nombre}")
        t_d = aplicar_tema(dlg)
        calcular_geometria_segura(dlg, 500, 520, min_w=440, min_h=460, modal_padre=ventana)
        dlg.configure(bg=t_d["bg_app"])
        dlg.transient(ventana)
        dlg.grab_set()

        tk.Label(
            dlg, text=f"💸 Pago de Nómina: {nombre}",
            font=("Segoe UI", 13, "bold"), bg=t_d["primary"], fg="white", pady=10
        ).pack(fill="x")

        body = tk.Frame(dlg, bg=t_d["bg_surface"], padx=18, pady=12, bd=1, relief="solid")
        body.pack(fill="both", expand=True, padx=15, pady=10)

        tk.Label(
            body,
            text=f"Saldo neto pendiente actual: {_fmt_cop(saldo_pend)}",
            font=("Segoe UI", 11, "bold"), bg=t_d["bg_surface"], fg="#059669"
        ).pack(anchor="w", pady=(0, 8))

        tk.Label(body, text="Tipo de Operación:", font=("Segoe UI", 9, "bold"), bg=t_d["bg_surface"], fg=t_d["text_primary"]).pack(anchor="w")
        tipo_var = tk.StringVar(value="LIQUIDACION_TOTAL" if saldo_pend > 0 else "ANTICIPO")
        cb_tipo = ttk.Combobox(
            body, textvariable=tipo_var,
            values=["LIQUIDACION_TOTAL", "PAGO_PARCIAL", "ANTICIPO"],
            state="readonly", width=28
        )
        cb_tipo.pack(anchor="w", pady=(2, 8))

        tk.Label(body, text="Monto a Pagar (COP):", font=("Segoe UI", 9, "bold"), bg=t_d["bg_surface"], fg=t_d["text_primary"]).pack(anchor="w")
        monto_var = tk.StringVar(value=str(int(round(max(0.0, saldo_pend)))))
        ent_monto = tk.Entry(body, textvariable=monto_var, font=("Segoe UI", 11, "bold"), width=22)
        ent_monto.pack(anchor="w", pady=(2, 8))

        def on_tipo_change(*args):
            if tipo_var.get() == "LIQUIDACION_TOTAL" and saldo_pend > 0:
                monto_var.set(str(int(round(saldo_pend))))

        cb_tipo.bind("<<ComboboxSelected>>", on_tipo_change)

        tk.Label(body, text="Método de Pago (Afectación de Tesorería):", font=("Segoe UI", 9, "bold"), bg=t_d["bg_surface"], fg=t_d["text_primary"]).pack(anchor="w")
        metodo_var = tk.StringVar(value="Efectivo")
        cb_metodo = ttk.Combobox(body, textvariable=metodo_var, values=["Efectivo", "Transferencia"], state="readonly", width=28)
        cb_metodo.pack(anchor="w", pady=(2, 4))
        tk.Label(
            body,
            text="• Efectivo: descuenta de Caja Física (Control de Caja)\n• Transferencia: registra salida por Banco sin restar efectivo físico",
            font=("Segoe UI", 8), bg=t_d["bg_surface"], fg=t_d["text_muted"], justify="left"
        ).pack(anchor="w", pady=(0, 8))

        per_frame = tk.Frame(body, bg=t_d["bg_surface"])
        per_frame.pack(fill="x", pady=(0, 8))
        tk.Label(per_frame, text="Período Desde:", font=("Segoe UI", 9), bg=t_d["bg_surface"], fg=t_d["text_primary"]).pack(side="left")
        p_ini_var = tk.StringVar(value=inicio_mes_iso)
        tk.Entry(per_frame, textvariable=p_ini_var, width=11).pack(side="left", padx=(4, 12))
        tk.Label(per_frame, text="Hasta:", font=("Segoe UI", 9), bg=t_d["bg_surface"], fg=t_d["text_primary"]).pack(side="left")
        p_fin_var = tk.StringVar(value=hoy_iso)
        tk.Entry(per_frame, textvariable=p_fin_var, width=11).pack(side="left", padx=4)

        tk.Label(body, text="Responsable que autoriza:", font=("Segoe UI", 9, "bold"), bg=t_d["bg_surface"], fg=t_d["text_primary"]).pack(anchor="w")
        resp_var = tk.StringVar(value="Administrador")
        tk.Entry(body, textvariable=resp_var, width=30).pack(anchor="w", pady=(2, 8))

        tk.Label(body, text="Observaciones:", font=("Segoe UI", 9, "bold"), bg=t_d["bg_surface"], fg=t_d["text_primary"]).pack(anchor="w")
        obs_var = tk.StringVar(value="")
        tk.Entry(body, textvariable=obs_var, width=42).pack(anchor="w", pady=(2, 4))

        footer = tk.Frame(dlg, bg=t_d["bg_app"])
        footer.pack(fill="x", padx=15, pady=(0, 10))

        def confirmar_pago():
            try:
                m_limpio = float(monto_var.get().replace("$", "").replace(",", "").replace("COP", "").strip() or 0)
            except ValueError:
                messagebox.showerror("Error", "Ingrese un monto numérico válido.", parent=dlg)
                return

            if m_limpio <= 0:
                messagebox.showerror("Error", "El monto a pagar debe ser mayor a $0 COP.", parent=dlg)
                return

            res = registrar_pago_nomina(
                usuario_id=id_emp,
                monto_pagado=m_limpio,
                tipo_pago=tipo_var.get(),
                metodo_pago=metodo_var.get(),
                periodo_inicio=p_ini_var.get().strip(),
                periodo_fin=p_fin_var.get().strip(),
                responsable=resp_var.get().strip() or "Administrador",
                observaciones=obs_var.get().strip(),
                permitir_caja_cerrada=True
            )
            if not res.get("exito"):
                messagebox.showerror("No se pudo registrar el pago", res.get("mensaje", "Error desconocido"), parent=dlg)
                return

            # Sincronizar con API si está en línea y fue liquidación total
            if tipo_var.get() == "LIQUIDACION_TOTAL" and getattr(api, "token", None):
                try:
                    api.post("/nomina/liquidaciones", json={"usuario_id": id_emp})
                except Exception:
                    pass

            messagebox.showinfo(
                "✅ Pago de Nómina Registrado",
                f"{res.get('mensaje')}\n\n"
                f"• Cuenta afectada: {res.get('cuenta_afectada')}\n"
                f"• Saldo pendiente restante: {_fmt_cop(res.get('saldo_restante', 0.0))}",
                parent=dlg
            )
            dlg.destroy()
            cargar_empleados()
            actualizar_combo_meses_emp()

        crear_boton(footer, text="❌ Cancelar", command=dlg.destroy, bg=t_d["btn_secondary_bg"], fg=t_d["btn_secondary_fg"], font=("Segoe UI", 9, "bold"), padx=12, pady=6).pack(side="right", padx=5)
        crear_boton(footer, text="✅ Confirmar y Contabilizar Pago", command=confirmar_pago, bg=t_d["success"], fg="white", font=("Segoe UI", 9, "bold"), padx=12, pady=6).pack(side="right", padx=5)

    def modal_registrar_ajuste():
        sel = tree_emp.selection()
        item = sel[0] if sel else tree_emp.focus()
        if not item:
            messagebox.showwarning("Atención", "Seleccione un empleado de la tabla para aplicar un ajuste o descuento.", parent=ventana)
            return

        val = tree_emp.item(item, "values")
        id_emp = int(val[0])
        nombre = val[1]

        dlg = tk.Toplevel(ventana)
        dlg.title(f"⚖️ Ajuste / Descuento de Nómina — {nombre}")
        t_d = aplicar_tema(dlg)
        calcular_geometria_segura(dlg, 460, 400, min_w=400, min_h=360, modal_padre=ventana)
        dlg.configure(bg=t_d["bg_app"])
        dlg.transient(ventana)
        dlg.grab_set()

        tk.Label(
            dlg, text=f"⚖️ Ajuste Auditable: {nombre}",
            font=("Segoe UI", 12, "bold"), bg=t_d["primary"], fg="white", pady=10
        ).pack(fill="x")

        body = tk.Frame(dlg, bg=t_d["bg_surface"], padx=18, pady=12, bd=1, relief="solid")
        body.pack(fill="both", expand=True, padx=15, pady=10)

        tk.Label(body, text="Tipo de Ajuste:", font=("Segoe UI", 9, "bold"), bg=t_d["bg_surface"], fg=t_d["text_primary"]).pack(anchor="w")
        tipo_aj_var = tk.StringVar(value="AJUSTE_POSITIVO")
        ttk.Combobox(
            body, textvariable=tipo_aj_var,
            values=["AJUSTE_POSITIVO", "AJUSTE_NEGATIVO"],
            state="readonly", width=26
        ).pack(anchor="w", pady=(2, 8))

        tk.Label(body, text="Monto del Ajuste (COP):", font=("Segoe UI", 9, "bold"), bg=t_d["bg_surface"], fg=t_d["text_primary"]).pack(anchor="w")
        monto_aj_var = tk.StringVar(value="0")
        tk.Entry(body, textvariable=monto_aj_var, font=("Segoe UI", 11, "bold"), width=20).pack(anchor="w", pady=(2, 8))

        tk.Label(body, text="Motivo obligatorio del ajuste:", font=("Segoe UI", 9, "bold"), bg=t_d["bg_surface"], fg=t_d["text_primary"]).pack(anchor="w")
        motivo_var = tk.StringVar(value="")
        tk.Entry(body, textvariable=motivo_var, width=40).pack(anchor="w", pady=(2, 8))

        tk.Label(body, text="Responsable:", font=("Segoe UI", 9, "bold"), bg=t_d["bg_surface"], fg=t_d["text_primary"]).pack(anchor="w")
        resp_var = tk.StringVar(value="Administrador")
        tk.Entry(body, textvariable=resp_var, width=28).pack(anchor="w", pady=(2, 4))

        footer = tk.Frame(dlg, bg=t_d["bg_app"])
        footer.pack(fill="x", padx=15, pady=(0, 10))

        def guardar_ajuste():
            try:
                m_val = float(monto_aj_var.get().replace("$", "").replace(",", "").strip() or 0)
            except ValueError:
                messagebox.showerror("Error", "Ingrese un monto numérico válido.", parent=dlg)
                return

            res = registrar_ajuste_nomina(
                usuario_id=id_emp,
                monto=m_val,
                es_positivo=(tipo_aj_var.get() == "AJUSTE_POSITIVO"),
                motivo=motivo_var.get().strip(),
                responsable=resp_var.get().strip() or "Administrador"
            )
            if not res.get("exito"):
                messagebox.showerror("Error", res.get("mensaje", "No se pudo guardar el ajuste"), parent=dlg)
                return

            messagebox.showinfo("✅ Ajuste Registrado", res.get("mensaje"), parent=dlg)
            dlg.destroy()
            cargar_empleados()
            cargar_historial_emp()

        crear_boton(footer, text="❌ Cancelar", command=dlg.destroy, bg=t_d["btn_secondary_bg"], fg=t_d["btn_secondary_fg"], font=("Segoe UI", 9, "bold"), padx=12, pady=6).pack(side="right", padx=5)
        crear_boton(footer, text="💾 Guardar Ajuste", command=guardar_ajuste, bg=t_d["success"], fg="white", font=("Segoe UI", 9, "bold"), padx=12, pady=6).pack(side="right", padx=5)

    def modal_editar_configuracion():
        sel = tree_cfg.selection()
        item = sel[0] if sel else tree_cfg.focus()
        if not item:
            messagebox.showwarning("Atención", "Seleccione un empleado en la pestaña '2. Empleados y Configuración'.", parent=ventana)
            return

        val = tree_cfg.item(item, "values")
        id_emp = int(val[0])
        emp = empleados_cache.get(id_emp, {})
        nombre = emp.get("nombre_completo") or val[2]

        dlg = tk.Toplevel(ventana)
        dlg.title(f"⚙️ Configurar Nómina y Comisiones — {nombre}")
        t_d = aplicar_tema(dlg)
        calcular_geometria_segura(dlg, 480, 480, min_w=420, min_h=420, modal_padre=ventana)
        dlg.configure(bg=t_d["bg_app"])
        dlg.transient(ventana)
        dlg.grab_set()

        tk.Label(
            dlg, text=f"⚙️ Configuración de Remuneración: {nombre}",
            font=("Segoe UI", 12, "bold"), bg=t_d["primary"], fg="white", pady=10
        ).pack(fill="x")

        body = tk.Frame(dlg, bg=t_d["bg_surface"], padx=18, pady=12, bd=1, relief="solid")
        body.pack(fill="both", expand=True, padx=15, pady=10)

        tk.Label(body, text="Tipo de Remuneración:", font=("Segoe UI", 9, "bold"), bg=t_d["bg_surface"], fg=t_d["text_primary"]).pack(anchor="w")
        t_nom_var = tk.StringVar(value=emp.get("tipo_nomina", "Porcentual"))
        ttk.Combobox(body, textvariable=t_nom_var, values=["Fija", "Porcentual", "Mixta"], state="readonly", width=24).pack(anchor="w", pady=(2, 8))

        tk.Label(body, text="Salario Diario (COP):", font=("Segoe UI", 9, "bold"), bg=t_d["bg_surface"], fg=t_d["text_primary"]).pack(anchor="w")
        sal_var = tk.StringVar(value=str(int(round(float(emp.get("salario_diario", 0.0))))))
        tk.Entry(body, textvariable=sal_var, width=20, font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 8))

        tk.Label(body, text="Porcentaje de Comisión (%):", font=("Segoe UI", 9, "bold"), bg=t_d["bg_surface"], fg=t_d["text_primary"]).pack(anchor="w")
        porc_var = tk.StringVar(value=str(float(emp.get("comision_porcentaje", 0.0))))
        tk.Entry(body, textvariable=porc_var, width=20, font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 8))

        tk.Label(body, text="Regla de Activación del Salario Diario:", font=("Segoe UI", 9, "bold"), bg=t_d["bg_surface"], fg=t_d["text_primary"]).pack(anchor="w")
        regla_var = tk.StringVar(value=emp.get("regla_devengo", "PRIMERA_VENTA"))
        ttk.Combobox(body, textvariable=regla_var, values=["PRIMERA_VENTA", "ASISTENCIA_DIRECTA"], state="readonly", width=26).pack(anchor="w", pady=(2, 8))

        var_c_prod = tk.BooleanVar(value=bool(emp.get("comision_productos", 1)))
        var_c_serv = tk.BooleanVar(value=bool(emp.get("comision_servicios", 1)))
        var_c_fiad = tk.BooleanVar(value=bool(emp.get("comision_fiados", 0)))

        tk.Checkbutton(body, text="Genera comisión sobre Productos físicos", variable=var_c_prod, bg=t_d["bg_surface"], fg=t_d["text_primary"]).pack(anchor="w")
        tk.Checkbutton(body, text="Genera comisión sobre Servicios", variable=var_c_serv, bg=t_d["bg_surface"], fg=t_d["text_primary"]).pack(anchor="w")
        tk.Checkbutton(body, text="Genera comisión inmediata en ventas Fiadas no cobradas", variable=var_c_fiad, bg=t_d["bg_surface"], fg=t_d["text_primary"]).pack(anchor="w")

        footer = tk.Frame(dlg, bg=t_d["bg_app"])
        footer.pack(fill="x", padx=15, pady=(0, 10))

        def guardar_cfg():
            try:
                s_val = float(sal_var.get().replace(",", "").strip() or 0.0)
                p_val = float(porc_var.get().replace(",", "").strip() or 0.0)
            except ValueError:
                messagebox.showerror("Error", "Salario diario y porcentaje deben ser numéricos.", parent=dlg)
                return

            ok = actualizar_configuracion_empleado(
                usuario_id=id_emp,
                tipo_nomina=t_nom_var.get(),
                salario_diario=s_val,
                comision_porcentaje=p_val,
                regla_devengo=regla_var.get(),
                comision_productos=1 if var_c_prod.get() else 0,
                comision_servicios=1 if var_c_serv.get() else 0,
                comision_fiados=1 if var_c_fiad.get() else 0,
                estado=emp.get("estado", "Activo")
            )
            if ok:
                messagebox.showinfo("✅ Configuración Actualizada", f"Se actualizaron las reglas de nómina para {nombre}.", parent=dlg)
                dlg.destroy()
                cargar_empleados()
            else:
                messagebox.showerror("Error", "No se pudo actualizar la configuración.", parent=dlg)

        crear_boton(footer, text="❌ Cancelar", command=dlg.destroy, bg=t_d["btn_secondary_bg"], fg=t_d["btn_secondary_fg"], font=("Segoe UI", 9, "bold"), padx=12, pady=6).pack(side="right", padx=5)
        crear_boton(footer, text="💾 Guardar Configuración", command=guardar_cfg, bg=t_d["success"], fg="white", font=("Segoe UI", 9, "bold"), padx=12, pady=6).pack(side="right", padx=5)

    def abrir_asistencia():
        ventana_ast = tk.Toplevel(ventana)
        ventana_ast.title("Control de Asistencia Diaria")
        t_ast = aplicar_tema(ventana_ast)
        calcular_geometria_segura(ventana_ast, 560, 560, min_w=460, min_h=380, modal_padre=ventana)
        ventana_ast.configure(bg=t_ast["bg_app"])
        ventana_ast.transient(ventana)
        ventana_ast.grab_set()

        hoy = datetime.date.today().strftime('%Y-%m-%d')

        header_ast = tk.Frame(ventana_ast, bg=t_ast["bg_app"])
        header_ast.pack(fill="x", pady=(12, 4))
        tk.Label(
            header_ast, text=f"📅 Control de Asistencia — {hoy}",
            font=("Segoe UI", 13, "bold"), bg=t_ast["bg_app"], fg=t_ast["text_primary"]
        ).pack()
        tk.Label(
            header_ast,
            text="Nota (Fase 3): Para Vendedores, el salario diario se activa al registrar su primera venta válida.",
            font=("Segoe UI", 8, "italic"), bg=t_ast["bg_app"], fg=t_ast["text_muted"]
        ).pack(pady=(2, 4))

        footer_ast = tk.Frame(ventana_ast, bg=t_ast["bg_card"], bd=1, relief="ridge")
        footer_ast.pack(side="bottom", fill="x", padx=10, pady=8)

        container = ScrollableContainer(ventana_ast, bg=t_ast["bg_surface"])
        container.pack(fill="both", expand=True, padx=15, pady=5)
        scrollable_frame = container.scrollable_frame

        empleados = obtener_empleados_configuracion(incluir_inactivos=False)
        asist_hoy_list = obtener_asistencias_jornadas(fecha_inicio=hoy, fecha_fin=hoy)
        asistencias_hoy = {int(a["usuario_id"]): a for a in asist_hoy_list}

        check_vars = {}
        for emp in empleados:
            e_id = int(emp["id"])
            info_a = asistencias_hoy.get(e_id)
            est_actual = info_a.get("estado") if info_a else None
            ya_asistio = est_actual in ("Presente", "Asistencia Marcada (Sin Venta)")
            var = tk.BooleanVar(value=True if ya_asistio else False)
            est_combo_val = est_actual if est_actual in ("Presente", "Ausente", "Permiso", "Incapacidad") else ("Presente" if ya_asistio else "Presente")
            est_var = tk.StringVar(value=est_combo_val)
            check_vars[e_id] = (var, est_var, emp, est_actual)

            nombre_comp = emp.get("nombre_completo") or emp.get("usuario", "")
            rol_txt = emp.get("rol", "")
            estado_tag = f" [{est_actual}]" if est_actual else " [Sin registro hoy]"

            row_ast = tk.Frame(scrollable_frame, bg=t_ast["bg_surface"])
            row_ast.pack(fill="x", pady=4, padx=5)

            chk = tk.Checkbutton(
                row_ast,
                text=f"{nombre_comp} ({rol_txt}){estado_tag}",
                variable=var,
                font=("Segoe UI", 9, "bold" if ya_asistio else "normal"),
                bg=t_ast["bg_surface"],
                fg="#059669" if est_actual == "Presente" else t_ast["text_primary"],
                selectcolor=t_ast["input_bg"],
                activebackground=t_ast["bg_surface"]
            )
            chk.pack(side="left", anchor="w")

            cb_est = ttk.Combobox(
                row_ast,
                textvariable=est_var,
                values=["Presente", "Ausente", "Permiso", "Incapacidad"],
                state="readonly",
                width=13
            )
            cb_est.pack(side="right", padx=4)

        def guardar_asistencia():
            procesados = 0
            for e_id, (var, est_var, emp, est_prev) in check_vars.items():
                estado_sel = est_var.get()
                if var.get() or estado_sel in ("Ausente", "Permiso", "Incapacidad"):
                    registrar_asistencia_jornada(
                        usuario_id=e_id,
                        usuario_nombre=emp.get("nombre_completo"),
                        rol=emp.get("rol"),
                        fecha=hoy,
                        estado_solicitado=estado_sel if var.get() or estado_sel != "Presente" else "Ausente",
                        origen="CONTROL_ADMIN",
                        responsable="Administrador"
                    )
                    procesados += 1
                    if getattr(api, "token", None):
                        try:
                            api.post("/nomina/asistencia", json={"usuario_id": e_id, "fecha": hoy, "estado": estado_sel})
                        except Exception:
                            pass
                elif est_prev is not None and not var.get():
                    registrar_asistencia_jornada(
                        usuario_id=e_id,
                        usuario_nombre=emp.get("nombre_completo"),
                        rol=emp.get("rol"),
                        fecha=hoy,
                        estado_solicitado="Ausente",
                        origen="CONTROL_ADMIN",
                        responsable="Administrador"
                    )
                    procesados += 1
            messagebox.showinfo("✅ Éxito", f"Control de asistencia actualizado ({procesados} registro(s)) respetando las reglas de devengo por rol.", parent=ventana_ast)
            ventana_ast.destroy()
            cargar_empleados()
            cargar_asistencias()
            cargar_historial_emp()

        crear_boton(footer_ast, text="❌ Cancelar", command=ventana_ast.destroy, bg=t_ast["btn_secondary_bg"], fg=t_ast["btn_secondary_fg"], font=("Segoe UI", 9, "bold"), padx=12, pady=6).pack(side="right", padx=5)
        crear_boton(footer_ast, text="💾 Guardar Asistencia", command=guardar_asistencia, bg=t_ast["success"], fg="white", font=("Segoe UI", 9, "bold"), padx=12, pady=6).pack(side="right", padx=5)

    # Botones de la barra de acciones de Liquidaciones (Tab 1)
    crear_boton(
        liq_actions_bar, text="💸 Registrar Pago / Liquidación", command=modal_registrar_pago,
        bg=t["success"], fg="white", hover_bg="#059669", font=("Segoe UI", 10, "bold"), padx=12, pady=6
    ).pack(side="left", padx=4)
    crear_boton(
        liq_actions_bar, text="⚖️ Registrar Ajuste / Descuento", command=modal_registrar_ajuste,
        bg="#D97706", fg="white", hover_bg="#B45309", font=("Segoe UI", 10, "bold"), padx=12, pady=6
    ).pack(side="left", padx=4)
    crear_boton(
        liq_actions_bar, text="📅 Control Asistencia Hoy", command=abrir_asistencia,
        bg=t["primary"], fg="white", hover_bg="#9D174D", font=("Segoe UI", 10, "bold"), padx=12, pady=6
    ).pack(side="left", padx=4)
    crear_boton(
        liq_actions_bar, text="🔄 Actualizar", command=lambda: (cargar_empleados(), cargar_asistencias(), cargar_historial_emp()),
        bg=t["btn_secondary_bg"], fg=t["btn_secondary_fg"], font=("Segoe UI", 9, "bold"), padx=10, pady=6
    ).pack(side="right", padx=4)
    tree_emp.bind("<Double-1>", lambda e: modal_registrar_pago())

    # Botones de la barra de Configuración (Tab 2)
    crear_boton(
        cfg_btn_bar, text="⚙️ Editar Configuración del Empleado Seleccionado", command=modal_editar_configuracion,
        bg=t["primary"], fg="white", font=("Segoe UI", 10, "bold"), padx=14, pady=6
    ).pack(side="left", padx=4)
    tree_cfg.bind("<Double-1>", lambda e: modal_editar_configuracion())

    # Botones de la barra de Asistencia (Tab 3)
    crear_boton(
        ast_btn_bar, text="📅 Registrar Asistencia del Día", command=abrir_asistencia,
        bg=t["success"], fg="white", font=("Segoe UI", 10, "bold"), padx=14, pady=6
    ).pack(side="left", padx=4)

    # =========================================================================
    # SECCIÓN 5 (TAB): PAGOS PROVEEDORES, CUENTAS POR PAGAR Y LIQUIDACIONES
    # =========================================================================
    prov_paned = tk.PanedWindow(tab_proveedores, orient="horizontal", sashrelief="flat", bg=t["border"])
    prov_paned.pack(fill="both", expand=True, padx=8, pady=8)

    prov_left = tk.Frame(prov_paned, bg=t["bg_surface"], width=460)
    prov_right = tk.Frame(prov_paned, bg=t["bg_surface"])
    prov_paned.add(prov_left, minsize=380, width=460)
    prov_paned.add(prov_right, minsize=500)

    # Encabezado Panel Izquierdo
    header_left = tk.Frame(prov_left, bg=t["bg_surface"])
    header_left.pack(fill="x", pady=(4, 6), padx=4)
    tk.Label(
        header_left, text="🏢 Saldos y Cuentas de Proveedores",
        font=("Segoe UI", 12, "bold"), bg=t["bg_surface"], fg=t["primary"]
    ).pack(side="left")

    prov_tree_container = tk.Frame(prov_left, bg=t["bg_surface"])
    prov_tree_container.pack(fill="both", expand=True, padx=4)
    prov_tree_container.rowconfigure(0, weight=1)
    prov_tree_container.columnconfigure(0, weight=1)

    cols_prov = ("ID", "Proveedor", "NIT", "Ventas Acum.", "Comisión Negocio", "Total Pagado", "Saldo Pendiente")
    tree_prov = ttk.Treeview(prov_tree_container, columns=cols_prov, show="headings", selectmode="browse")
    
    tree_prov.heading("ID", text="ID")
    tree_prov.column("ID", width=40, minwidth=35, anchor="center")
    tree_prov.heading("Proveedor", text="Proveedor")
    tree_prov.column("Proveedor", width=120, minwidth=90, anchor="w")
    tree_prov.heading("NIT", text="NIT / Doc")
    tree_prov.column("NIT", width=85, minwidth=70, anchor="center")
    tree_prov.heading("Ventas Acum.", text="Ventas")
    tree_prov.column("Ventas Acum.", width=85, minwidth=70, anchor="e")
    tree_prov.heading("Comisión Negocio", text="Comisión")
    tree_prov.column("Comisión Negocio", width=85, minwidth=70, anchor="e")
    tree_prov.heading("Total Pagado", text="Pagado")
    tree_prov.column("Total Pagado", width=85, minwidth=70, anchor="e")
    tree_prov.heading("Saldo Pendiente", text="Saldo Pend.")
    tree_prov.column("Saldo Pendiente", width=95, minwidth=80, anchor="e")

    scroll_prov_y = ttk.Scrollbar(prov_tree_container, orient="vertical", command=tree_prov.yview)
    scroll_prov_x = ttk.Scrollbar(prov_tree_container, orient="horizontal", command=tree_prov.xview)
    tree_prov.configure(yscrollcommand=scroll_prov_y.set, xscrollcommand=scroll_prov_x.set)

    tree_prov.grid(row=0, column=0, sticky="nsew")
    scroll_prov_y.grid(row=0, column=1, sticky="ns")
    scroll_prov_x.grid(row=1, column=0, sticky="ew")

    # Botonera inferior izquierda
    prov_actions_bar = tk.Frame(prov_left, bg=t["bg_surface"])
    prov_actions_bar.pack(fill="x", pady=(8, 4), padx=4)

    # -------------------------------------------------------------------------
    # Panel Derecho: Ficha Resumen + Sub-Pestañas (Detalle CXP / Historial)
    # -------------------------------------------------------------------------
    card_resumen = tk.Frame(prov_right, bg=t["bg_app"], bd=1, relief="solid")
    card_resumen.pack(fill="x", padx=6, pady=(4, 6))

    card_resumen_top = tk.Frame(card_resumen, bg=t["bg_app"])
    card_resumen_top.pack(fill="x", padx=10, pady=(6, 4))

    lbl_prov_seleccionado = tk.Label(
        card_resumen_top, text="👉 Seleccione un proveedor de la tabla para ver su detalle",
        font=("Segoe UI", 11, "bold"), bg=t["bg_app"], fg=t["primary"]
    )
    lbl_prov_seleccionado.pack(side="left")

    lbl_prov_doc = tk.Label(
        card_resumen_top, text="",
        font=("Segoe UI", 9, "italic"), bg=t["bg_app"], fg=t["text_secondary"]
    )
    lbl_prov_doc.pack(side="left", padx=10)

    # Mini tarjetas de métricas en fila
    card_metrics_row = tk.Frame(card_resumen, bg=t["bg_app"])
    card_metrics_row.pack(fill="x", padx=8, pady=(0, 6))

    def _crear_mini_badge(parent, titulo, valor_inicial, color_fg=None):
        f = tk.Frame(parent, bg=t["bg_surface"], bd=1, relief="ridge", padx=8, pady=4)
        f.pack(side="left", fill="x", expand=True, padx=4)
        tk.Label(f, text=titulo, font=("Segoe UI", 8), bg=t["bg_surface"], fg=t["text_secondary"]).pack(anchor="w")
        lbl_v = tk.Label(
            f, text=valor_inicial, font=("Segoe UI", 10, "bold"),
            bg=t["bg_surface"], fg=color_fg or t["text_primary"]
        )
        lbl_v.pack(anchor="w")
        return lbl_v

    badge_saldo = _crear_mini_badge(card_metrics_row, "Saldo Pendiente", "$0 COP", color_fg=t["danger"])
    badge_ventas = _crear_mini_badge(card_metrics_row, "Total Ventas Acum.", "$0 COP", color_fg=t["primary"])
    badge_comision = _crear_mini_badge(card_metrics_row, "Comisión Negocio", "$0 COP", color_fg=t["success"])
    badge_pagado = _crear_mini_badge(card_metrics_row, "Total Liquidado", "$0 COP", color_fg=t["text_primary"])

    # Sub-Notebook para Detalle de CXP e Historial
    sub_notebook_prov = ttk.Notebook(prov_right)
    sub_notebook_prov.pack(fill="both", expand=True, padx=6, pady=4)

    subtab_cxp = tk.Frame(sub_notebook_prov, bg=t["bg_surface"])
    subtab_historial = tk.Frame(sub_notebook_prov, bg=t["bg_surface"])

    sub_notebook_prov.add(subtab_cxp, text=" 📋 Facturas y Cuentas por Pagar (CXP) ")
    sub_notebook_prov.add(subtab_historial, text=" 📜 Historial Permanente de Liquidaciones ")

    # --- Contenido Subtab 1: CXP ---
    toolbar_cxp = tk.Frame(subtab_cxp, bg=t["bg_surface"])
    toolbar_cxp.pack(fill="x", padx=6, pady=(4, 4))

    var_solo_pendientes = tk.BooleanVar(value=True)

    lbl_info_cxp = tk.Label(
        toolbar_cxp, text="Ventas de servicios asociadas al proveedor y liquidación de comisiones:",
        font=("Segoe UI", 9), bg=t["bg_surface"], fg=t["text_secondary"]
    )
    lbl_info_cxp.pack(side="left")

    def toggle_filtro_pendientes():
        id_sel = obtener_id_proveedor_seleccionado()
        if id_sel:
            cargar_detalle_cuentas_prov(id_sel)

    chk_pend = ttk.Checkbutton(
        toolbar_cxp, text="Solo deudas pendientes", variable=var_solo_pendientes,
        command=toggle_filtro_pendientes
    )
    chk_pend.pack(side="right")

    cxp_tree_container = tk.Frame(subtab_cxp, bg=t["bg_surface"])
    cxp_tree_container.pack(fill="both", expand=True, padx=6, pady=(0, 4))
    cxp_tree_container.rowconfigure(0, weight=1)
    cxp_tree_container.columnconfigure(0, weight=1)

    cols_cxp = ("ID", "Fecha", "Venta Nº", "Servicio", "Venta Total", "% Com", "Comisión", "Por Pagar", "Pagado", "Saldo", "Estado")
    tree_cxp = ttk.Treeview(cxp_tree_container, columns=cols_cxp, show="headings", selectmode="browse")

    col_widths_cxp = {
        "ID": (40, "center"),
        "Fecha": (110, "center"),
        "Venta Nº": (65, "center"),
        "Servicio": (130, "w"),
        "Venta Total": (85, "e"),
        "% Com": (50, "center"),
        "Comisión": (80, "e"),
        "Por Pagar": (85, "e"),
        "Pagado": (80, "e"),
        "Saldo": (85, "e"),
        "Estado": (75, "center")
    }
    for c, (w, anch) in col_widths_cxp.items():
        tree_cxp.heading(c, text=c)
        tree_cxp.column(c, width=w, minwidth=40, anchor=anch)

    scroll_cxp_y = ttk.Scrollbar(cxp_tree_container, orient="vertical", command=tree_cxp.yview)
    scroll_cxp_x = ttk.Scrollbar(cxp_tree_container, orient="horizontal", command=tree_cxp.xview)
    tree_cxp.configure(yscrollcommand=scroll_cxp_y.set, xscrollcommand=scroll_cxp_x.set)

    tree_cxp.grid(row=0, column=0, sticky="nsew")
    scroll_cxp_y.grid(row=0, column=1, sticky="ns")
    scroll_cxp_x.grid(row=1, column=0, sticky="ew")

    # --- Contenido Subtab 2: Historial Permanente ---
    toolbar_hist = tk.Frame(subtab_historial, bg=t["bg_surface"])
    toolbar_hist.pack(fill="x", padx=6, pady=(4, 4))

    tk.Label(toolbar_hist, text="Filtro Mes:", font=("Segoe UI", 9), bg=t["bg_surface"], fg=t["text_primary"]).pack(side="left")
    mes_prov_var = tk.StringVar(value="Todos")
    combo_mes_prov = ttk.Combobox(toolbar_hist, textvariable=mes_prov_var, state="readonly", width=12, font=("Segoe UI", 9))
    combo_mes_prov.pack(side="left", padx=(6, 15))

    lbl_hist_info = tk.Label(
        toolbar_hist, text="Historial inmutable de comprobantes y recibos de pago:",
        font=("Segoe UI", 9), bg=t["bg_surface"], fg=t["text_secondary"]
    )
    lbl_hist_info.pack(side="left")

    hist_tree_container = tk.Frame(subtab_historial, bg=t["bg_surface"])
    hist_tree_container.pack(fill="both", expand=True, padx=6, pady=(0, 4))
    hist_tree_container.rowconfigure(0, weight=1)
    hist_tree_container.columnconfigure(0, weight=1)

    cols_hist_prov = ("Nº Recibo", "Fecha", "Proveedor", "Monto", "Método", "Saldo Ant.", "Saldo Rest.", "Usuario", "Comprobante", "Estado")
    tree_hist_prov = ttk.Treeview(hist_tree_container, columns=cols_hist_prov, show="headings", selectmode="browse")

    col_widths_hist = {
        "Nº Recibo": (70, "center"),
        "Fecha": (115, "center"),
        "Proveedor": (120, "w"),
        "Monto": (90, "e"),
        "Método": (75, "center"),
        "Saldo Ant.": (85, "e"),
        "Saldo Rest.": (85, "e"),
        "Usuario": (90, "w"),
        "Comprobante": (95, "center"),
        "Estado": (70, "center")
    }
    for c, (w, anch) in col_widths_hist.items():
        tree_hist_prov.heading(c, text=c)
        tree_hist_prov.column(c, width=w, minwidth=40, anchor=anch)

    scroll_hist_prov_y = ttk.Scrollbar(hist_tree_container, orient="vertical", command=tree_hist_prov.yview)
    scroll_hist_prov_x = ttk.Scrollbar(hist_tree_container, orient="horizontal", command=tree_hist_prov.xview)
    tree_hist_prov.configure(yscrollcommand=scroll_hist_prov_y.set, xscrollcommand=scroll_hist_prov_x.set)

    tree_hist_prov.grid(row=0, column=0, sticky="nsew")
    scroll_hist_prov_y.grid(row=0, column=1, sticky="ns")
    scroll_hist_prov_x.grid(row=1, column=0, sticky="ew")

    # -------------------------------------------------------------------------
    # Funciones de Soporte y Carga
    # -------------------------------------------------------------------------
    def obtener_id_proveedor_seleccionado():
        sel = tree_prov.selection()
        if not sel:
            return None
        try:
            return int(tree_prov.item(sel[0], "values")[0])
        except Exception:
            return None

    def obtener_datos_proveedor_seleccionado():
        sel = tree_prov.selection()
        if not sel:
            return None
        try:
            vals = tree_prov.item(sel[0], "values")
            return {
                "id": int(vals[0]),
                "nombre": vals[1],
                "documento_nit": vals[2],
                "total_ventas": vals[3],
                "total_comisiones": vals[4],
                "total_pagado": vals[5],
                "saldo_pendiente": vals[6]
            }
        except Exception:
            return None

    def cargar_detalle_cuentas_prov(id_prov):
        for i in tree_cxp.get_children():
            tree_cxp.delete(i)
        if not id_prov:
            return
        solo_pend = var_solo_pendientes.get()
        cuentas = obtener_detalle_cuentas_proveedor(id_prov, solo_pendientes=solo_pend)
        for c in cuentas:
            pct_str = f"{c.get('porcentaje_comision', 0.0):.1f}%"
            estado_tag = c.get("estado", "")
            tree_cxp.insert("", "end", values=(
                c.get("id"),
                c.get("fecha_venta", ""),
                f"#{c.get('venta_id')}" if c.get("venta_id") else "Manual",
                c.get("servicio_nombre", ""),
                _fmt_cop(c.get("precio_venta", 0.0)),
                pct_str,
                _fmt_cop(c.get("monto_comision", 0.0)),
                _fmt_cop(c.get("monto_por_pagar", 0.0)),
                _fmt_cop(c.get("monto_pagado", 0.0)),
                _fmt_cop(c.get("saldo_pendiente", 0.0)),
                estado_tag
            ))

    def on_proveedor_seleccionado(event=None):
        datos = obtener_datos_proveedor_seleccionado()
        if not datos:
            lbl_prov_seleccionado.config(text="👉 Seleccione un proveedor de la tabla para ver su detalle")
            lbl_prov_doc.config(text="")
            badge_saldo.config(text="$0 COP", fg=t["text_primary"])
            badge_ventas.config(text="$0 COP")
            badge_comision.config(text="$0 COP")
            badge_pagado.config(text="$0 COP")
            for i in tree_cxp.get_children():
                tree_cxp.delete(i)
            return

        lbl_prov_seleccionado.config(text=f"🏢 {datos['nombre']}")
        doc = datos.get("documento_nit") or "Sin NIT"
        lbl_prov_doc.config(text=f"NIT / Doc: {doc}")

        badge_ventas.config(text=str(datos.get("total_ventas", "$0 COP")))
        badge_comision.config(text=str(datos.get("total_comisiones", "$0 COP")))
        badge_pagado.config(text=str(datos.get("total_pagado", "$0 COP")))

        saldo_str = str(datos.get("saldo_pendiente", "$0 COP"))
        badge_saldo.config(text=saldo_str)
        try:
            val_num = float(saldo_str.replace("$", "").replace("COP", "").replace(",", "").strip() or 0)
            if val_num > 0:
                badge_saldo.config(fg=t["danger"])
            else:
                badge_saldo.config(fg=t["success"])
        except Exception:
            badge_saldo.config(fg=t["text_primary"])

        cargar_detalle_cuentas_prov(datos["id"])

    tree_prov.bind("<<TreeviewSelect>>", on_proveedor_seleccionado)

    def cargar_proveedores():
        selected_id = obtener_id_proveedor_seleccionado()

        for i in tree_prov.get_children():
            tree_prov.delete(i)

        proveedores = obtener_resumen_proveedores(solo_activos=False)
        item_to_select = None

        for p in proveedores:
            item_id = tree_prov.insert("", "end", values=(
                p["id"],
                p["nombre"],
                p.get("documento_nit") or "N/A",
                _fmt_cop(p["total_ventas"]),
                _fmt_cop(p["total_comisiones"]),
                _fmt_cop(p["total_pagado"]),
                _fmt_cop(p["saldo_pendiente"])
            ))
            if selected_id is not None and str(p["id"]) == str(selected_id):
                item_to_select = item_id

        if item_to_select:
            tree_prov.selection_set(item_to_select)
            tree_prov.focus(item_to_select)
            on_proveedor_seleccionado()
        elif tree_prov.get_children():
            primer = tree_prov.get_children()[0]
            tree_prov.selection_set(primer)
            tree_prov.focus(primer)
            on_proveedor_seleccionado()
        else:
            on_proveedor_seleccionado()

    def cargar_historial_prov(*args):
        for i in tree_hist_prov.get_children():
            tree_hist_prov.delete(i)
        filtro_mes = mes_prov_var.get()
        hist = obtener_historial_liquidaciones_proveedor(mes_anio=filtro_mes)
        for r in hist:
            monto_val = float(r.get("monto_liquidado", 0.0) or 0.0)
            fecha_val = r.get("fecha_pago", "")
            tree_hist_prov.insert("", "end", values=(
                r.get("numero_recibo", f"LP-{r.get('id')}"),
                fecha_val,
                r.get("proveedor_nombre", ""),
                _fmt_cop(monto_val),
                r.get("metodo_pago", "Efectivo"),
                _fmt_cop(r.get("saldo_anterior", 0.0)),
                _fmt_cop(r.get("saldo_restante", 0.0)),
                r.get("usuario_nombre", "Admin"),
                r.get("referencia_comprobante", "") or "N/A",
                r.get("estado", "Aplicado")
            ))

    def actualizar_combo_meses_prov():
        hist = obtener_historial_liquidaciones_proveedor()
        meses = ["Todos"]
        if hist:
            meses_set = set()
            for r in hist:
                f_str = r.get("fecha_pago", "")
                if len(f_str) >= 7:
                    meses_set.add(f_str[5:7] + "-" + f_str[0:4])
            meses.extend(sorted(list(meses_set), reverse=True))
        combo_mes_prov['values'] = meses
        if not mes_prov_var.get() or mes_prov_var.get() not in meses:
            mes_prov_var.set("Todos")
        cargar_historial_prov()

    combo_mes_prov.bind("<<ComboboxSelected>>", cargar_historial_prov)

    # -------------------------------------------------------------------------
    # MODAL DE LIQUIDACIÓN Y ABONO PARCIAL
    # -------------------------------------------------------------------------
    def abrir_dialogo_liquidacion():
        datos = obtener_datos_proveedor_seleccionado()
        if not datos:
            messagebox.showwarning("Atención", "Seleccione un proveedor de la tabla para realizar una liquidación o abono.")
            return

        id_prov = datos["id"]
        nombre = datos["nombre"]
        doc = datos.get("documento_nit") or "Sin documento"

        # Obtener saldo fresco recalculado directamente de base de datos
        res_calc = recalcular_saldo_proveedor(id_prov)
        saldo_actual = float(res_calc.get("saldo_pendiente", 0.0))

        if saldo_actual <= 0:
            messagebox.showinfo(
                "Sin saldo pendiente",
                f"El proveedor '{nombre}' se encuentra al día. No tiene saldo pendiente por liquidar ($0 COP)."
            )
            return

        # Modal
        modal = tk.Toplevel(ventana)
        modal.title(f"💸 Pago a Proveedor - {nombre}")
        modal.transient(ventana)
        modal.grab_set()
        modal.configure(bg=t["bg_app"])
        calcular_geometria_segura(modal, 520, 560, min_w=480, min_h=500)

        # Encabezado
        f_top = tk.Frame(modal, bg=t["primary"], padx=16, pady=12)
        f_top.pack(fill="x")
        tk.Label(
            f_top, text="Liquidación / Abono a Proveedor",
            font=("Segoe UI", 13, "bold"), fg="white", bg=t["primary"]
        ).pack(anchor="w")
        tk.Label(
            f_top, text=f"Beneficiario: {nombre} | NIT: {doc}",
            font=("Segoe UI", 10), fg="#E0E7FF", bg=t["primary"]
        ).pack(anchor="w", pady=(2, 0))

        # Cuerpo del formulario
        body = tk.Frame(modal, bg=t["bg_app"], padx=20, pady=16)
        body.pack(fill="both", expand=True)

        # Tarjeta saldo actual
        f_saldo = tk.Frame(body, bg=t["bg_surface"], bd=1, relief="ridge", padx=12, pady=10)
        f_saldo.pack(fill="x", pady=(0, 14))
        tk.Label(
            f_saldo, text="Saldo Pendiente Acumulado:",
            font=("Segoe UI", 9), bg=t["bg_surface"], fg=t["text_secondary"]
        ).pack(anchor="w")
        tk.Label(
            f_saldo, text=_fmt_cop(saldo_actual),
            font=("Segoe UI", 16, "bold"), bg=t["bg_surface"], fg=t["danger"]
        ).pack(anchor="w")

        # Tipo de Operación: Total vs Abono
        tipo_op_var = tk.StringVar(value="TOTAL")
        f_tipo = tk.Frame(body, bg=t["bg_app"])
        f_tipo.pack(fill="x", pady=(0, 10))
        tk.Label(f_tipo, text="Tipo de Pago:", font=("Segoe UI", 10, "bold"), bg=t["bg_app"], fg=t["text_primary"]).pack(anchor="w", pady=(0, 4))

        f_radios = tk.Frame(f_tipo, bg=t["bg_app"])
        f_radios.pack(fill="x")

        # Campo Monto
        f_monto = tk.Frame(body, bg=t["bg_app"])
        f_monto.pack(fill="x", pady=(0, 10))
        tk.Label(f_monto, text="Monto a Pagar (COP):", font=("Segoe UI", 10, "bold"), bg=t["bg_app"], fg=t["text_primary"]).pack(anchor="w")
        e_monto = ttk.Entry(f_monto, font=("Segoe UI", 11, "bold"))
        e_monto.pack(fill="x", pady=(3, 2))
        e_monto.insert(0, str(int(saldo_actual)))

        lbl_preview = tk.Label(
            f_monto, text=f"Saldo restante tras el pago: $0 COP",
            font=("Segoe UI", 9, "italic"), bg=t["bg_app"], fg=t["success"]
        )
        lbl_preview.pack(anchor="w")

        def actualizar_monto_por_tipo():
            if tipo_op_var.get() == "TOTAL":
                e_monto.delete(0, "end")
                e_monto.insert(0, str(int(saldo_actual)))
                e_monto.config(state="readonly")
            else:
                e_monto.config(state="normal")
                e_monto.focus()
            recalcular_preview()

        r_total = ttk.Radiobutton(
            f_radios, text="Liquidación Total (Pagar 100% de la deuda)",
            variable=tipo_op_var, value="TOTAL", command=actualizar_monto_por_tipo
        )
        r_total.pack(anchor="w", pady=2)

        r_abono = ttk.Radiobutton(
            f_radios, text="Abono Parcial (Definir monto a abonar)",
            variable=tipo_op_var, value="ABONO", command=actualizar_monto_por_tipo
        )
        r_abono.pack(anchor="w", pady=2)

        def recalcular_preview(*args):
            txt = e_monto.get().strip().replace("$", "").replace(",", "")
            try:
                val = float(txt or 0.0)
                if val <= 0:
                    lbl_preview.config(text="⚠️ Ingrese un valor mayor a $0", fg=t["danger"])
                elif val > saldo_actual + 0.01:
                    lbl_preview.config(
                        text=f"⚠️ El monto supera el saldo adeudado ({_fmt_cop(saldo_actual)})",
                        fg=t["danger"]
                    )
                else:
                    restante = max(0.0, saldo_actual - val)
                    lbl_preview.config(text=f"Saldo restante tras el pago: {_fmt_cop(restante)}", fg=t["primary"])
            except Exception:
                lbl_preview.config(text="⚠️ Monto inválido", fg=t["danger"])

        e_monto.bind("<KeyRelease>", recalcular_preview)
        actualizar_monto_por_tipo()

        # Método de Pago
        f_metodo = tk.Frame(body, bg=t["bg_app"])
        f_metodo.pack(fill="x", pady=(0, 10))
        tk.Label(f_metodo, text="Método de Pago:", font=("Segoe UI", 10, "bold"), bg=t["bg_app"], fg=t["text_primary"]).pack(anchor="w")
        var_metodo = tk.StringVar(value="Efectivo")
        combo_metodo = ttk.Combobox(
            f_metodo, textvariable=var_metodo,
            values=["Efectivo", "Transferencia"], state="readonly", font=("Segoe UI", 10)
        )
        combo_metodo.pack(fill="x", pady=(3, 2))

        lbl_nota_metodo = tk.Label(
            f_metodo,
            text="💵 Efectivo: Se descuenta de la caja registradora activa.",
            font=("Segoe UI", 8), bg=t["bg_app"], fg=t["text_secondary"]
        )
        lbl_nota_metodo.pack(anchor="w")

        def on_metodo_change(event=None):
            if var_metodo.get() == "Efectivo":
                lbl_nota_metodo.config(text="💵 Efectivo: Se descuenta de la caja registradora activa.")
            else:
                lbl_nota_metodo.config(text="🏦 Transferencia: Egresa del banco sin alterar el dinero en caja física.")

        combo_metodo.bind("<<ComboboxSelected>>", on_metodo_change)

        # Referencia y Notas
        f_extra = tk.Frame(body, bg=t["bg_app"])
        f_extra.pack(fill="x", pady=(0, 10))

        tk.Label(f_extra, text="Nº Comprobante / Referencia (Opcional):", font=("Segoe UI", 9), bg=t["bg_app"], fg=t["text_primary"]).pack(anchor="w")
        e_ref = ttk.Entry(f_extra, font=("Segoe UI", 10))
        e_ref.pack(fill="x", pady=(2, 6))

        tk.Label(f_extra, text="Observaciones / Notas:", font=("Segoe UI", 9), bg=t["bg_app"], fg=t["text_primary"]).pack(anchor="w")
        e_notas = ttk.Entry(f_extra, font=("Segoe UI", 10))
        e_notas.pack(fill="x", pady=(2, 0))

        # Botones de Acción
        f_btns = tk.Frame(modal, bg=t["bg_surface"], padx=16, pady=12)
        f_btns.pack(fill="x", side="bottom")

        def procesar_pago():
            try:
                monto_val = float(e_monto.get().strip().replace("$", "").replace(",", "") or 0.0)
            except Exception:
                messagebox.showerror("Error", "Ingrese un monto numérico válido.", parent=modal)
                return

            if monto_val <= 0:
                messagebox.showerror("Error", "El monto a liquidar debe ser estrictamente mayor a 0.", parent=modal)
                return

            if monto_val > saldo_actual + 0.01:
                messagebox.showerror(
                    "Error",
                    f"El monto a pagar ({_fmt_cop(monto_val)}) no puede ser superior al saldo pendiente ({_fmt_cop(saldo_actual)}).",
                    parent=modal
                )
                return

            metodo = var_metodo.get()
            ref = e_ref.get().strip()
            notas = e_notas.get().strip()

            msg_confirm = (
                f"¿Confirmar pago a '{nombre}'?\n\n"
                f"• Monto a pagar: {_fmt_cop(monto_val)}\n"
                f"• Método: {metodo}\n"
                f"• Saldo que quedará pendiente: {_fmt_cop(max(0.0, saldo_actual - monto_val))}\n\n"
                f"Esta operación es irreversible y afectará la contabilidad operativa."
            )

            if not messagebox.askyesno("Confirmar Pago", msg_confirm, parent=modal):
                return

            # Protección contra doble clic
            btn_confirmar.config(state="disabled", text="⏳ Procesando pago...")
            modal.update_idletasks()

            try:
                res = liquidar_proveedor_db(
                    proveedor_id=id_prov,
                    monto_abono=monto_val,
                    metodo_pago=metodo,
                    referencia_comprobante=ref,
                    usuario_nombre="Administrador",
                    notas=notas
                )

                if res.get("exito"):
                    recibo = res.get("numero_recibo", "")
                    messagebox.showinfo(
                        "✅ Pago Registrado con Éxito",
                        f"Se registró correctamente el pago a '{nombre}'.\n\n"
                        f"• Recibo: {recibo}\n"
                        f"• Monto Pagado: {_fmt_cop(res.get('monto_pagado', monto_val))}\n"
                        f"• Saldo Restante: {_fmt_cop(res.get('saldo_restante', 0.0))}\n"
                        f"• Medio: {metodo}\n"
                        f"• Facturas liquidadas: {res.get('cuentas_afectadas', 0)}",
                        parent=ventana
                    )
                    modal.destroy()
                    cargar_proveedores()
                    actualizar_combo_meses_prov()
                else:
                    messagebox.showerror(
                        "Error al liquidar",
                        f"No se pudo completar el pago:\n{res.get('mensaje', 'Error desconocido')}",
                        parent=modal
                    )
                    btn_confirmar.config(state="normal", text="✅ Confirmar Pago")
            except Exception as ex:
                messagebox.showerror("Error", f"Fallo de ejecución al registrar pago: {ex}", parent=modal)
                btn_confirmar.config(state="normal", text="✅ Confirmar Pago")

        btn_cancelar = crear_boton(
            f_btns, text="Cancelar", command=modal.destroy,
            bg=t["bg_app"], fg=t["text_primary"], hover_bg="#CBD5E1",
            font=("Segoe UI", 10), padx=14, pady=6
        )
        btn_cancelar.pack(side="right", padx=6)

        btn_confirmar = crear_boton(
            f_btns, text="✅ Confirmar Pago", command=procesar_pago,
            bg=t["success"], fg="white", hover_bg="#059669",
            font=("Segoe UI", 10, "bold"), padx=18, pady=6
        )
        btn_confirmar.pack(side="right", padx=6)

    def revertir_pago_seleccionado():
        sel = tree_hist_prov.selection()
        if not sel:
            messagebox.showwarning("Atención", "Seleccione una liquidación de la tabla de historial para revertir.")
            return

        vals = tree_hist_prov.item(sel[0], "values")
        recibo = vals[0]
        prov_nom = vals[2]
        monto_str = vals[3]
        estado = vals[9]

        if estado == "Anulado":
            messagebox.showwarning("Operación no válida", f"El recibo {recibo} ya se encuentra anulado.")
            return

        # Extraer ID de liquidación
        try:
            liq_id = int(recibo.replace("LP-", "").strip())
        except Exception:
            liq_id = None

        if not liq_id:
            messagebox.showerror("Error", "No se pudo identificar el identificador del recibo.")
            return

        if not messagebox.askyesno(
            "Confirmar Reversión",
            f"¿Desea revertir y anular la liquidación {recibo} de '{prov_nom}' por {monto_str}?\n\n"
            f"Esto reabrirá las cuentas por pagar asociadas y revertirá los movimientos contables."
        ):
            return

        res = revertir_liquidacion_proveedor_db(liq_id, usuario_nombre="Administrador")
        if res.get("exito"):
            messagebox.showinfo("✅ Liquidación Revertida", f"La liquidación {recibo} fue revertida con éxito.")
            cargar_proveedores()
            actualizar_combo_meses_prov()
        else:
            messagebox.showerror("Error", f"No se pudo revertir la liquidación: {res.get('mensaje')}")

    # Enlazar botones principales
    crear_boton(
        prov_actions_bar, text="💸 Liquidar / Abonar", command=abrir_dialogo_liquidacion,
        bg=t["success"], fg="white", hover_bg="#059669", font=("Segoe UI", 11, "bold"), padx=14, pady=7
    ).pack(side="left", padx=4)

    crear_boton(
        prov_actions_bar, text="🔄 Actualizar", command=cargar_proveedores,
        bg=t["bg_app"], fg=t["text_primary"], hover_bg="#CBD5E1", font=("Segoe UI", 10), padx=10, pady=7
    ).pack(side="left", padx=4)

    crear_boton(
        toolbar_hist, text="🔄 Revertir Pago", command=revertir_pago_seleccionado,
        bg=t["danger"], fg="white", hover_bg="#DC2626", font=("Segoe UI", 9, "bold"), padx=10, pady=4
    ).pack(side="right")

    def auto_refresco_nomina():
        try:
            if ventana.winfo_exists():
                cargar_empleados()
                cargar_proveedores()
        except Exception as e:
            print(f"Error en auto-refresco nómina: {e}")
        finally:
            try:
                if ventana.winfo_exists():
                    tid = ventana.after(8000, auto_refresco_nomina)
                    session_mgr.registrar_timer(ventana, tid)
            except Exception:
                pass

    cargar_empleados()
    cargar_asistencias()
    actualizar_combo_meses_emp()
    cargar_proveedores()
    actualizar_combo_meses_prov()
    auto_refresco_nomina()

    if not parent:
        ventana.mainloop()
    return ventana


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Nómina y Proveedores VmPOS")
    parser.add_argument("--parent_pid", default="")
    if "-h" in sys.argv or "--help" in sys.argv:
        parser.print_help()
        sys.exit(0)
    args, _ = parser.parse_known_args()
    parent_pid = args.parent_pid or os.environ.get("VMPOS_PARENT_PID", "")
    iniciar_nomina(parent_pid=parent_pid)
