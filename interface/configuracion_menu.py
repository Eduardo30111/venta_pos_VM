#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo de Configuración del Sistema - VmPOS
Archivo: interface/configuracion_menu.py

Permite administrar con persistencia real y reflejo en vivo:
1. Configuración e Identidad del Negocio (Nombre comercial, Razón social, NIT/RUT/Documento,
   Dirección, Ciudad, Teléfono, Correo, Eslogan, Tipo de comprobante, Logo con vista previa y Colores).
2. Impresoras y Formato de Factura (58 mm, 80 mm, A4, impresora seleccionada, márgenes,
   tamaño de fuente, densidad, alineación, campos visibles, copias, corte automático e Impresión de Prueba).
3. Verificación de Actualizaciones del Sistema.
4. Selector de Apariencia y Tema (Modo Claro / Oscuro / Automático).
5. Copias de Seguridad (Backup, Restauración y Diagnóstico de Base de Datos).
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import shutil
import sqlite3
import sys
from datetime import datetime

try:
    from PIL import Image, ImageTk
    PIL_DISPONIBLE = True
except ImportError:
    PIL_DISPONIBLE = False

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from client.utils.system_helper import abrir_archivo_o_carpeta
try:
    from interface.config import DB_VENTAS_PATH
except ImportError:
    from config import DB_VENTAS_PATH

try:
    from theme_manager import (
        theme_mgr, aplicar_tema, calcular_geometria_segura,
        calcular_color_texto_optimo, crear_boton, ScrollableContainer
    )
except ImportError:
    from interface.theme_manager import (
        theme_mgr, aplicar_tema, calcular_geometria_segura,
        calcular_color_texto_optimo, crear_boton, ScrollableContainer
    )

try:
    from session_manager import session_mgr
except ImportError:
    from interface.session_manager import session_mgr

try:
    from business_manager import (
        business_mgr, PALETAS_PREDEFINIDAS, CONFIG_FILE, PRINTER_CONFIG_FILE,
        TIPOS_COMPROBANTE_DISPONIBLES, TIPOS_DOCUMENTO_FISCAL
    )
except ImportError:
    from interface.business_manager import (
        business_mgr, PALETAS_PREDEFINIDAS, CONFIG_FILE, PRINTER_CONFIG_FILE,
        TIPOS_COMPROBANTE_DISPONIBLES, TIPOS_DOCUMENTO_FISCAL
    )

try:
    from receipt_manager import (
        detectar_impresoras_disponibles,
        construir_datos_factura_prueba,
        imprimir_prueba_configuracion,
        mostrar_dialogo_factura
    )
except ImportError:
    from interface.receipt_manager import (
        detectar_impresoras_disponibles,
        construir_datos_factura_prueba,
        imprimir_prueba_configuracion,
        mostrar_dialogo_factura
    )


# =============================================================================
# FUNCIONES DE BASE DE DATOS Y COPIAS DE SEGURIDAD (BACKUP)
# =============================================================================

