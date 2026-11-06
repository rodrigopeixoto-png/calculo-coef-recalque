import streamlit as st
import pandas as pd
import numpy as np
import io
import json
import re
import os
import tempfile
import ezdxf
import ifcopenshell

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

# -----------------------------------------------------------------------------import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import io
import json
import re
import os
import tempfile
import ezdxf
import ifcopenshell
from matplotlib.patches import Rectangle, Circle

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

# -----------------------------------------------------------------------------
# DICIONÁRIO GEOTÉCNICO E CONSTANTES
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
# LEITURA DO DXF
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
                    'Pilar': nome, 'Carga Vertical (tf)': carga_pilar, 'X': x_p, 'Y': y_p
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
# CÁLCULOS GEOTÉCNICOS E ESTRUTURAIS
# -----------------------------------------------------------------------------
def calcular_curva_capacidade(df_spt, B, metodo_construtivo, secao, criterio_q_adm, cota_assentamento):
    df = df_spt.copy()
    df = df.dropna(subset=['N_SPT']).copy()
    if df.empty: return None, 0.0
        
    df["N_SPT"] = pd.to_numeric(df["N_SPT"], errors="coerce").fillna(1)
    df["Tipo de Solo"] = df["Tipo de Solo"].fillna("Argila")
    
    mascara_aterro_fraco = (df["Tipo de Solo"] == "Aterro") & (df["N_SPT"] < 2)
    df.loc[mascara_aterro_fraco, "N_SPT"] = 2
    df["N_corr"] = df["N_SPT"].apply(lambda x: min(x, 50))
    
    df = df[df["Profundidade (m)"] > cota_assentamento].copy()
    if df.empty: return None, 0.0
    
    Area_c = (np.pi * B**2) / 4 if secao == "Circular" else B**2
    Perimetro = np.pi * B if secao == "Circular" else 4 * B
    f1, f2 = FATORES_CONSTRUTIVOS[metodo_construtivo]["F1"], FATORES_CONSTRUTIVOS[metodo_construtivo]["F2"]

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

    if "Escavada" in metodo_construtivo: alfa_dq, beta_dq, beta_t = 0.5, 0.8, 5.0
    elif "Hélice" in metodo_construtivo or "Raiz" in metodo_construtivo: alfa_dq, beta_dq, beta_t = 0.3, 1.0, 6.0
    else: alfa_dq, beta_dq, beta_t = 1.0, 1.0, 8.0

    def calc_aoki(row):
        solo = PARAMETROS_SOLO.get(row["Tipo de Solo"], PARAMETROS_SOLO["Argila"])
        rl = (solo["aoki_alpha"] * solo["aoki_K"] * row["N_corr"]) / f2
        rp = (solo["aoki_K"] * row["N_corr"]) / f1 * Area_c
        return pd.Series([rp, rl * Perimetro * 1.0])

    df[["Rp_aoki", "delta_Rl_aoki"]] = df.apply(calc_aoki, axis=1)

    df["N_dq"] = df["N_corr"].apply(lambda x: max(3, min(x, 50)))
    df["C_dq"] = df["Tipo de Solo"].apply(get_dq_c)
    df["delta_Rl_dq"] = beta_dq * 10 * ((df["N_dq"] / 3) + 1) * Perimetro * 1.0
    df["Rp_dq"] = alfa_dq * df["C_dq"] * df["N_corr"] * Area_c
    
    df["alpha_teix"] = df["Tipo de Solo"].apply(get_teix_alpha)
    df["delta_Rl_t"] = beta_t * df["N_corr"] * Perimetro * 1.0
    df["Rp_t"] = df["alpha_teix"] * df["N_corr"] * Area_c

    mascara_aterro = df["Tipo de Solo"] == "Aterro"
    P_neg_adotado = 0.0
    if mascara_aterro.any():
        P_neg_aoki, P_neg_dq, P_neg_t = df.loc[mascara_aterro, "delta_Rl_aoki"].sum(), df.loc[mascara_aterro, "delta_Rl_dq"].sum(), df.loc[mascara_aterro, "delta_Rl_t"].sum()
        df.loc[mascara_aterro, ["delta_Rl_aoki", "delta_Rl_dq", "delta_Rl_t"]] = 0.0
        P_neg_adotado = (P_neg_aoki + P_neg_dq + P_neg_t) / 3.0 if criterio_q_adm == "Média dos Métodos" else max(P_neg_aoki, P_neg_dq, P_neg_t)

    df["Rc_Aoki"] = (df["Rp_aoki"] + df["delta_Rl_aoki"].cumsum()) / 2.0
    df["Rc_DQ"] = (df["Rp_dq"] + df["delta_Rl_dq"].cumsum()) / 2.0
    df["Rc_Teix"] = (df["Rp_t"] + df["delta_Rl_t"].cumsum()) / 2.0

    if criterio_q_adm == "Média dos Métodos": df["Rc_Adotada"] = (df["Rc_Aoki"] + df["Rc_DQ"] + df["Rc_Teix"]) / 3.0
    elif criterio_q_adm == "Menor Valor (Mais Conservador)": df["Rc_Adotada"] = df[["Rc_Aoki", "Rc_DQ", "Rc_Teix"]].min(axis=1)
    elif criterio_q_adm == "Apenas Aoki-Velloso": df["Rc_Adotada"] = df["Rc_Aoki"]
    elif criterio_q_adm == "Apenas Décourt-Quaresma": df["Rc_Adotada"] = df["Rc_DQ"]
    elif criterio_q_adm == "Apenas Teixeira": df["Rc_Adotada"] = df["Rc_Teix"]

    return df, P_neg_adotado

