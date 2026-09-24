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
    st.error("A biblioteca 'ezdxf' não está instalada. Adicione 'ezdxf' ao requirements.txt e faça reboot!")

try:
    import ifcopenshell
    from ifcopenshell.api import run
    HAS_BIM = True
except ImportError:
    HAS_BIM = False

st.set_page_config(page_title="Gestor BIM e Orçamento - Fundações", page_icon="🏢", layout="wide")

# -----------------------------------------------------------------------------
# DICIONÁRIO GEOTÉCNICO
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

def get_dq_c(s): return 400 if "areia" in str(s).lower() else (200 if "silte" in str(s).lower() else 120)
def get_teix_alpha(s): return 250 if "areia" in str(s).lower() else (200 if "silte" in str(s).lower() else 150)

def calcular_profundidade_estaca(df_spt_raw, diametro_m, carga_alvo_kn, criterio="Média dos Métodos", prof_minima=6.0):
    df_spt = df_spt_raw.copy()
    df_spt["Profundidade (m)"] = pd.to_numeric(df_spt["Profundidade (m)"], errors='coerce').fillna(0)
    df_spt["N_SPT"] = pd.to_numeric(df_spt["N_SPT"], errors="coerce").fillna(1)
    df_spt["Tipo de Solo"] = df_spt["Tipo de Solo"].fillna("Argila")
    df_spt["N_corr"] = df_spt["N_SPT"].apply(lambda x: min(x, 50))
    
    Area_c = (np.pi * diametro_m**2) / 4 
    Perimetro = np.pi * diametro_m 
    f1, f2, alfa_dq, beta_dq, beta_t = 2.0, 4.0, 0.3, 1.0, 6.0 

    def proc_solo_aoki(row):
        solo = PARAMETROS_SOLO.get(row["Tipo de Solo"], PARAMETROS_SOLO["Argila"])
        rl = (solo["aoki_alpha"] * solo["aoki_K"] * row["N_corr"]) / f2
        rp = (solo["aoki_K"] * row["N_corr"]) / f1 * Area_c
        return pd.Series([rl * Perimetro * 1.0, rp])

    df_spt[["delta_Rl_aoki", "Rp_aoki"]] = df_spt.apply(proc_solo_aoki, axis=1)
    df_spt["Rc Aoki"] = (df_spt["Rp_aoki"] + df_spt["delta_Rl_aoki"].cumsum()) / 2.0
    
    df_spt["N_dq"] = df_spt["N_corr"].apply(lambda x: max(3, min(x, 50)))
    df_spt["C_dq"] = df_spt["Tipo de Solo"].apply(get_dq_c)
    df_spt["Rc DQ"] = ((alfa_dq * df_spt["C_dq"] * df_spt["N_corr"] * Area_c) + (beta_dq * 10 * ((df_spt["N_dq"] / 3) + 1) * Perimetro).cumsum()) / 2.0
    
    df_spt["alpha_teix"] = df_spt["Tipo de Solo"].apply(get_teix_alpha)
    df_spt["Rc Teix"] = ((df_spt["alpha_teix"] * df_spt["N_corr"] * Area_c) + (beta_t * df_spt["N_corr"] * Perimetro).cumsum()) / 2.0

    df_spt["Rc Média"] = (df_spt["Rc Aoki"] + df_spt["Rc DQ"] + df_spt["Rc Teix"]) / 3.0
    df_spt["Rc Menor"] = df_spt[["Rc Aoki", "Rc DQ", "Rc Teix"]].min(axis=1)

    col_adotada = "Rc Média" if criterio == "Média dos Métodos" else ("Rc Menor" if criterio == "Menor Valor (Mais Conservador)" else ("Rc Aoki" if "Aoki" in criterio else ("Rc DQ" if "Décourt" in criterio else "Rc Teix")))

    df_suficiente = df_spt[df_spt[col_adotada] >= carga_alvo_kn]
    
    prof_calc = df_suficiente.iloc[0]["Profundidade (m)"] if len(df_suficiente) > 0 else df_spt["Profundidade (m)"].max()
    return max(prof_calc, prof_minima)

