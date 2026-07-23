import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# -----------------------------------------------------------------------------
# DICIONÁRIO GEOTÉCNICO DE SOLOS (Parâmetros exatos Aoki-Velloso e Molas)
# -----------------------------------------------------------------------------
PARAMETROS_SOLO = {
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
st.caption("Verificação de Capacidade de Carga (Aoki-Velloso), Molas e Esforços (Winkler)")

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
# TABELA DE SONDAGEM SPT
# -----------------------------------------------------------------------------
col_esq, col_dir = st.columns([1.2, 1])

with col_esq:
    st.subheader("📑 Boletim de Sondagem SPT")
    profundidades = list(range(1, 16))
    
    spt_padrao = [6, 8, 4, 5, 8, 11, 5, 7, 8, 11, 11, 12, 18, 21, 24]
    solos_modelo = ["Argila"] * 15

    df_spt_input = pd.DataFrame({
        "Profundidade (m)": profundidades,
        "N_SPT": spt_padrao,
        "Tipo de Solo": solos_modelo
    })

    df_spt = st.data_editor(
        df_spt_input,
        column_config={
            "Profundidade (m)": st.column_config.NumberColumn(disabled=True),
            "N_SPT": st.column_config.NumberColumn(min_value=1, max_value=100, step=1),
            "Tipo de Solo": st.column_config.SelectboxColumn(options=OPCOES_SOLO)
        },
        num_rows="dynamic",
        use_container_width=True
    )

# -----------------------------------------------------------------------------
# CÁLCULOS DINÂMICOS (MOLAS E AOKI-VELLOSO CUMULATIVO)
# -----------------------------------------------------------------------------
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
    
    es = solo["alpha_k"] * n
    k1 = 1200 * n
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
# CÁLCULOS GLOBAIS ESTRUTURAIS
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
A_s = (taxa_armadura / 100) * Area_c
braco_alavanca = 0.75 * B if secao == "Circular" else 0.80 * B
M_rd = A_s * fyd * braco_alavanca 

K_linha = kh_global * B
lamb = (K_linha / (4 * E_c * Inercia_c)) ** 0.25
z_vals = np.linspace(0, comprimento_estaca if tipo_fundacao == "Profunda (Estaca)" else 1, 100)

y_disp = (np.exp(-lamb * z_vals) / (2 * E_c * Inercia_c * lamb**3)) * (carga_H * np.cos(lamb * z_vals) + lamb * carga_M * (np.cos(lamb * z_vals) + np.sin(lamb * z_vals)))
m_flet = (np.exp(-lamb * z_vals) / lamb) * (carga_H * np.sin(lamb * z_vals) + lamb * carga_M * (np.cos(lamb * z_vals) - np.sin(lamb * z_vals)))
momento_max_atuante = np.max(np.abs(m_flet)) if len(m_flet) > 0 else 0
deslocamento_max_mm = np.max(np.abs(y_disp)) * 1000 if len(y_disp) > 0 else 0

m_flet_unit = (np.exp(-lamb * z_vals) / lamb) * (1.0 * np.sin(lamb * z_vals))
momento_max_unit = np.max(np.abs(m_flet_unit))
H_rd = M_rd / momento_max_unit if momento_max_unit > 0 else 0

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
    st.markdown("---")
    
    st.markdown("**2. Coeficientes de Recalque (Molas)**")
    m1, m2 = st.columns(2)
    m1.metric("k_v (Vertical Global)", f"{kv_global:,.0f} kN/m³")
    m2.metric("k_h (Horizontal Médio)", f"{kh_global:,.0f} kN/m³")
    st.markdown("---")

    st.markdown("**3. Resistência Estrutural à Flexão**")
    f1, f2 = st.columns(2)
    f1.metric("Momento Resistente (M_Rd)", f"{M_rd:.1f} kN.m")
    f2.metric("Momento Máx Atuante", f"{momento_max_atuante:.1f} kN.m")
    
    h1, h2 = st.columns(2)
    h1.metric("Força Horiz. Máx (H_Rd)", f"{H_rd:.1f} kN")
    h2.metric("Deslocamento de Topo", f"{deslocamento_max_mm:.2f} mm")
    st.info(f"Status Estrutural: {'✅ OK' if momento_max_atuante <= M_rd else '❌ FALHA'}")

# -----------------------------------------------------------------------------
# TABELA DETALHADA UNIFICADA (AOKI-VELLOSO + MOLAS)
# -----------------------------------------------------------------------------
st.markdown("---")
st.subheader("📋 Discretização Metro a Metro (Aoki-Velloso e Molas)")
st.caption("Tabela completa com o cálculo cumulativo de resistência por atrito/ponta e os coeficientes de recalque k_v e k_h para lançamento estrutural.")

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
    use_container_width=True,
    hide_index=True
)

