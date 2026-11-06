import streamlit as st
import pandas as pd
import numpy as np
import io
import json
import re
import os
import tempfile
import ezdxf
import plotly.express as px

# -----------------------------------------------------------------------------
# FUNÇÃO DE LEITURA DO DXF (CORRIGIDA COM AUTO-ESCALA)
# -----------------------------------------------------------------------------
def processar_dxf(file_bytes):
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        doc = ezdxf.readfile(tmp_path)
        msp = doc.modelspace()

        textos = []
        for e in msp.query('TEXT MTEXT'):
            if e.dxftype() == 'TEXT':
                texto = e.dxf.text.strip()
                x, y = e.dxf.insert.x, e.dxf.insert.y
            elif e.dxftype() == 'MTEXT':
                texto = e.text.strip()
                x, y = e.dxf.insert.x, e.dxf.insert.y
            if texto:
                textos.append({'Texto': texto, 'X': x, 'Y': y})
        
        df_textos = pd.DataFrame(textos)
        if df_textos.empty: return pd.DataFrame(), "O arquivo DXF não contém entidades de texto válidas."

        df_pilares = df_textos[df_textos['Texto'].str.match(r'^P\s*[-_]?\s*\d+$', case=False, na=False)].copy()
        if df_pilares.empty: return df_textos, "DIAGNOSTICO"

        df_textos = df_textos.sort_values(by='Y', ascending=False).reset_index(drop=True)
        y_valores_unicos = np.sort(df_textos['Y'].unique())
        diferencas_y = np.diff(y_valores_unicos)
        diferencas_y = diferencas_y[diferencas_y > 0.1]
        tolerancia_y = min(diferencas_y) * 0.45 if len(diferencas_y) > 0 else 1.0

        dados_pilares = []
        for _, pilar in df_pilares.iterrows():
            nome = pilar['Texto']
            y_p, x_p = pilar['Y'], pilar['X']
            
            textos_linha = df_textos[(abs(df_textos['Y'] - y_p) <= tolerancia_y) & (df_textos['X'] > x_p)].sort_values(by='X')
            
            carga_pilar = None
            for _, txt_cand in textos_linha.iterrows():
                val_str = txt_cand['Texto'].replace(',', '.')
                if 'x' in val_str.lower() or 'X' in val_str: continue 
                try:
                    carga_val = float(val_str)
                    if carga_val > 0:
                        carga_pilar = carga_val
                        break
                except ValueError:
                    continue
                    
            if carga_pilar is not None:
                dados_pilares.append({
                    'Pilar': nome, 'Carga Vertical (tf)': carga_pilar, 'X_m': x_p, 'Y_m': y_p
                })

        df_final = pd.DataFrame(dados_pilares)
        if df_final.empty: return df_textos, "DIAGNOSTICO" 
            
        df_final['Carga Vertical (kN)'] = df_final['Carga Vertical (tf)'] * 10
        return df_final, ""
    except Exception as e:
        return pd.DataFrame(), f"Erro DXF: {e}"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except: pass

# -----------------------------------------------------------------------------
# CÁLCULOS ESTRUTURAIS BÁSICOS
# -----------------------------------------------------------------------------
def obter_capacidade_profundidade(df_curva, carga_total):
    if df_curva is None or df_curva.empty:
        return "Erro"
    
    cap_maxima = df_curva["Rc_Adotada"].iloc[-1]
    prof_maxima = df_curva["Profundidade (m)"].max()
    
    if carga_total > cap_maxima:
        return f"FALHA (> {prof_maxima}m)"
    else:
        linha_ideal = df_curva[df_curva["Rc_Adotada"] >= carga_total].iloc[0]
        return float(linha_ideal["Profundidade (m)"])

# -----------------------------------------------------------------------------
# INTERFACE PRINCIPAL (Layout Restaurado)
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Módulo Estrutural - DXF", page_icon="🏗️", layout="wide")
st.title("🏗️ Módulo Estrutural - Otimização de Pilares")
st.write("Mapeie as cargas do Eberick (DXF) e encontre a profundidade ideal da estaca para cada pilar.")

