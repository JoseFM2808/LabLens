"""Motor de extraccion: manda el documento a un modelo de vision y pide JSON.

Adaptado del prototipo de Colab. Tres cambios obligados al traerlo al servidor:

1. La clave sale de una variable de entorno, no de `google.colab.userdata`.
   Nunca se escribe en un archivo del repositorio ni del Drive.
2. Se quita `display(pd.DataFrame(...))`, que solo existe en un notebook. La
   tabla ahora se arma en el frontend.
3. La imagen no se lee de disco: llega ya enderezada y realzada por LabLens, y
   solo se le aplana la iluminacion antes de enviarla.

Configuracion
-------------
Cada valor se busca primero en las variables de entorno y despues en el archivo
local de credenciales (ver `app/credenciales.py`), que vive fuera de la carpeta
sincronizada para que la clave no llegue al Drive corporativo.

    LABLENS_NVIDIA_API_KEY   clave del NIM (tambien se acepta NVIDIA_API_KEY)
    LABLENS_MODELO_VISION    id del modelo; por defecto google/gemma-4-31b-it
    LABLENS_NIM_URL          endpoint; por defecto el de integrate.api.nvidia.com
    LABLENS_OCR_LADO_MAXIMO  lado mayor en px que se envia; por defecto 1100
    LABLENS_OCR_CALIDAD      calidad JPEG; por defecto 80
    LABLENS_TIEMPO_LIMITE    segundos por intento; por defecto 120
    LABLENS_SEGMENTOS        bandas en paralelo; por defecto 3, 1 = pedido unico
    LABLENS_MAX_TOKENS       tope de tokens de salida; por defecto 1500

Si no hay clave, `esta_configurada()` devuelve False y LabLens sigue guardando
las capturas sin intentar extraer nada.
"""

from __future__ import annotations

import base64
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests

from . import credenciales
from .enderezar import codificar_jpeg, preparar_para_ocr
from .esquema import clave_biomarcador, texto_limpio

URL_POR_DEFECTO = "https://integrate.api.nvidia.com/v1/chat/completions"
MODELO_POR_DEFECTO = "google/gemma-4-31b-it"
INTENTOS = 3
ESPERA_ENTRE_INTENTOS = 3.0

# Contrato de salida que se le pide al modelo. Si se agregan campos aqui hay que
# reflejarlos en `esquema.py`; las columnas `paciente` y `fecha_documento` de la
# base de datos ya existen como nulables para poder sumarlos sin migracion.
ESQUEMA_PEDIDO = (
    '{"informacion_general": {"centro_medico": "", "ubicacion": ""}, '
    '"resultados": [{"biomarcador": "", "valor_medido": "", "unidad": "", '
    '"rango_referencia": "", "fuera_de_rango": false}]}'
)
PROMPT = (
    f"JSON ONLY. No talk. Extract to: {ESQUEMA_PEDIDO}. Use 'N/A' for unknown."
)


def _entorno(clave: str, defecto: str) -> str:
    valor = credenciales.obtener(clave)
    return valor or defecto


def clave_api() -> str | None:
    """Clave del NIM: primero variables de entorno, despues el archivo local.

    Ver `app/credenciales.py`: el archivo vive fuera de la carpeta sincronizada
    para que la clave no llegue al Drive corporativo.
    """
    return credenciales.obtener("LABLENS_NVIDIA_API_KEY", "NVIDIA_API_KEY")


def esta_configurada() -> bool:
    return clave_api() is not None


def modelo() -> str:
    return _entorno("LABLENS_MODELO_VISION", MODELO_POR_DEFECTO)


def limpiar_json_respuesta(texto: str) -> str:
    """Limpia y repara la respuesta del modelo para que sea JSON parseable.

    Los modelos suelen envolver el JSON en un bloque markdown o agregar una
    frase antes. Se quita el markdown, se recorta al bloque de llaves mas
    externo y se eliminan los caracteres de control.
    """
    texto = re.sub(r"```json|```", "", texto)
    inicio = texto.find("{")
    fin = texto.rfind("}")
    if inicio != -1 and fin != -1:
        texto = texto[inicio : fin + 1]
    texto = re.sub(r"[\x00-\x1F\x7F]", "", texto)
    return texto.strip()


def imagen_para_modelo(bgr: np.ndarray) -> tuple[bytes, str, tuple[int, int]]:
    """Limpia y codifica el documento. Devuelve (jpeg, base64, (ancho, alto)).

    El lado maximo por defecto es 1100 px. Se probo con 1600 y el servicio
    respondia con ReadTimeout a los 60 s en la mayoria de los intentos: el
    tamano del payload pesa mucho en la latencia. 1100 px sobre un documento ya
    recortado y enderezado alcanza de sobra para la tabla de un informe de
    laboratorio, y el prototipo de Colab funcionaba con 800.
    """
    lado_maximo = int(_entorno("LABLENS_OCR_LADO_MAXIMO", "1100"))
    calidad = int(_entorno("LABLENS_OCR_CALIDAD", "80"))
    limpio = preparar_para_ocr(bgr, lado_maximo=lado_maximo)
    jpeg = codificar_jpeg(limpio, calidad=calidad)
    return jpeg, base64.b64encode(jpeg).decode("ascii"), (limpio.shape[1], limpio.shape[0])


