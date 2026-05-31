import streamlit as st
import fitz  # PyMuPDF
from docx import Document
from fpdf import FPDF  # ahora es fpdf2 (Unicode)
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

# CSS personalizado para botones más llamativos
st.markdown("""
<style>
    .stDownloadButton button {
        font-size: 18px !important;
        font-weight: bold !important;
        background-color: #FF4B4B !important;
        color: white !important;
        padding: 0.75em 2em !important;
        border-radius: 12px !important;
        border: none !important;
        box-shadow: 2px 2px 10px rgba(0,0,0,0.2);
        transition: transform 0.2s;
    }
    .stDownloadButton button:hover {
        background-color: #e04343 !important;
        transform: scale(1.05);
    }
    /* Ocultar la vista previa del markdown accidental */
    .element-container:has(.stMarkdown) + .stDownloadButton {
        margin-top: 1rem;
    }
</style>
""", unsafe_allow_html=True)

st.title("🌐 Traductor de documentos a cualquier idioma")
st.markdown("Sube un PDF, imagen o Word y obtén una traducción **natural y con formato**.")

# ------------------------------------------------------------
# Cliente de Groq (100 % gratuito)
# ------------------------------------------------------------
client = Groq(api_key=st.secrets["GROQ_API_KEY"])
MODELO = "llama-3.3-70b-versatile"

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
    """Extrae texto de un PDF con capa de texto digital."""
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
# División del texto en trozos (más grandes, menos peticiones)
# ------------------------------------------------------------
def dividir_texto(texto, max_chars=6000):
    """Divide el texto en fragmentos sin cortar palabras."""
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
# Traducción con Groq (prompt mejorado para naturalidad)
# ------------------------------------------------------------
@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    stop=stop_after_attempt(3)
)
def traducir_chunk(texto, idioma_origen, idioma_destino):
    """Traduce un fragmento con análisis de contexto y estilo."""
    origen_str = "el idioma detectado automáticamente" if idioma_origen == "auto" else idioma_origen

    prompt = f"""Eres un traductor profesional. Antes de traducir, analiza brevemente el tono, estilo y propósito del texto original (formal, técnico, coloquial, etc.). Luego, traduce el siguiente texto del {origen_str} al {idioma_destino} de manera **natural y fluida**, como si hubiera sido escrito originalmente en {idioma_destino}. Conserva el formato Markdown: títulos, listas, negritas, itálicas, enlaces. No añadas explicaciones ni notas, solo la traducción final.

Texto original:
{texto}"""

    respuesta = client.chat.completions.create(
        model=MODELO,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,  # un poco más de creatividad para naturalidad
    )
    return respuesta.choices[0].message.content

# ------------------------------------------------------------
# Creación de Word mejorada (desde Markdown)
# ------------------------------------------------------------
def crear_docx_desde_markdown(markdown):
    """Genera un .docx interpretando Markdown (títulos, listas, párrafos)."""
    doc = Document()
    for linea in markdown.split('\n'):
        linea = linea.strip()
        if not linea:
            doc.add_paragraph('')
            continue
        if linea.startswith('#'):
            nivel = len(re.match(r'^#+', linea).group())
            doc.add_heading(linea.lstrip('#').strip(), level=min(nivel, 9))
        elif linea.startswith('- ') or linea.startswith('* '):
            doc.add_paragraph(linea[2:], style='List Bullet')
        elif re.match(r'^\d+\.\s', linea):
            doc.add_paragraph(linea, style='List Number')
        else:
            doc.add_paragraph(linea)
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

# ------------------------------------------------------------
# Creación de PDF con soporte Unicode (fpdf2)
# ------------------------------------------------------------
def crear_pdf_desde_markdown(markdown):
    """Crea un PDF con texto Unicode (sin límite de latin-1)."""
    pdf = FPDF()
    pdf.add_page()
    pdf.add_font("NotoSans", "", "NotoSans-Regular.ttf", uni=True)  # fuente incluida en fpdf2
    pdf.set_font("NotoSans", size=12)
    for linea in markdown.split('\n'):
        pdf.multi_cell(0, 10, txt=linea)
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
        index=0  # Español
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
        # 1. Extraer el texto según el tipo
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

        st.success(f"✅ Texto extraído ({len(texto_bruto)} caracteres). Preparando traducción...")

    # 2. Dividir en trozos
    chunks = dividir_texto(texto_bruto, max_chars=6000)
    st.info(f"📦 El documento se ha dividido en {len(chunks)} fragmento(s).")

    # 3. Traducir cada trozo con barra de progreso
    traducciones = []
    progreso = st.progress(0)
    for i, chunk in enumerate(chunks):
        with st.spinner(f"🌍 Traduciendo fragmento {i+1}/{len(chunks)}..."):
            trad = traducir_chunk(chunk, idioma_origen, idioma_destino)
            traducciones.append(trad)
            progreso.progress((i + 1) / len(chunks))
        time.sleep(1)  # pausa mínima para respetar la API

    # 4. Unir las traducciones
    markdown_final = "\n\n".join(traducciones)

    # 5. Sin vista previa – solo mensaje y botones de descarga
    st.success("🎉 ¡Traducción completada!")

    col1, col2 = st.columns(2)
    with col1:
        docx_bytes = crear_docx_desde_markdown(markdown_final)
        st.download_button(
            label="⬇️ DESCARGAR WORD",
            data=docx_bytes,
            file_name="traduccion.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    with col2:
        pdf_bytes = crear_pdf_desde_markdown(markdown_final)
        st.download_button(
            label="⬇️ DESCARGAR PDF",
            data=pdf_bytes,
            file_name="traduccion.pdf",
            mime="application/pdf"
        )
