# Qhali — Estructura de Base de Datos

**Versión:** 0.1 — Documento de diseño inicial
**Fecha:** 2026-07-25 (pre-demo, Build with Gemma: GDG Callao)
**Responsable de implementación:** Jhair (estructuración de base personal)

---

## Decisión de arquitectura

**Una sola base de datos SQLite local con tres dominios lógicos** (no tres bases separadas).

| Criterio | Justificación |
|---|---|
| Procesamiento local/edge | SQLite es un archivo único por usuario, corre offline sin servidor |
| Simplicidad | Sin sincronización entre bases, sin múltiples conexiones |
| Cifrado (Fase 2) | SQLCipher cifra el archivo completo; clave derivada de usuario+contraseña con PBKDF2/Argon2 |
| Hackathon | SQLite estándar sin cifrar, misma estructura — migración directa a SQLCipher en Fase 2 |

---

## Dominio 1: Datos del usuario

> Principio: **cero PII**. El sistema no almacena nombres. Solo demografía mínima necesaria para aplicar rangos de referencia, más el distrito opcional para sugerencias de establecimientos.

```sql
CREATE TABLE usuario (
    id                  TEXT PRIMARY KEY,   -- UUID local, sin PII
    fecha_nacimiento    DATE NOT NULL,      -- requerido por rangos OMS (edad)
    sexo                TEXT NOT NULL,      -- requerido por rangos OMS
    distrito_residencia TEXT,               -- opcional, para sugerencias RENIPRESS
    creado_en           DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE documento (
    id                   TEXT PRIMARY KEY,
    usuario_id           TEXT NOT NULL REFERENCES usuario(id),
    tipo                 TEXT NOT NULL,     -- 'laboratorio' | 'receta' | 'imagenologia'
    fuente_obtencion     TEXT NOT NULL,     -- 'foto' | 'pdf' | 'manual'
    institucion_nombre   TEXT,              -- texto crudo extraído del membrete (SIEMPRE se guarda)
    institucion_id       INTEGER REFERENCES establecimiento_salud(id),
                                            -- FK solo si el match difuso supera el umbral
    distrito             TEXT,              -- distrito asociado al documento
    distrito_confianza   TEXT,              -- 'extraido' | 'inferido_por_institucion' | 'no_disponible'
    fecha_documento      DATE,
    fecha_carga          DATETIME DEFAULT CURRENT_TIMESTAMP,
    archivo_ruta         TEXT NOT NULL,
    estado_extraccion    TEXT DEFAULT 'pendiente'  -- 'pendiente' | 'procesado' | 'error'
);

CREATE TABLE estudio (
    id             TEXT PRIMARY KEY,
    documento_id   TEXT NOT NULL REFERENCES documento(id),
    categoria      TEXT NOT NULL,           -- 'hematologia' | 'bioquimica' | 'lipidos' | ...
    nombre_estudio TEXT NOT NULL
);

CREATE TABLE valor_extraido (
    id                   TEXT PRIMARY KEY,
    estudio_id           TEXT NOT NULL REFERENCES estudio(id),
    biomarcador_id       INTEGER NOT NULL REFERENCES biomarcador(id),
    valor_numerico       REAL,
    unidad               TEXT,
    valor_crudo_texto    TEXT NOT NULL,     -- lo que Gemma leyó literalmente (red de seguridad)
    confianza_extraccion REAL               -- score 0.0–1.0 de la extracción
);
```

### Reglas del dominio

1. `valor_crudo_texto` es **obligatorio**: permite al usuario auditar la extracción contra el documento original.
2. Gemma **nunca responde directamente** con datos médicos. Flujo: Gemma extrae → escribe en `valor_extraido` → la app consulta con SQL → la UI muestra resultados de la base. El modelo es capa de extracción, no de respuesta.
3. El match institución → RENIPRESS es **difuso** (normalización + similitud con umbral). Nunca se descarta un documento por falta de match.
4. El distrito tiene dos rutas de obtención (extraído del documento, o inferido vía institución matcheada). `distrito_confianza` registra cuál se usó, porque el cálculo de diferenciación entre instituciones depende de la confiabilidad de este dato.

