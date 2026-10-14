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
  /* --- La file hors ligne (phase 10) -----------------------------------------------------------------------
     Quand le réseau manque, une lecture qui peut attendre (réception, contrôle, consolidation, chargement, départ,
     inventaire — pas « consulter », dont on veut la réponse tout de suite) est gardée sur CE poste, avec SA clé
     d'idempotence et l'heure de la lecture, puis renvoyée seule dès que le réseau revient. La base ne la compte
     jamais deux fois (même clé) et garde l'heure du poste (recorded_at). La file appartient au compte connecté :
     un autre compte ouvert sur le même poste ne l'envoie pas en son nom. Rien d'autre n'y est gardé qu'un
     numéro lu, l'entrepôt et l'intention : pas de jeton, pas de donnée de client. */
  var FILE_MAX = 500, FILE_INTERVALLE_MS = 30000;
  var INTENTIONS_EN_FILE = ['receive', 'verify', 'consolidate', 'load', 'dispatch', 'inventory'];
  var proprietaire = null, fileEnCours = false;
  function enLigne() { return !(typeof navigator !== 'undefined' && navigator.onLine === false); }
  function erreurReseau(err) {
    if (!enLigne()) return true;
    var m = String((err && (err.message || err.code)) || err || '');
    return /failed to fetch|networkerror|load failed|network request failed|fetch failed|internet|hors-ligne|timed? ?out/i.test(m);
  }
  function peutAttendre(l) { return !!proprietaire && INTENTIONS_EN_FILE.indexOf(l.intention) >= 0; }
  function valideEnFile(x) {
    return !!x && typeof x.cle === 'string' && /^poste-[a-z0-9]+-[a-z0-9]+-\d+$/.test(x.cle) && typeof x.code === 'string' && x.code.length > 0 && x.code.length <= 500 &&
      INTENTIONS_EN_FILE.indexOf(x.intention) >= 0 && typeof x.entrepot === 'string' && typeof x.compte === 'string' && x.compte.length > 0 && !isNaN(Date.parse(x.horodatage));
  }
  function lireFile() {
    try { var v = JSON.parse(window.localStorage.getItem('ses-poste-file') || '[]'); return Array.isArray(v) ? v.filter(valideEnFile).slice(0, FILE_MAX) : []; } catch (x) { return []; }
  }
  function ecrireFile(f) { try { window.localStorage.setItem('ses-poste-file', JSON.stringify(f.slice(0, FILE_MAX))); } catch (x) { /* stockage refusé : la lecture reste « pas partie », à renvoyer à la main */ } }
  function retirerDeFile(cle) { var f = lireFile(); if (f.some(function (x) { return x.cle === cle; })) ecrireFile(f.filter(function (x) { return x.cle !== cle; })); }
  function mettreEnFile(l) {
    var f = lireFile().filter(function (x) { return x.cle !== l.cle; });
    if (f.length >= FILE_MAX) { l.etat = 'erreur'; l.erreur = t('c-poste-file-pleine'); return false; }
    f.push({ cle: l.cle, code: l.code, genre: l.genre, intention: l.intention, entrepot: l.entrepot, entrepotCode: l.entrepotCode, horodatage: l.horodatage, compte: proprietaire });
    ecrireFile(f);
    l.etat = 'attente'; l.erreur = null; l.enFile = true;
    return true;
  }
  /* Les lectures gardées par une session précédente (fenêtre fermée, poste redémarré) reviennent dans la liste de l'écran. */
  function reprendreFile() {
    lireFile().forEach(function (x) {
      if (x.compte !== proprietaire || etat.lectures.some(function (l) { return l.cle === x.cle; })) return;
      etat.lectures.push({ cle: x.cle, code: x.code, genre: x.genre, horodatage: x.horodatage, intention: x.intention, entrepot: x.entrepot, entrepotCode: x.entrepotCode || '',
                           etat: 'attente', enFile: true, verdict: null, verdictTexte: '', numero: null, erreur: null });
    });
    etat.lectures.sort(function (a, b) { return a.horodatage < b.horodatage ? 1 : -1; });
  }
  /* Une à une, dans l'ordre des lectures : la base répond à chacune avant la suivante. */
  function viderFile() {
    if (fileEnCours || !proprietaire || !enLigne()) return Promise.resolve();
    var a = lireFile().filter(function (x) { return x.compte === proprietaire; }).sort(function (x, y) { return x.horodatage < y.horodatage ? -1 : 1; });
    if (!a.length) return Promise.resolve();
    fileEnCours = true;
    reprendreFile();
    var suite = a.reduce(function (p, x) {
      return p.then(function () {
        var l = etat.lectures.filter(function (y) { return y.cle === x.cle; })[0];
        return l && enLigne() ? envoyer(l) : null;
      });
    }, Promise.resolve());
    return suite.then(function () { fileEnCours = false; dessinerLectures(); }, function () { fileEnCours = false; });
  }
  function compteFile() {
    var f = lireFile();
    return { miens: f.filter(function (x) { return x.compte === proprietaire; }).length, autres: f.filter(function (x) { return x.compte !== proprietaire; }).length };
  }

  function envoyer(l) {
    if (!enLigne() && peutAttendre(l)) {
      if (mettreEnFile(l)) annoncer(l);
      dessinerLectures();
      return Promise.resolve();
    }
    l.etat = 'envoi'; l.erreur = null;
    dessinerLectures();
    return API.poste.scanner({ code: l.code, intention: l.intention, entrepot: l.entrepot, genre: l.genre, cle: l.cle, horodatage: l.horodatage, enFile: !!l.enFile }).then(function (r) {
      l.etat = 'fait';
      l.verdict = r && r.result ? r.result : 'ACCEPTED';
      l.verdictTexte = t('c-scan-' + l.verdict) || l.verdict;
      l.numero = r && r.tracking_number ? r.tracking_number : null;
      retirerDeFile(l.cle);
      if (l.verdict !== 'ACCEPTED') bip();
      annoncer(l);
    }, function (err) {
      if (erreurReseau(err) && peutAttendre(l) && mettreEnFile(l)) { annoncer(l); return; }
      // La base a répondu (un refus, pas une coupure) : la lecture sort de la file, son erreur reste à l'écran.
      retirerDeFile(l.cle);
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
    if (l.etat === 'attente') { r.className = 'cc-poste-dernier cc-poste-attente'; r.textContent = l.code + ' — ' + t('c-poste-en-file'); return; }
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
  function arreterLecteur() { arreterCamera(); if (service) { service.arreter(); service = null; } }

  /* --- La caméra : Code 128 (étiquette) et QR, par le détecteur du navigateur (BarcodeDetector) ---
     Aucune bibliothèque de plus (rien ne se charge d'ailleurs que du site) : là où le navigateur n'a pas de détecteur (Safari, Firefox),
     le bouton le dit et le scanner USB ou la saisie restent là. La lecture passe par le MÊME service que le scanner USB (anti-rebond,
     clé d'idempotence) ; seule la source change. La caméra s'éteint dès qu'on quitte le poste. */
  var camera = null;
  function cameraPossible() {
    return !!(window.BarcodeDetector && navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  }
  function arreterCamera() {
    if (!camera) return;
    clearInterval(camera.minuteur);
    camera.flux.getTracks().forEach(function (piste) { piste.stop(); });
    camera.adaptateur.arreter();
    if (camera.video) { camera.video.srcObject = null; camera.video.hidden = true; }
    var b = zoneCourante && zoneCourante.querySelector('[data-poste-camera]');
    if (b) { b.textContent = t('c-poste-camera'); b.setAttribute('aria-pressed', 'false'); }
    camera = null;
  }
  function demarrerCamera() {
    var dernier = zoneCourante && zoneCourante.querySelector('#cc-poste-dernier');
    if (!cameraPossible() || !service) { if (dernier) dernier.textContent = t('c-poste-camera-indisponible'); return; }
    var video = zoneCourante.querySelector('#cc-poste-video');
    Promise.resolve(window.BarcodeDetector.getSupportedFormats ? window.BarcodeDetector.getSupportedFormats() : ['code_128', 'qr_code'])
      .then(function (formats) {
        var voulus = ['code_128', 'qr_code'].filter(function (x) { return formats.indexOf(x) >= 0; });
        if (!voulus.length) throw { code: 'formats' };
        return navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false }).then(function (flux) {
          var adaptateur = S.adaptateurCamera(new window.BarcodeDetector({ formats: voulus }));
          service.ajouterAdaptateur(adaptateur);
          video.srcObject = flux;
          video.hidden = false;
          return Promise.resolve(video.play()).then(function () {
            camera = { flux: flux, video: video, adaptateur: adaptateur, minuteur: setInterval(function () {
              if (camera && video.readyState >= 2 && visible()) adaptateur.image(video).catch(function () {});
            }, 300) };
            var b = zoneCourante.querySelector('[data-poste-camera]');
            if (b) { b.textContent = t('c-poste-camera-arreter'); b.setAttribute('aria-pressed', 'true'); }
          });
        });
      })
      .catch(function (err) {
        if (dernier) dernier.textContent = t(err && err.name === 'NotAllowedError' ? 'c-poste-camera-refusee' : 'c-poste-camera-indisponible');
      });
  }

  function ligneLecture(l) {
    var verdict = l.etat === 'envoi' ? '<span class="ses-pastille ses-pastille-info">' + e(t('c-poste-envoi')) + '</span>'
      : l.etat === 'attente' ? '<span class="ses-pastille ses-pastille-warn">' + e(t('c-poste-en-file')) + '</span>'
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
    dessinerFile();
    if (!z) return;
    if (!etat.lectures.length) { z.innerHTML = '<p class="cc-rien">' + e(t('c-poste-aucune')) + '</p>'; return; }
    var acceptees = etat.lectures.filter(function (l) { return l.verdict === 'ACCEPTED'; }).length;
    z.innerHTML = '<p class="cc-petit">' + e(t('c-poste-compte', { nombre: etat.lectures.length, acceptees: acceptees })) + '</p>' +
      '<div class="cc-table-zone"><table class="ses-tableau cc-table"><caption class="sr-only">' + e(t('c-poste-session')) + '</caption><thead><tr>' +
      '<th scope="col">' + e(t('c-poste-col-heure')) + '</th><th scope="col">' + e(t('c-col-numero')) + '</th><th scope="col">' + e(t('c-col-but')) + '</th>' +
      '<th scope="col">' + e(t('c-col-resultat')) + '</th><th scope="col">' + e(t('c-poste-col-lecteur')) + '</th><th scope="col"><span class="sr-only">' + e(t('c-poste-etiquette')) + '</span></th></tr></thead><tbody>' +
      etat.lectures.map(ligneLecture).join('') + '</tbody></table></div>';
  }

  /* Le bandeau de la file : combien attendent le réseau, et de quoi les envoyer tout de suite. */
  function dessinerFile() {
    var z = zoneCourante && zoneCourante.querySelector('#cc-poste-file');
    if (!z) return;
    var n = compteFile();
    if (!n.miens && !n.autres) { z.hidden = true; z.innerHTML = ''; return; }
    z.hidden = false;
    z.innerHTML = (n.miens ? '<p><strong>' + e(t('c-poste-file', { nombre: n.miens })) + '</strong> ' + e(t(enLigne() ? 'c-poste-file-envoi' : 'c-poste-file-hors-ligne')) +
      ' <button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-poste-file>' + e(t('c-poste-file-envoyer')) + '</button></p>' : '') +
      (n.autres ? '<p class="cc-petit">' + e(t('c-poste-file-autres', { nombre: n.autres })) + '</p>' : '');
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
      '<div id="cc-poste-file" class="cc-poste-file" role="status" aria-live="polite" hidden></div>' +
      '<video id="cc-poste-video" class="cc-poste-video" hidden playsinline muted aria-label="' + e(t('c-poste-camera')) + '"></video>' +
      '<div class="cc-poste-outils">' +
        '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-poste-camera aria-pressed="false">' + e(t('c-poste-camera')) + '</button>' +
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
      if (ev.target.closest('[data-poste-file]')) return viderFile();
      if (ev.target.closest('[data-poste-camera]')) return camera ? arreterCamera() : demarrerCamera();
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
      UI.imprimerEtiquette(c);
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
    // Le compte connecté (lu sur le poste, sans réseau) : le propriétaire de la file.
    Promise.resolve(API.session ? API.session() : null).then(function (s) {
      proprietaire = s && s.user && s.user.id ? String(s.user.id) : null;
      reprendreFile();
      if (zoneCourante === zone && etat.profil) dessinerLectures();
      viderFile();
    });
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
  // Le réseau revient : la file part seule ; et toutes les 30 s, au cas où l'événement ne viendrait pas.
  window.addEventListener('online', function () { viderFile(); dessinerFile(); });
  window.addEventListener('offline', dessinerFile);
  if (typeof window.setInterval === 'function') window.setInterval(function () { if (compteFile().miens) viderFile(); }, FILE_INTERVALLE_MS);

  C.poste = { csv: csv, lireListe: lireListe, celluleCsv: celluleCsv, cleLecture: cleLecture, aEntrepot: aEntrepot, etat: etat, lire: lire, MAX_IMPORT: MAX_IMPORT,
              file: { lire: lireFile, vider: viderFile, erreurReseau: erreurReseau, valide: valideEnFile, compter: compteFile, INTENTIONS: INTENTIONS_EN_FILE, MAX: FILE_MAX,
                      proprietaire: function (v) { if (arguments.length) proprietaire = v; return proprietaire; } } };
})();
