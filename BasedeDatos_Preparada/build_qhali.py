#!/usr/bin/env python3
"""
Qhali — construcción de la base de referencia.
Ejecución manual única. Versionado y hash_origen activos desde ya.
"""
import sqlite3, unicodedata, re, json, hashlib, os
import pandas as pd

XLSX = '/mnt/user-data/uploads/TABLA_DE_DATOS_SALUD.xlsx'
DB   = '/home/claude/qhali/qhali.db'
Y    = 365.25

def norm(s):
    if s is None or (isinstance(s, float) and pd.isna(s)): return ''
    s = str(s).upper().strip()
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    s = re.sub(r'[^A-Z0-9 ]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()

def clave(dep, prov, dis): return f'{norm(dep)}|{norm(prov)}|{norm(dis)}'
def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 16), b''): h.update(b)
    return h.hexdigest()

if os.path.exists(DB): os.remove(DB)
cx = sqlite3.connect(DB)
cx.executescript(open('/home/claude/qhali/schema.sql').read())
xl = pd.ExcelFile(XLSX)
HASH = sha(XLSX)
rechazos = []

# =====================================================================
# 1 · FUENTES
# =====================================================================
NTS = ('NTS N° 213-MINSA/DGIESP-2024, aprobada por RM 251-2024/MINSA '
       '(08/04/2024), modificada por RM 429-2024/MINSA')
FUENTES = [
 (1,'RENIPRESS','padron_establecimientos','Registro Nacional de IPRESS — SUSALUD/MINSA',None,'2026-07-25',3),
 (2,'POR_DEFINIR','altitud_distrital','PENDIENTE: falta organismo y año de la tabla de altitudes',None,'2024-01-01',4),
 (3,'MINSA',    'nts213_ajuste_altitud_hb', NTS + ', Tabla N° 1',None,'2024-04-08',1),
 (4,'MINSA',    'nts213_hemoglobina',       NTS + ', Tabla N° 13 (hasta 500 msnm)',None,'2024-04-08',1),
 (5,'MINSA',    'nts213_ferritina',         NTS + ', Tabla N° 14',None,'2024-04-08',1),
 (6,'MINSA',    'nts213_cie10',             NTS + ', Tabla N° 23',None,'2024-04-08',1),
 (7,'POR_DEFINIR','panel_hematologia','PENDIENTE: falta organismo emisor',None,None,8),
 (8,'POR_DEFINIR','panel_bioquimica','PENDIENTE: falta organismo emisor',None,None,8),
 (9,'POR_DEFINIR','panel_orina','PENDIENTE: falta organismo emisor',None,None,8),
 (10,'POR_DEFINIR','panel_ginecologia','PENDIENTE: falta organismo emisor',None,None,8),
 (11,'POR_DEFINIR','panel_signos_vitales','PENDIENTE: falta organismo emisor y criterio (ACC/AHA vs OMS)',None,None,8),
]
cx.executemany('INSERT INTO fuente_referencia(id,organismo,dataset,cita,url_origen,fecha_snapshot,prioridad) '
               'VALUES (?,?,?,?,?,?,?)', FUENTES)

def lote(fid, leidos, validos, rech, estado='completado'):
    c = cx.execute('INSERT INTO ingesta_lote(fuente_id,version,registros_leidos,registros_validos,'
                   'registros_rechazados,hash_origen,estado) VALUES (?,1,?,?,?,?,?)',
                   (fid, leidos, validos, rech, HASH, estado))
    return c.lastrowid

# =====================================================================
# 2 · DISTRITOS  (autoridad = tabla de altitudes: censo nacional completo)
# =====================================================================
dem = xl.parse('Mediciones demograficcas', dtype=str)
dem['K'] = [clave(a,b,c) for a,b,c in zip(dem.Departamento, dem.Provincia, dem.Distrito)]
dem['alt'] = pd.to_numeric(dem['altitude'], errors='coerce')
assert dem.K.is_unique

filas = [(r.K, norm(r.Departamento), norm(r.Provincia), norm(r.Distrito),
          None if pd.isna(r.alt) else int(r.alt), 2) for r in dem.itertuples()]
cx.executemany('INSERT INTO distrito(clave_norm,departamento,provincia,nombre,altitud_msnm,fuente_id) '
               'VALUES (?,?,?,?,?,?)', filas)
