"""Cliente propio para el MCP de Stitch, porque el servidor no carga en Claude Code.

Motivo
------
El MCP de Stitch queda instalado y conecta bien, pero Claude Code no puede cargar
sus herramientas: dos de ellas declaran una referencia de esquema rota.

    can't resolve reference #/$defs/ScreenInstance from id #

Las herramientas `create_design_system_from_design_md` y `apply_design_system`
apuntan a `#/$defs/ScreenInstance`, pero su esquema solo declara
`SelectedScreenInstance`. Es un error del lado de Stitch. Claude Code valida
todos los esquemas al cargar y descarta el conjunto entero si uno no resuelve.

Este cliente habla el mismo protocolo por HTTP, sin pasar por esa validacion, y
permite bajar los disenos igual. Cuando Google corrija el esquema, el MCP
funcionara de forma nativa y este archivo se puede borrar.

Credenciales
------------
La clave se lee de `STITCH_API_KEY`, que vive en el archivo local de
credenciales (ver `app/credenciales.py`), fuera de la carpeta sincronizada.

Uso
---
    python herramientas/stitch.py herramientas
    python herramientas/stitch.py proyectos
    python herramientas/stitch.py pantallas <nombre_del_proyecto>
    python herramientas/stitch.py pantalla <nombre_de_la_pantalla>
    python herramientas/stitch.py llamar <herramienta> '<json de argumentos>'
    python herramientas/stitch.py bajar <nombre_del_proyecto> [carpeta_destino]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app import credenciales  # noqa: E402

URL = "https://stitch.googleapis.com/mcp"
PROTOCOLO = "2025-06-18"


class Stitch:
    """Sesion MCP contra Stitch por HTTP."""

    def __init__(self, clave: str | None = None):
        self.clave = clave or credenciales.obtener("STITCH_API_KEY")
        if not self.clave:
            raise SystemExit(
                "Falta STITCH_API_KEY. Guardarla con:\n"
                "  python -c \"import sys; sys.path.insert(0,'.'); "
                "from app import credenciales; credenciales.guardar('STITCH_API_KEY','TU_CLAVE')\""
            )
        self.sesion = requests.Session()
        self.cabeceras = {
            "X-Goog-Api-Key": self.clave,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        self._id = 0
        self._iniciada = False

    def _rpc(self, metodo: str, parametros: dict | None = None) -> dict:
        self._id += 1
        cuerpo: dict = {"jsonrpc": "2.0", "id": self._id, "method": metodo}
        if parametros is not None:
            cuerpo["params"] = parametros
        respuesta = self.sesion.post(URL, headers=self.cabeceras, json=cuerpo, timeout=180)
        if "mcp-session-id" in respuesta.headers:
            self.cabeceras["Mcp-Session-Id"] = respuesta.headers["mcp-session-id"]
        return self._parsear(respuesta.text)

    @staticmethod
    def _parsear(texto: str) -> dict:
        """El transporte puede responder JSON plano o SSE; se acepta cualquiera."""
        if texto.startswith(("event:", "data:")) or "\ndata:" in texto:
            lineas = [l[5:].strip() for l in texto.splitlines() if l.startswith("data:")]
            texto = lineas[-1] if lineas else texto
        try:
            return json.loads(texto)
        except json.JSONDecodeError:
            raise SystemExit(f"respuesta que no es JSON: {texto[:400]}")

    def iniciar(self) -> dict:
        if self._iniciada:
            return {}
        respuesta = self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOLO,
                "capabilities": {},
                "clientInfo": {"name": "lablens-stitch", "version": "1.0"},
            },
        )
        if "error" in respuesta:
            raise SystemExit(f"initialize fallo: {respuesta['error']}")
        self.sesion.post(
            URL,
            headers=self.cabeceras,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            timeout=60,
        )
        self._iniciada = True
        return respuesta.get("result", {})

    def herramientas(self) -> list[dict]:
        self.iniciar()
        respuesta = self._rpc("tools/list", {})
        if "error" in respuesta:
            raise SystemExit(f"tools/list fallo: {respuesta['error']}")
        return respuesta["result"].get("tools", [])

    def llamar(self, nombre: str, argumentos: dict | None = None) -> dict:
        """Invoca una herramienta y devuelve el contenido ya desempaquetado."""
        self.iniciar()
        respuesta = self._rpc("tools/call", {"name": nombre, "arguments": argumentos or {}})
        if "error" in respuesta:
            return {"error": respuesta["error"]}
        resultado = respuesta.get("result", {})
        # El contenido suele venir como bloques de texto con JSON dentro.
        bloques = []
        for bloque in resultado.get("content") or []:
            if bloque.get("type") == "text":
                texto = bloque.get("text", "")
                try:
                    bloques.append(json.loads(texto))
                except json.JSONDecodeError:
                    bloques.append(texto)
            else:
                bloques.append(bloque)
        if resultado.get("structuredContent"):
            return {"structured": resultado["structuredContent"], "contenido": bloques}
        return {"contenido": bloques, "es_error": resultado.get("isError", False)}

    # --- Envoltorios de conveniencia -------------------------------------
    # Ojo: `list_screens` y `get_screen` piden el id SIN el prefijo
    # `projects/`, mientras que `get_project` lo pide CON el prefijo. Es facil
    # equivocarse: con el valor mal formado el servicio responde
    # "Request contains an invalid argument" sin decir cual.

    @staticmethod
    def solo_id(referencia: str) -> str:
        """`projects/123` -> `123`. Acepta el id pelado sin tocarlo."""
        return referencia.rsplit("/", 1)[-1]

    def proyectos(self) -> list[dict]:
        respuesta = self.llamar("list_projects")
        return (respuesta.get("structured") or {}).get("projects") or []

    def proyecto(self, referencia: str) -> dict:
        nombre = referencia if referencia.startswith("projects/") else f"projects/{referencia}"
        return self.llamar("get_project", {"name": nombre})

    def pantallas(self, referencia: str) -> dict:
        return self.llamar("list_screens", {"projectId": self.solo_id(referencia)})

    def pantalla(self, proyecto: str, pantalla: str) -> dict:
        id_proyecto = self.solo_id(proyecto)
        id_pantalla = self.solo_id(pantalla)
        return self.llamar(
            "get_screen",
            {
                "name": f"projects/{id_proyecto}/screens/{id_pantalla}",
                "projectId": id_proyecto,
                "screenId": id_pantalla,
            },
        )

    def sistemas_de_diseno(self, referencia: str | None = None) -> dict:
        argumentos = {"projectId": self.solo_id(referencia)} if referencia else {}
        return self.llamar("list_design_systems", argumentos)


# ==========================================================================
# CLI
# ==========================================================================

def _imprimir(dato) -> None:
    print(json.dumps(dato, indent=2, ensure_ascii=False))


def main() -> int:
    analizador = argparse.ArgumentParser(description="Cliente MCP de Stitch para LabLens")
    sub = analizador.add_subparsers(dest="comando", required=True)

    sub.add_parser("herramientas", help="lista las herramientas y sus parametros")
    sub.add_parser("proyectos", help="lista los proyectos de Stitch")

    p = sub.add_parser("pantallas", help="lista las pantallas de un proyecto")
    p.add_argument("proyecto")

    p = sub.add_parser("pantalla", help="detalle de una pantalla")
    p.add_argument("pantalla")

    p = sub.add_parser("llamar", help="invoca cualquier herramienta")
    p.add_argument("herramienta")
    p.add_argument("argumentos", nargs="?", default="{}")

    p = sub.add_parser("bajar", help="guarda las pantallas de un proyecto en disco")
    p.add_argument("proyecto")
    p.add_argument("destino", nargs="?", default=str(RAIZ / "UI" / "stitch"))

    args = analizador.parse_args()
    cliente = Stitch()

    if args.comando == "herramientas":
        for h in cliente.herramientas():
            requeridos = (h.get("inputSchema") or {}).get("required") or []
            propiedades = list(((h.get("inputSchema") or {}).get("properties") or {}).keys())
            print(f"\n{h['name']}")
            print(f"  requiere: {requeridos}")
            print(f"  acepta:   {propiedades}")
        return 0

    if args.comando == "proyectos":
        for p in cliente.proyectos():
            tema = p.get("designTheme") or {}
            print(f"{p.get('name')}  titulo={p.get('title')!r}  "
                  f"dispositivo={p.get('deviceType')}  actualizado={p.get('updateTime')}")
            print(f"    tema: {tema.get('bodyFontFamily')} / {tema.get('colorMode')} / "
                  f"{tema.get('customColor')}  pantallas={len(p.get('screenInstances') or [])}")
        return 0

    if args.comando == "pantallas":
        _imprimir(cliente.pantallas(args.proyecto))
        return 0

    if args.comando == "pantalla":
        proyecto, _, pantalla = args.pantalla.partition(":")
        if not pantalla:
            raise SystemExit("usar formato <id_proyecto>:<id_pantalla>")
        _imprimir(cliente.pantalla(proyecto, pantalla))
        return 0

    if args.comando == "llamar":
        _imprimir(cliente.llamar(args.herramienta, json.loads(args.argumentos)))
        return 0

    if args.comando == "bajar":
        return bajar(cliente, args.proyecto, Path(args.destino))

    return 1


def _slug(texto: str) -> str:
    """Nombre de archivo seguro a partir del titulo de la pantalla."""
    plano = unicodedata.normalize("NFD", texto or "sin-titulo")
    plano = "".join(c for c in plano if unicodedata.category(c) != "Mn").lower()
    plano = re.sub(r"[^a-z0-9]+", "-", plano).strip("-")
    return plano or "sin-titulo"


def bajar(cliente: Stitch, referencia: str, destino: Path) -> int:
    """Guarda en disco el sistema de diseno y todas las pantallas del proyecto."""
    id_proyecto = cliente.solo_id(referencia)
    destino.mkdir(parents=True, exist_ok=True)
    dir_html = destino / "html"
    dir_img = destino / "capturas"
    dir_html.mkdir(exist_ok=True)
    dir_img.mkdir(exist_ok=True)

    proyecto = cliente.proyecto(id_proyecto)
    datos = (proyecto.get("structured") or {})
    tema = datos.get("designTheme") or {}
    if tema.get("designMd"):
        (destino / "DESIGN.md").write_text(tema["designMd"], encoding="utf-8")
        print(f"DESIGN.md -> {destino / 'DESIGN.md'} ({len(tema['designMd'])} chars)")

    # El tema sin el designMd, que ya se guardo aparte
    (destino / "tema.json").write_text(
        json.dumps({k: v for k, v in tema.items() if k != "designMd"}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    respuesta = cliente.pantallas(id_proyecto)
    pantallas = (respuesta.get("structured") or {}).get("screens") or []
    if not pantallas:
        print(f"sin pantallas. Respuesta: {json.dumps(respuesta, ensure_ascii=False)[:400]}")
        return 1

    indice = []
    for numero, pantalla in enumerate(pantallas, start=1):
        titulo = pantalla.get("title") or f"pantalla-{numero}"
        base = f"{numero:02d}_{_slug(titulo)}"
        registro = {
            "orden": numero,
            "titulo": titulo,
            "id": cliente.solo_id(pantalla.get("name", "")),
            "dispositivo": pantalla.get("deviceType"),
            "ancho": pantalla.get("width"),
            "alto": pantalla.get("height"),
        }

        url_html = (pantalla.get("htmlCode") or {}).get("downloadUrl")
        if url_html:
            try:
                r = cliente.sesion.get(url_html, timeout=120)
                r.raise_for_status()
                ruta = dir_html / f"{base}.html"
                ruta.write_bytes(r.content)
                registro["html"] = f"html/{ruta.name}"
                registro["html_bytes"] = len(r.content)
            except requests.RequestException as error:
                registro["html_error"] = str(error)[:120]

        url_img = (pantalla.get("screenshot") or {}).get("downloadUrl")
        if url_img:
            try:
                r = cliente.sesion.get(url_img, timeout=120)
                r.raise_for_status()
                ruta = dir_img / f"{base}.png"
                ruta.write_bytes(r.content)
                registro["captura"] = f"capturas/{ruta.name}"
                registro["captura_bytes"] = len(r.content)
            except requests.RequestException as error:
                registro["captura_error"] = str(error)[:120]

        indice.append(registro)
        print(f"  {numero:2d}. {titulo:34s} html={registro.get('html_bytes', 0):>7} B  "
              f"png={registro.get('captura_bytes', 0):>8} B")

    (destino / "indice.json").write_text(
        json.dumps({"proyecto": id_proyecto, "pantallas": indice}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n{len(indice)} pantallas en {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
