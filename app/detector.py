"""Deteccion del contorno de un documento de fondo blanco (A4 / A5).

Version 2. La version 1 solo miraba la forma (area + esquinas rectas), asi que
cualquier objeto rectangular grande le ganaba al documento. Ahora se combinan
bordes y color, que es la conclusion del estado del arte en localizacion de
documentos en movil (ver HISTORY.md para las fuentes).

Pipeline
--------
1. `_preparar`: mapas auxiliares de la imagen.
   - `papel`: mascara de "papel blanco" = acromatico (S bajo) y claro (V alto
     por Otsu). Es la senal de color.
   - `magnitud`: magnitud de gradiente normalizada. Es la senal de borde.
2. `_fuentes_de_candidatos`: tres generadores independientes de cuadrilateros.
   - contornos de la mascara de papel
   - contornos de Canny
   - lineas de Hough agrupadas en horizontales y verticales, intersectadas
3. `_evaluar`: cada candidato recibe un puntaje con seis componentes y se
   rechaza si no parece papel. Gana el de mayor puntaje.

Las seis componentes del puntaje
--------------------------------
- `perimetro`: cuanto gradiente real hay bajo los 4 lados. El lado mas debil
  pesa la mitad del componente, asi que un cuadrilatero con un lado inventado
  no puede ganar. Es la idea del scoring de Dropbox.
- `papel`: cuanto del interior es papel blanco, mas contraste contra el
  exterior, brillo absoluto y baja saturacion.
- `area`: fraccion del cuadro que ocupa.
- `angulos`: rango entre el angulo interior mayor y el menor.
- `formato`: cercania a la proporcion esperada. A4 y A5 comparten 1:raiz(2).
- `guia`: cuanto del candidato cae dentro del marco guia de la camara.
"""

from __future__ import annotations

import itertools

import cv2
import numpy as np

# --- Rechazos duros -------------------------------------------------------
AREA_MINIMA = 0.15          # menos que esto: el documento esta muy lejos
AREA_MAXIMA = 0.97          # mas que esto: es el borde del cuadro, no el papel
RANGO_ANGULAR_MAXIMO = 40.0  # grados entre la esquina mas abierta y la mas cerrada
# El interior de un documento real da cobertura ~0.95. Se exige 0.65 para
# tolerar sombras y texto denso, pero rechazando los cuadrilateros que mezclan
# el papel con objetos de al lado: esos rondan 0.4-0.6.
COBERTURA_PAPEL_MINIMA = 0.65
PUNTAJE_PAPEL_MINIMO = 0.45

# --- Parametros de las senales -------------------------------------------
SATURACION_PAPEL = 70       # S < 70 se considera acromatico (papel blanco)
MUESTRAS_LADO = 48          # puntos por lado para el soporte de perimetro
LADO_REJILLA = 22           # rejilla interior de 22x22 = 484 muestras
MAXIMOS_CANDIDATOS = 40     # tope de candidatos que se puntuan por cuadro

PESOS = {
    "perimetro": 0.30,
    "papel": 0.28,
    "area": 0.12,
    "angulos": 0.12,
    "formato": 0.10,
    "guia": 0.08,
}

# Rejilla del cuadrado unidad, con margen para no muestrear sobre el borde.
_paso = np.linspace(0.08, 0.92, LADO_REJILLA, dtype=np.float32)
_malla_x, _malla_y = np.meshgrid(_paso, _paso)
REJILLA_UNIDAD = np.column_stack((_malla_x.ravel(), _malla_y.ravel())).reshape(-1, 1, 2)

# Posiciones a lo largo de un lado, sin llegar a las esquinas.
_T_LADO = np.linspace(0.06, 0.94, MUESTRAS_LADO, dtype=np.float32).reshape(-1, 1)


# ==========================================================================
# Geometria basica
# ==========================================================================

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


def _rango_angular(quad: np.ndarray) -> float:
    """Diferencia entre el angulo interior mayor y el menor, en grados.

    Un rectangulo perfecto da 0. Criterio tomado de OpenCV-Document-Scanner:
    es mas estable que medir el desvio de cada esquina por separado.
    """
    angulos = []
    for i in range(4):
        a = quad[i - 1] - quad[i]
        b = quad[(i + 1) % 4] - quad[i]
        norma = np.linalg.norm(a) * np.linalg.norm(b)
        if norma < 1e-6:
            return 360.0
        coseno = float(np.dot(a, b) / norma)
        angulos.append(np.degrees(np.arccos(np.clip(coseno, -1.0, 1.0))))
    return float(max(angulos) - min(angulos))