sin_alt = sum(1 for f in filas if f[4] is None)
l2 = lote(2, len(dem), len(filas), sin_alt, 'parcial' if sin_alt else 'completado')
for r in dem[dem.alt.isna()].itertuples():
    rechazos.append((l2, f'{r.Departamento}|{r.Provincia}|{r.Distrito}', 'altitud_ausente_en_la_fuente'))

# =====================================================================
# 3 · ALIAS DE DISTRITO  (grafías de RENIPRESS → forma canónica)
# =====================================================================
ALIAS = [
 # (dep, prov_reni, dis_reni, prov_canon, dis_canon, evidencia, nota)
 *[('ANCASH','ANTONIO RAIMONDI',d,'ANTONIO RAYMONDI',d,'A_variante_de_provincia',
    'Nombre de distrito idéntico; solo difiere la grafía de la provincia') for d in
   ['ACZO','CHACCHO','CHINGAS','LLAMELLIN','MIRGAS','SAN JUAN DE RONTOY']],
 ('AMAZONAS','LUYA','SAN FRANCISCO DE YESO','LUYA','SAN FRANCISCO DEL YESO','C_variante_ortografica','DE / DEL'),
 ('AMAZONAS','RODRIGUEZ DE MENDOZA','MILPUCC','RODRIGUEZ DE MENDOZA','MILPUC','C_variante_ortografica','C duplicada'),
 ('ANCASH','BOLOGNESI','ANTONIO RAIMONDI','BOLOGNESI','ANTONIO RAYMONDI','C_variante_ortografica','RAIMONDI / RAYMONDI'),
 ('APURIMAC','GRAU','HUAILLATI','GRAU','HUAYLLATI','C_variante_ortografica','I / Y'),
 ('AREQUIPA','AREQUIPA','SANTA RITA DE SIHUAS','AREQUIPA','SANTA RITA DE SIGUAS','C_variante_ortografica','H / G'),
 ('CUSCO','LA CONVENCION','KIMBIRI','LA CONVENCION','QUIMBIRI','C_variante_ortografica','K / QU'),
 ('HUANCAVELICA','ANGARAES','HUALLAY GRANDE','ANGARAES','HUAYLLAY GRANDE','C_variante_ortografica','HUALLAY / HUAYLLAY'),
 ('HUANUCO','LEONCIO PRADO','DANIEL ALOMIA ROBLES','LEONCIO PRADO','DANIEL ALOMIAS ROBLES','C_variante_ortografica','ALOMIA / ALOMIAS'),
 ('PUNO','EL COLLAO','CAPASO','EL COLLAO','CAPAZO','C_variante_ortografica','S / Z'),
 ('SAN MARTIN','PICOTA','CASPIZAPA','PICOTA','CASPISAPA','C_variante_ortografica','Z / S'),
 ('UCAYALI','ATALAYA','RAIMONDI','ATALAYA','RAYMONDI','C_variante_ortografica','RAIMONDI / RAYMONDI'),
 ('PASCO','PASCO','SAN FCO DE ASIS DE YARUSYACAN','PASCO','SAN FRANCISCO DE ASIS DE YARUSYACAN','B_abreviatura','SAN FCO'),
 ('CAJAMARCA','CONTUMAZA','SANTA CRUZ DE TOLED','CONTUMAZA','SANTA CRUZ DE TOLEDO','B_truncamiento','string cortado'),
 ('AYACUCHO','HUAMANGA','ANDRES AVELINO CACERES D','HUAMANGA','ANDRES AVELINO CACERES DORREGARAY','B_truncamiento','string cortado'),
 ('TACNA','TACNA','CORONEL GREGORIO ALBARRACIN L','TACNA','CORONEL GREGORIO ALBARRACIN LANCHIPA','B_truncamiento','string cortado'),
 ('TACNA','TARATA','HEROES ALBARRACIN','TARATA','HEROES ALBARRACIN CHUCATAMANI','B_nombre_corto','nombre oficial completo'),
 ('LIMA','HUAROCHIRI','CASTA','HUAROCHIRI','SAN PEDRO DE CASTA','B_nombre_corto','nombre oficial completo'),
 ('ANCASH','HUARAZ','PAMPAS GRANDE','HUARAZ','PAMPAS','D_eliminacion','único emparejamiento posible en la provincia'),
 ('APURIMAC','GRAU','MARISCAL GAMARRA','GRAU','GAMARRA','D_eliminacion','único emparejamiento posible en la provincia'),
 ('AYACUCHO','VICTOR FAJARDO','HUALLA','VICTOR FAJARDO','HUAYA','D_eliminacion','único emparejamiento posible en la provincia'),
 ('LIMA','YAUYOS','ALLAUCA','YAUYOS','AYAUCA','D_eliminacion','único emparejamiento posible en la provincia'),
]
# Distritos presentes en RENIPRESS pero ausentes de la tabla de altitudes:
# se crean con altitud NULL. No se les asigna un valor aproximado.
SIN_ALTITUD = [
 ('LA LIBERTAD','TRUJILLO','ALTO TRUJILLO',
  'Distrito de creación reciente; ausente de la tabla de altitudes'),
 ('LIMA','HUAROCHIRI','SAN JOSE DE LOS CHORRILLOS',
  'No figura como distrito en la tabla de altitudes; probable centro poblado registrado como distrito en RENIPRESS'),
]
for dep, prov, dis, nota in SIN_ALTITUD:
    cx.execute('INSERT INTO distrito(clave_norm,departamento,provincia,nombre,altitud_msnm,fuente_id) '
               'VALUES (?,?,?,?,NULL,1)', (clave(dep,prov,dis), norm(dep), norm(prov), norm(dis)))
    rechazos.append((l2, f'{dep}|{prov}|{dis}', 'distrito_sin_altitud_en_la_fuente'))

