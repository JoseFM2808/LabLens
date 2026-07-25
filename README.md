# LabLens

Escaner de documentos medicos: se captura la foto desde el celular, el servidor
detecta los bordes del documento y devuelve la imagen enderezada y plana, como
el modo "documento" de la camara del telefono.

El historial de cambios y el catalogo completo de funciones esta en
[HISTORY.md](HISTORY.md).

## Instalacion

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Arranque

```powershell
.\.venv\Scripts\python.exe servidor.py
```

La consola imprime la URL para la PC, la URL para el celular y un QR.

Opciones:

| Opcion | Para que |
|---|---|
| `--puerto 9000` | Cambia el puerto (por defecto 8443). |
| `--http` | Sin TLS. **La camara solo funciona en localhost.** |
| `--recargar` | Recarga el servidor al editar codigo. |

## Conectarse desde el celular

1. El celular y la PC deben estar en la misma red WiFi.
2. Abrir la URL `https://<IP>:8443/` que imprime la consola (o escanear el QR).
3. El certificado es autofirmado: aparece un aviso de seguridad.
   Elegir **Configuracion avanzada** y luego **Continuar al sitio**.
4. Pulsar **Activar camara** y aceptar el permiso del navegador.

### Si el celular no carga la pagina

El Firewall de Windows bloquea el puerto entrante por defecto. En PowerShell
**como administrador**, una sola vez:

```powershell
New-NetFirewallRule -DisplayName "LabLens 8443" -Direction Inbound `
  -Action Allow -Protocol TCP -LocalPort 8443 -Profile Any
```

Al terminar la prueba conviene quitarla:

```powershell
Remove-NetFirewallRule -DisplayName "LabLens 8443"
```

Nota: si `Get-NetConnectionProfile` marca la red como **Public**, la regla debe
usar `-Profile Any` (o `Public`), porque con `Private` no aplica. En una red
publica el puerto queda visible para los demas equipos de esa red mientras el
servidor este encendido.

### Si el navegador no entrega la camara

Ocurre si la pagina no esta en contexto seguro. Alternativa sin TLS en Chrome
Android: abrir `chrome://flags/#unsafely-treat-insecure-origin-as-secure`,
agregar `http://<IP>:8000`, reiniciar el navegador y arrancar con
`servidor.py --http --puerto 8000`.

## Como usarlo

1. Elegir el **formato** del documento: el marco punteado toma esa forma.
   A4 y A5 comparten proporcion, asi que el mismo formato sirve para los dos.
2. Encuadrar el documento **llenando** el marco, sobre un fondo contrastado.
3. El contorno detectado se dibuja en vivo: **ambar** = falta ajustar,
   **verde** = alineado.
4. Pulsar **Capturar**, o activar **Captura automatica al alinear**.

El detector combina tres senales: los bordes de la imagen, el color (busca papel
blanco: claro y sin saturacion) y las pistas que manda la camara (el marco guia y
la proporcion del formato). Un objeto rectangular que no sea papel se descarta
aunque sea mas grande que el documento.

### Si no reconoce el documento

Activar la casilla **Diagnostico** en la camara. Muestra:

- los candidatos descartados en gris, con su puntaje y el motivo del rechazo;
- un panel con los componentes del puntaje del ganador.

El boton **Guardar cuadro para diagnostico** escribe tres archivos en
`capturas/diagnostico/`: la foto original, la foto con los candidatos pintados y
un JSON con el detalle de cada candidato. Sirve para afinar el detector con
documentos reales.

Motivos de rechazo posibles:

| Motivo | Que significa |
|---|---|
| `area` | El documento ocupa menos del 15% del cuadro (muy lejos) o mas del 97% (se sale). |
| `angulos` | El cuadrilatero esta muy deformado: mas de 40 grados entre la esquina mas abierta y la mas cerrada. |
| `no_es_papel` | Menos del 65% del interior parece papel blanco. Es el filtro que evita confundir el documento con otro objeto. |
| `papel_debil` | Parece papel pero con poco contraste contra el fondo. Cambiar a una superficie mas oscura. |

Modos de realce:

- **Color**: conserva sellos, firmas y anotaciones en lapicero. Por defecto.
- **Grises**: mas contraste, archivo mas liviano.
- **Blanco y negro**: umbral adaptativo, ideal para texto impreso.

## Donde quedan las capturas

```
capturas/
  2026-07-25_183042_LABLENS_DOC_a4vertical_a1b2c3.jpg   documento enderezado
  originales/<mismo nombre>.jpg                          foto sin procesar
  registro.jsonl                                         una linea JSON por captura
```

## Extraccion de datos

Despues de cada captura, LabLens manda el documento plano a un modelo de vision y
guarda los biomarcadores en la base de datos Qhali.

### Activarla

```powershell
$env:LABLENS_NVIDIA_API_KEY = "tu-clave-del-NIM"
.\.venv\Scripts\python.exe servidor.py
```

