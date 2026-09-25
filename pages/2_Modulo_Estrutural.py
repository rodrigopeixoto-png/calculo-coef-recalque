import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import io
import re
import tempfile
import os
import json

# Importações para o PDF Profissional
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

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

st.set_page_config(page_title="Módulo Estrutural e BIM - UTEA", page_icon="🏢", layout="wide")

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

def calcular_profundidade_estaca(df_spt_raw, diametro_m, carga_alvo_kn, criterio, prof_minima, ne, verificar_bulbo):
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
    
    prof_calc = None
    if len(df_suficiente) > 0:
        if verificar_bulbo:
            fator_grupo = np.sqrt(ne) if ne > 1 else 1.0
            zona_influencia_m = max(3.0, 3.0 * diametro_m * fator_grupo)
            for idx in df_suficiente.index:
                prof_teste = df_spt.loc[idx, "Profundidade (m)"]
                spt_ponta = df_spt.loc[idx, "N_SPT"]
                camadas_abaixo = df_spt[(df_spt["Profundidade (m)"] > prof_teste) & 
                                        (df_spt["Profundidade (m)"] <= prof_teste + zona_influencia_m)]
                
                solo_seguro = True
                if len(camadas_abaixo) > 0:
                    spt_minimo_abaixo = camadas_abaixo["N_SPT"].min()
                    if spt_minimo_abaixo <= 3 or spt_minimo_abaixo < (spt_ponta * 0.5):
                        solo_seguro = False
                        
                if solo_seguro:
                    prof_calc = prof_teste
                    break
            
            if prof_calc is None: prof_calc = df_spt["Profundidade (m)"].max()
        else:
            prof_calc = df_suficiente.iloc[0]["Profundidade (m)"]
    else:
        prof_calc = df_spt["Profundidade (m)"].max()
        
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
# RADAR GEOMÉTRICO (DXF) - ATUALIZADO PARA SUPORTAR P-E-1, P_1, etc.
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
        if val in ['x', 'x(cm)', 'x (cm)', 'x(m)', 'x (m)', 'coord.x']: headers_x['x'] = row['X']
        elif val in ['y', 'y(cm)', 'y (cm)', 'y(m)', 'y (m)', 'coord.y']: headers_x['y'] = row['X']
        elif 'carga' in val and ('máx' in val or 'max' in val or 'tf' in val or 'kn' in val): headers_x['carga'] = row['X']
        elif val == 'ne': headers_x['ne'] = row['X']
        elif val == 'estaca': headers_x['estaca'] = row['X']

    if headers_x['carga'] is None:
        for index, row in df_raw.iterrows():
            if 'carga' in str(row['Texto']).lower(): headers_x['carga'] = row['X']

    # --- A CORREÇÃO ESTÁ AQUI: Novo Regex que aceita "P-E-1", "P_1", "PE 12", etc. ---
    pilares = df_raw[df_raw['Texto'].str.match(r'^P[-_A-Za-z]*\s*\d+$', case=False)].copy()
    
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
# MOTOR DE EXPORTAÇÃO BIM (.IFC4) - COMPATIBILIDADE TOTAL EBERICK / VISUS 5D
# -----------------------------------------------------------------------------
def gerar_modelo_ifc(df_projeto):
    model = ifcopenshell.file(schema="IFC4")
    
    project = run("root.create_entity", model, ifc_class="IfcProject", name="Projeto BIM - UTEA Fundações")
    
    # --- DECLARAÇÃO GLOBAL DE UNIDADES (Garante Kg, m³, m e kN no ficheiro) ---
    try:
        u_len = model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")
        u_area = model.create_entity("IfcSIUnit", UnitType="AREAUNIT", Name="SQUARE_METRE")
        u_vol = model.create_entity("IfcSIUnit", UnitType="VOLUMEUNIT", Name="CUBIC_METRE")
        u_mass = model.create_entity("IfcSIUnit", UnitType="MASSUNIT", Prefix="KILO", Name="GRAM")
        u_force = model.create_entity("IfcSIUnit", UnitType="FORCEUNIT", Prefix="KILO", Name="NEWTON")
        
        unit_assig = model.create_entity("IfcUnitAssignment", Units=[u_len, u_area, u_vol, u_mass, u_force])
        project.UnitsInContext = unit_assig
    except Exception:
        pass
    # ---------------------------------------------------------------------------------
    
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
        
        aco_long_tipo = "CA50"
        aco_estribo_tipo = "CA60" if bitola_e <= 6.3 else "CA50"
        
        for i in range(ne):
            if ne == 1: dx, dy = 0.0, 0.0
            else:
                raio_distribuicao = 1.5 * diam 
                angle = i * (2 * np.pi / ne)
                dx = raio_distribuicao * np.cos(angle)
                dy = raio_distribuicao * np.sin(angle)
            
            nome_estaca = f"E-{row['Pilar']}-{i+1}" if ne > 1 else f"E-{row['Pilar']}"
            pile = run("root.create_entity", model, ifc_class="IfcPile", name=nome_estaca)
            
            run("spatial.assign_container", model, relating_structure=building, products=[pile])
            
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
            
            # --- INJEÇÃO DE PSETS NATIVOS DO EBERICK COM UNIDADES PRECISAS ---
            try:
                # Entidade de unidade específica para Centímetros
                u_cm = model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Prefix="CENTI", Name="METRE")

                def injetar_propriedades(nome_pset, dic_props):
                    pset = run("pset.add_pset", model, product=pile, name=nome_pset)
                    lista_props = []
                    for k, v in dic_props.items():
                        t = v["type"]
                        val = v["value"]
                        
                        if t == "IfcLabel": 
                            ifc_val = model.createIfcLabel(str(val))
                        elif t == "IfcMassMeasure": 
                            ifc_val = model.createIfcMassMeasure(float(val))
                        elif t == "IfcVolumeMeasure": 
                            ifc_val = model.createIfcVolumeMeasure(float(val))
                        elif t == "IfcLengthMeasure": 
                            ifc_val = model.createIfcLengthMeasure(float(val))
                        elif t == "IfcLengthMeasure_CM":
                            # Associa explicitamente a unidade u_cm (cm) à propriedade
                            ifc_val = model.createIfcLengthMeasure(float(val))
                            prop = model.createIfcPropertySingleValue(k, None, ifc_val, u_cm)
                            lista_props.append(prop)
                            continue
                        elif t == "IfcForceMeasure": 
                            ifc_val = model.createIfcForceMeasure(float(val))
                        elif t == "IfcReal": 
                            ifc_val = model.createIfcReal(float(val))
                        elif t == "IfcInteger": 
                            ifc_val = model.createIfcInteger(int(val))
                        else: 
                            ifc_val = model.createIfcLabel(str(val))
                        
                        lista_props.append(model.createIfcPropertySingleValue(k, None, ifc_val, None))
                    
                    pset.HasProperties = lista_props

                # 1. AltoQi_Eberick-Itens_associados
                injetar_propriedades("AltoQi_Eberick-Itens_associados", {
                    "Status": {"type": "IfcLabel", "value": "Dimensionado"},
                    f"Concreto - C-{int(fck_val)} - Abatimento 5 cm": {"type": "IfcVolumeMeasure", "value": vol_concreto_estaca},
                    f"Armadura - Aço {aco_long_tipo} - ø {bitola_l:.1f} mm": {"type": "IfcMassMeasure", "value": peso_l_estaca},
                    f"Armadura - Aço {aco_estribo_tipo} - ø {bitola_e:.1f} mm": {"type": "IfcMassMeasure", "value": peso_e_estaca}
                })
                
                # 2. AltoQi_Eberick_Elemento
                injetar_propriedades("AltoQi_Eberick_Elemento", {
                    "Elemento": {"type": "IfcLabel", "value": "Estaca"},
                    "Elevação": {"type": "IfcLengthMeasure_CM", "value": 0.0},
                    "Comprimento_m": {"type": "IfcLengthMeasure", "value": prof},
                    "Seção_LB": {"type": "IfcLengthMeasure_CM", "value": diam * 100},
                    "Seção_LH": {"type": "IfcLengthMeasure_CM", "value": diam * 100},
                    "Tipo": {"type": "IfcInteger", "value": 1}
                })
                
                # 3. AltoQi_Eberick_Padrão (Cobrimento em cm)
                injetar_propriedades("AltoQi_Eberick_Padrão", {
                    "Classe de concreto": {"type": "IfcLabel", "value": f"C-{int(fck_val)}"},
                    "Cobrimento": {"type": "IfcLengthMeasure_CM", "value": 5.0}
                })
                
                # 4. Pset_ConcreteElementGeneral (Padrão em metros)
                injetar_propriedades("Pset_ConcreteElementGeneral", {
                    "ConcreteCover": {"type": "IfcLengthMeasure", "value": 0.05},
                    "ConstructionMethod": {"type": "IfcLabel", "value": "InSitu"},
                    "ExposureClass": {"type": "IfcLabel", "value": "2"},
                    "StrengthClass": {"type": "IfcLabel", "value": f"C-{int(fck_val)}"}
                })

                # 5. Pset_PileCommon
                injetar_propriedades("Pset_PileCommon", {
                    "Reference": {"type": "IfcLabel", "value": f"Estaca circular HC{int(diam*100)} - Concreto C-{int(fck_val)}"},
                    "Profundidade_Estaca_m": {"type": "IfcLengthMeasure", "value": prof},
                    "Carga_Aplicada_kN": {"type": "IfcForceMeasure", "value": float(row.get('Carga_por_Estaca_kN', 0))}
                })
                
            except Exception:
                pass 
                
    return model.to_string()

