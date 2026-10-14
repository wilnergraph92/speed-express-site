/* ==========================================================================
   Speed Express Shipping — l'application de bureau « Speed Express Operations »
   (phase 10, ADR 0016)
   --------------------------------------------------------------------------
   L'application Windows et macOS est une enveloppe Tauri 2 autour de CES
   pages (bureau/) : mêmes écrans, mêmes appels à la base (SES_API, les
   mêmes lg_* que le site et les applications mobiles). Ce fichier est le seul
   pont entre les pages et l'enveloppe. Dans un navigateur, il ne fait rien :
   SES_BUREAU.actif est faux et la section « Application de bureau » ne
   s'affiche pas.

   Ce que l'enveloppe ajoute, et rien d'autre :
     · imprimer : la boîte d'impression du système (WKWebView, sur macOS,
       ignore window.print() sans elle) ;
     · l'étiquette 4 × 6 envoyée TELLE QUELLE (ZPL) à l'imprimante thermique
       choisie, sans boîte de dialogue ;
     · la liste des imprimantes du poste ;
     · les mises à jour signées, canal stable ou bêta ;
     · un lien externe s'ouvre dans le navigateur du système, jamais dans la
       fenêtre de l'application.
   Aucune clé ici, ni dans l'enveloppe : l'application ne connaît que la clé
   PUBLIQUE de Supabase (config.js), comme le site. Pas de clé de service, pas
   de secret de paiement, jamais.

   Les préférences (imprimante, mode d'étiquette, canal) sont des réglages
   d'AFFICHAGE de ce poste, gardés sur l'appareil, revalidés à chaque lecture.
   ========================================================================== */
