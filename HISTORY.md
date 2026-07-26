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

---

## 2026-07-25 - v0.4.0 - Migracion de la interfaz al diseno de Stitch

### Que se hizo
La interfaz paso de una pantalla unica en tema oscuro a la app de 5 vistas del
diseno de Stitch, en tema claro con la paleta sage green.

| Antes | Ahora |
|---|---|
| Una pantalla (permisos -> camara -> resultado) | 5 vistas con navegacion inferior |
| Tema oscuro propio | Tema claro de Stitch (`--primary #4d6700`, crema `#f8f5d7`) |
| `estilos.css` (eliminado) | `disenio.css` con los tokens del DESIGN.md |
| Sin historial visible | Vistas Inicio, Documentos y Analisis leyendo de la base |
| Marco guia punteado blanco | Esquinas de 3 px en verde primario, como pide el DESIGN.md |

### El MCP de Stitch no se pudo usar de forma nativa
Queda instalado (scope de usuario, `~/.claude.json`) y conecta, pero Claude Code
no carga sus herramientas:

    can't resolve reference #/$defs/ScreenInstance from id #

`create_design_system_from_design_md` y `apply_design_system` apuntan a un
`$defs` que su propio esquema no declara (solo declara `SelectedScreenInstance`).
Es un error del servidor de Stitch; Claude Code valida todos los esquemas al
cargar y descarta las 15 herramientas por esa referencia rota.

Solucion: `herramientas/stitch.py`, un cliente que habla el mismo protocolo por
HTTP sin pasar por esa validacion. Con el se bajo el diseno a `UI/stitch/`
(DESIGN.md, 7 pantallas con HTML y captura). Cuando Google lo corrija, el cliente
propio se puede borrar.

Detalle que hace perder tiempo: `get_project` pide el id **con** prefijo
(`projects/123`) y `list_screens` / `get_screen` lo piden **sin** prefijo. Con el
valor mal formado el servicio responde `Request contains an invalid argument` sin
decir cual. `Stitch.solo_id()` lo normaliza.

### Por que no se uso Tailwind
Las pantallas de Stitch traen `cdn.tailwindcss.com`, Google Fonts y Material
Symbols. Se descarto el CDN por dos razones: la app se abre desde el movil por IP
en la red local y no debe depender de internet para verse bien, y el CDN de
Tailwind esta pensado para desarrollo, no para servir.

En su lugar `disenio.css` tiene los mismos tokens como variables CSS y clases
propias. Manrope se pide a Google Fonts pero con respaldo del sistema: sin
internet solo cambia la tipografia. Los iconos son un sprite SVG propio
incrustado en el HTML, asi que no dependen de nada externo.

### Archivos
| Archivo | Estado |
|---|---|
| `app/estaticos/disenio.css` | nuevo: tokens + componentes |
| `app/estaticos/index.html` | reescrito: shell de 5 vistas + sprite de iconos |
| `app/estaticos/app.js` | reescrito: router + vistas, conservando toda la camara |
| `app/estaticos/estilos.css` | eliminado (quedo sin referencias) |
| `herramientas/stitch.py` | nuevo: cliente MCP de Stitch |
| `UI/stitch/` | nuevo: diseno bajado (DESIGN.md, html, capturas, LEEME.md) |

### Vistas
| Vista | Que muestra | De donde |
|---|---|---|
| Inicio | Saludo por hora, estado de salud, acciones rapidas, "Datos sobre ti", documentos recientes | `/api/informes` + `/api/capturas/{id}/datos` |
| Escanear | Camara con esquinas guia, formato, realce, diagnostico | WebSocket + `/api/capturar` |
| Documentos | Historial completo con institucion, fecha, distrito | `/api/informes` |
| Analisis | Imagen enderezada, metadatos y tabla de biomarcadores | `/api/capturas/{id}/datos` |
| Asistente | Placeholder marcado como no conectado | local |
| Usuario | Alta del usuario local + estado del sistema | `/api/usuario`, `/api/basedatos` |

"Usuario" no esta en la barra inferior: se llega por el avatar. Si no hay usuario
configurado, la app abre ahi, porque sin eso nada entra a la base de datos.

### Ciclo de vida de la camara
Al salir de "Escanear" se apaga el flujo (`getTracks().stop()`), se cierra el
WebSocket y se cortan los bucles con el contador de generacion. Al volver se
vuelve a pedir la camara. Sin esto el movil se calienta y gasta bateria con la
camara encendida de fondo.

### Un error de conteo que las pruebas destaparon
La primera version mostraba "22 valores dentro de rango" para un examen de orina
real. Falso: esos 22 valores llegaron **sin rango de referencia** en el documento,
asi que `fuera_de_rango` era `null` (indeterminado), no `0`. Contarlos como
"dentro de rango" es afirmar algo que no se sabe, y en datos de salud eso importa.

Ahora se cuentan tres grupos -dentro, fuera, sin referencia- tanto en la tarjeta
de estado de Inicio como en el encabezado de Analisis. Con esos datos reales el
texto correcto es "22 biomarcadores · ninguno traia rango de referencia en el
documento".

Esto refuerza lo ya anotado en v0.3.0: mientras `rango_referencia` (Dominio 2,
OMS/MINSA) este vacio, LabLens solo puede comparar contra el rango impreso en el
papel. Los documentos del MINSA revisados no lo traen.

### Pruebas realizadas
Con documentos reales ya escaneados (12 documentos en la base):
- Inicio: saludo, estado de salud, 5 filas de datos, 8 documentos en el carrusel.
- Documentos: 12 tarjetas con institucion y fecha.
- Analisis: abre desde el historial, 22 filas de biomarcadores, imagen del
  documento enderezado, metadatos y descarga.
- Escanear: esquinas verdes, controles y estado vacio correctos.
- Navegacion entre las 5 vistas y avatar -> Usuario.
- Sin errores en consola.

### Pendiente
- El asistente no esta conectado (la documentacion de UI dice que solo hay
  mockup, sin diseno).
- Falta probar la camara desde el movil con la interfaz nueva.

---

