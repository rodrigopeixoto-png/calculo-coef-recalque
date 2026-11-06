import streamlit as st
import pandas as pd
import numpy as np
import io
import json
import re
import ezdxf

# -----------------------------------------------------------------------------
# DICIONÁRIO GEOTÉCNICO E CONSTANTES (Para recalcular a curva do furo)
# -----------------------------------------------------------------------------
PARAMETROS_SOLO = {
    "Aterro":                {"aoki_K": 400,  "aoki_alpha": 0.030, "alpha_k": 1000},
    "Areia":                 {"aoki_K": 1000, "aoki_alpha": 0.014, "alpha_k": 3000},
    "Areia Siltosa":         {"aoki_K": 800,  "aoki_alpha": 0.020, "alpha_k": 2800},
    "Areia Silto-argilosa":  {"aoki_K": 700,  "aoki_alpha": 0.024, "alpha_k": 2500},
    "Areia Argilosa":        {"aoki_K": 600,  "aoki_alpha": 0.030, "alpha_k": 2500},
    "Areia Argilo-siltosa":  {"aoki_K": 500,  "aoki_alpha": 0.028, "alpha_k": 2500},
    "Silte":                 {"aoki_K": 400,  "aoki_alpha": 0.030, "alpha_k": 2000},
    "Silte Arenoso":         {"aoki_K": 550,  "aoki_alpha": 0.022, "alpha_k": 2500},
    "Silte Areno-argiloso":  {"aoki_K": 450,  "aoki_alpha": 0.028, "alpha_k": 2200},
    "Silte Argiloso":        {"aoki_K": 230,  "aoki_alpha": 0.034, "alpha_k": 2000},
    "Silte Argilo-arenoso":  {"aoki_K": 250,  "aoki_alpha": 0.030, "alpha_k": 2000},
    "Argila":                {"aoki_K": 200,  "aoki_alpha": 0.060, "alpha_k": 1500},
    "Argila Arenosa":        {"aoki_K": 350,  "aoki_alpha": 0.024, "alpha_k": 2000},
    "Argila Areno-siltosa":  {"aoki_K": 300,  "aoki_alpha": 0.028, "alpha_k": 1800},
    "Argila Silto-arenosa":  {"aoki_K": 250,  "aoki_alpha": 0.030, "alpha_k": 1800},
    "Argila Siltosa":        {"aoki_K": 220,  "aoki_alpha": 0.040, "alpha_k": 1750}
}

FATORES_CONSTRUTIVOS = {
    "Franki": {"F1": 2.5, "F2": 5.0},
    "Metálica": {"F1": 1.8, "F2": 4.0},
    "Pré-moldada": {"F1": 1.8, "F2": 4.0},
    "Escavada": {"F1": 3.0, "F2": 6.0},
    "Raiz/Hélice": {"F1": 2.0, "F2": 4.0}
}

st.set_page_config(page_title="Módulo Estrutural - DXF", page_icon="🏗️", layout="wide")