def _lados(quad: np.ndarray) -> tuple[float, float]:
    """Ancho y alto medios del cuadrilatero."""
    largo = lambda a, b: float(np.linalg.norm(quad[a] - quad[b]))  # noqa: E731
    ancho = max(largo(0, 1), largo(3, 2))
    alto = max(largo(0, 3), largo(1, 2))
    return ancho, alto


def _area(quad: np.ndarray) -> float:
    return abs(float(cv2.contourArea(quad.reshape(-1, 1, 2))))


def _homografia_unidad(quad: np.ndarray) -> np.ndarray:
    unidad = np.float32([[0, 0], [1, 0], [1, 1], [0, 1]])
    return cv2.getPerspectiveTransform(unidad, quad.astype(np.float32))


def _muestrear(mapa: np.ndarray, puntos: np.ndarray) -> np.ndarray:
    """Lee valores del mapa en coordenadas float, recortando a los bordes."""
    alto, ancho = mapa.shape[:2]
    xs = np.clip(np.rint(puntos[:, 0]).astype(np.int32), 0, ancho - 1)
    ys = np.clip(np.rint(puntos[:, 1]).astype(np.int32), 0, alto - 1)
    return mapa[ys, xs]


# ==========================================================================
# Mapas auxiliares
# ==========================================================================

def _preparar(bgr: np.ndarray) -> dict:
    """Calcula una vez por cuadro las senales de color y de borde."""
    alto, ancho = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    saturacion = hsv[:, :, 1]
    valor = hsv[:, :, 2]

    # Senal de color: papel = acromatico y claro. El umbral de brillo lo pone
    # Otsu, asi que se adapta a la iluminacion de la foto.
    suave_v = cv2.GaussianBlur(valor, (5, 5), 0)
    _, claro = cv2.threshold(suave_v, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    acromatico = (saturacion < SATURACION_PAPEL).astype(np.uint8) * 255
    papel = cv2.bitwise_and(claro, acromatico)
    nucleo = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    papel = cv2.morphologyEx(papel, cv2.MORPH_CLOSE, nucleo, iterations=2)
    papel = cv2.morphologyEx(
        papel, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    )

    # Senal de borde: magnitud de gradiente normalizada por el percentil 99
    # (mas estable que el maximo, que lo fija un solo pixel de ruido).
    gris = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gris = cv2.GaussianBlur(gris, (5, 5), 0)
    gx = cv2.Sobel(gris, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gris, cv2.CV_32F, 0, 1, ksize=3)
    magnitud = cv2.magnitude(gx, gy)
    tope = float(np.percentile(magnitud, 99)) or 1.0
    magnitud = np.clip(magnitud / tope, 0.0, 1.0)

    # Canny sobre la imagen con el texto tapado, para no generar bordes internos.
    cerrado = cv2.morphologyEx(gris, cv2.MORPH_CLOSE, nucleo)
    mediana = float(np.median(cerrado))
    canny = cv2.Canny(cerrado, int(max(0, 0.66 * mediana)), int(min(255, 1.33 * mediana)))
    canny = cv2.dilate(canny, np.ones((3, 3), np.uint8), iterations=1)

    return {
        "forma": (alto, ancho),
        "area_cuadro": float(alto * ancho),
        "diagonal": float(np.hypot(alto, ancho)),
        "papel": papel,
        "borde_papel": cv2.morphologyEx(papel, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)),
        "canny": canny,
        "magnitud": magnitud,
        "saturacion": saturacion,
        "valor": valor,
    }


# ==========================================================================
# Generadores de candidatos
# ==========================================================================

def _aproximar_cuatro(contorno: np.ndarray) -> np.ndarray | None:
    """Reduce un contorno a 4 esquinas.

    Se trabaja sobre la envolvente convexa (un documento siempre es convexo) y
    se sube epsilon poco a poco hasta obtener 4 vertices. Si nunca ocurre, se
    usa el rectangulo rotado que lo envuelve.
    """
    envolvente = cv2.convexHull(contorno)
    perimetro = cv2.arcLength(envolvente, True)
    if perimetro < 1e-3:
        return None
    for epsilon in np.arange(0.01, 0.13, 0.01):
        aprox = cv2.approxPolyDP(envolvente, float(epsilon) * perimetro, True)
        if len(aprox) == 4:
            return aprox.reshape(4, 2).astype(np.float32)
    caja = cv2.boxPoints(cv2.minAreaRect(envolvente))
    return caja.astype(np.float32)


