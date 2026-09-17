/* =========================================================================
   Gráficos del panel (portada y Analítica). Requiere Chart.js 4 (CDN).
   -------------------------------------------------------------------------
   Cómo funciona:
   1. El template embebe los datos iniciales con {{ datos|json_script }}.
   2. PanelGraficos.init() dibuja los 4 gráficos con esos datos.
   3. Si hay un selector de rango (portada), al cambiarlo se pide de nuevo
      la serie a la API JSON (?dias=N) y se redibuja sin recargar la página.
   Accesibilidad: cada canvas tiene aria-label y, debajo, un <details> con
   la misma información en tabla, que también se completa desde acá.
   Colores: siempre planos (sin degradados), tomados de la marca.
   ========================================================================= */
(function () {
  'use strict';

  var PALETA = [
    '#0E8A6D', '#F0A04B', '#1F4B99', '#8E5BD6', '#146C2E',
    '#C2761F', '#52606D', '#0B6B55', '#B42318', '#3E4C59',
  ];

  var graficos = {}; // id del canvas → instancia de Chart

  // $ 12.345,67 — mismo formato que el filtro "moneda" de Django.
  function moneda(n) {
    var partes = Number(n || 0).toFixed(2).split('.');
    partes[0] = partes[0].replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    return '$ ' + partes[0] + ',' + partes[1];
  }

  function colores(cantidad) {
    var lista = [];
    for (var i = 0; i < cantidad; i++) lista.push(PALETA[i % PALETA.length]);
    return lista;
  }

  // Muestra u oculta el aviso "sin datos" que está sobre el canvas.
  function marcarVacio(canvas, vacio) {
    var aviso = canvas.parentElement.querySelector('.panel-grafico__vacio');
    if (aviso) aviso.hidden = !vacio;
    canvas.style.visibility = vacio ? 'hidden' : 'visible';
  }

  // Crea el gráfico la primera vez; después solo actualiza labels/datos.
  function dibujar(id, config) {
    var canvas = document.getElementById(id);
    if (!canvas || typeof Chart === 'undefined') return;

    var total = config.data.datasets[0].data.reduce(function (a, b) { return a + b; }, 0);
    marcarVacio(canvas, total === 0);

    if (graficos[id]) {
      graficos[id].data = config.data;
      graficos[id].update();
      return;
    }
    graficos[id] = new Chart(canvas, config);
  }

  // Rellena la tabla accesible que acompaña a cada gráfico.
  function tabla(id, columnas, filas) {
    var cuerpo = document.querySelector('#' + id + ' tbody');
    if (!cuerpo) return;
    cuerpo.innerHTML = '';
    if (!filas.length) {
      var vacia = document.createElement('tr');
      var celda = document.createElement('td');
      celda.colSpan = columnas.length;
      celda.textContent = 'Sin ventas en el período.';
      vacia.appendChild(celda);
      cuerpo.appendChild(vacia);
      return;
    }
    filas.forEach(function (fila) {
      var tr = document.createElement('tr');
      fila.forEach(function (valor, i) {
        var td = document.createElement('td');
        if (columnas[i].num) td.className = 'num';
        td.textContent = valor;
        tr.appendChild(td);
      });
      cuerpo.appendChild(tr);
    });
  }

  var opcionesBase = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          label: function (ctx) {
            var v = ctx.parsed.y !== undefined && ctx.chart.config.options.indexAxis !== 'y'
              ? ctx.parsed.y
              : (ctx.parsed.x !== undefined && ctx.chart.config.options.indexAxis === 'y' ? ctx.parsed.x : ctx.parsed);
            return moneda(v);
          },
        },
      },
    },
    scales: {
      y: { beginAtZero: true, ticks: { callback: function (v) { return moneda(v); } }, grid: { color: '#E1E8E5' } },
      x: { grid: { display: false } },
    },
  };

  function render(datos) {
    // 1. Ventas por día (barras)
    var dias = datos.por_dia || [];
    dibujar('grafico-dias', {
      type: 'bar',
      data: {
        labels: dias.map(function (d) { return d.etiqueta; }),
        datasets: [{
          label: 'Ventas',
          data: dias.map(function (d) { return d.monto; }),
          backgroundColor: '#0E8A6D',
          borderRadius: 4,
          extra: dias.map(function (d) { return d.pedidos; }),
        }],
      },
      options: Object.assign({}, opcionesBase, {
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var pedidos = ctx.dataset.extra[ctx.dataIndex];
                return moneda(ctx.parsed.y) + ' · ' + pedidos + ' pedido' + (pedidos === 1 ? '' : 's');
              },
            },
          },
        },
      }),
    });
    tabla('tabla-dias',
      [{}, { num: true }, { num: true }],
      dias.filter(function (d) { return d.pedidos > 0; })
          .map(function (d) { return [d.etiqueta, d.pedidos, moneda(d.monto)]; }));

    // 2. Top productos (barras horizontales)
    var productos = (datos.por_producto || []).slice(0, 10);
    dibujar('grafico-productos', {
      type: 'bar',
      data: {
        labels: productos.map(function (p) { return p.nombre; }),
        datasets: [{
          label: 'Monto',
          data: productos.map(function (p) { return p.monto; }),
          backgroundColor: colores(productos.length),
          borderRadius: 4,
        }],
      },
      options: Object.assign({}, opcionesBase, {
        indexAxis: 'y',
        scales: {
          x: { beginAtZero: true, ticks: { callback: function (v) { return moneda(v); } }, grid: { color: '#E1E8E5' } },
          y: { grid: { display: false }, ticks: { autoSkip: false, font: { size: 12 } } },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var p = productos[ctx.dataIndex];
                return moneda(p.monto) + ' · ' + p.unidades + ' u. · ' + p.porcentaje + '%';
              },
            },
          },
        },
      }),
    });
    tabla('tabla-productos',
      [{}, {}, { num: true }, { num: true }, { num: true }],
      productos.map(function (p) { return [p.nombre, p.categoria, p.unidades, moneda(p.monto), p.porcentaje + '%']; }));

    // 3. Ventas por categoría (dona)
    var categorias = datos.por_categoria || [];
    dibujar('grafico-categorias', {
      type: 'doughnut',
      data: {
        labels: categorias.map(function (c) { return c.categoria; }),
        datasets: [{
          data: categorias.map(function (c) { return c.monto; }),
          backgroundColor: colores(categorias.length),
          borderColor: '#FFFFFF',
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '60%',
        plugins: {
          legend: { position: 'right', labels: { boxWidth: 14, font: { size: 12 } } },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var c = categorias[ctx.dataIndex];
                return ctx.label + ': ' + moneda(c.monto) + ' (' + c.porcentaje + '%)';
              },
            },
          },
        },
      },
    });
    tabla('tabla-categorias',
      [{}, { num: true }, { num: true }, { num: true }],
      categorias.map(function (c) { return [c.categoria, c.unidades, moneda(c.monto), c.porcentaje + '%']; }));

    // 4. Medios de pago (barras)
    var medios = datos.por_medio_pago || [];
    dibujar('grafico-medios', {
      type: 'bar',
      data: {
        labels: medios.map(function (m) { return m.etiqueta; }),
        datasets: [{
          label: 'Monto',
          data: medios.map(function (m) { return m.monto; }),
          backgroundColor: colores(medios.length),
          borderRadius: 4,
        }],
      },
      options: Object.assign({}, opcionesBase, {
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var m = medios[ctx.dataIndex];
                return moneda(m.monto) + ' · ' + m.pedidos + ' pedidos · ' + m.porcentaje + '%';
              },
            },
          },
        },
      }),
    });
    tabla('tabla-medios',
      [{}, { num: true }, { num: true }, { num: true }],
      medios.map(function (m) { return [m.etiqueta, m.pedidos, moneda(m.monto), m.porcentaje + '%']; }));

    // KPIs del bloque de gráficos (si el template los tiene).
    var k = datos.kpis || {};
    var setTexto = function (id, texto) {
      var el = document.getElementById(id);
      if (el) el.textContent = texto;
    };
    setTexto('kpi-rango-monto', moneda(k.monto));
    setTexto('kpi-rango-pedidos', (k.pedidos || 0) + ' pedidos · ' + (k.unidades || 0) + ' unidades');
    setTexto('kpi-rango-ticket', moneda(k.ticket_promedio));
  }

  // Pide la serie a la API y redibuja. Muestra un estado "cargando" accesible.
  function cargar(api, params, estado) {
    if (estado) { estado.textContent = 'Actualizando gráficos…'; }
    var url = api + (api.indexOf('?') === -1 ? '?' : '&') + params;
    return fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (datos) {
        render(datos);
        if (estado) {
          estado.textContent = 'Mostrando del ' + datos.rango.desde.split('-').reverse().join('/') +
            ' al ' + datos.rango.hasta.split('-').reverse().join('/') + '.';
        }
      })
      .catch(function () {
        if (estado) estado.textContent = 'No se pudieron actualizar los gráficos. Probá de nuevo.';
      });
  }

  function init(config) {
    var nodo = document.getElementById(config.datosId || 'datos-analitica');
    if (nodo) {
      try { render(JSON.parse(nodo.textContent)); } catch (e) { /* sin datos iniciales */ }
    }

    var selector = document.getElementById(config.selectorId || 'selector-rango');
    var estado = document.getElementById(config.estadoId || 'estado-graficos');
    if (selector && config.api) {
      selector.addEventListener('change', function () {
        cargar(config.api, 'dias=' + encodeURIComponent(selector.value), estado);
      });
    }
  }

  window.PanelGraficos = { init: init, render: render, moneda: moneda };
})();
