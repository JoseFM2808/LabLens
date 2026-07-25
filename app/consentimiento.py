"""Consentimiento: terminos, comparticion con avisos y directiva post mortem.

Que resuelve
------------
1. **Terminos y condiciones**: se aceptan una vez por perfil, y se vuelven a pedir
   si cambia la version. Hasta que se aceptan, la app no deja entrar.
2. **Comparticion con una red medica**: la persona decide si sus datos pueden
   compartirse. Cuando una red los solicita, **no se comparte de inmediato**: se
   abre un aviso de 15 dias durante los cuales puede declinar. Si no dice nada, al
   vencer el plazo la solicitud queda lista para compartir.
3. **Migracion automatica**: se puede desactivar por completo. Con esto en `false`
   ninguna solicitud avanza sola: cada una necesita un si explicito.
4. **Directiva post mortem**: si el perfil no recibe informacion nueva durante 5
   anios, se considera inactivo y se aplica lo que la persona dejo dicho:
   - `mantener`: la comparticion **no** se revierte, sigue como estaba;
   - `revocar`: la comparticion se apaga y sus datos dejan de compartirse.

Limite deliberado: aqui **no se transmite nada**
-----------------------------------------------
Este modulo lleva el estado del consentimiento y prepara el paquete de datos, pero
no envia nada a ningun tercero. La entrega efectiva a una red medica necesita un
destinatario concreto, un canal acordado y autorizacion para ese destinatario;
ese es el gancho `entregar_a_red_medica`, que hoy solo registra la intencion.
Dejarlo asi es a proposito: un consentimiento firmado no es lo mismo que una
tuberia abierta hacia afuera.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta

from . import basedatos, perfiles

# Al cambiar el texto de los terminos se sube esta version: los perfiles que
# aceptaron una anterior vuelven a ver la pantalla.
VERSION_TERMINOS = "1.0"

# Dias de aviso antes de compartir. La persona puede declinar en ese plazo.
DIAS_DE_AVISO = 15

# Anios sin informacion nueva tras los cuales el perfil se considera inactivo.
# Se puede bajar desde `parametro_calculo` para poder probar el flujo.
ANIOS_INACTIVIDAD = 5
CLAVE_ANIOS_INACTIVIDAD = "post_mortem_anios_inactividad"

DIRECTIVAS = ("mantener", "revocar")
ESTADOS_SOLICITUD = ("en_aviso", "declinada", "autorizada", "lista_para_compartir", "cancelada")

DDL = """
CREATE TABLE IF NOT EXISTS consentimiento (
    usuario_id            TEXT PRIMARY KEY REFERENCES usuario(id),
    version_terminos      TEXT NOT NULL,
    aceptado_en           DATETIME NOT NULL,
    compartir_red_medica  INTEGER NOT NULL DEFAULT 0,
    migracion_automatica  INTEGER NOT NULL DEFAULT 0,
    directiva_post_mortem TEXT NOT NULL DEFAULT 'revocar',
    post_mortem_aplicado  DATETIME,
    actualizado_en        DATETIME
);

CREATE TABLE IF NOT EXISTS solicitud_datos (
    id             TEXT PRIMARY KEY,
    usuario_id     TEXT NOT NULL REFERENCES usuario(id),
    solicitante    TEXT NOT NULL,
    motivo         TEXT,
    alcance        TEXT,
    solicitado_en  DATETIME NOT NULL,
    comparte_en    DATETIME NOT NULL,
    estado         TEXT NOT NULL,
    decidido_en    DATETIME,
    nota           TEXT
);

CREATE INDEX IF NOT EXISTS idx_solicitud_usuario ON solicitud_datos (usuario_id, estado);

CREATE TABLE IF NOT EXISTS bitacora_consentimiento (
    id          INTEGER PRIMARY KEY,
    usuario_id  TEXT NOT NULL,
    momento     DATETIME NOT NULL,
    accion      TEXT NOT NULL,
    detalle     TEXT
);
"""

TEXTO_TERMINOS = """
## Qué es LabLens

