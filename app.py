import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# -----------------------------------------------------------------------------
# DICIONÁRIO GEOTÉCNICO DE SOLOS (Com parâmetros de Aoki-Velloso)
# K em kPa, alpha adimensional
# -----------------------------------------------------------------------------
PARAMETROS_SOLO = {
    "Argila":           {"alpha_k": 1500, "comportamento": "coesivo",       "aoki_K": 200,  "aoki_alpha": 0.060},
    "Argila siltosa":   {"alpha_k": 1750, "comportamento": "coesivo",       "aoki_K": 250,  "aoki_alpha": 0.050},
    "Argila arenosa":   {"alpha_k": 2000, "comportamento": "coesivo",       "aoki_K": 350,  "aoki_alpha": 0.040},
    "Silte":            {"alpha_k": 2000, "comportamento": "intermediario", "aoki_K": 400,  "aoki_alpha": 0.045},
    "Silte argiloso":   {"alpha_k": 2000, "comportamento": "coesivo",       "aoki_K": 300,  "aoki_alpha": 0.055},
    "Silte arenoso":    {"alpha_k": 2500, "comportamento": "granular",      "aoki_K": 550,  "aoki_alpha": 0.035},
    "Areia argilosa":   {"alpha_k": 2500, "comportamento": "granular",      "aoki_K": 600,  "aoki_alpha": 0.030},
    "Areia siltosa":    {"alpha_k": 2800, "comportamento": "granular",      "aoki_K": 800,  "aoki_alpha": 0.020},
    "Areia":            {"alpha_k": 3000, "comportamento": "granular",      "aoki_K": 1000, "aoki_alpha": 0.014}
}

OPCOES_SOLO = list(PARAMETROS_SOLO.keys())

# Fatores Construtivos (Aoki-Velloso F1 e F2)
FATORES_CONSTRUTIVOS = {
    "Escavada (Hélice, Trado, Tubulão)": {"F1": 3.0, "F2": 6.0},
    "Cravada (Pré-moldada, Metálica)": {"F1": 1.75, "F2": 3.5}
}

st.set_page_config(page_title="Dimensionamento de Estacas", page_icon="🏗️", layout="wide")
st.title("🏗️ Dimensionamento e Integração Solo-Estrutura de Estacas")
st.caption("Cálculo de Molas, Capacidade de Carga (Aoki-Velloso) e Esforços Internos (Winkler)")

# -----------------------------------------------------------------------------
# SIDEBAR - PARÂMETROS
# -----------------------------------------------------------------------------
st.sidebar.header("📋 Geometria da Fundação")
tipo_fundacao = st.sidebar.selectbox("Tipo de Fundação", ["Profunda (Estaca)", "Rasa (Sapata/Radier)"])

if tipo_fundacao == "Profunda (Estaca)":
    metodo_construtivo = st.sidebar.radio("Método Construtivo:", list(FATORES_CONSTRUTIVOS.keys()))
else:
    metodo_construtivo = "Cravada (Pré-moldada, Metálica)" # Default for safe logic

secao = st.sidebar.selectbox("Geometria da Seção", ["Circular", "Quadrada"])
B = st.sidebar.number_input("Largura/Diâmetro B (m)", min_value=0.1, value=0.4, step=0.05)
cota_assentamento = st.sidebar.number_input("Cota de Arrasamento (m)", min_value=0.0, value=1.0, step=0.5)
comprimento_estaca = st.sidebar.number_input("Comprimento da Estaca (m)", min_value=1.0, value=10.0, step=0.5) if tipo_fundacao == "Profunda (Estaca)" else 0.0
nu = st.sidebar.slider("Coeficiente de Poisson do Solo (ν)", min_value=0.1, max_value=0.5, value=0.35, step=0.01)

st.sidebar.markdown("---")
st.sidebar.header("⚖️ Cargas e Material (ELU)")
fck = st.sidebar.number_input("Resistência do Concreto (fck) em MPa", min_value=15.0, value=25.0, step=5.0)
carga_V = st.sidebar.number_input("Carga Vertical Atuante (kN)", min_value=0.0, value=500.0, step=50.0)
carga_H = st.sidebar.number_input("Força Horizontal de Topo (kN)", min_value=0.0, value=20.0, step=5.0)
carga_M = st.sidebar.number_input("Momento de Topo (kN.m)", min_value=0.0, value=0.0, step=5.0)

