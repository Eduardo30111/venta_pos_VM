import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from client.utils.system_helper import abrir_archivo_o_carpeta
from client.api_client import api
from interface.theme_manager import theme_mgr, aplicar_tema, calcular_geometria_segura, crear_boton, ScrollableContainer
try:
    from business_manager import business_mgr
except ImportError:
    from interface.business_manager import business_mgr
import os
import sys
from datetime import datetime, timedelta
import calendar
# Función verificar_y_crear_tablas removida: ahora se maneja en database_manager.py

# Configuración de rutas para PyInstaller
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Importaciones opcionales con manejo de errores
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    REPORTLAB_DISPONIBLE = True
except ImportError as e:
    print(f"Warning: ReportLab no disponible: {e}")
    REPORTLAB_DISPONIBLE = False

try:
    import pandas as pd
    PANDAS_DISPONIBLE = True
except ImportError as e:
    print(f"Warning: Pandas no disponible: {e}")
    PANDAS_DISPONIBLE = False

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    OPENPYXL_DISPONIBLE = True
except ImportError as e:
    print(f"Warning: OpenPyXL no disponible: {e}")
    OPENPYXL_DISPONIBLE = False

try:
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import matplotlib.dates as mdates
    MATPLOTLIB_DISPONIBLE = True
except ImportError as e:
    print(f"Warning: Matplotlib no disponible: {e}")
    MATPLOTLIB_DISPONIBLE = False

# ⚠️ The path to the database
# Configuración de rutas mejorada para PyInstaller
if getattr(sys, 'frozen', False):
    # Si está ejecutándose como ejecutable
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # Si está ejecutándose como script de Python
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Ruta de base de datos - siempre fuera del ejecutable para persistencia
base_dir = BASE_DIR
database_dir = os.path.join(base_dir, 'database')
ruta_db = os.path.join(database_dir, 'ventas.db')

# Crear directorio si no existe
if not os.path.exists(database_dir):
    os.makedirs(database_dir, exist_ok=True)
# ⚠️ The folder to save PDFs and Excel files
pdf_dir = os.path.join(base_dir, '..', 'reports_pdf')
excel_dir = os.path.join(base_dir, '..', 'reports_excel')
if not os.path.exists(pdf_dir):
    os.makedirs(pdf_dir)
if not os.path.exists(excel_dir):
    os.makedirs(excel_dir)

# 🔌 Single database connection
conn = None
cursor = None

try:
    from database_manager import conectar_db as _conectar_db
except ImportError:
    from interface.database_manager import conectar_db as _conectar_db

def conectar_db():
    """Establishes a single connection to the database."""
    global conn, cursor
    try:
        conn = _conectar_db()
        if not conn: return False
        cursor = conn.cursor()
        return True
    except Exception as e:
        messagebox.showerror("Error de conexión", f"No se pudo conectar a la base de datos:\n{e}")
        return False

def cerrar_app(ventana):
    """Closes the database connection and the main window."""
    if conn:
        conn.close()
    ventana.destroy()

def formato_peso(valor):
    """Formats a numeric value to the Colombian peso representation."""
    return f"${valor:,.0f} COP"

def limpiar_precio(texto):
    """Cleans a text string to extract a numeric float value."""
    texto = texto.replace("$", "").replace("COP", "").replace(",", "").strip()
    try:
        return float(texto)
    except ValueError:
        return 0.0

def convertir_fecha_sql(fecha_dd_mm_yyyy):
    """Convierte fecha de formato DD-MM-YYYY a YYYY-MM-DD para SQL."""
    try:
        fecha_obj = datetime.strptime(fecha_dd_mm_yyyy, "%d-%m-%Y")
        return fecha_obj.strftime("%Y-%m-%d")
    except:
        return fecha_dd_mm_yyyy

def obtener_gastos_periodo(fecha_inicio, fecha_fin):
    """Obtiene los gastos de un período específico."""
    try:
        if getattr(api, "token", None):
            respuesta = api.get("/gastos")
            if respuesta.status_code == 200:
                gastos = respuesta.json()
                inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d").date()
                fin = datetime.strptime(fecha_fin, "%Y-%m-%d").date()
                resultado = []
                for gasto in gastos:
                    creado = gasto.get("created_at")
                    if not creado:
                        continue
                    fecha_gasto = datetime.fromisoformat(str(creado).replace("Z", "+00:00")).date()
                    if inicio <= fecha_gasto <= fin:
                        resultado.append((
                            gasto.get("concepto", ""),
                            float(gasto.get("valor", 0.0)),
                            fecha_gasto.strftime("%Y-%m-%d"),
                            datetime.fromisoformat(str(creado).replace("Z", "+00:00")).strftime("%H:%M:%S"),
                            gasto.get("metodo_pago", "Efectivo")
                        ))
                return resultado

        # Convertir fechas si están en formato DD-MM-YYYY
        if len(fecha_inicio.split('-')[0]) == 2:  # Si el día tiene 2 dígitos, está en formato DD-MM-YYYY
            fecha_inicio_sql = convertir_fecha_sql(fecha_inicio)
            fecha_fin_sql = convertir_fecha_sql(fecha_fin)
        else:
            fecha_inicio_sql = fecha_inicio
            fecha_fin_sql = fecha_fin
            
        cursor.execute("""
            SELECT concepto, valor, fecha, hora, COALESCE(metodo_pago, 'Efectivo') FROM gastos
            WHERE date(substr(fecha, 7, 4) || '-' || 
                      case when length(substr(fecha, 4, 2)) = 1 then '0' || substr(fecha, 4, 2) else substr(fecha, 4, 2) end || '-' ||
                      case when length(substr(fecha, 1, 2)) = 1 then '0' || substr(fecha, 1, 2) else substr(fecha, 1, 2) end)
                  BETWEEN date(?) AND date(?)
            ORDER BY fecha_registro DESC
        """, (fecha_inicio_sql, fecha_fin_sql))
        return cursor.fetchall()
    except Exception as e:
        messagebox.showerror("Error", f"Error al obtener gastos del período: {e}")
        return []

# crear_tabla_reportes_si_no_existe se manejaba aquí, ahora en database_manager.py

# 📊 Report Functions
def generar_reporte_diario(ventana):
    """Prepares and displays the daily sales report with a date filter."""
    filtro = tk.Toplevel(ventana)
    filtro.title("Filtrar Reporte Diario")
    
    t = aplicar_tema(filtro)
    calcular_geometria_segura(filtro, 380, 260, min_w=320, min_h=220)
    filtro.configure(bg=t["bg_app"])
    filtro.transient(ventana)
    filtro.grab_set()

    # Encabezado compacto
    tk.Label(filtro, text="📅 Seleccione la fecha:", font=("Segoe UI", 12, "bold"), bg=t["bg_app"], fg=t["accent"]).pack(pady=(14, 8))

    from datetime import datetime
    ahora = datetime.now()
    
    frame = tk.Frame(filtro, bg=t["bg_app"])
    frame.pack(pady=8)

    meses = [str(i).zfill(2) for i in range(1, 13)]
    dias = [str(i).zfill(2) for i in range(1, 32)]
    
    tk.Label(frame, text="Mes:", bg=t["bg_app"], fg=t["text_primary"], font=("Segoe UI", 10, "bold")).grid(row=0, column=0, padx=5)
    combo_mes = ttk.Combobox(frame, values=meses, width=5, state="readonly")
    combo_mes.set(ahora.strftime("%m"))
    combo_mes.grid(row=0, column=1, padx=5)

    tk.Label(frame, text="Día:", bg=t["bg_app"], fg=t["text_primary"], font=("Segoe UI", 10, "bold")).grid(row=0, column=2, padx=5)
    combo_dia = ttk.Combobox(frame, values=dias, width=5, state="readonly")
    combo_dia.set(ahora.strftime("%d"))
    combo_dia.grid(row=0, column=3, padx=5)

    def ver_reporte():
        mes = combo_mes.get()
        dia = combo_dia.get()
        anio = ahora.strftime("%Y")
        fecha_str = f"{anio}-{mes}-{dia}"
        filtro.destroy()
        abrir_reporte_detallado(ventana, f"Reporte Diario ({fecha_str})", fecha_str, fecha_str)

    # Footer fijo con botones
    footer_bar = tk.Frame(filtro, bg=t["bg_app"])
    footer_bar.pack(side="bottom", fill="x", pady=(0, 15), padx=20)
    
    crear_boton(footer_bar, text="✖ Cancelar", command=filtro.destroy, bg_color=t["btn_secondary_bg"], fg_color=t["btn_secondary_fg"]).pack(side="left")
    crear_boton(footer_bar, text="👁️ Ver Reporte", command=ver_reporte, bg_color=t["btn_success_bg"], fg_color=t["btn_success_fg"]).pack(side="right")

def generar_reporte_semanal(ventana):
    """Prepares and displays the weekly sales report."""
    fecha_fin = datetime.now()
    fecha_inicio = fecha_fin - timedelta(days=7)
    fecha_fin_str = fecha_fin.strftime("%Y-%m-%d")
    fecha_inicio_str = fecha_inicio.strftime("%Y-%m-%d")
    abrir_reporte_detallado(ventana, "Reporte Semanal", fecha_inicio_str, fecha_fin_str)

