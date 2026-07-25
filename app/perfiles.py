"""Perfiles locales: varios usuarios en la misma instalacion, uno activo.

Por que existe
--------------
La tabla `usuario` siempre admitio varias filas, pero el codigo asumia una sola
(`ID_USUARIO_LOCAL`). Con eso no se podia empezar de cero sin borrar lo anterior:
los documentos de prueba quedaban mezclados con los reales.

Sobre el nombre y la regla de cero PII
-------------------------------------
El diseno es explicito: *"cero PII, el sistema no almacena nombres"*, y por eso
`usuario` no tiene columna de nombre. Aqui se agrega `etiqueta`, que es una
**etiqueta local para distinguir perfiles en este dispositivo**, no la identidad
del paciente:

- no se usa en ninguna consulta clinica ni entra en la comparacion con rangos;
- no viaja al modelo de vision ni al asistente;
- no aparece en el PDF del informe;
- es opcional: un perfil sin etiqueta funciona igual.

Si el criterio del equipo es que ni eso debe guardarse, se borra la columna y los
perfiles se distinguen por fecha de creacion, sin tocar nada mas.

El perfil activo se guarda en `parametro_calculo`, que es la tabla de
configuracion del sistema. Asi no hace falta otra tabla ni estado en memoria.
"""

from __future__ import annotations

import re
import unicodedata

from . import basedatos

CLAVE_PERFIL_ACTIVO = "perfil_activo"
ID_POR_DEFECTO = "usuario-local"


def asegurar_esquema() -> None:
    """Agrega la columna `etiqueta` si falta. Idempotente."""
    with basedatos.conectar() as conexion:
        columnas = {f["name"] for f in conexion.execute("PRAGMA table_info(usuario)")}
        if "etiqueta" not in columnas:
            conexion.execute("ALTER TABLE usuario ADD COLUMN etiqueta TEXT")