def _pedir(imagen_b64: str, prompt: str, clave: str, base: dict) -> dict:
    """Una llamada al servicio, con reintentos. Devuelve el resultado crudo."""
    url = _entorno("LABLENS_NIM_URL", URL_POR_DEFECTO)
    nombre_modelo = modelo()
    # 120 s por intento: con 60 s se observaron ReadTimeout repetidos contra
    # integrate.api.nvidia.com, incluso cuando el intento que si respondia
    # tardaba solo 18 s. La latencia del servicio es muy variable.
    tiempo_limite = float(_entorno("LABLENS_TIEMPO_LIMITE", "120"))

    cabeceras = {"Authorization": f"Bearer {clave}", "Content-Type": "application/json"}
    cuerpo = {
        "model": nombre_modelo,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{imagen_b64}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_tokens": int(_entorno("LABLENS_MAX_TOKENS", "1500")),
        "temperature": 0.1,
        "top_p": 0.95,
    }

    ultimo_error = None

    for intento in range(1, INTENTOS + 1):
        arranque = time.perf_counter()
        try:
            respuesta = requests.post(url, headers=cabeceras, json=cuerpo, timeout=tiempo_limite)
        except requests.RequestException as error:
            ultimo_error = {"estado": "error_red", "error": f"{type(error).__name__}: {error}"}
            time.sleep(ESPERA_ENTRE_INTENTOS)
            continue

        ms = int((time.perf_counter() - arranque) * 1000)
        if respuesta.status_code != 200:
            ultimo_error = {
                "estado": "error_api",
                "codigo": respuesta.status_code,
                "error": respuesta.text[:400],
            }
            # 4xx no se arregla reintentando, salvo el 429 de limite de uso.
            if 400 <= respuesta.status_code < 500 and respuesta.status_code != 429:
                return {**base, **ultimo_error, "intentos": intento, "ms_respuesta": ms}
            time.sleep(ESPERA_ENTRE_INTENTOS)
            continue

        try:
            contenido = respuesta.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError) as error:
            ultimo_error = {
                "estado": "error_json",
                "error": f"respuesta inesperada del servicio: {type(error).__name__}",
            }
            time.sleep(ESPERA_ENTRE_INTENTOS)
            continue

        limpio = limpiar_json_respuesta(contenido)
        try:
            datos = json.loads(limpio)
        except json.JSONDecodeError as error:
            ultimo_error = {
                "estado": "error_json",
                "error": f"JSON invalido: {error}",
                "respuesta_cruda": limpio[:600],
            }
            time.sleep(ESPERA_ENTRE_INTENTOS)
            continue

        return {
            **base,
            "estado": "ok",
            "intentos": intento,
            "ms_respuesta": ms,
            "crudo": datos,
        }

    return {**base, **(ultimo_error or {"estado": "error_red"}), "intentos": INTENTOS}


# ==========================================================================
# Extraccion en un solo pedido
# ==========================================================================

def extraer(bgr: np.ndarray) -> dict:
    """Envia el documento al modelo y devuelve el JSON crudo mas metadatos.

    Si `LABLENS_SEGMENTOS` es mayor que 1, delega en `extraer_por_segmentos`.

    Nunca lanza excepcion: los errores viajan en el resultado. Estados posibles
    en la clave ``estado``:
      - ``ok``           se obtuvo y parseo el JSON
      - ``sin_clave``    no hay clave configurada
      - ``error_api``    el servicio respondio con un codigo != 200
      - ``error_json``   respondio pero el contenido no era JSON parseable
      - ``error_red``    fallo de red o timeout en los tres intentos
    """
    # 3 segmentos por defecto: medido contra el servicio real, baja la mediana
    # de 25-47 s a 27 s y el peor caso de 73 s a 47 s, con 3/3 de exito frente a
    # 2/3. Ver la tabla de mediciones en HISTORY.md. Con `LABLENS_SEGMENTOS=1`
    # se vuelve al pedido unico.
    segmentos = int(_entorno("LABLENS_SEGMENTOS", "3"))
    if segmentos > 1:
        return extraer_por_segmentos(bgr, segmentos)

    clave = clave_api()
    if not clave:
        return _sin_clave()

    _, imagen_b64, tamano = imagen_para_modelo(bgr)
    base = {"modelo": modelo(), "tamano_enviado": list(tamano), "segmentos": 1}
    return _pedir(imagen_b64, PROMPT, clave, base)


def _sin_clave() -> dict:
    return {
        "estado": "sin_clave",
        "mensaje": "Definir LABLENS_NVIDIA_API_KEY en el entorno para activar la extraccion.",
    }


# ==========================================================================
# Extraccion por segmentos, en paralelo
# ==========================================================================

