"""Historico del asistente: conversaciones y mensajes guardados en la base.

Antes la conversacion vivia solo en el navegador y se perdia al recargar. Ahora se
guarda en `datos/qhali.sqlite3`, en dos tablas propias de la app (`conversacion` y
`mensaje_chat`). No son parte del esquema validado por el equipo: se declaran
aparte en `basedatos.DDL_CHAT` para que quede claro que no son Dominio 2.

Lo que hay que saber antes de usar esto
---------------------------------------
El diseno de la base dice **cero PII**: no se guardan nombres. El chat es la
primera cosa que rompe esa garantia, porque guarda **texto libre que escribe la
persona**, y ahi puede entrar cualquier cosa: un nombre, un sintoma, el nombre de
su medico. No es un descuido, es el precio de tener historico, y conviene tenerlo
escrito:

- El archivo es local y de un solo usuario, el mismo que ya guarda sus valores de
  laboratorio. No sale del equipo.
- La Fase 2 cifra el archivo completo con SQLCipher, y eso cubre tambien esto.
- La persona puede borrar una conversacion o todas desde la pantalla. `borrar`
  elimina de verdad las filas, no las marca.

Por que se guardan tambien los errores
--------------------------------------
Si el servicio falla, la respuesta se guarda con `estado` distinto de `'ok'`. Sirve
para dos cosas: la pantalla puede mostrar lo que realmente paso, y ese texto queda
**fuera** del historial que se le manda al modelo (`historial_para_modelo`), porque
un aviso de error no es parte de la conversacion.
"""

from __future__ import annotations

import uuid

from . import basedatos, perfiles

# Largo del titulo que se arma con la primera pregunta. Suficiente para reconocer
# la conversacion en la lista sin que la fila se parta en tres lineas.
LARGO_TITULO = 60

QUIENES = ("usuario", "asistente")


def _nuevo_id() -> str:
    return str(uuid.uuid4())


def _titulo(pregunta: str) -> str:
    texto = " ".join((pregunta or "").split())
    if not texto:
        return "Conversacion"
    if len(texto) <= LARGO_TITULO:
        return texto
    return texto[: LARGO_TITULO - 1].rstrip() + "…"


# ==========================================================================
# Escritura
# ==========================================================================

def crear(usuario_id: str | None, primera_pregunta: str) -> str:
    """Abre una conversacion y devuelve su id.

    Sin `usuario_id` la conversacion queda a nombre del **perfil activo**: cada
    perfil ve su propio historial, igual que ve sus propios documentos. Si todavia
    no hay ningun perfil creado se guarda sin dueno, porque se puede preguntar
    antes de registrarse (el asistente explica que sin perfil no hay mediciones).
    """
    identificador = _nuevo_id()
    duenio = usuario_id or perfiles.id_activo()
    with basedatos.conectar() as conexion:
        existe_usuario = duenio and conexion.execute(
            "SELECT 1 FROM usuario WHERE id = ?", (duenio,)
        ).fetchone()
        conexion.execute(
            "INSERT INTO conversacion (id, usuario_id, titulo) VALUES (?, ?, ?)",
            (identificador, duenio if existe_usuario else None, _titulo(primera_pregunta)),
        )
    return identificador