for dep, pr, dr, pa, da, ev, nota in ALIAS:
    ko, kc = clave(dep,pr,dr), clave(dep,pa,da)
    assert cx.execute('SELECT 1 FROM distrito WHERE clave_norm=?', (kc,)).fetchone(), kc
    cx.execute('INSERT INTO alias_distrito VALUES (?,?,?,?,?)', (ko, kc, 'RENIPRESS', ev, nota))

def resolver(k):
    a = cx.execute('SELECT clave_canonica FROM alias_distrito WHERE clave_origen=?', (k,)).fetchone()
    return a[0] if a else k

# =====================================================================
# 4 · ESTABLECIMIENTOS
# =====================================================================
est = xl.parse('Listado de Establecimientos', dtype=str)
est['K'] = [clave(a,b,c) for a,b,c in zip(est.Departamento, est.Provincia, est.Distrito)]
ok, bad = [], 0
for r in est.itertuples():
    k = resolver(r.K)
    if not cx.execute('SELECT 1 FROM distrito WHERE clave_norm=?', (k,)).fetchone():
        bad += 1; continue
    ok.append((str(r._2).strip(), str(r.Institución).strip(),
               str(r._3).strip(), norm(r._3), k))
cx.executemany('INSERT INTO establecimiento_salud'
               '(fuente_id,codigo_unico,institucion,nombre,nombre_normalizado,clave_norm) '
               'VALUES (1,?,?,?,?,?)', ok)
lote(1, len(est), len(ok), bad)

# =====================================================================
# 5 · BIOMARCADORES + RANGOS
# =====================================================================
def bio(nombre, matriz, cat, unidad, dire='bilateral', sistema=None, derivado=0,
        origen='documento', cpms=None, sin=None):
    cx.execute('INSERT INTO biomarcador(nombre,nombre_normalizado,matriz,categoria_examen,'
               'sistema_corporal,unidad_estandar,direccionalidad,derivado,origen_dato,codigo_cpms,sinonimos) '
               'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
               (nombre, norm(nombre), matriz, cat, sistema, unidad, dire, derivado, origen, cpms,
                json.dumps(sin, ensure_ascii=False) if sin else None))
    return cx.execute('SELECT last_insert_rowid()').fetchone()[0]

def rango(fid, bid, vmin, vmax, unidad, sexo=None, cond='general',
          emin=0, emax=43800, lim='cerrado', clas='normal', altmax=None):
    cx.execute('INSERT INTO rango_referencia(fuente_id,biomarcador_id,sexo,condicion,edad_min_dias,'
               'edad_max_dias,valor_min,valor_max,unidad,tipo_limite,clasificacion,altitud_max_aplicable) '
               'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
               (fid, bid, sexo, cond, emin, emax, vmin, vmax, unidad, lim, clas, altmax))

INF = 9e9

