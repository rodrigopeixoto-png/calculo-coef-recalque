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
                            
                            resposta = modelo.generate_content([prompt, img])
                            
                            # Quebrado em várias linhas para evitar corte ao colar
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
                                st.success("Tabela extraída! Confira os dados abaixo e clique em Salvar.")
                            else:
                                st.error("Tabela não reconhecida na imagem.")
                        except Exception as e:
                            st.error(f"Erro IA: {e}")
                            
        except Exception as e: st.error(f"Erro PDF: {e}")

    st.markdown("---")
    st.write(f"**Revisão: {st.session_state.furo_atual_nome}**")
    df_editado = st.data_editor(
        st.session_state.furo_atual_df,
        column_config={"Tipo de Solo": st.column_config.SelectboxColumn("Tipo de Solo", options=OPCOES_SOLO)},
        num_rows="dynamic", width="stretch"
    )
    
    if st.button(f"💾 Salvar {st.session_state.furo_atual_nome} no Projeto", type="primary", width="stretch"):
        st.session_state.projeto_furos[st.session_state.furo_atual_nome] = {
            "df": df_editado.copy(),
            "img": st.session_state.furo_atual_img
        }
        st.success(f"Furo {st.session_state.furo_atual_nome} adicionado ao projeto!")
        
    if len(st.session_state.projeto_furos) > 0:
        if st.button("🗑️ Limpar Todos os Furos Salvos", width="stretch"):
            st.session_state.projeto_furos = {}
            st.rerun()

# -----------------------------------------------------------------------------
# COLUNA DIREITA: ABAS DE RESULTADOS
# -----------------------------------------------------------------------------
with col_dir:
    tab_resumo, tab_atual = st.tabs(["📊 Visão Geral do Terreno", "🔍 Análise Detalhada dos Furos"])

    # ABA 1: RESUMO DO PROJETO E RECOMENDAÇÃO AUTOMÁTICA
    with tab_resumo:
        st.subheader("Resumo dos Furos Salvos no Projeto")
        if len(st.session_state.projeto_furos) == 0:
            st.warning("Nenhum furo salvo ainda. Importe um PDF, extraia a tabela e clique em Salvar.")
            dados_resumo = []
            recomendacao = ""
        else:
            dados_resumo = []
            todos_spt_rasos = []
            
            for nome_furo, dados in st.session_state.projeto_furos.items():
                calc = processar_calculos_estaca(dados["df"], L_armadura_manual)
                df_furo = calc["df_spt"]
                prof_max = df_furo["Profundidade (m)"].max()
                spt_max = df_furo["N_SPT"].max()
                
                # Pega N_SPT dos primeiros 3 metros para avaliar fundação rasa
                spt_rasos = df_furo[df_furo["Profundidade (m)"] <= 3]["N_SPT"].mean()
                if not pd.isna(spt_rasos): todos_spt_rasos.append(spt_rasos)
                
                status_geo = "✅ OK" if carga_V <= calc["Q_adm"] else "❌ FALHA"
                
                dados_resumo.append({
                    "Furo": nome_furo,
                    "Prof. Total (m)": prof_max,
                    "Maior N_SPT": spt_max,
                    "Carga Adm (kN)": f"{calc['Q_adm']:.1f}",
                    "Status Atual": status_geo
                })
            
            st.table(pd.DataFrame(dados_resumo))
            
            # MOTOR DE RECOMENDAÇÃO BASEADO EM REGRAS
            st.markdown("### 🤖 Diagnóstico e Recomendação de Fundação")
            recomendacao = ""
            media_spt_raso = np.mean(todos_spt_rasos) if todos_spt_rasos else 0
            
            if media_spt_raso < 5:
                recomendacao += "**Terreno superficial mole/fofo:** A média de N_SPT nos primeiros 3 metros é muito baixa. **Recomendada Fundação Profunda (Estacas)**.\n\n"
            elif media_spt_raso > 15:
                recomendacao += "**Terreno superficial muito resistente:** Solo competente encontrado próximo à superfície. Viabilidade técnica para **Fundação Rasa (Sapatas/Radier)**.\n\n"
            else:
                recomendacao += "**Terreno superficial intermediário:** Fazer verificação de viabilidade econômica entre Sapatas (com melhoria de solo) e Estacas curtas.\n\n"
                
            if tem_na and nivel_agua < 5.0:
                recomendacao += f"**⚠️ Atenção ao Nível d'Água:** O lençol freático foi detectado raso (Profundidade {nivel_agua}m). Se optar por estacas, **evitar estaca escavada mecanizada sem camisa metálica**. Sugeridas estacas tipo Hélice Contínua ou Raiz para evitar desmoronamento do fuste."
            
            st.info(recomendacao)
            
    # ABA 2: ANÁLISE INDIVIDUAL DOS FUROS
    with tab_atual:
        # Monta um dicionário com todos os furos disponíveis para o Seletor
        furos_disponiveis = {}
        furos_disponiveis[f"{st.session_state.furo_atual_nome} (Em Edição na Tabela)"] = df_editado
        
        for k, v in st.session_state.projeto_furos.items():
            furos_disponiveis[f"{k} (Salvo no Projeto)"] = v["df"]
            
        furo_selecionado_visualizacao = st.selectbox(
            "Selecione o furo que deseja analisar graficamente:", 
            list(furos_disponiveis.keys())
        )
        
        df_para_analise = furos_disponiveis[furo_selecionado_visualizacao]
        res_atual = processar_calculos_estaca(df_para_analise, L_armadura_manual)
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Carga Adm (Geotécnica)", f"{res_atual['Q_adm']:,.1f} kN")
        c2.metric("Momento Resistente (M_Rd)", f"{res_atual['M_rd']:.1f} kN.m")
        c3.metric("Aço Total (Estaca)", f"{res_atual['peso_aco_total']:.1f} kg")
        
        st.markdown(f"**Gaiola:** {res_atual['L_armadura']:.2f} m | **Arm. Long.:** {res_atual['n_barras']} Φ {bitola:.1f} mm | **Estribos:** Φ 6.3 c/ 15cm")
        
        # Gráficos Resumidos
        fig_g, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(10, 4))
        
        ax1.plot(res_atual["df_inf"]["Rc Adm (kN)"], res_atual["df_inf"]["Profundidade (m)"], color="green", marker="D")
        ax1.axvline(x=carga_V, color="red", linestyle="--")
        ax1.set_title("Resistência Aoki (kN)")
        ax1.invert_yaxis()
        
        ax2.plot(res_atual["m_flet"], res_atual["z_vals"], color="red")
        ax2.axvline(x=res_atual["M_rd"], color='darkred', linestyle='--')
        ax2.set_title("Momento Fletor")
        ax2.invert_yaxis()
        
        ax3.plot(res_atual["y_disp"]*1000, res_atual["z_vals"], color="blue")
        ax3.set_title("Elástica (mm)")
        ax3.invert_yaxis()
        
        st.pyplot(fig_g)
        plt.close(fig_g) # Limpa a memória do gráfico

