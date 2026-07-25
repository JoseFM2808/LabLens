"""Lectura de credenciales sin variables de entorno.

Por que existe este modulo: en el equipo de la prueba no se pueden definir
variables de entorno, y el proyecto vive dentro de una carpeta sincronizada
(`OneDrive - FuXion Biotech`). Guardar la clave en un archivo del proyecto la
subiria a la nube corporativa, que es justo lo que no debe pasar.

Solucion: un archivo de credenciales **fuera del arbol sincronizado**, en la
carpeta local del usuario. Nunca se sincroniza, nunca entra al repositorio.

    Windows:  %LOCALAPPDATA%\\LabLens\\credenciales.env
    Otros:    ~/.config/lablens/credenciales.env

Formato: una clave por linea, ``NOMBRE=valor``. Las lineas vacias y las que
empiezan con ``#`` se ignoran.

Orden de busqueda de cada credencial:
    1. variable de entorno (sigue funcionando si se puede definir)
    2. archivo de credenciales local

Advertencia: el archivo queda en texto plano. Para la Fase 2, junto con el paso
a SQLCipher, conviene moverlo al Administrador de credenciales de Windows o a un
gestor de secretos.
"""

from __future__ import annotations

import os
from pathlib import Path


def ruta_archivo() -> Path:
    """Ubicacion del archivo de credenciales, fuera de cualquier carpeta sincronizada."""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "LabLens" / "credenciales.env"
    return Path.home() / ".config" / "lablens" / "credenciales.env"


def _limpiar(valor: str) -> str:
    """Quita comillas y el prefijo `Bearer`, que es del header y no de la clave.

    Es habitual copiar la credencial junto con el `Bearer ` del ejemplo de la
    documentacion. Si se guardara asi, la peticion terminaria enviando
    `Authorization: Bearer Bearer nvapi-...` y el servicio responderia 401.
    """
    valor = valor.strip().strip('"').strip("'").strip()
    if valor.lower().startswith("bearer "):
        valor = valor[7:].strip()
    return valor


def leer_archivo() -> dict[str, str]:
    """Contenido del archivo de credenciales. Diccionario vacio si no existe."""
    ruta = ruta_archivo()
    if not ruta.exists():
        return {}
    valores: dict[str, str] = {}
    try:
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            nombre, _, valor = linea.partition("=")
            limpio = _limpiar(valor)
            if limpio:
                valores[nombre.strip()] = limpio
    except OSError:
        return {}
    return valores


def obtener(*nombres: str) -> str | None:
    """Primer valor encontrado entre los nombres dados.

    Revisa las variables de entorno y despues el archivo local. Permite aceptar
    varios alias de la misma credencial.
    """
    for nombre in nombres:
        valor = os.environ.get(nombre, "")
        if valor.strip():
            return _limpiar(valor)
    del_archivo = leer_archivo()
    for nombre in nombres:
        if nombre in del_archivo:
            return del_archivo[nombre]
    return None


def guardar(nombre: str, valor: str) -> Path:
    """Escribe o reemplaza una credencial en el archivo local.

    Se preservan las demas lineas. En Windows se restringen los permisos para
    que solo el usuario actual pueda leer el archivo.
    """
    ruta = ruta_archivo()
    ruta.parent.mkdir(parents=True, exist_ok=True)

    lineas: list[str] = []
    reemplazada = False
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            if linea.strip().startswith(f"{nombre}=") or linea.strip().startswith(f"{nombre} ="):
                lineas.append(f"{nombre}={_limpiar(valor)}")
                reemplazada = True
            else:
                lineas.append(linea)
    if not reemplazada:
        if not lineas:
            lineas.append("# Credenciales locales de LabLens. NO copiar a Drive ni al repositorio.")
        lineas.append(f"{nombre}={_limpiar(valor)}")

    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    _restringir_permisos(ruta)
    return ruta


def _restringir_permisos(ruta: Path) -> None:
    """Deja el archivo legible solo por el usuario actual."""
    try:
        if os.name == "nt":
            import subprocess

            usuario = os.environ.get("USERNAME", "")
            if usuario:
                subprocess.run(
                    ["icacls", str(ruta), "/inheritance:r", "/grant:r", f"{usuario}:F"],
                    capture_output=True,
                    check=False,
                    timeout=15,
                )
        else:
            ruta.chmod(0o600)
    except Exception:  # noqa: BLE001 - los permisos son un extra, no deben frenar nada
        pass


def estado() -> dict:
    """Resumen para diagnostico. Nunca incluye el valor de ninguna credencial."""
    ruta = ruta_archivo()
    return {
        "archivo": str(ruta),
        "existe": ruta.exists(),
        "fuera_de_carpeta_sincronizada": "OneDrive" not in str(ruta),
        "credenciales": sorted(leer_archivo().keys()),
    }
