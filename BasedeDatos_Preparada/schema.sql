-- =====================================================================
-- QHALI — Esquema final v1.0
-- Base SQLite local. Tres dominios lógicos en un solo archivo.
-- Fuentes: RENIPRESS · altitud distrital · NTS N° 213-MINSA/DGIESP-2024
--          (RM 251-2024/MINSA, mod. RM 429-2024/MINSA) · panel de laboratorio
-- =====================================================================
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- DOMINIO 2 · Fuentes y trazabilidad de ingesta
-- ---------------------------------------------------------------------
CREATE TABLE fuente_referencia (
    id             INTEGER PRIMARY KEY,
    organismo      TEXT NOT NULL,          -- 'MINSA' | 'RENIPRESS' | 'OMS' | 'LABORATORIO' | 'POR_DEFINIR'
    dataset        TEXT NOT NULL UNIQUE,
    cita           TEXT,                   -- referencia normativa exacta; NULL = sin respaldo documentado
    url_origen     TEXT,
    fecha_snapshot DATE,
    prioridad      INTEGER NOT NULL DEFAULT 5,  -- 1 = mayor autoridad; desempata rangos duplicados
    version        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE ingesta_lote (
    id                   INTEGER PRIMARY KEY,
    fuente_id            INTEGER NOT NULL REFERENCES fuente_referencia(id),
    fecha_ejecucion      DATETIME DEFAULT CURRENT_TIMESTAMP,
    version              INTEGER NOT NULL,
    registros_leidos     INTEGER,
    registros_validos    INTEGER,
    registros_rechazados INTEGER,
    hash_origen          TEXT,
    estado               TEXT             -- 'completado' | 'parcial' | 'fallido'
);

CREATE TABLE registro_rechazado (
    id            INTEGER PRIMARY KEY,
    lote_id       INTEGER NOT NULL REFERENCES ingesta_lote(id),
    dato_crudo    TEXT NOT NULL,
    regla_violada TEXT NOT NULL
);

-- ---------------------------------------------------------------------
-- DOMINIO 2 · Geografía
-- ---------------------------------------------------------------------
CREATE TABLE distrito (
    clave_norm   TEXT PRIMARY KEY,        -- 'DEPARTAMENTO|PROVINCIA|DISTRITO' normalizado
    departamento TEXT NOT NULL,
    provincia    TEXT NOT NULL,
    nombre       TEXT NOT NULL,
    altitud_msnm INTEGER,                 -- NULL = sin dato; no se ajusta y la UI lo declara
    fuente_id    INTEGER NOT NULL REFERENCES fuente_referencia(id),
    version      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE alias_distrito (
    clave_origen   TEXT PRIMARY KEY,      -- grafía tal como aparece en la fuente externa
    clave_canonica TEXT REFERENCES distrito(clave_norm),
    origen         TEXT NOT NULL,         -- 'RENIPRESS'
    tipo_evidencia TEXT NOT NULL,         -- ver documentación de resolución
    nota           TEXT
);

CREATE TABLE establecimiento_salud (
    id                 INTEGER PRIMARY KEY,
    fuente_id          INTEGER NOT NULL REFERENCES fuente_referencia(id),
    codigo_unico       TEXT NOT NULL,
    institucion        TEXT,
    nombre             TEXT NOT NULL,
    nombre_normalizado TEXT NOT NULL,     -- alimenta el match difuso contra el membrete
    clave_norm         TEXT NOT NULL REFERENCES distrito(clave_norm),
    version            INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX ux_estab_codigo ON establecimiento_salud(codigo_unico, version);
CREATE INDEX ix_estab_nombre       ON establecimiento_salud(nombre_normalizado);
CREATE INDEX ix_estab_clave        ON establecimiento_salud(clave_norm);

-- ---------------------------------------------------------------------
-- DOMINIO 3 · Catálogo de biomarcadores
-- ---------------------------------------------------------------------
CREATE TABLE biomarcador (
    id                 INTEGER PRIMARY KEY,
    nombre             TEXT NOT NULL,
    nombre_normalizado TEXT NOT NULL,
    matriz             TEXT NOT NULL,     -- 'sangre' | 'orina' | 'imagen' | 'clinico'
    categoria_examen   TEXT NOT NULL,     -- 'hematologia' | 'bioquimica' | 'orina' | 'ginecologia' | 'signos_vitales' | 'antropometria'
    sistema_corporal   TEXT,
    unidad_estandar    TEXT NOT NULL,     -- 'adimensional' cuando no aplica unidad
    direccionalidad    TEXT NOT NULL DEFAULT 'bilateral',
                                          -- 'bilateral' | 'menor_es_mejor' | 'mayor_es_mejor'
    derivado           INTEGER NOT NULL DEFAULT 0,  -- 1 = se calcula, no se extrae del documento
    origen_dato        TEXT NOT NULL DEFAULT 'documento', -- 'documento' | 'ingreso_manual'
    codigo_cpms        TEXT,              -- Catálogo de Procedimientos Médicos y Sanitarios (RM 1044-2020)
    sinonimos          TEXT               -- JSON array
);
CREATE UNIQUE INDEX ux_biomarcador ON biomarcador(nombre_normalizado, matriz);

-- ---------------------------------------------------------------------
-- DOMINIO 2 · Rangos de referencia
-- ---------------------------------------------------------------------
CREATE TABLE rango_referencia (
    id             INTEGER PRIMARY KEY,
    fuente_id      INTEGER NOT NULL REFERENCES fuente_referencia(id),
    biomarcador_id INTEGER NOT NULL REFERENCES biomarcador(id),
    sexo           TEXT,                  -- NULL = ambos; 'F' | 'M'
    condicion      TEXT NOT NULL DEFAULT 'general',
                                          -- 'general' | 'prematuro' | 'a_termino' | 'no_gestante'
                                          -- | 'gestante_t1' | 'gestante_t2' | 'gestante_t3' | 'puerpera'
    edad_min_dias  INTEGER NOT NULL DEFAULT 0,
    edad_max_dias  INTEGER NOT NULL DEFAULT 43800,   -- ~120 años; NUNCA NULL (BETWEEN con NULL no matchea)
    valor_min      REAL NOT NULL,
    valor_max      REAL NOT NULL,
    unidad         TEXT NOT NULL,
    tipo_limite    TEXT NOT NULL DEFAULT 'cerrado',  -- 'cerrado' | 'solo_superior' | 'solo_inferior'
    clasificacion  TEXT NOT NULL DEFAULT 'normal',   -- 'normal' | 'leve' | 'moderada' | 'severa'
    altitud_max_aplicable INTEGER,         -- p. ej. 500 para la tabla MINSA de Hb
    version        INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX ix_rango_bio ON rango_referencia(biomarcador_id, clasificacion);

-- Umbral que dispara alerta sin invalidar el rango normal
-- (p. ej. endometrio: normal hasta 14 mm, alerta a partir de 15 mm)
CREATE TABLE umbral_alerta (
    id             INTEGER PRIMARY KEY,
    fuente_id      INTEGER NOT NULL REFERENCES fuente_referencia(id),
    biomarcador_id INTEGER NOT NULL REFERENCES biomarcador(id),
    sexo           TEXT,
    operador       TEXT NOT NULL,         -- '>' | '>=' | '<' | '<=' | 'fuera_de'
    valor          REAL NOT NULL,
    valor_2        REAL,                  -- solo para 'fuera_de'
    mensaje        TEXT NOT NULL,
    version        INTEGER NOT NULL DEFAULT 1
);

-- ---------------------------------------------------------------------
-- DOMINIO 3 · Ajuste por altitud
-- ---------------------------------------------------------------------
CREATE TABLE ajuste_altitud (
    id               INTEGER PRIMARY KEY,
    fuente_id        INTEGER NOT NULL REFERENCES fuente_referencia(id),
    biomarcador_id   INTEGER NOT NULL REFERENCES biomarcador(id),
    altitud_min_msnm INTEGER NOT NULL,
    altitud_max_msnm INTEGER NOT NULL,
    factor_ajuste    REAL NOT NULL,
    unidad           TEXT NOT NULL,
    version          INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE parametro_calculo (
    id          INTEGER PRIMARY KEY,
    clave       TEXT NOT NULL UNIQUE,
    valor       TEXT NOT NULL,
    descripcion TEXT
);

-- ---------------------------------------------------------------------
-- DOMINIO 3 · Ponderación (vacía hasta tener citas)
-- ---------------------------------------------------------------------
CREATE TABLE peso_ponderacion (
    id             INTEGER PRIMARY KEY,
    biomarcador_id INTEGER NOT NULL REFERENCES biomarcador(id),
    peso_base      REAL NOT NULL,
    fuente_cita    TEXT NOT NULL          -- OBLIGATORIO: sin cita, el peso no entra
);

CREATE TABLE factor_severidad (
    id               INTEGER PRIMARY KEY,
    nivel_desviacion TEXT NOT NULL UNIQUE,
    multiplicador    REAL NOT NULL
);

-- ---------------------------------------------------------------------
-- DOMINIO 3 · Codificación clínica
-- ---------------------------------------------------------------------
CREATE TABLE codigo_cie10 (
    codigo      TEXT PRIMARY KEY,
    descripcion TEXT NOT NULL,
    grupo       TEXT
);

-- ---------------------------------------------------------------------
-- DOMINIO 1 · Datos del usuario  (cero PII)
-- ---------------------------------------------------------------------
CREATE TABLE usuario (
    id                        TEXT PRIMARY KEY,
    fecha_nacimiento          DATE NOT NULL,
    sexo                      TEXT NOT NULL,   -- 'F' | 'M'
    condicion                 TEXT NOT NULL DEFAULT 'general',
    clave_distrito_residencia TEXT REFERENCES distrito(clave_norm),
    residencia_desde          DATE,            -- NTS 213 §5.3.2: residencia de los últimos 4 meses
    creado_en                 DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE documento (
    id                 TEXT PRIMARY KEY,
    usuario_id         TEXT NOT NULL REFERENCES usuario(id),
    tipo               TEXT NOT NULL,    -- 'laboratorio' | 'receta' | 'imagenologia' | 'signos_vitales'
    fuente_obtencion   TEXT NOT NULL,    -- 'foto' | 'pdf' | 'manual'
    institucion_nombre TEXT,             -- texto crudo del membrete: SIEMPRE se guarda
    institucion_id     INTEGER REFERENCES establecimiento_salud(id),
    clave_norm         TEXT REFERENCES distrito(clave_norm),
    distrito_confianza TEXT,             -- 'extraido' | 'inferido_por_institucion' | 'no_disponible'
    fecha_documento    DATE,
    fecha_carga        DATETIME DEFAULT CURRENT_TIMESTAMP,
    archivo_ruta       TEXT NOT NULL,
    estado_extraccion  TEXT DEFAULT 'pendiente'
);

CREATE TABLE estudio (
    id             TEXT PRIMARY KEY,
    documento_id   TEXT NOT NULL REFERENCES documento(id),
    categoria      TEXT NOT NULL,
    nombre_estudio TEXT NOT NULL
);

CREATE TABLE valor_extraido (
    id                   TEXT PRIMARY KEY,
    estudio_id           TEXT NOT NULL REFERENCES estudio(id),
    biomarcador_id       INTEGER NOT NULL REFERENCES biomarcador(id),
    valor_numerico       REAL,
    unidad               TEXT,
    valor_crudo_texto    TEXT NOT NULL,   -- lo que Gemma leyó literalmente: red de seguridad
    confianza_extraccion REAL,
    valor_ajustado       REAL,            -- nunca sobrescribe valor_numerico
    ajuste_id            INTEGER REFERENCES ajuste_altitud(id)  -- NULL = no se aplicó ajuste
);

-- ---------------------------------------------------------------------
-- Vista de evaluación: valor crudo, valor ajustado y clasificación
-- ---------------------------------------------------------------------
CREATE VIEW v_evaluacion AS
WITH aplicable AS (
    SELECT r.*, f.prioridad, f.organismo, f.cita
    FROM rango_referencia r
    JOIN fuente_referencia f ON f.id = r.fuente_id
),
mejor AS (   -- por biomarcador gana la fuente de mayor autoridad (prioridad menor)
    SELECT biomarcador_id, MIN(prioridad) AS prioridad FROM aplicable GROUP BY biomarcador_id
)
SELECT
    u.id                                        AS usuario_id,
    b.id                                        AS biomarcador_id,
    b.nombre                                    AS biomarcador,
    b.unidad_estandar                           AS unidad,
    v.valor_numerico                            AS valor_crudo,
    d.altitud_msnm                              AS altitud_msnm,
    a.factor_ajuste                             AS factor_ajuste,
    ROUND(COALESCE(v.valor_numerico - a.factor_ajuste, v.valor_numerico), 2) AS valor_evaluado,
    CASE WHEN a.id IS NULL THEN 'sin_ajuste' ELSE 'ajustado_por_altitud' END AS estado_ajuste,
    r.valor_min, r.valor_max, r.tipo_limite, r.clasificacion,
    r.organismo || ' — ' || COALESCE(r.cita, 'SIN CITA DOCUMENTADA') AS respaldo
FROM valor_extraido v
JOIN estudio          e  ON e.id  = v.estudio_id
JOIN documento       do  ON do.id = e.documento_id
JOIN usuario          u  ON u.id  = do.usuario_id
JOIN biomarcador      b  ON b.id  = v.biomarcador_id
LEFT JOIN distrito    d  ON d.clave_norm = u.clave_distrito_residencia
LEFT JOIN ajuste_altitud a
       ON a.biomarcador_id = b.id
      AND a.factor_ajuste > 0
      AND d.altitud_msnm BETWEEN a.altitud_min_msnm AND a.altitud_max_msnm
JOIN mejor    m ON m.biomarcador_id = b.id
JOIN aplicable r ON r.biomarcador_id = b.id AND r.prioridad = m.prioridad
WHERE (r.sexo IS NULL OR r.sexo = u.sexo)
  AND (r.condicion = 'general' OR r.condicion = u.condicion)
  AND CAST(julianday('now') - julianday(u.fecha_nacimiento) AS INTEGER)
      BETWEEN r.edad_min_dias AND r.edad_max_dias
  AND ROUND(COALESCE(v.valor_numerico - a.factor_ajuste, v.valor_numerico), 2)
      BETWEEN r.valor_min AND r.valor_max;