# El primer segmento lleva el membrete, asi que es el unico al que se le pide la
# informacion general. A los demas solo la tabla, lo que ahorra tokens de salida.
PROMPT_SEGMENTO_CABECERA = (
    "JSON ONLY. No talk. This is the TOP part of a lab report. Extract to: "
    f"{ESQUEMA_PEDIDO}. Only rows fully visible in this crop. Use 'N/A' for unknown."
)
PROMPT_SEGMENTO_CUERPO = (
    'JSON ONLY. No talk. This is a CROP of a lab report table. Extract to: '
    '{"resultados": [{"biomarcador": "", "valor_medido": "", "unidad": "", '
    '"rango_referencia": "", "fuera_de_rango": false}]}. '
    "Only rows fully visible in this crop. Use 'N/A' for unknown."
)

# Solape entre bandas: sin esto una fila cortada por la mitad se perderia en
# los dos segmentos. Con solape aparece completa en alguno de los dos y el
# duplicado se elimina despues.
SOLAPE = 0.08


def _bandas(bgr: np.ndarray, cantidad: int) -> list[np.ndarray]:
    """Corta el documento en bandas horizontales con solape."""
    alto = bgr.shape[0]
    paso = alto / cantidad
    margen = paso * SOLAPE
    recortes = []
    for indice in range(cantidad):
        inicio = max(0, int(indice * paso - margen))
        fin = min(alto, int((indice + 1) * paso + margen))
        recortes.append(bgr[inicio:fin])
    return recortes


def extraer_por_segmentos(bgr: np.ndarray, cantidad: int) -> dict:
    """Parte el documento en bandas y las consulta en paralelo.

    La idea es que el tiempo total sea el de la banda mas lenta en vez de la
    suma. Ojo con el efecto contrario: si la latencia del servicio tiene mucha
    dispersion, el maximo de N muestras es peor que una sola muestra. Conviene
    medir antes de subir `LABLENS_SEGMENTOS` (ver HISTORY.md, donde estan las
    mediciones que justificaron el valor por defecto).

    Las filas duplicadas por el solape se eliminan por clave de biomarcador.
    """
    clave = clave_api()
    if not clave:
        return _sin_clave()

    recortes = _bandas(bgr, cantidad)
    preparados = [imagen_para_modelo(recorte) for recorte in recortes]
    nombre_modelo = modelo()

    def trabajo(indice: int) -> dict:
        _, imagen_b64, tamano = preparados[indice]
        prompt = PROMPT_SEGMENTO_CABECERA if indice == 0 else PROMPT_SEGMENTO_CUERPO
        base = {"modelo": nombre_modelo, "tamano_enviado": list(tamano), "segmento": indice}
        return _pedir(imagen_b64, prompt, clave, base)

    arranque = time.perf_counter()
    with ThreadPoolExecutor(max_workers=cantidad) as ejecutor:
        respuestas = list(ejecutor.map(trabajo, range(cantidad)))
    ms_total = int((time.perf_counter() - arranque) * 1000)

    return _fusionar(respuestas, nombre_modelo, cantidad, ms_total, preparados)


def _fusionar(
    respuestas: list[dict],
    nombre_modelo: str,
    cantidad: int,
    ms_total: int,
    preparados: list,
) -> dict:
    """Junta los segmentos en un unico JSON con la forma del contrato original."""
    correctas = [r for r in respuestas if r.get("estado") == "ok"]
    if not correctas:
        fallida = respuestas[0] if respuestas else {"estado": "error_red"}
        return {
            **fallida,
            "segmentos": cantidad,
            "ms_respuesta": ms_total,
            "error": f"ningun segmento respondio. Ultimo error: {fallida.get('error')}",
        }

    general: dict = {}
    resultados: list[dict] = []
    vistos: set[str] = set()

    for respuesta in respuestas:
        if respuesta.get("estado") != "ok":
            continue
        crudo = respuesta.get("crudo") or {}

        # La informacion general se toma del primer segmento que la traiga con
        # algo distinto de N/A.
        for campo, valor in (crudo.get("informacion_general") or {}).items():
            if campo not in general and texto_limpio(valor) is not None:
                general[campo] = valor

        for fila in crudo.get("resultados") or []:
            if not isinstance(fila, dict):
                continue
            nombre = texto_limpio(fila.get("biomarcador"))
            if nombre is None:
                continue
            clave_fila = clave_biomarcador(nombre)
            if clave_fila in vistos:  # duplicado por el solape entre bandas
                continue
            vistos.add(clave_fila)
            resultados.append(fila)

    return {
        "estado": "ok",
        "modelo": nombre_modelo,
        "segmentos": cantidad,
        "segmentos_ok": len(correctas),
        "intentos": max(r.get("intentos") or 1 for r in respuestas),
        "ms_respuesta": ms_total,
        "ms_por_segmento": [r.get("ms_respuesta") for r in respuestas],
        "tamano_enviado": [p[2] for p in preparados],
        "crudo": {"informacion_general": general, "resultados": resultados},
    }
