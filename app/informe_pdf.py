"""Genera el PDF de un documento escaneado: los datos, no la foto.

Que lleva
---------
La foto enderezada se puede bajar aparte; este PDF es el resultado del analisis
en forma legible e imprimible:

- membrete del establecimiento y fechas;
- una fila por biomarcador con el valor leido, el rango impreso en el papel y el
  rango de referencia (MINSA / OMS) que aplica a la persona;
- el estado de cada valor y el resumen de cuantos quedaron dentro, fuera y sin
  comparar;
- el descargo obligatorio: esto no es un diagnostico.

Decisiones
----------
- Se usan las fuentes base de PDF (Helvetica). Cubren el castellano con
  WinAnsiEncoding, asi que no hace falta empaquetar ningun TTF y el archivo pesa
  unos pocos KB.
- Los colores son los del sistema de diseno de Stitch, para que el PDF y la app
  se vean como lo mismo.
- El rango de referencia se resuelve con la misma logica que la vista Analisis
  (`comparativa`), no con una consulta propia: si un dia cambia el criterio,
  cambia en los dos lados a la vez.
"""

from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Paleta del DESIGN.md de Stitch
VERDE = colors.HexColor("#4d6700")
VERDE_SUAVE = colors.HexColor("#a7c957")
CREMA = colors.HexColor("#f8f5d7")
ROJO = colors.HexColor("#ba1a1a")
ROJO_SUAVE = colors.HexColor("#ffdad6")
GRIS = colors.HexColor("#444839")
GRIS_BORDE = colors.HexColor("#c5c9b4")
BLANCO_HUESO = colors.HexColor("#f8f9fa")

ETIQUETA_ESTADO = {
    "dentro": "Dentro de rango",
    "fuera": "FUERA DE RANGO",
    "sin_referencia": "Sin referencia",
    "sin_valor": "Sin valor",
}


def _estilos() -> dict:
    base = getSampleStyleSheet()
    return {
        "titulo": ParagraphStyle(
            "titulo", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=18, leading=22, textColor=VERDE, alignment=TA_LEFT, spaceAfter=2,
        ),
        "subtitulo": ParagraphStyle(
            "subtitulo", parent=base["Normal"], fontName="Helvetica",
            fontSize=10, leading=14, textColor=GRIS, spaceAfter=10,
        ),
        "seccion": ParagraphStyle(
            "seccion", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=12, leading=16, textColor=colors.HexColor("#191c1d"),
            spaceBefore=12, spaceAfter=6,
        ),
        "normal": ParagraphStyle(
            "cuerpo", parent=base["Normal"], fontName="Helvetica",
            fontSize=9, leading=12, textColor=colors.HexColor("#191c1d"),
        ),
        "celda": ParagraphStyle(
            "celda", parent=base["Normal"], fontName="Helvetica",
            fontSize=8, leading=10,
        ),
        "celda_negrita": ParagraphStyle(
            "celda_negrita", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=8, leading=10,
        ),
        "descargo": ParagraphStyle(
            "descargo", parent=base["Normal"], fontName="Helvetica-Oblique",
            fontSize=7.5, leading=10, textColor=GRIS,
        ),
    }


def _fecha_legible(iso: str | None) -> str:
    if not iso:
        return "no indicada"
    try:
        return datetime.fromisoformat(str(iso).replace(" ", "T")).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return str(iso)[:16]


