import re

with open("interface/usuarios_menu.py", "r") as f:
    content = f.read()

# Fix Estado layout
old_estado = '''    # Campo Estado
    tk.Label(form_frame, text="📊 Estado:", font=("Segoe UI", 11, "bold"), 
             bg="#FFDDEE", fg="#C71585").grid(row=5, column=0, padx=5, pady=8, sticky="w")
    combo_estado = ttk.Combobox(form_frame, textvariable=estado_var, values=estados, 
                                state="readonly", width=32, font=("Segoe UI", 11))
    combo_estado.grid(row=3, column=1, padx=5, pady=8, sticky="w")'''

new_estado = '''    # Campo Estado
    tk.Label(form_frame, text="📊 Estado:", font=("Segoe UI", 11, "bold"), 
             bg="#FFDDEE", fg="#C71585").grid(row=6, column=0, padx=5, pady=8, sticky="w")
    combo_estado = ttk.Combobox(form_frame, textvariable=estado_var, values=estados, 
                                state="readonly", width=32, font=("Segoe UI", 11))
    combo_estado.grid(row=6, column=1, padx=5, pady=8, sticky="w")'''

content = content.replace(old_estado, new_estado)

# Fix Botones layout
old_botones = '''    # Botones de acción
    botones_frame = tk.Frame(form_frame, bg="#FFDDEE")
    botones_frame.grid(row=4, column=0, columnspan=4, pady=15)'''

new_botones = '''    # Botones de acción
    botones_frame = tk.Frame(form_frame, bg="#FFDDEE")
    botones_frame.grid(row=7, column=0, columnspan=4, pady=15)'''

content = content.replace(old_botones, new_botones)

with open("interface/usuarios_menu.py", "w") as f:
    f.write(content)