# --- HEMATOLOGIA (encabezado en la fila 1, no en la 0) --------------------
hem = xl.parse('HEMATOLOGIA', header=1).dropna(how='all')
n_hem = 0
BIO_HB = None
for r in hem.itertuples():
    nombre, unidad, rng = str(r._1).strip(), str(r.Unidad).strip(), str(r._3).strip()
    m = re.match(r'^([\d.]+)\s*-\s*([\d.]+)$', rng)
    if not m:
        rechazos.append((None, f'HEMATOLOGIA|{nombre}|{rng}', 'rango_no_parseable')); continue
    unidad = 'adimensional' if unidad in ('-', 'nan', '') else unidad
    b = bio(nombre, 'sangre', 'hematologia', unidad, sistema='sangre',
            cpms='85031', sin=['Hb','HGB','hemoglobina'] if 'Hemoglobina' == nombre else None)
    rango(7, b, float(m.group(1)), float(m.group(2)), unidad)
    if nombre == 'Hemoglobina': BIO_HB = b
    n_hem += 1
lote(7, len(hem), n_hem, len(hem) - n_hem)

# --- BIOQUIMICA: direccionalidad y límites unilaterales explícitos --------
DIREC = {'GLUCOSA':('bilateral','cerrado'), 'COLESTEROL TOTAL':('menor_es_mejor','solo_superior'),
         'HDL COLESTEROL':('mayor_es_mejor','solo_inferior'), 'LDL COLESTEROL':('menor_es_mejor','solo_superior'),
         'TRIGLICERIDOS':('menor_es_mejor','solo_superior'), 'INDICE COL TOTAL HDL COL':('menor_es_mejor','solo_superior'),
         'INDICE LDL COL HDL COL':('menor_es_mejor','solo_superior'), 'LIPIDOS TOTALES':('bilateral','cerrado')}
DERIV = {'INDICE COL TOTAL HDL COL', 'INDICE LDL COL HDL COL'}
bq = xl.parse('BIOQUIMICA').dropna(how='all')
n_bq = 0
for r in bq.itertuples():
    nombre, unidad, rng = str(r.Análisis).strip(), str(r.Unidad).strip(), str(r._3).strip()
    m = re.match(r'^([\d.]+)\s*-\s*([\d.]+)$', rng)
    if not m:
        rechazos.append((None, f'BIOQUIMICA|{nombre}|{rng}', 'rango_no_parseable')); continue
    nn = norm(nombre)
    dire, lim = DIREC.get(nn, ('bilateral','cerrado'))
    unidad = 'adimensional' if unidad in ('-','nan','') else unidad
    b = bio(nombre, 'sangre', 'bioquimica', unidad, dire, sistema='sangre',
            derivado=1 if nn in DERIV else 0)
    vmin, vmax = float(m.group(1)), float(m.group(2))
    if lim == 'solo_superior': vmin = 0.0
    if lim == 'solo_inferior': vmax = INF
    rango(8, b, vmin, vmax, unidad, lim=lim)
    n_bq += 1
lote(8, len(bq), n_bq, len(bq) - n_bq)

# --- EXAMEN DE ORINA: solo lo parseable; el resto queda rechazado ---------
ori = xl.parse('EXAMEN DE ORINA').dropna(how='all')
ORINA_OK = [('pH','adimensional',4.6,8.0,'bilateral'), ('Densidad','adimensional',1016.0,1022.0,'bilateral')]
for nombre, unidad, vmin, vmax, dire in ORINA_OK:
    b = bio(nombre, 'orina', 'orina', unidad, dire, sistema='renal')
    rango(9, b, vmin, vmax, unidad)
n_ori_rech = 0
for r in ori.itertuples():
    nombre = str(r._1).strip()
    if nombre in ('nan','Sedimento urinario') or nombre in ('pH','Densidad'): continue
    rechazos.append((None, f'ORINA|{nombre}|{r._2}', 'valor_cualitativo_o_no_numerico')); n_ori_rech += 1
lote(9, len(ori), 2, n_ori_rech, 'parcial')

# --- GINECOLOGIA: rango normal + umbral de alerta separado ---------------
GINE = [
 ('Espesor del Endometrio','mm',1,14,'>',15,'Espesor mayor a 15 mm en premenopausia: sugiere revisión clínica'),
 ('Útero (Longitud)','mm',50,80,None,None,'Referencia de útero en edad reproductiva'),
 ('Útero (Ancho)','mm',30,50,None,None,None),
 ('Volumen Ovárico','cc',2,15,'>',15,'Volumen mayor a 15 cc: puede sugerir ovarios poliquísticos o masas'),
]
for nombre, unidad, vmin, vmax, op, uval, msg in GINE:
    b = bio(nombre, 'imagen', 'ginecologia', unidad, sistema='reproductivo',
            derivado=1 if 'Volumen' in nombre else 0)
    rango(10, b, float(vmin), float(vmax), unidad, sexo='F')
    if op:
        cx.execute('INSERT INTO umbral_alerta(fuente_id,biomarcador_id,sexo,operador,valor,mensaje) '
                   'VALUES (10,?,?,?,?,?)', (b,'F',op,float(uval),msg))
