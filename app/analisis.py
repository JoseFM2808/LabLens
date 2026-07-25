"""Orquestacion del analisis: encola la extraccion y expone su estado.

Por que en segundo plano: el modelo tarda entre 5 y 30 segundos, y con
reintentos puede llegar a minutos. Si se llamara dentro de `POST /api/capturar`
el telefono se quedaria esperando con la pantalla en blanco. Asi que la captura
responde al instante con ``estado: "en_proceso"`` y el frontend consulta
``GET /api/capturas/{id}/datos`` hasta que termina.

El estado vive en memoria mientras corre; el resultado final se persiste con
`repositorio.guardar`, asi que sobrevive a un reinicio del servidor.
"""

from __future__ import annotations

import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

import cv2

from . import esquema, extraccion, repositorio
from .integraciones import Captura

# Dos a la vez: mas no ayuda porque el cuello de botella es el servicio remoto.
_ejecutor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="lablens-analisis")
_candado = threading.Lock()
_en_curso: dict[str, dict] = {}


def _marcar(captura_id: str, datos: dict) -> None:
    with _candado:
        _en_curso[captura_id] = datos


def _olvidar(captura_id: str) -> None:
    with _candado:
        _en_curso.pop(captura_id, None)


def _trabajo(captura: Captura) -> None:
    """Corre en el hilo de fondo. Nunca debe propagar una excepcion."""
    try:
        bgr = cv2.imread(str(captura.ruta), cv2.IMREAD_COLOR)
        if bgr is None:
            informe = esquema.normalizar(
                captura, {"estado": "error_json", "error": "no se pudo leer el JPEG guardado"}
            )
        else:
            informe = esquema.normalizar(captura, extraccion.extraer(bgr))
        persistencia = repositorio.guardar(informe)
        _marcar(captura.id, {**informe.a_dict(), "persistencia": persistencia})
    except Exception as error:  # noqa: BLE001
        traceback.print_exc()
        _marcar(
            captura.id,
            {
                "id": captura.id,
                "estado": "error_interno",
                "error": f"{type(error).__name__}: {error}",
                "resultados": [],
                "total_resultados": 0,
                "fuera_de_rango": 0,
            },
        )


def encolar(captura: Captura) -> dict:
    """Programa la extraccion y devuelve el estado inicial para la respuesta HTTP."""
    if not extraccion.esta_configurada():
        return {
            "estado": "sin_clave",
            "mensaje": (
                "Definir LABLENS_NVIDIA_API_KEY en el entorno y reiniciar para activar "
                "la extraccion de datos."
            ),
            "url_imagen": f"/capturas/{captura.ruta.name}",
        }

    inicial = {
        "estado": "en_proceso",
        "id": captura.id,
        "modelo": extraccion.modelo(),
        "url_estado": f"/api/capturas/{captura.id}/datos",
    }
    _marcar(captura.id, inicial)
    _ejecutor.submit(_trabajo, captura)
    return inicial


def estado(captura_id: str) -> dict | None:
    """Estado del analisis: primero lo que este en curso, si no lo persistido."""
    with _candado:
        en_memoria = _en_curso.get(captura_id)
    if en_memoria is not None:
        if en_memoria.get("estado") != "en_proceso":
            # Ya termino: se deja de ocupar memoria, el dato esta en disco.
            _olvidar(captura_id)
        return en_memoria
    return repositorio.obtener(captura_id)


def analizar_ahora(captura: Captura) -> dict:
    """Version sincrona, para scripts y pruebas. Bloquea hasta terminar."""
    bgr = cv2.imread(str(captura.ruta), cv2.IMREAD_COLOR)
    if bgr is None:
        raise FileNotFoundError(f"No se pudo leer {captura.ruta}")
    informe = esquema.normalizar(captura, extraccion.extraer(bgr))
    persistencia = repositorio.guardar(informe)
    return {**informe.a_dict(), "persistencia": persistencia}


def guardar_informe_existente(informe) -> dict:
    """Reprocesa la persistencia de un informe ya extraido, sin llamar al modelo.

    Sirve cuando el analisis se guardo en JSON pero no entro a la base (por
    ejemplo, porque faltaba configurar el usuario local).
    """
    return repositorio.guardar(informe)
