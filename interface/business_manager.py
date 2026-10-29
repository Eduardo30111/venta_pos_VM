#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo de Gestión de Identidad del Negocio e Impresión (Marca Blanca / Whitelabel) - VmPOS
Archivo: interface/business_manager.py

Fuente única de verdad (Single Source of Truth) para:
- Datos comerciales y fiscales del negocio (Nombre comercial, Razón social, NIT/RUT/Documento,
  Dirección, Ciudad, Teléfono, Correo, Eslogan, Tipo de comprobante).
- Gestión de logo institucional (validación con Pillow, normalización PNG, bitmap térmico 1-bit,
  reemplazo sin caché huérfana y eliminación limpia).
- Preferencias de impresora y formato de factura por estación de trabajo (58mm, 80mm, A4,
  márgenes, fuente, densidad, alineación, campos visibles, copias, corte automático).
- Persistencia dual atómica (JSON en config/ + respaldo en SQLite database/ventas.db).
- Notificación en vivo (Observer pattern) para refrescar Menú de Inicio y módulos abiertos sin reiniciar.
"""

import os
import sys
import json
import time
import shutil
import sqlite3
import tempfile

try:
    from PIL import Image, ImageOps
    PIL_DISPONIBLE = True
except ImportError:
    PIL_DISPONIBLE = False

# Rutas centralizadas y seguras para desarrollo y ejecutable empaquetado
try:
    from interface.config import CONFIG_DIR, DB_VENTAS_PATH, LOGOS_DIR, USER_DATA_DIR, BUNDLE_DIR
except ImportError:
    try:
        from config import CONFIG_DIR, DB_VENTAS_PATH, LOGOS_DIR, USER_DATA_DIR, BUNDLE_DIR
    except ImportError:
        _curr = os.path.dirname(os.path.abspath(__file__))
        _root = os.path.abspath(os.path.join(_curr, ".."))
        CONFIG_DIR = os.path.join(_root, "config")
        DB_VENTAS_PATH = os.path.join(_root, "database", "ventas.db")
        LOGOS_DIR = os.path.join(_root, "assets", "logos")

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
CONFIG_FILE = os.path.join(CONFIG_DIR, "business_config.json")
PRINTER_CONFIG_FILE = os.path.join(CONFIG_DIR, "printer_config.json")

CONFIG_POR_DEFECTO = {
    "nombre_negocio": "VmPOS",
    "razon_social": "",
    "subtitulo_negocio": "",
    "tipo_documento_fiscal": "NIT",
    "nit": "",
    "regimen_fiscal": "",
    "direccion": "",
    "ciudad": "",
    "telefono": "",
    "email": "",
    "eslogan": "¡Gracias por su compra!",
    "encabezado_recibo": "",
    "tipo_comprobante": "RECIBO DE VENTA",
    "prefijo_comprobante": "",
    "color_barra": "#DB2777",
    "color_login": "#DB2777",
    "logo_path": "",
    "logo_thermal_path": ""
}

PRINTER_CONFIG_POR_DEFECTO = {
    "formato_papel": "58mm",            # "58mm", "80mm", "A4"
    "impresora_nombre": "Predeterminada del sistema",
    "metodo_impresion": "auto",         # "auto", "sistema", "escpos_usb", "solo_pdf"
    "ancho_papel_mm": 58,               # 58, 80, 210
    "margen_mm": 2,                     # 0 .. 20
    "tamano_fuente": "normal",          # "pequena", "normal", "grande"
    "densidad": "normal",               # "compacta", "normal", "amplia"
    "alineacion_encabezado": "center",  # "center", "left"
    "mostrar_logo": True,
    "mostrar_razon_social": True,
    "mostrar_nit": True,
    "mostrar_regimen": True,
    "mostrar_direccion": True,
    "mostrar_telefono": True,
    "mostrar_email": False,
    "mostrar_cliente": True,
    "mostrar_vendedor": True,
    "mostrar_eslogan": True,
    "pie_factura_extra": "",
    "copias": 1,
    "corte_automatico": True,
    "abrir_cajon": False,
    "usb_vendor_id": "",
    "usb_product_id": ""
}

PALETAS_PREDEFINIDAS = [
    ("Fucsia VmPOS", "#DB2777"),
    ("Azul Corporativo", "#1E40AF"),
    ("Celeste Moderno", "#0284C7"),
    ("Verde Esmeralda", "#059669"),
    ("Púrpura Amatista", "#7C3AED"),
    ("Índigo Elegante", "#4F46E5"),
    ("Ámbar Cálido", "#D97706"),
    ("Rojo Carmesí", "#DC2626"),
    ("Gris Pizarra", "#334155")
]

FORMATOS_PAPEL_DISPONIBLES = [
    ("58mm", "Térmico 58 mm (Tirilla estándar 32 col.)"),
    ("80mm", "Térmico 80 mm (Tirilla ancha 48 col.)"),
    ("A4", "Página completa A4 (210 × 297 mm)")
]

TIPOS_COMPROBANTE_DISPONIBLES = [
    "RECIBO DE VENTA",
    "COMPROBANTE COMERCIAL",
    "FACTURA DE VENTA POS",
    "NOTA DE ENTREGA"
]

TIPOS_DOCUMENTO_FISCAL = [
    "NIT",
    "RUT",
    "CC",
    "CE",
    "Documento"
]


class BusinessManager:
    def __init__(self):
        self._config = dict(CONFIG_POR_DEFECTO)
        self._printer_config = dict(PRINTER_CONFIG_POR_DEFECTO)
        self._listeners = []
        self._asegurar_tablas_sqlite()
        self.cargar()
        self.cargar_config_impresora()

    # =========================================================================
    # RESPALDO EN SQLITE (ventas.db)
    # =========================================================================
    def _asegurar_tablas_sqlite(self):
        """Crea la tabla de configuración en ventas.db para respaldo transaccional."""
        try:
            os.makedirs(os.path.dirname(DB_VENTAS_PATH), exist_ok=True)
            with sqlite3.connect(DB_VENTAS_PATH, timeout=5.0) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS configuracion_negocio (
                        clave TEXT PRIMARY KEY,
                        valor_json TEXT NOT NULL,
                        actualizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
        except Exception as e:
            print(f"Aviso al inicializar tabla configuracion_negocio en SQLite: {e}")

    def _guardar_en_sqlite(self, clave, dic_datos):
        try:
            self._asegurar_tablas_sqlite()
            payload = json.dumps(dic_datos, ensure_ascii=False)
            with sqlite3.connect(DB_VENTAS_PATH, timeout=5.0) as conn:
                conn.execute("""
                    INSERT INTO configuracion_negocio (clave, valor_json, actualizado_en)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(clave) DO UPDATE SET
                        valor_json = excluded.valor_json,
                        actualizado_en = CURRENT_TIMESTAMP
                """, (clave, payload))
                conn.commit()
        except Exception as e:
            print(f"Aviso al respaldar {clave} en SQLite: {e}")

    def _cargar_desde_sqlite(self, clave):
        try:
            if not os.path.exists(DB_VENTAS_PATH):
                return None
            with sqlite3.connect(DB_VENTAS_PATH, timeout=5.0) as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='configuracion_negocio'"
                )
                if not cur.fetchone():
                    return None
                cur.execute("SELECT valor_json FROM configuracion_negocio WHERE clave = ?", (clave,))
                row = cur.fetchone()
                if row and row[0]:
                    datos = json.loads(row[0])
                    if isinstance(datos, dict):
                        return datos
        except Exception as e:
            print(f"Aviso al leer {clave} desde SQLite: {e}")
        return None

    # =========================================================================
    # RESOLUCIÓN DE RUTAS DE ARCHIVOS (PORTABILIDAD)
    # =========================================================================
    def _resolver_ruta_logo(self, ruta_guardada):
        """Resuelve una ruta de logo relativa o absoluta verificando su existencia."""
        if not ruta_guardada or not isinstance(ruta_guardada, str):
            return ""
        ruta_guardada = ruta_guardada.strip()
        if not ruta_guardada:
            return ""
        # 1. Si es relativa a BASE_DIR
        if not os.path.isabs(ruta_guardada):
            candidata = os.path.join(BASE_DIR, ruta_guardada)
            if os.path.isfile(candidata):
                return candidata
        # 2. Si es absoluta y existe
        if os.path.isabs(ruta_guardada) and os.path.isfile(ruta_guardada):
            return ruta_guardada
        # 3. Buscar por basename dentro de LOGOS_DIR (por si se movió la carpeta del proyecto)
        basename = os.path.basename(ruta_guardada)
        if basename:
            candidata_logos = os.path.join(LOGOS_DIR, basename)
            if os.path.isfile(candidata_logos):
                return candidata_logos
        return ""

    def _hacer_ruta_relativa(self, ruta_absoluta):
        """Convierte una ruta dentro de BASE_DIR a ruta relativa para portabilidad."""
        if not ruta_absoluta:
            return ""
        try:
            abs_target = os.path.abspath(ruta_absoluta)
            abs_base = os.path.abspath(BASE_DIR)
            if abs_target.startswith(abs_base + os.sep):
                return os.path.relpath(abs_target, abs_base)
        except Exception:
            pass
        return ruta_absoluta

    # =========================================================================
    # CARGA Y GUARDADO DE IDENTIDAD DEL NEGOCIO
    # =========================================================================
    def cargar(self):
        """Carga la configuración del negocio desde JSON o respaldo SQLite."""
        datos_cargados = None
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    datos = json.load(f)
                    if isinstance(datos, dict):
                        datos_cargados = datos
            except Exception as e:
                print(f"Aviso al cargar business_config.json: {e}")

        if datos_cargados is None:
            datos_cargados = self._cargar_desde_sqlite("business_config")

        if isinstance(datos_cargados, dict):
            self._config.update(datos_cargados)
            # Asegurar que todas las claves nuevas existan
            for k, v in CONFIG_POR_DEFECTO.items():
                if k not in self._config or self._config[k] is None:
                    self._config[k] = v

        # Validar que el logo configurado realmente exista en disco
        logo_resuelto = self._resolver_ruta_logo(self._config.get("logo_path", ""))
        self._config["logo_path"] = logo_resuelto if logo_resuelto else ""

        thermal_resuelto = self._resolver_ruta_logo(self._config.get("logo_thermal_path", ""))
        self._config["logo_thermal_path"] = thermal_resuelto if thermal_resuelto else ""

        return self._config

    def recargar(self):
        """Recarga desde disco los datos del negocio y de la impresora."""
        self._config = dict(CONFIG_POR_DEFECTO)
        self.cargar()
        self.cargar_config_impresora()
        return self._config

    def guardar(self, nuevos_datos=None, notificar=True):
        """Guarda la configuración del negocio de forma atómica en JSON y SQLite."""
        if nuevos_datos and isinstance(nuevos_datos, dict):
            for k, v in nuevos_datos.items():
                self._config[k] = v if v is not None else ""

        # Asegurar nombre comercial mínimo si lo dejaron completamente vacío
        if not str(self._config.get("nombre_negocio", "")).strip():
            self._config["nombre_negocio"] = "VmPOS"

        # Preparar copia serializable con rutas relativas para portabilidad
        datos_para_disco = dict(self._config)
        if datos_para_disco.get("logo_path"):
            logo_abs = self._resolver_ruta_logo(datos_para_disco["logo_path"])
            datos_para_disco["logo_path"] = self._hacer_ruta_relativa(logo_abs) if logo_abs else ""
            self._config["logo_path"] = logo_abs
        if datos_para_disco.get("logo_thermal_path"):
            th_abs = self._resolver_ruta_logo(datos_para_disco["logo_thermal_path"])
            datos_para_disco["logo_thermal_path"] = self._hacer_ruta_relativa(th_abs) if th_abs else ""
            self._config["logo_thermal_path"] = th_abs

        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            fd, temp_path = tempfile.mkstemp(prefix="business_config_", suffix=".json", dir=CONFIG_DIR)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(datos_para_disco, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, CONFIG_FILE)
            self._guardar_en_sqlite("business_config", datos_para_disco)
            if notificar:
                self.notificar_cambio()
            return True
        except Exception as e:
            try:
                if "temp_path" in locals() and os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass
            print(f"Error al guardar business_config.json: {e}")
            return False

    def obtener(self, clave, valor_por_defecto=None):
        """Obtiene un valor de la configuración del negocio."""
        if clave == "logo_path":
            return self.logo_path
        if clave == "logo_thermal_path":
            return self.logo_thermal_path
        if clave in self._config:
            val = self._config.get(clave)
            if val is not None:
                return val
        return valor_por_defecto if valor_por_defecto is not None else CONFIG_POR_DEFECTO.get(clave, "")

    def establecer(self, clave, valor):
        """Establece un valor y lo persiste."""
        self._config[clave] = valor
        return self.guardar()

    # =========================================================================
    # CARGA Y GUARDADO DE CONFIGURACIÓN DE IMPRESORA Y FORMATO
    # =========================================================================
    def cargar_config_impresora(self):
        """Carga las preferencias de impresora y formato de factura de la estación."""
        self._printer_config = dict(PRINTER_CONFIG_POR_DEFECTO)
        datos_cargados = None
        if os.path.exists(PRINTER_CONFIG_FILE):
            try:
                with open(PRINTER_CONFIG_FILE, "r", encoding="utf-8") as f:
                    datos = json.load(f)
                    if isinstance(datos, dict):
                        datos_cargados = datos
            except Exception as e:
                print(f"Aviso al cargar printer_config.json: {e}")

        if datos_cargados is None:
            datos_cargados = self._cargar_desde_sqlite("printer_config")

        if isinstance(datos_cargados, dict):
            self._printer_config.update(datos_cargados)

        # Normalizar formato y ancho
        fmt = str(self._printer_config.get("formato_papel", "58mm")).strip()
        if fmt not in ("58mm", "80mm", "A4"):
            fmt = "58mm"
        self._printer_config["formato_papel"] = fmt
        if fmt == "58mm":
            self._printer_config["ancho_papel_mm"] = 58
        elif fmt == "80mm":
            self._printer_config["ancho_papel_mm"] = 80
        else:
            self._printer_config["ancho_papel_mm"] = 210

        try:
            copias = int(self._printer_config.get("copias", 1))
            self._printer_config["copias"] = max(1, min(10, copias))
        except Exception:
            self._printer_config["copias"] = 1

        try:
            margen = int(self._printer_config.get("margen_mm", 2))
            self._printer_config["margen_mm"] = max(0, min(25, margen))
        except Exception:
            self._printer_config["margen_mm"] = 2

        return dict(self._printer_config)

    def guardar_config_impresora(self, nuevos_datos=None, notificar=True):
        """Persiste la configuración de impresora y formato de factura."""
        if nuevos_datos and isinstance(nuevos_datos, dict):
            self._printer_config.update(nuevos_datos)

        fmt = str(self._printer_config.get("formato_papel", "58mm")).strip()
        if fmt not in ("58mm", "80mm", "A4"):
            fmt = "58mm"
        self._printer_config["formato_papel"] = fmt
        if fmt == "58mm":
            self._printer_config["ancho_papel_mm"] = 58
        elif fmt == "80mm":
            self._printer_config["ancho_papel_mm"] = 80
        else:
            self._printer_config["ancho_papel_mm"] = 210

        try:
            self._printer_config["copias"] = max(1, min(10, int(self._printer_config.get("copias", 1))))
        except Exception:
            self._printer_config["copias"] = 1

        try:
            self._printer_config["margen_mm"] = max(0, min(25, int(self._printer_config.get("margen_mm", 2))))
        except Exception:
            self._printer_config["margen_mm"] = 2

        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            fd, temp_path = tempfile.mkstemp(prefix="printer_config_", suffix=".json", dir=CONFIG_DIR)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._printer_config, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, PRINTER_CONFIG_FILE)
            self._guardar_en_sqlite("printer_config", self._printer_config)
            if notificar:
                self.notificar_cambio()
            return True
        except Exception as e:
            try:
                if "temp_path" in locals() and os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass
            print(f"Error al guardar printer_config.json: {e}")
            return False

    def obtener_config_impresora(self):
        """Retorna una copia del diccionario de configuración de impresora."""
        return dict(self._printer_config)

    def obtener_impresora(self, clave, valor_por_defecto=None):
        """Obtiene un valor puntual de la configuración de impresora."""
        if clave in self._printer_config:
            return self._printer_config[clave]
        return valor_por_defecto if valor_por_defecto is not None else PRINTER_CONFIG_POR_DEFECTO.get(clave)

    # =========================================================================
    # GESTIÓN DE LOGO (VALIDACIÓN, CONVERSIÓN TÉRMICA, REEMPLAZO Y ELIMINACIÓN)
    # =========================================================================
    def validar_archivo_imagen(self, ruta_archivo):
        """
        Valida que un archivo exista, no esté vacío y sea una imagen soportada.
        Retorna (es_valido: bool, mensaje_error_o_formato: str)
        """
        if not ruta_archivo or not isinstance(ruta_archivo, str):
            return False, "No se especificó una ruta de archivo."
        if not os.path.exists(ruta_archivo) or not os.path.isfile(ruta_archivo):
            return False, "El archivo seleccionado no existe."
        tamano = os.path.getsize(ruta_archivo)
        if tamano == 0:
            return False, "El archivo seleccionado está vacío (0 bytes)."
        if tamano > 15 * 1024 * 1024:
            return False, "El archivo supera el tamaño máximo permitido (15 MB)."

        if not PIL_DISPONIBLE:
            _, ext = os.path.splitext(ruta_archivo)
            if ext.lower() not in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"):
                return False, "Formato de imagen no soportado."
            return True, ext.upper()

        try:
            with Image.open(ruta_archivo) as img:
                img.verify()
            with Image.open(ruta_archivo) as img2:
                img2.load()
                ancho, alto = img2.size
                if ancho < 8 or alto < 8:
                    return False, "La imagen es demasiado pequeña (mínimo 8×8 píxeles)."
                formato = (img2.format or "PNG").upper()
                return True, formato
        except Exception as e:
            return False, f"El archivo no es una imagen válida o está corrupto ({e})."

    def _generar_bitmap_termico(self, img_pil, ruta_salida_thermal, max_width=384):
        """
        Convierte una imagen PIL a versión monocromática 1-bit de alto contraste
        optimizada para cabezales térmicos ESC/POS (58mm = 384 dots, 80mm = 576 dots).
        """
        try:
            # Si tiene canal alfa, componer sobre fondo blanco puro
            if img_pil.mode in ("RGBA", "LA") or (img_pil.mode == "P" and "transparency" in img_pil.info):
                rgba = img_pil.convert("RGBA")
                fondo = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                compuesta = Image.alpha_composite(fondo, rgba).convert("RGB")
            else:
                compuesta = img_pil.convert("RGB")

            # Recortar bordes blancos excesivos automáticamente
            invertida = ImageOps.invert(compuesta.convert("L"))
            bbox = invertida.getbbox()
            if bbox:
                compuesta = compuesta.crop(bbox)

            # Redimensionar manteniendo proporción (ancho ideal para ticket: 240 px centrado)
            target_w = min(max_width, max(120, compuesta.width))
            if compuesta.width > target_w or compuesta.height > 180:
                compuesta.thumbnail((target_w, 180), Image.Resampling.LANCZOS)

            # El ancho en bytes para ESC/POS GS v 0 debe ser múltiplo de 8
            nuevo_ancho = ((compuesta.width + 7) // 8) * 8
            if nuevo_ancho != compuesta.width:
                lienzo = Image.new("RGB", (nuevo_ancho, compuesta.height), (255, 255, 255))
                offset_x = (nuevo_ancho - compuesta.width) // 2
                lienzo.paste(compuesta, (offset_x, 0))
                compuesta = lienzo

            # Mejorar contraste y convertir a 1-bit monocromático
            gris = ImageOps.autocontrast(compuesta.convert("L"), cutoff=2)
            # Umbral limpio para logos (evita puntillismo excesivo en fondos claros)
            bw = gris.point(lambda x: 0 if x < 165 else 255, mode="1")
            bw.save(ruta_salida_thermal, format="PNG")
            return True
        except Exception as e:
            print(f"Aviso al generar bitmap térmico: {e}")
            return False

    def _limpiar_logos_anteriores(self, excepto_archivos=None):
        """Elimina archivos de logos previos en assets/logos/ para evitar basura o caché."""
        excepto = set(os.path.abspath(p) for p in (excepto_archivos or []) if p)
        try:
            if not os.path.exists(LOGOS_DIR):
                return
            for nombre in os.listdir(LOGOS_DIR):
                if nombre.startswith("logo_negocio") or nombre.startswith("logo_thermal"):
                    ruta_full = os.path.abspath(os.path.join(LOGOS_DIR, nombre))
                    if ruta_full not in excepto and os.path.isfile(ruta_full):
                        try:
                            os.remove(ruta_full)
                        except Exception:
                            pass
        except Exception:
            pass

    def guardar_logo(self, ruta_archivo_origen, persistir=True):
        """
        Valida, normaliza y guarda una imagen de logo en assets/logos/,
        generando tanto la versión UI/PDF (PNG) como la versión térmica 1-bit.
        Retorna (exito: bool, ruta_destino_o_mensaje_error: str)
        """
        es_valido, detalle = self.validar_archivo_imagen(ruta_archivo_origen)
        if not es_valido:
            return False, detalle

        try:
            os.makedirs(LOGOS_DIR, exist_ok=True)
            sello = int(time.time() * 1000)
            nombre_destino = f"logo_negocio_{sello}.png"
            nombre_thermal = f"logo_thermal_{sello}.png"
            ruta_destino = os.path.join(LOGOS_DIR, nombre_destino)
            ruta_thermal = os.path.join(LOGOS_DIR, nombre_thermal)

            if PIL_DISPONIBLE:
                with Image.open(ruta_archivo_origen) as img_orig:
                    img_orig.load()
                    # Conservar RGBA para UI y PDF, redimensionando si supera 800x800
                    if img_orig.mode not in ("RGB", "RGBA"):
                        img_ui = img_orig.convert("RGBA")
                    else:
                        img_ui = img_orig.copy()
                    img_ui.thumbnail((800, 800), Image.Resampling.LANCZOS)
                    img_ui.save(ruta_destino, format="PNG", optimize=True)
                    # Generar versión térmica monocromática
                    self._generar_bitmap_termico(img_ui, ruta_thermal)
            else:
                shutil.copy2(ruta_archivo_origen, ruta_destino)
                ruta_thermal = ""

            self._limpiar_logos_anteriores(excepto_archivos=[ruta_destino, ruta_thermal])
            self._config["logo_path"] = ruta_destino
            self._config["logo_thermal_path"] = ruta_thermal if os.path.exists(ruta_thermal) else ""

            if persistir:
                self.guardar()
            return True, ruta_destino
        except Exception as e:
            return False, f"No se pudo procesar el logo: {e}"

    def eliminar_logo(self, persistir=True):
        """Elimina el logo personalizado y deja la configuración sin logo."""
        self._limpiar_logos_anteriores(excepto_archivos=[])
        self._config["logo_path"] = ""
        self._config["logo_thermal_path"] = ""
        if persistir:
            self.guardar()
        return True

    # =========================================================================
    # LISTENERS / OBSERVADORES PARA REFRESCO EN VIVO
    # =========================================================================
    def agregar_listener(self, callback):
        """Registra una función callback que se invocará al guardar cambios."""
        if callable(callback) and callback not in self._listeners:
            self._listeners.append(callback)

    def eliminar_listener(self, callback):
        """Elimina un listener previamente registrado."""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def notificar_cambio(self):
        """Notifica a todas las ventanas activas que la configuración cambió."""
        for cb in list(self._listeners):
            try:
                cb()
            except Exception as e:
                print(f"Aviso al notificar listener de BusinessManager: {e}")

    # =========================================================================
    # PROPIEDADES Y HELPERS DE PRESENTACIÓN / SNAPSHOT
    # =========================================================================
    @property
    def nombre(self):
        val = str(self._config.get("nombre_negocio", "")).strip()
        return val if val else "VmPOS"

    @property
    def razon_social(self):
        return str(self._config.get("razon_social", "")).strip()

    @property
    def subtitulo(self):
        """
        Retorna el subtítulo configurado, o la razón social si no hay subtítulo.
        Nunca fuerza un texto quemado si el usuario decidió dejarlo vacío.
        """
        sub = str(self._config.get("subtitulo_negocio", "")).strip()
        if sub:
            return sub
        return str(self._config.get("razon_social", "")).strip()

    @property
    def nit(self):
        return str(self._config.get("nit", "")).strip()

    @property
    def tipo_documento_fiscal(self):
        val = str(self._config.get("tipo_documento_fiscal", "NIT")).strip()
        return val if val else "NIT"

    @property
    def direccion(self):
        return str(self._config.get("direccion", "")).strip()

    @property
    def ciudad(self):
        return str(self._config.get("ciudad", "")).strip()

    @property
    def telefono(self):
        return str(self._config.get("telefono", "")).strip()

    @property
    def email(self):
        return str(self._config.get("email", "")).strip()

    @property
    def eslogan(self):
        return str(self._config.get("eslogan", "")).strip()

    @property
    def color_barra(self):
        val = str(self._config.get("color_barra", "#DB2777")).strip()
        return val if val.startswith("#") and len(val) in (4, 7) else "#DB2777"

    @property
    def color_login(self):
        val = str(self._config.get("color_login", "#DB2777")).strip()
        return val if val.startswith("#") and len(val) in (4, 7) else "#DB2777"

    @property
    def logo_path(self):
        resuelto = self._resolver_ruta_logo(self._config.get("logo_path", ""))
        return resuelto

    @property
    def logo_thermal_path(self):
        resuelto = self._resolver_ruta_logo(self._config.get("logo_thermal_path", ""))
        if resuelto:
            return resuelto
        # Si hay logo normal pero aún no existe el térmico, generarlo al vuelo
        logo_normal = self.logo_path
        if logo_normal and PIL_DISPONIBLE:
            try:
                os.makedirs(LOGOS_DIR, exist_ok=True)
                ruta_th = os.path.join(LOGOS_DIR, "logo_thermal_auto.png")
                with Image.open(logo_normal) as im:
                    if self._generar_bitmap_termico(im, ruta_th):
                        self._config["logo_thermal_path"] = ruta_th
                        return ruta_th
            except Exception:
                pass
        return ""

    def obtener_texto_ubicacion_contacto(self):
        """
        Construye dinámicamente el texto para el pie de página de los módulos
        usando únicamente los datos reales configurados por el negocio.
        """
        partes = []
        dir_txt = self.direccion
        ciu_txt = self.ciudad
        if dir_txt and ciu_txt and ciu_txt.lower() not in dir_txt.lower():
            ubicacion = f"{dir_txt}, {ciu_txt}"
        else:
            ubicacion = dir_txt or ciu_txt

        if ubicacion:
            partes.append(f"📍 {ubicacion}")
        if self.telefono:
            partes.append(f"📞 {self.telefono}")
        if self.nit:
            partes.append(f"{self.tipo_documento_fiscal}: {self.nit}")

        if partes:
            return "  •  ".join(partes)

        # Si el negocio no configuró ubicación ni teléfono ni NIT, mostrar nombre comercial + subtítulo
        if self.subtitulo:
            return f"🏪 {self.nombre}  •  {self.subtitulo}"
        return f"🏪 {self.nombre}  •  Sistema POS"

    def obtener_snapshot_factura(self):
        """
        Retorna una copia inmutable de los datos del negocio en el instante actual
        para almacenarla junto con la venta y preservar la integridad histórica.
        """
        return {
            "nombre_negocio": self.nombre,
            "razon_social": self.razon_social,
            "subtitulo_negocio": str(self._config.get("subtitulo_negocio", "")).strip(),
            "tipo_documento_fiscal": self.tipo_documento_fiscal,
            "nit": self.nit,
            "regimen_fiscal": str(self._config.get("regimen_fiscal", "")).strip(),
            "direccion": self.direccion,
            "ciudad": self.ciudad,
            "telefono": self.telefono,
            "email": self.email,
            "eslogan": self.eslogan,
            "encabezado_recibo": str(self._config.get("encabezado_recibo", "")).strip(),
            "tipo_comprobante": str(self._config.get("tipo_comprobante", "RECIBO DE VENTA")).strip() or "RECIBO DE VENTA",
            "prefijo_comprobante": str(self._config.get("prefijo_comprobante", "")).strip(),
            "logo_path": self._hacer_ruta_relativa(self.logo_path) if self.logo_path else "",
            "logo_thermal_path": self._hacer_ruta_relativa(self.logo_thermal_path) if self.logo_thermal_path else ""
        }


# Instancia singleton accesible para toda la app
business_mgr = BusinessManager()