# SIDEBAR: 1. Dados do Terreno
st.sidebar.markdown("### 1️⃣ Dados do Terreno Geotécnico")
if 'projeto_geotecnico' in st.session_state and st.session_state['projeto_geotecnico']:
    st.sidebar.success("🔗 Terreno sincronizado automaticamente do Módulo Geotécnico!")
    
    projeto_furos = {}
    dados = st.session_state['projeto_geotecnico']
    for nome, info in dados.get("furos", {}).items():
        projeto_furos[nome] = pd.DataFrame(info["df"])
        
    furo_base_selecionado = st.sidebar.selectbox("Furo Base para Cálculo:", list(projeto_furos.keys()))
    criterio_q_adm = st.sidebar.selectbox("Critério Geotécnico:", ["Média dos Métodos", "Menor Valor (Mais Conservador)", "Apenas Aoki-Velloso", "Apenas Décourt-Quaresma", "Apenas Teixeira"])
else:
    st.sidebar.warning("Volte ao Módulo 1 e salve o Projeto primeiro.")
    furo_base_selecionado = None
    criterio_q_adm = "Média dos Métodos"

st.sidebar.markdown("---")
# SIDEBAR: 2. Importar Planta
st.sidebar.markdown("### 2️⃣ Importar Planta")
upload_dxf = st.sidebar.file_uploader("Planta do Eberick (.dxf, .xlsx)", type=["dxf"])

st.sidebar.markdown("---")
# SIDEBAR: 3. Configuração Estrutural e Materiais
st.sidebar.markdown("### 3️⃣ Configuração Estrutural e Materiais")
if 'params_globais' in st.session_state:
    st.sidebar.success("✅ Materiais e Armaduras sincronizados!")
    p_globais = st.session_state['params_globais']
    fck_val = p_globais.get("fck", 25.0)
    taxa_val = p_globais.get("taxa_armadura", 0.5)
    bit_long_val = p_globais.get("bitola", 10.0)
    bit_estr_val = p_globais.get("bitola_estribo", 6.3)
    esp_estr_val = p_globais.get("espacamento_estribo", 15.0)
else:
    fck_val = 25.0
    taxa_val = 0.5
    bit_long_val = 10.0
    bit_estr_val = 6.3
    esp_estr_val = 15.0

ativar_bulbo = st.sidebar.checkbox("👁️ Ativar Verificação do Bulbo de Tensões", value=True)
considerar_aterro = st.sidebar.checkbox("🚜 Considerar Atrito Negativo (Aterro)?", value=False)

fck = st.sidebar.selectbox("Classe do Concreto (Fck - MPa)", [15, 20, 25, 30, 35, 40], index=[15, 20, 25, 30, 35, 40].index(int(fck_val)) if int(fck_val) in [15, 20, 25, 30, 35, 40] else 2)
prof_minima = st.sidebar.number_input("Profundidade Mínima da Estaca (m)", min_value=1.0, value=6.0, step=0.5)
taxa_armadura = st.sidebar.number_input("Taxa de Armadura Longitudinal (%)", min_value=0.1, value=taxa_val, step=0.1)
bitola = st.sidebar.selectbox("Bitola Long. (mm)", [10.0, 12.5, 16.0, 20.0, 25.0], index=[10.0, 12.5, 16.0, 20.0, 25.0].index(bit_long_val) if bit_long_val in [10.0, 12.5, 16.0, 20.0, 25.0] else 0)
bitola_estribo = st.sidebar.selectbox("Bitola Estribo (mm)", [5.0, 6.3, 8.0, 10.0], index=[5.0, 6.3, 8.0, 10.0].index(bit_estr_val) if bit_estr_val in [5.0, 6.3, 8.0, 10.0] else 1)
espacamento_estribo = st.sidebar.number_input("Espaçamento Estribos (cm)", min_value=5.0, value=esp_estr_val, step=2.5)