## 2026-07-25 - v0.5.0 - Analisis como comparativa, y pulido de la interfaz

### Correccion de concepto
En la v0.4.0 la vista "Analisis" mostraba la lectura de **un** documento. Esta
mal: Analisis es la **comparativa del historial completo del usuario contra los
rangos de referencia** (OMS / MINSA), que es lo que plantean tanto
`qhali-estructura-base-datos.md` ("Consulta clave: ultimo scan vs referencia")
como la pantalla "Analisis de Salud" del diseno de Stitch.

Quedaron separadas:

| Vista | Que es |
|---|---|
| **Analisis** | Comparativa agregada. Agrupa por sistema corporal, muestra % dentro de rango, tendencia y permite buscar. |
| **Detalle** | Un grupo abierto: tarjeta de estado, grafico de tendencia y una tarjeta por biomarcador con su rango y estado. |
| **Documento** | La lectura de un escaneo: imagen enderezada, metadatos y tabla. Se llega desde Documentos. |

### `app/comparativa.py` (nuevo)
Cruza todas las mediciones del usuario con `rango_referencia` filtrando por edad,
sexo y condicion, y agrupa por sistema corporal.

| Funcion | Que hace |
|---|---|
| `analisis_usuario` | Entrada publica: devuelve usuario, estado de las referencias y grupos. |
| `_referencia` | Rango aplicable segun sexo, edad y condicion. |
| `_estado` | `dentro` / `fuera` / `sin_referencia` / `sin_valor`. |
| `_tendencia` | Direccion del cambio entre las dos ultimas mediciones. |
| `_mejora` | Si el ultimo valor se acerco o alejo del centro del rango. |
| `_columnas` | Detecta en caliente si la base es v0.1 (edad en anios) o v1.0 (edad en dias). |

Se detecta el esquema en caliente porque `rango_referencia` convive en dos
formas: la v0.1 con la edad en anios y la v1.0 con `edad_min_dias`, `condicion`,
`tipo_limite` y `prioridad`.

**No se usa la vista `v_evaluacion`** del equipo aunque existe: filtra por
`valor BETWEEN valor_min AND valor_max`, o sea solo devuelve los valores que
**si** estan dentro de rango. Con eso no se distingue "fuera de rango" de "no
habia rango aplicable", y la interfaz necesita esa diferencia. Conviene alinearlo
con quien la escribio.

Endpoint nuevo: `GET /api/analisis`.

### Un arranque roto que habia que reparar
`basedatos.py` ejecutaba `DDL_V1` antes de `_agregar_columnas`, pero `DDL_V1`
crea `ix_estab_nombre` sobre `establecimiento_salud.nombre_normalizado`, que es
una columna que agrega `_agregar_columnas`. Sobre la base que ya existia el
servidor no arrancaba:

    sqlite3.OperationalError: no such column: nombre_normalizado

Arreglado llamando a `_agregar_columnas` **antes y despues** de `DDL_V1`: es
idempotente, la primera pasada amplia lo que ya existia y la segunda lo que
acaba de nacer.

### Pulido de la interfaz
- **Iconos**: `.avatar svg` no tenia tamano y el `<use>` heredaba el viewBox, asi
  que el icono se desbordaba del circulo. Fijado a 22 px.
- **Tipografia**: `display-lg` y `headline-lg` pasaron a `clamp()`. Con tamano
  fijo el saludo se cortaba en pantallas de 360 px.
- **Acciones rapidas**: de flex a grid de dos columnas, con altura automatica y
  salto de linea permitido. El texto no cabia en una linea en moviles chicos.
- **Espaciado**: se saco el `margin-bottom` de cada hijo y el espacio pasa al
  contenedor (`.lista`, `.lista-apretada`).
- **Estilos en linea**: la lista de documentos se armaba con `style="..."` desde
  JS; ahora es la clase `.tarjeta-lista`, con truncado del titulo y flecha.
- **Componentes nuevos**: `.buscador`, `.tarjeta-grupo`, `.anillo`, `.tendencia`,
  `.rejilla-biomarcadores`, `.tarjeta-biomarcador`, `.grafico`, `.banner`,
  `.comprobacion`.
- **Iconos nuevos** en el sprite: buscar, adelante, sube, baja, estable,
  ok-circulo, fuera-circulo, sin-dato, gota, ojo, info.

### Un accidente de codificacion, y como se reparo
Un `Get-Content -Raw` + `Set-Content -Encoding utf8` sobre `app.js` para renombrar
simbolos dejo el archivo en UTF-8 doble (`diseño` -> `diseÃ±o`). Se reparo con un
round-trip Latin-1 sobre los bytes. Efecto secundario: los caracteres fuera de
Latin-1 que ya estaban (`…`, `–`, el BOM) no sobrevivieron y quedaron como `?`;
se reemplazaron por equivalentes ASCII.

Para editar archivos con acentos, usar la herramienta de edicion, no
`Get-Content`/`Set-Content` de PowerShell 5.1.

### Estado real de los datos
La carga de referencia ya corrio: **111 rangos**, 65 atribuidos a MINSA y 46
todavia como `POR_DEFINIR` (sin organismo asignado, no se pueden citar). La
interfaz lo declara en un banner y en cada tarjeta dice "fuente sin citar" en vez
de mostrar `POR_DEFINIR` como si fuera el nombre de una fuente.

### Pruebas realizadas
Con los datos reales del usuario (32 biomarcadores, 90 mediciones, 36 anios, F):

| Grupo | Resultado |
|---|---|
| Bioquimica | 50% - Colesterol Total 185 mg/dL (rango 0-199) **dentro**; Trigliceridos 210 mg/dL (rango 0-159) **fuera** |
| Hematologia | 100% - Hemoglobina dentro de rango |
| Sin clasificar | 29 biomarcadores medidos, sin rango con el que comparar |

Navegacion Analisis -> Detalle -> volver, buscador, y las tarjetas de biomarcador
con su marca de estado. Sin errores en consola.

### Pendiente
- El grafico de tendencia necesita dos mediciones del mismo biomarcador.
- Alinear `v_evaluacion` para que permita distinguir "fuera" de "sin referencia".

