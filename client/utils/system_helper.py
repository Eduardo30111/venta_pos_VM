import os
import sys
import subprocess

def abrir_archivo_o_carpeta(ruta: str):
    """
    Abre un archivo o directorio de forma segura dependiendo del sistema operativo,
    evitando los errores 'AttributeError: module os has no attribute startfile' en Mac/Linux.
    """
    try:
        ruta_absoluta = os.path.abspath(ruta)
        
        if sys.platform == "win32":
            # Windows
            if hasattr(os, "startfile"):
                os.startfile(ruta_absoluta)
            else:
                subprocess.run(['explorer', ruta_absoluta])
        elif sys.platform == "darwin":
            # macOS (Apple Silicon/Intel)
            subprocess.run(['open', ruta_absoluta])
        else:
            # Linux (incluyendo el contenedor Docker si se usa VNC)
            subprocess.run(['xdg-open', ruta_absoluta])
            
    except Exception as e:
        print(f"Error al intentar abrir el archivo: {e}")
        # Retorna el error para que la UI lo maneje si lo desea
        return e
    return None