LabLens toma una foto de tus documentos médicos, la endereza, lee los valores con
un modelo de inteligencia artificial y los compara contra los rangos de referencia
del MINSA y la OMS que correspondan a tu edad, sexo y condición.

## Esto no es un diagnóstico

Lo que ves es un **índice orientativo de seguimiento**. No es un diagnóstico, no
reemplaza la consulta con un profesional de la salud y puede contener errores de
lectura. Verifica siempre los valores contra el documento original antes de tomar
cualquier decisión.

## Qué datos se guardan y dónde

- Todo se guarda **en este dispositivo**, en un archivo de base de datos local.
- No se almacena tu nombre, documento de identidad ni ningún otro identificador
  personal. El nombre del perfil es solo una etiqueta para distinguir perfiles en
  este equipo.
- Se guardan: fecha de nacimiento, sexo, condición y distrito de residencia
  (necesarios para elegir el rango de referencia correcto), las fotos de tus
  documentos y los valores extraídos de ellos.

## La foto sale del dispositivo para poder leerla

Para extraer los valores, la imagen del documento se envía al servicio de
inteligencia artificial que hace la lectura. Es el único envío que ocurre de forma
rutinaria y es imprescindible para que la app funcione. Si no aceptas esto, la app
solo puede guardar la foto sin leerla.

## Compartir tus datos con una red médica

Compartir es **opcional y está desactivado por defecto**. Si lo activas:

- Cuando una red médica solicite tus datos, se te avisa y empieza un plazo de
  **15 días** antes de cualquier entrega.
- Durante esos 15 días puedes **declinar** la solicitud, sin dar explicaciones.
- Si no dices nada y tienes la migración automática activada, al vencer el plazo
  la solicitud queda lista para entregarse.
- Si desactivas la **migración automática**, ninguna solicitud avanza sola:
  cada una necesita que la autorices de forma expresa.
- Puedes revocar la compartición en cualquier momento. La revocación aplica hacia
  adelante: no alcanza a lo que ya se entregó.

## Qué pasa si dejas de usar la app

Si este perfil no recibe información nueva durante **5 años**, se considera
inactivo y se aplica la directiva que hayas dejado:

- **Mantener**: la compartición sigue como esté configurada y no se revierte.
- **Revocar**: la compartición se apaga y tus datos dejan de compartirse.

Puedes cambiar esta directiva cuando quieras, mientras el perfil siga activo.

## Tus datos son tuyos

En cualquier momento puedes eliminar un documento (se borran también la foto y el
archivo de auditoría), descargar tus datos en PDF, o borrar el perfil completo.

## Cifrado