# -----------------------------------------------------------------------------
# GRÁFICOS (CAPACIDADE, MOLAS E ESFORÇOS)
# -----------------------------------------------------------------------------
st.markdown("---")
st.subheader("📈 Diagramas Geotécnicos e Estruturais")

if tipo_fundacao == "Profunda (Estaca)":
    fig, (ax_cap, ax0, ax1, ax2) = plt.subplots(1, 4, figsize=(22, 5))
    
    # 0. Capacidade de Carga vs Profundidade
    ax_cap.plot(df_export_completo["Rc Adm (kN)"], df_export_completo["Profundidade (m)"], label="Carga Admissível", marker="D", color="green")
    ax_cap.axvline(x=carga_V, color='red', linestyle='--', label="Carga Atuante")
    ax_cap.invert_yaxis()
    ax_cap.set_xlabel("Capacidade Admissível (kN)")
    ax_cap.set_ylabel("Profundidade (m)")
    ax_cap.set_title("Resistência Geotécnica (Aoki)")
    ax_cap.grid(True, linestyle="--", alpha=0.6)
    ax_cap.legend()
    
    # 1. Perfil de Molas Geotécnicas (k_v e k_h restaurados)
    ax0.plot(df_spt["kh (kN/m³)"], df_spt["Profundidade (m)"], label="k_h Horizontal", marker="o", color="#1f77b4")
    ax0.plot(df_spt["kv (kN/m³)"], df_spt["Profundidade (m)"], label="k_v Vertical", marker="s", color="#ff7f0e")
    ax0.axhspan(cota_assentamento, cota_fim, color='yellow', alpha=0.2, label="Trecho da Estaca")
    ax0.invert_yaxis()
    ax0.set_xlabel("Módulo de Recalque (kN/m³)")
    ax0.set_title("Perfil Geotécnico de Molas")
    ax0.grid(True, linestyle="--", alpha=0.6)
    ax0.legend()

    # 2. Diagrama de Momentos Fletores
    ax1.plot(m_flet, z_vals, color="red", linewidth=2, label="Momento Atuante")
    ax1.fill_betweenx(z_vals, 0, m_flet, color="red", alpha=0.2)
    ax1.axvline(x=M_rd, color='darkred', linestyle='--', label="Limite M_Rd")
    ax1.axvline(x=-M_rd, color='darkred', linestyle='--')
    ax1.invert_yaxis()
    ax1.set_xlabel("Momento Fletor (kN.m)")
    ax1.set_title("Diagrama de Momento Fletor")
    ax1.grid(True, linestyle="--", alpha=0.6)
    ax1.legend()
    
    # 3. Diagrama de Deslocamentos
    ax2.plot(y_disp * 1000, z_vals, color="blue", linewidth=2, label="Deslocamento")
    ax2.fill_betweenx(z_vals, 0, y_disp * 1000, color="blue", alpha=0.2)
    ax2.invert_yaxis()
    ax2.set_xlabel("Deslocamento (mm)")
    ax2.set_title("Elástica da Estaca")
    ax2.grid(True, linestyle="--", alpha=0.6)
    
    st.pyplot(fig)
