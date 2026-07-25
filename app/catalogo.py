"""Emparejamiento entre lo que lee Gemma y el catalogo curado de biomarcadores.

El problema que resuelve
------------------------
El modelo devuelve el nombre tal como esta impreso en el papel: `REACCION`,
`F. Cardiaca`, `GLUCOSA BASAL, DOSAJE`, `Sat O2`, `HEMATES`. El catalogo curado
usa el nombre normativo: `pH`, `Frecuencia Cardiaca`, `Glucosa`, `Saturación O2`,
`Hematíes`. Sin emparejarlos, cada escaneo creaba un biomarcador nuevo con
`sistema_corporal = 'sin_clasificar'`, que por definicion no tiene rango de
referencia: los valores del usuario **nunca** llegaban a compararse.

La matriz importa
-----------------
`GLUCOSA` en un examen de orina no es la glucosa en sangre: la primera es
cualitativa (NEGATIVO) y la segunda se mide en mg/dL y tiene rango. Lo mismo con
`HEMATIES` (recuento en sangre vs sedimento urinario) y `DENSIDAD`. Por eso el
emparejamiento se restringe a la matriz del documento, que se deduce del conjunto
de nombres que trae ese examen. Si la matriz no calza, no se empareja: es
preferible dejar el valor sin clasificar que compararlo contra el rango
equivocado.
"""

from __future__ import annotations

import re
import unicodedata

# Nombres que delatan de que tipo de examen es el documento. Se cuentan las
# coincidencias y gana la matriz con mas aciertos.
PISTAS_MATRIZ: dict[str, tuple[str, ...]] = {
    "orina": (
        "VOLUMEN", "DENSIDAD", "ASPECTO", "COLOR", "REACCION", "CILINDROS",
        "CRISTALES", "NITRITOS", "UROBILINA", "CUERPOS CETONICOS", "PIOCITOS",
        "CELULAS EPITELIALES", "GERMENES", "P BILIARES", "PIGMENTOS BILIARES",
        "LEUCOCITOS AISLADOS", "LEUCOCITOS AGLUTINADOS", "AC ASCORBICO",
        "SEDIMENTO URINARIO", "EXAMEN DE ORINA",
    ),
    "sangre": (
        "HEMOGLOBINA", "HEMATOCRITO", "PLAQUETAS", "LINFOCITOS", "SEGMENTADOS",
        "MONOCITOS", "EOSINOFILOS", "BASOFILOS", "COLESTEROL", "TRIGLICERIDOS",
        "UREA", "CREATININA", "FERRITINA", "RDW", "VCM", "HCM", "CHCM",
        "HDL", "LDL", "TSH", "GLUCOSA BASAL", "GLUCOSA EN AYUNAS", "GLICEMIA",
    ),
    "clinico": (
        "IMC", "PESO", "TALLA", "PERIMETRO ABDOMINAL", "P ABDOMINAL",
        "PRESION SISTOLICA", "PRESION DIASTOLICA", "PRESION ARTERIAL",
        "FRECUENCIA CARDIACA", "F CARDIACA", "FRECUENCIA RESPIRATORIA",
        "F RESPIRATORIA", "SATURACION O2", "SAT O2", "TEMPERATURA",
        "GRASA CORPORAL",
    ),
}