# -----------------------------------------------------------------------------
# NOVO: MOTOR DE GERAÇÃO DO MEMORIAL (PDF) PILAR A PILAR
# -----------------------------------------------------------------------------
def obter_capacidades_na_cota(df_spt_raw, diametro_m, prof_alvo):
    # Recalcula rapidamente para extrair os valores exatos na cota de assentamento do pilar
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

    # Busca a linha exata da profundidade adotada (ou a mais próxima)
    linha = df_spt[df_spt["Profundidade (m)"] >= prof_alvo].head(1)
    if len(linha) > 0:
        return linha.iloc[0]
    return df_spt.iloc[-1]

def gerar_memorial_estrutural_pdf(df_projeto, df_spt_atual, config_global, fck, criterio, prof_minima, verificar_bulbo):
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story, styles = [], getSampleStyleSheet()

    title_style = ParagraphStyle('PDFTitle', parent=styles['Heading1'], fontSize=15, leading=18, textColor=colors.HexColor('#1E3A8A'), alignment=1, spaceAfter=10)
    h2_style = ParagraphStyle('PDFH2', parent=styles['Heading2'], fontSize=12, leading=16, textColor=colors.HexColor('#1E3A8A'), spaceBefore=10, spaceAfter=5)
    body_style = ParagraphStyle('PDFBody', parent=styles['Normal'], fontSize=9, leading=13)
    pilar_title = ParagraphStyle('PilarTitle', parent=styles['Heading3'], fontSize=11, leading=14, textColor=colors.white)

    story.append(Paragraph("<b>MEMORIAL DE CÁLCULO ESTRUTURAL - FUNDAÇÕES PROFUNDAS</b>", title_style))
    story.append(Paragraph("<b>Dimensionamento Detalhado e Geotécnico (Pilar a Pilar)</b>", ParagraphStyle('Sub', parent=body_style, alignment=1)))
    story.append(Spacer(1, 15))

    # --- 1. PARÂMETROS E CRITÉRIOS ---
    story.append(Paragraph("<b>1. Parâmetros e Critérios Adotados</b>", h2_style))
    txt_param = f"• <b>Classe do Concreto Adotada:</b> C{fck}<br/>"
    txt_param += f"• <b>Critério Geotécnico de Resistência:</b> {criterio}<br/>"
    txt_param += f"• <b>Profundidade Mínima Fixada:</b> {prof_minima} m<br/>"
    txt_param += f"• <b>Verificação da Zona de Influência (Bulbo de Tensões):</b> {'Ativada (Evita assentamento sobre camadas moles subjacentes)' if verificar_bulbo else 'Desativada'}<br/>"
    story.append(Paragraph(txt_param, body_style))
    story.append(Spacer(1, 10))

    # --- 2. RESUMO GLOBAL ---
    total_blocos = len(df_projeto)
    total_estacas = df_projeto["ne"].sum()
    total_metros = df_projeto["Metros_Perfurados"].sum()
    vol_total = df_projeto["Vol_Concreto_m3"].sum()
    aco_total = df_projeto["Peso_Aco_kg"].sum()

    story.append(Paragraph("<b>2. Resumo Executivo Quantitativo</b>", h2_style))
    txt_res = f"• <b>Total de Blocos Dimensionados:</b> {total_blocos} un<br/>"
    txt_res += f"• <b>Quantidade Total de Estacas:</b> {total_estacas:.0f} un<br/>"
    txt_res += f"• <b>Comprimento Total de Perfuração:</b> {total_metros:.1f} m<br/>"
    txt_res += f"• <b>Volume Total de Concreto Projetado:</b> {vol_total:.1f} m³<br/>"
    txt_res += f"• <b>Peso Total de Aço Armado:</b> {aco_total:.1f} kg<br/>"
    story.append(Paragraph(txt_res, body_style))
    story.append(Spacer(1, 15))

    story.append(PageBreak())

    # --- 3. MEMÓRIA DE CÁLCULO PILAR A PILAR ---
    story.append(Paragraph("<b>3. Memória de Cálculo Detalhada (Pilar a Pilar)</b>", h2_style))
    story.append(Spacer(1, 10))

    for idx, row in df_projeto.iterrows():
        pilar_elements = [] # Agrupa os elementos deste pilar para não quebrar na página
        
        nome_pilar = str(row['Pilar'])
        ne = int(row['ne'])
        diam = row['Diametro_m']
        carga_tot = row['Carga_Max_tf']
        carga_est = row['Carga_por_Estaca_kN']
        prof = row['Profundidade_m']
        
        # Avalia a capacidade exata na cota onde a estaca parou
        if df_spt_atual is not None:
            cota_info = obter_capacidades_na_cota(df_spt_atual, diam, prof)
            solo_tipo = cota_info["Tipo de Solo"]
            nspt = cota_info["N_SPT"]
            rc_aoki = cota_info["Rc Aoki"]
            rc_dq = cota_info["Rc DQ"]
            rc_tx = cota_info["Rc Teix"]
            rc_adotada = cota_info["Rc Média"] if criterio == "Média dos Métodos" else (cota_info["Rc Menor"] if criterio == "Menor Valor (Mais Conservador)" else (cota_info["Rc Aoki"] if "Aoki" in criterio else (cota_info["Rc DQ"] if "Décourt" in criterio else cota_info["Rc Teix"])))
        else:
            solo_tipo, nspt, rc_aoki, rc_dq, rc_tx, rc_adotada = "Desconhecido", 0, 0, 0, 0, 0
            
        # Cria a Tabela do Pilar
        t_header = Table([[Paragraph(f"<b>BLOCO DO PILAR {nome_pilar}</b> | {ne} Estaca(s) de Ø {diam*100:.0f} cm", pilar_title)]], colWidths=[540])
        t_header.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#1E3A8A')), ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('BOTTOMPADDING', (0,0), (-1,-1), 6)]))
        pilar_elements.append(t_header)

        # Corpo dos Dados
        dados_pilar = f"""<b>1. Esforços e Geometria</b><br/>
        Carga Total do Bloco (Catálogo): {carga_tot:.1f} tf<br/>
        Carga de Cálculo por Estaca (S_d): <b>{carga_est:.1f} kN</b><br/>
        Profundidade Adotada: <b>{prof:.1f} m</b> (Limitador Mínimo: {prof_minima}m)<br/><br/>
        """
        
        if df_spt_atual is not None:
            dados_pilar += f"""<b>2. Verificação Geotécnica na Cota de Assentamento (Z = {prof:.1f}m)</b><br/>
            Tipo de Solo na Ponta: {solo_tipo} (N_SPT = {nspt:.0f})<br/>
            Rc Aoki-Velloso: {rc_aoki:.1f} kN | Rc Décourt-Quaresma: {rc_dq:.1f} kN | Rc Teixeira: {rc_tx:.1f} kN<br/>
            Capacidade Resistente Adotada (R_c): <font color='green'><b>{rc_adotada:.1f} kN</b></font> (Situação: {'OK' if rc_adotada >= carga_est else 'Cravado na Prof. Mínima'})<br/><br/>
            """
        else:
            dados_pilar += "<b>2. Verificação Geotécnica</b><br/>Terreno não importado. Assumida profundidade teórica mínima.<br/><br/>"

        dados_pilar += f"""<b>3. Detalhamento Estrutural e Quantitativos (Por Estaca)</b><br/>
        Armadura Longitudinal: {row['Armadura_Principal']}<br/>
        Volume de Concreto (por estaca): {(row['Vol_Concreto_m3'] / ne):.2f} m³<br/>
        Peso de Aço Total (por estaca): {(row['Peso_Aco_kg'] / ne):.1f} kg<br/><br/>
        <b>TOTAIS DO BLOCO {nome_pilar}:</b> Concreto = {row['Vol_Concreto_m3']:.2f} m³ | Aço = {row['Peso_Aco_kg']:.1f} kg
        """

        t_body = Table([[Paragraph(dados_pilar, body_style)]], colWidths=[540])
        t_body.setStyle(TableStyle([
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#1E3A8A')),
            ('TOPPADDING', (0,0), (-1,-1), 10),
            ('BOTTOMPADDING', (0,0), (-1,-1), 10),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ]))
        pilar_elements.append(t_body)
        pilar_elements.append(Spacer(1, 15))
        
        # Junta o Cabeçalho e o Corpo do Pilar para não separarem de página
        story.append(KeepTogether(pilar_elements))

    doc.build(story)
    pdf_buffer.seek(0)
    return pdf_buffer.getvalue()

