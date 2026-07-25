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

### Dependencias instaladas
fastapi 0.140.0, uvicorn 0.51.0, starlette 1.3.1, opencv-python-headless
5.0.0.93, numpy 2.5.1, python-multipart 0.0.32, cryptography 49.0.0,
qrcode 8.2. Entorno: `.venv` con Python 3.13.