def plot_planta(df_resultados, B, secao):
    if df_resultados.empty: return None
    
    fig, ax = plt.subplots(figsize=(8, 6))
    for _, row in df_resultados.iterrows():
        x, y = row['X'], row['Y']
        status = row['Status']
        cor = '#22c55e' if 'OK' in status else '#ef4444' # Verde se OK, Vermelho se Falha
        
        if secao == "Circular":
            ax.add_patch(Circle((x, y), B/2, color=cor, alpha=0.6))
            ax.add_patch(Circle((x, y), B/2, fill=False, color='black', lw=1))
        else:
            ax.add_patch(Rectangle((x - B/2, y - B/2), B, B, color=cor, alpha=0.6))
            ax.add_patch(Rectangle((x - B/2, y - B/2), B, B, fill=False, color='black', lw=1))
            
        ax.text(x, y + B/2 + 0.1, row['Pilar'], ha='center', va='bottom', fontsize=8, fontweight='bold')
        
    # Auto-escala do gráfico
    ax.set_aspect('equal')
    ax.autoscale_view()
    ax.grid(True, linestyle='--', alpha=0.3)
    ax.set_title(f"Planta de Fundações - Estacas {secao} (B = {B}m)", pad=20)
    ax.set_xlabel("Eixo X (m)")
    ax.set_ylabel("Eixo Y (m)")
    fig.tight_layout()
    return fig

# -----------------------------------------------------------------------------
# FUNÇÕES DE EXPORTAÇÃO (PDF E IFC)
# -----------------------------------------------------------------------------
def gerar_pdf_estrutural(df_res, furo_base, B, secao, construtivo):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story, styles = [], getSampleStyleSheet()

    story.append(Paragraph("<b>MEMORIAL DE OTIMIZAÇÃO ESTRUTURAL DOS PILARES</b>", styles['Heading1']))
    story.append(Paragraph(f"<b>Furo Base Adotado:</b> {furo_base}", styles['Normal']))
    story.append(Paragraph(f"<b>Tipo de Fundação:</b> Estaca {construtivo} ({secao} - B={B:.2f}m)", styles['Normal']))
    story.append(Spacer(1, 20))

    t_data = [["Pilar", "Carga (kN)", "Atrito Neg. (kN)", "Total (kN)", "Profundidade (m)", "Status"]]
    for _, r in df_res.iterrows():
        t_data.append([r['Pilar'], r['Carga Atuante (kN)'], str(r['Atrito Negativo (kN)']), r['Carga Total (kN)'], str(r['Profundidade da Estaca (m)']), r['Status']])
    
    t = Table(t_data, colWidths=[60, 80, 100, 80, 100, 100])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1E3A8A')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey)
    ]))
    story.append(t)
    doc.build(story)
    return buffer.getvalue()

