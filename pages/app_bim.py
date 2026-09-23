import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import io
import re
import tempfile
import os
import json

try:
    import ezdxf
except ImportError:
    st.error("A biblioteca 'ezdxf' não está instalada. Adicione 'ezdxf' ao seu ficheiro requirements.txt e faça o reboot!")

st.set_page_config(page_title="Gestor BIM e Orçamento - Fundações", page_icon="🏢", layout="wide")

# -----------------------------------------------------------------------------
# DICIONÁRIO GEOTÉCNICO (CÉREBRO IMPORTADO DO APP.PY)
# -----------------------------------------------------------------------------
PARAMETROS_SOLO = {
    "Aterro":                {"aoki_K": 0,    "aoki_alpha": 0.000},
    "Areia":                 {"aoki_K": 1000, "aoki_alpha": 0.014},
    "Areia Siltosa":         {"aoki_K": 800,  "aoki_alpha": 0.020},
    "Areia Silto-argilosa":  {"aoki_K": 700,  "aoki_alpha": 0.024},
    "Areia Argilosa":        {"aoki_K": 600,  "aoki_alpha": 0.030},
    "Areia Argilo-siltosa":  {"aoki_K": 500,  "aoki_alpha": 0.028},
    "Silte":                 {"aoki_K": 400,  "aoki_alpha": 0.030},
    "Silte Arenoso":         {"aoki_K": 550,  "aoki_alpha": 0.022},
    "Silte Areno-argiloso":  {"aoki_K": 450,  "aoki_alpha": 0.028},
    "Silte Argiloso":        {"aoki_K": 230,  "aoki_alpha": 0.034},
    "Silte Argilo-arenoso":  {"aoki_K": 250,  "aoki_alpha": 0.030},
    "Argila":                {"aoki_K": 200,  "aoki_alpha": 0.060},
    "Argila Arenosa":        {"aoki_K": 350,  "aoki_alpha": 0.024},
    "Argila Areno-siltosa":  {"aoki_K": 300,  "aoki_alpha": 0.028},
    "Argila Silto-arenosa":  {"aoki_K": 250,  "aoki_alpha": 0.030},
    "Argila Siltosa":        {"aoki_K": 220,  "aoki_alpha": 0.040}
}

def get_dq_c(s):
    s = str(s).lower()
    if "areia" in s: return 400
    if "silte" in s: return 200
    return 120
    
def get_teix_alpha(s):
    s = str(s).lower()
    if "areia" in s: return 250
    if "silte" in s: return 200
    return 150

# -----------------------------------------------------------------------------
# FUNÇÃO DE CÁLCULO DE CAPACIDADE DE CARGA (POR DIÂMETRO)
# -----------------------------------------------------------------------------
def calcular_profundidade_estaca(df_spt_raw, diametro_m, carga_alvo_kn, criterio="Média dos Métodos"):
    df_spt = df_spt_raw.copy()
    df_spt["Profundidade (m)"] = pd.to_numeric(df_spt["Profundidade (m)"], errors='coerce').fillna(0)
    df_spt["N_SPT"] = pd.to_numeric(df_spt["N_SPT"], errors="coerce").fillna(1)
    df_spt["Tipo de Solo"] = df_spt["Tipo de Solo"].fillna("Argila")
    df_spt["N_corr"] = df_spt["N_SPT"].apply(lambda x: min(x, 50))
    
    Area_c = (np.pi * diametro_m**2) / 4 
    Perimetro = np.pi * diametro_m 
    
    # Assumindo estaca Hélice Contínua como padrão BIM
    f1, f2 = 2.0, 4.0 
    alfa_dq, beta_dq, beta_t = 0.3, 1.0, 6.0 

    def proc_solo_aoki(row):
        solo = PARAMETROS_SOLO.get(row["Tipo de Solo"], PARAMETROS_SOLO["Argila"])
        n = row["N_corr"]
        rl = (solo["aoki_alpha"] * solo["aoki_K"] * n) / f2
        rp = (solo["aoki_K"] * n) / f1 * Area_c
        return pd.Series([rl * Perimetro * 1.0, rp])

    df_spt[["delta_Rl_aoki", "Rp_aoki"]] = df_spt.apply(proc_solo_aoki, axis=1)
    df_spt["Rl_Aoki_Acum"] = df_spt["delta_Rl_aoki"].cumsum()
    df_spt["Rc Aoki"] = (df_spt["Rp_aoki"] + df_spt["Rl_Aoki_Acum"]) / 2.0
    
    df_spt["N_dq"] = df_spt["N_corr"].apply(lambda x: max(3, min(x, 50)))
    df_spt["C_dq"] = df_spt["Tipo de Solo"].apply(get_dq_c)
    df_spt["delta_Rl_dq"] = beta_dq * 10 * ((df_spt["N_dq"] / 3) + 1) * Perimetro * 1.0
    df_spt["Rl_DQ_Acum"] = df_spt["delta_Rl_dq"].cumsum()
    df_spt["Rp_dq"] = alfa_dq * df_spt["C_dq"] * df_spt["N_corr"] * Area_c
    df_spt["Rc DQ"] = (df_spt["Rp_dq"] + df_spt["Rl_DQ_Acum"]) / 2.0
    
    df_spt["alpha_teix"] = df_spt["Tipo de Solo"].apply(get_teix_alpha)
    df_spt["delta_Rl_t"] = beta_t * df_spt["N_corr"] * Perimetro * 1.0
    df_spt["Rl_T_Acum"] = df_spt["delta_Rl_t"].cumsum()
    df_spt["Rp_t"] = df_spt["alpha_teix"] * df_spt["N_corr"] * Area_c
    df_spt["Rc Teix"] = (df_spt["Rp_t"] + df_spt["Rl_T_Acum"]) / 2.0

    df_spt["Rc Média"] = (df_spt["Rc Aoki"] + df_spt["Rc DQ"] + df_spt["Rc Teix"]) / 3.0
    df_spt["Rc Menor"] = df_spt[["Rc Aoki", "Rc DQ", "Rc Teix"]].min(axis=1)

    if criterio == "Média dos Métodos": col_adotada = "Rc Média"
    elif criterio == "Menor Valor (Mais Conservador)": col_adotada = "Rc Menor"
    elif criterio == "Apenas Aoki-Velloso": col_adotada = "Rc Aoki"
    elif criterio == "Apenas Décourt-Quaresma": col_adotada = "Rc DQ"
    else: col_adotada = "Rc Teix"

    # Encontra a primeira profundidade onde a Resistência supera a Carga
    df_suficiente = df_spt[df_spt[col_adotada] >= carga_alvo_kn]
    
    if len(df_suficiente) > 0:
        return df_suficiente.iloc[0]["Profundidade (m)"]
    else:
        return df_spt["Profundidade (m)"].max() # Retorna a máx do furo se não for suficiente

