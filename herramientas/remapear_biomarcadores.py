"""Reengancha al catalogo curado los biomarcadores que el scanner creo sueltos.

Por que hace falta
------------------
Antes de que existiera el emparejamiento, cada escaneo creaba una fila nueva en
`biomarcador` con `sistema_corporal = 'sin_clasificar'`. Esas filas no tienen
rango de referencia, asi que sus valores nunca se comparaban contra nada: la
vista Analisis mostraba "sin rango con el que comparar" para casi todo.

Este script recorre las filas sueltas, busca su equivalente en el catalogo
curado con la misma logica que usan las capturas nuevas
(`referencia.buscar_en_catalogo` + `catalogo.SINONIMOS`), repunta los
`valor_extraido` al biomarcador correcto y borra la fila duplicada.

La matriz se deduce por documento, no por biomarcador suelto: `GLUCOSA` de un
examen de orina no es la glucosa en sangre, y solo mirando el resto del examen
se sabe cual es cual.

Uso
---
    python herramientas/remapear_biomarcadores.py            # simulacion
    python herramientas/remapear_biomarcadores.py --aplicar  # escribe

Sin `--aplicar` no toca nada: imprime que haria.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app import basedatos, catalogo, referencia  # noqa: E402


def matrices_por_documento(conexion) -> dict[str, str | None]:
    """Matriz deducida de cada documento a partir de todos sus biomarcadores."""
    nombres = defaultdict(list)
    for fila in conexion.execute(
        """
        SELECT d.id AS documento_id, b.nombre
        FROM valor_extraido v
        JOIN estudio e ON e.id = v.estudio_id
        JOIN documento d ON d.id = e.documento_id
        JOIN biomarcador b ON b.id = v.biomarcador_id
        """
    ):
        nombres[fila["documento_id"]].append(fila["nombre"])
    return {doc: catalogo.inferir_matriz(lista) for doc, lista in nombres.items()}


def plan(conexion) -> tuple[list[dict], list[dict]]:
    """Calcula que valores se repuntan y cuales se quedan sin catalogo."""
    matrices = matrices_por_documento(conexion)

    valores = conexion.execute(
        """
        SELECT v.id AS valor_id, v.unidad, v.biomarcador_id,
               b.nombre, b.sistema_corporal,
               e.documento_id
        FROM valor_extraido v
        JOIN estudio e ON e.id = v.estudio_id
        JOIN biomarcador b ON b.id = v.biomarcador_id
        WHERE b.sistema_corporal = 'sin_clasificar'
        """
    ).fetchall()

    cambios, sin_match = [], []
    for fila in valores:
        matriz = matrices.get(fila["documento_id"])
        destino = referencia.buscar_en_catalogo(
            conexion, fila["nombre"], fila["unidad"], matriz
        )
        registro = {
            "valor_id": fila["valor_id"],
            "nombre": fila["nombre"],
            "unidad": fila["unidad"],
            "matriz": matriz,
            "origen_id": fila["biomarcador_id"],
        }
        if destino:
            cambios.append({**registro, "destino_id": destino["id"], "destino": destino["nombre"]})
        else:
            sin_match.append(registro)
    return cambios, sin_match


def aplicar(conexion, cambios: list[dict]) -> int:
    """Repunta los valores y borra las filas duplicadas que quedan sin uso."""
    for cambio in cambios:
        conexion.execute(
            "UPDATE valor_extraido SET biomarcador_id = ? WHERE id = ?",
            (cambio["destino_id"], cambio["valor_id"]),
        )
        # El nombre tal como venia impreso se guarda como sinonimo: la proxima
        # captura lo reconoce sin pasar por aqui.
        referencia_fila = conexion.execute(
            "SELECT sinonimos FROM biomarcador WHERE id = ?", (cambio["destino_id"],)
        ).fetchone()
        try:
            actuales = json.loads(referencia_fila["sinonimos"] or "[]")
        except (ValueError, TypeError):
            actuales = []
        ya = {catalogo.normalizar(str(s)) for s in actuales}
        if catalogo.normalizar(cambio["nombre"]) not in ya:
            actuales.append(cambio["nombre"])
            conexion.execute(
                "UPDATE biomarcador SET sinonimos = ? WHERE id = ?",
                (json.dumps(actuales, ensure_ascii=False), cambio["destino_id"]),
            )

    borradas = conexion.execute(
        """
        DELETE FROM biomarcador
        WHERE sistema_corporal = 'sin_clasificar'
          AND id NOT IN (SELECT DISTINCT biomarcador_id FROM valor_extraido)
        """
    ).rowcount
    return borradas


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--aplicar", action="store_true", help="escribe los cambios")
    args = analizador.parse_args()

    basedatos.inicializar()
    conexion = basedatos.conectar()
    try:
        cambios, sin_match = plan(conexion)

        print(f"== {len(cambios)} valores se reenganchan al catalogo ==")
        resumen: dict[str, dict] = {}
        for c in cambios:
            clave = f"{c['nombre']} -> {c['destino']}"
            entrada = resumen.setdefault(clave, {"n": 0, "matriz": c["matriz"]})
            entrada["n"] += 1
        for clave, dato in sorted(resumen.items()):
            print(f"  {dato['n']:3d}x  {clave}   (matriz {dato['matriz']})")

        print(f"\n== {len(sin_match)} valores siguen sin equivalente en el catalogo ==")
        pendientes: dict[str, int] = {}
        for s in sin_match:
            pendientes[s["nombre"]] = pendientes.get(s["nombre"], 0) + 1
        for nombre, n in sorted(pendientes.items()):
            print(f"  {n:3d}x  {nombre}")

        if not args.aplicar:
            print("\nSimulacion. Reejecutar con --aplicar para escribir.")
            return 0

        with conexion:
            borradas = aplicar(conexion, cambios)
        print(f"\nAplicado: {len(cambios)} valores repuntados, {borradas} filas duplicadas borradas.")
        return 0
    finally:
        conexion.close()


if __name__ == "__main__":
    sys.exit(main())
