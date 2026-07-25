"""Deteccion del contorno de un documento dentro de una imagen.

Estrategia: se generan candidatos con dos metodos independientes (bordes
Canny y umbral adaptativo), se puntua cada cuadrilatero y se devuelve el
mejor. Las coordenadas se entregan normalizadas (0..1) para que el frontend
pueda dibujar el contorno sin depender de la resolucion del cuadro.
"""

from __future__ import annotations

import cv2
import numpy as np

# Un documento debe ocupar al menos este porcentaje del cuadro para ser valido.
AREA_MINIMA = 0.10
# Por encima de este porcentaje se asume que se detecto el borde del cuadro.
AREA_MAXIMA = 0.985
# Desvio maximo permitido respecto a 90 grados en cada esquina.
TOLERANCIA_ANGULO = 40.0


def ordenar_esquinas(puntos) -> np.ndarray:
    """Ordena 4 puntos como sup-izq, sup-der, inf-der, inf-izq.

    Usa el angulo respecto al centroide (robusto ante rotaciones grandes) y
    luego rota la secuencia para que arranque en la esquina mas cercana al
    origen de la imagen.
    """
    pts = np.asarray(puntos, dtype=np.float32).reshape(4, 2)
    centro = pts.mean(axis=0)
    angulos = np.arctan2(pts[:, 1] - centro[1], pts[:, 0] - centro[0])
    pts = pts[np.argsort(angulos)]  # sentido horario (eje Y hacia abajo)
    inicio = int(np.argmin(pts.sum(axis=1)))
    return np.roll(pts, -inicio, axis=0)


def _regularidad_angulos(quad: np.ndarray) -> float:
    """Devuelve 1.0 si las 4 esquinas son rectas, 0.0 si estan muy torcidas."""
    desvios = []
    for i in range(4):
        a = quad[i - 1] - quad[i]
        b = quad[(i + 1) % 4] - quad[i]
        norma = np.linalg.norm(a) * np.linalg.norm(b)
        if norma < 1e-6:
            return 0.0
        coseno = float(np.dot(a, b) / norma)
        angulo = np.degrees(np.arccos(np.clip(coseno, -1.0, 1.0)))
        desvios.append(abs(angulo - 90.0))
    peor = max(desvios)
    if peor > TOLERANCIA_ANGULO:
        return 0.0
    return 1.0 - (peor / TOLERANCIA_ANGULO)


def _candidatos_desde_mascara(mascara: np.ndarray, area_cuadro: float) -> list[np.ndarray]:
    """Extrae cuadrilateros convexos de una mascara binaria de bordes."""
    contornos, _ = cv2.findContours(mascara, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contornos = sorted(contornos, key=cv2.contourArea, reverse=True)[:10]

    encontrados: list[np.ndarray] = []
    for contorno in contornos:
        area_contorno = abs(cv2.contourArea(contorno))
        if area_contorno < AREA_MINIMA * area_cuadro:
            continue
        perimetro = cv2.arcLength(contorno, True)
        aprox_valida = None
        for epsilon in (0.02, 0.03, 0.05, 0.08):
            aprox = cv2.approxPolyDP(contorno, epsilon * perimetro, True)
            if len(aprox) == 4 and cv2.isContourConvex(aprox):
                aprox_valida = aprox
                break
        if aprox_valida is None:
            # Ultimo recurso: rectangulo rotado que envuelve al contorno.
            caja = cv2.boxPoints(cv2.minAreaRect(contorno))
            if abs(cv2.contourArea(caja)) > 0 and (
                area_contorno / abs(cv2.contourArea(caja)) > 0.80
            ):
                aprox_valida = caja
        if aprox_valida is not None:
            encontrados.append(np.asarray(aprox_valida, dtype=np.float32).reshape(4, 2))
    return encontrados


def _mascara_bordes(gris: np.ndarray) -> np.ndarray:
    """Mascara por gradiente: sirve con fondos de contraste medio."""
    suave = cv2.GaussianBlur(gris, (5, 5), 0)
    # El cierre morfologico tapa el texto para que no genere bordes internos.
    nucleo = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    cerrado = cv2.morphologyEx(suave, cv2.MORPH_CLOSE, nucleo)
    mediana = float(np.median(cerrado))
    bajo = int(max(0, 0.66 * mediana))
    alto = int(min(255, 1.33 * mediana))
    bordes = cv2.Canny(cerrado, bajo, alto)
    return cv2.dilate(bordes, np.ones((3, 3), np.uint8), iterations=1)


def _mascara_umbral(gris: np.ndarray) -> np.ndarray:
    """Mascara por umbral: sirve con papel claro sobre fondo oscuro."""
    suave = cv2.GaussianBlur(gris, (7, 7), 0)
    _, binaria = cv2.threshold(suave, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    nucleo = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    binaria = cv2.morphologyEx(binaria, cv2.MORPH_CLOSE, nucleo, iterations=2)
    return cv2.morphologyEx(binaria, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))


def detectar_documento(bgr: np.ndarray) -> dict | None:
    """Busca el documento en la imagen.

    Devuelve ``None`` si no se encontro nada confiable, o un dict con:
      - ``quad``: 4 esquinas normalizadas 0..1, orden sup-izq -> inf-izq
      - ``quad_px``: las mismas esquinas en pixeles
      - ``area``: fraccion del cuadro que ocupa el documento
      - ``puntaje``: 0..1, combina area y regularidad de las esquinas
      - ``metodo``: mascara que produjo el mejor candidato
    """
    if bgr is None or bgr.size == 0:
        return None

    alto, ancho = bgr.shape[:2]
    area_cuadro = float(alto * ancho)
    gris = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    mejor: dict | None = None
    for nombre, mascara in (("bordes", _mascara_bordes(gris)), ("umbral", _mascara_umbral(gris))):
        for quad in _candidatos_desde_mascara(mascara, area_cuadro):
            ordenado = ordenar_esquinas(quad)
            area = abs(cv2.contourArea(ordenado.reshape(-1, 1, 2))) / area_cuadro
            if not (AREA_MINIMA <= area <= AREA_MAXIMA):
                continue
            regularidad = _regularidad_angulos(ordenado)
            if regularidad <= 0.0:
                continue
            puntaje = 0.55 * min(area / 0.75, 1.0) + 0.45 * regularidad
            if mejor is None or puntaje > mejor["puntaje"]:
                mejor = {
                    "quad_px": ordenado,
                    "area": float(area),
                    "puntaje": float(puntaje),
                    "metodo": nombre,
                }

    if mejor is None:
        return None

    quad_px = mejor["quad_px"]
    normalizado = np.column_stack((quad_px[:, 0] / ancho, quad_px[:, 1] / alto))
    return {
        "quad": [[round(float(x), 5), round(float(y), 5)] for x, y in normalizado],
        "quad_px": quad_px,
        "area": round(mejor["area"], 4),
        "puntaje": round(mejor["puntaje"], 4),
        "metodo": mejor["metodo"],
    }


def decodificar_jpeg(datos: bytes) -> np.ndarray | None:
    """Convierte bytes JPEG/PNG en una imagen BGR de OpenCV."""
    buffer = np.frombuffer(datos, dtype=np.uint8)
    if buffer.size == 0:
        return None
    return cv2.imdecode(buffer, cv2.IMREAD_COLOR)
