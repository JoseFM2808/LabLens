# Qhali — Base de Datos Final v1.0

**Entregables:** `qhali.db` (SQLite, 5.5 MB) · `schema.sql` · `build_qhali.py` (ETL reproducible) · `alias_distrito_final.csv`

Para reconstruirla desde cero: `python3 build_qhali.py`. Idempotente, con `hash_origen` y versionado activos.

---

## El hallazgo principal: el PDF cierra las dos dudas bloqueantes

La **NTS N° 213-MINSA/DGIESP-2024** no solo trae la cita del ajuste por altitud. Trae también la tabla de hemoglobina que faltaba.

### 1. El ajuste por altitud — resuelto

- **Tabla N° 1**, columna titulada **"Disminuir"** → el factor **se resta al valor observado**. La duda del sentido queda cerrada.
- **§5.3.2:** el ajuste aplica **solo por encima de 500 msnm** y se calcula sobre la **residencia de los últimos 4 meses**, no sobre el lugar donde se hizo el análisis. Esto también responde la duda sobre mudanzas: la base ahora tiene `usuario.residencia_desde`.
- La tabla del Excel coincide exactamente con la Tabla N° 1 de la norma. Validada: 11 tramos contiguos, sin huecos.

> ⚠️ **La ecuación impresa en la NTS no reproduce su propia tabla.** El PDF muestra `(0,0056384 × elevación) + (0,0000003 × elevación)`, que a 3 250 msnm da **18.3 g/dL** donde la tabla dice **2.1**. Se perdieron decimales y el término cuadrático en la transcripción. **La base implementa la tabla, no la fórmula** — la tabla es el artefacto normativo y la fórmula es una nota al pie mal transcrita. Queda registrado en `parametro_calculo`.

### 2. La hemoglobina — resuelta, y cambia el producto

La **Tabla N° 13** ("Valores normales de concentración de hemoglobina y niveles de anemia, hasta 500 msnm") da lo que faltaba: rangos estratificados por **edad, sexo y condición**, con **niveles de severidad** (leve / moderada / severa) ya definidos.

Esto reemplaza el rango sin cita `11.00 – 16.00` del panel de laboratorio. Y no es un cambio cosmético:

| Caso | Panel de laboratorio | NTS 213 |
|---|---|---|
| Mujer 30 años, no gestante, Hb 11.5 en Lima | **Normal** | **Anemia leve** |

Con el rango sin cita, la app le habría dicho a esa usuaria que está bien. Es exactamente el error que el proyecto existe para evitar.

Ambos rangos siguen cargados; la vista `v_evaluacion` desempata por `fuente_referencia.prioridad` y MINSA gana. El panel de laboratorio queda como respaldo visible, no borrado.

### 3. Bonus del PDF

- **Tabla N° 14** → cortes de ferritina por grupo etario, cargados con cita.
- **Tabla N° 23** → códigos CIE-10 de anemia, en `codigo_cie10`.
- **Tabla N° 24** → códigos CPMS (85018 hemoglobina, 82728 ferritina, 85031 hemograma), en `biomarcador.codigo_cpms`.
- **§5.1** define anemia como Hb por debajo de 2 desviaciones estándar del promedio según género, edad y altura a nivel del mar. Es la frase que respalda todo el diseño.

---

## ⚠️ Pendiente normativo

La NTS 213 fue **modificada por la RM 429-2024/MINSA** (publicada el 19/06/2024). El PDF que subiste es la versión original (RM 251-2024). La modificatoria afecta principalmente las Tablas N° 4 y N° 20 (calendario de mediciones) y las presentaciones de suplementos — la Tabla N° 1 y la Tabla N° 13 coinciden con lo que circula después de la modificatoria, así que lo cargado es seguro. Aun así, conviene descargar la RM 429 antes de citar la norma en el pitch.

---

## Contenido de la base

| Tabla | Filas |
|---|---:|
| `distrito` | **1 895** |
| `alias_distrito` | 27 |
| `establecimiento_salud` | **26 798** |
| `biomarcador` | 45 |
| `rango_referencia` | 111 |
| `umbral_alerta` | 14 |
| `ajuste_altitud` | 11 |
| `codigo_cie10` | 6 |
| `parametro_calculo` | 6 |
| `registro_rechazado` | 32 |
| `peso_ponderacion` | **0** ← intencional |

Biomarcadores: hematología 21 · bioquímica 9 · signos vitales 6 · ginecología 4 · antropometría 3 · orina 2.