# -----------------------------------------------------------------------------
# PROCESSAMENTO DOS DADOS E ABAS DE RESULTADO
# -----------------------------------------------------------------------------
if upload_dxf is not None and furo_base_selecionado is not None:
    with st.spinner("A processar Planta do Eberick..."):
        df_cargas, erro_dxf = processar_dxf(upload_dxf.getvalue())
        
        if erro_dxf == "DIAGNOSTICO":
            st.error("⚠️ Não consegui detetar o padrão dos pilares. Textos encontrados:")
            st.dataframe(df_cargas)
        elif erro_dxf != "":
            st.error(erro_dxf)
        else:
            # Integração com a sua função original de capacidade do Módulo 1
            from pages.Modulo_Geotecnico import processar_calculos_estaca
            
            df_furo_base = projeto_furos[furo_base_selecionado]
            res_calc = processar_calculos_estaca(df_furo_base, None, criterio_q_adm)
            df_curva = res_calc['df_inf']
            P_neg = res_calc['P_neg'] if considerar_aterro else 0.0
            
            resultados = []
            for _, pilar in df_cargas.iterrows():
                carga_pura = pilar["Carga Vertical (kN)"]
                carga_total = carga_pura + P_neg
                prof = obter_capacidade_profundidade(df_curva, carga_total)
                
                # Aplica a trava da Profundidade Mínima escolhida no menu lateral
                if isinstance(prof, float) and prof < prof_minima:
                    prof = prof_minima
                
                status = "❌ Aumentar Secção" if isinstance(prof, str) else "✅ OK"
                
                resultados.append({
                    "Pilar": pilar["Pilar"],
                    "X_m": pilar["X_m"],
                    "Y_m": pilar["Y_m"],
                    "Carga (kN)": carga_pura,
                    "Atrito Neg.": P_neg,
                    "Total (kN)": carga_total,
                    "Furo Base": furo_base_selecionado,
                    "Prof. (m)": prof,
                    "Status": status
                })
            
            df_resultados = pd.DataFrame(resultados)
            
            # ABAS ORIGINAIS RESTAURADAS
            tab1, tab2 = st.tabs(["📊 Relatório de Otimização", "🗺️ Planta de Locação - Mapa Topográfico"])
            
            with tab1:
                st.success("Tabela de cargas processada com sucesso!")
                st.dataframe(df_resultados.drop(columns=['X_m', 'Y_m']), use_container_width=True, hide_index=True)
                
                csv_bytes = df_resultados.to_csv(index=False, sep=';', decimal=',').encode('utf-8-sig')
                st.download_button("📥 Exportar (CSV)", data=csv_bytes, file_name="pilares_otimizados.csv", mime="text/csv")
                
            with tab2:
                st.markdown("### Planta de Locação - Mapa Topográfico (Profundidades)")
                st.markdown("**Mapa de Calor**")
                
                df_plot = df_resultados[~df_resultados["Prof. (m)"].astype(str).str.contains("FALHA")].copy()
                if not df_plot.empty:
                    df_plot["Prof. (m)"] = df_plot["Prof. (m)"].astype(float)
                    fig = px.scatter(
                        df_plot, x="X_m", y="Y_m", color="Prof. (m)", text="Pilar",
                        color_continuous_scale="RdYlBu_r", size_max=20,
                        labels={"X_m": "X (m)", "Y_m": "Y (m)", "Prof. (m)": "Prof. (m)"}
                    )
                    fig.update_traces(marker=dict(size=18, line=dict(width=1, color='DarkSlateGrey')), textposition='top center')
                    fig.update_layout(yaxis=dict(scaleanchor="x", scaleratio=1), height=600)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning("Todos os pilares excedem a capacidade máxima do furo. Não é possível desenhar o mapa.")

elif upload_dxf is None:
    st.info("👈 Carregue a Planta do Eberick (.dxf) na barra lateral para iniciar a Otimização.")