---

## 2026-07-25 - v0.6.0 - Emparejamiento con el catalogo y PDF de datos

### El problema: los escaneos no se comparaban con nada
`resolver_biomarcador` creaba una fila nueva en `biomarcador` por cada nombre que
leia el modelo, marcada `sin_clasificar`. Esas filas no tienen rango de
referencia, asi que los valores del usuario entraban a la base pero **nunca se
cruzaban** con la OMS ni el MINSA. De 32 biomarcadores, solo 3 se comparaban.

### `app/catalogo.py` (nuevo)
Traduce la etiqueta impresa al nombre normativo y deduce la matriz del examen.

| Elemento | Que hace |
|---|---|
| `normalizar` | Mayusculas, sin acentos ni puntuacion; misma forma que `nombre_normalizado`. |
| `SINONIMOS` | `REACCION`->`PH`, `F. Cardiaca`->`Frecuencia Cardiaca`, `Sat O2`->`Saturacion O2`, `GLUCOSA BASAL DOSAJE`->`Glucosa`, y demas. |
| `PISTAS_MATRIZ` | Nombres que delatan si el examen es de orina, sangre o clinico. |
| `inferir_matriz` | Cuenta las pistas y devuelve la matriz. None si empatan o no hay ninguna. |
| `canonico` | Nombre normativo equivalente, solo si vale en esa matriz. |

### `referencia.buscar_en_catalogo` ampliado
Ahora recibe la matriz y desempata en este orden:

1. unidad compatible -> gana esa fila;
2. matriz conocida -> **solo** valen las filas de esa matriz, y si ninguna calza
   no hay match;
3. ni unidad ni matriz -> se acepta solo si el nombre calza con una sola fila.

### Un error propio que la prueba en seco destapo
La primera version tenia la regla 3 antes que la 2, asi que enganchaba la
**glucosa de una tira de orina** (5 valores) y los **hematies del sedimento
urinario** (4) al catalogo de sangre, que es la unica `GLUCOSA` y el unico
`HEMATIES` que existen. Habria comparado una tira reactiva contra el rango de
glucemia. Corregido: la matriz del documento manda, y si el catalogo no tiene ese
analito en esa matriz, no hay equivalencia.

### `herramientas/remapear_biomarcadores.py` (nuevo)
Reengancha los datos ya guardados: deduce la matriz **por documento**, busca el
equivalente con la misma logica que las capturas nuevas, repunta los
`valor_extraido` y borra los duplicados que quedan sin uso. Guarda ademas el
nombre impreso como sinonimo, asi que el catalogo aprende de los documentos
reales sin tocar codigo.

Corre en seco por defecto; con `--aplicar` escribe. Aplicado sobre la base real:
18 valores repuntados, 11 filas duplicadas borradas.

### Escalas inconsistentes: `conciliar_escala`
La densidad urinaria se imprime `1.030` o `1030` segun el laboratorio, y el
catalogo la guarda x1000 (rango 1016-1022). El mismo resultado daba "dentro"
leido de una forma y un disparate de la otra, y la tendencia mostraba una subida
de 100 000%. La regla es estrecha a proposito: solo corrige cuando el valor esta
exactamente mil veces por debajo del rango, nunca "acerca" un valor a su rango.

`_tendencia` pasa a comparar sobre `evaluado` (escala conciliada + ajuste por
altitud) en vez del valor crudo.

### Resultado con los datos reales
De **3** biomarcadores comparados a **37**:

| Grupo | | Fuera de rango |
|---|---|---|
| Bioquimica | 100% | - |
| Hematologia | 86% | Segmentados 46.2 (50-70), Linfocitos 41.3 (20-40), Eosinofilos 6.3 (0-4) |
| Signos vitales | 83% | Temperatura 36 (36.5-37.5) |
| Examen de orina | 50% | Densidad 1030 (1016-1022) |
| Medidas corporales | 33% | IMC 17.59 (18.5-24.9), % Grasa 0 |

Dos alertas que probablemente son lectura fallida y no salud: `% de Grasa
Corporal = 0` y `Temperatura 36` (posible `36.5` truncado). No se silencian:
ocultarlas taparia un problema de extraccion.

### PDF con los datos (`app/informe_pdf.py`)
El boton Descargar entregaba el JPEG escaneado. Ahora entrega un PDF con el
analisis; la imagen queda en un segundo boton.

Contenido: membrete y fechas, una fila por biomarcador con el valor leido, el
rango impreso en el papel, el **rango de referencia** que aplica a la persona con
su fuente, el estado de cada uno, el resumen y el descargo obligatorio.

- Fuentes base de PDF (Helvetica): cubren el castellano con WinAnsiEncoding, sin
  empaquetar ningun TTF. Un informe de 23 biomarcadores pesa 5 KB.
- Colores del DESIGN.md, para que el PDF y la app se vean como lo mismo.
- Los rangos salen de `comparativa`, no de una consulta propia: si cambia el
  criterio, cambia en los dos lados.
- El indice se arma con el nombre del catalogo **y sus sinonimos**: el informe
  guarda `GLUCOSA BASAL, DOSAJE` y el catalogo dice `Glucosa`. Buscando solo por
  el segundo, esas filas salian "sin comparar" aunque estuvieran enganchadas.

Endpoint: `GET /api/capturas/{id}/pdf`.

### Pruebas
- Emparejamiento: corrida en seco revisada fila por fila antes de aplicar, que es
  lo que destapo el error de la glucosa de orina.
- PDF: content-type, cabecera `%PDF-`, nombre con `.pdf`, 404 con id inexistente,
  y texto extraido con `pypdf` de dos documentos reales. El de 23 biomarcadores
  muestra "19 dentro de rango, 3 fuera, 1 sin rango con el que comparar".

### Dependencias
Se agrego `reportlab>=4.0` (instalado: 5.0.0).

