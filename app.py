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
import os
from groq import Groq
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# ------------------------------------------------------------
# Configuración de la página
# ------------------------------------------------------------
st.set_page_config(page_title="Traductor de documentos", layout="wide")

# CSS para botones de descarga más grandes y vistosos
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
</style>
""", unsafe_allow_html=True)

st.title("🌐 Traductor de documentos a cualquier idioma")
st.markdown("Sube un PDF, imagen o Word y obtén una traducción **natural y con formato**.")

# ------------------------------------------------------------
# Cliente de Groq (gratuito)
# ------------------------------------------------------------
client = Groq(api_key=st.secrets["GROQ_API_KEY"])
MODELO = "llama-3.3-70b-versatile"

# ------------------------------------------------------------
# Idiomas disponibles
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
# Extracción de texto (PDF, imagen, Word)
# ------------------------------------------------------------
def extraer_texto_pdf(pdf_file):
    doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
    return "\n".join([pagina.get_text() for pagina in doc])

def extraer_texto_pdf_escaneado(pdf_file):
    imagenes = convert_from_bytes(pdf_file.read())
    texto = ""
    for img in imagenes:
        texto += pytesseract.image_to_string(img, lang='spa+eng') + "\n"
    return texto

def extraer_texto_imagen(imagen_file):
    img = Image.open(imagen_file)
    return pytesseract.image_to_string(img, lang='spa+eng')

def extraer_texto_docx(docx_file):
    doc = Document(docx_file)
    return "\n".join([para.text for para in doc.paragraphs])

# ------------------------------------------------------------
# División en trozos respetando secciones (doble salto de línea)
# ------------------------------------------------------------
def dividir_texto(texto, max_chars=6000):
    """Divide el texto en bloques basados en párrafos, pero sin romper secciones."""
    secciones = texto.split('\n\n')  # separamos por párrafos dobles
    chunks = []
    chunk_actual = ""
    for sec in secciones:
        if len(chunk_actual) + len(sec) < max_chars:
            chunk_actual += sec + "\n\n"
        else:
            if chunk_actual.strip():
                chunks.append(chunk_actual.strip())
            # Si una sola sección es más grande que max_chars, la dividimos por líneas
            if len(sec) > max_chars:
                lineas = sec.split('\n')
                sub_chunk = ""
                for linea in lineas:
                    if len(sub_chunk) + len(linea) < max_chars:
                        sub_chunk += linea + "\n"
                    else:
                        if sub_chunk.strip():
                            chunks.append(sub_chunk.strip())
                        sub_chunk = linea + "\n"
                if sub_chunk.strip():
                    chunks.append(sub_chunk.strip())
            else:
                chunk_actual = sec + "\n\n"
    if chunk_actual.strip():
        chunks.append(chunk_actual.strip())
    return chunks

# ------------------------------------------------------------
# Traducción con Groq (prompt mejorado para integridad y naturalidad)
# ------------------------------------------------------------
@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    stop=stop_after_attempt(3)
)
def traducir_chunk(texto, idioma_origen, idioma_destino, contexto=""):
    origen_str = "el idioma detectado automáticamente" if idioma_origen == "auto" else idioma_origen

    prompt = f"""Eres un traductor profesional especializado en conservar el formato y la integridad del texto.
Antes de traducir, analiza el estilo y tono del texto original (formal, técnico, informal, etc.).
Traduce el siguiente fragmento del {origen_str} al {idioma_destino} de manera **natural y fluida**, como si hubiera sido escrito originalmente en {idioma_destino}.
**NO omitas ningún contenido:** conserva todos los títulos, párrafos, listas, notas al pie y cualquier elemento presente.
Mantén el formato Markdown exactamente: encabezados (#, ##), negritas (**texto**), cursivas (*texto*), listas (- o 1.), enlaces, etc.
No añadas explicaciones ni comentarios, solo la traducción final.

Contexto del documento (para referencia):
{contexto}

Texto original a traducir:
{texto}"""

    respuesta = client.chat.completions.create(
        model=MODELO,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return respuesta.choices[0].message.content

# ------------------------------------------------------------
# Creación de Word mejorada (Markdown → docx con estilos)
# ------------------------------------------------------------
def aplicar_formato(paragraph, texto):
    """Aplica negritas y cursivas básicas dentro de un párrafo."""
    # Dividimos por marcas de Markdown
    partes = re.split(r'(\*\*.*?\*\*|\*.*?\*)', texto)
    for parte in partes:
        if parte.startswith('**') and parte.endswith('**'):
            run = paragraph.add_run(parte[2:-2])
            run.bold = True
        elif parte.startswith('*') and parte.endswith('*'):
            run = paragraph.add_run(parte[1:-1])
            run.italic = True
        else:
            paragraph.add_run(parte)

def crear_pdf_desde_markdown(markdown):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    for linea in markdown.split('\n'):
        # Reemplazar caracteres no soportados por latin-1
        linea_limpia = linea.encode('latin-1', 'replace').decode('latin-1')
        pdf.multi_cell(0, 10, txt=linea_limpia)
    return pdf.output(dest='S')

# ------------------------------------------------------------
# Creación de PDF con fuente latin
# ------------------------------------------------------------
def crear_pdf_desde_markdown(markdown):
    pdf = FPDF()
    pdf.add_page()
    # Buscar fuente DejaVu en el sistema
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    if not os.path.exists(font_path):
        # fallback por si no existe (muy raro en Cloud)
        st.warning("Fuente DejaVu no encontrada. Algunos caracteres podrían no mostrarse correctamente.")
        pdf.set_font("Arial", size=12)
    else:
        pdf.add_font("DejaVu", "", font_path, uni=True)
        pdf.set_font("DejaVu", size=12)

    for linea in markdown.split('\n'):
        # Limpiamos caracteres de control
        linea = linea.replace('\r', '')
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
        index=0
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
# Lógica de traducción
# ------------------------------------------------------------
if archivo and st.button("Traducir documento", type="primary"):
    with st.spinner("⏳ Extrayendo texto..."):
        if tipo_archivo == "PDF (texto digital)":
            texto_bruto = extraer_texto_pdf(archivo)
        elif tipo_archivo == "PDF escaneado o imagen":
            if archivo.type == "application/pdf":
                texto_bruto = extraer_texto_pdf_escaneado(archivo)
            else:
                texto_bruto = extraer_texto_imagen(archivo)
        else:
            texto_bruto = extraer_texto_docx(archivo)

        if not texto_bruto.strip():
            st.error("❌ No se pudo extraer texto. ¿El documento está vacío o la imagen es ilegible?")
            st.stop()
        st.success(f"✅ Texto extraído ({len(texto_bruto)} caracteres).")

    chunks = dividir_texto(texto_bruto, max_chars=6000)
    st.info(f"📦 Documento dividido en {len(chunks)} fragmento(s).")

    # Contexto: primeras 1000 letras del documento para orientar al modelo
    contexto_global = texto_bruto[:1000]

    traducciones = []
    progreso = st.progress(0)
    for i, chunk in enumerate(chunks):
        with st.spinner(f"🌍 Traduciendo fragmento {i+1}/{len(chunks)}..."):
            trad = traducir_chunk(chunk, idioma_origen, idioma_destino, contexto_global)
            traducciones.append(trad)
            progreso.progress((i + 1) / len(chunks))
        time.sleep(1)  # respeto a la API gratuita

    markdown_final = "\n\n".join(traducciones)

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