# -----------------------------------------------------------------------------
# FUNÇÃO DE LEITURA DO DXF (COM CLUSTERING Y INTELIGENTE)
# -----------------------------------------------------------------------------
def processar_dxf(file_bytes):
    try:
        # CONVERSÃO DE BYTES PARA TEXTO (Corrige o erro do ezdxf)
        texto_dxf = file_bytes.decode('utf-8', errors='ignore')
        doc = ezdxf.read(io.StringIO(texto_dxf))
        msp = doc.modelspace()

        # Extrair todos os textos (TEXT e MTEXT) e as suas coordenadas X, Y
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
        if df_textos.empty:
            return pd.DataFrame(), "O arquivo DXF não contém entidades de texto válidas."

        # Agrupar textos que estão na mesma linha horizontal (tolerância de Y)
        df_textos = df_textos.sort_values(by='Y', ascending=False).reset_index(drop=True)
        
        linhas_agrupadas = []
        linha_atual = []
        y_ref = None
        tolerancia_y = 1.5 # Tolerância para considerar que textos estão na mesma linha

        for _, row in df_textos.iterrows():
            if y_ref is None:
                y_ref = row['Y']
                linha_atual.append(row)
            elif abs(row['Y'] - y_ref) <= tolerancia_y:
                linha_atual.append(row)
            else:
                linhas_agrupadas.append(linha_atual)
                y_ref = row['Y']
                linha_atual = [row]
        if linha_atual:
            linhas_agrupadas.append(linha_atual)

        dados_pilares = []
        
        # Procurar o padrão "Pilar" + "Carga" linha a linha da esquerda para a direita
        for linha in linhas_agrupadas:
            linha_ordenada = sorted(linha, key=lambda d: d['X'])
            textos_linha = [t['Texto'] for t in linha_ordenada]
            
            nome_pilar = None
            carga_pilar = None
            
            for i, txt in enumerate(textos_linha):
                # Deteta nomes como P1, P20, Pilar 1
                if re.match(r'^P\s*[-]?\s*\d+', txt, re.IGNORECASE):
                    nome_pilar = txt
                    
                    # Procura a primeira carga à direita ignorando secções (ex: 25x35)
                    for j in range(i+1, len(textos_linha)):
                        txt_candidato = textos_linha[j].replace(',', '.')
                        if 'x' in txt_candidato.lower() or 'X' in txt_candidato:
                            continue
                        try:
                            carga_val = float(txt_candidato)
                            if carga_val > 0:
                                carga_pilar = carga_val
                                break
                        except ValueError:
                            pass 
                    
                    if nome_pilar and carga_pilar is not None:
                        dados_pilares.append({
                            'Pilar': nome_pilar,
                            'Carga Vertical (tf)': carga_pilar
                        })
                        break 

        df_final = pd.DataFrame(dados_pilares)
        
        if df_final.empty:
            return df_textos, "DIAGNOSTICO" 
            
        df_final['Carga Vertical (kN)'] = df_final['Carga Vertical (tf)'] * 10
        return df_final, ""

    except Exception as e:
        return pd.DataFrame(), f"Erro ao processar o ficheiro DXF: {e}"

