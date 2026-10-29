import re

with open("interface/reportes_menu.py", "r") as f:
    content = f.read()

new_diario = '''def generar_reporte_diario(ventana):
    """Prepares and displays the daily sales report with a date filter."""
    filtro = tk.Toplevel(ventana)
    filtro.title("Filtrar Reporte Diario")
    filtro.geometry("300x200")
    filtro.configure(bg="#ff9ff3")
    filtro.transient(ventana)
    filtro.grab_set()

    tk.Label(filtro, text="Seleccione la fecha:", font=("Segoe UI", 12, "bold"), bg="#ff9ff3", fg="white").pack(pady=10)

    from datetime import datetime
    ahora = datetime.now()
    
    frame = tk.Frame(filtro, bg="#ff9ff3")
    frame.pack(pady=10)

    meses = [str(i).zfill(2) for i in range(1, 13)]
    dias = [str(i).zfill(2) for i in range(1, 32)]
    
    tk.Label(frame, text="Mes:", bg="#ff9ff3").grid(row=0, column=0, padx=5)
    combo_mes = ttk.Combobox(frame, values=meses, width=5, state="readonly")
    combo_mes.set(ahora.strftime("%m"))
    combo_mes.grid(row=0, column=1, padx=5)

    tk.Label(frame, text="Día:", bg="#ff9ff3").grid(row=0, column=2, padx=5)
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

    tk.Button(filtro, text="Ver Reporte", command=ver_reporte, bg="#4CAF50", fg="white", font=("Segoe UI", 10, "bold")).pack(pady=20)'''

pattern = r'def generar_reporte_diario\(ventana\):.*?(?=def generar_reporte_semanal)'
content = re.sub(pattern, new_diario + "\n", content, flags=re.DOTALL)

with open("interface/reportes_menu.py", "w") as f:
    f.write(content)