# -----------------------------------------------------------------------------
# FUNÇÃO: RADAR GEOMÉTRICO (DXF)
# -----------------------------------------------------------------------------
def extrair_tabela_do_dxf(dxf_bytes):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp:
        tmp.write(dxf_bytes)
        tmp_path = tmp.name
    try:
        doc = ezdxf.readfile(tmp_path)
    finally:
        if os.path.exists(tmp_path): os.remove(tmp_path)
    
    textos_brutos = []
    def limpar_texto(txt):
        t = str(txt).replace('\\P', ' ').replace('\\p', ' ')
        t = re.sub(r'\\[A-Za-z0-9~]+;', '', t).strip()
        return t.replace('{', '').replace('}', '')

    for e in doc.modelspace():
        if e.dxftype() in ('TEXT', 'MTEXT'):
            t_limpo = limpar_texto(e.dxf.text if e.dxftype() == 'TEXT' else e.text)
            if t_limpo: textos_brutos.append({'Texto': t_limpo, 'X': e.dxf.insert.x, 'Y': e.dxf.insert.y})
        elif e.dxftype() == 'INSERT':
            for attrib in e.attribs:
                t_limpo = limpar_texto(attrib.dxf.text)
                if t_limpo: textos_brutos.append({'Texto': t_limpo, 'X': attrib.dxf.insert.x, 'Y': attrib.dxf.insert.y})
            block = doc.blocks.get(e.dxf.name)
            if block:
                for entity in block.query('TEXT MTEXT'):
                    t_limpo = limpar_texto(entity.dxf.text if entity.dxftype() == 'TEXT' else entity.text)
                    if t_limpo: textos_brutos.append({'Texto': t_limpo, 'X': e.dxf.insert.x + entity.dxf.insert.x, 'Y': e.dxf.insert.y + entity.dxf.insert.y})

    if not textos_brutos: return None, pd.DataFrame()
    df_raw = pd.DataFrame(textos_brutos)
    
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

    pilares = df_raw[df_raw['Texto'].str.match(r'^P\s*\d+$', case=False)].copy()
    if len(pilares) == 0: return None, df_raw

    y_vals = sorted(pilares['Y'].unique(), reverse=True)
    if len(y_vals) > 1:
        espacamentos = [abs(y_vals[i] - y_vals[i+1]) for i in range(len(y_vals)-1)]
        tolerancia_y = np.median(espacamentos) * 0.40 
    else:
        tolerancia_y = 15.0 
    
    linhas_dados = []
    for _, p in pilares.iterrows():
        linha_textos = df_raw[abs(df_raw['Y'] - p['Y']) <= tolerancia_y].copy()
        
        def pega_valor(chave):
            x_alvo = headers_x[chave]
            if x_alvo is None or len(linha_textos) == 0: return None
            linha_textos['Dist'] = abs(linha_textos['X'] - x_alvo)
            texto_perto = linha_textos.loc[linha_textos['Dist'].idxmin()]
            texto_final = str(texto_perto['Texto']).strip()
            if texto_final.lower() not in ['x', 'y', 'x(cm)', 'y(cm)', 'ne', 'estaca']: return texto_final
            return None
            
        linhas_dados.append({
            "Pilar": str(p['Texto']).strip(), "X_cm": pega_valor('x'), "Y_cm": pega_valor('y'),
            "Carga_Max_tf": pega_valor('carga'), "ne": pega_valor('ne'), "Estaca": pega_valor('estaca')
        })
        
    df_final = pd.DataFrame(linhas_dados)
    for col in ["X_cm", "Y_cm", "Carga_Max_tf", "ne"]:
        if col in df_final.columns: df_final[col] = pd.to_numeric(df_final[col].astype(str).str.replace(',', '.').str.extract(r'([-+]?\d*\.?\d+)')[0], errors='coerce')
            
    df_final = df_final.dropna(subset=['Pilar'])
    if len(df_final) > 0 and headers_x['x'] is not None: return df_final, df_raw
    return None, df_raw

