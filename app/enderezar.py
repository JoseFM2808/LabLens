"""Correccion de perspectiva y realce del documento recortado.

Es el equivalente al modo "documento" de la camara del celular: toma las 4
esquinas detectadas y las proyecta sobre un rectangulo plano.
"""

from __future__ import annotations

import cv2
import numpy as np

from .detector import ordenar_esquinas

LADO_MAXIMO = 2400  # limite del lado mayor de la imagen enderezada

MODOS = ("color", "gris", "bn")


def _distancia(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


def _tamano_destino(quad: np.ndarray, ratio_objetivo: float | None) -> tuple[int, int]:
    """Calcula el tamano del lienzo plano a partir de los lados del cuadrilatero."""
    sup_izq, sup_der, inf_der, inf_izq = quad
    ancho = max(_distancia(inf_der, inf_izq), _distancia(sup_der, sup_izq))
    alto = max(_distancia(sup_der, inf_der), _distancia(sup_izq, inf_izq))
    ancho = max(ancho, 1.0)
    alto = max(alto, 1.0)

    if ratio_objetivo and ratio_objetivo > 0:
        # Se respeta el area medida y se fuerza la proporcion del formato.
        area = ancho * alto
        alto = (area / ratio_objetivo) ** 0.5
        ancho = alto * ratio_objetivo

    escala = min(1.0, LADO_MAXIMO / max(ancho, alto))
    return max(int(round(ancho * escala)), 1), max(int(round(alto * escala)), 1)


def enderezar(bgr: np.ndarray, quad, ratio_objetivo: float | None = None) -> np.ndarray:
    """Aplica la transformacion de perspectiva y devuelve el documento plano."""
    origen = ordenar_esquinas(quad)
    ancho, alto = _tamano_destino(origen, ratio_objetivo)
    destino = np.array(
        [[0, 0], [ancho - 1, 0], [ancho - 1, alto - 1], [0, alto - 1]],
        dtype=np.float32,
    )
    matriz = cv2.getPerspectiveTransform(origen, destino)
    return cv2.warpPerspective(
        bgr, matriz, (ancho, alto), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def _balance_grises(bgr: np.ndarray) -> np.ndarray:
    """Neutraliza el tinte de la iluminacion para que el papel salga blanco."""
    resultado = bgr.astype(np.float32)
    promedios = [resultado[:, :, c].mean() + 1e-6 for c in range(3)]
    objetivo = float(np.mean(promedios))
    for c in range(3):
        resultado[:, :, c] *= objetivo / promedios[c]
    return np.clip(resultado, 0, 255).astype(np.uint8)


def _nitidez(bgr: np.ndarray) -> np.ndarray:
    borroso = cv2.GaussianBlur(bgr, (0, 0), 1.2)
    return cv2.addWeighted(bgr, 1.45, borroso, -0.45, 0)


def realzar(bgr: np.ndarray, modo: str = "color") -> np.ndarray:
    """Mejora la legibilidad del documento enderezado.

    - ``color``: balance de blancos + contraste local + nitidez. Conserva
      sellos, firmas y marcas en lapicero de color. Es el modo por defecto
      para documentos medicos.
    - ``gris``: escala de grises con contraste local.
    - ``bn``: blanco y negro por umbral adaptativo, ideal para texto impreso.
    """
    if modo not in MODOS:
        modo = "color"

    if modo == "color":
        equilibrado = _balance_grises(bgr)
        lab = cv2.cvtColor(equilibrado, cv2.COLOR_BGR2LAB)
        canal_l, canal_a, canal_b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8))
        lab = cv2.merge((clahe.apply(canal_l), canal_a, canal_b))
        return _nitidez(cv2.cvtColor(lab, cv2.COLOR_LAB2BGR))

    gris = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    if modo == "gris":
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        return cv2.cvtColor(clahe.apply(gris), cv2.COLOR_GRAY2BGR)

    # modo == "bn"
    gris = cv2.medianBlur(gris, 3)
    binaria = cv2.adaptiveThreshold(
        gris, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 12
    )
    return cv2.cvtColor(binaria, cv2.COLOR_GRAY2BGR)


def codificar_jpeg(bgr: np.ndarray, calidad: int = 92) -> bytes:
    ok, buffer = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), calidad])
    if not ok:
        raise RuntimeError("No se pudo codificar la imagen a JPEG")
    return buffer.tobytes()
