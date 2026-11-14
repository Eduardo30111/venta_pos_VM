#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivo: table_filter_sorter.py
Módulo utilitario universal para búsqueda, filtrado multinivel y ordenamiento
profesional con flechas indicadoras en ttk.Treeview para VmPOS.

Características principales:
1. Ordenamiento cíclico de columnas: Ascendente (▲) -> Descendente (▼) -> Orden Original (sin flecha).
2. Manejo inteligente de tipos de datos:
   - Numérico / Stock: Flotantes y enteros positivos/negativos, maneja unidades ('10 und').
   - Moneda / Precios / Costos: Limpia símbolos de moneda, separadores de miles y decimales.
   - Códigos / SKU: Ordenamiento natural ('MAT-2' antes de 'MAT-10', ceros a la izquierda).
   - Fechas y Horas: Conversión cronológica ISO/datetime.
   - Texto / Categorías / Proveedores: Insensible a mayúsculas/minúsculas y a tildes/acentos (Unicode NFKD).
3. Motor de búsqueda multi-campo con coincidencia parcial e insensibilidad a tildes.
4. Preservación bidireccional del estado de ordenamiento al filtrar y viceversa.
5. Inserción elegante de estados vacíos cuando no hay coincidencias.
"""

import re
import unicodedata
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple, Union


def normalizar_texto(texto: Any) -> str:
    """Normaliza un texto eliminando tildes, diacríticos y convirtiendo a minúsculas para búsquedas y comparaciones justas."""
    if texto is None:
        return ""
    s = str(texto)
    # Descomposición canónica NFKD y descarte de marcas de combinación (acentos/tildes)
    return unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode("utf-8").lower().strip()


def extraer_clave_orden(val: Any, tipo: str = "auto", col_name: str = "") -> Any:
    """Extrae una clave de comparación adecuada según el tipo de datos de la columna."""
    if tipo == "auto":
        c_l = (col_name or "").lower()
        if any(k in c_l for k in ("precio", "costo", "total", "valor", "margen", "monto")):
            tipo = "currency"
        elif any(k in c_l for k in ("stock", "disponible", "recibido", "consumido", "desperdicio", "devuelto", "cantidad", "saldo", "id", "nº", "numero", "items", "factor")):
            tipo = "numeric"
        elif any(k in c_l for k in ("sku", "codigo", "código", "doc", "factura", "referencia")):
            tipo = "sku"
        elif any(k in c_l for k in ("fecha", "hora", "actualizacion", "actualización", "movimiento")):
            tipo = "date"
        else:
            tipo = "text"

    # 1. Códigos y SKUs (Orden Natural Alfanumérico)
    if tipo == "sku":
        if val is None or str(val).strip() in ("", "—"):
            return ["", 0, ""]
        tokens = re.split(r"(\d+)", str(val).strip())
        clave = []
        for c in tokens:
            if not c:
                continue
            if c.isdigit():
                clave.append(int(c))
            else:
                clave.append(normalizar_texto(c))
        return clave

    # 2. Moneda, Precios y Costos
    elif tipo == "currency":
        if val is None:
            return 0.0
        s = str(val).strip()
        if not s or s == "—":
            return 0.0
        # Remover $, COP, texto y espacios
        s_clean = re.sub(r"[^\d,\.\-]", "", s)
        if not s_clean:
            return 0.0
        if "," in s_clean and "." in s_clean:
            if s_clean.rfind(",") > s_clean.rfind("."):
                # Formato europeo/latino: 1.250,50
                s_clean = s_clean.replace(".", "").replace(",", ".")
            else:
                # Formato anglosajón: 1,250.50
                s_clean = s_clean.replace(",", "")
        elif "." in s_clean and s_clean.count(".") > 1:
            # Separador de miles con punto: 100.000.000
            s_clean = s_clean.replace(".", "")
        elif "." in s_clean and len(s_clean.split(".")[1]) == 3 and not (s_clean.startswith("0.")):
            # Probable separador de miles colombiano: 25.000
            s_clean = s_clean.replace(".", "")
        elif "," in s_clean:
            # Separador decimal con coma o miles con coma
            partes = s_clean.split(",")
            if len(partes) == 2 and len(partes[1]) in (1, 2):
                s_clean = s_clean.replace(",", ".")
            else:
                s_clean = s_clean.replace(",", "")
        try:
            return float(s_clean)
        except ValueError:
            return 0.0

    # 3. Stock, Cantidades y Números
    elif tipo == "numeric":
        if val is None:
            return -float("inf")
        s = str(val).strip()
        if not s or s == "—" or "servicio" in s.lower():
            return -float("inf")
        # Quitar espacios y buscar número inicial con posible decimal
        s_sin_espacio = s.replace(" ", "")
        m = re.search(r"[-+]?\d+(?:[.,]\d+)?", s_sin_espacio)
        if m:
            num_str = m.group(0)
            if "," in num_str and "." not in num_str:
                num_str = num_str.replace(",", ".")
            try:
                return float(num_str)
            except ValueError:
                pass
        return -float("inf")

    # 4. Fechas y Horas
    elif tipo == "date":
        if val is None:
            return ""
        s = str(val).strip()
        if not s or s == "—":
            return ""
        formatos = (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y %H:%M",
            "%d/%m/%Y",
            "%H:%M:%S",
            "%H:%M",
        )
        for fmt in formatos:
            try:
                dt = datetime.strptime(s, fmt)
                return dt.isoformat()
            except ValueError:
                pass
        return s.lower()

    # 5. Texto General (Alfabético sin acentos)
    else:
        return normalizar_texto(val)


def coincide_busqueda(
    item_o_valores: Union[Dict[str, Any], List[Any], Tuple[Any, ...]],
    termino_busqueda: str,
    campos: Optional[List[str]] = None,
) -> bool:
    """Verifica si un término de búsqueda coincide parcialmente con los campos del ítem de forma insensible a mayúsculas y acentos."""
    if not termino_busqueda or not termino_busqueda.strip():
        return True

    termino_norm = normalizar_texto(termino_busqueda)
    if not termino_norm:
        return True

    if isinstance(item_o_valores, dict):
        if campos:
            valores_a_revisar = [item_o_valores.get(c) for c in campos if c in item_o_valores]
        else:
            valores_a_revisar = list(item_o_valores.values())
    else:
        valores_a_revisar = list(item_o_valores)

    for val in valores_a_revisar:
        if val is None:
            continue
        v_norm = normalizar_texto(val)
        if termino_norm in v_norm:
            return True
    return False


class TreeviewSortManager:
    """Gestor integral de ordenamiento para ttk.Treeview con soporte para ciclo de 3 clics:
    1º clic: Ascendente (▲)
    2º clic: Descendente (▼)
    3º clic: Orden original (sin flecha)

    Conserva el estado de ordenamiento actual y lo re-aplica automáticamente cuando
    se recargan o filtran datos en la tabla.
    """

    TAG_ESTADO_VACIO = "fila_estado_vacio"

    def __init__(
        self,
        tree: Any,
        columnas_tipos: Optional[Dict[str, str]] = None,
        on_sort_changed: Optional[Callable[[Optional[str], Optional[str]], None]] = None,
    ):
        self.tree = tree
        self.columnas_tipos = columnas_tipos or {}
        self.on_sort_changed = on_sort_changed
        self.titulos_originales: Dict[str, str] = {}
        self.col_actual: Optional[str] = None
        self.direccion: Optional[str] = None  # None, "asc", "desc"
        self.orden_original_iids: List[str] = []

        self._vincular_cabeceras()

    def _vincular_cabeceras(self):
        """Registra los encabezados de las columnas del Treeview y vincula los comandos de clic."""
        cols = list(self.tree["columns"])
        for c in cols:
            txt = self.tree.heading(c).get("text", c)
            self.titulos_originales[c] = txt
            # Vincular callback en el encabezado
            self.tree.heading(c, command=lambda col=c: self.on_header_click(col))

    def registrar_datos_cargados(self):
        """Notifica al gestor que se insertaron nuevos datos en el Treeview.
        Guarda el nuevo orden original e inmediatamente re-aplica el ordenamiento
        activo si el usuario había seleccionado una columna.
        """
        # Guardar lista de iids excluyendo estados vacíos
        todos_iids = list(self.tree.get_children(""))
        self.orden_original_iids = [
            iid for iid in todos_iids
            if self.TAG_ESTADO_VACIO not in (self.tree.item(iid, "tags") or ())
        ]

        if self.col_actual and self.direccion:
            self._ordenar(self.col_actual, self.direccion)

    def on_header_click(self, col: str):
        """Maneja el clic en el encabezado de una columna según el ciclo:
        1º Clic: Ascendente (▲)
        2º Clic: Descendente (▼)
        3º Clic: Resetear a orden predeterminado (sin flecha)
        """
        if self.col_actual != col:
            self.col_actual = col
            self.direccion = "asc"
        elif self.direccion == "asc":
            self.direccion = "desc"
        elif self.direccion == "desc":
            self.col_actual = None
            self.direccion = None
        else:
            self.col_actual = col
            self.direccion = "asc"

        self._actualizar_cabeceras()

        if self.col_actual and self.direccion:
            self._ordenar(self.col_actual, self.direccion)
        else:
            self._restaurar_orden_original()

        if self.on_sort_changed:
            try:
                self.on_sort_changed(self.col_actual, self.direccion)
            except Exception:
                pass

    def _actualizar_cabeceras(self):
        """Actualiza el texto visible de los encabezados para mostrar ▲ o ▼ en la columna activa."""
        for c, orig in self.titulos_originales.items():
            if c == self.col_actual and self.direccion == "asc":
                self.tree.heading(c, text=f"{orig} ▲")
            elif c == self.col_actual and self.direccion == "desc":
                self.tree.heading(c, text=f"{orig} ▼")
            else:
                self.tree.heading(c, text=orig)

    def _ordenar(self, col: str, direccion: str):
        """Ordena las filas actualmente presentes en el Treeview usando la clave adecuada."""
        cols = list(self.tree["columns"])
        if col not in cols:
            return
        col_idx = cols.index(col)
        tipo = self.columnas_tipos.get(col, "auto")

        todos_iids = list(self.tree.get_children(""))
        # Excluir fila de estado vacío
        items_validos = [
            iid for iid in todos_iids
            if self.TAG_ESTADO_VACIO not in (self.tree.item(iid, "tags") or ())
        ]
        if not items_validos:
            return

        def _obtener_clave(iid):
            vals = self.tree.item(iid, "values") or ()
            raw = vals[col_idx] if col_idx < len(vals) else ""
            return extraer_clave_orden(raw, tipo=tipo, col_name=col)

        items_ordenados = sorted(items_validos, key=_obtener_clave, reverse=(direccion == "desc"))
        for idx, iid in enumerate(items_ordenados):
            self.tree.move(iid, "", idx)

    def _restaurar_orden_original(self):
        """Restaura las filas a su secuencia original registrada al momento de cargar los datos."""
        for idx, iid in enumerate(self.orden_original_iids):
            if self.tree.exists(iid):
                self.tree.move(iid, "", idx)

    def limpiar_orden(self):
        """Reinicia el estado de ordenamiento sin flechas y regresa al orden original."""
        self.col_actual = None
        self.direccion = None
        self._actualizar_cabeceras()
        self._restaurar_orden_original()

    def get_sort_state(self) -> Tuple[Optional[str], Optional[str]]:
        """Retorna la columna y dirección actualmente activas."""
        return self.col_actual, self.direccion

    def set_sort_state(self, col: Optional[str], direccion: Optional[str]):
        """Aplica programáticamente un ordenamiento a una columna específica."""
        self.col_actual = col
        self.direccion = direccion
        self._actualizar_cabeceras()
        if self.col_actual and self.direccion:
            self._ordenar(self.col_actual, self.direccion)
        else:
            self._restaurar_orden_original()


def insertar_estado_vacio(
    tree: Any,
    mensaje: str = "🔍 No se encontraron registros que coincidan con la búsqueda o filtros.",
    col_mensaje_idx: int = 2,
):
    """Inserta una fila visual informativa cuando no existen resultados coincidentes."""
    cols = list(tree["columns"])
    n = len(cols)
    valores = ["—"] * n
    if 0 <= col_mensaje_idx < n:
        valores[col_mensaje_idx] = mensaje
    elif n > 0:
        valores[0] = mensaje

    tree.insert("", "end", values=tuple(valores), tags=(TreeviewSortManager.TAG_ESTADO_VACIO,))
