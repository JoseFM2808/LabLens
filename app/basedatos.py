"""Base de datos Qhali: una sola SQLite local con tres dominios logicos.

El esquema es el de `qhali-estructura-base-datos.md` v0.1, transcrito sin
cambios. Este modulo solo crea la base y presta conexiones; quien escribe es
`repositorio.py`.

Alcance de lo que se llena hoy
------------------------------
Se crean **todas** las tablas, pero solo se escriben las del camino
scanner -> Gemma:

    usuario -> documento -> estudio -> valor_extraido >- biomarcador

Quedan **vacias a proposito** (pendientes):
    Dominio 2: fuente_referencia, rango_referencia, establecimiento_salud
    Dominio 3: peso_ponderacion, factor_severidad, umbral_desviacion,
               parametro_calculo
    ETL:       ingesta_lote, registro_rechazado

`biomarcador` es de Dominio 3 pero se puebla sobre la marcha porque
`valor_extraido.biomarcador_id` es NOT NULL: sin una fila de biomarcador no se
puede guardar ningun valor. Los que descubre el scanner entran con
``sistema_corporal = 'sin_clasificar'`` para que se distingan de los curados a
mano. Ver `repositorio.resolver_biomarcador`.

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

# Tablas que hoy quedan vacias a proposito. Se usa en el reporte de estado.
TABLAS_PENDIENTES = (
    "fuente_referencia",
    "rango_referencia",
    "establecimiento_salud",
    "peso_ponderacion",
    "factor_severidad",
    "umbral_desviacion",
    "parametro_calculo",
    "ingesta_lote",
    "registro_rechazado",
)

TABLAS_ACTIVAS = ("usuario", "documento", "estudio", "valor_extraido", "biomarcador")


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


def inicializar() -> Path:
    """Crea la base y todas las tablas si no existen. Idempotente."""
    DIR_DATOS.mkdir(parents=True, exist_ok=True)
    with conectar() as conexion:
        conexion.executescript(DDL)
    return RUTA_BASE


def estado() -> dict:
    """Conteo de filas por tabla, separando lo activo de lo pendiente."""
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
            "pendientes": {tabla: contar(tabla) for tabla in TABLAS_PENDIENTES},
        }
