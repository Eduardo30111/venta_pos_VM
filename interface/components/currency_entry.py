#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivo: interface/components/currency_entry.py
Componente empresarial para entrada de valores monetarios en Pesos Colombianos (COP).
- Elimina el problema de '0.0'.
- Inicializa visualmente en '0' o '$ 0'.
- El cero inicial no interfiere al escribir (100000 -> $100.000).
- Separa el formato visual del valor entero interno (.get_value() -> int).
"""

import tkinter as tk
from typing import Callable, Optional, Union

def formatear_cop(valor: Union[int, float, str], con_simbolo: bool = True) -> str:
    """Formatea un número como pesos colombianos sin decimales."""
    try:
        if isinstance(valor, str):
            digitos = "".join([c for c in valor if c.isdigit()])
            val_int = int(digitos) if digitos else 0
        elif isinstance(valor, float):
            val_int = int(round(valor))
        else:
            val_int = int(valor)
    except Exception:
        val_int = 0

    texto_formateado = f"{val_int:,}".replace(",", ".")
    return f"$ {texto_formateado}" if con_simbolo else texto_formateado

def desformatear_cop(texto: str) -> int:
    """Extrae el valor numérico entero limpio de una cadena formateada."""
    if not texto:
        return 0
    digitos = "".join([c for c in str(texto) if c.isdigit()])
    return int(digitos) if digitos else 0

class CurrencyEntry(tk.Entry):
    """
    Entry especializado para montos monetarios en COP.
    """
    def __init__(
        self,
        master,
        initial_value: Union[int, float, str] = 0,
        show_symbol: bool = True,
        on_change: Optional[Callable[[int], None]] = None,
        **kwargs
    ):
        self._show_symbol = show_symbol
        self._on_change = on_change
        self._var = tk.StringVar()
        self._internal_value = 0
        self._is_updating = False

        if "justify" not in kwargs:
            kwargs["justify"] = "right"

        super().__init__(master, textvariable=self._var, **kwargs)

        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<KeyRelease>", self._on_key_release)
        self.bind("<Control-a>", self._select_all)
        self.bind("<Command-a>", self._select_all)

        self.set_value(initial_value)

    def _select_all(self, event=None):
        self.selection_range(0, tk.END)
        return "break"

    def _on_focus_in(self, event=None):
        """Al recibir foco, selecciona todo para que el primer dígito sobrescriba."""
        self.selection_range(0, tk.END)

    def _on_focus_out(self, event=None):
        """Al perder foco, formatea asegurando visual consistente."""
        self.set_value(self._internal_value)

    def _on_key_release(self, event=None):
        """Filtra y formatea dinámicamente según lo que escribe el usuario."""
        if self._is_updating:
            return

        if event and event.keysym in ("Left", "Right", "Up", "Down", "Home", "End", "Tab", "Return", "Escape"):
            return

        raw_text = self._var.get()
        digitos = "".join([c for c in raw_text if c.isdigit()])

        if not digitos:
            nuevo_valor = 0
        else:
            nuevo_valor = int(digitos)

        self._internal_value = nuevo_valor
        self._is_updating = True

        formatted = formatear_cop(nuevo_valor, con_simbolo=self._show_symbol)
        self._var.set(formatted)

        self.icursor(tk.END)
        self._is_updating = False

        if self._on_change:
            try:
                self._on_change(self._internal_value)
            except Exception as e:
                print(f"Error en callback on_change de CurrencyEntry: {e}")

    def bind(self, sequence=None, func=None, add=None):
        if sequence == "<KeyRelease>" and add is None:
            add = "+"
        return super().bind(sequence, func, add=add)

    def get_value(self) -> int:
        """Retorna el valor numérico entero limpio (ej. 100000)."""
        try:
            raw = self._var.get() if hasattr(self, "_var") else self.get()
            digitos = "".join([c for c in str(raw) if c.isdigit()])
            if digitos:
                self._internal_value = int(digitos)
            else:
                self._internal_value = 0
        except Exception:
            pass
        return self._internal_value

    def set_value(self, val: Union[int, float, str]):
        """Establece un nuevo valor numérico y actualiza el formato visual."""
        try:
            if isinstance(val, (int, float)):
                val_int = int(round(val))
            elif isinstance(val, str):
                val_int = desformatear_cop(val)
            else:
                val_int = 0
        except Exception:
            val_int = 0

        self._internal_value = max(0, val_int)
        self._is_updating = True
        self._var.set(formatear_cop(self._internal_value, con_simbolo=self._show_symbol))
        self._is_updating = False

        if self._on_change:
            try:
                self._on_change(self._internal_value)
            except Exception:
                pass

    def clear(self):
        """Limpia a cero."""
        self.set_value(0)
