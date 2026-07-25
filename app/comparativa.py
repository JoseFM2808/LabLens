"""Comparativa: valores del usuario contra los rangos de referencia.

Es lo que alimenta la vista Análisis. No es la ficha de un documento: cruza
**todo el historial de escaneos** del usuario contra `rango_referencia`
(OMS / MINSA), filtrando por su edad y sexo, y agrupa por sistema corporal.

Corresponde a la "Consulta clave: último scan vs referencia" de
`qhali-estructura-base-datos.md`.

Estado de los datos de referencia
---------------------------------
`rango_referencia` es Dominio 2 y hoy está vacía a propósito. Mientras siga así,
`referencias.disponibles` viene en `false` y cada biomarcador queda en estado
`sin_referencia`: la app muestra el historial del usuario pero **no puede** decir
si un valor está bien o mal. Es la respuesta honesta, no un cero disfrazado.

Cuando se carguen los rangos, esta misma función empieza a devolver
`dentro` / `fuera` y el porcentaje por grupo, sin cambios en el frontend.
"""

from __future__ import annotations

from datetime import date

from . import basedatos, perfiles

# Un cambio menor a esto no se considera tendencia: es ruido de medición.
UMBRAL_TENDENCIA = 0.02

# Nombres legibles por sistema corporal. Las claves son las que trae el catálogo
# de biomarcadores de la base validada; las demás quedan por si el catálogo crece.
ETIQUETAS_SISTEMA = {
    "hematologia": "Hematología",
    "bioquimica": "Bioquímica",
    "orina": "Examen de orina",
    "antropometria": "Medidas corporales",
    "signos_vitales": "Signos vitales",
    "ginecologia": "Ginecología",
    "sangre": "Examen de sangre",
    "renal": "Función renal",
    "hepatico": "Función hepática",
    "lipidos": "Perfil lipídico",
    "tiroides": "Función tiroidea",
    "vision": "Examen de vista",
    "cardiovascular": "Examen cardiovascular",
    "sin_clasificar": "Sin clasificar",
}


def _edad(fecha_nacimiento: str | None) -> int | None:
    if not fecha_nacimiento:
        return None
    try:
        nacimiento = date.fromisoformat(str(fecha_nacimiento)[:10])
    except ValueError:
        return None
    hoy = date.today()
    return hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))


def _columnas(conexion, tabla: str) -> set[str]:
    """Columnas existentes de una tabla.

    Hace falta porque `rango_referencia` convive en dos formas: la v0.1 con la
    edad en anios y la v1.0 con la edad en dias, `condicion`, `tipo_limite` y
    `prioridad`. Se detecta en caliente en vez de asumir una.
    """
    return {
        fila["name"] for fila in conexion.execute(f"PRAGMA table_info({tabla})")
    }


def _version_vigente(conexion, fuente_id: int) -> int | None:
    """Versión de referencia a usar para una fuente.

    El diseño manda usar la versión del último lote de ingesta completado. Si
    todavía no se registró ningún lote (que es el caso hoy), se cae a la versión
    más alta que exista en `rango_referencia`, para que cargar rangos a mano
    también funcione.
    """
    fila = conexion.execute(
        "SELECT MAX(version) AS v FROM ingesta_lote WHERE fuente_id = ? AND estado = 'completado'",
        (fuente_id,),
    ).fetchone()
    if fila and fila["v"] is not None:
        return fila["v"]
    fila = conexion.execute(
        "SELECT MAX(version) AS v FROM rango_referencia WHERE fuente_id = ?", (fuente_id,)
    ).fetchone()
    return fila["v"] if fila else None


