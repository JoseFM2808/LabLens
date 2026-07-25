"""Servidor LabLens: camara web, deteccion en vivo y captura enderezada."""

from __future__ import annotations

import json
import traceback

from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, almacenamiento, detector, enderezar, formatos, integraciones

DIR_ESTATICOS = almacenamiento.RAIZ / "app" / "estaticos"

# Debe existir antes de montar StaticFiles.
almacenamiento.asegurar_directorios()

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
    }


@app.websocket("/ws/deteccion")
async def deteccion(websocket: WebSocket) -> None:
    """Recibe cuadros reducidos de la camara y responde con las 4 esquinas.

    Protocolo: el cliente envia un JPEG binario (ancho recomendado 480 px) y
    recibe un JSON ``{"encontrado": bool, "quad": [[x,y]x4], "area", "puntaje"}``
    con coordenadas normalizadas 0..1. El cliente debe esperar la respuesta
    antes de enviar el siguiente cuadro.
    """
    await websocket.accept()
    try:
        while True:
            datos = await websocket.receive_bytes()
            imagen = detector.decodificar_jpeg(datos)
            if imagen is None:
                await websocket.send_json({"encontrado": False, "error": "cuadro_invalido"})
                continue
            resultado = detector.detectar_documento(imagen)
            if resultado is None:
                await websocket.send_json({"encontrado": False})
                continue
            await websocket.send_json(
                {
                    "encontrado": True,
                    "quad": resultado["quad"],
                    "area": resultado["area"],
                    "puntaje": resultado["puntaje"],
                    "metodo": resultado["metodo"],
                }
            )
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
) -> JSONResponse:
    """Procesa la foto a resolucion completa y devuelve el documento plano.

    ``quad`` es opcional: si el cliente manda las esquinas normalizadas que ya
    tenia dibujadas (JSON ``[[x,y],...]``) se usan directamente; si viene vacio
    el servidor vuelve a detectar sobre la imagen completa.
    """
    contenido = await imagen.read()
    bgr = detector.decodificar_jpeg(contenido)
    if bgr is None:
        return JSONResponse({"ok": False, "error": "No se pudo leer la imagen"}, status_code=400)

    alto_img, ancho_img = bgr.shape[:2]

    esquinas = None
    if quad:
        try:
            crudas = json.loads(quad)
            if isinstance(crudas, list) and len(crudas) == 4:
                esquinas = [[float(x) * ancho_img, float(y) * alto_img] for x, y in crudas]
        except (ValueError, TypeError):
            esquinas = None

    deteccion_servidor = None
    if esquinas is None:
        deteccion_servidor = detector.detectar_documento(bgr)
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

    formato_elegido = formatos.obtener(formato)
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


@app.get("/api/capturas")
def api_capturas(limite: int = 30) -> dict:
    return {"capturas": almacenamiento.listar_capturas(limite)}


app.mount("/capturas", StaticFiles(directory=almacenamiento.DIR_CAPTURAS), name="capturas")
app.mount("/estaticos", StaticFiles(directory=DIR_ESTATICOS), name="estaticos")