lote(10, 4, 4, 0)

# --- SIGNOS VITALES / ANTROPOMETRIA (Hoja 6) -----------------------------
# Criterio de alerta transcrito a mano: 11 filas, más seguro que un parser.
SV = [
 ('Presión Sistólica','mmHg',None,90,119,'bilateral','>=',120,'Presión sistólica elevada','signos_vitales','ingreso_manual',0),
 ('Presión Diastólica','mmHg',None,60,79,'bilateral','>=',80,'Presión diastólica elevada','signos_vitales','ingreso_manual',0),
 ('Frecuencia Cardiaca','lpm',None,60,100,'bilateral','fuera_de',60,'Frecuencia fuera de 60–100 lpm','signos_vitales','ingreso_manual',0),
 ('Frecuencia Respiratoria','rpm',None,12,20,'bilateral','>',20,'Frecuencia respiratoria elevada','signos_vitales','ingreso_manual',0),
 ('Saturación O2','%',None,95,100,'mayor_es_mejor','<',95,'Saturación baja — RANGO VÁLIDO SOLO A NIVEL DEL MAR','signos_vitales','ingreso_manual',0),
 ('Temperatura','°C',None,36.5,37.5,'bilateral','>=',38.0,'Fiebre','signos_vitales','ingreso_manual',0),
 ('IMC','adimensional',None,18.5,24.9,'bilateral','fuera_de',18.5,'IMC fuera del rango 18.5–24.9','antropometria','ingreso_manual',1),
 ('Perímetro Abdominal','cm','F',0,79,'menor_es_mejor','>=',80,'Riesgo metabólico','antropometria','ingreso_manual',0),
 ('Perímetro Abdominal','cm','M',0,89,'menor_es_mejor','>=',90,'Riesgo metabólico','antropometria','ingreso_manual',0),
 ('% de Grasa Corporal','%','F',21,32,'bilateral','>',32,'Grasa corporal elevada','antropometria','ingreso_manual',1),
 ('% de Grasa Corporal','%','M',10,20,'bilateral','>',20,'Grasa corporal elevada','antropometria','ingreso_manual',1),
]
vistos = {}
for nombre, unidad, sexo, vmin, vmax, dire, op, uval, msg, cat, origen, deriv in SV:
    key = (norm(nombre), 'clinico')
    if key not in vistos:
        vistos[key] = bio(nombre, 'clinico', cat, unidad, dire, derivado=deriv, origen=origen)
    b = vistos[key]
    lim = 'solo_superior' if vmin == 0 else 'cerrado'
    rango(11, b, float(vmin), float(vmax), unidad, sexo=sexo, lim=lim)
    cx.execute('INSERT INTO umbral_alerta(fuente_id,biomarcador_id,sexo,operador,valor,valor_2,mensaje) '
               'VALUES (11,?,?,?,?,?,?)',
               (b, sexo, op, float(uval), float(vmax) if op == 'fuera_de' else None, msg))
lote(11, 11, 11, 0)

# =====================================================================
# 6 · HEMOGLOBINA SEGÚN NTS 213 — Tabla N° 13 (hasta 500 msnm)
#     Reemplaza el rango sin cita 11.00–16.00. Incluye severidad.
# =====================================================================
B_HB_MINSA = BIO_HB  # mismo biomarcador; distinta fuente y prioridad
def hb(sexo, cond, emin, emax, sev, mod_lo, mod_hi, leve_lo, leve_hi, normal_lo, normal_hi=INF):
    args = dict(sexo=sexo, cond=cond, emin=emin, emax=emax, unidad='g/dl')
    rango(4, B_HB_MINSA, 0.0, sev, 'g/dl', sexo=sexo, cond=cond, emin=emin, emax=emax,
          lim='solo_superior', clas='severa', altmax=500)
    rango(4, B_HB_MINSA, mod_lo, mod_hi, 'g/dl', sexo=sexo, cond=cond, emin=emin, emax=emax,
          clas='moderada', altmax=500)
    rango(4, B_HB_MINSA, leve_lo, leve_hi, 'g/dl', sexo=sexo, cond=cond, emin=emin, emax=emax,
          clas='leve', altmax=500)
    rango(4, B_HB_MINSA, normal_lo, normal_hi, 'g/dl', sexo=sexo, cond=cond, emin=emin, emax=emax,
          lim='cerrado' if normal_hi < INF else 'solo_inferior', clas='normal', altmax=500)