def _referencia(
    conexion,
    biomarcador_id: int,
    sexo: str | None,
    edad: int | None,
    dias: int | None,
    condicion: str | None,
    columnas: set[str],
) -> dict | None:
    """Rango de referencia aplicable a este biomarcador, sexo, edad y condicion.

    Se resuelve aqui en vez de usar la vista `v_evaluacion` del equipo porque esa
    vista filtra por `valor BETWEEN valor_min AND valor_max`: solo devuelve los
    valores que **si** estan dentro de rango. Con eso no se puede distinguir
    "fuera de rango" de "no habia rango aplicable", y la interfaz necesita esa
    diferencia. Conviene alinearlo con quien escribio la vista.

    Prioridad entre rangos: primero `prioridad` (v1.0) si existe, y en su defecto
    la version mas alta. `prioridad`, `organismo` y `cita` estan en
    `fuente_referencia`, **no** en `rango_referencia`, asi que se piden con alias:
    buscarlas en las columnas de `rango_referencia` daba siempre falso y el
    desempate por autoridad no se aplicaba. Con eso, la hemoglobina de una mujer
    adulta se comparaba contra el panel de laboratorio sin cita (11-16 g/dl) en vez
    de contra la NTS 213 (12 g/dl o mas), y la misma medicion salia "normal" en
    Analisis y "anemia leve" en `v_evaluacion`.

    El rango que se devuelve es el de clasificacion `normal`, no el primero que
    calce. La NTS 213 carga cuatro filas por grupo (normal / leve / moderada /
    severa) y todas pasan los mismos filtros de sexo, edad y condicion: sin este
    desempate ganaba la de anemia severa (0-8 g/dl) y una hemoglobina sana
    aparecia "fuera de rango" contra un rango que no era el normal.
    """
    columnas_fuente = _columnas(conexion, "fuente_referencia")
    alias = ", ".join(
        f"f.{columna} AS fuente_{columna}"
        for columna in ("organismo", "cita", "prioridad")
        if columna in columnas_fuente
    )
    orden = (
        "fuente_prioridad ASC, r.version DESC"
        if "prioridad" in columnas_fuente
        else "r.version DESC"
    )
    orden = f"(r.clasificacion = 'normal') DESC, {orden}"
    filas = conexion.execute(
        f"""
        SELECT r.*, f.nombre AS fuente_nombre{', ' + alias if alias else ''}
        FROM rango_referencia r
        JOIN fuente_referencia f ON f.id = r.fuente_id
        WHERE r.biomarcador_id = ?
        ORDER BY {orden}
        """,
        (biomarcador_id,),
    ).fetchall()

    usa_dias = "edad_min_dias" in columnas

    for fila in filas:
        if fila["sexo"] and sexo and fila["sexo"] != sexo:
            continue
        if "condicion" in columnas and fila["condicion"]:
            if fila["condicion"] != "general" and fila["condicion"] != (condicion or "general"):
                continue

        if usa_dias and dias is not None:
            if fila["edad_min_dias"] is not None and dias < fila["edad_min_dias"]:
                continue
            if fila["edad_max_dias"] is not None and dias > fila["edad_max_dias"]:
                continue
        elif edad is not None:
            if fila["edad_min"] is not None and edad < fila["edad_min"]:
                continue
            if fila["edad_max"] is not None and edad > fila["edad_max"]:
                continue

        if fila["version"] != _version_vigente(conexion, fila["fuente_id"]):
            continue

        claves = fila.keys()
        organismo = (
            fila["fuente_organismo"]
            if "fuente_organismo" in claves and fila["fuente_organismo"]
            else None
        )
        return {
            "min": fila["valor_min"],
            "max": fila["valor_max"],
            "unidad": fila["unidad"],
            "clasificacion": fila["clasificacion"],
            "tipo_limite": fila["tipo_limite"] if "tipo_limite" in claves else None,
            "fuente": organismo or fila["fuente_nombre"],
            # Sin cita, la interfaz debe decir que el rango no tiene respaldo
            # documentado. Es el caso de los paneles de laboratorio cargados.
            "cita": fila["fuente_cita"] if "fuente_cita" in claves else None,
            "version": fila["version"],
        }
    return None


def _ajuste_altitud(conexion, biomarcador_id: int, altitud: int | None) -> dict | None:
    """Factor que se le RESTA al valor observado segun la altitud de residencia.

    NTS 213 Tabla N.1, columna "Disminuir". Solo hay tramos con factor sobre los
    500 msnm (§5.3.2), asi que por debajo de eso la consulta no devuelve nada y
    el valor se evalua tal cual. Con altitud desconocida tampoco se ajusta: la
    interfaz debe declarar que no se pudo ajustar, no simular que no hacia falta.
    """
    if altitud is None:
        return None
    fila = conexion.execute(
        """
        SELECT a.id, a.factor_ajuste, a.unidad, a.altitud_min_msnm, a.altitud_max_msnm
        FROM ajuste_altitud a
        WHERE a.biomarcador_id = ? AND a.factor_ajuste > 0
          AND ? BETWEEN a.altitud_min_msnm AND a.altitud_max_msnm
        ORDER BY a.version DESC
        LIMIT 1
        """,
        (biomarcador_id, altitud),
    ).fetchone()
    if fila is None:
        return None
    return {
        "id": fila["id"],
        "factor": fila["factor_ajuste"],
        "unidad": fila["unidad"],
        "altitud_msnm": altitud,
        "tramo": f"{fila['altitud_min_msnm']}-{fila['altitud_max_msnm']} msnm",
    }