def guardar_mensaje(
    conversacion_id: str,
    quien: str,
    texto: str,
    estado: str | None = None,
    modelo: str | None = None,
    ms_respuesta: int | None = None,
) -> str:
    """Agrega un mensaje y marca la conversacion como recien usada."""
    if quien not in QUIENES:
        raise ValueError(f"quien debe ser uno de {QUIENES}")
    identificador = _nuevo_id()
    with basedatos.conectar() as conexion:
        conexion.execute(
            """
            INSERT INTO mensaje_chat (
                id, conversacion_id, quien, texto, estado, modelo, ms_respuesta
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (identificador, conversacion_id, quien, texto, estado, modelo, ms_respuesta),
        )
        conexion.execute(
            "UPDATE conversacion SET actualizada_en = CURRENT_TIMESTAMP WHERE id = ?",
            (conversacion_id,),
        )
    return identificador


def borrar(conversacion_id: str) -> bool:
    """Elimina una conversacion y sus mensajes. Devuelve False si no existia."""
    with basedatos.conectar() as conexion:
        # Los mensajes se van por ON DELETE CASCADE, que funciona porque
        # `basedatos.conectar` enciende las claves ajenas en cada conexion.
        cursor = conexion.execute("DELETE FROM conversacion WHERE id = ?", (conversacion_id,))
    return cursor.rowcount > 0


def borrar_todo(usuario_id: str | None = None, todos_los_perfiles: bool = False) -> int:
    """Elimina las conversaciones del perfil. Devuelve cuantas se borraron.

    Con `todos_los_perfiles` borra el historial completo de la instalacion. Es lo
    que hace falta al borrar un perfil, para no dejar sus conversaciones huerfanas.
    """
    with basedatos.conectar() as conexion:
        if todos_los_perfiles:
            cursor = conexion.execute("DELETE FROM conversacion")
        else:
            duenio = usuario_id or perfiles.id_activo()
            cursor = conexion.execute(
                "DELETE FROM conversacion WHERE usuario_id = ?", (duenio,)
            )
    return cursor.rowcount


# ==========================================================================
# Lectura
# ==========================================================================

def existe(conversacion_id: str | None) -> bool:
    if not conversacion_id:
        return False
    with basedatos.conectar() as conexion:
        return (
            conexion.execute(
                "SELECT 1 FROM conversacion WHERE id = ?", (conversacion_id,)
            ).fetchone()
            is not None
        )


def listar(limite: int = 30, usuario_id: str | None = None) -> list[dict]:
    """Conversaciones del perfil, de la mas usada recientemente a la mas vieja.

    Se filtra por dueno: cambiar de perfil no debe mostrar la conversacion de otra
    persona. Las que no tienen dueno (se preguntaron antes de crear el primer
    perfil) se cuentan como del perfil original, para que no queden invisibles.
    """
    duenio = usuario_id or perfiles.id_activo()
    condicion = "c.usuario_id = ?"
    parametros: list = [duenio]
    if duenio == perfiles.ID_POR_DEFECTO:
        condicion = "(c.usuario_id = ? OR c.usuario_id IS NULL)"
    parametros.append(limite)

    with basedatos.conectar() as conexion:
        filas = conexion.execute(
            f"""
            SELECT c.id, c.titulo, c.creada_en, c.actualizada_en,
                   COUNT(m.id) AS mensajes,
                   MAX(CASE WHEN m.quien = 'asistente' THEN m.creado_en END) AS ultima_respuesta
              FROM conversacion c
              LEFT JOIN mensaje_chat m ON m.conversacion_id = c.id
             WHERE {condicion}
             GROUP BY c.id
             ORDER BY c.actualizada_en DESC, c.creada_en DESC
             LIMIT ?
            """,
            parametros,
        ).fetchall()
    return [dict(fila) for fila in filas]


def mensajes(conversacion_id: str) -> list[dict]:
    """Mensajes de una conversacion, en orden.

    Se ordena por `creado_en` **y** `rowid`: el DEFAULT CURRENT_TIMESTAMP de SQLite
    tiene resolucion de un segundo, y pregunta y respuesta pueden caer en el mismo
    segundo. Sin el rowid el orden entre esas dos filas seria indefinido.
    """
    with basedatos.conectar() as conexion:
        filas = conexion.execute(
            """
            SELECT id, quien, texto, creado_en, estado, modelo, ms_respuesta
              FROM mensaje_chat
             WHERE conversacion_id = ?
             ORDER BY creado_en ASC, rowid ASC
            """,
            (conversacion_id,),
        ).fetchall()
    return [dict(fila) for fila in filas]


def historial_para_modelo(conversacion_id: str, turnos: int) -> list[dict]:
    """Ultimos `turnos` mensajes utiles, en el formato que espera el asistente.

    Deja fuera las respuestas que no salieron bien (`estado` distinto de 'ok'): un
    "no se pudo llegar al servicio" no es parte de la conversacion y meterlo en el
    contexto solo confunde al modelo.
    """
    utiles = [
        {"quien": mensaje["quien"], "texto": mensaje["texto"]}
        for mensaje in mensajes(conversacion_id)
        if mensaje["quien"] == "usuario" or (mensaje["estado"] or "ok") == "ok"
    ]
    return utiles[-turnos:] if turnos > 0 else []