Sin la clave la app funciona igual: guarda las capturas y avisa que la extraccion
esta desactivada. La clave **nunca** se escribe en un archivo del repositorio.

| Variable | Por defecto | Para que |
|---|---|---|
| `LABLENS_NVIDIA_API_KEY` | - | Clave del NIM (tambien vale `NVIDIA_API_KEY`). |
| `LABLENS_MODELO_VISION` | `google/gemma-4-31b-it` | Id del modelo. |
| `LABLENS_NIM_URL` | endpoint de integrate.api.nvidia.com | Servicio a usar. |
| `LABLENS_OCR_LADO_MAXIMO` | `1600` | Lado mayor en px que se envia. |
| `LABLENS_TIEMPO_LIMITE` | `60` | Segundos por intento (3 intentos). |

### Usuario local

Antes de la primera captura hay que registrar el usuario en la pantalla de inicio.
La base **no guarda nombres**: solo la fecha de nacimiento, el sexo, la condicion
(no gestante / gestante por trimestre / puerpera) y el distrito donde vive. Los
cuatro datos entran en el calculo: los rangos de la NTS 213 se estratifican por
edad, sexo y condicion, y la altitud del distrito ajusta la hemoglobina.

Sin usuario registrado la extraccion se hace igual, pero queda solo en el JSON de
auditoria y no entra a la base.

### Que pasa con cada captura

1. Se endereza y realza el documento (esto ya existia).
2. Se aplana la iluminacion para el OCR: se estima la luz con un desenfoque muy
   grande y se divide la imagen por esa estimacion, lo que borra sombras y
   vinetas. Solo se toca la luminancia, asi que los sellos de color se conservan.
3. Se envia al modelo y se pide JSON. Hasta 3 intentos; un 4xx no se reintenta.
4. Se normaliza el texto libre: `"12,5"` -> 12.5, `"< 0.01"` -> 0.01 con
   comparador `<`, `"Hasta 200"` -> techo 200.
5. **Se recalcula si el valor esta fuera de rango**, sin confiar en lo que dijo
   el modelo. Lo que dijo el modelo se guarda aparte para poder medir su acierto.
6. Se escribe el JSON de auditoria y despues la base de datos.

El paso 3 tarda entre 5 y 30 segundos, asi que corre en segundo plano: la captura
responde al instante y la pantalla de resultado se actualiza sola.

## Base de datos

Una sola SQLite local en `datos/qhali.sqlite3`, 19 tablas y una vista en tres
dominios logicos. Se crea sola al arrancar el servidor.

El esquema arranca en el de
[qhali-estructura-base-datos.md](qhali-estructura-base-datos.md) (v0.1) y se
**amplia** con el de la base validada por el equipo,
[BasedeDatos_Preparada/schema.sql](BasedeDatos_Preparada/schema.sql) (v1.0):
tablas nuevas (`distrito`, `alias_distrito`, `ajuste_altitud`, `umbral_alerta`,
`codigo_cie10`), columnas nuevas en las que ya existian y la vista
`v_evaluacion`. La ampliacion es aditiva: las columnas de la v0.1 siguen ahi como
compatibilidad. El detalle y el por que estan en `app/basedatos.py`.

**Lo que se llena con cada captura:**

```
usuario -> documento -> estudio -> valor_extraido >- biomarcador
```

### Cargar los datos de referencia

Los datos validados por el equipo (rangos MINSA, padron RENIPRESS, altitudes,
ajuste por altitud) se cargan desde `BasedeDatos_Preparada/qhali.db`:

```powershell
.\.venv\Scripts\python.exe herramientas\cargar_referencia.py
```

Respalda la base en `datos/respaldos/` antes de tocar nada, es idempotente y al
final verifica que no queden claves ajenas huerfanas. Lo que carga:

| Tabla | Filas | Fuente |
|---|---:|---|
| `distrito` | 1 895 | tabla de altitudes (21 sin altitud, declarados) |
| `establecimiento_salud` | 26 798 | RENIPRESS |
| `alias_distrito` | 27 | grafias de RENIPRESS resueltas en el ETL |
| `biomarcador` | 45 curados | paneles + NTS 213 |
| `rango_referencia` | 111 | NTS 213 (65) + paneles sin cita (46) |
| `umbral_alerta` | 14 | alerta sin invalidar el rango normal |
| `ajuste_altitud` | 11 | NTS 213 Tabla N.1 |
| `codigo_cie10` | 6 | NTS 213 Tabla N.23 |

**Sigue vacio a proposito:** `peso_ponderacion` (sin cita, ningun peso entra) y
`umbral_desviacion` (tabla de la v0.1 que la v1.0 reemplaza por `umbral_alerta`).

Ver el estado en `GET /api/basedatos`, que separa `activas` (dominio del usuario),
`referencia` y `pendientes`.

### Usuario de relleno para probar

```powershell
.\.venv\Scripts\python.exe herramientas\sembrar_usuario_demo.py
.\.venv\Scripts\python.exe herramientas\sembrar_usuario_demo.py --borrar
```