`peso_ponderacion` está vacía a propósito. La regla se mantiene: sin cita, el peso no entra. Hoy solo hemoglobina y ferritina tienen respaldo normativo suficiente.

---

## Distritos: qué se corrigió y qué no

**27 grafías corregidas.** La autoridad de nombres es la tabla de altitudes (censo nacional completo de 1 893 distritos); las grafías de RENIPRESS se resuelven contra ella vía `alias_distrito`. El match difuso se corrió una sola vez en el ETL y quedó congelado — **en runtime todo es JOIN exacto**, cero similitud de cadenas.

| Evidencia | Casos | Ejemplo |
|---|---:|---|
| A — variante en el nombre de la provincia | 6 | `ANTONIO RAIMONDI` → `ANTONIO RAYMONDI` (distrito idéntico) |
| B — truncamiento / abreviatura / nombre corto | 6 | `SANTA CRUZ DE TOLED` → `…TOLEDO` · `CASTA` → `SAN PEDRO DE CASTA` |
| C — variante ortográfica | 11 | `MILPUCC` → `MILPUC` · `CAPASO` → `CAPAZO` · `KIMBIRI` → `QUIMBIRI` |
| D — forzado por eliminación en la provincia | 4 | `PAMPAS GRANDE` → `PAMPAS` · `HUALLA` → `HUAYA` |

**2 distritos entraron con `altitud_msnm = NULL`.** No se les inventó un valor:

- **`ALTO TRUJILLO`** — Trujillo tiene 12 distritos en RENIPRESS y 11 en la tabla de altitudes. Es de creación reciente y no está.
- **`SAN JOSE DE LOS CHORRILLOS`** — en Huarochirí sobraban dos nombres de cada lado: `CASTA` / `SAN JOSE DE LOS CHORRILLOS` contra `SAN PEDRO DE CASTA` / `CUENCA`. `CASTA` → `SAN PEDRO DE CASTA` es evidente; por descarte quedaría `SAN JOSE DE LOS CHORRILLOS` → `CUENCA`, **y ese par se rechazó**. La explicación más probable es que Cuenca es un distrito real sin establecimientos registrados y San José de los Chorrillos es un centro poblado cargado como distrito en RENIPRESS. Emparejarlos habría convertido un error de la fuente en un dato falso.

Además, **19 distritos vienen con altitud vacía en la fuente** (Cielo Punco, Kumpirushiato, Putis, Santa María de Huachipa y otros). Mismo tratamiento.

**Total: 21 distritos sin altitud de 1 895.** Con altitud NULL no hay ajuste, y la vista devuelve `estado_ajuste = 'sin_ajuste'` para que la UI lo declare en pantalla.

Los 26 798 establecimientos quedaron con FK de distrito válida. Cero huérfanos.

---

## Inconsistencias corregidas

| # | Problema | Corrección |
|---|---|---|
| 1 | Rango de Hb sin cita, sin estratificar por sexo | Tabla N° 13 de la NTS 213, por edad/sexo/condición, con severidad |
| 2 | Sentido del ajuste por altitud sin definir | `restar_al_valor`, con la cita en `parametro_calculo` |
| 3 | Ajuste aplicado a cualquier altitud | Solo > 500 msnm (§5.3.2) |
| 4 | Altitud tomada del establecimiento | Se toma de la residencia; se agregó `residencia_desde` |
| 5 | `edad_min`/`edad_max` en NULL rompían el `BETWEEN` | `edad_min_dias` / `edad_max_dias` NOT NULL con default 0 / 43800 |
| 6 | Edad en años no cubría neonatos | Todo en **días**: la NTS estratifica por semanas en prematuros |
| 7 | `LDL 0-99`, `Triglicéridos 0-159`, `HDL 50-200` como rangos cerrados | `tipo_limite` + `direccionalidad`: un LDL de 30 ya no se penaliza |
| 8 | Glucosa en sangre y en orina colisionaban | `UNIQUE(nombre_normalizado, matriz)` |
| 9 | Índices Col/HDL y LDL/HDL como biomarcadores extraíbles | `derivado = 1` |
| 10 | Hoja HEMATOLOGIA con título en la fila 0 | Lectura con `header=1`; se recuperó Hematíes |
| 11 | Unidad `-` rompía el `NOT NULL` | `'adimensional'` |
| 12 | Signos vitales tratados como datos de laboratorio | `origen_dato = 'ingreso_manual'` |
| 13 | Endometrio: hueco aparente entre 14 y 15 mm | Corregido según tu indicación: **14.5 es normal**. `rango_referencia` 1–14 y `umbral_alerta > 15` son cosas distintas |
| 14 | Volumen ovárico: nota contradecía el rango | Igual: rango normal 2–15, alerta > 15 |
| 15 | Ecuación de la NTS no reproduce su tabla | Se implementa la tabla; queda documentado |
| 16 | Conflicto silencioso entre fuentes del mismo biomarcador | `fuente_referencia.prioridad`; la vista desempata y muestra el respaldo |

