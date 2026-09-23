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
import pdfplumber # Leitor OFFLINE
import base64 
from PIL import Image as PILImage
import google.generativeai as genai

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

def exportar_projeto_json():
    dados = {
        "furos": {},
        "croqui": None
    }
    for nome, info in st.session_state.projeto_furos.items():
        img_b64 = base64.b64encode(info["img"]).decode('utf-8') if info["img"] else None
        dados["furos"][nome] = {
            "df": info["df"].to_dict(orient="records"),
            "img": img_b64
        }
    if st.session_state.croqui_img:
        dados["croqui"] = base64.b64encode(st.session_state.croqui_img).decode('utf-8')
        
    return json.dumps(dados)

def carregar_projeto_json(json_str):
    try:
        dados = json.loads(json_str)
        st.session_state.projeto_furos = {}
        for nome, info in dados.get("furos", {}).items():
            df = pd.DataFrame(info["df"])
            img_bytes = base64.b64decode(info["img"]) if info.get("img") else None
            st.session_state.projeto_furos[nome] = {"df": df, "img": img_bytes}
            
        if dados.get("croqui"):
            st.session_state.croqui_img = base64.b64decode(dados["croqui"])
        else:
            st.session_state.croqui_img = None
        return True
    except Exception as e:
        return False

# -----------------------------------------------------------------------------
# SIDEBAR
# -----------------------------------------------------------------------------
logo_path = "fundo_transparente_2.png"
if os.path.exists(logo_path):
    st.sidebar.image(logo_path, use_container_width=True)

st.sidebar.header("📝 Identificação do Projeto")
nome_obra = st.sidebar.text_input("Nome da Obra", value="")
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

st.sidebar.markdown("---")
st.sidebar.header("💾 Gestão do Arquivo do Projeto")
st.sidebar.info("Guarde o seu trabalho para continuar mais tarde.")

json_projeto = exportar_projeto_json()
nome_arquivo_utea = re.sub(r'[^A-Za-z0-9_-]', '', nome_obra)[:20] if nome_obra else "Projeto"
st.sidebar.download_button(
    label="⬇️ Guardar Projeto (.utea)",
    data=json_projeto,
    file_name=f"{nome_arquivo_utea}.utea",
    mime="application/json",
    use_container_width=True
)

upload_proj = st.sidebar.file_uploader("⬆️ Abrir Projeto Guardado (.utea)", type=["utea", "json"])
if upload_proj is not None:
    if st.sidebar.button("Carregar Dados do Arquivo", use_container_width=True):
        json_lido = upload_proj.read().decode('utf-8')
        sucesso = carregar_projeto_json(json_lido)
        if sucesso:
            st.sidebar.success("Projeto carregado com sucesso!")
            st.rerun()
        else:
            st.sidebar.error("Erro ao carregar o arquivo. Formato inválido.")

# -----------------------------------------------------------------------------
# FUNÇÕES DE DESENHO
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

def plot_perfil_longitudinal(B_m, comp_estaca, L_armadura, espacamento_estribo_cm):
    fig, ax = plt.subplots(figsize=(1.5, 4))
    cob = 0.05
    raio_arm = B_m/2 - cob

    ax.plot([-B_m/2, -B_m/2], [0, -comp_estaca], color='black', lw=1.5)
    ax.plot([B_m/2, B_m/2], [0, -comp_estaca], color='black', lw=1.5)
    ax.plot([-B_m/2, B_m/2], [-comp_estaca, -comp_estaca], color='black', lw=1.5)
    ax.plot([-B_m/2, B_m/2], [0, 0], color='black', lw=1.5)
    ax.fill_betweenx([0, -comp_estaca], -B_m/2, B_m/2, color='#E0E0E0', alpha=0.5)

    ax.plot([-raio_arm, -raio_arm], [0, -L_armadura], color='red', lw=2)
    ax.plot([raio_arm, raio_arm], [0, -L_armadura], color='red', lw=2)
    ax.plot([-raio_arm, raio_arm], [-L_armadura, -L_armadura], color='red', lw=2)

    esp_m = espacamento_estribo_cm / 100
    z_estribos = np.arange(0, -L_armadura, -esp_m)
    for z in z_estribos:
        ax.plot([-raio_arm, raio_arm], [z, z], color='red', lw=0.5)

    ax.set_xlim(-B_m*1.5, B_m*1.5)
    ax.set_ylim(-comp_estaca - 0.5, 0.5)
    ax.set_xticks([])
    ax.set_ylabel("Profundidade (m)", fontsize=8)
    ax.set_title("Perfil", fontsize=10)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_visible(False)
    
    fig.tight_layout()
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

    # NOVO: Fator de aproximação estrutural para seções com armadura distribuída no perímetro
    fator_z_eq = 0.35 if secao == "Circular" else 0.40
    As_total = n_barras * area_barra
    M_rd = As_total * ((fyk / 1.15) * 1000) * (fator_z_eq * B)
    H_rd = M_rd / momento_max_unit if momento_max_unit > 0 else 0
    
    V_concreto = Area_c * comprimento_estaca
    qtd_estribos = int(L_armadura_calc / (espacamento_estribo / 100))
    peso_long = As_total * L_armadura_calc * 7850
    peso_estribo = qtd_estribos * (np.pi * (B - 0.10) if secao == "Circular" else 4 * (B - 0.10)) * ((np.pi * (bitola_estribo / 1000)**2) / 4) * 7850
    peso_aco_total = peso_long + peso_estribo

    return {
        "df_spt": df_spt, "df_inf": df_inf, 
        "Q_adm_aoki": Q_adm_aoki, "Q_adm_dq": Q_adm_dq, "Q_adm_t": Q_adm_t, "Q_adm_media": Q_adm_media,
        "Q_adm_adotada": Q_adm_adotada,
        "kv_global": kv_global, "kh_global": kh_global,
        "momento_max_atuante": momento_max_atuante, "momento_max_unit": momento_max_unit,
        "M_rd": M_rd, "H_rd": H_rd, "deslocamento_max_mm": deslocamento_max_mm,
        "L_armadura": L_armadura_calc, "n_barras": n_barras, "V_concreto": V_concreto, "peso_aco_total": peso_aco_total,
        "qtd_estribos": qtd_estribos,
        "z_vals": z_vals, "m_flet": m_flet, "y_disp": y_disp, "M_cr": M_cr,
        "Area_c": Area_c, "Perimetro": Perimetro, "E_c": E_c, "Inercia_c": Inercia_c,
        "f1": f1, "f2": f2, "alfa_dq": alfa_dq, "beta_dq": beta_dq, "beta_t": beta_t, "As_total": As_total,
        "fator_z_eq": fator_z_eq
    }


