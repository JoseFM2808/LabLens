"""Servidor LabLens: camara web, deteccion en vivo y captura enderezada."""

from __future__ import annotations

import base64
import json
import traceback
from datetime import datetime

from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import (
    __version__,
    almacenamiento,
    analisis,
    basedatos,
    detector,
    enderezar,
    extraccion,
    formatos,
    integraciones,
    repositorio,
)

DIR_ESTATICOS = almacenamiento.RAIZ / "app" / "estaticos"

# Debe existir antes de montar StaticFiles.
almacenamiento.asegurar_directorios()
repositorio.asegurar_directorios()
# Crea datos/qhali.sqlite3 con todas las tablas si aun no existe. Idempotente.
basedatos.inicializar()

app = FastAPI(title="LabLens", version=__version__)


@app.get("/")
def inicio() -> FileResponse:
    return FileResponse(DIR_ESTATICOS / "index.html")


@app.get("/api/config")
def config() -> dict:
    """Datos que el frontend necesita al arrancar."""
    return {
        "version": __version__,
        "formatos": formatos.listar(),
        "formato_por_defecto": formatos.FORMATO_POR_DEFECTO,
        "modos": list(enderezar.MODOS),
        "area_minima": detector.AREA_MINIMA,
        "extraccion": {
            "activa": extraccion.esta_configurada(),
            "modelo": extraccion.modelo() if extraccion.esta_configurada() else None,
        },
        "usuario_configurado": repositorio.usuario_local() is not None,
        "sexos": list(repositorio.SEXOS_VALIDOS),
    }


@app.get("/api/usuario")
def api_usuario_leer() -> dict:
    """Usuario local (sin PII). `configurado` en false = falta registrarlo."""
    usuario = repositorio.usuario_local()
    return {"configurado": usuario is not None, "usuario": usuario}


@app.post("/api/usuario")
def api_usuario_guardar(
    fecha_nacimiento: str = Form(...),
    sexo: str = Form(...),
    distrito_residencia: str = Form(""),
) -> JSONResponse:
    """Registra o actualiza el usuario local.

    Solo demografia minima: la fecha de nacimiento y el sexo son obligatorios
    porque los rangos de referencia de la OMS dependen de edad y sexo. No se
    guarda ningun nombre ni documento de identidad.
    """
    try:
        usuario = repositorio.guardar_usuario(
            fecha_nacimiento.strip(), sexo.strip(), distrito_residencia.strip() or None
        )
    except ValueError as error:
        return JSONResponse({"ok": False, "error": str(error)}, status_code=400)
    return JSONResponse({"ok": True, "usuario": usuario})


@app.get("/api/basedatos")
def api_basedatos() -> dict:
    """Estado de la base: tablas creadas y conteo de filas.

    `pendientes` son las tablas de los Dominios 2 y 3 que quedan vacias a
    proposito hasta que se cargue la data de referencia.
    """
    return basedatos.estado()


@app.get("/api/documentos/{documento_id}/valores")
def api_valores(documento_id: str) -> dict:
    """Valores extraidos de un documento, leidos de la base de datos."""
    return {
        "documento_id": documento_id,
        "valores": repositorio.valores_de_documento(documento_id),
    }


def _leer_guia(crudo) -> list[float] | None:
    """Valida el marco guia: 4 numeros normalizados 0..1."""
    if isinstance(crudo, str):
        try:
            crudo = json.loads(crudo)
        except (ValueError, TypeError):
            return None
    if not isinstance(crudo, (list, tuple)) or len(crudo) != 4:
        return None
    try:
        valores = [float(v) for v in crudo]
    except (ValueError, TypeError):
        return None
    if valores[2] <= 0 or valores[3] <= 0:
        return None
    return valores