def _candidatos_de_mascara(mascara: np.ndarray, mapas: dict, metodo: str) -> list:
    contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contornos = sorted(contornos, key=cv2.contourArea, reverse=True)[:8]
    salida = []
    for contorno in contornos:
        if cv2.contourArea(contorno) < AREA_MINIMA * mapas["area_cuadro"] * 0.6:
            continue
        quad = _aproximar_cuatro(contorno)
        if quad is not None:
            salida.append((metodo, quad))
    return salida


def _lineas_dominantes(mapas: dict) -> tuple[list, list]:
    """Lineas de Hough separadas en casi-horizontales y casi-verticales.

    Cada linea se guarda como (punto_a, punto_b, largo). Se fusionan las
    duplicadas para no inflar la combinatoria.
    """
    alto, ancho = mapas["forma"]
    lado_menor = min(alto, ancho)
    bordes = cv2.bitwise_or(mapas["canny"], mapas["borde_papel"])
    segmentos = cv2.HoughLinesP(
        bordes,
        rho=1,
        theta=np.pi / 180,
        threshold=45,
        minLineLength=int(0.22 * lado_menor),
        maxLineGap=int(0.04 * lado_menor),
    )
    if segmentos is None:
        return [], []

    horizontales, verticales = [], []
    for x1, y1, x2, y2 in segmentos.reshape(-1, 4):
        a = np.array([x1, y1], dtype=np.float32)
        b = np.array([x2, y2], dtype=np.float32)
        largo = float(np.linalg.norm(b - a))
        angulo = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1))) % 180.0
        if angulo < 40.0 or angulo > 140.0:
            horizontales.append((a, b, largo))
        elif 50.0 <= angulo <= 130.0:
            verticales.append((a, b, largo))

    def fusionar(lineas: list, eje: int) -> list:
        # Se ordenan por largo y se descarta la que casi coincide con otra ya
        # aceptada (mismo angulo y misma posicion en el eje perpendicular).
        lineas.sort(key=lambda l: l[2], reverse=True)
        aceptadas: list = []
        for a, b, largo in lineas:
            centro = (a + b) / 2.0
            angulo = np.degrees(np.arctan2(b[1] - a[1], b[0] - a[0])) % 180.0
            duplicada = False
            for a2, b2, _ in aceptadas:
                centro2 = (a2 + b2) / 2.0
                angulo2 = np.degrees(np.arctan2(b2[1] - a2[1], b2[0] - a2[0])) % 180.0
                if (
                    abs(angulo - angulo2) < 12.0
                    and abs(centro[eje] - centro2[eje]) < 0.06 * lado_menor
                ):
                    duplicada = True
                    break
            if not duplicada:
                aceptadas.append((a, b, largo))
            if len(aceptadas) >= 6:
                break
        return aceptadas

    return fusionar(horizontales, 1), fusionar(verticales, 0)


def _interseccion(linea_a, linea_b) -> np.ndarray | None:
    (p1, p2, _), (p3, p4, _) = linea_a, linea_b
    d1 = p2 - p1
    d2 = p4 - p3
    denominador = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(denominador) < 1e-6:
        return None
    t = ((p3[0] - p1[0]) * d2[1] - (p3[1] - p1[1]) * d2[0]) / denominador
    return p1 + d1 * t


def _candidatos_de_hough(mapas: dict) -> list:
    """Enumera cuadrilateros como 2 lineas horizontales x 2 verticales."""
    horizontales, verticales = _lineas_dominantes(mapas)
    if len(horizontales) < 2 or len(verticales) < 2:
        return []

    alto, ancho = mapas["forma"]
    margen = 0.06 * mapas["diagonal"]
    salida = []
    for (h1, h2) in itertools.combinations(horizontales, 2):
        for (v1, v2) in itertools.combinations(verticales, 2):
            esquinas = [
                _interseccion(h1, v1),
                _interseccion(h1, v2),
                _interseccion(h2, v2),
                _interseccion(h2, v1),
            ]
            if any(e is None for e in esquinas):
                continue
            quad = np.array(esquinas, dtype=np.float32)
            # Las esquinas deben caer dentro del cuadro (con algo de holgura).
            if (
                quad[:, 0].min() < -margen
                or quad[:, 1].min() < -margen
                or quad[:, 0].max() > ancho + margen
                or quad[:, 1].max() > alto + margen
            ):
                continue
            salida.append(("hough", quad))
    return salida