Hoy la base de datos local **no está cifrada**. El cifrado del archivo completo
está previsto para una fase posterior. Ten esto en cuenta si otras personas usan
este dispositivo.
""".strip()


# ==========================================================================
# Esquema y utilidades
# ==========================================================================

def asegurar_esquema() -> None:
    """Crea las tablas de consentimiento si faltan. Idempotente."""
    with basedatos.conectar() as conexion:
        conexion.executescript(DDL)


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _anios_inactividad() -> int:
    """Umbral de inactividad. Configurable para poder probar el flujo."""
    with basedatos.conectar() as conexion:
        fila = conexion.execute(
            "SELECT valor FROM parametro_calculo WHERE clave = ?", (CLAVE_ANIOS_INACTIVIDAD,)
        ).fetchone()
    if fila:
        try:
            return int(float(fila["valor"]))
        except (TypeError, ValueError):
            pass
    return ANIOS_INACTIVIDAD


def _anotar(conexion, usuario_id: str, accion: str, detalle: dict | None = None) -> None:
    """Deja rastro de cada cambio de consentimiento. Es un dato de auditoria."""
    conexion.execute(
        "INSERT INTO bitacora_consentimiento (usuario_id, momento, accion, detalle) "
        "VALUES (?, ?, ?, ?)",
        (usuario_id, _ahora(), accion, json.dumps(detalle or {}, ensure_ascii=False)),
    )


# ==========================================================================
# Terminos
# ==========================================================================

def consentimiento_de(usuario_id: str | None = None) -> dict | None:
    asegurar_esquema()
    usuario_id = usuario_id or perfiles.id_activo()
    with basedatos.conectar() as conexion:
        fila = conexion.execute(
            "SELECT * FROM consentimiento WHERE usuario_id = ?", (usuario_id,)
        ).fetchone()
    return dict(fila) if fila else None


def terminos_aceptados(usuario_id: str | None = None) -> bool:
    """True solo si acepto **esta** version de los terminos."""
    actual = consentimiento_de(usuario_id)
    return bool(actual and actual["version_terminos"] == VERSION_TERMINOS)


def aceptar_terminos(
    usuario_id: str | None = None,
    compartir_red_medica: bool = False,
    migracion_automatica: bool = False,
    directiva_post_mortem: str = "revocar",
) -> dict:
    """Registra la aceptacion y las preferencias iniciales.

    Las tres preferencias arrancan en la opcion mas conservadora: no compartir,
    sin migracion automatica y revocar al quedar inactivo. Compartir es una
    decision que se toma, no un valor por defecto que se hereda.
    """
    asegurar_esquema()
    usuario_id = usuario_id or perfiles.id_activo()
    if directiva_post_mortem not in DIRECTIVAS:
        raise ValueError(f"directiva_post_mortem debe ser una de {DIRECTIVAS}")

    with basedatos.conectar() as conexion:
        if not conexion.execute("SELECT 1 FROM usuario WHERE id = ?", (usuario_id,)).fetchone():
            raise ValueError(f"el perfil '{usuario_id}' no existe")
        conexion.execute(
            """
            INSERT INTO consentimiento (
                usuario_id, version_terminos, aceptado_en, compartir_red_medica,
                migracion_automatica, directiva_post_mortem, actualizado_en
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(usuario_id) DO UPDATE SET
                version_terminos = excluded.version_terminos,
                aceptado_en = excluded.aceptado_en,
                compartir_red_medica = excluded.compartir_red_medica,
                migracion_automatica = excluded.migracion_automatica,
                directiva_post_mortem = excluded.directiva_post_mortem,
                actualizado_en = excluded.actualizado_en,
                post_mortem_aplicado = NULL
            """,
            (
                usuario_id,
                VERSION_TERMINOS,
                _ahora(),
                int(bool(compartir_red_medica)),
                int(bool(migracion_automatica)),
                directiva_post_mortem,
                _ahora(),
            ),
        )
        _anotar(
            conexion,
            usuario_id,
            "acepto_terminos",
            {
                "version": VERSION_TERMINOS,
                "compartir": bool(compartir_red_medica),
                "migracion_automatica": bool(migracion_automatica),
                "post_mortem": directiva_post_mortem,
            },
        )
    return consentimiento_de(usuario_id)  # type: ignore[return-value]


def actualizar_preferencias(
    usuario_id: str | None = None,
    compartir_red_medica: bool | None = None,
    migracion_automatica: bool | None = None,
    directiva_post_mortem: str | None = None,
) -> dict:
    """Cambia las preferencias. Solo toca lo que se pasa; el resto queda igual."""
    usuario_id = usuario_id or perfiles.id_activo()
    actual = consentimiento_de(usuario_id)
    if actual is None:
        raise ValueError("hay que aceptar los terminos antes de cambiar preferencias")
    if directiva_post_mortem is not None and directiva_post_mortem not in DIRECTIVAS:
        raise ValueError(f"directiva_post_mortem debe ser una de {DIRECTIVAS}")

    nuevo = {
        "compartir_red_medica": int(
            actual["compartir_red_medica"] if compartir_red_medica is None else compartir_red_medica
        ),
        "migracion_automatica": int(
            actual["migracion_automatica"] if migracion_automatica is None else migracion_automatica
        ),
        "directiva_post_mortem": directiva_post_mortem or actual["directiva_post_mortem"],
    }

    # Invariante: sin comparticion, la migracion automatica no significa nada.
    # Se fuerza aqui y no solo en la interfaz, porque un cliente que llame al
    # endpoint directo dejaria el par en un estado que no se puede explicar.
    if not nuevo["compartir_red_medica"]:
        nuevo["migracion_automatica"] = 0

    with basedatos.conectar() as conexion:
        conexion.execute(
            """
            UPDATE consentimiento SET
                compartir_red_medica = ?, migracion_automatica = ?,
                directiva_post_mortem = ?, actualizado_en = ?
            WHERE usuario_id = ?
            """,
            (
                nuevo["compartir_red_medica"],
                nuevo["migracion_automatica"],
                nuevo["directiva_post_mortem"],
                _ahora(),
                usuario_id,
            ),
        )
        # Al apagar la comparticion se cancelan los avisos en curso: seguir
        # contando los 15 dias de una solicitud que ya no puede cumplirse seria
        # engañoso.
        if not nuevo["compartir_red_medica"]:
            canceladas = conexion.execute(
                """
                UPDATE solicitud_datos
                SET estado = 'cancelada', decidido_en = ?,
                    nota = 'cancelada al desactivar la comparticion'
                WHERE usuario_id = ? AND estado IN ('en_aviso', 'autorizada')
                """,
                (_ahora(), usuario_id),
            ).rowcount
            if canceladas:
                _anotar(conexion, usuario_id, "cancelo_solicitudes", {"cantidad": canceladas})
        _anotar(conexion, usuario_id, "cambio_preferencias", nuevo)
    return consentimiento_de(usuario_id)  # type: ignore[return-value]


# ==========================================================================
# Solicitudes de una red medica
# ==========================================================================

def crear_solicitud(
    solicitante: str,
    motivo: str | None = None,
    alcance: str | None = None,
    usuario_id: str | None = None,
) -> dict:
    """Registra que una red medica pidio los datos y abre el aviso de 15 dias.

    No comparte nada: solo empieza a contar el plazo. Si la persona no tiene la
    comparticion activada, la solicitud entra igual pero nace `declinada`, para
    que quede constancia de que se pidio y de que la respuesta fue no.
    """
    asegurar_esquema()
    usuario_id = usuario_id or perfiles.id_activo()
    actual = consentimiento_de(usuario_id)
    if actual is None:
        raise ValueError("el perfil todavia no acepto los terminos")
    if not solicitante or not solicitante.strip():
        raise ValueError("hay que indicar quien solicita los datos")

    ahora = datetime.now()
    comparte_en = ahora + timedelta(days=DIAS_DE_AVISO)
    permite = bool(actual["compartir_red_medica"])
    estado = "en_aviso" if permite else "declinada"

    solicitud_id = str(uuid.uuid4())
    with basedatos.conectar() as conexion:
        conexion.execute(
            """
            INSERT INTO solicitud_datos (
                id, usuario_id, solicitante, motivo, alcance,
                solicitado_en, comparte_en, estado, decidido_en, nota
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                solicitud_id,
                usuario_id,
                solicitante.strip(),
                (motivo or "").strip() or None,
                (alcance or "").strip() or None,
                ahora.isoformat(timespec="seconds"),
                comparte_en.isoformat(timespec="seconds"),
                estado,
                None if permite else ahora.isoformat(timespec="seconds"),
                None if permite else "la comparticion esta desactivada en este perfil",
            ),
        )
        _anotar(
            conexion,
            usuario_id,
            "solicitud_recibida",
            {"solicitud": solicitud_id, "solicitante": solicitante.strip(), "estado": estado},
        )
    return solicitud(solicitud_id)  # type: ignore[return-value]


