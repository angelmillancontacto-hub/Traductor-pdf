import streamlit as st
import fitz  
import google.generativeai as genai
import json
from docx import Document # Nueva librería para generar Word

# Configuración de Gemini
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
modelo = genai.GenerativeModel('gemini-2.0-flash')

def extraer_texto_fluido(pdf_file):
    doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
    texto_completo = ""
    for pagina in doc:
        texto_completo += pagina.get_text() + "\n"
    return texto_completo

def generar_documento(markdown_content, nombre_archivo):
    # Aquí crearías el PDF o Word a partir del Markdown
    # Ejemplo rápido para Word:
    doc = Document()
    doc.add_paragraph(markdown_content)
    doc.save(f"{nombre_archivo}.docx")
    return f"{nombre_archivo}.docx"

# Interfaz
st.title("🚀 Reconstructor de Documentos")
archivo = st.file_uploader("Sube el PDF", type="pdf")

if archivo and st.button("Reconstruir y Traducir"):
    # 1. Extracción
    texto_bruto = extraer_texto_fluido(archivo)
    
    # 2. IA como Diseñador Editorial
    prompt = f"""
    Actúa como un diseñador editorial experto.
    Traduce el siguiente texto de {idioma_origen} a {idioma_destino}.
    Devuélveme el resultado exclusivamente en formato Markdown estructurado:
    - Usa # para Títulos, ## para Subtítulos.
    - Usa - para listas.
    - Usa > para citas importantes.
    - Mantén el orden lógico del contenido.
    TEXTO: {texto_bruto}
    """
    
    response = modelo.generate_content(prompt)
    markdown_final = response.text
    
    # 3. Guardado
    archivo_word = generar_documento(markdown_final, "documento_reconstruido")
    st.success("¡Documento reconstruido con éxito!")
    st.download_button("Descargar Word", data=open(archivo_word, "rb"), file_name="resultado.docx")import streamlit as st
import fitz  
import google.generativeai as genai
import json
import time
import pytesseract
from PIL import Image
import io

st.set_page_config(page_title="Traductor IA de PDFs", page_icon="📄", layout="centered")
st.title("📄 Traductor de PDFs con IA (Gemini + OCR)")

# 1. Configuración de la API de Google
try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=API_KEY)
    # Usamos Gemini 1.5 Flash, ideal para tareas rápidas y estructuradas
    modelo = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error("Falta configurar la clave de API (GEMINI_API_KEY) en los secretos del servidor.")
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

                if b.get("type") == 0: 
                    for linea in b["lines"]:
                        for span in linea["spans"]:
                            texto_bloque += span["text"] + " "
                            tamaño_letra = span["size"]
                    texto_bloque = texto_bloque.strip()
                    
                elif b.get("type") == 1:
                    imagen_bytes = b["image"]
                    imagen_pil = Image.open(io.BytesIO(imagen_bytes))
                    try:
                        texto_bloque = pytesseract.image_to_string(imagen_pil).strip()
                    except:
                        pass
                    tamaño_letra = 12 

                if texto_bloque: 
                    datos_para_gemini.append({
                        "id": str(b.get("number", hash(texto_bloque))), 
                        "text": texto_bloque,
                        "bbox": bbox,
                        "size": tamaño_letra,
                        "is_image": b.get("type") == 1
                    })

            if not datos_para_gemini:
                continue

            prompt = f"""
            You are an expert translator specializing in JSON data. Your task is to accurately translate the text content within a JSON array of text objects from {idioma_origen} to {idioma_destino}.

            CRITICAL INSTRUCTIONS:
            1. Focus exclusively on the string associated with the "text" key in each object.
            2. Maintain brevity in your translations.
            3. Your output must be a valid JSON array that mirrors the structure of the input exactly.
            4. Only modify the 'text' values; do not alter 'id', 'bbox', 'size', and 'is_image'.
            5. Deliver the output as raw JSON without any Markdown formatting or code blocks.

            INPUT DATA: 
            {json.dumps(datos_para_gemini)}
            """

            exito = False
            intentos = 0
            
            while not exito and intentos < 3:
                try:
                    respuesta = modelo.generate_content(prompt)
                    contenido_respuesta = respuesta.text.strip()
                    
                    # Limpiamos los bloques de código Markdown si Gemini los incluye
                    if contenido_respuesta.startswith("```json"):
                        contenido_respuesta = contenido_respuesta[7:]
                    if contenido_respuesta.startswith("```"):
                        contenido_respuesta = contenido_respuesta[3:]
                    if contenido_respuesta.endswith("```"):
                        contenido_respuesta = contenido_respuesta[:-3]

                    textos_traducidos = json.loads(contenido_respuesta)
                    
                    for item in textos_traducidos:
                        id_bloque = str(item.get("id", "")) 
                        texto_nuevo = item.get("text", "") 
                        
                        datos_orig = next((d for d in datos_para_gemini if str(d["id"]) == id_bloque), None)
                        
                        if datos_orig:
                            rect_orig = fitz.Rect(datos_orig["bbox"])
                            # AMPLIACIÓN ANTIMUTILACIÓN: Más espacio a la derecha (50) y abajo (20)
                            rect_ampliado = rect_orig + (-2, -2, 50, 20) 

                            if datos_orig.get("is_image", False):
                                pagina.draw_rect(rect_orig, color=(1, 1, 1), fill=(1, 1, 1))
                            else:
                                pagina.add_redact_annot(rect_orig, text="", fill=(1, 1, 1)) 
                                pagina.apply_redactions()

                            # AUTO-AJUSTE DINÁMICO
                            tamaño_fuente = datos_orig["size"]
                            fuente_minima = 6.0
                            
                            while tamaño_fuente >= fuente_minima:
                                cabe_el_texto = pagina.insert_textbox(
                                    rect_ampliado, 
                                    texto_nuevo, 
                                    fontsize=tamaño_fuente, 
                                    fontname="helv", 
                                    color=(0.1, 0.1, 0.1) 
                                )
                                if cabe_el_texto >= 0:
                                    break 
                                
                                tamaño_fuente -= 0.5
                                
                                if tamaño_fuente < fuente_minima:
                                    pagina.insert_textbox(rect_ampliado, texto_nuevo, fontsize=fuente_minima, fontname="helv", color=(0.1, 0.1, 0.1))
                                    break

                    exito = True 
                    # FRENO ANTI-BLOQUEO: Espera 10 segundos entre páginas
                    time.sleep(10) 

                except Exception as e:
                    st.error(f"⚠️ Error REAL de Gemini: {e}")
                    intentos += 1
                    time.sleep(5)

            progreso = (num_pagina + 1) / len(doc)
            barra_progreso.progress(progreso)

        estado_texto.success("🎉 ¡Traducción completada y formateada!")
        pdf_bytes = doc.write()
        
        st.download_button(
            label="⬇️ Descargar PDF Traducido",
            data=pdf_bytes,
            file_name="documento_traducido_gemini.pdf",
            mime="application/pdf"
        )
