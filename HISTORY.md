# HISTORY - LabLens

Registro de cambios y catalogo de funciones implementadas. Sirve para que otro
modelo o colaborador sepa que existe antes de escribir codigo nuevo.

Convencion: cada entrada lleva fecha, alcance y las funciones publicas que
quedaron disponibles. Al agregar codigo, sumar una entrada nueva al final y
actualizar el indice de funciones.

---

## 2026-07-25 - v0.1.0 - Captura y enderezado de documentos medicos

Primera version funcional. Prueba local: se abre un servidor en la PC, se entra
desde el celular por IP, la camara muestra un marco guia con la forma del
documento, se detectan las 4 esquinas en vivo y al capturar se devuelve la
imagen enderezada y realzada.

### Estado
- Probado de punta a punta con imagen sintetica: deteccion con error de 1 px,
  proporcion del enderezado 0.7065 vs 0.7071 teorico de A4.
- Latencia de deteccion medida: 3 ms por cuadro (limite real: 110 ms del bucle).
- Servidor HTTPS verificado en `https://127.0.0.1:8443/api/config`.
- Frontend probado en Chrome con una camara falsa (canvas `captureStream` con la
  escena sintetica): marco guia, contorno verde en vivo, captura, pantalla de
  resultado y `Nueva captura`. Sin errores en consola.
- Pendiente: prueba con documentos reales en el celular. Requiere abrir el
  puerto en el Firewall de Windows (regla inbound, necesita administrador).

### Nota para futuras pruebas automatizadas
Para probar el frontend sin camara real, sobrescribir `getUserMedia` con el
stream de un canvas:

```js
const flujo = lienzo.captureStream(15);
navigator.mediaDevices.getUserMedia = async () => flujo;
navigator.mediaDevices.enumerateDevices = async () => ([{kind:'videoinput', deviceId:'falsa', label:'Camara de prueba'}]);
```

Ojo: en una pestana en segundo plano Chrome limita `setTimeout` a ~1/s y detiene
`requestAnimationFrame`, asi que el ritmo de cuadros medido ahi no es real.

### Arbol de archivos

    servidor.py              arranque, IP local, certificado, QR de consola
    requirements.txt         dependencias
    app/
      __init__.py            __version__
      main.py                FastAPI: rutas HTTP y WebSocket
      detector.py            deteccion de las 4 esquinas (OpenCV)
      enderezar.py           correccion de perspectiva y realce
      formatos.py            formatos de documento y su proporcion
      almacenamiento.py      guardado en disco y registro append-only
      certificado.py         certificado TLS autofirmado
      integraciones.py       PUNTO DE EXTENSION para extraer datos
      estaticos/
        index.html           3 pantallas: permisos, camara, resultado
        estilos.css          tema oscuro, responsive
        app.js               camara, marco guia, bucle de deteccion, captura

### Decisiones de diseno
- **Deteccion en el servidor, no en el navegador.** Se descarto OpenCV.js
  (~8 MB por CDN) para mantener Python como unico lenguaje de procesamiento y
  no cargar al celular. El navegador solo envia cuadros reducidos.
- **HTTPS obligatorio.** `getUserMedia` solo funciona en contexto seguro; por
  IP de red local eso exige TLS. De ahi el certificado autofirmado con la IP
  en el campo SAN.
- **La captura nunca se pierde.** Si no hay deteccion se guarda la foto
  completa; si el gancho de integracion falla, el error viaja en la respuesta
  pero la imagen ya quedo en disco.
- **Doble metodo de deteccion.** Canny (contraste medio) y Otsu (papel claro
  sobre fondo oscuro) compiten y gana el de mejor puntaje.

### Funciones implementadas