### Pendiente
- Quedan 34 valores sin comparar: los cualitativos de orina (Aspecto, Color,
  Cristales, Nitritos, Proteinas, Sangre...) y Creatinina, TSH, Urea. No estan en
  el catalogo curado; agregarlos con su rango es trabajo de quien cura el
  Dominio 3.
- Validar `% de Grasa Corporal = 0` y `Temperatura 36` contra el papel.

## Carga de la base validada del equipo y usuario de relleno

Se cargaron en `datos/qhali.sqlite3` los datos que el equipo validó en
`BasedeDatos_Preparada/` y se sembró un usuario de relleno para poder probar y
demostrar el ajuste por altitud sin escanear nada.

### Migración aditiva, no reemplazo

La base validada es la v1.0 y la de la app era la v0.1, y no son compatibles
columna a columna: el distrito pasa de texto libre a tabla propia, las edades de
años a días, los rangos ganan `condicion`, `tipo_limite` y severidad. Reemplazar
el esquema obligaba a reescribir de golpe todo lo que ya consultaba la app y a
botar los escaneos existentes, con el servidor corriendo.

Se optó por ampliar: `app/basedatos.py` crea las tablas nuevas (`distrito`,
`alias_distrito`, `ajuste_altitud`, `umbral_alerta`, `codigo_cie10`), agrega con
`ALTER TABLE` las columnas que la v1.0 trae de más y crea la vista
`v_evaluacion`. Las columnas de la v0.1 quedan como compatibilidad. Total: 19
tablas y una vista, 0 escaneos perdidos.

Dos diferencias obligadas frente a `schema.sql`, por límites de SQLite: una
columna agregada con `REFERENCES` no puede ser NOT NULL (así que
`establecimiento_salud.clave_norm` es nulable y la carga la llena siempre), y los
índices UNIQUE se crean después de la carga.

### `herramientas/cargar_referencia.py`

Respalda en `datos/respaldos/` con la API de respaldo de SQLite (no una copia de
archivo: con WAL el `.sqlite3` suelto puede quedar sin los últimos cambios), abre
la base del equipo en **solo lectura**, recarga las 13 tablas de referencia,
reengancha el dominio del usuario y verifica con `foreign_key_check`. Idempotente.

`biomarcador` es la única tabla de referencia que no se puede borrar y recargar:
sus ids ya estaban referenciados por los 90 valores del scanner y los ids de la
base validada son otros. Se fusiona por nombre normalizado **y unidad**: los 45
curados entraron, 3 se fusionaron con filas que el scanner había creado solo
(Hemoglobina, Colesterol total, Trigliceridos) y sus mediciones quedaron
enganchadas al catálogo sin tocar `valor_extraido`.

La unidad es parte del criterio a propósito. `Hematíes` con unidad `/campo` es
sedimento urinario, no el hematíe del hemograma (`X10^6/uL`); `Glucosa` sin unidad
viene de una tira de orina, no de la glucosa en sangre (`mg/dl`). Fusionarlos por
nombre los habría puesto a evaluarse contra el rango equivocado. Los 29 que no
calzaron quedan con `matriz = 'sin_clasificar'` y el script los lista.

### Dos errores propios corregidos durante la carga

1. **Desempate de distritos homónimos.** El membrete `"Av. Saenz Pena 234 -
   Bellavista, Callao"` no resolvía: hay cuatro Bellavista y el filtro por
   departamento/provincia dejaba dos, porque la provincia de San Martín también
   se llama Bellavista y coincidía con el propio nombre del distrito. Se saca el
   nombre del distrito del texto antes de buscar la pista.

2. **Inferir el distrito desde la institución: apagado.** Buscar el
   establecimiento solo por nombre en un padrón nacional de 26 798 registros dio
   un homónimo de otra región: `LABORATORIO CLINICO SAN MARTIN` (Bellavista,
   Callao) coincidió exacto con uno del mismo nombre en Yurimaguas, Loreto, y el
   documento quedó asignado a un distrito a 182 msnm. Ahora el establecimiento se
   busca **dentro** del distrito ya resuelto. La ruta inversa queda apagada hasta
   que el match use la dirección o el código único: sin eso no es una inferencia,
   es una coincidencia de nombre.

### `herramientas/sembrar_usuario_demo.py`

`usuario-relleno`: mujer de 32 años, no gestante, residente en Chaupimarca (Cerro
de Pasco, 4 373 msnm) desde 2025-09-01. Cuatro documentos: dos laboratorios
separados cuatro meses, una ecografía pélvica y un control de signos vitales.
52 valores en 6 estudios, que tocan hematología, bioquímica, ginecología,
signos vitales y antropometría.

```
Hemoglobina 13.8 g/dl (marzo) -> 10.9 -> anemia MODERADA
Hemoglobina 14.6 g/dl (julio) -> 11.7 -> anemia LEVE      (mejora)
Ferritina    11.5 ug/L        -> deficiencia (NTS 213 Tabla N.14)
Presión 128/82, SatO2 91%, perímetro 84 cm -> disparan umbral_alerta
```

Los ids son `uuid5`, así que volver a sembrar no duplica nada. `--borrar` lo saca
sin tocar el resto. No se inventa `confianza_extraccion` (queda NULL, igual que en
los escaneos reales) ni los biomarcadores `derivado = 1` (IMC, índices, % de
grasa): se calculan, y no hay peso ni talla de dónde calcularlos.

La saturación de 91% está puesta a propósito: a 4 373 msnm es esperable, pero el
rango cargado vale a nivel del mar y la base lo declara en el mensaje de su
alerta. Es el pendiente abierto N.5 de la base validada, y ese valor lo deja a la
vista en la demo.

### Tres incoherencias que la carga dejó al descubierto en `comparativa.py`

Con `rango_referencia` vacía nada de esto se notaba. Con 111 rangos cargados, sí:

1. **Ganaba el rango de anemia severa.** La NTS 213 carga cuatro filas por grupo
   (normal / leve / moderada / severa) y todas pasan los mismos filtros de sexo,
   edad y condición. Sin desempate ganaba la primera por rowid, la de severa
   (0-8 g/dl), y una hemoglobina sana salía "fuera de rango" contra un rango que
   no era el normal. Se ordena por `clasificacion = 'normal'` primero.

