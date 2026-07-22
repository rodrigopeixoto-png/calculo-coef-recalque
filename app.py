import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# -----------------------------------------------------------------------------
# DICIONÁRIO GEOTÉCNICO DE SOLOS
# -----------------------------------------------------------------------------
PARAMETROS_SOLO = {
    "Argila":           {"alpha": 1500, "comportamento": "coesivo"},
    "Argila siltosa":   {"alpha": 1750, "comportamento": "coesivo"},
    "Argila arenosa":   {"alpha": 2000, "comportamento": "coesivo"},
    "Silte":            {"alpha": 2000, "comportamento": "intermediario"},
    "Silte argiloso":   {"alpha": 2000, "comportamento": "coesivo"},
    "Silte arenoso":    {"alpha": 2500, "comportamento": "granular"},
    "Areia argilosa":   {"alpha": 2500, "comportamento": "granular"},
    "Areia siltosa":    {"alpha": 2800, "comportamento": "granular"},
    "Areia":            {"alpha": 3000, "comportamento": "granular"}
}

OPCOES_SOLO = list(PARAMETROS_SOLO.keys())

# Configuração da página
st.set_page_config(page_title="Calculadora Geotécnica", page_icon="🏗️", layout="wide")
st.title("🏗️ Coeficientes de Recalque (k_v e k_h)")
st.caption("Com refinamento de Meyerhof para Módulo de Elasticidade em Fundações Profundas")

# -----------------------------------------------------------------------------
# SIDEBAR - PARÂMETROS DA FUNDAÇÃO
# -----------------------------------------------------------------------------
st.sidebar.header("📋 Parâmetros da Fundação")
tipo_fundacao = st.sidebar.selectbox("Tipo de Fundação", ["Rasa (Sapata/Radier)", "Profunda (Estaca)"])

# Escolha do método construtivo (Aparece apenas se for Estaca)
if tipo_fundacao == "Profunda (Estaca)":
    metodo_construtivo = st.sidebar.radio(
        "Método Construtivo (Influencia rigidez de ponta):", 
        ["Escavada (Hélice, Trado, Tubulão)", "Cravada (Pré-moldada, Metálica)"]
    )
else:
    metodo_construtivo = None

secao = st.sidebar.selectbox("Geometria da Seção", ["Quadrada", "Circular", "Retangular"])

col_b, col_l = st.sidebar.columns(2)
B = col_b.number_input("Largura/Diâmetro B (m)", min_value=0.1, value=0.8, step=0.05)
L = col_l.number_input("Comprimento L (m)", min_value=0.1, value=0.8, step=0.05) if secao == "Retangular" else B

cota_assentamento = st.sidebar.number_input("Cota de Assentamento/Arrasamento (m)", min_value=0.0, value=1.5, step=0.5)
comprimento_estaca = st.sidebar.number_input("Comprimento da Estaca (m)", min_value=1.0, value=10.0, step=0.5) if tipo_fundacao == "Profunda (Estaca)" else 0.0
nu = st.sidebar.slider("Coeficiente de Poisson (ν)", min_value=0.1, max_value=0.5, value=0.35, step=0.01)

# -----------------------------------------------------------------------------
# TABELA DE SONDAGEM SPT
# -----------------------------------------------------------------------------
col_esq, col_dir = st.columns([1, 1])

