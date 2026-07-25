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
La base **no guarda nombres**: solo la fecha de nacimiento y el sexo, porque los
rangos de referencia de la OMS dependen de la edad y del sexo, mas el distrito
opcional.

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

Una sola SQLite local en `datos/qhali.sqlite3`, con el esquema de
[qhali-estructura-base-datos.md](qhali-estructura-base-datos.md): 14 tablas en
tres dominios logicos. Se crea sola al arrancar el servidor.

**Lo que se llena hoy:**

```
usuario -> documento -> estudio -> valor_extraido >- biomarcador
```

**Lo que queda vacio a proposito** (pendiente de cargar): los rangos de
referencia de la OMS/MINSA, el padron de establecimientos de RENIPRESS, los pesos
de ponderacion y los umbrales de desviacion.

Ver el estado en `GET /api/basedatos`.

### Puntos a revisar del mapeo

| Tema | Situacion |
|---|---|
| `biomarcador` | Se crea sobre la marcha porque `valor_extraido.biomarcador_id` es NOT NULL. Los del scanner quedan con `sistema_corporal = 'sin_clasificar'` para poder curarlos despues. |
| Rango impreso en el papel | `valor_extraido` no tiene columna para el. Se conserva solo en el JSON de auditoria. Hay que decidir si se agrega. |
| `confianza_extraccion` | Queda NULL: el servicio no devuelve confianza por valor. |
| `institucion_id` | Queda NULL hasta que exista `establecimiento_salud`. El nombre crudo siempre se guarda. |
| `estudio.categoria` | `'sin_clasificar'`: el prompt no pide la categoria del estudio. |
| Paciente y fecha | El prompt no los extrae todavia. Las columnas ya existen como nulables. |

```sql
-- Los biomarcadores que faltan curar
SELECT * FROM biomarcador WHERE sistema_corporal = 'sin_clasificar';

-- Seguimiento de un biomarcador en el tiempo
SELECT d.fecha_carga, v.valor_numerico, v.unidad
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
| `GET /api/capturas?limite=30` | Ultimas capturas registradas. |
| `GET /capturas/<archivo>` | Documento enderezado. |
| `GET /capturas/originales/<archivo>` | Foto original. |
| `POST /api/capturar` | Procesar una imagen ya existente (multipart). |

Tambien sirve leer `capturas/registro.jsonl` directamente, o vigilar la carpeta
`capturas/` con un proceso aparte.