#### `app/detector.py`
| Funcion | Firma | Que hace |
|---|---|---|
| `ordenar_esquinas` | `(puntos) -> np.ndarray` | Ordena 4 puntos como sup-izq, sup-der, inf-der, inf-izq usando el angulo respecto al centroide. Robusto ante rotaciones grandes. |
| `detectar_documento` | `(bgr) -> dict \| None` | Busca el documento. Devuelve `quad` (normalizado 0..1), `quad_px`, `area`, `puntaje`, `metodo`. `None` si no hay nada confiable. |
| `decodificar_jpeg` | `(bytes) -> np.ndarray \| None` | Bytes JPEG/PNG a imagen BGR. |
| `_regularidad_angulos` | `(quad) -> float` | 1.0 si las esquinas son rectas, 0.0 si pasan la tolerancia de 40 grados. |
| `_candidatos_desde_mascara` | `(mascara, area_cuadro) -> list` | Cuadrilateros convexos de una mascara binaria; cae a `minAreaRect` si `approxPolyDP` no da 4 lados. |
| `_mascara_bordes` | `(gris) -> np.ndarray` | Canny con umbrales por mediana + cierre morfologico que tapa el texto. |
| `_mascara_umbral` | `(gris) -> np.ndarray` | Otsu + gradiente morfologico. |

Constantes ajustables: `AREA_MINIMA` (0.10), `AREA_MAXIMA` (0.985),
`TOLERANCIA_ANGULO` (40.0).

#### `app/enderezar.py`
| Funcion | Firma | Que hace |
|---|---|---|
| `enderezar` | `(bgr, quad, ratio_objetivo=None) -> np.ndarray` | Transformacion de perspectiva. Con `ratio_objetivo` fuerza la proporcion del formato conservando el area medida. |
| `realzar` | `(bgr, modo='color') -> np.ndarray` | `color` (balance de blancos + CLAHE + nitidez, conserva sellos y firmas), `gris`, `bn` (umbral adaptativo). |
| `codificar_jpeg` | `(bgr, calidad=92) -> bytes` | Codifica a JPEG. |
| `_tamano_destino` | `(quad, ratio_objetivo) -> (ancho, alto)` | Tamano del lienzo plano a partir de los lados del cuadrilatero. |
| `_balance_grises` | `(bgr) -> np.ndarray` | Neutraliza el tinte de la iluminacion. |
| `_nitidez` | `(bgr) -> np.ndarray` | Mascara de enfoque. |

Constantes: `LADO_MAXIMO` (2400 px), `MODOS` (`color`, `gris`, `bn`).

#### `app/formatos.py`
| Funcion | Firma | Que hace |
|---|---|---|
| `obtener` | `(clave) -> Formato` | Formato pedido o el por defecto. |
| `listar` | `() -> list[dict]` | Lista serializable para el frontend. |

Formatos: `a4_vertical` (por defecto), `a4_horizontal`, `carta_vertical`,
`carta_horizontal`, `ticket`, `tarjeta`, `libre` (ratio 0 = sin ajuste).

#### `app/almacenamiento.py`
| Funcion | Firma | Que hace |
|---|---|---|
| `asegurar_directorios` | `() -> None` | Crea `capturas/` y `capturas/originales/`. |
| `guardar_captura` | `(jpeg_plano, jpeg_original, ancho, alto, formato, modo, quad) -> Captura` | Escribe ambas imagenes, anota `registro.jsonl` y devuelve la `Captura`. |
| `listar_capturas` | `(limite=30) -> list[dict]` | Ultimas capturas, de la mas reciente a la mas antigua. |

Nombre de archivo: `AAAA-MM-DD_HHMMSS_LABLENS_DOC_<formato>_<hex6>.jpg`.

#### `app/certificado.py`
| Funcion | Firma | Que hace |
|---|---|---|
| `ip_local` | `() -> str` | IP de la maquina en la red local (socket UDP sin enviar trafico). |
| `asegurar_certificado` | `(dir_certs, ips) -> (Path, Path)` | Devuelve cert y llave; regenera si falta una IP en el SAN o si vencio. Vigencia 825 dias. |

#### `app/integraciones.py` - PUNTO DE EXTENSION
| Elemento | Firma | Que hace |
|---|---|---|
| `Captura` | dataclass | `id`, `ruta`, `ruta_original`, `ancho`, `alto`, `formato`, `modo`, `quad`, `creado_en`, `bytes()`, `base64()`, `resumen()`. |
| `procesar_documento` | `(captura) -> dict` | **Gancho a reemplazar.** Se llama despues de cada captura; el dict devuelto viaja en `respuesta.datos` y se muestra en pantalla. Hoy devuelve `{"estado": "sin_integracion", ...}`. |
| `_ejemplo_ocr_local` | `(captura) -> dict` | Ejemplo inactivo: Tesseract en el mismo servidor. |
| `_ejemplo_api_externa` | `(captura) -> dict` | Ejemplo inactivo: POST a una API propia con la imagen en base64. |
| `_ejemplo_modelo_vision` | `(captura) -> dict` | Ejemplo inactivo: extraccion de campos con un modelo de vision de Claude. |

