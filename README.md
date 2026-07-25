# LabLens

Escaner de documentos medicos: se captura la foto desde el celular, el servidor
detecta los bordes del documento y devuelve la imagen enderezada y plana, como
el modo "documento" de la camara del telefono.

El historial de cambios y el catalogo completo de funciones esta en
[HISTORY.md](HISTORY.md).

## Instalacion

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Arranque

```powershell
.\.venv\Scripts\python.exe servidor.py
```

La consola imprime la URL para la PC, la URL para el celular y un QR.

Opciones:

| Opcion | Para que |
|---|---|
| `--puerto 9000` | Cambia el puerto (por defecto 8443). |
| `--http` | Sin TLS. **La camara solo funciona en localhost.** |
| `--recargar` | Recarga el servidor al editar codigo. |

## Conectarse desde el celular

1. El celular y la PC deben estar en la misma red WiFi.
2. Abrir la URL `https://<IP>:8443/` que imprime la consola (o escanear el QR).
3. El certificado es autofirmado: aparece un aviso de seguridad.
   Elegir **Configuracion avanzada** y luego **Continuar al sitio**.
4. Pulsar **Activar camara** y aceptar el permiso del navegador.

### Si el celular no carga la pagina

El Firewall de Windows bloquea el puerto entrante por defecto. En PowerShell
**como administrador**, una sola vez:

```powershell
New-NetFirewallRule -DisplayName "LabLens 8443" -Direction Inbound `
  -Action Allow -Protocol TCP -LocalPort 8443 -Profile Any
```

Al terminar la prueba conviene quitarla:

```powershell
Remove-NetFirewallRule -DisplayName "LabLens 8443"
```

Nota: si `Get-NetConnectionProfile` marca la red como **Public**, la regla debe
usar `-Profile Any` (o `Public`), porque con `Private` no aplica. En una red
publica el puerto queda visible para los demas equipos de esa red mientras el
servidor este encendido.

### Si el navegador no entrega la camara

Ocurre si la pagina no esta en contexto seguro. Alternativa sin TLS en Chrome
Android: abrir `chrome://flags/#unsafely-treat-insecure-origin-as-secure`,
agregar `http://<IP>:8000`, reiniciar el navegador y arrancar con
`servidor.py --http --puerto 8000`.

## Como usarlo

1. Elegir el **formato** del documento: el marco punteado toma esa forma.
2. Encuadrar el documento dentro del marco, sobre un fondo de color contrastado.
3. El contorno detectado se dibuja en vivo: **ambar** = falta ajustar,
   **verde** = alineado.
4. Pulsar **Capturar**, o activar **Captura automatica al alinear**.

Modos de realce:

- **Color**: conserva sellos, firmas y anotaciones en lapicero. Por defecto.
- **Grises**: mas contraste, archivo mas liviano.
- **Blanco y negro**: umbral adaptativo, ideal para texto impreso.

## Donde quedan las capturas

```
capturas/
  2026-07-25_183042_LABLENS_DOC_a4vertical_a1b2c3.jpg   documento enderezado
  originales/<mismo nombre>.jpg                          foto sin procesar
  registro.jsonl                                         una linea JSON por captura
```

## Conectar el extractor de datos

LabLens entrega la foto plana y se detiene ahi. La extraccion de datos (OCR,
API de laboratorio, modelo de vision) se conecta en un solo lugar:
`app/integraciones.py`, funcion `procesar_documento(captura)`.

```python
def procesar_documento(captura: Captura) -> dict:
    # captura.ruta      ruta del JPEG enderezado
    # captura.base64()  la imagen lista para enviar a una API
    # captura.formato   formato elegido en la camara
    return {"estado": "ok", "paciente": "...", "examenes": [...]}
```

Lo que devuelve viaja en la respuesta HTTP bajo `datos` y se muestra en la
pantalla de resultado. Si la funcion falla, la captura **no** se pierde: se
guarda igual y el error aparece en `datos.error`.

El archivo trae tres ejemplos inactivos y listos para copiar: Tesseract local,
POST a una API propia y extraccion de campos con un modelo de vision de Claude.

Las credenciales se leen de variables de entorno. No se escriben en el codigo.

## Consumir las capturas desde otro sistema

| Endpoint | Uso |
|---|---|
| `GET /api/capturas?limite=30` | Ultimas capturas registradas. |
| `GET /capturas/<archivo>` | Documento enderezado. |
| `GET /capturas/originales/<archivo>` | Foto original. |
| `POST /api/capturar` | Procesar una imagen ya existente (multipart). |

Tambien sirve leer `capturas/registro.jsonl` directamente, o vigilar la carpeta
`capturas/` con un proceso aparte.