# TÍTULO PRINCIPAL
st.title("🏗️ Projeto Integrado de Fundações")
st.caption("Múltiplos Furos, Múltiplos Métodos (Aoki, Décourt, Teixeira), Detalhamento de Armaduras e Diagrama P-M")

# -----------------------------------------------------------------------------
# COLUNA ESQUERDA
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
                with st.spinner("Analisando o PDF localmente sem internet..."):
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
                            
                            texto_limpo = resposta.text
                            texto_limpo = texto_limpo.replace("```csv", "")
                            texto_limpo = texto_limpo.replace("```", "")
                            texto_limpo = texto_limpo.strip()
                            
                            df_ia = pd.read_csv(io.StringIO(texto_limpo), sep=";")
                            df_ia.columns = ["Profundidade (m)", "N_SPT", "Tipo de Solo"]
                            
                            df_ia['Profundidade (m)'] = pd.to_numeric(df_ia['Profundidade (m)'].astype(str).str.replace(',', '.').str.extract(r'(\d+)')[0], errors='coerce')
                            df_ia['N_SPT'] = pd.to_numeric(df_ia['N_SPT'].astype(str).str.extract(r'(\d+)')[0], errors='coerce')
                            df_ia = df_ia.dropna(subset=['Profundidade (m)', 'N_SPT']).astype({'Profundidade (m)': 'int', 'N_SPT': 'int'})
                            
                            if len(df_ia) > 0:
                                st.session_state.furo_atual_df = df_ia
                                st.session_state.furo_atual_img = pix.tobytes("png")
                                st.session_state.furo_atual_nome = nome_furo_input
                                st.success("Tabela extraída via IA com sucesso!")
                                st.rerun()
                            else:
                                st.error("A IA não reconheceu a tabela na imagem.")
                        except Exception as e:
                            st.error(f"Erro IA: {e}")
            
            if btn_manual:
                try:
                    pix = doc.load_page(page_idx).get_pixmap(dpi=300)
                    st.session_state.furo_atual_img = pix.tobytes("png")
                    st.session_state.furo_atual_nome = nome_furo_input
                    st.success("Imagem anexada ao furo atual! Preencha a tabela abaixo à mão ou cole do Excel (Ctrl+V).")
                except Exception as e:
                    st.error(f"Erro ao capturar a imagem: {e}")
                            
        except Exception as e: 
            st.error(f"Erro PDF: {e}")
            doc = None

    st.markdown("---")
    st.write(f"**Tabela de Preenchimento: {nome_furo_input}** (Aceita Colar do Excel)")
    df_editado = st.data_editor(
        st.session_state.furo_atual_df,
        column_config={"Tipo de Solo": st.column_config.SelectboxColumn("Tipo de Solo", options=OPCOES_SOLO)},
        num_rows="dynamic", width="stretch"
    )
    
    if st.button(f"💾 Guardar {nome_furo_input} no Projeto", type="primary", width="stretch"):
        st.session_state.projeto_furos[nome_furo_input] = {
            "df": df_editado.copy(),
            "img": st.session_state.furo_atual_img
        }
        st.session_state.furo_atual_nome = nome_furo_input
        st.success(f"Furo {nome_furo_input} guardado e adicionado ao projeto!")
    
    st.markdown("---")
    st.subheader("🗺️ 2. Adicionar Croqui de Locação")
    st.info("Pode extrair a página do PDF carregado ou fazer o upload de uma imagem solta.")
    
    modo_croqui = st.radio("Origem do Croqui:", ["Extrair do PDF", "Fazer Upload de Imagem (.png/.jpg)"], horizontal=True)
    
    if modo_croqui == "Extrair do PDF":
        if arquivo_pdf is not None and doc is not None:
            col_pag_c, col_btn_c = st.columns([1, 1])
            with col_pag_c:
                pag_croqui = st.number_input(f"Página do Croqui (1 a {total_paginas}):", min_value=1, max_value=total_paginas, value=1, key="num_croqui")
            
            with st.expander("👁️ Pré-visualizar Croqui", expanded=True):
                st.markdown(f"**Página atual:** {pag_croqui}")
                pix_croqui = doc.load_page(pag_croqui - 1).get_pixmap(dpi=72)
                st.image(pix_croqui.tobytes("png"), caption=f"Página do Croqui: {pag_croqui}", use_container_width=True)
            
            if st.button("💾 Guardar Página como Croqui", width="stretch"):
                pix_high = doc.load_page(pag_croqui - 1).get_pixmap(dpi=300)
                st.session_state.croqui_img = pix_high.tobytes("png")
                st.success("Croqui guardado com sucesso a partir do PDF!")
        else:
            st.warning("Importe um PDF acima primeiro para poder extrair a página.")
            
    else:
        img_upload = st.file_uploader("Selecione o ficheiro do Croqui", type=["png", "jpg", "jpeg"])
        if img_upload is not None:
            st.image(img_upload, use_container_width=True)
            if st.button("💾 Guardar Upload como Croqui", width="stretch"):
                st.session_state.croqui_img = img_upload.getvalue()
                st.success("Croqui guardado com sucesso a partir do upload!")

    st.markdown("---")
    if len(st.session_state.projeto_furos) > 0:
        if st.button("🗑️ Limpar Todos os Furos Salvos", width="stretch"):
            st.session_state.projeto_furos = {}
            st.rerun()

