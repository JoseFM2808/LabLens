# Qhali — Apuntes y Recomendaciones de Diseño

**Complemento del documento de estructura de base de datos.**
Aquí está el *por qué* de cada decisión, los riesgos identificados y las mitigaciones acordadas.

---

## 1. Por qué una sola base y no tres

- La restricción no negociable del proyecto es **procesamiento local/edge**. Tres bases separadas implican sincronización, múltiples conexiones y más superficie de fallo — sin ganar nada en un entorno local.
- SQLite entrega: un archivo por usuario, cero servidor, funciona offline (clave para poblaciones con conectividad limitada, alineado con ODS 10).
- La separación conceptual se mantiene como **tres dominios lógicos** dentro de la misma base: datos del usuario / referencia externa / configuración.
- **Cifrado (Fase 2):** SQLCipher cifra el archivo completo. La clave se deriva de usuario+contraseña con PBKDF2 o Argon2. Ventaja: la estructura de la hackathon migra sin cambios.

## 2. Privacidad por diseño: cero PII

- No se almacena el nombre del usuario. Solo `fecha_nacimiento` y `sexo` (necesarios para aplicar rangos de referencia) y `distrito_residencia` opcional.
- Esto refuerza la narrativa del pitch: *el sistema no necesita saber quién eres para ayudarte a organizar tu salud*.
- La identidad del documento se ancla en la **institución**, no en la persona: `institucion_nombre` (texto crudo del membrete) + `institucion_id` (match con RENIPRESS) + `distrito`.

## 3. El rol de Gemma: extractor, no oráculo

Regla arquitectónica central: **Gemma nunca responde directamente al usuario con datos médicos.**

```
Gemma extrae → escribe en valor_extraido → la app consulta SQL → la UI muestra la base
```

Beneficios:
- El sistema **no puede alucinar** un valor que no existe en la base — cumple el requisito de que "el modelo solo devuelva información que la base puede obtener" por diseño, no por prompt.
- Auditable: todo lo que se muestra tiene una fila de origen.
- `valor_crudo_texto` (obligatorio) guarda lo que Gemma leyó literalmente. Si la extracción falla, el usuario verifica contra el original. **Esta es la red de seguridad de credibilidad para la demo.**
- `confianza_extraccion` permite marcar en UI los valores de baja confianza para revisión manual.

## 4. Match institución → RENIPRESS

- El membrete dirá "Hosp. Nac. Dos de Mayo"; RENIPRESS lo registra como "HOSPITAL NACIONAL DOS DE MAYO". El match **debe ser difuso**: normalización (mayúsculas, sin tildes) + similitud de cadenas con umbral.
- `institucion_nombre` se guarda **siempre**; `institucion_id` solo cuando el match supera el umbral. Nunca se descarta un documento por falta de match.
- El **distrito** tiene dos rutas: extraído del documento, o inferido por la institución matcheada (RENIPRESS trae el distrito de cada establecimiento). `distrito_confianza` registra cuál se usó — el cálculo de diferenciación entre instituciones depende de la confiabilidad de este dato, y en la demo es honesto poder decir "este dato lo leímos, este lo inferimos".

## 5. Ponderación dinámica: diseño y defensa

### La idea (analogía académica)
Como una nota final con pesos por práctica: cada biomarcador tiene un `peso_base`. Pero si un valor está mal, su peso **se amplifica** porque afecta más al estado actual del usuario.

### Decisiones de diseño
- Todo parametrizado en tablas (`peso_ponderacion`, `factor_severidad`, `umbral_desviacion`, `parametro_calculo`). Nada hardcodeado → el sistema es transparente y ajustable, no una caja negra. Esto es un punto vendible en la demo.
- La renormalización (`/ Σ peso_efectivo`) es obligatoria: sin ella, un usuario con más valores fuera de rango tendría otra escala y la comparación "último scan vs actual" perdería sentido.

### ⚠️ Riesgo crítico: defensa clínica de los pesos
Desde la salida de Josselyn, **nadie en el equipo cubre validación clínica**. Mitigaciones acordadas:

