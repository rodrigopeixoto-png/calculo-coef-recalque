import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import io
import re
import json
import os
import datetime
import fitz  # PyMuPDF
from PIL import Image as PILImage
import google.generativeai as genai

# Imports do ReportLab para geração do PDF
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as ReportLabImage, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# -----------------------------------------------------------------------------
# DICIONÁRIO GEOTÉCNICO DE SOLOS E CONSTANTES
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

st.set_page_config(page_title="Dimensionamento de Estacas UTEA", page_icon="🏗️", layout="wide")

# -----------------------------------------------------------------------------
# ESTADO DA APLICAÇÃO (CARRINHO DE FUROS)
# -----------------------------------------------------------------------------
if 'projeto_furos' not in st.session_state:
    st.session_state.projeto_furos = {} # { 'SP-01': {'df': dataframe, 'imagem': bytes} }

if 'furo_atual_df' not in st.session_state:
    st.session_state.furo_atual_df = pd.DataFrame({
        "Profundidade (m)": list(range(1, 16)),
        "N_SPT": [6, 8, 4, 5, 8, 11, 5, 7, 8, 11, 11, 12, 18, 21, 24],
        "Tipo de Solo": ["Aterro", "Aterro"] + ["Argila"] * 13
    })
if 'furo_atual_img' not in st.session_state:
    st.session_state.furo_atual_img = None
if 'furo_atual_nome' not in st.session_state:
    st.session_state.furo_atual_nome = "SP-01"

# -----------------------------------------------------------------------------
# SIDEBAR - CABEÇALHO INSTITUCIONAL E PARÂMETROS GLOBAIS
# -----------------------------------------------------------------------------
logo_path = "fundo_transparente_2.png"
if os.path.exists(logo_path):
    st.sidebar.image(logo_path, use_container_width=True)

st.sidebar.header("📝 Identificação do Projeto")
nome_obra = st.sidebar.text_input("Nome da Obra", value="Edificação Pública - Delegacia Cidadã")
resp_tecnico = st.sidebar.text_input("Responsável Técnico", value="Eng. ")

st.sidebar.markdown("---")
st.sidebar.header("📋 Geometria da Fundação Global")
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

st.sidebar.markdown("---")
st.sidebar.header("🔧 Detalhamento da Armadura")
bitola = st.sidebar.selectbox("Bitola Longitudinal (mm)", [10.0, 12.5, 16.0, 20.0, 25.0], index=0)

override_l = st.sidebar.checkbox("Ajustar Comprimento Manualmente?", value=False)
L_armadura_manual = None
if override_l:
    limite_maximo = float(comprimento_estaca) if comprimento_estaca > 3.0 else 3.0
    L_armadura_manual = st.sidebar.number_input(
        "Comprimento da Gaiola (m)", 
        min_value=3.0, 
        max_value=limite_maximo, 
        value=limite_maximo, 
        step=0.5
    )
else:
    st.sidebar.info("O comprimento da armadura será calculado automaticamente para cada furo conforme a norma.")


