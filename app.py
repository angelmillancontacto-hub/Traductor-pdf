import streamlit as st
import fitz  
from groq import Groq
import json
import time
import pytesseract
from PIL import Image
import io

# Configuración visual de la página web
st.set_page_config(page_title="Traductor IA de PDFs", page_icon="📄", layout="centered")

st.title("📄 Traductor de PDFs con IA (Groq + OCR)")
st.write("Sube tu documento PDF. La IA extraerá el texto y las imágenes, lo traducirá y te devolverá el archivo listo para descargar.")

# 1. Configuración de la API Key (Ahora se lee de forma segura desde los "Secrets" del servidor)
try:
    API_KEY = st.secrets["GROQ_API_KEY"]
    cliente_groq = Groq(api_key=API_KEY)
except:
    st.error("Falta configurar la clave de API de Groq en los secretos del servidor.")
    st.stop()

# 2. Panel lateral para elegir idiomas
with st.sidebar:
    st.header("Configuración")
    idioma_origen = st.selectbox("Idioma de origen", ["Inglés", "Francés", "Alemán", "Italiano", "Portugués"])
    idioma_destino = st.selectbox("Idioma de destino", ["Español", "Inglés"])

# 3. Botón para subir el archivo
archivo_subido = st.file_uploader("Sube tu PDF aquí", type="pdf")

if archivo_subido is not None:
    if st.button("🚀 Comenzar Traducción"):
        
        # Leemos el PDF directamente desde la memoria
        doc = fitz.open(stream=archivo_subido.read(), filetype="pdf")
        
        barra_progreso = st.progress(0)
        estado_texto = st.empty()
        
        for num_pagina in range(len(doc)):
            estado_texto.info(f"Procesando página {num_pagina + 1} de {len(doc)}...")
            pagina = doc[num_pagina]

            bloques = pagina.get_text("dict")["blocks"]
            datos_para_gemini = []

            for b in bloques:
                texto_bloque = ""
                bbox = b["bbox"]
                tamaño_letra = 10  
                color_letra = 0 

                if b.get("type") == 0: 
                    for linea in b["lines"]:
                        for span in linea["spans"]:
                            texto_bloque += span["text"] + " "
                            tamaño_letra = span["size"]
                            color_letra = span["color"]
                    texto_bloque = texto_bloque.strip()
                    
                elif b.get("type") == 1:
                    imagen_bytes = b["image"]
                    imagen_pil = Image.open(io.BytesIO(imagen_bytes))
                    texto_bloque = pytesseract.image_to_string(imagen_pil).strip()
                    tamaño_letra = 12 
                    color_letra = 0

                if texto_bloque: 
                    datos_para_gemini.append({
                        "id": b.get("number", hash(texto_bloque)), 
                        "text": texto_bloque,
                        "bbox": bbox,
                        "size": tamaño_letra,
                        "color": color_letra,
                        "is_image": b.get("type") == 1
                    })

            if not datos_para_gemini:
                continue

            prompt = f"""
            You are an expert translator specializing in JSON data. Your task is to accurately translate the text content within a JSON array of text objects from {idioma_origen} to {idioma_destino}.

            CRITICAL INSTRUCTIONS:
            1. Focus exclusively on the string associated with the "text" key in each object. Ensure that every translated string is populated and not left empty.
            2. Maintain brevity in your translations to ensure they fit the original layout and context.
            3. Your output must be a valid JSON array that mirrors the structure of the input exactly.
            4. Only modify the 'text' values; do not alter the 'id', 'bbox', 'size', 'color', and 'is_image' values in any way.
            5. Deliver the output as raw JSON without any Markdown formatting or code blocks.

            INPUT DATA: 
            {json.dumps(datos_para_gemini)}
            """

            exito = False
            intentos = 0
            
            while not exito and intentos < 3:
                try:
                    respuesta = cliente_groq.chat.completions.create(
                        messages=[{"role": "user", "content": prompt}],
                        model="llama-3.3-70b-versatile",
                        temperature=0.1 
                    )
                    
                    contenido_respuesta = respuesta.choices[0].message.content.strip()
                    if contenido_respuesta.startswith("```json"):
                        contenido_respuesta = contenido_respuesta[7:]
                    if contenido_respuesta.endswith("```"):
                        contenido_respuesta = contenido_respuesta[:-3]

                    textos_traducidos = json.loads(contenido_respuesta)
                    st.success(f"✅ ¡Groq tradujo con éxito la página {num_pagina + 1}!")
                    
                    # SUERO DE LA VERDAD: Mostrar en la web qué devolvió la IA
                    with st.expander(f"👁️ Ver qué respondió la IA en la página {num_pagina + 1}"):
                        st.json(textos_traducidos)
                    
                    for item in textos_traducidos:
                        id_bloque = str(item.get("id", "")) 
                        texto_nuevo = item.get("text", "") # Si no hay texto, pone vacío
                        
                        datos_orig = next((d for d in datos_para_gemini if str(d["id"]) == id_bloque), None)
                        
                        if datos_orig:
                            # Hacemos el cuadro un poco más grande por si la traducción es muy larga
                            rect_orig = fitz.Rect(datos_orig["bbox"])
                            rect_ampliado = rect_orig + (-5, -5, 5, 5) 

                            if datos_orig.get("is_image", False):
                                pagina.draw_rect(rect_orig, color=(1, 1, 1), fill=(1, 1, 1))
                            else:
                                pagina.add_redact_annot(rect_orig, text="", fill=(1, 1, 1)) 
                                pagina.apply_redactions()

                            # FORZAMOS TINTA NEGRA (0,0,0) PARA ASEGURARNOS DE QUE SE VEA
                            pagina.insert_textbox(rect_ampliado, texto_nuevo, fontsize=10, fontname="helv", color=(0,0,0))
                        else:
                            st.warning(f"⚠️ Se perdió el rastro del ID: {id_bloque}")
                    
                    exito = True 
                    time.sleep(2)

            # Actualizar barra de progreso
            progreso = (num_pagina + 1) / len(doc)
            barra_progreso.progress(progreso)

        estado_texto.success("¡Traducción completada con éxito!")
        
        # Convertir el PDF final a bytes para poder descargarlo
        pdf_bytes = doc.write()
        
        st.download_button(
            label="⬇️ Descargar PDF Traducido",
            data=pdf_bytes,
            file_name="documento_traducido.pdf",
            mime="application/pdf"
        )