@app.websocket("/ws/deteccion")
async def deteccion(websocket: WebSocket) -> None:
    """Recibe cuadros reducidos de la camara y responde con las 4 esquinas.

    Protocolo
    ---------
    - Mensaje de texto JSON: configuracion del cliente. Se guarda y se aplica a
      los cuadros siguientes.
        ``{"guia": [x, y, ancho, alto], "ratio": 0.7071, "candidatos": false}``
      El marco guia y la proporcion esperada entran en la puntuacion del
      detector: los candidatos de fuera del marco o con otra proporcion pierden.
    - Mensaje binario: un JPEG (ancho recomendado 480 px). La respuesta es
      ``{"encontrado", "quad", "area", "puntaje", "metodo", "componentes"}``
      con coordenadas normalizadas 0..1. El cliente debe esperar la respuesta
      antes de enviar el siguiente cuadro.

    Un cuadro invalido no cierra la conexion.
    """
    await websocket.accept()
    guia: list[float] | None = None
    ratio: float | None = None
    con_candidatos = False

    try:
        while True:
            mensaje = await websocket.receive()
            if mensaje.get("type") == "websocket.disconnect":
                return

            texto = mensaje.get("text")
            if texto is not None:
                try:
                    ajustes = json.loads(texto)
                except (ValueError, TypeError):
                    await websocket.send_json({"tipo": "config", "ok": False})
                    continue
                if "guia" in ajustes:
                    guia = _leer_guia(ajustes.get("guia"))
                if "ratio" in ajustes:
                    try:
                        valor = float(ajustes.get("ratio") or 0)
                    except (ValueError, TypeError):
                        valor = 0.0
                    ratio = valor if valor > 0 else None
                if "candidatos" in ajustes:
                    con_candidatos = bool(ajustes.get("candidatos"))
                await websocket.send_json(
                    {"tipo": "config", "ok": True, "guia": guia, "ratio": ratio,
                     "candidatos": con_candidatos}
                )
                continue

            datos = mensaje.get("bytes")
            if not datos:
                continue

            imagen = detector.decodificar_jpeg(datos)
            if imagen is None:
                await websocket.send_json({"encontrado": False, "error": "cuadro_invalido"})
                continue

            resultado = detector.detectar_documento(
                imagen, guia=guia, ratio_objetivo=ratio, con_candidatos=con_candidatos
            )
            if resultado is None:
                await websocket.send_json({"encontrado": False})
                continue
            if not resultado.get("quad"):
                # Hubo candidatos pero ninguno paso los filtros.
                await websocket.send_json(
                    {"encontrado": False, "candidatos": resultado.get("candidatos")}
                )
                continue

            respuesta = {
                "encontrado": True,
                "quad": resultado["quad"],
                "area": resultado["area"],
                "puntaje": resultado["puntaje"],
                "metodo": resultado["metodo"],
                "componentes": resultado["componentes"],
            }
            if con_candidatos:
                respuesta["candidatos"] = resultado.get("candidatos")
                respuesta["papel_detalle"] = resultado.get("papel_detalle")
            await websocket.send_json(respuesta)
    except WebSocketDisconnect:
        return
    except Exception:  # noqa: BLE001 - no debe tumbar el servidor
        traceback.print_exc()


@app.post("/api/capturar")
async def capturar(
    imagen: UploadFile = File(...),
    formato: str = Form(formatos.FORMATO_POR_DEFECTO),
    modo: str = Form("color"),
    ajustar_formato: bool = Form(True),
    quad: str = Form(""),
    guia: str = Form(""),
) -> JSONResponse:
    """Procesa la foto a resolucion completa y devuelve el documento plano.

    ``quad`` es opcional: si el cliente manda las esquinas normalizadas que ya
    tenia dibujadas (JSON ``[[x,y],...]``) se usan directamente; si viene vacio
    el servidor vuelve a detectar sobre la imagen completa, usando ``guia`` y la
    proporcion del formato como pistas.
    """
    contenido = await imagen.read()
    bgr = detector.decodificar_jpeg(contenido)
    if bgr is None:
        return JSONResponse({"ok": False, "error": "No se pudo leer la imagen"}, status_code=400)

    alto_img, ancho_img = bgr.shape[:2]
    formato_elegido = formatos.obtener(formato)

    esquinas = None
    if quad:
        try:
            crudas = json.loads(quad)
            if isinstance(crudas, list) and len(crudas) == 4:
                esquinas = [[float(x) * ancho_img, float(y) * alto_img] for x, y in crudas]
        except (ValueError, TypeError):
            esquinas = None

    if esquinas is None:
        deteccion_servidor = detector.detectar_documento(
            bgr,
            guia=_leer_guia(guia),
            ratio_objetivo=formato_elegido.ratio or None,
        )
        if deteccion_servidor is not None:
            esquinas = deteccion_servidor["quad_px"].tolist()

    recorte_aplicado = esquinas is not None
    if esquinas is None:
        # Sin deteccion: se guarda la foto completa para no perder el trabajo.
        esquinas = [
            [0, 0],
            [ancho_img - 1, 0],
            [ancho_img - 1, alto_img - 1],
            [0, alto_img - 1],
        ]

    ratio = formato_elegido.ratio if (ajustar_formato and recorte_aplicado) else None

    plano = enderezar.enderezar(bgr, esquinas, ratio_objetivo=ratio)
    plano = enderezar.realzar(plano, modo)
    jpeg_plano = enderezar.codificar_jpeg(plano)

    quad_normalizado = [
        [round(x / ancho_img, 5), round(y / alto_img, 5)] for x, y in esquinas
    ]
    captura = almacenamiento.guardar_captura(
        jpeg_plano=jpeg_plano,
        jpeg_original=contenido,
        ancho=plano.shape[1],
        alto=plano.shape[0],
        formato=formato_elegido.clave,
        modo=modo,
        quad=quad_normalizado,
    )

    # Gancho de integracion: nunca debe romper la captura.
    try:
        datos = integraciones.procesar_documento(captura)
    except Exception as error:  # noqa: BLE001
        traceback.print_exc()
        datos = {"estado": "error", "error": f"{type(error).__name__}: {error}"}

    return JSONResponse(
        {
            "ok": True,
            "captura": captura.resumen(),
            "url_imagen": f"/capturas/{captura.ruta.name}",
            "url_original": f"/capturas/originales/{captura.ruta.name}",
            "recorte_aplicado": recorte_aplicado,
            "origen_esquinas": "cliente" if quad and recorte_aplicado else "servidor",
            "quad": quad_normalizado,
            "datos": datos,
        }
    )


