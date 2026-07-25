"""Punto de integracion libre: aqui se conecta el sistema que extrae datos.

LabLens termina su trabajo cuando entrega la foto del documento ya plana y
realzada. Lo que se hace con esa foto (OCR, API de laboratorio, modelo de
lenguaje, historia clinica) se define en este archivo y en ningun otro.

Estado actual: conectado al motor de extraccion propio (`app/extraccion.py`),
que manda el documento a un modelo de vision y devuelve los biomarcadores
normalizados. Para usar otro extractor, reemplazar el cuerpo de
``procesar_documento``.

Contrato
--------
La funcion ``procesar_documento(captura)`` se llama automaticamente despues de
cada captura. Recibe un ``Captura`` y devuelve un dict libre que el servidor
adjunta en la respuesta HTTP bajo la clave ``datos`` y muestra en pantalla.
Si lanza una excepcion, la captura NO se pierde: se guarda igual y el error
viaja en ``datos.error``.

Datos disponibles en ``captura``
-------------------------------
    captura.id            identificador unico de la captura
    captura.ruta          ruta absoluta del JPEG enderezado
    captura.ruta_original ruta absoluta de la foto sin procesar
    captura.bytes()        contenido del JPEG enderezado
    captura.base64()       el mismo JPEG en base64, listo para una API
    captura.ancho/alto     dimensiones del documento enderezado
    captura.formato        formato elegido en la camara (ej. a4_vertical)
    captura.modo           realce aplicado (color / gris / bn)
    captura.quad           esquinas normalizadas usadas para enderezar
    captura.creado_en      timestamp ISO 8601

Reglas
------
- Nunca escribir claves ni tokens en este archivo. Leerlos de variables de
  entorno (``os.environ``) o del gestor de secretos del area.
- Mantener la funcion rapida; si el proceso es lento, encolarlo y devolver
  ``{"estado": "en_cola"}``.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Captura:
    """Documento capturado y listo para ser consumido por otro sistema."""

    id: str
    ruta: Path
    ruta_original: Path
    ancho: int
    alto: int
    formato: str
    modo: str
    quad: list[list[float]]
    creado_en: str

    def bytes(self) -> bytes:
        return self.ruta.read_bytes()

    def base64(self) -> str:
        return base64.b64encode(self.bytes()).decode("ascii")

    def resumen(self) -> dict:
        return {
            "id": self.id,
            "archivo": self.ruta.name,
            "ancho": self.ancho,
            "alto": self.alto,
            "formato": self.formato,
            "modo": self.modo,
            "creado_en": self.creado_en,
        }


def procesar_documento(captura: Captura) -> dict:
    """Gancho de integracion. Conectado al motor de extraccion de LabLens.

    Encola el analisis en segundo plano y devuelve el estado inicial. El modelo
    tarda entre 5 y 30 segundos, asi que no se espera aqui: la captura responde
    al instante y el frontend consulta ``/api/capturas/{id}/datos``.

    El recorrido completo es:
        analisis.encolar -> extraccion.extraer -> esquema.normalizar
        -> repositorio.guardar

    Si no hay clave configurada devuelve ``estado: "sin_clave"`` y la captura se
    guarda igual. Para conectar otro extractor en lugar de este, reemplazar el
    cuerpo de esta funcion; ver los ejemplos al final del archivo.
    """
    from . import analisis  # import diferido: analisis importa Captura de aqui

    return analisis.encolar(captura)


# ---------------------------------------------------------------------------
# Ejemplos de integracion. Descomentar uno y llamarlo desde
# procesar_documento(). Ninguno se ejecuta tal como esta el archivo.
# ---------------------------------------------------------------------------

def _ejemplo_ocr_local(captura: Captura) -> dict:
    """OCR en el mismo servidor con Tesseract.

    Requiere: pip install pytesseract  +  Tesseract instalado en el sistema.
    """
    import pytesseract  # noqa: PLC0415  (import diferido a proposito)
    from PIL import Image  # noqa: PLC0415

    texto = pytesseract.image_to_string(Image.open(captura.ruta), lang="spa")
    return {"estado": "ok", "motor": "tesseract", "texto": texto}


def _ejemplo_api_externa(captura: Captura) -> dict:
    """Envio a una API propia que devuelve los campos del documento."""
    import urllib.request  # noqa: PLC0415
    import json  # noqa: PLC0415

    url = os.environ["LABLENS_API_URL"]  # definir en el entorno, no aqui
    token = os.environ["LABLENS_API_TOKEN"]
    cuerpo = json.dumps(
        {"imagen_base64": captura.base64(), "formato": captura.formato}
    ).encode()
    peticion = urllib.request.Request(
        url,
        data=cuerpo,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(peticion, timeout=30) as respuesta:
        return {"estado": "ok", "datos": json.loads(respuesta.read())}


def _ejemplo_modelo_vision(captura: Captura) -> dict:
    """Extraccion de campos con un modelo de vision de Claude.

    Requiere: pip install anthropic  +  ANTHROPIC_API_KEY en el entorno.
    """
    import anthropic  # noqa: PLC0415

    cliente = anthropic.Anthropic()  # toma ANTHROPIC_API_KEY del entorno
    mensaje = cliente.messages.create(
        model="claude-sonnet-5",
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": captura.base64(),
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Extrae los campos de este documento medico en JSON: "
                            "paciente, documento_identidad, fecha, examenes "
                            "(nombre, resultado, unidad, rango_referencia)."
                        ),
                    },
                ],
            }
        ],
    )
    return {"estado": "ok", "motor": "claude", "respuesta": mensaje.content[0].text}