def calcular_peso_aco_estaca(diametro_m, prof_m, taxa_armadura, bitola_long, bitola_estribo, espacamento, l_manual):
    Area_c = (np.pi * diametro_m**2) / 4
    area_barra = (np.pi * (bitola_long / 1000)**2) / 4  
    n_barras = max(int(np.ceil((taxa_armadura / 100) * Area_c / area_barra)), 6)
    As_total = n_barras * area_barra
    
    L_arm = prof_m if l_manual is None else min(l_manual, prof_m)
    
    peso_long = As_total * L_arm * 7850
    qtd_estribos = int(L_arm / (espacamento / 100))
    peso_estribo = qtd_estribos * (np.pi * (diametro_m - 0.10)) * ((np.pi * (bitola_estribo / 1000)**2) / 4) * 7850
    
    return peso_long, peso_estribo, n_barras, L_arm

# -----------------------------------------------------------------------------
# RADAR GEOMÉTRICO (DXF)
# -----------------------------------------------------------------------------
def extrair_tabela_do_dxf(dxf_bytes):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp:
        tmp.write(dxf_bytes)
        tmp_path = tmp.name
    try: doc = ezdxf.readfile(tmp_path)
    finally:
        if os.path.exists(tmp_path): os.remove(tmp_path)
    
    textos_brutos = []
    def limpar_texto(txt):
        return re.sub(r'\\[A-Za-z0-9~]+;', '', str(txt).replace('\\P', ' ').replace('\\p', ' ')).strip().replace('{', '').replace('}', '')

    for e in doc.modelspace():
        if e.dxftype() in ('TEXT', 'MTEXT'):
            t = limpar_texto(e.dxf.text if e.dxftype() == 'TEXT' else e.text)
            if t: textos_brutos.append({'Texto': t, 'X': e.dxf.insert.x, 'Y': e.dxf.insert.y})
        elif e.dxftype() == 'INSERT':
            for attrib in e.attribs:
                t = limpar_texto(attrib.dxf.text)
                if t: textos_brutos.append({'Texto': t, 'X': attrib.dxf.insert.x, 'Y': attrib.dxf.insert.y})
            block = doc.blocks.get(e.dxf.name)
            if block:
                for entity in block.query('TEXT MTEXT'):
                    t = limpar_texto(entity.dxf.text if entity.dxftype() == 'TEXT' else entity.text)
                    if t: textos_brutos.append({'Texto': t, 'X': e.dxf.insert.x + entity.dxf.insert.x, 'Y': e.dxf.insert.y + entity.dxf.insert.y})

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
    tolerancia_y = np.median([abs(y_vals[i] - y_vals[i+1]) for i in range(len(y_vals)-1)]) * 0.40 if len(y_vals) > 1 else 15.0
    
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
# MOTOR DE EXPORTAÇÃO BIM (.IFC4)
# -----------------------------------------------------------------------------
def gerar_modelo_ifc(df_projeto):
    model = ifcopenshell.file(schema="IFC4")
    
    project = run("root.create_entity", model, ifc_class="IfcProject", name="Projeto BIM - UTEA Fundações")
    context = run("context.add_context", model, context_type="Model")
    body = run("context.add_context", model, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=context)
    
    site = run("root.create_entity", model, ifc_class="IfcSite", name="Terreno")
    run("aggregate.assign_object", model, relating_object=project, products=[site])
    
    building = run("root.create_entity", model, ifc_class="IfcBuilding", name="Fundações Profundas")
    run("aggregate.assign_object", model, relating_object=site, products=[building])
    
    for idx, row in df_projeto.iterrows():
        diam = row.get('Diametro_m', 0.5)
        prof = row.get('Profundidade_m', 12.0)
        ne = int(row.get('ne', 1))
        x_base = row.get('X_m', 0)
        y_base = row.get('Y_m', 0)
        
        peso_l_estaca = row.get('Peso_Long_Estaca_kg', 0)
        peso_e_estaca = row.get('Peso_Estribo_Estaca_kg', 0)
        bitola_l = row.get('Bitola_Long_mm', 10.0)
        bitola_e = row.get('Bitola_Estribo_mm', 5.0)
        fck_val = row.get('Fck_MPa', 25)
        vol_concreto_estaca = row.get('Vol_Concreto_m3', 0) / ne
        
        for i in range(ne):
            if ne == 1:
                dx, dy = 0.0, 0.0
            else:
                raio_distribuicao = 1.5 * diam 
                angle = i * (2 * np.pi / ne)
                dx = raio_distribuicao * np.cos(angle)
                dy = raio_distribuicao * np.sin(angle)
            
            nome_estaca = f"Estaca_{row['Pilar']}" if ne == 1 else f"Estaca_{row['Pilar']}_{i+1}"
            pile = run("root.create_entity", model, ifc_class="IfcPile", name=nome_estaca)
            
            run("spatial.assign_container", model, relating_structure=building, products=[pile])
            
            # Aqui fica o Radius bloqueado na geometria do modelo
            pt = model.createIfcCartesianPoint((0.0, 0.0))
            dir2d = model.createIfcDirection((1.0, 0.0))
            axis2d = model.createIfcAxis2Placement2D(pt, dir2d)
            profile = model.createIfcCircleProfileDef("AREA", None, axis2d, float(diam / 2.0))
            
            pt_3d = model.createIfcCartesianPoint((0.0, 0.0, 0.0))
            dir_z = model.createIfcDirection((0.0, 0.0, 1.0))
            dir_x = model.createIfcDirection((1.0, 0.0, 0.0))
            placement_3d = model.createIfcAxis2Placement3D(pt_3d, dir_z, dir_x)
            
            solid = model.createIfcExtrudedAreaSolid(profile, placement_3d, dir_z, float(prof))
            shape_rep = model.createIfcShapeRepresentation(context, "Body", "SweptSolid", [solid])
            prod_def = model.createIfcProductDefinitionShape(None, None, [shape_rep])
            pile.Representation = prod_def
            
            pt_loc = model.createIfcCartesianPoint((float(x_base + dx), float(y_base + dy), float(-prof)))
            loc_placement = model.createIfcAxis2Placement3D(pt_loc, dir_z, dir_x)
            local_placement = model.createIfcLocalPlacement(None, loc_placement)
            pile.ObjectPlacement = local_placement
            
            # Injetamos o "Diametro" exato na raiz do Pset para fácil extração no Visus
            try:
                pset = run("pset.add_pset", model, product=pile, name="Pset_PileCommon")
                run("pset.edit_pset", model, pset=pset, properties={
                    "Reference": str(row['Pilar']),
                    "LoadBearing": True,
                    "Carga_Aplicada_kN": float(row.get('Carga_por_Estaca_kN', 0)),
                    "Volume_Concreto_m3": float(vol_concreto_estaca),
                    "Classe_Resistencia_Concreto": f"C{int(fck_val)}",
                    "Diametro_Estaca_m": float(diam),
                    "Armadura_Descricao": str(row.get('Armadura_Principal', 'N/A')),
                    "Peso_Aco_Total_kg": float(peso_l_estaca + peso_e_estaca),
                    f"Peso_Aco_Longitudinal_{bitola_l}mm_kg": float(peso_l_estaca),
                    f"Peso_Aco_Estribo_{bitola_e}mm_kg": float(peso_e_estaca)
                })
            except Exception:
                pass 
                
    return model.to_string()


