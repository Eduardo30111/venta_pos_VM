#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generador y Diseñador Profesional de Códigos de Barras y Etiquetas - VmPOS
Archivo: interface/generador_codigo_barras.py

Módulo profesional para generación de códigos de barras (CODE128, EAN-13, UPC-A, CODE39),
diseño de etiquetas de productos, integración con inventario SQLite, personalización
con identidad corporativa (business_manager), diagramación para hojas (Carta, A4, Oficio)
y rollos térmicos, exportación en PNG/PDF (ReportLab) e impresión nativa multiplataforma.
"""

import os
import sys
import json
import math
import shutil
import tempfile
import subprocess
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# Configurar path raíz
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Importaciones de temas y sesión
from interface.theme_manager import (
    theme_mgr, aplicar_tema, calcular_geometria_segura,
    crear_boton, calcular_color_texto_optimo, iniciar_observador_tema,
    ScrollableContainer
)
try:
    from session_manager import session_mgr
except ImportError:
    from interface.session_manager import session_mgr

# Importación de identidad del negocio
try:
    from business_manager import business_mgr, BASE_DIR
except ImportError:
    from interface.business_manager import business_mgr, BASE_DIR

# Importación de base de datos
try:
    from database_manager import conectar_db
except ImportError:
    from interface.database_manager import conectar_db

# Importación de detección de impresoras
try:
    from receipt_manager import detectar_impresoras_disponibles
except ImportError:
    try:
        from interface.receipt_manager import detectar_impresoras_disponibles
    except ImportError:
        def detectar_impresoras_disponibles():
            return ["Predeterminada del sistema"]

# PIL / Pillow
try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
    PIL_DISPONIBLE = True
except ImportError:
    PIL_DISPONIBLE = False

# python-barcode
try:
    import barcode
    from barcode.writer import ImageWriter
    BARCODE_DISPONIBLE = True
except ImportError:
    BARCODE_DISPONIBLE = False

# ReportLab para PDFs
try:
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.units import mm as rl_mm
    from reportlab.lib.utils import ImageReader as RLImageReader
    REPORTLAB_DISPONIBLE = True
except ImportError:
    REPORTLAB_DISPONIBLE = False

CONFIG_DIR = os.path.join(BASE_DIR, "config")
CONFIG_FILE = os.path.join(CONFIG_DIR, "barcode_label_config.json")

def obtener_nombre_negocio_seguro() -> str:
    """Obtiene el nombre comercial del negocio sin asumir si es propiedad o método."""
    try:
        val = getattr(business_mgr, "nombre", None)
        if callable(val):
            return str(val())
        if isinstance(val, str) and val:
            return val
        return str(business_mgr.obtener("nombre_negocio") or "Comercio")
    except Exception:
        return "Comercio"

def obtener_logo_path_seguro() -> str:
    """Obtiene la ruta del logo del negocio de forma segura."""
    try:
        val = getattr(business_mgr, "logo_path", None)
        if callable(val):
            return str(val())
        if isinstance(val, str) and val:
            return val
        return str(business_mgr.obtener("logo_path") or "")
    except Exception:
        return ""



# ==============================================================================
# 1. MOTOR DE CÓDIGOS DE BARRAS (BarcodeEngine)
# ==============================================================================
class BarcodeEngine:
    """Motor de generación y validación de estándares industriales de códigos de barras."""

    @staticmethod
    def calcular_checksum_ean13(primeros12: str) -> str:
        """Calcula el dígito verificador de EAN-13 ponderado 1-3."""
        if len(primeros12) < 12 or not primeros12[:12].isdigit():
            return "0"
        s = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(primeros12[:12]))
        return str((10 - (s % 10)) % 10)

    @staticmethod
    def calcular_checksum_upca(primeros11: str) -> str:
        """Calcula el dígito verificador de UPC-A ponderado 3-1."""
        if len(primeros11) < 11 or not primeros11[:11].isdigit():
            return "0"
        s = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(primeros11[:11]))
        return str((10 - (s % 10)) % 10)

    @classmethod
    def validar_y_normalizar(cls, formato: str, codigo: str) -> tuple[bool, str, str]:
        """
        Valida el código según el estándar y devuelve (valido, mensaje_error, codigo_normalizado).
        """
        fmt = (formato or "CODE128").upper().strip()
        cod = str(codigo or "").strip()

        if not cod:
            return False, "El código no puede estar vacío.", ""

        if fmt == "CODE128":
            # Code 128 admite todos los caracteres ASCII imprimibles
            try:
                cod.encode("ascii")
                return True, "", cod
            except UnicodeEncodeError:
                return False, "CODE128 solo admite caracteres ASCII estándar.", ""

        elif fmt == "EAN-13" or fmt == "EAN13":
            if not cod.isdigit():
                return False, "EAN-13 solo admite dígitos numéricos.", ""
            if len(cod) == 12:
                check = cls.calcular_checksum_ean13(cod)
                return True, "", cod + check
            elif len(cod) == 13:
                check_esperado = cls.calcular_checksum_ean13(cod[:12])
                if cod[12] != check_esperado:
                    # Sugerir corrección automática
                    return True, f"Dígito de control corregido ({cod[12]} -> {check_esperado})", cod[:12] + check_esperado
                return True, "", cod
            else:
                return False, f"EAN-13 requiere 12 dígitos (o 13 con verificador). Longitud actual: {len(cod)}.", ""

        elif fmt == "UPC-A" or fmt == "UPCA":
            if not cod.isdigit():
                return False, "UPC-A solo admite dígitos numéricos.", ""
            if len(cod) == 11:
                check = cls.calcular_checksum_upca(cod)
                return True, "", cod + check
            elif len(cod) == 12:
                check_esperado = cls.calcular_checksum_upca(cod[:11])
                if cod[11] != check_esperado:
                    return True, f"Dígito de control corregido ({cod[11]} -> {check_esperado})", cod[:11] + check_esperado
                return True, "", cod
            else:
                return False, f"UPC-A requiere 11 dígitos (o 12 con verificador). Longitud actual: {len(cod)}.", ""

        elif fmt == "CODE39":
            validos = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-. $/+%"
            cod_up = cod.upper()
            if all(c in validos for c in cod_up):
                return True, "", cod_up
            return False, "CODE39 solo admite letras mayúsculas, números y caracteres -. $/+%", ""

        return True, "", cod

    @classmethod
    def generar_imagen_barcode(cls, formato: str, codigo: str, ancho_px: int = 400, alto_px: int = 150) -> Image.Image:
        """
        Genera una imagen PIL en blanco y negro del código de barras real.
        Utiliza python-barcode o fallback nativo.
        """
        fmt = (formato or "CODE128").upper().strip()
        valido, err, cod_norm = cls.validar_y_normalizar(fmt, codigo)
        if not valido:
            raise ValueError(err)

        if BARCODE_DISPONIBLE:
            nombre_bc = "code128"
            if "EAN" in fmt:
                nombre_bc = "ean13"
                # python-barcode ean13 espera 12 dígitos y agrega el 13
                datos_bc = cod_norm[:12]
            elif "UPC" in fmt:
                nombre_bc = "upca"
                datos_bc = cod_norm[:11]
            elif "39" in fmt:
                nombre_bc = "code39"
                datos_bc = cod_norm
            else:
                nombre_bc = "code128"
                datos_bc = cod_norm

            try:
                bc_class = barcode.get_barcode_class(nombre_bc)
                writer = ImageWriter()
                # Opciones de renderizado nítido sin texto inferior (el texto lo gestiona el diseñador de etiquetas)
                writer_options = {
                    "module_width": 0.25,
                    "module_height": 10.0,
                    "quiet_zone": 2.0,
                    "write_text": False,
                    "font_size": 0,
                    "text_distance": 0,
                    "background": "white",
                    "foreground": "black"
                }
                bc_obj = bc_class(datos_bc, writer=writer)
                img = bc_obj.render(writer_options)
                # Redimensionar al tamaño deseado manteniendo nitidez
                img = img.resize((max(50, ancho_px), max(20, alto_px)), Image.Resampling.NEAREST if hasattr(Image, "Resampling") else Image.NEAREST)
                return img.convert("RGB")
            except Exception as e:
                # Si falla python-barcode por alguna razón, usar renderizador nativo
                pass

        # Renderizador nativo de barras puras (Fallback determinista Code 128 / Binario)
        return cls._render_fallback_barcode(cod_norm, ancho_px, alto_px)

    @classmethod
    def _render_fallback_barcode(cls, texto: str, ancho: int, alto: int) -> Image.Image:
        """Generador nativo de barras monocromáticas en caso de ausencia de python-barcode."""
        img = Image.new("RGB", (ancho, alto), color="white")
        draw = ImageDraw.Draw(img)
        # Generar patrón pseudo-binario determinista estándar
        bits = "101" # Start
        for ch in texto:
            v = ord(ch)
            pat = bin(v)[2:].zfill(8)
            bits += pat + "0"
        bits += "101" # Stop

        total_mods = len(bits) + 8 # Margen
        mod_w = max(1.0, float(ancho) / total_mods)
        x_offset = (ancho - (len(bits) * mod_w)) / 2.0

        for i, b in enumerate(bits):
            if b == "1":
                x1 = int(x_offset + i * mod_w)
                x2 = int(x_offset + (i + 1) * mod_w)
                draw.rectangle([x1, 5, x2, alto - 5], fill="black")

        return img


# ==============================================================================
# 2. INTEGRACIÓN CON INVENTARIO (InventoryBarcodeManager)
# ==============================================================================
class InventoryBarcodeManager:
    """Gestiona la búsqueda, autogeneración y persistencia de códigos de barras en SQLite."""

    @staticmethod
    def obtener_productos(filtro: str = "") -> list[dict]:
        """Obtiene la lista de productos activos desde ventas.db."""
        productos = []
        try:
            conn = conectar_db()
            cur = conn.cursor()
            query = """
                SELECT id, codigo, nombre, precio, codigo_barras, categoria, tipo_producto, stock
                FROM productos
                WHERE estado = 'Activo'
            """
            params = []
            if filtro:
                f = f"%{filtro.strip()}%"
                query += " AND (codigo LIKE ? OR nombre LIKE ? OR codigo_barras LIKE ?)"
                params.extend([f, f, f])
            query += " ORDER BY nombre ASC LIMIT 100"

            cur.execute(query, params)
            for row in cur.fetchall():
                productos.append({
                    "id": row[0],
                    "codigo": str(row[1] or ""),
                    "nombre": str(row[2] or ""),
                    "precio": float(row[3] or 0.0),
                    "codigo_barras": str(row[4] or "").strip(),
                    "categoria": str(row[5] or ""),
                    "tipo_producto": str(row[6] or ""),
                    "stock": float(row[7] or 0.0)
                })
            conn.close()
        except Exception as e:
            print(f"Error al obtener productos de inventario: {e}")
        return productos

    @staticmethod
    def existe_codigo_barras(codigo_barras: str, excluir_id: int = None) -> bool:
        """Verifica si un código de barras ya está registrado en otro producto."""
        if not codigo_barras:
            return False
        try:
            conn = conectar_db()
            cur = conn.cursor()
            if excluir_id is not None:
                cur.execute("SELECT id FROM productos WHERE codigo_barras = ? AND id != ? LIMIT 1",
                            (codigo_barras.strip(), excluir_id))
            else:
                cur.execute("SELECT id FROM productos WHERE codigo_barras = ? LIMIT 1",
                            (codigo_barras.strip(),))
            existe = cur.fetchone() is not None
            conn.close()
            return existe
        except Exception as e:
            print(f"Error al verificar unicidad de código: {e}")
            return False

    @classmethod
    def generar_codigo_unico(cls, producto_id: int = None, formato: str = "CODE128") -> str:
        """
        Genera un código de barras interno garantizando unicidad en la base de datos.
        - EAN-13: Prefijo tienda 200 + 8 dígitos + Checksum
        - CODE128: VM-{SKU/ID} o numérico secuencial
        """
        fmt = (formato or "CODE128").upper().strip()

        for intento in range(1, 1000):
            if "EAN" in fmt:
                # Código interno EAN-13 (rango 200-299 reservado para tiendas minoristas internas)
                semilla = (producto_id or 1) * 100 + intento
                cuerpo12 = f"200{semilla:09d}"[:12]
                check = BarcodeEngine.calcular_checksum_ean13(cuerpo12)
                candidato = cuerpo12 + check
            else:
                # CODE128 alfanumérico limpio
                if producto_id:
                    candidato = f"VM{producto_id:05d}{intento:02d}" if intento > 1 else f"VM{producto_id:05d}"
                else:
                    candidato = f"VM{datetime.now().strftime('%y%m%d%H%M')}{intento:02d}"

            if not cls.existe_codigo_barras(candidato, excluir_id=producto_id):
                return candidato

        return f"VM{datetime.now().strftime('%S%f')[:8]}"

    @classmethod
    def guardar_codigo_en_producto(cls, producto_id: int, nuevo_codigo: str) -> tuple[bool, str]:
        """
        Asigna de forma persistente el código de barras a un producto en SQLite.
        Verifica unicidad y preserva la integridad del historial de ventas.
        """
        if not producto_id:
            return False, "ID de producto inválido."
        cod = str(nuevo_codigo or "").strip()
        if not cod:
            return False, "El código de barras no puede estar vacío."

        if cls.existe_codigo_barras(cod, excluir_id=producto_id):
            return False, f"El código '{cod}' ya está asignado a otro producto."

        try:
            conn = conectar_db()
            cur = conn.cursor()
            ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cur.execute("""
                UPDATE productos
                SET codigo_barras = ?, fecha_modificacion = ?
                WHERE id = ?
            """, (cod, ahora, producto_id))
            conn.commit()
            conn.close()
            return True, f"Código '{cod}' guardado correctamente en el inventario."
        except Exception as e:
            return False, f"Error al actualizar base de datos: {e}"


# ==============================================================================
# 3. DISEÑADOR DE ETIQUETA INDIVIDUAL (LabelDesignEngine)
# ==============================================================================
class LabelDesignEngine:
    """Diseña y renderiza etiquetas individuales a cualquier resolución (DPI)."""

    @staticmethod
    def _obtener_fuente(tamano_pt: int, negrita: bool = False):
        """Carga una fuente TrueType del sistema o fallback estándar PIL."""
        candidatos = [
            "DejaVuSans-Bold.ttf" if negrita else "DejaVuSans.ttf",
            "Arial Bold.ttf" if negrita else "Arial.ttf",
            "Helvetica-Bold" if negrita else "Helvetica",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/Library/Fonts/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if negrita else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ]
        for f in candidatos:
            try:
                return ImageFont.truetype(f, tamano_pt)
            except Exception:
                pass
        try:
            return ImageFont.load_default()
        except Exception:
            return None

    @classmethod
    def renderizar_etiqueta(
        cls,
        producto: dict,
        config: dict,
        ancho_mm: float,
        alto_mm: float,
        dpi: int = 300
    ) -> Image.Image:
        """
        Renderiza una etiqueta individual en alta resolución PIL.Image.
        """
        w_px = max(100, int(round(ancho_mm * dpi / 25.4)))
        h_px = max(60, int(round(alto_mm * dpi / 25.4)))

        img = Image.new("RGB", (w_px, h_px), color="white")
        draw = ImageDraw.Draw(img)

        # Márgenes internos (padding seguro)
        pad_x = max(6, int(w_px * 0.04))
        pad_y = max(4, int(h_px * 0.04))
        area_w = w_px - (pad_x * 2)

        cursor_y = pad_y

        # Factores de escala de fuentes según el alto de la etiqueta
        factor_fuente = max(0.6, (dpi / 300.0) * (alto_mm / 30.0))
        font_header = cls._obtener_fuente(int(14 * factor_fuente), negrita=True)
        font_prod = cls._obtener_fuente(int(13 * factor_fuente), negrita=True)
        font_sub = cls._obtener_fuente(int(10 * factor_fuente), negrita=False)
        font_barcode = cls._obtener_fuente(int(11 * factor_fuente), negrita=True)
        font_precio = cls._obtener_fuente(int(16 * factor_fuente), negrita=True)

        # 1. Identidad de Negocio (Nombre y Logo)
        mostrar_negocio = config.get("mostrar_negocio", True)
        mostrar_logo = config.get("mostrar_logo", False)

        nombre_negocio = obtener_nombre_negocio_seguro()

        if (mostrar_negocio and nombre_negocio) or mostrar_logo:
            header_h = int(24 * factor_fuente)
            # Dibujar logo si está activo y existe
            if mostrar_logo:
                logo_path = obtener_logo_path_seguro()
                if logo_path and os.path.isfile(logo_path):
                    try:
                        with Image.open(logo_path) as limg:
                            limg = limg.convert("RGBA")
                            lw = int(header_h * 1.5)
                            lh = header_h
                            limg.thumbnail((lw, lh), Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS)
                            img.paste(limg, (pad_x, cursor_y), limg)
                    except Exception:
                        pass
            if mostrar_negocio and nombre_negocio:
                draw.text((w_px / 2.0, cursor_y), str(nombre_negocio)[:28], fill="black",
                          font=font_header, anchor="mt")
            cursor_y += header_h + int(4 * factor_fuente)

        # 2. Nombre del Producto
        if config.get("mostrar_nombre_prod", True):
            nombre_p = str(producto.get("nombre", "") or "Producto General")
            # Cortar si es demasiado largo
            if len(nombre_p) > 35:
                nombre_p = nombre_p[:33] + "..."
            draw.text((w_px / 2.0, cursor_y), nombre_p, fill="black",
                      font=font_prod, anchor="mt")
            cursor_y += int(18 * factor_fuente)

        # 3. Categoría / SKU
        mostrar_sku = config.get("mostrar_sku", True)
        mostrar_cat = config.get("mostrar_categoria", False)
        sub_text = []
        if mostrar_sku and producto.get("codigo"):
            sub_text.append(f"SKU: {producto['codigo']}")
        if mostrar_cat and producto.get("categoria"):
            sub_text.append(f"{producto['categoria']}")
        if sub_text:
            draw.text((w_px / 2.0, cursor_y), " | ".join(sub_text), fill="#333333",
                      font=font_sub, anchor="mt")
            cursor_y += int(14 * factor_fuente)

        # 4. Código de Barras (Imagen + Texto numérico)
        mostrar_img_bc = config.get("mostrar_imagen_codigo", True)
        mostrar_txt_bc = config.get("mostrar_texto_codigo", True)
        cod_bc = str(producto.get("codigo_barras") or producto.get("codigo") or "00000000")
        formato_bc = config.get("formato_codigo", "CODE128")

        # Reservar espacio para precio en la parte inferior
        mostrar_precio = config.get("mostrar_precio", True)
        alto_precio = int(22 * factor_fuente) if mostrar_precio else 0
        alto_txt_bc = int(14 * factor_fuente) if mostrar_txt_bc else 0

        espacio_restante = h_px - cursor_y - pad_y - alto_precio - alto_txt_bc

        if mostrar_img_bc and espacio_restante > 20:
            alto_bc_px = max(20, espacio_restante)
            ancho_bc_px = int(area_w * 0.92)
            try:
                bc_img = BarcodeEngine.generar_imagen_barcode(formato_bc, cod_bc, ancho_bc_px, alto_bc_px)
                x_bc = int((w_px - bc_img.width) / 2.0)
                img.paste(bc_img, (x_bc, cursor_y))
                cursor_y += bc_img.height + int(2 * factor_fuente)
            except Exception as e:
                draw.text((w_px / 2.0, cursor_y + 5), f"[{cod_bc}]", fill="red", font=font_sub, anchor="mt")
                cursor_y += int(16 * factor_fuente)
        elif not mostrar_img_bc:
            cursor_y += int(4 * factor_fuente)

        if mostrar_txt_bc:
            draw.text((w_px / 2.0, cursor_y), str(cod_bc), fill="black",
                      font=font_barcode, anchor="mt")
            cursor_y += alto_txt_bc

        # 5. Precio Destacado
        if mostrar_precio:
            val_p = float(producto.get("precio", 0.0) or 0.0)
            precio_str = f"$ {val_p:,.0f}".replace(",", ".")
            y_precio = h_px - pad_y - int(4 * factor_fuente)
            draw.text((w_px / 2.0, y_precio), precio_str, fill="black",
                      font=font_precio, anchor="mb")

        # Borde sutil de corte/delimitación si se desea en hoja
        draw.rectangle([0, 0, w_px - 1, h_px - 1], outline="#E0E0E0", width=1)
        return img


# ==============================================================================
# 4. DIAGRAMACIÓN DE HOJAS Y TÉRMICAS (SheetAndThermalLayoutEngine)
# ==============================================================================
class SheetAndThermalLayoutEngine:
    """Calcula la grilla matemática y genera composiciones completas en hoja o bobina."""

    TAMAÑOS_PAPEL_MM = {
        "Carta": (215.9, 279.4),
        "A4": (210.0, 297.0),
        "Oficio": (215.9, 355.6),
        "Personalizado": (215.9, 279.4)
    }

    @classmethod
    def calcular_grilla(cls, cfg: dict) -> dict:
        """
        Calcula dimensiones, filas y columnas disponibles con validación estricta de márgenes.
        """
        tipo = cfg.get("tipo_impresion", "hoja")
        tam_papel = cfg.get("tamano_papel", "Carta")

        if tipo == "hoja":
            pw_def, ph_def = cls.TAMAÑOS_PAPEL_MM.get(tam_papel, (215.9, 279.4))
            papel_w = float(cfg.get("ancho_papel_mm") or pw_def)
            papel_h = float(cfg.get("alto_papel_mm") or ph_def)
        else:
            # Térmica o continuo
            papel_w = float(cfg.get("ancho_etiqueta_mm") or 50.0)
            papel_h = float(cfg.get("alto_etiqueta_mm") or 30.0)

        etiqueta_w = float(cfg.get("ancho_etiqueta_mm") or 50.0)
        etiqueta_h = float(cfg.get("alto_etiqueta_mm") or 25.0)

        margen_izq = float(cfg.get("margen_izquierdo_mm") or 10.0)
        margen_sup = float(cfg.get("margen_superior_mm") or 10.0)
        sep_x = float(cfg.get("separacion_x_mm") or 3.0)
        sep_y = float(cfg.get("separacion_y_mm") or 3.0)

        if tipo == "hoja":
            ancho_util = papel_w - (margen_izq * 2)
            alto_util = papel_h - (margen_sup * 2)

            cols_calc = max(1, int((ancho_util + sep_x) / (etiqueta_w + sep_x)))
            filas_calc = max(1, int((alto_util + sep_y) / (etiqueta_h + sep_y)))

            cols = int(cfg.get("columnas") or cols_calc)
            filas = int(cfg.get("filas") or filas_calc)
        else:
            cols = 1
            filas = 1
            margen_izq = 0.0
            margen_sup = 0.0
            sep_x = 0.0
            sep_y = 0.0

        etiquetas_por_pagina = cols * filas
        copias = max(1, int(cfg.get("copias") or 1))
        paginas_totales = max(1, int(math.ceil(copias / etiquetas_por_pagina)))

        return {
            "papel_w": papel_w,
            "papel_h": papel_h,
            "etiqueta_w": etiqueta_w,
            "etiqueta_h": etiqueta_h,
            "margen_izq": margen_izq,
            "margen_sup": margen_sup,
            "sep_x": sep_x,
            "sep_y": sep_y,
            "cols": cols,
            "filas": filas,
            "etiquetas_por_pagina": etiquetas_por_pagina,
            "copias": copias,
            "paginas_totales": paginas_totales
        }

    @classmethod
    def renderizar_hoja_preview(cls, producto: dict, cfg: dict, max_preview_px: int = 700) -> Image.Image:
        """
        Genera una imagen fidedigna en baja/mediana resolución de la primera página completa.
        """
        grilla = cls.calcular_grilla(cfg)
        pw, ph = grilla["papel_w"], grilla["papel_h"]

        # Escalar para que quepa en el canvas de preview
        escala = max_preview_px / max(pw, ph)
        w_px = max(150, int(pw * escala))
        h_px = max(150, int(ph * escala))

        hoja_img = Image.new("RGB", (w_px, h_px), color="white")
        draw = ImageDraw.Draw(hoja_img)

        # Borde exterior de la hoja con sombra
        draw.rectangle([0, 0, w_px - 1, h_px - 1], outline="#BDBDBD", width=2)

        # Generar imagen de una etiqueta individual
        lbl_img = LabelDesignEngine.renderizar_etiqueta(
            producto, cfg, grilla["etiqueta_w"], grilla["etiqueta_h"], dpi=120
        )
        lbl_w_px = max(10, int(grilla["etiqueta_w"] * escala))
        lbl_h_px = max(10, int(grilla["etiqueta_h"] * escala))
        lbl_resized = lbl_img.resize((lbl_w_px, lbl_h_px), Image.Resampling.BILINEAR if hasattr(Image, "Resampling") else Image.BILINEAR)

        m_izq_px = int(grilla["margen_izq"] * escala)
        m_sup_px = int(grilla["margen_sup"] * escala)
        sep_x_px = int(grilla["sep_x"] * escala)
        sep_y_px = int(grilla["sep_y"] * escala)

        copias_restantes = grilla["copias"]

        for r in range(grilla["filas"]):
            for c in range(grilla["cols"]):
                if copias_restantes <= 0:
                    break
                x = m_izq_px + c * (lbl_w_px + sep_x_px)
                y = m_sup_px + r * (lbl_h_px + sep_y_px)
                if x + lbl_w_px <= w_px and y + lbl_h_px <= h_px:
                    hoja_img.paste(lbl_resized, (x, y))
                    draw.rectangle([x, y, x + lbl_w_px, y + lbl_h_px], outline="#9E9E9E", width=1)
                copias_restantes -= 1
            if copias_restantes <= 0:
                break

        return hoja_img


# ==============================================================================
# 5. GENERADOR DE PDF VECTORIAL (PdfEngine)
# ==============================================================================
class PdfEngine:
    """Genera documentos PDF listos para imprimir con ReportLab a escala exacta."""

    @classmethod
    def exportar_pdf(cls, ruta_destino: str, producto: dict, cfg: dict) -> tuple[bool, str]:
        """
        Crea un PDF con la cuadrícula de etiquetas distribuida según la configuración.
        """
        if not REPORTLAB_DISPONIBLE:
            return False, "La biblioteca ReportLab no está disponible en el entorno."

        try:
            grilla = SheetAndThermalLayoutEngine.calcular_grilla(cfg)
            pw_pt = grilla["papel_w"] * rl_mm
            ph_pt = grilla["papel_h"] * rl_mm

            c = rl_canvas.Canvas(ruta_destino, pagesize=(pw_pt, ph_pt))

            # Pre-renderizar etiqueta individual en alta resolución (300 DPI)
            lbl_pil = LabelDesignEngine.renderizar_etiqueta(
                producto, cfg, grilla["etiqueta_w"], grilla["etiqueta_h"], dpi=300
            )

            # Convertir PIL Image a ImageReader de ReportLab
            lbl_reader = RLImageReader(lbl_pil)

            lbl_w_pt = grilla["etiqueta_w"] * rl_mm
            lbl_h_pt = grilla["etiqueta_h"] * rl_mm
            m_izq_pt = grilla["margen_izq"] * rl_mm
            m_sup_pt = grilla["margen_sup"] * rl_mm
            sep_x_pt = grilla["sep_x"] * rl_mm
            sep_y_pt = grilla["sep_y"] * rl_mm

            copias_totales = grilla["copias"]
            copias_dibujadas = 0

            while copias_dibujadas < copias_totales:
                for r in range(grilla["filas"]):
                    for col in range(grilla["cols"]):
                        if copias_dibujadas >= copias_totales:
                            break

                        x_pt = m_izq_pt + col * (lbl_w_pt + sep_x_pt)
                        # En ReportLab el origen (0,0) está en la esquina inferior izquierda
                        y_pt = ph_pt - m_sup_pt - (r + 1) * lbl_h_pt - r * sep_y_pt

                        c.drawImage(lbl_reader, x_pt, y_pt, width=lbl_w_pt, height=lbl_h_pt)
                        copias_dibujadas += 1

                    if copias_dibujadas >= copias_totales:
                        break

                c.showPage()

            c.save()
            return True, f"PDF generado exitosamente ({copias_totales} etiqueta(s) en {grilla['paginas_totales']} página(s))."
        except Exception as e:
            return False, f"Error al generar PDF: {e}"


# ==============================================================================
# 6. MOTOR DE IMPRESIÓN (PrintEngine)
# ==============================================================================
class PrintEngine:
    """Envía el trabajo a la impresora seleccionada en macOS, Linux o Windows."""

    @classmethod
    def imprimir_etiquetas(cls, producto: dict, cfg: dict) -> tuple[bool, str]:
        """
        Genera un PDF temporal y lo envía al servicio de impresión nativo del SO.
        """
        temp_dir = tempfile.mkdtemp(prefix="vmpos_etiquetas_")
        temp_pdf = os.path.join(temp_dir, f"etiquetas_{datetime.now().strftime('%H%M%S')}.pdf")

        ok_pdf, msg_pdf = PdfEngine.exportar_pdf(temp_pdf, producto, cfg)
        if not ok_pdf:
            return False, msg_pdf

        impresora = cfg.get("impresora_seleccionada", "Predeterminada del sistema")

        try:
            if sys.platform.startswith("darwin") or sys.platform.startswith("linux"):
                cmd = ["lp"]
                if impresora and impresora != "Predeterminada del sistema" and not impresora.startswith("USB"):
                    cmd.extend(["-d", impresora])
                cmd.append(temp_pdf)

                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if proc.returncode == 0:
                    return True, f"Enviado a la cola de impresión '{impresora}'."
                return False, f"La cola de impresión rechazó el trabajo: {proc.stderr.strip() or proc.stdout.strip()}"
            else:
                # Windows
                try:
                    import win32api
                    import win32print
                    target_p = impresora
                    if not target_p or target_p == "Predeterminada del sistema":
                        target_p = win32print.GetDefaultPrinter()
                    win32api.ShellExecute(0, "print", temp_pdf, f'/d:"{target_p}"', ".", 0)
                    return True, f"Documento enviado a '{target_p}'."
                except Exception as we:
                    return False, f"Error al imprimir en Windows: {we}"
        except Exception as e:
            return False, f"No se pudo enviar a imprimir: {e}"
        finally:
            # Mantener el temporal unos segundos o eliminar si ya terminó
            pass


# ==============================================================================
# 7. INTERFAZ GRÁFICA MODERNA (GeneradorCodigoBarras)
# ==============================================================================
class GeneradorCodigoBarras:
    """
    Ventana y Diseñador de Códigos de Barras y Etiquetas de VmPOS.
    Estructurado en 4 bloques funcionales con soporte completo de temas y persistencia.
    """

    def __init__(self, parent=None, parent_pid=""):
        self.ventana = tk.Toplevel(parent) if parent else tk.Tk()
        self.parent_pid = parent_pid or os.environ.get("VMPOS_PARENT_PID", "")
        session_mgr.iniciar_vigilante_padre(self.ventana, parent_pid=self.parent_pid)
        iniciar_observador_tema(self.ventana)

        # Producto seleccionado actualmente
        self.producto_actual = {
            "id": None,
            "codigo": "",
            "nombre": "Producto de Ejemplo",
            "precio": 15000.0,
            "codigo_barras": "770123456789",
            "categoria": "General",
            "tipo_producto": "Fisico"
        }

        # Cargar configuración persistente
        self.config = self.cargar_configuracion()

        # Variables de control Tkinter
        self._init_vars()

        self.setup_window()
        self.create_widgets()

        # Generar vista inicial
        self.ventana.after(150, self.actualizar_vista_previa)

    def cargar_configuracion(self) -> dict:
        """Carga preferencias desde config/barcode_label_config.json."""
        default_cfg = {
            "tipo_impresion": "hoja",
            "tamano_papel": "Carta",
            "ancho_papel_mm": 215.9,
            "alto_papel_mm": 279.4,
            "ancho_etiqueta_mm": 50.0,
            "alto_etiqueta_mm": 25.0,
            "margen_superior_mm": 10.0,
            "margen_izquierdo_mm": 10.0,
            "separacion_x_mm": 3.0,
            "separacion_y_mm": 3.0,
            "columnas": 3,
            "filas": 8,
            "orientacion": "Vertical",
            "copias": 1,
            "formato_codigo": "CODE128",
            "mostrar_negocio": True,
            "mostrar_logo": False,
            "mostrar_nombre_prod": True,
            "mostrar_precio": True,
            "mostrar_sku": True,
            "mostrar_categoria": False,
            "mostrar_imagen_codigo": True,
            "mostrar_texto_codigo": True,
            "impresora_seleccionada": "Predeterminada del sistema"
        }
        if os.path.isfile(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    c = json.load(f)
                    default_cfg.update(c)
            except Exception as e:
                print(f"Error al leer configuración de etiquetas: {e}")
        return default_cfg

    def guardar_configuracion(self):
        """Guarda preferencias en disco."""
        self._sincronizar_vars_hacia_config()
        try:
            os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error al guardar configuración: {e}")

    def _init_vars(self):
        """Inicializa las variables reactivas de la interfaz."""
        c = self.config
        self.var_formato_codigo = tk.StringVar(value=c.get("formato_codigo", "CODE128"))
        self.var_tipo_impresion = tk.StringVar(value=c.get("tipo_impresion", "hoja"))
        self.var_tamano_papel = tk.StringVar(value=c.get("tamano_papel", "Carta"))

        self.var_ancho_etiqueta = tk.DoubleVar(value=float(c.get("ancho_etiqueta_mm", 50.0)))
        self.var_alto_etiqueta = tk.DoubleVar(value=float(c.get("alto_etiqueta_mm", 25.0)))
        self.var_margen_izq = tk.DoubleVar(value=float(c.get("margen_izquierdo_mm", 10.0)))
        self.var_margen_sup = tk.DoubleVar(value=float(c.get("margen_superior_mm", 10.0)))
        self.var_sep_x = tk.DoubleVar(value=float(c.get("separacion_x_mm", 3.0)))
        self.var_sep_y = tk.DoubleVar(value=float(c.get("separacion_y_mm", 3.0)))
        self.var_columnas = tk.IntVar(value=int(c.get("columnas", 3)))
        self.var_filas = tk.IntVar(value=int(c.get("filas", 8)))
        self.var_copias = tk.IntVar(value=int(c.get("copias", 1)))

        self.var_mostrar_negocio = tk.BooleanVar(value=bool(c.get("mostrar_negocio", True)))
        self.var_mostrar_logo = tk.BooleanVar(value=bool(c.get("mostrar_logo", False)))
        self.var_mostrar_nombre = tk.BooleanVar(value=bool(c.get("mostrar_nombre_prod", True)))
        self.var_mostrar_precio = tk.BooleanVar(value=bool(c.get("mostrar_precio", True)))
        self.var_mostrar_sku = tk.BooleanVar(value=bool(c.get("mostrar_sku", True)))
        self.var_mostrar_cat = tk.BooleanVar(value=bool(c.get("mostrar_categoria", False)))
        self.var_mostrar_img_bc = tk.BooleanVar(value=bool(c.get("mostrar_imagen_codigo", True)))
        self.var_mostrar_txt_bc = tk.BooleanVar(value=bool(c.get("mostrar_texto_codigo", True)))

        self.var_impresora = tk.StringVar(value=c.get("impresora_seleccionada", "Predeterminada del sistema"))
        self.var_busqueda_prod = tk.StringVar()
        self.var_manual_codigo = tk.StringVar(value=self.producto_actual["codigo_barras"])
        self.var_manual_nombre = tk.StringVar(value=self.producto_actual["nombre"])
        self.var_manual_precio = tk.DoubleVar(value=self.producto_actual["precio"])

    def _sincronizar_vars_hacia_config(self):
        """Actualiza el diccionario config con los valores de los controles."""
        self.config["formato_codigo"] = self.var_formato_codigo.get()
        self.config["tipo_impresion"] = self.var_tipo_impresion.get()
        self.config["tamano_papel"] = self.var_tamano_papel.get()
        self.config["ancho_etiqueta_mm"] = self.var_ancho_etiqueta.get()
        self.config["alto_etiqueta_mm"] = self.var_alto_etiqueta.get()
        self.config["margen_izquierdo_mm"] = self.var_margen_izq.get()
        self.config["margen_superior_mm"] = self.var_margen_sup.get()
        self.config["separacion_x_mm"] = self.var_sep_x.get()
        self.config["separacion_y_mm"] = self.var_sep_y.get()
        self.config["columnas"] = self.var_columnas.get()
        self.config["filas"] = self.var_filas.get()
        self.config["copias"] = self.var_copias.get()

        self.config["mostrar_negocio"] = self.var_mostrar_negocio.get()
        self.config["mostrar_logo"] = self.var_mostrar_logo.get()
        self.config["mostrar_nombre_prod"] = self.var_mostrar_nombre.get()
        self.config["mostrar_precio"] = self.var_mostrar_precio.get()
        self.config["mostrar_sku"] = self.var_mostrar_sku.get()
        self.config["mostrar_categoria"] = self.var_mostrar_cat.get()
        self.config["mostrar_imagen_codigo"] = self.var_mostrar_img_bc.get()
        self.config["mostrar_texto_codigo"] = self.var_mostrar_txt_bc.get()
        self.config["impresora_seleccionada"] = self.var_impresora.get()

    def setup_window(self):
        """Configuración de ventana, resolución segura y tema."""
        self.ventana.title("🏷️ Diseñador y Generador de Etiquetas y Códigos de Barras - VmPOS")
        self.t = aplicar_tema(self.ventana)
        calcular_geometria_segura(self.ventana, 1080, 760, min_w=920, min_h=620)
        self.ventana.configure(bg=self.t["bg_app"])

        if self.ventana.master:
            self.ventana.transient(self.ventana.master)

        self.ventana.protocol("WM_DELETE_WINDOW", self.al_cerrar)

    def al_cerrar(self):
        """Guarda configuración al cerrar."""
        self.guardar_configuracion()
        self.ventana.destroy()

    def create_widgets(self):
        """Construye los 4 bloques principales de la interfaz."""
        self.create_header()

        # Contenedor principal horizontal
        main_paned = tk.PanedWindow(self.ventana, orient="horizontal", bg=self.t["bg_app"], sashwidth=4)
        main_paned.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        # Panel izquierdo con scroll: Bloques 1, 2 y 3
        left_container = tk.Frame(main_paned, bg=self.t["bg_surface"])
        main_paned.add(left_container, minsize=420, width=480)

        scroll_left = ScrollableContainer(left_container, bg=self.t["bg_surface"])
        scroll_left.pack(fill="both", expand=True)
        self.left_content = scroll_left.scrollable_frame

        # Bloque 1: Búsqueda y Selección de Producto
        self.crear_bloque_1_producto(self.left_content)

        # Bloque 2: Elementos de la Etiqueta
        self.crear_bloque_2_elementos(self.left_content)

        # Bloque 3: Formato e Impresión
        self.crear_bloque_3_impresion(self.left_content)

        # Panel derecho: Bloque 4 (Vista Previa y Acciones)
        right_container = tk.Frame(main_paned, bg=self.t["bg_app"])
        main_paned.add(right_container, minsize=420, width=560)
        self.crear_bloque_4_preview_y_acciones(right_container)

    def create_header(self):
        """Encabezado superior compacto."""
        header_frame = tk.Frame(self.ventana, bg=self.t["accent"], height=46)
        header_frame.pack(fill="x", side="top", pady=(0, 8))
        header_frame.pack_propagate(False)

        fg_h = calcular_color_texto_optimo(self.t["accent"])
        tk.Label(
            header_frame, text="🏷️ Generador y Diseñador de Etiquetas de Producto",
            font=("Segoe UI", 13, "bold"), bg=self.t["accent"], fg=fg_h
        ).pack(side="left", padx=16, pady=10)

        # Identidad del negocio actual
        nombre_neg = obtener_nombre_negocio_seguro()
        tk.Label(
            header_frame, text=f"Negocio: {nombre_neg}",
            font=("Segoe UI", 9), bg=self.t["accent"], fg=fg_h
        ).pack(side="right", padx=16, pady=12)

    # --------------------------------------------------------------------------
    # BLOQUE 1: INVENTARIO Y PRODUCTO
    # --------------------------------------------------------------------------
    def crear_bloque_1_producto(self, parent):
        frame = tk.LabelFrame(
            parent, text=" 📦 1. Selección de Producto e Inventario ",
            bg=self.t["bg_surface"], fg=self.t["accent"], font=("Segoe UI", 10, "bold"),
            bd=1, relief="solid"
        )
        frame.pack(fill="x", padx=8, pady=6)

        # Búsqueda rápida
        search_f = tk.Frame(frame, bg=self.t["bg_surface"])
        search_f.pack(fill="x", padx=8, pady=4)

        tk.Label(search_f, text="Buscar:", bg=self.t["bg_surface"], fg=self.t["fg_primary"],
                 font=("Segoe UI", 9, "bold")).pack(side="left")

        self.entry_busqueda = tk.Entry(
            search_f, textvariable=self.var_busqueda_prod,
            bg=self.t["bg_input"], fg=self.t["fg_primary"], insertbackground=self.t["fg_primary"],
            relief="solid", bd=1, font=("Segoe UI", 9)
        )
        self.entry_busqueda.pack(side="left", fill="x", expand=True, padx=6)
        self.entry_busqueda.bind("<KeyRelease>", self._filtrar_productos_evento)

        btn_limpiar_b = crear_boton(
            search_f, texto="✖", comando=self._limpiar_busqueda,
            tipo="secondary", ancho=3, alto=1
        )
        btn_limpiar_b.pack(side="right")

        # Lista desplegable / Combobox de productos encontrados
        self.combo_productos = ttk.Combobox(frame, state="readonly", font=("Segoe UI", 9))
        self.combo_productos.pack(fill="x", padx=8, pady=4)
        self.combo_productos.bind("<<ComboboxSelected>>", self._al_seleccionar_producto)
        self.cargar_lista_productos()

        # Edición manual / datos del producto
        detalles_f = tk.Frame(frame, bg=self.t["bg_surface"])
        detalles_f.pack(fill="x", padx=8, pady=4)

        # Nombre producto
        tk.Label(detalles_f, text="Nombre:", bg=self.t["bg_surface"], fg=self.t["fg_secondary"],
                 font=("Segoe UI", 8)).grid(row=0, column=0, sticky="w", pady=2)
        e_nombre = tk.Entry(
            detalles_f, textvariable=self.var_manual_nombre,
            bg=self.t["bg_input"], fg=self.t["fg_primary"], insertbackground=self.t["fg_primary"],
            relief="solid", bd=1, font=("Segoe UI", 9)
        )
        e_nombre.grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=2)
        e_nombre.bind("<KeyRelease>", lambda e: self._actualizar_producto_manual(refrescar_preview=True))

        # Precio
        tk.Label(detalles_f, text="Precio ($):", bg=self.t["bg_surface"], fg=self.t["fg_secondary"],
                 font=("Segoe UI", 8)).grid(row=1, column=0, sticky="w", pady=2)
        e_precio = tk.Entry(
            detalles_f, textvariable=self.var_manual_precio,
            bg=self.t["bg_input"], fg=self.t["fg_primary"], insertbackground=self.t["fg_primary"],
            relief="solid", bd=1, font=("Segoe UI", 9)
        )
        e_precio.grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=2)
        e_precio.bind("<KeyRelease>", lambda e: self._actualizar_producto_manual(refrescar_preview=True))

        # Código de barras y formato
        tk.Label(detalles_f, text="Código Barras:", bg=self.t["bg_surface"], fg=self.t["fg_secondary"],
                 font=("Segoe UI", 8)).grid(row=2, column=0, sticky="w", pady=2)
        e_codigo = tk.Entry(
            detalles_f, textvariable=self.var_manual_codigo,
            bg=self.t["bg_input"], fg=self.t["fg_primary"], insertbackground=self.t["fg_primary"],
            relief="solid", bd=1, font=("Segoe UI", 9, "bold")
        )
        e_codigo.grid(row=2, column=1, sticky="ew", padx=(4, 0), pady=2)
        e_codigo.bind("<KeyRelease>", lambda e: self._actualizar_producto_manual(refrescar_preview=True))

        detalles_f.columnconfigure(1, weight=1)

        # Botones de autogeneración y guardado en SQLite
        btns_bc_f = tk.Frame(frame, bg=self.t["bg_surface"])
        btns_bc_f.pack(fill="x", padx=8, pady=(4, 8))

        btn_auto = crear_boton(
            btns_bc_f, texto="⚡ Autogenerar Único", comando=self.autogenerar_codigo_producto,
            tipo="secondary", alto=1
        )
        btn_auto.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.btn_guardar_db = crear_boton(
            btns_bc_f, texto="💾 Guardar en Inventario", comando=self.guardar_codigo_en_inventario,
            tipo="primary", alto=1
        )
        self.btn_guardar_db.pack(side="right", fill="x", expand=True, padx=(4, 0))

    def cargar_lista_productos(self, filtro=""):
        """Llena el combobox con los productos de inventario."""
        self.lista_prods_db = InventoryBarcodeManager.obtener_productos(filtro)
        opciones = []
        for p in self.lista_prods_db:
            bc_indicador = f"[{p['codigo_barras']}]" if p['codigo_barras'] else "[SIN CÓDIGO]"
            opciones.append(f"{p['codigo']} - {p['nombre']} {bc_indicador}")
        self.combo_productos["values"] = opciones
        if opciones and not filtro:
            self.combo_productos.current(0)
            self._al_seleccionar_producto(None)

    def _filtrar_productos_evento(self, event=None):
        filtro = self.var_busqueda_prod.get()
        self.cargar_lista_productos(filtro)

    def _limpiar_busqueda(self):
        self.var_busqueda_prod.set("")
        self.cargar_lista_productos()

    def _al_seleccionar_producto(self, event=None):
        idx = self.combo_productos.current()
        if idx >= 0 and idx < len(self.lista_prods_db):
            p = self.lista_prods_db[idx]
            self.producto_actual = dict(p)
            self.var_manual_nombre.set(p["nombre"])
            self.var_manual_precio.set(p["precio"])
            # Si no tiene código de barras, dejamos vacío y sugerimos autogenerarlo
            self.var_manual_codigo.set(p["codigo_barras"] or "")
            self.actualizar_vista_previa()

    def _actualizar_producto_manual(self, refrescar_preview=False):
        self.producto_actual["nombre"] = self.var_manual_nombre.get()
        try:
            self.producto_actual["precio"] = float(self.var_manual_precio.get())
        except Exception:
            pass
        self.producto_actual["codigo_barras"] = self.var_manual_codigo.get().strip()
        if refrescar_preview:
            self.actualizar_vista_previa()

    def autogenerar_codigo_producto(self):
        """Genera un código único compatible con el estándar seleccionado."""
        pid = self.producto_actual.get("id")
        fmt = self.var_formato_codigo.get()
        nuevo = InventoryBarcodeManager.generar_codigo_unico(pid, formato=fmt)
        self.var_manual_codigo.set(nuevo)
        self._actualizar_producto_manual(refrescar_preview=True)

    def guardar_codigo_en_inventario(self):
        """Persiste el código de barras en la base de datos para el producto seleccionado."""
        pid = self.producto_actual.get("id")
        if not pid:
            messagebox.showwarning("Atención", "Selecciona primero un producto registrado del inventario.")
            return
        cod = self.var_manual_codigo.get().strip()
        if not cod:
            messagebox.showwarning("Atención", "El código de barras no puede estar vacío.")
            return

        ok, msg = InventoryBarcodeManager.guardar_codigo_en_producto(pid, cod)
        if ok:
            messagebox.showinfo("Éxito", msg)
            self.producto_actual["codigo_barras"] = cod
            self.cargar_lista_productos(self.var_busqueda_prod.get())
        else:
            messagebox.showerror("Error", msg)

    # --------------------------------------------------------------------------
    # BLOQUE 2: ELEMENTOS DE LA ETIQUETA
    # --------------------------------------------------------------------------
    def crear_bloque_2_elementos(self, parent):
        frame = tk.LabelFrame(
            parent, text=" 👁️ 2. Contenido Visible en la Etiqueta ",
            bg=self.t["bg_surface"], fg=self.t["accent"], font=("Segoe UI", 10, "bold"),
            bd=1, relief="solid"
        )
        frame.pack(fill="x", padx=8, pady=6)

        chk_grid = tk.Frame(frame, bg=self.t["bg_surface"])
        chk_grid.pack(fill="x", padx=8, pady=4)

        items = [
            ("Nombre Negocio", self.var_mostrar_negocio),
            ("Logotipo Empresa", self.var_mostrar_logo),
            ("Nombre Producto", self.var_mostrar_nombre),
            ("Precio de Venta", self.var_mostrar_precio),
            ("Código SKU", self.var_mostrar_sku),
            ("Categoría", self.var_mostrar_cat),
            ("Barras Gráficas", self.var_mostrar_img_bc),
            ("Texto del Código", self.var_mostrar_txt_bc),
        ]

        for i, (txt, var) in enumerate(items):
            r = i // 2
            c = i % 2
            cb = tk.Checkbutton(
                chk_grid, text=txt, variable=var,
                bg=self.t["bg_surface"], fg=self.t["fg_primary"],
                selectcolor=self.t["bg_input"], activebackground=self.t["bg_surface"],
                activeforeground=self.t["fg_primary"], font=("Segoe UI", 8),
                command=self.actualizar_vista_previa
            )
            cb.grid(row=r, column=c, sticky="w", padx=4, pady=2)

        # Selector de Estándar de Código de Barras
        fmt_f = tk.Frame(frame, bg=self.t["bg_surface"])
        fmt_f.pack(fill="x", padx=8, pady=(4, 6))

        tk.Label(fmt_f, text="Estándar:", bg=self.t["bg_surface"], fg=self.t["fg_secondary"],
                 font=("Segoe UI", 8, "bold")).pack(side="left")

        cb_fmt = ttk.Combobox(
            fmt_f, textvariable=self.var_formato_codigo,
            values=["CODE128", "EAN-13", "UPC-A", "CODE39"],
            state="readonly", width=12, font=("Segoe UI", 9)
        )
        cb_fmt.pack(side="left", padx=6)
        cb_fmt.bind("<<ComboboxSelected>>", lambda e: self.actualizar_vista_previa())

    # --------------------------------------------------------------------------
    # BLOQUE 3: FORMATO, TAMAÑO E IMPRESIÓN
    # --------------------------------------------------------------------------
    def crear_bloque_3_impresion(self, parent):
        frame = tk.LabelFrame(
            parent, text=" 📐 3. Formato, Medidas (mm) e Impresora ",
            bg=self.t["bg_surface"], fg=self.t["accent"], font=("Segoe UI", 10, "bold"),
            bd=1, relief="solid"
        )
        frame.pack(fill="x", padx=8, pady=6)

        # Tipo de Impresión (Hojas vs Térmica)
        tipo_f = tk.Frame(frame, bg=self.t["bg_surface"])
        tipo_f.pack(fill="x", padx=8, pady=4)

        tk.Radiobutton(
            tipo_f, text="📄 Hoja Etiquetas", variable=self.var_tipo_impresion, value="hoja",
            bg=self.t["bg_surface"], fg=self.t["fg_primary"], selectcolor=self.t["bg_input"],
            font=("Segoe UI", 9, "bold"), command=self._al_cambiar_tipo_impresion
        ).pack(side="left", padx=(0, 10))

        tk.Radiobutton(
            tipo_f, text="🏷️ Térmica Etiquetas", variable=self.var_tipo_impresion, value="termica",
            bg=self.t["bg_surface"], fg=self.t["fg_primary"], selectcolor=self.t["bg_input"],
            font=("Segoe UI", 9, "bold"), command=self._al_cambiar_tipo_impresion
        ).pack(side="left", padx=5)

        tk.Radiobutton(
            tipo_f, text="📜 Rollo Continuo", variable=self.var_tipo_impresion, value="continuo",
            bg=self.t["bg_surface"], fg=self.t["fg_primary"], selectcolor=self.t["bg_input"],
            font=("Segoe UI", 9, "bold"), command=self._al_cambiar_tipo_impresion
        ).pack(side="left", padx=5)

        # Selector de Papel para Hojas
        self.papel_f = tk.Frame(frame, bg=self.t["bg_surface"])
        self.papel_f.pack(fill="x", padx=8, pady=2)

        tk.Label(self.papel_f, text="Papel:", bg=self.t["bg_surface"], fg=self.t["fg_secondary"],
                 font=("Segoe UI", 8)).pack(side="left")
        cb_papel = ttk.Combobox(
            self.papel_f, textvariable=self.var_tamano_papel,
            values=["Carta", "A4", "Oficio", "Personalizado"],
            state="readonly", width=12, font=("Segoe UI", 8)
        )
        cb_papel.pack(side="left", padx=6)
        cb_papel.bind("<<ComboboxSelected>>", lambda e: self.actualizar_vista_previa())

        # Medidas en milímetros (Ancho, Alto, Márgenes, Columnas)
        dim_grid = tk.Frame(frame, bg=self.t["bg_surface"])
        dim_grid.pack(fill="x", padx=8, pady=4)

        def _crear_spin(parent, r, c, label, var, from_=1.0, to_=500.0, step=1.0):
            tk.Label(parent, text=label, bg=self.t["bg_surface"], fg=self.t["fg_secondary"],
                     font=("Segoe UI", 8)).grid(row=r, column=c*2, sticky="w", padx=2, pady=2)
            sp = tk.Spinbox(
                parent, textvariable=var, from_=from_, to=to_, increment=step, width=6,
                bg=self.t["bg_input"], fg=self.t["fg_primary"], insertbackground=self.t["fg_primary"],
                relief="solid", bd=1, font=("Segoe UI", 8), command=self.actualizar_vista_previa
            )
            sp.grid(row=r, column=c*2+1, sticky="w", padx=4, pady=2)
            sp.bind("<KeyRelease>", lambda e: self.actualizar_vista_previa())
            return sp

        _crear_spin(dim_grid, 0, 0, "Ancho mm:", self.var_ancho_etiqueta, from_=15.0, to_=220.0, step=5.0)
        _crear_spin(dim_grid, 0, 1, "Alto mm:", self.var_alto_etiqueta, from_=10.0, to_=220.0, step=5.0)

        _crear_spin(dim_grid, 1, 0, "Margen Izq:", self.var_margen_izq, from_=0.0, to_=50.0, step=1.0)
        _crear_spin(dim_grid, 1, 1, "Margen Sup:", self.var_margen_sup, from_=0.0, to_=50.0, step=1.0)

        _crear_spin(dim_grid, 2, 0, "Sep. X mm:", self.var_sep_x, from_=0.0, to_=30.0, step=1.0)
        _crear_spin(dim_grid, 2, 1, "Sep. Y mm:", self.var_sep_y, from_=0.0, to_=30.0, step=1.0)

        _crear_spin(dim_grid, 3, 0, "Columnas:", self.var_columnas, from_=1, to_=12, step=1)
        _crear_spin(dim_grid, 3, 1, "Filas:", self.var_filas, from_=1, to_=30, step=1)

        # Cantidad de copias
        copias_f = tk.Frame(frame, bg=self.t["bg_surface"])
        copias_f.pack(fill="x", padx=8, pady=4)
        tk.Label(copias_f, text="Copias totales a imprimir:", bg=self.t["bg_surface"],
                 fg=self.t["fg_primary"], font=("Segoe UI", 9, "bold")).pack(side="left")
        sp_copias = tk.Spinbox(
            copias_f, textvariable=self.var_copias, from_=1, to=10000, increment=1, width=7,
            bg=self.t["bg_input"], fg=self.t["fg_primary"], insertbackground=self.t["fg_primary"],
            relief="solid", bd=1, font=("Segoe UI", 9, "bold"), command=self.actualizar_vista_previa
        )
        sp_copias.pack(side="left", padx=8)
        sp_copias.bind("<KeyRelease>", lambda e: self.actualizar_vista_previa())

        # Selector de Impresora
        imp_f = tk.Frame(frame, bg=self.t["bg_surface"])
        imp_f.pack(fill="x", padx=8, pady=(4, 6))

        tk.Label(imp_f, text="Impresora:", bg=self.t["bg_surface"], fg=self.t["fg_secondary"],
                 font=("Segoe UI", 8)).pack(side="left")

        self.combo_impresoras = ttk.Combobox(
            imp_f, textvariable=self.var_impresora, state="readonly", font=("Segoe UI", 8)
        )
        self.combo_impresoras.pack(side="left", fill="x", expand=True, padx=6)
        self.cargar_impresoras()

        btn_prueba = crear_boton(
            imp_f, texto="🖨️ Probar", comando=self.imprimir_prueba,
            tipo="secondary", alto=1
        )
        btn_prueba.pack(side="right")

    def cargar_impresoras(self):
        """Detecta las impresoras del sistema operativo."""
        impresoras = detectar_impresoras_disponibles()
        self.combo_impresoras["values"] = impresoras
        if impresoras and (not self.var_impresora.get() or self.var_impresora.get() not in impresoras):
            self.combo_impresoras.current(0)

    def _al_cambiar_tipo_impresion(self):
        """Ajusta valores predeterminados al alternar entre hoja y térmica."""
        tipo = self.var_tipo_impresion.get()
        if tipo == "termica":
            self.var_ancho_etiqueta.set(50.0)
            self.var_alto_etiqueta.set(30.0)
            self.var_columnas.set(1)
            self.var_filas.set(1)
            self.var_margen_izq.set(0.0)
            self.var_margen_sup.set(0.0)
            self.papel_f.pack_forget()
        elif tipo == "continuo":
            self.var_ancho_etiqueta.set(58.0)
            self.var_alto_etiqueta.set(40.0)
            self.var_columnas.set(1)
            self.var_filas.set(1)
            self.papel_f.pack_forget()
        else:
            self.var_ancho_etiqueta.set(50.0)
            self.var_alto_etiqueta.set(25.0)
            self.var_columnas.set(3)
            self.var_filas.set(8)
            self.var_margen_izq.set(10.0)
            self.var_margen_sup.set(10.0)
            self.papel_f.pack(fill="x", padx=8, pady=2)
        self.actualizar_vista_previa()

    # --------------------------------------------------------------------------
    # BLOQUE 4: VISTA PREVIA DINÁMICA Y ACCIONES
    # --------------------------------------------------------------------------
    def crear_bloque_4_preview_y_acciones(self, parent):
        # Contenedor de vista previa
        preview_box = tk.LabelFrame(
            parent, text=" 🔍 4. Vista Previa en Tiempo Real ",
            bg=self.t["bg_surface"], fg=self.t["accent"], font=("Segoe UI", 10, "bold"),
            bd=1, relief="solid"
        )
        preview_box.pack(fill="both", expand=True, padx=4, pady=6)

        # Barra informativa superior de vista previa
        self.info_preview_lbl = tk.Label(
            preview_box, text="Cálculo de grilla: ...",
            bg=self.t["bg_surface"], fg=self.t["fg_secondary"], font=("Segoe UI", 9)
        )
        self.info_preview_lbl.pack(fill="x", padx=8, pady=4)

        # Canvas con fondo neutro para ver márgenes y hoja
        self.canvas_preview = tk.Canvas(
            preview_box, bg="#505050", highlightthickness=0, relief="flat"
        )
        self.canvas_preview.pack(fill="both", expand=True, padx=8, pady=6)

        # Botonera de Acciones en la parte inferior
        actions_f = tk.Frame(parent, bg=self.t["bg_app"])
        actions_f.pack(fill="x", padx=4, pady=(0, 6))

        btn_act = crear_boton(
            actions_f, texto="🔄 Refrescar", comando=self.actualizar_vista_previa,
            tipo="secondary", alto=2
        )
        btn_act.pack(side="left", fill="x", expand=True, padx=2)

        btn_png = crear_boton(
            actions_f, texto="💾 Guardar PNG", comando=self.guardar_imagen_png,
            tipo="secondary", alto=2
        )
        btn_png.pack(side="left", fill="x", expand=True, padx=2)

        btn_pdf = crear_boton(
            actions_f, texto="📄 Exportar PDF", comando=self.exportar_pdf,
            tipo="secondary", alto=2
        )
        btn_pdf.pack(side="left", fill="x", expand=True, padx=2)

        btn_print = crear_boton(
            actions_f, texto="🖨️ IMPRIMIR", comando=self.imprimir_etiquetas,
            tipo="primary", alto=2
        )
        btn_print.pack(side="left", fill="x", expand=True, padx=2)

        btn_clear = crear_boton(
            actions_f, texto="🧹 Limpiar", comando=self.limpiar_campos,
            tipo="danger", alto=2
        )
        btn_clear.pack(side="left", padx=2)

    # --------------------------------------------------------------------------
    # ACCIONES Y CONTROLADORES
    # --------------------------------------------------------------------------
    def actualizar_vista_previa(self):
        """Genera y dibuja la vista previa fidedigna en el canvas."""
        if not hasattr(self, "canvas_preview") or not hasattr(self, "info_preview_lbl"):
            return

        self._sincronizar_vars_hacia_config()
        self._actualizar_producto_manual(refrescar_preview=False)

        # Recalcular grilla
        grilla = SheetAndThermalLayoutEngine.calcular_grilla(self.config)
        tipo = self.config.get("tipo_impresion", "hoja")

        if tipo == "hoja":
            info_txt = (
                f"Papel {self.config.get('tamano_papel')}: {grilla['cols']} cols × {grilla['filas']} filas "
                f"({grilla['etiquetas_por_pagina']} por página) • {grilla['copias']} copia(s) en {grilla['paginas_totales']} pág(s)."
            )
        else:
            info_txt = (
                f"Térmica {grilla['etiqueta_w']}×{grilla['etiqueta_h']} mm • "
                f"{grilla['copias']} etiqueta(s) en cola continua."
            )
        self.info_preview_lbl.config(text=info_txt)

        # Generar imagen de preview según el modo
        canv_w = self.canvas_preview.winfo_width() or 480
        canv_h = self.canvas_preview.winfo_height() or 400

        max_dim = min(canv_w - 20, canv_h - 20)
        if max_dim < 120:
            max_dim = 380

        if tipo == "hoja":
            preview_img = SheetAndThermalLayoutEngine.renderizar_hoja_preview(
                self.producto_actual, self.config, max_preview_px=max_dim
            )
        else:
            preview_img = LabelDesignEngine.renderizar_etiqueta(
                self.producto_actual, self.config, grilla["etiqueta_w"], grilla["etiqueta_h"], dpi=150
            )

        # Mostrar en canvas
        self.tk_preview_img = ImageTk.PhotoImage(preview_img)
        self.canvas_preview.delete("all")
        cx = canv_w / 2.0
        cy = canv_h / 2.0
        self.canvas_preview.create_image(cx, cy, image=self.tk_preview_img, anchor="center")

    def guardar_imagen_png(self):
        """Exporta la etiqueta individual o la hoja completa a un archivo PNG."""
        self._sincronizar_vars_hacia_config()
        ruta = filedialog.asksaveasfilename(
            title="Guardar Imagen de Etiqueta",
            defaultextension=".png",
            filetypes=[("Imagen PNG", "*.png"), ("Todos los archivos", "*.*")],
            initialfile=f"etiqueta_{self.producto_actual.get('codigo', 'prod')}.png"
        )
        if not ruta:
            return

        try:
            grilla = SheetAndThermalLayoutEngine.calcular_grilla(self.config)
            tipo = self.config.get("tipo_impresion", "hoja")
            if tipo == "hoja":
                img = SheetAndThermalLayoutEngine.renderizar_hoja_preview(
                    self.producto_actual, self.config, max_preview_px=1400
                )
            else:
                img = LabelDesignEngine.renderizar_etiqueta(
                    self.producto_actual, self.config, grilla["etiqueta_w"], grilla["etiqueta_h"], dpi=300
                )
            img.save(ruta, "PNG")
            messagebox.showinfo("Guardado", f"Imagen guardada exitosamente en:\n{ruta}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar la imagen: {e}")

    def exportar_pdf(self):
        """Exporta la diagramación a PDF vectorial con ReportLab."""
        self._sincronizar_vars_hacia_config()
        ruta = filedialog.asksaveasfilename(
            title="Exportar Etiquetas a PDF",
            defaultextension=".pdf",
            filetypes=[("Documento PDF", "*.pdf"), ("Todos los archivos", "*.*")],
            initialfile=f"etiquetas_{self.producto_actual.get('codigo', 'prod')}.pdf"
        )
        if not ruta:
            return

        ok, msg = PdfEngine.exportar_pdf(ruta, self.producto_actual, self.config)
        if ok:
            messagebox.showinfo("Exportación Exitosa", msg)
        else:
            messagebox.showerror("Error al Exportar PDF", msg)

    def imprimir_etiquetas(self):
        """Envía el trabajo a la impresora configurada."""
        self._sincronizar_vars_hacia_config()
        self.guardar_configuracion()
        ok, msg = PrintEngine.imprimir_etiquetas(self.producto_actual, self.config)
        if ok:
            messagebox.showinfo("🖨️ Impresión Enviada", msg)
        else:
            messagebox.showwarning("Aviso de Impresión", msg)

    def imprimir_prueba(self):
        """Imprime una sola etiqueta de diagnóstico para calibrar márgenes."""
        cfg_prueba = dict(self.config)
        cfg_prueba["copias"] = 1
        prod_prueba = {
            "id": 0,
            "codigo": "PRUEBA",
            "nombre": "Etiqueta Diagnóstico Calibración",
            "precio": 99999.0,
            "codigo_barras": "770123456789",
            "categoria": "Calibracion"
        }
        ok, msg = PrintEngine.imprimir_etiquetas(prod_prueba, cfg_prueba)
        if ok:
            messagebox.showinfo("Prueba Enviada", f"Prueba enviada: {msg}")
        else:
            messagebox.showwarning("Aviso de Prueba", msg)

    def limpiar_campos(self):
        """Restaura los valores por defecto."""
        self.var_busqueda_prod.set("")
        self.cargar_lista_productos()
        self.var_manual_nombre.set("Producto Nuevo")
        self.var_manual_precio.set(0.0)
        self.var_manual_codigo.set("")
        self._actualizar_producto_manual(refrescar_preview=True)


# ==============================================================================
# PUNTO DE ENTRADA AUTÓNOMO / MODULAR
# ==============================================================================
def iniciar_generador_codigo_barras(parent=None, parent_pid=""):
    """Punto de entrada estándar para instanciar el generador."""
    app = GeneradorCodigoBarras(parent=parent, parent_pid=parent_pid)
    if not parent:
        app.ventana.mainloop()
    return app

# Alias de compatibilidad con menu_inicio.py
iniciar_generador_barras = iniciar_generador_codigo_barras


if __name__ == "__main__":
    iniciar_generador_codigo_barras()