# -----------------------------------------------------------------------------
# INTERFACE PRINCIPAL
# -----------------------------------------------------------------------------
st.title("🏢 Gestor BIM & Orçamento de Fundações")
st.caption("Dimensionamento automático de estacas cruzando Planta de Cargas (DXF) e Perfil do Terreno (.utea)")

col_side1, col_side2 = st.sidebar.columns(2)

st.sidebar.header("1️⃣ Importar Terreno (.utea)")
st.sidebar.info("Upload do projeto criado no Módulo Geotécnico.")
arquivo_utea = st.sidebar.file_uploader("Ficheiro .utea", type=["utea", "json"])

dados_terreno = {}
furo_selecionado = None
criterio_selecionado = "Média dos Métodos"

if arquivo_utea is not None:
    try:
        conteudo = json.loads(arquivo_utea.read().decode('utf-8'))
        for nome, info in conteudo.get("furos", {}).items():
            dados_terreno[nome] = pd.DataFrame(info["df"])
        st.sidebar.success(f"Terreno lido! ({len(dados_terreno)} furos encontrados)")
        
        furo_selecionado = st.sidebar.selectbox("Furo Base para Cálculo Global:", list(dados_terreno.keys()))
        criterio_selecionado = st.sidebar.selectbox("Critério Geotécnico:", ["Média dos Métodos", "Menor Valor (Mais Conservador)", "Apenas Aoki-Velloso", "Apenas Décourt-Quaresma"])
    except Exception as e:
        st.sidebar.error("Erro ao ler o ficheiro de terreno.")

st.sidebar.markdown("---")
st.sidebar.header("2️⃣ Importar Planta de Cargas")
arquivo_upload = st.sidebar.file_uploader("Planta do Eberick (.dxf, .xlsx)", type=["dxf", "xlsx", "csv"])

st.sidebar.markdown("---")
st.sidebar.header("⚙️ Configuração Estrutural")
taxa_aco_estimada = st.sidebar.number_input("Taxa de Aço Média (kg/m³ de betão)", value=85.0, step=5.0)

if 'df_projeto' not in st.session_state:
    st.session_state.df_projeto = None

if arquivo_upload is not None:
    ext = arquivo_upload.name.split('.')[-1].lower()
    if ext == 'dxf':
        with st.spinner("A varrer o desenho CAD com Radar Auto-Escalável..."):
            df_extraido, df_raw_debug = extrair_tabela_do_dxf(arquivo_upload.getvalue())
            if df_extraido is not None and "X_cm" in df_extraido.columns:
                st.session_state.df_projeto = df_extraido
            else:
                st.sidebar.warning("⚠️ O radar falhou na leitura padronizada.")
                st.session_state.df_projeto = df_raw_debug
    elif ext == 'csv': st.session_state.df_projeto = pd.read_csv(arquivo_upload)
    else: st.session_state.df_projeto = pd.read_excel(arquivo_upload)

