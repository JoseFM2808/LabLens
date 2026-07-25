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

from . import basedatos, catalogo, referencia
from .almacenamiento import DIR_CAPTURAS
from .esquema import Informe, clave_biomarcador, distrito_probable

DIR_INFORMES = DIR_CAPTURAS / "informes"
REGISTRO_INFORMES = DIR_INFORMES / "registro.jsonl"

# Un solo usuario local por instalacion, como plantea el documento de diseno
# ("un archivo unico por usuario").
ID_USUARIO_LOCAL = "usuario-local"

# 'F' y 'M' no son un capricho de formato: es el valor con el que la NTS 213
# estratifica los rangos en `rango_referencia.sexo`. Guardar "femenino" hacia que
# ningun rango por sexo calzara y la app se quedaba sin poder evaluar nada.
# 'otro' y 'no_especificado' se conservan como respuesta legitima: con ellos solo
# aplican los rangos que no distinguen sexo, que es lo correcto y no un vacio.
SEXOS_VALIDOS = ("F", "M", "otro", "no_especificado")
SEXOS_LEGADO = {"femenino": "F", "masculino": "M"}

# Condiciones de `rango_referencia.condicion` que aplican a una persona adulta.
# 'general' es el valor por defecto y nunca se asume otro: decir "no gestante" es
# una afirmacion clinica que solo la usuaria puede hacer.
# Nombre legible del estudio segun la matriz deducida del documento.
CATEGORIA_ESTUDIO = {
    "orina": "Examen completo de orina",
    "sangre": "Analisis de sangre",
    "clinico": "Control clinico",
}

CONDICIONES_VALIDAS = (
    "general",
    "no_gestante",
    "gestante_t1",
    "gestante_t2",
    "gestante_t3",
    "puerpera",
)


def asegurar_directorios() -> None:
    DIR_INFORMES.mkdir(parents=True, exist_ok=True)


# ==========================================================================
# Usuario local (Dominio 1). Sin PII: solo lo que exigen los rangos.
# ==========================================================================

def usuario_local() -> dict | None:
    """Devuelve el perfil activo, o None si todavia no se configuro ninguno.

    Se llama "local" por historia: ahora puede haber varios perfiles en la misma
    instalacion y este devuelve el que esta en uso (ver `app/perfiles.py`).
    """
    from . import perfiles  # import diferido: perfiles usa guardar_usuario

    with basedatos.conectar() as conexion:
        fila = conexion.execute(
            "SELECT * FROM usuario WHERE id = ?", (perfiles.id_activo(),)
        ).fetchone()
    return dict(fila) if fila else None


def guardar_usuario(
    fecha_nacimiento: str,
    sexo: str,
    distrito_residencia: str | None = None,
    condicion: str = "general",
    residencia_desde: str | None = None,
    usuario_id: str | None = None,
) -> dict:
    """Crea o actualiza el usuario local.

    `fecha_nacimiento` y `sexo` son obligatorios porque los rangos de referencia
    dependen de edad y sexo. No se guarda ningun nombre.

    El distrito se guarda dos veces a proposito: el texto tal como lo escribio la
    persona (`distrito_residencia`) y la clave del padron
    (`clave_distrito_residencia`), que es la que trae la altitud y habilita el
    ajuste de la NTS 213. Si el texto no resuelve a un solo distrito, se levanta
    ValueError con los candidatos: es la persona la que elige, no el programa.
    """
    from . import perfiles  # import diferido

    # Sin `usuario_id` se edita el perfil activo; con el, se crea o edita ese.
    destino = usuario_id or perfiles.id_activo()

    sexo = SEXOS_LEGADO.get(str(sexo).strip().lower(), str(sexo).strip())
    if sexo not in SEXOS_VALIDOS:
        raise ValueError(f"sexo debe ser uno de {SEXOS_VALIDOS}")
    if condicion not in CONDICIONES_VALIDAS:
        raise ValueError(f"condicion debe ser una de {CONDICIONES_VALIDAS}")
    if not fecha_nacimiento:
        raise ValueError("fecha_nacimiento es obligatoria")

    texto_distrito = (distrito_residencia or "").strip() or None
    with basedatos.conectar() as conexion:
        clave = None
        if texto_distrito:
            clave, candidatos = referencia.resolver_distrito(conexion, texto_distrito)
            if clave is None and candidatos:
                raise ValueError(
                    f"'{texto_distrito}' existe en varios departamentos. "
                    "Indique cual: " + ", ".join(candidatos)
                )
            if clave is None:
                raise ValueError(
                    f"'{texto_distrito}' no esta en el padron de distritos. "
                    "Reviselo o dejelo vacio."
                )
            # La interfaz manda la clave completa cuando la persona elige de la
            # lista ('PASCO|PASCO|CHAUPIMARCA'). Para mostrar se guarda el nombre
            # del padron, que es el mismo dato sin la parte tecnica.
            fila = conexion.execute(
                "SELECT nombre FROM distrito WHERE clave_norm = ?", (clave,)
            ).fetchone()
            if fila:
                texto_distrito = fila["nombre"]

        conexion.execute(
            """
            INSERT INTO usuario (
                id, fecha_nacimiento, sexo, distrito_residencia, condicion,
                clave_distrito_residencia, residencia_desde
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                fecha_nacimiento = excluded.fecha_nacimiento,
                sexo = excluded.sexo,
                distrito_residencia = excluded.distrito_residencia,
                condicion = excluded.condicion,
                clave_distrito_residencia = excluded.clave_distrito_residencia,
                residencia_desde = excluded.residencia_desde
            """,
            (
                destino,
                fecha_nacimiento,
                sexo,
                texto_distrito,
                condicion,
                clave,
                (residencia_desde or "").strip() or None,
            ),
        )
        fila = conexion.execute("SELECT * FROM usuario WHERE id = ?", (destino,)).fetchone()
    return dict(fila) if fila else {}