---

## Dominio 2: Datos de referencia (OMS, MINSA, RENIPRESS, SuSalud)

> Solo lectura desde la app. Versionados por lote de ingesta. Nunca se mezclan con datos del usuario.

```sql
CREATE TABLE fuente_referencia (
    id             INTEGER PRIMARY KEY,
    nombre         TEXT NOT NULL,           -- 'OMS' | 'MINSA' | 'RENIPRESS' | 'SUSALUD'
    url_origen     TEXT,
    fecha_snapshot DATE,
    version        INTEGER NOT NULL
);

CREATE TABLE rango_referencia (
    id             INTEGER PRIMARY KEY,
    fuente_id      INTEGER NOT NULL REFERENCES fuente_referencia(id),
    biomarcador_id INTEGER NOT NULL REFERENCES biomarcador(id),
    sexo           TEXT,                    -- NULL = aplica a ambos
    edad_min       INTEGER,
    edad_max       INTEGER,
    valor_min      REAL NOT NULL,
    valor_max      REAL NOT NULL,
    unidad         TEXT NOT NULL,           -- ya normalizada a unidad_estandar en la carga
    clasificacion  TEXT,                    -- 'normal' | 'precaucion' | 'alerta'
    version        INTEGER NOT NULL         -- versionado aditivo: nunca se sobrescribe
);

CREATE TABLE establecimiento_salud (
    id        INTEGER PRIMARY KEY,
    fuente_id INTEGER NOT NULL REFERENCES fuente_referencia(id),
    nombre    TEXT NOT NULL,                -- normalizado (mayúsculas, sin tildes)
    categoria TEXT,                         -- 'I-1' ... 'III-2'
    distrito  TEXT,
    lat       REAL,
    lng       REAL,
    version   INTEGER NOT NULL
);
```

### Consulta clave: "último scan vs referencia"

```sql
-- JOIN entre valores del usuario y rangos vigentes, filtrado por demografía
SELECT v.valor_numerico, v.unidad, r.valor_min, r.valor_max, r.clasificacion
FROM valor_extraido v
JOIN biomarcador b       ON b.id = v.biomarcador_id
JOIN rango_referencia r  ON r.biomarcador_id = b.id
JOIN usuario u           ON u.id = :usuario_id
WHERE (r.sexo IS NULL OR r.sexo = u.sexo)
  AND CAST((julianday('now') - julianday(u.fecha_nacimiento)) / 365.25 AS INTEGER)
      BETWEEN r.edad_min AND r.edad_max
  AND r.version = (SELECT MAX(version) FROM ingesta_lote
                   WHERE fuente_id = r.fuente_id AND estado = 'completado');
```

### Rol de cada fuente

| Fuente | Aporta | No aporta |
|---|---|---|
| OMS | Rangos de referencia clínicos internacionales | — |
| MINSA | Normas técnicas, rangos nacionales, datos abiertos | — |
| RENIPRESS | Padrón de establecimientos (nombre, categoría, distrito, geo) | Rangos clínicos |
| SuSalud | Datos de supervisión del sistema de salud | Rangos clínicos |

RENIPRESS cierra el ciclo de acción: *"tu valor está fuera de rango → estos son los establecimientos en tu distrito"*.

---

## Dominio 3: Configuración del sistema