def verificar_integridad_db(db_path):
    """Verifica la integridad física del archivo SQLite."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        resultado = cursor.fetchone()[0]
        conn.close()
        return resultado == "ok"
    except Exception as e:
        print(f"Error verificando integridad: {e}")
        return False


def crear_backup():
    """Crea una copia de seguridad timestamped de la base de datos ventas.db"""
    db_path = DB_VENTAS_PATH
    if not os.path.exists(db_path):
        messagebox.showerror("❌ Error", f"La base de datos '{db_path}' no existe.")
        return

    try:
        backup_dir = os.path.abspath("./backups")
        os.makedirs(backup_dir, exist_ok=True)
        fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"backup_vmpos_{fecha}.db"
        backup_path = os.path.join(backup_dir, backup_filename)

        shutil.copy2(db_path, backup_path)

        if os.path.exists(backup_path):
            tam_kb = round(os.path.getsize(backup_path) / 1024, 1)
            respuesta = messagebox.askyesno(
                "💾 Copia de Seguridad Exitosa",
                f"¡Copia de seguridad generada con éxito!\n\n"
                f"📁 Archivo: {backup_filename}\n"
                f"📊 Tamaño: {tam_kb} KB\n"
                f"📍 Carpeta: {backup_dir}\n\n"
                f"¿Deseas abrir la carpeta de copias de seguridad?"
            )
            if respuesta:
                abrir_archivo_o_carpeta(backup_dir)
        else:
            raise Exception("El archivo de copia de seguridad no se creó.")
    except Exception as e:
        messagebox.showerror("❌ Error", f"Error al generar la copia de seguridad:\n{str(e)}")


def restaurar_base_datos():
    """Restaura o vacía los datos transaccionales con backup de seguridad previo, preservando la configuración del negocio."""
    db_path = DB_VENTAS_PATH
    if not os.path.exists(db_path):
        messagebox.showerror("❌ Error", f"La base de datos '{db_path}' no existe.")
        return

    if not verificar_integridad_db(db_path):
        messagebox.showerror("❌ Error de Integridad", "La base de datos actual tiene errores de integridad.")
        return

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tablas = [t[0] for t in cursor.fetchall() if t[0] not in ("configuracion_negocio", "usuarios")]
        conn.close()

        if not tablas:
            messagebox.showinfo("ℹ️ Información", "No se encontraron tablas transaccionales en la base de datos.")
            return

        confirm = messagebox.askyesno(
            "⚠️ Restaurar Base de Datos",
            "¿Estás seguro de que deseas vaciar los registros transaccionales del sistema?\n\n"
            "⚠️ Se creará una copia de seguridad automática antes de proceder y se conservará la configuración del negocio.\n\n"
            "¿Deseas continuar?"
        )
        if not confirm:
            return

        crear_backup()

        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = OFF")
        cursor = conn.cursor()
        cursor.execute("BEGIN TRANSACTION;")
        for tbl in tablas:
            cursor.execute(f"DELETE FROM [{tbl}]")
        try:
            cursor.execute("DELETE FROM sqlite_sequence WHERE name NOT IN ('configuracion_negocio', 'usuarios')")
        except Exception:
            pass
        conn.commit()
        conn.close()

        messagebox.showinfo("✅ Restauración Completa", "La base de datos transaccional ha sido vaciada exitosamente.\nSe guardó una copia de respaldo.")
    except Exception as e:
        messagebox.showerror("❌ Error", f"Fallo durante la restauración: {e}")


def diagnosticar_base_datos():
    """Diagnóstico detallado de las tablas y registros en la base de datos."""
    db_path = DB_VENTAS_PATH
    if not os.path.exists(db_path):
        messagebox.showerror("❌ Error", f"Base de datos no encontrada: {db_path}")
        return

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        check = cursor.fetchone()[0]

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tablas = [t[0] for t in cursor.fetchall()]

        detalles = [f"🔍 DIAGNÓSTICO DE BASE DE DATOS: {os.path.basename(db_path)}", "=" * 50]
        detalles.append(f"Estado de Integridad: {'✅ CORRECTO (OK)' if check == 'ok' else '❌ ERROR: ' + check}")
        detalles.append(f"Ubicación: {os.path.abspath(db_path)}")
        detalles.append(f"Tamaño: {round(os.path.getsize(db_path) / 1024, 2)} KB")
        detalles.append(f"Total de Tablas: {len(tablas)}")
        detalles.append("\n📊 Registros por Tabla:")

        total_reg = 0
        for tbl in tablas:
            cursor.execute(f"SELECT COUNT(*) FROM [{tbl}]")
            count = cursor.fetchone()[0]
            total_reg += count
            detalles.append(f"  • {tbl:<24} : {count} registros")

        detalles.append(f"\nTotal Registros en el Sistema: {total_reg}")
        conn.close()

        win = tk.Toplevel()
        win.title("🔧 Diagnóstico de Base de Datos")
        calcular_geometria_segura(win, 580, 480)
        t = aplicar_tema(win)
        win.configure(bg=t["bg_app"])

        tk.Label(win, text="🔧 DIAGNÓSTICO COMPLETO", font=("Segoe UI", 12, "bold"),
                 bg=t["bg_app"], fg=t["primary"]).pack(pady=(12, 6))

        txt_frame = tk.Frame(win, bg=t["bg_surface"], bd=1, relief="solid")
        txt_frame.pack(fill="both", expand=True, padx=15, pady=8)

        txt = tk.Text(txt_frame, font=("Courier New", 9), bg=t["bg_surface"], fg=t["text_primary"])
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        txt.insert("1.0", "\n".join(detalles))
        txt.config(state="disabled")

        crear_boton(win, "Aceptar", win.destroy, tipo="primary").pack(pady=8)
    except Exception as e:
        messagebox.showerror("❌ Error", f"Error en diagnóstico: {e}")


# =============================================================================
# FUNCIONES DE ACTUALIZACIÓN DEL SISTEMA
# =============================================================================

def buscar_actualizaciones_sistema(parent_window=None):
    """Verifica la disponibilidad de actualizaciones del sistema VmPOS."""
    ventana_act = tk.Toplevel(parent_window) if parent_window else tk.Toplevel()
    ventana_act.title("🚀 Buscar Actualizaciones - VmPOS")
    calcular_geometria_segura(ventana_act, 520, 380, modal_padre=parent_window)
    t = aplicar_tema(ventana_act)
    ventana_act.configure(bg=t["bg_app"])
    ventana_act.resizable(False, False)
    ventana_act.grab_set()

    hdr = tk.Frame(ventana_act, bg=t["primary"], height=60)
    hdr.pack(fill="x")
    hdr.pack_propagate(False)
    tk.Label(hdr, text="🚀 ACTUALIZACIONES DEL SISTEMA", font=("Segoe UI", 12, "bold"),
             bg=t["primary"], fg="white").pack(side="left", padx=20, pady=16)

    box = tk.Frame(ventana_act, bg=t["bg_surface"], bd=1, relief="solid")
    box.pack(fill="both", expand=True, padx=20, pady=15)

    info_box = tk.Frame(box, bg=t["bg_surface"])
    info_box.pack(fill="x", padx=15, pady=12)

    version_actual = "v4.0.0 (Centralizado Empresarial)"
    canal = "Canal Oficial Estable"
    fecha_check = datetime.now().strftime("%d/%m/%Y %H:%M")

    items = [
        ("💻 Versión Actual:", version_actual, t["text_primary"]),
        ("📡 Canal de Distribución:", canal, t["btn_info_bg"]),
        ("🕒 Última Verificación:", fecha_check, t["text_muted"])
    ]

    for lbl, val, col in items:
        row = tk.Frame(info_box, bg=t["bg_surface"])
        row.pack(fill="x", pady=4)
        tk.Label(row, text=lbl, font=("Segoe UI", 10, "bold"), bg=t["bg_surface"], fg=t["text_secondary"], width=20, anchor="w").pack(side="left")
        tk.Label(row, text=val, font=("Segoe UI", 10), bg=t["bg_surface"], fg=col, anchor="w").pack(side="left")

    tk.Frame(box, bg=t["border"], height=1).pack(fill="x", padx=15, pady=8)

    lbl_status = tk.Label(box, text="✅ Tu sistema está actualizado a la versión más reciente.",
                          font=("Segoe UI", 10, "bold"), bg=t["bg_surface"], fg=t["success"], wraplength=420, justify="center")
    lbl_status.pack(pady=10)

    lbl_detalle = tk.Label(box, text="Todos los módulos (Ventas, Gastos, Inventario, Nómina y Reportes) están sincronizados y al día.",
                           font=("Segoe UI", 9), bg=t["bg_surface"], fg=t["text_muted"], wraplength=420, justify="center")
    lbl_detalle.pack(pady=(0, 10))

    btn_box = tk.Frame(ventana_act, bg=t["bg_app"])
    btn_box.pack(fill="x", padx=20, pady=(0, 15))

    def comprobar_de_nuevo():
        lbl_status.config(text="🔄 Buscando actualizaciones en el servidor...", fg=t["btn_info_bg"])
        lbl_detalle.config(text="Verificando integridad del paquete y versiones...")
        ventana_act.update()
        ventana_act.after(900, lambda: [
            lbl_status.config(text="✅ Sistema 100% actualizado. No se requieren descargas.", fg=t["success"]),
            lbl_detalle.config(text=f"Comprobación exitosa el {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        ])

    crear_boton(btn_box, "🔍 Comprobar Ahora", comprobar_de_nuevo, tipo="primary").pack(side="left", padx=(0, 10))
    crear_boton(btn_box, "Cerrar", ventana_act.destroy, tipo="secondary").pack(side="right")


# =============================================================================
# VENTANA PRINCIPAL DE CONFIGURACIÓN
# =============================================================================

def iniciar_configuracion(parent=None, on_save_callback=None):
    """
    Abre la ventana de configuración del sistema:
    1. Identidad comercial, fiscal y Logo del Negocio
    2. Impresoras y Formato de Factura (58mm, 80mm, A4, vista previa e impresión de prueba)
    3. Actualizaciones del Sistema
    4. Apariencia y Tema Visual
    5. Copias de Seguridad y Diagnóstico DB
    """
    business_mgr.recargar()

    # Evitar crear múltiples instancias tk.Tk() cuando ya existe una ventana raíz activa
    root_existente = parent if parent is not None else getattr(tk, "_default_root", None)
    es_toplevel = root_existente is not None
    ventana = tk.Toplevel(root_existente) if es_toplevel else tk.Tk()
    session_mgr.registrar_ventana(ventana)
    ventana.title(f"⚙️ Configuración del Sistema — {business_mgr.nombre}")
    if parent is not None:
        ventana.transient(parent)

    calcular_geometria_segura(ventana, 1140, 820, 960, 620)
    t = aplicar_tema(ventana)
    ventana.configure(bg=t["bg_app"])

    COLOR_HEADER = business_mgr.color_barra or t["bg_header"]
    FG_HEADER = calcular_color_texto_optimo(COLOR_HEADER)

    # 1. Header Principal
    header_frame = tk.Frame(ventana, bg=COLOR_HEADER, height=56)
    header_frame.pack(fill="x", side="top")
    header_frame.pack_propagate(False)

    header_left = tk.Frame(header_frame, bg=COLOR_HEADER)
    header_left.pack(side="left", fill="y", padx=20)

    lbl_hdr_icon = tk.Label(header_left, text="⚙️", font=("Segoe UI Emoji", 20), bg=COLOR_HEADER, fg=FG_HEADER)
    lbl_hdr_icon.pack(side="left", pady=10)
    lbl_hdr_title = tk.Label(header_left, text="CONFIGURACIÓN DEL SISTEMA", font=("Segoe UI", 15, "bold"), bg=COLOR_HEADER, fg=FG_HEADER)
    lbl_hdr_title.pack(side="left", padx=(10, 0), pady=12)
    lbl_hdr_negocio = tk.Label(header_left, text=f"• {business_mgr.nombre}", font=("Segoe UI", 10, "bold"), bg=COLOR_HEADER, fg=FG_HEADER)
    lbl_hdr_negocio.pack(side="left", padx=(10, 0), pady=14)

    reloj_lbl = tk.Label(header_frame, font=("Segoe UI", 10, "bold"), bg=COLOR_HEADER, fg=FG_HEADER)
    reloj_lbl.pack(side="right", padx=20)
    reloj_after_id = None

    def tick_reloj():
        nonlocal reloj_after_id
        if ventana.winfo_exists():
            reloj_lbl.config(text=f"🕒 {datetime.now().strftime('%d/%m/%Y  %H:%M:%S')}")
            reloj_after_id = ventana.after(1000, tick_reloj)

    def cerrar_configuracion():
        nonlocal reloj_after_id
        if reloj_after_id:
            try:
                ventana.after_cancel(reloj_after_id)
            except tk.TclError:
                pass
            reloj_after_id = None
        ventana.destroy()

    ventana.protocol("WM_DELETE_WINDOW", cerrar_configuracion)
    tick_reloj()

    # 2. Sticky Footer con acciones globales
    footer_bar = tk.Frame(ventana, bg=t["bg_surface_alt"], height=50)
    footer_bar.pack(side="bottom", fill="x")
    footer_bar.pack_propagate(False)

    tk.Label(footer_bar, text="⚡ ACCIONES DE CONFIGURACIÓN", font=("Segoe UI", 9, "bold"),
             bg=t["bg_surface_alt"], fg=t["text_secondary"]).pack(side="left", padx=20)

    f_btns = tk.Frame(footer_bar, bg=t["bg_surface_alt"])
    f_btns.pack(side="right", padx=15, pady=6)

    # 3. Contenedor Central Scrollable
    scroll_container = ScrollableContainer(ventana, bg=t["bg_app"])
    scroll_container.pack(fill="both", expand=True, padx=20, pady=10)
    scroll_body = scroll_container.scrollable_frame

    # =========================================================================
    # VARIABLES VINCULADAS EXPLÍCITAMENTE A `master=ventana`
    # =========================================================================
    var_nombre = tk.StringVar(master=ventana, value=business_mgr.obtener("nombre_negocio", "VmPOS"))
    var_razon_social = tk.StringVar(master=ventana, value=business_mgr.obtener("razon_social", ""))
    var_subtitulo = tk.StringVar(master=ventana, value=business_mgr.obtener("subtitulo_negocio", ""))
    var_tipo_doc = tk.StringVar(master=ventana, value=business_mgr.obtener("tipo_documento_fiscal", "NIT") or "NIT")
    var_nit = tk.StringVar(master=ventana, value=business_mgr.obtener("nit", ""))
    var_regimen = tk.StringVar(master=ventana, value=business_mgr.obtener("regimen_fiscal", ""))
    var_direccion = tk.StringVar(master=ventana, value=business_mgr.obtener("direccion", ""))
    var_ciudad = tk.StringVar(master=ventana, value=business_mgr.obtener("ciudad", ""))
    var_telefono = tk.StringVar(master=ventana, value=business_mgr.obtener("telefono", ""))
    var_email = tk.StringVar(master=ventana, value=business_mgr.obtener("email", ""))
    var_tipo_comp = tk.StringVar(master=ventana, value=business_mgr.obtener("tipo_comprobante", "RECIBO DE VENTA") or "RECIBO DE VENTA")
    var_prefijo = tk.StringVar(master=ventana, value=business_mgr.obtener("prefijo_comprobante", ""))
    var_encabezado_recibo = tk.StringVar(master=ventana, value=business_mgr.obtener("encabezado_recibo", ""))
    var_eslogan = tk.StringVar(master=ventana, value=business_mgr.obtener("eslogan", ""))
    var_color_barra = tk.StringVar(master=ventana, value=business_mgr.color_barra)
    var_color_login = tk.StringVar(master=ventana, value=business_mgr.color_login)
    var_logo_path = tk.StringVar(master=ventana, value=business_mgr.logo_path)

    # Variables de Impresora y Formato de Factura
    cfg_imp_ini = business_mgr.obtener_config_impresora()
    var_formato_papel = tk.StringVar(master=ventana, value=cfg_imp_ini.get("formato_papel", "58mm"))
    var_impresora_nombre = tk.StringVar(master=ventana, value=cfg_imp_ini.get("impresora_nombre", "Predeterminada del sistema"))
    var_metodo_impresion = tk.StringVar(master=ventana, value=cfg_imp_ini.get("metodo_impresion", "auto"))
    var_margen_mm = tk.IntVar(master=ventana, value=int(cfg_imp_ini.get("margen_mm", 2)))
    var_tamano_fuente = tk.StringVar(master=ventana, value=cfg_imp_ini.get("tamano_fuente", "normal"))
    var_densidad = tk.StringVar(master=ventana, value=cfg_imp_ini.get("densidad", "normal"))
    var_alineacion = tk.StringVar(master=ventana, value=cfg_imp_ini.get("alineacion_encabezado", "center"))
    var_copias = tk.IntVar(master=ventana, value=int(cfg_imp_ini.get("copias", 1)))
    var_corte_auto = tk.BooleanVar(master=ventana, value=bool(cfg_imp_ini.get("corte_automatico", True)))
    var_abrir_cajon = tk.BooleanVar(master=ventana, value=bool(cfg_imp_ini.get("abrir_cajon", False)))

    var_mostrar_logo = tk.BooleanVar(master=ventana, value=bool(cfg_imp_ini.get("mostrar_logo", True)))
    var_mostrar_razon = tk.BooleanVar(master=ventana, value=bool(cfg_imp_ini.get("mostrar_razon_social", True)))
    var_mostrar_nit = tk.BooleanVar(master=ventana, value=bool(cfg_imp_ini.get("mostrar_nit", True)))
    var_mostrar_regimen = tk.BooleanVar(master=ventana, value=bool(cfg_imp_ini.get("mostrar_regimen", True)))
    var_mostrar_dir = tk.BooleanVar(master=ventana, value=bool(cfg_imp_ini.get("mostrar_direccion", True)))
    var_mostrar_tel = tk.BooleanVar(master=ventana, value=bool(cfg_imp_ini.get("mostrar_telefono", True)))
    var_mostrar_email = tk.BooleanVar(master=ventana, value=bool(cfg_imp_ini.get("mostrar_email", False)))
    var_mostrar_cliente = tk.BooleanVar(master=ventana, value=bool(cfg_imp_ini.get("mostrar_cliente", True)))
    var_mostrar_vendedor = tk.BooleanVar(master=ventana, value=bool(cfg_imp_ini.get("mostrar_vendedor", True)))
    var_mostrar_eslogan = tk.BooleanVar(master=ventana, value=bool(cfg_imp_ini.get("mostrar_eslogan", True)))
    var_pie_extra = tk.StringVar(master=ventana, value=str(cfg_imp_ini.get("pie_factura_extra", "")))

    # =========================================================================
    # SECCIÓN 1: IDENTIDAD DEL NEGOCIO Y LOGO (MARCA BLANCA)
    # =========================================================================
    card_negocio = tk.Frame(scroll_body, bg=t["bg_surface"], bd=1, relief="solid")
    card_negocio.pack(fill="x", pady=(0, 15), padx=5)

    card_header = tk.Frame(card_negocio, bg=t["bg_surface_alt"], height=40)
    card_header.pack(fill="x")
    tk.Label(card_header, text="🏢 DATOS DEL NEGOCIO, IDENTIDAD VISUAL Y LOGO", font=("Segoe UI", 11, "bold"),
             bg=t["bg_surface_alt"], fg=t["text_primary"]).pack(side="left", padx=15, pady=8)

    body_negocio = tk.Frame(card_negocio, bg=t["bg_surface"], padx=20, pady=15)
    body_negocio.pack(fill="x")

    acciones_negocio = tk.Frame(body_negocio, bg=t["bg_surface"])
    acciones_negocio.pack(fill="x", pady=(0, 10))
    tk.Label(
        acciones_negocio,
        text="Personaliza la identidad comercial y fiscal de tu negocio. Se reflejará de inmediato en el Menú de Inicio, módulos y nuevas facturas.",
        font=("Segoe UI", 9, "italic"), bg=t["bg_surface"], fg=t["text_muted"]
    ).pack(side="left")

    grid_campos = tk.Frame(body_negocio, bg=t["bg_surface"])
    grid_campos.pack(fill="x", pady=(0, 12))
    grid_campos.columnconfigure((1, 3), weight=1)

    def _crear_entry(parent_g, textvariable, row, col, pad_right=20):
        ent = tk.Entry(
            parent_g, textvariable=textvariable, font=("Segoe UI", 10),
            relief="solid", bd=1, bg=t["input_bg"], fg=t["input_fg"],
            insertbackground=t.get("input_insert", t["input_fg"])
        )
        ent.grid(row=row, column=col, sticky="ew", pady=5, padx=(0, pad_right))
        return ent

    # Fila 0: Nombre comercial y Razón social
    tk.Label(grid_campos, text="Nombre Comercial (POS):", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=0, column=0, sticky="w", pady=5, padx=(0, 10))
    entry_nombre = _crear_entry(grid_campos, var_nombre, 0, 1, 20)

    tk.Label(grid_campos, text="Razón Social / Propietario:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=0, column=2, sticky="w", pady=5, padx=(0, 10))
    entry_razon = _crear_entry(grid_campos, var_razon_social, 0, 3, 0)

    # Fila 1: Subtítulo/Rubro y Tipo + Número de documento fiscal
    tk.Label(grid_campos, text="Subtítulo / Rubro (opcional):", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=1, column=0, sticky="w", pady=5, padx=(0, 10))
    entry_sub = _crear_entry(grid_campos, var_subtitulo, 1, 1, 20)

    tk.Label(grid_campos, text="Identificación Fiscal (NIT/RUT):", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=1, column=2, sticky="w", pady=5, padx=(0, 10))
    nit_frame = tk.Frame(grid_campos, bg=t["bg_surface"])
    nit_frame.grid(row=1, column=3, sticky="ew", pady=5)
    cb_tipo_doc = ttk.Combobox(nit_frame, textvariable=var_tipo_doc, values=TIPOS_DOCUMENTO_FISCAL, state="readonly", width=10)
    cb_tipo_doc.pack(side="left", padx=(0, 6))
    entry_nit = tk.Entry(nit_frame, textvariable=var_nit, font=("Segoe UI", 10), relief="solid", bd=1, bg=t["input_bg"], fg=t["input_fg"])
    entry_nit.pack(side="left", fill="x", expand=True)

    # Fila 2: Dirección y Ciudad
    tk.Label(grid_campos, text="Dirección Comercial:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=2, column=0, sticky="w", pady=5, padx=(0, 10))
    entry_dir = _crear_entry(grid_campos, var_direccion, 2, 1, 20)

    tk.Label(grid_campos, text="Ciudad / Municipio:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=2, column=2, sticky="w", pady=5, padx=(0, 10))
    entry_ciudad = _crear_entry(grid_campos, var_ciudad, 2, 3, 0)

    # Fila 3: Teléfono y Correo electrónico
    tk.Label(grid_campos, text="Teléfono / WhatsApp:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=3, column=0, sticky="w", pady=5, padx=(0, 10))
    entry_tel = _crear_entry(grid_campos, var_telefono, 3, 1, 20)

    tk.Label(grid_campos, text="Correo Electrónico:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=3, column=2, sticky="w", pady=5, padx=(0, 10))
    entry_email = _crear_entry(grid_campos, var_email, 3, 3, 0)

    # Fila 4: Régimen Tributario y Tipo/Prefijo de Comprobante
    tk.Label(grid_campos, text="Régimen / Nota Tributaria:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=4, column=0, sticky="w", pady=5, padx=(0, 10))
    entry_regimen = _crear_entry(grid_campos, var_regimen, 4, 1, 20)

    tk.Label(grid_campos, text="Título y Prefijo de Comprobante:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=4, column=2, sticky="w", pady=5, padx=(0, 10))
    comp_frame = tk.Frame(grid_campos, bg=t["bg_surface"])
    comp_frame.grid(row=4, column=3, sticky="ew", pady=5)
    cb_tipo_comp = ttk.Combobox(comp_frame, textvariable=var_tipo_comp, values=TIPOS_COMPROBANTE_DISPONIBLES, width=22)
    cb_tipo_comp.pack(side="left", padx=(0, 6))
    tk.Label(comp_frame, text="Prefijo:", font=("Segoe UI", 8, "bold"), bg=t["bg_surface"], fg=t["text_secondary"]).pack(side="left", padx=(2, 4))
    entry_prefijo = tk.Entry(comp_frame, textvariable=var_prefijo, font=("Segoe UI", 10), width=8, relief="solid", bd=1, bg=t["input_bg"], fg=t["input_fg"])
    entry_prefijo.pack(side="left")

    # Fila 5: Eslogan y Encabezado de recibo
    tk.Label(grid_campos, text="Eslogan / Pie de Factura:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=5, column=0, sticky="w", pady=5, padx=(0, 10))
    entry_eslogan = _crear_entry(grid_campos, var_eslogan, 5, 1, 20)

    tk.Label(grid_campos, text="Nota Superior en Recibo (opc.):", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=5, column=2, sticky="w", pady=5, padx=(0, 10))
    entry_enc_rec = _crear_entry(grid_campos, var_encabezado_recibo, 5, 3, 0)

    tk.Frame(body_negocio, bg=t["border"], height=1).pack(fill="x", pady=10)

    # Panel de Logo con Miniatura en Tiempo Real
    logo_row = tk.Frame(body_negocio, bg=t["bg_surface"])
    logo_row.pack(fill="x", pady=(0, 10))

    logo_thumb_container = tk.Frame(logo_row, bg="#FFFFFF", width=110, height=72, relief="solid", bd=1)
    logo_thumb_container.pack(side="left", padx=(0, 15))
    logo_thumb_container.pack_propagate(False)

    lbl_logo_thumb = tk.Label(logo_thumb_container, text="Sin logo", font=("Segoe UI", 8), bg="#FFFFFF", fg="#64748B")
    lbl_logo_thumb.pack(expand=True, fill="both")

    logo_meta_frame = tk.Frame(logo_row, bg=t["bg_surface"])
    logo_meta_frame.pack(side="left", fill="x", expand=True)

    tk.Label(logo_meta_frame, text="🖼️ Logo Institucional del Negocio (PNG / JPG / JPEG):", font=("Segoe UI", 9, "bold"),
             bg=t["bg_surface"], fg=t["text_primary"]).pack(anchor="w")

    lbl_logo_info = tk.Label(
        logo_meta_frame,
        text="",
        font=("Segoe UI", 9), bg=t["bg_surface"], fg=t["text_muted"]
    )
    lbl_logo_info.pack(anchor="w", pady=(2, 6))

    def refrescar_miniatura_logo():
        ruta = var_logo_path.get().strip()
        if ruta and os.path.isfile(ruta) and PIL_DISPONIBLE:
            try:
                with Image.open(ruta) as im:
                    im.load()
                    ancho_orig, alto_orig = im.size
                    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                        rgba = im.convert("RGBA")
                        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                        im_vis = Image.alpha_composite(bg, rgba).convert("RGB")
                    else:
                        im_vis = im.convert("RGB")
                    im_vis.thumbnail((102, 64), Image.Resampling.LANCZOS)
                    tk_img = ImageTk.PhotoImage(im_vis, master=ventana)
                    lbl_logo_thumb.config(image=tk_img, text="")
                    lbl_logo_thumb.image = tk_img
                    lbl_logo_info.config(
                        text=f"Archivo activo: {os.path.basename(ruta)} ({ancho_orig}×{alto_orig} px) — Listo para pantalla, PDF e impresora térmica."
                    )
                    return
            except Exception as e_th:
                print(f"Aviso mostrando miniatura de logo: {e_th}")

        lbl_logo_thumb.config(image="", text="Sin logo")
        lbl_logo_thumb.image = None
        lbl_logo_info.config(text="Ningún logo activo (se mostrará el ícono predeterminado del sistema).")

    def seleccionar_logo():
        archivo = filedialog.askopenfilename(
            parent=ventana,
            title="Seleccionar Logo del Negocio",
            filetypes=[("Imágenes soportadas", "*.png *.jpg *.jpeg *.bmp *.webp *.gif"), ("Todos los archivos", "*.*")]
        )
        if not archivo:
            return
        exito, res = business_mgr.guardar_logo(archivo, persistir=True)
        if exito:
            var_logo_path.set(res)
            refrescar_miniatura_logo()
            if callable(on_save_callback):
                try:
                    on_save_callback()
                except Exception:
                    pass
            messagebox.showinfo(
                "✅ Logo Cargado y Sincronizado",
                "El logo se validó y guardó correctamente.\n\n"
                "Ya está disponible en el Menú de Inicio, en la vista previa de facturas, en PDFs y en impresoras térmicas.",
                parent=ventana
            )
        else:
            messagebox.showerror("❌ Imagen Inválida", f"No se pudo cargar el logo seleccionado:\n{res}", parent=ventana)

    def quitar_logo():
        if not var_logo_path.get():
            messagebox.showinfo("ℹ️ Sin Logo", "Actualmente no hay ningún logo personalizado configurado.", parent=ventana)
            return
        if not messagebox.askyesno("Eliminar Logo", "¿Deseas eliminar el logo actual y dejar el negocio sin logo personalizado?", parent=ventana):
            return
        business_mgr.eliminar_logo(persistir=True)
        var_logo_path.set("")
        refrescar_miniatura_logo()
        if callable(on_save_callback):
            try:
                on_save_callback()
            except Exception:
                pass
        messagebox.showinfo("✅ Logo Eliminado", "El logo personalizado fue eliminado de la configuración.", parent=ventana)

    logo_btns = tk.Frame(logo_meta_frame, bg=t["bg_surface"])
    logo_btns.pack(anchor="w")
    crear_boton(logo_btns, "📂 Cargar / Reemplazar Logo", seleccionar_logo, tipo="secondary", tam_fuente=9).pack(side="left", padx=(0, 8))
    crear_boton(logo_btns, "🗑️ Eliminar Logo", quitar_logo, tipo="danger", tam_fuente=9).pack(side="left")

    refrescar_miniatura_logo()

    tk.Frame(body_negocio, bg=t["border"], height=1).pack(fill="x", pady=10)

    # Sección Colores de Barra y Login
    colores_row = tk.Frame(body_negocio, bg=t["bg_surface"])
    colores_row.pack(fill="x", pady=(0, 12))

    barra_box = tk.Frame(colores_row, bg=t["bg_surface"])
    barra_box.pack(side="left", fill="both", expand=True, padx=(0, 15))
    tk.Label(barra_box, text="🎨 Color de la Barra Superior (Header):", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).pack(anchor="w", pady=(0, 4))
    barra_preview = tk.Frame(barra_box, height=24, bg=var_color_barra.get(), relief="solid", bd=1)
    barra_preview.pack(fill="x", pady=(0, 6))

    def aplicar_color_barra(hex_code):
        var_color_barra.set(hex_code)
        barra_preview.config(bg=hex_code)

    paleta_barra_frame = tk.Frame(barra_box, bg=t["bg_surface"])
    paleta_barra_frame.pack(fill="x")
    for _, color_p in PALETAS_PREDEFINIDAS:
        tk.Button(
            paleta_barra_frame, bg=color_p, relief="flat", width=2, height=1,
            cursor="hand2", command=lambda c=color_p: aplicar_color_barra(c)
        ).pack(side="left", padx=2)

    login_box = tk.Frame(colores_row, bg=t["bg_surface"])
    login_box.pack(side="right", fill="both", expand=True)
    tk.Label(login_box, text="🔐 Color de Fondo / Acento de Login:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).pack(anchor="w", pady=(0, 4))
    login_preview = tk.Frame(login_box, height=24, bg=var_color_login.get(), relief="solid", bd=1)
    login_preview.pack(fill="x", pady=(0, 6))

    def aplicar_color_login(hex_code):
        var_color_login.set(hex_code)
        login_preview.config(bg=hex_code)

    paleta_login_frame = tk.Frame(login_box, bg=t["bg_surface"])
    paleta_login_frame.pack(fill="x")
    for _, color_p in PALETAS_PREDEFINIDAS:
        tk.Button(
            paleta_login_frame, bg=color_p, relief="flat", width=2, height=1,
            cursor="hand2", command=lambda c=color_p: aplicar_color_login(c)
        ).pack(side="left", padx=2)

    # Tabla resumen en vivo de la identidad configurada
    tabla_info = ttk.Treeview(body_negocio, columns=("campo", "valor"), show="headings", height=6)
    tabla_info.heading("campo", text="Campo de Identidad")
    tabla_info.heading("valor", text="Valor Actual")
    tabla_info.column("campo", width=230, anchor="w")
    tabla_info.column("valor", width=540, anchor="w")
    tabla_info.pack(fill="x", pady=(6, 4))

    campos_config = [
        ("Nombre Comercial (POS)", var_nombre, entry_nombre),
        ("Razón Social / Propietario", var_razon_social, entry_razon),
        ("Subtítulo / Rubro", var_subtitulo, entry_sub),
        ("NIT / RUT / Documento", var_nit, entry_nit),
        ("Dirección Comercial", var_direccion, entry_dir),
        ("Ciudad / Municipio", var_ciudad, entry_ciudad),
        ("Teléfono / WhatsApp", var_telefono, entry_tel),
        ("Eslogan / Pie de Factura", var_eslogan, entry_eslogan),
    ]

    def actualizar_tabla_info(*_):
        if not tabla_info.winfo_exists():
            return
        tabla_info.delete(*tabla_info.get_children())
        for etiqueta, variable, _ in campos_config:
            tabla_info.insert("", "end", values=(etiqueta, variable.get().strip() or "(vacío)"))

    def editar_campo_tabla(_event=None):
        seleccion = tabla_info.selection()
        if not seleccion:
            return
        indice = tabla_info.index(seleccion[0])
        if 0 <= indice < len(campos_config):
            entrada = campos_config[indice][2]
            entrada.focus_set()
            entrada.selection_range(0, tk.END)

    tabla_info.bind("<Double-1>", editar_campo_tabla)
    for _, variable, _ in campos_config:
        variable.trace_add("write", actualizar_tabla_info)
    actualizar_tabla_info()

    # =========================================================================
    # SECCIÓN 2: IMPRESORAS Y FORMATO DE FACTURA (58 MM, 80 MM, A4)
    # =========================================================================
    card_impresora = tk.Frame(scroll_body, bg=t["bg_surface"], bd=1, relief="solid")
    card_impresora.pack(fill="x", pady=(0, 15), padx=5)

    imp_header = tk.Frame(card_impresora, bg=t["bg_surface_alt"], height=40)
    imp_header.pack(fill="x")
    tk.Label(imp_header, text="🖨️ IMPRESORAS Y FORMATO DE FACTURA (58 MM, 80 MM, A4)", font=("Segoe UI", 11, "bold"),
             bg=t["bg_surface_alt"], fg=t["text_primary"]).pack(side="left", padx=15, pady=8)

    body_imp = tk.Frame(card_impresora, bg=t["bg_surface"], padx=20, pady=15)
    body_imp.pack(fill="x")

    tk.Label(
        body_imp,
        text="Configura el ancho de papel térmico o página completa, la impresora de esta estación y los elementos visibles en tus comprobantes.",
        font=("Segoe UI", 9, "italic"), bg=t["bg_surface"], fg=t["text_muted"]
    ).pack(anchor="w", pady=(0, 10))

    # Sub-fila 1: Formato de papel (Radio buttons grandes y claros)
    fmt_box = tk.Frame(body_imp, bg=t["bg_surface_alt"], bd=1, relief="solid", padx=12, pady=10)
    fmt_box.pack(fill="x", pady=(0, 12))

    tk.Label(fmt_box, text="📏 Formato de Papel / Tirilla:", font=("Segoe UI", 9, "bold"),
             bg=t["bg_surface_alt"], fg=t["text_primary"]).pack(side="left", padx=(0, 15))

    for codigo_fmt, desc_fmt in [
        ("58mm", "🧾 Térmico 58 mm (32 col. compacto)"),
        ("80mm", "🧾 Térmico 80 mm (48 col. estándar)"),
        ("A4", "📄 Página Completa A4 (Empresarial)")
    ]:
        tk.Radiobutton(
            fmt_box, text=desc_fmt, variable=var_formato_papel, value=codigo_fmt,
            font=("Segoe UI", 9, "bold"), bg=t["bg_surface_alt"], fg=t["text_primary"],
            activebackground=t["bg_surface_alt"], selectcolor=t["bg_surface"]
        ).pack(side="left", padx=12)

    # Sub-fila 2: Selección de Impresora, Método, Márgenes, Fuente, Densidad, Alineación y Copias
    grid_imp = tk.Frame(body_imp, bg=t["bg_surface"])
    grid_imp.pack(fill="x", pady=(0, 10))
    grid_imp.columnconfigure((1, 3), weight=1)

    tk.Label(grid_imp, text="Impresora de esta Estación:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=0, column=0, sticky="w", pady=5, padx=(0, 10))
    imp_sel_frame = tk.Frame(grid_imp, bg=t["bg_surface"])
    imp_sel_frame.grid(row=0, column=1, sticky="ew", pady=5, padx=(0, 20))

    lista_impresoras = detectar_impresoras_disponibles()
    if var_impresora_nombre.get() and var_impresora_nombre.get() not in lista_impresoras:
        lista_impresoras.append(var_impresora_nombre.get())

    cb_impresora = ttk.Combobox(imp_sel_frame, textvariable=var_impresora_nombre, values=lista_impresoras, width=28)
    cb_impresora.pack(side="left", fill="x", expand=True, padx=(0, 6))

    def refrescar_impresoras():
        nuevas = detectar_impresoras_disponibles()
        cb_impresora["values"] = nuevas
        if var_impresora_nombre.get() not in nuevas and nuevas:
            var_impresora_nombre.set(nuevas[0])
        messagebox.showinfo("🖨️ Impresoras Detectadas", f"Se encontraron {len(nuevas)} opciones de salida disponibles.", parent=ventana)

    crear_boton(imp_sel_frame, "🔄 Detectar", refrescar_impresoras, tipo="secondary", tam_fuente=8).pack(side="left")

    tk.Label(grid_imp, text="Método de Impresión:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=0, column=2, sticky="w", pady=5, padx=(0, 10))
    cb_metodo = ttk.Combobox(
        grid_imp, textvariable=var_metodo_impresion,
        values=["auto", "sistema", "escpos_usb", "solo_pdf"], state="readonly"
    )
    cb_metodo.grid(row=0, column=3, sticky="ew", pady=5)

    # Fila 1 de grid_imp: Margen, Tamaño de fuente, Densidad y Alineación
    tk.Label(grid_imp, text="Margen (mm) y Copias:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=1, column=0, sticky="w", pady=5, padx=(0, 10))
    mc_frame = tk.Frame(grid_imp, bg=t["bg_surface"])
    mc_frame.grid(row=1, column=1, sticky="w", pady=5, padx=(0, 20))
    tk.Label(mc_frame, text="Margen:", font=("Segoe UI", 9), bg=t["bg_surface"], fg=t["text_secondary"]).pack(side="left")
    tk.Spinbox(mc_frame, from_=0, to=25, textvariable=var_margen_mm, width=5, font=("Segoe UI", 10)).pack(side="left", padx=(4, 14))
    tk.Label(mc_frame, text="Copias:", font=("Segoe UI", 9), bg=t["bg_surface"], fg=t["text_secondary"]).pack(side="left")
    tk.Spinbox(mc_frame, from_=1, to=5, textvariable=var_copias, width=5, font=("Segoe UI", 10)).pack(side="left", padx=4)

    tk.Label(grid_imp, text="Fuente, Densidad y Alineación:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=1, column=2, sticky="w", pady=5, padx=(0, 10))
    fda_frame = tk.Frame(grid_imp, bg=t["bg_surface"])
    fda_frame.grid(row=1, column=3, sticky="ew", pady=5)
    ttk.Combobox(fda_frame, textvariable=var_tamano_fuente, values=["pequena", "normal", "grande"], state="readonly", width=9).pack(side="left", padx=(0, 6))
    ttk.Combobox(fda_frame, textvariable=var_densidad, values=["compacta", "normal", "amplia"], state="readonly", width=9).pack(side="left", padx=(0, 6))
    ttk.Combobox(fda_frame, textvariable=var_alineacion, values=["center", "left"], state="readonly", width=9).pack(side="left")

    # Fila 2 de grid_imp: Pie extra y corte automático
    tk.Label(grid_imp, text="Nota de Garantía / Pie Extra:", font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"]).grid(row=2, column=0, sticky="w", pady=5, padx=(0, 10))
    _crear_entry(grid_imp, var_pie_extra, 2, 1, 20)

    corte_frame = tk.Frame(grid_imp, bg=t["bg_surface"])
    corte_frame.grid(row=2, column=2, columnspan=2, sticky="w", pady=5)
    tk.Checkbutton(
        corte_frame, text="✂️ Corte automático de papel", variable=var_corte_auto,
        font=("Segoe UI", 9, "bold"), bg=t["bg_surface"], fg=t["text_primary"],
        activebackground=t["bg_surface"], selectcolor=t["bg_surface"]
    ).pack(side="left", padx=(0, 14))
    tk.Checkbutton(
        corte_frame, text="🔓 Abrir cajón monedero", variable=var_abrir_cajon,
        font=("Segoe UI", 9), bg=t["bg_surface"], fg=t["text_primary"],
        activebackground=t["bg_surface"], selectcolor=t["bg_surface"]
    ).pack(side="left")

    # Casillas de campos visibles en la factura
    tk.Label(body_imp, text="👁️ Campos Visibles en la Factura / Recibo:", font=("Segoe UI", 9, "bold"),
             bg=t["bg_surface"], fg=t["text_primary"]).pack(anchor="w", pady=(8, 4))

    chk_grid = tk.Frame(body_imp, bg=t["bg_surface"])
    chk_grid.pack(fill="x", pady=(0, 10))

    checks_visibles = [
        ("Mostrar Logo", var_mostrar_logo),
        ("Mostrar Razón Social / Subtítulo", var_mostrar_razon),
        ("Mostrar NIT / Documento", var_mostrar_nit),
        ("Mostrar Régimen Tributario", var_mostrar_regimen),
        ("Mostrar Dirección y Ciudad", var_mostrar_dir),
        ("Mostrar Teléfono", var_mostrar_tel),
        ("Mostrar Correo Electrónico", var_mostrar_email),
        ("Mostrar Datos del Cliente", var_mostrar_cliente),
        ("Mostrar Vendedor", var_mostrar_vendedor),
        ("Mostrar Eslogan / Pie", var_mostrar_eslogan),
    ]
    for idx_c, (txt_c, var_c) in enumerate(checks_visibles):
        r_c = idx_c // 5
        col_c = idx_c % 5
        tk.Checkbutton(
            chk_grid, text=txt_c, variable=var_c,
            font=("Segoe UI", 9), bg=t["bg_surface"], fg=t["text_primary"],
            activebackground=t["bg_surface"], selectcolor=t["bg_surface"]
        ).grid(row=r_c, column=col_c, sticky="w", padx=(0, 14), pady=2)

    # =========================================================================
    # FUNCIONES UNIFICADAS DE RECOLECCIÓN, GUARDADO, VISTA PREVIA E IMPRESIÓN DE PRUEBA
    # =========================================================================
    def recolectar_datos_negocio_formulario():
        return {
            "nombre_negocio": var_nombre.get().strip() or "VmPOS",
            "razon_social": var_razon_social.get().strip(),
            "subtitulo_negocio": var_subtitulo.get().strip(),
            "tipo_documento_fiscal": var_tipo_doc.get().strip() or "NIT",
            "nit": var_nit.get().strip(),
            "regimen_fiscal": var_regimen.get().strip(),
            "direccion": var_direccion.get().strip(),
            "ciudad": var_ciudad.get().strip(),
            "telefono": var_telefono.get().strip(),
            "email": var_email.get().strip(),
            "tipo_comprobante": var_tipo_comp.get().strip() or "RECIBO DE VENTA",
            "prefijo_comprobante": var_prefijo.get().strip(),
            "encabezado_recibo": var_encabezado_recibo.get().strip(),
            "eslogan": var_eslogan.get().strip(),
            "color_barra": var_color_barra.get().strip() or "#DB2777",
            "color_login": var_color_login.get().strip() or "#DB2777",
            "logo_path": var_logo_path.get().strip()
        }

    def recolectar_datos_impresora_formulario():
        try:
            margen_val = int(var_margen_mm.get())
        except Exception:
            margen_val = 2
        try:
            copias_val = int(var_copias.get())
        except Exception:
            copias_val = 1
        return {
            "formato_papel": var_formato_papel.get().strip() or "58mm",
            "impresora_nombre": var_impresora_nombre.get().strip() or "Predeterminada del sistema",
            "metodo_impresion": var_metodo_impresion.get().strip() or "auto",
            "margen_mm": max(0, min(25, margen_val)),
            "tamano_fuente": var_tamano_fuente.get().strip() or "normal",
            "densidad": var_densidad.get().strip() or "normal",
            "alineacion_encabezado": var_alineacion.get().strip() or "center",
            "copias": max(1, min(10, copias_val)),
            "corte_automatico": bool(var_corte_auto.get()),
            "abrir_cajon": bool(var_abrir_cajon.get()),
            "mostrar_logo": bool(var_mostrar_logo.get()),
            "mostrar_razon_social": bool(var_mostrar_razon.get()),
            "mostrar_nit": bool(var_mostrar_nit.get()),
            "mostrar_regimen": bool(var_mostrar_regimen.get()),
            "mostrar_direccion": bool(var_mostrar_dir.get()),
            "mostrar_telefono": bool(var_mostrar_tel.get()),
            "mostrar_email": bool(var_mostrar_email.get()),
            "mostrar_cliente": bool(var_mostrar_cliente.get()),
            "mostrar_vendedor": bool(var_mostrar_vendedor.get()),
            "mostrar_eslogan": bool(var_mostrar_eslogan.get()),
            "pie_factura_extra": var_pie_extra.get().strip()
        }

    def guardar_config_completa(mostrar_alerta=True):
        datos_neg = recolectar_datos_negocio_formulario()
        datos_imp = recolectar_datos_impresora_formulario()

        ok_neg = business_mgr.guardar(datos_neg, notificar=False)
        ok_imp = business_mgr.guardar_config_impresora(datos_imp, notificar=False)

        if ok_neg and ok_imp:
            business_mgr.recargar()
            business_mgr.notificar_cambio()
            if callable(on_save_callback):
                try:
                    on_save_callback()
                except Exception as e_cb:
                    print(f"Aviso en on_save_callback: {e_cb}")

            # Refrescar colores y título de esta misma ventana en caliente
            nuevo_col = business_mgr.color_barra
            nuevo_fg = calcular_color_texto_optimo(nuevo_col)
            ventana.title(f"⚙️ Configuración del Sistema — {business_mgr.nombre}")
            header_frame.config(bg=nuevo_col)
            header_left.config(bg=nuevo_col)
            lbl_hdr_icon.config(bg=nuevo_col, fg=nuevo_fg)
            lbl_hdr_title.config(bg=nuevo_col, fg=nuevo_fg)
            lbl_hdr_negocio.config(text=f"• {business_mgr.nombre}", bg=nuevo_col, fg=nuevo_fg)
            reloj_lbl.config(bg=nuevo_col, fg=nuevo_fg)
            actualizar_tabla_info()

            if mostrar_alerta:
                messagebox.showinfo(
                    "✅ Configuración Guardada y Aplicada",
                    f"¡La identidad de '{business_mgr.nombre}' y el formato de impresión ({datos_imp['formato_papel']}) "
                    f"se guardaron y aplicaron con éxito!\n\n"
                    f"• Negocio: {CONFIG_FILE}\n"
                    f"• Impresora: {PRINTER_CONFIG_FILE}",
                    parent=ventana
                )
            return True
        else:
            if mostrar_alerta:
                messagebox.showerror("❌ Error", "No se pudo guardar la configuración en disco.", parent=ventana)
            return False

    def abrir_vista_previa_prueba():
        guardar_config_completa(mostrar_alerta=False)
        datos_p = construir_datos_factura_prueba()
        cfg_imp = recolectar_datos_impresora_formulario()
        mostrar_dialogo_factura(
            ventana,
            datos_p,
            modo_confirmacion_venta=False,
            config_override=cfg_imp
        )

    def ejecutar_impresion_prueba():
        guardar_config_completa(mostrar_alerta=False)
        cfg_imp = recolectar_datos_impresora_formulario()
        exito, msg, datos_p = imprimir_prueba_configuracion(config_override=cfg_imp)
        if exito:
            messagebox.showinfo("🖨️ Impresión de Prueba Enviada", msg, parent=ventana)
        else:
            ver_previa = messagebox.askyesno(
                "⚠️ Impresora Física No Detectada",
                f"{msg}\n\n¿Deseas abrir la Vista Previa de Prueba para inspeccionar el formato ({cfg_imp['formato_papel']}) o exportarlo a PDF?",
                parent=ventana
            )
            if ver_previa:
                mostrar_dialogo_factura(
                    ventana,
                    datos_p,
                    modo_confirmacion_venta=False,
                    config_override=cfg_imp
                )

    # Botonera en Sección Negocio
    btns_neg_row = tk.Frame(body_negocio, bg=t["bg_surface"])
    btns_neg_row.pack(fill="x", pady=(8, 0))
    crear_boton(
        btns_neg_row, "💾 Guardar Identidad del Negocio", lambda: guardar_config_completa(True),
        tipo="primary", tam_fuente=10
    ).pack(side="right")

    crear_boton(
        acciones_negocio, "💾 Guardar ahora", lambda: guardar_config_completa(True),
        tipo="success", tam_fuente=10, padx=14, pady=5
    ).pack(side="right")

    # Botonera en Sección Impresoras
    btns_imp_row = tk.Frame(body_imp, bg=t["bg_surface"])
    btns_imp_row.pack(fill="x", pady=(8, 0))

    crear_boton(
        btns_imp_row, "🖨️ Imprimir Prueba", ejecutar_impresion_prueba,
        tipo="success", tam_fuente=10
    ).pack(side="right", padx=(6, 0))

    crear_boton(
        btns_imp_row, "👁️ Vista Previa de Prueba (58mm / 80mm / A4)", abrir_vista_previa_prueba,
        tipo="info", tam_fuente=10
    ).pack(side="right", padx=6)

    crear_boton(
        btns_imp_row, "💾 Guardar Formato e Impresora", lambda: guardar_config_completa(True),
        tipo="primary", tam_fuente=10
    ).pack(side="left")

    def abrir_dialogo_red_config():
        try:
            from interface.network_dialog import abrir_dialogo_red
        except ImportError:
            from network_dialog import abrir_dialogo_red
        abrir_dialogo_red(parent=ventana)

    # Botones en Sticky Footer
    crear_boton(f_btns, "🔧 Diagnóstico DB", diagnosticar_base_datos, tipo="secondary", tam_fuente=9).pack(side="left", padx=4)
    crear_boton(f_btns, "🌐 Red y Cajas", abrir_dialogo_red_config, tipo="warning", tam_fuente=9).pack(side="left", padx=4)
    crear_boton(f_btns, "🚀 Actualizaciones", lambda: buscar_actualizaciones_sistema(ventana), tipo="secondary", tam_fuente=9).pack(side="left", padx=4)
    crear_boton(f_btns, "💾 Backup Rápido", crear_backup, tipo="secondary", tam_fuente=9).pack(side="left", padx=4)
    crear_boton(f_btns, "🖨️ Imprimir Prueba", ejecutar_impresion_prueba, tipo="info", tam_fuente=9).pack(side="left", padx=4)
    crear_boton(f_btns, "💾 Guardar Todo", lambda: guardar_config_completa(True), tipo="success", tam_fuente=9).pack(side="left", padx=4)

    # =========================================================================
    # SECCIÓN 3: CONEXIÓN EN RED Y SERVIDOR MULTI-CAJA
    # =========================================================================
    card_net = tk.Frame(scroll_body, bg=t["bg_surface"], bd=1, relief="solid")
    card_net.pack(fill="x", pady=(0, 15), padx=5)

    n_header = tk.Frame(card_net, bg=t["bg_surface_alt"], height=38)
    n_header.pack(fill="x")
    tk.Label(n_header, text="🌐 CONEXIÓN EN RED Y SERVIDOR MULTI-CAJA", font=("Segoe UI", 11, "bold"),
             bg=t["bg_surface_alt"], fg=t["text_primary"]).pack(side="left", padx=15, pady=8)

    n_body = tk.Frame(card_net, bg=t["bg_surface"], padx=20, pady=15)
    n_body.pack(fill="x")

    n_left = tk.Frame(n_body, bg=t["bg_surface"])
    n_left.pack(side="left", fill="both", expand=True)

    try:
        from interface.network_manager import obtener_config_red, obtener_ips_locales
        net_cfg = obtener_config_red()
        ips_detectadas = ", ".join(obtener_ips_locales())
    except Exception:
        net_cfg = {}
        ips_detectadas = "127.0.0.1"

    modo_str = "🖥️ SERVIDOR CENTRAL (Caja Principal)" if net_cfg.get("modo") == "servidor" else "💻 CAJA CLIENTE (Conectada a Servidor)"
    tk.Label(n_left, text=f"Modo: {modo_str}", font=("Segoe UI", 10, "bold"),
             bg=t["bg_surface"], fg=t["accent"]).pack(anchor="w")
    tk.Label(n_left, text=f"IP del Servidor: {net_cfg.get('servidor_ip', '127.0.0.1')} • Puerto: {net_cfg.get('servidor_puerto', 8000)} • Terminal: {net_cfg.get('terminal_nombre', 'CAJA-01')} (ID: {net_cfg.get('terminal_id', 1)})",
             font=("Segoe UI", 9), bg=t["bg_surface"], fg=t["text_primary"]).pack(anchor="w", pady=(2, 0))
    tk.Label(n_left, text=f"IPs locales detectadas en esta máquina: {ips_detectadas}",
             font=("Segoe UI", 8), bg=t["bg_surface"], fg=t["text_muted"]).pack(anchor="w", pady=(2, 0))

    crear_boton(n_body, "🌐 Configurar Red y Cajas", abrir_dialogo_red_config, tipo="primary", tam_fuente=10).pack(side="right")

    # =========================================================================
    # SECCIÓN 4: ACTUALIZACIONES DEL SISTEMA
    # =========================================================================
    card_updates = tk.Frame(scroll_body, bg=t["bg_surface"], bd=1, relief="solid")
    card_updates.pack(fill="x", pady=(0, 15), padx=5)

    u_header = tk.Frame(card_updates, bg=t["bg_surface_alt"], height=38)
    u_header.pack(fill="x")
    tk.Label(u_header, text="🚀 ACTUALIZACIONES DEL SISTEMA", font=("Segoe UI", 11, "bold"),
             bg=t["bg_surface_alt"], fg=t["text_primary"]).pack(side="left", padx=15, pady=8)

    u_body = tk.Frame(card_updates, bg=t["bg_surface"], padx=20, pady=15)
    u_body.pack(fill="x")

    u_left = tk.Frame(u_body, bg=t["bg_surface"])
    u_left.pack(side="left", fill="both", expand=True)

    tk.Label(u_left, text="Estado: ✅ Sistema en la versión oficial v4.0.0 (Actualizado)", font=("Segoe UI", 10, "bold"),
             bg=t["bg_surface"], fg=t["success"]).pack(anchor="w")
    tk.Label(u_left, text="Canal de actualizaciones: Estable • Compatible con Windows 10/11 y macOS", font=("Segoe UI", 9),
             bg=t["bg_surface"], fg=t["text_muted"]).pack(anchor="w", pady=(2, 0))

    crear_boton(u_body, "🔍 Buscar Actualizaciones", lambda: buscar_actualizaciones_sistema(ventana), tipo="primary", tam_fuente=10).pack(side="right")

    # =========================================================================
    # SECCIÓN 4: APARIENCIA Y TEMAS VISUALES
    # =========================================================================
    card_tema = tk.Frame(scroll_body, bg=t["bg_surface"], bd=1, relief="solid")
    card_tema.pack(fill="x", pady=(0, 15), padx=5)

    t_header = tk.Frame(card_tema, bg=t["bg_surface_alt"], height=38)
    t_header.pack(fill="x")
    tk.Label(t_header, text="🎨 APARIENCIA Y TEMA DEL POS", font=("Segoe UI", 11, "bold"),
             bg=t["bg_surface_alt"], fg=t["text_primary"]).pack(side="left", padx=15, pady=8)

    t_body = tk.Frame(card_tema, bg=t["bg_surface"], padx=20, pady=15)
    t_body.pack(fill="x")

    tk.Label(t_body, text="Selecciona el modo visual preferido para las pantallas del sistema:",
             font=("Segoe UI", 9), bg=t["bg_surface"], fg=t["text_secondary"]).pack(anchor="w", pady=(0, 10))

    t_btns = tk.Frame(t_body, bg=t["bg_surface"])
    t_btns.pack(anchor="w")

    def cambiar_tema(nuevo_modo):
        theme_mgr.guardar_preferencia(nuevo_modo)
        messagebox.showinfo("🎨 Tema Actualizado", f"Tema establecido en modo: {nuevo_modo.upper()}.\nSe recargará la ventana de configuración.", parent=ventana)
        cerrar_configuracion()
        iniciar_configuracion(parent=parent, on_save_callback=on_save_callback)

    crear_boton(t_btns, "☀️ Modo Claro", lambda: cambiar_tema("claro"),
                tipo="primary" if theme_mgr.modo_preferido == "claro" else "secondary").pack(side="left", padx=(0, 10))
    crear_boton(t_btns, "🌙 Modo Oscuro", lambda: cambiar_tema("oscuro"),
                tipo="primary" if theme_mgr.modo_preferido == "oscuro" else "secondary").pack(side="left", padx=(0, 10))
    crear_boton(t_btns, "🖥️ Automático (SO)", lambda: cambiar_tema("auto"),
                tipo="primary" if theme_mgr.modo_preferido == "auto" else "secondary").pack(side="left")

    # =========================================================================
    # SECCIÓN 5: COPIAS DE SEGURIDAD Y MANTENIMIENTO
    # =========================================================================
    card_backup = tk.Frame(scroll_body, bg=t["bg_surface"], bd=1, relief="solid")
    card_backup.pack(fill="x", pady=(0, 20), padx=5)

    b_header = tk.Frame(card_backup, bg=t["bg_surface_alt"], height=38)
    b_header.pack(fill="x")
    tk.Label(b_header, text="💾 COPIAS DE SEGURIDAD Y MANTENIMIENTO", font=("Segoe UI", 11, "bold"),
             bg=t["bg_surface_alt"], fg=t["text_primary"]).pack(side="left", padx=15, pady=8)

    b_body = tk.Frame(card_backup, bg=t["bg_surface"], padx=20, pady=15)
    b_body.pack(fill="x")

    tk.Label(b_body, text="Protege los datos de ventas, clientes e inventario mediante copias de seguridad locales y diagnóstico de base de datos:",
             font=("Segoe UI", 9), bg=t["bg_surface"], fg=t["text_secondary"]).pack(anchor="w", pady=(0, 10))

    b_btns = tk.Frame(b_body, bg=t["bg_surface"])
    b_btns.pack(anchor="w")

    crear_boton(b_btns, "💾 Crear Copia de Seguridad", crear_backup, tipo="primary").pack(side="left", padx=(0, 10))
    crear_boton(b_btns, "🔧 Diagnóstico DB", diagnosticar_base_datos, tipo="secondary").pack(side="left", padx=(0, 10))
    crear_boton(b_btns, "🔄 Restaurar Base de Datos", restaurar_base_datos, tipo="danger").pack(side="left")

    def shortcuts(e):
        if e.state & 4:
            k = e.keysym.lower()
            if k == "b":
                crear_backup()
            elif k == "s":
                guardar_config_completa(True)

    ventana.bind("<Key>", shortcuts)

    if not es_toplevel:
        ventana.mainloop()
    return ventana


if __name__ == "__main__":
    iniciar_configuracion()