# Como se escribe en los informes -> como se llama en el catalogo.
# La segunda posicion es la matriz en la que vale ese sinonimo; None = cualquiera.
# Solo se agregan equivalencias que son ciertas por definicion, no parecidos.
SINONIMOS: dict[str, tuple[str, str | None]] = {
    # Orina: "reaccion" es como los laboratorios peruanos rotulan el pH
    "REACCION": ("PH", "orina"),
    "REACCION PH": ("PH", "orina"),
    # Sangre
    "HB": ("HEMOGLOBINA", "sangre"),
    "HGB": ("HEMOGLOBINA", "sangre"),
    "HEMOGLOBINA GR": ("HEMOGLOBINA", "sangre"),
    "HTO": ("HEMATOCRITO", "sangre"),
    "HEMATES": ("HEMATIES", "sangre"),          # falta la i acentuada al leer
    "GLOBULOS ROJOS": ("HEMATIES", "sangre"),
    "ERITROCITOS": ("HEMATIES", "sangre"),
    "GLOBULOS BLANCOS": ("LEUCOCITOS", "sangre"),
    "RECUENTO DE LEUCOCITOS": ("LEUCOCITOS", "sangre"),
    "VCM": ("VOLUMEN CORPUSCULAR MEDIO", "sangre"),
    "HCM": ("HEMOGLOBINA CORPUSCULAR MEDIA", "sangre"),
    "CHCM": ("CONCENTRACION HB CORPUSCULAR MEDIA", "sangre"),
    "VPM": ("VOLUMEN PLAQUETARIO MEDIO", "sangre"),
    "GLUCOSA EN AYUNAS": ("GLUCOSA", "sangre"),
    "GLUCOSA BASAL": ("GLUCOSA", "sangre"),
    "GLUCOSA BASAL DOSAJE": ("GLUCOSA", "sangre"),
    "GLICEMIA": ("GLUCOSA", "sangre"),
    "GLICEMIA BASAL": ("GLUCOSA", "sangre"),
    "COLESTEROL": ("COLESTEROL TOTAL", "sangre"),
    "COLESTEROL SERICO": ("COLESTEROL TOTAL", "sangre"),
    "HDL": ("HDL COLESTEROL", "sangre"),
    "COLESTEROL HDL": ("HDL COLESTEROL", "sangre"),
    "LDL": ("LDL COLESTEROL", "sangre"),
    "COLESTEROL LDL": ("LDL COLESTEROL", "sangre"),
    "TRIGLICERIDOS SERICOS": ("TRIGLICERIDOS", "sangre"),
    "FERRITINA": ("FERRITINA SERICA", "sangre"),
    # Signos vitales y antropometria
    "F CARDIACA": ("FRECUENCIA CARDIACA", "clinico"),
    "FC": ("FRECUENCIA CARDIACA", "clinico"),
    "PULSO": ("FRECUENCIA CARDIACA", "clinico"),
    "F RESPIRATORIA": ("FRECUENCIA RESPIRATORIA", "clinico"),
    "FR": ("FRECUENCIA RESPIRATORIA", "clinico"),
    "SAT O2": ("SATURACION O2", "clinico"),
    "SATO2": ("SATURACION O2", "clinico"),
    "SPO2": ("SATURACION O2", "clinico"),
    "SATURACION DE OXIGENO": ("SATURACION O2", "clinico"),
    "P ABDOMINAL": ("PERIMETRO ABDOMINAL", "clinico"),
    "PERIMETRO DE CINTURA": ("PERIMETRO ABDOMINAL", "clinico"),
    "CIRCUNFERENCIA ABDOMINAL": ("PERIMETRO ABDOMINAL", "clinico"),
    "PAS": ("PRESION SISTOLICA", "clinico"),
    "PA SISTOLICA": ("PRESION SISTOLICA", "clinico"),
    "PRESION ARTERIAL SISTOLICA": ("PRESION SISTOLICA", "clinico"),
    "PAD": ("PRESION DIASTOLICA", "clinico"),
    "PA DIASTOLICA": ("PRESION DIASTOLICA", "clinico"),
    "PRESION ARTERIAL DIASTOLICA": ("PRESION DIASTOLICA", "clinico"),
    "INDICE DE MASA CORPORAL": ("IMC", "clinico"),
    "PORCENTAJE DE GRASA CORPORAL": ("DE GRASA CORPORAL", "clinico"),
    "GRASA CORPORAL": ("DE GRASA CORPORAL", "clinico"),
}


def normalizar(nombre: str) -> str:
    """Deja el nombre en la forma de `biomarcador.nombre_normalizado`.

    Mayusculas, sin acentos, sin puntuacion y con los espacios colapsados.
    ``"Ac. Ascórbico"`` -> ``"AC ASCORBICO"``.
    """
    if not nombre:
        return ""
    plano = unicodedata.normalize("NFD", str(nombre))
    plano = "".join(c for c in plano if unicodedata.category(c) != "Mn")
    plano = re.sub(r"[^A-Za-z0-9]+", " ", plano)
    return re.sub(r"\s+", " ", plano).strip().upper()


def inferir_matriz(nombres: list[str]) -> str | None:
    """Deduce si el documento es de orina, sangre o clinico por sus nombres.

    Devuelve None si ninguna pista aparece: sin matriz no se empareja nada, que
    es preferible a adivinar y comparar contra el rango de otro examen.
    """
    normalizados = [normalizar(n) for n in nombres if n]
    puntajes = {}
    for matriz, pistas in PISTAS_MATRIZ.items():
        puntajes[matriz] = sum(
            1 for pista in pistas if any(pista in nombre for nombre in normalizados)
        )
    mejor = max(puntajes, key=lambda m: puntajes[m])
    if puntajes[mejor] == 0:
        return None
    # Un empate no decide: se prefiere no clasificar antes que elegir al azar.
    segundos = sorted(puntajes.values(), reverse=True)
    if len(segundos) > 1 and segundos[0] == segundos[1]:
        return None
    return mejor


def canonico(nombre: str, matriz: str | None) -> str | None:
    """Nombre normativo equivalente a la etiqueta impresa, o None si no hay.

    ``"Reacción"`` en un examen de orina -> ``"PH"``. Si la equivalencia solo
    vale en cierta matriz y el documento es de otra, no se aplica.
    """
    equivalencia = SINONIMOS.get(normalizar(nombre))
    if not equivalencia:
        return None
    destino, matriz_valida = equivalencia
    if matriz_valida is None or matriz is None or matriz_valida == matriz:
        return destino
    return None