# -----------------------------------------------------------------------------
# INTERFACE PRINCIPAL E BARRA LATERAL
# -----------------------------------------------------------------------------
st.title("🏢 Gestor BIM & Orçamento de Fundações")
st.caption("Dimensionamento 5D automático cruzando CAD, Terreno e Exportação IFC4")

st.sidebar.header("1️⃣ Dados do Terreno Geotécnico")

dados_terreno = {}
furo_selecionado = None
criterio_selecionado = "Média dos Métodos"
conteudo_utea = None

# SINCRONIZAÇÃO AUTOMÁTICA
if 'projeto_geotecnico' in st.session_state and st.session_state['projeto_geotecnico'] is not None:
    st.sidebar.success("🔗 Terreno sincronizado automaticamente do Módulo Geotécnico!")
    conteudo_utea = st.session_state['projeto_geotecnico']
else:
    st.sidebar.info("Projeto geotécnico não sincronizado. Volte à página anterior ou faça upload manual.")
    arquivo_utea = st.sidebar.file_uploader("Ficheiro .utea", type=["utea", "json"])
    if arquivo_utea is not None:
        conteudo_utea = json.loads(arquivo_utea.read().decode('utf-8'))

if conteudo_utea is not None:
    try:
        for nome, info in conteudo_utea.get("furos", {}).items():
            dados_terreno[nome] = pd.DataFrame(info["df"])
        
        if dados_terreno:
            furo_selecionado = st.sidebar.selectbox("Furo Base para Cálculo:", list(dados_terreno.keys()))
            criterio_selecionado = st.sidebar.selectbox("Critério Geotécnico:", ["Média dos Métodos", "Menor Valor", "Apenas Aoki-Velloso", "Apenas Décourt-Quaresma", "Apenas Teixeira"])
    except Exception as e:
        st.sidebar.error(f"Erro ao ler os dados do terreno: {e}")