with col_esq:
    st.subheader("📑 Boletim de Sondagem SPT")
    profundidades = list(range(1, 16))
    
    solos_modelo = [
        "Argila", "Argila siltosa", "Argila arenosa", "Silte argiloso", "Silte",
        "Silte arenoso", "Areia argilosa", "Areia argilosa", "Areia siltosa", "Areia siltosa",
        "Areia", "Areia", "Areia", "Areia", "Areia"
    ]

    df_spt_input = pd.DataFrame({
        "Profundidade (m)": profundidades,
        "N_SPT": [min(i * 2 + 3, 40) for i in profundidades],
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
# CÁLCULOS DINÂMICOS (POR CAMADA)
# -----------------------------------------------------------------------------
df_spt["N_corr"] = df_spt["N_SPT"].apply(lambda x: min(x, 50))

def calc_es(row):
    solo_info = PARAMETROS_SOLO.get(row["Tipo de Solo"], PARAMETROS_SOLO["Silte"])
    return solo_info["alpha"] * row["N_corr"]

df_spt["Es (kPa)"] = df_spt.apply(calc_es, axis=1)

def calc_kv(row):
    n = row["N_corr"]
    k1 = 1200 * n
    solo_info = PARAMETROS_SOLO.get(row["Tipo de Solo"], PARAMETROS_SOLO["Silte"])
    
    if solo_info["comportamento"] == "coesivo":
        return k1 * (0.3 / B)
    else:
        return k1 * ((B + 0.3) / (2 * B)) ** 2

df_spt["k_v Camada (kN/m³)"] = df_spt.apply(calc_kv, axis=1)
df_spt["k_h Camada (kN/m³)"] = df_spt["k_v Camada (kN/m³)"] * nu

# -----------------------------------------------------------------------------
# FILTROS E LÓGICA DE APLICAÇÃO (ZONA DE INFLUÊNCIA / MEYERHOF)
# -----------------------------------------------------------------------------
if tipo_fundacao == "Rasa (Sapata/Radier)":
    cota_fim = cota_assentamento + (1.5 * B)
    df_inf = df_spt[(df_spt["Profundidade (m)"] >= cota_assentamento) & (df_spt["Profundidade (m)"] <= cota_fim)]
    if df_inf.empty: df_inf = df_spt.head(1)
    nspt_medio = df_inf["N_corr"].mean()
    kv_global = df_inf["k_v Camada (kN/m³)"].mean()
    kh_global = kv_global * nu
    
else:
    cota_fim = cota_assentamento + comprimento_estaca
    df_inf = df_spt[(df_spt["Profundidade (m)"] >= cota_assentamento) & (df_spt["Profundidade (m)"] <= cota_fim)]
    if df_inf.empty: df_inf = df_spt.head(1)
    
    nspt_medio = df_inf["N_corr"].mean()
    kh_global = df_inf["k_h Camada (kN/m³)"].mean()
    
    # Aplicação do Refinamento de Meyerhof para o E_s de Ponta
    n_ponta = df_inf.iloc[-1]["N_corr"]
    
    if "Escavada" in metodo_construtivo:
        # Menor rigidez devido ao alívio de tensões na escavação (aprox. 1000 * N)
        es_ponta = 1000 * n_ponta  
    else:
        # Maior rigidez devido à compactação lateral na cravação (aprox. 3000 * N)
        es_ponta = 3000 * n_ponta  
        
    # Cálculo elástico da mola vertical na ponta da estaca (Vesić)
    kv_global = es_ponta / (B * (1 - nu**2) * 0.85)

# -----------------------------------------------------------------------------
# PAINEL DE RESULTADOS GLOBAIS
# -----------------------------------------------------------------------------
with col_dir:
    st.subheader("📊 Resultados Globais do Projeto")
    c1, c2 = st.columns(2)
    c1.metric("N_SPT Médio no Trecho", f"{nspt_medio:.1f}")
    c2.metric("Mola de Linha k_h (p/ Barras)", f"{kh_global * B:.2f} kN/m²")

    st.markdown("---")
    m1, m2 = st.columns(2)
    m1.metric("k_v Global (Base/Ponta)", f"{kv_global:,.2f} kN/m³")
    m2.metric("k_h Global (Lateral)", f"{kh_global:,.2f} kN/m³")

    st.markdown("---")
    st.write("### 🔄 Conversão para Eberick (Valores Globais)")
    e1, e2 = st.columns(2)
    e1.metric("k_v Global (Eberick)", f"{kv_global / 10000:.4f} kgf/cm³")
    e2.metric("k_h Global (Eberick)", f"{kh_global / 10000:.4f} kgf/cm³")

# -----------------------------------------------------------------------------
# TABELA DE DISCRETIZAÇÃO METRO A METRO (EXPORTAÇÃO)
# -----------------------------------------------------------------------------
st.markdown("---")
st.subheader("📋 Discretização Metro a Metro (Zona de Influência / Fuste)")
st.caption("Valores filtrados apenas para o trecho de atuação da fundação. Utilize esta tabela para lançar as camadas de solo no Eberick.")

# Preparando DataFrame de Saída
df_export = df_inf[["Profundidade (m)", "Tipo de Solo", "N_corr", "Es (kPa)", "k_h Camada (kN/m³)", "k_v Camada (kN/m³)"]].copy()
df_export["k_h Eberick (kgf/cm³)"] = df_export["k_h Camada (kN/m³)"] / 10000
df_export["k_v Eberick (kgf/cm³)"] = df_export["k_v Camada (kN/m³)"] / 10000

# Exibindo DataFrame Formatado
st.dataframe(
    df_export.style.format({
        "N_corr": "{:.0f}",
        "Es (kPa)": "{:,.2f}",
        "k_h Camada (kN/m³)": "{:,.2f}",
        "k_v Camada (kN/m³)": "{:,.2f}",
        "k_h Eberick (kgf/cm³)": "{:.4f}",
        "k_v Eberick (kgf/cm³)": "{:.4f}"
    }),
    use_container_width=True,
    hide_index=True
)

# -----------------------------------------------------------------------------
# GRÁFICO
# -----------------------------------------------------------------------------
st.markdown("---")
st.subheader("📈 Perfil Geotécnico")
fig, ax = plt.subplots(figsize=(10, 3.5))
ax.plot(df_spt["k_h Camada (kN/m³)"], df_spt["Profundidade (m)"], label="k_h Horizontal", marker="o", color="#1f77b4")
ax.plot(df_spt["k_v Camada (kN/m³)"], df_spt["Profundidade (m)"], label="k_v Vertical", marker="s", color="#ff7f0e")
ax.axhspan(cota_assentamento, cota_fim, color='yellow', alpha=0.2, label="Trecho de Influência da Fundação")
ax.invert_yaxis()
ax.set_xlabel("Módulo de Recalque (kN/m³)")
ax.set_ylabel("Profundidade (m)")
ax.grid(True, linestyle="--", alpha=0.6)
ax.legend()
st.pyplot(fig)
