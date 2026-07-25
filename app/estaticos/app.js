/* LabLens - interfaz migrada al sistema de diseño de Stitch.
 *
 * Cinco vistas dentro de una sola página, con la navegación inferior del diseño.
 * La cámara solo corre mientras la vista "escanear" está visible: al salir se
 * apaga el flujo y se detienen los bucles, si no el móvil se calienta y gasta
 * batería de fondo.
 */
(() => {
  'use strict';

  // --- Ajustes del bucle de detección -------------------------------------
  const ANCHO_ANALISIS = 480;
  const INTERVALO_MS = 110;
  const AREA_MINIMA_ALINEADO = 0.30;
  const PUNTAJE_MINIMO_ALINEADO = 0.55;
  const MARGEN_BORDE = 0.015;
  const CUADROS_ESTABLES = 5;
  const CUADROS_AUTO = 9;
  const TOLERANCIA_ESTABLE = 0.025;
  const VIGENCIA_QUAD_MS = 600;
  const TOLERANCIA_PROPORCION = 0.25;

  // --- Consulta del análisis en segundo plano -----------------------------
  const INTERVALO_SONDEO_MS = 1500;
  // 3 intentos x 120 s de tiempo límite + esperas = hasta ~6.5 min.
  const SONDEOS_MAXIMOS = 270;

  const $ = (id) => document.getElementById(id);

  const el = {
    contenido: $('contenido'),
    btnAtras: $('btn-atras'),
    huecoIzq: $('hueco-izq'),
    btnPerfil: $('btn-perfil'),
    // inicio
    saludo: $('saludo'),
    estadoSalud: $('estado-salud'),
    estadoSaludNota: $('estado-salud-nota'),
    datosSobreTi: $('datos-sobre-ti'),
    seccionDatos: $('seccion-datos'),
    documentosRecientes: $('documentos-recientes'),
    seccionRecientes: $('seccion-recientes'),
    // escanear
    visor: $('visor'),
    visorVacio: $('visor-vacio'),
    video: $('video'),
    lienzo: $('superposicion'),
    pista: $('pista'),
    errorCamara: $('error-camara'),
    btnActivar: $('btn-activar'),
    btnCapturar: $('btn-capturar'),
    selFormato: $('sel-formato'),
    selModo: $('sel-modo'),
    selCamara: $('sel-camara'),
    envoltorioCamaras: $('envoltorio-camaras'),
    chkAuto: $('chk-auto'),
    chkAjustar: $('chk-ajustar'),
    chkDiagnostico: $('chk-diagnostico'),
    panelDiagnostico: $('panel-diagnostico'),
    btnDiagnostico: $('btn-diagnostico'),
    // documentos
    listaDocumentos: $('lista-documentos'),
    // analisis (comparativa contra referencias)
    inpBuscar: $('inp-buscar-analisis'),
    bannerReferencias: $('banner-referencias'),
    resumenAnalisis: $('resumen-analisis'),
    gruposAnalisis: $('grupos-analisis'),
    // detalle de un grupo
    tituloDetalle: $('titulo-detalle'),
    resumenDetalle: $('resumen-detalle'),
    graficoDetalle: $('grafico-detalle'),
    rejillaDetalle: $('rejilla-detalle'),
    // documento (lectura de un escaneo)
    tituloDocumento: $('titulo-documento'),
    estadoDocumento: $('estado-documento'),
    imgResultado: $('img-resultado'),
    metaInforme: $('meta-informe'),
    tablaEnvoltorio: $('tabla-envoltorio'),
    cuerpoTabla: document.querySelector('table.biomarcadores tbody'),
    accionesDocumento: $('acciones-documento'),
    enlaceDescarga: $('enlace-descarga'),
    detalleJson: $('detalle-json'),
    jsonResultado: $('json-resultado'),
    // asistente
    chatMensajes: $('chat-mensajes'),
    chatEntrada: $('chat-entrada'),
    btnEnviarChat: $('btn-enviar-chat'),
    // usuario
    inpNacimiento: $('inp-nacimiento'),
    selSexo: $('sel-sexo'),
    selCondicion: $('sel-condicion'),
    inpDistrito: $('inp-distrito'),
    listaDistritos: $('lista-distritos'),
    pistaDistrito: $('pista-distrito'),
    inpResidenciaDesde: $('inp-residencia-desde'),
    btnGuardarUsuario: $('btn-guardar-usuario'),
    estadoUsuario: $('estado-usuario'),
    metaSistema: $('meta-sistema'),
  };

  const estado = {
    config: null,
    formatos: {},
    vista: 'inicio',
    vistaPrevia: null,
    // cámara
    flujo: null,
    ws: null,
    enVuelo: false,
    ultimoEnvio: 0,
    deteccion: null,
    candidatos: null,
    configEnviada: null,
    panelCongeladoHasta: 0,
    quadPrevio: null,
    estables: 0,
    alineados: 0,
    alineado: false,
    capturando: false,
    activo: false,
    generacion: 0,
    // análisis y documento
    analisis: null,        // respuesta de /api/analisis, para filtrar sin repedir
    capturaActual: null,
    sondeo: null,
  };

  const lienzoAnalisis = document.createElement('canvas');
  const lienzoCaptura = document.createElement('canvas');

  const icono = (nombre, estilo = '') =>
    `<svg${estilo ? ` style="${estilo}"` : ''}><use href="#i-${nombre}" /></svg>`;

  function escapar(texto) {
    const nodo = document.createElement('span');
    nodo.textContent = texto === null || texto === undefined ? '' : String(texto);
    return nodo.innerHTML;
  }

  // ======================================================================
  // Navegación
  // ======================================================================

  const VISTAS = [
    'inicio', 'escanear', 'documentos', 'analisis', 'detalle', 'documento', 'asistente', 'usuario',
  ];
  // Vistas a las que no se llega por la barra inferior: llevan botón de volver.
  const VISTAS_SECUNDARIAS = ['usuario', 'detalle', 'documento'];
  // Qué pestaña de la barra queda marcada cuando se está en una vista secundaria.
  const PESTANA_DE = { detalle: 'analisis', documento: 'documentos', usuario: null };

  function irA(nombre) {
    if (!VISTAS.includes(nombre)) return;
    if (nombre !== estado.vista) estado.vistaPrevia = estado.vista;

    // La cámara se apaga al salir de escanear.
    if (estado.vista === 'escanear' && nombre !== 'escanear') pausarCamara();

    estado.vista = nombre;
    for (const vista of VISTAS) {
      $(`v-${vista}`).classList.toggle('activa', vista === nombre);
    }
    const pestana = nombre in PESTANA_DE ? PESTANA_DE[nombre] : nombre;
    for (const boton of document.querySelectorAll('.nav-inferior button')) {
      boton.classList.toggle('activa', boton.dataset.ir === pestana);
    }
    const secundaria = VISTAS_SECUNDARIAS.includes(nombre);
    el.btnAtras.classList.toggle('oculto', !secundaria);
    el.huecoIzq.classList.toggle('oculto', secundaria);
    window.scrollTo({ top: 0, behavior: 'instant' });

    if (nombre === 'inicio') cargarInicio();
    if (nombre === 'documentos') cargarDocumentos();
    if (nombre === 'analisis') cargarAnalisis();
    if (nombre === 'usuario') cargarUsuario();
    if (nombre === 'escanear' && estado.flujo) reanudarCamara();
  }

  // ======================================================================
  // Configuración
  // ======================================================================

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

    // 'F' y 'M' son los valores con los que la NTS 213 estratifica los rangos;
    // aquí solo se les pone la etiqueta que la persona lee.
    if (el.selSexo.options.length === 0) {
      const etiquetas = {
        F: 'Femenino',
        M: 'Masculino',
        femenino: 'Femenino',
        masculino: 'Masculino',
        otro: 'Otro',
        no_especificado: 'Prefiero no indicarlo',
      };
      for (const clave of estado.config.sexos || []) {
        const opcion = document.createElement('option');
        opcion.value = clave;
        opcion.textContent = etiquetas[clave] || clave;
        el.selSexo.appendChild(opcion);
      }
    }

    // La condición cambia el rango de hemoglobina en mujeres adultas: la NTS 213
    // trae tablas distintas para no gestante, cada trimestre y puerperio.
    if (el.selCondicion && el.selCondicion.options.length === 0) {
      const etiquetas = {
        general: 'Sin especificar',
        no_gestante: 'No gestante',
        gestante_t1: 'Gestante, 1.er trimestre',
        gestante_t2: 'Gestante, 2.º trimestre',
        gestante_t3: 'Gestante, 3.er trimestre',
        puerpera: 'Puérpera',
      };
      for (const clave of estado.config.condiciones || []) {
        const opcion = document.createElement('option');
        opcion.value = clave;
        opcion.textContent = etiquetas[clave] || clave;
        el.selCondicion.appendChild(opcion);
      }
    }
  }

  // Sugerencias de distrito desde el padrón. Se muestra el departamento y la
  // altitud porque hay nombres repetidos: cuatro Bellavista, y solo una a 13 msnm.
  async function sugerirDistritos() {
    const texto = el.inpDistrito.value.trim();
    if (texto.length < 2) {
      el.listaDistritos.innerHTML = '';
      el.pistaDistrito.textContent = '';
      return;
    }
    try {
      const datos = await (await fetch(`/api/distritos?q=${encodeURIComponent(texto)}`)).json();
      el.listaDistritos.innerHTML = (datos.distritos || [])
        .map((d) => {
          const altitud = d.altitud_msnm === null ? 'altitud sin dato' : `${d.altitud_msnm} msnm`;
          return `<option value="${escapar(d.clave_norm)}">${escapar(d.nombre)} · ${escapar(
            d.provincia
          )}, ${escapar(d.departamento)} · ${escapar(altitud)}</option>`;
        })
        .join('');
      const total = (datos.distritos || []).length;
      el.pistaDistrito.textContent = total
        ? `${total} distrito(s) en el padrón coinciden. Elige uno de la lista.`
        : 'Ningún distrito del padrón empieza así.';
    } catch (error) {
      el.listaDistritos.innerHTML = '';
    }
  }

  function formatoActual() {
    return estado.formatos[el.selFormato.value] || { ratio: 0 };
  }

  // ======================================================================
  // Vista: inicio
  // ======================================================================

  function saludoSegunHora() {
    const hora = new Date().getHours();
    if (hora < 12) return 'Muy buenos días';
    if (hora < 19) return 'Buenas tardes';
    return 'Buenas noches';
  }

  async function cargarInicio() {
    el.saludo.textContent = `${saludoSegunHora()}.`;

    let documentos = [];
    try {
      documentos = (await (await fetch('/api/informes')).json()).documentos || [];
    } catch (error) {
      documentos = [];
    }

    // Documentos recientes
    if (!documentos.length) {
      el.documentosRecientes.innerHTML =
        `<div class="vacio">${icono('documento')}<p class="body-md">Todavía no hay documentos.</p>
         <button class="btn btn-primario" data-ir="escanear" style="max-width:220px">Escanear el primero</button></div>`;
    } else {
      el.documentosRecientes.innerHTML = documentos
        .slice(0, 8)
        .map(
          (d) => `
          <button class="tarjeta-documento" data-documento="${escapar(d.id)}">
            <div class="icono-caja">${icono('documento')}</div>
            <div>
              <p class="label-md">${escapar(d.institucion_nombre || 'Documento')}</p>
              <p class="label-sm suave">${escapar(fechaCorta(d.fecha_carga))}</p>
            </div>
            <span class="chip ${d.total_valores ? 'chip-ok' : 'chip-duda'}">
              ${d.total_valores || 0} valores</span>
          </button>`,
        )
        .join('');
    }

    // Datos sobre ti: biomarcadores del documento más reciente
    const reciente = documentos.find((d) => d.total_valores > 0);
    if (!reciente) {
      el.seccionDatos.classList.add('oculto');
      el.estadoSalud.textContent = 'Sin datos';
      el.estadoSaludNota.textContent = 'Escanea un documento para empezar';
      return;
    }
    el.seccionDatos.classList.remove('oculto');

    let informe = null;
    try {
      informe = (await (await fetch(`/api/capturas/${reciente.id}/datos`)).json()).datos;
    } catch (error) {
      informe = null;
    }
    const filas = informe?.resultados || [];
    if (!filas.length) {
      el.seccionDatos.classList.add('oculto');
      return;
    }

    // Tres grupos, no dos: muchos valores llegan sin rango de referencia en el
    // documento y contarlos como "dentro de rango" seria afirmar algo que no
    // se sabe.
    const fuera = filas.filter((f) => f.fuera_de_rango === 1);
    const dentro = filas.filter((f) => f.fuera_de_rango === 0);
    const indeterminados = filas.filter((f) => f.fuera_de_rango === null);

    if (fuera.length) {
      el.estadoSalud.textContent = 'Requiere atención';
      el.estadoSaludNota.textContent =
        `${fuera.length} de ${filas.length} valores fuera de rango`;
    } else if (dentro.length) {
      el.estadoSalud.textContent = 'Buena salud';
      el.estadoSaludNota.textContent =
        `${dentro.length} valores dentro de rango` +
        (indeterminados.length ? ` · ${indeterminados.length} sin referencia` : '');
    } else {
      el.estadoSalud.textContent = 'Sin evaluar';
      el.estadoSaludNota.textContent =
        `${filas.length} valores leídos, ninguno traía rango de referencia`;
    }

    // Primero lo que está fuera de rango: es lo que el usuario debe ver.
    const ordenadas = [...fuera, ...filas.filter((f) => f.fuera_de_rango !== 1)].slice(0, 5);
    el.datosSobreTi.innerHTML = ordenadas
      .map((f) => {
        const clase = f.fuera_de_rango === 1 ? 'alerta' : f.fuera_de_rango === null ? 'aviso' : 'ok';
        const nombreIcono =
          f.fuera_de_rango === 1 ? 'alerta' : f.fuera_de_rango === null ? 'duda' : 'ok';
        const texto =
          f.fuera_de_rango === 1
            ? `${f.biomarcador} fuera de rango`
            : f.fuera_de_rango === null
              ? `${f.biomarcador} sin rango de referencia`
              : `${f.biomarcador} dentro del rango`;
        const valor = f.valor_texto ? `${f.valor_texto} ${f.unidad || ''}`.trim() : '';
        return `<div class="fila-dato ${clase}">
          ${icono(nombreIcono)}<p class="body-md">${escapar(texto)}</p>
          <span class="valor label-sm">${escapar(valor)}</span></div>`;
      })
      .join('');
  }

  function fechaCorta(iso) {
    if (!iso) return '';
    const fecha = new Date(String(iso).replace(' ', 'T'));
    if (Number.isNaN(fecha.getTime())) return String(iso).slice(0, 10);
    return fecha.toLocaleDateString('es-PE', { day: '2-digit', month: 'long', year: 'numeric' });
  }

  // ======================================================================
  // Vista: documentos
  // ======================================================================

  async function cargarDocumentos() {
    el.listaDocumentos.innerHTML = '<p class="estado espera">Cargando historial</p>';
    let documentos = [];
    try {
      documentos = (await (await fetch('/api/informes')).json()).documentos || [];
    } catch (error) {
      el.listaDocumentos.innerHTML = '<p class="aviso-error">No se pudo leer el historial.</p>';
      return;
    }
    if (!documentos.length) {
      el.listaDocumentos.innerHTML =
        `<div class="vacio">${icono('documento')}<p class="body-md">
          Tu historial está vacío. Cada documento que escanees aparecerá aquí.</p>
          <button class="btn btn-primario" data-ir="escanear" style="max-width:240px">Escanear documento</button></div>`;
      return;
    }
    el.listaDocumentos.innerHTML = documentos
      .map((d) => {
        const chip =
          d.estado_extraccion === 'procesado'
            ? `<span class="chip chip-ok">${d.total_valores} valores</span>`
            : `<span class="chip chip-alerta">sin leer</span>`;
        const sub = [fechaCorta(d.fecha_carga), d.distrito].filter(Boolean).join(' · ');
        return `
        <button class="tarjeta-lista" data-documento="${escapar(d.id)}">
          <span class="icono-caja">${icono('documento')}</span>
          <span class="cuerpo">
            <span class="titulo">${escapar(d.institucion_nombre || 'Documento sin membrete')}</span>
            <span class="sub">${escapar(sub)}</span>
          </span>
          ${chip}
          <span class="flecha">${icono('adelante')}</span>
        </button>`;
      })
      .join('');
  }

  // ======================================================================
  // Vista: análisis (comparativa del historial contra las referencias)
  // ======================================================================

  const ICONO_SISTEMA = {
    hematologia: 'gota',
    bioquimica: 'gota',
    orina: 'gota',
    sangre: 'gota',
    lipidos: 'gota',
    renal: 'gota',
    hepatico: 'gota',
    ginecologia: 'corazon',
    cardiovascular: 'corazon',
    signos_vitales: 'corazon',
    antropometria: 'analisis',
    tiroides: 'analisis',
    vision: 'ojo',
  };

  const TENDENCIAS = {
    mejora: { icono: 'sube', texto: 'Mejorando' },
    empeora: { icono: 'baja', texto: 'Empeorando' },
    estable: { icono: 'estable', texto: 'Estable' },
  };

  // La base guarda el sexo con la codificación del esquema v1.0 ('F' / 'M');
  // las instalaciones viejas tienen las palabras completas. Se cubren las dos.
  function etiquetaSexo(sexo) {
    const mapa = {
      F: 'mujeres', M: 'hombres',
      femenino: 'mujeres', masculino: 'hombres',
      otro: 'otro', no_especificado: 'sexo no indicado',
    };
    return mapa[sexo] || sexo || 'sexo no indicado';
  }

  async function cargarAnalisis() {
    el.resumenAnalisis.className = 'estado espera';
    el.resumenAnalisis.textContent = 'Comparando tus valores';
    try {
      estado.analisis = await (await fetch('/api/analisis')).json();
    } catch (error) {
      el.resumenAnalisis.className = 'estado error';
      el.resumenAnalisis.textContent = 'No se pudo cargar la comparativa.';
      return;
    }
    pintarAnalisis();
  }

  function pintarAnalisis() {
    const datos = estado.analisis;
    if (!datos) return;

    if (!datos.usuario) {
      el.bannerReferencias.innerHTML = '';
      el.resumenAnalisis.className = 'estado error';
      el.resumenAnalisis.textContent = datos.mensaje || 'Falta configurar el usuario local.';
      el.gruposAnalisis.innerHTML =
        `<button class="btn btn-primario" data-ir="usuario">Configurar usuario local</button>`;
      return;
    }

    const referencias = datos.referencias || {};
    if (!referencias.disponibles) {
      // Sin rangos cargados no se puede clasificar nada: se dice explícitamente
      // en lugar de mostrar porcentajes en cero, que se leerían como "todo mal".
      el.bannerReferencias.innerHTML = `<div class="banner">${icono('info')}<p>
        <strong>Faltan los rangos de referencia</strong>
        La tabla <code>rango_referencia</code> (OMS, MINSA) está vacía, así que
        todavía no se puede decir si un valor está dentro o fuera. Abajo está tu
        historial y su evolución; la clasificación aparece sola en cuanto se
        carguen los rangos.</p></div>`;
    } else {
      // De dónde salen los rangos: sin la fuente citada, el número no es
      // verificable y no debería usarse para nada.
      const fuentes = (referencias.fuentes || [])
        .map((f) => `${escapar(f.nombre)} (${f.rangos})`)
        .join(', ');
      const sinAtribuir = referencias.rangos_sin_atribuir
        ? ` ${referencias.rangos_sin_atribuir} rangos siguen sin organismo asignado
            (<code>POR_DEFINIR</code>) y no se pueden citar.`
        : '';
      el.bannerReferencias.innerHTML = `<div class="banner">${icono('info')}<p>
        <strong>${referencias.total_rangos} rangos de referencia cargados</strong>
        Fuentes: ${fuentes || 'sin atribuir'}.${sinAtribuir}</p></div>`;
    }

    const usuario = datos.usuario;
    el.resumenAnalisis.className = 'estado';
    el.resumenAnalisis.textContent =
      `${datos.total_biomarcadores} biomarcadores · ${datos.total_mediciones} mediciones · ` +
      `rangos para ${usuario.edad ?? '?'} años, ${etiquetaSexo(usuario.sexo)}`;

    const filtro = (el.inpBuscar.value || '').trim().toLowerCase();
    const grupos = (datos.grupos || [])
      .map((grupo) => ({
        ...grupo,
        coincidencias: filtro
          ? grupo.biomarcadores.filter(
              (b) =>
                b.nombre.toLowerCase().includes(filtro) ||
                grupo.etiqueta.toLowerCase().includes(filtro),
            )
          : grupo.biomarcadores,
      }))
      .filter((grupo) => grupo.coincidencias.length > 0);

    if (!grupos.length) {
      el.gruposAnalisis.innerHTML = filtro
        ? `<div class="vacio">${icono('buscar')}<p class="body-md">Nada coincide con "${escapar(filtro)}".</p></div>`
        : `<div class="vacio">${icono('analisis')}<p class="body-md">
             Todavía no hay mediciones. Escanea un documento para empezar tu historial.</p>
             <button class="btn btn-primario" data-ir="escanear" style="max-width:240px">Escanear documento</button></div>`;
      return;
    }

    el.gruposAnalisis.innerHTML = grupos.map((grupo) => tarjetaGrupo(grupo, filtro)).join('');
  }

  function tarjetaGrupo(grupo, filtro) {
    const hayFuera = grupo.fuera > 0;
    const clase = hayFuera ? 'alerta' : grupo.evaluados ? '' : 'neutro';
    const anillo = grupo.porcentaje === null
      ? `<div class="anillo neutro">sin<br />rangos</div>`
      : `<div class="anillo ${hayFuera ? 'alerta' : ''}">${grupo.porcentaje}%</div>`;

    const tendencia = grupo.tendencia && TENDENCIAS[grupo.tendencia]
      ? `<span class="tendencia ${grupo.tendencia}">
           ${icono(TENDENCIAS[grupo.tendencia].icono)} ${TENDENCIAS[grupo.tendencia].texto}</span>`
      : '';

    const detalle = grupo.porcentaje === null
      ? `${grupo.total} biomarcadores medidos, sin rango con el que comparar`
      : `${grupo.dentro} de ${grupo.evaluados} dentro de rango` +
        (grupo.sin_referencia ? ` · ${grupo.sin_referencia} sin referencia` : '');

    const nombres = (filtro ? grupo.coincidencias : grupo.biomarcadores)
      .slice(0, 4)
      .map((b) => b.nombre)
      .join(', ');

    return `
      <button class="tarjeta-grupo ${clase}" data-grupo="${escapar(grupo.sistema)}">
        <div class="cabecera">
          ${icono(ICONO_SISTEMA[grupo.sistema] || 'documento')}
          <h3>${escapar(grupo.etiqueta)}</h3>
        </div>
        <div class="cuerpo">
          ${anillo}
          <div class="resumen">
            <p>${escapar(detalle)}</p>
            ${tendencia}
            <p class="label-sm">${escapar(nombres)}${
              grupo.biomarcadores.length > 4 ? '...' : ''
            }</p>
          </div>
          <span class="flecha">${icono('adelante')}</span>
        </div>
      </button>`;
  }

  // ======================================================================
  // Vista: detalle de un grupo
  // ======================================================================

  const MARCA_ESTADO = {
    dentro: 'ok-circulo',
    fuera: 'fuera-circulo',
    sin_referencia: 'sin-dato',
    sin_valor: 'sin-dato',
  };

  function abrirDetalle(sistema) {
    const grupo = (estado.analisis?.grupos || []).find((g) => g.sistema === sistema);
    if (!grupo) return;
    irA('detalle');

    el.tituloDetalle.textContent = grupo.etiqueta;

    const encabezado = grupo.porcentaje === null
      ? `<h2 class="headline-md">Sin clasificar</h2>
         <p class="body-md suave">${grupo.total} biomarcadores medidos. Falta cargar los
         rangos de referencia para poder decir si están bien o mal.</p>`
      : `<h2 class="headline-md">${grupo.porcentaje}% dentro de rango</h2>
         <p class="body-md suave">${grupo.dentro} de ${grupo.evaluados} biomarcadores
         evaluados${grupo.sin_referencia ? `, ${grupo.sin_referencia} sin referencia` : ''}.</p>`;
    const tendencia = grupo.tendencia && TENDENCIAS[grupo.tendencia]
      ? `<span class="tendencia ${grupo.tendencia}" style="margin-top:8px">
           ${icono(TENDENCIAS[grupo.tendencia].icono)} ${TENDENCIAS[grupo.tendencia].texto}
           respecto a la medición anterior</span>`
      : '';
    el.resumenDetalle.innerHTML = encabezado + tendencia;

    el.graficoDetalle.innerHTML = grafico(grupo.biomarcadores);
    el.rejillaDetalle.innerHTML = grupo.biomarcadores.map(tarjetaBiomarcador).join('');
  }

  function tarjetaBiomarcador(b) {
    const valor = b.ultimo.valor !== null
      ? `${b.ultimo.valor}<span class="unidad"> ${escapar(b.unidad || '')}</span>`
      : escapar(b.ultimo.texto || 'sin valor');
    // POR_DEFINIR es el marcador de un rango cargado sin organismo asignado. Se
    // dice tal cual en vez de mostrarlo como si fuera el nombre de una fuente.
    const fuente = !b.referencia
      ? ''
      : b.referencia.fuente === 'POR_DEFINIR'
        ? ' · fuente sin citar'
        : ` · ${escapar(b.referencia.fuente)}`;
    const rango = b.referencia
      ? `Rango ${b.referencia.min} a ${b.referencia.max} ${escapar(b.referencia.unidad || '')}${fuente}`
      : 'Sin rango de referencia cargado';
    const mediciones = b.mediciones > 1 ? ` · ${b.mediciones} mediciones` : '';
    return `
      <div class="tarjeta-biomarcador ${b.estado}">
        <span class="nombre">${escapar(b.nombre)}</span>
        <span class="valor">${valor}</span>
        <span class="rango">${rango}${mediciones}</span>
        <span class="marca-estado">${icono(MARCA_ESTADO[b.estado] || 'sin-dato')}</span>
      </div>`;
  }

  // Gráfico de líneas propio: una línea por biomarcador con 2+ mediciones
  // numéricas. Cada serie se normaliza a su propio mínimo y máximo, porque
  // mezclar mg/dL con g/dL en un eje común no diría nada.
  const COLORES_SERIE = ['#4d6700', '#67587d', '#a7c957', '#615f4b', '#ba1a1a', '#b0d360'];

  function grafico(biomarcadores) {
    const series = biomarcadores
      .map((b) => ({
        nombre: b.nombre,
        puntos: b.historial.filter((h) => h.valor !== null),
      }))
      .filter((s) => s.puntos.length >= 2)
      .slice(0, 6);

    if (!series.length) {
      return `<p class="body-md suave">
        Hace falta al menos un biomarcador con dos mediciones para dibujar una
        tendencia. Escanea otro documento del mismo tipo y aparecerá aquí.</p>`;
    }

    const ANCHO = 300;
    const ALTO = 120;
    const maxPuntos = Math.max(...series.map((s) => s.puntos.length));
    const trazos = series
      .map((serie, indice) => {
        const valores = serie.puntos.map((p) => p.valor);
        const minimo = Math.min(...valores);
        const maximo = Math.max(...valores);
        const rango = maximo - minimo || 1;
        const coords = serie.puntos.map((punto, i) => {
          const x = maxPuntos === 1 ? ANCHO / 2 : (i / (maxPuntos - 1)) * ANCHO;
          const y = ALTO - ((punto.valor - minimo) / rango) * (ALTO - 12) - 6;
          return [x, y];
        });
        const color = COLORES_SERIE[indice % COLORES_SERIE.length];
        const linea = coords.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
        const circulos = coords
          .map(([x, y]) => `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="2.5" fill="${color}" />`)
          .join('');
        return `<path d="${linea}" fill="none" stroke="${color}" stroke-width="1.8"
                  stroke-linecap="round" stroke-linejoin="round" />${circulos}`;
      })
      .join('');

    const leyenda = series
      .map(
        (serie, indice) =>
          `<span><i style="background:${COLORES_SERIE[indice % COLORES_SERIE.length]}"></i>
             ${escapar(serie.nombre)}</span>`,
      )
      .join('');

    return `
      <svg viewBox="0 0 ${ANCHO} ${ALTO}" preserveAspectRatio="none" role="img"
           aria-label="Tendencia de los biomarcadores">
        <line x1="0" y1="${ALTO}" x2="${ANCHO}" y2="${ALTO}" stroke="#c5c9b4" stroke-width="1" />
        ${trazos}
      </svg>
      <div class="leyenda">${leyenda}</div>
      <p class="label-sm suave" style="margin-top:8px">
        Cada serie está escalada a su propio mínimo y máximo: el gráfico muestra la
        dirección del cambio, no la magnitud comparada entre biomarcadores.</p>`;
  }

  // ======================================================================
  // Vista: documento (lectura de un escaneo)
  // ======================================================================

  async function abrirDocumento(capturaId) {
    estado.capturaActual = capturaId;
    irA('documento');
    el.estadoDocumento.className = 'estado espera';
    el.estadoDocumento.textContent = 'Cargando la lectura del documento';
    try {
      const respuesta = await fetch(`/api/capturas/${capturaId}/datos`);
      if (!respuesta.ok) throw new Error('no hay lectura guardada para este documento');
      const cuerpo = await respuesta.json();
      mostrarDocumento(cuerpo.datos, capturaId);
    } catch (error) {
      el.estadoDocumento.className = 'estado error';
      el.estadoDocumento.textContent = `No se pudo cargar: ${error.message}`;
      for (const nodo of [el.imgResultado, el.metaInforme, el.tablaEnvoltorio, el.detalleJson]) {
        nodo.classList.add('oculto');
      }
    }
  }

  function mostrarDocumento(datos, capturaId) {
    el.jsonResultado.textContent = JSON.stringify(datos, null, 2);
    el.detalleJson.classList.remove('oculto');
    el.accionesDocumento.classList.remove('oculto');
    el.accionesDocumento.style.display = 'flex';

    const archivo = datos?.captura_archivo;
    if (archivo) {
      el.imgResultado.src = `/capturas/${archivo}`;
      el.imgResultado.classList.remove('oculto');
      el.enlaceDescarga.href = `/capturas/${archivo}`;
      el.enlaceDescarga.setAttribute('download', archivo);
    } else {
      el.imgResultado.classList.add('oculto');
    }

    const estadoInforme = datos?.estado;
    if (estadoInforme === 'en_proceso') {
      el.estadoDocumento.className = 'estado espera';
      el.estadoDocumento.textContent = `Leyendo el documento con ${datos.modelo || 'el modelo'}`;
      el.metaInforme.classList.add('oculto');
      el.tablaEnvoltorio.classList.add('oculto');
      sondearDocumento(capturaId);
      return;
    }
    if (estadoInforme === 'sin_clave') {
      el.estadoDocumento.className = 'estado';
      el.estadoDocumento.textContent =
        'Extracción desactivada: falta la clave del modelo en el servidor.';
      el.metaInforme.classList.add('oculto');
      el.tablaEnvoltorio.classList.add('oculto');
      return;
    }
    if (estadoInforme !== 'ok') {
      el.estadoDocumento.className = 'estado error';
      el.estadoDocumento.textContent = `No se pudo extraer (${estadoInforme || 'desconocido'}): ${
        datos?.error || 'sin detalle'
      }`;
      el.metaInforme.classList.add('oculto');
      el.tablaEnvoltorio.classList.add('oculto');
      return;
    }

    const filas = datos.resultados || [];
    const total = filas.length;
    const fuera = filas.filter((f) => f.fuera_de_rango === 1).length;
    const dentro = filas.filter((f) => f.fuera_de_rango === 0).length;
    const sinReferencia = filas.filter((f) => f.fuera_de_rango === null).length;

    el.tituloDocumento.textContent = datos.centro_medico || 'Análisis de salud';
    // "todos dentro de rango" solo se puede decir si de verdad se comparó cada
    // valor contra un rango. Los que no traían referencia se cuentan aparte.
    if (fuera) {
      el.estadoDocumento.className = 'estado error';
      el.estadoDocumento.textContent = `${total} biomarcadores · ${fuera} fuera de rango`;
    } else if (dentro) {
      el.estadoDocumento.className = 'estado ok';
      el.estadoDocumento.textContent =
        `${total} biomarcadores · ${dentro} dentro de rango` +
        (sinReferencia ? ` · ${sinReferencia} sin referencia` : '');
    } else {
      el.estadoDocumento.className = 'estado';
      el.estadoDocumento.textContent =
        `${total} biomarcador${total === 1 ? '' : 'es'} · ninguno traía rango de referencia en el documento`;
    }

    const bd = datos.persistencia?.base_de_datos;
    let textoBd = null;
    if (bd?.guardado) {
      textoBd = `sí · ${bd.valores} valores`;
      if (bd.biomarcadores_nuevos) textoBd += ` · ${bd.biomarcadores_nuevos} biomarcador(es) nuevo(s)`;
    } else if (bd) {
      textoBd = `no (${bd.motivo})`;
    }

    const cabecera = [
      ['Centro médico', datos.centro_medico],
      ['Distrito', datos.ubicacion],
      ['Fecha del documento', datos.fecha_documento],
      ['Modelo', datos.modelo],
      ['Tiempo de lectura', datos.ms_respuesta ? `${(datos.ms_respuesta / 1000).toFixed(1)} s` : null],
      ['Segmentos', datos.crudo ? null : null],
      ['En base de datos', textoBd],
    ].filter(([, valor]) => valor);
    el.metaInforme.innerHTML = cabecera
      .map(([clave, valor]) => `<dt>${escapar(clave)}</dt><dd>${escapar(valor)}</dd>`)
      .join('');
    el.metaInforme.classList.toggle('oculto', cabecera.length === 0);

    el.cuerpoTabla.innerHTML = (datos.resultados || [])
      .map((fila) => {
        const alerta = fila.fuera_de_rango === 1;
        const dudoso = fila.fuera_de_rango === null;
        const chip = alerta
          ? '<span class="chip chip-alerta">fuera</span>'
          : dudoso
            ? '<span class="chip chip-duda">?</span>'
            : '<span class="chip chip-ok">ok</span>';
        return (
          `<tr class="${alerta ? 'alerta' : ''}">` +
          `<td>${escapar(fila.biomarcador)}</td>` +
          `<td>${escapar(fila.valor_texto ?? '')}</td>` +
          `<td>${escapar(fila.unidad ?? '')}</td>` +
          `<td>${escapar(fila.rango_texto ?? '')}</td>` +
          `<td>${chip}</td></tr>`
        );
      })
      .join('');
    el.tablaEnvoltorio.classList.toggle('oculto', !(datos.resultados || []).length);
  }

  function sondearDocumento(capturaId) {
    if (estado.sondeo) clearTimeout(estado.sondeo);
    let intentos = 0;
    const arranque = Date.now();
    const consultar = async () => {
      if (estado.capturaActual !== capturaId) return;
      intentos += 1;
      const segundos = Math.round((Date.now() - arranque) / 1000);
      el.estadoDocumento.textContent =
        `Leyendo el documento con ${estado.config?.extraccion?.modelo || 'el modelo'} (${segundos} s)`;
      try {
        const respuesta = await fetch(`/api/capturas/${capturaId}/datos`);
        if (respuesta.ok) {
          const cuerpo = await respuesta.json();
          if (cuerpo.datos?.estado !== 'en_proceso') {
            mostrarDocumento(cuerpo.datos, capturaId);
            cargarInicio();
            return;
          }
        }
      } catch (error) {
        /* corte momentáneo: se reintenta */
      }
      if (intentos >= SONDEOS_MAXIMOS) {
        el.estadoDocumento.className = 'estado error';
        el.estadoDocumento.textContent =
          'El análisis tarda más de lo esperado. El documento ya está guardado.';
        return;
      }
      estado.sondeo = setTimeout(consultar, INTERVALO_SONDEO_MS);
    };
    estado.sondeo = setTimeout(consultar, INTERVALO_SONDEO_MS);
  }

  // ======================================================================
  // Vista: usuario
  // ======================================================================

  async function cargarUsuario() {
    try {
      const usuario = (await (await fetch('/api/usuario')).json()).usuario;
      if (usuario) {
        el.inpNacimiento.value = usuario.fecha_nacimiento || '';
        el.selSexo.value = usuario.sexo || '';
        el.selCondicion.value = usuario.condicion || 'general';
        el.inpDistrito.value = usuario.distrito_residencia || '';
        el.inpResidenciaDesde.value = usuario.residencia_desde || '';
        el.estadoUsuario.className = 'estado ok';
        el.estadoUsuario.textContent = usuario.clave_distrito_residencia
          ? 'Usuario local configurado.'
          : 'Usuario configurado, pero sin distrito: la hemoglobina no se puede ajustar por altitud.';
      } else {
        el.estadoUsuario.className = 'estado';
        el.estadoUsuario.textContent =
          'Sin esto la extracción se guarda en JSON pero no entra a la base de datos.';
      }
    } catch (error) {
      /* se deja el formulario vacío */
    }

    try {
      const bd = await (await fetch('/api/basedatos')).json();
      const filas = [
        ['Versión', estado.config?.version],
        ['Extracción', estado.config?.extraccion?.activa
          ? `activa · ${estado.config.extraccion.modelo}`
          : 'desactivada (falta la clave)'],
        ['Base de datos', `${bd.tablas} tablas`],
        ['Documentos', bd.activas?.documento ?? 0],
        ['Valores extraídos', bd.activas?.valor_extraido ?? 0],
        ['Biomarcadores', bd.activas?.biomarcador ?? 0],
        ['Rangos de referencia', bd.referencia?.rango_referencia ?? 0],
        ['Distritos con altitud', bd.referencia?.distrito ?? 0],
        ['Establecimientos', bd.referencia?.establecimiento_salud ?? 0],
      ].filter(([, valor]) => valor !== undefined && valor !== null);
      el.metaSistema.innerHTML = filas
        .map(([c, v]) => `<dt>${escapar(c)}</dt><dd>${escapar(v)}</dd>`)
        .join('');
    } catch (error) {
      el.metaSistema.innerHTML = '';
    }
  }

  async function guardarUsuario() {
    if (!el.inpNacimiento.value) {
      el.estadoUsuario.className = 'estado error';
      el.estadoUsuario.textContent = 'Falta la fecha de nacimiento.';
      return;
    }
    el.btnGuardarUsuario.disabled = true;
    try {
      const cuerpo = new FormData();
      cuerpo.append('fecha_nacimiento', el.inpNacimiento.value);
      cuerpo.append('sexo', el.selSexo.value);
      cuerpo.append('condicion', el.selCondicion.value || 'general');
      cuerpo.append('distrito_residencia', el.inpDistrito.value.trim());
      cuerpo.append('residencia_desde', el.inpResidenciaDesde.value || '');
      const datos = await (await fetch('/api/usuario', { method: 'POST', body: cuerpo })).json();
      if (!datos.ok) throw new Error(datos.error || 'no se pudo guardar');
      if (estado.config) estado.config.usuario_configurado = true;
      el.estadoUsuario.className = 'estado ok';
      el.estadoUsuario.textContent = 'Usuario local guardado.';
      cargarUsuario();
    } catch (error) {
      el.estadoUsuario.className = 'estado error';
      el.estadoUsuario.textContent = `Error: ${error.message}`;
    } finally {
      el.btnGuardarUsuario.disabled = false;
    }
  }

  // ======================================================================
  // Cámara: geometría del visor
  // ======================================================================

  function ajustarVisor() {
    const ancho = el.video.videoWidth;
    const alto = el.video.videoHeight;
    if (ancho && alto) el.visor.style.aspectRatio = `${ancho} / ${alto}`;
  }

  function rectContenido() {
    const anchoCaja = el.lienzo.clientWidth;
    const altoCaja = el.lienzo.clientHeight;
    const anchoVideo = el.video.videoWidth || anchoCaja;
    const altoVideo = el.video.videoHeight || altoCaja;
    const escala = Math.min(anchoCaja / anchoVideo, altoCaja / altoVideo);
    const ancho = anchoVideo * escala;
    const alto = altoVideo * escala;
    return { x: (anchoCaja - ancho) / 2, y: (altoCaja - alto) / 2, ancho, alto };
  }

  function rectGuia(rect) {
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

  function guiaNormalizada() {
    const rect = rectContenido();
    if (!rect.ancho || !rect.alto) return null;
    const guia = rectGuia(rect);
    return [
      +((guia.x - rect.x) / rect.ancho).toFixed(4),
      +((guia.y - rect.y) / rect.alto).toFixed(4),
      +(guia.ancho / rect.ancho).toFixed(4),
      +(guia.alto / rect.alto).toFixed(4),
    ];
  }

  // ======================================================================
  // Cámara: dibujo del visor
  // ======================================================================

  // Colores del sistema de diseño, leídos del CSS para no duplicarlos aquí.
  const tema = getComputedStyle(document.documentElement);
  const COLOR_PRIMARIO = tema.getPropertyValue('--primary').trim() || '#4d6700';
  const COLOR_AVISO = tema.getPropertyValue('--aviso').trim() || '#c2610a';

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

    if (el.chkDiagnostico.checked && estado.candidatos) {
      dibujarCandidatos(ctx, estado.candidatos, rect);
    }
    const deteccion = estado.deteccion;
    if (deteccion && Date.now() - deteccion.momento < 900) {
      dibujarQuad(ctx, deteccion.quad, rect, estado.alineado);
    }
    requestAnimationFrame(() => dibujar(generacion));
  }

  function dibujarGuia(ctx, guia) {
    // DESIGN.md: "the viewfinder should have 2px thick corner brackets in the
    // primary green". Sin rectángulo punteado: el diseño solo lleva esquinas.
    ctx.save();
    const largo = Math.min(guia.ancho, guia.alto) * 0.16;
    ctx.strokeStyle = COLOR_PRIMARIO;
    ctx.globalAlpha = 0.85;
    ctx.lineWidth = 3;
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
    const color = alineado ? COLOR_PRIMARIO : COLOR_AVISO;
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(puntos[0][0], puntos[0][1]);
    for (let i = 1; i < puntos.length; i += 1) ctx.lineTo(puntos[i][0], puntos[i][1]);
    ctx.closePath();
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.18;
    ctx.fill();
    ctx.globalAlpha = 1;
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.stroke();
    ctx.fillStyle = color;
    for (const [x, y] of puntos) {
      ctx.beginPath();
      ctx.arc(x, y, 6, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  function dibujarCandidatos(ctx, candidatos, rect) {
    ctx.save();
    ctx.font = '11px Manrope, sans-serif';
    for (const candidato of candidatos) {
      if (candidato.aceptado) continue;
      const puntos = candidato.quad.map(([x, y]) => [
        rect.x + x * rect.ancho,
        rect.y + y * rect.alto,
      ]);
      ctx.beginPath();
      ctx.moveTo(puntos[0][0], puntos[0][1]);
      for (let i = 1; i < puntos.length; i += 1) ctx.lineTo(puntos[i][0], puntos[i][1]);
      ctx.closePath();
      ctx.strokeStyle = 'rgba(117, 121, 103, 0.8)';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = 'rgba(255,255,255,0.9)';
      ctx.fillText(
        `${candidato.puntaje.toFixed(2)} ${candidato.metodo} ${candidato.rechazo || ''}`,
        puntos[0][0] + 4,
        puntos[0][1] - 4,
      );
    }
    ctx.restore();
  }

  function actualizarPanelDiagnostico(respuesta) {
    if (!el.chkDiagnostico.checked) {
      el.panelDiagnostico.classList.add('oculto');
      return;
    }
    el.panelDiagnostico.classList.remove('oculto');
    if (Date.now() < estado.panelCongeladoHasta) return;
    if (!respuesta.encontrado) {
      const descartados = (respuesta.candidatos || [])
        .map((c) => `${c.puntaje.toFixed(2)} ${c.metodo} -> ${c.rechazo}`)
        .join('\n');
      el.panelDiagnostico.textContent = descartados
        ? `Sin documento aceptado.\n${descartados}`
        : 'Sin candidatos: no se halló ningún cuadrilátero.';
      return;
    }
    const componentes = Object.entries(respuesta.componentes || {})
      .map(([clave, valor]) => `${clave} ${valor.toFixed(2)}`)
      .join('  |  ');
    const papel = respuesta.papel_detalle;
    const lineas = [
      `ganador: ${respuesta.metodo}  puntaje ${respuesta.puntaje.toFixed(3)}  area ${respuesta.area.toFixed(2)}`,
      componentes,
    ];
    if (papel) {
      lineas.push(
        `papel: cobertura ${papel.cobertura.toFixed(2)}  contraste ${papel.contraste.toFixed(2)}  ` +
          `V dentro ${papel.valor_dentro} / fuera ${papel.valor_fuera ?? '-'}  S ${papel.saturacion_dentro}`,
      );
    }
    el.panelDiagnostico.textContent = lineas.join('\n');
  }

  // ======================================================================
  // Cámara: flujo y WebSocket
  // ======================================================================

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
    el.visorVacio.classList.add('oculto');
    el.pista.classList.remove('oculto');
    el.btnActivar.classList.add('oculto');
    el.btnCapturar.classList.remove('oculto');
  }

  function detenerFlujo() {
    if (estado.flujo) {
      estado.flujo.getTracks().forEach((pista) => pista.stop());
      estado.flujo = null;
    }
  }

  function pausarCamara() {
    estado.activo = false;
    estado.generacion += 1;
    detenerFlujo();
    if (estado.ws) {
      estado.ws.onclose = null;
      estado.ws.close();
      estado.ws = null;
    }
    estado.deteccion = null;
    estado.candidatos = null;
    el.visorVacio.classList.remove('oculto');
    el.pista.classList.add('oculto');
    el.btnActivar.classList.remove('oculto');
    el.btnCapturar.classList.add('oculto');
  }

  async function reanudarCamara() {
    // Al volver a la vista se vuelve a pedir la cámara: el flujo se cortó al salir.
    try {
      await activarCamara(el.selCamara.value || undefined);
      conectar();
      arrancarBucles();
    } catch (error) {
      el.errorCamara.textContent = descifrarError(error);
      el.errorCamara.classList.remove('oculto');
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
      opcion.textContent = camara.label || `Cámara ${indice + 1}`;
      el.selCamara.appendChild(opcion);
    });
    const activa = estado.flujo?.getVideoTracks()[0]?.getSettings()?.deviceId;
    if (activa) el.selCamara.value = activa;
    el.envoltorioCamaras.classList.remove('oculto');
  }

  function conectar() {
    const esquema = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${esquema}://${location.host}/ws/deteccion`);
    ws.binaryType = 'arraybuffer';
    estado.ws = ws;

    ws.onopen = () => {
      estado.configEnviada = null;
      enviarConfig(true);
    };
    ws.onclose = () => {
      estado.enVuelo = false;
      estado.configEnviada = null;
      if (estado.activo) setTimeout(conectar, 1200);
    };
    ws.onmessage = (evento) => {
      let respuesta;
      try {
        respuesta = JSON.parse(evento.data);
      } catch (error) {
        estado.enVuelo = false;
        return;
      }
      if (respuesta.tipo === 'config') return;
      estado.enVuelo = false;
      procesarDeteccion(respuesta);
    };
  }

  function enviarConfig(forzar = false) {
    if (estado.ws?.readyState !== WebSocket.OPEN) return;
    const guia = guiaNormalizada();
    if (!guia) return;
    const config = {
      guia,
      ratio: el.chkAjustar.checked ? formatoActual().ratio : 0,
      candidatos: el.chkDiagnostico.checked,
    };
    const serializada = JSON.stringify(config);
    if (!forzar && serializada === estado.configEnviada) return;
    estado.configEnviada = serializada;
    estado.ws.send(serializada);
  }

  function procesarDeteccion(respuesta) {
    estado.candidatos = respuesta.candidatos || null;
    actualizarPanelDiagnostico(respuesta);

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
      actualizarPista('Mantén el pulso...', 'aviso');
      return;
    }

    estado.alineados += 1;
    if (el.chkAuto.checked) {
      const faltan = Math.max(CUADROS_AUTO - estado.alineados, 0);
      actualizarPista(faltan ? `Capturando en ${faltan}...` : 'Capturando...', 'ok');
      if (estado.alineados >= CUADROS_AUTO && !estado.capturando) capturar();
    } else {
      actualizarPista('Documento alineado', 'ok');
    }
  }

  function evaluarEncuadre(deteccion) {
    if (deteccion.area < AREA_MINIMA_ALINEADO) return 'Acerca más el documento';
    if (deteccion.puntaje < PUNTAJE_MINIMO_ALINEADO) return 'Endereza un poco el documento';
    const fuera = deteccion.quad.some(
      ([x, y]) => x < MARGEN_BORDE || y < MARGEN_BORDE || x > 1 - MARGEN_BORDE || y > 1 - MARGEN_BORDE,
    );
    if (fuera) return 'El documento se sale del cuadro';

    const ratioFormato = formatoActual().ratio;
    if (ratioFormato > 0 && el.chkAjustar.checked) {
      const medido = proporcionDetectada(deteccion.quad);
      if (medido && Math.abs(medido - ratioFormato) / ratioFormato > TOLERANCIA_PROPORCION) {
        return 'Gira el documento o cambia el formato';
      }
    }
    return null;
  }

  function proporcionDetectada(quad) {
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

  function bucleAnalisis(generacion) {
    if (!estado.activo || generacion !== estado.generacion) return;
    enviarConfig();
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

  // ======================================================================
  // Captura
  // ======================================================================

  function cuadroActualJpeg(calidad) {
    lienzoCaptura.width = el.video.videoWidth;
    lienzoCaptura.height = el.video.videoHeight;
    lienzoCaptura.getContext('2d').drawImage(el.video, 0, 0);
    return new Promise((listo) => lienzoCaptura.toBlob(listo, 'image/jpeg', calidad));
  }

  async function capturar() {
    if (estado.capturando || !el.video.videoWidth) return;
    estado.capturando = true;
    el.btnCapturar.disabled = true;
    actualizarPista('Procesando...', '');

    try {
      const blob = await cuadroActualJpeg(0.95);
      const cuerpo = new FormData();
      cuerpo.append('imagen', blob, 'captura.jpg');
      cuerpo.append('formato', el.selFormato.value);
      cuerpo.append('modo', el.selModo.value);
      cuerpo.append('ajustar_formato', el.chkAjustar.checked ? 'true' : 'false');
      const guia = guiaNormalizada();
      if (guia) cuerpo.append('guia', JSON.stringify(guia));

      const deteccion = estado.deteccion;
      if (deteccion && Date.now() - deteccion.momento < VIGENCIA_QUAD_MS) {
        cuerpo.append('quad', JSON.stringify(deteccion.quad));
      }

      const datos = await (await fetch('/api/capturar', { method: 'POST', body: cuerpo })).json();
      if (!datos.ok) throw new Error(datos.error || 'falló la captura');

      estado.capturaActual = datos.captura.id;
      irA('documento');
      mostrarDocumento(
        { ...datos.datos, captura_archivo: datos.captura.archivo },
        datos.captura.id,
      );
    } catch (error) {
      actualizarPista(`Error: ${error.message}`, 'aviso');
    } finally {
      estado.capturando = false;
      el.btnCapturar.disabled = false;
    }
  }

  async function guardarDiagnostico() {
    if (!el.video.videoWidth) return;
    el.btnDiagnostico.disabled = true;
    const textoPrevio = el.btnDiagnostico.textContent;
    el.btnDiagnostico.textContent = 'Guardando...';
    try {
      const blob = await cuadroActualJpeg(0.92);
      const cuerpo = new FormData();
      cuerpo.append('imagen', blob, 'diagnostico.jpg');
      cuerpo.append('formato', el.selFormato.value);
      const guia = guiaNormalizada();
      if (guia) cuerpo.append('guia', JSON.stringify(guia));
      const datos = await (await fetch('/api/diagnostico', { method: 'POST', body: cuerpo })).json();
      if (!datos.ok) throw new Error(datos.error || 'falló el diagnóstico');
      el.panelDiagnostico.classList.remove('oculto');
      estado.panelCongeladoHasta = Date.now() + 12000;
      el.panelDiagnostico.textContent =
        `Guardado: ${datos.base}\ncandidatos: ${datos.informe.candidatos.length}  ` +
        `encontrado: ${datos.informe.encontrado}\n` +
        JSON.stringify(datos.informe.ganador ?? datos.informe.candidatos.slice(0, 3), null, 1);
      el.btnDiagnostico.textContent = 'Guardado';
      setTimeout(() => { el.btnDiagnostico.textContent = textoPrevio; }, 1500);
    } catch (error) {
      el.btnDiagnostico.textContent = `Error: ${error.message}`;
    } finally {
      el.btnDiagnostico.disabled = false;
    }
  }

  function descifrarError(error) {
    const nombre = error?.name || '';
    if (nombre === 'NotAllowedError') {
      return 'Permiso de cámara denegado. Habilítalo en el candado de la barra de direcciones y recarga.';
    }
    if (nombre === 'NotFoundError' || nombre === 'OverconstrainedError') {
      return 'No se encontró una cámara compatible en este dispositivo.';
    }
    if (nombre === 'NotReadableError') {
      return 'La cámara está ocupada por otra aplicación. Ciérrala e intenta de nuevo.';
    }
    return error?.message || 'No se pudo iniciar la cámara.';
  }

  // ======================================================================
  // Asistente (pendiente de conectar)
  // ======================================================================

  function enviarChat() {
    const texto = el.chatEntrada.value.trim();
    if (!texto) return;
    agregarMensaje(texto, 'usuario');
    el.chatEntrada.value = '';
    agregarMensaje(
      'El asistente todavía no está conectado. Mientras tanto, tus valores están en ' +
        'Análisis y el historial completo en Documentos.',
      'asistente',
    );
  }

  function agregarMensaje(texto, quien) {
    const burbuja = document.createElement('div');
    const propio = quien === 'usuario';
    burbuja.className = propio ? 'tarjeta' : 'tarjeta-crema';
    burbuja.style.maxWidth = '85%';
    burbuja.style.alignSelf = propio ? 'flex-end' : 'flex-start';
    burbuja.innerHTML = `<p class="body-md">${escapar(texto)}</p>`;
    el.chatMensajes.appendChild(burbuja);
    burbuja.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  // ======================================================================
  // Arranque
  // ======================================================================

  document.addEventListener('click', (evento) => {
    const irBoton = evento.target.closest('[data-ir]');
    if (irBoton) {
      irA(irBoton.dataset.ir);
      return;
    }
    const tarjetaGrupoPulsada = evento.target.closest('[data-grupo]');
    if (tarjetaGrupoPulsada) {
      abrirDetalle(tarjetaGrupoPulsada.dataset.grupo);
      return;
    }
    const tarjeta = evento.target.closest('[data-documento]');
    if (tarjeta) abrirDocumento(tarjeta.dataset.documento);
  });

  // El filtro se aplica sobre los datos ya cargados: no vuelve a pedir nada.
  el.inpBuscar.addEventListener('input', () => pintarAnalisis());

  el.btnPerfil.addEventListener('click', () => irA('usuario'));
  el.btnAtras.addEventListener('click', () => irA(estado.vistaPrevia || 'inicio'));
  el.btnGuardarUsuario.addEventListener('click', guardarUsuario);
  el.inpDistrito.addEventListener('input', sugerirDistritos);
  el.btnCapturar.addEventListener('click', capturar);
  el.btnDiagnostico.addEventListener('click', guardarDiagnostico);
  el.btnEnviarChat.addEventListener('click', enviarChat);
  el.chatEntrada.addEventListener('keydown', (evento) => {
    if (evento.key === 'Enter' && !evento.shiftKey) {
      evento.preventDefault();
      enviarChat();
    }
  });
  el.selCamara.addEventListener('change', () => activarCamara(el.selCamara.value));
  el.selFormato.addEventListener('change', () => enviarConfig());
  el.chkAjustar.addEventListener('change', () => enviarConfig());
  el.chkDiagnostico.addEventListener('change', () => {
    estado.candidatos = null;
    el.btnDiagnostico.classList.toggle('oculto', !el.chkDiagnostico.checked);
    el.panelDiagnostico.classList.toggle('oculto', !el.chkDiagnostico.checked);
    enviarConfig();
  });
  el.video.addEventListener('loadedmetadata', ajustarVisor);
  window.addEventListener('orientationchange', () => setTimeout(ajustarVisor, 300));

  el.btnActivar.addEventListener('click', async () => {
    el.btnActivar.disabled = true;
    el.errorCamara.classList.add('oculto');
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error(
          'Este navegador no expone la cámara. Se necesita HTTPS (o localhost) y un navegador moderno.',
        );
      }
      if (!estado.config) await cargarConfig();
      await activarCamara();
      await listarCamaras();
      conectar();
      arrancarBucles();
    } catch (error) {
      el.errorCamara.textContent = descifrarError(error);
      el.errorCamara.classList.remove('oculto');
    } finally {
      el.btnActivar.disabled = false;
    }
  });

  cargarConfig()
    .then(() => {
      cargarInicio();
      // Si no hay usuario local, se lleva ahí primero: sin eso no entra nada a
      // la base de datos y conviene resolverlo antes de escanear.
      if (estado.config && !estado.config.usuario_configurado) irA('usuario');
    })
    .catch(() => {
      el.saludo.textContent = 'Sin conexión con el servidor.';
    });
})();
