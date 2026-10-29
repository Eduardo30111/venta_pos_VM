"""
Módulo de Contabilidad y Finanzas - VmPOS (Rediseño UX/UI Profesional)

Diseño limpio, intuitivo y moderno:
1. Navegación clara con 3 secciones:
   - 📊 Resumen Financiero (Pantalla principal intuitiva)
   - 📑 Registros e Informes (Detalle contable y exportaciones)
   - 🔒 Cierre de Caja (Arqueo físico y conciliación bancaria)
2. Resumen Financiero simplificado para personas sin conocimientos contables:
   - 4 Tarjetas principales: Ventas Netas, Costo de Ventas, Gastos, Ganancia Neta.
   - Indicador secundario de Cartera (Fiados pendientes).
   - Bloque "¿Cómo se movió el dinero?": Efectivo vs Transferencias vs Fiados.
   - Tabla compacta de Estado de Resultados.
   - 2 Gráficas principales sin superposición: Evolución diaria de ventas y Medios de pago.
   - Subsección "Análisis del negocio" con recomendaciones sustentadas.
3. Registros e Informes con exportación profesional a Excel (9 pestañas) y PDF/HTML.
4. Cierre de caja en 2 bloques independientes: Efectivo físico y Conciliación bancaria.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, timedelta
import os
import sys
import sqlite3
import webbrowser

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
        conectar_db,
        obtener_sesion_activa,
        calcular_arqueo_sesion,
        cerrar_sesion_caja,
        calcular_metricas_contables,
        generar_alertas_recomendaciones,
        procesar_gastos_recurrentes
    )
except ImportError:
    from interface.caja_manager import (
        conectar_db,
        obtener_sesion_activa,
        calcular_arqueo_sesion,
        cerrar_sesion_caja,
        calcular_metricas_contables,
        generar_alertas_recomendaciones,
        procesar_gastos_recurrentes
    )


# ==============================================================================
# EXPORTADORES FINANCIEROS (EXCEL 9 PESTAÑAS + PDF/HTML)
# ==============================================================================

def exportar_excel_financiero(metricas: dict, ruta_destino: str) -> bool:
    """
    Exporta informe contable con 9 hojas de trabajo.
    Usa OpenPyXL si está disponible; de lo contrario genera XML Spreadsheet 2003 nativo.
    """
    try:
        from openpyxl import Workbook
        wb = Workbook()
        wb.remove(wb.active)
        
        # 1. Resumen Ejecutivo
        ws1 = wb.create_sheet("1. Resumen Ejecutivo")
        ws1.append([business_mgr.nombre.upper(), "INFORME CONTABLE EJECUTIVO"])
        ws1.append(["Periodo:", f"{metricas['periodo']['inicio']} al {metricas['periodo']['fin']}"])
        ws1.append([])
        ws1.append(["Indicador KPI", "Valor (COP)", "Lectura"])
        kpis = metricas["kpis"]
        ws1.append(["1. Ventas Netas Facturadas", kpis["A_ventas_netas"], "Ingreso por ventas activas"])
        ws1.append(["2. Costo de Mercancía Vendida (COGS)", kpis["B_costo_ventas"], "Costo de compra histórico"])
        ws1.append(["3. Utilidad Bruta Comercial", kpis["C_utilidad_bruta"], "Ventas Netas - Costo de Ventas"])
        ws1.append(["4. Gastos Operativos Totales", kpis["D_gastos_operativos"], "Desglose en 4 categorías"])
        ws1.append(["5. Utilidad Operacional Neta", kpis["E_utilidad_operacional_neta"], "Ganancia líquida del negocio"])
        ws1.append(["6. Margen Neto Operativo (%)", f"{kpis['F_margen_neto_pct']:.2f}%", "Rentabilidad sobre ingresos"])
        ws1.append(["7. Efectivo Físico en Caja", kpis["G_efectivo_en_caja"], "Saldo esperado en gaveta"])
        ws1.append(["8. Cuentas por Cobrar (Cartera)", kpis["H_cuentas_por_cobrar"], "Deuda de clientes fiadores"])
        ws1.append(["9. Bancos / Transferencias", kpis["I_dinero_en_bancos"], "Recaudos digitales conciliados"])

        # 2. Conceptos Contables (22)
        ws2 = wb.create_sheet("2. Conceptos Contables")
        ws2.append(["N°", "Código", "Concepto Contable", "Monto (COP)", "Tipo", "Explicación Técnica"])
        for c in metricas.get("conceptos_22", []):
            ws2.append([c["numero"], c["codigo"], c["concepto"], c["valor"], c["tipo"], c["descripcion"]])

        # 3. Ventas por Medio
        ws3 = wb.create_sheet("3. Ventas por Medio")
        ws3.append(["Medio de Pago", "Total Facturado (COP)", "Participación (%)"])
        rv = metricas["resumen_ventas"]
        ws3.append(["Efectivo", rv["efectivo"], f"{rv['pct_efectivo']:.2f}%"])
        ws3.append(["Transferencias Bancarias", rv["transferencia"], f"{rv['pct_transferencia']:.2f}%"])
        ws3.append(["Ventas a Crédito (Fiado)", rv["fiado"], f"{rv['pct_fiado']:.2f}%"])

        # 4. Gastos por Categoría
        ws4 = wb.create_sheet("4. Gastos por Categoría")
        ws4.append(["Categoría Contable", "Total Gastos (COP)"])
        for cat, val in metricas["gastos"]["por_categoria"].items():
            ws4.append([cat, val])
        ws4.append(["Total Gastos Pagados", metricas["gastos"]["pagados"]])
        ws4.append(["Total Gastos Pendientes", metricas["gastos"]["pendientes"]])

        # 5. Rendimiento Operarios
        ws5 = wb.create_sheet("5. Rendimiento Operarios")
        ws5.append(["Operario", "Total Vendido", "Cant. Ventas", "Efectivo", "Transferencia", "Fiado"])
        for op in metricas.get("operarios", []):
            ws5.append([op["operario"], op["total_vendido"], op["cant_ventas"], op["efectivo"], op["transferencia"], op["fiado"]])

        # 6. Top Productos
        ws6 = wb.create_sheet("6. Top Productos")
        ws6.append(["Código", "Producto", "Unidades", "Total Facturado", "Costo Total", "Ganancia", "Margen %"])
        for p in metricas.get("top_productos", []):
            ws6.append([p["codigo"], p["nombre"], p["unidades"], p["facturado"], p["costo"], p["ganancia"], f"{p['margen_pct']:.2f}%"])

        # 7. Cartera Clientes
        ws7 = wb.create_sheet("7. Cartera y Fiados")
        ws7.append(["Documento / Cédula", "Nombre Cliente", "Teléfono", "Saldo Pendiente (COP)"])
        for cl in metricas.get("top_deudores", []):
            ws7.append([cl.get("cedula", ""), cl.get("nombre", ""), cl.get("telefono", ""), cl.get("saldo_pendiente", 0.0)])

        # 8. Flujo Caja
        ws8 = wb.create_sheet("8. Flujo de Caja")
        ws8.append(["Concepto Flujo", "Monto (COP)"])
        cf = metricas["caja_fisica"]
        ws8.append(["Base Inicial Apertura", cf["base_inicial"]])
        ws8.append(["Ingresos Ventas Efectivo", cf["ingresos_ventas"]])
        ws8.append(["Abonos Cartera Efectivo", cf["abonos_cartera"]])
        ws8.append(["Egresos Gastos Pagados", cf["egresos_gastos"]])
        ws8.append(["Retiros de Dinero", cf["retiros"]])
        ws8.append(["Devoluciones de Ventas", cf["devoluciones"]])
        ws8.append(["Ajustes de Auditoría", cf["ajustes"]])
        ws8.append(["Efectivo Físico Esperado", cf["efectivo_esperado"]])
        ws8.append(["Diferencia Acumulada Cierres", cf["diferencia_acumulada"]])

        # 9. Conciliación Bancaria
        ws9 = wb.create_sheet("9. Conciliación Bancaria")
        ws9.append(["Rubro Bancario", "Monto (COP)"])
        bc = metricas["bancos"]
        ws9.append(["Transferencias Registradas en Ventas", bc["ventas_transferencia"]])
        ws9.append(["Transferencias Verificadas en Cierres", bc["verificado_sesiones"]])
        ws9.append(["Saldo Conciliado / Estimado", bc["saldo_estimado"]])

        wb.save(ruta_destino)
        return True
    except Exception as e:
        print(f"[AVISO] Fallback a XML Spreadsheet 2003: {e}")
        return exportar_xml_spreadsheet_2003(metricas, ruta_destino)


def exportar_xml_spreadsheet_2003(metricas: dict, ruta_destino: str) -> bool:
    """Genera XML Spreadsheet 2003 compatible nativamente con Excel sin librerías externas."""
    try:
        kpis = metricas["kpis"]
        rv = metricas["resumen_ventas"]
        cf = metricas["caja_fisica"]
        bc = metricas["bancos"]

        xml = ['<?xml version="1.0" encoding="UTF-8"?>']
        xml.append('<?mso-application progid="Excel.Sheet"?>')
        xml.append('<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"')
        xml.append(' xmlns:o="urn:schemas-microsoft-com:office:office"')
        xml.append(' xmlns:x="urn:schemas-microsoft-com:office:excel"')
        xml.append(' xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">')

        xml.append('<Styles>')
        xml.append(' <Style ss:ID="Header"><Font ss:Bold="1" ss:Color="#FFFFFF"/><Interior ss:Color="#1B5E20" ss:Pattern="Solid"/></Style>')
        xml.append(' <Style ss:ID="SubHeader"><Font ss:Bold="1" ss:Color="#FFFFFF"/><Interior ss:Color="#334155" ss:Pattern="Solid"/></Style>')
        xml.append(' <Style ss:ID="Bold"><Font ss:Bold="1"/></Style>')
        xml.append(' <Style ss:ID="Currency"><NumberFormat ss:Format="&quot;$&quot;#,##0"/></Style>')
        xml.append('</Styles>')

        # Hoja 1: Resumen Ejecutivo
        xml.append('<Worksheet ss:Name="1_Resumen_Ejecutivo"><Table>')
        xml.append(f'<Row><Cell ss:StyleID="Header"><Data ss:Type="String">{business_mgr.nombre.upper()} - INFORME CONTABLE EJECUTIVO</Data></Cell></Row>')
        xml.append(f'<Row><Cell ss:StyleID="Bold"><Data ss:Type="String">Periodo: {metricas["periodo"]["inicio"]} al {metricas["periodo"]["fin"]}</Data></Cell></Row>')
        xml.append('<Row/>')
        xml.append('<Row><Cell ss:StyleID="SubHeader"><Data ss:Type="String">Indicador KPI</Data></Cell><Cell ss:StyleID="SubHeader"><Data ss:Type="String">Valor (COP)</Data></Cell><Cell ss:StyleID="SubHeader"><Data ss:Type="String">Concepto</Data></Cell></Row>')
        kpi_list = [
            ("1. Ventas Netas Facturadas", kpis["A_ventas_netas"], "Ingreso neto por ventas activas"),
            ("2. Costo de Mercancía (COGS)", kpis["B_costo_ventas"], "Costo histórico de adquisición"),
            ("3. Utilidad Bruta Comercial", kpis["C_utilidad_bruta"], "Ventas Netas - Costo de Ventas"),
            ("4. Gastos Operativos Totales", kpis["D_gastos_operativos"], "Desglose 4 categorías"),
            ("5. Utilidad Operacional Neta", kpis["E_utilidad_operacional_neta"], "Ganancia líquida operativa"),
            ("6. Margen Neto Operativo (%)", f"{kpis['F_margen_neto_pct']:.2f}%", "Rentabilidad sobre ventas"),
            ("7. Efectivo Físico en Caja", kpis["G_efectivo_en_caja"], "Saldo esperado en gaveta"),
            ("8. Cuentas por Cobrar (Cartera)", kpis["H_cuentas_por_cobrar"], "Deuda viva de clientes"),
            ("9. Bancos / Transferencias", kpis["I_dinero_en_bancos"], "Ingresos recaudados digitalmente")
        ]
        for nom, val, desc in kpi_list:
            if isinstance(val, (int, float)):
                xml.append(f'<Row><Cell><Data ss:Type="String">{nom}</Data></Cell><Cell ss:StyleID="Currency"><Data ss:Type="Number">{val}</Data></Cell><Cell><Data ss:Type="String">{desc}</Data></Cell></Row>')
            else:
                xml.append(f'<Row><Cell><Data ss:Type="String">{nom}</Data></Cell><Cell><Data ss:Type="String">{val}</Data></Cell><Cell><Data ss:Type="String">{desc}</Data></Cell></Row>')
        xml.append('</Table></Worksheet>')

        # Hoja 2: Conceptos Contables (22)
        xml.append('<Worksheet ss:Name="2_Conceptos_Contables"><Table>')
        xml.append('<Row><Cell ss:StyleID="SubHeader"><Data ss:Type="String">N°</Data></Cell><Cell ss:StyleID="SubHeader"><Data ss:Type="String">Código</Data></Cell><Cell ss:StyleID="SubHeader"><Data ss:Type="String">Concepto</Data></Cell><Cell ss:StyleID="SubHeader"><Data ss:Type="String">Monto</Data></Cell><Cell ss:StyleID="SubHeader"><Data ss:Type="String">Tipo</Data></Cell><Cell ss:StyleID="SubHeader"><Data ss:Type="String">Explicación</Data></Cell></Row>')
        for c in metricas.get("conceptos_22", []):
            xml.append(f'<Row><Cell><Data ss:Type="Number">{c["numero"]}</Data></Cell><Cell><Data ss:Type="String">{c["codigo"]}</Data></Cell><Cell><Data ss:Type="String">{c["concepto"]}</Data></Cell><Cell ss:StyleID="Currency"><Data ss:Type="Number">{c["valor"]}</Data></Cell><Cell><Data ss:Type="String">{c["tipo"]}</Data></Cell><Cell><Data ss:Type="String">{c["descripcion"]}</Data></Cell></Row>')
        xml.append('</Table></Worksheet>')

        # Hoja 3: Medios de Pago
        xml.append('<Worksheet ss:Name="3_Medios_Pago"><Table>')
        xml.append('<Row><Cell ss:StyleID="SubHeader"><Data ss:Type="String">Medio</Data></Cell><Cell ss:StyleID="SubHeader"><Data ss:Type="String">Total (COP)</Data></Cell><Cell ss:StyleID="SubHeader"><Data ss:Type="String">Participación</Data></Cell></Row>')
        xml.append(f'<Row><Cell><Data ss:Type="String">Efectivo</Data></Cell><Cell ss:StyleID="Currency"><Data ss:Type="Number">{rv["efectivo"]}</Data></Cell><Cell><Data ss:Type="String">{rv["pct_efectivo"]:.2f}%</Data></Cell></Row>')
        xml.append(f'<Row><Cell><Data ss:Type="String">Transferencia</Data></Cell><Cell ss:StyleID="Currency"><Data ss:Type="Number">{rv["transferencia"]}</Data></Cell><Cell><Data ss:Type="String">{rv["pct_transferencia"]:.2f}%</Data></Cell></Row>')
        xml.append(f'<Row><Cell><Data ss:Type="String">Fiado (Crédito)</Data></Cell><Cell ss:StyleID="Currency"><Data ss:Type="Number">{rv["fiado"]}</Data></Cell><Cell><Data ss:Type="String">{rv["pct_fiado"]:.2f}%</Data></Cell></Row>')
        xml.append('</Table></Worksheet>')

        xml.append('</Workbook>')
        with open(ruta_destino, "w", encoding="utf-8") as f:
            f.write("\n".join(xml))
        return True
    except Exception as e:
        print(f"[ERROR] exportar_xml_spreadsheet_2003: {e}")
        return False


def exportar_informe_html_pdf(metricas: dict, ruta_destino: str) -> bool:
    """Genera informe contable imprimible con diseño corporativo limpio."""
    try:
        kpis = metricas["kpis"]
        conceptos = metricas.get("conceptos_22", [])
        operarios = metricas.get("operarios", [])
        top_prod = metricas.get("top_productos", [])

        html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Informe Financiero - {business_mgr.nombre}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 30px; color: #0F172A; background: #F8FAFC; }}
  .header {{ background: #0F172A; color: white; padding: 24px; border-radius: 8px; margin-bottom: 24px; }}
  .header h1 {{ margin: 0 0 6px 0; font-size: 22px; }}
  .header p {{ margin: 0; font-size: 13px; opacity: 0.85; }}
  .grid-4 {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 24px; }}
  .card {{ background: white; border: 1px solid #E2E8F0; border-radius: 8px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
  .card-title {{ font-size: 11px; font-weight: 700; color: #64748B; text-transform: uppercase; margin-bottom: 6px; }}
  .card-value {{ font-size: 22px; font-weight: 800; color: #0F172A; }}
  .card-desc {{ font-size: 11px; color: #94A3B8; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; background: white; margin-bottom: 24px; border-radius: 8px; overflow: hidden; border: 1px solid #E2E8F0; }}
  th {{ background: #F1F5F9; color: #334155; text-align: left; padding: 10px 14px; font-size: 12px; font-weight: 700; border-bottom: 1px solid #CBD5E1; }}
  td {{ padding: 10px 14px; border-bottom: 1px solid #F1F5F9; font-size: 12px; }}
  tr:nth-child(even) {{ background: #FAFAFA; }}
  .right {{ text-align: right; }}
  .section-h {{ font-size: 15px; font-weight: 700; color: #0F172A; margin: 24px 0 10px 0; }}
  @media print {{ body {{ background: white; margin: 0; }} .no-print {{ display: none; }} }}
</style>
</head>
<body>
  <div class="header">
    <h1>🏛️ {business_mgr.nombre.upper()} - INFORME FINANCIERO OFICIAL</h1>
    <p>Período Evaluado: <strong>{metricas['periodo']['inicio']}</strong> al <strong>{metricas['periodo']['fin']}</strong> | Generado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p>
  </div>

  <div class="grid-4">
    <div class="card" style="border-top: 4px solid #059669;">
      <div class="card-title">1. Ventas Netas</div>
      <div class="card-value" style="color: #059669;">${kpis['A_ventas_netas']:,.0f}</div>
      <div class="card-desc">Total ventas activas</div>
    </div>
    <div class="card" style="border-top: 4px solid #DC2626;">
      <div class="card-title">2. Costo de Ventas</div>
      <div class="card-value" style="color: #DC2626;">${kpis['B_costo_ventas']:,.0f}</div>
      <div class="card-desc">Costo real de compra</div>
    </div>
    <div class="card" style="border-top: 4px solid #D97706;">
      <div class="card-title">3. Gastos del Período</div>
      <div class="card-value" style="color: #D97706;">${kpis['D_gastos_operativos']:,.0f}</div>
      <div class="card-desc">Salidas operativas y fijas</div>
    </div>
    <div class="card" style="border-top: 4px solid #2563EB;">
      <div class="card-title">4. Ganancia Neta</div>
      <div class="card-value" style="color: #2563EB;">${kpis['E_utilidad_operacional_neta']:,.0f}</div>
      <div class="card-desc">Margen neto: {kpis['F_margen_neto_pct']:.1f}%</div>
    </div>
  </div>

  <div class="section-h">📑 22 CONCEPTOS CONTABLES OFICIALES</div>
  <table>
    <tr><th>N°</th><th>Código</th><th>Concepto</th><th class="right">Valor (COP)</th><th>Tipo</th><th>Explicación</th></tr>
"""
        for c in conceptos:
            val_fmt = f"${c['valor']:,.0f}" if isinstance(c['valor'], (int, float)) and c['tipo'] != 'Porcentaje' else (f"{c['valor']:.1f}%" if c['tipo'] == 'Porcentaje' else str(c['valor']))
            html += f"<tr><td>{c['numero']}</td><td><strong>{c['codigo']}</strong></td><td>{c['concepto']}</td><td class='right'><strong>{val_fmt}</strong></td><td>{c['tipo']}</td><td>{c['descripcion']}</td></tr>\n"

        html += f"""
  </table>

  <div class="section-h">👨‍💼 RENDIMIENTO POR OPERARIO</div>
  <table>
    <tr><th>Operario</th><th class="right">Total Facturado</th><th class="right">Cant. Ventas</th><th class="right">Efectivo</th><th class="right">Transferencia</th><th class="right">Fiado</th></tr>
"""
        for op in operarios:
            html += f"<tr><td><strong>{op['operario']}</strong></td><td class='right'>${op['total_vendido']:,.0f}</td><td class='right'>{op['cant_ventas']}</td><td class='right'>${op['efectivo']:,.0f}</td><td class='right'>${op['transferencia']:,.0f}</td><td class='right'>${op['fiado']:,.0f}</td></tr>\n"

        html += f"""
  </table>

  <div class="section-h">⭐ TOP PRODUCTOS MÁS VENDIDOS</div>
  <table>
    <tr><th>Código</th><th>Producto</th><th class="right">Unidades</th><th class="right">Total Facturado</th><th class="right">Costo</th><th class="right">Ganancia</th><th class="right">Margen</th></tr>
"""
        for p in top_prod[:10]:
            html += f"<tr><td>{p['codigo']}</td><td>{p['nombre']}</td><td class='right'>{p['unidades']}</td><td class='right'>${p['facturado']:,.0f}</td><td class='right'>${p['costo']:,.0f}</td><td class='right'>${p['ganancia']:,.0f}</td><td class='right'>{p['margen_pct']:.1f}%</td></tr>\n"

        html += f"""
  </table>
</body>
</html>
"""
        with open(ruta_destino, "w", encoding="utf-8") as f:
            f.write(html)
        return True
    except Exception as e:
        print(f"[ERROR] exportar_informe_html_pdf: {e}")
        return False