# -----------------------------------------------------------------------------
# FUNÇÃO NÚCLEO DE CÁLCULO (ENCAPSULADA PARA PROCESSAR MÚLTIPLOS FUROS)
# -----------------------------------------------------------------------------
def processar_calculos_estaca(df_original, l_arm_manual=None):
    df_spt = df_original.copy()
    df_spt["Profundidade (m)"] = range(1, len(df_spt) + 1)
    df_spt["N_SPT"] = pd.to_numeric(df_spt["N_SPT"], errors="coerce").fillna(1)
    df_spt["Tipo de Solo"] = df_spt["Tipo de Solo"].fillna("Argila")
    df_spt["N_corr"] = df_spt["N_SPT"].apply(lambda x: min(x, 50))
    df_spt["N_Aoki"] = df_spt["N_SPT"].apply(lambda x: min(x, 50))

    Area_c = (np.pi * B**2) / 4 if secao == "Circular" else B**2
    Inercia_c = (np.pi * B**4) / 64 if secao == "Circular" else (B**4) / 12
    Perimetro = np.pi * B if secao == "Circular" else 4 * B
    E_c = 5600 * np.sqrt(fck) * 1000 
    f1, f2 = FATORES_CONSTRUTIVOS[metodo_construtivo]["F1"], FATORES_CONSTRUTIVOS[metodo_construtivo]["F2"]

    def proc_solo(row):
        solo = PARAMETROS_SOLO.get(row["Tipo de Solo"], PARAMETROS_SOLO["Argila"])
        n, prof = row["N_corr"], row["Profundidade (m)"]
        fator_agua = 0.5 if (prof >= nivel_agua and solo["comportamento"] == "granular") else 1.0
        es = solo["alpha_k"] * n * fator_agua
        k1 = 1200 * n * fator_agua
        kv = k1 * (0.3 / B) if solo["comportamento"] == "coesivo" else k1 * ((B + 0.3) / (2 * B)) ** 2
        kh = kv * nu
        rl = (solo["aoki_alpha"] * solo["aoki_K"] * n) / f2
        rp = (solo["aoki_K"] * row["N_Aoki"]) / f1 * Area_c
        delta_rl = rl * Perimetro * 1.0 
        return pd.Series([es, kv, kh, rl, rp, delta_rl])

    df_spt[["Es (kPa)", "kv (kN/m³)", "kh (kN/m³)", "rl (kPa)", "Rp (kN)", "delta_Rl (kN)"]] = df_spt.apply(proc_solo, axis=1)

    cota_fim = cota_assentamento + (comprimento_estaca if tipo_fundacao == "Profunda (Estaca)" else 1.5 * B)
    df_inf = df_spt[(df_spt["Profundidade (m)"] > cota_assentamento) & (df_spt["Profundidade (m)"] <= cota_fim)].copy()

    if not df_inf.empty:
        df_inf["Rl Acum. (kN)"] = df_inf["delta_Rl (kN)"].cumsum()
        df_inf["Rc Adm (kN)"] = (df_inf["Rp (kN)"] + df_inf["Rl Acum. (kN)"]) / 2.0
    else:
        df_inf = df_spt.head(1).copy()
        df_inf["Rl Acum. (kN)"] = 0; df_inf["Rc Adm (kN)"] = 0

    kh_global = df_inf["kh (kN/m³)"].mean()
    if tipo_fundacao == "Rasa (Sapata/Radier)":
        kv_global = df_inf["kv (kN/m³)"].mean()
    else:
        n_ponta = df_inf.iloc[-1]["N_corr"]
        es_ponta = 1000 * n_ponta if "Escavada" in metodo_construtivo else 3000 * n_ponta
        kv_global = es_ponta / (B * (1 - nu**2) * 0.85)

    Q_adm = df_inf.iloc[-1]["Rc Adm (kN)"] if not df_inf.empty else 0

    K_linha = kh_global * B
    lamb = (K_linha / (4 * E_c * Inercia_c)) ** 0.25
    z_vals = np.linspace(0, comprimento_estaca if tipo_fundacao == "Profunda (Estaca)" else 1, 200)

    y_disp = (np.exp(-lamb * z_vals) / (2 * E_c * Inercia_c * lamb**3)) * (carga_H * np.cos(lamb * z_vals) + lamb * carga_M * (np.cos(lamb * z_vals) + np.sin(lamb * z_vals)))
    m_flet = (np.exp(-lamb * z_vals) / lamb) * (carga_H * np.sin(lamb * z_vals) + lamb * carga_M * (np.cos(lamb * z_vals) - np.sin(lamb * z_vals)))
    momento_max_atuante = np.max(np.abs(m_flet)) if len(m_flet) > 0 else 0
    deslocamento_max_mm = np.max(np.abs(y_disp)) * 1000 if len(y_disp) > 0 else 0
    m_flet_unit = (np.exp(-lamb * z_vals) / lamb) * (1.0 * np.sin(lamb * z_vals))
    momento_max_unit = np.max(np.max(np.abs(m_flet_unit)))

    f_ctk_inf = 0.21 * (fck ** (2/3)) * 1000 
    W_c = Inercia_c / (B / 2) 
    alpha_flexao = 1.5 if secao == "Quadrada" else 1.2
    M_cr = W_c * (alpha_flexao * f_ctk_inf + (carga_V / Area_c)) 

    idx_max_m = np.argmax(np.abs(m_flet))
    m_apos_max = np.abs(m_flet[idx_max_m:])
    z_apos_max = z_vals[idx_max_m:]
    idx_nulo = np.where(m_apos_max <= M_cr)[0]
    z_momento_nulo = z_apos_max[idx_nulo[0]] if len(idx_nulo) > 0 else comprimento_estaca

    # Define o comprimento da armadura (automático ou manual)
    L_armadura_calc = min(comprimento_estaca, max(max(3.0, 5 * B), z_momento_nulo + 0.40)) if tipo_fundacao == "Profunda (Estaca)" else 0.0
    if l_arm_manual is not None:
        L_armadura_calc = float(l_arm_manual)

    area_barra = (np.pi * (bitola / 1000)**2) / 4  
    n_barras = max(int(np.ceil((taxa_armadura / 100) * Area_c / area_barra)), 6)
    if secao == "Quadrada": n_barras = max(n_barras + (4 - n_barras % 4) if n_barras % 4 != 0 else n_barras, 8)

    M_rd = n_barras * area_barra * ((fyk / 1.15) * 1000) * (0.75 * B if secao == "Circular" else 0.80 * B)
    H_rd = M_rd / momento_max_unit if momento_max_unit > 0 else 0
    V_concreto = Area_c * comprimento_estaca
    peso_long = n_barras * area_barra * L_armadura_calc * 7850
    peso_estribo = int(L_armadura_calc / 0.15) * (np.pi * (B - 0.08) if secao == "Circular" else 4 * (B - 0.08)) * ((np.pi * (6.3 / 1000)**2) / 4) * 7850
    peso_aco_total = peso_long + peso_estribo

    return {
        "df_spt": df_spt, "df_inf": df_inf, "Q_adm": Q_adm, "kv_global": kv_global, "kh_global": kh_global,
        "momento_max_atuante": momento_max_atuante, "M_rd": M_rd, "H_rd": H_rd, "deslocamento_max_mm": deslocamento_max_mm,
        "L_armadura": L_armadura_calc, "n_barras": n_barras, "V_concreto": V_concreto, "peso_aco_total": peso_aco_total,
        "z_vals": z_vals, "m_flet": m_flet, "y_disp": y_disp, "M_cr": M_cr, "peso_long": peso_long, "peso_estribo": peso_estribo
    }