# Prematuros/as y neonatos: la NTS solo da umbral con/sin anemia
for cond, emin, emax, corte in [('prematuro',0,6,13.0), ('prematuro',7,27,10.0), ('prematuro',28,55,8.0),
                                ('a_termino',0,59,13.5)]:
    hi = 18.5 if cond == 'a_termino' else INF
    rango(4, B_HB_MINSA, 0.0, corte, 'g/dl', cond=cond, emin=emin, emax=emax,
          lim='solo_superior', clas='moderada', altmax=500)
    rango(4, B_HB_MINSA, corte, hi, 'g/dl', cond=cond, emin=emin, emax=emax,
          lim='cerrado' if hi < INF else 'solo_inferior', clas='normal', altmax=500)
rango(4, B_HB_MINSA, 0.0, 9.5, 'g/dl', cond='general', emin=60, emax=179,
      lim='solo_superior', clas='moderada', altmax=500)
rango(4, B_HB_MINSA, 9.5, 13.5, 'g/dl', cond='general', emin=60, emax=179, clas='normal', altmax=500)

hb(None,'general', 180,  719, 7.0, 7.0, 9.4, 9.5, 10.4, 10.5)   #  6–23 meses
hb(None,'general', 720, 1799, 7.0, 7.0, 9.9,10.0, 10.9, 11.0)   # 24–59 meses
hb(None,'general',1800, int(11.99*Y), 8.0, 8.0,10.9,11.0,11.4, 11.5)  # 5–11 años
hb('F','general', int(12*Y), int(14.99*Y), 8.0, 8.0,10.9,11.0,11.9, 12.0)
hb('M','general', int(12*Y), int(14.99*Y), 8.0, 8.0,10.9,11.0,11.9, 12.0)
hb('M','general', int(15*Y), 43800,        8.0, 8.0,10.9,11.0,12.9, 13.0)
hb('F','no_gestante', int(15*Y), 43800,    8.0, 8.0,10.9,11.0,11.9, 12.0)
hb('F','gestante_t1', 0, 43800, 7.0, 7.0, 9.9,10.0,10.5, 11.0)
hb('F','gestante_t2', 0, 43800, 7.0, 7.0, 9.4, 9.5,10.4, 10.5)
hb('F','gestante_t3', 0, 43800, 7.0, 7.0, 9.9,10.0,10.9, 11.0)
hb('F','puerpera',    0, 43800, 8.0, 8.0,10.9,11.0,11.9, 12.0)
n_hb = cx.execute('SELECT COUNT(*) FROM rango_referencia WHERE fuente_id=4').fetchone()[0]
lote(4, n_hb, n_hb, 0)

# =====================================================================
# 7 · FERRITINA — NTS 213 Tabla N° 14
# =====================================================================
B_FER = bio('Ferritina Sérica','sangre','bioquimica','ug/L','bilateral',sistema='sangre',cpms='82728',
            sin=['ferritina','Ferritina'])
for emin, emax, corte in [(0, 719, 12.0), (720, 1799, 12.0), (1800, int(11.99*Y), 15.0),
                          (int(12*Y), int(17.99*Y), 15.0), (int(18*Y), int(59.99*Y), 15.0)]:
    rango(5, B_FER, 0.0, corte, 'ug/L', emin=emin, emax=emax,
          lim='solo_superior', clas='moderada')
    rango(5, B_FER, corte, INF, 'ug/L', emin=emin, emax=emax, lim='solo_inferior', clas='normal')
rango(5, B_FER, 0.0, 15.0, 'ug/L', sexo='F', cond='gestante_t1',
      lim='solo_superior', clas='moderada')
cx.execute("INSERT INTO umbral_alerta(fuente_id,biomarcador_id,sexo,operador,valor,mensaje) "
           "VALUES (5,?,NULL,'>',500,'Ferritina elevada: puede indicar sobrecarga de hierro u otra enfermedad "
           "(NTS 213 Tabla N° 14, nota d)')", (B_FER,))
