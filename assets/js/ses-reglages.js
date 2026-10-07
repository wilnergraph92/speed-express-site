/* ==========================================================================
   Speed Express Shipping — les réglages du tableau de bord
   --------------------------------------------------------------------------
   Le menu ⚙ (apparence claire, sombre ou système ; personnaliser ; rétablir ;
   tous les réglages ; déconnexion), le menu du compte (e-mail, rôle,
   identifiant d'équipe, réglages, voir le site, déconnexion) et la fenêtre
   « Réglages » (Affichage, Mon compte, Système).

   Ces réglages sont des préférences d'AFFICHAGE, gardées sur cet appareil
   seulement (localStorage) : chaque membre de l'équipe règle le sien, et
   aucun ne touche aux données ni aux droits. Un stockage interdit ou
   illisible (navigation privée) donne simplement les valeurs par défaut.
   ========================================================================== */
(function () {
  'use strict';

  var CLE = 'ses-tdb-reglages';
  var DEFAUTS = { theme: 'clair', animations: true, periode: '30j', lignes: 20, reduit: false };
  var THEMES = ['clair', 'sombre', 'systeme'];
  var PERIODES = ['aujourdhui', '7j', '30j', '90j', 'semaine', 'mois', 'annee'];
  var LIGNES = [10, 20, 25, 50];
  var ecouteurs = [];

  function lire() {
    var r = {};
    try { r = JSON.parse(localStorage.getItem(CLE) || '{}') || {}; } catch (x) { r = {}; }
    // Chaque valeur relue est vérifiée : une valeur inconnue (ancien réglage, main malheureuse) redevient celle par défaut.
    return {
      theme: THEMES.indexOf(r.theme) >= 0 ? r.theme : DEFAUTS.theme,
      animations: r.animations !== false,
      periode: PERIODES.indexOf(r.periode) >= 0 ? r.periode : DEFAUTS.periode,
      lignes: LIGNES.indexOf(Number(r.lignes)) >= 0 ? Number(r.lignes) : DEFAUTS.lignes,
      reduit: r.reduit === true
    };
  }
  function ecrire(cle, valeur) {
    var r = lire();
    r[cle] = valeur;
    try { localStorage.setItem(CLE, JSON.stringify(r)); } catch (x) { /* sans mémoire : l'effet vaut pour cette page */ }
    appliquer(r);
    ecouteurs.forEach(function (f) { try { f(cle, r); } catch (x) { /* un écouteur en panne n'empêche pas les autres */ } });
  }
  function surChange(f) { ecouteurs.push(f); }

  /* ---------- Appliquer : thème, animations, menu réduit ---------- */
  var systemeSombre = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  function themeEffectif(r) {
    if (r.theme === 'systeme') return systemeSombre && systemeSombre.matches ? 'sombre' : 'clair';
    return r.theme;
  }
  function appliquer(r) {
    r = r || lire();
    var html = document.documentElement;
    html.setAttribute('data-theme', themeEffectif(r));
    html.classList.toggle('rg-sans-animations', !r.animations);
    var bureau = window.matchMedia && window.matchMedia('(min-width:1024px)').matches;
    var principal = document.querySelector('.ses-dashboard');
    if (principal && bureau) {
      principal.classList.toggle('is-reduit', r.reduit);
      var menu = document.getElementById('dash-menu');
      if (menu) menu.setAttribute('aria-expanded', String(!r.reduit));
    }
    Array.prototype.forEach.call(document.querySelectorAll('[data-theme-choix]'), function (b) {
      b.setAttribute('aria-pressed', String(b.getAttribute('data-theme-choix') === r.theme));
    });
  }
  if (systemeSombre && systemeSombre.addEventListener) systemeSombre.addEventListener('change', function () { appliquer(); });
  // Le plus tôt possible : la page ne clignote pas en clair avant de passer en sombre.
  appliquer();

  window.SES_REGLAGES = { lire: lire, ecrire: ecrire, surChange: surChange, appliquer: appliquer, DEFAUTS: DEFAUTS };

  /* ---------- Les menus déroulants (⚙ et compte) ---------- */
  function $(id) { return document.getElementById(id); }
  function t(k, v) { return window.SES_UI ? window.SES_UI.t(k, v) : ''; }

  function fermerMenus(sauf) {
    Array.prototype.forEach.call(document.querySelectorAll('.rg-menu'), function (m) {
      if (m === sauf || m.hidden) return;
      m.hidden = true;
      var b = document.querySelector('[aria-controls="' + m.id + '"]');
      if (b) b.setAttribute('aria-expanded', 'false');
    });
  }
  function elements(menu) {
    return Array.prototype.filter.call(menu.querySelectorAll('button,a[href]'), function (el) { return !el.hidden && el.getClientRects().length; });
  }
  function brancherMenu(bouton, menu) {
    bouton.addEventListener('click', function (ev) {
      ev.stopPropagation();
      var ouvrir = menu.hidden;
      fermerMenus(menu);
      menu.hidden = !ouvrir;
      bouton.setAttribute('aria-expanded', String(ouvrir));
      if (ouvrir) { var premier = elements(menu)[0]; if (premier) premier.focus(); }
    });
    menu.addEventListener('keydown', function (ev) {
      var liste = elements(menu), i = liste.indexOf(document.activeElement);
      if (ev.key === 'ArrowDown') { ev.preventDefault(); liste[(i + 1) % liste.length].focus(); }
      else if (ev.key === 'ArrowUp') { ev.preventDefault(); liste[(i - 1 + liste.length) % liste.length].focus(); }
      else if (ev.key === 'Escape') { ev.preventDefault(); fermerMenus(); bouton.focus(); }
      else if (ev.key === 'Tab') { fermerMenus(); }
    });
  }

  /* ---------- La fenêtre « Réglages » ---------- */
  function choisirSection(nom) {
    ['affichage', 'compte', 'systeme'].forEach(function (s) {
      var o = $('rg-o-' + s), p = $('rg-p-' + s), actif = s === nom;
      o.setAttribute('aria-selected', String(actif));
      o.tabIndex = actif ? 0 : -1;
      p.hidden = !actif;
    });
  }
  function remplirAffichage() {
    var r = lire();
    $('rg-theme').value = r.theme;
    $('rg-animations').checked = r.animations;
    $('rg-periode').value = r.periode;
    $('rg-lignes').value = String(r.lignes);
    $('rg-reduit').checked = r.reduit;
  }
  function remplirCompte() {
    var API = window.SES_API;
    if (!API) return;
    API.profil().then(function (p) {
      if (!p) return;
      $('rg-c-nom').textContent = p.nom_complet || '—';
      $('rg-c-email').textContent = p.email || '—';
      $('rg-c-role').textContent = t('role-' + p.role) || p.role || '—';
      $('rg-c-matricule').textContent = p.matricule || t('rg-aucun-matricule');
      $('rg-c-matricule').classList.toggle('ses-mono', !!p.matricule);
    }).catch(function () { /* hors connexion : la fiche garde ses tirets */ });
  }
  function remplirSysteme() {
    var API = window.SES_API;
    var mode = API ? API.mode : 'off';
    $('rg-s-mode').textContent = t('rg-mode-' + mode) || mode;
    var script = document.querySelector('script[src*="ses-reglages.js?v="]');
    $('rg-s-version').textContent = script ? 'v' + script.getAttribute('src').split('?v=')[1] : '—';
    $('rg-s-reseau').textContent = t(navigator.onLine ? 'rg-reseau-ok' : 'rg-reseau-ko');
    if (mode !== 'supabase' || !API.admin || !API.admin.baseAJour) { $('rg-s-base').textContent = t('rg-base-demo'); return; }
    $('rg-s-base').textContent = '…';
    API.admin.baseAJour().then(function (ok) { $('rg-s-base').textContent = t(ok ? 'rg-base-ok' : 'rg-base-a-mettre'); });
  }
  function ouvrir(section) {
    fermerMenus();
    Array.prototype.forEach.call(document.querySelectorAll('dialog.ses-dialogue[open]'), function (d) { d.close(); });
    remplirAffichage(); remplirCompte(); remplirSysteme();
    choisirSection(section || 'affichage');
    $('rg-reglages').showModal();
    $('rg-o-' + (section || 'affichage')).focus();
  }

  function demarrer() {
    if (!$('rg-reglages')) return;
    brancherMenu($('dash-vers-reglages'), $('rg-menu'));
    brancherMenu($('rg-compte'), $('rg-menu-compte'));
    document.addEventListener('click', function (ev) { if (!ev.target.closest('.rg-ancre')) fermerMenus(); });

    Array.prototype.forEach.call(document.querySelectorAll('[data-theme-choix]'), function (b) {
      b.addEventListener('click', function () { ecrire('theme', b.getAttribute('data-theme-choix')); });
    });
    $('rg-personnaliser').addEventListener('click', function () {
      fermerMenus();
      var o = $('ses-o-dashboard'); if (o && o.getAttribute('aria-selected') !== 'true') o.click();
      if (window.SES_DASHBOARD && window.SES_DASHBOARD.personnaliser) window.SES_DASHBOARD.personnaliser();
    });
    $('rg-retablir').addEventListener('click', function () {
      fermerMenus();
      if (window.SES_DASHBOARD && window.SES_DASHBOARD.retablir) window.SES_DASHBOARD.retablir();
      var zone = $('ses-message'); if (zone && window.SES_UI) window.SES_UI.annonce(zone, t('rg-retabli'), 'succes');
    });
    $('rg-tous').addEventListener('click', function () { ouvrir('affichage'); });
    $('rg-compte-reglages').addEventListener('click', function () { ouvrir('compte'); });
    // La déconnexion passe par le bouton d'origine du menu latéral : un seul chemin, celui qui retire aussi la session.
    Array.prototype.forEach.call(document.querySelectorAll('[data-rg-sortir]'), function (b) {
      b.addEventListener('click', function () { fermerMenus(); var s = $('ses-deconnexion'); if (s) s.click(); });
    });

    // La fenêtre : onglets à la souris et aux flèches
    var nav = document.querySelector('.rg-nav');
    nav.addEventListener('click', function (ev) {
      var b = ev.target.closest('[role=tab]'); if (b) choisirSection(b.id.replace('rg-o-', ''));
    });
    nav.addEventListener('keydown', function (ev) {
      if (['ArrowDown', 'ArrowUp'].indexOf(ev.key) < 0) return;
      ev.preventDefault();
      var onglets = Array.prototype.slice.call(nav.querySelectorAll('[role=tab]'));
      var i = onglets.indexOf(document.activeElement), j = (i + (ev.key === 'ArrowDown' ? 1 : -1) + onglets.length) % onglets.length;
      onglets[j].focus(); choisirSection(onglets[j].id.replace('rg-o-', ''));
    });
    // Chaque réglage s'applique tout de suite
    $('rg-theme').addEventListener('change', function () { ecrire('theme', this.value); });
    $('rg-animations').addEventListener('change', function () { ecrire('animations', this.checked); });
    $('rg-periode').addEventListener('change', function () { ecrire('periode', this.value); });
    $('rg-lignes').addEventListener('change', function () { ecrire('lignes', Number(this.value)); });
    $('rg-reduit').addEventListener('change', function () { ecrire('reduit', this.checked); });
    $('rg-defaut').addEventListener('click', function () {
      try { localStorage.removeItem(CLE); } catch (x) { /* rien à effacer */ }
      var r = lire();
      appliquer(r);
      ecouteurs.forEach(function (f) { try { f('*', r); } catch (x) { /* idem */ } });
      remplirAffichage();
      var zone = $('ses-message'); if (zone && window.SES_UI) window.SES_UI.annonce(zone, t('rg-defauts'), 'succes');
    });
    $('rg-termine').addEventListener('click', function () { $('rg-reglages').close(); });

    // « Mon compte » accueille le changement de mot de passe (déplacé depuis l'onglet Réglages, avec ses écouteurs).
    var mdp = $('ses-mdp');
    if (mdp) {
      var carte = mdp.closest('.ses-carte');
      var place = $('rg-mdp-place');
      if (carte && place) {
        Array.prototype.slice.call(carte.children).forEach(function (enfant) { place.appendChild(enfant); });
        carte.hidden = true;
      }
    }
    window.addEventListener('online', remplirSysteme);
    window.addEventListener('offline', remplirSysteme);
    appliquer();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', demarrer);
  else demarrer();
})();
