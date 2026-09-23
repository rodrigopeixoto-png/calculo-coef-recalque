import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="Gestor BIM e Orçamento - Fundações", page_icon="🏢", layout="wide")

st.title("🏢 Gestor BIM & Orçamento de Fundações")
st.caption("Módulo de Importação de Cargas (Padrão Eberick / TQS)")

# -----------------------------------------------------------------------------
# DADOS DE EXEMPLO BASEADOS NA IMAGEM FORNECIDA PELO USUÁRIO
# -----------------------------------------------------------------------------
dados_exemplo = [
    {"Pilar": "P1", "X_cm": -4323.69, "Y_cm": 2356.90, "Carga_Max_tf": 15.4, "ne": 2, "Estaca": "HCØ50cm"},
    {"Pilar": "P2", "X_cm": -363.69,  "Y_cm": 2356.90, "Carga_Max_tf": 14.0, "ne": 2, "Estaca": "HCØ50cm"},
    {"Pilar": "P5", "X_cm": -4192.19, "Y_cm": 2245.60, "Carga_Max_tf": 52.4, "ne": 2, "Estaca": "HCØ50cm"},
    {"Pilar": "P6", "X_cm": -3604.39, "Y_cm": 2245.60, "Carga_Max_tf": 97.8, "ne": 3, "Estaca": "HCØ50cm"},
    {"Pilar": "P7", "X_cm": -3065.77, "Y_cm": 2245.60, "Carga_Max_tf": 53.3, "ne": 2, "Estaca": "HCØ50cm"},
    {"Pilar": "P8", "X_cm": -2502.39, "Y_cm": 2245.60, "Carga_Max_tf": 39.4, "ne": 1, "Estaca": "HCØ50cm"},
    {"Pilar": "P9", "X_cm": -2043.98, "Y_cm": 2245.60, "Carga_Max_tf": 116.8, "ne": 4, "Estaca": "HCØ50cm"},
    {"Pilar": "P12", "X_cm": -4192.19, "Y_cm": 1551.36, "Carga_Max_tf": 63.2, "ne": 2, "Estaca": "HCØ50cm"},
    {"Pilar": "P13", "X_cm": -3604.39, "Y_cm": 1551.42, "Carga_Max_tf": 121.6, "ne": 3, "Estaca": "HCØ50cm"},
]

# -----------------------------------------------------------------------------
# BARRA LATERAL (IMPORTAÇÃO E PARÂMETROS)
# -----------------------------------------------------------------------------
st.sidebar.header("📥 Importação de Tabela")
st.sidebar.info("Exporte a Tabela de Cargas do Eberick para Excel (.xlsx) ou CSV e carregue aqui.")
arquivo_upload = st.sidebar.file_uploader("Upload da Tabela de Cargas", type=["xlsx", "csv"])

usar_exemplo = st.sidebar.button("Carregar Tabela de Exemplo (Da Imagem)", use_container_width=True)

if 'df_projeto' not in st.session_state:
    st.session_state.df_projeto = None

if usar_exemplo:
    st.session_state.df_projeto = pd.DataFrame(dados_exemplo)

if arquivo_upload is not None:
    if arquivo_upload.name.endswith('.csv'):
        st.session_state.df_projeto = pd.read_csv(arquivo_upload)
    else:
        st.session_state.df_projeto = pd.read_excel(arquivo_upload)

st.sidebar.markdown("---")
st.sidebar.header("⚙️ Parâmetros para Orçamento")
st.sidebar.markdown("*(Estes dados virão automaticamente do seu outro módulo Geotécnico futuramente)*")
profundidade_media = st.sidebar.number_input("Profundidade Média das Estacas (m)", value=12.0, step=0.5)
taxa_aco_estimada = st.sidebar.number_input("Taxa de Aço Média (kg/m³ de concreto)", value=85.0, step=5.0)