def gerar_ifc_estrutural(df_res, B, secao, cota_assentamento):
    try:
        model = ifcopenshell.file()
        project = model.createIfcProject(GlobalId=ifcopenshell.guid.new(), Name="Fundações UTEA")
        context = model.createIfcGeometricRepresentationContext(ContextType="Model", CoordinateSpaceDimension=3)
        
        # Rotina simplificada de marcação do IFC
        buffer = io.BytesIO()
        model.write(buffer)
        return buffer.getvalue()
    except Exception as e:
        return b"Erro ao gerar IFC: " + str(e).encode()

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
cota_assentamento = st.sidebar.number_input("Cota de Arrasamento (m)", min_value=0.0, value=0.0, step=0.5)
criterio_q_adm = st.sidebar.selectbox("Critério de Carga:", ["Média dos Métodos", "Menor Valor (Mais Conservador)", "Apenas Aoki-Velloso", "Apenas Décourt-Quaresma", "Apenas Teixeira"])

st.sidebar.markdown("---")
st.sidebar.header("4. 🔧 Parâmetros de Armadura (Opcional)")
fck = st.sidebar.number_input("Resistência do Concreto (fck) em MPa", min_value=15.0, value=25.0, step=5.0)
fyk = st.sidebar.number_input("Resistência do Aço (fyk) em MPa", min_value=250.0, value=500.0, step=50.0)
taxa_armadura = st.sidebar.number_input("Taxa de Armadura Longitudinal (%)", min_value=0.1, value=0.5, step=0.1)

# -----------------------------------------------------------------------------
# PROCESSAMENTO DOS DADOS E ABAS
# -----------------------------------------------------------------------------
if upload_dxf is not None and furo_base_selecionado is not None:
    with st.spinner("A processar Tabela DXF e Geometria..."):
        df_cargas, erro_dxf = processar_dxf(upload_dxf.getvalue())
        
        if erro_dxf == "DIAGNOSTICO":
            st.error("⚠️ O DXF foi lido, mas não consegui detetar o padrão dos pilares. Veja os textos extraídos:")
            st.dataframe(df_cargas)
        elif erro_dxf != "":
            st.error(erro_dxf)
        else:
            df_furo_base = projeto_furos[furo_base_selecionado]
            df_curva, P_neg = calcular_curva_capacidade(df_furo_base, B, metodo_construtivo, secao, criterio_q_adm, cota_assentamento)
            
            if df_curva is None or df_curva.empty:
                st.error("O furo selecionado não tem dados válidos abaixo da Cota de Arrasamento.")
            else:
                prof_maxima = df_curva["Profundidade (m)"].max()
                cap_maxima = df_curva["Rc_Adotada"].iloc[-1]
                
                resultados_finais = []
                for _, pilar in df_cargas.iterrows():
                    nome = pilar["Pilar"]
                    carga_pura = pilar["Carga Vertical (kN)"]
                    carga_total = carga_pura + P_neg
                    
                    if carga_total > cap_maxima:
                        prof_necessaria = f"FALHA (> {prof_maxima}m)"
                        status = "❌ Aumentar Secção"
                    else:
                        linha_ideal = df_curva[df_curva["Rc_Adotada"] >= carga_total].iloc[0]
                        prof_necessaria = linha_ideal["Profundidade (m)"]
                        status = "✅ OK"
                        
                    resultados_finais.append({
                        "Pilar": nome, "X": pilar["X"], "Y": pilar["Y"],
                        "Carga Atuante (kN)": f"{carga_pura:.1f}",
                        "Atrito Negativo (kN)": f"{P_neg:.1f}" if P_neg > 0 else "-",
                        "Carga Total (kN)": f"{carga_total:.1f}",
                        "Furo Adotado": furo_base_selecionado,
                        "Profundidade da Estaca (m)": prof_necessaria,
                        "Status": status
                    })
                
                df_resultados = pd.DataFrame(resultados_finais)
                
                # --- INTERFACE COM ABAS ---
                tab_tabela, tab_planta = st.tabs(["📋 Relatório de Otimização", "🗺️ Visualização em Planta"])
                
                with tab_tabela:
                    st.success(f"Foram processados {len(df_cargas)} pilares!")
                    st.write(f"Todos os pilares foram cruzados com a capacidade do **{furo_base_selecionado}**. Diâmetro adotado: **{B:.2f}m**.")
                    st.dataframe(df_resultados.drop(columns=['X', 'Y']), use_container_width=True, hide_index=True)
                    
                    st.markdown("---")
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        csv_bytes = df_resultados.drop(columns=['X', 'Y']).to_csv(index=False, sep=';', decimal=',').encode('utf-8-sig')
                        st.download_button("📥 Tabela Excel (CSV)", data=csv_bytes, file_name="otimizacao_pilares.csv", mime="text/csv", use_container_width=True)
                    with c2:
                        pdf_bytes = gerar_pdf_estrutural(df_resultados, furo_base_selecionado, B, secao, metodo_construtivo)
                        st.download_button("📄 Memorial (PDF)", data=pdf_bytes, file_name="memorial_pilares.pdf", mime="application/pdf", use_container_width=True)
                    with c3:
                        ifc_bytes = gerar_ifc_estrutural(df_resultados, B, secao, cota_assentamento)
                        st.download_button("🧱 Modelo 3D (IFC)", data=ifc_bytes, file_name="fundacoes.ifc", mime="application/octet-stream", use_container_width=True)
                
                with tab_planta:
                    st.markdown("### Locação dos Pilares e Status de Capacidade")
                    fig_planta = plot_planta(df_resultados, B, secao)
                    if fig_planta:
                        st.pyplot(fig_planta)

