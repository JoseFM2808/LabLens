"""Certificado TLS autofirmado para poder abrir la camara desde el celular.

Los navegadores solo entregan ``getUserMedia`` en un contexto seguro: HTTPS o
localhost. Al entrar por IP de red local hace falta HTTPS, y para eso se genera
un certificado propio que incluye la IP de la maquina en el campo SAN.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import socket
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

DIAS_VIGENCIA = 825


def ip_local() -> str:
    """IP de esta maquina en la red local (la que ve el celular)."""
    conector = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        conector.connect(("8.8.8.8", 80))  # no envia trafico, solo elige la ruta
        return conector.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        conector.close()


def _ips_del_certificado(ruta_cert: Path) -> set[str]:
    try:
        cert = x509.load_pem_x509_certificate(ruta_cert.read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        return {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}
    except Exception:  # noqa: BLE001 - certificado ilegible = hay que regenerarlo
        return set()


def _vencido(ruta_cert: Path) -> bool:
    try:
        cert = x509.load_pem_x509_certificate(ruta_cert.read_bytes())
        return cert.not_valid_after_utc <= dt.datetime.now(dt.timezone.utc)
    except Exception:  # noqa: BLE001
        return True


def asegurar_certificado(dir_certs: Path, ips: list[str]) -> tuple[Path, Path]:
    """Devuelve (cert, llave), regenerando si falta una IP o si vencio."""
    dir_certs.mkdir(parents=True, exist_ok=True)
    ruta_cert = dir_certs / "lablens.crt"
    ruta_llave = dir_certs / "lablens.key"

    objetivo = {"127.0.0.1", *ips}
    if (
        ruta_cert.exists()
        and ruta_llave.exists()
        and objetivo.issubset(_ips_del_certificado(ruta_cert))
        and not _vencido(ruta_cert)
    ):
        return ruta_cert, ruta_llave

    llave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "LabLens local"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "LabLens"),
        ]
    )
    alternativos: list[x509.GeneralName] = [x509.DNSName("localhost")]
    for texto in sorted(objetivo):
        try:
            alternativos.append(x509.IPAddress(ipaddress.ip_address(texto)))
        except ValueError:
            continue

    ahora = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nombre)
        .issuer_name(nombre)
        .public_key(llave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - dt.timedelta(days=1))
        .not_valid_after(ahora + dt.timedelta(days=DIAS_VIGENCIA))
        .add_extension(x509.SubjectAlternativeName(alternativos), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(llave, hashes.SHA256())
    )

    ruta_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    ruta_llave.write_bytes(
        llave.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return ruta_cert, ruta_llave
