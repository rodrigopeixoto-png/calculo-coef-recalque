import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# -----------------------------------------------------------------------------
# DICIONÁRIO GEOTÉCNICO DE SOLOS (Com parâmetros de Aoki-Velloso)
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

FATORES_CONSTRUTIVOS = {
    "Escavada (Hélice, Trado, Tubulão)": {"F1": 3.0, "F2": 6.0},
    "Cravada (Pré-moldada, Metálica)": {"F1": 1.75, "F2": 3.5}
}

st.set_page_config(page_title="Dimensionamento de Estacas", page_icon="🏗️", layout="wide")
st.title("🏗️ Dimensionamento e Integração Solo-Estrutura")
st.caption("Cálculo de Molas (k_v, k_h), Capacidade de Carga (Aoki-Velloso) e Verificação Estrutural")

# -----------------------------------------------------------------------------
# SIDEBAR - PARÂMETROS
# -----------------------------------------------------------------------------
st.sidebar.header("📋 Geometria da Fundação")
tipo_fundacao = st.sidebar.selectbox("Tipo de Fundação", ["Profunda (Estaca)", "Rasa (Sapata/Radier)"])

if tipo_fundacao == "Profunda (Estaca)":
    metodo_construtivo = st.sidebar.radio("Método Construtivo:", list(FATORES_CONSTRUTIVOS.keys()))
else:
    metodo_construtivo = "Cravada (Pré-moldada, Metálica)"

secao = st.sidebar.selectbox("Geometria da Seção", ["Circular", "Quadrada"])
B = st.sidebar.number_input("Largura/Diâmetro B (m)", min_value=0.1, value=0.4, step=0.05)
cota_assentamento = st.sidebar.number_input("Cota de Arrasamento (m)", min_value=0.0, value=1.0, step=0.5)
comprimento_estaca = st.sidebar.number_input("Comprimento da Estaca (m)", min_value=1.0, value=10.0, step=0.5) if tipo_fundacao == "Profunda (Estaca)" else 0.0
nu = st.sidebar.slider("Coeficiente de Poisson (ν)", min_value=0.1, max_value=0.5, value=0.35, step=0.01)

st.sidebar.markdown("---")
st.sidebar.header("⚖️ Cargas e Material")
fck = st.sidebar.number_input("Resistência do Concreto (fck) em MPa", min_value=15.0, value=25.0, step=5.0)
taxa_armadura = st.sidebar.number_input("Taxa de Armadura Longitudinal (%)", min_value=0.1, value=0.5, step=0.1)
fyk = st.sidebar.number_input("Resistência do Aço (fyk) em MPa", min_value=250.0, value=500.0, step=50.0)

st.sidebar.markdown("---")
st.sidebar.header("🔽 Esforços Atuantes (Topo)")
carga_V = st.sidebar.number_input("Carga Vertical (kN)", min_value=0.0, value=500.0, step=50.0)
carga_H = st.sidebar.number_input("Força Horizontal (kN)", min_value=0.0, value=20.0, step=5.0)
carga_M = st.sidebar.number_input("Momento Fletor (kN.m)", min_value=0.0, value=0.0, step=5.0)

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
df_spt["N_Aoki"] = df_spt["N_SPT"].apply(lambda x: min(x, 40))

Area_c = (np.pi * B**2) / 4 if secao == "Circular" else B**2
Inercia_c = (np.pi * B**4) / 64 if secao == "Circular" else (B**4) / 12
Perimetro = np.pi * B if secao == "Circular" else 4 * B
E_c = 5600 * np.sqrt(fck) * 1000 # E_ci em kPa

def processar_solo(row):
    solo = PARAMETROS_SOLO.get(row["Tipo de Solo"], PARAMETROS_SOLO["Silte"])
    n = row["N_corr"]
    
    # Molas (Terzaghi/Bowles)
    es = solo["alpha_k"] * n
    k1 = 1200 * n
    kv = k1 * (0.3 / B) if solo["comportamento"] == "coesivo" else k1 * ((B + 0.3) / (2 * B)) ** 2
    kh = kv * nu
    
    # Capacidade (Aoki-Velloso)
    qs = (solo["aoki_alpha"] * solo["aoki_K"] * n) / FATORES_CONSTRUTIVOS[metodo_construtivo]["F2"]
    qp = (solo["aoki_K"] * row["N_Aoki"]) / FATORES_CONSTRUTIVOS[metodo_construtivo]["F1"]
    
    return pd.Series([es, kv, kh, qs, qp])

