"""Arranque de LabLens en un equipo nuevo: prepara el entorno y levanta el servidor.

    python iniciar.py                 # prepara todo y arranca (HTTPS, puerto 8443)
    python iniciar.py --puerto 9000   # las opciones sueltas pasan a servidor.py
    python iniciar.py --solo-preparar # deja el equipo listo y no arranca

Que hace, en orden:

1. Verifica la version de Python (hace falta 3.10 o mas nueva).
2. Crea el entorno virtual `.venv` si no existe. Si existe pero no funciona en
   este equipo (caso tipico: la carpeta se copio o se sincronizo desde otra PC),
   lo borra y lo vuelve a crear. El entorno es desechable: se reconstruye entero
   desde `requirements.txt`.
3. Descarga e instala las dependencias. Recuerda la huella de `requirements.txt`
   en `.venv/.lablens-instalado.json`, asi que en los arranques siguientes no
   vuelve a bajar nada salvo que la lista cambie.
4. Carga los datos de referencia (distritos, RENIPRESS, rangos MINSA) desde
   `BasedeDatos_Preparada/qhali.db` la primera vez, porque `datos/` no viaja con
   el repositorio y sin esa carga la app arranca con la base vacia.
5. Arranca `servidor.py` con el Python del entorno.

Este archivo usa solo la biblioteca estandar: es lo unico que se puede ejecutar
antes de que exista el entorno.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

VERSION_MINIMA = (3, 10)

RAIZ = Path(__file__).resolve().parent
DIR_VENV = RAIZ / ".venv"
REQUISITOS = RAIZ / "requirements.txt"
SERVIDOR = RAIZ / "servidor.py"
CARGADOR_REFERENCIA = RAIZ / "herramientas" / "cargar_referencia.py"
BASE_VALIDADA = RAIZ / "BasedeDatos_Preparada" / "qhali.db"
BASE_APP = RAIZ / "datos" / "qhali.sqlite3"
MARCA = DIR_VENV / ".lablens-instalado.json"

# Modulos que se importan para comprobar que la instalacion quedo sana. El
# nombre de import no siempre es el del paquete (opencv-python-headless -> cv2),
# por eso la lista es explicita y no se deduce de requirements.txt.
MODULOS_CLAVE = (
    "fastapi",
    "uvicorn",
    "cv2",
    "numpy",
    "cryptography",
    "qrcode",
    "requests",
    "reportlab",
)


# ==========================================================================
# Salida por consola
# ==========================================================================

def _escribir(lineas):
    """Imprime y vacia el buffer.

    Sin el vaciado, los mensajes de este script salen despues de los de pip: la
    salida de Python va a un buffer y la del subproceso al terminal directo.
    """
    for linea in lineas:
        print(linea)
    sys.stdout.flush()


def titulo(texto):
    _escribir(["", "-" * 62, "  " + texto, "-" * 62])


def paso(texto):
    _escribir(["  * " + texto])


def aviso(texto):
    _escribir(["  ! " + texto])


# ==========================================================================
# Entorno virtual
# ==========================================================================

def python_del_entorno():
    """Ruta del interprete dentro de `.venv` segun el sistema operativo."""
    if sys.platform == "win32":
        return DIR_VENV / "Scripts" / "python.exe"
    return DIR_VENV / "bin" / "python"


def verificar_version_de_python():
    if sys.version_info < VERSION_MINIMA:
        actual = "%d.%d.%d" % sys.version_info[:3]
        minima = "%d.%d" % VERSION_MINIMA
        _escribir([
            "",
            "  LabLens necesita Python " + minima + " o mas nuevo.",
            "  Este interprete es " + actual + " (" + sys.executable + ").",
            "  Descargalo en https://www.python.org/downloads/ y volve a intentar.",
            "",
        ])
        return False
    return True


def advertir_ruta_larga():
    """Avisa si la carpeta esta tan adentro que Windows no podra abrir las DLL.

    Windows corta las rutas en 260 caracteres salvo que se habiliten las rutas
    largas. Dentro de `.venv` se llega facil a 150 caracteres de anidamiento, asi
    que una carpeta base larga rompe la carga de librerias compiladas (cryptography,
    opencv) con un error que no dice de donde viene.
    """
    if sys.platform != "win32" or len(str(RAIZ)) <= 120:
        return
    aviso("La ruta de la carpeta es muy larga (" + str(len(str(RAIZ))) + " caracteres).")
    aviso("Windows puede fallar al cargar las librerias con un error de nombre")
    aviso("de archivo demasiado largo. Conviene mover LabLens mas cerca de la")
    aviso("raiz del disco, por ejemplo C:\\LabLens.")


def entorno_funciona(python):
    """True si el interprete del entorno existe y corre en este equipo.

    Un `.venv` copiado desde otra PC (por ejemplo, arrastrado por OneDrive)
    queda apuntando a un Python que aqui no existe: la carpeta esta, pero el
    interprete no arranca.
    """
    if not python.exists():
        return False
    try:
        completado = subprocess.run(
            [str(python), "-c", "import sys; print(sys.version)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError:
        return False
    return completado.returncode == 0


def crear_entorno(python):
    """Deja `.venv` utilizable. Lo recrea si esta roto."""
    if DIR_VENV.exists():
        if entorno_funciona(python):
            paso("Entorno virtual: ya existe en " + str(DIR_VENV))
            return True
        aviso("El entorno .venv no funciona en este equipo (viene de otra PC).")
        aviso("Se borra y se reconstruye desde requirements.txt.")
        try:
            shutil.rmtree(DIR_VENV)
        except OSError as error:
            aviso("No se pudo borrar " + str(DIR_VENV) + ": " + str(error))
            aviso("Cerra los programas que lo esten usando y volve a intentar.")
            return False

    paso("Creando el entorno virtual en " + str(DIR_VENV) + " ...")
    completado = subprocess.run([sys.executable, "-m", "venv", str(DIR_VENV)])
    if completado.returncode != 0 or not entorno_funciona(python):
        aviso("No se pudo crear el entorno virtual.")
        if sys.platform.startswith("linux"):
            aviso("En Debian/Ubuntu falta el paquete: sudo apt install python3-venv")
        return False
    paso("Entorno virtual creado.")
    return True


# ==========================================================================
# Dependencias
# ==========================================================================

def huella_actual():
    """Identifica la instalacion: que lista se instalo y con que interprete."""
    return {
        "requisitos_sha256": hashlib.sha256(REQUISITOS.read_bytes()).hexdigest(),
        "python": "%d.%d" % sys.version_info[:2],
        "plataforma": sys.platform,
    }


def huella_guardada():
    try:
        return json.loads(MARCA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def dependencias_importables(python):
    codigo = "import " + ", ".join(MODULOS_CLAVE)
    completado = subprocess.run(
        [str(python), "-c", codigo],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completado.returncode == 0


def instalar_dependencias(python, forzar=False):
    if not REQUISITOS.exists():
        aviso("Falta " + str(REQUISITOS) + ".")
        return False

    esperada = huella_actual()
    if not forzar and huella_guardada() == esperada and dependencias_importables(python):
        paso("Dependencias: al dia (nada que descargar).")
        return True

    if forzar:
        paso("Reinstalando las dependencias por pedido explicito ...")
    elif huella_guardada() is None:
        paso("Primera instalacion: descargando las dependencias ...")
    else:
        paso("La lista de dependencias cambio o falta algo: actualizando ...")

    # pip viejo no entiende las ruedas nuevas. Si esta actualizacion falla no se
    # aborta: puede que la version incluida ya alcance.
    subprocess.run(
        [str(python), "-m", "pip", "install", "--upgrade", "--quiet",
         "pip", "setuptools", "wheel"],
    )

    comando = [str(python), "-m", "pip", "install", "--disable-pip-version-check",
               "--requirement", str(REQUISITOS)]
    if forzar:
        comando[4:4] = ["--upgrade", "--force-reinstall"]

    _escribir([""])
    completado = subprocess.run(comando)
    _escribir([""])
    if completado.returncode != 0:
        aviso("La instalacion de dependencias fallo.")
        aviso("Revisa la conexion a internet. Si la red usa un espejo interno,")
        aviso("define PIP_INDEX_URL antes de correr este script.")
        return False

    if not dependencias_importables(python):
        aviso("Las dependencias se instalaron pero no se pueden importar.")
        aviso("Proba de nuevo con: python iniciar.py --reinstalar")
        return False

    try:
        MARCA.write_text(json.dumps(esperada, indent=2), encoding="utf-8")
    except OSError:
        pass  # La marca es una optimizacion; sin ella solo se revisa mas seguido.
    paso("Dependencias instaladas.")
    return True


# ==========================================================================
# Datos de referencia
# ==========================================================================

def cargar_referencia(python, forzar=False):
    """Llena la base local con los datos validados del equipo.

    `datos/` no viaja con el repositorio, asi que en un equipo nuevo la base no
    existe y hay que construirla desde `BasedeDatos_Preparada/qhali.db`.
    """
    if BASE_APP.exists() and not forzar:
        paso("Datos de referencia: la base ya existe en " + str(BASE_APP) + ".")
        return True

    if not BASE_VALIDADA.exists():
        aviso("No esta " + str(BASE_VALIDADA) + ": la app arranca con la base vacia.")
        aviso("Sin distritos ni rangos no hay ajuste por altitud ni evaluacion.")
        return True  # No es motivo para no arrancar.

    paso("Cargando los datos de referencia (distritos, RENIPRESS, rangos) ...")
    _escribir([""])
    completado = subprocess.run([str(python), str(CARGADOR_REFERENCIA)], cwd=str(RAIZ))
    _escribir([""])
    if completado.returncode != 0:
        aviso("La carga de referencia fallo. La app arranca igual, con la base vacia.")
        aviso("Se puede reintentar con: python iniciar.py --cargar-referencia")
        return True
    paso("Datos de referencia cargados.")
    return True


# ==========================================================================
# Arranque
# ==========================================================================

def arrancar_servidor(python, extras):
    titulo("Arrancando el servidor")
    try:
        return subprocess.call([str(python), str(SERVIDOR)] + extras, cwd=str(RAIZ))
    except KeyboardInterrupt:
        return 0


def main():
    analizador = argparse.ArgumentParser(
        description="Prepara el entorno de LabLens y arranca el servidor.",
        epilog="Las opciones que no aparecen aca se pasan tal cual a servidor.py "
               "(--puerto, --http, --recargar).",
        allow_abbrev=False,  # para que --recargar no se confunda con --cargar-referencia
    )
    analizador.add_argument("--solo-preparar", action="store_true",
                            help="instala todo y no arranca el servidor")
    analizador.add_argument("--reinstalar", action="store_true",
                            help="vuelve a bajar las dependencias aunque esten al dia")
    analizador.add_argument("--cargar-referencia", action="store_true",
                            help="recarga los datos de referencia aunque la base exista")
    analizador.add_argument("--sin-referencia", action="store_true",
                            help="no toca la base de datos")
    argumentos, extras = analizador.parse_known_args()

    _escribir(["", "=" * 62, "  LabLens - preparacion del equipo", "=" * 62])

    if not verificar_version_de_python():
        return 1

    titulo("1/3  Entorno virtual")
    advertir_ruta_larga()
    python = python_del_entorno()
    if not crear_entorno(python):
        return 1

    titulo("2/3  Dependencias")
    if not instalar_dependencias(python, forzar=argumentos.reinstalar):
        return 1

    titulo("3/3  Datos de referencia")
    if argumentos.sin_referencia:
        paso("Omitida por pedido explicito (--sin-referencia).")
    else:
        cargar_referencia(python, forzar=argumentos.cargar_referencia)

    if argumentos.solo_preparar:
        titulo("Listo")
        _escribir(["  El equipo quedo preparado. Para arrancar:",
                   "     python iniciar.py", ""])
        return 0

    return arrancar_servidor(python, extras)


if __name__ == "__main__":
    sys.exit(main())