# ==============================================================================
# CLASE PRINCIPAL: CONTABILIDADAPP (REDISEÑO UX/UI PROFESIONAL)
# ==============================================================================

class ContabilidadApp:
    def __init__(self, root, parent_pid=""):
        self.root = root
        self.parent_pid = parent_pid or os.environ.get("VMPOS_PARENT_PID", "")
        session_mgr.iniciar_vigilante_padre(self.root, parent_pid=self.parent_pid)
        iniciar_observador_tema(self.root)

        self.root.title(f"Contabilidad y Finanzas - {business_mgr.nombre}")
        self.t = aplicar_tema(self.root)
        calcular_geometria_segura(self.root, 1200, 760, min_w=980, min_h=600)
        self.root.configure(bg="#F1F5F9")  # Fondo neutro profesional suave

        # Paleta de colores visual de alto contraste
        self.c_bg = "#F8FAFC"
        self.c_card = "#FFFFFF"
        self.c_border = "#E2E8F0"
        self.c_text = "#0F172A"
        self.c_text_muted = "#64748B"
        self.c_primary = "#0F172A"       # Azul pizarra oscuro
        self.c_accent = "#2563EB"        # Azul profesional
        self.c_green = "#059669"         # Verde éxito
        self.c_red = "#DC2626"           # Rojo costos/faltantes
        self.c_amber = "#D97706"         # Ámbar advertencias/gastos
        self.c_indigo = "#4F46E5"

        # Fechas
        self.hoy = datetime.now()
        self.fecha_ini = self.hoy.strftime("%Y-%m-01")
        self.fecha_fin = self.hoy.strftime("%Y-%m-%d")
        self.metricas_actuales = {}

        self._crear_header_moderno()
        self._crear_barra_navegacion()

        # Contenedor principal de pantallas
        self.container = tk.Frame(self.root, bg=self.c_bg)
        self.container.pack(fill="both", expand=True, padx=16, pady=(4, 12))

        # 3 Pantallas Principales
        self.vista_resumen = tk.Frame(self.container, bg=self.c_bg)
        self.vista_registros = tk.Frame(self.container, bg=self.c_bg)
        self.vista_cierre = tk.Frame(self.container, bg=self.c_bg)

        # Construir cada una
        self._construir_resumen_financiero()
        self._construir_registros_e_informes()
        self._construir_cierre_de_caja()

        # Abrir pantalla inicial
        self.cambiar_vista("resumen")
        self.actualizar_todo()

    # --------------------------------------------------------------------------
    # 1. HEADER Y BARRA DE NAVEGACIÓN
    # --------------------------------------------------------------------------
    def _crear_header_moderno(self):
        header = tk.Frame(self.root, bg=self.c_primary, height=48)
        header.pack(fill="x")
        header.pack_propagate(False)

        h_left = tk.Frame(header, bg=self.c_primary)
        h_left.pack(side="left", padx=16)
        tk.Label(h_left, text="🏛️", font=("Segoe UI Emoji", 16), bg=self.c_primary, fg="white").pack(side="left", padx=(0, 8))
        tk.Label(h_left, text="CONTABILIDAD Y FINANZAS", font=("Segoe UI", 12, "bold"), bg=self.c_primary, fg="white").pack(side="left")
        tk.Label(h_left, text=f"• {business_mgr.nombre}", font=("Segoe UI", 10), bg=self.c_primary, fg="#94A3B8").pack(side="left", padx=(8, 0))

        h_right = tk.Frame(header, bg=self.c_primary)
        h_right.pack(side="right", padx=16)
        self.lbl_reloj = tk.Label(h_right, text="", font=("Segoe UI", 9, "bold"), bg=self.c_primary, fg="#CBD5E1")
        self.lbl_reloj.pack(side="right")
        self._tick_reloj()

    def _tick_reloj(self):
        try:
            if self.root.winfo_exists():
                self.lbl_reloj.config(text=f"🕒 {datetime.now().strftime('%d/%m/%Y  %H:%M:%S')}")
                tid = self.root.after(1000, self._tick_reloj)
                session_mgr.registrar_timer(self.root, tid)
        except Exception:
            pass

    def _crear_barra_navegacion(self):
        nav_card = tk.Frame(self.root, bg=self.c_card, relief="flat", bd=0, highlightbackground=self.c_border, highlightthickness=1)
        nav_card.pack(fill="x", padx=16, pady=(8, 4))
        inner = tk.Frame(nav_card, bg=self.c_card, padx=12, pady=6)
        inner.pack(fill="x")

        # 3 PESTAÑAS PRINCIPALES
        self.nav_btns = {}
        tabs = [
            ("resumen", "📊 Resumen Financiero"),
            ("registros", "📑 Registros e Informes"),
            ("cierre", "🔒 Cierre de Caja")
        ]

        f_tabs = tk.Frame(inner, bg=self.c_card)
        f_tabs.pack(side="left")

        for key, text in tabs:
            btn = tk.Button(
                f_tabs, text=text, font=("Segoe UI", 9, "bold"),
                relief="flat", cursor="hand2", padx=14, pady=6,
                command=lambda k=key: self.cambiar_vista(k)
            )
            btn.pack(side="left", padx=(0, 6))
            self.nav_btns[key] = btn

        # FILTRO DE PERÍODO Y BOTÓN ACTUALIZAR (DERECHA)
        f_filtro = tk.Frame(inner, bg=self.c_card)
        f_filtro.pack(side="right")

        tk.Label(f_filtro, text="📅 Período:", font=("Segoe UI", 9, "bold"), bg=self.c_card, fg=self.c_text).pack(side="left", padx=(0, 4))
        self.combo_periodo = ttk.Combobox(f_filtro, values=["Hoy", "Ayer", "Esta semana", "Este mes", "Mes anterior", "Personalizado"], state="readonly", width=12)
        self.combo_periodo.set("Este mes")
        self.combo_periodo.pack(side="left", padx=(0, 6))
        self.combo_periodo.bind("<<ComboboxSelected>>", self._on_cambio_periodo)

        self.lbl_rango_fechas = tk.Label(f_filtro, text=f"({self.fecha_ini} al {self.fecha_fin})", font=("Segoe UI", 9), bg=self.c_card, fg=self.c_text_muted)
        self.lbl_rango_fechas.pack(side="left", padx=(0, 10))

        # Botón Actualizar de alto contraste
        self.btn_actualizar = tk.Button(
            f_filtro, text="🔄 Actualizar", font=("Segoe UI", 9, "bold"),
            bg="#0F172A", fg="white", activebackground="#334155", activeforeground="white",
            relief="flat", cursor="hand2", padx=12, pady=5,
            command=self._animar_actualizar
        )
        self.btn_actualizar.pack(side="left")

    def cambiar_vista(self, nombre):
        self.vista_resumen.pack_forget()
        self.vista_registros.pack_forget()
        self.vista_cierre.pack_forget()

        # Estilo de botones de navegación
        for k, b in self.nav_btns.items():
            if k == nombre:
                b.config(bg=self.c_primary, fg="white", activebackground=self.c_primary, activeforeground="white")
            else:
                b.config(bg="#F1F5F9", fg=self.c_text, activebackground="#E2E8F0", activeforeground=self.c_text)

        if nombre == "resumen":
            self.vista_resumen.pack(fill="both", expand=True)
        elif nombre == "registros":
            self.vista_registros.pack(fill="both", expand=True)
        elif nombre == "cierre":
            self.vista_cierre.pack(fill="both", expand=True)
            self._cargar_datos_cierre()

    def _animar_actualizar(self):
        self.btn_actualizar.config(text="⏳ Actualizando...", state="disabled")
        self.root.update_idletasks()
        try:
            self.actualizar_todo()
        finally:
            self.root.after(300, lambda: self.btn_actualizar.config(text="🔄 Actualizar", state="normal"))

    def _on_cambio_periodo(self, event=None):
        sel = self.combo_periodo.get()
        hoy = datetime.now()
        if sel == "Hoy":
            self.fecha_ini = hoy.strftime("%Y-%m-%d")
            self.fecha_fin = self.fecha_ini
        elif sel == "Ayer":
            ayer = hoy - timedelta(days=1)
            self.fecha_ini = ayer.strftime("%Y-%m-%d")
            self.fecha_fin = self.fecha_ini
        elif sel == "Esta semana":
            ini_sem = hoy - timedelta(days=hoy.weekday())
            self.fecha_ini = ini_sem.strftime("%Y-%m-%d")
            self.fecha_fin = hoy.strftime("%Y-%m-%d")
        elif sel == "Este mes":
            self.fecha_ini = hoy.strftime("%Y-%m-01")
            self.fecha_fin = hoy.strftime("%Y-%m-%d")
        elif sel == "Mes anterior":
            primer_dia = hoy.replace(day=1)
            ultimo_ant = primer_dia - timedelta(days=1)
            self.fecha_ini = ultimo_ant.strftime("%Y-%m-01")
            self.fecha_fin = ultimo_ant.strftime("%Y-%m-%d")
        elif sel == "Personalizado":
            self._abrir_modal_rango_fechas()
            return

        self.lbl_rango_fechas.config(text=f"({self.fecha_ini} al {self.fecha_fin})")
        self.actualizar_todo()

    def _abrir_modal_rango_fechas(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Seleccionar Rango de Fechas")
        calcular_geometria_segura(dlg, 360, 240, modal_padre=self.root)
        dlg.configure(bg=self.c_bg)
        dlg.transient(self.root)
        dlg.grab_set()

        tk.Label(dlg, text="📅 Rango Personalizado", font=("Segoe UI", 11, "bold"), bg=self.c_bg, fg=self.c_text).pack(pady=(15, 10))
        box = tk.Frame(dlg, bg=self.c_card, padx=15, pady=12, highlightbackground=self.c_border, highlightthickness=1)
        box.pack(fill="both", expand=True, padx=20, pady=(0, 15))

        tk.Label(box, text="Fecha Inicial (YYYY-MM-DD):", font=("Segoe UI", 9, "bold"), bg=self.c_card, fg=self.c_text).pack(anchor="w", pady=(0, 2))
        e_ini = tk.Entry(box, font=("Segoe UI", 10), width=20)
        e_ini.insert(0, self.fecha_ini)
        e_ini.pack(anchor="w", pady=(0, 8))

        tk.Label(box, text="Fecha Final (YYYY-MM-DD):", font=("Segoe UI", 9, "bold"), bg=self.c_card, fg=self.c_text).pack(anchor="w", pady=(0, 2))
        e_fin = tk.Entry(box, font=("Segoe UI", 10), width=20)
        e_fin.insert(0, self.fecha_fin)
        e_fin.pack(anchor="w", pady=(0, 12))

        def _aplicar():
            f1, f2 = e_ini.get().strip(), e_fin.get().strip()
            try:
                datetime.strptime(f1, "%Y-%m-%d")
                datetime.strptime(f2, "%Y-%m-%d")
            except Exception:
                messagebox.showwarning("Formato Inválido", "Ingresa las fechas en formato YYYY-MM-DD (ej: 2026-10-01)", parent=dlg)
                return
            if f1 > f2:
                messagebox.showwarning("Rango Inválido", "La fecha inicial no puede ser posterior a la final.", parent=dlg)
                return
            self.fecha_ini, self.fecha_fin = f1, f2
            self.lbl_rango_fechas.config(text=f"({f1} al {f2})")
            dlg.destroy()
            self.actualizar_todo()

        b_row = tk.Frame(box, bg=self.c_card)
        b_row.pack(fill="x")
        tk.Button(b_row, text="Cancelar", command=dlg.destroy, font=("Segoe UI", 9), relief="flat", bg="#F1F5F9", fg=self.c_text, padx=10, pady=4).pack(side="left")
        tk.Button(b_row, text="Aplicar Rango", command=_aplicar, font=("Segoe UI", 9, "bold"), relief="flat", bg=self.c_primary, fg="white", padx=12, pady=4).pack(side="right")

    # --------------------------------------------------------------------------
    # 2. PANTALLA 1: RESUMEN FINANCIERO (4 TARJETAS + CÓMO SE MOVIÓ + 2 GRÁFICAS)
    # --------------------------------------------------------------------------
    def _construir_resumen_financiero(self):
        scroll = ScrollableContainer(self.vista_resumen, bg=self.c_bg)
        scroll.pack(fill="both", expand=True)
        content = scroll.scrollable_frame

        # ======================================================================
        # BLOQUE 1: LAS 4 TARJETAS PRINCIPALES (Ventas, Costos, Gastos, Ganancia)
        # ======================================================================
        f_top_cards = tk.Frame(content, bg=self.c_bg)
        f_top_cards.pack(fill="x", pady=(2, 8))

        self.card_labels = {}
        configs_4 = [
            ("ventas_netas", "1. VENTAS NETAS", self.c_green, "Facturación en ventas activas"),
            ("costo_ventas", "2. COSTOS DE PRODUCTOS", self.c_red, "Costo de compra de lo vendido"),
            ("gastos_total", "3. GASTOS DEL PERÍODO", self.c_amber, "Arriendos, servicios y operación"),
            ("ganancia_neta", "4. GANANCIA NETA ESTIMADA", "#2563EB", "Utilidad final disponible")
        ]

        for i, (key, titulo, color, desc) in enumerate(configs_4):
            card = tk.Frame(f_top_cards, bg=self.c_card, relief="flat", bd=0, highlightbackground=self.c_border, highlightthickness=1)
            card.pack(side="left", fill="both", expand=True, padx=(0 if i == 0 else 6, 0))

            # Franja superior de color
            tk.Frame(card, bg=color, height=4).pack(fill="x")

            inner = tk.Frame(card, bg=self.c_card, padx=14, pady=10)
            inner.pack(fill="both", expand=True)

            tk.Label(inner, text=titulo, font=("Segoe UI", 9, "bold"), bg=self.c_card, fg=self.c_text_muted).pack(anchor="w")
            lbl_val = tk.Label(inner, text="$0", font=("Segoe UI", 18, "bold"), bg=self.c_card, fg=color)
            lbl_val.pack(anchor="w", pady=(3, 1))

            lbl_sub = tk.Label(inner, text=desc, font=("Segoe UI", 8), bg=self.c_card, fg=self.c_text_muted)
            lbl_sub.pack(anchor="w")

            self.card_labels[key] = (lbl_val, lbl_sub)

        # ======================================================================
        # INDICADOR SECUNDARIO: CARTERA PENDIENTE (FIADOS) Y VALOR DEL INVENTARIO
        # ======================================================================
        f_cartera_banner = tk.Frame(content, bg=self.c_card, relief="flat", bd=0, highlightbackground=self.c_border, highlightthickness=1)
        f_cartera_banner.pack(fill="x", pady=(0, 10))
        b_in = tk.Frame(f_cartera_banner, bg=self.c_card, padx=14, pady=8)
        b_in.pack(fill="x")

        # Lado izquierdo: Cartera pendiente
        tk.Label(b_in, text="💳 CARTERA PENDIENTE (FIADOS):", font=("Segoe UI", 9, "bold"), bg=self.c_card, fg=self.c_indigo).pack(side="left")
        self.lbl_cartera_banner = tk.Label(b_in, text="$0", font=("Segoe UI", 12, "bold"), bg=self.c_card, fg=self.c_indigo)
        self.lbl_cartera_banner.pack(side="left", padx=(4, 16))

        # Separador vertical
        tk.Frame(b_in, bg=self.c_border, width=1, height=18).pack(side="left", padx=8)

        # Lado derecho: Valor del inventario a costo
        tk.Label(b_in, text="📦 VALOR DEL INVENTARIO (COSTO):", font=("Segoe UI", 9, "bold"), bg=self.c_card, fg="#0F766E").pack(side="left")
        self.lbl_inventario_banner = tk.Label(b_in, text="$0", font=("Segoe UI", 12, "bold"), bg=self.c_card, fg="#0F766E")
        self.lbl_inventario_banner.pack(side="left", padx=(4, 8))

        tk.Label(b_in, text="• Activos y créditos comerciales del negocio", font=("Segoe UI", 8, "italic"), bg=self.c_card, fg=self.c_text_muted).pack(side="right")

        # ======================================================================
        # BLOQUE 2: ¿CÓMO SE MOVIÓ EL DINERO? Y ESTADO DE RESULTADOS COMPACTO
        # ======================================================================
        f_mov_container = tk.Frame(content, bg=self.c_card, relief="flat", bd=0, highlightbackground=self.c_border, highlightthickness=1)
        f_mov_container.pack(fill="x", pady=(0, 10))

        tk.Label(f_mov_container, text="💵 ¿CÓMO SE MOVIÓ EL DINERO EN ESTE PERÍODO?", font=("Segoe UI", 11, "bold"), bg=self.c_card, fg=self.c_text).pack(anchor="w", padx=16, pady=(12, 2))
        tk.Label(f_mov_container, text="Diferencia transparente entre las ventas facturadas y los recaudos efectivos de tesorería", font=("Segoe UI", 9), bg=self.c_card, fg=self.c_text_muted).pack(anchor="w", padx=16, pady=(0, 8))

        f_mov_grid = tk.Frame(f_mov_container, bg=self.c_card, padx=14, pady=4)
        f_mov_grid.pack(fill="x", pady=(0, 12))

        # 3 Columnas de recaudos
        # Columna 1: Efectivo Recibido
        col_efectivo = tk.Frame(f_mov_grid, bg="#F0FDF4", highlightbackground="#86EFAC", highlightthickness=1, padx=12, pady=10)
        col_efectivo.pack(side="left", fill="both", expand=True, padx=(0, 6))

        tk.Label(col_efectivo, text="💵 EFECTIVO RECIBIDO", font=("Segoe UI", 9, "bold"), bg="#F0FDF4", fg="#166534").pack(anchor="w")
        self.lbl_efectivo_total = tk.Label(col_efectivo, text="$0", font=("Segoe UI", 16, "bold"), bg="#F0FDF4", fg="#15803D")
        self.lbl_efectivo_total.pack(anchor="w", pady=(2, 2))
        self.lbl_efectivo_desglose = tk.Label(col_efectivo, text="Ventas efectivo: $0 | Abonos: $0", font=("Segoe UI", 8), bg="#F0FDF4", fg="#166534")
        self.lbl_efectivo_desglose.pack(anchor="w")
        tk.Label(col_efectivo, text="✅ Dinero físico recibido en gaveta", font=("Segoe UI", 8, "italic"), bg="#F0FDF4", fg="#166534").pack(anchor="w", pady=(4, 0))

        # Columna 2: Transferencias Recibidas
        col_transf = tk.Frame(f_mov_grid, bg="#EFF6FF", highlightbackground="#93C5FD", highlightthickness=1, padx=12, pady=10)
        col_transf.pack(side="left", fill="both", expand=True, padx=4)

        tk.Label(col_transf, text="📲 TRANSFERENCIAS RECIBIDAS", font=("Segoe UI", 9, "bold"), bg="#EFF6FF", fg="#1E40AF").pack(anchor="w")
        self.lbl_transf_total = tk.Label(col_transf, text="$0", font=("Segoe UI", 16, "bold"), bg="#EFF6FF", fg="#1D4ED8")
        self.lbl_transf_total.pack(anchor="w", pady=(2, 2))
        self.lbl_transf_desglose = tk.Label(col_transf, text="0.0% de las ventas del período", font=("Segoe UI", 8), bg="#EFF6FF", fg="#1E40AF")
        self.lbl_transf_desglose.pack(anchor="w")
        tk.Label(col_transf, text="✅ Dinero digital recibido en cuentas/bancos", font=("Segoe UI", 8, "italic"), bg="#EFF6FF", fg="#1E40AF").pack(anchor="w", pady=(4, 0))

        # Columna 3: Ventas a Crédito (Fiados)
        col_fiados = tk.Frame(f_mov_grid, bg="#FFFBEB", highlightbackground="#FDE68A", highlightthickness=1, padx=12, pady=10)
        col_fiados.pack(side="left", fill="both", expand=True, padx=(6, 0))

        tk.Label(col_fiados, text="📝 VENTAS A CRÉDITO (FIADOS)", font=("Segoe UI", 9, "bold"), bg="#FFFBEB", fg="#92400E").pack(anchor="w")
        self.lbl_fiados_total = tk.Label(col_fiados, text="$0", font=("Segoe UI", 16, "bold"), bg="#FFFBEB", fg="#B45309")
        self.lbl_fiados_total.pack(anchor="w", pady=(2, 2))
        self.lbl_fiados_desglose = tk.Label(col_fiados, text="0.0% de las ventas otorgadas a fiado", font=("Segoe UI", 8), bg="#FFFBEB", fg="#92400E")
        self.lbl_fiados_desglose.pack(anchor="w")
        tk.Label(col_fiados, text="⚠️ No es dinero recibido aún", font=("Segoe UI", 8, "italic"), bg="#FFFBEB", fg="#B45309").pack(anchor="w", pady=(4, 0))

        # Tabla de Estado de Resultados Compacta
        f_tbl_resultados = tk.Frame(f_mov_container, bg="#F8FAFC", highlightbackground=self.c_border, highlightthickness=1)
        f_tbl_resultados.pack(fill="x", padx=14, pady=(0, 14))

        self.lbl_estado_res_rows = {}
        filas_conceptos = [
            ("ventas", "(+) Ventas Netas Facturadas:", self.c_green),
            ("costos", "(-) Costo de Mercancía Vendida:", self.c_red),
            ("utilidad_bruta", "(=) Utilidad Bruta Comercial:", self.c_primary),
            ("gastos", "(-) Gastos Operativos del Período:", self.c_amber),
            ("nomina", "(-) Gastos de Personal y Comisiones (Nómina):", "#7C3AED"),
            ("ganancia_neta", "(=) Ganancia Operativa Neta Estimada:", "#2563EB")
        ]

        for i, (k, desc, col) in enumerate(filas_conceptos):
            r_box = tk.Frame(f_tbl_resultados, bg="#F8FAFC" if i % 2 == 0 else "#FFFFFF", padx=14, pady=5)
            r_box.pack(fill="x")
            tk.Label(r_box, text=desc, font=("Segoe UI", 9, "bold" if "(=)" in desc else "normal"), bg=r_box["bg"], fg=self.c_text).pack(side="left")
            
            lbl_v = tk.Label(r_box, text="$0", font=("Segoe UI", 9, "bold"), bg=r_box["bg"], fg=col)
            lbl_v.pack(side="right", padx=(10, 0))
            
            lbl_pct = tk.Label(r_box, text="100%", font=("Segoe UI", 8), bg=r_box["bg"], fg=self.c_text_muted)
            lbl_pct.pack(side="right")
            self.lbl_estado_res_rows[k] = (lbl_v, lbl_pct)

        # ======================================================================
        # BLOQUE 3: LAS DOS GRÁFICAS PRINCIPALES (SIN SUPERPOSICIÓN)
        # ======================================================================
        f_charts_row = tk.Frame(content, bg=self.c_bg)
        f_charts_row.pack(fill="x", pady=(0, 10))

        # Gráfica 1: Evolución de Ventas Diarias
        card_g1 = tk.Frame(f_charts_row, bg=self.c_card, relief="flat", bd=0, highlightbackground=self.c_border, highlightthickness=1)
        card_g1.pack(side="left", fill="both", expand=True, padx=(0, 5))

        tk.Label(card_g1, text="📈 EVOLUCIÓN DE VENTAS POR DÍA", font=("Segoe UI", 10, "bold"), bg=self.c_card, fg=self.c_text).pack(anchor="w", padx=14, pady=(10, 2))
        tk.Label(card_g1, text="Comportamiento diario de la facturación en el período", font=("Segoe UI", 8), bg=self.c_card, fg=self.c_text_muted).pack(anchor="w", padx=14, pady=(0, 6))

        self.cv_ventas_diarias = tk.Canvas(card_g1, bg=self.c_card, height=190, highlightthickness=0)
        self.cv_ventas_diarias.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # Gráfica 2: Distribución de Ventas por Medio de Pago
        card_g2 = tk.Frame(f_charts_row, bg=self.c_card, relief="flat", bd=0, highlightbackground=self.c_border, highlightthickness=1)
        card_g2.pack(side="right", fill="both", expand=True, padx=(5, 0))

        tk.Label(card_g2, text="📊 DISTRIBUCIÓN POR MEDIO DE PAGO", font=("Segoe UI", 10, "bold"), bg=self.c_card, fg=self.c_text).pack(anchor="w", padx=14, pady=(10, 2))
        tk.Label(card_g2, text="Proporción entre efectivo, transferencias y créditos", font=("Segoe UI", 8), bg=self.c_card, fg=self.c_text_muted).pack(anchor="w", padx=14, pady=(0, 6))

        self.cv_medios_pago = tk.Canvas(card_g2, bg=self.c_card, height=190, highlightthickness=0)
        self.cv_medios_pago.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # ======================================================================
        # BLOQUE 4: ACCESO DESTACADO A "ANÁLISIS DEL NEGOCIO"
        # ======================================================================
        f_analisis_callout = tk.Frame(content, bg=self.c_card, relief="flat", bd=0, highlightbackground=self.c_border, highlightthickness=1)
        f_analisis_callout.pack(fill="x", pady=(0, 14))

        in_an = tk.Frame(f_analisis_callout, bg=self.c_card, padx=16, pady=12)
        in_an.pack(fill="x")

        tk.Label(in_an, text="🔍 ANÁLISIS COMERCIAL Y RECOMENDACIONES", font=("Segoe UI", 10, "bold"), bg=self.c_card, fg=self.c_text).pack(side="left")
        tk.Label(in_an, text="Rentabilidad, productos más rentables, mejores días, stock bajo y sugerencias", font=("Segoe UI", 8), bg=self.c_card, fg=self.c_text_muted).pack(side="left", padx=10)

        tk.Button(
            in_an, text="Abrir Análisis Completo ➔", font=("Segoe UI", 9, "bold"),
            bg="#2563EB", fg="white", activebackground="#1D4ED8", activeforeground="white",
            relief="flat", cursor="hand2", padx=14, pady=5,
            command=self._abrir_modal_analisis_negocio
        ).pack(side="right")

    # --------------------------------------------------------------------------
    # DIBUJO DE LAS DOS GRÁFICAS (CON ESPACIO Y SIN SUPERPOSICIONES)
    # --------------------------------------------------------------------------
    def _dibujar_graficas(self):
        # 1. Gráfica de Ventas Diarias
        cv1 = self.cv_ventas_diarias
        cv1.delete("all")
        w1 = cv1.winfo_width() or 480
        h1 = cv1.winfo_height() or 190

        ventas_d = self.metricas_actuales.get("ventas_diarias", [])
        if not ventas_d or all(v["total"] == 0 for v in ventas_d):
            cv1.create_text(w1 // 2, h1 // 2, text="No hay ventas registradas en las fechas seleccionadas.",
                            font=("Segoe UI", 9, "italic"), fill=self.c_text_muted)
        else:
            # Dibujar gráfico de barras diario limpio
            pad_left = 60
            pad_right = 20
            pad_top = 25
            pad_bot = 35

            chart_w = w1 - pad_left - pad_right
            chart_h = h1 - pad_top - pad_bot
            max_v = max(v["total"] for v in ventas_d)
            if max_v <= 0: max_v = 1.0

            # Líneas guía horizontales
            cv1.create_line(pad_left, pad_top + chart_h, pad_left + chart_w, pad_top + chart_h, fill="#CBD5E1")
            cv1.create_text(pad_left - 8, pad_top + chart_h, text="$0", anchor="e", font=("Segoe UI", 8), fill=self.c_text_muted)

            top_y = pad_top
            cv1.create_line(pad_left, top_y, pad_left + chart_w, top_y, fill="#F1F5F9", dash=(2, 2))
            cv1.create_text(pad_left - 8, top_y, text=f"${max_v:,.0f}", anchor="e", font=("Segoe UI", 8), fill=self.c_text_muted)

            mid_y = pad_top + (chart_h / 2)
            cv1.create_line(pad_left, mid_y, pad_left + chart_w, mid_y, fill="#F1F5F9", dash=(2, 2))
            cv1.create_text(pad_left - 8, mid_y, text=f"${max_v / 2:,.0f}", anchor="e", font=("Segoe UI", 8), fill=self.c_text_muted)

            n_bars = len(ventas_d)
            slot_w = chart_w / n_bars
            bar_w = max(10, min(36, slot_w * 0.65))

            for i, item in enumerate(ventas_d):
                cx = pad_left + (i * slot_w) + (slot_w / 2)
                val = item["total"]
                bar_h = (val / max_v) * chart_h
                by = pad_top + chart_h - bar_h

                # Barra
                if bar_h > 0:
                    cv1.create_rectangle(cx - bar_w / 2, by, cx + bar_w / 2, pad_top + chart_h, fill="#059669", outline="")
                    # Valor arriba de la barra (solo si cabe y no satura)
                    if n_bars <= 10:
                        cv1.create_text(cx, by - 6, text=f"${val:,.0f}", anchor="s", font=("Segoe UI", 7, "bold"), fill=self.c_text)

                # Etiqueta de fecha abajo
                cv1.create_text(cx, pad_top + chart_h + 8, text=item["dia_label"], anchor="n", font=("Segoe UI", 7), fill=self.c_text_muted)

        # 2. Gráfica de Medios de Pago
        cv2 = self.cv_medios_pago
        cv2.delete("all")
        w2 = cv2.winfo_width() or 480
        h2 = cv2.winfo_height() or 190

        rv = self.metricas_actuales.get("resumen_ventas", {})
        v_net = rv.get("ventas_netas", 0.0)
        if v_net <= 0:
            cv2.create_text(w2 // 2, h2 // 2, text="Sin recaudos en este período para clasificar.",
                            font=("Segoe UI", 9, "italic"), fill=self.c_text_muted)
        else:
            items_p = [
                ("💵 Efectivo", rv.get("efectivo", 0.0), rv.get("pct_efectivo", 0.0), "#059669"),
                ("📲 Transferencia", rv.get("transferencia", 0.0), rv.get("pct_transferencia", 0.0), "#2563EB"),
                ("📝 Fiados (Crédito)", rv.get("fiado", 0.0), rv.get("pct_fiado", 0.0), "#D97706")
            ]

            y_pos = 28
            bar_start_x = 180
            bar_max_w = max(60, w2 - bar_start_x - 30)

            for nom, val, pct, col in items_p:
                # Nombre y monto
                cv2.create_text(16, y_pos, text=nom, anchor="w", font=("Segoe UI", 9, "bold"), fill=self.c_text)
                cv2.create_text(16, y_pos + 18, text=f"${val:,.0f} ({pct:.1f}%)", anchor="w", font=("Segoe UI", 8), fill=self.c_text_muted)

                # Barra horizontal proporcional
                b_w = (pct / 100.0) * bar_max_w if v_net > 0 else 0
                cv2.create_rectangle(bar_start_x, y_pos + 4, bar_start_x + bar_max_w, y_pos + 18, fill="#E2E8F0", outline="")
                if b_w > 0:
                    cv2.create_rectangle(bar_start_x, y_pos + 4, bar_start_x + b_w, y_pos + 18, fill=col, outline="")

                y_pos += 48

    # --------------------------------------------------------------------------
    # SUBSECCIÓN / MODAL: ANÁLISIS DETALLADO DEL NEGOCIO
    # --------------------------------------------------------------------------
    def _abrir_modal_analisis_negocio(self):
        an_dlg = tk.Toplevel(self.root)
        an_dlg.title("🔍 Análisis Detallado del Negocio e Inteligencia Comercial")
        calcular_geometria_segura(an_dlg, 860, 640, modal_padre=self.root)
        an_dlg.configure(bg=self.c_bg)
        an_dlg.transient(self.root)

        scroll = ScrollableContainer(an_dlg, bg=self.c_bg)
        scroll.pack(fill="both", expand=True, padx=12, pady=12)
        content = scroll.scrollable_frame

        tk.Label(content, text="🔍 ANÁLISIS DETALLADO DEL NEGOCIO", font=("Segoe UI", 13, "bold"), bg=self.c_bg, fg=self.c_text).pack(anchor="w", pady=(0, 4))
        tk.Label(content, text=f"Período evaluado: {self.fecha_ini} al {self.fecha_fin}", font=("Segoe UI", 9), bg=self.c_bg, fg=self.c_text_muted).pack(anchor="w", pady=(0, 12))

        an_data = self.metricas_actuales.get("analisis_negocio", {})
        kpis = self.metricas_actuales.get("kpis", {})

        # 1. RENTABILIDAD SOBRE VENTAS Y DÍAS CLAVE
        f_rent = tk.Frame(content, bg=self.c_card, padx=16, pady=12, highlightbackground=self.c_border, highlightthickness=1)
        f_rent.pack(fill="x", pady=(0, 10))

        tk.Label(f_rent, text="📊 RENTABILIDAD Y DÍAS DESTACADOS", font=("Segoe UI", 10, "bold"), bg=self.c_card, fg=self.c_text).pack(anchor="w", pady=(0, 8))
        
        c_r_row = tk.Frame(f_rent, bg=self.c_card)
        c_r_row.pack(fill="x")

        # Margen Bruto
        mb = kpis.get("C_utilidad_bruta", 0.0)
        v_net = kpis.get("A_ventas_netas", 0.0)
        mb_pct = (mb / v_net * 100.0) if v_net > 0 else 0.0
        mn_pct = kpis.get("F_margen_neto_pct", 0.0)

        tk.Label(c_r_row, text=f"• Margen Bruto Comercial: {mb_pct:.1f}%", font=("Segoe UI", 9), bg=self.c_card, fg=self.c_text).pack(side="left", padx=(0, 20))
        tk.Label(c_r_row, text=f"• Margen Neto Operativo: {mn_pct:.1f}%", font=("Segoe UI", 9), bg=self.c_card, fg=self.c_text).pack(side="left", padx=(0, 20))

        dia_top = an_data.get("dia_mejor")
        if dia_top:
            tk.Label(f_rent, text=f"🏆 Día con mayores ventas: {dia_top['fecha']} (${dia_top['total']:,.0f} facturados en {dia_top['cantidad']} ventas)", font=("Segoe UI", 9), bg=self.c_card, fg="#166534").pack(anchor="w", pady=(6, 0))

        dia_bot = an_data.get("dia_peor")
        if dia_bot:
            tk.Label(f_rent, text=f"📉 Día con menores ventas: {dia_bot['fecha']} (${dia_bot['total']:,.0f} facturados)", font=("Segoe UI", 9), bg=self.c_card, fg=self.c_text_muted).pack(anchor="w", pady=(2, 0))

        # 2. TOP PRODUCTOS CON MAYOR GANANCIA BRUTA
        f_prods = tk.Frame(content, bg=self.c_card, padx=16, pady=12, highlightbackground=self.c_border, highlightthickness=1)
        f_prods.pack(fill="x", pady=(0, 10))

        tk.Label(f_prods, text="⭐ PRODUCTOS QUE DEJAN MAYOR GANANCIA BRUTA", font=("Segoe UI", 10, "bold"), bg=self.c_card, fg=self.c_text).pack(anchor="w", pady=(0, 6))
        top_u = an_data.get("top_utilidad_productos", [])
        if top_u:
            for p in top_u:
                tk.Label(f_prods, text=f"• {p['nombre']}: Ganancia Bruta ${p['ganancia']:,.0f} (Margen: {p['margen_pct']:.1f}% | {p['unidades']} unidades)", font=("Segoe UI", 9), bg=self.c_card, fg=self.c_text).pack(anchor="w", pady=1)
        else:
            tk.Label(f_prods, text="No hay ventas de productos en este período.", font=("Segoe UI", 8, "italic"), bg=self.c_card, fg=self.c_text_muted).pack(anchor="w")

        # 3. GASTOS MÁS ELEVADOS
        f_gastos_m = tk.Frame(content, bg=self.c_card, padx=16, pady=12, highlightbackground=self.c_border, highlightthickness=1)
        f_gastos_m.pack(fill="x", pady=(0, 10))

        tk.Label(f_gastos_m, text="💸 GASTOS MÁS ELEVADOS DEL PERÍODO", font=("Segoe UI", 10, "bold"), bg=self.c_card, fg=self.c_text).pack(anchor="w", pady=(0, 6))
        gm = an_data.get("gastos_mayores", [])
        if gm:
            for g in gm:
                tk.Label(f_gastos_m, text=f"• {g.get('concepto')}: ${float(g.get('valor',0.0)):,.0f} ({g.get('categoria')}) - {g.get('fecha')} [{g.get('estado')}]", font=("Segoe UI", 9), bg=self.c_card, fg=self.c_text).pack(anchor="w", pady=1)
        else:
            tk.Label(f_gastos_m, text="No hay gastos registrados en este período.", font=("Segoe UI", 8, "italic"), bg=self.c_card, fg=self.c_text_muted).pack(anchor="w")

        # 4. ALERTA DE PRODUCTOS CON STOCK BAJO (<= 5)
        f_stock = tk.Frame(content, bg=self.c_card, padx=16, pady=12, highlightbackground=self.c_border, highlightthickness=1)
        f_stock.pack(fill="x", pady=(0, 10))

        tk.Label(f_stock, text="📦 PRODUCTOS CON INVENTARIO BAJO (≤ 5 UNIDADES)", font=("Segoe UI", 10, "bold"), bg=self.c_card, fg="#DC2626").pack(anchor="w", pady=(0, 6))
        sb = an_data.get("productos_stock_bajo", [])
        if sb:
            for p in sb[:6]:
                tk.Label(f_stock, text=f"• {p['nombre']} (Cód: {p['codigo']}): Solo quedan {p['stock']} unidades disponibles", font=("Segoe UI", 9), bg=self.c_card, fg="#B91C1C").pack(anchor="w", pady=1)
        else:
            tk.Label(f_stock, text="Todos los productos físicos cuentan con stock suficiente (>5).", font=("Segoe UI", 8, "italic"), bg=self.c_card, fg="#166534").pack(anchor="w")

        # 5. RECOMENDACIONES SUSTENTADAS EN DATOS
        f_recom = tk.Frame(content, bg=self.c_card, padx=16, pady=12, highlightbackground=self.c_border, highlightthickness=1)
        f_recom.pack(fill="x", pady=(0, 10))

        tk.Label(f_recom, text="💡 RECOMENDACIONES Y ALERTAS CONCRETAS", font=("Segoe UI", 10, "bold"), bg=self.c_card, fg=self.c_text).pack(anchor="w", pady=(0, 6))
        alertas = generar_alertas_recomendaciones(self.fecha_ini, self.fecha_fin)
        for a in alertas:
            col_icon = "#DC2626" if a["tipo"] == "alerta" else ("#D97706" if a["tipo"] == "advertencia" else ("#059669" if a["tipo"] == "positivo" else "#2563EB"))
            row = tk.Frame(f_recom, bg=self.c_card, pady=4)
            row.pack(fill="x")
            tk.Label(row, text=f"• {a['titulo']}:", font=("Segoe UI", 9, "bold"), bg=self.c_card, fg=col_icon).pack(anchor="w")
            tk.Label(row, text=f"  {a['mensaje']} ➔ {a['accion']}", font=("Segoe UI", 8), bg=self.c_card, fg=self.c_text, wraplength=780, justify="left").pack(anchor="w")

    # --------------------------------------------------------------------------
    # 3. PANTALLA 2: REGISTROS E INFORMES (INDEPENDIENTE CON TABLAS Y EXPORTACIONES)
    # --------------------------------------------------------------------------
    def _construir_registros_e_informes(self):
        # Barra superior con botones de exportación
        top_bar = tk.Frame(self.vista_registros, bg=self.c_card, padx=16, pady=10, highlightbackground=self.c_border, highlightthickness=1)
        top_bar.pack(fill="x", pady=(0, 8))

        tk.Label(top_bar, text="📑 REGISTROS E INFORMES FINANCIEROS DETALLADOS", font=("Segoe UI", 11, "bold"), bg=self.c_card, fg=self.c_text).pack(side="left")

        # Botones de exportación con alto contraste y claridad
        tk.Button(
            top_bar, text="📑 Exportar a Excel (9 Pestañas)", font=("Segoe UI", 9, "bold"),
            bg="#16A34A", fg="white", activebackground="#15803D", activeforeground="white",
            relief="flat", cursor="hand2", padx=14, pady=5,
            command=self._exportar_excel
        ).pack(side="right", padx=(6, 0))

        tk.Button(
            top_bar, text="📄 Exportar a PDF / Imprimible", font=("Segoe UI", 9, "bold"),
            bg="#0284C7", fg="white", activebackground="#0369A1", activeforeground="white",
            relief="flat", cursor="hand2", padx=14, pady=5,
            command=self._exportar_pdf
        ).pack(side="right")

        # Cuaderno de pestañas secundario para no amontonar
        nb = ttk.Notebook(self.vista_registros)
        nb.pack(fill="both", expand=True)

        tab_22 = tk.Frame(nb, bg=self.c_bg)
        tab_op = tk.Frame(nb, bg=self.c_bg)
        tab_top = tk.Frame(nb, bg=self.c_bg)
        tab_cli = tk.Frame(nb, bg=self.c_bg)

        nb.add(tab_22, text="📋 22 Conceptos Oficiales")
        nb.add(tab_op, text="👨‍💼 Rendimiento Operarios")
        nb.add(tab_top, text="⭐ Productos y Rentabilidad")
        nb.add(tab_cli, text="💳 Cartera y Fiados")

        # 1. TABLA 22 CONCEPTOS
        f22 = tk.Frame(tab_22, bg=self.c_card, highlightbackground=self.c_border, highlightthickness=1)
        f22.pack(fill="both", expand=True, padx=8, pady=8)

        cols_22 = ("N°", "Código", "Concepto Contable", "Monto (COP)", "Tipo", "Explicación")
        self.tree_22 = ttk.Treeview(f22, columns=cols_22, show="headings", height=14)
        w_22 = [40, 75, 260, 120, 110, 380]
        for c, w in zip(cols_22, w_22):
            self.tree_22.heading(c, text=c)
            self.tree_22.column(c, width=w, anchor="e" if c == "Monto (COP)" else ("center" if c in ["N°", "Código", "Tipo"] else "w"))

        sb22 = ttk.Scrollbar(f22, orient="vertical", command=self.tree_22.yview)
        self.tree_22.configure(yscrollcommand=sb22.set)
        self.tree_22.pack(side="left", fill="both", expand=True)
        sb22.pack(side="right", fill="y")

        # 2. TABLA OPERARIOS
        f_op = tk.Frame(tab_op, bg=self.c_card, highlightbackground=self.c_border, highlightthickness=1)
        f_op.pack(fill="both", expand=True, padx=8, pady=8)

        cols_op = ("Operario", "Total Vendido", "Cant. Ventas", "Ticket Promedio", "Efectivo", "Transferencia", "Fiado")
        self.tree_op = ttk.Treeview(f_op, columns=cols_op, show="headings", height=10)
        for c in cols_op:
            self.tree_op.heading(c, text=c)
            self.tree_op.column(c, width=130, anchor="e" if c not in ["Operario"] else "w")
        self.tree_op.pack(fill="both", expand=True)

        # 3. TABLA PRODUCTOS
        f_pr = tk.Frame(tab_top, bg=self.c_card, highlightbackground=self.c_border, highlightthickness=1)
        f_pr.pack(fill="both", expand=True, padx=8, pady=8)

        cols_p = ("Código", "Producto", "Unidades", "Total Facturado", "Costo Total", "Ganancia Bruta", "Margen %")
        self.tree_prod = ttk.Treeview(f_pr, columns=cols_p, show="headings", height=10)
        for c in cols_p:
            self.tree_prod.heading(c, text=c)
            self.tree_prod.column(c, width=130, anchor="e" if c not in ["Código", "Producto"] else "w")
        self.tree_prod.pack(fill="both", expand=True)

        # 4. TABLA CARTERA
        f_cl = tk.Frame(tab_cli, bg=self.c_card, highlightbackground=self.c_border, highlightthickness=1)
        f_cl.pack(fill="both", expand=True, padx=8, pady=8)

        cols_cl = ("Cédula / Documento", "Nombre Cliente", "Teléfono", "Saldo Pendiente (COP)")
        self.tree_cli = ttk.Treeview(f_cl, columns=cols_cl, show="headings", height=10)
        for c in cols_cl:
            self.tree_cli.heading(c, text=c)
            self.tree_cli.column(c, width=180, anchor="e" if "Saldo" in c else "w")
        self.tree_cli.pack(fill="both", expand=True)

    # --------------------------------------------------------------------------
    # 4. PANTALLA 3: CIERRE DE CAJA (DOS BLOQUES CLAROS: EFECTIVO Y BANCOS)
    # --------------------------------------------------------------------------
    def _construir_cierre_de_caja(self):
        scroll = ScrollableContainer(self.vista_cierre, bg=self.c_bg)
        scroll.pack(fill="both", expand=True)
        content = scroll.scrollable_frame

        # ENCABEZADO SESIÓN
        f_ses = tk.Frame(content, bg=self.c_card, padx=16, pady=10, highlightbackground=self.c_border, highlightthickness=1)
        f_ses.pack(fill="x", pady=(0, 10))

        self.lbl_sesion_cierre = tk.Label(f_ses, text="🟢 Sesión de Caja Activa", font=("Segoe UI", 11, "bold"), bg=self.c_card, fg=self.c_text)
        self.lbl_sesion_cierre.pack(side="left")

        # CONTENEDOR DE DOS BLOQUES LADO A LADO
        f_bloques = tk.Frame(content, bg=self.c_bg)
        f_bloques.pack(fill="x", pady=(0, 10))

        # ======================================================================
        # BLOQUE A: EFECTIVO FÍSICO EN GAVETA
        # ======================================================================
        bloque_a = tk.Frame(f_bloques, bg=self.c_card, padx=16, pady=14, highlightbackground=self.c_border, highlightthickness=1)
        bloque_a.pack(side="left", fill="both", expand=True, padx=(0, 5))

        tk.Label(bloque_a, text="💵 BLOQUE A: EFECTIVO FÍSICO (GAVETA)", font=("Segoe UI", 11, "bold"), bg=self.c_card, fg=self.c_green).pack(anchor="w", pady=(0, 4))
        tk.Label(bloque_a, text="Control estricto de dinero en efectivo en el punto de venta", font=("Segoe UI", 8), bg=self.c_card, fg=self.c_text_muted).pack(anchor="w", pady=(0, 10))

        self.lbl_cierre_base = tk.Label(bloque_a, text="• Base Inicial de Caja: $0", font=("Segoe UI", 9), bg=self.c_card, fg=self.c_text)
        self.lbl_cierre_base.pack(anchor="w", pady=1)

        self.lbl_cierre_ventas_ef = tk.Label(bloque_a, text="• (+) Ventas en Efectivo: $0", font=("Segoe UI", 9), bg=self.c_card, fg="#166534")
        self.lbl_cierre_ventas_ef.pack(anchor="w", pady=1)

        self.lbl_cierre_abonos = tk.Label(bloque_a, text="• (+) Abonos de Cartera: $0", font=("Segoe UI", 9), bg=self.c_card, fg="#166534")
        self.lbl_cierre_abonos.pack(anchor="w", pady=1)

        self.lbl_cierre_egresos = tk.Label(bloque_a, text="• (-) Egresos y Gastos Pagados: $0", font=("Segoe UI", 9), bg=self.c_card, fg="#991B1B")
        self.lbl_cierre_egresos.pack(anchor="w", pady=1)

        self.lbl_cierre_devoluciones = tk.Label(bloque_a, text="• (-) Devoluciones / Anulaciones: $0", font=("Segoe UI", 9), bg=self.c_card, fg="#991B1B")
        self.lbl_cierre_devoluciones.pack(anchor="w", pady=1)

        # Destacado: Efectivo Esperado
        f_esp = tk.Frame(bloque_a, bg="#F0FDF4", padx=12, pady=8, highlightbackground="#86EFAC", highlightthickness=1)
        f_esp.pack(fill="x", pady=(10, 10))

        tk.Label(f_esp, text="EFECTIVO ESPERADO EN GAVETA:", font=("Segoe UI", 8, "bold"), bg="#F0FDF4", fg="#166534").pack(anchor="w")
        self.lbl_cierre_esperado = tk.Label(f_esp, text="$0", font=("Segoe UI", 16, "bold"), bg="#F0FDF4", fg="#15803D")
        self.lbl_cierre_esperado.pack(anchor="w")

        # Entrada para Efectivo Contado
        tk.Label(bloque_a, text="Introduce el efectivo contado físicamente en gaveta *:", font=("Segoe UI", 9, "bold"), bg=self.c_card, fg=self.c_text).pack(anchor="w", pady=(2, 2))
        self.entry_efectivo_contado = CurrencyEntry(
            bloque_a, initial_value=0, font=("Segoe UI", 12, "bold"), width=18,
            on_change=lambda val: self._recalcular_diferencia_caja()
        )
        self.entry_efectivo_contado.pack(anchor="w", pady=(0, 6))

        # Mensaje de Diferencia
        self.lbl_cierre_dif_msg = tk.Label(bloque_a, text="Caja cuadrada ($0)", font=("Segoe UI", 10, "bold"), bg=self.c_card, fg=self.c_green)
        self.lbl_cierre_dif_msg.pack(anchor="w", pady=(2, 4))

        # ======================================================================
        # BLOQUE B: CONCILIACIÓN BANCARIA (DIGITAL)
        # ======================================================================
        bloque_b = tk.Frame(f_bloques, bg=self.c_card, padx=16, pady=14, highlightbackground=self.c_border, highlightthickness=1)
        bloque_b.pack(side="right", fill="both", expand=True, padx=(5, 0))

        tk.Label(bloque_b, text="🏦 BLOQUE B: TRANSFERENCIAS BANCARIAS", font=("Segoe UI", 11, "bold"), bg=self.c_card, fg=self.c_accent).pack(anchor="w", pady=(0, 4))
        tk.Label(bloque_b, text="Conciliación de pagos digitales (Nequi, Daviplata, Bancolombia)", font=("Segoe UI", 8), bg=self.c_card, fg=self.c_text_muted).pack(anchor="w", pady=(0, 10))

        f_b_esp = tk.Frame(bloque_b, bg="#EFF6FF", padx=12, pady=8, highlightbackground="#93C5FD", highlightthickness=1)
        f_b_esp.pack(fill="x", pady=(0, 10))

        tk.Label(f_b_esp, text="TRANSFERENCIAS REGISTRADAS EN VENTAS:", font=("Segoe UI", 8, "bold"), bg="#EFF6FF", fg="#1E40AF").pack(anchor="w")
        self.lbl_banco_esperado = tk.Label(f_b_esp, text="$0", font=("Segoe UI", 16, "bold"), bg="#EFF6FF", fg="#1D4ED8")
        self.lbl_banco_esperado.pack(anchor="w")

        tk.Label(bloque_b, text="Monto verificado en extracto o notificaciones bancarias *:", font=("Segoe UI", 9, "bold"), bg=self.c_card, fg=self.c_text).pack(anchor="w", pady=(4, 2))
        self.entry_banco_verificado = CurrencyEntry(
            bloque_b, initial_value=0, font=("Segoe UI", 12, "bold"), width=18,
            on_change=lambda val: self._recalcular_diferencia_banco()
        )
        self.entry_banco_verificado.pack(anchor="w", pady=(0, 6))

        self.lbl_banco_dif_msg = tk.Label(bloque_b, text="Estado: Pendiente de verificar", font=("Segoe UI", 10, "bold"), bg=self.c_card, fg=self.c_amber)
        self.lbl_banco_dif_msg.pack(anchor="w", pady=(2, 4))

        # ======================================================================
        # ACCIONES DE CIERRE Y OBSERVACIONES
        # ======================================================================
        f_acciones_cierre = tk.Frame(content, bg=self.c_card, padx=16, pady=12, highlightbackground=self.c_border, highlightthickness=1)
        f_acciones_cierre.pack(fill="x", pady=(0, 10))

        tk.Label(f_acciones_cierre, text="Observaciones del Cierre de Turno:", font=("Segoe UI", 9, "bold"), bg=self.c_card, fg=self.c_text).pack(anchor="w", pady=(0, 3))
        self.entry_cierre_obs = tk.Entry(f_acciones_cierre, font=("Segoe UI", 10), width=60)
        self.entry_cierre_obs.pack(anchor="w", pady=(0, 10))

        self.btn_ejecutar_cierre = tk.Button(
            f_acciones_cierre, text="🔒 Ejecutar Cierre Definitivo de Caja", font=("Segoe UI", 10, "bold"),
            bg="#DC2626", fg="white", activebackground="#B91C1C", activeforeground="white",
            relief="flat", cursor="hand2", padx=20, pady=7,
            command=self._ejecutar_cierre_caja
        )
        self.btn_ejecutar_cierre.pack(side="left")

        # ======================================================================
        # HISTORIAL DE CIERRES ANTERIORES
        # ======================================================================
        f_historial = tk.Frame(content, bg=self.c_card, padx=16, pady=12, highlightbackground=self.c_border, highlightthickness=1)
        f_historial.pack(fill="x", pady=(0, 14))

        tk.Label(f_historial, text="📋 HISTORIAL DE CIERRES ANTERIORES", font=("Segoe UI", 10, "bold"), bg=self.c_card, fg=self.c_text).pack(anchor="w", pady=(0, 6))

        cols_h = ("ID", "Responsable", "Apertura", "Cierre", "Base", "Esp. Efectivo", "Real Efectivo", "Diferencia Caja", "Diferencia Banco", "Estado")
        self.tree_hist_cierres = ttk.Treeview(f_historial, columns=cols_h, show="headings", height=6)
        w_h = [40, 110, 110, 110, 90, 100, 100, 100, 100, 80]
        for c, w in zip(cols_h, w_h):
            self.tree_hist_cierres.heading(c, text=c)
            self.tree_hist_cierres.column(c, width=w, anchor="e" if "Base" in c or "Efectivo" in c or "Banco" in c or "Diferencia" in c else "center")
        self.tree_hist_cierres.pack(fill="x")

    def _recalcular_diferencia_caja(self, event=None):
        try:
            real = float(self.entry_efectivo_contado.get_value())
            esp = getattr(self, "monto_esperado_efectivo_act", 0.0)
            dif = real - esp
            if abs(dif) < 1.0:
                self.lbl_cierre_dif_msg.config(text="✅ Caja cuadrada ($0)", fg=self.c_green)
            elif dif < 0:
                self.lbl_cierre_dif_msg.config(text=f"🚨 Faltan ${abs(dif):,.0f}", fg=self.c_red)
            else:
                self.lbl_cierre_dif_msg.config(text=f"⚠️ Sobran ${dif:,.0f}", fg=self.c_accent)
        except Exception:
            pass

    def _recalcular_diferencia_banco(self, event=None):
        try:
            real = float(self.entry_banco_verificado.get_value())
            esp = getattr(self, "monto_transf_esperado_act", 0.0)
            dif = real - esp
            if abs(dif) < 1.0:
                self.lbl_banco_dif_msg.config(text="✅ Conciliación bancaria cuadrada (Coincide)", fg=self.c_green)
            elif dif < 0:
                self.lbl_banco_dif_msg.config(text=f"🚨 Diferencia: Faltan ${abs(dif):,.0f} en extracto", fg=self.c_red)
            else:
                self.lbl_banco_dif_msg.config(text=f"⚠️ Diferencia: Sobran ${dif:,.0f} en extracto", fg=self.c_accent)
        except Exception:
            pass

    def _cargar_datos_cierre(self):
        activa = obtener_sesion_activa()
        if activa:
            self.sesion_activa_id = activa["id"]
            arq = calcular_arqueo_sesion(activa["id"])
            esp_ef = arq.get("efectivo_esperado", 0.0)
            esp_bc = arq.get("ventas_transferencia", 0.0)
            base = arq.get("monto_inicial", 0.0)

            self.monto_esperado_efectivo_act = esp_ef
            self.monto_transf_esperado_act = esp_bc

            u_nom = activa.get("usuario_apertura", activa.get("usuario", "Admin"))
            f_ap = activa.get("fecha_apertura", "")
            h_ap = activa.get("hora_apertura", "")
            self.lbl_sesion_cierre.config(text=f"🟢 Turno Activo #{activa['id']} | Responsable: {u_nom} | Abierta: {f_ap} {h_ap}", fg=self.c_green)

            self.lbl_cierre_base.config(text=f"• Base Inicial de Caja: ${base:,.0f}")
            self.lbl_cierre_ventas_ef.config(text=f"• (+) Ventas en Efectivo: ${arq.get('ventas_efectivo', 0.0):,.0f}")
            self.lbl_cierre_abonos.config(text=f"• (+) Abonos de Cartera: ${arq.get('abonos_efectivo', 0.0):,.0f}")
            self.lbl_cierre_egresos.config(text=f"• (-) Egresos y Gastos Pagados: ${arq.get('egresos', 0.0):,.0f}")
            self.lbl_cierre_devoluciones.config(text=f"• (-) Devoluciones / Anulaciones: ${arq.get('devoluciones', 0.0):,.0f}")

            self.lbl_cierre_esperado.config(text=f"${esp_ef:,.0f}")
            self.lbl_banco_esperado.config(text=f"${esp_bc:,.0f}")

            self.entry_efectivo_contado.config(state="normal")
            self.entry_banco_verificado.config(state="normal")
            self.entry_cierre_obs.config(state="normal")
            self.btn_ejecutar_cierre.config(state="normal", bg="#DC2626", cursor="hand2")

            # Inicializar con el monto esperado para comodidad
            self.entry_efectivo_contado.set_value(int(round(esp_ef)))
            self.entry_banco_verificado.set_value(int(round(esp_bc)))
            self._recalcular_diferencia_caja()
            self._recalcular_diferencia_banco()
        else:
            self.sesion_activa_id = None
            self.monto_esperado_efectivo_act = 0.0
            self.monto_transf_esperado_act = 0.0
            self.lbl_sesion_cierre.config(text="🔴 No hay ninguna sesión de caja abierta en este momento.", fg=self.c_red)
            self.lbl_cierre_base.config(text="• Base Inicial de Caja: —")
            self.lbl_cierre_ventas_ef.config(text="• (+) Ventas en Efectivo: —")
            self.lbl_cierre_abonos.config(text="• (+) Abonos de Cartera: —")
            self.lbl_cierre_egresos.config(text="• (-) Egresos y Gastos Pagados: —")
            self.lbl_cierre_devoluciones.config(text="• (-) Devoluciones / Anulaciones: —")
            self.lbl_cierre_esperado.config(text="$0")
            self.lbl_banco_esperado.config(text="$0")
            self.entry_efectivo_contado.set_value(0)
            self.entry_banco_verificado.set_value(0)
            self.entry_efectivo_contado.config(state="disabled")
            self.entry_banco_verificado.config(state="disabled")
            self.entry_cierre_obs.config(state="disabled")
            self.lbl_cierre_dif_msg.config(text="Sin turno activo", fg=self.c_text_muted)
            self.lbl_banco_dif_msg.config(text="Sin turno activo", fg=self.c_text_muted)
            self.btn_ejecutar_cierre.config(state="disabled", bg="#9CA3AF", cursor="arrow")

        # Cargar historial
        self.tree_hist_cierres.delete(*self.tree_hist_cierres.get_children())
        conn = conectar_db()
        if conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(sesiones_caja)")
            cols = [c[1] for c in cur.fetchall()]
            col_u = "usuario" if "usuario" in cols else ("usuario_apertura" if "usuario_apertura" in cols else "''")
            col_esp = "monto_esperado_efectivo" if "monto_esperado_efectivo" in cols else ("monto_esperado" if "monto_esperado" in cols else "0.0")
            col_real = "monto_real_contado" if "monto_real_contado" in cols else ("monto_real_efectivo" if "monto_real_efectivo" in cols else ("monto_cierre" if "monto_cierre" in cols else "0.0"))
            col_dif_banco = "diferencia_banco" if "diferencia_banco" in cols else "0.0"

            cur.execute(f"""
                SELECT 
                    id, {col_u} as responsable, fecha_apertura, fecha_cierre, monto_inicial,
                    COALESCE({col_esp}, 0.0) as esp_ef,
                    COALESCE({col_real}, 0.0) as real_ef,
                    COALESCE(diferencia, 0.0) as dif_ef,
                    COALESCE({col_dif_banco}, 0.0) as dif_bc,
                    COALESCE(estado, 'CERRADA') as estado
                FROM sesiones_caja
                WHERE fecha_cierre IS NOT NULL
                ORDER BY id DESC LIMIT 15
            """)
            for r in cur.fetchall():
                self.tree_hist_cierres.insert("", "end", values=(
                    r["id"], r["responsable"], r["fecha_apertura"] or "-", r["fecha_cierre"] or "-",
                    f"${float(r['monto_inicial'] or 0.0):,.0f}",
                    f"${float(r['esp_ef'] or 0.0):,.0f}",
                    f"${float(r['real_ef'] or 0.0):,.0f}",
                    f"${float(r['dif_ef'] or 0.0):,.0f}",
                    f"${float(r['dif_bc'] or 0.0):,.0f}",
                    r["estado"]
                ))
            conn.close()

    def _ejecutar_cierre_caja(self):
        if not getattr(self, "sesion_activa_id", None):
            messagebox.showwarning("Sin Sesión", "No hay ninguna sesión de caja abierta para cerrar.")
            return

        real_ef = float(self.entry_efectivo_contado.get_value())
        verif_bc = float(self.entry_banco_verificado.get_value())
        dif_ef = real_ef - self.monto_esperado_efectivo_act
        dif_bc = verif_bc - self.monto_transf_esperado_act

        msg = f"¿Confirmas el CIERRE DEFINITIVO de la Sesión #{self.sesion_activa_id}?\n\n"
        msg += f"• Efectivo Contado: ${real_ef:,.0f} (Diferencia: ${dif_ef:,.0f})\n"
        msg += f"• Bancos Verificado: ${verif_bc:,.0f} (Diferencia: ${dif_bc:,.0f})\n\n"
        msg += "Esta acción finalizará el turno y guardará el registro inmutable."

        if messagebox.askyesno("Confirmar Cierre de Caja", msg):
            try:
                obs = self.entry_cierre_obs.get().strip() or f"Cierre contable. Dif Efectivo: ${dif_ef:,.0f}, Dif Bancos: ${dif_bc:,.0f}"
                res = cerrar_sesion_caja(
                    sesion_id=self.sesion_activa_id,
                    monto_real_contado=real_ef,
                    monto_real_efectivo=real_ef,
                    observaciones=obs,
                    monto_transferencias_verificado=verif_bc
                )

                messagebox.showinfo("Cierre Exitoso", f"Sesión #{self.sesion_activa_id} cerrada con éxito.\n\nEfectivo contado: ${real_ef:,.0f}\nDiferencia: ${dif_ef:,.0f}")
                self.actualizar_todo()
            except Exception as e:
                messagebox.showerror("Error", f"Error al ejecutar el cierre: {e}")

    # --------------------------------------------------------------------------
    # ACTUALIZACIÓN INTEGRAL DE DATOS
    # --------------------------------------------------------------------------
    def actualizar_todo(self):
        self.metricas_actuales = calcular_metricas_contables(self.fecha_ini, self.fecha_fin)
        if not self.metricas_actuales:
            return

        kpis = self.metricas_actuales.get("kpis", {})
        rv = self.metricas_actuales.get("resumen_ventas", {})
        cf = self.metricas_actuales.get("caja_fisica", {})

        # 1. Actualizar las 4 tarjetas principales
        v_net = kpis.get("A_ventas_netas", 0.0)
        c_vent = kpis.get("B_costo_ventas", 0.0)
        g_tot = kpis.get("D_gastos_operativos", 0.0)
        g_net = kpis.get("E_utilidad_operacional_neta", 0.0)
        m_net_pct = kpis.get("F_margen_neto_pct", 0.0)

        self.card_labels["ventas_netas"][0].config(text=f"${v_net:,.0f}")
        self.card_labels["costo_ventas"][0].config(text=f"${c_vent:,.0f}")
        self.card_labels["gastos_total"][0].config(text=f"${g_tot:,.0f}")
        
        # Ganancia neta: verde si positivo, rojo si pérdida
        col_ganancia = self.c_green if g_net >= 0 else self.c_red
        self.card_labels["ganancia_neta"][0].config(text=f"${g_net:,.0f}", fg=col_ganancia)
        self.card_labels["ganancia_neta"][1].config(text=f"Margen neto: {m_net_pct:.1f}% sobre ventas")

        # 2. Indicador secundario de Cartera (Fiados) y Valor del Inventario
        cartera_total = kpis.get("H_cuentas_por_cobrar", 0.0)
        self.lbl_cartera_banner.config(text=f"${cartera_total:,.0f}")

        val_inv = self.metricas_actuales.get("valor_inventario", kpis.get("J_valor_inventario", 0.0))
        self.lbl_inventario_banner.config(text=f"${val_inv:,.0f}")

        # 3. Sección "¿Cómo se movió el dinero?"
        ef_ventas = rv.get("efectivo", 0.0)
        ef_abonos = cf.get("abonos_cartera", 0.0)
        ef_recibido_total = ef_ventas + ef_abonos

        tr_total = rv.get("transferencia", 0.0)
        fi_total = rv.get("fiado", 0.0)

        self.lbl_efectivo_total.config(text=f"${ef_recibido_total:,.0f}")
        self.lbl_efectivo_desglose.config(text=f"Ventas efectivo: ${ef_ventas:,.0f} | Abonos cartera: ${ef_abonos:,.0f}")

        self.lbl_transf_total.config(text=f"${tr_total:,.0f}")
        self.lbl_transf_desglose.config(text=f"{rv.get('pct_transferencia', 0.0):.1f}% de las ventas del período")

        self.lbl_fiados_total.config(text=f"${fi_total:,.0f}")
        self.lbl_fiados_desglose.config(text=f"{rv.get('pct_fiado', 0.0):.1f}% de las ventas otorgadas a fiado")

        # Tabla de Estado de Resultados Compacta
        ub = kpis.get("C_utilidad_bruta", 0.0)
        self.lbl_estado_res_rows["ventas"][0].config(text=f"${v_net:,.0f}")
        self.lbl_estado_res_rows["ventas"][1].config(text="100.0%")

        pct_c = (c_vent / v_net * 100.0) if v_net > 0 else 0.0
        self.lbl_estado_res_rows["costos"][0].config(text=f"-${c_vent:,.0f}")
        self.lbl_estado_res_rows["costos"][1].config(text=f"{pct_c:.1f}%")

        pct_ub = (ub / v_net * 100.0) if v_net > 0 else 0.0
        self.lbl_estado_res_rows["utilidad_bruta"][0].config(text=f"+${ub:,.0f}")
        self.lbl_estado_res_rows["utilidad_bruta"][1].config(text=f"{pct_ub:.1f}%")

        pct_g = (g_tot / v_net * 100.0) if v_net > 0 else 0.0
        self.lbl_estado_res_rows["gastos"][0].config(text=f"-${g_tot:,.0f}")
        self.lbl_estado_res_rows["gastos"][1].config(text=f"{pct_g:.1f}%")

        if "nomina" in self.lbl_estado_res_rows:
            nom_info = self.metricas_actuales.get("nomina") or {}
            g_nom = float(self.metricas_actuales.get("comisiones_nomina") or nom_info.get("gasto_personal_devengado") or 0.0)
            pag_nom = float(nom_info.get("pagos_nomina_realizados") or 0.0)
            pend_nom = float(nom_info.get("obligaciones_pendientes") or 0.0)
            pct_n = (g_nom / v_net * 100.0) if v_net > 0 else 0.0
            self.lbl_estado_res_rows["nomina"][0].config(text=f"-${g_nom:,.0f}")
            self.lbl_estado_res_rows["nomina"][1].config(
                text=f"Pagado: ${pag_nom:,.0f} | Pendiente: ${pend_nom:,.0f} ({pct_n:.1f}%)"
            )

        sgn = "+" if g_net >= 0 else "-"
        self.lbl_estado_res_rows["ganancia_neta"][0].config(text=f"{sgn}${abs(g_net):,.0f}", fg=col_ganancia)
        self.lbl_estado_res_rows["ganancia_neta"][1].config(text=f"{m_net_pct:.1f}%")

        # 4. Dibujar las dos gráficas principales
        self._dibujar_graficas()

        # 5. Cargar tablas de Registros e Informes
        self.tree_22.delete(*self.tree_22.get_children())
        for c in self.metricas_actuales.get("conceptos_22", []):
            val_txt = f"${c['valor']:,.0f}" if isinstance(c['valor'], (int, float)) and c['tipo'] != 'Porcentaje' else (f"{c['valor']:.1f}%" if c['tipo'] == 'Porcentaje' else str(c['valor']))
            self.tree_22.insert("", "end", values=(c["numero"], c["codigo"], c["concepto"], val_txt, c["tipo"], c["descripcion"]))

        self.tree_op.delete(*self.tree_op.get_children())
        for op in self.metricas_actuales.get("operarios", []):
            tp = (op["total_vendido"] / op["cant_ventas"]) if op["cant_ventas"] > 0 else 0.0
            self.tree_op.insert("", "end", values=(
                op["operario"], f"${op['total_vendido']:,.0f}", op["cant_ventas"],
                f"${tp:,.0f}", f"${op['efectivo']:,.0f}", f"${op['transferencia']:,.0f}", f"${op['fiado']:,.0f}"
            ))

        self.tree_prod.delete(*self.tree_prod.get_children())
        for p in self.metricas_actuales.get("top_productos", []):
            self.tree_prod.insert("", "end", values=(
                p["codigo"], p["nombre"], p["unidades"], f"${p['facturado']:,.0f}",
                f"${p['costo']:,.0f}", f"${p['ganancia']:,.0f}", f"{p['margen_pct']:.1f}%"
            ))

        self.tree_cli.delete(*self.tree_cli.get_children())
        for cl in self.metricas_actuales.get("top_deudores", []):
            self.tree_cli.insert("", "end", values=(
                cl.get("cedula", ""), cl.get("nombre", ""), cl.get("telefono", "") or "-", f"${float(cl.get('saldo_pendiente',0.0)):,.0f}"
            ))

        # 6. Cierre de caja
        self._cargar_datos_cierre()

    # --------------------------------------------------------------------------
    # EXPORTACIÓN
    # --------------------------------------------------------------------------
    def _exportar_excel(self):
        if not self.metricas_actuales:
            return
        nombre_safe = "".join(c for c in business_mgr.nombre if c.isalnum() or c in (' ', '_')).strip().replace(' ', '_')
        def_file = f"Contabilidad_{nombre_safe}_{self.fecha_ini}_al_{self.fecha_fin}.xls"
        
        ruta = filedialog.asksaveasfilename(
            parent=self.root,
            title="Guardar Cierre Contable en Excel",
            initialfile=def_file,
            filetypes=[("Libro de Excel (*.xls / *.xlsx)", "*.xls *.xlsx"), ("Todos los archivos", "*.*")]
        )
        if not ruta:
            return

        if exportar_excel_financiero(self.metricas_actuales, ruta):
            if messagebox.askyesno("Exportación Exitosa", f"Informe contable guardado exitosamente:\n\n{ruta}\n\n¿Deseas abrir el archivo ahora?"):
                try:
                    os.system(f'open "{ruta}"' if sys.platform == "darwin" else f'start "" "{ruta}"')
                except Exception:
                    pass
        else:
            messagebox.showerror("Error", "No se pudo generar el archivo de Excel.")

    def _exportar_pdf(self):
        if not self.metricas_actuales:
            return
        nombre_safe = "".join(c for c in business_mgr.nombre if c.isalnum() or c in (' ', '_')).strip().replace(' ', '_')
        def_file = f"Informe_Financiero_{nombre_safe}_{self.fecha_ini}_al_{self.fecha_fin}.html"
        
        ruta = filedialog.asksaveasfilename(
            parent=self.root,
            title="Guardar Informe Financiero Imprimible",
            initialfile=def_file,
            filetypes=[("Documento HTML Imprimible / PDF (*.html)", "*.html"), ("Todos los archivos", "*.*")]
        )
        if not ruta:
            return

        if exportar_informe_html_pdf(self.metricas_actuales, ruta):
            if messagebox.askyesno("Exportación Exitosa", f"Informe generado exitosamente en:\n\n{ruta}\n\n¿Deseas abrirlo en el navegador para imprimir o guardar como PDF?"):
                try:
                    webbrowser.open(f"file://{os.path.abspath(ruta)}")
                except Exception:
                    pass
        else:
            messagebox.showerror("Error", "No se pudo generar el informe.")


def iniciar_contabilidad(parent_pid=""):
    try:
        procesar_gastos_recurrentes()
    except Exception:
        pass
    root = tk.Tk()
    parent_pid = parent_pid or os.environ.get("VMPOS_PARENT_PID", "")
    app = ContabilidadApp(root, parent_pid=parent_pid)
    root.mainloop()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Contabilidad y Finanzas VmPOS")
    parser.add_argument("--parent_pid", default="")
    if "-h" in sys.argv or "--help" in sys.argv:
        parser.print_help()
        sys.exit(0)
    args, _ = parser.parse_known_args()
    parent_pid = args.parent_pid or os.environ.get("VMPOS_PARENT_PID", "")
    iniciar_contabilidad(parent_pid=parent_pid)