1. **La AI propone, no decide.** Se puede usar la AI para proponer pesos base *con citas*, pero los valores que entran a `peso_ponderacion` quedan fijos y revisados antes de la demo. `fuente_cita` es obligatorio: **sin cita, el peso no entra.** "Lo decidió el modelo" es indefendible ante un jurado; "guía OMS de anemia, aquí la cita" sí lo es.
2. La amplificación por severidad es defendible como principio general ("lo que está mal pesa más en tu seguimiento"), pero los umbrales de leve/moderada/severa también necesitan fuente para los biomarcadores del alcance.
3. **Nomenclatura:** en UI y pitch, el resultado se llama **"índice orientativo de seguimiento"** — nunca "puntaje de salud" ni nada diagnóstico. Disclaimer visible en pantalla, no solo en el pitch.
4. **Alcance reducido = cero afirmaciones indefendibles.** Solo 5–8 biomarcadores con rangos OMS bien documentados: hemoglobina, glucosa, colesterol total, LDL, HDL, triglicéridos, creatinina.

## 6. ETL y versionado de fuentes externas

### Estructura del pipeline (local, automatizable)

```
ingesta/
  ├── extractores/          # uno por fuente
  │   ├── oms.py
  │   ├── minsa.py
  │   ├── renipress.py      # padrón en CSV público
  │   └── susalud.py
  ├── reglas/               # validación y transformación
  └── cargador.py           # escribe a la base con versionado
```

### Reglas ETL mínimas

| Regla | Detalle | Por qué |
|---|---|---|
| Validación de esquema | Columnas esperadas presentes, tipos correctos | RENIPRESS cambia el formato de su CSV entre publicaciones |
| Normalización de unidades | Conversión a `unidad_estandar` **en la carga**, nunca en la consulta | g/dL vs g/L en hemoglobina es un error clásico |
| Normalización de texto | Distritos e instituciones a mayúsculas sin tildes | El match difuso necesita datos limpios en ambos lados |
| Coherencia | `valor_min < valor_max`; edades sin solapamiento por biomarcador/sexo | Rechazar a `registro_rechazado`, nunca cargar silenciosamente |
| Versionado aditivo | Nunca sobrescribir `rango_referencia`; cada lote crea registros nuevos con su `version` | Trazabilidad total: "estos rangos vienen del snapshot OMS del 2026-07-10" |
| Hash de origen | `hash_origen` por lote; si el archivo fuente no cambió, no se recarga | Evita cargas duplicadas en la automatización |

### Sinónimos de biomarcadores
Los laboratorios peruanos escriben el mismo análisis de formas distintas ("Hb", "hemoglobina", "HGB"). El campo `sinonimos` en `biomarcador` normaliza la salida de Gemma hacia un solo `biomarcador_id` — sin esto, el JOIN con rangos de referencia falla en silencio.

## 7. Alcance hackathon vs Fase 2

| Tema | Hackathon (demo 25/07) | Fase 2 |
|---|---|---|
| Cifrado | SQLite sin cifrar | SQLCipher (usuario+contraseña) |
| ETL | Ejecución manual única, con hash y versionado activos | Automatización programada (cron) |
| Anonimización adicional | — | Sí (según tabla de fases) |
| Biomarcadores | 5–8 con rangos OMS documentados | Catálogo ampliado |
| Ponderación | Pesos fijos con cita, amplificación por severidad | Revisión con asesoría clínica |

**Regla del pitch:** lo que es Fase 2 se menciona como roadmap. Vale más una demo estrecha y defendible que una amplia con afirmaciones cuestionables.

## 8. Pendientes abiertos

- [ ] Conseguir revisión clínica (o al menos citas sólidas OMS/MINSA) para pesos base y umbrales de severidad — **riesgo abierto sin responsable desde la salida de Josselyn**
- [ ] Definir umbral de similitud para el match institución → RENIPRESS con datos reales
- [ ] Redactar el disclaimer de pantalla del índice orientativo (Kiara puede alinearlo con el pitch)
- [ ] Pasar muestra de datos reales de cada fuente para construir extractores y carga inicial