df_spt[["Es (kPa)", "kv (kN/m³)", "kh (kN/m³)", "qs_Aoki (kPa)", "qp_Aoki (kPa)"]] = df_spt.apply(processar_solo, axis=1)

# Filtro do Trecho Atuante
cota_fim = cota_assentamento + (comprimento_estaca if tipo_fundacao == "Profunda (Estaca)" else 1.5 * B)
df_inf = df_spt[(df_spt["Profundidade (m)"] >= cota_assentamento) & (df_spt["Profundidade (m)"] <= cota_fim)]
if df_inf.empty: df_inf = df_spt.head(1)

# -----------------------------------------------------------------------------
# CÁLCULOS GLOBAIS
# -----------------------------------------------------------------------------
# 1. Molas Globais (k_v e k_h)
kh_global = df_inf["kh (kN/m³)"].mean()

if tipo_fundacao == "Rasa (Sapata/Radier)":
    kv_global = df_inf["kv (kN/m³)"].mean()
else:
    n_ponta = df_inf.iloc[-1]["N_corr"]
    es_ponta = 1000 * n_ponta if "Escavada" in metodo_construtivo else 3000 * n_ponta
    kv_global = es_ponta / (B * (1 - nu**2) * 0.85)

# 2. Capacidade Geotécnica (Vertical)
carga_atrito_qs = df_inf["qs_Aoki (kPa)"].sum() * 1.0 * Perimetro
carga_ponta_qp = df_inf.iloc[-1]["qp_Aoki (kPa)"] * Area_c
Q_ult = carga_atrito_qs + carga_ponta_qp
Q_adm = Q_ult / 2.0

# 3. Resistência Estrutural (Concreto Armado)
N_d_max = Area_c * ((0.85 * fck * 1000) / 1.4) 
fyd = (fyk / 1.15) * 1000
A_s = (taxa_armadura / 100) * Area_c
braco_alavanca = 0.75 * B if secao == "Circular" else 0.80 * B
M_rd = A_s * fyd * braco_alavanca 

# 4. Integração Solo-Estrutura (Winkler)
K_linha = kh_global * B
lamb = (K_linha / (4 * E_c * Inercia_c)) ** 0.25
z_vals = np.linspace(0, comprimento_estaca if tipo_fundacao == "Profunda (Estaca)" else 1, 100)

y_disp = (np.exp(-lamb * z_vals) / (2 * E_c * Inercia_c * lamb**3)) * (carga_H * np.cos(lamb * z_vals) + lamb * carga_M * (np.cos(lamb * z_vals) + np.sin(lamb * z_vals)))
m_flet = (np.exp(-lamb * z_vals) / lamb) * (carga_H * np.sin(lamb * z_vals) + lamb * carga_M * (np.cos(lamb * z_vals) - np.sin(lamb * z_vals)))
momento_max_atuante = np.max(np.abs(m_flet))
deslocamento_max_mm = np.max(np.abs(y_disp)) * 1000

m_flet_unit = (np.exp(-lamb * z_vals) / lamb) * (1.0 * np.sin(lamb * z_vals))
momento_max_unit = np.max(np.abs(m_flet_unit))
H_rd = M_rd / momento_max_unit if momento_max_unit > 0 else 0