def solicitud(solicitud_id: str) -> dict | None:
    asegurar_esquema()
    with basedatos.conectar() as conexion:
        fila = conexion.execute(
            "SELECT * FROM solicitud_datos WHERE id = ?", (solicitud_id,)
        ).fetchone()
    return _con_dias(dict(fila)) if fila else None


def _con_dias(fila: dict) -> dict:
    """Agrega los dias que faltan para que venza el aviso."""
    try:
        comparte_en = datetime.fromisoformat(fila["comparte_en"])
    except (TypeError, ValueError):
        fila["dias_restantes"] = None
        return fila
    restantes = (comparte_en - datetime.now()).total_seconds() / 86400
    fila["dias_restantes"] = max(0, int(restantes // 1) + (1 if restantes % 1 else 0))
    fila["vencido"] = restantes <= 0
    return fila


def solicitudes(usuario_id: str | None = None, limite: int = 50) -> list[dict]:
    asegurar_esquema()
    usuario_id = usuario_id or perfiles.id_activo()
    with basedatos.conectar() as conexion:
        filas = conexion.execute(
            "SELECT * FROM solicitud_datos WHERE usuario_id = ? "
            "ORDER BY solicitado_en DESC LIMIT ?",
            (usuario_id, limite),
        ).fetchall()
    return [_con_dias(dict(f)) for f in filas]


def decidir_solicitud(solicitud_id: str, aceptar: bool, nota: str | None = None) -> dict:
    """La persona declina o autoriza una solicitud durante el plazo de aviso."""
    actual = solicitud(solicitud_id)
    if actual is None:
        raise ValueError("la solicitud no existe")
    if actual["estado"] not in ("en_aviso", "autorizada"):
        raise ValueError(f"la solicitud ya esta '{actual['estado']}' y no se puede cambiar")

    estado = "autorizada" if aceptar else "declinada"
    with basedatos.conectar() as conexion:
        conexion.execute(
            "UPDATE solicitud_datos SET estado = ?, decidido_en = ?, nota = ? WHERE id = ?",
            (estado, _ahora(), (nota or "").strip() or None, solicitud_id),
        )
        _anotar(
            conexion,
            actual["usuario_id"],
            "declino_solicitud" if not aceptar else "autorizo_solicitud",
            {"solicitud": solicitud_id, "solicitante": actual["solicitante"]},
        )
    return solicitud(solicitud_id)  # type: ignore[return-value]


def procesar_vencidas(usuario_id: str | None = None) -> list[dict]:
    """Cierra los avisos cuyos 15 dias ya pasaron.

    Con migracion automatica activa, la solicitud pasa a `lista_para_compartir`.
    Sin ella, se declina por falta de respuesta: el silencio no autoriza.
    """
    asegurar_esquema()
    usuario_id = usuario_id or perfiles.id_activo()
    actual = consentimiento_de(usuario_id)
    if actual is None:
        return []

    automatica = bool(actual["migracion_automatica"]) and bool(actual["compartir_red_medica"])
    cambiadas = []
    with basedatos.conectar() as conexion:
        pendientes = conexion.execute(
            "SELECT * FROM solicitud_datos WHERE usuario_id = ? AND estado IN ('en_aviso', 'autorizada')",
            (usuario_id,),
        ).fetchall()
        for fila in pendientes:
            datos = _con_dias(dict(fila))
            if not datos.get("vencido"):
                continue
            if datos["estado"] == "autorizada" or automatica:
                estado, nota = "lista_para_compartir", (
                    "autorizada por la persona" if datos["estado"] == "autorizada"
                    else f"vencio el aviso de {DIAS_DE_AVISO} dias sin respuesta"
                )
            else:
                estado, nota = "declinada", (
                    "vencio el aviso sin respuesta y la migracion automatica esta desactivada"
                )
            conexion.execute(
                "UPDATE solicitud_datos SET estado = ?, decidido_en = ?, nota = ? WHERE id = ?",
                (estado, _ahora(), nota, datos["id"]),
            )
            _anotar(conexion, usuario_id, "aviso_vencido", {"solicitud": datos["id"], "estado": estado})
            cambiadas.append({**datos, "estado": estado, "nota": nota})
    return cambiadas


# ==========================================================================
# Inactividad y directiva post mortem
# ==========================================================================

def ultima_actividad(usuario_id: str | None = None) -> str | None:
    """Fecha de la informacion mas reciente del perfil.

    Se mide por el ultimo documento cargado; si no hay ninguno, por la creacion
    del perfil. Cambiar una preferencia no cuenta como informacion nueva: la
    directiva habla de "no brindar nueva informacion".
    """
    usuario_id = usuario_id or perfiles.id_activo()
    with basedatos.conectar() as conexion:
        fila = conexion.execute(
            "SELECT MAX(fecha_carga) AS ultima FROM documento WHERE usuario_id = ?",
            (usuario_id,),
        ).fetchone()
        if fila and fila["ultima"]:
            return fila["ultima"]
        fila = conexion.execute(
            "SELECT creado_en FROM usuario WHERE id = ?", (usuario_id,)
        ).fetchone()
    return fila["creado_en"] if fila else None


def estado_post_mortem(usuario_id: str | None = None) -> dict:
    """Cuanto lleva el perfil sin informacion nueva y que pasaria al vencer."""
    usuario_id = usuario_id or perfiles.id_activo()
    actual = consentimiento_de(usuario_id)
    ultima = ultima_actividad(usuario_id)
    anios = _anios_inactividad()

    dias_sin_datos = None
    vence_en = None
    if ultima:
        try:
            momento = datetime.fromisoformat(str(ultima).replace(" ", "T"))
            dias_sin_datos = (datetime.now() - momento).days
            vence_en = (momento + timedelta(days=round(anios * 365.25))).date().isoformat()
        except ValueError:
            pass

    limite_dias = round(anios * 365.25)
    return {
        "ultima_actividad": ultima,
        "dias_sin_informacion": dias_sin_datos,
        "anios_umbral": anios,
        "inactivo": dias_sin_datos is not None and dias_sin_datos >= limite_dias,
        "se_aplica_el": vence_en,
        "directiva": actual["directiva_post_mortem"] if actual else "revocar",
        "aplicado_en": actual["post_mortem_aplicado"] if actual else None,
    }


def aplicar_post_mortem(usuario_id: str | None = None) -> dict:
    """Aplica la directiva si el perfil ya paso el umbral de inactividad.

    - `mantener`: no se toca nada. La comparticion **no se revierte**.
    - `revocar`: se apaga la comparticion y la migracion automatica, y se cierran
      las solicitudes en curso.

    Idempotente: si ya se aplico, no vuelve a hacerlo.
    """
    usuario_id = usuario_id or perfiles.id_activo()
    estado = estado_post_mortem(usuario_id)
    if not estado["inactivo"]:
        return {"aplicado": False, "motivo": "el perfil sigue activo", **estado}
    if estado["aplicado_en"]:
        return {"aplicado": False, "motivo": "ya se habia aplicado", **estado}

    with basedatos.conectar() as conexion:
        if estado["directiva"] == "mantener":
            conexion.execute(
                "UPDATE consentimiento SET post_mortem_aplicado = ? WHERE usuario_id = ?",
                (_ahora(), usuario_id),
            )
            _anotar(conexion, usuario_id, "post_mortem_mantener", estado)
            resultado = {
                "aplicado": True,
                "directiva": "mantener",
                "mensaje": "La comparticion se mantiene como estaba, no se revierte.",
            }
        else:
            conexion.execute(
                """
                UPDATE consentimiento
                SET compartir_red_medica = 0, migracion_automatica = 0,
                    post_mortem_aplicado = ?, actualizado_en = ?
                WHERE usuario_id = ?
                """,
                (_ahora(), _ahora(), usuario_id),
            )
            canceladas = conexion.execute(
                """
                UPDATE solicitud_datos
                SET estado = 'cancelada', decidido_en = ?,
                    nota = 'cancelada por la directiva post mortem'
                WHERE usuario_id = ? AND estado IN ('en_aviso', 'autorizada', 'lista_para_compartir')
                """,
                (_ahora(), usuario_id),
            ).rowcount
            _anotar(conexion, usuario_id, "post_mortem_revocar", {**estado, "canceladas": canceladas})
            resultado = {
                "aplicado": True,
                "directiva": "revocar",
                "solicitudes_canceladas": canceladas,
                "mensaje": "La comparticion se apago y sus datos dejan de compartirse.",
            }
    return {**resultado, **estado_post_mortem(usuario_id)}


# ==========================================================================
# Estado completo, para la interfaz
# ==========================================================================

def estado(usuario_id: str | None = None) -> dict:
    """Todo lo que la pantalla de perfil necesita, en una sola llamada.

    Antes de responder cierra los avisos vencidos y aplica la directiva post
    mortem si corresponde: el estado que se muestra es el estado real, no una
    foto que alguien tiene que refrescar a mano.
    """
    asegurar_esquema()
    usuario_id = usuario_id or perfiles.id_activo()
    vencidas = procesar_vencidas(usuario_id)
    post_mortem = aplicar_post_mortem(usuario_id)
    actual = consentimiento_de(usuario_id)

    return {
        "usuario_id": usuario_id,
        "terminos": {
            "version_actual": VERSION_TERMINOS,
            "aceptada": actual["version_terminos"] if actual else None,
            "al_dia": bool(actual and actual["version_terminos"] == VERSION_TERMINOS),
            "aceptado_en": actual["aceptado_en"] if actual else None,
        },
        "preferencias": {
            "compartir_red_medica": bool(actual["compartir_red_medica"]) if actual else False,
            "migracion_automatica": bool(actual["migracion_automatica"]) if actual else False,
            "directiva_post_mortem": actual["directiva_post_mortem"] if actual else "revocar",
            "actualizado_en": actual["actualizado_en"] if actual else None,
        },
        "dias_de_aviso": DIAS_DE_AVISO,
        "solicitudes": solicitudes(usuario_id),
        "cerradas_ahora": vencidas,
        "post_mortem": post_mortem,
        "transmision": {
            "habilitada": False,
            "nota": (
                "LabLens lleva el consentimiento pero todavia no entrega datos a "
                "ninguna red medica: no hay destinatario configurado. Ver "
                "`entregar_a_red_medica` en app/consentimiento.py."
            ),
        },
    }


# ==========================================================================
# Punto de extension: la entrega efectiva
# ==========================================================================

def entregar_a_red_medica(solicitud_id: str) -> dict:
    """Gancho de la entrega real. Hoy **no envia nada**.

    Para conectar una red medica de verdad hacen falta cuatro cosas que no se
    pueden inventar desde aqui: el destinatario, el canal y su autenticacion, el
    formato acordado, y la autorizacion explicita de la persona para **ese**
    destinatario. Mientras no esten, esta funcion registra la intencion y no
    transmite: una autorizacion firmada no es lo mismo que una tuberia abierta.

    Cuando se implemente, debe verificar en este orden:
      1. `consentimiento.compartir_red_medica` sigue activo;
      2. la solicitud esta en `lista_para_compartir`;
      3. paso el plazo de aviso completo;
      4. la directiva post mortem no la revoco.
    """
    actual = solicitud(solicitud_id)
    if actual is None:
        raise ValueError("la solicitud no existe")
    if actual["estado"] != "lista_para_compartir":
        return {
            "entregado": False,
            "motivo": f"la solicitud esta '{actual['estado']}', no lista para compartir",
        }
    return {
        "entregado": False,
        "motivo": "no hay red medica configurada",
        "solicitud": solicitud_id,
        "solicitante": actual["solicitante"],
        "siguiente_paso": (
            "Definir destinatario, canal y formato, y pedir autorizacion para ese "
            "destinatario concreto antes de transmitir."
        ),
    }
