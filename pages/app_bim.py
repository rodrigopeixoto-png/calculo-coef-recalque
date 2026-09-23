import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import io
import re
import tempfile
import os

try:
    import ezdxf
except ImportError:
    st.error("A biblioteca 'ezdxf' não está instalada. Adicione 'ezdxf' ao seu ficheiro requirements.txt e faça o reboot!")

st.set_page_config(page_title="Gestor BIM e Orçamento - Fundações", page_icon="🏢", layout="wide")

st.title("🏢 Gestor BIM & Orçamento de Fundações")
st.caption("Leitura Nativa de CAD (.DXF) com Radar Auto-Escalável e Importação de Excel")

# -----------------------------------------------------------------------------
# FUNÇÃO: RADAR GEOMÉTRICO AUTO-ESCALÁVEL PARA TABELAS DXF
# -----------------------------------------------------------------------------
def extrair_tabela_do_dxf(dxf_bytes):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp:
        tmp.write(dxf_bytes)
        tmp_path = tmp.name
        
    try:
        doc = ezdxf.readfile(tmp_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    
    textos_brutos = []
    
    def limpar_texto(txt):
        t = str(txt).replace('\\P', ' ').replace('\\p', ' ')
        t = re.sub(r'\\[A-Za-z0-9~]+;', '', t).strip()
        return t.replace('{', '').replace('}', '')

    # Extrai todos os textos
    for e in doc.modelspace():
        if e.dxftype() in ('TEXT', 'MTEXT'):
            t = e.dxf.text if e.dxftype() == 'TEXT' else e.text
            t_limpo = limpar_texto(t)
            if t_limpo: textos_brutos.append({'Texto': t_limpo, 'X': e.dxf.insert.x, 'Y': e.dxf.insert.y})
                
        elif e.dxftype() == 'INSERT':
            for attrib in e.attribs:
                t_limpo = limpar_texto(attrib.dxf.text)
                if t_limpo: textos_brutos.append({'Texto': t_limpo, 'X': attrib.dxf.insert.x, 'Y': attrib.dxf.insert.y})
            block = doc.blocks.get(e.dxf.name)
            if block:
                for entity in block.query('TEXT MTEXT'):
                    t = entity.dxf.text if entity.dxftype() == 'TEXT' else entity.text
                    t_limpo = limpar_texto(t)
                    if t_limpo: textos_brutos.append({'Texto': t_limpo, 'X': e.dxf.insert.x + entity.dxf.insert.x, 'Y': e.dxf.insert.y + entity.dxf.insert.y})

    if not textos_brutos: return None, pd.DataFrame()

    df_raw = pd.DataFrame(textos_brutos)
    
    # 1. Caça os cabeçalhos das colunas
    headers_x = {'x': None, 'y': None, 'carga': None, 'ne': None, 'estaca': None}
    for index, row in df_raw.iterrows():
        val = str(row['Texto']).lower().strip()
        if val in ['x', 'x(cm)', 'x (cm)', 'x(m)', 'x (m)']: headers_x['x'] = row['X']
        elif val in ['y', 'y(cm)', 'y (cm)', 'y(m)', 'y (m)']: headers_x['y'] = row['X']
        elif 'carga' in val and ('máx' in val or 'max' in val or 'tf' in val or 'kn' in val): headers_x['carga'] = row['X']
        elif val == 'ne': headers_x['ne'] = row['X']
        elif val == 'estaca': headers_x['estaca'] = row['X']

    if headers_x['carga'] is None:
        for index, row in df_raw.iterrows():
            if 'carga' in str(row['Texto']).lower(): headers_x['carga'] = row['X']

    # 2. Identifica os Pilares
    pilares = df_raw[df_raw['Texto'].str.match(r'^P\s*\d+$', case=False)].copy()
    
    if len(pilares) == 0: return None, df_raw

    # 3. MÁGICA AUTO-ESCALÁVEL: Calcular o espaçamento exato das linhas do CAD
    y_vals = sorted(pilares['Y'].unique(), reverse=True)
    if len(y_vals) > 1:
        espacamentos = [abs(y_vals[i] - y_vals[i+1]) for i in range(len(y_vals)-1)]
        tolerancia_y = np.median(espacamentos) * 0.40 # 40% do espaço de uma linha para a outra
    else:
        tolerancia_y = 15.0 # Fallback genérico se só existir 1 pilar
    
    # 4. Cruzamento de dados com Bloqueio de Linha
    linhas_dados = []
    for _, p in pilares.iterrows():
        y_ref = p['Y']
        # Foca APENAS na linha atual, ignorando cabeçalhos e linhas adjacentes
        linha_textos = df_raw[abs(df_raw['Y'] - y_ref) <= tolerancia_y].copy()
        
        def pega_valor(chave):
            x_alvo = headers_x[chave]
            if x_alvo is None or len(linha_textos) == 0: return None
            
            # Encontra o texto desta linha que está mais alinhado com o cabeçalho
            linha_textos['Dist'] = abs(linha_textos['X'] - x_alvo)
            texto_perto = linha_textos.loc[linha_textos['Dist'].idxmin()]
            
            # Retorna o texto se não for exatamente o próprio texto do cabeçalho
            texto_final = str(texto_perto['Texto']).strip()
            if texto_final.lower() not in ['x', 'y', 'x(cm)', 'y(cm)', 'ne', 'estaca']:
                return texto_final
            return None
            
        linhas_dados.append({
            "Pilar": str(p['Texto']).strip(),
            "X_cm": pega_valor('x'),
            "Y_cm": pega_valor('y'),
            "Carga_Max_tf": pega_valor('carga'),
            "ne": pega_valor('ne'),
            "Estaca": pega_valor('estaca')
        })
        
    df_final = pd.DataFrame(linhas_dados)
    
    # Limpeza final dos números
    for col in ["X_cm", "Y_cm", "Carga_Max_tf", "ne"]:
        if col in df_final.columns:
            df_final[col] = pd.to_numeric(df_final[col].astype(str).str.replace(',', '.').str.extract(r'([-+]?\d*\.?\d+)')[0], errors='coerce')
            
    df_final = df_final.dropna(subset=['Pilar'])
    
    if len(df_final) > 0 and headers_x['x'] is not None:
        return df_final, df_raw
        
    return None, df_raw

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
        with st.spinner("A varrer o desenho CAD com Radar Auto-Escalável..."):
            try:
                df_extraido, df_raw_debug = extrair_tabela_do_dxf(arquivo_upload.getvalue())
                
                if df_extraido is not None and "X_cm" in df_extraido.columns:
                    st.session_state.df_projeto = df_extraido
                    st.sidebar.success(f"Tabela CAD lida com sucesso! ({len(df_extraido)} blocos extraídos)")
                else:
                    st.sidebar.warning("⚠️ O radar não encontrou os cabeçalhos padrão. Exibindo textos brutos.")
                    st.session_state.df_projeto = df_raw_debug
                    
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
profundidade_media = st.sidebar.number_input("Profundidade Média das Estacas (m)", value=12.0, step=0.5)
taxa_aco_estimada = st.sidebar.number_input("Taxa de Aço Média (kg/m³ de betão)", value=85.0, step=5.0)

# -----------------------------------------------------------------------------
# ÁREA PRINCIPAL DO SOFTWARE
# -----------------------------------------------------------------------------
if st.session_state.df_projeto is not None:
    df = st.session_state.df_projeto.copy()
    
    if "Pilar" in df.columns and "X_cm" in df.columns:
        
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
        df["ne"] = pd.to_numeric(df["ne"], errors='coerce').fillna(1)
        
        if "Carga_Max_tf" not in df.columns: df["Carga_Max_tf"] = 0.0
        df["Carga_Max_tf"] = pd.to_numeric(df["Carga_Max_tf"], errors='coerce').fillna(0.0)

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
        
        df["Tamanho_Visual"] = df["Carga_Max_tf"].abs()
        df.loc[df["Tamanho_Visual"] < 5, "Tamanho_Visual"] = 5 
        
        if "Estaca" not in df.columns: df["Estaca"] = "N/A"

        try:
            fig = px.scatter(
                df, 
                x="X_m", 
                y="Y_m", 
                text="Pilar",
                size="Tamanho_Visual", 
                color="ne",          
                hover_data={"Carga_Max_tf": True, "ne": True, "Estaca": True, "Diametro_m": True, "X_m": False, "Y_m": False},
                labels={"Carga_Max_tf": "Carga (tf)", "ne": "Nº de Estacas"},
                color_continuous_scale=px.colors.sequential.Viridis
            )
            
            fig.update_traces(textposition='top center', marker=dict(line=dict(width=1, color='DarkSlateGrey')))
            fig.update_layout(
                height=650, 
                plot_bgcolor='rgba(240, 240, 240, 0.8)',
                title_text="Visualização Top-Down do Projeto",
                xaxis=dict(scaleanchor="y", scaleratio=1), 
            )
            st.plotly_chart(fig, use_container_width=True)
        except Exception as e:
            st.error(f"Erro ao gerar a visualização gráfica: {e}")

        with st.expander("👁️ Tabela Oficial Extraída do Arquivo", expanded=False):
            st.dataframe(df, use_container_width=True)
            
        st.markdown("---")
        st.subheader("🏗️ Próximo Passo: Exportação BIM")
        if st.button("🚀 Gerar Modelo 3D (.IFC)", type="primary", use_container_width=True):
            st.success("Temos as Coordenadas, os Diâmetros, o número de estacas e as Cargas extraídas do CAD perfeitamente. O próximo passo será exportar para Revit/Navisworks!")

    else:
        st.warning("⚠️ **DIAGNÓSTICO:** O Radar não conseguiu alinhar as colunas com os Pilares.")
        st.dataframe(df, use_container_width=True)

else:
    st.info("👈 Por favor, faça o upload da Planta de Cargas (.DXF do Eberick ou Tabela Excel) na barra lateral.")