# -----------------------------------------------------------------------------
# GERAÇÃO DO MEGA RELATÓRIO PDF
# -----------------------------------------------------------------------------
def gerar_pdf_multiprojeto():
    if len(st.session_state.projeto_furos) == 0:
        return None
        
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('PDFTitle', parent=styles['Heading1'], fontSize=16, leading=20, textColor=colors.HexColor('#1E3A8A'), alignment=1, spaceAfter=10)
    h2_style = ParagraphStyle('PDFH2', parent=styles['Heading2'], fontSize=12, leading=16, textColor=colors.HexColor('#1E3A8A'), spaceBefore=10, spaceAfter=5)
    body_style = ParagraphStyle('PDFBody', parent=styles['Normal'], fontSize=9, leading=12)

    # 1. CABEÇALHO E CAPA GERAL
    if os.path.exists(logo_path):
        im = ReportLabImage(logo_path, width=150, height=60)
        im.hAlign = 'LEFT'
        t_cab = Table([[im, Paragraph(f"<b>OBRA:</b> {nome_obra}<br/><b>RESP. TÉCNICO:</b> {resp_tecnico}<br/><b>DATA:</b> {datetime.datetime.now().strftime('%d/%m/%Y')}", ParagraphStyle('CabInfo', parent=body_style, alignment=2))]], colWidths=[160, 340])
        t_cab.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
        story.append(t_cab)
        story.append(Spacer(1, 20))
        
    story.append(Paragraph("<b>MEMORIAL DE CÁLCULO DE FUNDAÇÕES</b>", title_style))
    story.append(Paragraph("<b>Projeto Geotécnico Consolidado - Múltiplos Furos</b>", ParagraphStyle('Sub', parent=body_style, alignment=1)))
    story.append(Spacer(1, 15))

    # 2. RESUMO DO PROJETO E RECOMENDAÇÃO
    story.append(Paragraph("<b>1. Resumo do Terreno e Diagnóstico</b>", h2_style))
    story.append(Paragraph(recomendacao.replace('\n', '<br/>'), body_style))
    story.append(Spacer(1, 10))
    
    dados_tab_resumo = [["Furo", "Prof. Final", "Maior SPT", "Rc Adm", "Status"]]
    for f in dados_resumo:
        dados_tab_resumo.append([f["Furo"], f"{f['Prof. Total (m)']}m", f['Maior N_SPT'], f"{f['Carga Adm (kN)']} kN", f['Status Atual']])
        
    t_res_geral = Table(dados_tab_resumo, colWidths=[100, 100, 100, 100, 100])
    t_res_geral.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1E3A8A')), ('TEXTCOLOR', (0,0), (-1,0), colors.white), ('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('ALIGN', (0,0), (-1,-1), 'CENTER')]))
    story.append(t_res_geral)
    story.append(PageBreak())

    # 3. LOOP PARA CADA FURO SALVO
    for nome_furo, dados in st.session_state.projeto_furos.items():
        res = processar_calculos_estaca(dados["df"], L_armadura_manual)
        
        story.append(Paragraph(f"<b>ANÁLISE INDIVIDUAL: FURO {nome_furo}</b>", title_style))
        story.append(Spacer(1, 10))
        
        story.append(Paragraph("<b>Geometria e Quantitativos (Por Estaca)</b>", h2_style))
        txt_res = f"<b>Q_adm:</b> {res['Q_adm']:.1f} kN | <b>M_Rd:</b> {res['M_rd']:.1f} kN.m | <b>Desloc Topo:</b> {res['deslocamento_max_mm']:.2f} mm<br/>"
        txt_res += f"<b>Armadura Long.:</b> {res['n_barras']} Φ {bitola:.1f} mm | <b>Comprimento Gaiola:</b> {res['L_armadura']:.2f} m<br/>"
        txt_res += f"<b>Volume Concreto:</b> {res['V_concreto']:.2f} m³ | <b>Aço Total:</b> {res['peso_aco_total']:.1f} kg"
        story.append(Paragraph(txt_res, body_style))
        story.append(Spacer(1, 15))
        
        # GERAR GRÁFICOS DO FURO ESPECÍFICO
        fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(12, 3))
        ax1.plot(res["df_inf"]["Rc Adm (kN)"], res["df_inf"]["Profundidade (m)"], label="Carga Adm", color="green")
        ax1.axvline(x=carga_V, color='red', linestyle='--')
        ax1.invert_yaxis(); ax1.set_title("Resistência Aoki"); ax1.grid(True, ls="--", alpha=0.5)
        
        ax2.plot(res["m_flet"], res["z_vals"], color="red")
        ax2.axvline(x=res["M_rd"], color='darkred', linestyle='--')
        ax2.invert_yaxis(); ax2.set_title("Momento Fletor"); ax2.grid(True, ls="--", alpha=0.5)
        
        ax3.plot(res["y_disp"]*1000, res["z_vals"], color="blue")
        ax3.invert_yaxis(); ax3.set_title("Deslocamento (mm)"); ax3.grid(True, ls="--", alpha=0.5)
        
        buf_graf = io.BytesIO()
        fig.savefig(buf_graf, format='png', dpi=150, bbox_inches='tight')
        buf_graf.seek(0)
        plt.close(fig) # Importante para não explodir a memória RAM
        
        story.append(ReportLabImage(buf_graf, width=500, height=130))
        story.append(Spacer(1, 15))
        
        # TABELA DISCRETIZADA
        story.append(Paragraph("<b>Tabela Metro a Metro</b>", h2_style))
        data_tab = [["Prof(m)", "Solo", "N_SPT", "k_v", "k_h", "Rc Adm (kN)"]]
        for idx, r in res["df_inf"].head(10).iterrows(): # Mostra os primeiros 10m no PDF para caber
            data_tab.append([f"{r['Profundidade (m)']:.0f}", str(r['Tipo de Solo'])[:10], f"{r['N_SPT']:.0f}", f"{r['kv (kN/m³)']:,.0f}", f"{r['kh (kN/m³)']:,.0f}", f"{r['Rc Adm (kN)']:.1f}"])
        t_m = Table(data_tab, colWidths=[50, 90, 50, 60, 60, 90])
        t_m.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1E3A8A')), ('TEXTCOLOR', (0,0), (-1,0), colors.white), ('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('ALIGN', (0,0), (-1,-1), 'CENTER')]))
        story.append(t_m)
        
        # IMAGEM ORIGINAL DO FURO
        if dados["img"] is not None:
            story.append(PageBreak())
            story.append(Paragraph(f"<b>Anexo Visual: Imagem Capturada do {nome_furo}</b>", h2_style))
            img_buffer = io.BytesIO(dados["img"])
            story.append(ReportLabImage(img_buffer, width=400, height=600))
            
        story.append(PageBreak())

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
