"""
Generador de recursos visuales offline para denominaciones de efectivo colombianas
(Billetes y Monedas para Arqueo de Caja en VmPOS).
Crea imágenes nítidas de referencia en assets/denominaciones/.
"""

import os
from PIL import Image, ImageDraw, ImageFont

ASSETS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "denominaciones"))
os.makedirs(ASSETS_DIR, exist_ok=True)

# Paletas oficiales de referencia de la Nueva Familia de Billetes Colombianos
BILLETES = [
    {
        "valor": 100000,
        "texto": "$100.000",
        "sub": "100 MIL",
        "personaje": "Valle de Cocora",
        "bg": "#1B5E20",
        "accent": "#2E7D32",
        "border": "#81C784",
        "text_col": "#FFFFFF"
    },
    {
        "valor": 50000,
        "texto": "$50.000",
        "sub": "50 MIL",
        "personaje": "G. García Márquez",
        "bg": "#4A148C",
        "accent": "#6A1B9A",
        "border": "#BA68C8",
        "text_col": "#FFFFFF"
    },
    {
        "valor": 20000,
        "texto": "$20.000",
        "sub": "20 MIL",
        "personaje": "Alfonso López M.",
        "bg": "#E65100",
        "accent": "#EF6C00",
        "border": "#FFB74D",
        "text_col": "#FFFFFF"
    },
    {
        "valor": 10000,
        "texto": "$10.000",
        "sub": "10 MIL",
        "personaje": "Virginia Gutiérrez",
        "bg": "#B71C1C",
        "accent": "#C62828",
        "border": "#E57373",
        "text_col": "#FFFFFF"
    },
    {
        "valor": 5000,
        "texto": "$5.000",
        "sub": "5 MIL",
        "personaje": "José Asunción Silva",
        "bg": "#4E342E",
        "accent": "#5D4037",
        "border": "#A1887F",
        "text_col": "#FFFFFF"
    },
    {
        "valor": 2000,
        "texto": "$2.000",
        "sub": "2 MIL",
        "personaje": "Débora Arango",
        "bg": "#0D47A1",
        "accent": "#1565C0",
        "border": "#64B5F6",
        "text_col": "#FFFFFF"
    },
]

MONEDAS = [
    {
        "valor": 2000,
        "texto": "$2.000",
        "sub": "PESOS",
        "outer": "#D4AF37",
        "inner": "#C0C0C0",
        "border": "#B8860B",
        "text_col": "#1A1A1A"
    },
    {
        "valor": 1000,
        "texto": "$1.000",
        "sub": "PESOS",
        "outer": "#D4AF37",
        "inner": "#D8D8D8",
        "border": "#B8860B",
        "text_col": "#1A1A1A"
    },
    {
        "valor": 500,
        "texto": "$500",
        "sub": "PESOS",
        "outer": "#C0C0C0",
        "inner": "#D4AF37",
        "border": "#9E9E9E",
        "text_col": "#1A1A1A"
    },
    {
        "valor": 200,
        "texto": "$200",
        "sub": "PESOS",
        "outer": "#C0C0C0",
        "inner": "#D5D5D5",
        "border": "#757575",
        "text_col": "#212121"
    },
    {
        "valor": 100,
        "texto": "$100",
        "sub": "PESOS",
        "outer": "#D4AF37",
        "inner": "#E5C158",
        "border": "#B8860B",
        "text_col": "#212121"
    },
    {
        "valor": 50,
        "texto": "$50",
        "sub": "PESOS",
        "outer": "#B0BEC5",
        "inner": "#CFD8DC",
        "border": "#78909C",
        "text_col": "#263238"
    },
]

def crear_imagen_billete(b):
    w, h = 100, 50
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    
    # Fondo redondeado
    d.rounded_rectangle([(1, 1), (w - 2, h - 2)], radius=5, fill=b["bg"], outline=b["border"], width=2)
    
    # Franja de seguridad lateral
    d.rounded_rectangle([(4, 4), (20, h - 5)], radius=3, fill=b["accent"])
    
    # Texto vertical / microimpresión en la franja
    d.text((6, 6), "BR", fill=b["border"])
    d.text((6, h - 16), "COL", fill=b["border"])
    
    # Valor principal
    d.text((25, 6), b["texto"], fill=b["text_col"])
    d.text((25, 20), b["sub"], fill=b["border"])
    d.text((25, 34), b["personaje"][:15], fill="#E0E0E0")
    
    # Marca de agua simulada / óvalo de seguridad
    d.ellipse([(w - 24, 12), (w - 6, 38)], outline=b["border"], width=1)
    d.text((w - 20, 18), "BR", fill=b["border"])
    
    ruta = os.path.join(ASSETS_DIR, f"billete_{b['valor']}.png")
    img.save(ruta, "PNG")
    print(f"Creado: {ruta}")

def crear_imagen_moneda(m):
    size = 50
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    
    # Anillo exterior
    d.ellipse([(1, 1), (size - 2, size - 2)], fill=m["outer"], outline=m["border"], width=2)
    
    # Centro / bimetálico
    margin = 8
    d.ellipse([(margin, margin), (size - margin, size - margin)], fill=m["inner"], outline=m["border"], width=1)
    
    # Relieve texto central
    txt = m["texto"]
    d.text((size // 2 - 12 if len(txt) <= 4 else size // 2 - 16, 12), txt, fill=m["text_col"])
    d.text((size // 2 - 12, 28), m["sub"], fill=m["border"])
    
    ruta = os.path.join(ASSETS_DIR, f"moneda_{m['valor']}.png")
    img.save(ruta, "PNG")
    print(f"Creado: {ruta}")

if __name__ == "__main__":
    for b in BILLETES:
        crear_imagen_billete(b)
    for m in MONEDAS:
        crear_imagen_moneda(m)
    print("✅ Todas las denominaciones generadas exitosamente.")