st.sidebar.markdown("---")
st.sidebar.header("2️⃣ Importar Planta")
arquivo_upload = st.sidebar.file_uploader("Planta do Eberick (.dxf, .xlsx)", type=["dxf", "xlsx", "csv"])

st.sidebar.markdown("---")
st.sidebar.header("3️⃣ Configuração Estrutural e Materiais")
fck_concreto = st.sidebar.selectbox("Classe do Concreto (Fck - MPa)", [20, 25, 30, 35, 40], index=1)
prof_minima_global = st.sidebar.number_input("Profundidade Mínima da Estaca (m)", min_value=1.0, value=6.0, step=0.5)
taxa_armadura = st.sidebar.number_input("Taxa de Armadura Longitudinal (%)", min_value=0.1, value=0.5, step=0.1)
bitola = st.sidebar.selectbox("Bitola Long. (mm)", [10.0, 12.5, 16.0, 20.0, 25.0], index=0)
bitola_estribo = st.sidebar.selectbox("Bitola Estribo (mm)", [5.0, 6.3, 8.0, 10.0], index=1)
espacamento_estribo = st.sidebar.number_input("Espaçamento Estribos (cm)", min_value=5.0, max_value=30.0, value=15.0, step=2.5)

gaiola_tipo = st.sidebar.selectbox("Gaiola", ["Total (Toda a estaca)", "Parcial (Manual)"])
L_armadura_manual = st.sidebar.number_input("Comp. Manual (m)", value=6.0, step=0.5) if gaiola_tipo == "Parcial (Manual)" else None

if 'df_projeto' not in st.session_state: st.session_state.df_projeto = None

