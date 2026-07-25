"""Resolucion contra los datos de referencia: distrito, establecimiento, catalogo.

Los tres cruces que la app necesita hacer contra el Dominio 2 viven aqui, en un
solo lugar, porque los usa tanto el servidor (`repositorio.py`) como la carga de
referencia (`herramientas/cargar_referencia.py`).

Regla que no se negocia: **en runtime todo es JOIN exacto**. El match difuso de
grafias de distrito se corrio una sola vez en el ETL del equipo y quedo
congelado en `alias_distrito`; aqui no hay similitud de cadenas. Si un texto no
resuelve, la respuesta es "no resuelve" y el dato crudo se conserva. Inventar un
distrito cambia el ajuste por altitud, y el ajuste cambia el diagnostico.
"""

from __future__ import annotations

import json
import re
import unicodedata

from . import catalogo

# Unidades que en realidad significan "no se sabe". No son compatibles con una
# unidad real: si el catalogo dice mg/dl y el documento no trae unidad, no hay
# forma de afirmar que hablan del mismo analito.
UNIDADES_VACIAS = {"", "-", "--", "sin_unidad", "sin unidad", "n/a", "na", "none"}


def normalizar_nombre(texto: str | None) -> str:
    """Forma canonica de un nombre: sin acentos, mayusculas, solo alfanumerico.

    Reproduce `nombre_normalizado` de la base validada del equipo, que es lo que
    permite cruzar el catalogo curado con lo que leyo el modelo:
    ``"Índice Col / HDL"`` -> ``"INDICE COL HDL"``.
    """
    if texto is None:
        return ""
    plano = "".join(
        c for c in unicodedata.normalize("NFD", str(texto))
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[^A-Za-z0-9]+", " ", plano).strip().upper()


def normalizar_unidad(unidad: str | None) -> str:
    """Unidad comparable: minusculas, sin espacios. Cadena vacia = desconocida."""
    texto = re.sub(r"\s+", "", str(unidad or "")).lower()
    return "" if texto in UNIDADES_VACIAS else texto


def unidades_compatibles(una: str | None, otra: str | None) -> bool:
    """True si las dos unidades son la misma. Desconocida no equivale a nada.

    Es el filtro que evita que la glucosa de una tira de orina (sin unidad) se
    enganche al catalogo de glucosa en sangre (mg/dl) y termine evaluada contra
    el rango equivocado.
    """
    izquierda = normalizar_unidad(una)
    derecha = normalizar_unidad(otra)
    return bool(izquierda) and izquierda == derecha


# ==========================================================================
# Distrito
# ==========================================================================

def resolver_distrito(
    conexion, texto: str | None, contexto: str | None = None
) -> tuple[str | None, list[str]]:
    """Devuelve ``(clave_norm, candidatos)`` para un nombre de distrito.

    `texto` es el nombre del distrito; `contexto` es el texto completo de donde
    salio (el membrete, por ejemplo), que se usa para desempatar cuando el
    nombre se repite en varios departamentos: hay cuatro Bellavista, y
    ``"Bellavista, Callao"`` resuelve al del Callao.

    - ``(clave, [])``  resolvio a un solo distrito.
    - ``(None, [...])`` ambiguo: la lista trae las claves candidatas.
    - ``(None, [])``   no existe en el padron.
    """
    nombre = normalizar_nombre(texto)
    if not nombre:
        return None, []

    # Ya viene como clave completa 'DEPARTAMENTO|PROVINCIA|DISTRITO'.
    if "|" in str(texto or ""):
        fila = conexion.execute(
            "SELECT clave_norm FROM distrito WHERE clave_norm = ?", (str(texto).strip().upper(),)
        ).fetchone()
        if fila:
            return fila["clave_norm"], []
        alias = conexion.execute(
            "SELECT clave_canonica FROM alias_distrito WHERE clave_origen = ?",
            (str(texto).strip().upper(),),
        ).fetchone()
        if alias and alias["clave_canonica"]:
            return alias["clave_canonica"], []
        return None, []

    candidatos = [
        dict(fila)
        for fila in conexion.execute(
            "SELECT clave_norm, departamento, provincia FROM distrito WHERE nombre = ?",
            (nombre,),
        )
    ]
    if not candidatos:
        return None, []
    if len(candidatos) == 1:
        return candidatos[0]["clave_norm"], []

    # Se desempata buscando el departamento o la provincia en el texto completo,
    # pero **sacando antes el nombre del distrito**: hay provincias que se llaman
    # igual que su distrito (San Martin|Bellavista|Bellavista), y sin quitarlo
    # esa provincia coincide con el propio nombre y el desempate no desempata.
    pista = normalizar_nombre(contexto or texto).replace(nombre, " ")
    filtrados = [
        c for c in candidatos
        if c["departamento"] in pista or c["provincia"] in pista
    ]
    if len(filtrados) == 1:
        return filtrados[0]["clave_norm"], []
    return None, [c["clave_norm"] for c in (filtrados or candidatos)]


def distritos_parecidos(conexion, texto: str | None, limite: int = 12) -> list[dict]:
    """Distritos cuyo nombre empieza con lo tecleado. Alimenta el buscador de la UI."""
    nombre = normalizar_nombre(texto)
    if len(nombre) < 2:
        return []
    filas = conexion.execute(
        """
        SELECT clave_norm, departamento, provincia, nombre, altitud_msnm
        FROM distrito
        WHERE nombre LIKE ? || '%'
        ORDER BY nombre, departamento, provincia
        LIMIT ?
        """,
        (nombre, limite),
    ).fetchall()
    return [dict(fila) for fila in filas]


# ==========================================================================
# Establecimiento de salud (RENIPRESS)
# ==========================================================================

def resolver_establecimiento(
    conexion, nombre: str | None, clave_norm: str | None
) -> dict | None:
    """Establecimiento del padron que coincide con el membrete, **dentro de un distrito**.

    El distrito es obligatorio a proposito. Buscar solo por nombre en un padron
    nacional de 26 798 establecimientos produce homonimos de otra region: en los
    escaneos de prueba, ``LABORATORIO CLINICO SAN MARTIN`` (Bellavista, Callao)
    coincidio exacto con un laboratorio del mismo nombre en Yurimaguas, Loreto.
    Guardar ese id habria puesto el documento en el distrito equivocado, y el
    distrito es lo que decide el ajuste por altitud.

    Por eso la ruta "inferir el distrito desde la institucion" que plantea el
    documento de diseno queda apagada hasta que el match use tambien la direccion
    o el codigo unico. Sin eso no es una inferencia: es una coincidencia de nombre.

    Si no coincide se devuelve None y el nombre crudo del membrete se guarda
    igual: **nunca** se descarta un documento por falta de match.
    """
    clave = normalizar_nombre(nombre)
    if not clave or not clave_norm:
        return None
    filas = conexion.execute(
        """
        SELECT id, nombre, clave_norm, institucion
        FROM establecimiento_salud
        WHERE nombre_normalizado = ? AND clave_norm = ?
        LIMIT 2
        """,
        (clave, clave_norm),
    ).fetchall()
    if len(filas) != 1:  # 0 = no esta; 2 = repetido en el mismo distrito
        return None
    return dict(filas[0])


def establecimientos_de_distrito(conexion, clave_norm: str, limite: int = 20) -> list[dict]:
    """Establecimientos del distrito. Cierra el ciclo: valor fuera de rango -> a donde ir."""
    if not clave_norm:
        return []
    filas = conexion.execute(
        """
        SELECT id, nombre, institucion, codigo_unico
        FROM establecimiento_salud
        WHERE clave_norm = ?
        ORDER BY institucion, nombre
        LIMIT ?
        """,
        (clave_norm, limite),
    ).fetchall()
    return [dict(fila) for fila in filas]


# ==========================================================================
# Catalogo de biomarcadores
# ==========================================================================

def buscar_en_catalogo(
    conexion, nombre: str, unidad: str | None, matriz: str | None = None
) -> dict | None:
    """Fila del catalogo curado que corresponde a lo que leyo el modelo.

    Empareja por nombre normalizado, por los sinonimos guardados en la fila, o
    por la tabla de etiquetas impresas de `catalogo.SINONIMOS` (`REACCION` es el
    pH urinario, `F. Cardiaca` es la Frecuencia Cardiaca, y asi).

    Desempate cuando el nombre calza con mas de una fila del catalogo
    -----------------------------------------------------------------
    `GLUCOSA`, `HEMATIES`, `DENSIDAD` o `PROTEINAS` existen en sangre y en orina,
    y son analitos distintos. El criterio, en orden:

    1. Si la unidad leida coincide con la del catalogo, gana esa fila. Es la
       senal mas fuerte: mg/dl es sangre, la tira de orina no trae unidad.
    2. Si no se conoce la unidad pero si la matriz del documento (deducida del
       conjunto de nombres del examen), **solo** valen las filas de esa matriz.
       Si ninguna calza, no hay match: la glucosa de una tira de orina no se
       engancha al catalogo de glucosa en sangre aunque sea la unica `GLUCOSA`
       que existe.
    3. Si no se conoce ni la unidad ni la matriz, se acepta solo cuando el nombre
       calza con una unica fila. Asi entran los que no son ambiguos y no traen
       unidad, como la frecuencia cardiaca.

    Devuelve None si no hay coincidencia segura: el llamador crea entonces una
    fila propia marcada como sin clasificar. Es preferible dejar un valor sin
    comparar que compararlo contra el rango de otro examen.
    """
    clave = normalizar_nombre(nombre)
    if not clave:
        return None
    equivalente = catalogo.canonico(nombre, matriz)

    filas = conexion.execute(
        """
        SELECT id, nombre, nombre_normalizado, matriz, categoria_examen,
               unidad_estandar, sinonimos
        FROM biomarcador
        WHERE matriz IS NOT NULL AND matriz <> 'sin_clasificar'
        """
    ).fetchall()

    candidatas = []
    for fila in filas:
        nombres = {fila["nombre_normalizado"] or normalizar_nombre(fila["nombre"])}
        try:
            nombres.update(normalizar_nombre(s) for s in json.loads(fila["sinonimos"] or "[]"))
        except (ValueError, TypeError):
            pass
        if clave in nombres or (equivalente and equivalente in nombres):
            candidatas.append(dict(fila))

    if not candidatas:
        return None

    por_unidad = [f for f in candidatas if unidades_compatibles(unidad, f["unidad_estandar"])]
    if por_unidad:
        return por_unidad[0]

    if matriz:
        # La matriz del documento manda: si el catalogo no tiene ese analito en
        # esta matriz, no hay equivalencia. Caer al unico candidato de otra
        # matriz seria comparar la orina contra el rango de la sangre.
        por_matriz = [f for f in candidatas if f["matriz"] == matriz]
        return por_matriz[0] if len(por_matriz) == 1 else None

    if len(candidatas) == 1:
        return candidatas[0]

    # Varias filas posibles y nada que las distinga: no se elige al azar.
    return None
