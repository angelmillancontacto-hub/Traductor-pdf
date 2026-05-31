import streamlit as st
import fitz
import google.generativeai as genai
from docx import Document
from fpdf import FPDF
import io

st.set_page_config(page_title="Reconstructor IA", layout="wide")
st.title("🚀 Reconstructor de Reportes (Word + PDF)")

genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
modelo = genai.GenerativeModel('gemini-2.0-flash')

def extraer_texto(pdf_file):
    doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
    return "\n".join([pagina.get_text() for pagina in doc])

def crear_docx(markdown):
    doc = Document()
    for linea in markdown.split('\n'):
        if linea.startswith('#'): doc.add_heading(linea.replace('#', '').strip(), level=1)
        elif linea.startswith('-'): doc.add_paragraph(linea.replace('-', '').strip(), style='List Bullet')
        else: doc.add_paragraph(linea)
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

def crear_pdf(markdown):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    for linea in markdown.split('\n'):
        pdf.cell(200, 10, txt=linea.encode('latin-1', 'replace').decode('latin-1'), ln=True)
    return pdf.output(dest='S')

archivo = st.file_uploader("Sube tu PDF", type="pdf")

if archivo and st.button("Traducir y Reconstruir"):
    with st.spinner("Procesando..."):
        texto_bruto = extraer_texto(archivo)
        prompt = f"Traduce al español y estructura en Markdown: {texto_bruto}"
        markdown_final = modelo.generate_content(prompt).text
        
        st.markdown(markdown_final)
        
        # Botones de descarga
        st.download_button("⬇️ Descargar Word", data=crear_docx(markdown_final), file_name="reporte.docx")
        st.download_button("⬇️ Descargar PDF", data=crear_pdf(markdown_final), file_name="reporte.pdf")
