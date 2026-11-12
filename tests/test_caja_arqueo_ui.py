#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest
import tkinter as tk
from tkinter import ttk
from interface.theme_manager import aplicar_tema, ScrollableContainer
from interface.caja_menu import DENOM_BILLETES, DENOM_MONEDAS


class TestCajaArqueoUI(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_scrollable_container_has_interior(self):
        sc = ScrollableContainer(self.root)
        self.assertTrue(hasattr(sc, "interior"))
        self.assertTrue(hasattr(sc, "scrollable_frame"))
        self.assertTrue(hasattr(sc, "content_frame"))
        self.assertEqual(sc.interior, sc.content_frame)

    def test_denominaciones_filas_creation(self):
        nb = ttk.Notebook(self.root)
        tab_b = tk.Frame(nb)
        tab_m = tk.Frame(nb)
        nb.add(tab_b, text="Billetes")
        nb.add(tab_m, text="Monedas")

        cant_vars = {}
        subtotal_lbls = {}

        def build_rows(parent, denoms):
            sc = ScrollableContainer(parent)
            sc.pack(fill="both", expand=True)
            interior = getattr(sc, "interior", getattr(sc, "scrollable_frame", sc.content_frame))
            for item in denoms:
                val = item["valor"]
                row_f = tk.Frame(interior)
                row_f.pack(fill="x", pady=2)

                lbl_nom = tk.Label(row_f, text=item["nombre"])
                lbl_nom.pack(side="left")

                var_q = tk.StringVar(value="0")
                cant_vars[val] = var_q
                ent = tk.Entry(row_f, textvariable=var_q)
                ent.pack(side="left")

                lbl_sub = tk.Label(row_f, text="$ 0")
                lbl_sub.pack(side="right")
                subtotal_lbls[val] = lbl_sub
            return interior

        int_b = build_rows(tab_b, DENOM_BILLETES)
        int_m = build_rows(tab_m, DENOM_MONEDAS)

        # 6 billetes y 6 monedas
        self.assertEqual(len(int_b.winfo_children()), 6)
        self.assertEqual(len(int_m.winfo_children()), 6)

        # Verificar calculos
        cant_vars[50000].set("2")
        cant_vars[1000].set("5")

        tot = sum(int(cant_vars[v].get()) * v for v in cant_vars)
        self.assertEqual(tot, 105000)


if __name__ == "__main__":
    unittest.main()
