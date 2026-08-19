import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import io
import re
import pdfplumber
from difflib import get_close_matches
import google.generativeai as genai
import fitz  # PyMuPDF
from PIL import Image as PILImage

# Imports do ReportLab para geração do PDF
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as ReportLabImage, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# -----------------------------------------------------------------------------
# DICIONÁRIO GEOTÉCNICO DE SOLOS (Parâmetros exatos Aoki-Velloso e Molas)
# -----------------------------------------------------------------------------
PARAMETROS_SOLO = {
    "Aterro":                {"aoki_K": 0,    "aoki_alpha": 0.000, "alpha_k": 800,  "comportamento": "intermediario"},
    "Areia":                 {"aoki_K": 1000, "aoki_alpha": 0.014, "alpha_k": 3000, "comportamento": "granular"},
    "Areia Siltosa":         {"aoki_K": 800,  "aoki_alpha": 0.020, "alpha_k": 2800, "comportamento": "granular"},
    "Areia Silto-argilosa":  {"aoki_K": 700,  "aoki_alpha": 0.024, "alpha_k": 2500, "comportamento": "granular"},
    "Areia Argilosa":        {"aoki_K": 600,  "aoki_alpha": 0.030, "alpha_k": 2500, "comportamento": "granular"},
    "Areia Argilo-siltosa":  {"aoki_K": 500,  "aoki_alpha": 0.028, "alpha_k": 2500, "comportamento": "granular"},
    "Silte":                 {"aoki_K": 400,  "aoki_alpha": 0.030, "alpha_k": 2000, "comportamento": "intermediario"},
    "Silte Arenoso":         {"aoki_K": 550,  "aoki_alpha": 0.022, "alpha_k": 2500, "comportamento": "granular"},
    "Silte Areno-argiloso":  {"aoki_K": 450,  "aoki_alpha": 0.028, "alpha_k": 2200, "comportamento": "intermediario"},
    "Silte Argiloso":        {"aoki_K": 230,  "aoki_alpha": 0.034, "alpha_k": 2000, "comportamento": "coesivo"},
    "Silte Argilo-arenoso":  {"aoki_K": 250,  "aoki_alpha": 0.030, "alpha_k": 2000, "comportamento": "coesivo"},
    "Argila":                {"aoki_K": 200,  "aoki_alpha": 0.060, "alpha_k": 1500, "comportamento": "coesivo"},
    "Argila Arenosa":        {"aoki_K": 350,  "aoki_alpha": 0.024, "alpha_k": 2000, "comportamento": "coesivo"},
    "Argila Areno-siltosa":  {"aoki_K": 300,  "aoki_alpha": 0.028, "alpha_k": 1800, "comportamento": "coesivo"},
    "Argila Silto-arenosa":  {"aoki_K": 250,  "aoki_alpha": 0.030, "alpha_k": 1800, "comportamento": "coesivo"},
    "Argila Siltosa":        {"aoki_K": 220,  "aoki_alpha": 0.040, "alpha_k": 1750, "comportamento": "coesivo"}
}

OPCOES_SOLO = list(PARAMETROS_SOLO.keys())

FATORES_CONSTRUTIVOS = {
    "Franki": {"F1": 2.5, "F2": 5.0},
    "Metálica": {"F1": 1.8, "F2": 4.0},
    "Pré-moldada": {"F1": 1.8, "F2": 4.0},
    "Escavada": {"F1": 3.0, "F2": 6.0},
    "Raiz/Hélice": {"F1": 2.0, "F2": 4.0}
}

st.set_page_config(page_title="Dimensionamento de Estacas", page_icon="🏗️", layout="wide")
st.title("🏗️ Dimensionamento e Integração Solo-Estrutura")
st.caption("Leitor de PDF, Verificação Geotécnica, Esforços, Armação e Quantitativos")

# -----------------------------------------------------------------------------
# SIDEBAR - PARÂMETROS
# -----------------------------------------------------------------------------
st.sidebar.header("📋 Geometria da Fundação")
tipo_fundacao = st.sidebar.selectbox("Tipo de Fundação", ["Profunda (Estaca)", "Rasa (Sapata/Radier)"])

if tipo_fundacao == "Profunda (Estaca)":
    metodo_construtivo = st.sidebar.selectbox("Método Construtivo:", list(FATORES_CONSTRUTIVOS.keys()), index=4)
else:
    metodo_construtivo = "Raiz/Hélice"

secao = st.sidebar.selectbox("Geometria da Seção", ["Circular", "Quadrada"])
B = st.sidebar.number_input("Largura/Diâmetro B (m)", min_value=0.1, value=0.30, step=0.05)
cota_assentamento = st.sidebar.number_input("Cota de Arrasamento (m)", min_value=0.0, value=0.0, step=0.5)
comprimento_estaca = st.sidebar.number_input("Comprimento da Estaca (m)", min_value=1.0, value=15.0, step=0.5) if tipo_fundacao == "Profunda (Estaca)" else 0.0
nu = st.sidebar.slider("Coeficiente de Poisson (v)", min_value=0.1, max_value=0.5, value=0.35, step=0.01)

st.sidebar.markdown("---")
st.sidebar.header("💧 Condições do Lençol Freático")
tem_na = st.sidebar.checkbox("Considerar Nível d'Água (N.A.)?", value=False)
nivel_agua = st.sidebar.number_input("Profundidade do N.A. (m)", min_value=0.0, value=3.0, step=0.5) if tem_na else 999.0

