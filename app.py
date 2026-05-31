import streamlit as st
import fitz  # PyMuPDF
from docx import Document
from fpdf import FPDF
from pdf2image import convert_from_bytes
import pytesseract
from PIL import Image
import io
import re
import time
from groq import Groq
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# ------------------------------------------------------------
# Configuración de la página
# ------------------------------------------------------------
st.set_page_config(page_title="Traductor de documentos", layout="wide")
st.title("🌐 Traductor de documentos a cualquier idioma")
st.markdown("Sube un PDF, imagen o Word y tradúcelo conservando el formato.")

# ------------------------------------------------------------
# Cliente de Groq (100 % gratuito)
# ------------------------------------------------------------
client = Groq(api_key=st.secrets["GROQ_API_KEY"])
MODELO = "llama-3.3-70b-versatile"   # modelo gratuito y excelente para traducción

# ------------------------------------------------------------
# Diccionario de idiomas para los selectores
# ------------------------------------------------------------
IDIOMAS = {
    "Español": "Spanish",
    "Inglés": "English",
    "Francés": "French",
    "Alemán": "German",
    "Portugués": "Portuguese",
    "Italiano": "Italian",
    "Neerlandés": "Dutch",
    "Ruso": "Russian",
    "Chino (simplificado)": "Chinese (simplified)",
    "Japonés": "Japanese",
    "Coreano": "Korean",
    "Árabe": "Arabic",
    "Auto (detección automática)": "auto"
}

# ------------------------------------------------------------
# Funciones de extracción de texto
# ------------------------------------------------------------
def extraer_texto_pdf(pdf_file):
    """Extrae texto de un PDF con capa de texto digital (no escaneado)."""
    doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
    texto = "\n".join([pagina.get_text() for pagina in doc])
    return texto

def extraer_texto_pdf_escaneado(pdf_file):
    """Convierte PDF a imágenes y aplica OCR a cada página."""
    imagenes = convert_from_bytes(pdf_file.read())
    texto = ""
    for img in imagenes:
        texto += pytesseract.image_to_string(img, lang='spa+eng') + "\n"
    return texto

def extraer_texto_imagen(imagen_file):
    """Aplica OCR a una imagen (PNG, JPG...)."""
    img = Image.open(imagen_file)
    return pytesseract.image_to_string(img, lang='spa+eng')

def extraer_texto_docx(docx_file):
    """Extrae texto de un archivo .docx."""
    doc = Document(docx_file)
    return "\n".join([para.text for para in doc.paragraphs])

# ------------------------------------------------------------
# División del texto en trozos
# ------------------------------------------------------------
def dividir_texto(texto, max_chars=6000):
    """Divide el texto en fragmentos sin cortar palabras (máximo 6000 caracteres por trozo)."""
    parrafos = texto.split('\n')
    chunks = []
    chunk_actual = ""
    for p in parrafos:
        if len(chunk_actual) + len(p) < max_chars:
            chunk_actual += p + "\n"
        else:
            if chunk_actual.strip():
                chunks.append(chunk_actual.strip())
            chunk_actual = p + "\n"
    if chunk_actual.strip():
        chunks.append(chunk_actual.strip())
    return chunks

# ------------------------------------------------------------
# Traducción con Groq (reintentos automáticos por si acaso)
# ------------------------------------------------------------
@retry(
    retry=retry_if_exception_type(Exception),  # captura cualquier error de red o API
    wait=wait_exponential(multiplier=2, min=2, max=30),
    stop=stop_after_attempt(3)
)
def traducir_chunk(texto, idioma_origen, idioma_destino):
    """Traduce un fragmento y devuelve el texto en formato Markdown."""
    # Construir prompt
    if idioma_origen == "auto":
        origen_str = "el idioma detectado automáticamente"
    else:
        origen_str = idioma_origen

    prompt = f"""Traduce el siguiente texto del {origen_str} al {idioma_destino}.
Devuelve ÚNICAMENTE la traducción en formato Markdown, conservando títulos, listas, negritas, itálicas, enlaces y cualquier otra estructura.
No añadas ningún comentario ni nota.
Texto:
{texto}"""

    respuesta = client.chat.completions.create(
        model=MODELO,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,  # favorece la precisión
    )
    return respuesta.choices[0].message.content

