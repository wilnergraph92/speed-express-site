/* ==========================================================================
   Speed Express Shipping — carrousel du hero (page d'accueil)
   -------------------------------------------------------------------------
   Trois diapositives plein cadre : image de fond + texte, fondus enchaînés,
   pastilles 01 · 02 · 03. Défilement automatique toutes les 6,5 secondes,
   en pause au survol, au focus, au balayage tactile et quand l'onglet est
   masqué ; désactivé complètement si le système demande moins de mouvement.
   JavaScript ES5 en IIFE, comme le reste du projet.
   ========================================================================== */
(function () {
  'use strict';

  function demarrer() {
    var racine = document.querySelector('[data-ses-hero]');
    if (!racine) return;

    var pistes = racine.querySelectorAll('.hero__piste');
    var fonds = racine.querySelectorAll('.hero__fond');
    var pastilles = racine.querySelectorAll('[data-aller]');
    var total = pistes.length;
    if (total < 2 || !pastilles.length) return;

    var courant = 0;
    var minuteur = null;
    var reduit = window.matchMedia &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function basculer(el, actif, classe) {
      if (!el) return;
      if (actif) el.classList.add(classe);
      else el.classList.remove(classe);
    }

    function afficher(indice) {
      courant = (indice % total + total) % total;
      for (var i = 0; i < total; i++) {
        var actif = i === courant;
        basculer(pistes[i], actif, 'est-active');
        basculer(fonds[i], actif, 'est-active');
        if (pastilles[i]) {
          basculer(pastilles[i], actif, 'est-active');
          pastilles[i].setAttribute('aria-pressed', actif ? 'true' : 'false');
        }
      }
    }

    function arreter() {
      if (minuteur) { window.clearInterval(minuteur); minuteur = null; }
    }

    function lancer() {
      arreter();
      if (reduit || document.hidden) return;
      minuteur = window.setInterval(function () { afficher(courant + 1); }, 6500);
    }

    /* Pastilles 01 · 02 · 03 --------------------------------------------- */
    Array.prototype.forEach.call(pastilles, function (bouton) {
      bouton.addEventListener('click', function () {
        afficher(parseInt(bouton.getAttribute('data-aller'), 10) || 0);
        lancer();
      });
    });

    /* Flèches gauche / droite quand le carrousel a le focus --------------- */
    racine.addEventListener('keydown', function (e) {
      var touche = e.key || e.keyCode;
      if (touche === 'ArrowRight' || touche === 39) {
        afficher(courant + 1); lancer();
        if (e.preventDefault) e.preventDefault();
      } else if (touche === 'ArrowLeft' || touche === 37) {
        afficher(courant - 1); lancer();
        if (e.preventDefault) e.preventDefault();
      }
    });

    /* Pause au survol et au focus, reprise ensuite ------------------------ */
    racine.addEventListener('mouseenter', arreter);
    racine.addEventListener('mouseleave', lancer);
    racine.addEventListener('focusin', arreter);
    racine.addEventListener('focusout', function (e) {
      var vers = e.relatedTarget;
      if (!vers || !racine.contains(vers)) lancer();
    });

    /* Balayage tactile (téléphone) --------------------------------------- */
    var xDepart = null;
    racine.addEventListener('touchstart', function (e) {
      xDepart = e.touches && e.touches.length ? e.touches[0].clientX : null;
      arreter();
    }, { passive: true });
    racine.addEventListener('touchend', function (e) {
      if (xDepart === null) return;
      var xFin = e.changedTouches && e.changedTouches.length
        ? e.changedTouches[0].clientX : xDepart;
      var ecart = xFin - xDepart;
      xDepart = null;
      if (Math.abs(ecart) > 44) afficher(courant + (ecart < 0 ? 1 : -1));
      lancer();
    }, { passive: true });

    /* Onglet masqué : on ne défile pas pour rien -------------------------- */
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) arreter(); else lancer();
    });

    afficher(0);
    lancer();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', demarrer);
  } else {
    demarrer();
  }
})();
