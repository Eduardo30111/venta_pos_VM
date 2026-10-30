"""
Módulo Profesional de Control de Gastos - VmPOS
Incluye:
- Clasificación en 4 categorías contables: Operativo diario, Fijo periódico, Variable, Extraordinario (+ personalizadas).
- Estados de gasto: Pagado, Pendiente, Vencido, Anulado.
- Motor de gastos recurrentes (arriendo, servicios, suscripciones) sin duplicidad por reinicio.
- Impacto contable estricto: Una obligación pendiente no descuenta caja física hasta que se liquida en Efectivo.
- 3 Vistas: 1) Registro y Lista de Gastos, 2) Gastos Recurrentes, 3) Dashboard de Gastos.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timedelta
import os
import sys
import sqlite3

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from client.api_client import api
from interface.business_manager import business_mgr
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
    from caja_manager import (
        conectar_db as conectar_sqlite,
        registrar_movimiento_caja,
        obtener_sesion_activa,
        procesar_gastos_recurrentes,
        pagar_gasto
    )
except ImportError:
    from interface.caja_manager import (
        conectar_db as conectar_sqlite,
        registrar_movimiento_caja,
        obtener_sesion_activa,
        procesar_gastos_recurrentes,
        pagar_gasto
    )

CATEGORIAS_GASTO = [
    "Operativo diario",
    "Fijo periódico",
    "Variable",
    "Extraordinario"
]

FRECUENCIAS = ["Diaria", "Semanal", "Quincenal", "Mensual", "Anual"]


# ==============================================================================
# FUNCIONES DE BASE DE DATOS
# ==============================================================================

def obtener_gastos_db(filtro_periodo="Todos", filtro_cat="Todas", filtro_estado="Todos", busqueda=""):
    """Consulta gastos con filtros contables y búsqueda."""
    conn = conectar_sqlite()
    if not conn:
        return []
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        query = """
            SELECT 
                id_gasto, concepto, valor, fecha, hora, metodo_pago,
                COALESCE(categoria, clasificacion, 'Operativo diario') as categoria,
                COALESCE(estado, 'Pagado') as estado,
                fecha_vencimiento, fecha_pago, proveedor, comprobante, observaciones,
                es_recurrente
            FROM gastos
            WHERE 1=1
        """
        params = []

        # Filtro de periodo
        hoy = datetime.now()
        hoy_str = hoy.strftime("%Y-%m-%d")
        if filtro_periodo == "Hoy":
            query += " AND fecha = ?"
            params.append(hoy_str)
        elif filtro_periodo == "Ayer":
            ayer_str = (hoy - timedelta(days=1)).strftime("%Y-%m-%d")
            query += " AND fecha = ?"
            params.append(ayer_str)
        elif filtro_periodo == "Esta semana":
            inicio_sem = (hoy - timedelta(days=hoy.weekday())).strftime("%Y-%m-%d")
            query += " AND fecha BETWEEN ? AND ?"
            params.extend([inicio_sem, hoy_str])
        elif filtro_periodo == "Este mes":
            inicio_mes = hoy.strftime("%Y-%m-01")
            query += " AND fecha BETWEEN ? AND ?"
            params.extend([inicio_mes, hoy_str])

        # Filtro de categoría
        if filtro_cat != "Todas":
            query += " AND (categoria = ? OR clasificacion = ?)"
            params.extend([filtro_cat, filtro_cat])

        # Filtro de estado
        if filtro_estado != "Todos":
            query += " AND estado = ?"
            params.append(filtro_estado)

        # Búsqueda libre
        if busqueda:
            query += " AND (concepto LIKE ? OR proveedor LIKE ? OR comprobante LIKE ?)"
            patron = f"%{busqueda}%"
            params.extend([patron, patron, patron])

        query += " ORDER BY id_gasto DESC"
        cur.execute(query, params)
        rows = cur.fetchall()
        
        # Actualizar automáticamente a 'Vencido' si es Pendiente y pasó la fecha de vencimiento
        gastos = []
        for r in rows:
            g = dict(r)
            if g.get("estado") == "Pendiente" and g.get("fecha_vencimiento"):
                if g["fecha_vencimiento"] < hoy_str:
                    g["estado"] = "Vencido"
            gastos.append(g)
        return gastos
    finally:
        conn.close()


def registrar_nuevo_gasto(
    concepto: str,
    valor: float,
    categoria: str = "Operativo diario",
    metodo_pago: str = "Efectivo",
    estado: str = "Pagado",
    fecha_vencimiento: str = "",
    proveedor: str = "",
    comprobante: str = "",
    observaciones: str = "",
    usuario: str = "Administrador"
) -> bool:
    """Inserta un gasto. Si es Pagado en Efectivo, descuenta de la sesión física de caja."""
    conn = conectar_sqlite()
    if not conn:
        return False
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        ahora = datetime.now()
        fecha_str = ahora.strftime("%Y-%m-%d")
        hora_str = ahora.strftime("%H:%M:%S")
        fecha_pago_val = f"{fecha_str} {hora_str}" if estado == "Pagado" else None

        cur.execute("""
            INSERT INTO gastos (
                concepto, valor, fecha, hora, metodo_pago, categoria, clasificacion,
                descripcion, fecha_vencimiento, fecha_pago, frecuencia, estado,
                usuario, proveedor, comprobante, observaciones, es_recurrente, recurrencia_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Único', ?, ?, ?, ?, ?, 0, NULL)
        """, (
            concepto, valor, fecha_str, hora_str, metodo_pago, categoria, categoria,
            observaciones, fecha_vencimiento or None, fecha_pago_val, estado,
            usuario, proveedor, comprobante, observaciones
        ))
        id_gasto = cur.lastrowid

        # Si se crea como PAGADO, registrar impacto en libro mayor según medio de pago
        if estado == "Pagado":
            activa = obtener_sesion_activa()
            sesion_id = activa["id"] if activa else None
            cuenta = "CAJA_FISICA" if metodo_pago == "Efectivo" else "BANCO_TRANSFERENCIA"
            try:
                cur.execute("""
                    INSERT INTO movimientos_financieros (
                        fecha, hora, tipo, concepto, monto, metodo_pago,
                        cuenta_afectada, usuario, referencia_origen, sesion_caja_id,
                        estado, observaciones
                    ) VALUES (?, ?, 'GASTO_PAGADO', ?, ?, ?, ?, ?, ?, ?, 'Activo', ?)
                """, (
                    fecha_str, hora_str, f"Gasto #{id_gasto}: {concepto} ({categoria})",
                    float(valor), metodo_pago, cuenta, usuario, f"GASTO-{id_gasto}",
                    sesion_id, f"Proveedor: {proveedor or 'Varios'}"
                ))
            except Exception:
                pass

            if metodo_pago == "Efectivo":
                cur.execute("PRAGMA table_info(movimientos_caja)")
                cols_m = [c[1] for c in cur.fetchall()]
                col_sesion = "sesion_id" if "sesion_id" in cols_m else "sesion_caja_id"
                col_concepto = "concepto" if "concepto" in cols_m else "descripcion"
                col_ref = "id_referencia" if "id_referencia" in cols_m else "referencia_id"

                if "terminal" in cols_m:
                    cur.execute(f"""
                        INSERT INTO movimientos_caja (
                            {col_sesion}, fecha, hora, tipo, monto, usuario, terminal, {col_ref}, {col_concepto}
                        ) VALUES (?, ?, ?, 'EGRESO', ?, ?, 'Terminal-1', ?, ?)
                    """, (sesion_id, fecha_str, hora_str, valor, usuario, str(id_gasto), f"Gasto #{id_gasto}: {concepto} ({categoria})"))
                else:
                    cur.execute(f"""
                        INSERT INTO movimientos_caja (
                            {col_sesion}, fecha, hora, tipo, monto, usuario, {col_ref}, {col_concepto}
                        ) VALUES (?, ?, ?, 'EGRESO', ?, ?, ?, ?)
                    """, (sesion_id, fecha_str, hora_str, valor, usuario, str(id_gasto), f"Gasto #{id_gasto}: {concepto} ({categoria})"))

        conn.commit()
        return True
    except Exception as e:
        print(f"[ERROR] registrar_nuevo_gasto: {e}")
        return False
    finally:
        conn.close()


def anular_gasto_db(id_gasto: int) -> bool:
    """Marca un gasto como Anulado y actualiza la trazabilidad financiera."""
    conn = conectar_sqlite()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("UPDATE gastos SET estado = 'Anulado' WHERE id_gasto = ?", (id_gasto,))
        try:
            cur.execute("""
                UPDATE movimientos_financieros 
                SET estado = 'Anulado', observaciones = observaciones || ' | Gasto anulado'
                WHERE referencia_origen = ?
            """, (f"GASTO-{id_gasto}",))
        except Exception:
            pass
        conn.commit()
        return True
    finally:
        conn.close()


def obtener_recurrentes_db():
    """Retorna todas las reglas de gastos recurrentes."""
    conn = conectar_sqlite()
    if not conn:
        return []
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM gastos_recurrentes ORDER BY id DESC")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def guardar_recurrente_db(concepto, valor, frecuencia, categoria, dia_corte, proveedor, metodo_defecto, id_rec=None):
    """Crea o actualiza una regla de gasto recurrente."""
    conn = conectar_sqlite()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        if id_rec:
            cur.execute("""
                UPDATE gastos_recurrentes SET
                    concepto = ?, valor = ?, frecuencia = ?, categoria = ?, clasificacion = ?,
                    dia_corte = ?, proveedor = ?, metodo_pago_defecto = ?
                WHERE id = ?
            """, (concepto, valor, frecuencia, categoria, categoria, dia_corte, proveedor, metodo_defecto, id_rec))
        else:
            cur.execute("""
                INSERT INTO gastos_recurrentes (
                    concepto, valor, frecuencia, categoria, clasificacion, dia_corte, proveedor, metodo_pago_defecto, activo
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (concepto, valor, frecuencia, categoria, categoria, dia_corte, proveedor, metodo_defecto))
        conn.commit()
        return True
    finally:
        conn.close()


def toggle_activo_recurrente_db(id_rec, estado_actual):
    """Pausa o activa una regla recurrente."""
    conn = conectar_sqlite()
    if not conn:
        return False
    try:
        nuevo = 0 if estado_actual == 1 else 1
        cur = conn.cursor()
        cur.execute("UPDATE gastos_recurrentes SET activo = ? WHERE id = ?", (nuevo, id_rec))
        conn.commit()
        return True
    finally:
        conn.close()


# ==============================================================================
# INTERFAZ GRÁFICA PROFESIONAL
# ==============================================================================

def iniciar_gastos(parent_pid="", parent=None):
    # Procesar recurrentes pendientes al abrir
    try:
        nuevos_rec = procesar_gastos_recurrentes()
    except Exception:
        nuevos_rec = 0

    if parent:
        ventana = tk.Toplevel(parent)
    else:
        ventana = tk.Tk()
    parent_pid = parent_pid or os.environ.get("VMPOS_PARENT_PID", "")
    session_mgr.iniciar_vigilante_padre(ventana, parent_pid=parent_pid)
    iniciar_observador_tema(ventana)

    ventana.title(f"💸 Control Integral de Gastos - {business_mgr.nombre}")
    t = aplicar_tema(ventana)
    calcular_geometria_segura(ventana, 1180, 760, min_w=950, min_h=580)
    ventana.configure(bg=t["bg_app"])

    # HEADER
    header = tk.Frame(ventana, bg=t["primary"])
    header.pack(fill="x")
    
    fg_h = calcular_color_texto_optimo(t["primary"])

    h_left = tk.Frame(header, bg=t["primary"])
    h_left.pack(side="left", padx=20, pady=10)
    tk.Label(h_left, text="💸", font=("Segoe UI Emoji", 22), bg=t["primary"], fg=fg_h).pack(side="left", padx=(0, 10))
    lbl_title = tk.Label(h_left, text="CONTROL INTEGRAL DE GASTOS Y OBLIGACIONES", font=("Segoe UI", 15, "bold"), bg=t["primary"], fg=fg_h)
    lbl_title.pack(side="left")

    h_right = tk.Frame(header, bg=t["primary"])
    h_right.pack(side="right", padx=20, pady=10)
    lbl_recurrentes_info = tk.Label(h_right, text=f"⚡ Auto-Recurrentes: {nuevos_rec} generados hoy", font=("Segoe UI", 9, "bold"), bg=t["primary"], fg=fg_h)
    lbl_recurrentes_info.pack(side="left", padx=10)

    # NOTEBOOK PRINCIPAL CON 3 PESTAÑAS
    notebook = ttk.Notebook(ventana)
    notebook.pack(fill="both", expand=True, padx=15, pady=10)

    tab_gastos = tk.Frame(notebook, bg=t["bg_app"])
    tab_recurrentes = tk.Frame(notebook, bg=t["bg_app"])
    tab_dashboard = tk.Frame(notebook, bg=t["bg_app"])

    notebook.add(tab_gastos, text="📋 Registro y Lista de Gastos")
    notebook.add(tab_recurrentes, text="🔄 Gastos Recurrentes (Arriendos/Servicios)")
    notebook.add(tab_dashboard, text="📊 Dashboard y Vencimientos")

    # ==========================================================================
    # PESTAÑA 1: REGISTRO Y LISTA DE GASTOS
    # ==========================================================================
    top_bar = tk.Frame(tab_gastos, bg=t["bg_surface"], relief="solid", bd=1, highlightbackground=t["border"], highlightthickness=1)
    top_bar.pack(fill="x", padx=10, pady=(8, 4))
    top_bar_inner = tk.Frame(top_bar, bg=t["bg_surface"], padx=10, pady=8)
    top_bar_inner.pack(fill="x")

    # Filtros
    tk.Label(top_bar_inner, text="📅 Periodo:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).pack(side="left", padx=(0, 4))
    periodo_var = tk.StringVar(value="Este mes")
    periodo_combo = ttk.Combobox(top_bar_inner, textvariable=periodo_var, values=["Hoy", "Ayer", "Esta semana", "Este mes", "Todos"], state="readonly", width=12)
    periodo_combo.pack(side="left", padx=(0, 10))

    tk.Label(top_bar_inner, text="🏷️ Categoría:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).pack(side="left", padx=(0, 4))
    cat_var = tk.StringVar(value="Todas")
    cat_combo = ttk.Combobox(top_bar_inner, textvariable=cat_var, values=["Todas"] + CATEGORIAS_GASTO, state="readonly", width=16)
    cat_combo.pack(side="left", padx=(0, 10))

    tk.Label(top_bar_inner, text="📌 Estado:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).pack(side="left", padx=(0, 4))
    estado_var = tk.StringVar(value="Todos")
    estado_combo = ttk.Combobox(top_bar_inner, textvariable=estado_var, values=["Todos", "Pagado", "Pendiente", "Vencido", "Anulado"], state="readonly", width=11)
    estado_combo.pack(side="left", padx=(0, 10))

    tk.Label(top_bar_inner, text="🔍 Buscar:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).pack(side="left", padx=(0, 4))
    buscar_var = tk.StringVar()
    buscar_entry = tk.Entry(top_bar_inner, textvariable=buscar_var, font=("Segoe UI", 9), width=18, relief="solid", bd=1, bg=t["input_bg"], fg=t["input_fg"])
    buscar_entry.pack(side="left", padx=(0, 10))

    # Botón Nuevo Gasto
    def abrir_modal_nuevo_gasto():
        modal = tk.Toplevel(ventana)
        modal.title("➕ Registrar Nuevo Gasto")
        t_mod = aplicar_tema(modal)
        calcular_geometria_segura(modal, 540, 560, modal_padre=ventana)
        modal.configure(bg=t_mod["bg_app"])
        modal.transient(ventana)
        modal.grab_set()

        tk.Label(modal, text="➕ REGISTRO DE GASTO", font=("Segoe UI", 13, "bold"), bg=t_mod["bg_app"], fg=t_mod["primary"]).pack(pady=12)
        
        box = tk.Frame(modal, bg=t_mod["bg_surface"], padx=20, pady=15, relief="solid", bd=1, highlightbackground=t_mod["border"], highlightthickness=1)
        box.pack(fill="both", expand=True, padx=20, pady=(0, 15))

        # Concepto
        tk.Label(box, text="📝 Concepto / Motivo *:", font=("Segoe UI", 9, "bold"), bg=t_mod["bg_surface"], fg=t_mod["text_primary"]).grid(row=0, column=0, sticky="w", pady=4)
        c_entry = tk.Entry(box, font=("Segoe UI", 10), width=35, bg=t_mod["input_bg"], fg=t_mod["input_fg"])
        c_entry.grid(row=0, column=1, sticky="w", pady=4)
        c_entry.focus()

        # Valor
        tk.Label(box, text="💰 Valor (COP) *:", font=("Segoe UI", 9, "bold"), bg=t_mod["bg_surface"], fg=t_mod["text_primary"]).grid(row=1, column=0, sticky="w", pady=4)
        v_entry = CurrencyEntry(box, initial_value=0, font=("Segoe UI", 10, "bold"), width=20, bg=t_mod["input_bg"], fg=t_mod["input_fg"])
        v_entry.grid(row=1, column=1, sticky="w", pady=4)

        # Categoría
        tk.Label(box, text="🏷️ Categoría Contable:", font=("Segoe UI", 9, "bold"), bg=t_mod["bg_surface"], fg=t_mod["text_primary"]).grid(row=2, column=0, sticky="w", pady=4)
        m_cat_var = tk.StringVar(value="Operativo diario")
        m_cat_cb = ttk.Combobox(box, textvariable=m_cat_var, values=CATEGORIAS_GASTO, state="readonly", width=25)
        m_cat_cb.grid(row=2, column=1, sticky="w", pady=4)

        # Método de Pago
        tk.Label(box, text="💳 Medio de Pago:", font=("Segoe UI", 9, "bold"), bg=t_mod["bg_surface"], fg=t_mod["text_primary"]).grid(row=3, column=0, sticky="w", pady=4)
        m_met_var = tk.StringVar(value="Efectivo")
        m_met_cb = ttk.Combobox(box, textvariable=m_met_var, values=["Efectivo", "Transferencia"], state="readonly", width=25)
        m_met_cb.grid(row=3, column=1, sticky="w", pady=4)

        # Estado inicial
        tk.Label(box, text="📌 Estado Inicial:", font=("Segoe UI", 9, "bold"), bg=t_mod["bg_surface"], fg=t_mod["text_primary"]).grid(row=4, column=0, sticky="w", pady=4)
        m_est_var = tk.StringVar(value="Pagado")
        m_est_cb = ttk.Combobox(box, textvariable=m_est_var, values=["Pagado", "Pendiente"], state="readonly", width=25)
        m_est_cb.grid(row=4, column=1, sticky="w", pady=4)

        # Fecha Vencimiento
        tk.Label(box, text="📅 Vencimiento (YYYY-MM-DD):", font=("Segoe UI", 9, "bold"), bg=t_mod["bg_surface"], fg=t_mod["text_primary"]).grid(row=5, column=0, sticky="w", pady=4)
        venc_entry = tk.Entry(box, font=("Segoe UI", 10), width=20, bg=t_mod["input_bg"], fg=t_mod["input_fg"])
        venc_entry.insert(0, (datetime.now() + timedelta(days=15)).strftime("%Y-%m-%d"))
        venc_entry.grid(row=5, column=1, sticky="w", pady=4)

        # Proveedor
        tk.Label(box, text="🏢 Proveedor / Acreedor:", font=("Segoe UI", 9, "bold"), bg=t_mod["bg_surface"], fg=t_mod["text_primary"]).grid(row=6, column=0, sticky="w", pady=4)
        prov_entry = tk.Entry(box, font=("Segoe UI", 10), width=35, bg=t_mod["input_bg"], fg=t_mod["input_fg"])
        prov_entry.grid(row=6, column=1, sticky="w", pady=4)

        # Comprobante
        tk.Label(box, text="🧾 N° Comprobante / Factura:", font=("Segoe UI", 9, "bold"), bg=t_mod["bg_surface"], fg=t_mod["text_primary"]).grid(row=7, column=0, sticky="w", pady=4)
        comp_entry = tk.Entry(box, font=("Segoe UI", 10), width=35, bg=t_mod["input_bg"], fg=t_mod["input_fg"])
        comp_entry.grid(row=7, column=1, sticky="w", pady=4)

        # Observaciones
        tk.Label(box, text="📝 Observaciones:", font=("Segoe UI", 9, "bold"), bg=t_mod["bg_surface"], fg=t_mod["text_primary"]).grid(row=8, column=0, sticky="w", pady=4)
        obs_entry = tk.Entry(box, font=("Segoe UI", 10), width=35, bg=t_mod["input_bg"], fg=t_mod["input_fg"])
        obs_entry.grid(row=8, column=1, sticky="w", pady=4)

        def guardar():
            conc = c_entry.get().strip()
            if not conc:
                messagebox.showwarning("Campo Vacío", "Por favor ingresa un concepto para el gasto.", parent=modal)
                c_entry.focus()
                return
            monto = float(v_entry.get_value())
            if monto <= 0:
                messagebox.showwarning("Monto Inválido", "El valor del gasto debe ser mayor a 0.", parent=modal)
                v_entry.focus()
                return

            est = m_est_var.get()
            venc = venc_entry.get().strip() if est == "Pendiente" else ""

            ok = registrar_nuevo_gasto(
                concepto=conc,
                valor=monto,
                categoria=m_cat_var.get(),
                metodo_pago=m_met_var.get(),
                estado=est,
                fecha_vencimiento=venc,
                proveedor=prov_entry.get().strip(),
                comprobante=comp_entry.get().strip(),
                observaciones=obs_entry.get().strip()
            )
            if ok:
                modal.destroy()
                recargar_todo()
                messagebox.showinfo("Éxito", f"Gasto registrado exitosamente:\n\n{conc} - ${monto:,.0f} ({est})")
            else:
                messagebox.showerror("Error", "No se pudo registrar el gasto en la base de datos.", parent=modal)

        btn_box = tk.Frame(box, bg=t_mod["bg_surface"])
        btn_box.grid(row=9, column=0, columnspan=2, pady=(15, 0), sticky="ew")

        crear_boton(btn_box, text="❌ Cancelar", command=modal.destroy, bg=t_mod["btn_secondary_bg"], fg=t_mod["btn_secondary_fg"]).pack(side="left")
        crear_boton(btn_box, text="💾 Registrar Gasto", command=guardar, bg=t_mod["success"], fg="white").pack(side="right")

    crear_boton(top_bar_inner, text="➕ Nuevo Gasto", command=abrir_modal_nuevo_gasto, bg=t["success"], fg="white", font=("Segoe UI", 9, "bold"), padx=12, pady=4).pack(side="right", padx=5)

    # ACCIONES INFERIORES DE LA TABLA
    action_bar = tk.Frame(tab_gastos, bg=t["bg_app"])
    action_bar.pack(fill="x", padx=10, pady=(2, 4))

    def pagar_gasto_seleccionado():
        item = tree_gastos.focus()
        if not item:
            messagebox.showwarning("Selección Requerida", "Por favor selecciona un gasto para liquidar/pagar.")
            return
        g_id = tree_gastos.item(item)["values"][0]
        # Consultar estado
        conn = conectar_sqlite()
        cur = conn.cursor()
        cur.execute("SELECT concepto, valor, estado, metodo_pago FROM gastos WHERE id_gasto = ?", (g_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return

        concepto, valor, estado_act, met_act = row[0], float(row[1]), row[2], row[3]
        if estado_act == "Pagado":
            messagebox.showinfo("Ya Pagado", f"El gasto #{g_id} ya fue pagado previamente.")
            return
        if estado_act == "Anulado":
            messagebox.showwarning("Gasto Anulado", f"El gasto #{g_id} está anulado.")
            return

        # Modal de confirmación de pago
        p_modal = tk.Toplevel(ventana)
        p_modal.title(f"💰 Liquidar Gasto #{g_id}")
        t_pmod = aplicar_tema(p_modal)
        calcular_geometria_segura(p_modal, 450, 320, modal_padre=ventana)
        p_modal.configure(bg=t_pmod["bg_app"])
        p_modal.transient(ventana)
        p_modal.grab_set()

        tk.Label(p_modal, text=f"💰 LIQUIDAR PAGO DE GASTO #{g_id}", font=("Segoe UI", 12, "bold"), bg=t_pmod["bg_app"], fg=t_pmod["primary"]).pack(pady=12)
        p_box = tk.Frame(p_modal, bg=t_pmod["bg_surface"], padx=20, pady=15, relief="solid", bd=1, highlightbackground=t_pmod["border"], highlightthickness=1)
        p_box.pack(fill="both", expand=True, padx=20, pady=(0, 15))

        tk.Label(p_box, text=f"Concepto: {concepto}", font=("Segoe UI", 10, "bold"), bg=t_pmod["bg_surface"], fg=t_pmod["text_primary"]).pack(anchor="w", pady=2)
        tk.Label(p_box, text=f"Monto a Pagar: ${valor:,.0f}", font=("Segoe UI", 12, "bold"), bg=t_pmod["bg_surface"], fg=t_pmod["danger"]).pack(anchor="w", pady=4)

        tk.Label(p_box, text="Medio con que se cancela:", font=("Segoe UI", 9, "bold"), bg=t_pmod["bg_surface"], fg=t_pmod["text_primary"]).pack(anchor="w", pady=(8, 2))
        p_met_var = tk.StringVar(value=met_act or "Efectivo")
        p_cb = ttk.Combobox(p_box, textvariable=p_met_var, values=["Efectivo", "Transferencia"], state="readonly", width=25)
        p_cb.pack(anchor="w", pady=2)

        tk.Label(p_box, text="N° Comprobante / Soporte:", font=("Segoe UI", 9, "bold"), bg=t_pmod["bg_surface"], fg=t_pmod["text_primary"]).pack(anchor="w", pady=(8, 2))
        p_comp = tk.Entry(p_box, font=("Segoe UI", 10), width=30, bg=t_pmod["input_bg"], fg=t_pmod["input_fg"])
        p_comp.pack(anchor="w", pady=2)

        def ejecutar_pago():
            try:
                res = pagar_gasto(
                    id_gasto=g_id,
                    metodo_pago=p_met_var.get(),
                    usuario="Administrador",
                    comprobante=p_comp.get().strip()
                )
                p_modal.destroy()
                recargar_todo()
                msg = f"Gasto #{g_id} liquidado como PAGADO.\n\nMedio: {res['metodo_pago']}\nMonto: ${res['monto']:,.0f}"
                if res.get("movimiento_caja_id"):
                    msg += f"\n\n💵 Se generó EGRESO en la caja física activa."
                messagebox.showinfo("Gasto Liquidado", msg)
            except Exception as e:
                messagebox.showerror("Error", f"Error liquidando gasto: {e}", parent=p_modal)

        p_btns = tk.Frame(p_box, bg=t_pmod["bg_surface"])
        p_btns.pack(fill="x", pady=(15, 0))
        crear_boton(p_btns, text="❌ Cancelar", command=p_modal.destroy, bg=t_pmod["btn_secondary_bg"], fg=t_pmod["btn_secondary_fg"]).pack(side="left")
        crear_boton(p_btns, text="✅ Confirmar Pago", command=ejecutar_pago, bg=t_pmod["success"], fg="white").pack(side="right")

    def anular_gasto():
        item = tree_gastos.focus()
        if not item:
            messagebox.showwarning("Selección", "Por favor selecciona un gasto para anular.")
            return
        g_id = tree_gastos.item(item)["values"][0]
        if messagebox.askyesno("Confirmar Anulación", f"¿Estás seguro de anular el gasto #{g_id}?"):
            if anular_gasto_db(g_id):
                recargar_todo()
                messagebox.showinfo("Anulado", f"El gasto #{g_id} ha sido anulado.")

    btn_pagar = crear_boton(action_bar, text="💰 Pagar / Liquidar Gasto", command=pagar_gasto_seleccionado, bg="#0284C7", fg="white", font=("Segoe UI", 9, "bold"), padx=12, pady=3)
    btn_pagar.pack(side="left", padx=4)

    btn_anular = crear_boton(action_bar, text="🚫 Anular Gasto", command=anular_gasto, bg=t["danger"], fg="white", font=("Segoe UI", 9, "bold"), padx=10, pady=3)
    btn_anular.pack(side="left", padx=4)

    btn_actualizar = crear_boton(action_bar, text="🔄 Refrescar", command=lambda: recargar_todo(), bg=t["btn_secondary_bg"], fg=t["btn_secondary_fg"], font=("Segoe UI", 9, "bold"), padx=10, pady=3)
    btn_actualizar.pack(side="left", padx=4)

    lbl_total_filtrado = tk.Label(action_bar, text="Total Filtrado: $0", font=("Segoe UI", 10, "bold"), bg=t["bg_app"], fg=t["primary"])
    lbl_total_filtrado.pack(side="right", padx=10)

    # TREEVIEW GASTOS
    frame_tree = tk.Frame(tab_gastos, bg=t["bg_surface"], relief="solid", bd=1, highlightbackground=t["border"], highlightthickness=1)
    frame_tree.pack(fill="both", expand=True, padx=10, pady=(0, 8))

    cols = ("ID", "Fecha", "Concepto", "Categoría", "Valor", "Medio", "Estado", "Vence", "Proveedor", "Comprobante")
    tree_gastos = ttk.Treeview(frame_tree, columns=cols, show="headings", height=12)
    widths = [50, 85, 200, 120, 100, 95, 85, 85, 130, 110]
    for c, w in zip(cols, widths):
        tree_gastos.heading(c, text=c)
        tree_gastos.column(c, width=w, anchor="center" if c in ["ID", "Fecha", "Medio", "Estado", "Vence"] else ("e" if c == "Valor" else "w"))

    sb_v = ttk.Scrollbar(frame_tree, orient="vertical", command=tree_gastos.yview)
    sb_h = ttk.Scrollbar(frame_tree, orient="horizontal", command=tree_gastos.xview)
    tree_gastos.configure(yscrollcommand=sb_v.set, xscrollcommand=sb_h.set)
    tree_gastos.grid(row=0, column=0, sticky="nsew")
    sb_v.grid(row=0, column=1, sticky="ns")
    sb_h.grid(row=1, column=0, sticky="ew")
    frame_tree.grid_rowconfigure(0, weight=1)
    frame_tree.grid_columnconfigure(0, weight=1)

    # Tags de colores por estado
    tree_gastos.tag_configure("pagado", foreground="#059669")
    tree_gastos.tag_configure("pendiente", foreground="#D97706", font=("Segoe UI", 9, "bold"))
    tree_gastos.tag_configure("vencido", foreground="#DC2626", font=("Segoe UI", 9, "bold"))
    tree_gastos.tag_configure("anulado", foreground="#9CA3AF")

    def recargar_tabla_gastos():
        tree_gastos.delete(*tree_gastos.get_children())
        gastos = obtener_gastos_db(
            filtro_periodo=periodo_var.get(),
            filtro_cat=cat_var.get(),
            filtro_estado=estado_var.get(),
            busqueda=buscar_var.get().strip()
        )
        total_acum = 0.0
        for g in gastos:
            v = float(g.get("valor", 0.0))
            if g.get("estado") != "Anulado":
                total_acum += v
            est = g.get("estado", "Pagado")
            tag = est.lower()
            tree_gastos.insert("", "end", values=(
                g["id_gasto"],
                g.get("fecha", ""),
                g.get("concepto", ""),
                g.get("categoria", ""),
                f"${v:,.0f}",
                g.get("metodo_pago", ""),
                est,
                g.get("fecha_vencimiento") or "-",
                g.get("proveedor") or "-",
                g.get("comprobante") or "-"
            ), tags=(tag,))
        lbl_total_filtrado.config(text=f"Total Filtrado: ${total_acum:,.0f} ({len(gastos)} registros)")

    periodo_combo.bind("<<ComboboxSelected>>", lambda e: recargar_tabla_gastos())
    cat_combo.bind("<<ComboboxSelected>>", lambda e: recargar_tabla_gastos())
    estado_combo.bind("<<ComboboxSelected>>", lambda e: recargar_tabla_gastos())
    buscar_entry.bind("<KeyRelease>", lambda e: recargar_tabla_gastos())

    # ==========================================================================
    # PESTAÑA 2: GASTOS RECURRENTES (ARRIENDOS, SERVICIOS, SUSCRIPCIONES)
    # ==========================================================================
    rec_top = tk.Frame(tab_recurrentes, bg=t["bg_surface"], relief="solid", bd=1, highlightbackground=t["border"], highlightthickness=1)
    rec_top.pack(fill="x", padx=10, pady=8)
    rec_top_inner = tk.Frame(rec_top, bg=t["bg_surface"], padx=10, pady=8)
    rec_top_inner.pack(fill="x")

    tk.Label(rec_top_inner, text="🔄 Reglas Automáticas de Gastos Fijos (Arriendos, Servicios Públicos, Nóminas fijas, Software)",
             font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).pack(side="left")

    def modal_nueva_recurrencia(id_rec=None, datos_prev=None):
        m_rec = tk.Toplevel(ventana)
        m_rec.title("🔄 Programar Gasto Recurrente")
        t_mrec = aplicar_tema(m_rec)
        calcular_geometria_segura(m_rec, 480, 460, modal_padre=ventana)
        m_rec.configure(bg=t_mrec["bg_app"])
        m_rec.transient(ventana)
        m_rec.grab_set()

        tk.Label(m_rec, text="🔄 REGLA DE GASTO RECURRENTE", font=("Segoe UI", 12, "bold"), bg=t_mrec["bg_app"], fg=t_mrec["primary"]).pack(pady=10)
        box = tk.Frame(m_rec, bg=t_mrec["bg_surface"], padx=20, pady=15, relief="solid", bd=1, highlightbackground=t_mrec["border"], highlightthickness=1)
        box.pack(fill="both", expand=True, padx=20, pady=(0, 15))

        tk.Label(box, text="📝 Concepto (Ej. Arriendo Local, Internet):", font=("Segoe UI", 9, "bold"), bg=t_mrec["bg_surface"], fg=t_mrec["text_primary"]).grid(row=0, column=0, sticky="w", pady=4)
        c_ent = tk.Entry(box, font=("Segoe UI", 10), width=30, bg=t_mrec["input_bg"], fg=t_mrec["input_fg"])
        if datos_prev: c_ent.insert(0, datos_prev.get("concepto", ""))
        c_ent.grid(row=0, column=1, sticky="w", pady=4)

        tk.Label(box, text="💰 Valor Estimado (COP):", font=("Segoe UI", 9, "bold"), bg=t_mrec["bg_surface"], fg=t_mrec["text_primary"]).grid(row=1, column=0, sticky="w", pady=4)
        v_ent = CurrencyEntry(box, initial_value=datos_prev.get("valor", 0) if datos_prev else 0, font=("Segoe UI", 10, "bold"), width=18, bg=t_mrec["input_bg"], fg=t_mrec["input_fg"])
        v_ent.grid(row=1, column=1, sticky="w", pady=4)

        tk.Label(box, text="⏰ Frecuencia:", font=("Segoe UI", 9, "bold"), bg=t_mrec["bg_surface"], fg=t_mrec["text_primary"]).grid(row=2, column=0, sticky="w", pady=4)
        f_var = tk.StringVar(value=datos_prev.get("frecuencia", "Mensual") if datos_prev else "Mensual")
        f_cb = ttk.Combobox(box, textvariable=f_var, values=FRECUENCIAS, state="readonly", width=18)
        f_cb.grid(row=2, column=1, sticky="w", pady=4)

        tk.Label(box, text="🏷️ Categoría:", font=("Segoe UI", 9, "bold"), bg=t_mrec["bg_surface"], fg=t_mrec["text_primary"]).grid(row=3, column=0, sticky="w", pady=4)
        cat_r_var = tk.StringVar(value=datos_prev.get("categoria", "Fijo periódico") if datos_prev else "Fijo periódico")
        cat_r_cb = ttk.Combobox(box, textvariable=cat_r_var, values=CATEGORIAS_GASTO, state="readonly", width=18)
        cat_r_cb.grid(row=3, column=1, sticky="w", pady=4)

        tk.Label(box, text="📅 Día de Corte / Pago (1 a 28):", font=("Segoe UI", 9, "bold"), bg=t_mrec["bg_surface"], fg=t_mrec["text_primary"]).grid(row=4, column=0, sticky="w", pady=4)
        dia_ent = tk.Spinbox(box, from_=1, to=28, font=("Segoe UI", 10), width=10, bg=t_mrec["input_bg"], fg=t_mrec["input_fg"])
        if datos_prev: dia_ent.delete(0, "end"); dia_ent.insert(0, str(datos_prev.get("dia_corte", 5)))
        dia_ent.grid(row=4, column=1, sticky="w", pady=4)

        tk.Label(box, text="🏢 Proveedor:", font=("Segoe UI", 9, "bold"), bg=t_mrec["bg_surface"], fg=t_mrec["text_primary"]).grid(row=5, column=0, sticky="w", pady=4)
        p_ent = tk.Entry(box, font=("Segoe UI", 10), width=30, bg=t_mrec["input_bg"], fg=t_mrec["input_fg"])
        if datos_prev: p_ent.insert(0, datos_prev.get("proveedor", ""))
        p_ent.grid(row=5, column=1, sticky="w", pady=4)

        tk.Label(box, text="💳 Medio por Defecto:", font=("Segoe UI", 9, "bold"), bg=t_mrec["bg_surface"], fg=t_mrec["text_primary"]).grid(row=6, column=0, sticky="w", pady=4)
        met_r_var = tk.StringVar(value=datos_prev.get("metodo_pago_defecto", "Efectivo") if datos_prev else "Efectivo")
        met_r_cb = ttk.Combobox(box, textvariable=met_r_var, values=["Efectivo", "Transferencia"], state="readonly", width=18)
        met_r_cb.grid(row=6, column=1, sticky="w", pady=4)

        def guardar_r():
            conc = c_ent.get().strip()
            if not conc:
                messagebox.showwarning("Concepto Vacío", "Ingresa un concepto.", parent=m_rec); return
            val = float(v_ent.get_value())
            if val <= 0:
                messagebox.showwarning("Valor Inválido", "Ingresa un valor mayor a cero.", parent=m_rec); return
            try:
                dc = int(dia_ent.get())
            except Exception:
                dc = 1

            if guardar_recurrente_db(conc, val, f_var.get(), cat_r_var.get(), dc, p_ent.get().strip(), met_r_var.get(), id_rec):
                m_rec.destroy()
                recargar_todo()
                messagebox.showinfo("Guardado", f"Regla recurrente para '{conc}' guardada con éxito.")

        btn_box = tk.Frame(box, bg=t_mrec["bg_surface"])
        btn_box.grid(row=7, column=0, columnspan=2, pady=(15, 0), sticky="ew")
        crear_boton(btn_box, text="❌ Cancelar", command=m_rec.destroy, bg=t_mrec["btn_secondary_bg"], fg=t_mrec["btn_secondary_fg"]).pack(side="left")
        crear_boton(btn_box, text="💾 Guardar Regla", command=guardar_r, bg=t_mrec["success"], fg="white").pack(side="right")

    crear_boton(rec_top_inner, text="➕ Nueva Regla Recurrente", command=modal_nueva_recurrencia, bg=t["success"], fg="white", font=("Segoe UI", 9, "bold"), padx=10, pady=3).pack(side="right", padx=4)

    def forzar_procesamiento():
        n = procesar_gastos_recurrentes()
        recargar_todo()
        messagebox.showinfo("Procesador de Recurrentes", f"Se han generado {n} nuevas obligaciones pendientes.")

    crear_boton(rec_top_inner, text="⚡ Generar Pendientes Ahora", command=forzar_procesamiento, bg="#D97706", fg="white", font=("Segoe UI", 9, "bold"), padx=10, pady=3).pack(side="right", padx=4)

    # TREEVIEW RECURRENTES
    rec_frame = tk.Frame(tab_recurrentes, bg=t["bg_surface"], relief="solid", bd=1, highlightbackground=t["border"], highlightthickness=1)
    rec_frame.pack(fill="both", expand=True, padx=10, pady=(0, 8))

    cols_rec = ("ID", "Concepto", "Valor", "Frecuencia", "Categoría", "Día Corte", "Proveedor", "Medio", "Último Periodo", "Estado")
    tree_rec = ttk.Treeview(rec_frame, columns=cols_rec, show="headings", height=10)
    w_rec = [40, 220, 110, 90, 120, 70, 140, 95, 110, 80]
    for c, w in zip(cols_rec, w_rec):
        tree_rec.heading(c, text=c)
        tree_rec.column(c, width=w, anchor="center" if c not in ["Concepto", "Proveedor"] else "w")

    tree_rec.pack(fill="both", expand=True)

    rec_actions = tk.Frame(tab_recurrentes, bg=t["bg_app"])
    rec_actions.pack(fill="x", padx=10, pady=4)

    def toggle_recurrente():
        item = tree_rec.focus()
        if not item: return
        vals = tree_rec.item(item)["values"]
        id_r = vals[0]
        est_txt = vals[9]
        est_act = 1 if est_txt == "Activo" else 0
        toggle_activo_recurrente_db(id_r, est_act)
        recargar_tabla_recurrentes()

    crear_boton(rec_actions, text="⏸️ Pausar / Activar Regla", command=toggle_recurrente, bg="#4B5563", fg="white", font=("Segoe UI", 9, "bold"), padx=10, pady=3).pack(side="left", padx=4)

    def recargar_tabla_recurrentes():
        tree_rec.delete(*tree_rec.get_children())
        recs = obtener_recurrentes_db()
        for r in recs:
            tree_rec.insert("", "end", values=(
                r["id"],
                r.get("concepto", ""),
                f"${float(r.get('valor', 0.0)):,.0f}",
                r.get("frecuencia", ""),
                r.get("categoria", ""),
                r.get("dia_corte", 1),
                r.get("proveedor") or "-",
                r.get("metodo_pago_defecto", "Efectivo"),
                r.get("ultimo_periodo_generado") or "Nunca",
                "Activo" if r.get("activo") == 1 else "Pausado"
            ))

    # ==========================================================================
    # PESTAÑA 3: DASHBOARD Y VENCIMIENTOS
    # ==========================================================================
    dash_scroll = ScrollableContainer(tab_dashboard, bg=t["bg_app"])
    dash_scroll.pack(fill="both", expand=True, padx=10, pady=10)
    dash_content = dash_scroll.scrollable_frame

    # TARJETAS KPI RESUMEN GASTOS
    kpi_frame = tk.Frame(dash_content, bg=t["bg_app"])
    kpi_frame.pack(fill="x", pady=(0, 10))

    card_hoy = tk.Frame(kpi_frame, bg=t["bg_surface"], relief="solid", bd=1, highlightbackground=t["border"], highlightthickness=1)
    card_hoy.pack(side="left", fill="both", expand=True, padx=(0, 8))
    tk.Frame(card_hoy, bg="#10B981", height=4).pack(fill="x")
    lbl_dash_hoy = tk.Label(card_hoy, text="$0", font=("Segoe UI", 16, "bold"), bg=t["bg_surface"], fg="#10B981")
    tk.Label(card_hoy, text="Gastos Pagados Hoy", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_muted"]).pack(pady=(6, 2))
    lbl_dash_hoy.pack(pady=(0, 8))

    card_sem = tk.Frame(kpi_frame, bg=t["bg_surface"], relief="solid", bd=1, highlightbackground=t["border"], highlightthickness=1)
    card_sem.pack(side="left", fill="both", expand=True, padx=4)
    tk.Frame(card_sem, bg="#0284C7", height=4).pack(fill="x")
    lbl_dash_sem = tk.Label(card_sem, text="$0", font=("Segoe UI", 16, "bold"), bg=t["bg_surface"], fg="#0284C7")
    tk.Label(card_sem, text="Gastos Esta Semana", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_muted"]).pack(pady=(6, 2))
    lbl_dash_sem.pack(pady=(0, 8))

    card_mes = tk.Frame(kpi_frame, bg=t["bg_surface"], relief="solid", bd=1, highlightbackground=t["border"], highlightthickness=1)
    card_mes.pack(side="left", fill="both", expand=True, padx=4)
    tk.Frame(card_mes, bg="#8B5CF6", height=4).pack(fill="x")
    lbl_dash_mes = tk.Label(card_mes, text="$0", font=("Segoe UI", 16, "bold"), bg=t["bg_surface"], fg="#8B5CF6")
    tk.Label(card_mes, text="Gastos Este Mes", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_muted"]).pack(pady=(6, 2))
    lbl_dash_mes.pack(pady=(0, 8))

    card_pen = tk.Frame(kpi_frame, bg=t["bg_surface"], relief="solid", bd=1, highlightbackground=t["border"], highlightthickness=1)
    card_pen.pack(side="left", fill="both", expand=True, padx=(8, 0))
    tk.Frame(card_pen, bg="#EF4444", height=4).pack(fill="x")
    lbl_dash_pen = tk.Label(card_pen, text="$0", font=("Segoe UI", 16, "bold"), bg=t["bg_surface"], fg="#EF4444")
    tk.Label(card_pen, text="Obligaciones Pendientes", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_muted"]).pack(pady=(6, 2))
    lbl_dash_pen.pack(pady=(0, 8))

    # SECCIÓN DE GRÁFICO POR CATEGORÍA
    chart_frame = tk.Frame(dash_content, bg=t["bg_surface"], relief="solid", bd=1, highlightbackground=t["border"], highlightthickness=1)
    chart_frame.pack(fill="x", pady=8)
    tk.Label(chart_frame, text="📊 Distribución de Gastos por Categoría (Mes Actual)", font=("Segoe UI", 11, "bold"), bg=t["bg_surface"], fg=t["primary"]).pack(anchor="w", padx=15, pady=(10, 4))
    
    canvas_cat = tk.Canvas(chart_frame, bg=t["bg_surface"], height=160, highlightthickness=0)
    canvas_cat.pack(fill="x", padx=15, pady=(4, 15))

    # LISTA DE OBLIGACIONES PENDIENTES Y PRÓXIMAS A VENCER
    pen_frame = tk.Frame(dash_content, bg=t["bg_surface"], relief="solid", bd=1, highlightbackground=t["border"], highlightthickness=1)
    pen_frame.pack(fill="x", pady=8)
    tk.Label(pen_frame, text="🚨 Cuentas y Obligaciones Pendientes de Pago (Ordenadas por Vencimiento)", font=("Segoe UI", 11, "bold"), bg=t["bg_surface"], fg="#DC2626").pack(anchor="w", padx=15, pady=(10, 6))

    cols_pen = ("ID", "Concepto", "Monto", "Categoría", "Vencimiento", "Proveedor", "Estado")
    tree_pendientes = ttk.Treeview(pen_frame, columns=cols_pen, show="headings", height=6)
    w_pen = [50, 240, 110, 130, 100, 160, 90]
    for c, w in zip(cols_pen, w_pen):
        tree_pendientes.heading(c, text=c)
        tree_pendientes.column(c, width=w, anchor="center" if c not in ["Concepto", "Proveedor"] else "w")
    tree_pendientes.pack(fill="x", padx=15, pady=(0, 15))
    tree_pendientes.tag_configure("vencido", foreground="#DC2626", font=("Segoe UI", 9, "bold"))
    tree_pendientes.tag_configure("pendiente", foreground="#D97706")

    def recargar_dashboard():
        conn = conectar_sqlite()
        if not conn: return
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        hoy = datetime.now()
        hoy_str = hoy.strftime("%Y-%m-%d")
        ini_sem = (hoy - timedelta(days=hoy.weekday())).strftime("%Y-%m-%d")
        ini_mes = hoy.strftime("%Y-%m-01")

        # Hoy
        cur.execute("SELECT COALESCE(SUM(valor), 0.0) FROM gastos WHERE fecha = ? AND estado != 'Anulado'", (hoy_str,))
        g_hoy = float(cur.fetchone()[0] or 0.0)
        lbl_dash_hoy.config(text=f"${g_hoy:,.0f}")

        # Semana
        cur.execute("SELECT COALESCE(SUM(valor), 0.0) FROM gastos WHERE fecha BETWEEN ? AND ? AND estado != 'Anulado'", (ini_sem, hoy_str))
        g_sem = float(cur.fetchone()[0] or 0.0)
        lbl_dash_sem.config(text=f"${g_sem:,.0f}")

        # Mes
        cur.execute("SELECT COALESCE(SUM(valor), 0.0) FROM gastos WHERE fecha BETWEEN ? AND ? AND estado != 'Anulado'", (ini_mes, hoy_str))
        g_mes = float(cur.fetchone()[0] or 0.0)
        lbl_dash_mes.config(text=f"${g_mes:,.0f}")

        # Pendientes / Vencidos
        cur.execute("SELECT COALESCE(SUM(valor), 0.0) FROM gastos WHERE estado IN ('Pendiente', 'Vencido')")
        g_pen = float(cur.fetchone()[0] or 0.0)
        lbl_dash_pen.config(text=f"${g_pen:,.0f}")

        # Gráfico por categoría (Mes Actual)
        cur.execute("""
            SELECT COALESCE(categoria, clasificacion, 'Operativo diario') as cat, SUM(valor) as total
            FROM gastos
            WHERE fecha BETWEEN ? AND ? AND estado != 'Anulado'
            GROUP BY cat
        """, (ini_mes, hoy_str))
        cat_map = {c: 0.0 for c in CATEGORIAS_GASTO}
        for r in cur.fetchall():
            c_name = r["cat"] or "Operativo diario"
            matched = "Operativo diario"
            for k in CATEGORIAS_GASTO:
                if k.lower() in c_name.lower():
                    matched = k; break
            cat_map[matched] = cat_map.get(matched, 0.0) + float(r["total"] or 0.0)

        # Dibujar Canvas Bars
        canvas_cat.delete("all")
        w_can = canvas_cat.winfo_width() or 600
        total_cats = sum(cat_map.values())
        y = 15
        colores_bar = ["#10B981", "#3B82F6", "#F59E0B", "#EF4444"]
        for i, cat in enumerate(CATEGORIAS_GASTO):
            val = cat_map.get(cat, 0.0)
            pct = (val / total_cats * 100.0) if total_cats > 0 else 0.0
            canvas_cat.create_text(15, y, anchor="w", text=f"{cat}:", font=("Segoe UI", 9, "bold"), fill=t["text_primary"])
            canvas_cat.create_text(180, y, anchor="w", text=f"${val:,.0f} ({pct:.1f}%)", font=("Segoe UI", 9), fill=t["text_muted"])
            
            # Barra
            bar_start_x = 300
            bar_max_w = max(50, w_can - bar_start_x - 30)
            bar_w = (pct / 100.0) * bar_max_w if total_cats > 0 else 0
            canvas_cat.create_rectangle(bar_start_x, y - 6, bar_start_x + bar_max_w, y + 6, fill="#E5E7EB", outline="")
            if bar_w > 0:
                canvas_cat.create_rectangle(bar_start_x, y - 6, bar_start_x + bar_w, y + 6, fill=colores_bar[i % len(colores_bar)], outline="")
            y += 32

        # Cargar tabla pendientes
        tree_pendientes.delete(*tree_pendientes.get_children())
        cur.execute("""
            SELECT id_gasto, concepto, valor, COALESCE(categoria, 'Operativo'), fecha_vencimiento, proveedor, estado
            FROM gastos
            WHERE estado IN ('Pendiente', 'Vencido')
            ORDER BY COALESCE(fecha_vencimiento, '9999-99-99') ASC
        """)
        for r in cur.fetchall():
            venc = r[4] or "-"
            est = "Vencido" if (venc != "-" and venc < hoy_str) else r[6]
            tag = "vencido" if est == "Vencido" else "pendiente"
            tree_pendientes.insert("", "end", values=(
                r[0], r[1], f"${float(r[2]):,.0f}", r[3], venc, r[5] or "-", est
            ), tags=(tag,))

        conn.close()

    def recargar_todo():
        recargar_tabla_gastos()
        recargar_tabla_recurrentes()
        recargar_dashboard()

    recargar_todo()

    # Redibujar gráfico al cambiar tamaño de ventana
    canvas_cat.bind("<Configure>", lambda e: recargar_dashboard())

    # Footer
    footer = tk.Frame(ventana, bg=t["primary"], height=28)
    footer.pack(fill="x")
    tk.Label(footer, text="💎 Control de Gastos • Contabilidad VmPOS 💎", font=("Segoe UI", 9), bg=t["primary"], fg=fg_h).pack(pady=4)

    if not parent:
        ventana.mainloop()
    return ventana


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Control de Gastos VmPOS")
    parser.add_argument("--parent_pid", default="")
    if "-h" in sys.argv or "--help" in sys.argv:
        parser.print_help()
        sys.exit(0)
    args, _ = parser.parse_known_args()
    parent_pid = args.parent_pid or os.environ.get("VMPOS_PARENT_PID", "")
    iniciar_gastos(parent_pid=parent_pid)