Crea `usuario-relleno`: mujer de 32 anios, no gestante, residente en Chaupimarca
(Cerro de Pasco, 4 373 msnm), con tres documentos y 49 valores. Sirve para ver el
ajuste por altitud sin tener que escanear nada:

```
Hemoglobina 13.8 g/dl  ->  13.8 - 2.9 = 10.9  ->  anemia MODERADA (NTS 213)
```

Los datos son inventados y se distinguen: el usuario es `usuario-relleno` y los
documentos empiezan con `relleno-`.

### El ajuste por altitud

El factor se toma de la **residencia declarada del usuario**, no del lugar donde
se hizo el analisis (NTS 213 §5.3.2), y se **resta** al valor observado (Tabla
N.1, columna "Disminuir"). Solo aplica sobre 500 msnm. `valor_numerico` nunca se
sobrescribe: el ajuste se guarda al lado en `valor_ajustado` y `ajuste_id`.

Sin distrito, sin altitud o bajo 500 msnm no hay ajuste y la interfaz lo declara.
Por eso la pantalla de usuario pide el distrito de una lista del padron: hay
cuatro Bellavista y solo una esta a 13 msnm (`GET /api/distritos?q=bellav`).

### Puntos a revisar del mapeo

| Tema | Situacion |
|---|---|
| `biomarcador` | Se resuelve contra el catalogo curado por nombre **y unidad**. Lo que no calza entra con `matriz = 'sin_clasificar'` para curarlo despues. La unidad se exige a proposito: `Glucosa` de una tira de orina no es la glucosa en sangre. |
| Rango impreso en el papel | `valor_extraido` no tiene columna para el. Se conserva solo en el JSON de auditoria. Hay que decidir si se agrega. |
| `confianza_extraccion` | Queda NULL: el servicio no devuelve confianza por valor. |
| `institucion_id` | Se busca en el padron **dentro del distrito del documento**. El nombre crudo siempre se guarda. Inferir el distrito desde la institucion esta apagado: un nombre exacto repetido en otra region metia el documento en el distrito equivocado. |
| `estudio.categoria` | `'sin_clasificar'`: el prompt no pide la categoria del estudio. |
| Paciente y fecha | El prompt no los extrae todavia. Las columnas ya existen como nulables. |
| `condicion` del usuario | Sin declararla, los rangos de la NTS 213 para mujeres adultas (estratificados en no gestante / gestante / puerpera) no aplican y se cae al panel sin cita. La pantalla de usuario la pide. |

```sql
-- Los biomarcadores que faltan curar
SELECT * FROM biomarcador WHERE matriz = 'sin_clasificar';

-- Evaluacion completa de un usuario, con ajuste y cita normativa
SELECT biomarcador, valor_crudo, factor_ajuste, valor_evaluado,
       clasificacion, estado_ajuste, respaldo
FROM v_evaluacion WHERE usuario_id = 'usuario-local';

-- Seguimiento de un biomarcador en el tiempo
SELECT d.fecha_carga, v.valor_numerico, v.valor_ajustado, v.unidad
FROM valor_extraido v
JOIN estudio e   ON e.id = v.estudio_id
JOIN documento d ON d.id = e.documento_id
JOIN biomarcador b ON b.id = v.biomarcador_id
WHERE b.nombre = 'Hemoglobina'
ORDER BY d.fecha_carga;
```

## Conectar otro extractor de datos

El gancho esta en `app/integraciones.py`, funcion `procesar_documento(captura)`.
Hoy encola el motor propio; para usar otro extractor se reemplaza ese cuerpo.

```python
def procesar_documento(captura: Captura) -> dict:
    # captura.ruta      ruta del JPEG enderezado
    # captura.base64()  la imagen lista para enviar a una API
    # captura.formato   formato elegido en la camara
    return {"estado": "ok", "paciente": "...", "examenes": [...]}
```

Lo que devuelve viaja en la respuesta HTTP bajo `datos` y se muestra en la
pantalla de resultado. Si la funcion falla, la captura **no** se pierde: se
guarda igual y el error aparece en `datos.error`.

El archivo trae tres ejemplos inactivos y listos para copiar: Tesseract local,
POST a una API propia y extraccion de campos con un modelo de vision de Claude.

Las credenciales se leen de variables de entorno. No se escriben en el codigo.

## Consumir las capturas desde otro sistema

| Endpoint | Uso |
|---|---|
| `GET /api/basedatos` | Estado de la base: tablas y filas por dominio. |
| `GET /api/distritos?q=bellav` | Distritos del padron con su altitud. |
| `GET /api/capturas?limite=30` | Ultimas capturas registradas. |
| `GET /capturas/<archivo>` | Documento enderezado. |
| `GET /capturas/originales/<archivo>` | Foto original. |
| `POST /api/capturar` | Procesar una imagen ya existente (multipart). |

Tambien sirve leer `capturas/registro.jsonl` directamente, o vigilar la carpeta
`capturas/` con un proceso aparte.