def _referencias_por_biomarcador(documento_id: str) -> dict[str, dict]:
    """Rango de referencia y estado de cada biomarcador de este documento.

    Se toma de `comparativa`, que ya resuelve sexo, edad, condicion y altitud.

    El indice se arma con **todos** los nombres con los que se conoce a cada
    biomarcador: el del catalogo y sus sinonimos. El informe guarda el nombre tal
    como estaba impreso (`GLUCOSA BASAL, DOSAJE`) y el catalogo usa el normativo
    (`Glucosa`); buscando solo por el segundo, esas filas salian "sin comparar"
    aunque en la base si estuvieran enganchadas.

    Si algo falla, el PDF se genera igual sin la columna de referencia: vale mas
    entregar los datos leidos que no entregar nada.
    """
    try:
        import json as _json

        from . import basedatos, catalogo, comparativa

        analisis = comparativa.analisis_usuario()

        # nombre normalizado -> nombre del catalogo, incluyendo sinonimos
        alias: dict[str, str] = {}
        with basedatos.conectar() as conexion:
            for fila in conexion.execute("SELECT nombre, sinonimos FROM biomarcador"):
                alias[catalogo.normalizar(fila["nombre"])] = fila["nombre"]
                try:
                    for sinonimo in _json.loads(fila["sinonimos"] or "[]"):
                        alias.setdefault(catalogo.normalizar(str(sinonimo)), fila["nombre"])
                except (ValueError, TypeError):
                    pass
    except Exception:  # noqa: BLE001
        return {}

    por_catalogo: dict[str, dict] = {}
    for grupo in analisis.get("grupos", []):
        for biomarcador in grupo.get("biomarcadores", []):
            if not any(
                m.get("documento_id") == documento_id
                for m in biomarcador.get("historial", [])
            ):
                continue
            por_catalogo[biomarcador["nombre"]] = {
                "referencia": biomarcador.get("referencia"),
                "estado": biomarcador.get("estado"),
                "sistema": grupo.get("etiqueta"),
            }

    salida: dict[str, dict] = {}
    for normalizado, nombre_catalogo in alias.items():
        entrada = por_catalogo.get(nombre_catalogo)
        if entrada:
            salida[normalizado] = entrada
    return salida


def _texto_referencia(entrada: dict | None) -> str:
    if not entrada or not entrada.get("referencia"):
        return "sin rango cargado"
    referencia = entrada["referencia"]
    unidad = referencia.get("unidad") or ""
    fuente = referencia.get("fuente")
    fuente_texto = "" if not fuente or fuente == "POR_DEFINIR" else f"<br/>{fuente}"
    return f"{referencia['min']} a {referencia['max']} {unidad}{fuente_texto}"


