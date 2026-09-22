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
import pdfplumber # Leitor OFFLINE (Extração Relâmpago)
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
# ESTADO DA APLICAÇÃO (CARRINHO DE FUROS E CROQUI)
# -----------------------------------------------------------------------------
if 'projeto_furos' not in st.session_state:
    st.session_state.projeto_furos = {} 

if 'croqui_img' not in st.session_state:
    st.session_state.croqui_img = None

if 'furo_atual_df' not in st.session_state:
    st.session_state.furo_atual_df = pd.DataFrame({
        "Profundidade (m)": list(range(1, 16)),
        "N_SPT": [None] * 15,
        "Tipo de Solo": ["Argila"] * 15
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
registro_crea = st.sidebar.text_input("Registro CREA", value="")

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
st.sidebar.header("🎯 Critério de Carga Admissível")
criterio_q_adm = st.sidebar.selectbox(
    "Adotar como Resistência Final:",
    [
        "Média dos Métodos",
        "Menor Valor (Mais Conservador)",
        "Apenas Aoki-Velloso",
        "Apenas Décourt-Quaresma",
        "Apenas Teixeira"
    ]
)

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
bitola_estribo = st.sidebar.selectbox("Bitola do Estribo (mm)", [5.0, 6.3, 8.0, 10.0], index=1)
espacamento_estribo = st.sidebar.number_input("Espaçamento dos Estribos (cm)", min_value=5.0, max_value=30.0, value=15.0, step=2.5)

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

st.sidebar.markdown("---")
st.sidebar.header("📄 Relatório PDF")
incluir_pm = st.sidebar.checkbox("Incluir Diagrama de Interação P-M?", value=True)

# -----------------------------------------------------------------------------
# FUNÇÕES DE DESENHO (SEÇÃO E DIAGRAMA P-M)
# -----------------------------------------------------------------------------
def plot_secao_transversal(B_m, secao_tipo, n_barras, bitola_long_mm, bitola_estribo_mm):
    fig, ax = plt.subplots(figsize=(4, 4))
    cob = 0.05  
    
    if secao_tipo == "Circular":
        circle_ext = plt.Circle((0, 0), B_m/2, color='#E0E0E0', ec='black', lw=1.5, zorder=1)
        raio_estribo = B_m/2 - cob
        circle_int = plt.Circle((0, 0), raio_estribo, color='none', ec='red', lw=1.5, zorder=2)
        ax.add_patch(circle_ext)
        ax.add_patch(circle_int)
        
        angles = np.linspace(0, 2*np.pi, n_barras, endpoint=False)
        r_barras = raio_estribo - (bitola_estribo_mm/2000) - (bitola_long_mm/2000)
        for angle in angles:
            x = r_barras * np.cos(angle)
            y = r_barras * np.sin(angle)
            rebar = plt.Circle((x, y), bitola_long_mm/2000, color='black', zorder=3)
            ax.add_patch(rebar)
            
    else: 
        rect_ext = plt.Rectangle((-B_m/2, -B_m/2), B_m, B_m, color='#E0E0E0', ec='black', lw=1.5, zorder=1)
        L_estribo = B_m - 2*cob
        rect_int = plt.Rectangle((-L_estribo/2, -L_estribo/2), L_estribo, L_estribo, color='none', ec='red', lw=1.5, zorder=2)
        ax.add_patch(rect_ext)
        ax.add_patch(rect_int)
        
        L_barras = L_estribo - (bitola_estribo_mm/1000) - (bitola_long_mm/1000)
        perimetro = 4 * L_barras
        for i in range(n_barras):
            s = (i / n_barras) * perimetro
            if s <= L_barras: 
                x, y = -L_barras/2 + s, L_barras/2
            elif s <= 2*L_barras: 
                x, y = L_barras/2, L_barras/2 - (s - L_barras)
            elif s <= 3*L_barras: 
                x, y = L_barras/2 - (s - 2*L_barras), -L_barras/2
            else: 
                x, y = -L_barras/2, -L_barras/2 + (s - 3*L_barras)
            rebar = plt.Circle((x, y), bitola_long_mm/2000, color='black', zorder=3)
            ax.add_patch(rebar)

    ax.set_xlim(-B_m/2 - 0.05, B_m/2 + 0.05)
    ax.set_ylim(-B_m/2 - 0.05, B_m/2 + 0.05)
    ax.set_aspect('equal')
    ax.axis('off')
    ax.set_title(f"Armadura: {n_barras} Φ {bitola_long_mm:.1f} mm\nEstribo: Φ {bitola_estribo_mm:.1f} c/ {espacamento_estribo:.0f}cm", fontsize=10)
    return fig

def plot_diagrama_pm(M_rd, fck, fyk, Area_c, As, carga_V, momento_max):
    fcd = (fck / 1.4) * 1000 
    fyd = (fyk / 1.15) * 1000 
    
    N_max_comp = 0.85 * fcd * Area_c + fyd * As
    N_max_trac = -fyd * As
    N_bal = 0.35 * N_max_comp 
    M_bal = 1.35 * M_rd       
    
    N_vals = np.linspace(N_max_trac, N_max_comp, 100)
    M_vals = []
    
    for n in N_vals:
        if n < 0:
            m = M_rd * (1 - (n/N_max_trac)**2)
        elif n < N_bal:
            m = M_rd + (M_bal - M_rd) * ((n/N_bal)**0.65)
        else:
            m = M_bal * (1 - ((n - N_bal)/(N_max_comp - N_bal))**1.8)
        M_vals.append(max(0, m))
        
    fig, ax = plt.subplots(figsize=(4, 4))
    ax.plot(M_vals, N_vals, color='#1E3A8A', lw=2, label='Envoltória Resistente')
    ax.fill_betweenx(N_vals, M_vals, 0, color='#1E3A8A', alpha=0.1)
    
    ax.scatter([momento_max], [carga_V], color='red', zorder=5, s=60, edgecolors='black', label='Esforço Atuante ($S_d$)')
    
    ax.axhline(0, color='black', linewidth=1)
    ax.axvline(0, color='black', linewidth=1)
    ax.set_xlabel('Momento Fletor (kN.m)')
    ax.set_ylabel('Carga Axial (kN)')
    ax.set_title('Diagrama de Interação (P-M)')
    ax.legend(fontsize=8)
    ax.grid(True, ls='--', alpha=0.5)
    return fig

# -----------------------------------------------------------------------------
# FUNÇÃO NÚCLEO DE CÁLCULO
# -----------------------------------------------------------------------------
def processar_calculos_estaca(df_original, l_arm_manual=None, criterio="Média dos Métodos"):
    df_spt = df_original.copy()
    df_spt["Profundidade (m)"] = range(1, len(df_spt) + 1)
    df_spt["N_SPT"] = pd.to_numeric(df_spt["N_SPT"], errors="coerce").fillna(1)
    df_spt["Tipo de Solo"] = df_spt["Tipo de Solo"].fillna("Argila")
    df_spt["N_corr"] = df_spt["N_SPT"].apply(lambda x: min(x, 50))
    
    Area_c = (np.pi * B**2) / 4 if secao == "Circular" else B**2
    Inercia_c = (np.pi * B**4) / 64 if secao == "Circular" else (B**4) / 12
    Perimetro = np.pi * B if secao == "Circular" else 4 * B
    E_c = 5600 * np.sqrt(fck) * 1000 
    
    f1, f2 = FATORES_CONSTRUTIVOS[metodo_construtivo]["F1"], FATORES_CONSTRUTIVOS[metodo_construtivo]["F2"]

    def get_dq_c(s):
        s = str(s).lower()
        if "areia" in s: return 400
        if "silte" in s: return 200
        return 120
        
    def get_teix_alpha(s):
        s = str(s).lower()
        if "areia" in s: return 250
        if "silte" in s: return 200
        return 150
        
    if "Escavada" in metodo_construtivo:
        alfa_dq, beta_dq, beta_t = 0.5, 0.8, 5.0
    elif "Hélice" in metodo_construtivo or "Raiz" in metodo_construtivo:
        alfa_dq, beta_dq, beta_t = 0.3, 1.0, 6.0
    else:
        alfa_dq, beta_dq, beta_t = 1.0, 1.0, 8.0

    def proc_solo_aoki(row):
        solo = PARAMETROS_SOLO.get(row["Tipo de Solo"], PARAMETROS_SOLO["Argila"])
        n, prof = row["N_corr"], row["Profundidade (m)"]
        fator_agua = 0.5 if (prof >= nivel_agua and solo["comportamento"] == "granular") else 1.0
        es = solo["alpha_k"] * n * fator_agua
        k1 = 1200 * n * fator_agua
        kv = k1 * (0.3 / B) if solo["comportamento"] == "coesivo" else k1 * ((B + 0.3) / (2 * B)) ** 2
        kh = kv * nu
        rl = (solo["aoki_alpha"] * solo["aoki_K"] * n) / f2
        rp = (solo["aoki_K"] * n) / f1 * Area_c
        delta_rl = rl * Perimetro * 1.0 
        return pd.Series([es, kv, kh, rl, rp, delta_rl, solo["aoki_K"], solo["aoki_alpha"]])

    df_spt[["Es (kPa)", "kv (kN/m³)", "kh (kN/m³)", "rl (kPa)", "Rp (kN)", "delta_Rl (kN)", "K_aoki", "alpha_aoki"]] = df_spt.apply(proc_solo_aoki, axis=1)

    cota_fim = cota_assentamento + (comprimento_estaca if tipo_fundacao == "Profunda (Estaca)" else 1.5 * B)
    df_inf = df_spt[(df_spt["Profundidade (m)"] > cota_assentamento) & (df_spt["Profundidade (m)"] <= cota_fim)].copy()

    if not df_inf.empty:
        df_inf["Rl_Aoki_Acum"] = df_inf["delta_Rl (kN)"].cumsum()
        df_inf["Rc Adm Aoki (kN)"] = (df_inf["Rp (kN)"] + df_inf["Rl_Aoki_Acum"]) / 2.0
        
        df_inf["N_dq"] = df_inf["N_corr"].apply(lambda x: max(3, min(x, 50)))
        df_inf["C_dq"] = df_inf["Tipo de Solo"].apply(get_dq_c)
        df_inf["delta_Rl_dq"] = beta_dq * 10 * ((df_inf["N_dq"] / 3) + 1) * Perimetro * 1.0
        df_inf["Rl_DQ_Acum"] = df_inf["delta_Rl_dq"].cumsum()
        df_inf["Rp_dq"] = alfa_dq * df_inf["C_dq"] * df_inf["N_corr"] * Area_c
        df_inf["Rc Adm DQ (kN)"] = (df_inf["Rp_dq"] + df_inf["Rl_DQ_Acum"]) / 2.0
        
        df_inf["alpha_teix"] = df_inf["Tipo de Solo"].apply(get_teix_alpha)
        df_inf["delta_Rl_t"] = beta_t * df_inf["N_corr"] * Perimetro * 1.0
        df_inf["Rl_T_Acum"] = df_inf["delta_Rl_t"].cumsum()
        df_inf["Rp_t"] = df_inf["alpha_teix"] * df_inf["N_corr"] * Area_c
        df_inf["Rc Adm Teix (kN)"] = (df_inf["Rp_t"] + df_inf["Rl_T_Acum"]) / 2.0

        df_inf["Rc Adm Média (kN)"] = (df_inf["Rc Adm Aoki (kN)"] + df_inf["Rc Adm DQ (kN)"] + df_inf["Rc Adm Teix (kN)"]) / 3.0
        df_inf["Rc Adm Menor (kN)"] = df_inf[["Rc Adm Aoki (kN)", "Rc Adm DQ (kN)", "Rc Adm Teix (kN)"]].min(axis=1)

        if criterio == "Média dos Métodos":
            df_inf["Rc Adm Adotada (kN)"] = df_inf["Rc Adm Média (kN)"]
        elif criterio == "Menor Valor (Mais Conservador)":
            df_inf["Rc Adm Adotada (kN)"] = df_inf["Rc Adm Menor (kN)"]
        elif criterio == "Apenas Aoki-Velloso":
            df_inf["Rc Adm Adotada (kN)"] = df_inf["Rc Adm Aoki (kN)"]
        elif criterio == "Apenas Décourt-Quaresma":
            df_inf["Rc Adm Adotada (kN)"] = df_inf["Rc Adm DQ (kN)"]
        elif criterio == "Apenas Teixeira":
            df_inf["Rc Adm Adotada (kN)"] = df_inf["Rc Adm Teix (kN)"]

        Q_adm_aoki = df_inf.iloc[-1]["Rc Adm Aoki (kN)"]
        Q_adm_dq = df_inf.iloc[-1]["Rc Adm DQ (kN)"]
        Q_adm_t = df_inf.iloc[-1]["Rc Adm Teix (kN)"]
        Q_adm_media = df_inf.iloc[-1]["Rc Adm Média (kN)"]
        Q_adm_adotada = df_inf.iloc[-1]["Rc Adm Adotada (kN)"]
    else:
        df_inf = df_spt.head(1).copy()
        df_inf["Rc Adm Aoki (kN)"] = df_inf["Rc Adm DQ (kN)"] = df_inf["Rc Adm Teix (kN)"] = df_inf["Rc Adm Média (kN)"] = df_inf["Rc Adm Adotada (kN)"] = 0
        Q_adm_aoki = Q_adm_dq = Q_adm_t = Q_adm_media = Q_adm_adotada = 0

    kh_global = df_inf["kh (kN/m³)"].mean() if not df_inf.empty else 0
    kv_global = df_inf["kv (kN/m³)"].mean() if not df_inf.empty else 0

    K_linha = kh_global * B
    lamb = (K_linha / (4 * E_c * Inercia_c)) ** 0.25 if kh_global > 0 else 1.0
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

    L_armadura_calc = min(comprimento_estaca, max(max(3.0, 5 * B), z_momento_nulo + 0.40)) if tipo_fundacao == "Profunda (Estaca)" else 0.0
    if l_arm_manual is not None:
        L_armadura_calc = float(l_arm_manual)

    area_barra = (np.pi * (bitola / 1000)**2) / 4  
    n_barras = max(int(np.ceil((taxa_armadura / 100) * Area_c / area_barra)), 6)
    if secao == "Quadrada": n_barras = max(n_barras + (4 - n_barras % 4) if n_barras % 4 != 0 else n_barras, 8)

    M_rd = n_barras * area_barra * ((fyk / 1.15) * 1000) * (0.75 * B if secao == "Circular" else 0.80 * B)
    H_rd = M_rd / momento_max_unit if momento_max_unit > 0 else 0
    
    As_total = n_barras * area_barra
    V_concreto = Area_c * comprimento_estaca
    peso_long = As_total * L_armadura_calc * 7850
    peso_estribo = int(L_armadura_calc / (espacamento_estribo/100)) * (np.pi * (B - 0.10) if secao == "Circular" else 4 * (B - 0.10)) * ((np.pi * (bitola_estribo / 1000)**2) / 4) * 7850
    peso_aco_total = peso_long + peso_estribo

    return {
        "df_spt": df_spt, "df_inf": df_inf, 
        "Q_adm_aoki": Q_adm_aoki, "Q_adm_dq": Q_adm_dq, "Q_adm_t": Q_adm_t, "Q_adm_media": Q_adm_media,
        "Q_adm_adotada": Q_adm_adotada,
        "kv_global": kv_global, "kh_global": kh_global,
        "momento_max_atuante": momento_max_atuante, "M_rd": M_rd, "H_rd": H_rd, "deslocamento_max_mm": deslocamento_max_mm,
        "L_armadura": L_armadura_calc, "n_barras": n_barras, "V_concreto": V_concreto, "peso_aco_total": peso_aco_total,
        "z_vals": z_vals, "m_flet": m_flet, "y_disp": y_disp, "M_cr": M_cr,
        "Area_c": Area_c, "Perimetro": Perimetro, "E_c": E_c, "Inercia_c": Inercia_c,
        "f1": f1, "f2": f2, "alfa_dq": alfa_dq, "beta_dq": beta_dq, "beta_t": beta_t, "As_total": As_total
    }


# TÍTULO PRINCIPAL
st.title("🏗️ Projeto Integrado de Fundações")
st.caption("Múltiplos Furos, Múltiplos Métodos (Aoki, Décourt, Teixeira), Detalhamento de Armaduras e Diagrama P-M")

# -----------------------------------------------------------------------------
# COLUNA ESQUERDA: IMPORTAÇÃO, IA, OFFLINE E CROQUI
# -----------------------------------------------------------------------------
col_esq, col_dir = st.columns([1.2, 2])

with col_esq:
    st.subheader("📥 1. Dados do Furo de Sondagem")
    
    nome_furo_input = st.text_input("📌 Nome do Furo em Edição:", value=st.session_state.furo_atual_nome)
    
    st.info("Para contornar os limites gratuitos da IA, experimente o nosso Leitor Offline ou copie e cole os dados diretamente do Excel na tabela!")
    
    st.markdown("[👉 **Clique aqui para gerar sua API Key gratuita no Google AI Studio**](https://aistudio.google.com/app/apikey)")
    api_key = st.text_input("🔑 API Key do Gemini (Opcional se usar Offline ou Manual):", type="password")
    
    arquivo_pdf = st.file_uploader("📥 Importar Laudo de Sondagem (PDF)", type=["pdf"])
    
    doc = None
    if arquivo_pdf is not None:
        try:
            arquivo_pdf.seek(0)
            bytes_pdf = arquivo_pdf.read()
            doc = fitz.open(stream=bytes_pdf, filetype="pdf")
            total_paginas = len(doc)
            
            st.markdown("---")
            st.write("**Extração de Dados do PDF:**")
            
            pagina_selecionada = st.number_input(f"Página do Perfil (1 a {total_paginas}):", min_value=1, max_value=total_paginas, value=1, key="pag_perfil_input")
                
            page_idx = pagina_selecionada - 1
            
            with st.expander("👁️ Pré-visualizar Página Selecionada", expanded=True):
                st.markdown(f"**Página atual:** {pagina_selecionada}")
                pix_preview = doc.load_page(page_idx).get_pixmap(dpi=72)
                st.image(pix_preview.tobytes("png"), caption=f"Página do Perfil: {pagina_selecionada}", use_container_width=True)
            
            c_btn1, c_btn2, c_btn3, c_btn4 = st.columns(4)
            with c_btn1:
                btn_ia = st.button("🤖 Ler IA (Limitado)", use_container_width=True, help="Usa o Google Gemini (20 leituras/dia)")
            with c_btn2:
                btn_offline = st.button("⚡ Extração Relâmpago (Nativa)", use_container_width=True, help="Lê o texto nativo do PDF sem internet usando pdfplumber")
            with c_btn3:
                btn_manual = st.button("📸 Imagem (Manual)", use_container_width=True, help="Captura apenas o recorte da imagem")
            with c_btn4:
                btn_limpar = st.button("🧹 Zerar Tabela", use_container_width=True, help="Limpa a tabela para editar um furo novo")
                
            if btn_limpar:
                st.session_state.furo_atual_df = pd.DataFrame({
                    "Profundidade (m)": list(range(1, 16)),
                    "N_SPT": [None] * 15,
                    "Tipo de Solo": ["Argila"] * 15
                })
                st.rerun()
                
            if btn_offline:
                with st.spinner("A analisar o PDF localmente sem internet..."):
                    try:
                        arquivo_pdf.seek(0)
                        with pdfplumber.open(arquivo_pdf) as pdf:
                            page_plumber = pdf.pages[page_idx]
                            texto_pdf = page_plumber.extract_text()
                            
                            if not texto_pdf or len(texto_pdf.strip()) < 10:
                                st.error("⚠️ O PDF parece ser uma imagem escaneada. O leitor offline precisa de um PDF digital (com texto selecionável). Use o botão 'Imagem (Manual)' e cole do Excel.")
                            else:
                                linhas = texto_pdf.split('\n')
                                prof_esperada = 1
                                dados_offline = []
                                
                                for linha in linhas:
                                    match = re.search(rf"^\s*0*{prof_esperada}(?:[,.]0+)?\s+([\d\s/]+)", linha)
                                    if not match:
                                        match = re.search(rf"\s+0*{prof_esperada}(?:[,.]0+)?\s+([\d\s/]+)", linha)
                                        
                                    if match:
                                        numeros_str = match.group(1)
                                        nums = re.findall(r'\b\d+\b', numeros_str)
                                        if nums:
                                            n_spt = int(nums[-1]) 
                                            if n_spt > 60: n_spt = 60 
                                            dados_offline.append([prof_esperada, n_spt, "Argila"])
                                            prof_esperada += 1
                                            
                                if len(dados_offline) > 0:
                                    df_off = pd.DataFrame(dados_offline, columns=["Profundidade (m)", "N_SPT", "Tipo de Solo"])
                                    while len(df_off) < 15:
                                        df_off.loc[len(df_off)] = [len(df_off)+1, None, "Argila"]
                                        
                                    st.session_state.furo_atual_df = df_off
                                    pix = doc.load_page(page_idx).get_pixmap(dpi=300)
                                    st.session_state.furo_atual_img = pix.tobytes("png")
                                    st.session_state.furo_atual_nome = nome_furo_input
                                    st.success(f"Extração relâmpago concluída! Foram lidos {len(dados_offline)} metros.")
                                    st.rerun()
                                else:
                                    st.warning("O formato visual desta tabela é complexo para o leitor offline básico. Use o modo 'Imagem (Manual)' e cole os números diretamente do seu Excel!")
                    except Exception as e:
                        st.error(f"Erro na extração offline: {e}")
            
            if btn_ia:
                if not api_key: st.warning("Insira a chave de API primeiro.")
                else:
                    with st.spinner("Lendo tabela na nuvem..."):
                        try:
                            genai.configure(api_key=api_key)
                            modelo = genai.GenerativeModel('gemini-3.6-flash')
                            pix = doc.load_page(page_idx).get_pixmap(dpi=300)
                            img = PILImage.open(io.BytesIO(pix.tobytes("png")))
                            
                            prompt = f"""Extraia a tabela SPT.
                            Retorne apenas CSV separado por ponto e vírgula (;). Cabeçalho: Profundidade;N_SPT;Tipo de Solo
                            REGRAS: 1. Profundidade: apenas número. 2. N_SPT: golpes finais (se fração, só o numerador). 3. Tipo: {", ".join(OPCOES_SOLO)}"""
                            
                            resposta = modelo.generate_content([prompt, img])
                            texto_limpo = resposta.text.replace("```csv", "").replace("