def _fuentes_de_candidatos(mapas: dict) -> list:
    """Junta los tres generadores y quita duplicados."""
    brutos = (
        _candidatos_de_mascara(mapas["papel"], mapas, "papel")
        + _candidatos_de_mascara(mapas["canny"], mapas, "canny")
        + _candidatos_de_hough(mapas)
    )

    tolerancia = 0.015 * mapas["diagonal"]
    unicos: list = []
    for metodo, quad in brutos:
        ordenado = ordenar_esquinas(quad)
        if any(
            np.abs(ordenado - previo).max() < tolerancia for _, previo in unicos
        ):
            continue
        unicos.append((metodo, ordenado))
    return unicos


# ==========================================================================
# Puntuacion
# ==========================================================================

def _puntaje_perimetro(mapas: dict, quad: np.ndarray) -> float:
    """Cuanto gradiente real hay debajo de los 4 lados.

    Se muestrea tambien a +-1 y +-2 px de la linea, para tolerar que el
    candidato este un par de pixeles corrido. El lado mas debil pesa la mitad:
    asi un cuadrilatero con tres lados buenos y uno inventado no puede ganar.
    """
    magnitud = mapas["magnitud"]
    por_lado = []
    for i in range(4):
        a = quad[i]
        b = quad[(i + 1) % 4]
        direccion = b - a
        largo = float(np.linalg.norm(direccion))
        if largo < 1e-3:
            return 0.0
        puntos = a + direccion * _T_LADO
        normal = np.array([direccion[1], -direccion[0]], dtype=np.float32) / largo
        valores = np.maximum.reduce(
            [_muestrear(magnitud, puntos + normal * desvio) for desvio in (-2.0, -1.0, 0.0, 1.0, 2.0)]
        )
        por_lado.append(float(valores.mean()))
    return float(0.5 * np.mean(por_lado) + 0.5 * np.min(por_lado))


def _puntaje_papel(mapas: dict, quad: np.ndarray, interior: np.ndarray) -> dict:
    """Cuanto se parece el interior a una hoja blanca."""
    cobertura = float((_muestrear(mapas["papel"], interior) > 0).mean())
    valor_dentro = float(_muestrear(mapas["valor"], interior).mean())
    saturacion_dentro = float(_muestrear(mapas["saturacion"], interior).mean())

    # Anillo exterior: se desplazan los lados hacia afuera y se descartan los
    # puntos que caen fuera de la imagen (recortarlos sesgaria el promedio).
    alto, ancho = mapas["forma"]
    desvio = max(3.0, 0.025 * mapas["diagonal"])
    fuera = []
    for i in range(4):
        a = quad[i]
        b = quad[(i + 1) % 4]
        direccion = b - a
        largo = float(np.linalg.norm(direccion))
        if largo < 1e-3:
            continue
        normal = np.array([direccion[1], -direccion[0]], dtype=np.float32) / largo
        fuera.append(a + direccion * _T_LADO + normal * desvio)
    if fuera:
        anillo = np.vstack(fuera)
        validos = (
            (anillo[:, 0] >= 0)
            & (anillo[:, 1] >= 0)
            & (anillo[:, 0] < ancho)
            & (anillo[:, 1] < alto)
        )
        anillo = anillo[validos]
    else:
        anillo = np.empty((0, 2), dtype=np.float32)

    if len(anillo) >= 0.2 * MUESTRAS_LADO * 4:
        valor_fuera = float(_muestrear(mapas["valor"], anillo).mean())
        contraste = float(np.clip((valor_dentro - valor_fuera) / 40.0, 0.0, 1.0))
    else:
        # El documento llega al borde del cuadro: no hay exterior que medir.
        valor_fuera = float("nan")
        contraste = 0.5

    blancura = float(np.clip((valor_dentro - 100.0) / 110.0, 0.0, 1.0))
    neutro = float(np.clip(1.0 - saturacion_dentro / 90.0, 0.0, 1.0))
    # La cobertura manda: es la senal que distingue el papel de un objeto vecino.
    puntaje = 0.55 * cobertura + 0.20 * contraste + 0.10 * blancura + 0.15 * neutro
    return {
        "puntaje": float(puntaje),
        "cobertura": cobertura,
        "contraste": contraste,
        "blancura": blancura,
        "neutro": neutro,
        "valor_dentro": round(valor_dentro, 1),
        "valor_fuera": None if np.isnan(valor_fuera) else round(valor_fuera, 1),
        "saturacion_dentro": round(saturacion_dentro, 1),
    }