elif upload_dxf is None:
    st.info("👈 Por favor, carregue o ficheiro de projeto (.utea) e a tabela do Eberick (.dxf) na barra lateral para iniciar.")
# DICIONÁRIO GEOTÉCNICO E CONSTANTES
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
# FUNÇÃO DE LEITURA DO DXF (CAPTURANDO X e Y PARA O IFC)
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
        if df_textos.empty:
            return pd.DataFrame(), "O arquivo DXF não contém entidades de texto válidas."

        df_pilares = df_textos[df_textos['Texto'].str.match(r'^P\s*[-_]?\s*\d+$', case=False, na=False)].copy()
        if df_pilares.empty:
            return df_textos, "DIAGNOSTICO"

        y_valores_unicos = np.sort(df_textos['Y'].unique())
        diferencas_y = np.diff(y_valores_unicos)
        diferencas_y = diferencas_y[diferencas_y > 0.1]
        tolerancia_y = min(diferencas_y) * 0.45 if len(diferencas_y) > 0 else 1.0

        dados_pilares = []
        
        for _, pilar in df_pilares.iterrows():
            nome = pilar['Texto']
            y_p = pilar['Y']
            x_p = pilar['X']
            
            textos_linha = df_textos[
                (abs(df_textos['Y'] - y_p) <= tolerancia_y) & 
                (df_textos['X'] > x_p)
            ].sort_values(by='X')
            
            carga_pilar = None
            for _, txt_cand in textos_linha.iterrows():
                val_str = txt_cand['Texto'].replace(',', '.')
                if 'x' in val_str.lower() or 'X' in val_str:
                    continue
                try:
                    carga_val = float(val_str)
                    if carga_val > 0:
                        carga_pilar = carga_val
                        break
                except ValueError:
                    continue
                    
            if carga_pilar is not None:
                dados_pilares.append({
                    'Pilar': nome,
                    'Carga Vertical (tf)': carga_pilar,
                    'X': x_p,
                    'Y': y_p
                })

        df_final = pd.DataFrame(dados_pilares)
        if df_final.empty:
            return df_textos, "DIAGNOSTICO" 
            
        df_final['Carga Vertical (kN)'] = df_final['Carga Vertical (tf)'] * 10
        return df_final, ""
    except Exception as e:
        return pd.DataFrame(), f"Erro ao processar o ficheiro DXF: {e}"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except: pass

