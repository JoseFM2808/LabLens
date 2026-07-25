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


def aplanar_iluminacion(bgr: np.ndarray) -> np.ndarray:
    """Quita el degradado de luz para que el fondo del papel quede blanco parejo.

    Correccion de campo plano: se estima la iluminacion con un desenfoque muy
    grande y se divide la imagen por esa estimacion. Elimina sombras suaves y
    vinetas, que es lo que mas confunde al OCR. Solo se toca la luminancia (canal
    L), asi que los sellos y las firmas de color se conservan.

    Es complementario al CLAHE de `realzar`: CLAHE trabaja el contraste local,
    esto quita la variacion de baja frecuencia.
    """
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    canal_l, canal_a, canal_b = cv2.split(lab)

    # El nucleo debe ser bastante mayor que el texto para no borrarlo.
    lado = max(bgr.shape[:2])
    radio = max(31, (lado // 8) | 1)  # impar
    fondo = cv2.GaussianBlur(canal_l, (radio, radio), 0)
    fondo = np.maximum(fondo, 1)
    corregido = cv2.divide(canal_l, fondo, scale=235.0)

    # Estiramiento suave de contraste, recortando colas.
    bajo, alto = np.percentile(corregido, (2, 99))
    if alto - bajo > 5:
        corregido = np.clip((corregido.astype(np.float32) - bajo) * (255.0 / (alto - bajo)), 0, 255)
    corregido = corregido.astype(np.uint8)

    return cv2.cvtColor(cv2.merge((corregido, canal_a, canal_b)), cv2.COLOR_LAB2BGR)


def preparar_para_ocr(bgr: np.ndarray, lado_maximo: int = 1600) -> np.ndarray:
    """Deja el documento listo para el modelo de vision.

    El documento ya llega enderezado y realzado, asi que aqui solo se aplana la
    iluminacion y se reduce el tamano. No se vuelve a aplicar nitidez: hacerlo
    dos veces genera halos alrededor de las letras y empeora la lectura.
    """
    limpio = aplanar_iluminacion(bgr)
    lado = max(limpio.shape[:2])
    if lado > lado_maximo:
        escala = lado_maximo / lado
        limpio = cv2.resize(limpio, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)
    return limpio


def codificar_jpeg(bgr: np.ndarray, calidad: int = 92) -> bytes:
    ok, buffer = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), calidad])
    if not ok:
        raise RuntimeError("No se pudo codificar la imagen a JPEG")
    return buffer.tobytes()