st.sidebar.markdown("---")
st.sidebar.header("⚖️ Cargas e Material")
fck = st.sidebar.number_input("Resistência do Concreto (fck) em MPa", min_value=15.0, value=25.0, step=5.0)
taxa_armadura = st.sidebar.number_input("Taxa de Armadura Longitudinal (%)", min_value=0.1, value=0.5, step=0.1)
fyk = st.sidebar.number_input("Resistência do Aço (fyk) em MPa", min_value=250.0, value=500.0, step=50.0)

st.sidebar.markdown("---")
st.sidebar.header("🔽 Esforços Atuantes (Topo)")
carga_V = st.sidebar.number_input("Carga Vertical (kN)", min_value=0.0, value=250.0, step=50.0)
carga_H = st.sidebar.number_input("Força Horizontal (kN)", min_value=0.0, value=20.0, step=5.0)
carga_M = st.sidebar.number_input("Momento Fletor (kN.m)", min_value=0.0, value=0.0, step=5.0)

# -----------------------------------------------------------------------------
# TABELA DE SONDAGEM SPT E LEITOR DE PDF HÍBRIDO (MAPEAMENTO + IA VISUAL)
# -----------------------------------------------------------------------------
col_esq, col_dir = st.columns([1.2, 1])

with col_esq:
    st.subheader("📑 Boletim de Sondagem SPT")
    st.info("🤖 **Leitor Híbrido:** O sistema detecta os furos do PDF e a IA analisa visualmente a página do furo escolhido.")
    st.markdown("[👉 **Clique aqui para gerar sua API Key gratuita no Google AI Studio**](https://aistudio.google.com/app/apikey)")
    
    api_key = st.text_input("🔑 Insira sua API Key do Google Gemini:", type="password")
    arquivo_pdf = st.file_uploader("📥 Importar Laudo de Sondagem (PDF)", type=["pdf"])
    
    # 1. Tabela padrão na sessão caso ainda não exista
    if "tabela_spt" not in st.session_state:
        st.session_state.tabela_spt = pd.DataFrame({
            "Profundidade (m)": list(range(1, 16)),
            "N_SPT": [6, 8, 4, 5, 8, 11, 5, 7, 8, 11, 11, 12, 18, 21, 24],
            "Tipo de Solo": ["Aterro", "Aterro"] + ["Argila"] * 13
        })

    if arquivo_pdf is not None:
        try:
            arquivo_pdf.seek(0)
            bytes_pdf = arquivo_pdf.read()
            doc = fitz.open(stream=bytes_pdf, filetype="pdf")
            
            furos_map = {}
            for page_num in range(len(doc)):
                page_text = doc[page_num].get_text()
                matches = re.findall(r'\b(SP\s*-\s*\d+|SP\s*\d+|Furo\s*[A-Z0-9\-]+)\b', page_text, re.IGNORECASE)
                for m in matches:
                    nome_limpo = re.sub(r'\s+', '', m.upper())
                    if nome_limpo.startswith("SP") and "-" not in nome_limpo:
                        nome_limpo = nome_limpo[:2] + "-" + nome_limpo[2:]
                    if nome_limpo not in furos_map:
                        furos_map[nome_limpo] = page_num
            
            # Se for PDF escaneado (sem texto detectável por regex), lista por páginas
            if not furos_map:
                for p in range(len(doc)):
                    furos_map[f"Página {p+1}"] = p
                    
            st.session_state["furos_map"] = furos_map
        except Exception as e:
            st.error(f"Erro ao ler arquivo PDF: {e}")

        if "furos_map" in st.session_state and st.session_state["furos_map"]:
            opcoes_furos = list(st.session_state["furos_map"].keys())
            furo_selecionado = st.selectbox("📌 Selecione o Furo Encontrado:", opcoes_furos)
            
            if st.button("Processar Furo Selecionado com IA", width="stretch"):
                if not api_key:
                    st.warning("⚠️ Insira sua Chave de API do Gemini no campo acima.")
                else:
                    with st.spinner(f"Analisando visualmente o furo {furo_selecionado}..."):
                        try:
                            genai.configure(api_key=api_key)
                            modelo_visao = genai.GenerativeModel('gemini-3.6-flash')
                            
                            page_idx = st.session_state["furos_map"][furo_selecionado]
                            page = doc.load_page(page_idx)
                            pix = page.get_pixmap(dpi=150)
                            b_data = pix.tobytes("png")
                            img = PILImage.open(io.BytesIO(b_data))
                            
                            lista_solos_str = ", ".join(OPCOES_SOLO)
                            prompt = f"""
                            Você é um engenheiro geotécnico especialista em ler laudos de sondagem SPT.
                            Analise a imagem desta página de laudo.
                            
                            TAREFA:
                            Localize a tabela do furo "{furo_selecionado}" nesta página.
                            Extraia metro a metro a profundidade, o N_SPT e o tipo de solo.
                            
                            FORMATO DE SAÍDA:
                            Retorne os dados ESTRITAMENTE em formato CSV, sem markdown, sem explicações.
                            O cabeçalho deve ser exatamente: Profundidade (m);N_SPT;Tipo de Solo
                            
                            Regras:
                            1. Profundidade deve ser número inteiro sequencial (1, 2, 3...) do furo.
                            2. N_SPT é o número de golpes final daquele metro (se houver fração como 13/29, use apenas 13).
                            3. O Tipo de Solo deve ser ESCOLHIDO obrigatoriamente a partir desta lista: {lista_solos_str}. Aproxime se necessário.
                            Não escreva NENHUM texto além do formato CSV separado por ponto e vírgula (;).
                            """
                            
                            resposta = modelo_visao.generate_content([prompt, img])
                            texto_csv = resposta.text.replace("```csv", "").replace("