# -----------------------------------------------------------------------------
# MOTOR GEOTÉCNICO SIMPLIFICADO
# -----------------------------------------------------------------------------
def calcular_curva_capacidade(df_spt, B, metodo_construtivo, secao, criterio_q_adm, cota_assentamento):
    df = df_spt.copy()
    df = df.dropna(subset=['N_SPT']).copy()
    if df.empty: return None, 0.0
        
    df["N_SPT"] = pd.to_numeric(df["N_SPT"], errors="coerce").fillna(1)
    df["Tipo de Solo"] = df["Tipo de Solo"].fillna("Argila")
    
    mascara_aterro_fraco = (df["Tipo de Solo"] == "Aterro") & (df["N_SPT"] < 2)
    df.loc[mascara_aterro_fraco, "N_SPT"] = 2
    df["N_corr"] = df["N_SPT"].apply(lambda x: min(x, 50))
    
    df = df[df["Profundidade (m)"] > cota_assentamento].copy()
    if df.empty: return None, 0.0
    
    Area_c = (np.pi * B**2) / 4 if secao == "Circular" else B**2
    Perimetro = np.pi * B if secao == "Circular" else 4 * B
    f1, f2 = FATORES_CONSTRUTIVOS[metodo_construtivo]["F1"], FATORES_CONSTRUTIVOS[metodo_construtivo]["F2"]

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

    if "Escavada" in metodo_construtivo: alfa_dq, beta_dq, beta_t = 0.5, 0.8, 5.0
    elif "Hélice" in metodo_construtivo or "Raiz" in metodo_construtivo: alfa_dq, beta_dq, beta_t = 0.3, 1.0, 6.0
    else: alfa_dq, beta_dq, beta_t = 1.0, 1.0, 8.0

    def calc_aoki(row):
        solo = PARAMETROS_SOLO.get(row["Tipo de Solo"], PARAMETROS_SOLO["Argila"])
        rl = (solo["aoki_alpha"] * solo["aoki_K"] * row["N_corr"]) / f2
        rp = (solo["aoki_K"] * row["N_corr"]) / f1 * Area_c
        return pd.Series([rp, rl * Perimetro * 1.0])

    df[["Rp_aoki", "delta_Rl_aoki"]] = df.apply(calc_aoki, axis=1)

    df["N_dq"] = df["N_corr"].apply(lambda x: max(3, min(x, 50)))
    df["C_dq"] = df["Tipo de Solo"].apply(get_dq_c)
    df["delta_Rl_dq"] = beta_dq * 10 * ((df["N_dq"] / 3) + 1) * Perimetro * 1.0
    df["Rp_dq"] = alfa_dq * df["C_dq"] * df["N_corr"] * Area_c
    
    df["alpha_teix"] = df["Tipo de Solo"].apply(get_teix_alpha)
    df["delta_Rl_t"] = beta_t * df["N_corr"] * Perimetro * 1.0
    df["Rp_t"] = df["alpha_teix"] * df["N_corr"] * Area_c

    mascara_aterro = df["Tipo de Solo"] == "Aterro"
    P_neg_adotado = 0.0
    if mascara_aterro.any():
        P_neg_aoki, P_neg_dq, P_neg_t = df.loc[mascara_aterro, "delta_Rl_aoki"].sum(), df.loc[mascara_aterro, "delta_Rl_dq"].sum(), df.loc[mascara_aterro, "delta_Rl_t"].sum()
        df.loc[mascara_aterro, ["delta_Rl_aoki", "delta_Rl_dq", "delta_Rl_t"]] = 0.0
        P_neg_adotado = (P_neg_aoki + P_neg_dq + P_neg_t) / 3.0 if criterio_q_adm == "Média dos Métodos" else max(P_neg_aoki, P_neg_dq, P_neg_t)

    df["Rc_Aoki"] = (df["Rp_aoki"] + df["delta_Rl_aoki"].cumsum()) / 2.0
    df["Rc_DQ"] = (df["Rp_dq"] + df["delta_Rl_dq"].cumsum()) / 2.0
    df["Rc_Teix"] = (df["Rp_t"] + df["delta_Rl_t"].cumsum()) / 2.0

    if criterio_q_adm == "Média dos Métodos": df["Rc_Adotada"] = (df["Rc_Aoki"] + df["Rc_DQ"] + df["Rc_Teix"]) / 3.0
    elif criterio_q_adm == "Menor Valor (Mais Conservador)": df["Rc_Adotada"] = df[["Rc_Aoki", "Rc_DQ", "Rc_Teix"]].min(axis=1)
    elif criterio_q_adm == "Apenas Aoki-Velloso": df["Rc_Adotada"] = df["Rc_Aoki"]
    elif criterio_q_adm == "Apenas Décourt-Quaresma": df["Rc_Adotada"] = df["Rc_DQ"]
    elif criterio_q_adm == "Apenas Teixeira": df["Rc_Adotada"] = df["Rc_Teix"]

    return df, P_neg_adotado

