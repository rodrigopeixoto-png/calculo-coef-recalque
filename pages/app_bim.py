import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import io
import re

# Importação da biblioteca CAD
try:
    import ezdxf
except ImportError:
    st.error("A biblioteca 'ezdxf' não está instalada. Adicione 'ezdxf' ao seu ficheiro requirements.txt!")

st.set_page_config(page_title="Gestor BIM e Orçamento - Fundações", page_icon="🏢", layout="wide")

st.title("🏢 Gestor BIM & Orçamento de Fundações")
st.caption("Importação Inteligente de Cargas via Excel ou Leitura Nativa de CAD (.DXF)")

# -----------------------------------------------------------------------------
# FUNÇÃO: EXTRATOR GEOMÉTRICO DE TABELAS DXF (PADRÃO EBERICK)
# -----------------------------------------------------------------------------
def extrair_tabela_do_dxf(dxf_bytes):
    # Lê o ficheiro DXF diretamente da memória
    text_stream = io.StringIO(dxf_bytes.decode('utf-8', errors='ignore'))
    doc = ezdxf.read(text_stream)
    msp = doc.modelspace()
    
    # 1. Coleta todos os Textos e MTexts
    textos_brutos = []
    for e in msp.query('TEXT MTEXT'):
        texto = e.dxf.text if e.dxftype() == 'TEXT' else e.text
        # Limpa formatações malucas do AutoCAD (ex: \A1; \pxqc;)
        texto_limpo = re.sub(r'\\[A-Za-z0-9~]+;', '', texto).strip()
        if texto_limpo:
            y_coord = e.dxf.insert.y
            x_coord = e.dxf.insert.x
            textos_brutos.append({'Texto': texto_limpo, 'X': x_coord, 'Y': y_coord})
            
    if not textos_brutos:
        return None
        
    df_raw = pd.DataFrame(textos_brutos)
    df_raw = df_raw.sort_values(by='Y', ascending=False) # Ordena de cima para baixo
    
    # 2. Agrupamento (Clustering) por Linhas (Tolerância para alinhamento CAD)
    linhas = []
    linha_atual = []
    y_ref = df_raw.iloc[0]['Y']
    tolerancia_y = 15.0 # Unidades de desenho CAD (ajustável)
    
    for _, row in df_raw.iterrows():
        if abs(row['Y'] - y_ref) <= tolerancia_y:
            linha_atual.append(row)
        else:
            linha_atual.sort(key=lambda item: item['X']) # Ordena da Esquerda para a Direita
            linhas.append([str(item['Texto']) for item in linha_atual])
            linha_atual = [row]
            y_ref = row['Y']
            
    if linha_atual:
        linha_atual.sort(key=lambda item: item['X'])
        linhas.append([str(item['Texto']) for item in linha_atual])
        
    # 3. Montar o DataFrame Bruto
    df_tabela = pd.DataFrame(linhas)
    
    # 4. Caçar o Cabeçalho do Eberick (Nome, X, Y, Carga...)
    header_idx = -1
    for i in range(min(15, len(df_tabela))): # Procura nas primeiras 15 linhas
        linha_str = " ".join([str(val).lower() for val in df_tabela.iloc[i].dropna()])
        if "nome" in linha_str and "x" in linha_str and "y" in linha_str:
            header_idx = i
            break
            
    if header_idx != -1:
        df_tabela.columns = df_tabela.iloc[header_idx]
        df_limpo = df_tabela.iloc[header_idx+1:].copy()
        df_limpo = df_limpo.dropna(how='all')
        
        # Renomear colunas para o padrão do nosso software
        col_mapping = {}
        for col in df_limpo.columns:
            c = str(col).lower()
            if "nome" in c or "pilar" in c: col_mapping[col] = "Pilar"
            elif c == "x" or "x (cm)" in c: col_mapping[col] = "X_cm"
            elif c == "y" or "y (cm)" in c: col_mapping[col] = "Y_cm"
            elif "carga máx" in c or "tf" in c: col_mapping[col] = "Carga_Max_tf"
            elif "ne" in c: col_mapping[col] = "ne"
            elif "estaca" in c: col_mapping[col] = "Estaca"
            
        df_limpo = df_limpo.rename(columns=col_mapping)
        
        # Filtrar apenas as colunas que conseguimos mapear e remover linhas vazias no Pilar
        cols_utea = [c for c in ["Pilar", "X_cm", "Y_cm", "Carga_Max_tf", "ne", "Estaca"] if c in df_limpo.columns]
        df_final = df_limpo[cols_utea].copy()
        
        # Limpar números
        for col in ["X_cm", "Y_cm", "Carga_Max_tf", "ne"]:
            if col in df_final.columns:
                df_final[col] = pd.to_numeric(df_final[col].astype(str).str.replace(',', '.').str.extract(r'([-+]?\d*\.?\d+)')[0], errors='coerce')
        
        df_final = df_final.dropna(subset=['Pilar'])
        return df_final[df_final['Pilar'].astype(str).str.contains(r'[a-zA-Z]')] # Filtra só o que parece pilar (Ex: P1)
    
    return df_tabela # Se não achar o cabeçalho, devolve a tabela bruta para debug

