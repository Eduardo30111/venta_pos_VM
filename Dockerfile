FROM ubuntu:22.04

# Evitar prompts interactivos
ENV DEBIAN_FRONTEND=noninteractive

# Instalar dependencias del sistema, Python y herramientas de X11/VNC
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-tk \
    xvfb \
    x11vnc \
    novnc \
    fluxbox \
    websockify \
    espeak \
    fonts-liberation \
    x11-xserver-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar el código fuente
COPY . /app

# Instalar dependencias principales compatibles con Linux
# Se omiten librerias de Windows (pywin32, comtypes) que romperian el build
RUN pip3 install reportlab pillow matplotlib pandas python-escpos pyusb pyserial qrcode python-barcode pyttsx3 tkcalendar

# Script de inicio
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Puerto para la interfaz web (NoVNC)
EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