# -----------------------------------------------------------------------------
# MOTOR GEOTÉCNICO SIMPLIFICADO PARA CALCULAR A CURVA DO FURO BASE
# -----------------------------------------------------------------------------
def calcular_curva_capacidade(df_spt, B, metodo_construtivo, secao, criterio_q_adm):
    df = df_spt.copy()
    
    # Prepara a tabela
    df = df.dropna(subset=['N_SPT']).copy()
    if df.empty:
        return None
        
    df["N_SPT"] = pd.to_numeric(df["N_SPT"], errors="coerce").fillna(1)
    df["N_corr"] = df["N_SPT"].apply(lambda x: min(x, 50))
    
    # Geometria
    Area_c = (np.pi * B**2) / 4 if secao == "Circular" else B**2
    Perimetro = np.pi * B if secao == "Circular" else 4 * B
    f1, f2 = FATORES_CONSTRUTIVOS[metodo_construtivo]["F1"], FATORES_CONSTRUTIVOS[metodo_construtivo]["F2"]

    # Funções auxiliares
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

    if "Escavada" in metodo_construtivo:
        alfa_dq, beta_dq, beta_t = 0.5, 0.8, 5.0
    elif "Hélice" in metodo_construtivo or "Raiz" in metodo_construtivo:
        alfa_dq, beta_dq, beta_t = 0.3, 1.0, 6.0
    else:
        alfa_dq, beta_dq, beta_t = 1.0, 1.0, 8.0

    # Aoki
    def calc_aoki(row):
        solo = PARAMETROS_SOLO.get(row["Tipo de Solo"], PARAMETROS_SOLO["Argila"])
        rl = (solo["aoki_alpha"] * solo["aoki_K"] * row["N_corr"]) / f2
        rp = (solo["aoki_K"] * row["N_corr"]) / f1 * Area_c
        delta_rl = rl * Perimetro * 1.0 
        return pd.Series([rp, delta_rl])

    df[["Rp_aoki", "delta_Rl_aoki"]] = df.apply(calc_aoki, axis=1)

    # Decourt e Teixeira
    df["N_dq"] = df["N_corr"].apply(lambda x: max(3, min(x, 50)))
    df["C_dq"] = df["Tipo de Solo"].apply(get_dq_c)
    df["delta_Rl_dq"] = beta_dq * 10 * ((df["N_dq"] / 3) + 1) * Perimetro * 1.0
    df["Rp_dq"] = alfa_dq * df["C_dq"] * df["N_corr"] * Area_c
    
    df["alpha_teix"] = df["Tipo de Solo"].apply(get_teix_alpha)
    df["delta_Rl_t"] = beta_t * df["N_corr"] * Perimetro * 1.0
    df["Rp_t"] = df["alpha_teix"] * df["N_corr"] * Area_c

    # Atrito Negativo (Automático se Aterro)
    mascara_aterro = df["Tipo de Solo"] == "Aterro"
    P_neg_adotado = 0.0
    
    if mascara_aterro.any():
        P_neg_aoki = df.loc[mascara_aterro, "delta_Rl_aoki"].sum()
        P_neg_dq = df.loc[mascara_aterro, "delta_Rl_dq"].sum()
        P_neg_t = df.loc[mascara_aterro, "delta_Rl_t"].sum()
        
        df.loc[mascara_aterro, "delta_Rl_aoki"] = 0.0
        df.loc[mascara_aterro, "delta_Rl_dq"] = 0.0
        df.loc[mascara_aterro, "delta_Rl_t"] = 0.0
        
        if criterio_q_adm == "Média dos Métodos":
            P_neg_adotado = (P_neg_aoki + P_neg_dq + P_neg_t) / 3.0
        else:
            P_neg_adotado = max(P_neg_aoki, P_neg_dq, P_neg_t)

    # Acumulados e Admissíveis Metro a Metro
    df["Rl_Aoki_Acum"] = df["delta_Rl_aoki"].cumsum()
    df["Rc_Aoki"] = (df["Rp_aoki"] + df["Rl_Aoki_Acum"]) / 2.0
    
    df["Rl_DQ_Acum"] = df["delta_Rl_dq"].cumsum()
    df["Rc_DQ"] = (df["Rp_dq"] + df["Rl_DQ_Acum"]) / 2.0
    
    df["Rl_T_Acum"] = df["delta_Rl_t"].cumsum()
    df["Rc_Teix"] = (df["Rp_t"] + df["Rl_T_Acum"]) / 2.0

    df["Rc_Media"] = (df["Rc_Aoki"] + df["Rc_DQ"] + df["Rc_Teix"]) / 3.0
    df["Rc_Menor"] = df[["Rc_Aoki", "Rc_DQ", "Rc_Teix"]].min(axis=1)

    if criterio_q_adm == "Média dos Métodos": df["Rc_Adotada"] = df["Rc_Media"]
    elif criterio_q_adm == "Menor Valor (Mais Conservador)": df["Rc_Adotada"] = df["Rc_Menor"]
    elif criterio_q_adm == "Apenas Aoki-Velloso": df["Rc_Adotada"] = df["Rc_Aoki"]
    elif criterio_q_adm == "Apenas Décourt-Quaresma": df["Rc_Adotada"] = df["Rc_DQ"]
    elif criterio_q_adm == "Apenas Teixeira": df["Rc_Adotada"] = df["Rc_Teix"]

    return df, P_neg_adotado

# -----------------------------------------------------------------------------
# INTERFACE PRINCIPAL
# -----------------------------------------------------------------------------
st.title("🏗️ Módulo Estrutural - Otimização de Pilares")
st.write("Mapeie as cargas do Eberick (DXF) e encontre a profundidade ideal da estaca para cada pilar.")

# SIDEBAR: Configurações e Uploads
st.sidebar.header("1. 📂 Projeto Geotécnico")
upload_utea = st.sidebar.file_uploader("Upload do ficheiro (.utea)", type=["utea", "json"])

projeto_furos = {}
if upload_utea is not None:
    try:
        dados = json.loads(upload_utea.read().decode('utf-8'))
        for nome, info in dados.get("furos", {}).items():
            projeto_furos[nome] = pd.DataFrame(info["df"])
        st.sidebar.success(f"{len(projeto_furos)} Furos carregados!")
    except Exception:
        st.sidebar.error("Ficheiro .utea inválido.")

if len(projeto_furos) > 0:
    furo_base_selecionado = st.sidebar.selectbox("🎯 Furo Base para Cálculo:", list(projeto_furos.keys()))
else:
    furo_base_selecionado = None
    st.sidebar.warning("Carregue o projeto .utea primeiro.")

st.sidebar.markdown("---")
st.sidebar.header("2. 📋 Tabela do Eberick")
upload_dxf = st.sidebar.file_uploader("Upload da Tabela de Cargas (.dxf)", type=["dxf"])