# TÍTULO PRINCIPAL
st.title("🏗️ Projeto Integrado de Fundações")
st.caption("Múltiplos Furos, Verificação Geotécnica, Esforços e Memorial Completo")

# -----------------------------------------------------------------------------
# COLUNA ESQUERDA: IMPORTAÇÃO E IA (O "CARRINHO DE COMPRAS")
# -----------------------------------------------------------------------------
col_esq, col_dir = st.columns([1.2, 2])

with col_esq:
    st.subheader("📥 1. Adicionar Furo ao Projeto")
    st.info("Escolha a página do PDF, use a IA para ler e salve no projeto geral.")
    
    st.markdown("[👉 **Clique aqui para gerar sua API Key gratuita no Google AI Studio**](https://aistudio.google.com/app/apikey)")
    api_key = st.text_input("🔑 API Key do Gemini (Obrigatório):", type="password")
    arquivo_pdf = st.file_uploader("Importar Laudo (PDF)", type=["pdf"])
    
    if arquivo_pdf is not None:
        try:
            arquivo_pdf.seek(0)
            doc = fitz.open(stream=arquivo_pdf.read(), filetype="pdf")
            total_paginas = len(doc)
            
            c1, c2 = st.columns([1, 1])
            with c1:
                pagina_selecionada = st.number_input(f"Página (1 a {total_paginas}):", min_value=1, max_value=total_paginas, value=1)
            with c2:
                nome_furo_input = st.text_input("Nome do Furo:", value=st.session_state.furo_atual_nome)
                
            page_idx = pagina_selecionada - 1
            
            with st.expander(f"👁️ Pré-visualizar Página {pagina_selecionada}", expanded=False):
                pix_preview = doc.load_page(page_idx).get_pixmap(dpi=72)
                st.image(PILImage.open(io.BytesIO(pix_preview.tobytes("png"))), use_container_width=True)
            
            if st.button("🤖 Ler Tabela com IA", width="stretch"):
                if not api_key: st.warning("Insira a chave de API primeiro.")
                else:
                    with st.spinner("Lendo tabela..."):
                        try:
                            genai.configure(api_key=api_key)
                            modelo = genai.GenerativeModel('gemini-3.6-flash')
                            pix = doc.load_page(page_idx).get_pixmap(dpi=300)
                            img = PILImage.open(io.BytesIO(pix.tobytes("png")))
                            
                            prompt = f"""Extraia a tabela SPT.
                            Retorne apenas CSV separado por ponto e vírgula (;). Cabeçalho: Profundidade;N_SPT;Tipo de Solo
                            REGRAS: 1. Profundidade: apenas número. 2. N_SPT: golpes finais (se fração, só o numerador). 3. Tipo: {", ".join(OPCOES_SOLO)}"""
                            
                            resp = modelo.generate_content([prompt, img]).text.replace("```csv", "").replace("
