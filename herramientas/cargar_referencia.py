"""Carga en la base de la app los datos de referencia validados por el equipo.

Origen: `BasedeDatos_Preparada/qhali.db` (Qhali v1.0, ETL reproducible del
equipo, documentado en `BasedeDatos_Preparada/qhali-base-final-v1.md`).
Destino: `datos/qhali.sqlite3`, la base que usa el servidor.

    .\\.venv\\Scripts\\python.exe herramientas\\cargar_referencia.py

Que hace
--------
1. Respalda la base actual en `datos/respaldos/` (copia consistente, aunque el
   servidor este corriendo).
2. Amplia el esquema a la v1.0 (`basedatos.inicializar`).
3. Recarga **todas** las tablas de referencia desde la base validada. Es
   idempotente: borra y vuelve a escribir, asi que correrla dos veces deja el
   mismo resultado.
4. Fusiona el catalogo curado con los biomarcadores que el scanner habia
   descubierto solo (ver `_cargar_biomarcadores`).
5. Vuelve a enganchar el dominio del usuario: distrito de residencia,
   establecimiento del documento y ajuste por altitud.
6. Verifica que no queden claves ajenas huerfanas y reporta.

Lo que NO hace: tocar el archivo del equipo. Se abre en modo solo lectura.

Lo que queda vacio a proposito: `peso_ponderacion`, porque sin cita normativa el
peso no entra, y `umbral_desviacion`, que es de la v0.1 y la v1.0 reemplaza por
`umbral_alerta`.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app import basedatos, referencia, repositorio  # noqa: E402
from app.esquema import distrito_probable  # noqa: E402

RUTA_VALIDADA = RAIZ / "BasedeDatos_Preparada" / "qhali.db"
DIR_RESPALDOS = RAIZ / "datos" / "respaldos"

# Orden de borrado: primero quien referencia, despues el referenciado. Se corre
# con las claves ajenas apagadas, pero el orden se respeta igual para que el
# script siga siendo correcto si algun dia se encienden.
TABLAS_A_RECARGAR = (
    "registro_rechazado",
    "ingesta_lote",
    "rango_referencia",
    "umbral_alerta",
    "peso_ponderacion",
    "ajuste_altitud",
    "codigo_cie10",
    "alias_distrito",
    "establecimiento_salud",
    "distrito",
    "fuente_referencia",
    "parametro_calculo",
    "factor_severidad",
)

# La v0.1 guardaba la edad en anios y la v1.0 la guarda en dias, que es lo que la
# NTS 213 necesita para estratificar neonatos por semanas. Las columnas viejas se
# dejan en NULL a proposito: un tramo de "6 a 23 meses" no se puede escribir en
# anios enteros sin mentir. Quien consulta usa edad_min_dias / edad_max_dias.
SEXO_LEGADO = {"femenino": "F", "masculino": "M"}


# ==========================================================================
# Apertura y respaldo
# ==========================================================================

def abrir_validada(ruta: Path) -> sqlite3.Connection:
    """Base del equipo en solo lectura: este script nunca la modifica."""
    if not ruta.exists():
        raise SystemExit(f"No se encontro la base validada: {ruta}")
    conexion = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    conexion.row_factory = sqlite3.Row
    return conexion


def respaldar() -> Path | None:
    """Copia consistente de la base actual. Devuelve None si todavia no existe.

    Usa la API de respaldo de SQLite y no una copia de archivo, porque con
    journal WAL el .sqlite3 suelto puede quedar sin los ultimos cambios.
    """
    if not basedatos.RUTA_BASE.exists():
        return None
    DIR_RESPALDOS.mkdir(parents=True, exist_ok=True)
    destino = DIR_RESPALDOS / f"qhali_{datetime.now():%Y-%m-%d_%H%M%S}.sqlite3"
    origen = sqlite3.connect(basedatos.RUTA_BASE, timeout=15)
    copia = sqlite3.connect(destino)
    try:
        with copia:
            origen.backup(copia)
    finally:
        copia.close()
        origen.close()
    return destino


def _columnas_utiles(conexion, tabla: str, datos: dict) -> dict:
    """Filtra un dict de valores a las columnas que la tabla realmente tiene."""
    existentes = basedatos.columnas(conexion, tabla)
    return {k: v for k, v in datos.items() if k in existentes}


def _insertar(conexion, tabla: str, filas: list[dict]) -> int:
    if not filas:
        return 0
    columnas = list(filas[0])
    marcadores = ", ".join("?" for _ in columnas)
    sentencia = (
        f"INSERT INTO {tabla} ({', '.join(columnas)}) VALUES ({marcadores})"
    )
    conexion.executemany(sentencia, [[fila[c] for c in columnas] for fila in filas])
    return len(filas)


# ==========================================================================
# Catalogo de biomarcadores: fusion con lo que el scanner descubrio solo
# ==========================================================================

def _cargar_biomarcadores(destino, validada) -> tuple[dict[int, int], list[str]]:
    """Deja el catalogo curado en la base y devuelve ``(mapa_ids, sin_curar)``.

    `biomarcador` es la unica tabla de referencia que no se puede borrar y
    recargar: sus ids ya estan referenciados por los 90 valores que el scanner
    guardo, y los ids de la base validada son otros. Asi que se fusiona.

    Para cada fila curada se busca una fila descubierta por el scanner que
    coincida en nombre normalizado **y** unidad. Si coincide, esa fila se
    actualiza con los atributos curados: los valores que ya apuntaban ahi quedan
    enganchados al catalogo sin tocar `valor_extraido`. Si no coincide, la fila
    curada entra nueva.

    La unidad es parte del criterio a proposito. `Hematies` con unidad `/campo`
    es sedimento urinario y no el hematie del hemograma (`X10^6/uL`); `Glucosa`
    sin unidad viene de una tira reactiva de orina y no de la glucosa en sangre
    (`mg/dl`). Fusionarlos por nombre los pondria a evaluarse contra el rango
    equivocado, que es justo el error que este proyecto existe para evitar.

    Las filas del scanner que no coinciden con nada quedan con
    ``matriz = 'sin_clasificar'``, listas para curar a mano.
    """
    mapa: dict[int, int] = {}

    vivos = [
        dict(fila)
        for fila in destino.execute(
            "SELECT id, nombre, nombre_normalizado, matriz, unidad_estandar FROM biomarcador"
        )
    ]

    for curado in validada.execute("SELECT * FROM biomarcador ORDER BY id"):
        curado = dict(curado)
        # La v0.1 exige sistema_corporal NOT NULL; la v1.0 lo parte en matriz +
        # categoria_examen. Se refleja la categoria para que la vista Analisis,
        # que agrupa por sistema_corporal, siga agrupando con sentido.
        campos = {
            "nombre": curado["nombre"],
            "nombre_normalizado": curado["nombre_normalizado"],
            "matriz": curado["matriz"],
            "categoria_examen": curado["categoria_examen"],
            "sistema_corporal": curado["categoria_examen"],
            "unidad_estandar": curado["unidad_estandar"],
            "direccionalidad": curado["direccionalidad"],
            "derivado": curado["derivado"],
            "origen_dato": curado["origen_dato"],
            "codigo_cpms": curado["codigo_cpms"],
            "sinonimos": curado["sinonimos"],
        }
        campos = _columnas_utiles(destino, "biomarcador", campos)

        # 1) Ya cargado en una corrida anterior: se actualiza en su lugar.
        objetivo = next(
            (
                v["id"] for v in vivos
                if v["nombre_normalizado"] == curado["nombre_normalizado"]
                and v["matriz"] == curado["matriz"]
            ),
            None,
        )
        # 2) Fila que el scanner descubrio y que corresponde a esta: se fusiona.
        if objetivo is None:
            objetivo = next(
                (
                    v["id"] for v in vivos
                    if v["matriz"] in (None, "sin_clasificar")
                    and referencia.normalizar_nombre(v["nombre"]) == curado["nombre_normalizado"]
                    and referencia.unidades_compatibles(
                        v["unidad_estandar"], curado["unidad_estandar"]
                    )
                ),
                None,
            )

        if objetivo is None:  # 3) No estaba: entra nueva.
            cursor = destino.execute(
                f"INSERT INTO biomarcador ({', '.join(campos)}) "
                f"VALUES ({', '.join('?' for _ in campos)})",
                list(campos.values()),
            )
            objetivo = int(cursor.lastrowid)
            vivos.append(
                {
                    "id": objetivo,
                    "nombre": curado["nombre"],
                    "nombre_normalizado": curado["nombre_normalizado"],
                    "matriz": curado["matriz"],
                    "unidad_estandar": curado["unidad_estandar"],
                }
            )
        else:
            asignaciones = ", ".join(f"{c} = ?" for c in campos)
            destino.execute(
                f"UPDATE biomarcador SET {asignaciones} WHERE id = ?",
                [*campos.values(), objetivo],
            )
            for v in vivos:
                if v["id"] == objetivo:
                    v.update(
                        nombre=curado["nombre"],
                        nombre_normalizado=curado["nombre_normalizado"],
                        matriz=curado["matriz"],
                        unidad_estandar=curado["unidad_estandar"],
                    )
        mapa[curado["id"]] = objetivo

    # Lo que el scanner descubrio y nadie curo: se marca para que se distinga.
    sin_curar = []
    for fila in destino.execute(
        "SELECT id, nombre, unidad_estandar FROM biomarcador "
        "WHERE matriz IS NULL OR matriz = 'sin_clasificar' ORDER BY id"
    ).fetchall():
        destino.execute(
            """
            UPDATE biomarcador
               SET nombre_normalizado = ?, matriz = 'sin_clasificar',
                   categoria_examen = 'sin_clasificar', sistema_corporal = 'sin_clasificar'
             WHERE id = ?
            """,
            (referencia.normalizar_nombre(fila["nombre"]), fila["id"]),
        )
        sin_curar.append(f"{fila['nombre']} ({fila['unidad_estandar']})")

    return mapa, sin_curar


# ==========================================================================
# Tablas de referencia
# ==========================================================================

def _cargar_referencia(destino, validada, mapa_bio: dict[int, int]) -> dict[str, int]:
    """Recarga las tablas de referencia. Devuelve cuantas filas entraron en cada una."""
    conteos: dict[str, int] = {}

    # --- Fuentes. El `nombre` de la v0.1 se llena con el organismo para que las
    # consultas ya escritas sigan funcionando; la cita y la prioridad son v1.0.
    filas = []
    for f in validada.execute("SELECT * FROM fuente_referencia ORDER BY id"):
        filas.append(
            _columnas_utiles(destino, "fuente_referencia", {
                "id": f["id"],
                "nombre": f["organismo"],
                "organismo": f["organismo"],
                "dataset": f["dataset"],
                "cita": f["cita"],
                "url_origen": f["url_origen"],
                "fecha_snapshot": f["fecha_snapshot"],
                "prioridad": f["prioridad"],
                "version": f["version"],
            })
        )
    conteos["fuente_referencia"] = _insertar(destino, "fuente_referencia", filas)

    # --- Geografia.
    conteos["distrito"] = _insertar(destino, "distrito", [
        _columnas_utiles(destino, "distrito", dict(f))
        for f in validada.execute("SELECT * FROM distrito ORDER BY clave_norm")
    ])
    conteos["alias_distrito"] = _insertar(destino, "alias_distrito", [
        _columnas_utiles(destino, "alias_distrito", dict(f))
        for f in validada.execute("SELECT * FROM alias_distrito ORDER BY clave_origen")
    ])

    # --- Padron RENIPRESS. `distrito` (texto, v0.1) se llena con el nombre que
    # sale de la clave; `categoria` queda NULL porque la fuente no la trae.
    filas = []
    for f in validada.execute("SELECT * FROM establecimiento_salud ORDER BY id"):
        filas.append(
            _columnas_utiles(destino, "establecimiento_salud", {
                "id": f["id"],
                "fuente_id": f["fuente_id"],
                "nombre": f["nombre"],
                "categoria": None,
                "distrito": f["clave_norm"].split("|")[-1],
                "lat": None,
                "lng": None,
                "version": f["version"],
                "codigo_unico": f["codigo_unico"],
                "institucion": f["institucion"],
                "nombre_normalizado": f["nombre_normalizado"],
                "clave_norm": f["clave_norm"],
            })
        )
    conteos["establecimiento_salud"] = _insertar(destino, "establecimiento_salud", filas)

    # --- Rangos de referencia.
    filas = []
    for f in validada.execute("SELECT * FROM rango_referencia ORDER BY id"):
        filas.append(
            _columnas_utiles(destino, "rango_referencia", {
                "id": f["id"],
                "fuente_id": f["fuente_id"],
                "biomarcador_id": mapa_bio[f["biomarcador_id"]],
                "sexo": f["sexo"],
                "edad_min": None,   # ver nota de SEXO_LEGADO: la edad vive en dias
                "edad_max": None,
                "valor_min": f["valor_min"],
                "valor_max": f["valor_max"],
                "unidad": f["unidad"],
                "clasificacion": f["clasificacion"],
                "version": f["version"],
                "condicion": f["condicion"],
                "edad_min_dias": f["edad_min_dias"],
                "edad_max_dias": f["edad_max_dias"],
                "tipo_limite": f["tipo_limite"],
                "altitud_max_aplicable": f["altitud_max_aplicable"],
            })
        )
    conteos["rango_referencia"] = _insertar(destino, "rango_referencia", filas)

    # --- Umbrales de alerta y ajuste por altitud.
    for tabla in ("umbral_alerta", "ajuste_altitud", "peso_ponderacion"):
        filas = []
        for f in validada.execute(f"SELECT * FROM {tabla} ORDER BY id"):
            fila = dict(f)
            fila["biomarcador_id"] = mapa_bio[fila["biomarcador_id"]]
            filas.append(_columnas_utiles(destino, tabla, fila))
        conteos[tabla] = _insertar(destino, tabla, filas)

    # --- Tablas que se copian tal cual.
    for tabla, orden in (
        ("codigo_cie10", "codigo"),
        ("parametro_calculo", "id"),
        ("factor_severidad", "id"),
        ("ingesta_lote", "id"),
        ("registro_rechazado", "id"),
    ):
        conteos[tabla] = _insertar(destino, tabla, [
            _columnas_utiles(destino, tabla, dict(f))
            for f in validada.execute(f"SELECT * FROM {tabla} ORDER BY {orden}")
        ])

    return conteos


# ==========================================================================
# Reenganche del dominio del usuario
# ==========================================================================

def _enganchar_usuarios(destino) -> list[str]:
    """Normaliza el sexo y resuelve el distrito de residencia de cada usuario."""
    avisos = []
    for fila in destino.execute("SELECT * FROM usuario").fetchall():
        sexo = SEXO_LEGADO.get(str(fila["sexo"]).strip().lower(), fila["sexo"])
        clave, candidatos = referencia.resolver_distrito(destino, fila["distrito_residencia"])
        destino.execute(
            "UPDATE usuario SET sexo = ?, clave_distrito_residencia = ? WHERE id = ?",
            (sexo, clave, fila["id"]),
        )
        if fila["distrito_residencia"] and clave is None:
            avisos.append(
                f"usuario {fila['id']}: distrito '{fila['distrito_residencia']}' "
                + (f"es ambiguo ({len(candidatos)} coincidencias)" if candidatos
                   else "no esta en el padron")
                + " - queda sin ajuste por altitud"
            )
    return avisos


def _enganchar_documentos(destino) -> dict[str, int]:
    """Resuelve el distrito y la institucion de cada documento ya guardado.

    El orden es distrito primero, institucion despues: el establecimiento se
    busca **dentro** del distrito que salio del membrete, nunca al reves (ver
    `referencia.resolver_establecimiento`). El texto crudo del membrete no se
    toca nunca.
    """
    conteo = {"con_institucion": 0, "por_texto": 0, "sin_distrito": 0}
    for fila in destino.execute("SELECT * FROM documento").fetchall():
        crudo = fila["distrito"]
        clave, _ = referencia.resolver_distrito(destino, distrito_probable(crudo), crudo)
        establecimiento = referencia.resolver_establecimiento(
            destino, fila["institucion_nombre"], clave
        )

        destino.execute(
            """
            UPDATE documento
               SET institucion_id = ?, clave_norm = ?, distrito_confianza = ?
             WHERE id = ?
            """,
            (
                establecimiento["id"] if establecimiento else None,
                clave,
                "extraido" if clave else "no_disponible",
                fila["id"],
            ),
        )
        if clave:
            conteo["por_texto"] += 1
        else:
            conteo["sin_distrito"] += 1
        if establecimiento:
            conteo["con_institucion"] += 1
    return conteo


# ==========================================================================
# Programa
# ==========================================================================

def cargar(ruta_validada: Path = RUTA_VALIDADA, con_respaldo: bool = True) -> dict:
    basedatos.inicializar()
    respaldo = respaldar() if con_respaldo else None

    validada = abrir_validada(ruta_validada)
    destino = sqlite3.connect(basedatos.RUTA_BASE, timeout=30)
    destino.row_factory = sqlite3.Row
    # Apagadas durante la recarga: borrar `distrito` con usuarios apuntando ahi
    # fallaria aunque despues se vuelva a escribir la misma clave. Al final se
    # verifica con foreign_key_check, que es mas confiable que el orden.
    destino.execute("PRAGMA foreign_keys = OFF")
    try:
        with destino:
            for tabla in TABLAS_A_RECARGAR:
                destino.execute(f"DELETE FROM {tabla}")
            mapa_bio, sin_curar = _cargar_biomarcadores(destino, validada)
            conteos = _cargar_referencia(destino, validada, mapa_bio)
            avisos = _enganchar_usuarios(destino)
            documentos = _enganchar_documentos(destino)
            # Misma funcion que usa el servidor al guardar una captura: el ajuste
            # se calcula en un solo lugar.
            ajustados = repositorio.aplicar_ajuste_altitud(destino)
            huerfanos = [dict(f) for f in destino.execute("PRAGMA foreign_key_check")]
    finally:
        destino.close()
        validada.close()

    fallidos = basedatos.crear_indices_unicos()

    return {
        "respaldo": str(respaldo) if respaldo else None,
        "conteos": conteos,
        "biomarcadores_sin_curar": sin_curar,
        "avisos": avisos,
        "documentos": documentos,
        "valores_ajustados": ajustados,
        "claves_huerfanas": huerfanos,
        "indices_no_creados": fallidos,
    }


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument(
        "--validada", type=Path, default=RUTA_VALIDADA,
        help="ruta de la base validada de origen",
    )
    analizador.add_argument(
        "--sin-respaldo", action="store_true",
        help="no respaldar antes de cargar (no recomendado)",
    )
    argumentos = analizador.parse_args()

    reporte = cargar(argumentos.validada, con_respaldo=not argumentos.sin_respaldo)

    print(f"Origen : {argumentos.validada}")
    print(f"Destino: {basedatos.RUTA_BASE}")
    if reporte["respaldo"]:
        print(f"Respaldo: {reporte['respaldo']}")
    print()
    print("Filas cargadas por tabla")
    for tabla, n in reporte["conteos"].items():
        print(f"  {tabla:24} {n:7}")

    estado = basedatos.estado()
    print()
    print(f"Tablas en la base: {estado['tablas']}")
    print("  del usuario:", ", ".join(f"{k}={v}" for k, v in estado["activas"].items()))
    print("  pendientes :", ", ".join(f"{k}={v}" for k, v in estado["pendientes"].items()))

    print()
    print("Dominio del usuario reenganchado")
    print(f"  documentos con distrito del membrete   : {reporte['documentos']['por_texto']}")
    print(f"  documentos con establecimiento del padron: {reporte['documentos']['con_institucion']}")
    print(f"  documentos sin distrito                : {reporte['documentos']['sin_distrito']}")
    print(f"  valores con ajuste por altitud         : {reporte['valores_ajustados']}")

    if reporte["avisos"]:
        print()
        print("Avisos")
        for aviso in reporte["avisos"]:
            print(f"  - {aviso}")

    if reporte["biomarcadores_sin_curar"]:
        print()
        print(
            f"Biomarcadores del scanner sin curar ({len(reporte['biomarcadores_sin_curar'])}): "
            "no coincidieron con el catalogo en nombre y unidad."
        )
        for nombre in reporte["biomarcadores_sin_curar"]:
            print(f"  - {nombre}")

    if reporte["indices_no_creados"]:
        print()
        print("Indices UNIQUE que no se pudieron crear:")
        for detalle in reporte["indices_no_creados"]:
            print(f"  - {detalle}")

    if reporte["claves_huerfanas"]:
        print()
        print(f"ERROR: {len(reporte['claves_huerfanas'])} claves ajenas huerfanas")
        for fila in reporte["claves_huerfanas"][:10]:
            print(f"  - {fila}")
        return 1

    print()
    print("Sin claves ajenas huerfanas. Carga completa.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