# -----------------------------------------------------------------------------
# COLUNA DIREITA
# -----------------------------------------------------------------------------
with col_dir:
    tab_resumo, tab_atual = st.tabs(["📊 Visão Geral do Terreno", "🔍 Análise Detalhada dos Furos"])

    with tab_resumo:
        st.subheader("Resumo dos Furos Salvos no Projeto")
        if len(st.session_state.projeto_furos) == 0:
            st.warning("Nenhum furo salvo ainda. Preencha a tabela ao lado e clique em Guardar.")
            dados_resumo = []
            recomendacao = ""
        else:
            dados_resumo = []
            todos_spt_rasos = []
            
            for nome_furo, dados in st.session_state.projeto_furos.items():
                calc = processar_calculos_estaca(dados["df"], L_armadura_manual, criterio_q_adm)
                df_furo = calc["df_spt"]
                prof_max = df_furo["Profundidade (m)"].max()
                
                spt_rasos = df_furo[df_furo["Profundidade (m)"] <= 3]["N_SPT"].mean()
                if not pd.isna(spt_rasos): todos_spt_rasos.append(spt_rasos)
                
                status_geo = "✅ OK" if carga_V <= calc["Q_adm_adotada"] else "❌ FALHA"
                
                dados_resumo.append({
                    "Furo": nome_furo,
                    "Prof. (m)": prof_max,
                    "Aoki (kN)": f"{calc['Q_adm_aoki']:.0f}",
                    "Décourt-Q. (kN)": f"{calc['Q_adm_dq']:.0f}",
                    "Teixeira (kN)": f"{calc['Q_adm_t']:.0f}",
                    "Adotada (kN)": f"{calc['Q_adm_adotada']:.0f}",
                    "Status": status_geo
                })
            
            st.table(pd.DataFrame(dados_resumo))
            
            st.markdown("### 🤖 Diagnóstico e Recomendação de Fundação")
            recomendacao = ""
            media_spt_raso = np.mean(todos_spt_rasos) if todos_spt_rasos else 0
            
            if media_spt_raso < 5:
                recomendacao += "**Terreno superficial mole/fofo:** A média de N_SPT nos primeiros 3 metros é muito baixa. **Recomendada Fundação Profunda (Estacas)**.\n\n"
            elif media_spt_raso > 15:
                recomendacao += "**Terreno superficial muito resistente:** Solo competente encontrado próximo à superfície. Viabilidade técnica para **Fundação Rasa (Sapatas/Radier)**.\n\n"
            else:
                recomendacao += "**Terreno superficial intermediário:** Fazer verificação de viabilidade económica entre Sapatas (com melhoria de solo) e Estacas curtas.\n\n"
                
            if tem_na and nivel_agua < 5.0:
                recomendacao += f"**⚠️ Atenção ao Nível d'Água:** O lençol freático foi detado raso (Profundidade {nivel_agua}m). Se optar por estacas, **evite estaca escavada mecanizada sem camisa metálica**. Sugeridas estacas tipo Hélice Contínua ou Raiz."
            
            st.info(recomendacao)
            
            if st.session_state.croqui_img is not None:
                st.markdown("---")
                st.markdown("### 🗺️ Croqui de Locação dos Furos")
                st.image(st.session_state.croqui_img, use_container_width=True)
                if st.button("🗑️ Remover Croqui"):
                    st.session_state.croqui_img = None
                    st.rerun()
            
    with tab_atual:
        furos_disponiveis = {f"{nome_furo_input} (Em Edição na Tabela)": df_editado}
        for k, v in st.session_state.projeto_furos.items():
            furos_disponiveis[f"{k} (Salvo no Projeto)"] = v["df"]
            
        furo_selecionado_visualizacao = st.selectbox("🔍 Escolha qual furo visualizar nos gráficos:", list(furos_disponiveis.keys()))
        res_atual = processar_calculos_estaca(furos_disponiveis[furo_selecionado_visualizacao], L_armadura_manual, criterio_q_adm)
        
        st.markdown(f"### 📊 Capacidade de Carga Geotécnica")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(f"⚖️ ADOTADA", f"{res_atual['Q_adm_adotada']:,.1f} kN", delta=f"{criterio_q_adm}", delta_color="off")
        c2.metric("Aoki-Velloso", f"{res_atual['Q_adm_aoki']:,.1f} kN")
        c3.metric("Décourt-Quaresma", f"{res_atual['Q_adm_dq']:,.1f} kN")
        c4.metric("Teixeira", f"{res_atual['Q_adm_t']:,.1f} kN")
        
        st.markdown("### 🏗️ Estrutural e Interação Solo-Estrutura")
        e1, e2, e3, e4 = st.columns(4)
        e1.metric("M_Rd (Momento Resist.)", f"{res_atual['M_rd']:.1f} kN.m")
        e2.metric("H_Rd (Horiz. Máx)", f"{res_atual['H_rd']:.1f} kN")
        e3.metric("Coef. de Mola (K_h)", f"{res_atual['kh_global']:,.0f} kN/m³")
        e4.metric("Desloc. Topo", f"{res_atual['deslocamento_max_mm']:.2f} mm")
        
        st.markdown("### ⚙️ Detalhamento Estrutural e Armaduras")
        
        c_det1, c_det2, c_det3, c_det4 = st.columns(4)
        c_det1.metric("Vol. Concreto (Estaca)", f"{res_atual['V_concreto']:.2f} m³")
        c_det2.metric("Peso Aço Total", f"{res_atual['peso_aco_total']:.1f} kg")
        c_det3.metric("Armadura Long.", f"{res_atual['n_barras']} un - {res_atual['L_armadura']:.2f} m")
        c_det4.metric("Qtd. Estribos", f"{res_atual['qtd_estribos']} un")
        
        col_sec, col_long, col_pm = st.columns([1, 0.8, 1.5])
        with col_sec:
            fig_sec = plot_secao_transversal(B, secao, res_atual['n_barras'], bitola, bitola_estribo)
            st.pyplot(fig_sec)
        with col_long:
            fig_long = plot_perfil_longitudinal(B, comprimento_estaca, res_atual['L_armadura'], espacamento_estribo)
            st.pyplot(fig_long)
        with col_pm:
            fig_pm = plot_diagrama_pm(res_atual['M_rd'], fck, fyk, res_atual['Area_c'], res_atual['As_total'], carga_V, res_atual['momento_max_atuante'])
            st.pyplot(fig_pm)
        
        st.markdown("### 📈 Perfis Geotécnicos")
        fig_g, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(11, 4))
        
        ax1.plot(res_atual["df_inf"]["Rc Adm Aoki (kN)"], res_atual["df_inf"]["Profundidade (m)"], label="Aoki", color="green", alpha=0.3)
        ax1.plot(res_atual["df_inf"]["Rc Adm DQ (kN)"], res_atual["df_inf"]["Profundidade (m)"], label="Décourt", color="blue", alpha=0.3)
        ax1.plot(res_atual["df_inf"]["Rc Adm Teix (kN)"], res_atual["df_inf"]["Profundidade (m)"], label="Teixeira", color="orange", alpha=0.3)
        ax1.plot(res_atual["df_inf"]["Rc Adm Adotada (kN)"], res_atual["df_inf"]["Profundidade (m)"], label="Adotada", color="black", linewidth=2.5, linestyle=':')
        ax1.axvline(x=carga_V, color='red', linestyle='--')
        ax1.set_title("Resistência (kN)")
        ax1.invert_yaxis()
        ax1.grid(True, ls="--", alpha=0.5)
        ax1.legend(fontsize=8)
        
        ax2.plot(res_atual["m_flet"], res_atual["z_vals"], color="red")
        ax2.axvline(x=res_atual["M_rd"], color='darkred', linestyle='--')
        ax2.set_title("Momento Fletor")
        ax2.invert_yaxis()
        ax2.grid(True, ls="--", alpha=0.5)
        
        ax3.plot(res_atual["y_disp"]*1000, res_atual["z_vals"], color="blue")
        ax3.set_title("Elástica (mm)")
        ax3.invert_yaxis()
        ax3.grid(True, ls="--", alpha=0.5)
        
        st.pyplot(fig_g)
        plt.close(fig_g)

