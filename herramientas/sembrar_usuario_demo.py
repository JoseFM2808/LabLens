"""Crea un usuario de relleno con historial completo, para probar y para la demo.

    .\\.venv\\Scripts\\python.exe herramientas\\sembrar_usuario_demo.py
    .\\.venv\\Scripts\\python.exe herramientas\\sembrar_usuario_demo.py --borrar

Necesita que los datos de referencia esten cargados
(`herramientas/cargar_referencia.py`): los valores se enganchan al catalogo
curado por nombre y unidad, y el distrito tiene que existir en el padron.

Que se siembra y por que
------------------------
Una mujer de 32 anios, no gestante, que vive en **Chaupimarca (Cerro de Pasco),
4 373 msnm**, con tres documentos: dos analisis de laboratorio separados cuatro
meses y un control de signos vitales.

El caso esta elegido para que se vea el ajuste por altitud de la NTS 213:

    Hemoglobina 13.8 g/dl  ->  13.8 - 2.9 = 10.9  ->  anemia MODERADA

13.8 g/dl parece una hemoglobina sana en cualquier lectura ingenua. A 4 373 msnm
es anemia moderada segun la norma peruana vigente. El segundo analisis sube a
14.6 (11.7 ajustado, anemia leve), asi que el historial tambien muestra mejora.

Los datos son inventados y estan marcados como tales: el usuario es
``usuario-relleno`` y los documentos empiezan con ``relleno-``. `--borrar` los
saca sin tocar nada mas. Las rutas de archivo apuntan a `relleno/`, una carpeta
que no existe, porque estos documentos nunca se escanearon.

Lo que **no** se inventa: `confianza_extraccion` queda en NULL, igual que en los
escaneos reales. El servicio de extraccion no devuelve una confianza por valor y
poner un numero inventado en un dato de salud es peor que dejarlo vacio. Los
biomarcadores derivados (IMC, indice Col/HDL, % de grasa) tampoco se siembran:
son `derivado = 1`, se calculan, y no hay peso ni talla de donde calcularlos.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app import basedatos, referencia, repositorio  # noqa: E402

ID_USUARIO = "usuario-relleno"
PREFIJO_DOCUMENTO = "relleno-"

# uuid5 en vez de uuid4: los ids salen iguales en cada corrida, asi que volver a
# sembrar no deja duplicados ni cambia los identificadores en las capturas.
ESPACIO = uuid.UUID("6f6b1f3a-6b4a-5a2e-9c7d-0a1b2c3d4e5f")

USUARIO = {
    "fecha_nacimiento": "1994-03-12",
    "sexo": "F",
    "condicion": "no_gestante",
    "distrito_texto": "Chaupimarca",
    "clave_distrito": "PASCO|PASCO|CHAUPIMARCA",
    # NTS 213 §5.3.2: el ajuste se calcula sobre la residencia de los ultimos 4
    # meses. Esta fecha esta bastante antes, asi que el ajuste corresponde.
    "residencia_desde": "2025-09-01",
}

# (nombre del catalogo, matriz, valor). La unidad la pone el catalogo.
HEMOGRAMA_MARZO = [
    ("Hemoglobina", "sangre", 13.8),          # 10.9 ajustado -> anemia moderada
    ("Hematocrito", "sangre", 41.2),
    ("Hematíes", "sangre", 4.55),
    ("Volumen Corpuscular Medio", "sangre", 88.4),
    ("Hemoglobina Corpuscular Media", "sangre", 27.9),
    ("Concentración Hb Corpuscular Media", "sangre", 33.5),
    ("RDW-CV", "sangre", 13.8),
    ("Leucocitos", "sangre", 6.8),
    ("Segmentados P.", "sangre", 58.0),
    ("Linfocitos P.", "sangre", 31.0),
    ("Monocitos P.", "sangre", 7.0),
    ("Eosinofilos P.", "sangre", 3.0),
    ("Basofilos P.", "sangre", 0.6),
    ("Plaquetas", "sangre", 268.0),
    ("Volumen Plaquetario Medio", "sangre", 9.4),
]

BIOQUIMICA_MARZO = [
    ("Glucosa", "sangre", 92.0),              # normal
    ("Colesterol Total", "sangre", 212.0),    # sobre 199: fuera
    ("HDL Colesterol", "sangre", 44.0),       # bajo 50: fuera
    ("LDL Colesterol", "sangre", 128.0),      # sobre 99: fuera
    ("Triglicéridos", "sangre", 168.0),       # sobre 159: fuera
    ("Ferritina Sérica", "sangre", 11.5),     # bajo 15: deficiencia de hierro
]

HEMOGRAMA_JULIO = [
    ("Hemoglobina", "sangre", 14.6),          # 11.7 ajustado -> anemia leve
    ("Hematocrito", "sangre", 43.0),
    ("Hematíes", "sangre", 4.72),
    ("Volumen Corpuscular Medio", "sangre", 89.1),
    ("Hemoglobina Corpuscular Media", "sangre", 28.6),
    ("Concentración Hb Corpuscular Media", "sangre", 33.9),
    ("RDW-CV", "sangre", 13.2),
    ("Leucocitos", "sangre", 6.2),
    ("Segmentados P.", "sangre", 56.0),
    ("Linfocitos P.", "sangre", 33.0),
    ("Monocitos P.", "sangre", 7.5),
    ("Eosinofilos P.", "sangre", 2.8),
    ("Basofilos P.", "sangre", 0.5),
    ("Plaquetas", "sangre", 279.0),
    ("Volumen Plaquetario Medio", "sangre", 9.1),
]

BIOQUIMICA_JULIO = [
    ("Glucosa", "sangre", 88.0),
    ("Colesterol Total", "sangre", 186.0),    # ya dentro
    ("HDL Colesterol", "sangre", 53.0),       # ya dentro
    ("LDL Colesterol", "sangre", 96.0),       # ya dentro
    ("Triglicéridos", "sangre", 132.0),       # ya dentro
    ("Ferritina Sérica", "sangre", 24.0),     # ya dentro
]

SIGNOS_VITALES = [
    ("Presión Sistólica", "clinico", 128.0),  # dispara umbral_alerta (>= 120)
    ("Presión Diastólica", "clinico", 82.0),  # dispara umbral_alerta (>= 80)
    ("Frecuencia Cardiaca", "clinico", 74.0),
    ("Frecuencia Respiratoria", "clinico", 17.0),
    # 91% a 4 373 msnm es esperable, pero el rango cargado vale a nivel del mar y
    # la base lo declara asi en el mensaje de su alerta. Es el pendiente abierto
    # N.5 de la base validada, y este valor lo deja a la vista.
    ("Saturación O2", "clinico", 91.0),
    ("Temperatura", "clinico", 36.8),
    ("Perímetro Abdominal", "clinico", 84.0),  # sobre 79: riesgo metabolico
]

DOCUMENTOS = [
    {
        "id": f"{PREFIJO_DOCUMENTO}laboratorio-2026-03-10",
        "tipo": "laboratorio",
        "fuente_obtencion": "foto",
        "institucion": 'LABORATORIO CLÍNICO "MÁS SALUD"',
        "fecha_documento": "2026-03-10",
        "archivo": "relleno/2026-03-10_laboratorio.jpg",
        "estudios": [
            ("hematologia", "Hemograma completo", HEMOGRAMA_MARZO),
            ("bioquimica", "Perfil bioquimico y ferritina", BIOQUIMICA_MARZO),
        ],
    },
    {
        "id": f"{PREFIJO_DOCUMENTO}laboratorio-2026-07-18",
        "tipo": "laboratorio",
        "fuente_obtencion": "foto",
        "institucion": 'LABORATORIO CLÍNICO "MÁS SALUD"',
        "fecha_documento": "2026-07-18",
        "archivo": "relleno/2026-07-18_laboratorio.jpg",
        "estudios": [
            ("hematologia", "Hemograma completo", HEMOGRAMA_JULIO),
            ("bioquimica", "Perfil bioquimico y ferritina", BIOQUIMICA_JULIO),
        ],
    },
    {
        # origen_dato = 'ingreso_manual' en el catalogo: los signos vitales no se
        # leen de un documento, los escribe la persona. No hay archivo que citar.
        "id": f"{PREFIJO_DOCUMENTO}signos-2026-07-20",
        "tipo": "signos_vitales",
        "fuente_obtencion": "manual",
        "institucion": None,
        "fecha_documento": "2026-07-20",
        "archivo": "relleno/ingreso-manual",
        "estudios": [
            ("signos_vitales", "Control de signos vitales", SIGNOS_VITALES),
        ],
    },
]


def _id_estable(*partes: str) -> str:
    return str(uuid.uuid5(ESPACIO, "|".join(partes)))


def _biomarcador(conexion, nombre: str, matriz: str) -> tuple[int, str]:
    """Id y unidad del catalogo curado. Falla claro si la referencia no esta cargada."""
    fila = conexion.execute(
        """
        SELECT id, unidad_estandar FROM biomarcador
         WHERE nombre_normalizado = ? AND matriz = ?
        """,
        (referencia.normalizar_nombre(nombre), matriz),
    ).fetchone()
    if fila is None:
        raise SystemExit(
            f"El catalogo no tiene '{nombre}' ({matriz}). "
            "Corre primero herramientas\\cargar_referencia.py"
        )
    return int(fila["id"]), fila["unidad_estandar"]


def borrar(conexion) -> dict[str, int]:
    """Saca el usuario de relleno y todo lo que cuelga de el. No toca nada mas."""
    valores = conexion.execute(
        """
        DELETE FROM valor_extraido
         WHERE estudio_id IN (
                   SELECT e.id FROM estudio e
                     JOIN documento d ON d.id = e.documento_id
                    WHERE d.usuario_id = ?)
        """,
        (ID_USUARIO,),
    ).rowcount
    estudios = conexion.execute(
        """
        DELETE FROM estudio
         WHERE documento_id IN (SELECT id FROM documento WHERE usuario_id = ?)
        """,
        (ID_USUARIO,),
    ).rowcount
    documentos = conexion.execute(
        "DELETE FROM documento WHERE usuario_id = ?", (ID_USUARIO,)
    ).rowcount
    usuarios = conexion.execute("DELETE FROM usuario WHERE id = ?", (ID_USUARIO,)).rowcount
    return {
        "usuario": usuarios,
        "documentos": documentos,
        "estudios": estudios,
        "valores": valores,
    }


def sembrar(conexion) -> dict:
    distrito = conexion.execute(
        "SELECT nombre, provincia, altitud_msnm FROM distrito WHERE clave_norm = ?",
        (USUARIO["clave_distrito"],),
    ).fetchone()
    if distrito is None:
        raise SystemExit(
            f"El padron no tiene el distrito {USUARIO['clave_distrito']}. "
            "Corre primero herramientas\\cargar_referencia.py"
        )

    borrar(conexion)

    conexion.execute(
        """
        INSERT INTO usuario (
            id, fecha_nacimiento, sexo, distrito_residencia, condicion,
            clave_distrito_residencia, residencia_desde
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ID_USUARIO,
            USUARIO["fecha_nacimiento"],
            USUARIO["sexo"],
            USUARIO["distrito_texto"],
            USUARIO["condicion"],
            USUARIO["clave_distrito"],
            USUARIO["residencia_desde"],
        ),
    )

    total_valores = 0
    estudios_creados = []
    for documento in DOCUMENTOS:
        establecimiento = referencia.resolver_establecimiento(
            conexion, documento["institucion"], USUARIO["clave_distrito"]
        )
        conexion.execute(
            """
            INSERT INTO documento (
                id, usuario_id, tipo, fuente_obtencion, institucion_nombre,
                institucion_id, distrito, clave_norm, distrito_confianza,
                fecha_documento, archivo_ruta, estado_extraccion
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'procesado')
            """,
            (
                documento["id"],
                ID_USUARIO,
                documento["tipo"],
                documento["fuente_obtencion"],
                documento["institucion"],
                establecimiento["id"] if establecimiento else None,
                distrito["nombre"],
                USUARIO["clave_distrito"],
                "extraido",
                documento["fecha_documento"],
                documento["archivo"],
            ),
        )

        for categoria, nombre_estudio, valores in documento["estudios"]:
            estudio_id = _id_estable(documento["id"], categoria)
            conexion.execute(
                "INSERT INTO estudio (id, documento_id, categoria, nombre_estudio) "
                "VALUES (?, ?, ?, ?)",
                (estudio_id, documento["id"], categoria, nombre_estudio),
            )
            estudios_creados.append(estudio_id)
            for nombre, matriz, valor in valores:
                biomarcador_id, unidad = _biomarcador(conexion, nombre, matriz)
                conexion.execute(
                    """
                    INSERT INTO valor_extraido (
                        id, estudio_id, biomarcador_id, valor_numerico, unidad,
                        valor_crudo_texto, confianza_extraccion
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        _id_estable(estudio_id, nombre),
                        estudio_id,
                        biomarcador_id,
                        valor,
                        unidad,
                        f"{valor:g}",
                    ),
                )
                total_valores += 1

    ajustados = 0
    for estudio_id in estudios_creados:
        ajustados += repositorio.aplicar_ajuste_altitud(conexion, estudio_id)

    return {
        "distrito": f"{distrito['nombre']} ({distrito['provincia']}), "
                    f"{distrito['altitud_msnm']} msnm",
        "documentos": len(DOCUMENTOS),
        "estudios": len(estudios_creados),
        "valores": total_valores,
        "valores_ajustados": ajustados,
    }


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument(
        "--borrar", action="store_true", help="elimina el usuario de relleno y sus datos"
    )
    argumentos = analizador.parse_args()

    basedatos.inicializar()
    conexion = basedatos.conectar()
    try:
        if argumentos.borrar:
            with conexion:
                borrado = borrar(conexion)
            print("Usuario de relleno eliminado:")
            for clave, n in borrado.items():
                print(f"  {clave:12} {n}")
            return 0

        with conexion:
            resumen = sembrar(conexion)

        print(f"Usuario de relleno: {ID_USUARIO}")
        print(f"  nacimiento {USUARIO['fecha_nacimiento']} · sexo {USUARIO['sexo']} · "
              f"{USUARIO['condicion']}")
        print(f"  residencia {resumen['distrito']} desde {USUARIO['residencia_desde']}")
        print(f"  documentos {resumen['documentos']} · estudios {resumen['estudios']} · "
              f"valores {resumen['valores']}")
        print(f"  valores con ajuste por altitud: {resumen['valores_ajustados']}")

        print()
        print("Evaluacion segun v_evaluacion (valor crudo -> ajustado -> clasificacion)")
        filas = conexion.execute(
            """
            SELECT biomarcador, valor_crudo, factor_ajuste, valor_evaluado,
                   clasificacion, estado_ajuste, respaldo
              FROM v_evaluacion
             WHERE usuario_id = ?
             ORDER BY biomarcador
            """,
            (ID_USUARIO,),
        ).fetchall()
        for fila in filas:
            factor = "-" if fila["factor_ajuste"] is None else f"-{fila['factor_ajuste']}"
            print(
                f"  {fila['biomarcador'][:32]:32} {fila['valor_crudo']:>8} {factor:>6} "
                f"{fila['valor_evaluado']:>8}  {fila['clasificacion']:9} "
                f"{fila['estado_ajuste']:22} {fila['respaldo'][:38]}"
            )
        print(f"  ({len(filas)} valores con rango aplicable; la vista solo trae los que caen "
              "dentro de un tramo definido)")
        return 0
    finally:
        conexion.close()


if __name__ == "__main__":
    raise SystemExit(main())