# -----------------------------------------------------------------------------
# ÁREA PRINCIPAL DO SOFTWARE
# -----------------------------------------------------------------------------
if st.session_state.df_projeto is not None:
    df = st.session_state.df_projeto.copy()
    
    # Padronização de colunas (Convertendo cm para metros para o desenho BIM)
    if "X_cm" in df.columns:
        df["X_m"] = df["X_cm"] / 100.0
        df["Y_m"] = df["Y_cm"] / 100.0
    
    # Extrair diâmetro da estaca do texto "HCØ50cm"
    def extrair_diametro(texto):
        import re
        match = re.search(r'\d+', str(texto))
        return float(match.group(0))/100 if match else 0.50 # Padrão 50cm (0.5m)
    
    if "Estaca" in df.columns:
        df["Diametro_m"] = df["Estaca"].apply(extrair_diametro)
    else:
        df["Diametro_m"] = 0.50

    # -------------------------------------------------------------------------
    # 1. ORÇAMENTO GERAL E QUANTITATIVOS (A MÁGICA)
    # -------------------------------------------------------------------------
    total_blocos = len(df)
    total_estacas = df["ne"].sum() if "ne" in df.columns else total_blocos
    
    # Cálculo de Volume de Concreto: (pi * D^2 / 4) * Profundidade * qtd_estacas
    df["Vol_Concreto_m3"] = (np.pi * (df["Diametro_m"]**2) / 4) * profundidade_media * df["ne"]
    volume_concreto_total = df["Vol_Concreto_m3"].sum()
    peso_aco_total = volume_concreto_total * taxa_aco_estimada

    st.subheader("💰 Resumo de Quantitativos (Orçamento Executivo)")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pilares / Blocos", f"{total_blocos} un")
    c2.metric("Total de Estacas", f"{total_estacas} un", f"Total: {total_estacas * profundidade_media:.1f} m perfurados")
    c3.metric("Volume de Concreto", f"{volume_concreto_total:.1f} m³")
    c4.metric("Aço Estimado (Total)", f"{peso_aco_total:,.1f} kg")

    st.markdown("---")

    # -------------------------------------------------------------------------
    # 2. PLANTA DE LOCAÇÃO INTERATIVA (VISÃO BIM 2D)
    # -------------------------------------------------------------------------
    st.subheader("🗺️ Planta de Locação e Mapa de Cargas")
    st.info("Passe o rato sobre os blocos para ver as informações detalhadas lidas da tabela.")
    
    # Criar um gráfico de dispersão (Scatter Plot) interativo reproduzindo o CAD
    fig = px.scatter(
        df, 
        x="X_m", 
        y="Y_m", 
        text="Pilar",
        size="Carga_Max_tf", # Tamanho da bolha depende da carga
        color="ne",          # Cor muda de acordo com o número de estacas do bloco
        hover_data=["Carga_Max_tf", "ne", "Estaca"],
        labels={"X_m": "Coordenada X (m)", "Y_m": "Coordenada Y (m)", "ne": "Nº de Estacas"},
        color_continuous_scale=px.colors.sequential.Viridis
    )
    
    fig.update_traces(textposition='top center', marker=dict(line=dict(width=1, color='DarkSlateGrey')))
    fig.update_layout(
        height=600, 
        plot_bgcolor='rgba(240, 240, 240, 0.8)',
        title_text="Visualização Top-Down do Projeto (Auto-Gerada a partir da Tabela)",
        xaxis=dict(scaleanchor="y", scaleratio=1), # Força a escala 1:1 para não distorcer a planta
    )
    st.plotly_chart(fig, use_container_width=True)

    # -------------------------------------------------------------------------
    # 3. TABELA DE DADOS DE ENTRADA
    # -------------------------------------------------------------------------
    with st.expander("👁️ Ver Tabela Lida do Eberick", expanded=False):
        st.dataframe(df, use_container_width=True)
        
    # -------------------------------------------------------------------------
    # 4. BOTÃO PARA O FUTURO IFC
    # -------------------------------------------------------------------------
    st.markdown("---")
    st.subheader("🏗️ Integração BIM")
    if st.button("🚀 Exportar Modelo 3D para IFC (Em Desenvolvimento)", type="primary", use_container_width=True):
        st.success("No futuro, este botão chamará a biblioteca `IfcOpenShell` e criará as estacas virtuais no espaço 3D usando o Raio, o X, o Y e a Profundidade que lemos acima!")

else:
    st.info("👈 Por favor, faça o upload de uma Tabela de Cargas na barra lateral ou clique em 'Carregar Tabela de Exemplo'.")