Regla: las credenciales se leen de variables de entorno, nunca se escriben en
el archivo.

#### `app/main.py` - API
| Ruta | Metodo | Que hace |
|---|---|---|
| `/` | GET | Sirve `index.html`. |
| `/api/config` | GET | `version`, `formatos`, `formato_por_defecto`, `modos`. |
| `/ws/deteccion` | WS | Recibe un JPEG binario (480 px de lado mayor) y responde `{"encontrado", "quad", "area", "puntaje", "metodo"}`. El cliente espera la respuesta antes del siguiente cuadro. Un cuadro invalido no cierra la conexion. |
| `/api/capturar` | POST | Multipart: `imagen`, `formato`, `modo`, `ajustar_formato`, `quad` (opcional). Si `quad` viene vacio el servidor redetecta a resolucion completa. Devuelve `captura`, `url_imagen`, `url_original`, `recorte_aplicado`, `origen_esquinas`, `quad`, `datos`. |
| `/api/capturas` | GET | Ultimas capturas del registro (`?limite=`). |
| `/capturas/*` | GET | Archivos guardados (estatico). |
| `/estaticos/*` | GET | Frontend (estatico). |

#### `app/estaticos/app.js`
| Funcion | Que hace |
|---|---|
| `cargarConfig` | Trae `/api/config` y llena el selector de formatos. |
| `activarCamara` | `getUserMedia` con `facingMode: environment` a 1920x1080 ideal. |
| `listarCamaras` | Muestra el selector solo si hay 2 o mas camaras. |
| `ajustarVisor` | Aplica la proporcion real de la camara al visor para que no queden bandas. |
| `rectContenido` | Rectangulo real del video dentro del elemento (`object-fit: contain`). |
| `rectGuia` | Marco guia al 88% con la proporcion del formato elegido. |
| `dibujar` | Bucle de `requestAnimationFrame`; escala por `devicePixelRatio`. |
| `dibujarGuia` | Rectangulo punteado + esquinas marcadas. |
| `dibujarQuad` | Contorno detectado: ambar si falta ajustar, verde si esta alineado. |
| `conectar` | WebSocket con reconexion a 1.2 s. |
| `procesarDeteccion` | Estabilidad, alineacion y cuenta atras de la autocaptura. |
| `evaluarEncuadre` | Mensajes: acerca mas / endereza / se sale del cuadro. |
| `bucleAnalisis` | Envia cuadros con un solo pedido en vuelo a la vez. |
| `capturar` | Foto a resolucion completa, reutiliza el `quad` si tiene menos de 600 ms. |
| `mostrarResultado` | Imagen, metadatos, JSON de la integracion y descarga. |
| `descifrarError` | Traduce `NotAllowedError`, `NotFoundError`, `NotReadableError`. |

Constantes ajustables al inicio del archivo: `ANCHO_ANALISIS` (480),
`INTERVALO_MS` (110), `AREA_MINIMA_ALINEADO` (0.30),
`PUNTAJE_MINIMO_ALINEADO` (0.55), `MARGEN_BORDE` (0.015),
`CUADROS_ESTABLES` (5), `CUADROS_AUTO` (9), `TOLERANCIA_ESTABLE` (0.025),
`VIGENCIA_QUAD_MS` (600).

#### `servidor.py`
| Funcion | Que hace |
|---|---|
| `main` | Argumentos `--puerto` (8443), `--host` (0.0.0.0), `--http`, `--recargar`. Genera el certificado, imprime URLs y arranca uvicorn. |
| `_qr` | QR ASCII en consola para abrir la URL desde el celular. |