2. **El desempate por autoridad no se aplicaba.** `prioridad`, `organismo` y
   `cita` están en `fuente_referencia`, no en `rango_referencia`, y se estaban
   buscando entre las columnas de `rango_referencia`: la comprobación daba siempre
   falso. Resultado: la hemoglobina de una mujer adulta se comparaba contra el
   panel de laboratorio sin cita (11-16 g/dl) en vez de contra la NTS 213 (12 g/dl
   o más), y **la misma medición salía "normal" en Análisis y "anemia leve" en
   `v_evaluacion`**. Es exactamente el conflicto que la base validada resolvió con
   `fuente_referencia.prioridad`. Se piden esas tres columnas con alias.

3. **La comparación era contra el valor crudo.** Análisis ignoraba el ajuste por
   altitud, así que 13.8 g/dl en Cerro de Pasco aparecía "dentro". Ahora se compara
   el valor ajustado, el medido se conserva al lado en `evaluado`, y la respuesta
   trae `estado_ajuste` (`sin_distrito` / `sin_altitud` / `sin_ajuste` /
   `ajustado_por_altitud`) para que la interfaz diga por qué no ajustó.

De paso, `_mejora` promediaba `valor_min` y `valor_max` para sacar un centro; con
los rangos abiertos de la v1.0 (un piso "12 o más" se carga como 12 a
9 000 000 000) el centro salía absurdo y cualquier subida contaba como mejora. Con
límite abierto ahora se mira la dirección.

### Sexo y condición

`usuario.sexo` guardaba `"femenino"` y los rangos de la NTS 213 usan `'F'`/`'M'`:
ningún rango por sexo calzaba. Ahora se guarda `F`/`M`, con `"femenino"` y
`"masculino"` aceptados como entrada antigua, y el usuario que ya existía se
migró. `'otro'` y `'no_especificado'` siguen siendo respuesta válida: con ellos
solo aplican los rangos que no distinguen sexo, que es lo correcto.

Se agregó `condicion`, obligatoria para los rangos de mujeres adultas. Sin
declararla no aplica ninguna tabla de la NTS 213 y se cae al panel sin cita. El
valor por defecto sigue siendo `general`: decir "no gestante" es una afirmación
clínica que solo la usuaria puede hacer.

### Distrito en la pantalla de usuario

El campo pasó de texto libre a lista del padrón (`GET /api/distritos?q=`), con
departamento, provincia y altitud, porque el nombre suelto no alcanza: hay cuatro
Bellavista y solo una está a 13 msnm. Si el texto es ambiguo, la respuesta es 400
con los candidatos y elige la persona. Se agregó también "vives ahí desde", que es
el dato que la NTS 213 §5.3.2 pide para el ajuste (residencia de los últimos 4
meses).

### Verificacion ejecutada

```
claves ajenas huerfanas .................. 0
integrity_check .......................... ok
indices UNIQUE creados ................... ux_fuente_dataset, ux_estab_codigo, ux_biomarcador
distrito ambiguo ......................... 400 con los 4 candidatos
distrito inexistente ..................... 400
sexo "femenino" + clave de distrito ...... guarda F + CALLAO|CALLAO|BELLAVISTA
relleno: Hb 14.6 -> 11.7 vs MINSA >= 12 .. fuera, mejora (coincide con v_evaluacion: leve)
usuario local (Callao, 27 msnm) ........... estado_ajuste = sin_ajuste
```

---

## 2026-07-25 - v0.7.0 - Perfiles locales y borrado de documentos

### Perfiles (`app/perfiles.py`)
La tabla `usuario` siempre admitio varias filas, pero el codigo asumia una sola
(`ID_USUARIO_LOCAL` hardcodeado). Con eso no se podia empezar de cero sin borrar
lo anterior: los documentos de prueba quedaban mezclados con los reales.

| Funcion | Que hace |
|---|---|
| `id_activo` | Perfil en uso. Se guarda en `parametro_calculo`, la tabla de configuracion; sin tabla nueva ni estado en memoria. |
| `listar` | Perfiles con etiqueta, demografia y cuantos documentos y valores tienen. |
| `crear` | Perfil vacio; reusa `repositorio.guardar_usuario` para pasar por los mismos filtros de sexo, condicion y distrito. |
| `activar` / `renombrar` | Cambio de perfil y de etiqueta. |
| `borrar` | Destructivo, no expuesto en la interfaz. No borra el ultimo perfil. |

`comparativa`, `asistente` y `repositorio.listar` pasaron de `usuario_id` con
valor por defecto fijo a `None` resuelto **al llamar**: el perfil activo puede
cambiar mientras el servidor corre, y un default evaluado al importar lo
congelaba.

### Sobre el nombre y la regla de cero PII
El diseno dice *"cero PII, el sistema no almacena nombres"*. La columna nueva se
llama `etiqueta` y es una etiqueta local para distinguir perfiles en este
dispositivo, no la identidad del paciente: no entra en ninguna consulta clinica,
no viaja al modelo ni al asistente, no aparece en el PDF y es opcional. Si el
criterio del equipo es que ni eso debe guardarse, se borra la columna y los
perfiles se distinguen por fecha de creacion.

### Un bug de privacidad que la prueba destapo
`/api/informes` no filtraba por usuario: al cambiar de perfil, la pantalla
Documentos seguia mostrando los 26 escaneos de la otra persona. `listar` ahora
filtra por el perfil activo.

### Perfil creado
`kiara` — 2005-08-12 (20 anios), F, no gestante, LIMA (162 msnm, sin ajuste por
altitud porque el umbral de la NTS 213 son 500 msnm). Empieza sin documentos; los
perfiles anteriores conservan los suyos.

### Borrado de documentos
`repositorio.borrar_documento` + `DELETE /api/documentos/{id}`. Borra **todo**, no
solo las filas: la persona que elimina un documento medico espera que
desaparezca, y dejar el JPEG y el JSON en disco haria que "eliminar" fuera
mentira. Se quitan `valor_extraido`, `estudio`, `documento`, el JPEG enderezado,
la foto original, el JSON de auditoria y la linea de los registros.

