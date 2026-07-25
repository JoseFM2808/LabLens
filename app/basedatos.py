"""Base de datos Qhali: una sola SQLite local con tres dominios logicos.

El esquema arranca en el de `qhali-estructura-base-datos.md` v0.1 y se **amplia**
con el de la base validada por el equipo,
`BasedeDatos_Preparada/schema.sql` (Qhali v1.0). Este modulo solo crea la base y
presta conexiones; quien escribe es `repositorio.py`.

Por que ampliar y no reemplazar
-------------------------------
La v1.0 no es compatible columna a columna con la v0.1: el distrito pasa de
texto libre a tabla propia, las edades pasan de anios a dias, los rangos ganan
`condicion`, `tipo_limite` y severidad. Reemplazar el esquema obligaba a
reescribir de golpe todo lo que ya consulta la app y a botar los escaneos
existentes. Asi que la migracion es **aditiva**:

- se crean las tablas nuevas de la v1.0 (`distrito`, `alias_distrito`,
  `ajuste_altitud`, `umbral_alerta`, `codigo_cie10`) y la vista `v_evaluacion`;
- se agregan a las tablas que ya existian las columnas que la v1.0 trae de mas
  (ver `COLUMNAS_NUEVAS`), sin borrar las de la v0.1.

Las columnas de la v0.1 que quedan duplicadas (`rango_referencia.edad_min` en
anios junto a `edad_min_dias`, `documento.distrito` junto a `clave_norm`) se
llenan las dos en la carga, para que ninguna consulta ya escrita se rompa. Son
compatibilidad, no diseno: la fuente de verdad es la columna v1.0.

Dos diferencias frente a `schema.sql`, obligadas por SQLite: una columna que se
agrega con `ALTER TABLE` y referencia a otra tabla no puede ser NOT NULL, asi que
`establecimiento_salud.clave_norm` queda nulable (la carga la llena siempre), y
los indices UNIQUE se crean despues de la carga (ver `crear_indices_unicos`).

Alcance de lo que se llena
--------------------------
El camino scanner -> Gemma escribe:

    usuario -> documento -> estudio -> valor_extraido >- biomarcador

Los datos de referencia (Dominios 2 y 3) los carga
`herramientas/cargar_referencia.py` desde la base validada del equipo. Siguen
vacias a proposito:

    peso_ponderacion    sin cita normativa no entra ningun peso
    umbral_desviacion   tabla de la v0.1 que la v1.0 reemplaza por umbral_alerta

`biomarcador` tambien se puebla sobre la marcha porque
`valor_extraido.biomarcador_id` es NOT NULL: sin una fila de biomarcador no se
puede guardar ningun valor. Los que descubre el scanner y no coinciden con el
catalogo curado entran con ``sistema_corporal = 'sin_clasificar'`` para que se
distingan. Ver `repositorio.resolver_biomarcador`.

Cifrado: la Fase 2 pasa a SQLCipher con el mismo esquema. Nada de lo que hay
aqui depende de que la base este sin cifrar.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR_DATOS = RAIZ / "datos"
RUTA_BASE = DIR_DATOS / "qhali.sqlite3"

# Transcripcion literal del DDL del documento de diseno. El orden importa por
# las claves ajenas: biomarcador y establecimiento_salud antes de quien los
# referencia.
DDL = """
-- ==========================================================================
-- Dominio 3: Configuracion del sistema (biomarcador va primero por las FK)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS biomarcador (
    id               INTEGER PRIMARY KEY,
    nombre           TEXT NOT NULL,
    sistema_corporal TEXT NOT NULL,
    unidad_estandar  TEXT NOT NULL,
    sinonimos        TEXT
);