# -----------------------------------------------------------------------------
# INTERFACE PRINCIPAL E BARRA LATERAL
# -----------------------------------------------------------------------------
st.title("🏢 Gestor BIM & Orçamento de Fundações")
st.caption("Dimensionamento 5D automático cruzando CAD, Terreno e Exportação IFC4")

with st.expander("📖 Guia de Utilização - Módulo Estrutural & BIM 5D", expanded=False):
    st.markdown("""
    ### 🎯 Objetivo do Módulo
    Efetuar a integração entre o projeto geotécnico e a planta estrutural importada do CAD/Eberick, realizando o dimensionamento automático por bloco/pilar, verificação de estabilidade do solo e exportação do modelo **BIM 5D (.IFC4)** e **Memorial em PDF**.

    ---

    ### 📋 Passo a Passo de Operação

    #### 1. Sincronização Geotécnica e Importação do CAD
    * **Terreno (.utea):** Se veio diretamente do *Módulo Geotécnico*, o terreno já estará sincronizado automaticamente. Caso contrário, faça o upload do ficheiro `.utea`.
    * **Planta de Cargas (.dxf):** Faça o upload da planta exportada do CAD/Eberick em formato `.dxf`. O algoritmo lerá autonomamente as coordenadas $(X,Y)$, a carga máxima de cada pilar e a quantidade de estacas por bloco.

    #### 2. Configuração de Materiais e Radar de Bulbo
    * **👁️ Radar do Bulbo de Tensões:** Mantendo ativado, o algoritmo inspeciona a zona de influência (mínimo de 3x o diâmetro) abaixo da ponta das estacas. Se detetar solos moles ($N_{SPT} \le 3$) ou perda acentuada de resistência, forçará o aprofundamento para evitar assentamentos.
    * **Concreto e Armaduras:** Configure a classe de concreto ($F_{ck}$), a taxa de aço longitudinal, bitolas e espaçamento dos estribos. Os valores definidos no Módulo Geotécnico são herdados automaticamente.

    #### 3. Análise Visual e Memória
    * **Resumo Executivo:** Veja o volume total de concreto escavado, metragem de perfuração e peso total de aço ($CA50/CA60$).
    * **Planta de Locação Topográfica:** Analise o mapa de calor interativo mostrando a profundidade de cada estaca e a distribuição de cargas no terreno.

    #### 4. Exportação BIM 5D e Documentação
    * **Modelo 3D (.IFC4):** Gere o ficheiro IFC perfeitamente padronizado com os metadados da AltoQi Eberick (`AltoQi_Eberick-Itens_associados`, `Pset_PileCommon`, etc.) e unidades nativas em **kg**, **m³**, **m**, **kN** e **cm** para integração direta no **Visus / PriMus**.
    * **Memorial Estrutural (PDF):** Baixe o relatório analítico detalhado pilar a pilar com a memória geotécnica e quantitativos de armaduras e concreto.
    """)

