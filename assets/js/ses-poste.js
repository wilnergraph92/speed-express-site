/* ==========================================================================
   Speed Express Shipping — le poste de scan du bureau (phase 15, ADR 0013)
   --------------------------------------------------------------------------
   Une section du centre de commande, pensée pour un ordinateur d'entrepôt
   (Windows ou Mac) : un scanner USB branché lit ICI sans aucun clic (il se
   comporte comme un clavier très rapide : voir ses-scanner.js), la saisie à
   la main reste possible, l'imprimante du système sort l'étiquette d'un
   colis et le bordereau de la session, un fichier exporte ou importe une
   liste de numéros, et une notification du système prévient quand l'onglet
   est caché.

   Aucune règle métier ici. Le profil (ai-je l'entrepôt ? lesquels ?) vient de
   lg_my_staff_profile, le verdict de chaque lecture de lg_scan_parcel. Chaque
   lecture porte une clé d'idempotence : « Réessayer » après une coupure
   renvoie la même clé, et la base ne compte jamais deux fois le même scan.

   Les fonctions sans écran (CSV, lecture d'une liste, clés) sont exposées
   sous SES_CENTRE.poste pour outils/tests/poste-contrat.cjs.
   ========================================================================== */
(function () {
  'use strict';

  var C = window.SES_CENTRE = window.SES_CENTRE || {};
  var API = window.SES_API, UI = window.SES_UI, S = window.SES_SCANNER;
  var MAX_LECTURES = 200, MAX_IMPORT = 500, NOTIF_INTERVALLE_MS = 60000;
  var t = function (k, v) { return C.t ? C.t(k, v) : k; };
  var e = function (x) { return C.e ? C.e(x) : String(x); };

  /* --- Ce que la session du poste retient (survit au changement de langue et de section) --- */
  var etat = { profil: null, entrepot: null, intention: 'receive', lectures: [], seq: 0 };
  var service = null, zoneCourante = null, desabonnerNotif = null, derniereNotif = 0, installation = null;

  /* Petites préférences de CE poste (pas des données) : le navigateur peut les refuser, rien ne casse. */
  function lirePref(cle, defaut) { try { var v = window.localStorage.getItem('ses-poste-' + cle); return v === null ? defaut : v; } catch (x) { return defaut; } }
  function ecrirePref(cle, v) { try { window.localStorage.setItem('ses-poste-' + cle, String(v)); } catch (x) { /* mode privé : tant pis */ } }

  /* L'identifiant de CE poste, dans les clés d'idempotence : deux postes qui lisent le même colis à la même milliseconde ne se confondent pas. */
  function identifiantPoste() {
    var id = lirePref('id', '');
    if (!/^[a-z0-9]{8,16}$/.test(id)) { id = Math.random().toString(36).slice(2, 12); ecrirePref('id', id); }
    return id;
  }
  /* L'heure et la date dans la langue de la PAGE (pas celle du navigateur) : un écran en créole n'affiche pas « AM ». */
  function locale() { return ({ fr: 'fr-FR', en: 'en-US', es: 'es-ES', ht: 'fr-HT' })[(document.documentElement.lang || 'fr').slice(0, 2)] || 'fr-FR'; }
  function heure(iso) { return new Date(iso).toLocaleTimeString(locale()); }
  function cleLecture(poste, horodatage, seq) { return 'poste-' + poste + '-' + Number(horodatage).toString(36) + '-' + seq; }

  /* --- Fichiers -------------------------------------------------------------------------------------------- */
  /* Une cellule de CSV : guillemets doublés, et jamais une formule (un numéro qui commencerait par « = » s'exécuterait dans un tableur). */
  function celluleCsv(v) {
    var s = v === null || v === undefined ? '' : String(v);
    if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
    return '"' + s.replace(/"/g, '""') + '"';
  }
  function csv(lectures, libelles) {
    var l = libelles || {};
    var lignes = [[l.heure || 'heure', l.numero || 'numero', l.intention || 'intention', l.entrepot || 'entrepot', l.verdict || 'verdict', l.code || 'code', l.lecteur || 'lecteur'].map(celluleCsv).join(',')];
    lectures.forEach(function (x) {
      lignes.push([x.horodatage, x.code, x.intention, x.entrepotCode, x.verdictTexte || '', x.verdict || x.etat, x.genre].map(celluleCsv).join(','));
    });
    return '﻿' + lignes.join('\r\n') + '\r\n';    // l'en-tête UTF-8 : Excel affiche les accents
  }
  /* Une liste de numéros lue dans un fichier (.txt ou .csv) : sur chaque ligne, la première cellule qui a l'allure d'un numéro de colis (lettres,
     chiffres, tirets, AU MOINS un chiffre), sans doublon. Un en-tête (« numero », « Heure ») n'en a pas : il ne part jamais, car un code
     inconnu scanné ouvre un incident dans la base. Un export de ce poste se réimporte tel quel (l'heure n'a pas l'allure d'un numéro). */
  function numeroDeLigne(ligne) {
    var cellules = ligne.split(/[,;\t]/);
    for (var i = 0; i < cellules.length; i++) {
      var c = cellules[i].replace(/^\s+|\s+$/g, '').replace(/^"|"$/g, '');
      if (/^[A-Za-z0-9][A-Za-z0-9-]{2,63}$/.test(c) && /\d/.test(c)) return c;
    }
    return null;
  }
  function lireListe(texte) {
    var vus = {}, sortie = [];
    String(texte || '').replace(/^﻿/, '').split(/\r\n|\r|\n/).forEach(function (ligne) {
      var c = numeroDeLigne(ligne);
      if (!c) return;
      var k = c.toUpperCase();
      if (vus[k] || sortie.length >= MAX_IMPORT) return;
      vus[k] = true; sortie.push(c);
    });
    return sortie;
  }
  function telecharger(nom, contenu, type) {
    var url = URL.createObjectURL(new Blob([contenu], { type: type }));
    var a = document.createElement('a');
    a.href = url; a.download = nom; document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 1000);
  }

  /* --- Le profil : la base dit si ce compte a l'entrepôt, et lesquels --- */
  function aEntrepot(p) { return !!(p && p.staff && (p.profiles || []).indexOf('WAREHOUSE_AGENT') >= 0 && (p.warehouses || []).length); }
  function entrepotChoisi() {
    var ws = (etat.profil && etat.profil.warehouses) || [];
    return ws.filter(function (w) { return w.warehouse_id === etat.entrepot; })[0] || ws[0] || null;
  }

  /* --- Une lecture : envoyée, puis son verdict --- */
  function nouvelleLecture(code, genre) {
    var w = entrepotChoisi(), h = Date.now();
    etat.seq += 1;
    var l = { cle: cleLecture(identifiantPoste(), h, etat.seq), code: code, genre: genre, horodatage: new Date(h).toISOString(), intention: etat.intention,
              entrepot: w && w.warehouse_id, entrepotCode: w ? w.code : '', etat: 'envoi', verdict: null, verdictTexte: '', numero: null, erreur: null };
    etat.lectures.unshift(l);
    if (etat.lectures.length > MAX_LECTURES) etat.lectures.length = MAX_LECTURES;
    return l;
  }
  function envoyer(l) {
    l.etat = 'envoi'; l.erreur = null;
    dessinerLectures();
    return API.poste.scanner({ code: l.code, intention: l.intention, entrepot: l.entrepot, genre: l.genre, cle: l.cle, horodatage: l.horodatage }).then(function (r) {
      l.etat = 'fait';
      l.verdict = r && r.result ? r.result : 'ACCEPTED';
      l.verdictTexte = t('c-scan-' + l.verdict) || l.verdict;
      l.numero = r && r.tracking_number ? r.tracking_number : null;
      if (l.verdict !== 'ACCEPTED') bip();
      annoncer(l);
    }, function (err) {
      l.etat = 'erreur';
      l.erreur = C.message ? C.message(err) : String(err && err.message);
      bip();
      annoncer(l);
    }).then(dessinerLectures);
  }
  function lire(code, genre) {
    if (!aEntrepot(etat.profil) || !entrepotChoisi()) return;
    return envoyer(nouvelleLecture(code, genre));
  }

  /* Un refus s'entend : un agent qui scanne en rafale ne regarde pas l'écran à chaque colis. Réglable, et rien si le navigateur refuse le son. */
  function bip() {
    if (lirePref('son', '1') !== '1') return;
    try {
      var Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      var a = bip.ctx || (bip.ctx = new Ctx()), o = a.createOscillator(), g = a.createGain();
      o.frequency.value = 330; g.gain.value = 0.08;
      o.connect(g); g.connect(a.destination); o.start(); o.stop(a.currentTime + 0.25);
    } catch (x) { /* pas de son : l'écran suffit */ }
  }
  function annoncer(l) {
    var r = zoneCourante && zoneCourante.querySelector('#cc-poste-dernier');
    if (!r) return;
    r.className = 'cc-poste-dernier ' + (l.etat === 'erreur' ? 'cc-poste-ko' : (l.verdict === 'ACCEPTED' ? 'cc-poste-ok' : 'cc-poste-ko'));
    r.textContent = l.code + ' — ' + (l.etat === 'erreur' ? l.erreur : l.verdictTexte);
  }

  /* --- L'écran --- */
  function visible() { return !!(zoneCourante && zoneCourante.isConnected && zoneCourante.querySelector('#cc-poste') && zoneCourante.offsetParent !== null); }

  function demarrerLecteur() {
    if (service || !S) return;
    service = S.creerService({ debounceMs: 1500, longueurMin: 3 });
    // Le scanner USB tape n'importe où dans la page : il lit tant que le poste est à l'écran, même si le curseur est dans le champ de saisie.
    service.ajouterAdaptateur(S.adaptateurClavier(document, { delaiMaxMs: 50, longueurMin: 3 }));
    service.surLecture(function (x) {
      if (!visible()) return;
      var champ = zoneCourante.querySelector('#cc-poste-code');
      if (champ && x.genre !== 'manual') champ.value = '';      // ce que le scanner a tapé dans le champ n'est pas à renvoyer à la main
      lire(x.code, x.genre === 'manual' ? 'manual' : x.genre);
    });
    service.demarrer();
  }
  function arreterLecteur() { if (service) { service.arreter(); service = null; } }

  function ligneLecture(l) {
    var verdict = l.etat === 'envoi' ? '<span class="ses-pastille ses-pastille-info">' + e(t('c-poste-envoi')) + '</span>'
      : l.etat === 'erreur' ? '<span class="ses-pastille ses-pastille-bad">' + e(t('c-poste-pas-parti')) + '</span> <button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-poste-reessayer="' + e(l.cle) + '">' + e(t('c-reessayer')) + '</button>'
      : C.pastille('c-scan-' + l.verdict, l.verdict === 'ACCEPTED' ? 'SENT' : 'FAILED');
    return '<tr><td data-label="' + e(t('c-poste-col-heure')) + '">' + e(heure(l.horodatage)) + '</td>' +
      '<td data-label="' + e(t('c-col-numero')) + '"><span class="ses-mono">' + e(l.code) + '</span></td>' +
      '<td data-label="' + e(t('c-col-but')) + '">' + e(t('c-but-' + l.intention)) + ' · ' + e(l.entrepotCode) + '</td>' +
      '<td data-label="' + e(t('c-col-resultat')) + '">' + verdict + '</td>' +
      '<td data-label="' + e(t('c-poste-col-lecteur')) + '">' + e(t('c-poste-genre-' + l.genre)) + '</td>' +
      '<td>' + (l.etat === 'fait' && l.numero ? '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-poste-etiquette="' + e(l.numero) + '">' + e(t('c-poste-etiquette')) + '</button>' : '') + '</td></tr>';
  }
  function dessinerLectures() {
    var z = zoneCourante && zoneCourante.querySelector('#cc-poste-lectures');
    if (!z) return;
    if (!etat.lectures.length) { z.innerHTML = '<p class="cc-rien">' + e(t('c-poste-aucune')) + '</p>'; return; }
    var acceptees = etat.lectures.filter(function (l) { return l.verdict === 'ACCEPTED'; }).length;
    z.innerHTML = '<p class="cc-petit">' + e(t('c-poste-compte', { nombre: etat.lectures.length, acceptees: acceptees })) + '</p>' +
      '<div class="cc-table-zone"><table class="ses-tableau cc-table"><caption class="sr-only">' + e(t('c-poste-session')) + '</caption><thead><tr>' +
      '<th scope="col">' + e(t('c-poste-col-heure')) + '</th><th scope="col">' + e(t('c-col-numero')) + '</th><th scope="col">' + e(t('c-col-but')) + '</th>' +
      '<th scope="col">' + e(t('c-col-resultat')) + '</th><th scope="col">' + e(t('c-poste-col-lecteur')) + '</th><th scope="col"><span class="sr-only">' + e(t('c-poste-etiquette')) + '</span></th></tr></thead><tbody>' +
      etat.lectures.map(ligneLecture).join('') + '</tbody></table></div>';
  }

  function options(valeurs, courant, libelle) {
    return valeurs.map(function (v) { return '<option value="' + e(v) + '"' + (v === courant ? ' selected' : '') + '>' + e(libelle(v)) + '</option>'; }).join('');
  }

  function dessiner(zone) {
    zoneCourante = zone;
    var p = etat.profil;
    if (!aEntrepot(p)) { arreterLecteur(); zone.innerHTML = '<p class="cc-intro">' + e(t('c-poste-sans-profil')) + '</p>'; return; }
    var w = entrepotChoisi();
    etat.entrepot = w.warehouse_id;
    var notifPossible = 'Notification' in window;
    var notifActive = notifPossible && Notification.permission === 'granted' && lirePref('notif', '0') === '1';
    zone.innerHTML = '<div id="cc-poste">' +
      '<p class="cc-intro">' + e(t('c-poste-intro')) + '</p>' +
      '<form class="cc-poste-reglages cc-form-grille" novalidate>' +
        '<label class="ses-champ" for="cc-poste-entrepot"><span>' + e(t('c-poste-entrepot')) + '</span><select id="cc-poste-entrepot">' +
          options(p.warehouses.map(function (x) { return x.warehouse_id; }), etat.entrepot, function (id) { var x = p.warehouses.filter(function (y) { return y.warehouse_id === id; })[0]; return x.code + ' — ' + x.name; }) + '</select></label>' +
        '<label class="ses-champ" for="cc-poste-intention"><span>' + e(t('c-poste-intention')) + '</span><select id="cc-poste-intention">' +
          options(API.INTENTIONS_POSTE, etat.intention, function (v) { return t('c-but-' + v); }) + '</select></label>' +
      '</form>' +
      '<form id="cc-poste-saisie" class="cc-poste-saisie" novalidate>' +
        '<label class="ses-champ" for="cc-poste-code"><span>' + e(t('c-poste-code')) + '</span><input id="cc-poste-code" type="text" inputmode="text" autocomplete="off" autocapitalize="characters" spellcheck="false" maxlength="500"></label>' +
        '<button type="submit" class="ses-bouton ses-bouton-principal">' + e(t('c-poste-lire')) + '</button>' +
      '</form>' +
      '<p id="cc-poste-dernier" class="cc-poste-dernier" role="status" aria-live="polite">' + e(t('c-poste-pret')) + '</p>' +
      '<div class="cc-poste-outils">' +
        '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-poste-exporter>' + e(t('c-poste-exporter')) + '</button>' +
        '<label class="ses-bouton ses-bouton-second ses-bouton-mini cc-poste-fichier">' + e(t('c-poste-importer')) + '<input type="file" accept=".txt,.csv,text/plain,text/csv" data-poste-importer class="sr-only"></label>' +
        '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-poste-bordereau>' + e(t('c-poste-imprimer')) + '</button>' +
        '<label class="cc-poste-case"><input type="checkbox" data-poste-son' + (lirePref('son', '1') === '1' ? ' checked' : '') + '> ' + e(t('c-poste-son')) + '</label>' +
        (notifPossible ? '<label class="cc-poste-case"><input type="checkbox" data-poste-notif' + (notifActive ? ' checked' : '') + '> ' + e(t('c-poste-notif')) + '</label>' : '') +
        (installation ? '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-poste-installer>' + e(t('c-poste-installer')) + '</button>' : '') +
      '</div>' +
      '<p class="cc-petit">' + e(t('c-poste-installer-aide')) + '</p>' +
      '<h3 class="cc-sous-titre">' + e(t('c-poste-session')) + '</h3><div id="cc-poste-lectures"></div>' +
    '</div>';
    dessinerLectures();
    brancher(zone);
    demarrerLecteur();
    var champ = zone.querySelector('#cc-poste-code');
    if (champ) champ.focus();
  }

  function brancher(zone) {
    zone.querySelector('#cc-poste-entrepot').addEventListener('change', function (ev) { etat.entrepot = ev.target.value; ecrirePref('entrepot', etat.entrepot); });
    zone.querySelector('#cc-poste-intention').addEventListener('change', function (ev) { etat.intention = ev.target.value; });
    zone.querySelector('#cc-poste-saisie').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var champ = zone.querySelector('#cc-poste-code'), v = champ.value;
      champ.value = '';
      if (service) service.soumettre(v); else lire(v, 'manual');
      champ.focus();
    });
    zone.querySelector('#cc-poste').addEventListener('click', function (ev) {
      var b;
      if ((b = ev.target.closest('[data-poste-reessayer]'))) {
        var l = etat.lectures.filter(function (x) { return x.cle === b.getAttribute('data-poste-reessayer'); })[0];
        if (l) envoyer(l);                                   // la MÊME clé : la base ne comptera pas deux scans
        return;
      }
      if ((b = ev.target.closest('[data-poste-etiquette]'))) return imprimerEtiquette(b.getAttribute('data-poste-etiquette'));
      if (ev.target.closest('[data-poste-exporter]')) return exporter();
      if (ev.target.closest('[data-poste-bordereau]')) return imprimerBordereau();
      if (ev.target.closest('[data-poste-installer]') && installation) {
        installation.prompt();
        installation = null;
      }
    });
    zone.querySelector('[data-poste-importer]').addEventListener('change', function (ev) { importer(ev.target); });
    zone.querySelector('[data-poste-son]').addEventListener('change', function (ev) { ecrirePref('son', ev.target.checked ? '1' : '0'); });
    var n = zone.querySelector('[data-poste-notif]');
    if (n) n.addEventListener('change', function (ev) { reglerNotifications(ev.target); });
  }

  /* L'étiquette d'un colis : celle que le tableau de bord imprime déjà (même gabarit, même code QR), retrouvée par son numéro exact. */
  function imprimerEtiquette(numero) {
    API.admin.colis({ recherche: numero, parPage: 10 }).then(function (r) {
      var c = (r && r.lignes || []).filter(function (x) { return String(x.numero || '').toUpperCase() === String(numero).toUpperCase(); })[0];
      if (!c) return C.annoncer(t('c-poste-etiquette-absente'), 'erreur');
      UI.imprimer(UI.etiquette(c), 'etiquette');
    }).catch(function (err) { C.annoncer(C.message(err), 'erreur'); });
  }

  function libellesCsv() {
    return { heure: t('c-poste-col-heure'), numero: t('c-col-numero'), intention: t('c-col-but'), entrepot: t('c-poste-entrepot'), verdict: t('c-col-resultat'), code: t('c-poste-col-code'), lecteur: t('c-poste-col-lecteur') };
  }
  function exporter() {
    if (!etat.lectures.length) return C.annoncer(t('c-poste-aucune'), 'erreur');
    var w = entrepotChoisi();
    telecharger('scans-' + (w ? w.code : 'poste') + '-' + new Date().toISOString().slice(0, 10) + '.csv', csv(etat.lectures.slice().reverse(), libellesCsv()), 'text/csv;charset=utf-8');
  }

  function importer(entree) {
    var f = entree.files && entree.files[0];
    entree.value = '';
    if (!f) return;
    if (f.size > 1024 * 1024) return C.annoncer(t('c-poste-import-trop'), 'erreur');
    var lecteur = new FileReader();
    lecteur.onload = function () {
      var numeros = lireListe(lecteur.result);
      if (!numeros.length) return C.annoncer(t('c-poste-import-vide'), 'erreur');
      if (!window.confirm(t('c-poste-import-confirmer', { nombre: numeros.length, intention: t('c-but-' + etat.intention) }))) return;
      // Un par un : la base répond à chaque colis avant le suivant, et la file de l'écran reste dans l'ordre du fichier.
      numeros.reduce(function (p, numero) { return p.then(function () { return lire(numero, 'manual'); }); }, Promise.resolve());
    };
    lecteur.readAsText(f);
  }

  function imprimerBordereau() {
    if (!etat.lectures.length) return C.annoncer(t('c-poste-aucune'), 'erreur');
    var w = entrepotChoisi();
    var html = '<div style="font-family:Manrope,system-ui,sans-serif;color:#0b0c0e;padding:12mm">' +
      '<h1 style="font-size:18px;margin:0 0 4px">' + e(t('c-poste-bordereau')) + '</h1>' +
      '<p style="margin:0 0 12px;font-size:12px">' + e((w ? w.code + ' — ' + w.name : '') + ' · ' + new Date().toLocaleString(locale())) + '</p>' +
      '<table style="width:100%;border-collapse:collapse;font-size:11px"><thead><tr>' +
      ['c-poste-col-heure', 'c-col-numero', 'c-col-but', 'c-col-resultat'].map(function (k) { return '<th style="text-align:left;border-bottom:1px solid #0b0c0e;padding:4px">' + e(t(k)) + '</th>'; }).join('') +
      '</tr></thead><tbody>' + etat.lectures.slice().reverse().map(function (l) {
        return '<tr><td style="padding:3px 4px;border-bottom:1px solid #ccc">' + e(heure(l.horodatage)) + '</td><td style="padding:3px 4px;border-bottom:1px solid #ccc;font-family:monospace">' + e(l.code) +
          '</td><td style="padding:3px 4px;border-bottom:1px solid #ccc">' + e(t('c-but-' + l.intention)) + '</td><td style="padding:3px 4px;border-bottom:1px solid #ccc">' + e(l.etat === 'fait' ? l.verdictTexte : t('c-poste-pas-parti')) + '</td></tr>';
      }).join('') + '</tbody></table></div>';
    UI.imprimer(html);
  }

  /* --- Notifications du système : une phrase sans donnée, quand l'onglet est caché, au plus une par minute --- */
  function notifier() {
    if (!document.hidden || Date.now() - derniereNotif < NOTIF_INTERVALLE_MS) return;
    derniereNotif = Date.now();
    try { new Notification(t('c-poste-notif-titre'), { body: t('c-poste-notif-corps'), tag: 'ses-centre' }); } catch (x) { /* refusée en cours de route */ }
  }
  function brancherNotifications() {
    if (desabonnerNotif || !('Notification' in window) || Notification.permission !== 'granted' || lirePref('notif', '0') !== '1') return;
    desabonnerNotif = API.notifications.surveiller('staff', notifier);
  }
  function reglerNotifications(caseACocher) {
    if (!caseACocher.checked) {
      ecrirePref('notif', '0');
      if (desabonnerNotif) { desabonnerNotif(); desabonnerNotif = null; }
      return;
    }
    // La permission ne se demande qu'ici, après un clic : jamais à l'ouverture de la page.
    Promise.resolve(Notification.requestPermission()).then(function (p) {
      if (p !== 'granted') { caseACocher.checked = false; return C.annoncer(t('c-poste-notif-refusees'), 'erreur'); }
      ecrirePref('notif', '1');
      brancherNotifications();
    });
  }

  /* L'installation comme application de bureau (Chrome, Edge) : le navigateur la propose, on garde sa proposition pour un bouton. */
  window.addEventListener('beforeinstallprompt', function (ev) { ev.preventDefault(); installation = ev; });

  /* --- La section --- */
  function charger(zone) {
    zoneCourante = zone;
    if (etat.profil) return dessiner(zone);
    C.etat(zone, 'chargement');
    API.poste.profil().then(function (p) {
      etat.profil = p;
      var pref = lirePref('entrepot', '');
      if (p && (p.warehouses || []).some(function (w) { return w.warehouse_id === pref; })) etat.entrepot = pref;
      if (zoneCourante === zone) dessiner(zone);
    }, function (err) { C.erreur(zone, err, function () { charger(zone); }); });
  }

  if (C.enregistrer) {
    C.enregistrer({
      id: 'poste', ordre: 45, filtres: [],
      // Ouvert à qui voit les opérations ; c'est ensuite la base (profil, puis chaque scan) qui accepte ou refuse.
      ouvrir: function (acces) { return !!(acces && acces.ops); },
      rendre: function (zone) { charger(zone); },
      actualiser: function () { /* jamais de relecture automatique : elle effacerait ce que l'agent est en train de scanner */ },
      quitter: function () { arreterLecteur(); zoneCourante = null; }
    });
  }
  brancherNotifications();

  C.poste = { csv: csv, lireListe: lireListe, celluleCsv: celluleCsv, cleLecture: cleLecture, aEntrepot: aEntrepot, etat: etat, lire: lire, MAX_IMPORT: MAX_IMPORT };
})();