# -----------------------------------------------------------------------------
# BARRA LATERAL (IMPORTAÇÃO E PARÂMETROS)
# -----------------------------------------------------------------------------
st.sidebar.header("📥 Importação da Planta de Cargas")
st.sidebar.info("Faça o upload do CAD (.dxf) exportado do Eberick ou da tabela em Excel.")
arquivo_upload = st.sidebar.file_uploader("Upload do Ficheiro (.dxf, .xlsx, .csv)", type=["dxf", "xlsx", "csv"])

if 'df_projeto' not in st.session_state:
    st.session_state.df_projeto = None

if arquivo_upload is not None:
    ext = arquivo_upload.name.split('.')[-1].lower()
    
    if ext == 'dxf':
        with st.spinner("A escanear o desenho CAD e a reconstruir tabelas..."):
            try:
                df_extraido = extrair_tabela_do_dxf(arquivo_upload.getvalue())
                if df_extraido is not None and "Pilar" in df_extraido.columns:
                    st.session_state.df_projeto = df_extraido
                    st.sidebar.success(f"Tabela CAD lida com sucesso! ({len(df_extraido)} pilares encontrados)")
                else:
                    st.sidebar.warning("Não consegui identificar o cabeçalho padrão do Eberick na tabela do CAD. Mostrando extração bruta na tela.")
                    st.session_state.df_projeto = df_extraido
            except Exception as e:
                st.sidebar.error(f"Erro ao ler o DXF: {e}")
                
    elif ext == 'csv':
        st.session_state.df_projeto = pd.read_csv(arquivo_upload)
        st.sidebar.success("CSV lido com sucesso!")
    else:
        st.session_state.df_projeto = pd.read_excel(arquivo_upload)
        st.sidebar.success("Excel lido com sucesso!")

st.sidebar.markdown("---")
st.sidebar.header("⚙️ Parâmetros para Orçamento")
st.sidebar.markdown("*(Estes dados virão do seu Módulo Geotécnico futuramente)*")
profundidade_media = st.sidebar.number_input("Profundidade Média das Estacas (m)", value=12.0, step=0.5)
taxa_aco_estimada = st.sidebar.number_input("Taxa de Aço Média (kg/m³ de betão)", value=85.0, step=5.0)

