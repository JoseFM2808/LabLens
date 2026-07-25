"""Arranque del servidor LabLens para la prueba en red local.

Uso:
    .venv\\Scripts\\python.exe servidor.py            # HTTPS en el puerto 8443
    .venv\\Scripts\\python.exe servidor.py --http     # HTTP (solo localhost)
    .venv\\Scripts\\python.exe servidor.py --puerto 9000

HTTPS es obligatorio para entrar desde el celular: sin contexto seguro el
navegador no entrega la camara. El certificado es autofirmado, asi que el
celular mostrara un aviso; hay que elegir "Configuracion avanzada" y continuar.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

from app.certificado import asegurar_certificado, ip_local

RAIZ = Path(__file__).resolve().parent
DIR_CERTS = RAIZ / "certs"


def _qr(url: str) -> None:
    """Imprime un QR en la consola para abrir la URL desde el celular."""
    try:
        import qrcode

        codigo = qrcode.QRCode(border=1)
        codigo.add_data(url)
        codigo.print_ascii(invert=True)
    except Exception:  # noqa: BLE001 - el QR es un extra, no debe frenar el arranque
        pass


def main() -> int:
    analizador = argparse.ArgumentParser(description="Servidor local de LabLens")
    analizador.add_argument("--puerto", type=int, default=8443)
    analizador.add_argument("--host", default="0.0.0.0")
    analizador.add_argument("--http", action="store_true", help="sin TLS, solo localhost")
    analizador.add_argument("--recargar", action="store_true", help="recarga al editar codigo")
    argumentos = analizador.parse_args()

    ip = ip_local()
    esquema = "http" if argumentos.http else "https"
    url_lan = f"{esquema}://{ip}:{argumentos.puerto}/"

    opciones: dict = {}
    if not argumentos.http:
        cert, llave = asegurar_certificado(DIR_CERTS, [ip])
        opciones["ssl_certfile"] = str(cert)
        opciones["ssl_keyfile"] = str(llave)

    print()
    print("=" * 62)
    print("  LabLens - escaner de documentos medicos (prueba local)")
    print("=" * 62)
    print(f"  En esta PC:     {esquema}://localhost:{argumentos.puerto}/")
    print(f"  Desde el movil: {url_lan}")
    if argumentos.http:
        print()
        print("  AVISO: en modo --http la camara solo funciona en localhost.")
    else:
        print()
        print("  El certificado es autofirmado: acepta el aviso del navegador")
        print("  ('Configuracion avanzada' -> 'Continuar al sitio').")
    print(f"  Capturas en:    {RAIZ / 'capturas'}")
    print("=" * 62)
    _qr(url_lan)
    print("  Ctrl+C para detener.")
    print()

    uvicorn.run(
        "app.main:app",
        host=argumentos.host,
        port=argumentos.puerto,
        reload=argumentos.recargar,
        **opciones,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