# ------------------------------------------------------------
# Creación de archivos de salida (Word y PDF desde Markdown)
# ------------------------------------------------------------
def crear_docx_desde_markdown(markdown):
    """Crea un archivo .docx interpretando el Markdown básico."""
    doc = Document()
    for linea in markdown.split('\n'):
        linea = linea.strip()
        if not linea:
            doc.add_paragraph('')
            continue
        # Títulos
        if linea.startswith('#'):
            nivel = len(re.match(r'^#+', linea).group())
            texto = linea.lstrip('#').strip()
            doc.add_heading(texto, level=min(nivel, 9))
        # Listas no ordenadas
        elif linea.startswith('- ') or linea.startswith('* '):
            doc.add_paragraph(linea[2:], style='List Bullet')
        # Listas ordenadas (simples)
        elif re.match(r'^\d+\.\s', linea):
            doc.add_paragraph(linea, style='List Number')
        else:
            # Aquí se podría procesar Markdown inline, pero lo dejamos como texto
            doc.add_paragraph(linea)
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

def crear_pdf_desde_markdown(markdown):
    """Crea un PDF simple a partir de Markdown (solo texto, sin formato rico)."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    for linea in markdown.split('\n'):
        # Reemplazar caracteres no Latin-1 para evitar errores (puedes usar fuentes TTF para Unicode)
        linea_limpia = linea.encode('latin-1', 'replace').decode('latin-1')
        pdf.multi_cell(0, 10, txt=linea_limpia)
    return pdf.output(dest='S')

# ------------------------------------------------------------
# Interfaz de usuario
# ------------------------------------------------------------
st.sidebar.header("⚙️ Configuración de idiomas")
col1, col2 = st.sidebar.columns(2)
with col1:
    idioma_origen_key = st.selectbox(
        "Idioma de origen",
        list(IDIOMAS.keys()),
        index=list(IDIOMAS.keys()).index("Auto (detección automática)")
    )
with col2:
    idioma_destino_key = st.selectbox(
        "Idioma de destino",
        [k for k in IDIOMAS.keys() if k != "Auto (detección automática)"],
        index=0  # Español por defecto
    )

idioma_origen = IDIOMAS[idioma_origen_key]
idioma_destino = IDIOMAS[idioma_destino_key]

tipo_archivo = st.radio(
    "Tipo de documento a subir:",
    ("PDF (texto digital)", "PDF escaneado o imagen", "Word (.docx)"),
    horizontal=True
)

if tipo_archivo == "Word (.docx)":
    archivo = st.file_uploader("Sube tu archivo", type=["docx"])
else:
    archivo = st.file_uploader("Sube tu archivo", type=["pdf", "png", "jpg", "jpeg"])

# ------------------------------------------------------------
# Procesamiento al pulsar el botón
# ------------------------------------------------------------
if archivo and st.button("Traducir documento", type="primary"):
    with st.spinner("⏳ Extrayendo texto..."):
        # 1. Extraer el texto según el tipo de archivo
        if tipo_archivo == "PDF (texto digital)":
            texto_bruto = extraer_texto_pdf(archivo)
        elif tipo_archivo == "PDF escaneado o imagen":
            if archivo.type == "application/pdf":
                texto_bruto = extraer_texto_pdf_escaneado(archivo)
            else:
                texto_bruto = extraer_texto_imagen(archivo)
        else:  # Word
            texto_bruto = extraer_texto_docx(archivo)

        if not texto_bruto.strip():
            st.error("❌ No se pudo extraer texto. ¿El documento está vacío o la imagen es ilegible?")
            st.stop()

        st.success(f"✅ Texto extraído ({len(texto_bruto)} caracteres). Dividiendo en fragmentos...")

    # 2. Dividir en trozos
    chunks = dividir_texto(texto_bruto, max_chars=6000)
    st.info(f"📦 El documento se ha dividido en {len(chunks)} fragmento(s) para su traducción.")

    # 3. Traducir cada trozo con barra de progreso
    traducciones = []
    progreso = st.progress(0)
    for i, chunk in enumerate(chunks):
        with st.spinner(f"🌍 Traduciendo fragmento {i+1}/{len(chunks)}..."):
            trad = traducir_chunk(chunk, idioma_origen, idioma_destino)
            traducciones.append(trad)
            progreso.progress((i + 1) / len(chunks))
        # Pequeña pausa para no saturar la API (aunque Groq es muy generoso, 1 s es prudente)
        time.sleep(1)

    # 4. Unir las traducciones
    markdown_final = "\n\n".join(traducciones)

    # 5. Mostrar resultado
    st.success("🎉 ¡Traducción completada!")
    st.markdown("### Vista previa de la traducción")
    st.markdown(markdown_final)

    # 6. Botones de descarga
    col1, col2 = st.columns(2)
    with col1:
        docx_bytes = crear_docx_desde_markdown(markdown_final)
        st.download_button(
            label="⬇️ Descargar Word",
            data=docx_bytes,
            file_name="traduccion.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    with col2:
        pdf_bytes = crear_pdf_desde_markdown(markdown_final)
        st.download_button(
            label="⬇️ Descargar PDF",
            data=pdf_bytes,
            file_name="traduccion.pdf",
            mime="application/pdf"
        )
