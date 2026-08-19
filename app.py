import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import io
import re
import json
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
    st.info("🤖 **Leitor Híbrido IA:** Detecta os furos do PDF e analisa a imagem da página do furo escolhido.")
    st.markdown("[👉 **Clique aqui para gerar sua API Key gratuita no Google AI Studio**](https://aistudio.google.com/app/apikey)")
    
    api_key = st.text_input("🔑 Insira sua API Key do Google Gemini:", type="password")
    arquivo_pdf = st.file_uploader("📥 Importar Laudo de Sondagem (PDF)", type=["pdf"])
    
    # Tabela inicial na sessão
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
                            Você é um engenheiro geotécnico especialista em ler laudos de sondagem SPT brasileiros.
                            Analise a imagem desta página de laudo referente ao furo "{furo_selecionado}".

                            INSTRUÇÕES DE EXTRAÇÃO METRO A METRO:
                            1. "Profundidade (m)": Número inteiro sequencial de cada metro (1, 2, 3, 4, 5, 6, 7, 8, 9, 10...).
                            2. "N_SPT": É o valor correspondente aos golpes dos últimos 30 cm (coluna "2ª + 3ª").
                               - Se for um valor numérico simples (ex: 7, 26, 25), extraia o número.
                               - Se for uma fração (ex: "13/29", "15/28", "10/28"), EXTRAIA APENAS O NUMERADOR (ex: 13, 15, 10).
                            3. "Tipo de Solo": Analise a "Classificação do Material" para aquele metro e ESCOLHA OBRIGATORIAMENTE o solo mais correspondente desta lista:
                               {lista_solos_str}

                            Retorne uma LISTA DE OBJETOS JSON, onde cada objeto tem exatamente as chaves:
                            "Profundidade (m)", "N_SPT", "Tipo de Solo"
                            """
                            
                            # Chamada nativa com retorno em JSON
                            resposta = modelo_visao.generate_content(
                                [prompt, img],
                                generation_config={"response_mime_type": "application/json"}
                            )
                            
                            dados_json = json.loads(resposta.text)
                            df_ia = pd.DataFrame(dados_json)
                            
                            # Tratamento e limpeza dos tipos de dados
                            df_ia['Profundidade (m)'] = pd.to_numeric(df_ia['Profundidade (m)'], errors='coerce')
                            df_ia['N_SPT'] = pd.to_numeric(df_ia['N_SPT'], errors='coerce')
                            df_ia = df_ia.dropna(subset=['Profundidade (m)']).astype({'Profundidade (m)': 'int', 'N_SPT': 'int'})
                            
                            if len(df_ia) > 0:
                                st.session_state.tabela_spt = df_ia
                                st.session_state.imagem_sondagem = b_data
                                st.success(f"✅ Furo {furo_selecionado} lido com sucesso!")
                                st.rerun()
                            else:
                                st.error("A IA não retornou linhas válidas para o furo.")
                        except Exception as e:
                            st.error(f"Erro na análise visual da IA: {e}")

    st.markdown("---")

    # Declaração incondicional de df_editado
    df_editado = st.data_editor(
        st.session_state.tabela_spt,
        column_config={
            "Profundidade (m)": st.column_config.NumberColumn("Profundidade (m)", min_value=1, step=1),
            "N_SPT": st.column_config.NumberColumn("N_SPT", min_value=1, max_value=100, step=1),
            "Tipo de Solo": st.column_config.SelectboxColumn("Tipo de Solo", options=OPCOES_SOLO)
        },
        num_rows="dynamic",
        width="stretch"
    )

# -----------------------------------------------------------------------------
# CÁLCULOS DINÂMICOS (MOLAS E AOKI-VELLOSO CUMULATIVO)
# -----------------------------------------------------------------------------
df_spt = df_editado.copy()

df_spt["Profundidade (m)"] = range(1, len(df_spt) + 1)
df_spt["N_SPT"] = pd.to_numeric(df_spt["N_SPT"], errors="coerce").fillna(1)
df_spt["Tipo de Solo"] = df_spt["Tipo de Solo"].fillna("Argila")
df_spt["N_corr"] = df_spt["N_SPT"].apply(lambda x: min(x, 50))
df_spt["N_Aoki"] = df_spt["N_SPT"].apply(lambda x: min(x, 50))

Area_c = (np.pi * B**2) / 4 if secao == "Circular" else B**2
Inercia_c = (np.pi * B**4) / 64 if secao == "Circular" else (B**4) / 12
Perimetro = np.pi * B if secao == "Circular" else 4 * B
E_c = 5600 * np.sqrt(fck) * 1000 

f1 = FATORES_CONSTRUTIVOS[metodo_construtivo]["F1"]
f2 = FATORES_CONSTRUTIVOS[metodo_construtivo]["F2"]

def processar_solo(row):
    solo = PARAMETROS_SOLO.get(row["Tipo de Solo"], PARAMETROS_SOLO["Argila"])
    n = row["N_corr"]
    prof = row["Profundidade (m)"]
    
    fator_agua = 0.5 if (prof >= nivel_agua and solo["comportamento"] == "granular") else 1.0
    
    es = solo["alpha_k"] * n * fator_agua
    k1 = 1200 * n * fator_agua
    kv = k1 * (0.3 / B) if solo["comportamento"] == "coesivo" else k1 * ((B + 0.3) / (2 * B)) ** 2
    kh = kv * nu
    
    rl = (solo["aoki_alpha"] * solo["aoki_K"] * n) / f2
    rp = (solo["aoki_K"] * row["N_Aoki"]) / f1 * Area_c
    delta_rl = rl * Perimetro * 1.0 
    
    return pd.Series([es, kv, kh, rl, rp, delta_rl])

df_spt[["Es (kPa)", "kv (kN/m³)", "kh (kN/m³)", "rl (kPa)", "Rp (kN)", "delta_Rl (kN)"]] = df_spt.apply(processar_solo, axis=1)

cota_fim = cota_assentamento + (comprimento_estaca if tipo_fundacao == "Profunda (Estaca)" else 1.5 * B)
df_inf = df_spt[(df_spt["Profundidade (m)"] > cota_assentamento) & (df_spt["Profundidade (m)"] <= cota_fim)].copy()

if not df_inf.empty:
    df_inf["Rl Acum. (kN)"] = df_inf["delta_Rl (kN)"].cumsum()
    df_inf["Rc Adm (kN)"] = (df_inf["Rp (kN)"] + df_inf["Rl Acum. (kN)"]) / 2.0
else:
    df_inf = df_spt.head(1).copy()
    df_inf["Rl Acum. (kN)"] = 0
    df_inf["Rc Adm (kN)"] = 0

# -----------------------------------------------------------------------------
# CÁLCULOS GLOBAIS ESTRUTURAIS E ESFORÇOS (Winkler)
# -----------------------------------------------------------------------------
kh_global = df_inf["kh (kN/m³)"].mean()

if tipo_fundacao == "Rasa (Sapata/Radier)":
    kv_global = df_inf["kv (kN/m³)"].mean()
else:
    n_ponta = df_inf.iloc[-1]["N_corr"]
    es_ponta = 1000 * n_ponta if "Escavada" in metodo_construtivo else 3000 * n_ponta
    kv_global = es_ponta / (B * (1 - nu**2) * 0.85)

Q_adm = df_inf.iloc[-1]["Rc Adm (kN)"] if not df_inf.empty else 0
N_d_max = Area_c * ((0.85 * fck * 1000) / 1.4) 
fyd = (fyk / 1.15) * 1000

K_linha = kh_global * B
lamb = (K_linha / (4 * E_c * Inercia_c)) ** 0.25
z_vals = np.linspace(0, comprimento_estaca if tipo_fundacao == "Profunda (Estaca)" else 1, 200)

y_disp = (np.exp(-lamb * z_vals) / (2 * E_c * Inercia_c * lamb**3)) * (carga_H * np.cos(lamb * z_vals) + lamb * carga_M * (np.cos(lamb * z_vals) + np.sin(lamb * z_vals)))
m_flet = (np.exp(-lamb * z_vals) / lamb) * (carga_H * np.sin(lamb * z_vals) + lamb * carga_M * (np.cos(lamb * z_vals) - np.sin(lamb * z_vals)))
momento_max_atuante = np.max(np.abs(m_flet)) if len(m_flet) > 0 else 0
deslocamento_max_mm = np.max(np.abs(y_disp)) * 1000 if len(y_disp) > 0 else 0

m_flet_unit = (np.exp(-lamb * z_vals) / lamb) * (1.0 * np.sin(lamb * z_vals))
momento_max_unit = np.max(np.max(np.abs(m_flet_unit)))

# -----------------------------------------------------------------------------
# DEDUZINDO O COMPRIMENTO DA ARMADURA (NBR 6118 / NBR 6122)
# -----------------------------------------------------------------------------
f_ctk_inf = 0.21 * (fck ** (2/3)) * 1000 
W_c = Inercia_c / (B / 2) 
alpha_flexao = 1.5 if secao == "Quadrada" else 1.2
M_cr = W_c * (alpha_flexao * f_ctk_inf + (carga_V / Area_c)) 

idx_max_m = np.argmax(np.abs(m_flet))
m_apos_max = np.abs(m_flet[idx_max_m:])
z_apos_max = z_vals[idx_max_m:]

idx_nulo = np.where(m_apos_max <= M_cr)[0]
z_momento_nulo = z_apos_max[idx_nulo[0]] if len(idx_nulo) > 0 else comprimento_estaca

L_b = 0.40 
L_flexao_necessario = z_momento_nulo + L_b
L_min_norma = max(3.0, 5 * B)
L_armadura_calc = min(comprimento_estaca, max(L_min_norma, L_flexao_necessario)) if tipo_fundacao == "Profunda (Estaca)" else 0.0

# -----------------------------------------------------------------------------
# SIDEBAR - DETALHAMENTO DA ARMADURA E QUANTITATIVOS
# -----------------------------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.header("🔧 Detalhamento da Armadura")

bitola = st.sidebar.selectbox("Bitola Longitudinal (mm)", [10.0, 12.5, 16.0, 20.0, 25.0], index=0)

override_l = st.sidebar.checkbox("Ajustar Comprimento Manualmente?", value=False)
if override_l:
    limite_minimo = float(L_armadura_calc)
    limite_maximo = float(comprimento_estaca) if comprimento_estaca > L_armadura_calc else limite_minimo
    valor_sugerido = min(np.ceil(L_armadura_calc * 2) / 2, limite_maximo) 
    L_armadura = st.sidebar.number_input(
        "Comprimento da Gaiola (m)", 
        min_value=limite_minimo, 
        max_value=limite_maximo, 
        value=float(valor_sugerido), 
        step=0.5
    )
else:
    L_armadura = L_armadura_calc
    st.sidebar.info(f"Comprimento automático (Norma): {L_armadura_calc:.2f} m")

# -----------------------------------------------------------------------------
# CÁLCULO DA RESISTÊNCIA ESTRUTURAL E QUANTITATIVOS DE MATERIAIS
# -----------------------------------------------------------------------------
area_barra = (np.pi * (bitola / 1000)**2) / 4  
A_s_teorico = (taxa_armadura / 100) * Area_c
n_raw = A_s_teorico / area_barra
frac = n_raw - np.floor(n_raw)
n_barras = int(np.floor(n_raw)) if frac < 0.5 else int(np.ceil(n_raw))
n_barras = max(n_barras, 6)

if secao == "Quadrada":
    if n_barras % 4 != 0:
        n_barras += (4 - n_barras % 4)
    n_barras = max(n_barras, 8)

A_s_real = n_barras * area_barra
braco_alavanca = 0.75 * B if secao == "Circular" else 0.80 * B
M_rd = A_s_real * fyd * braco_alavanca 
H_rd = M_rd / momento_max_unit if momento_max_unit > 0 else 0

V_concreto = Area_c * comprimento_estaca
peso_esp_aco = 7850 
cobrimento = 0.04 
peso_long = n_barras * area_barra * L_armadura * peso_esp_aco

bitola_estribo = 6.3 
espacamento_estribo = 0.15 
area_estribo = (np.pi * (bitola_estribo / 1000)**2) / 4
perimetro_estribo = np.pi * (B - 2*cobrimento) if secao == "Circular" else 4 * (B - 2*cobrimento)
n_estribos = int(L_armadura / espacamento_estribo)
peso_estribo = n_estribos * perimetro_estribo * area_estribo * peso_esp_aco

peso_aco_total = peso_long + peso_estribo
taxa_aco_kg_m3 = peso_aco_total / V_concreto if V_concreto > 0 else 0

# -----------------------------------------------------------------------------
# PAINEL DE RESULTADOS (COLUNA DIREITA)
# -----------------------------------------------------------------------------
with col_dir:
    st.subheader("📊 Relatório Final da Estaca")
    
    st.markdown("**1. Capacidade Geotécnica (Aoki-Velloso)**")
    c1, c2 = st.columns(2)
    c1.metric("Carga Adm. Total (Rc Adm)", f"{Q_adm:,.2f} kN")
    c2.metric("Carga Atuante (Pilar)", f"{carga_V:,.2f} kN")
    st.info(f"Status Geotécnico: {'✅ OK' if carga_V <= Q_adm else '❌ FALHA'}")
    
    st.markdown("**2. Coeficientes de Recalque (Molas)**")
    m1, m2 = st.columns(2)
    m1.metric("k_v (Vertical Global)", f"{kv_global:,.0f} kN/m³")
    m2.metric("k_h (Horizontal Médio)", f"{kh_global:,.0f} kN/m³")

    st.markdown("**3. Resistência Estrutural à Flexão**")
    f1, f2 = st.columns(2)
    f1.metric("Momento Resistente (M_Rd)", f"{M_rd:.1f} kN.m")
    f2.metric("Momento Máx Atuante", f"{momento_max_atuante:.1f} kN.m")
    h1, h2 = st.columns(2)
    h1.metric("Força Horiz. Máx (H_Rd)", f"{H_rd:.1f} kN")
    h2.metric("Deslocamento de Topo", f"{deslocamento_max_mm:.2f} mm")
    st.info(f"Status Estrutural: {'✅ OK' if momento_max_atuante <= M_rd else '❌ FALHA'}")

    st.markdown("---")
    st.markdown("**4. Detalhamento e Quantitativos (Por Estaca)**")
    
    col_info, col_img = st.columns([1.2, 1])
    with col_info:
        st.write(f"**Gaiola ($L_{{arm}}$):** **{L_armadura:.2f} m**")
        st.write(f"**Arm. Long.:** {n_barras} Φ {bitola:.1f} mm")
        st.write(f"**Estribos:** Φ 6.3 c/ 15cm")
        st.markdown("---")
        st.write(f"**Concreto:** {V_concreto:.2f} m³")
        st.write(f"**Aço Long.:** {peso_long:.1f} kg")
        st.write(f"**Aço Estribo:** {peso_estribo:.1f} kg")
        st.write(f"**Aço Total:** **{peso_aco_total:.1f} kg**")
        st.write(f"**Taxa de Aço:** {taxa_aco_kg_m3:.1f} kg/m³")

    with col_img:
        fig_sec, ax_sec = plt.subplots(figsize=(2.8, 2.8))
        if secao == "Circular":
            R = B / 2
            Rs = R - cobrimento
            ax_sec.add_patch(plt.Circle((0, 0), R, color='#E0E0E0', ec='black', lw=1.5))
            ax_sec.add_patch(plt.Circle((0, 0), Rs, color='none', ec='black', lw=1.5, ls='--')) 
            theta = np.linspace(0, 2*np.pi, n_barras, endpoint=False)
            ax_sec.plot(Rs * np.cos(theta), Rs * np.sin(theta), 'ro', markersize=6, markeredgecolor='darkred')
        else:
            L = B / 2
            Ls = L - cobrimento
            ax_sec.add_patch(plt.Rectangle((-L, -L), B, B, color='#E0E0E0', ec='black', lw=1.5))
            ax_sec.add_patch(plt.Rectangle((-Ls, -Ls), B - 2*cobrimento, B - 2*cobrimento, fill=False, ec='black', lw=1.5, ls='--')) 
            x_bars, y_bars = [], []
            n_per_side = n_barras // 4
            corners_x, corners_y = [-Ls, Ls, Ls, -Ls], [Ls, Ls, -Ls, -Ls]
            for i in range(4):
                x1, y1 = corners_x[i], corners_y[i]
                x2, y2 = corners_x[(i+1)%4], corners_y[(i+1)%4]
                for j in range(n_per_side):
                    f = j / n_per_side
                    x_bars.append(x1 + f * (x2 - x1))
                    y_bars.append(y1 + f * (y2 - y1))
            ax_sec.plot(x_bars, y_bars, 'ro', markersize=6, markeredgecolor='darkred')

        ax_sec.set_xlim(-B/2 - 0.05, B/2 + 0.05)
        ax_sec.set_ylim(-B/2 - 0.05, B/2 + 0.05)
        ax_sec.set_aspect('equal')
        ax_sec.axis('off')
        st.pyplot(fig_sec)

# -----------------------------------------------------------------------------
# TABELA DETALHADA UNIFICADA (AOKI-VELLOSO + MOLAS)
# -----------------------------------------------------------------------------
st.markdown("---")
st.subheader("📋 Discretização Metro a Metro (Aoki-Velloso e Molas)")

df_export_completo = df_inf[[
    "Profundidade (m)", "Tipo de Solo", "N_SPT", 
    "kv (kN/m³)", "kh (kN/m³)", 
    "rl (kPa)", "Rp (kN)", "Rl Acum. (kN)", "Rc Adm (kN)"
]].copy()

st.dataframe(
    df_export_completo.style.format({
        "kv (kN/m³)": "{:,.2f}",
        "kh (kN/m³)": "{:,.2f}",
        "rl (kPa)": "{:,.2f}",
        "Rp (kN)": "{:,.2f}",
        "Rl Acum. (kN)": "{:,.2f}",
        "Rc Adm (kN)": "{:,.2f}"
    }),
    hide_index=True,
    width="stretch"
)

# -----------------------------------------------------------------------------
# GRÁFICOS (CAPACIDADE, MOLAS, ESFORÇOS E ELEVAÇÃO DA ARMADURA)
# -----------------------------------------------------------------------------
st.markdown("---")
st.subheader("📈 Diagramas Geotécnicos, Esforços e Elevação da Armadura")

if tipo_fundacao == "Profunda (Estaca)":
    fig_graficos, (ax_cap, ax0, ax1, ax2, ax_elev) = plt.subplots(1, 5, figsize=(25, 5.5))
    
    def plota_na(ax, c_len):
        if tem_na and nivel_agua <= c_len:
            ax.axhline(y=nivel_agua, color='blue', linestyle='-.', lw=1.2, alpha=0.6, label="N.A.")

    # 0. Capacidade Geotécnica
    ax_cap.plot(df_export_completo["Rc Adm (kN)"], df_export_completo["Profundidade (m)"], label="Carga Admissível", marker="D", color="green")
    ax_cap.axvline(x=carga_V, color='red', linestyle='--', label="Carga Atuante")
    plota_na(ax_cap, df_export_completo["Profundidade (m)"].max())
    ax_cap.invert_yaxis()
    ax_cap.set_xlabel("Capacidade Admissível (kN)")
    ax_cap.set_ylabel("Profundidade (m)")
    ax_cap.set_title("Resistência (Aoki)")
    ax_cap.grid(True, linestyle="--", alpha=0.6)
    
    # 1. Molas Geotécnicas
    ax0.plot(df_spt["kh (kN/m³)"], df_spt["Profundidade (m)"], label="k_h (Horizontal)", marker="o", color="#1f77b4")
    ax0.plot(df_spt["kv (kN/m³)"], df_spt["Profundidade (m)"], label="k_v (Vertical)", marker="s", color="#ff7f0e")
    ax0.axhspan(cota_assentamento, cota_fim, color='yellow', alpha=0.2)
    plota_na(ax0, df_spt["Profundidade (m)"].max())
    ax0.invert_yaxis()
    ax0.set_xlabel("Recalque (kN/m³)")
    ax0.set_title("Molas Solo")
    ax0.grid(True, linestyle="--", alpha=0.6)
    ax0.legend(loc="lower right", fontsize=9)

    # 2. Momento Fletor
    ax1.plot(m_flet, z_vals, color="red", linewidth=2, label="M Atuante")
    ax1.fill_betweenx(z_vals, 0, m_flet, color="red", alpha=0.2)
    ax1.axvline(x=M_cr, color='green', linestyle=':', label="M_cr")
    ax1.axvline(x=M_rd, color='darkred', linestyle='--', label="M_Rd")
    ax1.axvline(x=-M_rd, color='darkred', linestyle='--')
    plota_na(ax1, comprimento_estaca)
    ax1.invert_yaxis()
    ax1.set_xlabel("Momento (kN.m)")
    ax1.set_title("Momento Fletor")
    ax1.grid(True, linestyle="--", alpha=0.6)
    
    # 3. Deslocamentos
    ax2.plot(y_disp * 1000, z_vals, color="blue", linewidth=2, label="Desl.")
    ax2.fill_betweenx(z_vals, 0, y_disp * 1000, color="blue", alpha=0.2)
    plota_na(ax2, comprimento_estaca)
    ax2.invert_yaxis()
    ax2.set_xlabel("Deslocamento (mm)")
    ax2.set_title("Elástica")
    ax2.grid(True, linestyle="--", alpha=0.6)

    # 4. ELEVAÇÃO DETALHADA DA ESTACA
    ax_elev.plot([-B/2, -B/2], [0, comprimento_estaca], color='grey', lw=2)
    ax_elev.plot([B/2, B/2], [0, comprimento_estaca], color='grey', lw=2)
    ax_elev.plot([-B/2, B/2], [comprimento_estaca, comprimento_estaca], color='grey', lw=2)
    ax_elev.plot([-B/2*1.5, B/2*1.5], [0, 0], color='black', lw=3)
    
    if tem_na and nivel_agua <= comprimento_estaca:
        ax_elev.axhline(y=nivel_agua, color='blue', linestyle='-.', lw=2)
        ax_elev.fill_betweenx([nivel_agua, comprimento_estaca * 1.05], -B*1.2, B*1.2, color='blue', alpha=0.08)

    r_arm = B/2 - cobrimento
    ax_elev.plot([-r_arm, -r_arm], [0, L_armadura], color='red', lw=2)
    ax_elev.plot([r_arm, r_arm], [0, L_armadura], color='red', lw=2)
    
    z_estribos = np.arange(0, L_armadura, espacamento_estribo)
    for z_est in z_estribos:
        ax_elev.plot([-r_arm, r_arm], [z_est, z_est], color='darkred', lw=0.8, alpha=0.6)
        
    ax_elev.set_xlim(-B*1.2, B*1.2)
    ax_elev.set_ylim(0, comprimento_estaca * 1.05)
    ax_elev.invert_yaxis()
    ax_elev.set_ylabel("Profundidade (m)")
    ax_elev.set_title("Elevação e Armadura")
    ax_elev.grid(True, linestyle="--", alpha=0.4)

    st.pyplot(fig_graficos)

# -----------------------------------------------------------------------------
# FUNÇÃO PARA GERAR O RELATÓRIO PDF EM MEMÓRIA (REPORTLAB)
# -----------------------------------------------------------------------------
def gerar_pdf():
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('PDFTitle', parent=styles['Heading1'], fontSize=18, leading=22, textColor=colors.HexColor('#1E3A8A'), alignment=1, spaceAfter=15)
    h2_style = ParagraphStyle('PDFH2', parent=styles['Heading2'], fontSize=12, leading=16, textColor=colors.HexColor('#1E3A8A'), spaceBefore=10, spaceAfter=5)
    body_style = ParagraphStyle('PDFBody', parent=styles['Normal'], fontSize=9, leading=12)

    story.append(Paragraph("<b>MEMORIAL DE CÁLCULO DE FUNDAÇÕES</b>", title_style))
    story.append(Paragraph("<b>Integração Solo-Estrutura, Verificação e Quantitativos</b>", ParagraphStyle('Sub', parent=body_style, alignment=1, fontSize=10, leading=14)))
    story.append(Spacer(1, 15))

    story.append(Paragraph("<b>1. Parâmetros Gerais e Solicitações</b>", h2_style))
    data_input = [
        [Paragraph("<b>Fundação:</b>", body_style), Paragraph(f"{tipo_fundacao} ({metodo_construtivo})", body_style),
         Paragraph("<b>Carga Vertical (V):</b>", body_style), Paragraph(f"{carga_V:.1f} kN", body_style)],
        [Paragraph("<b>Geometria:</b>", body_style), Paragraph(f"{secao} - B = {B*100:.0f} cm", body_style),
         Paragraph("<b>Força Horizontal (H):</b>", body_style), Paragraph(f"{carga_H:.1f} kN", body_style)],
        [Paragraph("<b>Comprimento:</b>", body_style), Paragraph(f"{comprimento_estaca:.1f} m", body_style),
         Paragraph("<b>Momento Fletor (M):</b>", body_style), Paragraph(f"{carga_M:.1f} kN.m", body_style)],
        [Paragraph("<b>Material:</b>", body_style), Paragraph(f"fck = {fck:.0f} MPa | fyk = {fyk:.0f} MPa", body_style),
         Paragraph("<b>Nível d'Água (N.A.):</b>", body_style), Paragraph(f"{'Prof: ' + str(nivel_agua) + 'm' if tem_na else 'Ausente'}", body_style)]
    ]
    t_input = Table(data_input, colWidths=[90, 170, 110, 160])
    t_input.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F3F4F6')), ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#D1D5DB')), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('TOPPADDING', (0,0), (-1,-1), 4), ('BOTTOMPADDING', (0,0), (-1,-1), 4)]))
    story.append(t_input)
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>2. Resultados e Quantitativos de Materiais</b>", h2_style))
    data_res = [
        [Paragraph("<b>Capacidade Geotécnica (Q_adm)</b>", body_style), Paragraph(f"<b>{Q_adm:,.2f} kN</b> (Status: {'OK' if carga_V <= Q_adm else 'FALHA'})", body_style)],
        [Paragraph("<b>Capacidade Estrutural à Flexão (M_Rd)</b>", body_style), Paragraph(f"<b>{M_rd:.1f} kN.m</b> vs M_max = <b>{momento_max_atuante:.1f} kN.m</b>", body_style)],
        [Paragraph("<b>Força Horizontal (H_Rd) e Deslocamento</b>", body_style), Paragraph(f"H_Rd = <b>{H_rd:.1f} kN</b> | Desloc. = <b>{deslocamento_max_mm:.2f} mm</b>", body_style)],
        [Paragraph("<b>Detalhamento da Armadura</b>", body_style), Paragraph(f"Gaiola: <b>{L_armadura:.2f} m</b> | Long: <b>{n_barras} Φ {bitola:.1f} mm</b> | Estribo: <b>Φ 6.3 c/ 15cm</b>", body_style)],
        [Paragraph("<b>Quantitativos (Concreto e Aço)</b>", body_style), Paragraph(f"Vol. Conc.: <b>{V_concreto:.2f} m³</b> | Peso Aço: <b>{peso_aco_total:.1f} kg</b> (Taxa: {taxa_aco_kg_m3:.1f} kg/m³)", body_style)]
    ]
    t_res = Table(data_res, colWidths=[200, 330])
    t_res.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#9CA3AF')), ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#E5E7EB')), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('TOPPADDING', (0,0), (-1,-1), 4), ('BOTTOMPADDING', (0,0), (-1,-1), 4)]))
    story.append(t_res)
    story.append(Spacer(1, 15))

    buf_sec = io.BytesIO()
    fig_sec.savefig(buf_sec, format='png', dpi=200, bbox_inches='tight')
    buf_sec.seek(0)
    story.append(Paragraph("<b>3. Seção Transversal e Armadura</b>", h2_style))
    story.append(ReportLabImage(buf_sec, width=150, height=150))
    story.append(Spacer(1, 10))

    story.append(PageBreak())

    story.append(Paragraph("<b>4. Diagramas Geotécnicos, Esforços e Elevação</b>", h2_style))
    buf_graf = io.BytesIO()
    fig_graficos.savefig(buf_graf, format='png', dpi=200, bbox_inches='tight')
    buf_graf.seek(0)
    story.append(ReportLabImage(buf_graf, width=530, height=125))
    story.append(Spacer(1, 15))

    story.append(Paragraph("<b>5. Discretização Metro a Metro (Aoki-Velloso & Winkler)</b>", h2_style))
    data_tab = [["Prof(m)", "Solo", "N_SPT", "k_v (kN/m³)", "k_h (kN/m³)", "r_l (kPa)", "R_p (kN)", "R_c Adm (kN)"]]
    for idx, r in df_export_completo.head(15).iterrows():
        data_tab.append([
            f"{r['Profundidade (m)']:.0f}",
            str(r['Tipo de Solo'])[:12],
            f"{r['N_SPT']:.0f}",
            f"{r['kv (kN/m³)']:,.0f}",
            f"{r['kh (kN/m³)']:,.0f}",
            f"{r['rl (kPa)']:.1f}",
            f"{r['Rp (kN)']:.1f}",
            f"{r['Rc Adm (kN)']:.1f}"
        ])
    t_m = Table(data_tab, colWidths=[40, 80, 45, 75, 75, 60, 60, 95])
    t_m.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1E3A8A')), ('TEXTCOLOR', (0,0), (-1,0), colors.white), ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'), ('FONTSIZE', (0,0), (-1,-1), 8), ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#D1D5DB')), ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
    story.append(t_m)

    # ANEXO: IMAGEM DO BOLETIM DE SONDAGEM
    if "imagem_sondagem" in st.session_state and st.session_state.imagem_sondagem:
        story.append(Spacer(1, 15))
        story.append(Paragraph("<b>Anexo: Perfil do Boletim de Sondagem SPT</b>", h2_style))
        story.append(Spacer(1, 10))

        img_buffer = io.BytesIO(st.session_state.imagem_sondagem)
        largura_pdf = 14 * 28.35
        altura_pdf = 18 * 28.35
        
        img_pdf = ReportLabImage(img_buffer, width=largura_pdf, height=altura_pdf)
        img_pdf.hAlign = 'CENTER'
        story.append(img_pdf)

    doc.build(story)
    pdf_buffer.seek(0)
    return pdf_buffer.getvalue()

# -----------------------------------------------------------------------------
# BOTÃO DE DOWNLOAD DO PDF NO PAINEL DIREITO
# -----------------------------------------------------------------------------
with col_dir:
    st.markdown("---")
    pdf_bytes = gerar_pdf()
    st.download_button(
        label="📄 Baixar Memorial de Cálculo em PDF",
        data=pdf_bytes,
        file_name=f"Memorial_Calculo_Estaca_B{B*100:.0f}cm.pdf",
        mime="application/pdf",
        width="stretch"
    )