# -----------------------------------------------------------------------------
# TABELA DE SONDAGEM SPT
# -----------------------------------------------------------------------------
col_esq, col_dir = st.columns([1.2, 1])

with col_esq:
    st.subheader("📑 Boletim de Sondagem SPT")
    profundidades = list(range(1, 16))
    solos_modelo = ["Argila siltosa", "Argila siltosa", "Argila arenosa", "Silte argiloso", "Silte",
                    "Areia argilosa", "Areia argilosa", "Areia siltosa", "Areia siltosa", "Areia",
                    "Areia", "Areia", "Areia", "Areia", "Areia"]

    df_spt_input = pd.DataFrame({
        "Profundidade (m)": profundidades,
        "N_SPT": [min(i * 3 + 2, 50) for i in profundidades],
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
# CÁLCULOS DINÂMICOS (MOLAS E AOKI-VELLOSO)
# -----------------------------------------------------------------------------
df_spt["N_corr"] = df_spt["N_SPT"].apply(lambda x: min(x, 50))
df_spt["N_Aoki"] = df_spt["N_SPT"].apply(lambda x: min(x, 40)) # Limite usual de ponta para Aoki

# Propriedades da Seção Estrutural
Area_c = (np.pi * B**2) / 4 if secao == "Circular" else B**2
Inercia_c = (np.pi * B**4) / 64 if secao == "Circular" else (B**4) / 12
Perimetro = np.pi * B if secao == "Circular" else 4 * B
E_c = 5600 * np.sqrt(fck) * 1000 # E_ci em kPa (kN/m²)

# Geotecnia metro a metro
def processar_solo(row):
    solo = PARAMETROS_SOLO.get(row["Tipo de Solo"], PARAMETROS_SOLO["Silte"])
    n = row["N_corr"]
    
    # Molas
    es = solo["alpha_k"] * n
    k1 = 1200 * n
    kv = k1 * (0.3 / B) if solo["comportamento"] == "coesivo" else k1 * ((B + 0.3) / (2 * B)) ** 2
    kh = kv * nu
    
    # Aoki-Velloso
    qs = (solo["aoki_alpha"] * solo["aoki_K"] * n) / FATORES_CONSTRUTIVOS[metodo_construtivo]["F2"]
    qp = (solo["aoki_K"] * row["N_Aoki"]) / FATORES_CONSTRUTIVOS[metodo_construtivo]["F1"]
    
    return pd.Series([es, kv, kh, qs, qp])

df_spt[["Es (kPa)", "kv (kN/m³)", "kh (kN/m³)", "qs_Aoki (kPa)", "qp_Aoki (kPa)"]] = df_spt.apply(processar_solo, axis=1)

# Filtro do Fuste
cota_fim = cota_assentamento + comprimento_estaca
df_inf = df_spt[(df_spt["Profundidade (m)"] >= cota_assentamento) & (df_spt["Profundidade (m)"] <= cota_fim)]
if df_inf.empty: df_inf = df_spt.head(1)

# -----------------------------------------------------------------------------
# CÁLCULOS GLOBAIS E ESTRUTURAIS
# -----------------------------------------------------------------------------
# Capacidade Geotécnica
carga_atrito_qs = df_inf["qs_Aoki (kPa)"].sum() * 1.0 * Perimetro # qs * espessura_camada(1m) * Perimetro
carga_ponta_qp = df_inf.iloc[-1]["qp_Aoki (kPa)"] * Area_c
Q_ult = carga_atrito_qs + carga_ponta_qp
Q_adm = Q_ult / 2.0 # Fator de segurança global = 2.0

# Capacidade Estrutural (Carga Axial Simples)
N_d_max = Area_c * ((0.85 * fck * 1000) / 1.4)

# Integração Solo-Estrutura (Winkler / Matlock & Reese Analítico)
kh_global = df_inf["kh (kN/m³)"].mean()
K_linha = kh_global * B # Mola de linha em kN/m²
lamb = (K_linha / (4 * E_c * Inercia_c)) ** 0.25

# Vetor de profundidade local da estaca (z = 0 no topo da estaca)
z_vals = np.linspace(0, comprimento_estaca, 100)

# Solução exata da equação diferencial de Winkler para estacas longas
y_disp = (np.exp(-lamb * z_vals) / (2 * E_c * Inercia_c * lamb**3)) * (carga_H * np.cos(lamb * z_vals) + lamb * carga_M * (np.cos(lamb * z_vals) + np.sin(lamb * z_vals)))
m_flet = (np.exp(-lamb * z_vals) / lamb) * (carga_H * np.sin(lamb * z_vals) + lamb * carga_M * (np.cos(lamb * z_vals) - np.sin(lamb * z_vals)))

momento_max = np.max(np.abs(m_flet))
deslocamento_max_mm = np.max(np.abs(y_disp)) * 1000

# -----------------------------------------------------------------------------
# PAINEL DE RESULTADOS (COLUNA DIREITA)
# -----------------------------------------------------------------------------
with col_dir:
    st.subheader("📊 Relatório de Capacidade")
    
    st.markdown("**1. Capacidade Vertical (Aoki-Velloso)**")
    c1, c2, c3 = st.columns(3)
    c1.metric("Atrito Lateral ($Q_s$)", f"{carga_atrito_qs:,.0f} kN")
    c2.metric("Ponta ($Q_p$)", f"{carga_ponta_qp:,.0f} kN")
    c3.metric("Carga Adm. ($Q_{adm}$)", f"{Q_adm:,.0f} kN")
    
    status_geo = "✅ OK" if carga_V <= Q_adm else "❌ FALHA"
    st.info(f"**Verificação Geotécnica:** Carga Atuante ({carga_V} kN) vs Resistência ({Q_adm:,.0f} kN) ➔ {status_geo}")

    st.markdown("**2. Capacidade Estrutural do Concreto**")
    status_est = "✅ OK" if carga_V <= N_d_max else "❌ FALHA"
    st.info(f"**Verificação Axial:** Compressão Máx. Projeto = {N_d_max:,.0f} kN ➔ {status_est}")

    st.markdown("**3. Integração Solo-Estrutura (Matlock/Winkler)**")
    m1, m2 = st.columns(2)
    m1.metric("Momento Máximo Fuste", f"{momento_max:.2f} kN.m")
    m2.metric("Deslocamento Topo", f"{deslocamento_max_mm:.2f} mm")

# -----------------------------------------------------------------------------
# GRÁFICOS DE ESFORÇOS (MOMENTO E DESLOCAMENTO)
# -----------------------------------------------------------------------------
if tipo_fundacao == "Profunda (Estaca)":
    st.markdown("---")
    st.subheader("📈 Diagramas de Esforços Internos e Deformação")
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    
    # Gráfico de Momento Fletor
    ax1.plot(m_flet, z_vals, color="red", linewidth=2, label="Momento Fletor")
    ax1.fill_betweenx(z_vals, 0, m_flet, color="red", alpha=0.2)
    ax1.invert_yaxis()
    ax1.set_xlabel("Momento Fletor (kN.m)")
    ax1.set_ylabel("Profundidade na Estaca (z em metros)")
    ax1.set_title("Diagrama de Momento Fletor - $M(z)$")
    ax1.grid(True, linestyle="--", alpha=0.6)
    
    # Gráfico de Deslocamento Horizontal
    ax2.plot(y_disp * 1000, z_vals, color="blue", linewidth=2, label="Deslocamento Horizontal")
    ax2.fill_betweenx(z_vals, 0, y_disp * 1000, color="blue", alpha=0.2)
    ax2.invert_yaxis()
    ax2.set_xlabel("Deslocamento $y$ (mm)")
    ax2.set_ylabel("Profundidade na Estaca (z em metros)")
    ax2.set_title("Elástica da Estaca - $y(z)$")
    ax2.grid(True, linestyle="--", alpha=0.6)
    
    st.pyplot(fig)