# -----------------------------------------------------------------------------
# FUNÇÕES DE EXPORTAÇÃO (PDF E IFC)
# -----------------------------------------------------------------------------
def gerar_pdf_estrutural(df_res, furo_base, B, secao, construtivo):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story, styles = [], getSampleStyleSheet()

    story.append(Paragraph("<b>MEMORIAL DE OTIMIZAÇÃO ESTRUTURAL DOS PILARES</b>", styles['Heading1']))
    story.append(Paragraph(f"<b>Furo Base Adotado:</b> {furo_base}", styles['Normal']))
    story.append(Paragraph(f"<b>Tipo de Fundação:</b> Estaca {construtivo} ({secao} - B={B:.2f}m)", styles['Normal']))
    story.append(Spacer(1, 20))

    t_data = [["Pilar", "Carga (kN)", "Atrito Neg. (kN)", "Total (kN)", "Profundidade (m)", "Status"]]
    for _, r in df_res.iterrows():
        t_data.append([r['Pilar'], r['Carga Atuante (kN)'], r['Atrito Negativo (kN)'], r['Carga Total (kN)'], str(r['Profundidade da Estaca (m)']), r['Status']])
    
    t = Table(t_data, colWidths=[60, 80, 100, 80, 100, 100])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1E3A8A')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey)
    ]))
    story.append(t)
    doc.build(story)
    return buffer.getvalue()

def gerar_ifc_estrutural(df_res, B, secao, cota_assentamento):
    # Template IFC Básico (Para modelos com ifcopenshell)
    try:
        model = ifcopenshell.file()
        project = model.createIfcProject(GlobalId=ifcopenshell.guid.new(), Name="Fundações UTEA")
        context = model.createIfcGeometricRepresentationContext(ContextType="Model", CoordinateSpaceDimension=3)
        
        for _, r in df_res.iterrows():
            prof = r['Profundidade da Estaca (m)']
            if isinstance(prof, str) and "FALHA" in prof: continue
            
            x, y = float(r['X']), float(r['Y'])
            z_top = float(cota_assentamento)
            depth = float(prof)
            
            # Aqui entraria a geração de IfcPile e ExtrudedAreaSolid com ifcopenshell.api
            # (Em produção, o modelo seria totalmente populado)
            
        buffer = io.BytesIO()
        model.write(buffer)
        return buffer.getvalue()
    except Exception as e:
        return b"Erro ao gerar IFC: " + str(e).encode()

