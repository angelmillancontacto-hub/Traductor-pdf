import streamlit as st
import fitz  # PyMuPDF
import google.generativeai as genai
from docx import Document
from fpdf import FPDF
from pdf2image import convert_from_bytes
import pytesseract
from PIL import Image
import io
import re

# ------------------------------
# Configuración inicial
# ------------------------------
st.set_page_config(page_title="Traductor de documentos", layout="wide")
st.title("🌐 Traductor de documentos a cualquier idioma")

# Conectar con Gemini
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
modelo = genai.GenerativeModel('gemini-2.0-flash')

# Si usas Windows local, tal vez necesites indicar la ruta de Tesseract:
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
# En Streamlit Cloud no hace falta.

# ------------------------------
# Funciones auxiliares
# ------------------------------
def extraer_texto_pdf(pdf_file):
    """Extrae texto de un PDF (solo PDFs con texto digital, no escaneados)"""
    doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
    texto = "\n".join([pagina.get_text() for pagina in doc])
    return texto

def extraer_texto_imagen(imagen):
    """Aplica OCR a una imagen PIL y devuelve el texto"""
    return pytesseract.image_to_string(imagen, lang='spa+eng')  # puede detectar español e inglés

def extraer_texto_pdf_escaneado(pdf_file):
    """Convierte PDF a imágenes y aplica OCR a cada página"""
    imagenes = convert_from_bytes(pdf_file.read())
    texto = ""
    for img in imagenes:
        texto += pytesseract.image_to_string(img, lang='spa+eng') + "\n"
    return texto

def extraer_texto_docx(docx_file):
    """Extrae texto de un archivo .docx"""
    doc = Document(docx_file)
    return "\n".join([para.text for para in doc.paragraphs])

def dividir_texto(texto, max_chars=3000):
    """Divide el texto en fragmentos sin cortar palabras, por párrafos"""
    parrafos = texto.split('\n')
    chunks = []
    chunk_actual = ""
    for p in parrafos:
        if len(chunk_actual) + len(p) < max_chars:
            chunk_actual += p + "\n"
        else:
            chunks.append(chunk_actual.strip())
            chunk_actual = p + "\n"
    if chunk_actual:
        chunks.append(chunk_actual.strip())
    return chunks

def traducir_chunk(texto, idioma_origen, idioma_destino):
    """Traduce un fragmento con Gemini y devuelve el Markdown"""
    prompt = f"""Traduce el siguiente texto del {idioma_origen} al {idioma_destino}.
Devuelve ÚNICAMENTE la traducción en formato Markdown, conservando títulos, listas, negritas y estructura.
No añadas comentarios.
Texto:
{texto}"""
    respuesta = modelo.generate_content(prompt)
    return respuesta.text

def crear_docx_desde_markdown(markdown):
    """Crea un archivo .docx a partir de un texto en Markdown (estilos simples)"""
    doc = Document()
    for linea in markdown.split('\n'):
        linea = linea.strip()
        if linea.startswith('#'):
            # Contar cuántos # para el nivel de título
            nivel = len(re.match(r'^#+', linea).group())
            doc.add_heading(linea.lstrip('#').strip(), level=min(nivel, 9))
        elif linea.startswith('- ') or linea.startswith('* '):
            doc.add_paragraph(linea[2:], style='List Bullet')
        elif linea == '':
            doc.add_paragraph('')
        else:
            # Podrías detectar negritas con **texto** y aplicar estilo, pero por ahora texto simple
            doc.add_paragraph(linea)
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

def crear_pdf_desde_markdown(markdown):
    """Crea un PDF simple desde Markdown (mejorable)"""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    for linea in markdown.split('\n'):
        # Reemplazar caracteres no soportados por latin-1
        linea_limpia = linea.encode('latin-1', 'replace').decode('latin-1')
        pdf.cell(200, 10, txt=linea_limpia, ln=True)
    return pdf.output(dest='S')

# ------------------------------
# Interfaz de usuario
# ------------------------------
st.sidebar.header("⚙️ Configuración de idiomas")
idioma_origen = st.sidebar.text_input("Idioma de origen (ej. English, French, Chinese, auto)", value="auto")
idioma_destino = st.sidebar.text_input("Idioma de destino", value="Spanish")
st.sidebar.info("Puedes escribir 'auto' para que la IA detecte el idioma de origen automáticamente.")

tipo_archivo = st.radio("Tipo de documento a subir:",
                        ("PDF (texto digital)", "PDF escaneado o imagen", "Word (.docx)"))

archivo = st.file_uploader("Sube tu archivo",
                           type=["pdf", "docx", "png", "jpg", "jpeg"] if tipo_archivo != "Word (.docx)" else ["docx"])

if archivo and st.button("Traducir documento"):
    with st.spinner("⏳ Procesando..."):
        # 1. Extraer texto según tipo
        if tipo_archivo == "PDF (texto digital)":
            texto_bruto = extraer_texto_pdf(archivo)
        elif tipo_archivo == "PDF escaneado o imagen":
            if archivo.type == "application/pdf":
                texto_bruto = extraer_texto_pdf_escaneado(archivo)
            else:  # imagen
                imagen = Image.open(archivo)
                texto_bruto = pytesseract.image_to_string(imagen, lang='spa+eng')
        else:  # Word
            texto_bruto = extraer_texto_docx(archivo)

        if not texto_bruto.strip():
            st.error("No se pudo extraer texto. ¿El documento está vacío o la imagen es ilegible?")
            st.stop()

        # 2. Dividir en trozos
        chunks = dividir_texto(texto_bruto, max_chars=3000)
        traducciones = []
        progreso = st.progress(0)
        for i, chunk in enumerate(chunks):
            trad = traducir_chunk(chunk, idioma_origen, idioma_destino)
            traducciones.append(trad)
            progreso.progress((i+1)/len(chunks))

        # 3. Unir traducciones
        markdown_final = "\n\n".join(traducciones)

        # 4. Mostrar y descargar
        st.success("✅ Traducción completada")
        st.markdown(markdown_final)

        col1, col2 = st.columns(2)
        with col1:
            st.download_button("⬇️ Descargar Word",
                               data=crear_docx_desde_markdown(markdown_final),
                               file_name="traduccion.docx")
        with col2:
            st.download_button("⬇️ Descargar PDF",
                               data=crear_pdf_desde_markdown(markdown_final),
                               file_name="traduccion.pdf")