def _slug(texto: str) -> str:
    plano = unicodedata.normalize("NFD", texto or "")
    plano = "".join(c for c in plano if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", "-", plano).strip("-") or "perfil"


def _id_libre(conexion, base: str) -> str:
    """Id derivado de la etiqueta, con sufijo si ya existe."""
    candidato = _slug(base)
    existentes = {f["id"] for f in conexion.execute("SELECT id FROM usuario")}
    if candidato not in existentes:
        return candidato
    for numero in range(2, 100):
        alterno = f"{candidato}-{numero}"
        if alterno not in existentes:
            return alterno
    raise ValueError("demasiados perfiles con la misma etiqueta")


def id_activo() -> str:
    """Perfil activo. Si no hay marca, cae al que exista, priorizando el original."""
    with basedatos.conectar() as conexion:
        fila = conexion.execute(
            "SELECT valor FROM parametro_calculo WHERE clave = ?", (CLAVE_PERFIL_ACTIVO,)
        ).fetchone()
        if fila:
            existe = conexion.execute(
                "SELECT 1 FROM usuario WHERE id = ?", (fila["valor"],)
            ).fetchone()
            if existe:
                return fila["valor"]

        # Sin marca valida: el original si esta, y si no el primero por antiguedad.
        fila = conexion.execute(
            "SELECT id FROM usuario WHERE id = ?", (ID_POR_DEFECTO,)
        ).fetchone()
        if fila:
            return fila["id"]
        fila = conexion.execute(
            "SELECT id FROM usuario ORDER BY creado_en LIMIT 1"
        ).fetchone()
        return fila["id"] if fila else ID_POR_DEFECTO


def activar(perfil_id: str) -> bool:
    """Marca un perfil como activo. False si el perfil no existe."""
    with basedatos.conectar() as conexion:
        if not conexion.execute("SELECT 1 FROM usuario WHERE id = ?", (perfil_id,)).fetchone():
            return False
        conexion.execute(
            """
            INSERT INTO parametro_calculo (clave, valor, descripcion)
            VALUES (?, ?, 'Perfil local en uso. Lo cambia la persona desde la app.')
            ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor
            """,
            (CLAVE_PERFIL_ACTIVO, perfil_id),
        )
    return True


def listar() -> list[dict]:
    """Perfiles con su etiqueta, demografia y cuantos documentos tienen."""
    asegurar_esquema()
    activo = id_activo()
    with basedatos.conectar() as conexion:
        filas = conexion.execute(
            """
            SELECT u.*,
                   (SELECT COUNT(*) FROM documento d WHERE d.usuario_id = u.id) AS documentos,
                   (SELECT COUNT(*) FROM valor_extraido v
                      JOIN estudio e ON e.id = v.estudio_id
                      JOIN documento d ON d.id = e.documento_id
                     WHERE d.usuario_id = u.id) AS valores
            FROM usuario u
            ORDER BY u.creado_en
            """
        ).fetchall()
    return [{**dict(f), "activo": f["id"] == activo} for f in filas]


def crear(
    etiqueta: str,
    fecha_nacimiento: str,
    sexo: str,
    condicion: str = "general",
    distrito_residencia: str | None = None,
    residencia_desde: str | None = None,
    activar_al_crear: bool = True,
) -> dict:
    """Crea un perfil vacio y (por defecto) lo deja activo.

    `fecha_nacimiento`, `sexo` y `condicion` son obligatorios porque de ellos
    dependen los rangos de referencia. No se inventan valores por defecto: un
    rango elegido con la demografia equivocada da una alerta falsa o esconde una
    real.
    """
    from . import repositorio  # import diferido: repositorio importa este modulo

    asegurar_esquema()
    if not etiqueta or not etiqueta.strip():
        raise ValueError("la etiqueta del perfil no puede estar vacia")

    with basedatos.conectar() as conexion:
        nuevo_id = _id_libre(conexion, etiqueta)

    # La validacion de sexo, condicion y distrito vive en repositorio: se reusa
    # tal cual para que un perfil nuevo pase por los mismos filtros.
    usuario = repositorio.guardar_usuario(
        fecha_nacimiento=fecha_nacimiento,
        sexo=sexo,
        distrito_residencia=distrito_residencia,
        condicion=condicion,
        residencia_desde=residencia_desde,
        usuario_id=nuevo_id,
    )
    with basedatos.conectar() as conexion:
        conexion.execute(
            "UPDATE usuario SET etiqueta = ? WHERE id = ?", (etiqueta.strip(), nuevo_id)
        )
    if activar_al_crear:
        activar(nuevo_id)
    return {**usuario, "id": nuevo_id, "etiqueta": etiqueta.strip(), "activo": activar_al_crear}


def renombrar(perfil_id: str, etiqueta: str) -> bool:
    with basedatos.conectar() as conexion:
        cursor = conexion.execute(
            "UPDATE usuario SET etiqueta = ? WHERE id = ?", (etiqueta.strip() or None, perfil_id)
        )
    return cursor.rowcount > 0


def borrar(perfil_id: str) -> dict:
    """Borra un perfil con todos sus documentos, estudios y valores.

    Es destructivo y no se ofrece desde la interfaz: se llama a proposito. No
    borra los JPEG ni los JSON de auditoria de `capturas/`, para que quede
    rastro de lo que habia; eso se limpia a mano si se quiere.

    No se puede borrar el ultimo perfil que queda: la app necesita uno.
    """
    with basedatos.conectar() as conexion:
        total = conexion.execute("SELECT COUNT(*) AS n FROM usuario").fetchone()["n"]
        if total <= 1:
            raise ValueError("no se puede borrar el unico perfil que queda")
        if not conexion.execute("SELECT 1 FROM usuario WHERE id = ?", (perfil_id,)).fetchone():
            raise ValueError(f"el perfil '{perfil_id}' no existe")

        valores = conexion.execute(
            """
            DELETE FROM valor_extraido
            WHERE estudio_id IN (
                SELECT e.id FROM estudio e
                JOIN documento d ON d.id = e.documento_id
                WHERE d.usuario_id = ?
            )
            """,
            (perfil_id,),
        ).rowcount
        estudios = conexion.execute(
            """
            DELETE FROM estudio
            WHERE documento_id IN (SELECT id FROM documento WHERE usuario_id = ?)
            """,
            (perfil_id,),
        ).rowcount
        documentos = conexion.execute(
            "DELETE FROM documento WHERE usuario_id = ?", (perfil_id,)
        ).rowcount
        # El historico del asistente tambien apunta a `usuario`, asi que hay que
        # sacarlo antes: si no, el DELETE de abajo falla por clave ajena. Los
        # mensajes se van solos, `mensaje_chat` cuelga de `conversacion` con
        # ON DELETE CASCADE.
        conversaciones = conexion.execute(
            "DELETE FROM conversacion WHERE usuario_id = ?", (perfil_id,)
        ).rowcount
        conexion.execute("DELETE FROM usuario WHERE id = ?", (perfil_id,))

    if id_activo() == perfil_id:
        restantes = listar()
        if restantes:
            activar(restantes[0]["id"])

    return {
        "perfil": perfil_id,
        "documentos": documentos,
        "estudios": estudios,
        "valores": valores,
        "conversaciones": conversaciones,
    }