# -----------------------------------------------------------------------------
# INTERFACE PRINCIPAL
# -----------------------------------------------------------------------------
st.title("🏗️ Módulo Estrutural - Otimização de Pilares")
st.write("Mapeie as cargas do Eberick (DXF) e encontre a profundidade ideal da estaca para cada pilar.")

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
cota_assentamento = st.sidebar.number_input("Cota de Arrasamento (m)", min_value=0.0, value=0.0, step=0.5)
criterio_q_adm = st.sidebar.selectbox("Critério de Carga:", ["Média dos Métodos", "Menor Valor (Mais Conservador)", "Apenas Aoki-Velloso", "Apenas Décourt-Quaresma", "Apenas Teixeira"])

# -----------------------------------------------------------------------------
# PROCESSAMENTO DOS DADOS
# -----------------------------------------------------------------------------
if upload_dxf is not None and furo_base_selecionado is not None:
    with st.spinner("A ler o DXF com motor de Auto-escala..."):
        df_cargas, erro_dxf = processar_dxf(upload_dxf.getvalue())
        
        if erro_dxf == "DIAGNOSTICO":
            st.error("⚠️ O DXF foi lido, mas não consegui detetar o padrão dos pilares. Veja abaixo os textos extraídos:")
            st.dataframe(df_cargas)
        elif erro_dxf != "":
            st.error(erro_dxf)
        else:
            st.success(f"Tabela de cargas processada com sucesso! {len(df_cargas)} pilares encontrados.")
            
            df_furo_base = projeto_furos[furo_base_selecionado]
            df_curva, P_neg = calcular_curva_capacidade(df_furo_base, B, metodo_construtivo, secao, criterio_q_adm, cota_assentamento)
            
            if df_curva is None or df_curva.empty:
                st.error("O furo selecionado não tem dados válidos abaixo da Cota de Arrasamento especificada.")
            else:
                prof_maxima = df_curva["Profundidade (m)"].max()
                cap_maxima = df_curva["Rc_Adotada"].iloc[-1]
                
                resultados_finais = []
                for _, pilar in df_cargas.iterrows():
                    nome = pilar["Pilar"]
                    carga_pura = pilar["Carga Vertical (kN)"]
                    carga_total = carga_pura + P_neg
                    
                    if carga_total > cap_maxima:
                        prof_necessaria = f"FALHA (> {prof_maxima}m)"
                        status = "❌ Aumentar Secção"
                    else:
                        linha_ideal = df_curva[df_curva["Rc_Adotada"] >= carga_total].iloc[0]
                        prof_necessaria = linha_ideal["Profundidade (m)"]
                        status = "✅ OK"
                        
                    resultados_finais.append({
                        "Pilar": nome,
                        "X": pilar["X"],
                        "Y": pilar["Y"],
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
                
                # Ocultar X e Y na tabela visual da Interface para ficar mais limpo
                st.dataframe(df_resultados.drop(columns=['X', 'Y']), use_container_width=True, hide_index=True)
                
                # --- BOTÕES DE EXPORTAÇÃO ---
                st.markdown("---")
                c1, c2, c3 = st.columns(3)
                
                with c1:
                    csv_bytes = df_resultados.drop(columns=['X', 'Y']).to_csv(index=False, sep=';', decimal=',').encode('utf-8-sig')
                    st.download_button("📥 Tabela Excel (CSV)", data=csv_bytes, file_name="otimizacao_pilares.csv", mime="text/csv", use_container_width=True)
                
                with c2:
                    pdf_bytes = gerar_pdf_estrutural(df_resultados, furo_base_selecionado, B, secao, metodo_construtivo)
                    st.download_button("📄 Memorial (PDF)", data=pdf_bytes, file_name="memorial_pilares.pdf", mime="application/pdf", use_container_width=True)
                
                with c3:
                    ifc_bytes = gerar_ifc_estrutural(df_resultados, B, secao, cota_assentamento)
                    st.download_button("🧱 Modelo 3D (IFC)", data=ifc_bytes, file_name="fundacoes.ifc", mime="application/octet-stream", use_container_width=True)

elif upload_dxf is None:
    st.info("👈 Por favor, carregue o ficheiro de projeto (.utea) e a tabela do Eberick (.dxf) na barra lateral para iniciar o dimensionamento estrutural.")