@app.post("/api/diagnostico")
async def diagnostico(
    imagen: UploadFile = File(...),
    formato: str = Form(formatos.FORMATO_POR_DEFECTO),
    guia: str = Form(""),
) -> JSONResponse:
    """Guarda un cuadro con todos los candidatos dibujados y su puntaje.

    Sirve para entender por que el detector eligio (o no eligio) un contorno
    con documentos reales. Escribe tres archivos en ``capturas/diagnostico/``:
    la foto original, la foto con los candidatos pintados y un JSON con los
    componentes del puntaje de cada uno.
    """
    contenido = await imagen.read()
    bgr = detector.decodificar_jpeg(contenido)
    if bgr is None:
        return JSONResponse({"ok": False, "error": "No se pudo leer la imagen"}, status_code=400)

    formato_elegido = formatos.obtener(formato)
    resultado = detector.detectar_documento(
        bgr,
        guia=_leer_guia(guia),
        ratio_objetivo=formato_elegido.ratio or None,
        con_candidatos=True,
    )

    momento = datetime.now()
    base = f"{momento:%Y-%m-%d_%H%M%S}_LABLENS_DIAG"
    carpeta = almacenamiento.DIR_DIAGNOSTICO
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / f"{base}_original.jpg").write_bytes(contenido)

    pintado = detector.dibujar_diagnostico(bgr, resultado)
    (carpeta / f"{base}_candidatos.jpg").write_bytes(enderezar.codificar_jpeg(pintado, 88))

    informe = {
        "creado_en": momento.isoformat(timespec="seconds"),
        "formato": formato_elegido.clave,
        "ratio_objetivo": formato_elegido.ratio,
        "guia": _leer_guia(guia),
        "tamano": [bgr.shape[1], bgr.shape[0]],
        "encontrado": bool(resultado and resultado.get("quad")),
        "ganador": None
        if not (resultado and resultado.get("quad"))
        else {
            "metodo": resultado["metodo"],
            "puntaje": resultado["puntaje"],
            "area": resultado["area"],
            "rango_angular": resultado["rango_angular"],
            "componentes": resultado["componentes"],
            "papel_detalle": resultado["papel_detalle"],
        },
        "candidatos": (resultado or {}).get("candidatos") or [],
    }
    (carpeta / f"{base}_informe.json").write_text(
        json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return JSONResponse(
        {
            "ok": True,
            "base": base,
            "url_candidatos": f"/capturas/diagnostico/{base}_candidatos.jpg",
            "vista_previa": "data:image/jpeg;base64,"
            + base64.b64encode(enderezar.codificar_jpeg(pintado, 70)).decode("ascii"),
            "informe": informe,
        }
    )


@app.get("/api/capturas")
def api_capturas(limite: int = 30) -> dict:
    return {"capturas": almacenamiento.listar_capturas(limite)}


@app.get("/api/capturas/{captura_id}/datos")
def api_datos(captura_id: str) -> JSONResponse:
    """Estado o resultado del analisis de una captura.

    El frontend consulta esta ruta hasta que ``estado`` deja de ser
    ``en_proceso``. Devuelve 404 si no hay analisis para ese id.
    """
    resultado = analisis.estado(captura_id)
    if resultado is None:
        return JSONResponse(
            {"ok": False, "error": "sin analisis para esa captura"}, status_code=404
        )
    return JSONResponse({"ok": True, "datos": resultado})


@app.get("/api/informes")
def api_informes(limite: int = 30) -> dict:
    """Documentos registrados en la base, del mas reciente al mas antiguo."""
    return {"documentos": repositorio.listar(limite)}


app.mount("/capturas", StaticFiles(directory=almacenamiento.DIR_CAPTURAS), name="capturas")
app.mount("/estaticos", StaticFiles(directory=DIR_ESTATICOS), name="estaticos")