def conciliar_escala(valor: float | None, referencia: dict | None) -> tuple[float | None, bool]:
    """Ajusta el valor cuando viene en otra escala que la del rango.

    Caso real: la densidad urinaria se imprime como ``1.030`` o como ``1030``
    segun el laboratorio, y el catalogo la guarda en la convencion x1000
    (rango 1016 a 1022). Sin conciliar, el mismo resultado daba "dentro" leido de
    una forma y un disparate leido de la otra.

    La regla es deliberadamente estrecha: solo se corrige cuando el valor esta
    exactamente mil veces por debajo del rango. No se hace nada parecido a
    "acercar" un valor a su rango, que seria inventar el resultado.

    Devuelve ``(valor, se_ajusto)``.
    """
    if valor is None or referencia is None:
        return valor, False
    minimo, maximo = referencia.get("min"), referencia.get("max")
    if minimo is None or maximo is None or valor == 0:
        return valor, False
    if minimo <= valor <= maximo:
        return valor, False
    escalado = valor * 1000
    if minimo <= escalado <= maximo:
        return escalado, True
    return valor, False


def _estado(valor: float | None, referencia: dict | None) -> str:
    if referencia is None:
        return "sin_referencia"
    if valor is None:
        return "sin_valor"
    if valor < referencia["min"] or valor > referencia["max"]:
        return "fuera"
    return "dentro"


def _tendencia(historial: list[dict], clave: str = "evaluado") -> str | None:
    """Dirección del cambio entre las dos últimas mediciones numéricas.

    Se compara sobre `evaluado`, no sobre el valor crudo: ese ya viene con la
    escala conciliada y el ajuste por altitud aplicado. Con el crudo, una
    densidad leída ``1.030`` y otra ``1030`` -el mismo resultado- daban una
    subida de 100 000%.
    """
    numericos = [h for h in historial if h.get(clave) is not None]
    if len(numericos) < 2:
        return None
    previo = numericos[-2][clave]
    ultimo = numericos[-1][clave]
    if previo == 0:
        return "estable" if ultimo == 0 else ("sube" if ultimo > 0 else "baja")
    cambio = (ultimo - previo) / abs(previo)
    if abs(cambio) < UMBRAL_TENDENCIA:
        return "estable"
    return "sube" if cambio > 0 else "baja"


def _mejora(historial: list[dict], referencia: dict | None, clave: str = "valor") -> str | None:
    """Si el último valor se acercó o se alejó del centro del rango.

    Sin rango de referencia no se puede afirmar que subir sea mejor o peor, así
    que devuelve None. Es el caso hoy, con el Dominio 2 vacío.
    """
    if referencia is None:
        return None
    numericos = [h for h in historial if h.get(clave) is not None]
    if len(numericos) < 2:
        return None
    previo = numericos[-2][clave]
    ultimo = numericos[-1][clave]

    # Los rangos abiertos de la v1.0 no tienen centro: un piso "12 o mas" se
    # carga como 12 a 9 000 000 000, y promediar eso da un centro absurdo que
    # convierte cualquier subida en mejora. Con un limite abierto la direccion ya
    # dice todo: acercarse al lado cerrado es mejorar.
    limite = referencia.get("tipo_limite")
    if limite == "solo_inferior":
        cerca = ultimo - previo
    elif limite == "solo_superior":
        cerca = previo - ultimo
    else:
        centro = (referencia["min"] + referencia["max"]) / 2
        cerca = abs(previo - centro) - abs(ultimo - centro)

    if abs(cerca) < 1e-9:
        return "igual"
    return "mejora" if cerca > 0 else "empeora"


def analisis_usuario(usuario_id: str | None = None) -> dict:
    # El valor por defecto se resuelve al llamar, no al importar: el perfil
    # activo puede cambiar mientras el servidor corre.
    usuario_id = usuario_id or perfiles.id_activo()
    return _analisis_usuario(usuario_id)