st.sidebar.markdown("---")
st.sidebar.header("3. ⚙️ Parâmetros da Fundação")
metodo_construtivo = st.sidebar.selectbox("Método Construtivo:", list(FATORES_CONSTRUTIVOS.keys()), index=4)
secao = st.sidebar.selectbox("Secção", ["Circular", "Quadrada"])
B = st.sidebar.number_input("Largura/Diâmetro B (m)", min_value=0.1, value=0.30, step=0.05)
criterio_q_adm = st.sidebar.selectbox("Critério de Carga:", ["Média dos Métodos", "Menor Valor (Mais Conservador)", "Apenas Aoki-Velloso", "Apenas Décourt-Quaresma", "Apenas Teixeira"])

# -----------------------------------------------------------------------------
# PROCESSAMENTO DOS DADOS
# -----------------------------------------------------------------------------
if upload_dxf is not None and furo_base_selecionado is not None:
    with st.spinner("A ler o DXF com motor de Clustering Y..."):
        df_cargas, erro_dxf = processar_dxf(upload_dxf.getvalue())
        
        if erro_dxf == "DIAGNOSTICO":
            st.error("⚠️ O DXF foi lido, mas não consegui detetar o padrão dos pilares. Veja abaixo os textos extraídos:")
            st.dataframe(df_cargas)
        elif erro_dxf != "":
            st.error(erro_dxf)
        else:
            st.success(f"Tabela de cargas processada com sucesso! {len(df_cargas)} pilares encontrados.")
            
            # Obter a curva de capacidade do furo selecionado
            df_furo_base = projeto_furos[furo_base_selecionado]
            df_curva, P_neg = calcular_curva_capacidade(df_furo_base, B, metodo_construtivo, secao, criterio_q_adm)
            
            if df_curva is None or df_curva.empty:
                st.error("O furo selecionado não tem dados válidos.")
            else:
                prof_maxima = df_curva["Profundidade (m)"].max()
                cap_maxima = df_curva["Rc_Adotada"].iloc[-1]
                
                # Calcular a profundidade necessária para cada pilar
                resultados_finais = []
                for _, pilar in df_cargas.iterrows():
                    nome = pilar["Pilar"]
                    carga_pura = pilar["Carga Vertical (kN)"]
                    carga_total = carga_pura + P_neg
                    
                    if carga_total > cap_maxima:
                        prof_necessaria = f"FALHA (> {prof_maxima}m)"
                        status = "❌ Aumentar Secção"
                    else:
                        # Encontra a primeira linha onde a capacidade >= carga total
                        linha_ideal = df_curva[df_curva["Rc_Adotada"] >= carga_total].iloc[0]
                        prof_necessaria = linha_ideal["Profundidade (m)"]
                        status = "✅ OK"
                        
                    resultados_finais.append({
                        "Pilar": nome,
                        "Carga Atuante (kN)": f"{carga_pura:.1f}",
                        "Atrito Negativo (kN)": f"{P_neg:.1f}" if P_neg > 0 else "-",
                        "Carga Total (kN)": f"{carga_total:.1f}",
                        "Furo Adotado": furo_base_selecionado,
                        "Profundidade da Estaca (m)": prof_necessaria,
                        "Status": status
                    })
                
                st.markdown("### 📊 Relatório de Otimização de Pilares")
                st.write(f"Todos os pilares foram cruzados com a capacidade do **{furo_base_selecionado}**. Diâmetro adotado: **{B:.2f}m**.")
                
                df_resultados = pd.DataFrame(resultados_finais)
                st.dataframe(df_resultados, use_container_width=True, hide_index=True)
                
                # Botão para exportar o relatório para Excel
                buffer_excel = io.BytesIO()
                with pd.ExcelWriter(buffer_excel, engine='xlsxwriter') as writer:
                    df_resultados.to_excel(writer, index=False, sheet_name='Otimização Estacas')
                
                st.download_button(
                    label="📥 Baixar Tabela de Pilares em Excel",
                    data=buffer_excel.getvalue(),
                    file_name="otimizacao_pilares.xlsx",
                    mime="application/vnd.ms-excel",
                    type="primary"
                )
elif upload_dxf is None:
    st.info("👈 Por favor, carregue o ficheiro de projeto (.utea) e a tabela do Eberick (.dxf) na barra lateral para iniciar o dimensionamento estrutural.")