# ==========================================================================
# Biomarcadores (Dominio 3, poblado sobre la marcha por necesidad de la FK)
# ==========================================================================

def resolver_biomarcador(
    conexion, nombre: str, unidad: str | None, matriz: str | None = None
) -> int:
    """Devuelve el id del biomarcador, creandolo si no existe.

    Tres intentos, en este orden:

    1. **Catalogo curado** (`referencia.buscar_en_catalogo`): coincide el nombre
       normalizado o un sinonimo **y** la unidad. Solo asi el valor entra con
       rango de referencia, ajuste por altitud y cita normativa.
    2. **Lo que el scanner ya habia descubierto**: coincide el nombre, sin exigir
       unidad, porque esas filas las creo este mismo codigo con este mismo nombre.
    3. **Fila nueva** marcada ``sin_clasificar``, que es la marca de que nadie la
       curo todavia:

           SELECT * FROM biomarcador WHERE matriz = 'sin_clasificar';

    La unidad se exige en el paso 1 y no en el 2 a proposito. El catalogo tiene
    `Glucosa` en sangre (mg/dl) y el scanner lee `Glucosa` de una tira de orina
    sin unidad: son dos analitos distintos y engancharlos haria que la orina se
    evalue contra el rango de la sangre.
    """
    curado = referencia.buscar_en_catalogo(conexion, nombre, unidad, matriz)
    if curado:
        return int(curado["id"])

    clave = clave_biomarcador(nombre)
    for fila in conexion.execute(
        "SELECT id, nombre, sinonimos FROM biomarcador "
        "WHERE matriz IS NULL OR matriz = 'sin_clasificar'"
    ):
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
        INSERT INTO biomarcador (
            nombre, sistema_corporal, unidad_estandar, sinonimos,
            nombre_normalizado, matriz, categoria_examen
        ) VALUES (?, 'sin_clasificar', ?, ?, ?, 'sin_clasificar', 'sin_clasificar')
        """,
        (
            nombre,
            unidad or "sin_unidad",
            json.dumps([clave], ensure_ascii=False),
            referencia.normalizar_nombre(nombre),
        ),
    )
    return int(cursor.lastrowid)


# ==========================================================================
# Ajuste por altitud (NTS 213 Tabla N.1)
# ==========================================================================

def aplicar_ajuste_altitud(conexion, estudio_id: str | None = None) -> int:
    """Escribe `valor_ajustado` y `ajuste_id` en los valores que lo necesitan.

    El factor se decide por la **altitud del distrito de residencia** del usuario
    (NTS 213 §5.3.2), no por donde se hizo el analisis, y se **resta** al valor
    observado (Tabla N.1, columna "Disminuir"). `valor_numerico` no se toca nunca:
    el valor que decia el papel tiene que seguir siendo auditable.

    Sin distrito, sin altitud o por debajo de 500 msnm no hay tramo que aplicar y
    las dos columnas quedan en NULL, que es lo que la interfaz lee para declarar
    que no se pudo ajustar.

    Con `estudio_id` recalcula solo ese estudio; sin el, todos. Devuelve cuantos
    valores quedaron con ajuste.
    """
    filtro = "AND estudio_id = ?" if estudio_id else ""
    parametros = (estudio_id,) if estudio_id else ()

    conexion.execute(
        f"UPDATE valor_extraido SET valor_ajustado = NULL, ajuste_id = NULL "
        f"WHERE 1 = 1 {filtro}",
        parametros,
    )
    conexion.execute(
        f"""
        UPDATE valor_extraido
           SET ajuste_id = (
                   SELECT a.id
                     FROM estudio e
                     JOIN documento d ON d.id = e.documento_id
                     JOIN usuario u   ON u.id = d.usuario_id
                     JOIN distrito g  ON g.clave_norm = u.clave_distrito_residencia
                     JOIN ajuste_altitud a
                          ON a.biomarcador_id = valor_extraido.biomarcador_id
                         AND a.factor_ajuste > 0
                         AND g.altitud_msnm BETWEEN a.altitud_min_msnm AND a.altitud_max_msnm
                    WHERE e.id = valor_extraido.estudio_id
               )
         WHERE valor_numerico IS NOT NULL {filtro}
        """,
        parametros,
    )
    conexion.execute(
        f"""
        UPDATE valor_extraido
           SET valor_ajustado = ROUND(
                   valor_numerico - (SELECT factor_ajuste FROM ajuste_altitud
                                      WHERE id = valor_extraido.ajuste_id), 2)
         WHERE ajuste_id IS NOT NULL {filtro}
        """,
        parametros,
    )
    return conexion.execute(
        f"SELECT COUNT(*) AS n FROM valor_extraido WHERE ajuste_id IS NOT NULL {filtro}",
        parametros,
    ).fetchone()["n"]


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
        # Distrito primero y establecimiento despues, buscado dentro de ese
        # distrito: al reves, un nombre repetido en otra region mete el documento
        # en el distrito equivocado. Ver referencia.resolver_establecimiento.
        clave_norm, _ = referencia.resolver_distrito(conexion, distrito, informe.ubicacion)
        establecimiento = referencia.resolver_establecimiento(
            conexion, informe.centro_medico, clave_norm
        )

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
                    institucion_id, distrito, clave_norm, distrito_confianza,
                    fecha_documento, archivo_ruta, estado_extraccion
                ) VALUES (?, ?, 'laboratorio', 'foto', ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    institucion_nombre = excluded.institucion_nombre,
                    institucion_id = excluded.institucion_id,
                    distrito = excluded.distrito,
                    clave_norm = excluded.clave_norm,
                    distrito_confianza = excluded.distrito_confianza,
                    fecha_documento = excluded.fecha_documento,
                    archivo_ruta = excluded.archivo_ruta,
                    estado_extraccion = excluded.estado_extraccion
                """,
                (
                    informe.id,
                    usuario["id"],
                    informe.centro_medico,
                    establecimiento["id"] if establecimiento else None,
                    distrito,
                    clave_norm,
                    "extraido" if clave_norm else "no_disponible",
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

            # La matriz se deduce una vez, del conjunto de nombres del examen:
            # con VOLUMEN / DENSIDAD / ASPECTO es orina, con HEMOGLOBINA /
            # PLAQUETAS es sangre. Sirve para desempatar los nombres que existen
            # en las dos (GLUCOSA, HEMATIES) cuando el valor no trae unidad.
            matriz_documento = catalogo.inferir_matriz(
                [r.biomarcador for r in informe.resultados]
            )

            estudio_id = str(uuid.uuid4())
            conexion.execute(
                """
                INSERT INTO estudio (id, documento_id, categoria, nombre_estudio)
                VALUES (?, ?, ?, ?)
                """,
                (
                    estudio_id,
                    informe.id,
                    matriz_documento or "sin_clasificar",
                    CATEGORIA_ESTUDIO.get(matriz_documento, "Analisis de laboratorio"),
                ),
            )

            antes = conexion.execute("SELECT COUNT(*) AS n FROM biomarcador").fetchone()["n"]
            for resultado in informe.resultados:
                biomarcador_id = resolver_biomarcador(
                    conexion, resultado.biomarcador, resultado.unidad, matriz_documento
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
            ajustados = aplicar_ajuste_altitud(conexion, estudio_id)

        return {
            "guardado": True,
            "documento_id": informe.id,
            "estudio_id": estudio_id,
            "valores": len(informe.resultados),
            "biomarcadores_nuevos": despues - antes,
            "valores_ajustados_por_altitud": ajustados,
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


def listar(limite: int = 30, usuario_id: str | None = None) -> list[dict]:
    """Documentos del perfil activo, del mas reciente al mas antiguo.

    El filtro por perfil no es cosmetico: sin el, al cambiar de perfil la
    pantalla Documentos seguia mostrando los escaneos de la otra persona.
    """
    from . import perfiles  # import diferido

    usuario_id = usuario_id or perfiles.id_activo()
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
            WHERE d.usuario_id = ?
            ORDER BY d.fecha_carga DESC
            LIMIT ?
            """,
            (usuario_id, limite),
        ).fetchall()
    return [dict(fila) for fila in filas]


def borrar_documento(documento_id: str) -> dict:
    """Elimina un documento por completo: filas de la base y archivos.

    Se borra todo, no solo las filas: la persona que elimina un documento medico
    espera que desaparezca, y dejar el JPEG y el JSON en disco haria que
    "eliminar" fuera mentira. Se quitan:

    - `valor_extraido`, `estudio` y `documento` de la base;
    - el JPEG enderezado y la foto original de `capturas/`;
    - el JSON de auditoria de `capturas/informes/`;
    - la linea correspondiente de `registro.jsonl`.

    Es irreversible. La confirmacion la pide la interfaz, no este modulo.

    Devuelve el detalle de lo borrado. Si el documento no existe levanta
    ValueError, para que la ruta pueda responder 404.
    """
    from .almacenamiento import DIR_CAPTURAS as _DIR, DIR_ORIGINALES, REGISTRO

    conexion = basedatos.conectar()
    try:
        fila = conexion.execute(
            "SELECT archivo_ruta FROM documento WHERE id = ?", (documento_id,)
        ).fetchone()
        if fila is None:
            raise ValueError(f"el documento '{documento_id}' no existe")
        archivo = Path(fila["archivo_ruta"]).name if fila["archivo_ruta"] else None

        with conexion:
            valores = conexion.execute(
                """
                DELETE FROM valor_extraido
                WHERE estudio_id IN (SELECT id FROM estudio WHERE documento_id = ?)
                """,
                (documento_id,),
            ).rowcount
            estudios = conexion.execute(
                "DELETE FROM estudio WHERE documento_id = ?", (documento_id,)
            ).rowcount
            conexion.execute("DELETE FROM documento WHERE id = ?", (documento_id,))
    finally:
        conexion.close()

    archivos = []
    for ruta in (
        _DIR / archivo if archivo else None,
        DIR_ORIGINALES / archivo if archivo else None,
        _ruta_json(documento_id),
    ):
        if ruta and ruta.exists():
            try:
                ruta.unlink()
                archivos.append(ruta.name)
            except OSError:
                pass  # el archivo queda, pero la base ya no lo referencia

    # Los registros son append-only: para quitar una linea hay que reescribirlos.
    # Hay dos y los dos guardan el id, asi que se limpian ambos: `capturas/
    # registro.jsonl` (una linea por captura) y `capturas/informes/registro.jsonl`
    # (una linea por informe extraido). Limpiar solo uno dejaba el documento
    # apareciendo en `/api/capturas`.
    for registro in (REGISTRO, REGISTRO_INFORMES):
        if not registro.exists():
            continue
        try:
            lineas = [
                linea for linea in registro.read_text(encoding="utf-8").splitlines() if linea.strip()
            ]
            quedan = []
            for linea in lineas:
                try:
                    if json.loads(linea).get("id") == documento_id:
                        continue
                except json.JSONDecodeError:
                    pass  # linea ilegible: se conserva, no se pierde informacion
                quedan.append(linea)
            if len(quedan) != len(lineas):
                registro.write_text(
                    "\n".join(quedan) + ("\n" if quedan else ""), encoding="utf-8"
                )
        except OSError:
            pass

    return {
        "documento": documento_id,
        "valores": valores,
        "estudios": estudios,
        "archivos": archivos,
    }


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