CREATE TABLE IF NOT EXISTS peso_ponderacion (
    id             INTEGER PRIMARY KEY,
    biomarcador_id INTEGER NOT NULL REFERENCES biomarcador(id),
    peso_base      REAL NOT NULL,
    fuente_cita    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS factor_severidad (
    id               INTEGER PRIMARY KEY,
    nivel_desviacion TEXT NOT NULL UNIQUE,
    multiplicador    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS umbral_desviacion (
    id                 INTEGER PRIMARY KEY,
    biomarcador_id     INTEGER NOT NULL REFERENCES biomarcador(id),
    nivel_desviacion   TEXT NOT NULL,
    desviacion_min_pct REAL NOT NULL,
    desviacion_max_pct REAL NOT NULL,
    fuente_cita        TEXT
);

CREATE TABLE IF NOT EXISTS parametro_calculo (
    id          INTEGER PRIMARY KEY,
    clave       TEXT NOT NULL UNIQUE,
    valor       TEXT NOT NULL,
    descripcion TEXT
);

-- ==========================================================================
-- Dominio 2: Datos de referencia (OMS, MINSA, RENIPRESS, SuSalud)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS fuente_referencia (
    id             INTEGER PRIMARY KEY,
    nombre         TEXT NOT NULL,
    url_origen     TEXT,
    fecha_snapshot DATE,
    version        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS rango_referencia (
    id             INTEGER PRIMARY KEY,
    fuente_id      INTEGER NOT NULL REFERENCES fuente_referencia(id),
    biomarcador_id INTEGER NOT NULL REFERENCES biomarcador(id),
    sexo           TEXT,
    edad_min       INTEGER,
    edad_max       INTEGER,
    valor_min      REAL NOT NULL,
    valor_max      REAL NOT NULL,
    unidad         TEXT NOT NULL,
    clasificacion  TEXT,
    version        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS establecimiento_salud (
    id        INTEGER PRIMARY KEY,
    fuente_id INTEGER NOT NULL REFERENCES fuente_referencia(id),
    nombre    TEXT NOT NULL,
    categoria TEXT,
    distrito  TEXT,
    lat       REAL,
    lng       REAL,
    version   INTEGER NOT NULL
);

-- ==========================================================================
-- Dominio 1: Datos del usuario (cero PII)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS usuario (
    id                  TEXT PRIMARY KEY,
    fecha_nacimiento    DATE NOT NULL,
    sexo                TEXT NOT NULL,
    distrito_residencia TEXT,
    creado_en           DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS documento (
    id                 TEXT PRIMARY KEY,
    usuario_id         TEXT NOT NULL REFERENCES usuario(id),
    tipo               TEXT NOT NULL,
    fuente_obtencion   TEXT NOT NULL,
    institucion_nombre TEXT,
    institucion_id     INTEGER REFERENCES establecimiento_salud(id),
    distrito           TEXT,
    distrito_confianza TEXT,
    fecha_documento    DATE,
    fecha_carga        DATETIME DEFAULT CURRENT_TIMESTAMP,
    archivo_ruta       TEXT NOT NULL,
    estado_extraccion  TEXT DEFAULT 'pendiente'
);

CREATE TABLE IF NOT EXISTS estudio (
    id             TEXT PRIMARY KEY,
    documento_id   TEXT NOT NULL REFERENCES documento(id),
    categoria      TEXT NOT NULL,
    nombre_estudio TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS valor_extraido (
    id                   TEXT PRIMARY KEY,
    estudio_id           TEXT NOT NULL REFERENCES estudio(id),
    biomarcador_id       INTEGER NOT NULL REFERENCES biomarcador(id),
    valor_numerico       REAL,
    unidad               TEXT,
    valor_crudo_texto    TEXT NOT NULL,
    confianza_extraccion REAL
);

-- ==========================================================================
-- Tablas de soporte ETL
-- ==========================================================================
CREATE TABLE IF NOT EXISTS ingesta_lote (
    id                   INTEGER PRIMARY KEY,
    fuente_id            INTEGER NOT NULL REFERENCES fuente_referencia(id),
    fecha_ejecucion      DATETIME DEFAULT CURRENT_TIMESTAMP,
    version              INTEGER NOT NULL,
    registros_leidos     INTEGER,
    registros_validos    INTEGER,
    registros_rechazados INTEGER,
    hash_origen          TEXT,
    estado               TEXT
);

CREATE TABLE IF NOT EXISTS registro_rechazado (
    id            INTEGER PRIMARY KEY,
    lote_id       INTEGER NOT NULL REFERENCES ingesta_lote(id),
    dato_crudo    TEXT NOT NULL,
    regla_violada TEXT NOT NULL
);

-- ==========================================================================
-- Indices
-- ==========================================================================
CREATE INDEX IF NOT EXISTS idx_documento_usuario ON documento (usuario_id);
CREATE INDEX IF NOT EXISTS idx_documento_carga ON documento (fecha_carga);
CREATE INDEX IF NOT EXISTS idx_estudio_documento ON estudio (documento_id);
CREATE INDEX IF NOT EXISTS idx_valor_estudio ON valor_extraido (estudio_id);
CREATE INDEX IF NOT EXISTS idx_valor_biomarcador ON valor_extraido (biomarcador_id);
CREATE INDEX IF NOT EXISTS idx_rango_biomarcador ON rango_referencia (biomarcador_id);
CREATE INDEX IF NOT EXISTS idx_establecimiento_distrito ON establecimiento_salud (distrito);
"""

# ==========================================================================
# Ampliacion v1.0: tablas que la v0.1 no tenia.
# Transcritas de BasedeDatos_Preparada/schema.sql. El orden importa por las FK:
# distrito antes de quien lo referencia.
# ==========================================================================
DDL_V1 = """
-- Geografia: la autoridad de nombres de distrito y su altitud.
CREATE TABLE IF NOT EXISTS distrito (
    clave_norm   TEXT PRIMARY KEY,        -- 'DEPARTAMENTO|PROVINCIA|DISTRITO'
    departamento TEXT NOT NULL,
    provincia    TEXT NOT NULL,
    nombre       TEXT NOT NULL,
    altitud_msnm INTEGER,                 -- NULL = sin dato; no se ajusta y la UI lo declara
    fuente_id    INTEGER NOT NULL REFERENCES fuente_referencia(id),
    version      INTEGER NOT NULL DEFAULT 1
);

-- Grafias de fuentes externas resueltas contra la tabla anterior. El match
-- difuso se corrio una sola vez en el ETL: en runtime todo es JOIN exacto.
CREATE TABLE IF NOT EXISTS alias_distrito (
    clave_origen   TEXT PRIMARY KEY,
    clave_canonica TEXT REFERENCES distrito(clave_norm),
    origen         TEXT NOT NULL,
    tipo_evidencia TEXT NOT NULL,
    nota           TEXT
);

-- Umbral que dispara alerta sin invalidar el rango normal (p. ej. endometrio:
-- normal hasta 14 mm, alerta a partir de 15 mm). Reemplaza umbral_desviacion.
CREATE TABLE IF NOT EXISTS umbral_alerta (
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

-- NTS 213 Tabla N.1: cuanto se le RESTA a la hemoglobina segun la altitud de
-- residencia. Solo aplica sobre 500 msnm (§5.3.2).
CREATE TABLE IF NOT EXISTS ajuste_altitud (
    id               INTEGER PRIMARY KEY,
    fuente_id        INTEGER NOT NULL REFERENCES fuente_referencia(id),
    biomarcador_id   INTEGER NOT NULL REFERENCES biomarcador(id),
    altitud_min_msnm INTEGER NOT NULL,
    altitud_max_msnm INTEGER NOT NULL,
    factor_ajuste    REAL NOT NULL,
    unidad           TEXT NOT NULL,
    version          INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS codigo_cie10 (
    codigo      TEXT PRIMARY KEY,
    descripcion TEXT NOT NULL,
    grupo       TEXT
);

CREATE INDEX IF NOT EXISTS idx_distrito_nombre ON distrito (nombre);
"""

# Indices que caen sobre columnas agregadas por COLUMNAS_NUEVAS: van despues de
# los ALTER TABLE, no en el DDL de las tablas.
INDICES_V1 = """
CREATE INDEX IF NOT EXISTS ix_estab_nombre ON establecimiento_salud (nombre_normalizado);
CREATE INDEX IF NOT EXISTS ix_estab_clave ON establecimiento_salud (clave_norm);
CREATE INDEX IF NOT EXISTS ix_rango_bio ON rango_referencia (biomarcador_id, clasificacion);
CREATE INDEX IF NOT EXISTS ix_usuario_distrito ON usuario (clave_distrito_residencia);
CREATE INDEX IF NOT EXISTS ix_documento_distrito ON documento (clave_norm);
"""

# Columnas que la v1.0 agrega a tablas que ya existian. Se aplican con
# ALTER TABLE ADD COLUMN, que en SQLite es barato y no reescribe la tabla.
#
# Restriccion de SQLite: una columna agregada con REFERENCES no puede ser
# NOT NULL, y una UNIQUE no se puede agregar aqui. Por eso `clave_norm`,
# `codigo_unico` y `dataset` quedan nulables aunque en schema.sql no lo sean;
# la carga las llena siempre y `crear_indices_unicos` pone los UNIQUE despues.
COLUMNAS_NUEVAS: dict[str, tuple[tuple[str, str], ...]] = {
    "fuente_referencia": (
        ("organismo", "TEXT"),                 # 'MINSA' | 'RENIPRESS' | 'OMS' | ...
        ("dataset", "TEXT"),                   # UNIQUE via crear_indices_unicos
        ("cita", "TEXT"),                      # NULL = sin respaldo documentado
        ("prioridad", "INTEGER NOT NULL DEFAULT 5"),  # 1 = mayor autoridad
    ),
    "rango_referencia": (
        ("condicion", "TEXT NOT NULL DEFAULT 'general'"),
        ("edad_min_dias", "INTEGER NOT NULL DEFAULT 0"),
        ("edad_max_dias", "INTEGER NOT NULL DEFAULT 43800"),  # ~120 anios, nunca NULL
        ("tipo_limite", "TEXT NOT NULL DEFAULT 'cerrado'"),
        ("altitud_max_aplicable", "INTEGER"),  # 500 en la tabla MINSA de Hb
    ),
    "establecimiento_salud": (
        ("codigo_unico", "TEXT"),
        ("institucion", "TEXT"),
        ("nombre_normalizado", "TEXT"),        # alimenta el match contra el membrete
        ("clave_norm", "TEXT REFERENCES distrito(clave_norm)"),
    ),
    "biomarcador": (
        ("nombre_normalizado", "TEXT"),
        ("matriz", "TEXT"),                    # 'sangre' | 'orina' | 'imagen' | 'clinico'
        ("categoria_examen", "TEXT"),
        ("direccionalidad", "TEXT NOT NULL DEFAULT 'bilateral'"),
        ("derivado", "INTEGER NOT NULL DEFAULT 0"),       # 1 = se calcula, no se extrae
        ("origen_dato", "TEXT NOT NULL DEFAULT 'documento'"),
        ("codigo_cpms", "TEXT"),
    ),
    "usuario": (
        ("condicion", "TEXT NOT NULL DEFAULT 'general'"),
        ("clave_distrito_residencia", "TEXT REFERENCES distrito(clave_norm)"),
        ("residencia_desde", "DATE"),          # NTS 213 §5.3.2: ultimos 4 meses
    ),
    "documento": (
        ("clave_norm", "TEXT REFERENCES distrito(clave_norm)"),
    ),
    "valor_extraido": (
        ("valor_ajustado", "REAL"),            # nunca sobrescribe valor_numerico
        ("ajuste_id", "INTEGER REFERENCES ajuste_altitud(id)"),
    ),
}

# Vista de evaluacion, copiada de schema.sql sin cambios: valor crudo, valor
# ajustado por altitud, clasificacion y la cita normativa que la respalda.
VISTA_EVALUACION = """
CREATE VIEW IF NOT EXISTS v_evaluacion AS
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
    r.organismo || ' - ' || COALESCE(r.cita, 'SIN CITA DOCUMENTADA') AS respaldo
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
"""

# Indices UNIQUE de la v1.0. Van aparte porque solo se pueden crear cuando las
# columnas ya estan llenas: si la base traia filas de la v0.1 con la columna en
# NULL, el indice se crea igual (SQLite permite varios NULL), pero si hubiera
# duplicados reales debe fallar de forma visible y no tumbar el arranque.
INDICES_UNICOS = (
    ("ux_fuente_dataset", "CREATE UNIQUE INDEX IF NOT EXISTS ux_fuente_dataset ON fuente_referencia (dataset)"),
    ("ux_estab_codigo", "CREATE UNIQUE INDEX IF NOT EXISTS ux_estab_codigo ON establecimiento_salud (codigo_unico, version)"),
    ("ux_biomarcador", "CREATE UNIQUE INDEX IF NOT EXISTS ux_biomarcador ON biomarcador (nombre_normalizado, matriz)"),
)

# Tablas que hoy quedan vacias a proposito. Se usa en el reporte de estado.
TABLAS_PENDIENTES = (
    "peso_ponderacion",   # sin cita normativa, ningun peso entra
    "umbral_desviacion",  # de la v0.1; la v1.0 la reemplaza por umbral_alerta
)

TABLAS_ACTIVAS = ("usuario", "documento", "estudio", "valor_extraido", "biomarcador")

# Datos de referencia: los carga herramientas/cargar_referencia.py desde la base
# validada por el equipo. Se listan para el reporte de estado.
TABLAS_REFERENCIA = (
    "fuente_referencia",
    "distrito",
    "alias_distrito",
    "establecimiento_salud",
    "rango_referencia",
    "umbral_alerta",
    "ajuste_altitud",
    "codigo_cie10",
    "parametro_calculo",
    "factor_severidad",
    "ingesta_lote",
    "registro_rechazado",
)


def conectar() -> sqlite3.Connection:
    """Conexion nueva con claves ajenas activas y filas accesibles por nombre.

    SQLite desactiva las claves ajenas por defecto y hay que encenderlas en
    cada conexion, no una sola vez en el archivo.
    """
    DIR_DATOS.mkdir(parents=True, exist_ok=True)
    conexion = sqlite3.connect(RUTA_BASE, timeout=15)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON")
    conexion.execute("PRAGMA journal_mode = WAL")
    return conexion


def columnas(conexion, tabla: str) -> set[str]:
    """Nombres de columna de una tabla. Vacio si la tabla no existe."""
    return {fila["name"] for fila in conexion.execute(f"PRAGMA table_info({tabla})")}


def _agregar_columnas(conexion) -> list[str]:
    """Aplica COLUMNAS_NUEVAS sobre las tablas que ya existian. Idempotente."""
    agregadas = []
    for tabla, nuevas in COLUMNAS_NUEVAS.items():
        existentes = columnas(conexion, tabla)
        if not existentes:  # la tabla no existe: nada que ampliar
            continue
        for nombre, definicion in nuevas:
            if nombre in existentes:
                continue
            conexion.execute(f"ALTER TABLE {tabla} ADD COLUMN {nombre} {definicion}")
            agregadas.append(f"{tabla}.{nombre}")
    return agregadas


def crear_indices_unicos() -> list[str]:
    """Crea los indices UNIQUE de la v1.0 y devuelve los que no se pudieron crear.

    Se llama al final de la carga de referencia, cuando las columnas nuevas ya
    tienen valor. Un duplicado real se reporta en vez de reventar el arranque:
    la base sigue usable y el aviso dice que hay catalogo que curar.
    """
    fallidos = []
    with conectar() as conexion:
        for nombre, sentencia in INDICES_UNICOS:
            try:
                conexion.execute(sentencia)
            except sqlite3.IntegrityError as error:
                fallidos.append(f"{nombre}: {error}")
    return fallidos


def inicializar() -> Path:
    """Crea la base, la amplia a la v1.0 y deja la vista lista. Idempotente."""
    DIR_DATOS.mkdir(parents=True, exist_ok=True)
    with conectar() as conexion:
        conexion.executescript(DDL)         # base v0.1
        conexion.executescript(DDL_V1)      # tablas nuevas de la v1.0
        # Las columnas van despues de las dos tandas de tablas, porque hay
        # columnas que referencian tablas que recien crea DDL_V1
        # (`valor_extraido.ajuste_id` -> `ajuste_altitud`).
        _agregar_columnas(conexion)
        # Y los indices al final: `ix_estab_nombre` cae sobre
        # `establecimiento_salud.nombre_normalizado`, que es una de esas columnas
        # nuevas. Crearlo antes fallaba con "no such column" sobre cualquier base
        # que ya existiera con el esquema v0.1, y el servidor no arrancaba.
        conexion.executescript(INDICES_V1)
        conexion.executescript(VISTA_EVALUACION)
    return RUTA_BASE


def estado() -> dict:
    """Conteo de filas por tabla: lo del usuario, lo de referencia y lo pendiente."""
    with conectar() as conexion:
        nombres = {
            fila["name"]
            for fila in conexion.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

        def contar(tabla: str) -> int | None:
            if tabla not in nombres:
                return None
            return conexion.execute(f"SELECT COUNT(*) AS n FROM {tabla}").fetchone()["n"]

        return {
            "ruta": str(RUTA_BASE),
            "existe": RUTA_BASE.exists(),
            "tablas": len(nombres - {"sqlite_sequence"}),
            "activas": {tabla: contar(tabla) for tabla in TABLAS_ACTIVAS},
            "referencia": {tabla: contar(tabla) for tabla in TABLAS_REFERENCIA},
            "pendientes": {tabla: contar(tabla) for tabla in TABLAS_PENDIENTES},
        }