def _puntaje_formato(quad: np.ndarray, ratio_objetivo: float | None) -> float | None:
    """Cercania a la proporcion esperada. A4 y A5 comparten 1:raiz(2)."""
    if not ratio_objetivo or ratio_objetivo <= 0:
        return None
    ancho, alto = _lados(quad)
    if alto < 1e-3:
        return None
    razon = (ancho / alto) / ratio_objetivo
    return float(np.clip(1.0 - abs(np.log(razon)) / np.log(1.7), 0.0, 1.0))


def _puntaje_guia(mapas: dict, quad: np.ndarray, interior: np.ndarray, guia) -> float | None:
    """Cuanto del candidato cae dentro del marco guia dibujado en la camara."""
    if not guia or len(guia) != 4:
        return None
    alto, ancho = mapas["forma"]
    gx, gy, gancho, galto = (
        float(guia[0]) * ancho,
        float(guia[1]) * alto,
        float(guia[2]) * ancho,
        float(guia[3]) * alto,
    )
    if gancho <= 1 or galto <= 1:
        return None
    dentro = float(
        (
            (interior[:, 0] >= gx)
            & (interior[:, 0] <= gx + gancho)
            & (interior[:, 1] >= gy)
            & (interior[:, 1] <= gy + galto)
        ).mean()
    )
    centro_quad = quad.mean(axis=0)
    centro_guia = np.array([gx + gancho / 2.0, gy + galto / 2.0], dtype=np.float32)
    distancia = float(np.linalg.norm(centro_quad - centro_guia) / np.hypot(gancho, galto))
    cercania = float(np.clip(1.0 - distancia, 0.0, 1.0))
    return 0.75 * dentro + 0.25 * cercania


def _evaluar(
    quad: np.ndarray,
    mapas: dict,
    metodo: str,
    guia,
    ratio_objetivo: float | None,
) -> dict:
    """Puntua un candidato. Siempre devuelve dict; `aceptado` dice si sirve."""
    area = _area(quad) / mapas["area_cuadro"]
    rango = _rango_angular(quad)
    base = {"metodo": metodo, "quad_px": quad, "area": round(area, 4), "rango_angular": round(rango, 1)}

    if not (AREA_MINIMA <= area <= AREA_MAXIMA):
        return {**base, "aceptado": False, "rechazo": "area", "puntaje": 0.0, "componentes": {}}
    if rango > RANGO_ANGULAR_MAXIMO:
        return {**base, "aceptado": False, "rechazo": "angulos", "puntaje": 0.0, "componentes": {}}

    interior = cv2.perspectiveTransform(REJILLA_UNIDAD, _homografia_unidad(quad)).reshape(-1, 2)
    papel = _puntaje_papel(mapas, quad, interior)

    componentes = {
        "perimetro": round(_puntaje_perimetro(mapas, quad), 3),
        "papel": round(papel["puntaje"], 3),
        "area": round(float(np.clip(area / 0.60, 0.0, 1.0)), 3),
        "angulos": round(float(1.0 - rango / RANGO_ANGULAR_MAXIMO), 3),
    }
    formato = _puntaje_formato(quad, ratio_objetivo)
    if formato is not None:
        componentes["formato"] = round(formato, 3)
    puntaje_guia = _puntaje_guia(mapas, quad, interior, guia)
    if puntaje_guia is not None:
        componentes["guia"] = round(puntaje_guia, 3)

    peso_total = sum(PESOS[clave] for clave in componentes)
    puntaje = sum(PESOS[clave] * valor for clave, valor in componentes.items()) / peso_total

    detalle = {**base, "componentes": componentes, "papel_detalle": papel, "puntaje": round(puntaje, 4)}

    if papel["cobertura"] < COBERTURA_PAPEL_MINIMA:
        return {**detalle, "aceptado": False, "rechazo": "no_es_papel"}
    if papel["puntaje"] < PUNTAJE_PAPEL_MINIMO:
        return {**detalle, "aceptado": False, "rechazo": "papel_debil"}
    return {**detalle, "aceptado": True, "rechazo": None}


