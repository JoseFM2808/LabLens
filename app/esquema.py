"""Normalizacion del JSON del modelo a una estructura lista para base de datos.

El modelo devuelve texto libre dentro de cada campo: ``"12,5"``, ``"< 0.01"``,
``"3.5 - 5.5"``, ``"Hasta 200"``. Guardar eso tal cual haria imposible consultar
por valor o comparar entre informes. Aqui se separa cada campo en columnas
tipadas, conservando siempre el texto original para auditoria.

Decision importante: ``fuera_de_rango`` se **recalcula** a partir del valor y de
los limites parseados, y no se confia en lo que dijo el modelo. Lo que dijo el
modelo se guarda aparte en ``fuera_de_rango_modelo`` para poder medir su acierto.

Relacion con la base de datos
-----------------------------
El esquema real es el de `qhali-estructura-base-datos.md`, creado por
`app/basedatos.py` y escrito por `app/repositorio.py`. Este modulo es la capa
intermedia: convierte el texto libre del modelo en los tipos que esas tablas
esperan.

Mapeo de cada campo de `ResultadoBiomarcador`:

| Campo aqui | Destino en la base |
|---|---|
| `biomarcador` | `biomarcador.nombre` (se resuelve o se crea) |
| `biomarcador_clave` | se usa para el match; se guarda en `biomarcador.sinonimos` |
| `valor_numerico` | `valor_extraido.valor_numerico` |
| `valor_texto` | `valor_extraido.valor_crudo_texto` |
| `unidad` | `valor_extraido.unidad` |
| `comparador` | sin columna; queda en el JSON de auditoria |
| `rango_texto`, `limite_inferior`, `limite_superior` | sin columna; ver nota abajo |
| `fuera_de_rango`, `fuera_de_rango_modelo` | sin columna; se recalculan al consultar |

Nota sobre el rango impreso en el documento: `valor_extraido` no tiene donde
guardarlo. El diseno prevé comparar contra `rango_referencia` (OMS/MINSA), que
es Dominio 2 y esta pendiente. Mientras tanto el rango que venia impreso en el
papel se conserva solo en el JSON de auditoria, y `fuera_de_rango` que se
calcula aqui sirve para la pantalla, no para la base.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

VACIOS = {"", "n/a", "na", "no aplica", "none", "null", "-", "--", "sin dato", "s/d"}

# Palabras que en un rango de referencia indican un limite solo superior o solo
# inferior. Se comparan en minusculas y sin acentos.
PALABRAS_MENOR = ("hasta", "menor", "menos", "inferior", "max", "maximo")
PALABRAS_MAYOR = ("desde", "mayor", "mas", "superior", "min", "minimo")

_NUMERO = r"[+-]?\d+(?:[.,]\d+)*"


def _sin_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def texto_limpio(valor) -> str | None:
    """Normaliza espacios y convierte los marcadores de vacio en None."""
    if valor is None:
        return None
    texto = re.sub(r"\s+", " ", str(valor)).strip()
    if texto.lower() in VACIOS:
        return None
    return texto


# Prefijos que delatan un segmento de direccion, no un distrito.
PREFIJOS_CALLE = (
    "av", "avenida", "jr", "jiron", "calle", "ca", "mz", "manzana", "urb",
    "urbanizacion", "psje", "pasaje", "km", "carretera", "lote", "lt", "int",
    "piso", "of", "oficina", "nro", "no",
)


def distrito_probable(ubicacion: str | None) -> str | None:
    """Extrae el distrito del texto libre que devuelve el modelo.

    El modelo responde el membrete completo, por ejemplo
    ``"Av. Saenz Pena 234 - Bellavista, Callao"``. Guardar eso en
    `documento.distrito` rompe cualquier consulta por distrito, asi que se
    descartan los segmentos que son direccion (llevan numero o empiezan con
    Av./Jr./Mz.) y se toma el primero de los que quedan: en Peru el distrito va
    antes de la provincia, o sea ``"Bellavista"`` y no ``"Callao"``.

    Devuelve None si no queda ningun candidato. El texto completo nunca se
    pierde: sigue en `Informe.ubicacion` y en el JSON de auditoria.
    """
    texto = texto_limpio(ubicacion)
    if texto is None:
        return None

    candidatos = []
    for parte in re.split(r"[,;/|\-–]", texto):
        parte = parte.strip(" .")
        if len(parte) < 3:
            continue
        if re.search(r"\d", parte):  # tiene numero: es una direccion
            continue
        palabras = _sin_acentos(parte).lower().split()
        if palabras and palabras[0].rstrip(".") in PREFIJOS_CALLE:
            continue
        candidatos.append(parte)

    return candidatos[0] if candidatos else None


def clave_biomarcador(nombre: str) -> str:
    """Slug estable para indexar y agrupar el mismo biomarcador entre informes."""
    base = _sin_acentos(nombre).lower()
    base = re.sub(r"[^a-z0-9]+", "_", base)
    return base.strip("_") or "sin_nombre"


def _a_float(crudo: str) -> float | None:
    """Convierte un numero escrito a la europea o a la inglesa.

    Regla principal: cuando aparecen coma y punto, **el que va ultimo es el
    separador decimal** y el otro es de miles. Asi ``1,234.5`` y ``1.234,5``
    dan los dos 1234.5.

    Con un solo tipo de separador hay ambiguedad real. Si es coma y separa 1 o 2
    digitos finales se toma como decimal (``12,5``), si separa 3 se toma como
    miles (``1,234``). Si es punto se toma siempre como decimal, que es lo
    habitual en informes de laboratorio.
    """
    texto = crudo.strip()
    if not texto:
        return None

    posicion_coma = texto.rfind(",")
    posicion_punto = texto.rfind(".")

    if posicion_coma != -1 and posicion_punto != -1:
        if posicion_coma > posicion_punto:  # formato europeo: 1.234,5
            texto = texto.replace(".", "").replace(",", ".")
        else:  # formato ingles: 1,234.5
            texto = texto.replace(",", "")
    elif posicion_coma != -1:
        ultima = texto.rsplit(",", 1)[-1]
        texto = texto.replace(",", "." if len(ultima) in (1, 2) else "")

    try:
        return float(texto)
    except ValueError:
        return None


def parsear_valor(crudo) -> tuple[float | None, str | None]:
    """Separa el valor medido en numero y comparador.

    ``"12,5"`` -> (12.5, None) | ``"< 0.01"`` -> (0.01, '<') |
    ``"Negativo"`` -> (None, None)
    """
    texto = texto_limpio(crudo)
    if texto is None:
        return None, None
    comparador = None
    coincidencia = re.match(r"^\s*(<=|>=|<|>)\s*", texto)
    if coincidencia:
        comparador = coincidencia.group(1)
        texto = texto[coincidencia.end() :]
    numero = re.search(_NUMERO, texto)
    if not numero:
        return None, comparador
    return _a_float(numero.group(0)), comparador


def parsear_rango(crudo) -> tuple[float | None, float | None]:
    """Separa el rango de referencia en limite inferior y superior.

    ``"3.5 - 5.5"`` -> (3.5, 5.5) | ``"0,5 a 1,2"`` -> (0.5, 1.2) |
    ``"< 200"`` / ``"Hasta 200"`` -> (None, 200.0) |
    ``"> 40"`` / ``"Mayor a 40"`` -> (40.0, None)
    """
    texto = texto_limpio(crudo)
    if texto is None:
        return None, None
    plano = _sin_acentos(texto).lower()

    # Dos numeros = intervalo cerrado. El separador puede ser guion, "a" o "-".
    intervalo = re.match(
        rf"^\s*({_NUMERO})\s*(?:-|–|a|to|hasta)\s*({_NUMERO})\s*", plano
    )
    if intervalo:
        inferior = _a_float(intervalo.group(1))
        superior = _a_float(intervalo.group(2))
        if inferior is not None and superior is not None and inferior > superior:
            inferior, superior = superior, inferior
        return inferior, superior

    numero = re.search(_NUMERO, plano)
    if not numero:
        return None, None
    valor = _a_float(numero.group(0))
    antes = plano[: numero.start()]

    if "<" in antes or any(p in antes for p in PALABRAS_MENOR):
        return None, valor
    if ">" in antes or any(p in antes for p in PALABRAS_MAYOR):
        return valor, None
    # Un solo numero sin pista: se toma como techo, que es lo habitual en
    # informes de laboratorio ("Colesterol total 200").
    return None, valor


def evaluar_fuera_de_rango(
    valor: float | None,
    comparador: str | None,
    inferior: float | None,
    superior: float | None,
) -> bool | None:
    """Decide si el valor esta fuera del rango. None = no se puede afirmar.

    Con comparador el valor real es desconocido: ``"< 0.01"`` significa que esta
    por debajo de 0.01. Primero se revisa el limite que puede dar una respuesta
    definitiva y solo despues el que deja duda.

    Ejemplos con ``"< 0.01"``:
      - rango [0.4, 4.0] -> 0.01 ya esta bajo el piso, el real tambien: **fuera**
      - rango hasta 200  -> el real esta bajo 0.01, sin piso que violar: dentro
      - rango [3.5, 20]  -> con ``"< 10"`` el real puede caer a cualquier lado
        del piso: indeterminado
    """
    if valor is None or (inferior is None and superior is None):
        return None

    if comparador in ("<", "<="):
        # El valor real es aun menor, asi que si ya esta bajo el piso, esta fuera.
        if inferior is not None and valor <= inferior:
            return True
        if superior is not None and valor <= superior:
            return False if inferior is None else None
        return None
    if comparador in (">", ">="):
        # El valor real es aun mayor: si ya supera el techo, esta fuera.
        if superior is not None and valor >= superior:
            return True
        if inferior is not None and valor >= inferior:
            return False if superior is None else None
        return None

    if inferior is not None and valor < inferior:
        return True
    if superior is not None and valor > superior:
        return True
    return False


def _a_bool(valor) -> bool | None:
    if isinstance(valor, bool):
        return valor
    texto = texto_limpio(valor)
    if texto is None:
        return None
    if texto.lower() in ("true", "si", "sí", "1", "yes", "alto", "bajo", "anormal"):
        return True
    if texto.lower() in ("false", "no", "0", "normal"):
        return False
    return None


@dataclass
class ResultadoBiomarcador:
    orden: int
    biomarcador: str
    biomarcador_clave: str
    valor_texto: str | None
    valor_numerico: float | None
    comparador: str | None
    unidad: str | None
    rango_texto: str | None
    limite_inferior: float | None
    limite_superior: float | None
    fuera_de_rango: bool | None
    fuera_de_rango_modelo: bool | None

    def a_fila(self, informe_id: str) -> dict:
        """Fila lista para INSERT en la tabla `resultado`."""
        return {
            "informe_id": informe_id,
            "orden": self.orden,
            "biomarcador": self.biomarcador,
            "biomarcador_clave": self.biomarcador_clave,
            "valor_texto": self.valor_texto,
            "valor_numerico": self.valor_numerico,
            "comparador": self.comparador,
            "unidad": self.unidad,
            "rango_texto": self.rango_texto,
            "limite_inferior": self.limite_inferior,
            "limite_superior": self.limite_superior,
            "fuera_de_rango": None if self.fuera_de_rango is None else int(self.fuera_de_rango),
            "fuera_de_rango_modelo": None
            if self.fuera_de_rango_modelo is None
            else int(self.fuera_de_rango_modelo),
        }


@dataclass
class Informe:
    id: str
    captura_archivo: str
    creado_en: str
    formato: str | None
    centro_medico: str | None
    ubicacion: str | None
    paciente: str | None
    fecha_documento: str | None
    estado: str
    error: str | None
    modelo: str | None
    intentos: int | None
    ms_respuesta: int | None
    crudo: dict | None
    resultados: list[ResultadoBiomarcador] = field(default_factory=list)

    def a_fila(self) -> dict:
        """Fila lista para INSERT en la tabla `informe`."""
        import json as _json

        return {
            "id": self.id,
            "captura_archivo": self.captura_archivo,
            "creado_en": self.creado_en,
            "formato": self.formato,
            "centro_medico": self.centro_medico,
            "ubicacion": self.ubicacion,
            "paciente": self.paciente,
            "fecha_documento": self.fecha_documento,
            "estado": self.estado,
            "error": self.error,
            "modelo": self.modelo,
            "intentos": self.intentos,
            "ms_respuesta": self.ms_respuesta,
            "crudo_json": None if self.crudo is None else _json.dumps(self.crudo, ensure_ascii=False),
        }

    def a_dict(self) -> dict:
        """Representacion serializable, la que viaja al frontend y al JSONL."""
        return {
            **self.a_fila(),
            "resultados": [r.a_fila(self.id) for r in self.resultados],
            "total_resultados": len(self.resultados),
            "fuera_de_rango": sum(1 for r in self.resultados if r.fuera_de_rango),
        }


def normalizar(captura, salida_extraccion: dict) -> Informe:
    """Convierte la salida cruda del modelo en un `Informe` listo para guardar."""
    crudo = salida_extraccion.get("crudo") or {}
    general = crudo.get("informacion_general") or {}

    informe = Informe(
        id=captura.id,
        captura_archivo=captura.ruta.name,
        creado_en=captura.creado_en,
        formato=captura.formato,
        centro_medico=texto_limpio(general.get("centro_medico")),
        ubicacion=texto_limpio(general.get("ubicacion")),
        # Todavia no se piden al modelo; las columnas existen para no migrar luego.
        paciente=texto_limpio(general.get("paciente")),
        fecha_documento=texto_limpio(general.get("fecha") or general.get("fecha_documento")),
        estado=salida_extraccion.get("estado", "error_json"),
        error=salida_extraccion.get("error") or salida_extraccion.get("mensaje"),
        modelo=salida_extraccion.get("modelo"),
        intentos=salida_extraccion.get("intentos"),
        ms_respuesta=salida_extraccion.get("ms_respuesta"),
        crudo=crudo or None,
    )

    filas = crudo.get("resultados")
    if not isinstance(filas, list):
        return informe

    for orden, fila in enumerate(filas, start=1):
        if not isinstance(fila, dict):
            continue
        nombre = texto_limpio(fila.get("biomarcador"))
        if nombre is None:
            continue
        valor_numerico, comparador = parsear_valor(fila.get("valor_medido"))
        inferior, superior = parsear_rango(fila.get("rango_referencia"))
        informe.resultados.append(
            ResultadoBiomarcador(
                orden=orden,
                biomarcador=nombre,
                biomarcador_clave=clave_biomarcador(nombre),
                valor_texto=texto_limpio(fila.get("valor_medido")),
                valor_numerico=valor_numerico,
                comparador=comparador,
                unidad=texto_limpio(fila.get("unidad")),
                rango_texto=texto_limpio(fila.get("rango_referencia")),
                limite_inferior=inferior,
                limite_superior=superior,
                fuera_de_rango=evaluar_fuera_de_rango(
                    valor_numerico, comparador, inferior, superior
                ),
                fuera_de_rango_modelo=_a_bool(fila.get("fuera_de_rango")),
            )
        )
    return informe