# -----------------------------------------------------------------------------
# PROCESSAMENTO DOS DADOS CRUZADOS
# -----------------------------------------------------------------------------
if st.session_state.df_projeto is not None:
    df = st.session_state.df_projeto.copy()
    
    if "Pilar" in df.columns and "X_cm" in df.columns:
        df["X_m"] = df["X_cm"].fillna(0) / 100.0
        df["Y_m"] = df["Y_cm"].fillna(0) / 100.0
        
        def extrair_diametro(texto):
            match = re.search(r'\d+', str(texto))
            return float(match.group(0))/100 if match else 0.50 
        
        df["Diametro_m"] = df["Estaca"].apply(extrair_diametro) if "Estaca" in df.columns else 0.50
        df["ne"] = pd.to_numeric(df.get("ne", 1), errors='coerce').fillna(1)
        df["Carga_Max_tf"] = pd.to_numeric(df.get("Carga_Max_tf", 0.0), errors='coerce').fillna(0.0)
        
        df["Carga_por_Estaca_kN"] = (df["Carga_Max_tf"] * 10) / df["ne"]

        # --- A GRANDE INTEGRAÇÃO GEOTÉCNICA ---
        if furo_selecionado and furo_selecionado in dados_terreno:
            df_spt_atual = dados_terreno[furo_selecionado]
            profundidades = []
            
            for index, row in df.iterrows():
                prof = calcular_profundidade_estaca(df_spt_atual, row["Diametro_m"], row["Carga_por_Estaca_kN"], criterio_selecionado)
                profundidades.append(prof)
                
            df["Profundidade_m"] = profundidades
            st.success(f"✅ O Software cruzou as cargas com o {furo_selecionado} e dimensionou as profundidades de todas as estacas com sucesso!")
        else:
            st.warning("⚠️ Nenhum Terreno (.utea) carregado. Assumindo profundidade teórica de 12m para orçamento.")
            df["Profundidade_m"] = 12.0

        # --- ORÇAMENTO REAL ---
        total_blocos = len(df)
        total_estacas = df["ne"].sum()
        df["Metros_Perfurados"] = df["Profundidade_m"] * df["ne"]
        total_metros = df["Metros_Perfurados"].sum()
        
        df["Vol_Concreto_m3"] = (np.pi * (df["Diametro_m"]**2) / 4) * df["Metros_Perfurados"]
        volume_concreto_total = df["Vol_Concreto_m3"].sum()
        peso_aco_total = volume_concreto_total * taxa_aco_estimada

        st.subheader("💰 Resumo Executivo da Fundação")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Pilares / Blocos", f"{total_blocos} un")
        c2.metric("Total Perfurado", f"{total_metros:.1f} m", f"Em {total_estacas:.0f} estacas")
        c3.metric("Volume de Betão/Concreto", f"{volume_concreto_total:.1f} m³")
        c4.metric("Aço Estimado (Total)", f"{peso_aco_total:,.1f} kg")

        st.markdown("---")

        # --- PLANTA BIM 2D COM MAPA DE CALOR ---
        st.subheader("🗺️ Planta de Locação - Mapa Topográfico (Profundidades)")
        st.info("Passe o rato sobre os pilares. A cor indica a profundidade que a estaca precisa atingir para suportar a carga no terreno selecionado!")
        
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
                color="Profundidade_m", # AGORA O MAPA É COLORIDO PELA PROFUNDIDADE!
                hover_data={"Carga_Max_tf": True, "ne": True, "Diametro_m": True, "Carga_por_Estaca_kN": True, "Profundidade_m": True, "X_m": False, "Y_m": False, "Tamanho_Visual": False},
                labels={"Carga_Max_tf": "Carga Total (tf)", "ne": "Estacas", "Profundidade_m": "Prof. (m)", "Carga_por_Estaca_kN": "Carga/Estaca (kN)"},
                color_continuous_scale=px.colors.diverging.RdYlBu_r # Escala de calor perfeita
            )
            
            fig.update_traces(textposition='top center', marker=dict(line=dict(width=1, color='DarkSlateGrey')))
            fig.update_layout(
                height=700, 
                plot_bgcolor='rgba(240, 240, 240, 0.8)',
                title_text=f"Mapa de Calor: Profundidade Necessária (Baseado no {furo_selecionado if furo_selecionado else 'Padrão'})",
                xaxis=dict(scaleanchor="y", scaleratio=1), 
            )
            st.plotly_chart(fig, use_container_width=True)
        except Exception as e:
            st.error(f"Erro ao gerar a visualização gráfica: {e}")

        with st.expander("👁️ Ver Memória de Cálculo Individual (Pilar a Pilar)", expanded=False):
            df_mostrar = df[["Pilar", "Carga_Max_tf", "ne", "Diametro_m", "Carga_por_Estaca_kN", "Profundidade_m", "Vol_Concreto_m3"]].copy()
            df_mostrar.columns = ["Pilar", "Carga Total (tf)", "Nº Estacas", "Diâmetro (m)", "Esforço p/ Estaca (kN)", "Prof. Calculada (m)", "Concreto (m³)"]
            st.dataframe(df_mostrar, use_container_width=True)

    else:
        st.warning("⚠️ **DIAGNÓSTICO:** O Radar não encontrou coordenadas na tabela do DXF.")

else:
    st.info("👈 Faça o upload do Terreno (.utea) e da Planta do Eberick (.dxf) na barra lateral para iniciar a integração.")
