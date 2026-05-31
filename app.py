import streamlit as st
import fitz  
from groq import Groq
import json
import time
import pytesseract
from PIL import Image
import io

st.set_page_config(page_title="Traductor IA de PDFs", page_icon="📄", layout="centered")
st.title("📄 Traductor de PDFs con IA (Groq + OCR)")

try:
    API_KEY = st.secrets["GROQ_API_KEY"]
    cliente_groq = Groq(api_key=API_KEY)
except:
    st.error("Falta configurar la clave de API en los secretos del servidor.")
    st.stop()

with st.sidebar:
    st.header("Configuración")
    idioma_origen = st.selectbox("Idioma de origen", ["Portugués", "Inglés", "Francés", "Alemán", "Italiano"])
    idioma_destino = st.selectbox("Idioma de destino", ["Español", "Inglés"])

archivo_subido = st.file_uploader("Sube tu PDF aquí", type="pdf")

if archivo_subido is not None:
    if st.button("🚀 Comenzar Traducción"):
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
                    try:
                        texto_bloque = pytesseract.image_to_string(imagen_pil).strip()
                    except:
                        pass
                    tamaño_letra = 12 
                    color_letra = 0

                if texto_bloque: 
                    datos_para_gemini.append({
                        "id": str(b.get("number", hash(texto_bloque))), 
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
                    
                    for item in textos_traducidos:
                        id_bloque = str(item.get("id", "")) 
                        texto_nuevo = item.get("text", "") 
                        
                        datos_orig = next((d for d in datos_para_gemini if str(d["id"]) == id_bloque), None)
                        
                        if datos_orig:
                            rect_orig = fitz.Rect(datos_orig["bbox"])
                            # Ampliamos ligeramente la caja para dar margen
                            rect_ampliado = rect_orig + (-2, -2, 50, 20) 

                            # Borramos el fondo
                            if datos_orig.get("is_image", False):
                                pagina.draw_rect(rect_orig, color=(1, 1, 1), fill=(1, 1, 1))
                            else:
                                pagina.add_redact_annot(rect_orig, text="", fill=(1, 1, 1)) 
                                pagina.apply_redactions()

                            # SISTEMA DE AUTO-AJUSTE DINÁMICO
                            tamaño_fuente = datos_orig["size"]
                            fuente_minima = 6.0
                            
                            while tamaño_fuente >= fuente_minima:
                                # insert_textbox devuelve un número < 0 si el texto no cabe
                                cabe_el_texto = pagina.insert_textbox(
                                    rect_ampliado, 
                                    texto_nuevo, 
                                    fontsize=tamaño_fuente, 
                                    fontname="helv", 
                                    color=(0.1, 0.1, 0.1) 
                                )
                                if cabe_el_texto >= 0:
                                    break # El texto encajó, rompemos el bucle
                                
                                # Si no cabe, reducimos la fuente y volvemos a intentar
                                tamaño_fuente -= 0.5
                                
                                # Si llegamos al mínimo y aún no cabe, lo forzamos
                                if tamaño_fuente < fuente_minima:
                                    pagina.insert_textbox(rect_ampliado, texto_nuevo, fontsize=fuente_minima, fontname="helv", color=(0.1, 0.1, 0.1))
                                    break

                    exito = True 
                    time.sleep(2) 

                except Exception as e:
                    st.warning(f"⚠️ Pausa técnica en página {num_pagina + 1} por límite de la IA. Esperando 15 segundos...")
                    intentos += 1
                    time.sleep(15)

            progreso = (num_pagina + 1) / len(doc)
            barra_progreso.progress(progreso)

        estado_texto.success("🎉 ¡Traducción completada y formateada!")
        pdf_bytes = doc.write()
        
        st.download_button(
            label="⬇️ Descargar PDF Traducido",
            data=pdf_bytes,
            file_name="documento_traducido_final.pdf",
            mime="application/pdf"
        )
