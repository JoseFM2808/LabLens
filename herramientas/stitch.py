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
import sys
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
        _imprimir(cliente.llamar("list_projects"))
        return 0

    if args.comando == "pantallas":
        _imprimir(cliente.llamar("list_screens", {"project": args.proyecto}))
        return 0

    if args.comando == "pantalla":
        _imprimir(cliente.llamar("get_screen", {"name": args.pantalla}))
        return 0

    if args.comando == "llamar":
        _imprimir(cliente.llamar(args.herramienta, json.loads(args.argumentos)))
        return 0

    if args.comando == "bajar":
        destino = Path(args.destino)
        destino.mkdir(parents=True, exist_ok=True)
        pantallas = cliente.llamar("list_screens", {"project": args.proyecto})
        (destino / "pantallas.json").write_text(
            json.dumps(pantallas, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"listado guardado en {destino / 'pantallas.json'}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
