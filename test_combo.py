import tkinter as tk
from tkinter import ttk

root = tk.Tk()
root.geometry("300x200")

var = tk.StringVar(value="A")
lbl = tk.Label(root, text="Current: A")
lbl.pack(pady=20)

def on_change(*args):
    lbl.config(text=f"Current: {var.get()}")

cb = ttk.Combobox(root, textvariable=var, values=["A", "B", "C"])
cb.pack()

# Both approaches
var.trace_add("write", on_change)
cb.bind("<<ComboboxSelected>>", lambda e: root.after(10, on_change))

root.mainloop()