lote(5, 11, 11, 0)

# =====================================================================
# 8 · AJUSTE POR ALTITUD — NTS 213 Tabla N° 1
# =====================================================================
oms = xl.parse('AJUSTE OMS 2024')
tramos = [(int(r.altitud_min_msnm), int(r.altitud_max_msnm), float(r.factor_ajuste_hemoglobina))
          for r in oms.itertuples()]
tramos.sort()
for (a1,b1,_), (a2,_,_) in zip(tramos, tramos[1:]):
    assert a2 == b1 + 1, f'hueco o solapamiento entre {b1} y {a2}'
cx.executemany('INSERT INTO ajuste_altitud(fuente_id,biomarcador_id,altitud_min_msnm,'
               'altitud_max_msnm,factor_ajuste,unidad) VALUES (3,?,?,?,?,?)',
               [(B_HB_MINSA, a, b, f, 'g/dl') for a, b, f in tramos])
lote(3, len(tramos), len(tramos), 0)

cx.executemany('INSERT INTO parametro_calculo(clave,valor,descripcion) VALUES (?,?,?)', [
 ('ajuste_hb_altitud_modo','restar_al_valor',
  'NTS 213 Tabla N° 1: la columna se titula "Disminuir". El ajuste se resta al valor observado.'),
 ('ajuste_hb_altitud_umbral_msnm','500',
  'NTS 213 §5.3.2: el ajuste se aplica en zonas con altitud > 500 msnm.'),
 ('ajuste_hb_altitud_residencia_meses','4',
  'NTS 213 §5.3.2: se considera la residencia de los últimos 4 meses, no el lugar del análisis.'),
 ('ajuste_hb_altitud_fuente', NTS + ', Tabla N° 1', 'Cita normativa del ajuste.'),
 ('ajuste_hb_altitud_metodo','tabla',
  'La ecuación impresa en la NTS no reproduce la tabla (transcripción incompleta del término cuadrático). '
  'Se implementa la tabla, que es el artefacto normativo.'),
 ('nomenclatura_indice','indice orientativo de seguimiento',
  'Nunca "puntaje de salud" ni terminología diagnóstica.'),
])

cx.executemany('INSERT INTO factor_severidad(nivel_desviacion,multiplicador) VALUES (?,?)',
               [('normal',1.0),('leve',1.25),('moderada',1.5),('severa',2.0)])

# =====================================================================
# 9 · CIE-10 — NTS 213 Tabla N° 23
# =====================================================================
cx.executemany('INSERT INTO codigo_cie10 VALUES (?,?,?)', [
 ('D50.0','Anemia por deficiencia de hierro secundaria a pérdida de sangre (crónica)','anemia'),
 ('D50.8','Otras anemias por deficiencia de hierro','anemia'),
 ('D50.9','Anemia por deficiencia de hierro sin especificación','anemia'),
 ('D64.9','Anemia de tipo no especificado','anemia'),
 ('D53.9','Anemia nutricional, no especificada','anemia'),
 ('O99.0','Anemia que complica el embarazo, el parto y el puerperio','anemia'),
])
lote(6, 6, 6, 0)

# =====================================================================
# 10 · Rechazos y cierre
# =====================================================================
l_gen = lote(2, 0, 0, 0)
cx.executemany('INSERT INTO registro_rechazado(lote_id,dato_crudo,regla_violada) VALUES (?,?,?)',
               [(lid if lid else l_gen, d, r) for lid, d, r in rechazos])
cx.commit()

# =====================================================================
# Informe
# =====================================================================
print('=' * 66)
print('QHALI · base construida:', DB)
print('=' * 66)
for t in ['fuente_referencia','ingesta_lote','distrito','alias_distrito','establecimiento_salud',
          'biomarcador','rango_referencia','umbral_alerta','ajuste_altitud','parametro_calculo',
          'codigo_cie10','registro_rechazado','peso_ponderacion']:
    print(f'  {t:24} {cx.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]:>7}')
print()
print('Distritos sin altitud:',
      cx.execute('SELECT COUNT(*) FROM distrito WHERE altitud_msnm IS NULL').fetchone()[0])
print('Establecimientos sin distrito válido: 0 (FK obligatoria)')
print('Distritos >1000 msnm:',
      cx.execute('SELECT COUNT(*) FROM distrito WHERE altitud_msnm>=1000').fetchone()[0])
cx.close()