def abrir_reporte_detallado(ventana, titulo, fecha_inicio_str, fecha_fin_str):
    """Opens a window with a detailed sales table for a given period with expenses included."""
    if not cursor: return
    
    ventana_reporte = tk.Toplevel(ventana)
    ventana_reporte.title(f"📊 {titulo}")
    
    t = aplicar_tema(ventana_reporte)
    calcular_geometria_segura(ventana_reporte, 1180, 730, min_w=920, min_h=540)
    ventana_reporte.configure(bg=t["bg_app"])
    ventana_reporte.transient(ventana)
    ventana_reporte.grab_set()

    # Encabezado compacto
    header_bar = tk.Frame(ventana_reporte, bg=t["accent"], height=45)
    header_bar.pack(fill="x", side="top")
    header_bar.pack_propagate(False)

    tk.Label(header_bar, text=f"📊  {titulo.upper()} ({fecha_inicio_str} a {fecha_fin_str})",
             font=("Segoe UI", 13, "bold"), bg=t["accent"], fg="white").pack(side="left", padx=15)

    # Footer fijo de acciones
    footer_bar = tk.Frame(ventana_reporte, bg=t["bg_surface"], height=48, relief="solid", bd=1)
    footer_bar.pack(fill="x", side="bottom")
    footer_bar.pack_propagate(False)

    crear_boton(footer_bar, text="✖ Cerrar Ventana", command=ventana_reporte.destroy,
                bg_color=t["btn_secondary_bg"], fg_color=t["btn_secondary_fg"]).pack(side="right", padx=15, pady=6)

    # Resumen Financiero Compacto (Strip horizontal justo arriba del footer)
    resumen_frame = tk.Frame(ventana_reporte, bg=t["bg_card"], relief="solid", bd=1)
    resumen_frame.pack(fill="x", side="bottom", padx=12, pady=(0, 6))

    resumen_title_bar = tk.Frame(resumen_frame, bg="#3B82F6", height=24)
    resumen_title_bar.pack(fill="x")
    resumen_title_bar.pack_propagate(False)
    tk.Label(resumen_title_bar, text="📈 RESUMEN FINANCIERO CONSOLIDADO", font=("Segoe UI", 9, "bold"),
             bg="#3B82F6", fg="white").pack(side="left", padx=10)

    resumen_content = tk.Frame(resumen_frame, bg=t["bg_card"])
    resumen_content.pack(fill="x", padx=10, pady=6)
    for col_idx in range(6):
        resumen_content.columnconfigure(col_idx, weight=1)
    
    # Body Frame para las tablas (lado a lado)
    tablas_frame = tk.Frame(ventana_reporte, bg=t["bg_app"])
    tablas_frame.pack(fill="both", expand=True, padx=12, pady=8)

    # TABLA DE VENTAS (Izquierda)
    ventas_frame = tk.Frame(tablas_frame, bg=t["bg_surface"], relief="solid", bd=1)
    ventas_frame.pack(side="left", fill="both", expand=True, padx=(0, 6))

    ventas_header = tk.Frame(ventas_frame, bg="#10B981", height=28)
    ventas_header.pack(fill="x")
    ventas_header.pack_propagate(False)
    tk.Label(ventas_header, text="💰 VENTAS DEL PERÍODO", font=("Segoe UI", 10, "bold"), 
             bg="#10B981", fg="white").pack(side="left", padx=8)

    ventas_table_container = tk.Frame(ventas_frame, bg=t["bg_surface"])
    ventas_table_container.pack(fill="both", expand=True, padx=3, pady=3)
    ventas_table_container.rowconfigure(0, weight=1)
    ventas_table_container.columnconfigure(0, weight=1)

    columnas_ventas = ("Fecha", "Hora", "Producto", "Cant.", "P. Unit.", "Subtotal", "Método")
    tabla_ventas = ttk.Treeview(ventas_table_container, columns=columnas_ventas, show="headings")
    tabla_ventas.grid(row=0, column=0, sticky="nsew")

    v_scroll_v = ttk.Scrollbar(ventas_table_container, orient="vertical", command=tabla_ventas.yview)
    v_scroll_v.grid(row=0, column=1, sticky="ns")
    h_scroll_v = ttk.Scrollbar(ventas_table_container, orient="horizontal", command=tabla_ventas.xview)
    h_scroll_v.grid(row=1, column=0, sticky="ew")
    tabla_ventas.configure(yscrollcommand=v_scroll_v.set, xscrollcommand=h_scroll_v.set)

    widths_ventas = [75, 55, 140, 45, 75, 75, 80]
    for i, col in enumerate(columnas_ventas):
        tabla_ventas.heading(col, text=col)
        tabla_ventas.column(col, width=widths_ventas[i], anchor="center")

    # TABLA DE GASTOS (Derecha)
    gastos_frame = tk.Frame(tablas_frame, bg=t["bg_surface"], relief="solid", bd=1)
    gastos_frame.pack(side="right", fill="both", expand=True, padx=(6, 0))

    gastos_header = tk.Frame(gastos_frame, bg="#EF4444", height=28)
    gastos_header.pack(fill="x")
    gastos_header.pack_propagate(False)
    tk.Label(gastos_header, text="💸 GASTOS DEL PERÍODO", font=("Segoe UI", 10, "bold"), 
             bg="#EF4444", fg="white").pack(side="left", padx=8)

    gastos_table_container = tk.Frame(gastos_frame, bg=t["bg_surface"])
    gastos_table_container.pack(fill="both", expand=True, padx=3, pady=3)
    gastos_table_container.rowconfigure(0, weight=1)
    gastos_table_container.columnconfigure(0, weight=1)

    columnas_gastos = ("Fecha", "Hora", "Concepto", "Valor", "Medio")
    tabla_gastos = ttk.Treeview(gastos_table_container, columns=columnas_gastos, show="headings")
    tabla_gastos.grid(row=0, column=0, sticky="nsew")

    v_scroll_g = ttk.Scrollbar(gastos_table_container, orient="vertical", command=tabla_gastos.yview)
    v_scroll_g.grid(row=0, column=1, sticky="ns")
    h_scroll_g = ttk.Scrollbar(gastos_table_container, orient="horizontal", command=tabla_gastos.xview)
    h_scroll_g.grid(row=1, column=0, sticky="ew")
    tabla_gastos.configure(yscrollcommand=v_scroll_g.set, xscrollcommand=h_scroll_g.set)

    widths_gastos = [75, 55, 160, 85, 100]
    for i, col in enumerate(columnas_gastos):
        tabla_gastos.heading(col, text=col)
        tabla_gastos.column(col, width=widths_gastos[i], anchor="center")

    # Obtener y mostrar datos de VENTAS - VERSIÓN SEGURA
    total_ventas_periodo = 0
    total_efectivo = 0
    total_transferencia = 0
    total_fiado = 0
    
    try:
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name IN ('ventas', 'detalle_ventas')
        """)
        tablas_existentes = [row[0] for row in cursor.fetchall()]
    
        if 'ventas' not in tablas_existentes:
            ventas_periodo = []
        elif 'detalle_ventas' not in tablas_existentes:
            cursor.execute("""
                SELECT fecha_venta, hora_venta, 'Venta General' as producto, 1 as cantidad, total_venta, total_venta, COALESCE(metodo_pago, 'Efectivo')
                FROM ventas
                WHERE (fecha_venta BETWEEN ? AND ?)
                  AND (estado IS NULL OR estado != 'Anulada')
                ORDER BY fecha_venta DESC, hora_venta DESC
            """, (fecha_inicio_str, fecha_fin_str))
            ventas_periodo = cursor.fetchall()
        else:
            cursor.execute("""
                SELECT v.fecha_venta, v.hora_venta, 
                   COALESCE(dv.nombre_producto, 'Venta General') as nombre_producto, 
                   COALESCE(dv.cantidad, 1) as cantidad, 
                   COALESCE(dv.precio_unitario, v.total_venta) as precio_unitario, 
                   COALESCE(dv.subtotal, v.total_venta) as subtotal,
                   COALESCE(v.metodo_pago, 'Efectivo') as metodo_pago
                FROM ventas v
                LEFT JOIN detalle_ventas dv ON v.id_venta = dv.id_venta
                WHERE (v.fecha_venta BETWEEN ? AND ?)
                  AND (v.estado IS NULL OR v.estado != 'Anulada')
                ORDER BY v.fecha_venta DESC, v.hora_venta DESC
            """, (fecha_inicio_str, fecha_fin_str))
            ventas_periodo = cursor.fetchall()
        
        for venta in ventas_periodo:
            tabla_ventas.insert("", tk.END, values=(
                venta[0], venta[1], venta[2], venta[3], 
                formato_peso(venta[4]), formato_peso(venta[5]), venta[6]
            ))
            total_ventas_periodo += venta[5]
            if venta[6] == "Efectivo": total_efectivo += venta[5]
            elif venta[6] == "Transferencia": total_transferencia += venta[5]
            elif venta[6] == "Fiado": total_fiado += venta[5]

    except Exception as e:
        messagebox.showerror("❌ Error al cargar ventas", str(e))

    # Obtener y mostrar datos de GASTOS
    total_gastos_periodo = 0
    gastos_efectivo = 0
    gastos_transferencia = 0
    gastos_periodo = obtener_gastos_periodo(fecha_inicio_str, fecha_fin_str)
    
    for gasto in gastos_periodo:
        tabla_gastos.insert("", tk.END, values=(
            gasto[2], gasto[3], gasto[0], formato_peso(gasto[1]), gasto[4]
        ))
        total_gastos_periodo += gasto[1]
        if gasto[4] == "Transferencia":
            gastos_transferencia += gasto[1]
        else:
            gastos_efectivo += gasto[1]

    # Calcular ganancia neta (solo ingresos liquidos vs gastos)
    ingresos_liquidos = total_efectivo + total_transferencia
    ganancia_neta = ingresos_liquidos - total_gastos_periodo

    resumen_data = [
        ("💰 Ventas Brutas", formato_peso(total_ventas_periodo), t["text_primary"]),
        ("💵 Efectivo", formato_peso(total_efectivo), "#10B981"),
        ("💳 Transferencias", formato_peso(total_transferencia), "#0EA5E9"),
        ("📝 Por Cobrar", formato_peso(total_fiado), "#F59E0B"),
        ("💸 Gastos", formato_peso(total_gastos_periodo), "#EF4444"),
        ("Caja real", formato_peso(total_efectivo - gastos_efectivo), "#059669"),
        ("Transferencia real", formato_peso(total_transferencia - gastos_transferencia), "#0284C7"),
        ("📊 Ganancia Neta", formato_peso(ganancia_neta), "#10B981" if ganancia_neta >= 0 else "#EF4444")
    ]

    for col_idx, (label, valor, color) in enumerate(resumen_data):
        card = tk.Frame(resumen_content, bg=t["bg_surface"], relief="solid", bd=1, padx=6, pady=4)
        card.grid(row=0, column=col_idx, padx=3, sticky="nsew")
        
        tk.Label(card, text=label, font=("Segoe UI", 8, "bold"), bg=t["bg_surface"], fg=t["text_secondary"]).pack(anchor="w")
        tk.Label(card, text=valor, font=("Segoe UI", 10, "bold"), bg=t["bg_surface"], fg=color).pack(anchor="w")

def generar_reporte_mensual_pdf():
    """Generates a monthly report and creates a PDF with expenses included."""
    if not REPORTLAB_DISPONIBLE:
        messagebox.showerror("❌ Error", "ReportLab no está disponible. No se pueden generar reportes PDF.")
        return
        
    if not cursor: return
    try:
        # Calcular fechas del mes actual
        hoy = datetime.now()
        ultimo_dia = calendar.monthrange(hoy.year, hoy.month)[1]
        fecha_inicio_str = hoy.replace(day=1).strftime("%Y-%m-%d")
        fecha_fin_str = hoy.replace(day=ultimo_dia).strftime("%Y-%m-%d")

        # Obtener datos de ventas
        cursor.execute("""
            SELECT v.fecha_venta, v.hora_venta, v.total_venta
            FROM ventas v
            WHERE (v.fecha_venta BETWEEN ? AND ?)
              AND (v.estado IS NULL OR v.estado != 'Anulada')
            ORDER BY v.fecha_venta DESC
        """, (fecha_inicio_str, fecha_fin_str))
        ventas_mes = cursor.fetchall()
        
        cursor.execute("""
            SELECT SUM(total_venta) FROM ventas
            WHERE (fecha_venta BETWEEN ? AND ?)
              AND (estado IS NULL OR estado != 'Anulada')
        """, (fecha_inicio_str, fecha_fin_str))
        total_ventas = cursor.fetchone()[0] or 0

        # Obtener datos de gastos
        gastos_mes = obtener_gastos_periodo(fecha_inicio_str, fecha_fin_str)
        total_gastos = sum(gasto[1] for gasto in gastos_mes)
        
        # Calcular ganancia neta
        ganancia_neta = total_ventas - total_gastos
        
        # Crear PDF
        pdf_path = os.path.join(pdf_dir, f"Reporte_Mensual_Completo_{hoy.strftime('%Y-%m')}.pdf")
        doc = SimpleDocTemplate(pdf_path, pagesize=letter)
        story = []
        
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name='Heading1', fontSize=18, fontName='Helvetica-Bold'))
        styles.add(ParagraphStyle(name='Normal', fontSize=10))

        story.append(Paragraph("Reporte Financiero Mensual Completo", styles['Heading1']))
        story.append(Paragraph(f"Periodo: {fecha_inicio_str} a {fecha_fin_str}", styles['Normal']))
        story.append(Spacer(1, 0.2 * inch))

        # Resumen ejecutivo
        story.append(Paragraph("<b>RESUMEN EJECUTIVO</b>", styles['Normal']))
        story.append(Paragraph(f"<b>Total de Ventas:</b> {formato_peso(total_ventas)}", styles['Normal']))
        story.append(Paragraph(f"<b>Total de Gastos:</b> {formato_peso(total_gastos)}", styles['Normal']))
        story.append(Paragraph(f"<b>Ganancia Neta:</b> {formato_peso(ganancia_neta)}", styles['Normal']))
        story.append(Spacer(1, 0.3 * inch))

        # Tabla de ventas
        story.append(Paragraph("<b>DETALLE DE VENTAS</b>", styles['Normal']))
        data_ventas = [["Fecha", "Hora", "Total Venta"]]
        for venta in ventas_mes:
            data_ventas.append([venta[0], venta[1], formato_peso(venta[2])])

        if len(data_ventas) > 1:
            table_ventas = Table(data_ventas, colWidths=[2.5*inch, 2*inch, 2.5*inch])
            table_ventas.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4CAF50')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#E8F5E8')),
                ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#4CAF50'))
            ]))
            story.append(table_ventas)
        
        story.append(Spacer(1, 0.3 * inch))

        # Tabla de gastos
        story.append(Paragraph("<b>DETALLE DE GASTOS</b>", styles['Normal']))
        data_gastos = [["Fecha", "Concepto", "Valor"]]
        for gasto in gastos_mes:
            data_gastos.append([gasto[2], gasto[0], formato_peso(gasto[1])])

        if len(data_gastos) > 1:
            table_gastos = Table(data_gastos, colWidths=[2*inch, 3.5*inch, 2.5*inch])
            table_gastos.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#FF5722')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#FFE8E0')),
                ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#FF5722'))
            ]))
            story.append(table_gastos)
        else:
            story.append(Paragraph("No hay gastos registrados en este periodo.", styles['Normal']))

        doc.build(story)

        # Guardar en la base de datos
        resumen = f"Ventas: {formato_peso(total_ventas)} | Gastos: {formato_peso(total_gastos)} | Ganancia: {formato_peso(ganancia_neta)}"
        cursor.execute("""
            INSERT INTO reportes (tipo, fecha_inicio, fecha_fin, resumen, ruta_pdf)
            VALUES (?, ?, ?, ?, ?)
        """, ('mensual', fecha_inicio_str, fecha_fin_str, resumen, pdf_path))
        conn.commit()

        messagebox.showinfo("✅ Reporte Mensual", f"Reporte mensual completo generado exitosamente.\n\n{resumen}")
        
    except Exception as e:
        messagebox.showerror("❌ Error al generar reporte", f"Error: {str(e)}")
        conn.rollback()

def generar_excel_mensual(mes=None, anio=None, modal_padre=None):
    """
    Genera un archivo Excel profesional con el reporte mensual detallado:
    1. Resumen Financiero y Estadísticas Generales
    2. Tablas Porcentuales (Métodos de Pago, Top Productos y Desglose Diario)
    3. Productividad y Ranking por Operario / Vendedor
    4. Detalle Completo de Ventas del Mes
    """
    if not OPENPYXL_DISPONIBLE:
        messagebox.showerror("❌ Error", "OpenPyXL no está disponible. No se pueden generar reportes Excel.")
        return

    if not cursor:
        if not conectar_db():
            messagebox.showerror("❌ Error", "No se pudo conectar a la base de datos.")
            return

    # Si no se especifican mes y año, abrir diálogo interactivo de selección
    if mes is None or anio is None:
        hoy = datetime.now()
        mes = hoy.month
        anio = hoy.year

        dialogo = tk.Toplevel(modal_padre) if modal_padre else tk.Toplevel()
        dialogo.title("📊 Generar Cierre Mensual Excel")
        calcular_geometria_segura(dialogo, 440, 270, modal_padre=modal_padre)
        t_d = aplicar_tema(dialogo)
        dialogo.configure(bg=t_d["bg_app"])
        dialogo.resizable(False, False)
        dialogo.grab_set()

        hdr = tk.Frame(dialogo, bg=t_d["primary"], height=48)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="📊 CIERRE MENSUAL EXCEL", font=("Segoe UI", 11, "bold"), bg=t_d["primary"], fg="white").pack(side="left", padx=15, pady=12)

        content = tk.Frame(dialogo, bg=t_d["bg_surface"], padx=20, pady=15, bd=1, relief="solid")
        content.pack(fill="both", expand=True, padx=15, pady=12)

        MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        
        tk.Label(content, text="Selecciona el período mensual a consolidar:", font=("Segoe UI", 9, "bold"), bg=t_d["bg_surface"], fg=t_d["text_primary"]).pack(anchor="w", pady=(0, 10))

        row_sel = tk.Frame(content, bg=t_d["bg_surface"])
        row_sel.pack(fill="x", pady=5)

        tk.Label(row_sel, text="Mes:", font=("Segoe UI", 9), bg=t_d["bg_surface"], fg=t_d["text_secondary"]).pack(side="left", padx=(0, 6))
        mes_cb = ttk.Combobox(row_sel, values=MESES, state="readonly", width=14, font=("Segoe UI", 9))
        mes_cb.current(mes - 1)
        mes_cb.pack(side="left", padx=(0, 15))

        tk.Label(row_sel, text="Año:", font=("Segoe UI", 9), bg=t_d["bg_surface"], fg=t_d["text_secondary"]).pack(side="left", padx=(0, 6))
        anio_cb = ttk.Combobox(row_sel, values=[str(y) for y in range(2024, 2030)], state="readonly", width=8, font=("Segoe UI", 9))
        anio_cb.set(str(anio))
        anio_cb.pack(side="left")

        def ejecutar_generacion():
            idx_mes = mes_cb.current() + 1
            val_anio = int(anio_cb.get())
            dialogo.destroy()
            _ejecutar_generacion_excel_mes(idx_mes, val_anio)

        btn_box = tk.Frame(dialogo, bg=t_d["bg_app"])
        btn_box.pack(fill="x", padx=15, pady=(0, 12))

        crear_boton(btn_box, "Generar Informe Excel", ejecutar_generacion, tipo="primary").pack(side="right")
        crear_boton(btn_box, "Cancelar", dialogo.destroy, tipo="secondary").pack(side="left")
        return

    return _ejecutar_generacion_excel_mes(mes, anio)


def _ejecutar_generacion_excel_mes(mes, anio, mostrar_alerta=True, abrir_archivo=True):
    """Construcción física del libro de Excel con las 4 hojas estadísticas y porcentuales."""
    try:
        global conn, cursor
        if cursor is None or conn is None:
            conectar_db()

        MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        nombre_mes = MESES[mes - 1]
        ultimo_dia = calendar.monthrange(anio, mes)[1]
        fecha_inicio_str = f"{anio}-{mes:02d}-01"
        fecha_fin_str = f"{anio}-{mes:02d}-{ultimo_dia:02d}"

        os.makedirs(excel_dir, exist_ok=True)
        nombre_negocio_safe = "".join(c for c in business_mgr.nombre if c.isalnum() or c in (' ', '_')).strip().replace(' ', '_')
        excel_path = os.path.join(excel_dir, f"Cierre_Mensual_{nombre_negocio_safe}_{anio}_{mes:02d}.xlsx")

        wb = Workbook()
        wb.remove(wb.active)  # Eliminar hoja vacía por defecto

        # Estilos corporativos
        color_hex = business_mgr.color_barra.replace("#", "") if business_mgr.color_barra else "1B5E20"
        fill_header = PatternFill(start_color=color_hex, end_color=color_hex, fill_type="solid")
        fill_sub = PatternFill(start_color="334155", end_color="334155", fill_type="solid")
        fill_total = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")

        font_titulo = Font(name="Calibri", size=13, bold=True, color="FFFFFF")
        font_header = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
        font_bold = Font(name="Calibri", size=10, bold=True)
        font_normal = Font(name="Calibri", size=10)

        border_thin = Border(
            left=Side(style='thin', color='CBD5E1'),
            right=Side(style='thin', color='CBD5E1'),
            top=Side(style='thin', color='CBD5E1'),
            bottom=Side(style='thin', color='CBD5E1')
        )
        border_total = Border(
            left=Side(style='thin', color='94A3B8'),
            right=Side(style='thin', color='94A3B8'),
            top=Side(style='medium', color='1E293B'),
            bottom=Side(style='double', color='1E293B')
        )

        # -------------------------------------------------------------
        # HOJA 1: RESUMEN FINANCIERO Y ESTADÍSTICAS
        # -------------------------------------------------------------
        ws1 = wb.create_sheet("Resumen Ejecutivo")

        # Título
        ws1.merge_cells('A1:E1')
        ws1['A1'] = f"{business_mgr.nombre.upper()} - CIERRE FINANCIERO Y ESTADÍSTICO ({nombre_mes.upper()} {anio})"
        ws1['A1'].font = font_titulo
        ws1['A1'].fill = fill_header
        ws1['A1'].alignment = Alignment(horizontal='center', vertical='center')
        ws1.row_dimensions[1].height = 36

        ws1.merge_cells('A2:E2')
        ws1['A2'] = f"Período Evaluado: {fecha_inicio_str} al {fecha_fin_str}  |  Fecha de Generación: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        ws1['A2'].font = Font(name="Calibri", size=9, italic=True, color="475569")
        ws1['A2'].alignment = Alignment(horizontal='center')

        # Consultas de métricas
        cursor.execute("SELECT COALESCE(SUM(total_venta), 0.0), COUNT(id_venta) FROM ventas WHERE (fecha_venta BETWEEN ? AND ?) AND (estado IS NULL OR estado != 'Anulada')", (fecha_inicio_str, fecha_fin_str))
        row_v = cursor.fetchone()
        tot_ventas = row_v[0] or 0.0
        tot_transacciones = row_v[1] or 0

        cursor.execute("""
            SELECT COALESCE(SUM(dv.cantidad * COALESCE(p.costo, 0.0)), 0.0), COALESCE(SUM(dv.cantidad), 0)
            FROM detalle_ventas dv
            INNER JOIN ventas v ON dv.id_venta = v.id_venta
            LEFT JOIN productos p ON dv.codigo_producto = p.codigo
            WHERE (v.fecha_venta BETWEEN ? AND ?) AND (v.estado IS NULL OR v.estado != 'Anulada')
        """, (fecha_inicio_str, fecha_fin_str))
        row_c = cursor.fetchone()
        tot_costos = row_c[0] or 0.0
        tot_unidades = row_c[1] or 0

        gastos_mes = obtener_gastos_periodo(fecha_inicio_str, fecha_fin_str)
        tot_gastos = sum(g[1] for g in gastos_mes)

        utilidad_bruta = tot_ventas - tot_costos
        ganancia_neta = tot_ventas - tot_costos - tot_gastos
        margen_neto_pct = (ganancia_neta / tot_ventas) if tot_ventas > 0 else 0.0
        ticket_promedio = (tot_ventas / tot_transacciones) if tot_transacciones > 0 else 0.0
        unidades_por_ticket = (tot_unidades / tot_transacciones) if tot_transacciones > 0 else 0.0

        cursor.execute("SELECT COUNT(DISTINCT fecha_venta) FROM ventas WHERE (fecha_venta BETWEEN ? AND ?) AND (estado IS NULL OR estado != 'Anulada')", (fecha_inicio_str, fecha_fin_str))
        dias_activos = cursor.fetchone()[0] or 0
        promedio_diario = (tot_ventas / dias_activos) if dias_activos > 0 else 0.0

        # Tabla Resumen Financiero
        ws1['A4'] = "INDICADOR FINANCIERO"
        ws1['B4'] = "VALOR"
        ws1['C4'] = "INCIDENCIA / NOTA"
        for col in ['A4', 'B4', 'C4']:
            ws1[col].font = font_header
            ws1[col].fill = fill_sub
            ws1[col].alignment = Alignment(horizontal='center' if col != 'A4' else 'left')

        metricas_financieras = [
            ("Total Ventas Facturadas (Ingresos Brutos)", tot_ventas, "$#,##0", "100.0% Base"),
            ("Costo Estimado de Mercancía / Insumos", tot_costos, "$#,##0", f"{(tot_costos/tot_ventas*100):.1f}% de costo" if tot_ventas > 0 else "0%"),
            ("Utilidad Bruta (Ventas - Costos)", utilidad_bruta, "$#,##0", f"{(utilidad_bruta/tot_ventas*100):.1f}% margen bruto" if tot_ventas > 0 else "0%"),
            ("Gastos Operativos Registrados (Servicios/Nómina)", tot_gastos, "$#,##0", f"{(tot_gastos/tot_ventas*100):.1f}% de gastos" if tot_ventas > 0 else "0%"),
            ("Ganancia Neta Real del Mes", ganancia_neta, "$#,##0", "Beneficio Líquido Final"),
            ("Margen Neto de Rentabilidad (%)", margen_neto_pct, "0.0%", "Rentabilidad Neta sobre Ventas")
        ]

        for i, (concepto, valor, formato, nota) in enumerate(metricas_financieras, 5):
            ws1[f'A{i}'] = concepto
            ws1[f'B{i}'] = valor
            ws1[f'C{i}'] = nota
            ws1[f'A{i}'].font = font_bold if "Ganancia" in concepto or "Total" in concepto else font_normal
            ws1[f'B{i}'].font = font_bold if "Ganancia" in concepto or "Total" in concepto else font_normal
            ws1[f'B{i}'].number_format = formato
            ws1[f'C{i}'].font = Font(name="Calibri", size=9, color="475569")
            for c in ['A', 'B', 'C']:
                ws1[f'{c}{i}'].border = border_thin
                if "Ganancia" in concepto:
                    ws1[f'{c}{i}'].fill = PatternFill(start_color="DCFCE7", fill_type="solid")

        # Tabla Estadísticas Operativas
        row_op = 12
        ws1[f'A{row_op}'] = "INDICADOR OPERATIVO Y COMERCIAL"
        ws1[f'B{row_op}'] = "VALOR"
        ws1[f'C{row_op}'] = "UNIDAD DE MEDIDA"
        for col in [f'A{row_op}', f'B{row_op}', f'C{row_op}']:
            ws1[col].font = font_header
            ws1[col].fill = fill_sub
            ws1[col].alignment = Alignment(horizontal='center' if 'A' not in col else 'left')

        metricas_operativas = [
            ("Total de Facturas / Pedidos Atendidos", tot_transacciones, "#,##0", "Transacciones"),
            ("Ticket Promedio Facturado por Cliente", ticket_promedio, "$#,##0", "COP por Venta"),
            ("Total de Unidades / Artículos Vendidos", tot_unidades, "#,##0", "Unidades Físicas / Copias"),
            ("Promedio de Artículos por Factura", unidades_por_ticket, "0.0", "Unidades por Venta"),
            ("Días con Actividad Comercial en el Mes", dias_activos, "#,##0", f"de {ultimo_dia} días del mes"),
            ("Promedio de Facturación Diaria Activa", promedio_diario, "$#,##0", "COP por Día Activo")
        ]

        for j, (ind, val, fmt, uni) in enumerate(metricas_operativas, row_op + 1):
            ws1[f'A{j}'] = ind
            ws1[f'B{j}'] = val
            ws1[f'C{j}'] = uni
            ws1[f'A{j}'].font = font_normal
            ws1[f'B{j}'].font = font_bold
            ws1[f'B{j}'].number_format = fmt
            ws1[f'C{j}'].font = Font(name="Calibri", size=9, color="475569")
            for c in ['A', 'B', 'C']:
                ws1[f'{c}{j}'].border = border_thin

        # -------------------------------------------------------------
        # HOJA 2: TABLAS PORCENTUALES
        # -------------------------------------------------------------
        ws2 = wb.create_sheet("Tablas Porcentuales")

        ws2.merge_cells('A1:D1')
        ws2['A1'] = f"TABLAS PORCENTUALES Y DISTRIBUCIÓN - {nombre_mes.upper()} {anio}"
        ws2['A1'].font = font_titulo
        ws2['A1'].fill = fill_header
        ws2['A1'].alignment = Alignment(horizontal='center', vertical='center')
        ws2.row_dimensions[1].height = 34

        # A. Métodos de pago
        ws2['A3'] = "1. PARTICIPACIÓN POR MÉTODO DE PAGO"
        ws2['A3'].font = Font(name="Calibri", size=11, bold=True, color=color_hex)

        headers_pago = ["Método de Pago", "Transacciones", "Total Facturado ($)", "% Participación"]
        for col_idx, h in enumerate(headers_pago, 1):
            cell = ws2.cell(row=4, column=col_idx, value=h)
            cell.font = font_header
            cell.fill = fill_sub
            cell.alignment = Alignment(horizontal='center' if col_idx > 1 else 'left')

        cursor.execute("""
            SELECT COALESCE(metodo_pago, 'Efectivo') as metodo, COUNT(*), SUM(total_venta)
            FROM ventas
            WHERE (fecha_venta BETWEEN ? AND ?)
              AND (estado IS NULL OR estado != 'Anulada')
            GROUP BY COALESCE(metodo_pago, 'Efectivo')
            ORDER BY SUM(total_venta) DESC
        """, (fecha_inicio_str, fecha_fin_str))
        pagos_data = cursor.fetchall()

        r = 5
        for p in pagos_data:
            metodo_nombre = p[0]
            cant_p = p[1]
            monto_p = p[2] or 0.0
            pct_p = (monto_p / tot_ventas) if tot_ventas > 0 else 0.0

            ws2.cell(row=r, column=1, value=metodo_nombre).font = font_normal
            ws2.cell(row=r, column=2, value=cant_p).number_format = "#,##0"
            cell_m = ws2.cell(row=r, column=3, value=monto_p)
            cell_m.number_format = "$#,##0"
            cell_m.font = font_bold
            cell_pct = ws2.cell(row=r, column=4, value=pct_p)
            cell_pct.number_format = "0.0%"
            cell_pct.font = font_bold

            for c_i in range(1, 5):
                ws2.cell(row=r, column=c_i).border = border_thin
            r += 1

        # Fila Total Pagos
        ws2.cell(row=r, column=1, value="TOTAL CONSOLIDADO").font = font_bold
        ws2.cell(row=r, column=2, value=tot_transacciones).number_format = "#,##0"
        cell_tm = ws2.cell(row=r, column=3, value=tot_ventas)
        cell_tm.number_format = "$#,##0"
        cell_tm.font = font_bold
        cell_tp = ws2.cell(row=r, column=4, value=1.0 if tot_ventas > 0 else 0.0)
        cell_tp.number_format = "0.0%"
        cell_tp.font = font_bold
        for c_i in range(1, 5):
            ws2.cell(row=r, column=c_i).border = border_total
            ws2.cell(row=r, column=c_i).fill = fill_total

        # B. Top 10 Productos y Participación
        r_prod = r + 3
        ws2.cell(row=r_prod, column=1, value="2. TOP 10 PRODUCTOS Y SERVICIOS CON MAYOR FACTURACIÓN").font = Font(name="Calibri", size=11, bold=True, color=color_hex)
        r_prod += 1

        headers_prod = ["Ranking", "Producto / Servicio", "Unidades Vendidas", "Total Facturado ($)", "% del Total Mensual"]
        for col_idx, h in enumerate(headers_prod, 1):
            cell = ws2.cell(row=r_prod, column=col_idx, value=h)
            cell.font = font_header
            cell.fill = fill_sub
            cell.alignment = Alignment(horizontal='center' if col_idx != 2 else 'left')

        cursor.execute("""
            SELECT dv.nombre_producto, SUM(dv.cantidad), SUM(dv.subtotal)
            FROM detalle_ventas dv
            INNER JOIN ventas v ON dv.id_venta = v.id_venta
            WHERE (v.fecha_venta BETWEEN ? AND ?)
              AND (v.estado IS NULL OR v.estado != 'Anulada')
            GROUP BY dv.nombre_producto
            ORDER BY SUM(dv.subtotal) DESC
            LIMIT 10
        """, (fecha_inicio_str, fecha_fin_str))
        prods_data = cursor.fetchall()

        r_prod += 1
        for idx_p, prod in enumerate(prods_data, 1):
            nom_p = prod[0]
            cant_p = prod[1] or 0
            monto_p = prod[2] or 0.0
            pct_prod = (monto_p / tot_ventas) if tot_ventas > 0 else 0.0

            ws2.cell(row=r_prod, column=1, value=f"{idx_p}º").alignment = Alignment(horizontal='center')
            ws2.cell(row=r_prod, column=2, value=nom_p).font = font_normal
            ws2.cell(row=r_prod, column=3, value=cant_p).number_format = "#,##0"
            cell_pm = ws2.cell(row=r_prod, column=4, value=monto_p)
            cell_pm.number_format = "$#,##0"
            cell_pm.font = font_bold
            cell_pp = ws2.cell(row=r_prod, column=5, value=pct_prod)
            cell_pp.number_format = "0.0%"
            cell_pp.font = font_bold

            for c_i in range(1, 6):
                ws2.cell(row=r_prod, column=c_i).border = border_thin
            r_prod += 1

        # -------------------------------------------------------------
        # HOJA 3: RANKING Y RENDIMIENTO DE OPERARIOS (QUIÉN VENDE MÁS)
        # -------------------------------------------------------------
        ws3 = wb.create_sheet("Ranking Operarios")

        ws3.merge_cells('A1:G1')
        ws3['A1'] = f"RANKING Y PRODUCTIVIDAD DE OPERARIOS / VENDEDORES - {nombre_mes.upper()} {anio}"
        ws3['A1'].font = font_titulo
        ws3['A1'].fill = fill_header
        ws3['A1'].alignment = Alignment(horizontal='center', vertical='center')
        ws3.row_dimensions[1].height = 34

        ws3.merge_cells('A2:G2')
        ws3['A2'] = "Evaluación de productividad: quién genera mayor facturación, volumen de pedidos y ticket promedio."
        ws3['A2'].font = Font(name="Calibri", size=9, italic=True, color="475569")
        ws3['A2'].alignment = Alignment(horizontal='center')

        headers_op = [
            "Posición", "Operario / Vendedor", "Facturas Atendidas",
            "Unidades Vendidas", "Total Facturado ($)", "% Participación del Mes", "Ticket Promedio ($)"
        ]
        for col_idx, h in enumerate(headers_op, 1):
            cell = ws3.cell(row=4, column=col_idx, value=h)
            cell.font = font_header
            cell.fill = fill_sub
            cell.alignment = Alignment(horizontal='center' if col_idx != 2 else 'left')

        cursor.execute("""
            SELECT COALESCE(operario, 'Administrador') as nombre_op,
                   COUNT(id_venta) as total_pedidos,
                   SUM(total_venta) as total_monto
            FROM ventas
            WHERE (fecha_venta BETWEEN ? AND ?)
              AND (estado IS NULL OR estado != 'Anulada')
            GROUP BY COALESCE(operario, 'Administrador')
            ORDER BY total_monto DESC
        """, (fecha_inicio_str, fecha_fin_str))
        ops_data = cursor.fetchall()

        r_op = 5
        medals = ["🥇 1º", "🥈 2º", "🥉 3º"]
        for idx_op, op in enumerate(ops_data, 1):
            nom_op = op[0]
            pedidos_op = op[1] or 0
            monto_op = op[2] or 0.0
            pct_op = (monto_op / tot_ventas) if tot_ventas > 0 else 0.0
            ticket_op = (monto_op / pedidos_op) if pedidos_op > 0 else 0.0

            cursor.execute("""
                SELECT COALESCE(SUM(dv.cantidad), 0)
                FROM detalle_ventas dv
                INNER JOIN ventas v ON dv.id_venta = v.id_venta
                WHERE COALESCE(v.operario, 'Administrador') = ? AND (v.fecha_venta BETWEEN ? AND ?)
                  AND (v.estado IS NULL OR v.estado != 'Anulada')
            """, (nom_op, fecha_inicio_str, fecha_fin_str))
            uni_op = cursor.fetchone()[0] or 0

            pos_txt = medals[idx_op - 1] if idx_op <= 3 else f"{idx_op}º"
            ws3.cell(row=r_op, column=1, value=pos_txt).alignment = Alignment(horizontal='center')
            ws3.cell(row=r_op, column=2, value=nom_op).font = font_bold if idx_op == 1 else font_normal
            ws3.cell(row=r_op, column=3, value=pedidos_op).number_format = "#,##0"
            ws3.cell(row=r_op, column=4, value=uni_op).number_format = "#,##0"
            cell_om = ws3.cell(row=r_op, column=5, value=monto_op)
            cell_om.number_format = "$#,##0"
            cell_om.font = font_bold
            cell_op = ws3.cell(row=r_op, column=6, value=pct_op)
            cell_op.number_format = "0.0%"
            cell_op.font = font_bold
            cell_ot = ws3.cell(row=r_op, column=7, value=ticket_op)
            cell_ot.number_format = "$#,##0"

            for c_i in range(1, 8):
                ws3.cell(row=r_op, column=c_i).border = border_thin
                if idx_op == 1:
                    ws3.cell(row=r_op, column=c_i).fill = PatternFill(start_color="FEF3C7", fill_type="solid")
            r_op += 1

        # Fila Total Operarios
        ws3.cell(row=r_op, column=1, value="TOTAL").alignment = Alignment(horizontal='center')
        ws3.cell(row=r_op, column=2, value="CONSOLIDADO OPERATIVO").font = font_bold
        ws3.cell(row=r_op, column=3, value=tot_transacciones).number_format = "#,##0"
        ws3.cell(row=r_op, column=4, value=tot_unidades).number_format = "#,##0"
        cell_tom = ws3.cell(row=r_op, column=5, value=tot_ventas)
        cell_tom.number_format = "$#,##0"
        cell_tom.font = font_bold
        cell_top = ws3.cell(row=r_op, column=6, value=1.0 if tot_ventas > 0 else 0.0)
        cell_top.number_format = "0.0%"
        cell_top.font = font_bold
        cell_tot = ws3.cell(row=r_op, column=7, value=ticket_promedio)
        cell_tot.number_format = "$#,##0"
        for c_i in range(1, 8):
            ws3.cell(row=r_op, column=c_i).border = border_total
            ws3.cell(row=r_op, column=c_i).fill = fill_total

        # -------------------------------------------------------------
        # HOJA 4: DETALLE COMPLETO DE VENTAS
        # -------------------------------------------------------------
        ws4 = wb.create_sheet("Detalle de Ventas")

        headers_det = ["Fecha", "Hora", "Factura Nº", "Operario / Vendedor", "Cliente (Documento)", "Método de Pago", "Total Venta ($)"]
        for col_idx, h in enumerate(headers_det, 1):
            cell = ws4.cell(row=1, column=col_idx, value=h)
            cell.font = font_header
            cell.fill = fill_header
            cell.alignment = Alignment(horizontal='center' if col_idx not in (4, 5) else 'left')

        cursor.execute("""
            SELECT v.fecha_venta, v.hora_venta, v.id_venta,
                   COALESCE(v.operario, 'Administrador'),
                   COALESCE(v.documento_cliente, 'Consumidor Final'),
                   COALESCE(v.metodo_pago, 'Efectivo'),
                   v.total_venta
            FROM ventas v
            WHERE (v.fecha_venta BETWEEN ? AND ?)
              AND (v.estado IS NULL OR v.estado != 'Anulada')
            ORDER BY v.fecha_venta DESC, v.hora_venta DESC
        """, (fecha_inicio_str, fecha_fin_str))
        ventas_detalle = cursor.fetchall()

        for row_idx, v in enumerate(ventas_detalle, 2):
            ws4.cell(row=row_idx, column=1, value=v[0]).alignment = Alignment(horizontal='center')
            ws4.cell(row=row_idx, column=2, value=v[1]).alignment = Alignment(horizontal='center')
            ws4.cell(row=row_idx, column=3, value=f"FAC-{v[2]:05d}").alignment = Alignment(horizontal='center')
            ws4.cell(row=row_idx, column=4, value=v[3]).font = font_normal
            ws4.cell(row=row_idx, column=5, value=v[4]).font = font_normal
            ws4.cell(row=row_idx, column=6, value=v[5]).alignment = Alignment(horizontal='center')
            cell_vt = ws4.cell(row=row_idx, column=7, value=v[6])
            cell_vt.number_format = "$#,##0"
            cell_vt.font = font_bold

            for c_i in range(1, 8):
                ws4.cell(row=row_idx, column=c_i).border = border_thin

        # -------------------------------------------------------------
        # AJUSTE AUTOMÁTICO DE ANCHO EN TODAS LAS HOJAS
        # -------------------------------------------------------------
        for ws in [ws1, ws2, ws3, ws4]:
            for col_idx, col in enumerate(ws.columns, 1):
                max_len = 0
                col_letter = get_column_letter(col_idx)
                for cell in col:
                    # Ignorar filas de título combinadas (filas 1 y 2) para no sobredimensionar la primera columna
                    if hasattr(cell, 'row') and cell.row in (1, 2) and ws in (ws1, ws2, ws3):
                        continue
                    val_str = str(cell.value or '')
                    if '\n' in val_str:
                        val_str = max(val_str.split('\n'), key=len)
                    max_len = max(max_len, len(val_str))
                ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

        # Guardar archivo Excel
        wb.save(excel_path)

        # Registrar en la base de datos para historial de reportes
        try:
            cursor.execute("""
                INSERT INTO reportes (tipo, fecha_inicio, fecha_fin, resumen, ruta_pdf)
                VALUES ('mensual', ?, ?, ?, ?)
            """, (fecha_inicio_str, fecha_fin_str, f"Cierre mensual {nombre_mes} {anio} - Total: {formato_peso(tot_ventas)} ({tot_transacciones} ventas).", excel_path))
            conn.commit()
        except Exception as ex_rep:
            print(f"Aviso registrando reporte: {ex_rep}")

        if mostrar_alerta:
            try:
                messagebox.showinfo(
                    "✅ Cierre Mensual en Excel Generado",
                    f"¡El Cierre Mensual de {nombre_mes} {anio} ha sido generado exitosamente!\n\n"
                    f"📁 Archivo: {os.path.basename(excel_path)}\n"
                    f"📍 Ubicación: {excel_path}\n\n"
                    f"📊 Resumen del mes:\n"
                    f"• Ventas Totales: {formato_peso(tot_ventas)}\n"
                    f"• Transacciones: {tot_transacciones}\n"
                    f"• Ganancia Neta: {formato_peso(ganancia_neta)}\n"
                    f"• Margen Neto: {margen_neto_pct*100:.1f}%\n"
                    f"• Operarios Evaluados: {len(ops_data)}"
                )
            except Exception:
                pass

        if abrir_archivo:
            try:
                abrir_archivo_o_carpeta(excel_path)
            except Exception:
                pass
        return excel_path

    except Exception as e:
        if mostrar_alerta:
            try:
                messagebox.showerror("❌ Error al Generar Excel", f"Error durante la generación del informe Excel mensual:\n{str(e)}")
            except Exception:
                pass
        import traceback
        traceback.print_exc()
        return None

def verificar_cierre_mensual_automatico(ventana_padre=None):
    """
    Verifica si hoy es el fin de mes (o primeros días del mes siguiente)
    y sugiere generar el cierre mensual consolidado en Excel si aún no existe.
    """
    try:
        hoy = datetime.now()
        ultimo_dia = calendar.monthrange(hoy.year, hoy.month)[1]
        if hoy.day >= ultimo_dia - 1 or hoy.day <= 2:
            mes_eval = hoy.month if hoy.day >= ultimo_dia - 1 else (12 if hoy.month == 1 else hoy.month - 1)
            anio_eval = hoy.year if hoy.day >= ultimo_dia - 1 else (hoy.year - 1 if hoy.month == 1 else hoy.year)
            nombre_negocio_safe = "".join(c for c in business_mgr.nombre if c.isalnum() or c in (' ', '_')).strip().replace(' ', '_')
            nombre_esperado = f"Cierre_Mensual_{nombre_negocio_safe}_{anio_eval}_{mes_eval:02d}.xlsx"
            ruta_esperada = os.path.join(excel_dir, nombre_esperado)
            if not os.path.exists(ruta_esperada):
                MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
                res = messagebox.askyesno(
                    "📅 Cierre Mensual Detectado",
                    f"🌟 ¡Ha finalizado o está cerrando el mes de {MESES[mes_eval - 1]} {anio_eval}!\n\n"
                    f"¿Deseas generar ahora el informe oficial de Cierre Mensual en Excel con tablas estadísticas, tablas porcentuales y ranking de operarios?"
                )
                if res:
                    generar_excel_mensual(mes=mes_eval, anio=anio_eval, modal_padre=ventana_padre)
    except Exception as e:
        print(f"Aviso verificando cierre mensual: {e}")

def abrir_reportes_mensuales(ventana):
    """Opens a window to view and download monthly reports."""
    if not cursor: return
    
    ventana_mensual = tk.Toplevel(ventana)
    ventana_mensual.title("📁 Reportes Mensuales")
    
    t = aplicar_tema(ventana_mensual)
    calcular_geometria_segura(ventana_mensual, 960, 680, min_w=800, min_h=480)
    ventana_mensual.configure(bg=t["bg_app"])
    ventana_mensual.transient(ventana)
    ventana_mensual.grab_set()
    
    # Header compacto
    header_bar = tk.Frame(ventana_mensual, bg=t["accent"], height=45)
    header_bar.pack(fill="x", side="top")
    header_bar.pack_propagate(False)

    tk.Label(header_bar, text="📁  HISTORIAL DE REPORTES MENSUALES",
             font=("Segoe UI", 13, "bold"), bg=t["accent"], fg="white").pack(side="left", padx=15)

    # Footer fijo de acciones
    footer_bar = tk.Frame(ventana_mensual, bg=t["bg_surface"], height=48, relief="solid", bd=1)
    footer_bar.pack(fill="x", side="bottom")
    footer_bar.pack_propagate(False)

    # Contenedor de la tabla con scrollbars duales
    table_container = tk.Frame(ventana_mensual, bg=t["bg_surface"], relief="solid", bd=1)
    table_container.pack(fill="both", expand=True, padx=15, pady=12)
    table_container.rowconfigure(0, weight=1)
    table_container.columnconfigure(0, weight=1)

    columnas = ("Nº", "Período / Mes", "Fecha Desde", "Fecha Hasta", "Transacciones", "Total Facturado ($)", "Operario Top", "Estado Cierre")
    tabla_reportes = ttk.Treeview(table_container, columns=columnas, show="headings")
    tabla_reportes.grid(row=0, column=0, sticky="nsew")

    v_scroll = ttk.Scrollbar(table_container, orient="vertical", command=tabla_reportes.yview)
    v_scroll.grid(row=0, column=1, sticky="ns")
    h_scroll = ttk.Scrollbar(table_container, orient="horizontal", command=tabla_reportes.xview)
    h_scroll.grid(row=1, column=0, sticky="ew")
    tabla_reportes.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

    tabla_reportes.heading("Nº", text="Nº")
    tabla_reportes.heading("Período / Mes", text="Período / Mes")
    tabla_reportes.heading("Fecha Desde", text="Fecha Desde")
    tabla_reportes.heading("Fecha Hasta", text="Fecha Hasta")
    tabla_reportes.heading("Transacciones", text="Transacciones")
    tabla_reportes.heading("Total Facturado ($)", text="Total Facturado ($)")
    tabla_reportes.heading("Operario Top", text="Operario Líder")
    tabla_reportes.heading("Estado Cierre", text="Estado Cierre")

    tabla_reportes.column("Nº", width=45, anchor="center")
    tabla_reportes.column("Período / Mes", width=140, anchor="w")
    tabla_reportes.column("Fecha Desde", width=100, anchor="center")
    tabla_reportes.column("Fecha Hasta", width=100, anchor="center")
    tabla_reportes.column("Transacciones", width=110, anchor="center")
    tabla_reportes.column("Total Facturado ($)", width=140, anchor="e")
    tabla_reportes.column("Operario Top", width=130, anchor="w")
    tabla_reportes.column("Estado Cierre", width=140, anchor="center")

    MESES_ESP = {
        "01": "Enero", "02": "Febrero", "03": "Marzo", "04": "Abril",
        "05": "Mayo", "06": "Junio", "07": "Julio", "08": "Agosto",
        "09": "Septiembre", "10": "Octubre", "11": "Noviembre", "12": "Diciembre"
    }

    def cargar_reportes():
        tabla_reportes.delete(*tabla_reportes.get_children())
        nombre_negocio_safe = "".join(c for c in business_mgr.nombre if c.isalnum() or c in (' ', '_')).strip().replace(' ', '_')

        # 1. Obtener todos los meses con ventas reales registradas
        cursor.execute("""
            SELECT strftime('%Y-%m', fecha_venta) as mes_key,
                   COUNT(id_venta) as total_pedidos,
                   COALESCE(SUM(total_venta), 0.0) as total_facturado,
                   MIN(fecha_venta) as f_min,
                   MAX(fecha_venta) as f_max
            FROM ventas
            WHERE fecha_venta IS NOT NULL AND fecha_venta != ''
              AND (estado IS NULL OR estado != 'Anulada')
            GROUP BY strftime('%Y-%m', fecha_venta)
            ORDER BY mes_key DESC
        """)
        meses_activos = cursor.fetchall()

        for idx, m in enumerate(meses_activos, 1):
            mes_key, pedidos, total, f_min, f_max = m
            if not mes_key or len(mes_key) < 7:
                continue
            partes = mes_key.split("-")
            anio_str = partes[0]
            mes_str = partes[1]
            nom_mes = f"{MESES_ESP.get(mes_str, mes_str)} {anio_str}"

            # Verificar si existe archivo Excel de cierre mensual
            excel_name = f"Cierre_Mensual_{nombre_negocio_safe}_{anio_str}_{int(mes_str):02d}.xlsx"
            excel_path = os.path.join(excel_dir, excel_name)
            archivo_existe = os.path.exists(excel_path)

            # Buscar operario líder del mes
            cursor.execute("""
                SELECT COALESCE(operario, 'Administrador'), SUM(total_venta)
                FROM ventas
                WHERE strftime('%Y-%m', fecha_venta) = ?
                  AND (estado IS NULL OR estado != 'Anulada')
                GROUP BY COALESCE(operario, 'Administrador')
                ORDER BY SUM(total_venta) DESC LIMIT 1
            """, (mes_key,))
            op_row = cursor.fetchone()
            op_lider = op_row[0] if op_row else "Administrador"

            estado_txt = "✅ Excel Generado" if archivo_existe else "⚡ Listo para Cierre"
            ruta_asociada = excel_path if archivo_existe else ""

            tabla_reportes.insert(
                "", tk.END,
                values=(
                    f"#{idx}",
                    nom_mes,
                    f_min,
                    f_max,
                    f"{pedidos} pedidos",
                    formato_peso(total),
                    op_lider,
                    estado_txt
                ),
                tags=(ruta_asociada, anio_str, mes_str)
            )

    def accionar_excel_seleccionado():
        seleccionado = tabla_reportes.focus()
        if not seleccionado:
            generar_excel_mensual(modal_padre=ventana_mensual)
            cargar_reportes()
            return

        tags = tabla_reportes.item(seleccionado, "tags")
        ruta_archivo = tags[0] if len(tags) > 0 else ""
        anio_sel = int(tags[1]) if len(tags) > 1 and tags[1].isdigit() else datetime.now().year
        mes_sel = int(tags[2]) if len(tags) > 2 and tags[2].isdigit() else datetime.now().month

        if ruta_archivo and os.path.exists(ruta_archivo):
            abrir_archivo_o_carpeta(ruta_archivo)
        else:
            _ejecutar_generacion_excel_mes(mes_sel, anio_sel, mostrar_alerta=True, abrir_archivo=True)
            cargar_reportes()

    def accionar_pdf_mensual():
        generar_reporte_mensual_pdf()
        cargar_reportes()

    def on_double_click(event):
        accionar_excel_seleccionado()

    tabla_reportes.bind("<Double-1>", on_double_click)

    # Actualizar botones del footer para usar las funciones mejoradas
    for btn in footer_bar.winfo_children():
        btn.destroy()

    crear_boton(footer_bar, text="✖ Cerrar", command=ventana_mensual.destroy,
                bg_color=t["btn_secondary_bg"], fg_color=t["btn_secondary_fg"]).pack(side="left", padx=15, pady=6)
    
    crear_boton(footer_bar, text="✨ Generar PDF Mensual",
                command=accionar_pdf_mensual, bg_color="#8B5CF6", fg_color="white").pack(side="right", padx=6, pady=6)
    
    crear_boton(footer_bar, text="📊 Generar / Abrir Excel Mensual",
                command=accionar_excel_seleccionado, bg_color=t["btn_success_bg"], fg_color=t["btn_success_fg"]).pack(side="right", padx=6, pady=6)

    cargar_reportes()

def generar_grafico_ventas_mensuales(ventana):
    """Genera un gráfico de ventas mensuales históricas."""
    if not MATPLOTLIB_DISPONIBLE:
        messagebox.showerror("❌ Error", "Matplotlib no está disponible. No se pueden generar gráficos.")
        return
        
    try:
        cursor.execute("""
            SELECT strftime('%Y-%m', fecha_venta) as mes, 
                   SUM(total_venta) as total_ventas,
                   COUNT(*) as num_ventas
            FROM ventas
            WHERE fecha_venta IS NOT NULL AND fecha_venta != ''
              AND (estado IS NULL OR estado != 'Anulada')
            GROUP BY strftime('%Y-%m', fecha_venta)
            ORDER BY mes ASC
        """)
        
        datos = cursor.fetchall()
        
        if not datos:
            messagebox.showinfo("📊 Sin Datos", "No hay datos suficientes para generar el gráfico.")
            return
        
        # Crear ventana para el gráfico
        ventana_grafico = tk.Toplevel(ventana)
        ventana_grafico.title("📈 Análisis de Ventas Mensuales")
        
        t = aplicar_tema(ventana_grafico)
        calcular_geometria_segura(ventana_grafico, 1080, 730, min_w=850, min_h=520)
        ventana_grafico.configure(bg=t["bg_app"])
        ventana_grafico.transient(ventana)
        ventana_grafico.grab_set()

        # Header compacto
        header_bar = tk.Frame(ventana_grafico, bg=t["accent"], height=45)
        header_bar.pack(fill="x", side="top")
        header_bar.pack_propagate(False)
        tk.Label(header_bar, text="📈  ANÁLISIS DE VENTAS MENSUALES (ÚLTIMOS 12 MESES)",
                 font=("Segoe UI", 13, "bold"), bg=t["accent"], fg="white").pack(side="left", padx=15)

        # Footer fijo de acciones
        footer_bar = tk.Frame(ventana_grafico, bg=t["bg_surface"], height=48, relief="solid", bd=1)
        footer_bar.pack(fill="x", side="bottom")
        footer_bar.pack_propagate(False)

        crear_boton(footer_bar, text="✖ Cerrar Ventana", command=ventana_grafico.destroy,
                    bg_color=t["btn_secondary_bg"], fg_color=t["btn_secondary_fg"]).pack(side="right", padx=15, pady=6)

        # Procesar datos
        meses = []
        ventas = []
        num_transacciones = []
        
        for mes, total_venta, num_venta in datos:
            fecha_mes = datetime.strptime(mes + "-01", "%Y-%m-%d")
            meses.append(fecha_mes)
            ventas.append(total_venta)
            num_transacciones.append(num_venta)
        
        # Estadísticas rápidas (horizontal compact strip)
        promedio_ventas = sum(ventas) / len(ventas)
        mes_mejor = meses[ventas.index(max(ventas))]
        mes_peor = meses[ventas.index(min(ventas))]

        stats_frame = tk.Frame(ventana_grafico, bg=t["bg_card"], relief="solid", bd=1)
        stats_frame.pack(fill="x", side="bottom", padx=15, pady=(0, 8))

        stats_strip = tk.Frame(stats_frame, bg=t["bg_card"])
        stats_strip.pack(fill="x", padx=10, pady=6)
        stats_strip.columnconfigure((0, 1, 2, 3), weight=1)

        metricas_grafico = [
            ("💰 Promedio Mensual", f"${promedio_ventas:,.0f}", t["text_primary"]),
            ("📈 Mejor Mes", f"{mes_mejor.strftime('%b %Y')} (${max(ventas):,.0f})", "#10B981"),
            ("📉 Peor Mes", f"{mes_peor.strftime('%b %Y')} (${min(ventas):,.0f})", "#EF4444"),
            ("📊 Total Período", f"${sum(ventas):,.0f}", "#3B82F6")
        ]

        for idx, (lbl, val, col) in enumerate(metricas_grafico):
            c = tk.Frame(stats_strip, bg=t["bg_surface"], relief="solid", bd=1, padx=8, pady=4)
            c.grid(row=0, column=idx, padx=4, sticky="nsew")
            tk.Label(c, text=lbl, font=("Segoe UI", 8, "bold"), bg=t["bg_surface"], fg=t["text_secondary"]).pack(anchor="w")
            tk.Label(c, text=val, font=("Segoe UI", 10, "bold"), bg=t["bg_surface"], fg=col).pack(anchor="w")

        # Crear gráfico Matplotlib adaptativo al tema
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 5), dpi=100)
        fig.patch.set_facecolor(t["bg_surface"])
        
        ax1.set_facecolor(t["bg_app"])
        ax1.plot(meses, ventas, marker='o', linewidth=2, markersize=6, color=t["accent"])
        ax1.fill_between(meses, ventas, alpha=0.2, color=t["accent"])
        ax1.set_title('Total de Ventas por Mes', fontsize=11, fontweight='bold', color=t["text_primary"])
        ax1.set_ylabel('COP', fontsize=9, color=t["text_secondary"])
        ax1.tick_params(colors=t["text_secondary"])
        ax1.grid(True, alpha=0.25)
        ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
        
        ax2.set_facecolor(t["bg_app"])
        ax2.bar(meses, num_transacciones, color='#3B82F6', alpha=0.8, width=15)
        ax2.set_title('Número de Transacciones por Mes', fontsize=11, fontweight='bold', color=t["text_primary"])
        ax2.set_ylabel('Transacciones', fontsize=9, color=t["text_secondary"])
        ax2.set_xlabel('Mes', fontsize=9, color=t["text_secondary"])
        ax2.tick_params(colors=t["text_secondary"])
        ax2.grid(True, alpha=0.25, axis='y')
        
        for ax in [ax1, ax2]:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
            ax.xaxis.set_major_locator(mdates.MonthLocator())
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, fontsize=8)
        
        plt.tight_layout()
        
        # Integrar gráfico en la ventana
        canvas_container = tk.Frame(ventana_grafico, bg=t["bg_surface"], relief="solid", bd=1)
        canvas_container.pack(fill="both", expand=True, padx=15, pady=10)

        canvas = FigureCanvasTkAgg(fig, canvas_container)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        
    except ImportError:
        messagebox.showerror("❌ Error", "Se requiere instalar matplotlib para generar gráficos.\nEjecute: pip install matplotlib")
    except Exception as e:
        messagebox.showerror("❌ Error", f"Error al generar gráfico: {str(e)}")

def abrir_reporte(tipo, ventana):
    """Calls the corresponding report function."""
    if tipo == "diario":
        generar_reporte_diario(ventana)
    elif tipo == "semanal":
        generar_reporte_semanal(ventana)
    elif tipo == "mensual":
        abrir_reportes_mensuales(ventana)
    elif tipo == "graf_ganancia":
        generar_grafico_ventas_mensuales(ventana)
    elif tipo == "graf_ventas":
        generar_grafico_ventas_mensuales(ventana)
    elif tipo == "graf_categoria":
        generar_productos_mas_vendidos(ventana)
    else:
        print(f"Reporte no implementado: {tipo}")

def generar_productos_mas_vendidos(ventana):
    """Genera un reporte de productos más vendidos."""
    if not cursor: return
    
    fecha_fin = datetime.now()
    fecha_inicio = fecha_fin - timedelta(days=30)
    fecha_fin_str = fecha_fin.strftime("%Y-%m-%d")
    fecha_inicio_str = fecha_inicio.strftime("%Y-%m-%d")

    try:
        cursor.execute("""
            SELECT dv.nombre_producto, 
                   SUM(dv.cantidad) as total_cantidad,
                   SUM(dv.subtotal) as total_ingresos,
                   COUNT(DISTINCT v.id_venta) as num_ventas
            FROM detalle_ventas dv
            INNER JOIN ventas v ON dv.id_venta = v.id_venta
            WHERE (v.fecha_venta BETWEEN ? AND ?)
              AND (v.estado IS NULL OR v.estado != 'Anulada')
            GROUP BY dv.nombre_producto
            ORDER BY total_cantidad DESC
            LIMIT 20
        """, (fecha_inicio_str, fecha_fin_str))
        
        productos_data = cursor.fetchall()
        
        if not productos_data:
            messagebox.showinfo("📭 Sin Datos", "No hay datos de productos vendidos en el último mes.")
            return
        
        ventana_productos = tk.Toplevel(ventana)
        ventana_productos.title("⭐ Productos Más Vendidos")
        
        t = aplicar_tema(ventana_productos)
        calcular_geometria_segura(ventana_productos, 950, 700, min_w=780, min_h=500)
        ventana_productos.configure(bg=t["bg_app"])
        ventana_productos.transient(ventana)
        ventana_productos.grab_set()

        # Header compacto
        header_bar = tk.Frame(ventana_productos, bg=t["accent"], height=45)
        header_bar.pack(fill="x", side="top")
        header_bar.pack_propagate(False)
        tk.Label(header_bar, text="⭐  PRODUCTOS MÁS VENDIDOS - ÚLTIMO MES",
                 font=("Segoe UI", 13, "bold"), bg=t["accent"], fg="white").pack(side="left", padx=15)

        # Footer fijo de acciones
        footer_bar = tk.Frame(ventana_productos, bg=t["bg_surface"], height=48, relief="solid", bd=1)
        footer_bar.pack(fill="x", side="bottom")
        footer_bar.pack_propagate(False)

        crear_boton(footer_bar, text="✖ Cerrar Ventana", command=ventana_productos.destroy,
                    bg_color=t["btn_secondary_bg"], fg_color=t["btn_secondary_fg"]).pack(side="right", padx=15, pady=6)

        # Estadísticas resumidas (Strip horizontal compacto)
        producto_top = productos_data[0]
        total_productos_vendidos = sum(p[1] for p in productos_data)
        total_ingresos_productos = sum(p[2] for p in productos_data)

        stats_frame = tk.Frame(ventana_productos, bg=t["bg_card"], relief="solid", bd=1)
        stats_frame.pack(fill="x", side="bottom", padx=15, pady=(0, 8))

        stats_strip = tk.Frame(stats_frame, bg=t["bg_card"])
        stats_strip.pack(fill="x", padx=10, pady=6)
        stats_strip.columnconfigure((0, 1, 2), weight=1)

        metricas_top = [
            ("🥇 Producto #1", f"{producto_top[0]} ({producto_top[1]:.0f} uds)", t["accent"]),
            ("📦 Total Productos Vendidos", f"{total_productos_vendidos:.0f} unidades", "#10B981"),
            ("💰 Total Ingresos Top", formato_peso(total_ingresos_productos), "#3B82F6")
        ]

        for idx, (lbl, val, col) in enumerate(metricas_top):
            c = tk.Frame(stats_strip, bg=t["bg_surface"], relief="solid", bd=1, padx=8, pady=4)
            c.grid(row=0, column=idx, padx=4, sticky="nsew")
            tk.Label(c, text=lbl, font=("Segoe UI", 8, "bold"), bg=t["bg_surface"], fg=t["text_secondary"]).pack(anchor="w")
            tk.Label(c, text=val, font=("Segoe UI", 10, "bold"), bg=t["bg_surface"], fg=col).pack(anchor="w")

        # Contenedor de la tabla con scrollbars duales
        table_container = tk.Frame(ventana_productos, bg=t["bg_surface"], relief="solid", bd=1)
        table_container.pack(fill="both", expand=True, padx=15, pady=10)
        table_container.rowconfigure(0, weight=1)
        table_container.columnconfigure(0, weight=1)

        columnas = ("Ranking", "Producto", "Cant. Vendida", "Ingresos", "Núm. Ventas")
        tabla_productos = ttk.Treeview(table_container, columns=columnas, show="headings")
        tabla_productos.grid(row=0, column=0, sticky="nsew")

        v_scroll = ttk.Scrollbar(table_container, orient="vertical", command=tabla_productos.yview)
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll = ttk.Scrollbar(table_container, orient="horizontal", command=tabla_productos.xview)
        h_scroll.grid(row=1, column=0, sticky="ew")
        tabla_productos.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        widths = [80, 300, 120, 120, 100]
        for i, col in enumerate(columnas):
            tabla_productos.heading(col, text=col)
            tabla_productos.column(col, width=widths[i], anchor="center")

        for i, (producto, cantidad, ingresos, num_ventas) in enumerate(productos_data, 1):
            emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}°"
            tabla_productos.insert("", tk.END, values=(
                emoji, producto, f"{cantidad:.0f}", formato_peso(ingresos), num_ventas
            ))

    except Exception as e:
        messagebox.showerror("❌ Error", f"Error al obtener productos más vendidos: {str(e)}")

# 🖼️ User interface functions
def crear_cuadro(padre, texto, color, tipo, icon, ventana):
    """Creates an interactive box for the reports."""
    t = theme_mgr.get_theme_tokens()
    frame = tk.Frame(padre, width=280, height=110, bg=t["bg_surface"], bd=1, relief="solid", highlightbackground=t["border"], highlightthickness=1)

    card_header = tk.Frame(frame, bg=color, height=6)
    card_header.pack(fill="x")

    card_content = tk.Frame(frame, bg=t["bg_surface"])
    card_content.pack(fill="both", expand=True, padx=12, pady=8)

    tk.Label(card_content, text=icon, font=("Segoe UI Emoji", 26), bg=t["bg_surface"], fg=color).pack(pady=2)
    tk.Label(card_content, text=texto, font=("Segoe UI", 11, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).pack()

    def on_enter(e):
        frame.config(relief="raised", bd=2)
    def on_leave(e):
        frame.config(relief="solid", bd=1)
    def on_press(e):
        frame.config(relief="sunken", bd=2)
    def on_release(e):
        if frame.winfo_containing(e.x_root, e.y_root) == frame:
            frame.config(relief="raised", bd=2)
        else:
            frame.config(relief="solid", bd=1)
        abrir_reporte(tipo, ventana)

    frame.bind("<Enter>", on_enter)
    frame.bind("<Leave>", on_leave)
    frame.bind("<ButtonPress-1>", on_press)
    frame.bind("<ButtonRelease-1>", on_release)
    
    for child in frame.winfo_children():
        if isinstance(child, tk.Frame):
            child.bind("<Enter>", on_enter)
            child.bind("<Leave>", on_leave)
            child.bind("<ButtonPress-1>", on_press)
            child.bind("<ButtonRelease-1>", on_release)
            for widget in child.winfo_children():
                widget.bind("<Enter>", on_enter)
                widget.bind("<Leave>", on_leave)
                widget.bind("<ButtonPress-1>", on_press)
                widget.bind("<ButtonRelease-1>", on_release)

    return frame

def iniciar_reportes():
    """Redirige al nuevo y completo módulo de Contabilidad e Inteligencia Financiera."""
    try:
        from interface.contabilidad_menu import iniciar_contabilidad
        iniciar_contabilidad()
        return
    except Exception as e:
        print(f"[AVISO] Error cargando contabilidad_menu: {e}")

    global conn, cursor
    if not conectar_db():
        return
        
    ventana = tk.Tk()
    ventana.title(f"📊 Reportes Financieros - {business_mgr.nombre}")
    
    t = aplicar_tema(ventana)
    calcular_geometria_segura(ventana, 1120, 730, min_w=880, min_h=540)
    ventana.configure(bg=t["bg_app"])
    
    COLOR_PRIMARIO = t["accent"]
    
    # Header compacto elegante con reloj
    header_frame = tk.Frame(ventana, bg=COLOR_PRIMARIO, height=52)
    header_frame.pack(fill="x")
    header_frame.pack_propagate(False)

    header_left = tk.Frame(header_frame, bg=COLOR_PRIMARIO)
    header_left.pack(side="left", fill="y", padx=20)

    tk.Label(header_left, text="📊", font=("Segoe UI Emoji", 20),
            bg=COLOR_PRIMARIO, fg="white").pack(side="left", pady=10)
    tk.Label(header_left, text="REPORTES", font=("Segoe UI", 16, "bold"),
            bg=COLOR_PRIMARIO, fg="white").pack(side="left", padx=(8, 0), pady=12)
    tk.Label(header_left, text="• Análisis Financiero Completo", font=("Segoe UI", 10),
            bg=COLOR_PRIMARIO, fg="#FCE7F3").pack(side="left", padx=(10, 0), pady=14)

    # Reloj y selector rápido de tema a la derecha
    header_right = tk.Frame(header_frame, bg=COLOR_PRIMARIO)
    header_right.pack(side="right", fill="y", padx=15)

    def toggle_theme():
        nuevo = "claro" if theme_mgr.es_oscuro() else "oscuro"
        theme_mgr.cambiar_tema(nuevo)
        messagebox.showinfo("Tema", f"Tema cambiado a {nuevo.upper()}. Reinicie el módulo para ver todos los cambios reflejados.")

    btn_tema = tk.Button(header_right, text="🌙/☀️", command=toggle_theme,
                         font=("Segoe UI", 9, "bold"), bg=COLOR_PRIMARIO, fg="white",
                         relief="flat", cursor="hand2", padx=6, pady=2)
    btn_tema.pack(side="right", padx=(10, 0), pady=12)

    # Reloj en tiempo real
    reloj_label = tk.Label(header_right, font=("Segoe UI", 10, "bold"), bg=COLOR_PRIMARIO, fg="white")
    reloj_label.pack(side="right", pady=14)

    def actualizar_reloj():
        if ventana.winfo_exists():
            ahora = datetime.now().strftime("%d/%m/%Y  %H:%M:%S")
            reloj_label.config(text=f"🕒 {ahora}")
            ventana.after(1000, actualizar_reloj)

    actualizar_reloj()

    # 📊 Footer fijo
    footer = tk.Frame(ventana, bg=COLOR_PRIMARIO, height=32)
    footer.pack(fill="x", side="bottom")
    footer.pack_propagate(False)

    tk.Label(footer, text=business_mgr.obtener_texto_ubicacion_contacto(),
            font=("Segoe UI", 9), bg=COLOR_PRIMARIO, fg="white").pack(side="left", padx=15)

    tk.Label(footer, text=f"✨ {business_mgr.nombre} • Módulo de Inteligencia Financiera ✨",
            font=("Segoe UI", 9), bg=COLOR_PRIMARIO, fg="#FCE7F3").pack(side="right", padx=15)

    # 📊 Main content
    main_content = tk.Frame(ventana, bg=t["bg_app"])
    main_content.pack(fill="both", expand=True, padx=20, pady=10)

    top_actions = tk.Frame(main_content, bg=t["bg_app"])
    top_actions.pack(fill="x", pady=(0, 10))

    tk.Label(top_actions, text="✨ MÓDULO DE INTELIGENCIA Y REPORTES", font=("Segoe UI", 13, "bold"),
            bg=t["bg_app"], fg=COLOR_PRIMARIO).pack(side="left")

    btn_cierre = crear_boton(top_actions, "📊 Generar Cierre Mensual en Excel",
                             lambda: generar_excel_mensual(modal_padre=ventana),
                             bg_color=t["btn_success_bg"], fg_color=t["btn_success_fg"])
    btn_cierre.pack(side="right")

    panel = tk.Frame(main_content, bg=t["bg_app"])
    panel.pack(expand=True)

    # 📦 Report configuration in a 2x3 grid with icons
    opciones = [
        ("Reportes Diarios", "#EC4899", "diario", "☀️"),
        ("Reportes Semanales", "#3B82F6", "semanal", "🗓️"),
        ("Reportes Mensuales", "#8B5CF6", "mensual", "🌙"),
        ("Análisis de Ventas", "#10B981", "graf_ganancia", "💰"),
        ("Gráfico de Ventas", "#EF4444", "graf_ventas", "📈"),
        ("Productos Top", "#F59E0B", "graf_categoria", "⭐"),
    ]

    for i in range(2):
        fila = tk.Frame(panel, bg=t["bg_app"])
        fila.pack(pady=8)
        for j in range(3):
            index = i * 3 + j
            if index < len(opciones):
                texto, color, tipo, icon = opciones[index]
                cuadro = crear_cuadro(fila, texto, color, tipo, icon, ventana)
                cuadro.pack(side="left", padx=12)

    ventana.mainloop()

if __name__ == "__main__":
    iniciar_reportes()