# ==========================================================================
# Entrada publica
# ==========================================================================

def _normalizar(quad: np.ndarray, forma) -> list[list[float]]:
    alto, ancho = forma
    return [[round(float(x) / ancho, 5), round(float(y) / alto, 5)] for x, y in quad]


def detectar_documento(
    bgr: np.ndarray,
    guia=None,
    ratio_objetivo: float | None = None,
    con_candidatos: bool = False,
) -> dict | None:
    """Busca el documento en la imagen.

    Parametros
    ----------
    guia : (x, y, ancho, alto) normalizados 0..1, el marco dibujado en la
        camara. Opcional; si se pasa, los candidatos de fuera pierden puntaje.
    ratio_objetivo : ancho/alto esperado del documento. Para A4 y A5 es el
        mismo valor, 1/raiz(2) = 0.7071 en vertical.
    con_candidatos : si es True, incluye en la respuesta los candidatos
        descartados con el motivo del rechazo (para la vista de diagnostico).

    Devuelve ``None`` si nada paso los filtros, o un dict con ``quad``
    (normalizado 0..1), ``quad_px``, ``area``, ``puntaje``, ``metodo``,
    ``componentes`` y opcionalmente ``candidatos``.
    """
    if bgr is None or bgr.size == 0:
        return None

    mapas = _preparar(bgr)
    candidatos = _fuentes_de_candidatos(mapas)[:MAXIMOS_CANDIDATOS]

    evaluados = [
        _evaluar(quad, mapas, metodo, guia, ratio_objetivo) for metodo, quad in candidatos
    ]
    evaluados.sort(key=lambda e: (e["aceptado"], e["puntaje"]), reverse=True)
    aceptados = [e for e in evaluados if e["aceptado"]]

    if con_candidatos:
        resumen_candidatos = [
            {
                "quad": _normalizar(e["quad_px"], mapas["forma"]),
                "puntaje": e["puntaje"],
                "metodo": e["metodo"],
                "area": e["area"],
                "rango_angular": e["rango_angular"],
                "aceptado": e["aceptado"],
                "rechazo": e["rechazo"],
                "componentes": e["componentes"],
            }
            for e in evaluados[:6]
        ]
    else:
        resumen_candidatos = None

    if not aceptados:
        if con_candidatos:
            return {"encontrado": False, "candidatos": resumen_candidatos}
        return None

    mejor = aceptados[0]
    salida = {
        "quad": _normalizar(mejor["quad_px"], mapas["forma"]),
        "quad_px": mejor["quad_px"],
        "area": mejor["area"],
        "puntaje": mejor["puntaje"],
        "metodo": mejor["metodo"],
        "rango_angular": mejor["rango_angular"],
        "componentes": mejor["componentes"],
        "papel_detalle": mejor["papel_detalle"],
    }
    if con_candidatos:
        salida["candidatos"] = resumen_candidatos
    return salida


def decodificar_jpeg(datos: bytes) -> np.ndarray | None:
    """Convierte bytes JPEG/PNG en una imagen BGR de OpenCV."""
    buffer = np.frombuffer(datos, dtype=np.uint8)
    if buffer.size == 0:
        return None
    return cv2.imdecode(buffer, cv2.IMREAD_COLOR)


def dibujar_diagnostico(bgr: np.ndarray, resultado: dict | None) -> np.ndarray:
    """Pinta los candidatos sobre la imagen, para inspeccion manual."""
    lienzo = bgr.copy()
    if resultado is None:
        cv2.putText(lienzo, "sin candidatos", (16, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        return lienzo

    alto, ancho = lienzo.shape[:2]
    for indice, candidato in enumerate(reversed(resultado.get("candidatos") or [])):
        puntos = np.array(
            [[x * ancho, y * alto] for x, y in candidato["quad"]], dtype=np.int32
        )
        aceptado = candidato["aceptado"]
        color = (0, 200, 0) if aceptado else (120, 120, 120)
        cv2.polylines(lienzo, [puntos], True, color, 3 if aceptado else 1)
        etiqueta = f"{candidato['puntaje']:.2f} {candidato['metodo']}"
        if candidato["rechazo"]:
            etiqueta += f" X{candidato['rechazo']}"
        cv2.putText(
            lienzo,
            etiqueta,
            tuple(puntos[0] + np.array([4, -6 - 18 * (indice % 3)])),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
        )
    return lienzo