st.sidebar.header("1️⃣ Dados do Terreno Geotécnico")

dados_terreno = {}
furo_selecionado = None
criterio_selecionado = "Média dos Métodos"
conteudo_utea = None

if 'projeto_geotecnico' in st.session_state and st.session_state['projeto_geotecnico'] is not None:
    st.sidebar.success("🔗 Terreno sincronizado automaticamente do Módulo Geotécnico!")
    conteudo_utea = st.session_state['projeto_geotecnico']
else:
    st.sidebar.info("Projeto geotécnico não sincronizado. Volte à página anterior ou faça upload manual.")
    arquivo_utea = st.sidebar.file_uploader("Ficheiro .utea", type=["utea", "json"])
    if arquivo_utea is not None:
        conteudo_utea = json.loads(arquivo_utea.read().decode('utf-8'))

config_memoria = st.session_state.get('params_globais', {})

if conteudo_utea is not None:
    try:
        for nome, info in conteudo_utea.get("furos", {}).items():
            dados_terreno[nome] = pd.DataFrame(info["df"])
        
        if dados_terreno:
            furo_selecionado = st.sidebar.selectbox("Furo Base para Cálculo:", list(dados_terreno.keys()))
            opts_crit = ["Média dos Métodos", "Menor Valor (Mais Conservador)", "Apenas Aoki-Velloso", "Apenas Décourt-Quaresma", "Apenas Teixeira"]
            def_crit = config_memoria.get("criterio_q_adm", "Média dos Métodos")
            idx_crit = opts_crit.index(def_crit) if def_crit in opts_crit else 0
            criterio_selecionado = st.sidebar.selectbox("Critério Geotécnico:", opts_crit, index=idx_crit)
    except Exception as e:
        st.sidebar.error(f"Erro ao ler os dados do terreno: {e}")