**Tu corrección del 14.5 cambió el modelo para mejor.** Separar "rango normal" de "umbral de alerta" en dos tablas resultó ser lo correcto también para signos vitales: la presión sistólica tiene rango normal 90–119 y alerta ≥120, que son dos afirmaciones distintas y no un rango con un hueco.

---

## Validación ejecutada

```
rangos con edad NULL ............ 0
rangos con valor_min > valor_max . 0
biomarcadores sin unidad ......... 0
alias que no resuelven ........... 0
pesos sin cita ................... 0
establecimientos sin distrito .... 0
tramos de altitud contiguos ...... OK (assert en el ETL)
```

### Casos de prueba

```
Hb 11.5 g/dl — mujer 30 años, no gestante
  Lima              162 msnm   sin ajuste     11.50   LEVE
  Puno             3848 msnm   −2.5            9.00   MODERADA

Hb 13.8 g/dl — el mismo valor "normal"
  Lima              162 msnm   sin ajuste     13.80   NORMAL
  Cerro de Pasco   4373 msnm   −2.9           10.90   MODERADA

Gestante 2º trimestre, Hb 10.8
  Huancavelica     3746 msnm   −2.5            8.30   MODERADA

Distrito sin altitud
  Alto Trujillo      NULL      sin ajuste     11.50   LEVE   [estado: sin_ajuste]
```

El caso de Cerro de Pasco es el más fuerte para la demo: **13.8 g/dL suena a hemoglobina sana en cualquier lectura ingenua, y a 4 373 msnm es anemia moderada según la norma peruana vigente.** Un solo dato, dos lecturas, y la segunda con resolución ministerial detrás.

---

## Cómo consultar

```sql
SELECT biomarcador, valor_crudo, altitud_msnm, factor_ajuste,
       valor_evaluado, clasificacion, estado_ajuste, respaldo
FROM v_evaluacion
WHERE usuario_id = :uid;
```

La vista aplica en un solo paso: filtro por sexo, condición y edad en días · ajuste por altitud si corresponde · desempate por autoridad de la fuente · devuelve la cita normativa junto al resultado. Si no hay ajuste, `estado_ajuste = 'sin_ajuste'` y la UI debe decir por qué.

---

## Lo que sigue abierto

| # | Pendiente | Por qué importa |
|---|---|---|
| 1 | **RM 429-2024/MINSA** (modificatoria de la NTS 213) | Para citar la norma completa y verificada |
| 2 | **Organismo y año de la tabla de altitudes** | Alimenta un cálculo clínico y es la única fuente geográfica sin cita |
| 3 | **Origen de los paneles** de hematología, bioquímica, orina, ginecología y signos vitales | Sin cita quedan como catálogo; no entran al índice ponderado |
| 4 | **Criterio de presión arterial**: alerta ≥120 (ACC/AHA) vs ≥140 (OMS/MINSA) | Marcar alerta a 120 alarma a mucha gente sana |
| 5 | **`Saturación O2 (Costa)`** sin tabla por altitud | Cargado con advertencia en el mensaje de alerta. Mismo problema que la Hb, sin la tabla que lo resuelva |
| 6 | **Endometrio depende del ciclo menstrual** | La base no modela fase del ciclo ni estado menopáusico |
| 7 | **¿El usuario declara su distrito de residencia?** | Sin ese dato no hay ajuste, y el ajuste es la demo |
| 8 | **Peso y talla** para el IMC | El IMC está en el catálogo pero no hay de dónde calcularlo |
| 9 | **`peso_ponderacion`** vacía | Hoy solo Hb y ferritina tienen respaldo suficiente para pesar |

El pendiente 2 es ahora el más urgente. Con la NTS 213 en mano, la hemoglobina está completamente respaldada **excepto por la altitud**, que viene de una tabla sin autor conocido. Es el último eslabón sin cita en la cadena de la demo.