(function () {
  'use strict';

  var T = window.__TAURI__;
  var invoke = T && T.core && typeof T.core.invoke === 'function' ? T.core.invoke : null;
  var actif = !!invoke;
  var CANAUX = ['stable', 'beta'], MODES = ['dialogue', 'zpl'];

  function lirePref(cle, permis, defaut) {
    try { var v = window.localStorage.getItem('ses-bureau-' + cle); return v !== null && (!permis || permis.indexOf(v) >= 0) ? v : defaut; } catch (x) { return defaut; }
  }
  function ecrirePref(cle, v) { try { window.localStorage.setItem('ses-bureau-' + cle, String(v)); } catch (x) { /* rien ne casse */ } }
  function appeler(commande, args) { return actif ? Promise.resolve(invoke(commande, args || {})) : Promise.reject(new Error('hors-bureau')); }

  /* Un nom d'imprimante revient de la liste du système ; on ne garde qu'un texte simple et court. */
  function nomImprimante(v) { var s = String(v || '').trim(); return s.length > 0 && s.length <= 200 && !/[\u0000-\u001f]/.test(s) ? s : ''; }

  var B = window.SES_BUREAU = {
    actif: actif,
    canal: function () { return lirePref('canal', CANAUX, 'stable'); },
    modeEtiquette: function () { return lirePref('etiquette-mode', MODES, 'dialogue'); },
    imprimante: function () { return nomImprimante(lirePref('etiquette-imprimante', null, '')); },
    etiquetteDirecte: function () { return actif && B.modeEtiquette() === 'zpl' && !!B.imprimante(); },
    infos: function () { return appeler('infos'); },
    imprimantes: function () { return appeler('imprimantes'); },
    imprimerPage: function () { return appeler('imprimer'); },
    imprimerBrut: function (donnees) {
      var nom = B.imprimante();
      if (!nom) return Promise.reject(new Error('imprimante-absente'));
      return appeler('imprimer_brut', { imprimante: nom, donnees: String(donnees || '') });
    },
    verifierMaj: function () { return appeler('verifier_mise_a_jour', { canal: B.canal() }); },
    installerMaj: function () { return appeler('installer_mise_a_jour', { canal: B.canal() }); },
    signaler: function (err) {
      var C = window.SES_CENTRE;
      if (C && C.annoncer) C.annoncer(C.t('c-bur-erreur-imprimante', { detail: String((err && (err.message || err)) || '') }), 'erreur');
    },
    // exposé pour outils/tests/bureau-contrat.cjs
    _prefs: { lire: lirePref, ecrire: ecrirePref, nomImprimante: nomImprimante }
  };
  if (!actif) return;

  document.documentElement.classList.add('ses-bureau');
  // La boîte d'impression du système : sur macOS par l'enveloppe (WKWebView n'en ouvre aucune d'elle-même) ; sous Windows, l'enveloppe
  // répond « navigateur » et WebView2 ouvre la sienne, par le window.print d'origine.
  var printNatif = typeof window.print === 'function' ? window.print.bind(window) : null;
  window.print = function () {
    B.imprimerPage().then(function (voie) { if (voie === 'navigateur' && printNatif) printNatif(); }, B.signaler);
  };
  // Un lien vers un autre site (WhatsApp, une carte, l'aide…) s'ouvre dans le navigateur du système ; l'enveloppe refuse de toute façon
  // de naviguer ailleurs que dans ses propres pages.
  document.addEventListener('click', function (ev) {
    var a = ev.target && ev.target.closest ? ev.target.closest('a[href]') : null;
    if (!a) return;
    var url;
    try { url = new URL(a.getAttribute('href'), location.href); } catch (x) { return; }
    if (url.origin === location.origin) return;
    if (['https:', 'http:', 'mailto:', 'tel:'].indexOf(url.protocol) < 0) return;
    ev.preventDefault();
    appeler('ouvrir_lien', { url: url.href }).catch(function () { /* rien : le lien n'est simplement pas ouvert */ });
  }, true);

  /* --- La section « Application de bureau » du centre de commande (module Scanner) --- */
  var C = window.SES_CENTRE;
  if (!C || !C.enregistrer) return;
  var t = function (k, v) { return C.t ? C.t(k, v) : k; };
  var e = function (x) { return C.e ? C.e(x) : String(x); };

  function option(valeur, libelle, courant) { return '<option value="' + e(valeur) + '"' + (valeur === courant ? ' selected' : '') + '>' + e(libelle) + '</option>'; }
  function dessiner(zone) {
    zone.innerHTML = '<p class="cc-intro">' + e(t('c-bur-intro')) + '</p>' +
      '<section class="cc-carte cc-site"><h3>' + e(t('c-bur-version')) + '</h3><p id="cc-bur-infos" class="cc-petit">' + e(t('c-chargement')) + '</p>' +
      '<div class="cc-form-grille"><label class="ses-champ"><span>' + e(t('c-bur-canal')) + '</span><select id="cc-bur-canal">' +
      option('stable', t('c-bur-canal-stable'), B.canal()) + option('beta', t('c-bur-canal-beta'), B.canal()) + '</select><small>' + e(t('c-bur-canal-aide')) + '</small></label></div>' +
      '<div class="cc-barre-actions"><button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" id="cc-bur-verifier">' + e(t('c-bur-verifier')) + '</button></div>' +
      '<div id="cc-bur-maj" aria-live="polite"></div></section>' +
      '<section class="cc-carte cc-site"><h3>' + e(t('c-bur-etiquettes')) + '</h3>' +
      '<div class="cc-form-grille"><label class="ses-champ"><span>' + e(t('c-bur-mode')) + '</span><select id="cc-bur-mode">' +
      option('dialogue', t('c-bur-mode-dialogue'), B.modeEtiquette()) + option('zpl', t('c-bur-mode-zpl'), B.modeEtiquette()) + '</select><small>' + e(t('c-bur-mode-aide')) + '</small></label>' +
      '<label class="ses-champ"><span>' + e(t('c-bur-imprimante')) + '</span><select id="cc-bur-imprimante"><option value="">' + e(t('c-chargement')) + '</option></select></label></div>' +
      '<div class="cc-barre-actions"><button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" id="cc-bur-essai">' + e(t('c-bur-essai')) + '</button></div>' +
      '<p id="cc-bur-msg" class="cc-petit" aria-live="polite"></p></section>';

    B.infos().then(function (i) {
      zone.querySelector('#cc-bur-infos').textContent = t('c-bur-infos', { version: i.version, systeme: i.systeme, architecture: i.architecture }) +
        (i.mises_a_jour ? '' : ' · ' + t('c-bur-maj-non-configurees'));
    }, function (err) { zone.querySelector('#cc-bur-infos').textContent = String(err); });

    var choix = zone.querySelector('#cc-bur-imprimante');
    B.imprimantes().then(function (l) {
      var courant = B.imprimante();
      choix.innerHTML = '<option value="">' + e(t(l.length ? 'c-bur-imprimante-choisir' : 'c-bur-aucune-imprimante')) + '</option>' +
        l.map(function (n) { return option(n, n, courant); }).join('');
    }, function (err) { choix.innerHTML = '<option value="">' + e(String(err)) + '</option>'; });

    zone.querySelector('#cc-bur-canal').addEventListener('change', function (ev) { ecrirePref('canal', CANAUX.indexOf(ev.target.value) >= 0 ? ev.target.value : 'stable'); });
    zone.querySelector('#cc-bur-mode').addEventListener('change', function (ev) { ecrirePref('etiquette-mode', MODES.indexOf(ev.target.value) >= 0 ? ev.target.value : 'dialogue'); });
    choix.addEventListener('change', function (ev) { ecrirePref('etiquette-imprimante', nomImprimante(ev.target.value)); });

    var msg = zone.querySelector('#cc-bur-msg');
    zone.querySelector('#cc-bur-essai').addEventListener('click', function () {
      var essai = { numero: 'SES-0000000000', service: 'aerien', destinataire: t('c-bur-essai-nom'), ville_destination: 'Port-au-Prince', pays_destination: 'HT',
                    code_client: 'SES-00000', poids_lb: 1, description: t('c-bur-essai-contenu'), cree_le: new Date().toISOString() };
      msg.textContent = t('c-chargement');
      window.SES_UI.imprimerEtiquette(essai).then(function () { msg.textContent = t('c-bur-essai-envoye'); });
    });

    var zoneMaj = zone.querySelector('#cc-bur-maj');
    zone.querySelector('#cc-bur-verifier').addEventListener('click', function () {
      zoneMaj.innerHTML = '<p class="cc-petit">' + e(t('c-chargement')) + '</p>';
      B.verifierMaj().then(function (m) {
        if (!m) { zoneMaj.innerHTML = '<p class="cc-petit">' + e(t('c-bur-a-jour')) + '</p>'; return; }
        zoneMaj.innerHTML = '<p>' + e(t('c-bur-maj-dispo', { version: m.version })) + '</p>' + (m.notes ? '<p class="cc-petit">' + e(m.notes) + '</p>' : '') +
          '<button type="button" class="ses-bouton ses-bouton-principal ses-bouton-mini" id="cc-bur-installer">' + e(t('c-bur-installer')) + '</button>';
        zoneMaj.querySelector('#cc-bur-installer').addEventListener('click', function (ev) {
          ev.target.disabled = true;
          zoneMaj.insertAdjacentHTML('beforeend', '<p class="cc-petit">' + e(t('c-bur-installation')) + '</p>');
          B.installerMaj().catch(function (err) { ev.target.disabled = false; zoneMaj.insertAdjacentHTML('beforeend', '<p class="cc-form-msg">' + e(String(err)) + '</p>'); });
        });
      }, function (err) { zoneMaj.innerHTML = '<p class="cc-form-msg">' + e(String(err)) + '</p>'; });
    });
  }

  C.enregistrer({ id: 'bureau', ordre: 31, filtres: [], ouvrir: function () { return actif; },
                  rendre: function (zone) { dessiner(zone); }, actualiser: function () { return Promise.resolve(); } });
})();
