import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import io
import re

try:
    import ezdxf
except ImportError:
    st.error("A biblioteca 'ezdxf' não está instalada. Adicione 'ezdxf' ao seu ficheiro requirements.txt e faça o reboot!")

st.set_page_config(page_title="Gestor BIM e Orçamento - Fundações", page_icon="🏢", layout="wide")

st.title("🏢 Gestor BIM & Orçamento de Fundações")
st.caption("Leitura Nativa de CAD (.DXF) com Radar Geométrico e Importação de Excel")

# -----------------------------------------------------------------------------
# FUNÇÃO: RADAR GEOMÉTRICO PARA TABELAS DXF (PADRÃO EBERICK)
# -----------------------------------------------------------------------------
def extrair_tabela_do_dxf(dxf_bytes):
    # 1. Lê o ficheiro DXF
    text_stream = io.StringIO(dxf_bytes.decode('utf-8', errors='ignore'))
    doc = ezdxf.read(text_stream)
    msp = doc.modelspace()
    
    # 2. Varre o desenho à procura de todos os Textos
    textos_brutos = []
    for e in msp.query('TEXT MTEXT'):
        texto = e.dxf.text if e.dxftype() == 'TEXT' else e.text
        # Limpar lixo de formatação do AutoCAD (ex: \A1; \pxqc; {})
        texto_limpo = re.sub(r'\\[A-Za-z0-9~]+;', '', str(texto)).strip()
        texto_limpo = texto_limpo.replace('{', '').replace('}', '')
        
        if texto_limpo:
            textos_brutos.append({
                'Texto': texto_limpo, 
                'X': e.dxf.insert.x, 
                'Y': e.dxf.insert.y
            })
            
    if not textos_brutos: return None

    # 3. Mapear onde estão as Colunas (Eixo X)
    headers_x = {'x': None, 'y': None, 'carga': None, 'ne': None, 'estaca': None}
    
    for t in textos_brutos:
        val = t['Texto'].lower().strip()
        if val in ['x', 'x (cm)', 'x(cm)']: headers_x['x'] = t['X']
        elif val in ['y', 'y (cm)', 'y(cm)']: headers_x['y'] = t['X']
        elif 'carga' in val and ('máx' in val or 'max' in val): headers_x['carga'] = t['X']
        elif val == 'ne': headers_x['ne'] = t['X']
        elif val == 'estaca': headers_x['estaca'] = t['X']

    # Se falhar o 'Carga Máx', caça só a palavra 'Carga'
    if headers_x['carga'] is None:
        for t in textos_brutos:
            if 'carga' in t['Texto'].lower(): headers_x['carga'] = t['X']

    # 4. Caçar os Pilares (Ex: P1, P12) para mapear as Linhas (Eixo Y)
    pilares = [t for t in textos_brutos if re.match(r'^P\s*\d+$', t['Texto'].strip(), re.IGNORECASE)]
    
    # 5. Cruzar Linhas e Colunas (A Batalha Naval)
    linhas_dados = []
    for p in pilares:
        y_ref = p['Y']
        # Pega todos os textos que estão na mesma altura deste pilar (margem de 30 unidades CAD)
        textos_linha = [t for t in textos_brutos if abs(t['Y'] - y_ref) <= 30.0]
        
        def pega_texto_da_coluna(chave_header):
            x_alvo = headers_x[chave_header]
            if x_alvo is None or not textos_linha: return None
            # Dos textos desta linha, qual está perfeitamente alinhado com o X do cabeçalho?
            texto_coluna = min(textos_linha, key=lambda item: abs(item['X'] - x_alvo))
            return texto_coluna['Texto']
            
        linhas_dados.append({
            "Pilar": p['Texto'].strip(),
            "X_cm": pega_texto_da_coluna('x'),
            "Y_cm": pega_texto_da_coluna('y'),
            "Carga_Max_tf": pega_texto_da_coluna('carga'),
            "ne": pega_texto_da_coluna('ne'),
            "Estaca": pega_texto_da_coluna('estaca')
        })
        
    df_final = pd.DataFrame(linhas_dados)
    
    # 6. Limpeza e Conversão Numérica
    for col in ["X_cm", "Y_cm", "Carga_Max_tf", "ne"]:
        if col in df_final.columns:
            # Extrai apenas os números e substitui vírgula por ponto
            df_final[col] = pd.to_numeric(df_final[col].astype(str).str.replace(',', '.').str.extract(r'([-+]?\d*\.?\d+)')[0], errors='coerce')
            
    df_final = df_final.dropna(subset=['Pilar'])
    
    if len(df_final) > 0:
        return df_final
    return pd.DataFrame(textos_brutos) # Fallback: se tudo falhar, exibe os textos brutos para debugar

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
        with st.spinner("A varrer o desenho CAD com o Radar Geométrico..."):
            try:
                df_extraido = extrair_tabela_do_dxf(arquivo_upload.getvalue())
                
                # Se as colunas mágicas foram encontradas e processadas
                if df_extraido is not None and "Carga_Max_tf" in df_extraido.columns:
                    st.session_state.df_projeto = df_extraido
                    st.sidebar.success(f"Tabela CAD lida na perfeição! ({len(df_extraido)} blocos extraídos)")
                else:
                    st.sidebar.warning("Aviso: O radar não encontrou os cabeçalhos padrão. Exibindo os textos brutos.")
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
st.sidebar.markdown("*(Futuramente, estes dados serão importados do seu ficheiro .utea)*")
profundidade_media = st.sidebar.number_input("Profundidade Média das Estacas (m)", value=12.0, step=0.5)
taxa_aco_estimada = st.sidebar.number_input("Taxa de Aço Média (kg/m³ de betão)", value=85.0, step=5.0)