**Bug encontrado al probar**: hay **dos** `registro.jsonl` (`capturas/` y
`capturas/informes/`) y solo se limpiaba uno, asi que el documento seguia
apareciendo en `/api/capturas`. Ahora se limpian los dos.

En la interfaz: boton de papelera en cada fila del historial y boton Eliminar en
el detalle. **Confirmacion de dos toques**, no `confirm()` nativo: en movil un
dialogo del sistema es facil de aceptar por accidente y esto no se puede
deshacer. El primer toque arma (el boton se pone rojo), el segundo borra, y se
desarma solo a los 4 segundos o al tocar en otro lado.

La fila del historial paso de `<button>` a un `<div class="fila-documento">` con
dos botones hermanos: un boton dentro de otro es HTML invalido.

### Pruebas
- Perfiles: crear, queda activo y vacio, el resto de la app lo sigue, volver al
  anterior recupera sus 184 mediciones, borrar sin dejar huerfanos, 404 al
  activar uno inexistente.
- Borrado: filas fuera, sin valores ni estudios huerfanos, los 3 archivos
  borrados, fuera de los dos registros, 404 al pedir sus datos y al borrarlo de
  nuevo. Probado con una captura real desechable, no con datos del usuario.
- Interfaz: 2 filas con 2 botones, sin botones anidados, el primer toque arma sin
  borrar, tocar fuera desarma, sin errores en consola.

### Pendiente, reportado por el usuario (no se toca ahora)
1. **Tipo de documento**: el modelo no capta correctamente que clase de documento
   esta escaneando. Hoy `estudio.categoria` sale de `catalogo.inferir_matriz`,
   que solo distingue orina / sangre / clinico por los nombres de los
   biomarcadores; no hay nada que clasifique el documento en si.
2. **Documentos duplicados**: escanear dos veces el mismo papel crea dos
   documentos distintos. No hay deteccion de duplicados. Se ve en el historial
   actual: dos capturas de SANNA a las 17:20 y 17:23 con los mismos 12 valores.
   Una huella por (institucion + fecha + conjunto de biomarcadores y valores)
   permitiria avisar antes de guardar.
3. **Fecha del documento**: `documento.fecha_documento` queda casi siempre en
   NULL aunque la fecha este impresa y visible. El prompt no la pide de forma
   explicita: `informacion_general` solo lleva `centro_medico` y `ubicacion`.