def construir(informe: dict) -> bytes:
    """Arma el PDF de un informe y devuelve sus bytes."""
    estilos = _estilos()
    buffer = io.BytesIO()
    documento = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"LabLens - {informe.get('centro_medico') or 'Documento'}",
        author="LabLens",
    )

    partes = []
    partes.append(Paragraph("LabLens", estilos["titulo"]))
    partes.append(
        Paragraph(
            informe.get("centro_medico") or "Documento sin membrete", estilos["subtitulo"]
        )
    )

    # --- Datos del documento ---
    datos = [
        ["Fecha del documento", informe.get("fecha_documento") or "no indicada"],
        ["Escaneado el", _fecha_legible(informe.get("creado_en"))],
        ["Distrito", informe.get("ubicacion") or "no indicado"],
        ["Archivo de origen", informe.get("captura_archivo") or "-"],
        ["Lectura automatica", informe.get("modelo") or "-"],
    ]
    tabla_datos = Table(datos, colWidths=[38 * mm, None], hAlign="LEFT")
    tabla_datos.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 8),
                ("FONT", (1, 0), (1, -1), "Helvetica", 8),
                ("TEXTCOLOR", (0, 0), (0, -1), GRIS),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BACKGROUND", (0, 0), (-1, -1), BLANCO_HUESO),
                ("BOX", (0, 0), (-1, -1), 0.5, GRIS_BORDE),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, GRIS_BORDE),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    partes.append(tabla_datos)

    resultados = informe.get("resultados") or []
    referencias = _referencias_por_biomarcador(informe.get("id", ""))

    partes.append(Paragraph("Resultados", estilos["seccion"]))

    if not resultados:
        partes.append(
            Paragraph(
                "La lectura automatica no devolvio valores para este documento.",
                estilos["normal"],
            )
        )
    else:
        encabezado = [
            Paragraph(t, estilos["celda_negrita"])
            for t in ("Biomarcador", "Resultado", "Unidad", "Rango del documento",
                      "Rango de referencia", "Estado")
        ]
        filas = [encabezado]
        estilo_filas = []
        dentro = fuera = sin_comparar = 0

        from . import catalogo

        for indice, fila in enumerate(resultados, start=1):
            entrada = referencias.get(catalogo.normalizar(fila.get("biomarcador") or ""))
            estado = (entrada or {}).get("estado")
            if estado == "dentro":
                dentro += 1
            elif estado == "fuera":
                fuera += 1
            else:
                sin_comparar += 1

            filas.append(
                [
                    Paragraph(str(fila.get("biomarcador") or ""), estilos["celda"]),
                    Paragraph(str(fila.get("valor_texto") or "-"), estilos["celda_negrita"]),
                    Paragraph(str(fila.get("unidad") or ""), estilos["celda"]),
                    Paragraph(str(fila.get("rango_texto") or "-"), estilos["celda"]),
                    Paragraph(_texto_referencia(entrada), estilos["celda"]),
                    Paragraph(ETIQUETA_ESTADO.get(estado, "Sin comparar"), estilos["celda"]),
                ]
            )
            if estado == "fuera":
                estilo_filas.append(("BACKGROUND", (0, indice), (-1, indice), ROJO_SUAVE))
                estilo_filas.append(("TEXTCOLOR", (5, indice), (5, indice), ROJO))
            elif estado == "dentro":
                estilo_filas.append(("TEXTCOLOR", (5, indice), (5, indice), VERDE))

        tabla = Table(
            filas,
            colWidths=[42 * mm, 20 * mm, 16 * mm, 30 * mm, 34 * mm, 25 * mm],
            repeatRows=1,
            hAlign="LEFT",
        )
        tabla.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), VERDE_SUAVE),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOX", (0, 0), (-1, -1), 0.5, GRIS_BORDE),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, GRIS_BORDE),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    *estilo_filas,
                ]
            )
        )
        partes.append(tabla)

        partes.append(Spacer(1, 8))
        resumen = (
            f"<b>{len(resultados)}</b> biomarcadores leidos &nbsp;|&nbsp; "
            f"<font color='#4d6700'><b>{dentro}</b> dentro de rango</font> &nbsp;|&nbsp; "
            f"<font color='#ba1a1a'><b>{fuera}</b> fuera de rango</font> &nbsp;|&nbsp; "
            f"<b>{sin_comparar}</b> sin rango con el que comparar"
        )
        partes.append(Paragraph(resumen, estilos["normal"]))

    partes.append(Spacer(1, 14))
    partes.append(
        Paragraph(
            "Los valores de este informe provienen de la lectura automatica de una "
            "fotografia del documento original y pueden contener errores: "
            "verifiquelos contra el papel antes de tomar cualquier decision. "
            "La comparacion con rangos de referencia es un indice orientativo de "
            "seguimiento y no constituye un diagnostico medico ni reemplaza la "
            "consulta con un profesional de la salud.",
            estilos["descargo"],
        )
    )
    partes.append(Spacer(1, 6))
    partes.append(
        Paragraph(
            f"Generado por LabLens el {datetime.now():%d/%m/%Y %H:%M}.",
            estilos["descargo"],
        )
    )

    documento.build(partes)
    return buffer.getvalue()


def nombre_archivo(informe: dict) -> str:
    """Nombre del PDF: mismo patron que la captura, con extension .pdf."""
    base = informe.get("captura_archivo") or f"{informe.get('id', 'informe')}.jpg"
    if base.lower().endswith(".jpg"):
        base = base[:-4]
    return f"{base}_DATOS.pdf"
