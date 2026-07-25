"""Persistencia de los informes extraidos en la base Qhali.

Dos destinos por cada informe:

1. **SQLite** (`datos/qhali.sqlite3`), con el esquema de
   `qhali-estructura-base-datos.md`. Es la fuente para consultar.
2. **JSON de auditoria** (`capturas/informes/<id>.json`), con todo lo que
   devolvio el modelo mas lo que se parseo. Es el respaldo si un INSERT falla y
   la fuente para reprocesar sin volver a llamar al modelo.

Mapeo scanner + Gemma -> tablas
-------------------------------
| Origen | Destino |
|---|---|
| `captura.id` | `documento.id` |
| ruta del JPEG enderezado | `documento.archivo_ruta` |
| `informacion_general.centro_medico` | `documento.institucion_nombre` (siempre se guarda) |
| `informacion_general.ubicacion` | `documento.distrito` + `distrito_confianza='extraido'` |
| un `estudio` por documento | `categoria='sin_clasificar'` |
| cada `resultados[]` | una fila de `valor_extraido` |
| `biomarcador` del resultado | se resuelve o se crea en `biomarcador` |

Decisiones que conviene conocer
-------------------------------
- `documento.institucion_id` queda NULL: el match difuso contra RENIPRESS
  necesita `establecimiento_salud`, que es Dominio 2 y esta pendiente. La regla
  del documento de diseno se respeta: nunca se descarta un documento por falta
  de match, y el nombre crudo siempre se guarda.
- `valor_extraido.confianza_extraccion` queda NULL. El servicio no devuelve una
  confianza por valor, y poner un numero inventado en un dato de salud seria
  peor que dejarlo vacio.
- El rango de referencia **impreso en el documento** no tiene columna en
  `valor_extraido`. Se conserva en el JSON de auditoria (`rango_texto`,
  `limite_inferior`, `limite_superior`). Ver la nota en HISTORY.md: hace falta
  decidir si se agrega una columna o si se descarta en favor de
  `rango_referencia` de la OMS.
- Reprocesar una captura borra sus `estudio` y `valor_extraido` anteriores, para
  no duplicar filas.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from . import basedatos
from .almacenamiento import DIR_CAPTURAS
from .esquema import Informe, clave_biomarcador, distrito_probable

DIR_INFORMES = DIR_CAPTURAS / "informes"
REGISTRO_INFORMES = DIR_INFORMES / "registro.jsonl"

# Un solo usuario local por instalacion, como plantea el documento de diseno
# ("un archivo unico por usuario").
ID_USUARIO_LOCAL = "usuario-local"

SEXOS_VALIDOS = ("femenino", "masculino", "otro", "no_especificado")


def asegurar_directorios() -> None:
    DIR_INFORMES.mkdir(parents=True, exist_ok=True)


# ==========================================================================
# Usuario local (Dominio 1). Sin PII: solo lo que exigen los rangos.
# ==========================================================================

def usuario_local() -> dict | None:
    """Devuelve el usuario local, o None si todavia no se configuro."""
    with basedatos.conectar() as conexion:
        fila = conexion.execute(
            "SELECT * FROM usuario WHERE id = ?", (ID_USUARIO_LOCAL,)
        ).fetchone()
    return dict(fila) if fila else None


def guardar_usuario(
    fecha_nacimiento: str, sexo: str, distrito_residencia: str | None = None
) -> dict:
    """Crea o actualiza el usuario local.

    `fecha_nacimiento` y `sexo` son obligatorios porque los rangos de referencia
    de la OMS dependen de edad y sexo. No se guarda ningun nombre.
    """
    if sexo not in SEXOS_VALIDOS:
        raise ValueError(f"sexo debe ser uno de {SEXOS_VALIDOS}")
    if not fecha_nacimiento:
        raise ValueError("fecha_nacimiento es obligatoria")

    with basedatos.conectar() as conexion:
        conexion.execute(
            """
            INSERT INTO usuario (id, fecha_nacimiento, sexo, distrito_residencia)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                fecha_nacimiento = excluded.fecha_nacimiento,
                sexo = excluded.sexo,
                distrito_residencia = excluded.distrito_residencia
            """,
            (ID_USUARIO_LOCAL, fecha_nacimiento, sexo, distrito_residencia or None),
        )
    return usuario_local()  # type: ignore[return-value]


# ==========================================================================
# Biomarcadores (Dominio 3, poblado sobre la marcha por necesidad de la FK)
# ==========================================================================

def resolver_biomarcador(conexion, nombre: str, unidad: str | None) -> int:
    """Devuelve el id del biomarcador, creandolo si no existe.

    Busca por la clave normalizada contra `nombre` y contra cada entrada de
    `sinonimos`. La tabla tiene decenas de filas, asi que un recorrido completo
    es mas claro que inventar un indice sobre el JSON.

    Los que se crean aqui llevan ``sistema_corporal = 'sin_clasificar'``: es la
    marca de que nadie los curo todavia. Quien complete el Dominio 3 puede
    encontrarlos con:

        SELECT * FROM biomarcador WHERE sistema_corporal = 'sin_clasificar';
    """
    clave = clave_biomarcador(nombre)
    for fila in conexion.execute("SELECT id, nombre, sinonimos FROM biomarcador"):
        if clave_biomarcador(fila["nombre"]) == clave:
            return fila["id"]
        try:
            sinonimos = json.loads(fila["sinonimos"] or "[]")
        except json.JSONDecodeError:
            sinonimos = []
        if any(clave_biomarcador(str(s)) == clave for s in sinonimos):
            return fila["id"]

    cursor = conexion.execute(
        """
        INSERT INTO biomarcador (nombre, sistema_corporal, unidad_estandar, sinonimos)
        VALUES (?, 'sin_clasificar', ?, ?)
        """,
        (nombre, unidad or "sin_unidad", json.dumps([clave], ensure_ascii=False)),
    )
    return int(cursor.lastrowid)


# ==========================================================================
# Guardado del informe
# ==========================================================================

def _ruta_json(informe_id: str) -> Path:
    # Nunca se arma una ruta con texto de afuera sin filtrar.
    seguro = "".join(c for c in informe_id if c.isalnum() or c in "-_")
    return DIR_INFORMES / f"{seguro}.json"


def _guardar_json(informe: Informe) -> Path:
    asegurar_directorios()
    datos = informe.a_dict()
    ruta = _ruta_json(informe.id)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")

    resumen = {
        "id": informe.id,
        "captura_archivo": informe.captura_archivo,
        "creado_en": informe.creado_en,
        "estado": informe.estado,
        "institucion_nombre": informe.centro_medico,
        "total_resultados": datos["total_resultados"],
        "fuera_de_rango": datos["fuera_de_rango"],
    }
    with REGISTRO_INFORMES.open("a", encoding="utf-8") as archivo:
        archivo.write(json.dumps(resumen, ensure_ascii=False) + "\n")
    return ruta


def _guardar_en_bd(informe: Informe) -> dict:
    """Inserta el documento, su estudio y sus valores. Todo en una transaccion."""
    usuario = usuario_local()
    if usuario is None:
        return {
            "guardado": False,
            "motivo": "sin_usuario_local",
            "mensaje": (
                "Falta configurar el usuario local (fecha de nacimiento y sexo). "
                "El informe quedo guardado en JSON y se puede reprocesar despues."
            ),
        }

    # El modelo devuelve el membrete completo; en `distrito` solo debe ir el
    # distrito. El texto integro queda en el JSON de auditoria.
    distrito = distrito_probable(informe.ubicacion)
    conexion = basedatos.conectar()
    try:
        with conexion:  # transaccion: o entra todo, o no entra nada
            # Reprocesar: se limpian los valores y estudios anteriores.
            conexion.execute(
                """
                DELETE FROM valor_extraido
                WHERE estudio_id IN (SELECT id FROM estudio WHERE documento_id = ?)
                """,
                (informe.id,),
            )
            conexion.execute("DELETE FROM estudio WHERE documento_id = ?", (informe.id,))

            conexion.execute(
                """
                INSERT INTO documento (
                    id, usuario_id, tipo, fuente_obtencion, institucion_nombre,
                    institucion_id, distrito, distrito_confianza, fecha_documento,
                    archivo_ruta, estado_extraccion
                ) VALUES (?, ?, 'laboratorio', 'foto', ?, NULL, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    institucion_nombre = excluded.institucion_nombre,
                    distrito = excluded.distrito,
                    distrito_confianza = excluded.distrito_confianza,
                    fecha_documento = excluded.fecha_documento,
                    archivo_ruta = excluded.archivo_ruta,
                    estado_extraccion = excluded.estado_extraccion
                """,
                (
                    informe.id,
                    usuario["id"],
                    informe.centro_medico,
                    distrito,
                    "extraido" if distrito else "no_disponible",
                    informe.fecha_documento,
                    f"capturas/{informe.captura_archivo}",
                    "procesado" if informe.estado == "ok" else "error",
                ),
            )

            if not informe.resultados:
                return {
                    "guardado": True,
                    "documento_id": informe.id,
                    "estudio_id": None,
                    "valores": 0,
                    "biomarcadores_nuevos": 0,
                    "mensaje": "Documento registrado sin valores: el modelo no devolvio resultados.",
                }

            estudio_id = str(uuid.uuid4())
            conexion.execute(
                """
                INSERT INTO estudio (id, documento_id, categoria, nombre_estudio)
                VALUES (?, ?, 'sin_clasificar', 'Analisis de laboratorio')
                """,
                (estudio_id, informe.id),
            )

            antes = conexion.execute("SELECT COUNT(*) AS n FROM biomarcador").fetchone()["n"]
            for resultado in informe.resultados:
                biomarcador_id = resolver_biomarcador(
                    conexion, resultado.biomarcador, resultado.unidad
                )
                conexion.execute(
                    """
                    INSERT INTO valor_extraido (
                        id, estudio_id, biomarcador_id, valor_numerico, unidad,
                        valor_crudo_texto, confianza_extraccion
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        str(uuid.uuid4()),
                        estudio_id,
                        biomarcador_id,
                        resultado.valor_numerico,
                        resultado.unidad,
                        resultado.valor_texto or "N/A",
                    ),
                )
            despues = conexion.execute("SELECT COUNT(*) AS n FROM biomarcador").fetchone()["n"]

        return {
            "guardado": True,
            "documento_id": informe.id,
            "estudio_id": estudio_id,
            "valores": len(informe.resultados),
            "biomarcadores_nuevos": despues - antes,
        }
    finally:
        conexion.close()