def _analisis_usuario(usuario_id: str) -> dict:
    """Comparativa completa del usuario contra los rangos de referencia."""
    with basedatos.conectar() as conexion:
        usuario = conexion.execute(
            "SELECT * FROM usuario WHERE id = ?", (usuario_id,)
        ).fetchone()
        if usuario is None:
            return {
                "usuario": None,
                "mensaje": "Falta configurar el usuario local (fecha de nacimiento y sexo).",
                "referencias": {"disponibles": False, "total_rangos": 0, "fuentes": []},
                "grupos": [],
            }

        edad = _edad(usuario["fecha_nacimiento"])
        sexo = usuario["sexo"]
        columnas_rango = _columnas(conexion, "rango_referencia")
        claves_usuario = usuario.keys()
        condicion = usuario["condicion"] if "condicion" in claves_usuario else None
        # La v1.0 filtra por edad en dias, no en anios.
        fila_dias = conexion.execute(
            "SELECT CAST(julianday('now') - julianday(?) AS INTEGER) AS d",
            (usuario["fecha_nacimiento"],),
        ).fetchone()
        dias = fila_dias["d"] if fila_dias else None

        # Altitud de la residencia declarada. La NTS 213 §5.3.2 la toma de donde
        # vive la persona, no de donde le hicieron el analisis, y de ahi sale el
        # ajuste de la hemoglobina.
        clave_distrito = (
            usuario["clave_distrito_residencia"]
            if "clave_distrito_residencia" in claves_usuario
            else None
        )
        distrito = (
            conexion.execute(
                "SELECT nombre, departamento, altitud_msnm FROM distrito WHERE clave_norm = ?",
                (clave_distrito,),
            ).fetchone()
            if clave_distrito
            else None
        )
        altitud = distrito["altitud_msnm"] if distrito else None

        total_rangos = conexion.execute(
            "SELECT COUNT(*) AS n FROM rango_referencia"
        ).fetchone()["n"]
        # Se cuentan los rangos realmente usables por fuente. `fuente_referencia`
        # trae una fila por dataset, así que sin agrupar salen repetidas; y las
        # que están como POR_DEFINIR no tienen organismo asignado todavía, así
        # que no se pueden citar y se reportan aparte.
        fuentes = [
            dict(f)
            for f in conexion.execute(
                """
                SELECT f.nombre, MAX(f.fecha_snapshot) AS fecha_snapshot,
                       MAX(f.version) AS version, COUNT(r.id) AS rangos
                FROM fuente_referencia f
                LEFT JOIN rango_referencia r ON r.fuente_id = f.id
                GROUP BY f.nombre
                HAVING rangos > 0
                ORDER BY rangos DESC
                """
            )
        ]
        sin_atribuir = sum(f["rangos"] for f in fuentes if f["nombre"] == "POR_DEFINIR")
        fuentes = [f for f in fuentes if f["nombre"] != "POR_DEFINIR"]

        # Todas las mediciones del usuario, ordenadas en el tiempo.
        filas = conexion.execute(
            """
            SELECT b.id AS biomarcador_id, b.nombre, b.sistema_corporal, b.unidad_estandar,
                   v.valor_numerico, v.unidad, v.valor_crudo_texto,
                   d.id AS documento_id, d.fecha_carga, d.fecha_documento,
                   d.institucion_nombre
            FROM valor_extraido v
            JOIN estudio e ON e.id = v.estudio_id
            JOIN documento d ON d.id = e.documento_id
            JOIN biomarcador b ON b.id = v.biomarcador_id
            WHERE d.usuario_id = ?
            ORDER BY d.fecha_carga ASC, v.rowid ASC
            """,
            (usuario_id,),
        ).fetchall()

        por_biomarcador: dict[int, dict] = {}
        for fila in filas:
            entrada = por_biomarcador.setdefault(
                fila["biomarcador_id"],
                {
                    "id": fila["biomarcador_id"],
                    "nombre": fila["nombre"],
                    "sistema": fila["sistema_corporal"],
                    "unidad": fila["unidad"] or fila["unidad_estandar"],
                    "historial": [],
                },
            )
            entrada["historial"].append(
                {
                    "valor": fila["valor_numerico"],
                    "texto": fila["valor_crudo_texto"],
                    "unidad": fila["unidad"],
                    "fecha": fila["fecha_documento"] or fila["fecha_carga"],
                    "documento_id": fila["documento_id"],
                    "institucion": fila["institucion_nombre"],
                }
            )

        biomarcadores = []
        for entrada in por_biomarcador.values():
            referencia = _referencia(
                conexion, entrada["id"], sexo, edad, dias, condicion, columnas_rango
            )
            # El valor se compara **ajustado** por altitud, no crudo: a 4 373 msnm
            # una hemoglobina de 13.8 g/dl es anemia moderada segun la NTS 213. El
            # valor medido no se pisa nunca, se guarda al lado en `evaluado`.
            ajuste = _ajuste_altitud(conexion, entrada["id"], altitud)
            factor = ajuste["factor"] if ajuste else 0.0
            reescalados = 0
            for medicion in entrada["historial"]:
                if medicion["valor"] is None:
                    medicion["evaluado"] = None
                    continue
                # Antes de restar el ajuste hay que tener el valor en la misma
                # escala que el rango: la densidad urinaria llega como 1.030 o
                # como 1030 segun el laboratorio.
                base, se_reescalo = conciliar_escala(medicion["valor"], referencia)
                medicion["evaluado"] = round(base - factor, 2)
                medicion["reescalado"] = se_reescalo
                reescalados += 1 if se_reescalo else 0
            ultimo = entrada["historial"][-1]
            biomarcadores.append(
                {
                    **entrada,
                    "mediciones": len(entrada["historial"]),
                    "ultimo": ultimo,
                    "referencia": referencia,
                    "ajuste": ajuste,
                    "mediciones_reescaladas": reescalados,
                    "estado": _estado(ultimo["evaluado"], referencia),
                    "tendencia": _tendencia(entrada["historial"]),
                    "evolucion": _mejora(entrada["historial"], referencia, "evaluado"),
                }
            )

    # Agrupado por sistema corporal
    grupos: dict[str, dict] = {}
    for biomarcador in biomarcadores:
        sistema = biomarcador["sistema"] or "sin_clasificar"
        grupo = grupos.setdefault(
            sistema,
            {
                "sistema": sistema,
                "etiqueta": ETIQUETAS_SISTEMA.get(sistema, sistema.replace("_", " ").capitalize()),
                "biomarcadores": [],
            },
        )
        grupo["biomarcadores"].append(biomarcador)

    salida = []
    for grupo in grupos.values():
        lista = grupo["biomarcadores"]
        evaluados = [b for b in lista if b["estado"] in ("dentro", "fuera")]
        dentro = [b for b in evaluados if b["estado"] == "dentro"]
        mejoras = sum(1 for b in lista if b["evolucion"] == "mejora")
        empeoramientos = sum(1 for b in lista if b["evolucion"] == "empeora")

        if not evaluados:
            tendencia_grupo = None
        elif mejoras > empeoramientos:
            tendencia_grupo = "mejora"
        elif empeoramientos > mejoras:
            tendencia_grupo = "empeora"
        else:
            tendencia_grupo = "estable"

        salida.append(
            {
                **grupo,
                "total": len(lista),
                "evaluados": len(evaluados),
                "dentro": len(dentro),
                "fuera": len(evaluados) - len(dentro),
                "sin_referencia": len(lista) - len(evaluados),
                # None, no 0: sin rangos cargados no hay porcentaje que mostrar.
                "porcentaje": round(100 * len(dentro) / len(evaluados)) if evaluados else None,
                "tendencia": tendencia_grupo,
            }
        )

    # Primero los grupos con algo fuera de rango, luego por cantidad de datos.
    salida.sort(key=lambda g: (-(g["fuera"] or 0), -g["total"]))

    return {
        "usuario": {
            "edad": edad,
            "sexo": sexo,
            "condicion": condicion,
            "distrito": usuario["distrito_residencia"],
            "clave_distrito": clave_distrito,
            "altitud_msnm": altitud,
            # La interfaz tiene que decir por que no hubo ajuste, no callarlo.
            "estado_ajuste": (
                "sin_distrito" if clave_distrito is None
                else "sin_altitud" if altitud is None
                else "sin_ajuste" if altitud <= 500
                else "ajustado_por_altitud"
            ),
        },
        "referencias": {
            "disponibles": total_rangos > 0,
            "total_rangos": total_rangos,
            "fuentes": fuentes,
            "rangos_sin_atribuir": sin_atribuir,
        },
        "total_biomarcadores": len(biomarcadores),
        "total_mediciones": sum(b["mediciones"] for b in biomarcadores),
        "grupos": salida,
    }