### Dependencias instaladas (v0.1.0)
fastapi 0.140.0, uvicorn 0.51.0, starlette 1.3.1, opencv-python-headless
5.0.0.93, numpy 2.5.1, python-multipart 0.0.32, cryptography 49.0.0,
qrcode 8.2. Entorno: `.venv` con Python 3.13.

---

## 2026-07-25 - v0.2.0 - Detector v2: bordes + color + pistas

### Motivo
En la prueba con el movil el detector eligio un objeto cualquiera en lugar del
documento. La causa: la v1 solo puntuaba **forma** (area + esquinas rectas), asi
que cualquier rectangulo grande le ganaba a una hoja A4.

### Investigacion previa
- El paper de localizacion de documentos en movil ([arXiv 2106.09987](https://arxiv.org/abs/2106.09987))
  concluye que hay que **combinar bordes y color**. Era exactamente lo que
  faltaba.
- [Dropbox Engineering](https://dropbox.tech/machine-learning/fast-and-accurate-document-detection-for-scanning)
  puntua cada cuadrilatero sumando la respuesta del detector de bordes a lo
  largo de su perimetro, en vez de confiar en el contorno.
- [OpenCV-Document-Scanner](https://github.com/andrewdcampbell/OpenCV-Document-Scanner)
  aporta dos criterios mejores: **rango angular** (angulo interior mayor menos
  el menor) en lugar de medir cada esquina por separado, y un umbral de area
  bastante mas alto del que teniamos.
- Umbral de saturacion ~50-70 para separar acromatico (papel blanco) de color.

### Restricciones del dominio que ahora se aprovechan
- Los documentos son A4 o A5, que **comparten la misma proporcion** 1:raiz(2).
  Un solo valor de ratio sirve como pista fuerte para ambos tamanos.
- Todos tienen fondo blanco: la senal de color es fiable.

### Cambios
- `app/detector.py` reescrito por completo (v2).
- `app/main.py`: el WebSocket acepta mensajes de configuracion; nuevo endpoint
  `/api/diagnostico`; `/api/capturar` acepta `guia`.
- `app/estaticos/*`: el cliente envia el marco guia y el formato al detector;
  vista de diagnostico con los candidatos y sus puntajes.
- `app/formatos.py`: `a4_vertical` ahora se llama "A4 / A5 vertical (1:1.41)".
- `app/almacenamiento.py`: nuevo `DIR_DIAGNOSTICO`.

### Como puntua el detector v2
Tres generadores independientes proponen cuadrilateros y seis componentes
deciden el ganador. Los pesos estan en `PESOS`:

| Componente | Peso | Que mide |
|---|---|---|
| `perimetro` | 0.30 | Gradiente real bajo los 4 lados. El lado mas debil pesa la mitad del componente, asi un cuadrilatero con un lado inventado no puede ganar. |
| `papel` | 0.28 | Cobertura de la mascara de papel en el interior + contraste contra el exterior + brillo + baja saturacion. |
| `area` | 0.12 | Fraccion del cuadro que ocupa, saturando en 0.60. |
| `angulos` | 0.12 | Rango angular; 0 grados es un rectangulo perfecto. |
| `formato` | 0.10 | Cercania a 1:raiz(2). Solo si el cliente manda `ratio`. |
| `guia` | 0.08 | Cuanto del candidato cae dentro del marco guia. Solo si el cliente manda `guia`. |

Los pesos se renormalizan sobre los componentes presentes, asi que si el cliente
no manda pistas el puntaje sigue siendo comparable.

**Rechazos duros**: `area` fuera de [0.15, 0.97], `rango_angular` > 40 grados,
`cobertura` de papel < 0.65, `papel` < 0.45. El filtro de cobertura es el que
resuelve el problema original: un documento real da cobertura ~1.00, mientras que
un cuadrilatero que mezcla el papel con un objeto vecino ronda 0.4-0.6.

### Funciones de `app/detector.py` (v2)
| Funcion | Firma | Que hace |
|---|---|---|
| `detectar_documento` | `(bgr, guia=None, ratio_objetivo=None, con_candidatos=False) -> dict\|None` | Entrada publica. `guia` es (x,y,ancho,alto) normalizado; `con_candidatos` incluye los descartados con el motivo. |
| `ordenar_esquinas` | `(puntos) -> np.ndarray` | Ordena 4 puntos sup-izq, sup-der, inf-der, inf-izq. Sin cambios respecto a v1. |
| `dibujar_diagnostico` | `(bgr, resultado) -> np.ndarray` | Pinta los candidatos con puntaje y motivo de rechazo. |
| `decodificar_jpeg` | `(bytes) -> np.ndarray\|None` | Bytes a imagen BGR. |
| `_preparar` | `(bgr) -> dict` | Calcula una vez por cuadro: `papel` (mascara S<70 AND Otsu sobre V), `borde_papel`, `canny`, `magnitud` (gradiente Sobel normalizado por el percentil 99), `saturacion`, `valor`. |
| `_fuentes_de_candidatos` | `(mapas) -> list` | Junta los tres generadores y quita duplicados a 1.5% de la diagonal. |
| `_candidatos_de_mascara` | `(mascara, mapas, metodo) -> list` | Contornos externos -> `_aproximar_cuatro`. |
| `_candidatos_de_hough` | `(mapas) -> list` | Enumera 2 lineas horizontales x 2 verticales e intersecta. |
| `_lineas_dominantes` | `(mapas) -> (list, list)` | `HoughLinesP` sobre canny OR borde_papel, separadas por angulo y fusionando duplicadas. Maximo 6 por grupo. |
| `_aproximar_cuatro` | `(contorno) -> np.ndarray\|None` | Envolvente convexa + epsilon creciente de 0.01 a 0.12 hasta obtener 4 vertices; si no, `minAreaRect`. |
| `_evaluar` | `(quad, mapas, metodo, guia, ratio) -> dict` | Aplica rechazos y calcula el puntaje. Siempre devuelve dict con `aceptado` y `rechazo`. |
| `_puntaje_perimetro` | `(mapas, quad) -> float` | 48 muestras por lado a +-2 px; 0.5*media + 0.5*minimo de los 4 lados. |
| `_puntaje_papel` | `(mapas, quad, interior) -> dict` | Rejilla interior de 22x22 via homografia (sin rasterizar) + anillo exterior desplazado 2.5% de la diagonal. |
| `_puntaje_formato` | `(quad, ratio) -> float\|None` | `1 - abs(log(medido/objetivo))/log(1.7)`, simetrico. |
| `_puntaje_guia` | `(mapas, quad, interior, guia) -> float\|None` | 0.75 contencion + 0.25 cercania de centroides. |
| `_rango_angular` | `(quad) -> float` | Angulo interior mayor menos el menor, en grados. |
| `_homografia_unidad` | `(quad) -> np.ndarray` | Cuadrado unidad -> cuadrilatero, para muestrear el interior sin mascaras. |

### Protocolo del WebSocket (cambio incompatible con v0.1.0)
- **Texto JSON** = configuracion: `{"guia": [x,y,ancho,alto], "ratio": 0.7071, "candidatos": false}`.
  El servidor responde `{"tipo": "config", "ok": true, ...}`. El cliente debe
  ignorar esa respuesta y **no** contarla como el cuadro en vuelo.
- **Binario** = un JPEG. Responde `{"encontrado", "quad", "area", "puntaje", "metodo", "componentes"}`,
  mas `candidatos` y `papel_detalle` si el diagnostico esta activo.

### Vista de diagnostico
Casilla **Diagnostico** en la camara:
- dibuja los candidatos descartados en gris punteado con su puntaje y motivo,
- muestra un panel con los componentes del ganador y el detalle de `papel`,
- boton **Guardar cuadro para diagnostico** -> `POST /api/diagnostico`, que
  escribe en `capturas/diagnostico/` tres archivos: `_original.jpg`,
  `_candidatos.jpg` (con los candidatos pintados) y `_informe.json`.
  El panel se congela 12 s para poder leer el informe.

Es la herramienta para afinar el detector con documentos reales: si algo no se
reconoce, se guarda el cuadro y el informe dice que candidatos habia y por que
se rechazaron.

### Pruebas realizadas
Cinco escenas sinteticas analizadas a 480 px, con marco guia y ratio A4 activos:

| Caso | Resultado | Puntaje | Mejor rival | Error esquinas |
|---|---|---|---|---|
| Documento + caja azul MAS GRANDE al lado | acierta el documento | 0.894 | 0.700 | 1.7 px (0.3%) |
| Documento sobre fondo tipo madera | acierta | 0.802 | - | 2.1 px (0.3%) |
| Documento sobre escritorio claro (poco contraste) | acierta | 0.677 | - | 2.7 px (0.4%) |
| Documento con iluminacion desigual (mitad en sombra) | acierta | 0.874 | 0.836 | 1.7 px (0.3%) |
| Solo la caja azul, sin documento | **no detecta nada** (rechazo `no_es_papel`) | - | 0.64 | - |

Cobertura de papel del ganador: 1.00 en los cuatro casos con documento.
Latencia: 8-11 ms por cuadro en local, 16-20 ms extremo a extremo por WebSocket.
Frontend verificado en Chrome con camara falsa: envio de configuracion, panel de
diagnostico y guardado del informe.

### Pendiente
Prueba con documentos medicos reales desde el movil.

### Dependencias
Sin cambios respecto a v0.1.0.

---

## 2026-07-25 - v0.3.0 - Extraccion de datos y base Qhali

### Que se agrego
1. El motor de extraccion del prototipo de Colab, traido al servidor.
2. Limpieza de imagen orientada a OCR.
3. Normalizacion del texto libre del modelo a tipos consultables.
4. La base de datos SQLite de `qhali-estructura-base-datos.md`, con el camino
   scanner -> Gemma conectado.

### Cambios al codigo del prototipo
| Prototipo (Colab) | Aqui | Por que |
|---|---|---|
| `userdata.get('NVIDIA-API')` | `os.environ['LABLENS_NVIDIA_API_KEY']` | `google.colab` no existe fuera del notebook, y los secretos no van en archivos. |
| `display(pd.DataFrame(...))` | tabla HTML en el frontend | `display` es de notebook. Se elimino la dependencia de pandas. |
| `cv2.imread(image_path)` | la imagen llega en memoria | El documento ya viene enderezado por LabLens; no hay que releerlo de disco. |
| `max_dim = 800` | 1600, configurable | 800 px en un A4 con texto denso pierde digitos. Al venir recortado y enderezado, el mismo numero de pixeles rinde mucho mas. Se ajusta con `LABLENS_OCR_LADO_MAXIMO`. |
| bucle de 3 intentos con `sleep(3)` | igual, pero sin reintentar los 4xx | Un 400 o 404 (por ejemplo, id de modelo equivocado) no se arregla reintentando. El 429 si se reintenta. |
| llamada sincrona | hilo de fondo + consulta de estado | Con reintentos la llamada puede tardar minutos; el telefono no puede quedarse esperando. |
| `limpiar_json_respuesta` | igual | Ya estaba bien: quita el markdown, recorta al bloque de llaves y limpia caracteres de control. |

### Modulos nuevos
| Archivo | Responsabilidad |
|---|---|
| `app/extraccion.py` | Llamada al NIM, reintentos, limpieza del JSON. |
| `app/esquema.py` | Parseo de valores y rangos; recalculo de fuera de rango. |
| `app/basedatos.py` | DDL de la base Qhali, conexiones, estado. |
| `app/repositorio.py` | Escritura en SQLite + JSON de auditoria. Usuario local. Biomarcadores. |
| `app/analisis.py` | Cola en segundo plano y estado del analisis. |

### Limpieza de imagen para OCR
`enderezar.aplanar_iluminacion` hace correccion de campo plano: estima la
iluminacion con un desenfoque muy grande y divide la imagen por esa estimacion.
Elimina sombras suaves y vinetas, que es lo que mas confunde al OCR. Solo toca el
canal L, asi que sellos y firmas de color se conservan.

`enderezar.preparar_para_ocr` aplana y reduce. **No** vuelve a aplicar nitidez:
`realzar` ya lo hizo, y hacerlo dos veces genera halos alrededor de las letras y
empeora la lectura.

### Normalizacion (`app/esquema.py`)
El modelo devuelve texto libre: `"12,5"`, `"< 0.01"`, `"3.5 - 5.5"`,
`"Hasta 200"`. Sin separar eso en columnas no se puede consultar por valor.

| Funcion | Que resuelve |
|---|---|
| `parsear_valor` | `"12,5"`->(12.5,None), `"< 0.01"`->(0.01,'<'), `"Negativo"`->(None,None) |
| `parsear_rango` | `"3.5 - 5.5"`->(3.5,5.5), `"Hasta 200"`->(None,200), `"Mayor a 40"`->(40,None) |
| `evaluar_fuera_de_rango` | Recalcula el estado. Devuelve None cuando no se puede afirmar. |
| `clave_biomarcador` | Slug sin acentos para agrupar el mismo biomarcador entre informes. |
| `_a_float` | Numero europeo o ingles: **el ultimo separador es el decimal**. |

**`fuera_de_rango` se recalcula y no se confia en el modelo.** Lo que dijo el
modelo se guarda aparte en `fuera_de_rango_modelo` para poder medir su acierto.
En las pruebas el modelo simulado marco "Glucosa 126, rango 70-110" como dentro
de rango; el recalculo la corrige.

Dos bugs encontrados por las pruebas y corregidos:
- `"1.234,5"` (formato europeo) daba 1.2345. La regla vieja asumia que la coma
  siempre era de miles. Ahora decide por cual separador va ultimo.
- `evaluar_fuera_de_rango(0.01, '<', 3.5, 5.5)` devolvia None en vez de True.
  Revisaba el techo antes del piso; con un comparador hay que revisar primero el
  limite que puede dar respuesta definitiva.

### Base de datos Qhali
`app/basedatos.py` transcribe el DDL de `qhali-estructura-base-datos.md` sin
cambios: **14 tablas en un solo archivo SQLite** (`datos/qhali.sqlite3`), tres
dominios logicos. `PRAGMA foreign_keys = ON` en cada conexion, porque SQLite las
desactiva por defecto y no se recuerda en el archivo. `journal_mode = WAL` para
que leer no bloquee escribir.

**Lo que se llena hoy** (camino scanner -> Gemma):

    usuario -> documento -> estudio -> valor_extraido >- biomarcador

**Lo que queda vacio a proposito**: `fuente_referencia`, `rango_referencia`,
`establecimiento_salud`, `peso_ponderacion`, `factor_severidad`,
`umbral_desviacion`, `parametro_calculo`, `ingesta_lote`, `registro_rechazado`.

### Mapeo scanner + Gemma -> tablas
| Origen | Destino |
|---|---|
| `captura.id` | `documento.id` |
| ruta del JPEG enderezado | `documento.archivo_ruta` |
| (fijo) | `documento.tipo='laboratorio'`, `fuente_obtencion='foto'` |
| `informacion_general.centro_medico` | `documento.institucion_nombre` |
| `informacion_general.ubicacion` | `documento.distrito` + `distrito_confianza='extraido'` |
| un estudio por documento | `estudio.categoria='sin_clasificar'` |
| cada `resultados[]` | una fila de `valor_extraido` |
| `resultados[].biomarcador` | se resuelve o se crea en `biomarcador` |

### Decisiones que conviene revisar con Jhair
1. **`biomarcador` se puebla sobre la marcha.** Es Dominio 3, pero
   `valor_extraido.biomarcador_id` es NOT NULL: sin fila de biomarcador no entra
   ningun valor. Los que crea el scanner llevan
   `sistema_corporal = 'sin_clasificar'` para distinguirlos de los curados.
   Se encuentran con:
   `SELECT * FROM biomarcador WHERE sistema_corporal = 'sin_clasificar';`
2. **El rango impreso en el documento no tiene columna.** `valor_extraido` no
   tiene donde guardarlo; el diseno prevé comparar contra `rango_referencia`
   (OMS). Mientras tanto se conserva solo en el JSON de auditoria. Hace falta
   decidir: agregar `rango_crudo_texto` a `valor_extraido`, o descartarlo.
3. **`confianza_extraccion` queda NULL.** El servicio no devuelve confianza por
   valor. Inventar un numero en un dato de salud seria peor que dejarlo vacio.
4. **`institucion_id` queda NULL.** El match difuso necesita
   `establecimiento_salud` (Dominio 2, pendiente). Se respeta la regla del
   diseno: nunca se descarta un documento por falta de match, y el nombre crudo
   siempre se guarda.
5. **`estudio.categoria` = 'sin_clasificar'.** El prompt no pide la categoria.
   Agrupar en estudios reales (hematologia, lipidos) requiere pedirsela al modelo.
6. **El prompt no extrae paciente ni fecha del documento.** Se mantuvo el
   contrato exacto del prototipo. Las columnas `paciente` y `fecha_documento` ya
   existen como nulables, asi que sumarlos no necesita migracion.

### Usuario local
`documento.usuario_id` es NOT NULL, asi que hace falta un usuario antes de poder
guardar. Se registra desde la pantalla de inicio o con `POST /api/usuario`, y
solo pide fecha de nacimiento y sexo (los rangos de la OMS dependen de edad y
sexo) mas el distrito opcional. **Cero PII: no hay columna de nombre.**

Si no hay usuario configurado, la extraccion se hace igual y queda en el JSON de
auditoria con `motivo: "sin_usuario_local"`; se puede reprocesar despues sin
volver a llamar al modelo (`analisis.guardar_informe_existente`).

El JSON se escribe **antes** que la base a proposito: si el INSERT falla, el
trabajo del modelo no se pierde.

### Endpoints nuevos
| Ruta | Metodo | Que hace |
|---|---|---|
| `/api/capturas/{id}/datos` | GET | Estado o resultado del analisis. El frontend consulta cada 1.5 s. 404 si no hay analisis. |
| `/api/usuario` | GET / POST | Lee o registra el usuario local. |
| `/api/basedatos` | GET | Tablas creadas y conteo de filas, separando activas de pendientes. |
| `/api/informes` | GET | Documentos registrados en la base. |
| `/api/documentos/{id}/valores` | GET | Valores extraidos, con JOIN a `biomarcador`. |

`/api/config` ahora informa `extraccion.activa`, `extraccion.modelo`,
`usuario_configurado` y `sexos`.

### Variables de entorno
| Variable | Por defecto | Para que |
|---|---|---|
| `LABLENS_NVIDIA_API_KEY` | - | Clave del NIM. Sin ella no se intenta extraer. Tambien se acepta `NVIDIA_API_KEY`. |
| `LABLENS_MODELO_VISION` | `google/gemma-4-31b-it` | Id del modelo. |
| `LABLENS_NIM_URL` | `https://integrate.api.nvidia.com/v1/chat/completions` | Endpoint. |
| `LABLENS_OCR_LADO_MAXIMO` | `1600` | Lado mayor en px que se envia. |
| `LABLENS_TIEMPO_LIMITE` | `60` | Segundos por intento. |

### Pruebas realizadas
- **Normalizacion**: 41 casos (valores, rangos, fuera de rango, claves) mas un
  informe completo. Encontro los dos bugs listados arriba.
- **Base de datos**: creacion idempotente, 14 tablas, claves ajenas activas,
  rechazo sin usuario local, insercion, reproceso sin duplicar, reuso de
  biomarcadores, dominios pendientes en cero.
- **Endpoints**: config, usuario (incluido el rechazo de sexo invalido), estado
  de la base, captura sin clave, 404 sin analisis.
- **Flujo completo con NIM simulado** (servidor local que responde como NVIDIA,
  envolviendo el JSON en markdown para probar la limpieza): captura -> deteccion
  -> enderezado -> extraccion -> normalizacion -> SQLite. Verificado que llegan
  el modelo correcto, el header de autorizacion y una imagen de ~40 KB; que el
  documento, el estudio y los 5 valores quedan en la base; que la segunda
  captura reusa los biomarcadores y el historico se acumula.

### Sin probar todavia
La llamada al servicio real de NVIDIA. Falta definir
`LABLENS_NVIDIA_API_KEY`. Ojo con el id `google/gemma-4-31b-it`: si no existe en
el catalogo del NIM, la respuesta sera un 4xx y el error aparecera completo en
pantalla; se corrige con `LABLENS_MODELO_VISION` sin tocar codigo.

### Dependencias
Se agrego `requests>=2.32` (instalado: 2.34.2). Se descarto `pandas`, que en el
prototipo solo servia para `display`.