# -----------------------------------------------------------------------------
# GERAÇÃO DO MEGA RELATÓRIO PDF
# -----------------------------------------------------------------------------
def gerar_pdf_multiprojeto():
    if len(st.session_state.projeto_furos) == 0: return None
        
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story, styles = [], getSampleStyleSheet()

    title_style = ParagraphStyle('PDFTitle', parent=styles['Heading1'], fontSize=16, leading=20, textColor=colors.HexColor('#1E3A8A'), alignment=1, spaceAfter=10)
    h2_style = ParagraphStyle('PDFH2', parent=styles['Heading2'], fontSize=12, leading=16, textColor=colors.HexColor('#1E3A8A'), spaceBefore=10, spaceAfter=5)
    body_style = ParagraphStyle('PDFBody', parent=styles['Normal'], fontSize=9, leading=12)

    if os.path.exists(logo_path):
        im = ReportLabImage(logo_path, width=150, height=60)
        im.hAlign = 'LEFT'
        
        crea_texto = f" - <b>CREA:</b> {registro_crea}" if registro_crea.strip() != "" else ""
        t_cab = Table([[im, Paragraph(f"<b>OBRA:</b> {nome_obra}<br/><b>RESP. TÉCNICO:</b> {resp_tecnico}{crea_texto}<br/><b>DATA:</b> {datetime.datetime.now().strftime('%d/%m/%Y')}", ParagraphStyle('CabInfo', parent=body_style, alignment=2))]], colWidths=[160, 340])
        
        t_cab.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
        story.append(t_cab)
        story.append(Spacer(1, 20))
        
    story.append(Paragraph("<b>MEMORIAL DE CÁLCULO DE FUNDAÇÕES</b>", title_style))
    story.append(Paragraph("<b>Projeto Geotécnico Consolidado - Múltiplos Furos</b>", ParagraphStyle('Sub', parent=body_style, alignment=1)))
    story.append(Spacer(1, 15))

    story.append(Paragraph("<b>1. Resumo do Terreno e Diagnóstico</b>", h2_style))
    story.append(Paragraph(f"<b>Critério de Segurança Adotado:</b> {criterio_q_adm}<br/>", body_style))
    story.append(Paragraph(recomendacao.replace('\n', '<br/>'), body_style))
    story.append(Spacer(1, 10))
    
    dados_tab_resumo = [["Furo", "Prof.", "Aoki", "Décourt", "Teixeira", "Adotada"]]
    for f in dados_resumo:
        dados_tab_resumo.append([f["Furo"], f"{f['Prof. (m)']}m", f"{f['Aoki (kN)']} kN", f"{f['Décourt-Q. (kN)']} kN", f"{f['Teixeira (kN)']} kN", f"{f['Adotada (kN)']} kN"])
        
    t_res_geral = Table(dados_tab_resumo, colWidths=[80, 50, 85, 85, 85, 95])
    t_res_geral.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1E3A8A')), ('TEXTCOLOR', (0,0), (-1,0), colors.white), ('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('ALIGN', (0,0), (-1,-1), 'CENTER')]))
    story.append(t_res_geral)
    story.append(PageBreak())

    if st.session_state.croqui_img is not None:
        story.append(Paragraph("<b>2. Croqui de Locação dos Furos</b>", h2_style))
        story.append(Spacer(1, 10))
        img_croqui_buffer = io.BytesIO(st.session_state.croqui_img)
        story.append(ReportLabImage(img_croqui_buffer, width=500, height=650, kind='proportional'))
        story.append(PageBreak())
        num_seccao = 3
    else:
        num_seccao = 2

    for nome_furo, dados in st.session_state.projeto_furos.items():
        res = processar_calculos_estaca(dados["df"], L_armadura_manual, criterio_q_adm)
        
        story.append(Paragraph(f"<b>{num_seccao}. ANÁLISE INDIVIDUAL: FURO {nome_furo}</b>", title_style))
        story.append(Spacer(1, 10))
        
        story.append(Paragraph("<b>Resumo da Capacidade de Carga (Três Métodos)</b>", h2_style))
        txt_cap = f"<b>Aoki-Velloso:</b> {res['Q_adm_aoki']:.1f} kN | <b>Décourt-Quaresma:</b> {res['Q_adm_dq']:.1f} kN | <b>Teixeira:</b> {res['Q_adm_t']:.1f} kN<br/>"
        txt_cap += f"<b>Carga Admissível Adotada ({criterio_q_adm}):</b> <font color='green'><b>{res['Q_adm_adotada']:.1f} kN</b></font>"
        story.append(Paragraph(txt_cap, body_style))
        story.append(Spacer(1, 5))
        
        story.append(Paragraph("<b>Memória de Cálculo Detalhada e Estrutural</b>", h2_style))
        
        txt_geo = f"<b>Geometria:</b> Comprimento da Estaca = {comprimento_estaca:.2f} m | Área da Seção (A_c) = {res['Area_c']:.4f} m² | Perímetro (U) = {res['Perimetro']:.3f} m<br/>"
        txt_geo += f"<b>Concreto:</b> Inércia (I_c) = {res['Inercia_c']:.6f} m<sup>4</sup> | Módulo Elasticidade (E_c) = {(res['E_c']/1000):.0f} MPa<br/>"
        txt_geo += f"<b>Solo-Estrutura:</b> K_h Global = {res['kh_global']:,.0f} kN/m³ | K_v Global = {res['kv_global']:,.0f} kN/m³<br/>"
        txt_geo += f"<b>Armadura Long.:</b> {res['n_barras']} Φ {bitola:.1f} mm (Comp. Gaiola: {res['L_armadura']:.2f} m) | <b>Armadura Transv.:</b> {res['qtd_estribos']} Estribos Φ {bitola_estribo:.1f} mm c/ {espacamento_estribo:.0f} cm<br/>"
        txt_geo += f"<b>Quantitativos da Estaca:</b> Volume de Concreto = {res['V_concreto']:.2f} m³ | Peso Total de Aço = {res['peso_aco_total']:.1f} kg<br/>"
        story.append(Paragraph(txt_geo, body_style))
        story.append(Spacer(1, 10))

        fig_sec = plot_secao_transversal(B, secao, res['n_barras'], bitola, bitola_estribo)
        buf_sec = io.BytesIO()
        fig_sec.savefig(buf_sec, format='png', dpi=150, bbox_inches='tight')
        buf_sec.seek(0)
        plt.close(fig_sec)
        
        fig_long = plot_perfil_longitudinal(B, comprimento_estaca, res['L_armadura'], espacamento_estribo)
        buf_long = io.BytesIO()
        fig_long.savefig(buf_long, format='png', dpi=150, bbox_inches='tight')
        buf_long.seek(0)
        plt.close(fig_long)

        if incluir_pm:
            fig_pm = plot_diagrama_pm(res['M_rd'], fck, fyk, res['Area_c'], res['As_total'], carga_V, res['momento_max_atuante'])
            buf_pm = io.BytesIO()
            fig_pm.savefig(buf_pm, format='png', dpi=150, bbox_inches='tight')
            buf_pm.seek(0)
            plt.close(fig_pm)
            
            t_img = Table([[ReportLabImage(buf_sec, width=150, height=150), ReportLabImage(buf_long, width=75, height=150), ReportLabImage(buf_pm, width=150, height=150)]])
            t_img.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER'), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
            story.append(t_img)
        else:
            t_img = Table([[ReportLabImage(buf_sec, width=200, height=200), ReportLabImage(buf_long, width=100, height=200)]])
            t_img.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER'), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
            story.append(t_img)
        
        story.append(Spacer(1, 15))

        story.append(Paragraph("<b>Equações Analíticas Utilizadas</b>", h2_style))
        eq_style = ParagraphStyle('EQ', parent=body_style, leftIndent=15, spaceBefore=2, spaceAfter=2, fontSize=8)
        legenda_style = ParagraphStyle('LEG', parent=body_style, leftIndent=0, spaceBefore=4, spaceAfter=10, fontSize=7, textColor=colors.grey)

        if criterio_q_adm in ["Apenas Aoki-Velloso", "Média dos Métodos", "Menor Valor (Mais Conservador)"]:
            story.append(Paragraph("<b>Método de Aoki-Velloso (1975):</b>", body_style))
            story.append(Paragraph("• Resistência de Ponta: R<sub>p</sub> = (K x N<sub>SPT</sub> / F<sub>1</sub>) x A<sub>c</sub>", eq_style))
            story.append(Paragraph("• Atrito Lateral: R<sub>l</sub> = Σ [ (α x K x N<sub>SPT</sub> / F<sub>2</sub>) x U x Δz ]", eq_style))
            story.append(Paragraph(f"• Fatores Adotados para Estaca {metodo_construtivo}: F<sub>1</sub> = {res['f1']} | F<sub>2</sub> = {res['f2']}", eq_style))
            story.append(Spacer(1, 4))

        if criterio_q_adm in ["Apenas Décourt-Quaresma", "Média dos Métodos", "Menor Valor (Mais Conservador)"]:
            story.append(Paragraph("<b>Método de Décourt-Quaresma (1996):</b>", body_style))
            story.append(Paragraph("• Resistência de Ponta: R<sub>p</sub> = α x C x N<sub>SPT</sub> x A<sub>c</sub>", eq_style))
            story.append(Paragraph("• Atrito Lateral: R<sub>l</sub> = Σ [ β x 10 x ((N<sub>eq</sub> / 3) + 1) x U x Δz ]", eq_style))
            story.append(Paragraph(f"• Fatores Adotados para Estaca {metodo_construtivo}: α = {res['alfa_dq']} | β = {res['beta_dq']}", eq_style))
            story.append(Spacer(1, 4))

        if criterio_q_adm in ["Apenas Teixeira", "Média dos Métodos", "Menor Valor (Mais Conservador)"]:
            story.append(Paragraph("<b>Método de Teixeira (1996):</b>", body_style))
            story.append(Paragraph("• Resistência de Ponta: R<sub>p</sub> = α<sub>T</sub> x N<sub>SPT</sub> x A<sub>c</sub>", eq_style))
            story.append(Paragraph("• Atrito Lateral: R<sub>l</sub> = Σ [ β<sub>T</sub> x N<sub>SPT</sub> x U x Δz ]", eq_style))
            story.append(Paragraph(f"• Fatores Adotados para Estaca {metodo_construtivo}: β<sub>T</sub> = {res['beta_t']}", eq_style))
            story.append(Spacer(1, 4))

        story.append(Paragraph("<b>Modelo Estrutural e Interação Solo-Estrutura (Winkler):</b>", body_style))
        story.append(Paragraph("• Fator de Rigidez Relativa: λ = [ (K<sub>h</sub> x B) / (4 x E<sub>c</sub> x I<sub>c</sub>) ]<sup>0.25</sup>", eq_style))
        story.append(Paragraph("• Deslocamento Lateral: y(z) = [e<sup>-λz</sup> / (2 E<sub>c</sub> I<sub>c</sub> λ³)] x [H cos(λz) + λ M (cos(λz) + sin(λz))]", eq_style))
        story.append(Spacer(1, 4))
        
        story.append(Paragraph("<b>Capacidade Estrutural da Seção (Armadura):</b>", body_style))
        z_str = "0.35 B" if secao == "Circular" else "0.40 B"
        z_val = res['fator_z_eq'] * B
        story.append(Paragraph(f"• Momento Resistente: M<sub>Rd</sub> = A<sub>s,tot</sub> x f<sub>yd</sub> x z<sub>eq</sub>   |   (Braço de alavanca efetivo z<sub>eq</sub> ≈ {z_str})", eq_style))
        story.append(Paragraph(f"  <i>M<sub>Rd</sub> = {res['As_total']:.6f} m² x ({fyk}/1.15) x 10³ kPa x {z_val:.3f} m = <b>{res['M_rd']:.1f} kN.m</b></i>", eq_style))
        story.append(Paragraph(f"• Força Horizontal Máx: H<sub>Rd</sub> = M<sub>Rd</sub> / M<sub>max,unit</sub>", eq_style))
        story.append(Paragraph(f"  <i>H<sub>Rd</sub> = {res['M_rd']:.1f} kN.m / {res['momento_max_unit']:.4f} m = <b>{res['H_rd']:.1f} kN</b></i>", eq_style))
        story.append(Spacer(1, 4))

        txt_legenda = "<i><u>Nomenclatura:</u> <b>A<sub>c</sub></b> = Área da Seção; <b>U</b> = Perímetro; <b>Δz</b> = Incremento de profundidade; <b>N<sub>SPT</sub></b> = Índice de penetração; <b>K, C, α, β</b> = Parâmetros do solo; <b>H</b> = Força Horizontal; <b>M</b> = Momento Fletor; <b>M<sub>max,unit</sub></b> = Momento gerado por força horizontal unitária de 1kN.</i>"
        story.append(Paragraph(txt_legenda, legenda_style))
        
        if criterio_q_adm == "Apenas Aoki-Velloso":
            data_tab = [["Prof(m)", "Solo", "N", "K", "α", "Kh(kN/m³)", "Kv(kN/m³)", "Rp (kN)", "Σ Rl (kN)", "Rc Adm"]]
            for idx, r in res["df_inf"].iterrows(): 
                data_tab.append([f"{r['Profundidade (m)']:.1f}", str(r['Tipo de Solo'])[:8], f"{r['N_SPT']:.0f}", f"{r['K_aoki']:.0f}", f"{r['alpha_aoki']:.3f}", f"{r['kh (kN/m³)']:.0f}", f"{r['kv (kN/m³)']:.0f}", f"{r['Rp (kN)']:.1f}", f"{r['Rl_Aoki_Acum']:.1f}", f"{r['Rc Adm Aoki (kN)']:.1f}"])
            t_m = Table(data_tab, colWidths=[40, 70, 25, 30, 35, 60, 60, 60, 60, 75], repeatRows=1)
        
        elif criterio_q_adm == "Apenas Décourt-Quaresma":
            data_tab = [["Prof(m)", "Solo", "N", "C", "N_eq", "Kh(kN/m³)", "Kv(kN/m³)", "Rp (kN)", "Σ Rl (kN)", "Rc Adm"]]
            for idx, r in res["df_inf"].iterrows(): 
                data_tab.append([f"{r['Profundidade (m)']:.1f}", str(r['Tipo de Solo'])[:8], f"{r['N_SPT']:.0f}", f"{r['C_dq']:.0f}", f"{r['N_dq']:.1f}", f"{r['kh (kN/m³)']:.0f}", f"{r['kv (kN/m³)']:.0f}", f"{r['Rp_dq']:.1f}", f"{r['Rl_DQ_Acum']:.1f}", f"{r['Rc Adm DQ (kN)']:.1f}"])
            t_m = Table(data_tab, colWidths=[40, 70, 25, 30, 35, 60, 60, 60, 60, 75], repeatRows=1)
        
        elif criterio_q_adm == "Apenas Teixeira":
            data_tab = [["Prof(m)", "Solo", "N", "α_T", "Kh(kN/m³)", "Kv(kN/m³)", "Rp (kN)", "Σ Rl (kN)", "Rc Adm (kN)"]]
            for idx, r in res["df_inf"].iterrows(): 
                data_tab.append([f"{r['Profundidade (m)']:.1f}", str(r['Tipo de Solo'])[:8], f"{r['N_SPT']:.0f}", f"{r['alpha_teix']:.0f}", f"{r['kh (kN/m³)']:.0f}", f"{r['kv (kN/m³)']:.0f}", f"{r['Rp_t']:.1f}", f"{r['Rl_T_Acum']:.1f}", f"{r['Rc Adm Teix (kN)']:.1f}"])
            t_m = Table(data_tab, colWidths=[40, 80, 30, 35, 65, 65, 65, 65, 80], repeatRows=1)
        
        else:
            data_tab = [["Prof(m)", "Solo", "N", "Kh(kN/m³)", "Kv(kN/m³)", "Rc Aoki", "Rc Décourt", "Rc Teix.", "Rc Adot."]]
            for idx, r in res["df_inf"].iterrows(): 
                data_tab.append([f"{r['Profundidade (m)']:.1f}", str(r['Tipo de Solo'])[:8], f"{r['N_SPT']:.0f}", f"{r['kh (kN/m³)']:.0f}", f"{r['kv (kN/m³)']:.0f}", f"{r['Rc Adm Aoki (kN)']:.0f}", f"{r['Rc Adm DQ (kN)']:.0f}", f"{r['Rc Adm Teix (kN)']:.0f}", f"{r['Rc Adm Adotada (kN)']:.0f}"])
            t_m = Table(data_tab, colWidths=[40, 75, 25, 60, 60, 65, 65, 65, 75], repeatRows=1)
            
        t_m.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1E3A8A')), 
            ('TEXTCOLOR', (0,0), (-1,0), colors.white), 
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey), 
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('TOPPADDING', (0,0), (-1,-1), 4)
        ]))
        story.append(t_m)
        story.append(PageBreak())
        
        story.append(Paragraph("<b>Análise Visual de Comportamento</b>", h2_style))
        fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(12, 3))
        ax1.plot(res["df_inf"]["Rc Adm Aoki (kN)"], res["df_inf"]["Profundidade (m)"], label="Aoki", color="green", alpha=0.3)
        ax1.plot(res["df_inf"]["Rc Adm DQ (kN)"], res["df_inf"]["Profundidade (m)"], label="Décourt", color="blue", alpha=0.3)
        ax1.plot(res["df_inf"]["Rc Adm Teix (kN)"], res["df_inf"]["Profundidade (m)"], label="Teixeira", color="orange", alpha=0.3)
        ax1.plot(res["df_inf"]["Rc Adm Adotada (kN)"], res["df_inf"]["Profundidade (m)"], label="Adotada", color="black", linewidth=2.5, linestyle=':')
        ax1.axvline(x=carga_V, color='red', linestyle='--')
        ax1.invert_yaxis(); ax1.set_title("Resistência (kN)"); ax1.grid(True, ls="--", alpha=0.5); ax1.legend(fontsize=7)
        
        ax2.plot(res["m_flet"], res["z_vals"], color="red")
        ax2.axvline(x=res["M_rd"], color='darkred', linestyle='--')
        ax2.invert_yaxis(); ax2.set_title("Momento Fletor"); ax2.grid(True, ls="--", alpha=0.5)
        
        ax3.plot(res_atual["y_disp"]*1000, res_atual["z_vals"], color="blue")
        ax3.invert_yaxis(); ax3.set_title("Elástica (mm)"); ax3.grid(True, ls="--", alpha=0.5)
        
        buf_graf = io.BytesIO()
        fig.savefig(buf_graf, format='png', dpi=150, bbox_inches='tight')
        buf_graf.seek(0)
        plt.close(fig) 
        
        story.append(ReportLabImage(buf_graf, width=500, height=130))
        story.append(Spacer(1, 15))
        
        if dados["img"] is not None:
            story.append(Paragraph(f"<b>Anexo Visual: Imagem Capturada do {nome_furo}</b>", h2_style))
            img_buffer = io.BytesIO(dados["img"])
            story.append(ReportLabImage(img_buffer, width=400, height=550, kind='proportional'))
            
        story.append(PageBreak())
        num_seccao += 1

    doc.build(story)
    pdf_buffer.seek(0)
    return pdf_buffer.getvalue()

st.sidebar.markdown("---")
st.sidebar.header("📁 Geração do Relatório")
if len(st.session_state.projeto_furos) > 0:
    pdf_final_bytes = gerar_pdf_multiprojeto()
    if pdf_final_bytes:
        nome_arquivo_pdf = re.sub(r'[^A-Za-z0-9_-]', '', nome_obra)[:20]
        st.sidebar.download_button(
            label="📄 Baixar Memorial Completo (PDF)",
            data=pdf_final_bytes,
            file_name=f"Memorial_Consolidado_{nome_arquivo_pdf}.pdf",
            mime="application/pdf",
            type="primary",
            use_container_width=True
        )
else:
    st.sidebar.info("Salve furos no projeto para habilitar a geração do PDF.")