st.sidebar.markdown("---")
st.sidebar.header("2️⃣ Importar Planta")
arquivo_upload = st.sidebar.file_uploader("Planta do Eberick (.dxf, .xlsx)", type=["dxf", "xlsx", "csv"])

st.sidebar.markdown("---")
st.sidebar.header("3️⃣ Configuração Estrutural e Materiais")

if config_memoria: st.sidebar.success("✅ Materiais e Armaduras sincronizados!")

verificar_bulbo = st.sidebar.checkbox("👁️ Ativar Verificação do Bulbo de Tensões", value=True, help="Varre camadas subjacentes para evitar que a estaca pare sobre solos moles.")

def_fck = int(config_memoria.get("fck", 25))
def_taxa = float(config_memoria.get("taxa_armadura", 0.5))
def_bitola = float(config_memoria.get("bitola", 10.0))
def_bitola_e = float(config_memoria.get("bitola_estribo", 6.3))
def_espac = float(config_memoria.get("espacamento_estribo", 15.0))
def_l_man = config_memoria.get("L_armadura_manual", None)

opts_fck = [20, 25, 30, 35, 40]
idx_fck = opts_fck.index(def_fck) if def_fck in opts_fck else 1
fck_concreto = st.sidebar.selectbox("Classe do Concreto (Fck - MPa)", opts_fck, index=idx_fck)

