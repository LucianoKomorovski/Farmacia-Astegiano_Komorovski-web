/* =========================================================================
   JS del sitio. Se carga después de Bootstrap (usa window.bootstrap).
   Función anónima que se ejecuta sola (IIFE) para no ensuciar el ámbito global.
   ========================================================================= */
(function () {
  'use strict';

  var header = document.querySelector('.header-sticky'); // bloque fijo arriba (header + nav)
  var offcanvasEl = document.getElementById('menuMobile'); // panel lateral del menú mobile

  // Devuelve cuántos píxeles ocupa el header fijo + un poco de aire.
  // Se usa para que el título de la sección no quede tapado al scrollear a un ancla.
  function alturaHeader() {
    return (header ? header.offsetHeight : 110) + 16;
  }

  // Baja la página hasta el elemento indicado por el hash (#turnos, #sucursales...).
  function scrollAHash(hash) {
    var target = document.querySelector(hash);
    if (!target) return;
    var top =
      target.getBoundingClientRect().top + window.scrollY - alturaHeader();
    window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
  }

  // Dice si el link apunta a la misma página en la que ya estamos.
  // Ejemplo: estamos en "/" y el link es "/#turnos" → true (solo hay que scrollear).
  function mismaPagina(pathDelLink) {
    if (!pathDelLink || pathDelLink === '/') {
      return (
        window.location.pathname === '/' || window.location.pathname === ''
      );
    }
    return pathDelLink === window.location.pathname;
  }

  // Si el menú mobile está abierto lo cierra y, cuando terminó de cerrarse,
  // ejecuta "callback". Si está cerrado, ejecuta el callback de inmediato.
  function cerrarMenuLuego(callback) {
    var abierto = offcanvasEl && offcanvasEl.classList.contains('show');
    if (!abierto) {
      callback();
      return;
    }
    offcanvasEl.addEventListener('hidden.bs.offcanvas', function alCerrar() {
      offcanvasEl.removeEventListener('hidden.bs.offcanvas', alCerrar);
      callback();
    });
    bootstrap.Offcanvas.getOrCreateInstance(offcanvasEl).hide();
  }

  // Todos los links con ancla (href que contiene "#") del header y del menú mobile.
  document
    .querySelectorAll('.header-sticky a[href*="#"], #menuMobile a[href*="#"]')
    .forEach(function (link) {
      link.addEventListener('click', function (e) {
        var href = link.getAttribute('href') || '';
        var i = href.indexOf('#');
        var path = href.slice(0, i); // parte antes del #: "/"
        var hash = href.slice(i); // parte del #: "#turnos"

        // Ancla de OTRA página o la sección no existe → dejamos navegar normal.
        if (
          hash.length < 2 ||
          !mismaPagina(path) ||
          !document.querySelector(hash)
        ) {
          cerrarMenuLuego(function () {});
          return;
        }

        // Misma página + ancla → manejamos nosotros el scroll con el offset del header.
        e.preventDefault();
        cerrarMenuLuego(function () {
          history.replaceState(null, '', hash);
          scrollAHash(hash);
        });
      });
    });

  // Si la página se abrió directamente con un hash (ej. /#sucursales desde otra página),
  // corregimos la posición para que el header no tape el título.
  if (window.location.hash && document.querySelector(window.location.hash)) {
    window.setTimeout(function () {
      scrollAHash(window.location.hash);
    }, 200);
  }
})();
