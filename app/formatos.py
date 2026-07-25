"""Formatos de documento soportados por el marco guia de la camara.

Cada formato define la relacion ancho/alto que se dibuja como guia en la
camara y a la que se ajusta la imagen enderezada.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Formato:
    clave: str
    etiqueta: str
    ratio: float  # ancho / alto


# A4 y A5 comparten exactamente la misma proporcion, 1:raiz(2). Por eso un solo
# formato cubre ambos tamanos y sirve como pista fuerte para el detector.
FORMATOS = {
    f.clave: f
    for f in (
        Formato("a4_vertical", "A4 / A5 vertical (1:1.41)", 210 / 297),
        Formato("a4_horizontal", "A4 / A5 horizontal (1.41:1)", 297 / 210),
        Formato("carta_vertical", "Carta vertical (216x279)", 216 / 279),
        Formato("carta_horizontal", "Carta horizontal (279x216)", 279 / 216),
        Formato("ticket", "Ticket / tira de resultados", 80 / 200),
        Formato("tarjeta", "Carnet o tarjeta (85x54)", 85.6 / 53.98),
        Formato("libre", "Libre (sin ajuste)", 0.0),
    )
}

FORMATO_POR_DEFECTO = "a4_vertical"


def obtener(clave: str | None) -> Formato:
    """Devuelve el formato pedido o el formato por defecto si no existe."""
    return FORMATOS.get(clave or "", FORMATOS[FORMATO_POR_DEFECTO])


def listar() -> list[dict]:
    """Lista serializable de formatos para el frontend."""
    return [
        {"clave": f.clave, "etiqueta": f.etiqueta, "ratio": f.ratio}
        for f in FORMATOS.values()
    ]