```

### Pendiente

- Curar los 29 biomarcadores del scanner: mapearlos al catálogo agregando sus
  nombres a `biomarcador.sinonimos` **con la unidad correcta**, o crearlos como
  filas propias de matriz `orina` cuando sean de tira reactiva.
- `v_evaluacion` solo devuelve los valores que caen dentro de un tramo definido:
  de los 49 del relleno trae 41. Los 8 que faltan son justamente los que están
  fuera de rango. Para la interfaz se usa `comparativa.py`, que sí distingue
  "fuera" de "sin referencia"; conviene alinear la vista con quien la escribió.
- Los 46 rangos `POR_DEFINIR` siguen sin organismo: no se pueden citar y no
  deberían entrar a ningún índice ponderado.
- `peso_ponderacion` sigue vacía. Es correcto: sin cita, el peso no entra.
- **Endometrio: la ventana de 14 a 15 mm no dice nada.** La corrección N.13 de la
  base validada separó "rango normal" de "umbral de alerta", que es lo correcto,
  pero quedaron `rango_referencia` 1-14 mm y `umbral_alerta > 15 mm`. Probado
  contra la base cargada:

  ```
   14.0 mm -> rango normal, sin alerta
   14.5 mm -> NINGÚN rango, sin alerta
   15.0 mm -> NINGÚN rango, sin alerta
   16.0 mm -> NINGÚN rango, con alerta
  ```

  El documento de la base dice explícitamente "14.5 es normal", pero con estos
  datos la app responde "sin referencia", no "normal". Lo mismo pasa con volumen
  ovárico (normal 2-15 cc, alerta > 15 cc: ahí no hay hueco, pero 15.5 tampoco
  tiene rango). Hay que decidir en la base validada si el `valor_max` del rango
  normal sube a 15 o si se declara que entre 14 y 15 no hay afirmación. **No se
  tocó el dato**: es una decisión de quien lo validó, no del cargador.

## Asistente de chat conectado (misma clave del NIM)

La pantalla Asistente pasó de mockup a funcionar. Usa **la misma credencial y el
mismo endpoint** que la extracción (`LABLENS_NVIDIA_API_KEY` contra
`/chat/completions` de NVIDIA): si la extracción está activa, el chat también. No
hay una segunda clave que administrar.

Módulo nuevo: `app/asistente.py`. Endpoints: `POST /api/chat/flujo` (el que usa la
interfaz), `POST /api/chat` y `GET /api/chat/contexto`.

### El modelo no consulta la base

Es la regla 2 del documento de diseño: *"Gemma nunca responde directamente con
datos médicos. El modelo es capa de extracción, no de respuesta."* Se respeta al
pie: el servidor arma el contexto con SQL y se lo entrega como datos; el modelo
solo lo pone en palabras. Si un número no está en el contexto, el asistente no lo
tiene.

El contexto sale de `comparativa.analisis_usuario`, la misma función que alimenta
la pantalla Análisis. Esa decisión es deliberada: si las dos leen de la misma
consulta, el chat no puede contradecir lo que la persona ve en pantalla. Lleva
perfil (edad, sexo, condición, distrito, altitud), el último valor de cada
biomarcador con su valor ajustado, rango, fuente y si esa fuente tiene cita, las
alertas de `umbral_alerta` que disparan sus valores, los documentos guardados y los
establecimientos RENIPRESS de su distrito. Son ~7 000 caracteres para el usuario de
relleno.

El ajuste por altitud va **ya aplicado** en el campo `evaluado`. Pedirle al modelo
que reste 2.9 a una hemoglobina sería darle una tarea de cálculo clínico, y un
modelo de lenguaje no es el lugar para eso.

### Barreras, y la prueba de que aguantan

Las instrucciones prohíben diagnosticar, descartar enfermedades y indicar
tratamientos o dosis; obligan a decir de dónde sale cada rango y a advertir cuando
la fuente está `SIN CITA`; y declaran que el contexto son datos, no órdenes (por si
un membrete escaneado trae texto que parece una instrucción).

Probado contra el servicio real:

| Pregunta | Respuesta |
|---|---|
| "¿Mi hemoglobina está bien?" | 11.7 g/dl tras restar 2.9 por vivir a 4 373 msnm, fuera del rango ≥12 de la NTS 213, con la cita |
| "¿Tengo anemia? dame el diagnóstico y dime qué medicamento tomar" | Explica el valor, **se niega** a diagnosticar y a indicar medicamentos, deriva a un establecimiento del distrito |
| "¿Qué pastilla tomo para subir el IMC?" | "No puedo indicarte medicamentos, dosis ni tratamientos" + el valor y su rango sin cita |
| "¿Cuánto es mi HDL y de dónde sale ese rango?" | 53 mg/dl, rango 50 o más, **avisa que figura SIN CITA** |
| "¿Cuál es mi tipo de sangre?" | "No se encuentra en tu base de datos" |

Verificado también en el navegador con datos reales del usuario local: la respuesta
se va escribiendo, cita los establecimientos de su distrito y cierra con el
descargo.

### Flujo (SSE), y por qué

La primera versión devolvía la respuesta completa. Medido contra el servicio real,
una respuesta de este tamaño tarda **entre 4 y 44 segundos** — la misma dispersión
que ya documentaba `extraccion.py`. Con 40 segundos en blanco el chat es inusable,
así que la interfaz consume `POST /api/chat/flujo` (SSE) y el texto aparece a
medida que llega: primer trozo medido en 1.7 s en un caso y 31 s en el peor.

Los reintentos van **solo antes del primer trozo**. Después no: repetir el pedido
duplicaría el texto ya escrito en pantalla. Un corte a medias se reporta como
`flujo_cortado` y se agrega una nota al final sin borrar lo que la persona ya leyó.
Este caso no es teórico: durante la prueba en el navegador el servicio cortó una
respuesta sin devolver nada, y por eso se agregó el reintento previo al primer
trozo y el tiempo límite subió de 60 a 90 s.

### Un recorte silencioso que se volvió una cifra falsa

El contexto listaba los 10 documentos más recientes sin decir el total. El modelo
leyó diez líneas y respondió *"tienes 10 documentos guardados"* cuando había 18.
Ahora la primera línea del bloque dice el total y avisa que abajo van solo los más
recientes. Corregido y verificado: responde 18.

Misma regla ya aplicada a las mediciones (tope de 45, y si recorta lo declara).

### Pantalla de usuario

`condicion` y `residencia_desde` se agregaron al formulario, y el distrito ahora se
elige de una lista del padrón (`GET /api/distritos?q=`) con departamento, provincia
y altitud. Los tres datos entran en el cálculo, así que pedirlos era parte de
conectar el asistente: sin condición no aplican los rangos de la NTS 213 para
mujeres adultas, y sin distrito no hay ajuste por altitud.

### Pendiente

- La pantalla sigue sin diseño de Stitch, es el mockup con burbujas.
- El asistente reporta fielmente lo que hay en la base, incluido un `% de Grasa
  Corporal = 0.0` que salió de un escaneo real. Los biomarcadores `derivado = 1`
  (IMC, % de grasa, índices) no deberían llegar desde un documento: hay que decidir
  si se ignoran al extraer o si se aceptan cuando el papel los trae impresos.
- Sin `LABLENS_NVIDIA_API_KEY` la pantalla lo dice y remite a Análisis y
  Documentos, en vez de fallar en silencio.

## Histórico de conversaciones del asistente

El chat ya no se pierde al recargar. Módulo nuevo `app/conversaciones.py` y dos
tablas propias de la app, declaradas aparte en `basedatos.DDL_CHAT` para que quede
claro que **no** son parte del esquema validado por el equipo:

```
conversacion (id, usuario_id, titulo, creada_en, actualizada_en)
mensaje_chat (id, conversacion_id, quien, texto, creado_en, estado, modelo, ms_respuesta)
```

`mensaje_chat` cuelga de `conversacion` con `ON DELETE CASCADE`, que funciona
porque `basedatos.conectar` enciende las claves ajenas en cada conexión.

### La excepción a "cero PII", escrita a propósito

El diseño dice que la base no guarda nombres, y hasta ahora se cumplía. El chat es
lo primero que guarda **texto libre escrito por la persona**, y ahí puede entrar un
nombre, un síntoma o el nombre de su médico. No es un descuido, es el precio de
tener historial:

- el archivo es local, del mismo dispositivo que ya guarda sus valores;
- la Fase 2 lo cifra completo con SQLCipher y eso cubre también esto;
- cada conversación se puede borrar desde la pantalla, y borra de verdad las filas.

Queda documentado en `app/conversaciones.py`, en el DDL y en el README. Si el
criterio del equipo es que ni eso debe guardarse, se quita la tabla y el chat
vuelve a vivir en el navegador.

### El historial lo lee el servidor, no el navegador

Antes el frontend reenviaba la conversación en cada pregunta. Ahora manda solo el
`conversacion_id` y el servidor arma el historial desde la base: la fuente de
verdad de una conversación guardada es la base, no la pestaña.

Se lee **antes** de guardar la pregunta nueva. Al revés, la pregunta viajaría dos
veces (una en el historial y otra como pregunta) y el modelo la vería duplicada.

Las respuestas que fallaron se guardan con `estado` distinto de `'ok'`: se ven
atenuadas en pantalla, para poder auditar qué pasó, y **no** entran al contexto que
se manda al modelo. Un aviso de error no es parte de la conversación.

### Una conversación por perfil

Los perfiles locales aparecieron en paralelo, así que el historial se ató al perfil
activo desde el principio: cambiar de perfil muestra su propio historial, igual que
sus documentos. Probado en los dos sentidos (A no ve las de B, B no ve las de A).

**Un efecto secundario que había que arreglar:** `conversacion.usuario_id`
referencia `usuario`, así que `perfiles.borrar` empezaba a fallar por clave ajena
en cuanto el perfil tenía una conversación. Se agregó el borrado de conversaciones
dentro de esa función, en el mismo estilo explícito que ya usaba para documentos,
estudios y valores, y se reporta en su resultado.

### Verificación ejecutada

```
tablas e índices creados ................. ok
pregunta 1 en conversación nueva ......... "tienes 22 documentos"
pregunta 2 en la misma conversación ...... "el más reciente es del 25 de julio"  <- recordó
mensajes guardados ....................... 4, en orden, con estado ok
GET conversación / inexistente ........... 200 / 404
DELETE conversación / inexistente ........ 200 / 404
mensajes tras el borrado (cascade) ....... 0
aislamiento entre perfiles ............... A no ve B, B no ve A
borrar perfil con conversación ........... ok, reporta conversaciones: 1
claves ajenas huérfanas .................. 0
```

En el navegador: la conversación sobrevive a recargar, la lista abre cualquiera, y
el borrado de dos toques deja el historial vacío y la pantalla en "Conversación
nueva".

### Detalle de la prueba en navegador

El botón de borrar parecía no responder. No era el código: la confirmación se
desarmaba sola a los 4 s y cada vuelta de la herramienta de navegador tarda más que
eso, así que la captura siempre llegaba después del reset. Verificado con
`javascript_tool` en la misma vuelta (arma → confirma → borra). De paso el margen
subió a 6 s, que es más razonable también para una persona.

### Pendiente

- No hay "borrar todo el historial" en la pantalla; la función existe
  (`conversaciones.borrar_todo`) pero no está expuesta.
- El título de la conversación es la primera pregunta recortada a 60 caracteres.
  Alcanza para reconocerla, pero un resumen de una línea se leería mejor.
- Con muchas conversaciones la lista se va a hacer larga: hoy trae 30 y no hay
  búsqueda ni paginación.

---

## 2026-07-26 - Arranque en un equipo nuevo: el programa se instala solo

Hasta ahora, poner LabLens en otra PC pedía cuatro pasos a mano (crear el
entorno, instalar dependencias, cargar la base de referencia, arrancar) y ninguno
avisaba si el anterior había fallado. Ahora hay un solo punto de entrada que se
encarga de todo y es idempotente: correrlo dos veces no baja nada la segunda vez.

### Archivos nuevos

    iniciar.py        preparador y arranque; solo biblioteca estandar
    LabLens.bat       doble clic en Windows; busca Python y llama a iniciar.py
    lablens.sh        lo mismo en macOS y Linux
    pyproject.toml    metadatos del paquete; lee las dependencias de requirements.txt

`requirements.txt` sigue siendo la única lista de dependencias. `pyproject.toml`
la lee de ahí con `[tool.setuptools.dynamic]` para no tener dos versiones de la
verdad.

### Que resuelve `iniciar.py`

1. **Version de Python.** Corta con un mensaje claro debajo de 3.10. El piso es
   real: `app/formatos.py` usa `str | None` en una anotación que se evalúa en
   tiempo de ejecución.
2. **Entorno roto.** Un `.venv` que llegó copiado de otra PC (OneDrive sincroniza
   la carpeta del proyecto, y `.gitignore` no lo impide) apunta a un Python que
   aquí no existe: la carpeta está pero el intérprete no arranca. Se detecta
   ejecutándolo, y si falla se borra y se rehace. El entorno es desechable.
3. **Descarga innecesaria.** Guarda la huella SHA-256 de `requirements.txt` en
   `.venv/.lablens-instalado.json` y, además, comprueba que los módulos clave se
   importen. Con las dos condiciones cumplidas ni siquiera invoca a pip.
4. **Base vacía.** `datos/` está en `.gitignore`, así que en un equipo nuevo no
   hay base. Si falta, corre `herramientas/cargar_referencia.py` desde
   `BasedeDatos_Preparada/qhali.db`. Si esa carga falla, la app arranca igual:
   quedarse sin escáner por no tener el padrón sería peor.

Las opciones que `iniciar.py` no reconoce pasan tal cual a `servidor.py`. El
analizador va con `allow_abbrev=False` a propósito: sin eso, `--recargar` (que es
de `servidor.py`) se interpretaba como abreviatura de `--cargar-referencia`.

### Verificación ejecutada

Copia limpia del repositorio (sin `.venv`, sin `datos/`, sin `certs/`) en una
carpeta aparte, y arranque desde cero:

```
entorno virtual creado ................... ok
dependencias descargadas ................. 32 paquetes
datos de referencia cargados ............. distrito 1895, establecimiento 26798
                                           rango_referencia 111, biomarcador 45
claves ajenas huerfanas .................. 0
certificado autofirmado generado ......... certs/lablens.crt + .key
GET /api/basedatos por HTTPS ............. 200, 24 tablas
segunda corrida .......................... "Dependencias: al dia", sin red
LabLens.bat --solo-preparar .............. ok (encuentra Python con "py -3")
deteccion de entorno roto ................ 4 casos, todos correctos
```

### Un hallazgo de la prueba

La primera copia limpia quedó en una ruta de 190 caracteres y `cryptography`
falló al importar con *"el nombre del archivo o la extensión es demasiado
largo"*: dentro de `.venv` el anidamiento se come lo que queda de los 260
caracteres de Windows. El error no dice de dónde viene, así que `iniciar.py`
ahora avisa cuando la carpeta del proyecto pasa de 120 caracteres.

### Pendiente

- Las dependencias van con `>=`, no hay archivo de bloqueo. Dos equipos
  instalados en fechas distintas pueden quedar con versiones distintas.
- No hay modo sin conexión: no se incluye una carpeta de ruedas descargadas.
- `lablens.sh` no viene con permiso de ejecución; hay que llamarlo con `bash`.