def guardar(informe: Informe) -> dict:
    """Persiste el informe: primero el JSON, despues la base.

    El JSON va primero a proposito: si el INSERT falla, el trabajo del modelo no
    se pierde y la captura se puede reprocesar sin volver a pagar la llamada.
    """
    ruta_json = _guardar_json(informe)
    try:
        resultado_bd = _guardar_en_bd(informe)
    except Exception as error:  # noqa: BLE001 - el JSON ya esta a salvo
        resultado_bd = {
            "guardado": False,
            "motivo": "error_bd",
            "mensaje": f"{type(error).__name__}: {error}",
        }
    return {"json": str(ruta_json), "base_de_datos": resultado_bd}


# ==========================================================================
# Consultas
# ==========================================================================

def obtener(informe_id: str) -> dict | None:
    """Informe completo desde el JSON de auditoria, o None si no existe."""
    ruta = _ruta_json(informe_id)
    if not ruta.exists():
        return None
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def listar(limite: int = 30) -> list[dict]:
    """Documentos guardados en la base, del mas reciente al mas antiguo."""
    with basedatos.conectar() as conexion:
        filas = conexion.execute(
            """
            SELECT d.id, d.institucion_nombre, d.distrito, d.distrito_confianza,
                   d.fecha_documento, d.fecha_carga, d.estado_extraccion,
                   d.archivo_ruta,
                   (SELECT COUNT(*) FROM valor_extraido v
                      JOIN estudio e ON e.id = v.estudio_id
                     WHERE e.documento_id = d.id) AS total_valores
            FROM documento d
            ORDER BY d.fecha_carga DESC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()
    return [dict(fila) for fila in filas]


def valores_de_documento(documento_id: str) -> list[dict]:
    """Valores extraidos de un documento, con el nombre del biomarcador."""
    with basedatos.conectar() as conexion:
        filas = conexion.execute(
            """
            SELECT v.id, b.nombre AS biomarcador, b.sistema_corporal,
                   v.valor_numerico, v.unidad, v.valor_crudo_texto,
                   v.confianza_extraccion
            FROM valor_extraido v
            JOIN estudio e ON e.id = v.estudio_id
            JOIN biomarcador b ON b.id = v.biomarcador_id
            WHERE e.documento_id = ?
            ORDER BY v.rowid
            """,
            (documento_id,),
        ).fetchall()
    return [dict(fila) for fila in filas]