# -----------------------------------------------------------------------------
# ÁREA PRINCIPAL DO SOFTWARE
# -----------------------------------------------------------------------------
if st.session_state.df_projeto is not None:
    df = st.session_state.df_projeto.copy()
    
    # Valida se o radar resultou na tabela bonitinha (tem a coluna X_cm)
    if "X_cm" in df.columns and "Y_cm" in df.columns:
        
        # 1. Tratar os dados para o Orçamento e Desenho
        df["X_m"] = df["X_cm"].fillna(0) / 100.0
        df["Y_m"] = df["Y_cm"].fillna(0) / 100.0
        
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
        # 2. ORÇAMENTO GERAL
        # -------------------------------------------------------------------------
        total_blocos = len(df)
        total_estacas = df["ne"].sum()
        
        df["Vol_Concreto_m3"] = (np.pi * (df["Diametro_m"]**2) / 4) * profundidade_media * df["ne"]
        volume_concreto_total = df["Vol_Concreto_m3"].sum()
        peso_aco_total = volume_concreto_total * taxa_aco_estimada

        st.subheader("💰 Resumo de Quantitativos do Edifício")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Pilares / Blocos", f"{total_blocos} un")
        c2.metric("Total de Estacas", f"{total_estacas:.0f} un", f"Furos: {total_estacas * profundidade_media:.1f} m")
        c3.metric("Volume de Concreto", f"{volume_concreto_total:.1f} m³")
        c4.metric("Aço Estimado (Total)", f"{peso_aco_total:,.1f} kg")

        st.markdown("---")

        # -------------------------------------------------------------------------
        # 3. PLANTA DE LOCAÇÃO INTERATIVA (BIM 2D)
        # -------------------------------------------------------------------------
        st.subheader("🗺️ Planta de Locação e Mapa de Cargas")
        st.info("Passe o rato sobre os blocos para ver as informações extraídas cirurgicamente do seu arquivo DXF.")
        
        fig = px.scatter(
            df, 
            x="X_m", 
            y="Y_m", 
            text="Pilar",
            size="Carga_Max_tf", 
            color="ne",          
            hover_data={"Carga_Max_tf": True, "ne": True, "Estaca": True, "Diametro_m": True, "X_m": False, "Y_m": False},
            labels={"Carga_Max_tf": "Carga (tf)", "ne": "Nº de Estacas"},
            color_continuous_scale=px.colors.sequential.Viridis
        )
        
        fig.update_traces(textposition='top center', marker=dict(line=dict(width=1, color='DarkSlateGrey')))
        fig.update_layout(
            height=650, 
            plot_bgcolor='rgba(240, 240, 240, 0.8)',
            title_text="Visualização Top-Down do Projeto (Coordenadas reais do Eberick)",
            xaxis=dict(scaleanchor="y", scaleratio=1), 
        )
        st.plotly_chart(fig, use_container_width=True)

        with st.expander("👁️ Tabela Oficial Extraída do Arquivo DXF", expanded=False):
            st.dataframe(df, use_container_width=True)
            
        st.markdown("---")
        st.subheader("🏗️ Próximo Passo: Exportação BIM")
        if st.button("🚀 Gerar Modelo 3D (.IFC)", type="primary", use_container_width=True):
            st.success("Temos as Coordenadas, os Diâmetros, o número de estacas e as Cargas extraídas do CAD perfeitamente. O próximo passo de desenvolvimento será importar a biblioteca 'ifcopenshell' para transformar este mapa 2D num esqueleto 3D que abrirá direto no Revit!")

    else:
        st.warning("⚠️ O DXF parece ser diferente do padrão ou os textos não foram alinhados. Esta é a leitura bruta do que encontrei dentro do ficheiro:")
        st.dataframe(df)

else:
    st.info("👈 Por favor, faça o upload da Planta de Cargas (.DXF do Eberick ou Tabela Excel) na barra lateral.")