# -----------------------------------------------------------------------------
# ÁREA PRINCIPAL DO SOFTWARE
# -----------------------------------------------------------------------------
if st.session_state.df_projeto is not None:
    df = st.session_state.df_projeto.copy()
    
    # Verifica se a tabela já passou pelo filtro inteligente do DXF/Excel
    if "Pilar" in df.columns:
        # Padronização de colunas (Convertendo cm para metros para o desenho BIM)
        if "X_cm" in df.columns:
            df["X_m"] = df["X_cm"].fillna(0) / 100.0
            df["Y_m"] = df["Y_cm"].fillna(0) / 100.0
        else:
            df["X_m"] = 0
            df["Y_m"] = 0
        
        # Extrair diâmetro da estaca do texto (ex: "HCØ50cm" -> 0.50)
        def extrair_diametro(texto):
            match = re.search(r'\d+', str(texto))
            return float(match.group(0))/100 if match else 0.50 
        
        if "Estaca" in df.columns:
            df["Diametro_m"] = df["Estaca"].apply(extrair_diametro)
        else:
            df["Diametro_m"] = 0.50

        if "ne" not in df.columns: df["ne"] = 1
        if "Carga_Max_tf" not in df.columns: df["Carga_Max_tf"] = 50.0

        # -------------------------------------------------------------------------
        # 1. ORÇAMENTO GERAL E QUANTITATIVOS
        # -------------------------------------------------------------------------
        total_blocos = len(df)
        total_estacas = df["ne"].sum()
        
        # Volume = (pi * D^2 / 4) * L * ne
        df["Vol_Concreto_m3"] = (np.pi * (df["Diametro_m"]**2) / 4) * profundidade_media * df["ne"]
        volume_concreto_total = df["Vol_Concreto_m3"].sum()
        peso_aco_total = volume_concreto_total * taxa_aco_estimada

        st.subheader("💰 Resumo de Quantitativos (Orçamento Executivo)")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Pilares / Blocos", f"{total_blocos} un")
        c2.metric("Total de Estacas", f"{total_estacas:.0f} un", f"Total: {total_estacas * profundidade_media:.1f} m perfurados")
        c3.metric("Volume de Concreto", f"{volume_concreto_total:.1f} m³")
        c4.metric("Aço Estimado (Total)", f"{peso_aco_total:,.1f} kg")

        st.markdown("---")

        # -------------------------------------------------------------------------
        # 2. PLANTA DE LOCAÇÃO INTERATIVA (VISÃO BIM 2D)
        # -------------------------------------------------------------------------
        st.subheader("🗺️ Planta de Locação e Mapa de Cargas")
        st.info("Passe o rato sobre os blocos para ver as informações detalhadas extraídas do CAD/Excel.")
        
        fig = px.scatter(
            df, 
            x="X_m", 
            y="Y_m", 
            text="Pilar",
            size="Carga_Max_tf", 
            color="ne",          
            hover_data=["Carga_Max_tf", "ne", "Estaca", "Diametro_m"],
            labels={"X_m": "Coordenada X (m)", "Y_m": "Coordenada Y (m)", "ne": "Nº de Estacas"},
            color_continuous_scale=px.colors.sequential.Viridis
        )
        
        fig.update_traces(textposition='top center', marker=dict(line=dict(width=1, color='DarkSlateGrey')))
        fig.update_layout(
            height=600, 
            plot_bgcolor='rgba(240, 240, 240, 0.8)',
            title_text="Visualização Top-Down do Projeto (Auto-Gerada a partir do DXF/Tabela)",
            xaxis=dict(scaleanchor="y", scaleratio=1), 
        )
        st.plotly_chart(fig, use_container_width=True)

        with st.expander("👁️ Ver Tabela Estruturada Lida do Arquivo", expanded=False):
            st.dataframe(df, use_container_width=True)
            
        st.markdown("---")
        st.subheader("🏗️ Integração BIM")
        if st.button("🚀 Exportar Modelo 3D para IFC (Em Desenvolvimento)", type="primary", use_container_width=True):
            st.success("No futuro, este botão chamará a biblioteca `IfcOpenShell` e criará as estacas virtuais no espaço 3D usando as coordenadas extraídas do seu DXF!")

    else:
        st.warning("⚠️ O sistema extraiu os textos do ficheiro, mas não conseguiu encontrar o cabeçalho padrão do Eberick (Nome, X, Y, Carga Máx). Abaixo está a leitura bruta do CAD. Tente limpar o desenho CAD para deixar apenas a tabela visível, ou use Excel.")
        st.dataframe(df)
else:
    st.info("👈 Por favor, faça o upload da Planta de Cargas em .DXF ou Excel na barra lateral.")
