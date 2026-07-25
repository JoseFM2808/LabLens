/* LabLens - camara, marco guia, deteccion en vivo y captura. */
(() => {
  'use strict';

  // --- Ajustes del bucle de deteccion -------------------------------------
  const ANCHO_ANALISIS = 480;      // lado mayor del cuadro que se envia al servidor
  const INTERVALO_MS = 110;        // pausa minima entre cuadros
  const AREA_MINIMA_ALINEADO = 0.30;
  const PUNTAJE_MINIMO_ALINEADO = 0.55;
  const MARGEN_BORDE = 0.015;      // el documento no debe tocar el borde del cuadro
  const CUADROS_ESTABLES = 5;      // cuadros seguidos casi iguales = documento quieto
  const CUADROS_AUTO = 9;          // cuadros seguidos alineados para autocapturar
  const TOLERANCIA_ESTABLE = 0.025;
  const VIGENCIA_QUAD_MS = 600;    // despues de esto el servidor vuelve a detectar
  const TOLERANCIA_PROPORCION = 0.25; // distingue vertical de horizontal, no A4 de Carta

  const $ = (id) => document.getElementById(id);

  const el = {
    inicio: $('pantalla-inicio'),
    camara: $('pantalla-camara'),
    resultado: $('pantalla-resultado'),
    btnActivar: $('btn-activar'),
    btnCapturar: $('btn-capturar'),
    btnNueva: $('btn-nueva'),
    errorCamara: $('error-camara'),
    video: $('video'),
    lienzo: $('superposicion'),
    pista: $('pista'),
    estadoConexion: $('estado-conexion'),
    selFormato: $('sel-formato'),
    selModo: $('sel-modo'),
    selCamara: $('sel-camara'),
    envoltorioCamaras: $('envoltorio-camaras'),
    chkAuto: $('chk-auto'),
    chkAjustar: $('chk-ajustar'),
    imgResultado: $('img-resultado'),
    metaResultado: $('meta-resultado'),
    jsonResultado: $('json-resultado'),
    enlaceDescarga: $('enlace-descarga'),
  };

  const estado = {
    config: null,
    formatos: {},
    flujo: null,
    ws: null,
    enVuelo: false,
    ultimoEnvio: 0,
    deteccion: null,       // { quad, area, puntaje, momento }
    quadPrevio: null,
    estables: 0,
    alineados: 0,
    alineado: false,
    capturando: false,
    activo: false,
    generacion: 0,         // evita que convivan dos bucles tras una captura
  };

  const lienzoAnalisis = document.createElement('canvas');
  const lienzoCaptura = document.createElement('canvas');

  // --- Configuracion ------------------------------------------------------
  async function cargarConfig() {
    const respuesta = await fetch('/api/config');
    estado.config = await respuesta.json();
    el.selFormato.innerHTML = '';
    for (const formato of estado.config.formatos) {
      estado.formatos[formato.clave] = formato;
      const opcion = document.createElement('option');
      opcion.value = formato.clave;
      opcion.textContent = formato.etiqueta;
      el.selFormato.appendChild(opcion);
    }
    el.selFormato.value = estado.config.formato_por_defecto;
  }

  function formatoActual() {
    return estado.formatos[el.selFormato.value] || { ratio: 0 };
  }

  // --- Camara -------------------------------------------------------------
  async function activarCamara(idDispositivo) {
    detenerFlujo();
    const restricciones = {
      audio: false,
      video: idDispositivo
        ? { deviceId: { exact: idDispositivo }, width: { ideal: 1920 }, height: { ideal: 1080 } }
        : { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } },
    };
    estado.flujo = await navigator.mediaDevices.getUserMedia(restricciones);
    el.video.srcObject = estado.flujo;
    await el.video.play();
    await new Promise((listo) => {
      if (el.video.videoWidth) return listo();
      el.video.onloadedmetadata = () => listo();
    });
    ajustarVisor();
  }

  function detenerFlujo() {
    if (estado.flujo) {
      estado.flujo.getTracks().forEach((pista) => pista.stop());
      estado.flujo = null;
    }
  }

  async function listarCamaras() {
    if (!navigator.mediaDevices.enumerateDevices) return;
    const dispositivos = await navigator.mediaDevices.enumerateDevices();
    const camaras = dispositivos.filter((d) => d.kind === 'videoinput');
    if (camaras.length < 2) return;
    el.selCamara.innerHTML = '';
    camaras.forEach((camara, indice) => {
      const opcion = document.createElement('option');
      opcion.value = camara.deviceId;
      opcion.textContent = camara.label || `Camara ${indice + 1}`;
      el.selCamara.appendChild(opcion);
    });
    const activa = estado.flujo?.getVideoTracks()[0]?.getSettings()?.deviceId;
    if (activa) el.selCamara.value = activa;
    el.envoltorioCamaras.classList.remove('oculto');
  }

  function ajustarVisor() {
    // El visor toma la proporcion real de la camara para que no haya bandas.
    const ancho = el.video.videoWidth;
    const alto = el.video.videoHeight;
    if (ancho && alto) {
      document.querySelector('.visor').style.aspectRatio = `${ancho} / ${alto}`;
    }
  }

  // --- Geometria del visor ------------------------------------------------
  function rectContenido() {
    // Con object-fit: contain el video se centra dentro del elemento.
    const anchoCaja = el.lienzo.clientWidth;
    const altoCaja = el.lienzo.clientHeight;
    const anchoVideo = el.video.videoWidth || anchoCaja;
    const altoVideo = el.video.videoHeight || altoCaja;
    const escala = Math.min(anchoCaja / anchoVideo, altoCaja / altoVideo);
    const ancho = anchoVideo * escala;
    const alto = altoVideo * escala;
    return {
      x: (anchoCaja - ancho) / 2,
      y: (altoCaja - alto) / 2,
      ancho,
      alto,
      anchoCaja,
      altoCaja,
    };
  }

  function rectGuia(rect) {
    // Marco con la forma del documento elegido, al 88% del area visible.
    const ratio = formatoActual().ratio;
    let ancho = rect.ancho * 0.88;
    let alto = rect.alto * 0.88;
    if (ratio > 0) {
      if (ancho / alto > ratio) ancho = alto * ratio;
      else alto = ancho / ratio;
    }
    return {
      x: rect.x + (rect.ancho - ancho) / 2,
      y: rect.y + (rect.alto - alto) / 2,
      ancho,
      alto,
    };
  }

  // --- Dibujo -------------------------------------------------------------
  function dibujar(generacion) {
    if (!estado.activo || generacion !== estado.generacion) return;
    const dpr = window.devicePixelRatio || 1;
    const anchoCss = el.lienzo.clientWidth;
    const altoCss = el.lienzo.clientHeight;
    if (el.lienzo.width !== Math.round(anchoCss * dpr)) {
      el.lienzo.width = Math.round(anchoCss * dpr);
      el.lienzo.height = Math.round(altoCss * dpr);
    }
    const ctx = el.lienzo.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, anchoCss, altoCss);

    const rect = rectContenido();
    dibujarGuia(ctx, rectGuia(rect));

    const deteccion = estado.deteccion;
    if (deteccion && Date.now() - deteccion.momento < 900) {
      dibujarQuad(ctx, deteccion.quad, rect, estado.alineado);
    }
    requestAnimationFrame(() => dibujar(generacion));
  }

  function dibujarGuia(ctx, guia) {
    ctx.save();
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.55)';
    ctx.lineWidth = 2;
    ctx.setLineDash([10, 8]);
    ctx.strokeRect(guia.x, guia.y, guia.ancho, guia.alto);
    ctx.setLineDash([]);

    // Esquinas marcadas, como en la camara de documentos del celular.
    const largo = Math.min(guia.ancho, guia.alto) * 0.11;
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 4;
    ctx.lineCap = 'round';
    const esquinas = [
      [guia.x, guia.y, 1, 1],
      [guia.x + guia.ancho, guia.y, -1, 1],
      [guia.x + guia.ancho, guia.y + guia.alto, -1, -1],
      [guia.x, guia.y + guia.alto, 1, -1],
    ];
    for (const [x, y, sx, sy] of esquinas) {
      ctx.beginPath();
      ctx.moveTo(x + sx * largo, y);
      ctx.lineTo(x, y);
      ctx.lineTo(x, y + sy * largo);
      ctx.stroke();
    }
    ctx.restore();
  }

  function dibujarQuad(ctx, quad, rect, alineado) {
    const puntos = quad.map(([x, y]) => [rect.x + x * rect.ancho, rect.y + y * rect.alto]);
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(puntos[0][0], puntos[0][1]);
    for (let i = 1; i < puntos.length; i += 1) ctx.lineTo(puntos[i][0], puntos[i][1]);
    ctx.closePath();
    ctx.fillStyle = alineado ? 'rgba(34, 197, 94, 0.20)' : 'rgba(245, 158, 11, 0.16)';
    ctx.fill();
    ctx.strokeStyle = alineado ? '#22c55e' : '#f59e0b';
    ctx.lineWidth = 3;
    ctx.stroke();
    ctx.fillStyle = ctx.strokeStyle;
    for (const [x, y] of puntos) {
      ctx.beginPath();
      ctx.arc(x, y, 6, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  // --- WebSocket de deteccion --------------------------------------------
  function conectar() {
    const esquema = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${esquema}://${location.host}/ws/deteccion`);
    ws.binaryType = 'arraybuffer';
    estado.ws = ws;

    ws.onopen = () => marcarConexion('Deteccion activa', 'chip-ok');
    ws.onclose = () => {
      marcarConexion('Reconectando...', 'chip-error');
      estado.enVuelo = false;
      if (estado.activo) setTimeout(conectar, 1200);
    };
    ws.onerror = () => marcarConexion('Error de conexion', 'chip-error');
    ws.onmessage = (evento) => {
      estado.enVuelo = false;
      let respuesta;
      try {
        respuesta = JSON.parse(evento.data);
      } catch (error) {
        return;
      }
      procesarDeteccion(respuesta);
    };
  }

  function marcarConexion(texto, clase) {
    el.estadoConexion.textContent = texto;
    el.estadoConexion.className = `chip ${clase}`;
  }

  function procesarDeteccion(respuesta) {
    if (!respuesta.encontrado) {
      estado.deteccion = null;
      estado.quadPrevio = null;
      estado.estables = 0;
      estado.alineados = 0;
      estado.alineado = false;
      actualizarPista('Buscando documento...', '');
      return;
    }

    estado.deteccion = { ...respuesta, momento: Date.now() };
    const quad = respuesta.quad;

    if (estado.quadPrevio && desplazamientoMaximo(quad, estado.quadPrevio) < TOLERANCIA_ESTABLE) {
      estado.estables += 1;
    } else {
      estado.estables = 0;
    }
    estado.quadPrevio = quad;

    const problema = evaluarEncuadre(respuesta);
    estado.alineado = problema === null && estado.estables >= CUADROS_ESTABLES;

    if (problema) {
      estado.alineados = 0;
      actualizarPista(problema, 'aviso');
      return;
    }
    if (!estado.alineado) {
      actualizarPista('Manten el pulso...', 'aviso');
      return;
    }

    estado.alineados += 1;
    if (el.chkAuto.checked) {
      const faltan = Math.max(CUADROS_AUTO - estado.alineados, 0);
      actualizarPista(faltan ? `Capturando en ${faltan}...` : 'Capturando...', 'ok');
      if (estado.alineados >= CUADROS_AUTO && !estado.capturando) capturar();
    } else {
      actualizarPista('Documento alineado - listo', 'ok');
    }
  }

  function evaluarEncuadre(deteccion) {
    if (deteccion.area < AREA_MINIMA_ALINEADO) return 'Acerca mas el documento';
    if (deteccion.puntaje < PUNTAJE_MINIMO_ALINEADO) return 'Endereza un poco el documento';
    const fuera = deteccion.quad.some(
      ([x, y]) => x < MARGEN_BORDE || y < MARGEN_BORDE || x > 1 - MARGEN_BORDE || y > 1 - MARGEN_BORDE,
    );
    if (fuera) return 'El documento se sale del cuadro';

    // Sin este aviso, "ajustar al formato" deformaria un documento horizontal
    // encuadrado con un formato vertical (o al reves).
    const ratioFormato = formatoActual().ratio;
    if (ratioFormato > 0 && el.chkAjustar.checked) {
      const medido = proporcionDetectada(deteccion.quad);
      if (medido && Math.abs(medido - ratioFormato) / ratioFormato > TOLERANCIA_PROPORCION) {
        return 'No coincide con el formato: gira el documento o cambia el formato';
      }
    }
    return null;
  }

  function proporcionDetectada(quad) {
    // Las coordenadas son relativas a cada eje: hay que devolverlas a pixeles
    // del video para medir la proporcion real del documento.
    const anchoVideo = el.video.videoWidth;
    const altoVideo = el.video.videoHeight;
    if (!anchoVideo || !altoVideo) return null;
    const px = quad.map(([x, y]) => [x * anchoVideo, y * altoVideo]);
    const largo = (a, b) => Math.hypot(px[a][0] - px[b][0], px[a][1] - px[b][1]);
    const ancho = Math.max(largo(0, 1), largo(3, 2));
    const alto = Math.max(largo(0, 3), largo(1, 2));
    return alto > 0 ? ancho / alto : null;
  }

  function desplazamientoMaximo(a, b) {
    let peor = 0;
    for (let i = 0; i < 4; i += 1) {
      peor = Math.max(peor, Math.abs(a[i][0] - b[i][0]), Math.abs(a[i][1] - b[i][1]));
    }
    return peor;
  }

  function actualizarPista(texto, clase) {
    el.pista.textContent = texto;
    el.pista.className = `pista ${clase}`;
  }

  // --- Bucle de envio de cuadros -----------------------------------------
  function bucleAnalisis(generacion) {
    if (!estado.activo || generacion !== estado.generacion) return;
    const ahora = Date.now();
    const listo =
      estado.ws?.readyState === WebSocket.OPEN &&
      !estado.enVuelo &&
      !estado.capturando &&
      ahora - estado.ultimoEnvio >= INTERVALO_MS &&
      el.video.videoWidth > 0;

    if (listo) {
      estado.ultimoEnvio = ahora;
      const anchoVideo = el.video.videoWidth;
      const altoVideo = el.video.videoHeight;
      const escala = ANCHO_ANALISIS / Math.max(anchoVideo, altoVideo);
      lienzoAnalisis.width = Math.max(Math.round(anchoVideo * escala), 1);
      lienzoAnalisis.height = Math.max(Math.round(altoVideo * escala), 1);
      const ctx = lienzoAnalisis.getContext('2d');
      ctx.drawImage(el.video, 0, 0, lienzoAnalisis.width, lienzoAnalisis.height);
      lienzoAnalisis.toBlob(
        (blob) => {
          if (!blob || estado.ws?.readyState !== WebSocket.OPEN) return;
          estado.enVuelo = true;
          blob.arrayBuffer().then((buffer) => {
            if (estado.ws?.readyState === WebSocket.OPEN) estado.ws.send(buffer);
            else estado.enVuelo = false;
          });
        },
        'image/jpeg',
        0.62,
      );
    }
    setTimeout(() => bucleAnalisis(generacion), 40);
  }

  function arrancarBucles() {
    estado.generacion += 1;
    estado.activo = true;
    const generacion = estado.generacion;
    requestAnimationFrame(() => dibujar(generacion));
    bucleAnalisis(generacion);
  }

  // --- Captura ------------------------------------------------------------
  async function capturar() {
    if (estado.capturando || !el.video.videoWidth) return;
    estado.capturando = true;
    el.btnCapturar.disabled = true;
    actualizarPista('Procesando...', '');

    try {
      lienzoCaptura.width = el.video.videoWidth;
      lienzoCaptura.height = el.video.videoHeight;
      lienzoCaptura.getContext('2d').drawImage(el.video, 0, 0);
      const blob = await new Promise((listo) =>
        lienzoCaptura.toBlob(listo, 'image/jpeg', 0.95),
      );

      const cuerpo = new FormData();
      cuerpo.append('imagen', blob, 'captura.jpg');
      cuerpo.append('formato', el.selFormato.value);
      cuerpo.append('modo', el.selModo.value);
      cuerpo.append('ajustar_formato', el.chkAjustar.checked ? 'true' : 'false');

      // Si hay una deteccion fresca se reutiliza; si no, el servidor redetecta.
      const deteccion = estado.deteccion;
      if (deteccion && Date.now() - deteccion.momento < VIGENCIA_QUAD_MS) {
        cuerpo.append('quad', JSON.stringify(deteccion.quad));
      }

      const respuesta = await fetch('/api/capturar', { method: 'POST', body: cuerpo });
      const datos = await respuesta.json();
      if (!datos.ok) throw new Error(datos.error || 'Fallo la captura');
      mostrarResultado(datos);
    } catch (error) {
      actualizarPista(`Error: ${error.message}`, 'aviso');
      estado.capturando = false;
      el.btnCapturar.disabled = false;
      return;
    }

    estado.activo = false;
    el.btnCapturar.disabled = false;
    estado.capturando = false;
  }

  function mostrarResultado(datos) {
    el.camara.classList.add('oculto');
    el.resultado.classList.remove('oculto');
    el.imgResultado.src = `${datos.url_imagen}?t=${Date.now()}`;
    el.enlaceDescarga.href = datos.url_imagen;
    el.enlaceDescarga.setAttribute('download', datos.captura.archivo);

    const filas = [
      ['Archivo', datos.captura.archivo],
      ['Tamano', `${datos.captura.ancho} x ${datos.captura.alto} px`],
      ['Formato', datos.captura.formato],
      ['Realce', datos.captura.modo],
      ['Recorte', datos.recorte_aplicado ? `si (esquinas del ${datos.origen_esquinas})` : 'no - se guardo la foto completa'],
      ['Creado', datos.captura.creado_en],
    ];
    el.metaResultado.innerHTML = filas
      .map(([clave, valor]) => `<dt>${clave}</dt><dd>${valor}</dd>`)
      .join('');
    el.jsonResultado.textContent = JSON.stringify(datos.datos, null, 2);
  }

  function volverACamara() {
    el.resultado.classList.add('oculto');
    el.camara.classList.remove('oculto');
    estado.deteccion = null;
    estado.quadPrevio = null;
    estado.estables = 0;
    estado.alineados = 0;
    estado.alineado = false;
    actualizarPista('Buscando documento...', '');
    if (!estado.ws || estado.ws.readyState > WebSocket.OPEN) conectar();
    arrancarBucles();
  }

  // --- Arranque -----------------------------------------------------------
  el.btnActivar.addEventListener('click', async () => {
    el.btnActivar.disabled = true;
    el.errorCamara.classList.add('oculto');
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error(
          'Este navegador no expone la camara. Se necesita HTTPS (o localhost) y un navegador moderno.',
        );
      }
      await cargarConfig();
      await activarCamara();
      await listarCamaras();
      el.inicio.classList.add('oculto');
      el.camara.classList.remove('oculto');
      conectar();
      arrancarBucles();
    } catch (error) {
      el.errorCamara.textContent = descifrarError(error);
      el.errorCamara.classList.remove('oculto');
    } finally {
      el.btnActivar.disabled = false;
    }
  });

  function descifrarError(error) {
    const nombre = error?.name || '';
    if (nombre === 'NotAllowedError') {
      return 'Permiso de camara denegado. Habilitalo en el candado de la barra de direcciones y recarga.';
    }
    if (nombre === 'NotFoundError' || nombre === 'OverconstrainedError') {
      return 'No se encontro una camara compatible en este dispositivo.';
    }
    if (nombre === 'NotReadableError') {
      return 'La camara esta ocupada por otra aplicacion. Cierrala e intenta de nuevo.';
    }
    return error?.message || 'No se pudo iniciar la camara.';
  }

  el.btnCapturar.addEventListener('click', capturar);
  el.btnNueva.addEventListener('click', volverACamara);
  el.selCamara.addEventListener('change', () => activarCamara(el.selCamara.value));
  el.video.addEventListener('loadedmetadata', ajustarVisor);
  window.addEventListener('orientationchange', () => setTimeout(ajustarVisor, 300));
})();