if arquivo_upload is not None:
    ext = arquivo_upload.name.split('.')[-1].lower()
    if ext == 'dxf':
        with st.spinner("A varrer DXF..."):
            df_extraido, df_raw_debug = extrair_tabela_do_dxf(arquivo_upload.getvalue())
            if df_extraido is not None and "X_cm" in df_extraido.columns: st.session_state.df_projeto = df_extraido
            else:
                st.sidebar.warning("⚠️ Falha na leitura padronizada.")
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

        profundidades, pesos_aco, detalhes_armadura = [], [], []
        pesos_long_estaca, pesos_estribo_estaca = [], []

        df_spt_atual = dados_terreno[furo_selecionado] if furo_selecionado and furo_selecionado in dados_terreno else None

        for index, row in df.iterrows():
            prof = calcular_profundidade_estaca(df_spt_atual, row["Diametro_m"], row["Carga_por_Estaca_kN"], criterio_selecionado, prof_minima_global) if df_spt_atual is not None else prof_minima_global
            profundidades.append(prof)
            
            peso_long, peso_estribo, num_barras, comp_gaiola = calcular_peso_aco_estaca(row["Diametro_m"], prof, taxa_armadura, bitola, bitola_estribo, espacamento_estribo, L_armadura_manual)
            
            pesos_long_estaca.append(peso_long)
            pesos_estribo_estaca.append(peso_estribo)
            pesos_aco.append((peso_long + peso_estribo) * row["ne"])
            detalhes_armadura.append(f"{num_barras} Φ {bitola} (L={comp_gaiola:.1f}m)")
                
        df["Profundidade_m"] = profundidades
        df["Peso_Aco_kg"] = pesos_aco
        df["Peso_Long_Estaca_kg"] = pesos_long_estaca
        df["Peso_Estribo_Estaca_kg"] = pesos_estribo_estaca
        df["Armadura_Principal"] = detalhes_armadura
        df["Fck_MPa"] = fck_concreto
        df["Bitola_Long_mm"] = bitola
        df["Bitola_Estribo_mm"] = bitola_estribo

        total_blocos = len(df)
        total_estacas = df["ne"].sum()
        df["Metros_Perfurados"] = df["Profundidade_m"] * df["ne"]
        total_metros = df["Metros_Perfurados"].sum()
        df["Vol_Concreto_m3"] = (np.pi * (df["Diametro_m"]**2) / 4) * df["Metros_Perfurados"]
        volume_concreto_total = df["Vol_Concreto_m3"].sum()
        peso_aco_total = df["Peso_Aco_kg"].sum()

        st.subheader("💰 Resumo Executivo da Fundação")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Pilares / Blocos", f"{total_blocos} un")
        c2.metric("Total Perfurado", f"{total_metros:.1f} m", f"Em {total_estacas:.0f} estacas")
        c3.metric("Volume de Concreto", f"{volume_concreto_total:.1f} m³", f"Classe C{fck_concreto}")
        c4.metric("Aço Detalhado (Total)", f"{peso_aco_total:,.1f} kg")

        st.markdown("---")

        st.subheader("🗺️ Planta de Locação - Mapa Topográfico (Profundidades)")
        df["Tamanho_Visual"] = df["Carga_Max_tf"].abs()
        df.loc[df["Tamanho_Visual"] < 5, "Tamanho_Visual"] = 5 
        if "Estaca" not in df.columns: df["Estaca"] = "N/A"

        try:
            fig = px.scatter(
                df, x="X_m", y="Y_m", text="Pilar", size="Tamanho_Visual", color="Profundidade_m", 
                hover_data={"Carga_Max_tf": True, "ne": True, "Diametro_m": True, "Profundidade_m": True, "Armadura_Principal": True, "X_m": False, "Y_m": False, "Tamanho_Visual": False},
                labels={"Carga_Max_tf": "Carga (tf)", "ne": "Estacas", "Profundidade_m": "Prof. (m)", "Armadura_Principal": "Armadura"},
                color_continuous_scale=px.colors.diverging.RdYlBu_r 
            )
            fig.update_traces(textposition='top center', marker=dict(line=dict(width=1, color='DarkSlateGrey')))
            fig.update_layout(height=700, plot_bgcolor='rgba(240, 240, 240, 0.8)', title_text="Mapa de Calor", xaxis=dict(scaleanchor="y", scaleratio=1))
            st.plotly_chart(fig, use_container_width=True)
        except Exception: pass

        with st.expander("👁️ Ver Memória de Cálculo Individual (Pilar a Pilar)", expanded=False):
            df_mostrar = df[["Pilar", "Carga_Max_tf", "ne", "Diametro_m", "Carga_por_Estaca_kN", "Profundidade_m", "Armadura_Principal", "Peso_Aco_kg", "Vol_Concreto_m3"]].copy()
            st.dataframe(df_mostrar, use_container_width=True)

        st.markdown("---")
        st.subheader("🏗️ Exportação para BIM 5D (.IFC4)")
        
        if HAS_BIM:
            if st.button("🚀 Gerar Ficheiro 3D (.IFC4) - Otimizado para Visus", type="primary", use_container_width=True):
                with st.spinner("A modelar as estacas e a compilar mapa de quantidades IFC4..."):
                    try:
                        ifc_string = gerar_modelo_ifc(df)
                        st.success("✅ Modelo BIM gerado com sucesso!")
                        st.download_button(
                            label="⬇️ Baixar Modelo IFC4 (Pronto para Orçamentação)",
                            data=ifc_string.encode('utf-8'),
                            file_name="Projeto_Fundacoes_5D.ifc",
                            mime="application/octet-stream",
                            use_container_width=True
                        )
                    except Exception as e:
                        st.error(f"Erro ao gerar IFC: {e}")
        else:
            st.error("❌ A biblioteca 'ifcopenshell' não foi carregada.")

    else:
        st.warning("⚠️ **DIAGNÓSTICO:** O Radar não encontrou coordenadas na tabela do DXF.")
else:
    st.info("👈 Faça o upload do Terreno (.utea) e da Planta do Eberick (.dxf) na barra lateral para iniciar a integração.")
