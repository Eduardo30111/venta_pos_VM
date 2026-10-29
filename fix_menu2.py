with open("interface/menu_inicio.py", "r") as f:
    content = f.read()

# Insert before '# --- Punto de entrada desde el login ---'
new_method = """
    def _abrir_nomina(self):
        \"\"\"Abre el módulo de nómina y liquidación usando subprocess.\"\"\"
        try:
            import subprocess
            import sys
            import os
            
            base_dir = os.path.dirname(os.path.abspath(__file__))
            script_path = os.path.join(base_dir, 'nomina_menu.py')
            
            if os.path.exists(script_path):
                print("Abriendo módulo de nómina en proceso separado...")
                subprocess.Popen([sys.executable, script_path])
            else:
                messagebox.showerror("❌ Error", f"No se encontró el módulo: {script_path}")
        except Exception as e:
            messagebox.showerror("❌ Error", f"Error al abrir el módulo de nómina: {e}")

"""

content = content.replace("# --- Punto de entrada desde el login ---", new_method + "# --- Punto de entrada desde el login ---")

with open("interface/menu_inicio.py", "w") as f:
    f.write(content)