prof_minima_global = st.sidebar.number_input("Profundidade Mínima da Estaca (m)", min_value=1.0, value=6.0, step=0.5)
taxa_armadura = st.sidebar.number_input("Taxa de Armadura Longitudinal (%)", min_value=0.1, value=def_taxa, step=0.1)

opts_bitola = [10.0, 12.5, 16.0, 20.0, 25.0]
idx_bitola = opts_bitola.index(def_bitola) if def_bitola in opts_bitola else 0
bitola = st.sidebar.selectbox("Bitola Long. (mm)", opts_bitola, index=idx_bitola)

opts_estribo = [5.0, 6.3, 8.0, 10.0]
idx_estribo = opts_estribo.index(def_bitola_e) if def_bitola_e in opts_estribo else 1
bitola_estribo = st.sidebar.selectbox("Bitola Estribo (mm)", opts_estribo, index=idx_estribo)

espacamento_estribo = st.sidebar.number_input("Espaçamento Estribos (cm)", min_value=5.0, max_value=30.0, value=def_espac, step=2.5)

idx_gaiola = 1 if def_l_man is not None else 0
gaiola_tipo = st.sidebar.selectbox("Gaiola", ["Total (Toda a estaca)", "Parcial (Manual)"], index=idx_gaiola)

val_l_man = def_l_man if def_l_man is not None else 6.0
L_armadura_manual = st.sidebar.number_input("Comp. Manual (m)", value=val_l_man, step=0.5) if gaiola_tipo == "Parcial (Manual)" else None

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
        if df_spt_atual is None: st.warning("⚠️ Sem Terreno (.utea). Assumindo a Profundidade Mínima para orçamento.")

        for index, row in df.iterrows():
            if df_spt_atual is not None:
                prof = calcular_profundidade_estaca(df_spt_atual, row["Diametro_m"], row["Carga_por_Estaca_kN"], criterio_selecionado, prof_minima_global, row["ne"], verificar_bulbo) 
            else:
                prof = prof_minima_global
                
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
        st.subheader("🏗️ Exportação e Relatórios (BIM e PDF)")
        
        col_btn1, col_btn2 = st.columns(2)
        
        with col_btn1:
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

        with col_btn2:
            try:
                pdf_estrutural = gerar_memorial_estrutural_pdf(df, df_spt_atual, config_memoria, fck_concreto, criterio_selecionado, prof_minima_global, verificar_bulbo)
                st.download_button(
                    label="📄 Baixar Memorial Estrutural (PDF)",
                    data=pdf_estrutural,
                    file_name="Memorial_Calculo_Estrutural.pdf",
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"Erro ao compilar o PDF Estrutural: {e}")

    else:
        st.warning("⚠️ **DIAGNÓSTICO:** O Radar não encontrou coordenadas na tabela do DXF.")
else:
    st.info("👈 Faça o upload do Terreno (.utea) e da Planta do Eberick (.dxf) na barra lateral para iniciar a integração.")
