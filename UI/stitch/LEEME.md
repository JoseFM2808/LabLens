# Diseño bajado de Stitch

Contenido generado automáticamente. **No editar a mano**: se sobrescribe al
volver a sincronizar.

## Qué hay aquí

| Ruta | Qué es |
|---|---|
| `DESIGN.md` | Sistema de diseño completo: paleta, tipografía, formas, componentes. |
| `tema.json` | El mismo tema en JSON (fuente, modo de color, color base). |
| `indice.json` | Las pantallas con su id, título, tamaño y rutas de archivo. |
| `html/` | El HTML generado de cada pantalla. |
| `capturas/` | La captura PNG de cada pantalla. |

## Proyecto de origen

- Proyecto: `projects/17237519883750637887` — "Digital Design Concept"
- Dispositivo: MOBILE (780 px de ancho de diseño)
- Tema: Manrope, modo claro, color base `#a7c957`

## Pantallas

1. Dashboard Principal
2. Asistente LabLens
3. Detalle de Análisis
4. Historial Médico
5. Historial Médico (Con Contenido)
6. Escanear Documento
7. Análisis de Salud

## Cómo volver a sincronizar

```powershell
.\.venv\Scripts\python.exe herramientas\stitch.py bajar 17237519883750637887 "UI\stitch"
```

Otros comandos:

```powershell
.\.venv\Scripts\python.exe herramientas\stitch.py proyectos
.\.venv\Scripts\python.exe herramientas\stitch.py pantallas 17237519883750637887
.\.venv\Scripts\python.exe herramientas\stitch.py herramientas
```

## Por qué hay un cliente propio y no se usa el MCP directo

El MCP de Stitch está instalado (a nivel de usuario, en `~/.claude.json`) y
conecta bien, pero Claude Code no puede cargar sus herramientas:

```
can't resolve reference #/$defs/ScreenInstance from id #
```

Las herramientas `create_design_system_from_design_md` y `apply_design_system`
declaran una referencia a `#/$defs/ScreenInstance`, pero su esquema solo declara
`SelectedScreenInstance`. Es un error del lado de Stitch. Claude Code valida
todos los esquemas al cargar y descarta el conjunto entero si uno no resuelve,
así que ninguna de las 15 herramientas queda disponible.

`herramientas/stitch.py` habla el mismo protocolo por HTTP y no pasa por esa
validación. Cuando Google corrija el esquema, el MCP funcionará de forma nativa
y el cliente propio se puede borrar.

## Detalle que hace perder tiempo

`get_project` pide el nombre **con** prefijo (`projects/123`), pero
`list_screens` y `get_screen` piden el id **sin** prefijo (`123`). Si se manda
mal, el servicio responde `Request contains an invalid argument` sin indicar cuál.
`Stitch.solo_id()` normaliza esto.
