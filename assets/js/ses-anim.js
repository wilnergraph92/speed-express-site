/* ==========================================================================
   Speed Express Shipping — animations
   --------------------------------------------------------------------------
   Quatre effets, pas un de plus, et chacun a une raison d'être :

   1. Apparition au défilement  guide la lecture et signale qu'il y a une
                                suite plus bas. Une seule fois par bloc : en
                                remontant, rien ne rebouge. Ce qui est déjà à
                                l'écran au chargement n'est jamais masqué —
                                pas de clignotement sur la première page.
   2. Parallaxe du camion       donne de la profondeur à la seule image
                                décorative du site. 14 pixels au maximum.
   3. Survol                    montre ce qui est cliquable (cartes, lignes
                                de tableau, boutons).
   4. Lueur sous le curseur     sur les cartes de chiffres des tableaux de
                                bord : celle que l'on vise se détache.

   Rien n'est masqué par une feuille de style seule : c'est toujours ce
   fichier qui pose le masque, juste avant de le lever. Si le script ne se
   charge pas, ou si le système demande moins de mouvement, la page reste
   entière et lisible.
   ========================================================================== */
(function () {
  'use strict';

  var sobre = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var pointeur = window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches;

  var CSS = [
    /* 1. Apparition — la classe n'est posée que par le JavaScript */
    '.ses-cache{opacity:0;transform:translateY(16px);' +
      'transition:opacity .55s cubic-bezier(.22,.61,.36,1),transform .55s cubic-bezier(.22,.61,.36,1)}',
    '.ses-cache.ses-vu{opacity:1;transform:none}',

    /* 3. Survol : la même réponse partout */
    '.ses-carte{transition:transform .22s cubic-bezier(.22,.61,.36,1),box-shadow .22s ease,border-color .22s ease}',
    '@media (hover:hover){.ses-carte:hover{transform:translateY(-2px);' +
      'box-shadow:0 18px 34px -24px rgba(11,12,14,.5);border-color:#d3d8e0}}',
    '.ses-bouton{transition:background .18s ease,color .18s ease,transform .12s ease,box-shadow .18s ease}',
    '.ses-bouton:active{transform:translateY(1px)}',
    '.ses-ligne{transition:background .16s ease}',
    '@media (hover:hover){.ses-ligne:hover{background:#fafbfc}}',

    /* 4. Lueur sous le curseur */
    '.ses-lueur{position:relative;overflow:hidden}',
    '.ses-lueur::after{content:"";position:absolute;inset:0;pointer-events:none;opacity:0;' +
      'transition:opacity .25s ease;background:radial-gradient(180px circle at var(--x,50%) var(--y,50%),' +
      'rgba(232,18,27,.09),transparent 65%)}',
    '@media (hover:hover){.ses-lueur:hover::after{opacity:1}}',

    /* Le mouvement s'arrête si le système le demande ; le survol reste. */
    '@media (prefers-reduced-motion: reduce){.ses-cache,.ses-cache.ses-vu{opacity:1;transform:none;transition:none}}'
  ].join('\n');

  function poserStyle() {
    if (document.getElementById('ses-anim-css')) return;
    var s = document.createElement('style');
    s.id = 'ses-anim-css';
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  /* --- 1. Apparition au défilement ---------------------------------------
     Un simple balayage à chaque défilement, plutôt qu'un IntersectionObserver :
     celui-ci ne se réveille que lorsqu'un bloc traverse l'écran. Un visiteur
     qui saute d'un coup en bas de page (touche Fin, lien d'ancre, molette
     rapide) laissait derrière lui des sections jamais traversées, donc
     jamais révélées — c'est-à-dire invisibles. Ici, tout ce qui se retrouve
     au-dessus du bas de l'écran est révélé, quel que soit le chemin pris. */
  var enAttente = [];
  var branche = false;
  var prevu = false;

  function balayer() {
    prevu = false;
    var hauteur = window.innerHeight || 800;
    var reste = [];
    enAttente.forEach(function (el, i) {
      if (!el.isConnected) return;
      if (el.getBoundingClientRect().top < hauteur * 0.92) {
        el.style.transitionDelay = (Math.min(i, 6) * 60) + 'ms';
        el.classList.add('ses-vu');
      } else {
        reste.push(el);
      }
    });
    enAttente = reste;
    if (!enAttente.length && branche) {
      window.removeEventListener('scroll', auDefilement);
      window.removeEventListener('resize', auDefilement);
      branche = false;
    }
  }

  function auDefilement() {
    if (prevu) return;
    prevu = true;
    requestAnimationFrame(balayer);
  }

  /* Prend en charge les blocs marqués qui ne le sont pas encore. Ceux déjà
     visibles à l'écran sont laissés tels quels : les masquer pour les
     remontrer aussitôt ne ferait que clignoter. */
  function preparer(racine) {
    var blocs = (racine || document).querySelectorAll('[data-ses-reveal]:not(.ses-vu):not(.ses-cache)');
    if (!blocs.length) return;
    var hauteur = window.innerHeight || 800;

    Array.prototype.forEach.call(blocs, function (el) {
      var r = el.getBoundingClientRect();
      if (r.top < hauteur * 0.92) {
        el.classList.add('ses-vu');         // déjà à l'écran : rien à animer
        return;
      }
      el.classList.add('ses-cache');
      enAttente.push(el);
    });

    if (enAttente.length && !branche) {
      branche = true;
      window.addEventListener('scroll', auDefilement, { passive: true });
      window.addEventListener('resize', auDefilement, { passive: true });
    }
  }

  /* Blocs ajoutés après coup (listes des tableaux de bord) : ils arrivent
     après une action du visiteur, donc ils s'animent même déjà à l'écran. */
  function revelerMaintenant(racine) {
    var blocs = (racine || document).querySelectorAll('[data-ses-reveal]:not(.ses-vu)');
    if (!blocs.length) return;
    Array.prototype.forEach.call(blocs, function (el, i) {
      if (sobre) { el.classList.add('ses-vu'); return; }
      el.classList.add('ses-cache');
      el.style.transitionDelay = (Math.min(i, 8) * 45) + 'ms';
      requestAnimationFrame(function () {
        requestAnimationFrame(function () { el.classList.add('ses-vu'); });
      });
    });
  }

  /* --- 2. Parallaxe du camion du hero ------------------------------------ */
  function parallaxe() {
    var image = document.querySelector('.ses-hero-camion img');
    if (!image || window.innerWidth < 900) return;
    var enCours = false;
    function placer() {
      enCours = false;
      var y = window.scrollY || 0;
      if (y > 900) return;                  // au-delà du hero, plus rien à animer
      image.style.transform = 'translate3d(0,' + (y * 0.06).toFixed(2) + 'px,0)';
    }
    window.addEventListener('scroll', function () {
      if (enCours) return;
      enCours = true;
      requestAnimationFrame(placer);
    }, { passive: true });
    placer();
  }

  /* --- 4. Lueur sous le curseur ------------------------------------------ */
  function lueur() {
    if (!pointeur) return;
    document.addEventListener('pointermove', function (e) {
      var carte = e.target.closest && e.target.closest('.ses-lueur');
      if (!carte) return;
      var r = carte.getBoundingClientRect();
      carte.style.setProperty('--x', (e.clientX - r.left) + 'px');
      carte.style.setProperty('--y', (e.clientY - r.top) + 'px');
    }, { passive: true });
  }

  function demarrer() {
    poserStyle();
    lueur();
    if (sobre) {
      // Mouvement réduit : tout s'affiche d'emblée, le survol reste.
      Array.prototype.forEach.call(document.querySelectorAll('[data-ses-reveal]'), function (el) {
        el.classList.add('ses-vu');
      });
      return;
    }
    preparer();
    parallaxe();
  }

  window.SES_ANIM = { reveler: revelerMaintenant, preparer: preparer, sobre: sobre };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', demarrer);
  else demarrer();
})();
