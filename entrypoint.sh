#!/bin/bash
set -e

# 1. Iniciar servidor X virtual (Xvfb)
export DISPLAY=:99
rm -f /tmp/.X99-lock
Xvfb :99 -screen 0 1280x800x24 -ac +extension GLX +render -noreset &
sleep 2

# 2. Iniciar gestor de ventanas ligero
fluxbox &
sleep 1

# 3. Iniciar servidor VNC en background
x11vnc -display :99 -nopw -listen 127.0.0.1 -xkb -forever -shared &
sleep 2

# 4. Iniciar puente NoVNC (Web VNC) en el puerto 8080
echo "=> Iniciando servidor web VNC en http://localhost:8080/vnc.html"
websockify --web /usr/share/novnc/ 8080 localhost:5900 &

# 5. Iniciar la aplicación
echo "=> Iniciando VmPOS..."
python3 interface/inicio_sesion.py