# -----------------------------------------------------------------------------
# PAINEL DE RESULTADOS (COLUNA DIREITA)
# -----------------------------------------------------------------------------
with col_dir:
    st.subheader("📊 Relatório Completo")
    
    st.markdown("**1. Coeficientes de Recalque (Molas Globais)**")
    m1, m2 = st.columns(2)
    m1.metric("k_v (Vertical)", f"{kv_global:,.2f} kN/m³")
    m2.metric("k_h (Horizontal)", f"{kh_global:,.2f} kN/m³")
    
    e1, e2 = st.columns(2)
    e1.caption(f"**Eberick k_v:** {kv_global / 10000:.4f} kgf/cm³")
    e2.caption(f"**Eberick k_h:** {kh_global / 10000:.4f} kgf/cm³")
    st.markdown("---")
    
    st.markdown("**2. Capacidade Vertical Geotécnica (Aoki)**")
    c1, c2 = st.columns(2)
    c1.metric("Carga Adm. (Q_adm)", f"{Q_adm:,.0f} kN")
    c2.metric("Carga Atuante", f"{carga_V:,.0f} kN")
    st.info(f"Status Geotécnico: {'✅ OK' if carga_V <= Q_adm else '❌ FALHA'}")
    st.markdown("---")

    st.markdown("**3. Resistência Estrutural à Flexão**")
    f1, f2 = st.columns(2)
    f1.metric("Momento Resistente (M_Rd)", f"{M_rd:.1f} kN.m")
    f2.metric("Momento Máximo Atuante", f"{momento_max_atuante:.1f} kN.m")
    
    h1, h2 = st.columns(2)
    h1.metric("Força Horizontal Res.", f"{H_rd:.1f} kN")
    h2.metric("Deslocamento de Topo", f"{deslocamento_max_mm:.2f} mm")
    st.info(f"Status Estrutural: {'✅ OK' if momento_max_atuante <= M_rd else '❌ FALHA'}")

# -----------------------------------------------------------------------------
# TABELA DE DISCRETIZAÇÃO
# -----------------------------------------------------------------------------
st.markdown("---")
st.subheader("📋 Discretização Metro a Metro (Trecho de Atuação)")
st.caption("Valores filtrados das Molas (k_v, k_h) e Capacidade (Atrito Lateral q_s e Ponta q_p)")

df_export = df_inf[["Profundidade (m)", "Tipo de Solo", "N_corr", "kv (kN/m³)", "kh (kN/m³)", "qs_Aoki (kPa)", "qp_Aoki (kPa)"]].copy()
st.dataframe(
    df_export.style.format({
        "kv (kN/m³)": "{:,.2f}",
        "kh (kN/m³)": "{:,.2f}",
        "qs_Aoki (kPa)": "{:.2f}",
        "qp_Aoki (kPa)": "{:.2f}"
    }),
    use_container_width=True,
    hide_index=True
)

# -----------------------------------------------------------------------------
# GRÁFICOS (PERFIL DE MOLAS E ESFORÇOS)
# -----------------------------------------------------------------------------
st.markdown("---")
st.subheader("📈 Diagramas Geotécnicos e Estruturais")

if tipo_fundacao == "Profunda (Estaca)":
    fig, (ax0, ax1, ax2) = plt.subplots(1, 3, figsize=(18, 5))
    
    # 1. Perfil de Molas Geotécnicas
    ax0.plot(df_spt["kh (kN/m³)"], df_spt["Profundidade (m)"], label="k_h Horizontal", marker="o", color="#1f77b4")
    ax0.plot(df_spt["kv (kN/m³)"], df_spt["Profundidade (m)"], label="k_v Vertical", marker="s", color="#ff7f0e")
    ax0.axhspan(cota_assentamento, cota_fim, color='yellow', alpha=0.2, label="Trecho da Estaca")
    ax0.invert_yaxis()
    ax0.set_xlabel("Módulo de Recalque (kN/m³)")
    ax0.set_ylabel("Profundidade (m)")
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
else:
    # Se for Sapata, exibe apenas o gráfico de Molas
    fig, ax0 = plt.subplots(figsize=(10, 5))
    ax0.plot(df_spt["kh (kN/m³)"], df_spt["Profundidade (m)"], label="k_h Horizontal", marker="o", color="#1f77b4")
    ax0.plot(df_spt["kv (kN/m³)"], df_spt["Profundidade (m)"], label="k_v Vertical", marker="s", color="#ff7f0e")
    ax0.axhspan(cota_assentamento, cota_fim, color='yellow', alpha=0.2, label="Influência da Sapata")
    ax0.invert_yaxis()
    ax0.set_xlabel("Módulo de Recalque (kN/m³)")
    ax0.set_ylabel("Profundidade (m)")
    ax0.set_title("Perfil Geotécnico de Molas")
    ax0.grid(True, linestyle="--", alpha=0.6)
    ax0.legend()
    st.pyplot(fig)
