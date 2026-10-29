# 📦 Guía de Empaquetado e Instaladores — VmPOS

Esta carpeta contiene las herramientas para empaquetar VmPOS en instaladores nativos para **macOS** y **Windows**.

---

## 🍎 1. Compilar Instalador para macOS (.dmg)

En cualquier computadora Mac con Python:

```bash
chmod +x packaging/build_macos.sh
./packaging/build_macos.sh
```

**Resultado:**
- `dist/VmPOS.app`: Aplicación nativa de macOS lista para usar.
- `dist/VmPOS_macOS_Instalador.dmg`: Imagen de disco instaladora con soporte tradicional de arrastrar a la carpeta `/Applications`.

---

## 🪟 2. Compilar Instalador para Windows (.exe)

En una computadora con Windows:

1. Ejecutar el script por lotes:
   ```cmd
   packaging\build_windows.bat
   ```
2. Si tienes [Inno Setup 6](https://jrsoftware.org/isdl.php) instalado, el script generará automáticamente:
   - `dist\VmPOS_Setup_v4.0.exe`: Instalador con asistente en español (*Siguiente > Siguiente > Instalar*), creación de accesos directos en el Escritorio y Menú Inicio, y regla de Firewall para el puerto 8000.
3. Si no tienes Inno Setup, se genera la carpeta portable `dist\VmPOS\` con todos los archivos necesarios.

---

## ☁️ 3. Compilación Automática en la Nube (GitHub Actions)

Si subes este repositorio a GitHub, no necesitas tener una computadora con Windows para compilar el instalador `.exe`.

1. Entra a tu repositorio en GitHub.
2. Ve a la pestaña **Actions**.
3. Selecciona el flujo **Compilar Instaladores (Windows y macOS)**.
4. Haz clic en **Run workflow**.
5. Al terminar, podrás descargar directamente:
   - `VmPOS-macOS-Instalador.zip` (que contiene el `.dmg`)
   - `VmPOS-Windows-Setup.zip` (que contiene el instalador `.exe`)