```sql
CREATE TABLE biomarcador (
    id              INTEGER PRIMARY KEY,
    nombre          TEXT NOT NULL,
    sistema_corporal TEXT NOT NULL,         -- 'sangre' | 'renal' | 'hepatico' | 'vision' | ...
    unidad_estandar TEXT NOT NULL,
    sinonimos       TEXT                    -- JSON array: ["Hb","hemoglobina","HGB"]
);

CREATE TABLE peso_ponderacion (
    id             INTEGER PRIMARY KEY,
    biomarcador_id INTEGER NOT NULL REFERENCES biomarcador(id),
    peso_base      REAL NOT NULL,           -- 0.0–1.0
    fuente_cita    TEXT NOT NULL            -- OBLIGATORIO: sin cita, el peso no entra
);

CREATE TABLE factor_severidad (
    id               INTEGER PRIMARY KEY,
    nivel_desviacion TEXT NOT NULL UNIQUE,  -- 'normal' | 'leve' | 'moderada' | 'severa'
    multiplicador    REAL NOT NULL          -- 1.0 | 1.25 | 1.5 | 2.0 (valores iniciales)
);

CREATE TABLE umbral_desviacion (
    id                 INTEGER PRIMARY KEY,
    biomarcador_id     INTEGER NOT NULL REFERENCES biomarcador(id),
    nivel_desviacion   TEXT NOT NULL,
    desviacion_min_pct REAL NOT NULL,       -- % fuera del rango de referencia
    desviacion_max_pct REAL NOT NULL,
    fuente_cita        TEXT                 -- requerido para los biomarcadores del alcance demo
);

CREATE TABLE parametro_calculo (
    id          INTEGER PRIMARY KEY,
    clave       TEXT NOT NULL UNIQUE,
    valor       TEXT NOT NULL,
    descripcion TEXT
);
```

### Fórmula del índice ponderado (con amplificación por severidad)

```
peso_efectivo(b) = peso_base(b) × factor_severidad(b)

factor_severidad según desviación respecto al rango de referencia:
    dentro del rango     → 1.0
    desviación leve      → 1.25
    desviación moderada  → 1.5
    desviación severa    → 2.0

índice = Σ ( calificación(b) × peso_efectivo(b) ) / Σ peso_efectivo(b)
```

La **renormalización** (división por `Σ peso_efectivo`) mantiene el índice comparable entre usuarios y entre scans en el tiempo.

> ⚠️ En UI y pitch el índice se denomina **"índice orientativo de seguimiento"**, nunca "puntaje de salud" ni nada que sugiera diagnóstico. Disclaimer visible en pantalla.

---

## Tablas de soporte ETL

```sql
CREATE TABLE ingesta_lote (
    id                   INTEGER PRIMARY KEY,
    fuente_id            INTEGER NOT NULL REFERENCES fuente_referencia(id),
    fecha_ejecucion      DATETIME DEFAULT CURRENT_TIMESTAMP,
    version              INTEGER NOT NULL,  -- incremental por fuente
    registros_leidos     INTEGER,
    registros_validos    INTEGER,
    registros_rechazados INTEGER,
    hash_origen          TEXT,              -- hash del archivo fuente: si no cambió, no se recarga
    estado               TEXT               -- 'completado' | 'parcial' | 'fallido'
);

CREATE TABLE registro_rechazado (
    id            INTEGER PRIMARY KEY,
    lote_id       INTEGER NOT NULL REFERENCES ingesta_lote(id),
    dato_crudo    TEXT NOT NULL,
    regla_violada TEXT NOT NULL
);
```

---

## Diagrama de relaciones (resumen)

```
usuario ─┬─< documento ─< estudio ─< valor_extraido >─ biomarcador
         │                    │                            │
         │        institucion_id                 ┌─────────┼──────────┐
         │             │                  peso_ponderacion │   umbral_desviacion
         │      establecimiento_salud            rango_referencia >─ fuente_referencia
         │             │                                   │
         └── distrito_residencia            ingesta_lote ──┴─< registro_rechazado
```

---

## Alcance para la hackathon (demo 25/07)

- SQLite sin cifrar (SQLCipher = Fase 2)
- 5–8 biomarcadores con rangos OMS bien documentados: hemoglobina, glucosa, colesterol total, LDL, HDL, triglicéridos, creatinina
- ETL ejecutado una vez de forma manual, con `hash_origen` y versionado ya funcionando
- Automatización programada (cron) del ETL = Fase 2, mencionada como roadmap
- Anonimización adicional de datos = Fase 2 (según tabla de fases)
