/* ==========================================================================
   Speed Express Shipping — les modules du tableau de bord qui manquaient (phase 7)
   --------------------------------------------------------------------------
   Des sections du centre de commande, chacune ouverte par son entrée de la
   barre latérale :
     · « temps-reel » : le CENTRE DE COMMANDE en cartes (colis à traiter, scans
       récents, arrivages, départs, douane, livraisons du jour, retards,
       incidents, paiements en attente, tâches, alertes) ; chaque carte ouvre
       son module ;
     · « vehicules », « tournees », « depenses » ;
     · « pointage » : le POINTAGE EXPRESS, des colis (contre une liste
       attendue, au scanner ou au clavier) et du personnel (arrivée, pause,
       reprise, départ ; relevé de la direction) ;
     · « mes-missions » : les missions d'un chauffeur.

   Tout vient de SES_API.tableau (019-tableau-de-bord.sql) : la base décide qui
   voit quoi, compte et juge. L'écran ne calcule aucun indicateur ; il met en
   forme (une date, une durée en heures et minutes). Il se relit à chaque
   signal temps réel, comme tout le centre.
   ========================================================================== */
(function () {
  'use strict';

  var C = window.SES_CENTRE = window.SES_CENTRE || {};
  var API = window.SES_API;
  var UI = window.SES_UI;
  var t = function (k, v) { return C.t ? C.t(k, v) : k; };
  var e = function (x) { return C.e ? C.e(x) : String(x); };
  var nombre = function (v) { return v === null || v === undefined ? '—' : (C.nombre ? C.nombre(v) : String(v)); };
  var date = function (v) { return C.date ? C.date(v) : (v || '—'); };
  var jour = function (v) { return C.jour ? C.jour(v) : (v || '—'); };
  var pastille = function (cle, code) { return C.pastille ? C.pastille(cle, code) : e(code); };
  var GENRE = { ok: 'ACTIVE', info: 'REQUESTED', warn: 'PENDING', bad: 'OVERDUE' };

  function accesTableau() { return C.accesTableau ? C.accesTableau() : null; }
  function module(m) { var x = C.modules ? C.modules() : null; return x ? x.indexOf(m) >= 0 : null; }
  /* L'adresse d'un module (pour qu'une carte l'ouvre) : sa première section du centre, ou son onglet de l'ancien schéma. */
  function lienModule(m) {
    var b = document.querySelector('.ses-onglets [data-module="' + m + '"]');
    if (!b || b.hidden) return '';
    if (!b.hasAttribute('data-sections')) return '#' + b.id.replace('ses-o-', '');
    var s = b.getAttribute('data-sections').split(' ').filter(function (x) { return !C.peutOuvrir || C.peutOuvrir(x); })[0];
    return s ? '#centre/' + s : '';
  }
  /* Une durée en minutes, écrite « 7 h 05 » : une mise en forme ; la base a compté les minutes. */
  function duree(min) {
    if (min === null || min === undefined) return '—';
    var h = Math.floor(min / 60), m = min % 60;
    return t('c-pt-duree', { h: nombre(h), m: (m < 10 ? '0' : '') + m });
  }
  function charger(zone, appel, dessiner, silencieux) { return C.charger(zone, appel, dessiner, { silencieux: silencieux }); }

  /* ====================================================================== le centre de commande en cartes */
  function detailCarte(c) {
    return '<dl class="cc-tr-detail">' + Object.keys(c.detail || {}).filter(function (k) { return k !== 'balances' && c.detail[k] !== null && typeof c.detail[k] !== 'object'; }).map(function (k) {
      var v = c.detail[k];
      return '<div><dt>' + e(t('c-tr-d-' + k)) + '</dt><dd>' + e(typeof v === 'boolean' ? t(v ? 'c-tr-oui' : 'c-tr-non') : (typeof v === 'string' ? t('c-sa-s-' + v) || v : nombre(v))) + '</dd></div>';
    }).join('') + ((c.detail && c.detail.balances) || []).map(function (b) {
      return '<div><dt>' + e(t('c-tr-d-balance', { devise: b.currency })) + '</dt><dd>' + e(C.montant ? C.montant(b.balance, b.currency) : b.balance) + '</dd></div>';
    }).join('') + '</dl>';
  }
  function elementsCarte(c) {
    var l = c.items || [];
    if (!l.length) return '';
    return '<ul class="cc-tr-liste">' + l.slice(0, 5).map(function (x) {
      if (c.key === 'scans') return '<li><span class="ses-mono">' + e(x.code) + '</span> · ' + e(t('c-but-' + x.purpose) || x.purpose) + ' · ' + pastille('c-scan-' + x.result, x.result === 'ACCEPTED' ? 'ACTIVE' : 'PENDING') + '</li>';
      if (c.key === 'alerts') return '<li>' + e(t('c-att-' + x.kind) || x.kind) + ' · <strong>' + e(nombre(x.count)) + '</strong></li>';
      if (x.tracking_number) return '<li><span class="ses-mono">' + e(x.tracking_number) + '</span> · ' + e(t('c-colis-' + x.status) || x.status) + (x.since ? ' · ' + e(C.age ? C.age(x.since) : '') : '') + '</li>';
      if (x.code) return '<li><span class="ses-mono">' + e(x.code) + '</span> · ' + e(t('c-exp-' + x.status) || x.status) + (x.at ? ' · ' + e(date(x.at)) : '') + '</li>';
      return '';
    }).join('') + '</ul>';
  }
  /* Une carte de la base qui ouvrait un module retiré de la barre (Transport, Douane, Consolidations, Entrepôts) ouvre maintenant les
     Expéditions : leurs gestes y sont, sur la fiche de chaque expédition. */
  var MODULE_RELAIS = { transport: 'expeditions', douane: 'expeditions', consolidations: 'expeditions', entrepots: 'expeditions' };
  function dessinerCartes(zone, d) {
    var cartes = d.cards || [];
    zone.innerHTML = '<p class="cc-intro">' + e(t('c-tr-intro')) + '</p>' +
      (cartes.length ? '<ul class="cc-tr-grille">' + cartes.map(function (c) {
        var mod = MODULE_RELAIS[c.module] || c.module, href = lienModule(mod);
        var corps = '<span class="cc-tr-titre">' + e(t('c-tr-' + c.key)) + '</span><strong class="cc-tr-nombre">' + e(nombre(c.count)) + '</strong>' + detailCarte(c) + elementsCarte(c) +
          (href ? '<span class="cc-tr-ouvrir">' + e(t('c-tr-ouvrir', { module: t('c-mod-' + mod) })) + '</span>' : '');
        return '<li class="cc-tr-carte cc-tr-' + e(c.severity) + '">' + (href ? '<a class="cc-tr-lien" href="' + e(href) + '">' + corps + '</a>' : '<div class="cc-tr-lien">' + corps + '</div>') + '</li>';
      }).join('') + '</ul>' : '<p class="cc-rien">' + e(t('c-tr-aucune')) + '</p>') +
      '<p class="cc-petit">' + e(t('c-tr-maj', { heure: date(d.as_of) })) + '</p>';
  }
  function chargerCartes(zone, st, ctx, silencieux) { return charger(zone, function () { return API.tableau.commande(); }, function (d) { dessinerCartes(zone, d); }, silencieux); }

  /* ====================================================================== véhicules */
  function dessinerVehicules(zone, d) {
    var parStatut = d.by_status || {};
    var colonneGestion = C.colonneParc('vehicules');
    zone.innerHTML = '<p class="cc-intro">' + e(t('c-veh-intro')) + '</p>' + C.actionsParc('vehicules') +
      '<ul class="cc-puces">' + Object.keys(parStatut).sort().map(function (k) { return '<li><span class="cc-puce">' + e(t('c-veh-' + k)) + ' <strong>' + e(nombre(parStatut[k])) + '</strong></span></li>'; }).join('') + '</ul>' +
      (d.items.length ? C.tableau([
        { t: 'c-veh-col-plaque', rendre: function (v) { return '<span class="ses-mono">' + e(v.plate) + '</span>'; } },
        { t: 'c-veh-col-type', rendre: function (v) { return e(t('c-veh-kind-' + v.kind) || v.kind); } },
        { t: 'c-veh-col-statut', rendre: function (v) { return pastille('c-veh-' + v.status, v.status === 'ACTIVE' ? 'ACTIVE' : (v.status === 'MAINTENANCE' ? 'PENDING' : 'INACTIVE')) + (v.status_reason ? ' <span class="cc-petit">' + e(v.status_reason) + '</span>' : ''); } },
        { t: 'c-veh-col-chauffeurs', rendre: function (v) { return e((v.drivers || []).join(', ') || '—'); } },
        { t: 'c-veh-col-agence', rendre: function (v) { return e(v.branch || '—'); } },
        { t: 'c-veh-col-capacite', rendre: function (v) { return e(nombre(v.capacity_lb) + ' lb' + (v.capacity_ft3 ? ' · ' + nombre(v.capacity_ft3) + ' pi³' : '')); } },
        { t: 'c-veh-col-tournee', rendre: function (v) { return v.trip_today ? pastille('c-trip-' + v.trip_today.status, v.trip_today.status === 'STARTED' ? 'ACTIVE' : 'REQUESTED') + ' · ' + e(t('c-trip-arrets', { n: nombre(v.trip_today.stops) })) : '—'; } }
      ].concat(colonneGestion ? [colonneGestion] : []), d.items, { legende: 'c-sec-vehicules' }) : '<p class="cc-rien">' + e(t('c-veh-aucun')) + '</p>');
  }

  /* ====================================================================== tournées */
  function dessinerTournees(zone, d) {
    var gerer = !d.mine_only && C.peutGererTournees && C.peutGererTournees();
    zone.innerHTML = '<p class="cc-intro">' + e(t(d.mine_only ? 'c-trip-intro-moi' : 'c-trip-intro', { date: jour(d.date) })) + '</p>' +
      (gerer ? '<div class="cc-barre-actions"><button type="button" class="ses-bouton ses-bouton-principal" data-act="trip-nouvelle">' + e(t('c-dk-g-tournee')) + '</button></div>' : '') +
      (d.items.length ? C.tableau([
        { t: 'c-trip-col-chauffeur', rendre: function (x) { return e(x.driver || '—'); } },
        { t: 'c-trip-col-vehicule', rendre: function (x) { return '<span class="ses-mono">' + e(x.vehicle || '—') + '</span>'; } },
        { t: 'c-trip-col-statut', rendre: function (x) { return pastille('c-trip-' + x.status, x.status === 'COMPLETED' || x.status === 'STARTED' ? 'ACTIVE' : (x.status === 'CANCELLED' ? 'INACTIVE' : 'REQUESTED')); } },
        { t: 'c-trip-col-arrets', rendre: function (x) { return e(t('c-trip-avancement', { faits: nombre(x.done), echecs: nombre(x.failed), total: nombre(x.stops) })); } },
        { t: 'c-trip-col-charge', rendre: function (x) { return e(nombre(x.load_lb) + ' / ' + nombre(x.capacity_lb) + ' lb'); } },
        { t: 'c-trip-col-depart', rendre: function (x) { return e(x.started_at ? date(x.started_at) : '—'); } }
      ].concat(gerer ? [{ t: 'c-gst-col-actions', rendre: function (x) {
        return x.status === 'PLANNED' && x.trip_id ? '<button type="button" class="ses-bouton ses-bouton-mini ses-bouton-second" data-act="trip-annuler" data-ligne="' +
          e(JSON.stringify({ id: x.trip_id, chauffeur: x.driver })) + '">' + e(t('c-dk-g-annuler-tournee')) + '</button>' : '';
      } }] : []), d.items, { legende: 'c-sec-tournees' }) : '<p class="cc-rien">' + e(t('c-trip-aucune')) + '</p>');
  }

  /* ====================================================================== dépenses */
  var CATEGORIES = ['TRANSPORT', 'CUSTOMS', 'FUEL', 'SALARY', 'RENT', 'UTILITIES', 'MAINTENANCE', 'PACKAGING', 'OTHER'];
  function formDepenses(st) {
    var f = st.filtres || {};
    return '<form class="cc-filtres cc-dep-filtres" novalidate aria-label="' + e(t('c-filtres-titre')) + '">' +
      '<label class="ses-champ" for="cc-dep-du"><span>' + e(t('c-f-du')) + '</span><input id="cc-dep-du" name="du" type="date" value="' + e(f.du || '') + '"></label>' +
      '<label class="ses-champ" for="cc-dep-au"><span>' + e(t('c-f-au')) + '</span><input id="cc-dep-au" name="au" type="date" value="' + e(f.au || '') + '"></label>' +
      '<label class="ses-champ" for="cc-dep-cat"><span>' + e(t('c-dep-categorie')) + '</span><select id="cc-dep-cat" name="categorie"><option value="">' + e(t('c-f-tous')) + '</option>' +
      CATEGORIES.map(function (c) { return '<option value="' + c + '"' + (f.categorie === c ? ' selected' : '') + '>' + e(t('c-dep-cat-' + c)) + '</option>'; }).join('') + '</select></label>' +
      '<div class="cc-filtres-actions"><button type="submit" class="ses-bouton ses-bouton-principal ses-bouton-mini">' + e(t('c-appliquer')) + '</button></div></form>';
  }
  function dessinerDepenses(zone, d) {
    var cible = zone.querySelector('#cc-dep-resultat') || zone;
    cible.innerHTML = '<ul class="cc-kpis"><li><div class="cc-kpi"><span class="cc-kpi-etiquette">' + e(t('c-dep-total')) + '</span><strong class="cc-kpi-valeur">' + e(C.montant(d.total_usd, 'USD')) + '</strong>' +
      '<span class="cc-petit">' + e(t('c-dep-periode', { du: jour(d.from), au: jour(d.to) })) + '</span></div></li>' +
      d.by_category.map(function (c) { return '<li><div class="cc-kpi"><span class="cc-kpi-etiquette">' + e(t('c-dep-cat-' + c.category)) + '</span><strong class="cc-kpi-valeur">' + e(C.montant(c.total_usd, 'USD')) + '</strong><span class="cc-petit">' + e(t('c-dep-nb', { n: nombre(c.count) })) + '</span></div></li>'; }).join('') +
      '</ul>' + (d.by_currency.length > 1 ? '<p class="cc-petit">' + d.by_currency.map(function (c) { return e(C.montant(c.total, c.currency)); }).join(' · ') + '</p>' : '') +
      (d.items.length ? C.tableau([
        { t: 'c-dep-col-numero', rendre: function (x) { return '<span class="ses-mono">' + e(x.number) + '</span>'; } },
        { t: 'c-dep-col-date', rendre: function (x) { return e(jour(x.incurred_on)); } },
        { t: 'c-dep-categorie', rendre: function (x) { return e(t('c-dep-cat-' + x.category)); } },
        { t: 'c-dep-col-description', rendre: function (x) { return e(x.description || '—') + (x.supplier ? ' <span class="cc-petit">' + e(x.supplier) + '</span>' : ''); } },
        { t: 'c-dep-col-montant', rendre: function (x) { return e(C.montant(x.amount, x.currency)) + (x.currency !== 'USD' ? ' <span class="cc-petit">' + e(C.montant(x.amount_usd, 'USD')) + '</span>' : ''); } },
        { t: 'c-dep-col-statut', rendre: function (x) { return pastille('c-dep-st-' + x.status, x.status === 'VOIDED' ? 'INACTIVE' : 'ACTIVE'); } }
      ], d.items, { legende: 'c-sec-depenses' }) : '<p class="cc-rien">' + e(t('c-dep-aucune')) + '</p>');
  }
  function chargerDepenses(zone, st, silencieux) {
    var cible = zone.querySelector('#cc-dep-resultat');
    return C.charger(cible, function () { return API.tableau.depenses(st.filtres || {}); }, function (d) { dessinerDepenses(zone, d); }, { silencieux: silencieux });
  }

  /* ====================================================================== pointage express */
  var etatPt = { vue: 'personnel', session: null };
  var GENRES_PT = ['ARRIVAL', 'LOADING', 'INVENTORY', 'OTHER'];
  function peutPointerColis() { var a = accesTableau(); return !!(a && a.can && a.can.status); }
  function estDirection() { var a = accesTableau(); return !!(a && a.direction); }

  function boutonsHorloge(j) {
    var permis = { OUT: ['IN'], IN: ['BREAK_START', 'OUT'], BREAK_END: ['BREAK_START', 'OUT'], BREAK_START: ['BREAK_END'] }[j.state] || ['IN'];
    return '<div class="cc-pt-horloge">' + ['IN', 'BREAK_START', 'BREAK_END', 'OUT'].map(function (k) {
      var ok = permis.indexOf(k) >= 0;
      return '<button type="button" class="ses-bouton ' + (ok ? 'ses-bouton-principal' : 'ses-bouton-second') + '" data-horloge="' + k + '"' + (ok ? '' : ' disabled') + '>' + e(t('c-pt-' + k)) + '</button>';
    }).join('') + '</div>';
  }
  function dessinerPersonnel(zone, j, releve) {
    var html = '<section class="cc-groupe"><h3>' + e(t('c-pt-ma-journee')) + '</h3>' +
      '<p class="cc-pt-etat">' + pastille('c-pt-etat-' + j.state, j.state === 'OUT' ? 'INACTIVE' : (j.state === 'BREAK_START' ? 'PENDING' : 'ACTIVE')) +
      ' <span>' + e(t('c-pt-travaille', { duree: duree(j.worked_minutes) })) + '</span> · <span>' + e(t('c-pt-pause', { duree: duree(j.break_minutes) })) + '</span></p>' +
      boutonsHorloge(j) + '<p class="cc-form-msg" role="status" data-pt="message" hidden></p>' +
      (j.events.length ? '<ol class="cc-pt-evenements">' + j.events.map(function (x) { return '<li>' + e(t('c-pt-' + x.kind)) + ' · ' + e(date(x.at)) + (x.reason ? ' · <span class="cc-petit">' + e(x.reason) + '</span>' : '') + '</li>'; }).join('') + '</ol>' : '') +
      '</section>';
    if (estDirection()) {
      html += '<section class="cc-groupe cc-pt-releve"><h3>' + e(t('c-pt-releve')) + '</h3>' +
        '<form class="cc-filtres" data-pt="releve" novalidate><label class="ses-champ" for="cc-pt-du"><span>' + e(t('c-f-du')) + '</span><input id="cc-pt-du" name="du" type="date" required value="' + e(releve.du) + '"></label>' +
        '<label class="ses-champ" for="cc-pt-au"><span>' + e(t('c-f-au')) + '</span><input id="cc-pt-au" name="au" type="date" required value="' + e(releve.au) + '"></label>' +
        '<div class="cc-filtres-actions"><button type="submit" class="ses-bouton ses-bouton-principal ses-bouton-mini">' + e(t('c-appliquer')) + '</button></div></form><div data-pt="releve-resultat" aria-live="polite"></div></section>';
    }
    zone.innerHTML = html;
  }
  function dessinerReleve(cible, r) {
    cible.innerHTML = '<p class="cc-petit">' + e(t('c-pt-releve-total', { duree: duree(r.total_minutes), n: nombre(r.anomalies) })) + '</p>' +
      (r.rows.length ? C.tableau([
        { t: 'c-pt-col-membre', rendre: function (x) { return e(x.name || x.staff_code || '—') + (x.staff_code ? ' <span class="ses-mono cc-petit">' + e(x.staff_code) + '</span>' : ''); } },
        { t: 'c-pt-col-jour', rendre: function (x) { return e(jour(x.date)); } },
        { t: 'c-pt-col-arrivee', rendre: function (x) { return e(x.first_in ? date(x.first_in) : '—'); } },
        { t: 'c-pt-col-depart', rendre: function (x) { return e(x.last_out ? date(x.last_out) : '—'); } },
        { t: 'c-pt-col-travaille', rendre: function (x) { return e(duree(x.worked_minutes)); } },
        { t: 'c-pt-col-anomalies', rendre: function (x) { return x.anomalies.length ? x.anomalies.map(function (a) { return pastille('c-pt-anom-' + a, 'PENDING'); }).join(' ') : '—'; } }
      ], r.rows, { legende: 'c-pt-releve' }) : '<p class="cc-rien">' + e(t('c-pt-releve-vide')) + '</p>');
  }

  function dessinerColis(zone, liste) {
    var entrepots = C.entrepots ? C.entrepots() : [];
    zone.innerHTML = '<section class="cc-groupe"><h3>' + e(t('c-pt-nouveau')) + '</h3><form class="cc-filtres" data-pt="ouvrir" novalidate>' +
      '<label class="ses-champ" for="cc-pt-genre"><span>' + e(t('c-pt-genre')) + '</span><select id="cc-pt-genre" name="genre">' + GENRES_PT.map(function (g) { return '<option value="' + g + '">' + e(t('c-pt-genre-' + g)) + '</option>'; }).join('') + '</select></label>' +
      '<label class="ses-champ" for="cc-pt-source"><span>' + e(t('c-pt-source')) + '</span><select id="cc-pt-source" name="source">' +
      entrepots.map(function (w) { return '<option value="warehouse:' + e(w.warehouse_id) + '">' + e(t('c-pt-source-entrepot', { entrepot: w.code + ' — ' + w.name })) + '</option>'; }).join('') +
      '<option value="list">' + e(t('c-pt-source-liste')) + '</option></select></label>' +
      '<label class="ses-champ cc-pt-numeros" for="cc-pt-numeros"><span>' + e(t('c-pt-numeros')) + '</span><textarea id="cc-pt-numeros" name="numeros" rows="3" placeholder="SES-4821937065"></textarea></label>' +
      '<div class="cc-filtres-actions"><button type="submit" class="ses-bouton ses-bouton-principal ses-bouton-mini">' + e(t('c-pt-ouvrir')) + '</button></div></form>' +
      '<p class="cc-form-msg" role="status" data-pt="message" hidden></p></section>' +
      '<section class="cc-groupe"><h3>' + e(t('c-pt-liste')) + '</h3>' + (liste.length ? C.tableau([
        { t: 'c-pt-col-numero', rendre: function (x) { return '<button type="button" class="cc-lien-bouton ses-mono" data-pt-session="' + e(x.tally_id) + '">' + e(x.number) + '</button>'; } },
        { t: 'c-pt-genre', rendre: function (x) { return e(t('c-pt-genre-' + x.kind)); } },
        { t: 'c-pt-source', rendre: function (x) { return e(x.source); } },
        { t: 'c-pt-col-statut', rendre: function (x) { return pastille('c-pt-st-' + x.status, x.status === 'OPEN' ? 'REQUESTED' : 'INACTIVE'); } },
        { t: 'c-pt-col-avancement', rendre: function (x) { return e(t('c-pt-avancement', { pointes: nombre(x.checked), attendus: nombre(x.expected), trop: nombre(x.extra) })); } },
        { t: 'c-pt-col-ouvert', rendre: function (x) { return e(date(x.opened_at)); } }
      ], liste, { legende: 'c-pt-liste' }) : '<p class="cc-rien">' + e(t('c-pt-aucun')) + '</p>') + '</section>';
  }
  function dessinerSession(zone, s, dernier) {
    var ouvert = s.status === 'OPEN';
    zone.innerHTML = '<p><button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-pt="retour">← ' + e(t('c-pt-liste')) + '</button></p>' +
      '<section class="cc-groupe"><h3>' + e(t('c-pt-session', { numero: s.number })) + ' · ' + e(t('c-pt-genre-' + s.kind)) + ' · ' + e(s.source) + '</h3>' +
      '<ul class="cc-kpis"><li><div class="cc-kpi"><span class="cc-kpi-etiquette">' + e(t('c-pt-attendus')) + '</span><strong class="cc-kpi-valeur">' + e(nombre(s.expected)) + '</strong></div></li>' +
      '<li><div class="cc-kpi"><span class="cc-kpi-etiquette">' + e(t('c-pt-pointes')) + '</span><strong class="cc-kpi-valeur">' + e(nombre(s.checked)) + '</strong></div></li>' +
      '<li><div class="cc-kpi"><span class="cc-kpi-etiquette">' + e(t('c-pt-manquants')) + '</span><strong class="cc-kpi-valeur">' + e(nombre(s.missing.length)) + '</strong></div></li>' +
      '<li><div class="cc-kpi"><span class="cc-kpi-etiquette">' + e(t('c-pt-en-trop')) + '</span><strong class="cc-kpi-valeur">' + e(nombre(s.extra.length + s.unknown.length)) + '</strong></div></li></ul>' +
      (ouvert ? '<form class="cc-pt-lecture" data-pt="lire" novalidate><label class="ses-champ" for="cc-pt-code"><span>' + e(t('c-pt-code')) + '</span>' +
        '<input id="cc-pt-code" name="code" type="text" autocomplete="off" autocapitalize="characters" spellcheck="false" maxlength="500"></label>' +
        '<button type="submit" class="ses-bouton ses-bouton-principal">' + e(t('c-pt-pointer')) + '</button></form>' +
        '<p class="cc-pt-resultat cc-pt-' + e(dernier ? dernier.result : 'vide') + '" role="status" aria-live="assertive">' + (dernier ? e(t('c-pt-res-' + dernier.result, { numero: dernier.tracking_number })) : '') + '</p>' +
        '<p><button type="button" class="ses-bouton ses-bouton-second" data-pt="clore">' + e(t('c-pt-clore')) + '</button></p>'
        : '<p class="cc-note" role="note">' + e(t('c-pt-clos', { date: date(s.closed_at) })) + '</p>') +
      (s.missing.length ? '<h4>' + e(t('c-pt-manquants')) + '</h4><p class="ses-mono cc-pt-numeros-liste">' + s.missing.map(e).join(' · ') + '</p>' : '') +
      (s.extra.length ? '<h4>' + e(t('c-pt-en-trop')) + '</h4><p class="ses-mono cc-pt-numeros-liste">' + s.extra.map(e).join(' · ') + '</p>' : '') +
      (s.unknown.length ? '<h4>' + e(t('c-pt-inconnus')) + '</h4><p class="ses-mono cc-pt-numeros-liste">' + s.unknown.map(e).join(' · ') + '</p>' : '') + '</section>';
    var champ = zone.querySelector('#cc-pt-code');
    if (champ) champ.focus();
  }

  function rendrePointage(zone, st, ctx, silencieux) {
    var aujourdHui = (accesTableau() || {}).today || '';
    if (!zone.querySelector('[data-pt="corps"]')) {
      zone.innerHTML = '<p class="cc-intro">' + e(t('c-pt-intro')) + '</p>' +
        (peutPointerColis() ? '<div class="cc-pt-vues" role="group" aria-label="' + e(t('c-sec-pointage')) + '">' +
          ['personnel', 'colis'].map(function (v) { return '<button type="button" class="cc-puce' + (etatPt.vue === v ? ' cc-puce-actif' : '') + '" data-pt-vue="' + v + '" aria-pressed="' + (etatPt.vue === v) + '">' + e(t('c-pt-vue-' + v)) + '</button>'; }).join('') + '</div>' : '') +
        '<div data-pt="corps" aria-live="polite"></div>';
    }
    var corps = zone.querySelector('[data-pt="corps"]');
    if (etatPt.vue === 'colis' && peutPointerColis()) {
      if (etatPt.session) return C.charger(corps, function () { return API.tableau.detailPointage(etatPt.session); }, function (s) { dessinerSession(corps, s, etatPt.dernier); }, { silencieux: silencieux });
      return C.charger(corps, function () { return API.tableau.pointages(); }, function (l) { dessinerColis(corps, l); }, { silencieux: silencieux });
    }
    var releve = etatPt.releve || { du: aujourdHui, au: aujourdHui };
    return C.charger(corps, function () { return API.tableau.maJournee(); }, function (j) { dessinerPersonnel(corps, j, releve); }, { silencieux: silencieux });
  }

  function message(zone, cle, err) {
    var m = zone.querySelector('[data-pt="message"]');
    if (!m) return;
    m.hidden = false;
    m.textContent = err ? ((window.SES_UI && window.SES_UI.messageErreur) ? window.SES_UI.messageErreur(err) : String(err.message || err)) : t(cle);
  }

  function clicPointage(ev, st, ctx) {
    var zone = document.getElementById('cc-contenu');
    var b;
    if ((b = ev.target.closest('[data-pt-vue]'))) { etatPt.vue = b.getAttribute('data-pt-vue'); etatPt.session = null; zone.innerHTML = ''; return rendrePointage(zone, st, ctx); }
    if ((b = ev.target.closest('[data-horloge]'))) {
      b.disabled = true;
      return API.tableau.horloge(b.getAttribute('data-horloge')).then(function () { rendrePointage(zone, st, ctx, true); }, function (err) { message(zone, null, err); b.disabled = false; });
    }
    if ((b = ev.target.closest('[data-pt-session]'))) { etatPt.session = b.getAttribute('data-pt-session'); etatPt.dernier = null; return rendrePointage(zone, st, ctx); }
    if ((b = ev.target.closest('[data-pt="retour"]'))) { etatPt.session = null; return rendrePointage(zone, st, ctx); }
    if ((b = ev.target.closest('[data-pt="clore"]'))) {
      b.disabled = true;
      return API.tableau.clorePointage(etatPt.session).then(function () { etatPt.dernier = null; rendrePointage(zone, st, ctx); }, function (err) { b.disabled = false; message(zone, null, err); });
    }
  }
  function soumettrePointage(ev) {
    var f = ev.target.closest('[data-pt]');
    if (!f || f.tagName !== 'FORM') return false;
    ev.preventDefault();
    var zone = document.getElementById('cc-contenu');
    var kind = f.getAttribute('data-pt');
    if (kind === 'lire') {
      var champ = f.elements.code, code = String(champ.value || '').trim();
      if (!code) return true;
      champ.value = '';
      // Une clé par lecture : un double envoi (réseau lent, double appui) ne pointe pas deux fois.
      var cle = 'ptg:' + etatPt.session + ':' + Date.now().toString(36) + ':' + Math.random().toString(36).slice(2, 8);
      API.tableau.pointer(etatPt.session, code, 'manual', cle).then(function (r) { etatPt.dernier = r; rendrePointage(zone, {}, {}, true); },
        function (err) { etatPt.dernier = { result: 'ERREUR', tracking_number: code }; rendrePointage(zone, {}, {}, true); message(zone, null, err); });
      return true;
    }
    if (kind === 'ouvrir') {
      var src = f.elements.source.value, nums = String(f.elements.numeros.value || '').split(/[\s,;]+/).filter(Boolean);
      var o = { genre: f.elements.genre.value, source: src === 'list' ? 'list' : 'warehouse', id: src === 'list' ? undefined : src.split(':')[1], numeros: src === 'list' ? nums : undefined };
      API.tableau.ouvrirPointage(o).then(function (s) { etatPt.session = s.tally_id; etatPt.dernier = null; rendrePointage(zone, {}, {}); }, function (err) { message(zone, null, err); });
      return true;
    }
    if (kind === 'releve') {
      etatPt.releve = { du: f.elements.du.value, au: f.elements.au.value };
      var cible = zone.querySelector('[data-pt="releve-resultat"]');
      C.charger(cible, function () { return API.tableau.releve(etatPt.releve.du, etatPt.releve.au); }, function (r) { dessinerReleve(cible, r); }, {});
      return true;
    }
    return false;
  }

  /* ====================================================================== mes missions (chauffeur) */
  function dessinerMissions(zone, l) {
    zone.innerHTML = '<p class="cc-intro">' + e(t('c-mm-intro')) + '</p>' + (l.length ? C.tableau([
      { t: 'c-mm-col-genre', rendre: function (x) { return e(t(x.kind === 'PICKUP' ? 'c-dk-enlevement' : 'c-dk-livraison')); } },
      { t: 'c-mm-col-statut', rendre: function (x) { return pastille('c-miss-' + x.status, x.status === 'STARTED' ? 'ACTIVE' : 'REQUESTED'); } },
      { t: 'c-mm-col-adresse', rendre: function (x) { return e(x.address) + (x.recipient_name ? ' <span class="cc-petit">' + e(x.recipient_name) + '</span>' : ''); } },
      { t: 'c-mm-col-creneau', rendre: function (x) { return e(x.window_start ? date(x.window_start) + ' – ' + date(x.window_end) : jour(x.scheduled_date)); } },
      { t: 'c-mm-col-colis', rendre: function (x) { return '<span class="ses-mono">' + (x.parcels || []).map(function (p) { return e(p.tracking_number); }).join(' · ') + '</span>'; } }
    ], l, { legende: 'c-sec-mes-missions' }) : '<p class="cc-rien">' + e(t('c-mm-aucune')) + '</p>');
  }

  /* ====================================================================== le parc et les chauffeurs : créer, modifier
     Les formulaires ne décident rien : la base vérifie les droits (créer : la direction ; modifier : un responsable de livraison),
     les valeurs (plaque unique, capacité positive, véhicule actif et libre…) et exige un MOTIF pour tout changement de statut.
     Une erreur de la base s'affiche telle quelle dans le formulaire, qui reste ouvert. */
  var TYPES_VEHICULE = ['MOTORCYCLE', 'CAR', 'VAN', 'TRUCK'];
  var STATUTS_VEHICULE = ['ACTIVE', 'MAINTENANCE', 'OUT_OF_SERVICE'];
  var STATUTS_CHAUFFEUR = ['ACTIVE', 'ON_LEAVE', 'INACTIVE'];
  function peutGererParc() { var a = accesTableau(); return !!(a && (a.direction || a.ops)); }
  function champ(cle, html, aide) { return '<label class="ses-champ"><span>' + e(t(cle)) + '</span>' + html + (aide ? '<small>' + e(t(aide)) + '</small>' : '') + '</label>'; }
  function choix(nom, valeurs, prefixe, courant, premier) {
    return '<select name="' + nom + '">' + (premier ? '<option value="' + e(premier[0]) + '">' + e(t(premier[1])) + '</option>' : '') + valeurs.map(function (v) {
      var val = typeof v === 'string' ? v : v.valeur, lib = typeof v === 'string' ? t(prefixe + v) : v.libelle;
      return '<option value="' + e(val) + '"' + (val === courant ? ' selected' : '') + '>' + e(lib) + '</option>';
    }).join('') + '</select>';
  }
  function formulaire(id, corps, bouton) {
    return '<form id="' + id + '" novalidate>' + corps + '<div id="cc-form-msg" role="alert" class="cc-form-msg" hidden></div>' +
      '<div class="cc-form-actions"><button type="button" class="ses-bouton ses-bouton-second" data-fermer>' + e(t('c-gst-annuler')) + '</button>' +
      '<button type="submit" class="ses-bouton ses-bouton-principal">' + e(t(bouton)) + '</button></div></form>';
  }
  // Ouvre le dialogue, branche « Annuler » et l'envoi ; `envoyer(f)` rend une promesse, ou une clé de texte si un champ manque.
  function dialogueGestion(titre, id, corps, bouton, envoyer, succes, ensuite) {
    var zone = C.dialogue(titre, formulaire(id, corps, bouton), 'etroit');
    var f = zone && zone.querySelector('#' + id);
    if (!f) return null;
    var msg = zone.querySelector('#cc-form-msg');
    f.querySelector('[data-fermer]').addEventListener('click', function () { C.fermerDialogue(); });
    f.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var r = envoyer(f);
      if (typeof r === 'string') { msg.hidden = false; msg.textContent = t(r); return; }
      msg.hidden = true;
      var fin = UI.occuper(f.querySelector('button[type=submit]'), t('c-envoi'));
      r.then(function (rep) { fin(); C.fermerDialogue(); C.annoncer(t(succes), 'succes'); C.rafraichir(); if (ensuite) ensuite(rep); },
             function (err) { fin(); msg.hidden = false; msg.textContent = C.message(err); });
    });
    return f;
  }
  function vehiculesActifs() {
    return API.tableau.vehicules().then(function (d) { return (d && d.items || []).filter(function (v) { return v.status === 'ACTIVE'; }); }, function () { return []; });
  }
  function ligneDe(b) { try { return JSON.parse(b.getAttribute('data-ligne') || '{}'); } catch (x) { return {}; } }
  function boutonLigne(act, cle, ligne) {
    return '<button type="button" class="ses-bouton ses-bouton-mini ses-bouton-second" data-act="' + act + '" data-ligne="' + e(JSON.stringify(ligne)) + '">' + e(t(cle)) + '</button>';
  }
  /* La barre d'actions au-dessus d'une liste : seulement pour qui peut s'en servir (la base le revérifie). */
  C.actionsParc = function (quoi) {
    if (!peutGererParc()) return '';
    var direction = estDirection();
    if (quoi === 'chauffeurs') return direction ? '<div class="cc-barre-actions"><button type="button" class="ses-bouton ses-bouton-principal" data-act="chauffeur-ajouter">' + e(t('c-gst-ajouter-chauffeur')) + '</button></div>' : '';
    if (quoi === 'vehicules') return direction ? '<div class="cc-barre-actions"><button type="button" class="ses-bouton ses-bouton-principal" data-act="vehicule-ajouter">' + e(t('c-gst-ajouter-vehicule')) + '</button></div>' : '';
    return '';
  };
  C.colonneParc = function (quoi) {
    if (!peutGererParc()) return null;
    if (quoi === 'chauffeurs') return { t: 'c-gst-col-actions', rendre: function (l) { return boutonLigne('chauffeur-modifier', 'c-gst-modifier', { id: l.driver_id, nom: l.name, telephone: l.phone, statut: l.status }); } };
    if (quoi === 'vehicules') return { t: 'c-gst-col-actions', rendre: function (v) { return boutonLigne('vehicule-statut', 'c-gst-changer-statut', { id: v.vehicle_id, plaque: v.plate, statut: v.status }); } };
    return null;
  };

  C.actions = C.actions || {};
  C.actions['vehicule-ajouter'] = function () {
    dialogueGestion('c-gst-ajouter-vehicule', 'cc-veh-ajout',
      '<p class="cc-intro">' + e(t('c-gst-vehicule-intro')) + '</p><div class="cc-form-grille">' +
      champ('c-veh-col-plaque', '<input name="plaque" maxlength="20" autocomplete="off" required>') +
      champ('c-veh-col-type', choix('type', TYPES_VEHICULE, 'c-veh-kind-', 'VAN')) +
      champ('c-gst-capacite-lb', '<input name="capacite" type="number" inputmode="decimal" min="1" step="1" required>') +
      champ('c-gst-volume', '<input name="volume" type="number" inputmode="decimal" min="1" step="1">', 'c-gst-facultatif') + '</div>',
      'c-gst-ajouter', function (f) {
        var plaque = String(f.elements.plaque.value || '').trim(), cap = String(f.elements.capacite.value || '').trim();
        if (!plaque) return 'c-gst-plaque-obligatoire';
        if (!(Number(cap) > 0)) return 'c-gst-capacite-obligatoire';
        return API.tableau.creerVehicule({ plaque: plaque, type: f.elements.type.value, capaciteLb: cap, volume: String(f.elements.volume.value || '').trim() });
      }, 'c-gst-vehicule-ajoute');
  };
  C.actions['vehicule-statut'] = function (b) {
    var l = ligneDe(b);
    dialogueGestion('c-gst-changer-statut', 'cc-veh-statut',
      '<p class="cc-intro">' + e(t('c-gst-statut-intro', { nom: l.plaque || '' })) + '</p><div class="cc-form-grille">' +
      champ('c-veh-col-statut', choix('statut', STATUTS_VEHICULE, 'c-veh-', l.statut)) + '</div>' +
      champ('c-motif', '<textarea name="motif" rows="2" maxlength="300" required></textarea>', 'c-gst-motif-aide'),
      'c-gst-enregistrer', function (f) {
        var motif = String(f.elements.motif.value || '').trim();
        if (f.elements.statut.value === l.statut) return 'c-gst-rien-change';
        if (!motif) return 'c-gst-motif-obligatoire';
        return API.tableau.statutVehicule(l.id, f.elements.statut.value, motif);
      }, 'c-gst-enregistre');
  };
  C.actions['chauffeur-ajouter'] = function () {
    var f = dialogueGestion('c-gst-ajouter-chauffeur', 'cc-chauf-ajout',
      '<p class="cc-intro">' + e(t('c-gst-chauffeur-intro')) + '</p><div class="cc-form-grille">' +
      champ('c-gst-membre', '<select name="membre" required><option value="">' + e(t('c-gst-chargement')) + '</option></select>', 'c-gst-membre-aide') +
      champ('c-col-nom', '<input name="nom" maxlength="120" autocomplete="off" required>') +
      champ('c-gst-telephone', '<input name="telephone" type="tel" maxlength="40" autocomplete="off">') +
      champ('c-col-vehicule', '<select name="vehicule"><option value="">' + e(t('c-gst-sans-vehicule')) + '</option></select>', 'c-gst-facultatif') +
      champ('c-gst-arrets-max', '<input name="arrets" type="number" min="1" max="200" step="1" value="30">') + '</div>',
      'c-gst-ajouter', function (f) {
        if (!f.elements.membre.value) return 'c-gst-membre-obligatoire';
        if (!String(f.elements.nom.value || '').trim()) return 'c-gst-nom-obligatoire';
        return API.tableau.creerChauffeur({ membre: f.elements.membre.value, nom: f.elements.nom.value, telephone: f.elements.telephone.value,
                                            vehicule: f.elements.vehicule.value || undefined, arretsMax: f.elements.arrets.value });
      }, 'c-gst-chauffeur-ajoute');
    if (!f) return;
    // Les membres de l'équipe actifs qui ne sont pas encore chauffeurs (la base les liste ; seule la direction peut les lire).
    API.centre.liste('utilisateurs', {}, { limite: 200, decalage: 0 }).then(function (d) {
      var l = (d && d.items || []).filter(function (u) { return u.active && !u.driver; });
      f.elements.membre.innerHTML = '<option value="">' + e(t(l.length ? 'c-gst-choisir' : 'c-gst-aucun-membre')) + '</option>' +
        l.map(function (u) { return '<option value="' + e(u.user_id) + '">' + e(u.email) + ' · ' + e(t('c-gst-role-' + u.role) || u.role) + '</option>'; }).join('');
    }, function (err) { f.elements.membre.innerHTML = '<option value="">' + e(C.message(err)) + '</option>'; });
    vehiculesActifs().then(function (l) {
      f.elements.vehicule.insertAdjacentHTML('beforeend', l.map(function (v) { return '<option value="' + e(v.vehicle_id) + '">' + e(v.plate) + ' · ' + e(t('c-veh-kind-' + v.kind)) + '</option>'; }).join(''));
    });
  };
  C.actions['chauffeur-modifier'] = function (b) {
    var l = ligneDe(b);
    var f = dialogueGestion('c-gst-modifier-chauffeur', 'cc-chauf-modif',
      '<p class="cc-intro">' + e(t('c-gst-modifier-intro', { nom: l.nom || '' })) + '</p><div class="cc-form-grille">' +
      champ('c-col-nom', '<input name="nom" maxlength="120" autocomplete="off" value="' + e(l.nom || '') + '">') +
      champ('c-gst-telephone', '<input name="telephone" type="tel" maxlength="40" autocomplete="off" value="' + e(l.telephone || '') + '">') +
      champ('c-gst-permis', '<input name="permis" maxlength="40" autocomplete="off">', 'c-gst-vide-inchange') +
      champ('c-gst-arrets-max', '<input name="arrets" type="number" min="1" max="200" step="1">', 'c-gst-vide-inchange') +
      champ('c-col-vehicule', '<select name="vehicule"><option value="-">' + e(t('c-gst-inchange')) + '</option><option value="">' + e(t('c-gst-sans-vehicule')) + '</option></select>') +
      champ('c-col-statut', choix('statut', STATUTS_CHAUFFEUR, 'c-chauf-', l.statut)) + '</div>' +
      champ('c-motif', '<textarea name="motif" rows="2" maxlength="300"></textarea>', 'c-gst-motif-statut-aide'),
      'c-gst-enregistrer', function (f) {
        var nom = String(f.elements.nom.value || '').trim(), tel = String(f.elements.telephone.value || '').trim();
        var permis = String(f.elements.permis.value || '').trim(), arrets = String(f.elements.arrets.value || '').trim();
        var vehicule = f.elements.vehicule.value, statut = f.elements.statut.value, motif = String(f.elements.motif.value || '').trim();
        var fiche = {};
        if (nom && nom !== l.nom) fiche.nom = nom;
        if (tel !== (l.telephone || '') && tel) fiche.telephone = tel;
        if (permis) fiche.permis = permis;
        if (arrets) fiche.arretsMax = arrets;
        var changeStatut = statut !== l.statut;
        if (changeStatut && !motif) return 'c-gst-motif-obligatoire';
        if (!Object.keys(fiche).length && vehicule === '-' && !changeStatut) return 'c-gst-rien-change';
        // L'un après l'autre : la fiche, le véhicule, puis le statut (un chauffeur mis en congé garde ainsi son véhicule à jour).
        var p = Promise.resolve();
        if (Object.keys(fiche).length) p = p.then(function () { return API.tableau.modifierChauffeur(l.id, fiche); });
        if (vehicule !== '-') p = p.then(function () { return API.tableau.vehiculeChauffeur(l.id, vehicule || null); });
        if (changeStatut) p = p.then(function () { return API.tableau.statutChauffeur(l.id, statut, motif); });
        return p;
      }, 'c-gst-enregistre');
    if (!f) return;
    vehiculesActifs().then(function (v) {
      f.elements.vehicule.insertAdjacentHTML('beforeend', v.map(function (x) { return '<option value="' + e(x.vehicle_id) + '">' + e(x.plate) + ' · ' + e(t('c-veh-kind-' + x.kind)) + '</option>'; }).join(''));
    });
  };

  /* ====================================================================== agences, entrepôts, emplacements (étape 023)
     La production n'en avait aucun : la direction les saisit ici (Miami, les HUB de Port-au-Prince et de Saint-Domingue…). Tout
     le reste en dépend : une expédition part d'une agence vers un HUB, le poste de scan reçoit dans un entrepôt. La base trace
     chaque geste, refuse un code déjà pris, ne change jamais le code ni le pays, ne désactive rien qui garde un colis. */
  var GENRES_AGENCE = ['office', 'hub', 'agency', 'warehouse_site'];
  var PAYS_AGENCE = ['US', 'HT', 'DO'];
  var GENRES_EMPLACEMENT = ['receiving', 'storage', 'staging', 'dispatch', 'quarantine', 'damaged'];
  var etatSites = { gerer: false };
  function actifPastille(actif) { return actif ? '<span class="ses-pastille ses-pastille-ok">' + e(t('c-site-actif')) + '</span>' : '<span class="ses-pastille ses-pastille-neutre">' + e(t('c-site-inactif')) + '</span>'; }
  function bouton(act, cle, ligne, principal) {
    return '<button type="button" class="ses-bouton ses-bouton-mini ' + (principal ? 'ses-bouton-principal' : 'ses-bouton-second') + '" data-act="' + act + '"' +
      (ligne ? ' data-ligne="' + e(JSON.stringify(ligne)) + '"' : '') + '>' + e(t(cle)) + '</button>';
  }
  function dessinerSites(zone, d) {
    var g = etatSites.gerer = !!(d && d.can_manage);
    var agences = (d && d.branches) || [];
    var html = '<p class="cc-intro">' + e(t('c-site-intro')) + '</p>' + (g ? '<div class="cc-barre-actions">' + bouton('agence-ajouter', 'c-site-ajouter-agence', null, true) + '</div>' : '');
    if (!agences.length) return (zone.innerHTML = html + '<p class="cc-rien">' + e(t(g ? 'c-site-aucune-direction' : 'c-site-aucune')) + '</p>');
    html += agences.map(function (b) {
      var entrepots = b.warehouses || [];
      return '<section class="cc-carte cc-site"><div class="cc-site-tete"><div><h3><span class="ses-mono">' + e(b.code) + '</span> · ' + e(b.name) + '</h3>' +
        '<p class="cc-petit">' + e(t('c-site-genre-' + b.kind)) + ' · ' + e(C.pays ? C.pays(b.country) : b.country) + (b.city ? ' · ' + e(b.city) : '') + ' ' + actifPastille(b.active) + '</p></div>' +
        (g ? '<div class="cc-site-actions">' + bouton('agence-modifier', 'c-gst-modifier', { id: b.branch_id, code: b.code, nom: b.name, genre: b.kind, ville: b.city, actif: b.active }) +
             (b.active ? bouton('entrepot-ajouter', 'c-site-ajouter-entrepot', { id: b.branch_id, code: b.code }) : '') + '</div>' : '') + '</div>' +
        (entrepots.length ? '<ul class="cc-site-entrepots">' + entrepots.map(function (w) {
          var empl = w.locations || [];
          return '<li class="cc-site-entrepot"><div class="cc-site-tete"><div><strong class="ses-mono">' + e(w.code) + '</strong> · ' + e(w.name) + ' ' + actifPastille(w.active) +
            ' <span class="cc-petit">' + e(t('c-site-n-emplacements', { n: nombre(empl.filter(function (l) { return l.active; }).length) })) + '</span></div>' +
            (g ? '<div class="cc-site-actions">' + bouton('entrepot-modifier', 'c-gst-modifier', { id: w.warehouse_id, code: w.code, nom: w.name, actif: w.active }) +
                 (w.active ? bouton('emplacement-ajouter', 'c-site-ajouter-emplacement', { id: w.warehouse_id, code: w.code }) : '') + '</div>' : '') + '</div>' +
            (empl.length ? '<details class="cc-site-details"><summary>' + e(t('c-site-voir-emplacements')) + '</summary><ul class="cc-site-emplacements">' + empl.map(function (l) {
              return '<li><span class="ses-mono">' + e(l.code) + '</span>' + (l.zone ? ' · ' + e(t('c-site-zone', { zone: l.zone })) : '') + ' · ' + e(t('c-site-empl-' + l.kind)) + ' ' + actifPastille(l.active) +
                (g ? ' ' + bouton('emplacement-actif', l.active ? 'c-site-desactiver' : 'c-site-reactiver', { id: l.location_id, code: l.code, actif: l.active }) : '') + '</li>';
            }).join('') + '</ul></details>' : '') + '</li>';
        }).join('') + '</ul>' : '<p class="cc-petit">' + e(t('c-site-aucun-entrepot')) + '</p>') + '</section>';
    }).join('');
    zone.innerHTML = html;
  }
  function chargerSites(z, st, ctx, s) { return charger(z, function () { return API.tableau.sites(); }, function (d) { dessinerSites(z, d); }, s); }

  C.actions['agence-ajouter'] = function () {
    dialogueGestion('c-site-ajouter-agence', 'cc-agence-ajout',
      '<p class="cc-intro">' + e(t('c-site-agence-intro')) + '</p><div class="cc-form-grille">' +
      champ('c-site-code', '<input name="code" maxlength="20" autocomplete="off" required>', 'c-site-code-aide') +
      champ('c-col-nom', '<input name="nom" maxlength="120" autocomplete="off" required>') +
      champ('c-site-genre', choix('genre', GENRES_AGENCE, 'c-site-genre-', 'hub')) +
      champ('c-site-pays', choix('pays', PAYS_AGENCE.map(function (x) { return { valeur: x, libelle: C.pays ? C.pays(x) : x }; }), '', 'HT'), 'c-site-pays-aide') +
      champ('c-site-ville', '<input name="ville" maxlength="80" autocomplete="off">') + '</div>',
      'c-gst-ajouter', function (f) {
        if (!String(f.elements.code.value || '').trim()) return 'c-site-code-obligatoire';
        if (!String(f.elements.nom.value || '').trim()) return 'c-site-nom-obligatoire';
        return API.tableau.creerAgence({ code: f.elements.code.value, nom: f.elements.nom.value, genre: f.elements.genre.value, pays: f.elements.pays.value, ville: f.elements.ville.value });
      }, 'c-site-agence-ajoutee');
  };
  C.actions['agence-modifier'] = function (b) {
    var l = ligneDe(b);
    dialogueGestion('c-site-modifier-agence', 'cc-agence-modif',
      '<p class="cc-intro">' + e(t('c-site-modifier-intro', { code: l.code || '' })) + '</p><div class="cc-form-grille">' +
      champ('c-col-nom', '<input name="nom" maxlength="120" autocomplete="off" value="' + e(l.nom || '') + '">') +
      champ('c-site-genre', choix('genre', GENRES_AGENCE, 'c-site-genre-', l.genre)) +
      champ('c-site-ville', '<input name="ville" maxlength="80" autocomplete="off" value="' + e(l.ville || '') + '">') +
      champ('c-site-etat', choix('actif', [{ valeur: 'oui', libelle: t('c-site-actif') }, { valeur: 'non', libelle: t('c-site-inactif') }], '', l.actif ? 'oui' : 'non')) + '</div>',
      'c-gst-enregistrer', function (f) {
        var o = {}, nom = String(f.elements.nom.value || '').trim(), ville = String(f.elements.ville.value || '').trim(), actif = f.elements.actif.value === 'oui';
        if (!nom) return 'c-site-nom-obligatoire';
        if (nom !== l.nom) o.nom = nom;
        if (f.elements.genre.value !== l.genre) o.genre = f.elements.genre.value;
        if (ville !== (l.ville || '')) o.ville = ville;
        if (actif !== !!l.actif) o.actif = actif;
        if (!Object.keys(o).length) return 'c-gst-rien-change';
        return API.tableau.modifierAgence(l.id, o);
      }, 'c-gst-enregistre');
  };
  C.actions['entrepot-ajouter'] = function (b) {
    var l = ligneDe(b);
    dialogueGestion('c-site-ajouter-entrepot', 'cc-entrepot-ajout',
      '<p class="cc-intro">' + e(t('c-site-entrepot-intro', { code: l.code || '' })) + '</p><div class="cc-form-grille">' +
      champ('c-site-code', '<input name="code" maxlength="20" autocomplete="off" required>', 'c-site-code-aide') +
      champ('c-col-nom', '<input name="nom" maxlength="120" autocomplete="off" required>') + '</div>',
      'c-gst-ajouter', function (f) {
        if (!String(f.elements.code.value || '').trim()) return 'c-site-code-obligatoire';
        if (!String(f.elements.nom.value || '').trim()) return 'c-site-nom-obligatoire';
        return API.tableau.creerEntrepot(l.id, { code: f.elements.code.value, nom: f.elements.nom.value });
      }, 'c-site-entrepot-ajoute');
  };
  C.actions['entrepot-modifier'] = function (b) {
    var l = ligneDe(b);
    dialogueGestion('c-site-modifier-entrepot', 'cc-entrepot-modif',
      '<p class="cc-intro">' + e(t('c-site-modifier-intro', { code: l.code || '' })) + '</p><div class="cc-form-grille">' +
      champ('c-col-nom', '<input name="nom" maxlength="120" autocomplete="off" value="' + e(l.nom || '') + '">') +
      champ('c-site-etat', choix('actif', [{ valeur: 'oui', libelle: t('c-site-actif') }, { valeur: 'non', libelle: t('c-site-inactif') }], '', l.actif ? 'oui' : 'non'), 'c-site-desactiver-aide') + '</div>',
      'c-gst-enregistrer', function (f) {
        var o = {}, nom = String(f.elements.nom.value || '').trim(), actif = f.elements.actif.value === 'oui';
        if (!nom) return 'c-site-nom-obligatoire';
        if (nom !== l.nom) o.nom = nom;
        if (actif !== !!l.actif) o.actif = actif;
        if (!Object.keys(o).length) return 'c-gst-rien-change';
        return API.tableau.modifierEntrepot(l.id, o);
      }, 'c-gst-enregistre');
  };
  C.actions['emplacement-ajouter'] = function (b) {
    var l = ligneDe(b);
    dialogueGestion('c-site-ajouter-emplacement', 'cc-empl-ajout',
      '<p class="cc-intro">' + e(t('c-site-emplacement-intro', { code: l.code || '' })) + '</p><div class="cc-form-grille">' +
      champ('c-site-code', '<input name="code" maxlength="20" autocomplete="off" required>', 'c-site-empl-code-aide') +
      champ('c-site-zone-champ', '<input name="zone" maxlength="40" autocomplete="off">', 'c-gst-facultatif') +
      champ('c-site-genre', choix('genre', GENRES_EMPLACEMENT, 'c-site-empl-', 'storage')) + '</div>',
      'c-gst-ajouter', function (f) {
        if (!String(f.elements.code.value || '').trim()) return 'c-site-code-obligatoire';
        return API.tableau.creerEmplacement(l.id, { code: f.elements.code.value, zone: f.elements.zone.value, genre: f.elements.genre.value });
      }, 'c-site-emplacement-ajoute');
  };
  C.actions['emplacement-actif'] = function (b) {
    var l = ligneDe(b);
    API.tableau.emplacementActif(l.id, !l.actif).then(function () { C.annoncer(t('c-gst-enregistre'), 'succes'); C.rafraichir(); },
                                                     function (err) { C.annoncer(C.message(err), 'erreur'); });
  };

  /* ====================================================================== expéditions et transports (étapes 005, 016, 024)
     Le cycle d'une expédition, tel que la base l'impose : brouillon → prête (manifeste) → partie (sur un transport) → en transit →
     arrivée → douane (droits, payés, libérée) → au HUB → clôturée (quand ses colis ont quitté le HUB). La fiche ne propose que les
     gestes de l'état présent ; la base revérifie chacun et dit pourquoi elle refuse. « Préparer des colis » fait faire à chaque colis
     le chemin du poste de scan (reçu, vérifié avec son poids, rangé, à consolider) : seuls ces colis peuvent partir en vrac. */
  var MODES = ['air', 'sea', 'ground'];
  var DEVISES = ['USD', 'DOP', 'HTG'];
  var GESTES_EXP = {
    DRAFT: ['planifier', 'prete', 'annuler'], READY: ['partir', 'rouvrir'], DISPATCHED: ['entransit', 'arrivee'], IN_TRANSIT: ['arrivee'],
    ARRIVED: ['douane', 'recevoir'], CUSTOMS_PROCESSING: ['droits', 'droitspayes', 'liberer', 'rejeter'], CUSTOMS_CLEARED: ['recevoir'], AT_HUB: ['cloturer']
  };
  function peutExpedier() { var a = accesTableau(); return !!(a && (a.direction || (a.can && a.can.status))); }
  function versIso(v) { if (!v) return null; var d = new Date(v); return isNaN(d.getTime()) ? null : d.toISOString(); }
  function versLocal(iso) { if (!iso) return ''; var d = new Date(iso); if (isNaN(d.getTime())) return ''; d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); }
  function cleUnique(prefixe) { return prefixe + '-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10); }
  function codeDuJour(prefixe) { var d = new Date(), z = function (n) { return (n < 10 ? '0' : '') + n; }; return prefixe + '-' + d.getFullYear() + z(d.getMonth() + 1) + z(d.getDate()) + '-' + z(d.getHours()) + z(d.getMinutes()); }
  function codeExpedition() { return codeDuJour('EXP'); }
  function agences(d, filtre) { return ((d && d.branches) || []).filter(function (b) { return b.active && (!filtre || filtre(b)); }); }
  function optionsAgences(l) { return l.map(function (b) { return { valeur: b.branch_id, libelle: b.code + ' · ' + b.name + ' (' + (C.pays ? C.pays(b.country) : b.country) + ')' }; }); }
  function entrepotsDe(d, branche) {
    var l = [];
    agences(d).forEach(function (b) { if (!branche || b.branch_id === branche) (b.warehouses || []).forEach(function (w) { if (w.active) l.push({ w: w, b: b }); }); });
    return l;
  }

  C.peutGererTournees = function () { return peutExpedier(); };
  C.actionsExpeditions = function () {
    if (!peutExpedier()) return '';
    return '<div class="cc-barre-actions">' + bouton('exp-nouvelle', 'c-exp-g-nouvelle', null, true) + bouton('exp-preparer', 'c-exp-g-preparer', null) +
      bouton('exp-transbordement', 'c-trb-g', null) + '</div>';
  };
  C.colonneExpeditions = function () {
    return { t: 'c-gst-col-actions', rendre: function (l) { return l.shipment_id ? bouton('exp-fiche', 'c-exp-g-ouvrir', { id: l.shipment_id, code: l.code }) : ''; } };
  };
  C.actionsTransports = function () { return peutExpedier() ? '<div class="cc-barre-actions">' + bouton('trans-nouveau', 'c-trans-g-nouveau', null, true) + '</div>' : ''; };
  C.colonneTransports = function () {
    if (!peutExpedier()) return null;
    return { t: 'c-gst-col-actions', rendre: function (l) {
      return l.transport_id && l.status === 'PLANNED' ? bouton('trans-replanifier', 'c-trans-g-replanifier', { id: l.transport_id, reference: l.reference, depart: l.planned_departure_at, arrivee: l.planned_arrival_at }) : '';
    } };
  };

  /* --- préparer des colis --- */
  C.actions['exp-preparer'] = function () {
    var f = dialogueGestion('c-exp-g-preparer', 'cc-exp-prep',
      '<p class="cc-intro">' + e(t('c-exp-prep-intro')) + '</p>' +
      champ('c-exp-prep-numeros', '<textarea name="numeros" rows="5" autocomplete="off" spellcheck="false" required></textarea>', 'c-exp-prep-numeros-aide') +
      '<div class="cc-form-grille">' + champ('c-exp-entrepot', '<select name="entrepot" required><option value="">' + e(t('c-gst-chargement')) + '</option></select>') +
      champ('c-exp-emplacement', '<select name="emplacement" required><option value="">' + e(t('c-gst-choisir')) + '</option></select>', 'c-exp-emplacement-aide') + '</div>',
      'c-exp-g-preparer-bouton', function (f) {
        if (!String(f.elements.numeros.value || '').trim()) return 'c-exp-prep-vide';
        if (!f.elements.entrepot.value || !f.elements.emplacement.value) return 'c-exp-prep-lieu';
        return API.tableau.preparer(f.elements.numeros.value, f.elements.entrepot.value, f.elements.emplacement.value);
      }, 'c-exp-prep-fait', function (rep) { resultatsPreparation(rep); });
    if (!f) return;
    API.tableau.sites().then(function (d) {
      var l = entrepotsDe(d);
      f.elements.entrepot.innerHTML = '<option value="">' + e(t(l.length ? 'c-gst-choisir' : 'c-exp-aucun-entrepot')) + '</option>' +
        l.map(function (x) { return '<option value="' + e(x.w.warehouse_id) + '">' + e(x.w.code + ' · ' + x.w.name + ' (' + x.b.code + ')') + '</option>'; }).join('');
      f.elements.entrepot.addEventListener('change', function () {
        var w = l.filter(function (x) { return x.w.warehouse_id === f.elements.entrepot.value; })[0];
        var empl = w ? (w.w.locations || []).filter(function (x) { return x.active; }) : [];
        f.elements.emplacement.innerHTML = '<option value="">' + e(t(empl.length ? 'c-gst-choisir' : 'c-exp-aucun-emplacement')) + '</option>' +
          empl.map(function (x) { return '<option value="' + e(x.location_id) + '">' + e(x.code + ' · ' + t('c-site-empl-' + x.kind)) + '</option>'; }).join('');
      });
    }, function (err) { f.elements.entrepot.innerHTML = '<option value="">' + e(C.message(err)) + '</option>'; });
  };
  function resultatsPreparation(rep) {
    var l = (rep && rep.results) || [], ko = l.filter(function (x) { return !x.ready; });
    var zone = C.dialogue('c-exp-prep-resultat', '<p class="cc-intro">' + e(t('c-exp-prep-bilan', { prets: nombre(rep && rep.prepared), total: nombre(l.length) })) + '</p>' +
      (ko.length ? '<ul class="cc-site-emplacements">' + ko.map(function (x) {
        return '<li><span class="ses-mono">' + e(x.code) + '</span> · ' + e(t('c-exp-raison-' + x.reason) || x.reason || '') + (x.status ? ' · ' + e(t('c-colis-' + x.status) || x.status) : '') + '</li>';
      }).join('') + '</ul>' : '') +
      '<div class="cc-form-actions">' + bouton('exp-nouvelle', 'c-exp-g-nouvelle', null, true) + '</div>', 'etroit');
    return zone;
  }

  /* --- nouvelle expédition --- */
  C.actions['exp-nouvelle'] = function () {
    var sites = null;
    var f = dialogueGestion('c-exp-g-nouvelle', 'cc-exp-nouv',
      '<p class="cc-intro">' + e(t('c-exp-nouv-intro')) + '</p><div class="cc-form-grille">' +
      champ('c-site-code', '<input name="code" maxlength="40" autocomplete="off" required value="' + e(codeExpedition()) + '">') +
      champ('c-exp-mode', choix('mode', MODES, 'c-svc-', 'air')) +
      champ('c-exp-origine', '<select name="origine" required><option value="">' + e(t('c-gst-chargement')) + '</option></select>') +
      champ('c-exp-destination', '<select name="destination" required><option value="">' + e(t('c-gst-chargement')) + '</option></select>', 'c-exp-destination-aide') + '</div>' +
      '<fieldset class="cc-exp-contenu"><legend>' + e(t('c-exp-contenu')) + '</legend><div id="cc-exp-pret" aria-live="polite"></div></fieldset>' +
      // 031 : où la base prépare les colis confirmés cochés (reçu, vérifié, rangé), demandé seulement s'il y en a
      '<div class="cc-form-grille" id="cc-exp-lieu-prep" hidden>' + champ('c-exp-entrepot', '<select name="entrepot"><option value="">' + e(t('c-gst-chargement')) + '</option></select>') +
      champ('c-exp-emplacement', '<select name="emplacement"><option value="">' + e(t('c-gst-choisir')) + '</option></select>', 'c-exp-confirmes-lieu') + '</div>',
      'c-exp-g-creer', function (f) {
        var colis = [].slice.call(f.querySelectorAll('input[name=colis]:checked')).map(function (x) { return x.value; });
        var confirmes = cocheesDe(f, 'confirme');
        var cons = [].slice.call(f.querySelectorAll('input[name=cons]:checked')).map(function (x) { return x.value; });
        var unites = cocheesDe(f, 'unite');
        if (!String(f.elements.code.value || '').trim()) return 'c-site-code-obligatoire';
        if (!f.elements.origine.value || !f.elements.destination.value) return 'c-exp-lieux-obligatoires';
        if (!colis.length && !cons.length && !unites.length && !confirmes.length) return 'c-exp-rien-choisi';
        if (confirmes.length) {
          if (!f.elements.entrepot.value || !f.elements.emplacement.value) return 'c-exp-prep-lieu';
          return API.tableau.creerExpeditionPreparee({ code: f.elements.code.value, mode: f.elements.mode.value, origine: f.elements.origine.value, destination: f.elements.destination.value,
                                                       colis: colis, consolidations: cons, unites: unites, confirmes: confirmes, entrepot: f.elements.entrepot.value,
                                                       emplacement: f.elements.emplacement.value, cle: f.getAttribute('data-cle') });
        }
        return API.tableau.creerExpedition({ code: f.elements.code.value, mode: f.elements.mode.value, origine: f.elements.origine.value, destination: f.elements.destination.value,
                                             colis: colis, consolidations: cons, unites: unites, cle: f.getAttribute('data-cle') });
      }, 'c-exp-creee', function (rep) { if (rep && rep.shipment_id) ouvrirFiche(rep.shipment_id); });
    if (!f) return;
    f.setAttribute('data-cle', cleUnique('exp'));   // un double clic ne crée pas deux expéditions (la base rend la première)
    var zonePret = f.querySelector('#cc-exp-pret');
    function chargerPret() {
      zonePret.innerHTML = '<p class="cc-petit">' + e(t('c-gst-chargement')) + '</p>';
      API.tableau.pret(f.elements.mode.value).then(function (d) {
        var p = d.parcels || [], k = d.consolidations || [], u = d.load_units || [], cf = d.confirmed || [];
        if (!p.length && !k.length && !u.length && !cf.length) { zonePret.innerHTML = '<p class="cc-petit">' + e(t('c-exp-rien-pret')) + '</p>'; majLieuPrep(); return; }
        zonePret.innerHTML = (u.length ? '<p class="cc-petit"><strong>' + e(t('c-exp-unites')) + '</strong></p><ul class="cc-exp-choix">' + u.map(function (x) {
          return '<li><label><input type="checkbox" name="unite" value="' + e(x.load_unit_id) + '"><span><span class="ses-mono">' + e(x.code) + '</span> · ' + e(t('c-unite-genre-' + x.kind)) + ' · ' +
            e(C.pays ? C.pays(x.destination_country) : x.destination_country) + ' · ' + e(t('c-exp-n-colis', { n: nombre(x.parcels) })) + ' · ' + e(nombre(x.weight_lb)) + ' lb · ' +
            e(x.status === 'SEALED' ? t('c-unite-scelle-n', { scelle: x.seal_number || '' }) : t('c-unite-a-sceller')) + '</span></label></li>';
        }).join('') + '</ul>' : '') + (k.length ? '<p class="cc-petit"><strong>' + e(t('c-exp-consolidations')) + '</strong></p><ul class="cc-exp-choix">' + k.map(function (x) {
          return '<li><label><input type="checkbox" name="cons" value="' + e(x.consolidation_id) + '"><span><span class="ses-mono">' + e(x.code) + '</span> · ' +
            e(C.pays ? C.pays(x.destination_country) : x.destination_country) + ' · ' + e(t('c-exp-n-colis', { n: nombre(x.parcels) })) + ' · ' + e(nombre(x.weight_lb)) + ' lb</span></label></li>';
        }).join('') + '</ul>' : '') +
        (p.length ? '<p class="cc-petit"><strong>' + e(t('c-exp-colis-prets', { n: nombre(p.length) })) + '</strong> <button type="button" class="cc-lien" data-tout>' + e(t('c-exp-tout-cocher')) + '</button></p><ul class="cc-exp-choix">' + p.map(function (x) {
          return '<li><label><input type="checkbox" name="colis" value="' + e(x.parcel_id) + '"><span><span class="ses-mono">' + e(x.tracking_number) + '</span> · ' +
            e((x.customer && (x.customer.code || x.customer.name)) || '') + ' · ' + e([x.destination_city, C.pays ? C.pays(x.destination_country) : x.destination_country].filter(Boolean).join(', ')) +
            (x.weight_lb !== null && x.weight_lb !== undefined ? ' · ' + e(nombre(x.weight_lb)) + ' lb' : '') + '</span></label></li>';
        }).join('') + '</ul>' : '');
        // 031 : les colis CONFIRMÉS (onglet Colis) : la base les prépare à la création de l'expédition
        zonePret.innerHTML += cf.length ? '<p class="cc-petit"><strong>' + e(t('c-exp-confirmes', { n: nombre(cf.length) })) + '</strong> <button type="button" class="cc-lien" data-tout-confirmes>' +
          e(t('c-exp-tout-cocher')) + '</button></p><ul class="cc-exp-choix">' + cf.map(function (x) {
            return '<li><label><input type="checkbox" name="confirme" value="' + e(x.parcel_id) + '"><span><span class="ses-mono">' + e(x.tracking_number) + '</span> · ' +
              e((x.customer && (x.customer.code || x.customer.name)) || '') + ' · ' + e([x.destination_city, C.pays ? C.pays(x.destination_country) : x.destination_country].filter(Boolean).join(', ')) +
              (x.weight_lb !== null && x.weight_lb !== undefined ? ' · ' + e(nombre(x.weight_lb)) + ' lb' : ' · ' + e(t('c-exp-sans-poids'))) + '</span></label></li>';
          }).join('') + '</ul>' : '';
        var tout = zonePret.querySelector('[data-tout]');
        if (tout) tout.addEventListener('click', function () { [].slice.call(zonePret.querySelectorAll('input[name=colis]')).forEach(function (x) { x.checked = true; }); });
        var toutConfirmes = zonePret.querySelector('[data-tout-confirmes]');
        if (toutConfirmes) toutConfirmes.addEventListener('click', function () { [].slice.call(zonePret.querySelectorAll('input[name=confirme]')).forEach(function (x) { x.checked = true; }); majLieuPrep(); });
        majLieuPrep();
      }, function (err) { zonePret.innerHTML = '<p class="cc-form-msg">' + e(C.message(err)) + '</p>'; });
    }
    // Le lieu de préparation n'apparaît (et ne devient obligatoire) que si un colis confirmé est coché.
    var lieuPrep = f.querySelector('#cc-exp-lieu-prep');
    function majLieuPrep() {
      var besoin = !!zonePret.querySelector('input[name=confirme]:checked');
      lieuPrep.hidden = !besoin;
      f.elements.entrepot.required = besoin; f.elements.emplacement.required = besoin;
    }
    zonePret.addEventListener('change', function (ev) { if (ev.target && ev.target.name === 'confirme') majLieuPrep(); });
    f.elements.mode.addEventListener('change', chargerPret);
    chargerPret();
    API.tableau.sites().then(function (d) {
      sites = d;
      var orig = agences(d), dest = agences(d, function (b) { return b.kind === 'hub'; });
      f.elements.origine.innerHTML = '<option value="">' + e(t(orig.length ? 'c-gst-choisir' : 'c-exp-aucune-agence')) + '</option>' + optionsAgences(orig).map(function (o) { return '<option value="' + e(o.valeur) + '">' + e(o.libelle) + '</option>'; }).join('');
      f.elements.destination.innerHTML = '<option value="">' + e(t(dest.length ? 'c-gst-choisir' : 'c-exp-aucun-hub')) + '</option>' + optionsAgences(dest).map(function (o) { return '<option value="' + e(o.valeur) + '">' + e(o.libelle) + '</option>'; }).join('');
      var l = entrepotsDe(d);
      f.elements.entrepot.innerHTML = '<option value="">' + e(t(l.length ? 'c-gst-choisir' : 'c-exp-aucun-entrepot')) + '</option>' +
        l.map(function (x) { return '<option value="' + e(x.w.warehouse_id) + '">' + e(x.w.code + ' · ' + x.w.name + ' (' + x.b.code + ')') + '</option>'; }).join('');
      f.elements.entrepot.addEventListener('change', function () {
        var w = l.filter(function (x) { return x.w.warehouse_id === f.elements.entrepot.value; })[0];
        var empl = w ? (w.w.locations || []).filter(function (x) { return x.active; }) : [];
        f.elements.emplacement.innerHTML = '<option value="">' + e(t(empl.length ? 'c-gst-choisir' : 'c-exp-aucun-emplacement')) + '</option>' +
          empl.map(function (x) { return '<option value="' + e(x.location_id) + '">' + e(x.code + ' · ' + t('c-site-empl-' + x.kind)) + '</option>'; }).join('');
      });
    });
  };

  /* --- la fiche d'une expédition --- */
  function ouvrirFiche(id) {
    var zone = C.dialogue('c-exp-fiche-titre', '<div id="cc-exp-fiche"><p class="cc-petit">' + e(t('c-gst-chargement')) + '</p></div>');
    var cible = zone && zone.querySelector('#cc-exp-fiche');
    if (!cible) return;
    Promise.all([API.tableau.ficheExpedition(id), API.tableau.colisExpedition(id)]).then(function (r) {
      var x = r[0] || {}, colis = r[1] || [], tr = x.transport, dou = x.customs;
      var gestes = peutExpedier() ? (GESTES_EXP[x.status] || []) : [];
      cible.innerHTML = '<div class="cc-site-tete"><div><h3><span class="ses-mono">' + e(x.code) + '</span> ' + pastille('c-exp-' + x.status, x.status) + '</h3>' +
        '<p class="cc-petit">' + e(t('c-svc-' + x.mode)) + ' · ' + e((x.origin && (x.origin.code || x.origin.label)) || '—') + ' → ' + e((x.destination && (x.destination.code || x.destination.label)) || '—') +
        (x.hub_warehouse ? ' · ' + e(x.hub_warehouse.code) : '') + '</p></div></div>' +
        '<dl class="cc-exp-dl">' +
        '<dt>' + e(t('c-exp-depart-prevu')) + '</dt><dd>' + e(x.planned_departure_at ? date(x.planned_departure_at) : '—') + '</dd>' +
        '<dt>' + e(t('c-exp-arrivee-prevue')) + '</dt><dd>' + e(x.planned_arrival_at ? date(x.planned_arrival_at) : '—') + '</dd>' +
        '<dt>' + e(t('c-col-transport')) + '</dt><dd>' + (tr ? e([tr.carrier, tr.reference, tr.voyage_number].filter(Boolean).join(' · ')) + ' ' + pastille('c-trans-' + tr.status, tr.status) : '—') + '</dd>' +
        '<dt>' + e(t('c-exp-douane')) + '</dt><dd>' + (dou ? e(dou.reference || '') + ' ' + pastille('c-dou-' + dou.status, dou.status) +
          (dou.duties_amount !== null && dou.duties_amount !== undefined ? ' · ' + e(t('c-exp-droits-montant', { montant: nombre(dou.duties_amount), devise: dou.duties_currency || '' })) + ' · ' + e(t(dou.duties_paid ? 'c-exp-droits-payes' : 'c-exp-droits-dus')) : '') : '—') + '</dd>' +
        '</dl>' +
        (gestes.length ? '<div class="cc-barre-actions">' + gestes.map(function (g) { return bouton('exp-geste', 'c-exp-g-' + g, { id: id, geste: g, code: x.code, mode: x.mode, statut: x.status,
          destination: x.destination && x.destination.code, hub: x.hub_warehouse && x.hub_warehouse.code, depart: x.planned_departure_at, arrivee: x.planned_arrival_at }, g === gestes[0]); }).join('') + '</div>' : '') +
        '<h4>' + e(t('c-exp-colis-titre', { n: nombre(colis.length) })) + '</h4>' +
        (colis.length ? '<ul class="cc-site-emplacements">' + colis.map(function (c) {
          return '<li><span class="ses-mono">' + e(c.tracking_number) + '</span> · ' + pastille('c-colis-' + c.status, c.status) + ' · ' + e((c.customer && (c.customer.code || c.customer.name)) || '') +
            ' · ' + e([c.destination_city, C.pays ? C.pays(c.destination_country) : c.destination_country].filter(Boolean).join(', ')) + '</li>';
        }).join('') + '</ul>' : '<p class="cc-petit">—</p>');
    }, function (err) { cible.innerHTML = '<p class="cc-form-msg">' + e(C.message(err)) + '</p>'; });
  }
  C.actions['exp-fiche'] = function (b) { ouvrirFiche(ligneDe(b).id); };

  /* --- les gestes de la fiche --- */
  C.actions['exp-geste'] = function (b) {
    var l = ligneDe(b), id = l.id, g = l.geste, reouvrir = function () { ouvrirFiche(id); };
    var simple = { prete: 'expeditionPrete', rouvrir: 'rouvrirExpedition', entransit: 'enTransit', arrivee: 'arrivee', droitspayes: 'droitsPayes', cloturer: 'cloturerExpedition' };
    if (simple[g]) {
      return dialogueGestion('c-exp-g-' + g, 'cc-exp-geste', '<p class="cc-intro">' + e(t('c-exp-conf-' + g, { code: l.code })) + '</p>', 'c-exp-confirmer',
        function () { return API.tableau[simple[g]](id); }, 'c-gst-enregistre', reouvrir);
    }
    if (g === 'annuler' || g === 'rejeter') {
      return dialogueGestion('c-exp-g-' + g, 'cc-exp-geste', '<p class="cc-intro">' + e(t('c-exp-conf-' + g, { code: l.code })) + '</p>' +
        champ('c-motif', '<textarea name="motif" rows="2" maxlength="300" required></textarea>'), 'c-exp-confirmer', function (f) {
          var m = String(f.elements.motif.value || '').trim();
          if (!m) return 'c-gst-motif-obligatoire';
          return g === 'annuler' ? API.tableau.annulerExpedition(id, m) : API.tableau.rejeterDouane(id, m);
        }, 'c-gst-enregistre', reouvrir);
    }
    if (g === 'douane') {
      return dialogueGestion('c-exp-g-douane', 'cc-exp-geste', '<p class="cc-intro">' + e(t('c-exp-conf-douane', { code: l.code })) + '</p><div class="cc-form-grille">' +
        champ('c-exp-douane-ref', '<input name="ref" maxlength="80" autocomplete="off">') + champ('c-exp-courtier', '<input name="courtier" maxlength="120" autocomplete="off">', 'c-gst-facultatif') + '</div>',
        'c-exp-confirmer', function (f) { return API.tableau.commencerDouane(id, f.elements.ref.value, f.elements.courtier.value); }, 'c-gst-enregistre', reouvrir);
    }
    if (g === 'droits') {
      return dialogueGestion('c-exp-g-droits', 'cc-exp-geste', '<p class="cc-intro">' + e(t('c-exp-conf-droits')) + '</p><div class="cc-form-grille">' +
        champ('c-exp-montant', '<input name="montant" type="number" inputmode="decimal" min="0" step="0.01" required>') +
        champ('c-exp-devise', choix('devise', DEVISES.map(function (x) { return { valeur: x, libelle: x }; }), '', 'USD')) + '</div>',
        'c-exp-confirmer', function (f) {
          var m = String(f.elements.montant.value || '').trim();
          if (m === '' || !(Number(m) >= 0)) return 'c-exp-montant-obligatoire';
          return API.tableau.fixerDroits(id, m, f.elements.devise.value);
        }, 'c-gst-enregistre', reouvrir);
    }
    if (g === 'liberer') {
      return dialogueGestion('c-exp-g-liberer', 'cc-exp-geste', '<p class="cc-intro">' + e(t('c-exp-conf-liberer', { code: l.code })) + '</p>' +
        champ('c-exp-mainlevee', '<input name="ref" maxlength="80" autocomplete="off">', 'c-gst-facultatif'),
        'c-exp-confirmer', function (f) { return API.tableau.libererDouane(id, f.elements.ref.value); }, 'c-gst-enregistre', reouvrir);
    }
    if (g === 'planifier' || g === 'recevoir') {
      var f = dialogueGestion('c-exp-g-' + g, 'cc-exp-geste', '<p class="cc-intro">' + e(t('c-exp-conf-' + g, { code: l.code })) + '</p><div class="cc-form-grille">' +
        (g === 'planifier' ? champ('c-exp-depart-prevu', '<input name="depart" type="datetime-local" required value="' + e(versLocal(l.depart)) + '">') +
                             champ('c-exp-arrivee-prevue', '<input name="arrivee" type="datetime-local" required value="' + e(versLocal(l.arrivee)) + '">') : '') +
        champ('c-exp-entrepot-hub', '<select name="hub"><option value="">' + e(t('c-gst-chargement')) + '</option></select>', g === 'planifier' ? 'c-gst-facultatif' : 'c-exp-hub-aide') + '</div>',
        'c-exp-confirmer', function (f) {
          if (g === 'recevoir') return API.tableau.recevoirHub(id, f.elements.hub.value || undefined);
          var d = versIso(f.elements.depart.value), a = versIso(f.elements.arrivee.value);
          if (!d || !a) return 'c-exp-dates-obligatoires';
          return API.tableau.planifierExpedition(id, d, a, f.elements.hub.value || undefined);
        }, 'c-gst-enregistre', reouvrir);
      if (f) API.tableau.sites().then(function (d) {
        var hub = agences(d).filter(function (x) { return x.code === l.destination; })[0];
        var w = entrepotsDe(d, hub && hub.branch_id);
        f.elements.hub.innerHTML = '<option value="">' + e(t(g === 'planifier' ? 'c-gst-inchange' : 'c-exp-hub-prevu')) + '</option>' +
          w.map(function (x) { return '<option value="' + e(x.w.warehouse_id) + '"' + (x.w.code === l.hub ? ' selected' : '') + '>' + e(x.w.code + ' · ' + x.w.name) + '</option>'; }).join('');
      });
      return f;
    }
    if (g === 'partir') {
      var fp = dialogueGestion('c-exp-g-partir', 'cc-exp-geste', '<p class="cc-intro">' + e(t('c-exp-conf-partir', { code: l.code })) + '</p>' +
        champ('c-col-transport', '<select name="transport" required><option value="">' + e(t('c-gst-chargement')) + '</option></select>', 'c-exp-transport-aide'),
        'c-exp-confirmer', function (f) {
          if (!f.elements.transport.value) return 'c-exp-transport-obligatoire';
          return API.tableau.partir(id, f.elements.transport.value, f.getAttribute('data-cle'));
        }, 'c-gst-enregistre', reouvrir);
      if (!fp) return;
      fp.setAttribute('data-cle', cleUnique('dep'));
      Promise.all([API.centre.liste('transport', { statut: 'PLANNED', service: l.mode }, { limite: 100, decalage: 0 }),
                   API.centre.liste('transport', { statut: 'DEPARTED', service: l.mode }, { limite: 100, decalage: 0 })]).then(function (r) {
        var tl = ((r[0] && r[0].items) || []).concat((r[1] && r[1].items) || []);
        fp.elements.transport.innerHTML = '<option value="">' + e(t(tl.length ? 'c-gst-choisir' : 'c-exp-aucun-transport')) + '</option>' + tl.map(function (x) {
          var reste = x.capacity_weight_lb ? ' · ' + t('c-exp-capacite-reste', { reste: nombre(Number(x.capacity_weight_lb) - Number(x.load_weight_lb || 0)) }) : '';
          return '<option value="' + e(x.transport_id) + '">' + e([x.reference, x.carrier, x.voyage_number].filter(Boolean).join(' · ') + ' · ' + (x.origin || '') + ' → ' + (x.destination || '') +
            (x.planned_departure_at ? ' · ' + date(x.planned_departure_at) : '') + reste) + '</option>';
        }).join('');
      }, function (err) { fp.elements.transport.innerHTML = '<option value="">' + e(C.message(err)) + '</option>'; });
      return fp;
    }
  };

  /* --- les transports --- */
  C.actions['trans-nouveau'] = function () {
    var f = dialogueGestion('c-trans-g-nouveau', 'cc-trans-nouv', '<p class="cc-intro">' + e(t('c-trans-nouv-intro')) + '</p><div class="cc-form-grille">' +
      champ('c-exp-mode', choix('mode', MODES, 'c-svc-', 'air')) +
      champ('c-trans-compagnie', '<input name="compagnie" maxlength="120" autocomplete="off" required>') +
      champ('c-col-reference', '<input name="reference" maxlength="80" autocomplete="off">', 'c-trans-reference-aide') +
      champ('c-trans-voyage', '<input name="voyage" maxlength="40" autocomplete="off">') +
      champ('c-exp-origine', '<select name="origine" required><option value="">' + e(t('c-gst-chargement')) + '</option></select>') +
      champ('c-exp-destination', '<select name="destination" required><option value="">' + e(t('c-gst-chargement')) + '</option></select>') +
      champ('c-exp-depart-prevu', '<input name="depart" type="datetime-local" required>') + champ('c-exp-arrivee-prevue', '<input name="arrivee" type="datetime-local" required>') +
      champ('c-gst-capacite-lb', '<input name="capacite" type="number" inputmode="decimal" min="1" step="1">', 'c-trans-capacite-aide') +
      champ('c-gst-volume', '<input name="volume" type="number" inputmode="decimal" min="1" step="1">', 'c-gst-facultatif') +
      champ('c-trans-vehicule', '<input name="vehicule" maxlength="80" autocomplete="off">', 'c-gst-facultatif') + '</div>',
      'c-gst-ajouter', function (f) {
        if (!String(f.elements.compagnie.value || '').trim()) return 'c-trans-compagnie-obligatoire';
        if (!String(f.elements.reference.value || '').trim() && !String(f.elements.voyage.value || '').trim()) return 'c-trans-reference-obligatoire';
        if (!f.elements.origine.value || !f.elements.destination.value) return 'c-exp-lieux-obligatoires';
        var d = versIso(f.elements.depart.value), a = versIso(f.elements.arrivee.value);
        if (!d || !a) return 'c-exp-dates-obligatoires';
        return API.tableau.creerTransport({ mode: f.elements.mode.value, compagnie: f.elements.compagnie.value, reference: f.elements.reference.value, voyage: f.elements.voyage.value,
          origine: f.elements.origine.value, destination: f.elements.destination.value, depart: d, arrivee: a, capaciteLb: f.elements.capacite.value, volume: f.elements.volume.value,
          vehicule: f.elements.vehicule.value });
      }, 'c-trans-cree');
    if (!f) return;
    API.tableau.sites().then(function (d) {
      var o = optionsAgences(agences(d)).map(function (x) { return '<option value="' + e(x.valeur) + '">' + e(x.libelle) + '</option>'; }).join('');
      f.elements.origine.innerHTML = '<option value="">' + e(t('c-gst-choisir')) + '</option>' + o;
      f.elements.destination.innerHTML = '<option value="">' + e(t('c-gst-choisir')) + '</option>' + o;
    });
  };
  C.actions['trans-replanifier'] = function (b) {
    var l = ligneDe(b);
    dialogueGestion('c-trans-g-replanifier', 'cc-trans-replan', '<p class="cc-intro">' + e(t('c-trans-replan-intro', { reference: l.reference || '' })) + '</p><div class="cc-form-grille">' +
      champ('c-exp-depart-prevu', '<input name="depart" type="datetime-local" required value="' + e(versLocal(l.depart)) + '">') +
      champ('c-exp-arrivee-prevue', '<input name="arrivee" type="datetime-local" required value="' + e(versLocal(l.arrivee)) + '">') + '</div>',
      'c-gst-enregistrer', function (f) {
        var d = versIso(f.elements.depart.value), a = versIso(f.elements.arrivee.value);
        if (!d || !a) return 'c-exp-dates-obligatoires';
        return API.tableau.replanifierTransport(l.id, d, a);
      }, 'c-gst-enregistre');
  };

  /* ====================================================================== consolidations, unités logistiques, transbordement (005, 016, 026)
     Une consolidation regroupe les colis « à consolider » d'un même pays et d'un même mode ; fermée, elle part seule, ou dans une unité
     logistique (palette, conteneur, ULD aérien, sac) qu'on scelle avant le départ et qu'on n'ouvre qu'avec un motif (inspection). Un colis
     arrivé à un hub qui n'est pas dans son pays y attend son ÉTAPE SUIVANTE (transbordement). Les écrans ne proposent que ce que la base
     acceptera ; elle revérifie chaque geste et dit pourquoi elle refuse. */
  var GENRES_UNITE = ['PALLET', 'CONTAINER', 'ULD', 'BAG'];
  var PAYS_DESTINATION = ['HT', 'DO'];
  var TONS_UNITE = { OPEN: 'PENDING', SEALED: 'ACTIVE', OPENED: 'ON_HOLD' };
  function cocheesDe(f, nom) { return [].slice.call(f.querySelectorAll('input[name=' + nom + ']:checked')).map(function (x) { return x.value; }); }
  function ligneConsolidation(l) { return { id: l.consolidation_id, code: l.code, mode: l.mode, pays: l.destination_country, statut: l.status }; }

  C.actionsConsolidations = function () { return peutExpedier() ? '<div class="cc-barre-actions">' + bouton('cons-nouvelle', 'c-cons-g-nouvelle', null, true) + '</div>' : ''; };
  // L'unité où elle est chargée (étape 026), pour tous ; les gestes, pour qui peut expédier.
  C.colonnesConsolidations = function () {
    var unite = { t: 'c-unite-unite', rendre: function (l) {
      return l.load_unit ? '<span class="ses-mono">' + e(l.load_unit.code) + '</span><br><span class="cc-petit">' + e(t('c-unite-genre-' + l.load_unit.kind)) + '</span>' : '—';
    } };
    if (!peutExpedier()) return [unite];
    return [unite, { t: 'c-gst-col-actions', rendre: function (l) {
      if (!l.consolidation_id) return '';
      var x = ligneConsolidation(l), b = [];
      if (l.status === 'OPEN') b.push(bouton('cons-remplir', 'c-cons-g-remplir', x, true), bouton('cons-fermer', 'c-cons-g-fermer', x));
      if (l.status === 'CLOSED' && !l.load_unit && !l.shipment) b.push(bouton('cons-charger', 'c-cons-g-charger', x));
      if (l.status === 'CLOSED' && l.load_unit && l.load_unit.status !== 'SEALED') {
        b.push(bouton('cons-decharger', 'c-cons-g-decharger', { id: l.consolidation_id, code: l.code, unite: l.load_unit.code }));
      }
      b.push(bouton('cons-colis', 'c-cons-g-colis', x));
      return b.join(' ');
    } }];
  };

  /* --- ouvrir une consolidation, puis la remplir --- */
  C.actions['cons-nouvelle'] = function () {
    var f = dialogueGestion('c-cons-g-nouvelle', 'cc-cons-nouv',
      '<p class="cc-intro">' + e(t('c-cons-nouv-intro')) + '</p><div class="cc-form-grille">' +
      champ('c-site-code', '<input name="code" maxlength="40" autocomplete="off" required value="' + e(codeDuJour('CONS')) + '">') +
      champ('c-exp-entrepot', '<select name="entrepot"><option value="">' + e(t('c-gst-chargement')) + '</option></select>') +
      champ('c-col-destination', choix('pays', PAYS_DESTINATION.map(function (x) { return { valeur: x, libelle: C.pays ? C.pays(x) : x }; }), '', 'HT')) +
      champ('c-exp-mode', choix('mode', MODES, 'c-svc-', 'air')) + '</div>',
      'c-cons-g-ouvrir', function (f) {
        if (!String(f.elements.code.value || '').trim()) return 'c-site-code-obligatoire';
        return API.tableau.ouvrirConsolidation({ code: f.elements.code.value, entrepot: f.elements.entrepot.value || null, pays: f.elements.pays.value, mode: f.elements.mode.value });
      }, 'c-cons-ouverte', function (rep) {
        if (rep && rep.consolidation_id) remplirConsolidation({ id: rep.consolidation_id, code: rep.code, pays: f.elements.pays.value, mode: f.elements.mode.value });
      });
    if (!f) return;
    API.tableau.sites().then(function (d) {
      var l = entrepotsDe(d);
      f.elements.entrepot.innerHTML = '<option value="">—</option>' +
        l.map(function (x) { return '<option value="' + e(x.w.warehouse_id) + '">' + e(x.w.code + ' · ' + x.w.name + ' (' + x.b.code + ')') + '</option>'; }).join('');
    }, function () { f.elements.entrepot.innerHTML = '<option value="">—</option>'; });
  };
  function remplirConsolidation(l) {
    var f = dialogueGestion('c-cons-g-remplir', 'cc-cons-remp',
      '<p class="cc-intro">' + e(t('c-cons-remplir-intro', { code: l.code || '', pays: C.pays ? C.pays(l.pays) : l.pays, mode: t('c-svc-' + l.mode) })) + '</p>' +
      champ('c-exp-prep-numeros', '<textarea name="numeros" rows="4" autocomplete="off" spellcheck="false"></textarea>', 'c-cons-numeros-aide') +
      '<fieldset class="cc-exp-contenu"><legend>' + e(t('c-cons-a-consolider')) + '</legend><div id="cc-cons-prets" aria-live="polite"><p class="cc-petit">' + e(t('c-gst-chargement')) + '</p></div></fieldset>',
      'c-cons-g-ajouter', function (f) {
        var l2 = String(f.elements.numeros.value || '').split(/[\s,;]+/).filter(Boolean).concat(cocheesDe(f, 'numero'));
        if (!l2.length) return 'c-cons-rien-choisi';
        return API.tableau.remplirConsolidation(l.id, l2);
      }, 'c-cons-remplie', function (rep) { resultatsRemplissage(l, rep); });
    if (!f) return;
    var zone = f.querySelector('#cc-cons-prets');
    API.tableau.pret(l.mode).then(function (d) {
      var p = (d.parcels || []).filter(function (x) { return x.destination_country === l.pays; });
      zone.innerHTML = p.length ? '<p class="cc-petit"><button type="button" class="cc-lien" data-tout>' + e(t('c-exp-tout-cocher')) + '</button></p><ul class="cc-exp-choix">' + p.map(function (x) {
        return '<li><label><input type="checkbox" name="numero" value="' + e(x.tracking_number) + '"><span><span class="ses-mono">' + e(x.tracking_number) + '</span> · ' +
          e((x.customer && (x.customer.code || x.customer.name)) || '') + (x.destination_city ? ' · ' + e(x.destination_city) : '') +
          (x.weight_lb !== null && x.weight_lb !== undefined ? ' · ' + e(nombre(x.weight_lb)) + ' lb' : '') + '</span></label></li>';
      }).join('') + '</ul>' : '<p class="cc-petit">' + e(t('c-cons-aucun-pret')) + '</p>';
      var tout = zone.querySelector('[data-tout]');
      if (tout) tout.addEventListener('click', function () { [].slice.call(zone.querySelectorAll('input[name=numero]')).forEach(function (x) { x.checked = true; }); });
    }, function (err) { zone.innerHTML = '<p class="cc-form-msg">' + e(C.message(err)) + '</p>'; });
  }
  function resultatsRemplissage(l, rep) {
    var r = (rep && rep.results) || [], ko = r.filter(function (x) { return !x.added; });
    C.dialogue('c-cons-resultat', '<p class="cc-intro">' + e(t('c-cons-bilan', { ajoutes: nombre(rep && rep.added), total: nombre(r.length), colis: nombre(rep && rep.parcels) })) + '</p>' +
      (ko.length ? '<ul class="cc-site-emplacements">' + ko.map(function (x) {
        return '<li><span class="ses-mono">' + e(x.code) + '</span> · ' + e(t('c-exp-raison-' + x.reason) || x.reason || '') + (x.status ? ' · ' + e(t('c-colis-' + x.status) || x.status) : '') + '</li>';
      }).join('') + '</ul>' : '') +
      '<div class="cc-form-actions">' + bouton('cons-remplir', 'c-cons-g-remplir', { id: l.id, code: l.code, mode: l.mode, pays: l.pays }) + ' ' +
      bouton('cons-fermer', 'c-cons-g-fermer', { id: l.id, code: l.code }, true) + '</div>', 'etroit');
  }
  C.actions['cons-remplir'] = function (b) { remplirConsolidation(ligneDe(b)); };

  /* --- ses colis (et en retirer un tant qu'elle est ouverte) --- */
  function colisConsolidation(l) {
    var zone = C.dialogue('c-cons-colis-titre', '<div id="cc-cons-colis"><p class="cc-petit">' + e(t('c-gst-chargement')) + '</p></div>', 'etroit');
    var cible = zone && zone.querySelector('#cc-cons-colis');
    if (!cible) return;
    API.tableau.colisConsolidation(l.id).then(function (colis) {
      var retirer = peutExpedier() && l.statut === 'OPEN';
      cible.innerHTML = '<p class="cc-intro"><span class="ses-mono">' + e(l.code) + '</span> · ' + e(t('c-exp-n-colis', { n: nombre(colis.length) })) + '</p>' +
        (colis.length ? '<ul class="cc-site-emplacements">' + colis.map(function (c) {
          return '<li><span class="ses-mono">' + e(c.tracking_number) + '</span> · ' + e((c.customer && (c.customer.code || c.customer.name)) || '') +
            (c.weight_lb !== null && c.weight_lb !== undefined ? ' · ' + e(nombre(c.weight_lb)) + ' lb' : '') + ' · ' + pastille('c-colis-' + c.status, c.status) +
            (retirer ? ' ' + bouton('cons-retirer-colis', 'c-cons-g-retirer', { id: l.id, code: l.code, statut: l.statut, colis: c.parcel_id, numero: c.tracking_number }) : '') + '</li>';
        }).join('') + '</ul>' : '<p class="cc-petit">' + e(t('c-cons-vide')) + '</p>');
    }, function (err) { cible.innerHTML = '<p class="cc-form-msg">' + e(C.message(err)) + '</p>'; });
  }
  C.actions['cons-colis'] = function (b) { colisConsolidation(ligneDe(b)); };
  C.actions['cons-retirer-colis'] = function (b) {
    var l = ligneDe(b);
    b.disabled = true;
    API.tableau.retirerDeConsolidation(l.id, l.colis).then(function () {
      C.annoncer(t('c-cons-colis-retire', { numero: l.numero || '' }), 'succes'); C.rafraichir(); colisConsolidation(l);
    }, function (err) { b.disabled = false; C.annoncer(C.message(err), 'erreur'); });
  };

  /* --- fermer : tous ses colis passent « consolidés », ou rien ne se passe --- */
  C.actions['cons-fermer'] = function (b) {
    var l = ligneDe(b), cle = cleUnique('cons');
    dialogueGestion('c-cons-g-fermer', 'cc-cons-ferm', '<p class="cc-intro">' + e(t('c-cons-fermer-intro', { code: l.code || '' })) + '</p>', 'c-exp-confirmer',
      function () { return API.tableau.fermerConsolidation(l.id, cle); }, 'c-cons-fermee');
  };

  /* --- la charger dans une unité, l'en retirer --- */
  function choisirUnite(f, l) {
    API.tableau.unites({ status: 'OPEN' }).then(function (d) {
      var u = ((d && d.items) || []).filter(function (x) {
        return (!x.mode || x.mode === l.mode) && (!x.destination_country || x.destination_country === l.pays) && (!x.shipment || x.shipment.status === 'DRAFT');
      });
      f.elements.unite.innerHTML = '<option value="">' + e(t(u.length ? 'c-gst-choisir' : 'c-cons-aucune-unite')) + '</option>' + u.map(function (x) {
        return '<option value="' + e(x.load_unit_id) + '">' + e(x.code + ' · ' + t('c-unite-genre-' + x.kind) + ' · ' + t('c-exp-n-colis', { n: nombre(x.parcels) }) +
          (x.max_weight_lb ? ' · ' + nombre(x.weight_lb) + ' / ' + nombre(x.max_weight_lb) + ' lb' : '')) + '</option>';
      }).join('');
    }, function (err) { f.elements.unite.innerHTML = '<option value="">' + e(C.message(err)) + '</option>'; });
  }
  C.actions['cons-charger'] = function (b) {
    var l = ligneDe(b);
    var f = dialogueGestion('c-cons-g-charger', 'cc-cons-charg', '<p class="cc-intro">' + e(t('c-cons-charger-intro', { code: l.code || '' })) + '</p>' +
      champ('c-unite-unite', '<select name="unite" required><option value="">' + e(t('c-gst-chargement')) + '</option></select>', 'c-cons-unite-aide'),
      'c-cons-g-charger', function (f) {
        if (!f.elements.unite.value) return 'c-cons-unite-obligatoire';
        return API.tableau.chargerUnite(l.id, f.elements.unite.value);
      }, 'c-cons-chargee');
    if (f) choisirUnite(f, l);
  };
  C.actions['cons-decharger'] = function (b) {
    var l = ligneDe(b);
    dialogueGestion('c-cons-g-decharger', 'cc-cons-dech', '<p class="cc-intro">' + e(t('c-cons-decharger-intro', { code: l.code || '', unite: l.unite || '' })) + '</p>' +
      champ('c-motif', '<textarea name="motif" rows="2" maxlength="300" required></textarea>'), 'c-exp-confirmer', function (f) {
        var m = String(f.elements.motif.value || '').trim();
        if (!m) return 'c-gst-motif-obligatoire';
        return API.tableau.retirerDeUnite(l.id, m);
      }, 'c-gst-enregistre');
  };

  /* --- la section « Unités logistiques » --- */
  function dessinerUnites(zone, d) {
    var gerer = peutExpedier(), l = (d && d.items) || [];
    var compte = {};
    l.forEach(function (x) { compte[x.status] = (compte[x.status] || 0) + 1; });
    zone.innerHTML = '<p class="cc-intro">' + e(t('c-unite-intro')) + '</p>' +
      (gerer ? '<div class="cc-barre-actions">' + bouton('unite-nouvelle', 'c-unite-g-nouvelle', null, true) + '</div>' : '') +
      '<ul class="cc-puces">' + Object.keys(compte).sort().map(function (k) { return '<li><span class="cc-puce">' + e(t('c-unite-' + k)) + ' <strong>' + e(nombre(compte[k])) + '</strong></span></li>'; }).join('') + '</ul>' +
      (l.length ? C.tableau([
        { t: 'c-unite-unite', rendre: function (x) { return '<span class="ses-mono">' + e(x.code) + '</span><br><span class="cc-petit">' + e(t('c-unite-genre-' + x.kind)) + '</span>'; } },
        { t: 'c-col-statut', rendre: function (x) {
          return pastille('c-unite-' + x.status, TONS_UNITE[x.status] || x.status) + (x.seal_number ? '<br><span class="cc-petit">' + e(t('c-unite-scelle-n', { scelle: x.seal_number })) + '</span>' : '') +
            (x.status === 'OPENED' && x.opened_reason ? '<br><span class="cc-petit">' + e(x.opened_reason) + '</span>' : '');
        } },
        { t: 'c-col-destination', rendre: function (x) { return x.mode ? e(t('c-svc-' + x.mode)) + ' · ' + e(C.pays ? C.pays(x.destination_country) : x.destination_country) : '<span class="cc-petit">' + e(t('c-unite-vide')) + '</span>'; } },
        { t: 'c-unite-contenu', rendre: function (x) {
          var retirer = gerer && x.status !== 'SEALED' && (!x.shipment || x.shipment.status === 'DRAFT');
          return (x.consolidations.length ? '<ul class="cc-site-emplacements">' + x.consolidations.map(function (c) {
            return '<li><span class="ses-mono">' + e(c.code) + '</span>' + (retirer ? ' ' + bouton('cons-decharger', 'c-cons-g-retirer', { id: c.consolidation_id, code: c.code, unite: x.code }) : '') + '</li>';
          }).join('') + '</ul>' : '') +
            '<span class="cc-petit">' + e(t('c-exp-n-colis', { n: nombre(x.parcels) })) + ' · ' + e(nombre(x.weight_lb)) + (x.max_weight_lb ? ' / ' + e(nombre(x.max_weight_lb)) : '') + ' lb</span>';
        } },
        { t: 'c-col-expedition', rendre: function (x) { return x.shipment ? '<span class="ses-mono">' + e(x.shipment.code) + '</span> ' + pastille('c-exp-' + x.shipment.status, x.shipment.status) : '<span class="cc-petit">' + e(t('c-pas-expediee')) + '</span>'; } }
      ].concat(gerer ? [{ t: 'c-gst-col-actions', rendre: function (x) {
        var y = { id: x.load_unit_id, code: x.code, mode: x.mode, pays: x.destination_country, statut: x.status }, b = [];
        if (x.status === 'OPEN') b.push(bouton('unite-charger', 'c-unite-g-charger', y, true));
        if (x.status !== 'SEALED' && x.consolidations.length) b.push(bouton('unite-sceller', x.status === 'OPENED' ? 'c-unite-g-resceller' : 'c-unite-g-sceller', y));
        if (x.status === 'SEALED') b.push(bouton('unite-ouvrir', 'c-unite-g-ouvrir', y));
        return b.join(' ');
      } }] : []), l, { legende: 'c-sec-unites' }) : '<p class="cc-rien">' + e(t('c-unite-aucune')) + '</p>');
  }
  function chargerUnites(z, st, ctx, s) { return charger(z, function () { return API.tableau.unites(); }, function (d) { dessinerUnites(z, d); }, s); }

  C.actions['unite-nouvelle'] = function () {
    dialogueGestion('c-unite-g-nouvelle', 'cc-unite-nouv', '<p class="cc-intro">' + e(t('c-unite-nouv-intro')) + '</p><div class="cc-form-grille">' +
      champ('c-site-code', '<input name="code" maxlength="40" autocomplete="off" required value="' + e(codeDuJour('UL')) + '">', 'c-unite-code-aide') +
      champ('c-unite-genre', choix('genre', GENRES_UNITE, 'c-unite-genre-', 'PALLET')) +
      champ('c-unite-poids-max', '<input name="poids" inputmode="decimal" autocomplete="off">', 'c-unite-max-aide') +
      champ('c-unite-volume-max', '<input name="volume" inputmode="decimal" autocomplete="off">', 'c-unite-max-aide') + '</div>',
      'c-gst-ajouter', function (f) {
        if (!String(f.elements.code.value || '').trim()) return 'c-site-code-obligatoire';
        var p = String(f.elements.poids.value || '').trim(), v = String(f.elements.volume.value || '').trim();
        if ((p && !(Number(p.replace(',', '.')) > 0)) || (v && !(Number(v.replace(',', '.')) > 0))) return 'c-unite-max-invalide';
        return API.tableau.creerUnite({ code: f.elements.code.value, genre: f.elements.genre.value, poidsMax: p, volumeMax: v });
      }, 'c-unite-creee');
  };
  C.actions['unite-charger'] = function (b) {
    var l = ligneDe(b);
    var f = dialogueGestion('c-unite-g-charger', 'cc-unite-charg', '<p class="cc-intro">' + e(t('c-unite-charger-intro', { code: l.code || '' })) + '</p>' +
      champ('c-col-consolidation', '<select name="cons" required><option value="">' + e(t('c-gst-chargement')) + '</option></select>', 'c-unite-charger-aide'),
      'c-unite-g-charger', function (f) {
        if (!f.elements.cons.value) return 'c-unite-cons-obligatoire';
        return API.tableau.chargerUnite(f.elements.cons.value, l.id);
      }, 'c-cons-chargee');
    if (!f) return;
    API.tableau.pret(l.mode || undefined).then(function (d) {
      var k = (d.consolidations || []).filter(function (x) { return !l.pays || x.destination_country === l.pays; });
      f.elements.cons.innerHTML = '<option value="">' + e(t(k.length ? 'c-gst-choisir' : 'c-unite-aucune-cons')) + '</option>' + k.map(function (x) {
        return '<option value="' + e(x.consolidation_id) + '">' + e(x.code + ' · ' + t('c-svc-' + x.mode) + ' · ' + (C.pays ? C.pays(x.destination_country) : x.destination_country) + ' · ' +
          t('c-exp-n-colis', { n: nombre(x.parcels) }) + ' · ' + nombre(x.weight_lb) + ' lb') + '</option>';
      }).join('');
    }, function (err) { f.elements.cons.innerHTML = '<option value="">' + e(C.message(err)) + '</option>'; });
  };
  C.actions['unite-sceller'] = function (b) {
    var l = ligneDe(b);
    dialogueGestion(l.statut === 'OPENED' ? 'c-unite-g-resceller' : 'c-unite-g-sceller', 'cc-unite-scel', '<p class="cc-intro">' + e(t('c-unite-sceller-intro', { code: l.code || '' })) + '</p>' +
      champ('c-unite-scelle', '<input name="scelle" maxlength="60" autocomplete="off" required>', 'c-unite-scelle-aide'), 'c-exp-confirmer', function (f) {
        if (!String(f.elements.scelle.value || '').trim()) return 'c-unite-scelle-obligatoire';
        return API.tableau.scellerUnite(l.id, f.elements.scelle.value);
      }, 'c-unite-scellee');
  };
  C.actions['unite-ouvrir'] = function (b) {
    var l = ligneDe(b);
    dialogueGestion('c-unite-g-ouvrir', 'cc-unite-ouv', '<p class="cc-intro">' + e(t('c-unite-ouvrir-intro', { code: l.code || '' })) + '</p>' +
      champ('c-motif', '<textarea name="motif" rows="2" maxlength="300" required></textarea>'), 'c-exp-confirmer', function (f) {
        var m = String(f.elements.motif.value || '').trim();
        if (!m) return 'c-gst-motif-obligatoire';
        return API.tableau.ouvrirUnite(l.id, m);
      }, 'c-gst-enregistre');
  };

  /* --- le transbordement : l'étape suivante, depuis un hub de transit --- */
  C.actions['exp-transbordement'] = function () {
    var attente = [], sites = null;
    var f = dialogueGestion('c-trb-g', 'cc-trb', '<p class="cc-intro">' + e(t('c-trb-intro')) + '</p><div class="cc-form-grille">' +
      champ('c-trb-hub', '<select name="hub" required><option value="">' + e(t('c-gst-chargement')) + '</option></select>') +
      champ('c-exp-destination', '<select name="destination" required><option value="">' + e(t('c-gst-choisir')) + '</option></select>', 'c-trb-destination-aide') +
      champ('c-exp-mode', choix('mode', MODES, 'c-svc-', 'ground')) +
      champ('c-site-code', '<input name="code" maxlength="40" autocomplete="off" required value="' + e(codeExpedition()) + '">') + '</div>' +
      '<fieldset class="cc-exp-contenu"><legend>' + e(t('c-trb-colis')) + '</legend><div id="cc-trb-colis"><p class="cc-petit">—</p></div></fieldset>',
      'c-exp-g-creer', function (f) {
        var colis = cocheesDe(f, 'colis');
        if (!String(f.elements.code.value || '').trim()) return 'c-site-code-obligatoire';
        if (!f.elements.hub.value || !f.elements.destination.value) return 'c-exp-lieux-obligatoires';
        if (!colis.length) return 'c-exp-rien-choisi';
        return API.tableau.etapeSuivante({ code: f.elements.code.value, mode: f.elements.mode.value, origine: f.elements.hub.value, destination: f.elements.destination.value,
                                           colis: colis, cle: f.getAttribute('data-cle') });
      }, 'c-exp-creee', function (rep) { if (rep && rep.shipment_id) ouvrirFiche(rep.shipment_id); });
    if (!f) return;
    f.setAttribute('data-cle', cleUnique('trb'));
    var zone = f.querySelector('#cc-trb-colis');
    function dessinerColis() {
      var hub = f.elements.hub.value, l = attente.filter(function (x) { return x.hub && x.hub.branch_id === hub; });
      zone.innerHTML = l.length ? '<ul class="cc-exp-choix">' + l.map(function (x) {
        return '<li><label><input type="checkbox" name="colis" value="' + e(x.parcel_id) + '" checked><span><span class="ses-mono">' + e(x.tracking_number) + '</span> · ' +
          e((x.customer && (x.customer.code || x.customer.name)) || '') + ' · ' + e([x.destination_city, C.pays ? C.pays(x.destination_country) : x.destination_country].filter(Boolean).join(', ')) +
          ' · ' + e(t('c-trb-arrive-par', { code: (x.from_shipment && x.from_shipment.code) || '' })) + '</span></label></li>';
      }).join('') + '</ul>' : '<p class="cc-petit">—</p>';
      // la destination proposée d'abord : le hub du pays de ces colis
      var pays = l.length ? l[0].destination_country : null;
      var hubs = agences(sites, function (b) { return b.kind === 'hub' && b.branch_id !== hub; });
      hubs.sort(function (a, b) { return (b.country === pays) - (a.country === pays); });
      f.elements.destination.innerHTML = '<option value="">' + e(t(hubs.length ? 'c-gst-choisir' : 'c-exp-aucun-hub')) + '</option>' +
        optionsAgences(hubs).map(function (o, i) { return '<option value="' + e(o.valeur) + '"' + (i === 0 && pays && hubs[0].country === pays ? ' selected' : '') + '>' + e(o.libelle) + '</option>'; }).join('');
    }
    Promise.all([API.tableau.attenteTransbordement(), API.tableau.sites()]).then(function (r) {
      attente = r[0] || []; sites = r[1];
      var parHub = {}, ordre = [];
      attente.forEach(function (x) { var k = x.hub && x.hub.branch_id; if (!k) return; if (!parHub[k]) { parHub[k] = { hub: x.hub, n: 0 }; ordre.push(k); } parHub[k].n++; });
      f.elements.hub.innerHTML = '<option value="">' + e(t(ordre.length ? 'c-gst-choisir' : 'c-trb-rien')) + '</option>' + ordre.map(function (k) {
        return '<option value="' + e(k) + '"' + (ordre.length === 1 ? ' selected' : '') + '>' + e(parHub[k].hub.code + ' · ' + t('c-exp-n-colis', { n: nombre(parHub[k].n) })) + '</option>';
      }).join('');
      f.elements.hub.addEventListener('change', dessinerColis);
      dessinerColis();
    }, function (err) { f.elements.hub.innerHTML = '<option value="">' + e(C.message(err)) + '</option>'; });
  };

  /* ====================================================================== le dernier kilomètre (étapes 006, 017, 025)
     Ce qui attend au HUB se livre de DEUX façons, confirmées par le propriétaire : par un chauffeur (une livraison, puis une mission
     affectée, acceptée dans l'application, mise dans une tournée), ou au COMPTOIR (la personne qui retire, sa pièce : la preuve de la
     remise). Les gestes proposés suivent l'état de la mission ; la base revérifie chacun. */
  var MISSION_OUVERTE = ['CREATED', 'ASSIGNED', 'ACCEPTED', 'STARTED'];
  function aujourdhui() { var d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); }
  function groupesClients(l) {
    var g = {}, ordre = [];
    l.forEach(function (x) { var k = x.customer.customer_id; if (!g[k]) { g[k] = { client: x.customer, colis: [] }; ordre.push(k); } g[k].colis.push(x); });
    return ordre.map(function (k) { return g[k]; });
  }
  function choixColis(groupe) {
    return '<ul class="cc-exp-choix">' + groupe.colis.map(function (x) {
      return '<li><label><input type="checkbox" name="colis" value="' + e(x.parcel_id) + '" checked><span><span class="ses-mono">' + e(x.tracking_number) + '</span>' +
        (x.hub ? ' · ' + e(x.hub.code) : '') + (x.warehouse ? ' · ' + e(x.warehouse) : '') + (x.weight_lb !== null && x.weight_lb !== undefined ? ' · ' + e(nombre(x.weight_lb)) + ' lb' : '') +
        (x.destination_city ? ' · ' + e(x.destination_city) : '') + '</span></label></li>';
    }).join('') + '</ul>';
  }
  /* Un formulaire en deux temps : d'abord le client (ses colis qui attendent), puis ce qu'on fait de ses colis. */
  function formulaireClients(titre, id, intro, champs, bouton, envoyer, succes, preremplir) {
    var groupes = [];
    var f = dialogueGestion(titre, id, '<p class="cc-intro">' + e(t(intro)) + '</p>' +
      champ('c-col-client', '<select name="client" required><option value="">' + e(t('c-gst-chargement')) + '</option></select>', 'c-dk-client-aide') +
      '<fieldset class="cc-exp-contenu"><legend>' + e(t('c-dk-colis-attente')) + '</legend><div id="cc-dk-colis"><p class="cc-petit">—</p></div></fieldset>' + champs,
      bouton, function (f) {
        var g = groupes[Number(f.elements.client.value)];
        var colis = [].slice.call(f.querySelectorAll('input[name=colis]:checked')).map(function (x) { return x.value; });
        if (!g) return 'c-dk-client-obligatoire';
        if (!colis.length) return 'c-exp-rien-choisi';
        return envoyer(f, g, colis);
      }, succes);
    if (!f) return null;
    API.tableau.attenteHub().then(function (l) {
      groupes = groupesClients(l || []);
      f.elements.client.innerHTML = '<option value="">' + e(t(groupes.length ? 'c-gst-choisir' : 'c-dk-rien-au-hub')) + '</option>' + groupes.map(function (g, i) {
        return '<option value="' + i + '">' + e((g.client.code ? g.client.code + ' · ' : '') + (g.client.name || '') + ' (' + t('c-exp-n-colis', { n: nombre(g.colis.length) }) + ')') + '</option>';
      }).join('');
      f.elements.client.addEventListener('change', function () {
        var g = groupes[Number(f.elements.client.value)];
        f.querySelector('#cc-dk-colis').innerHTML = g ? choixColis(g) : '<p class="cc-petit">—</p>';
        if (g && preremplir) preremplir(f, g);
      });
    }, function (err) { f.elements.client.innerHTML = '<option value="">' + e(C.message(err)) + '</option>'; });
    return f;
  }

  C.actionsLivraisons = function () {
    if (!peutExpedier()) return '';
    return '<div class="cc-barre-actions">' + bouton('dk-livraison', 'c-dk-g-livraison', null, true) + bouton('dk-comptoir', 'c-dk-g-comptoir', null) + '</div>';
  };
  /* Les gestes d'une mission de livraison, dans la colonne « Actions » de la liste (après « Traiter » des demandes). */
  C.boutonsLivraison = function (l) {
    if (!peutExpedier() || l.kind !== 'TASK' || !l.ref_id) return '';
    var m = { id: l.ref_id, statut: l.task_status, numero: l.number, jour: l.date }, h = [];
    if (l.task_status === 'CREATED' || l.task_status === 'ASSIGNED') h.push(bouton('dk-affecter', l.task_status === 'CREATED' ? 'c-dk-g-affecter' : 'c-dk-g-reaffecter', m, l.task_status === 'CREATED'));
    if (l.task_status === 'FAILED') h.push(bouton('dk-replanifier', 'c-dk-g-replanifier', m));
    if (MISSION_OUVERTE.indexOf(l.task_status) >= 0) { h.push(bouton('dk-code', 'c-dk-g-code', m)); h.push(bouton('dk-annuler', 'c-dk-g-annuler', m)); }
    return h.length ? '<div class="cc-site-actions">' + h.join('') + '</div>' : '';
  };

  C.actions['dk-livraison'] = function () {
    formulaireClients('c-dk-g-livraison', 'cc-dk-liv', 'c-dk-liv-intro',
      '<div class="cc-form-grille">' + champ('c-dk-destinataire', '<input name="destinataire" maxlength="120" autocomplete="off">') +
      champ('c-gst-telephone', '<input name="telephone" type="tel" maxlength="40" autocomplete="off">') + '</div>' +
      champ('c-col-adresse', '<textarea name="adresse" rows="2" maxlength="300" required></textarea>') +
      '<div class="cc-form-grille">' + champ('c-col-date', '<input name="jour" type="date" required value="' + e(aujourdhui()) + '">') +
      champ('c-dk-hub', '<select name="hub"><option value="">' + e(t('c-dk-hub-du-colis')) + '</option></select>', 'c-dk-hub-aide') + '</div>' +
      '<label class="cc-case"><input type="checkbox" name="code"> <span>' + e(t('c-dk-code-exige')) + '</span></label>',
      'c-dk-g-creer-livraison', function (f, g, colis) {
        var adresse = String(f.elements.adresse.value || '').trim();
        if (!adresse) return 'c-dk-adresse-obligatoire';
        if (!f.elements.jour.value) return 'c-dk-date-obligatoire';
        var choisis = g.colis.filter(function (x) { return colis.indexOf(x.parcel_id) >= 0; });
        var hub = f.elements.hub.value || (choisis[0] && choisis[0].hub && choisis[0].hub.branch_id);
        if (!hub) return 'c-dk-hub-obligatoire';
        return API.tableau.creerLivraison({ colis: colis, hub: hub, jour: f.elements.jour.value, destinataire: f.elements.destinataire.value,
                                            telephone: f.elements.telephone.value, adresse: adresse, code: f.elements.code.checked });
      }, 'c-dk-livraison-creee', function (f, g) {
        f.elements.destinataire.value = g.client.name || '';
        f.elements.telephone.value = g.client.phone || '';
        f.elements.adresse.value = [g.client.address, g.client.city].filter(Boolean).join(', ');
      });
    var f = document.querySelector('#cc-dk-liv');
    if (f) API.tableau.sites().then(function (d) {
      f.elements.hub.insertAdjacentHTML('beforeend', optionsAgences(agences(d, function (b) { return b.kind === 'hub'; })).map(function (o) { return '<option value="' + e(o.valeur) + '">' + e(o.libelle) + '</option>'; }).join(''));
    });
  };
  C.actions['dk-comptoir'] = function () {
    formulaireClients('c-dk-g-comptoir', 'cc-dk-cpt', 'c-dk-cpt-intro',
      '<div class="cc-form-grille">' + champ('c-dk-qui-retire', '<input name="personne" maxlength="200" autocomplete="off" required>') +
      champ('c-dk-piece', '<input name="piece" maxlength="120" autocomplete="off">', 'c-dk-piece-aide') + '</div>' +
      champ('c-dk-note', '<input name="note" maxlength="500" autocomplete="off">', 'c-gst-facultatif'),
      'c-dk-g-remettre', function (f, g, colis) {
        if (!String(f.elements.personne.value || '').trim()) return 'c-dk-personne-obligatoire';
        return API.tableau.remettre(colis, f.elements.personne.value, f.elements.piece.value, f.elements.note.value);
      }, 'c-dk-remis', function (f, g) { if (!f.elements.personne.value) f.elements.personne.value = g.client.name || ''; });
  };
  C.actions['dk-affecter'] = function (b) {
    var l = ligneDe(b);
    var f = dialogueGestion('c-dk-g-affecter', 'cc-dk-aff', '<p class="cc-intro">' + e(t('c-dk-aff-intro', { numero: l.numero || '' })) + '</p>' +
      champ('c-col-chauffeur', '<select name="chauffeur" required><option value="">' + e(t('c-gst-chargement')) + '</option></select>', 'c-dk-aff-aide') +
      '<div id="cc-dk-raisons" class="cc-petit"></div>' +
      champ('c-dk-motif-forcer', '<input name="motif" maxlength="300" autocomplete="off">', 'c-dk-motif-forcer-aide') +
      '<div class="cc-form-actions">' + bouton('dk-auto', 'c-dk-g-auto', l) + '</div>',
      'c-dk-g-affecter', function (f) {
        var o = f.elements.chauffeur.selectedOptions[0];
        if (!f.elements.chauffeur.value) return 'c-dk-chauffeur-obligatoire';
        var forcer = o && o.getAttribute('data-retenu') !== 'oui';
        if (forcer && !String(f.elements.motif.value || '').trim()) return 'c-dk-motif-forcer-obligatoire';
        return API.tableau.affecter(l.id, f.elements.chauffeur.value, forcer, f.elements.motif.value);
      }, 'c-dk-affectee');
    if (!f) return;
    Promise.all([API.tableau.classerChauffeurs(l.id), API.centre.liste('chauffeurs', { statut: 'ACTIVE' }, { limite: 200, decalage: 0 })]).then(function (r) {
      var classes = r[0] || [], noms = {};
      ((r[1] && r[1].items) || []).forEach(function (x) { noms[x.driver_id] = x.name + (x.vehicle ? ' · ' + x.vehicle : ''); });
      classes.sort(function (a, b) { return (b.eligible ? 1 : 0) - (a.eligible ? 1 : 0) || Number(b.score || 0) - Number(a.score || 0); });
      f.elements.chauffeur.innerHTML = '<option value="">' + e(t(classes.length ? 'c-gst-choisir' : 'c-dk-aucun-actif')) + '</option>' + classes.map(function (x) {
        return '<option value="' + e(x.driver_id) + '" data-retenu="' + (x.eligible ? 'oui' : 'non') + '">' + e((noms[x.driver_id] || x.driver_id) + ' · ' + t(x.eligible ? 'c-dk-retenu' : 'c-dk-non-retenu')) + '</option>';
      }).join('');
      f.elements.chauffeur.addEventListener('change', function () {
        var x = classes.filter(function (c) { return c.driver_id === f.elements.chauffeur.value; })[0];
        f.querySelector('#cc-dk-raisons').textContent = x && x.reasons && x.reasons.length ? x.reasons.join(' · ') : '';
      });
    }, function (err) { f.elements.chauffeur.innerHTML = '<option value="">' + e(C.message(err)) + '</option>'; });
  };
  C.actions['dk-auto'] = function (b) {
    var l = ligneDe(b), fin = UI.occuper(b, t('c-envoi'));
    API.tableau.affecterAuto(l.id).then(function () { fin(); C.fermerDialogue(); C.annoncer(t('c-dk-affectee'), 'succes'); C.rafraichir(); },
                                        function (err) { fin(); C.annoncer(C.message(err), 'erreur'); });
  };
  C.actions['dk-code'] = function (b) {
    var l = ligneDe(b);
    dialogueGestion('c-dk-g-code', 'cc-dk-code', '<p class="cc-intro">' + e(t('c-dk-code-intro', { numero: l.numero || '' })) + '</p>', 'c-exp-confirmer',
      function () { return API.tableau.codeLivraison(l.id); }, 'c-dk-code-envoye');
  };
  C.actions['dk-replanifier'] = function (b) {
    var l = ligneDe(b);
    dialogueGestion('c-dk-g-replanifier', 'cc-dk-replan', '<p class="cc-intro">' + e(t('c-dk-replan-intro', { numero: l.numero || '' })) + '</p>' +
      champ('c-col-date', '<input name="jour" type="date" required value="' + e(aujourdhui()) + '">'), 'c-gst-enregistrer', function (f) {
        if (!f.elements.jour.value) return 'c-dk-date-obligatoire';
        return API.tableau.replanifierMission(l.id, f.elements.jour.value);
      }, 'c-gst-enregistre');
  };
  C.actions['dk-annuler'] = function (b) {
    var l = ligneDe(b);
    dialogueGestion('c-dk-g-annuler', 'cc-dk-ann', '<p class="cc-intro">' + e(t('c-dk-annuler-intro', { numero: l.numero || '' })) + '</p>' +
      champ('c-motif', '<textarea name="motif" rows="2" maxlength="300" required></textarea>'), 'c-exp-confirmer', function (f) {
        var m = String(f.elements.motif.value || '').trim();
        if (!m) return 'c-gst-motif-obligatoire';
        return API.tableau.annulerMission(l.id, m);
      }, 'c-gst-enregistre');
  };

  /* --- les tournées --- */
  C.actions['trip-nouvelle'] = function () {
    var missions = [];
    var f = dialogueGestion('c-dk-g-tournee', 'cc-trip-nouv', '<p class="cc-intro">' + e(t('c-dk-trip-intro')) + '</p><div class="cc-form-grille">' +
      champ('c-col-chauffeur', '<select name="chauffeur" required><option value="">' + e(t('c-gst-chargement')) + '</option></select>') +
      champ('c-col-date', '<input name="jour" type="date" required value="' + e(aujourdhui()) + '">') + '</div>' +
      '<fieldset class="cc-exp-contenu"><legend>' + e(t('c-dk-missions-acceptees')) + '</legend><div id="cc-trip-missions"><p class="cc-petit">—</p></div></fieldset>',
      'c-dk-g-creer-tournee', function (f) {
        var ids = [].slice.call(f.querySelectorAll('input[name=mission]:checked')).map(function (x) { return x.value; });
        if (!f.elements.chauffeur.value) return 'c-dk-chauffeur-obligatoire';
        if (!ids.length) return 'c-dk-mission-obligatoire';
        return API.tableau.creerTournee(f.elements.chauffeur.value, f.elements.jour.value, ids);
      }, 'c-dk-tournee-creee');
    if (!f) return;
    var zone = f.querySelector('#cc-trip-missions');
    function charger() {
      if (!f.elements.chauffeur.value || !f.elements.jour.value) { zone.innerHTML = '<p class="cc-petit">—</p>'; return; }
      API.tableau.missionsDuJour(f.elements.jour.value).then(function (l) {
        missions = (l || []).filter(function (x) { return x.driver_id === f.elements.chauffeur.value && x.status === 'ACCEPTED' && !x.trip_id; });
        zone.innerHTML = missions.length ? '<ul class="cc-exp-choix">' + missions.map(function (x) {
          return '<li><label><input type="checkbox" name="mission" value="' + e(x.task_id) + '" checked><span>' + e(t(x.kind === 'PICKUP' ? 'c-dk-enlevement' : 'c-dk-livraison')) + ' · ' + e(x.address || '') +
            (x.weight_lb ? ' · ' + e(nombre(x.weight_lb)) + ' lb' : '') + '</span></label></li>';
        }).join('') + '</ul>' : '<p class="cc-petit">' + e(t('c-dk-aucune-acceptee')) + '</p>';
      }, function (err) { zone.innerHTML = '<p class="cc-form-msg">' + e(C.message(err)) + '</p>'; });
    }
    f.elements.chauffeur.addEventListener('change', charger);
    f.elements.jour.addEventListener('change', charger);
    API.centre.liste('chauffeurs', { statut: 'ACTIVE' }, { limite: 200, decalage: 0 }).then(function (d) {
      var l = (d && d.items) || [];
      f.elements.chauffeur.innerHTML = '<option value="">' + e(t(l.length ? 'c-gst-choisir' : 'c-dk-aucun-actif')) + '</option>' +
        l.map(function (x) { return '<option value="' + e(x.driver_id) + '">' + e(x.name + (x.vehicle ? ' · ' + x.vehicle : '')) + '</option>'; }).join('');
    });
  };
  C.actions['trip-annuler'] = function (b) {
    var l = ligneDe(b);
    dialogueGestion('c-dk-g-annuler-tournee', 'cc-trip-ann', '<p class="cc-intro">' + e(t('c-dk-annuler-tournee-intro', { chauffeur: l.chauffeur || '' })) + '</p>' +
      champ('c-motif', '<textarea name="motif" rows="2" maxlength="300" required></textarea>'), 'c-exp-confirmer', function (f) {
        var m = String(f.elements.motif.value || '').trim();
        if (!m) return 'c-gst-motif-obligatoire';
        return API.tableau.annulerTournee(l.id, m);
      }, 'c-gst-enregistre');
  };

  if (C.enregistrer) {
    var avecBase = function (m, repli) { return function (acces) { var x = module(m); return x === null ? !!repli(acces || {}) : x; }; };
    C.enregistrer({ id: 'temps-reel', ordre: 1, filtres: [], ouvrir: avecBase('commande', function (a) { return a.ops || a.finance || a.customers || a.direction; }),
                    rendre: function (z, st, ctx) { chargerCartes(z, st, ctx, false); }, actualiser: chargerCartes });
    C.enregistrer({ id: 'vehicules', ordre: 92, filtres: [], ouvrir: avecBase('vehicules', function (a) { return a.ops; }),
                    rendre: function (z) { charger(z, function () { return API.tableau.vehicules(); }, function (d) { dessinerVehicules(z, d); }); },
                    actualiser: function (z, st, ctx, s) { return charger(z, function () { return API.tableau.vehicules(); }, function (d) { dessinerVehicules(z, d); }, s); } });
    C.enregistrer({ id: 'unites', ordre: 51, filtres: [], ouvrir: avecBase('consolidations', function (a) { return a.ops || a.direction; }),
                    rendre: function (z, st, ctx) { chargerUnites(z, st, ctx, false); }, actualiser: chargerUnites });
    C.enregistrer({ id: 'sites', ordre: 41, filtres: [], ouvrir: avecBase('entrepots', function (a) { return a.ops || a.direction; }),
                    rendre: function (z, st, ctx) { chargerSites(z, st, ctx, false); }, actualiser: chargerSites });
    C.enregistrer({ id: 'tournees', ordre: 93, filtres: [], ouvrir: avecBase('tournees', function (a) { return a.ops || a.driver; }),
                    rendre: function (z) { charger(z, function () { return API.tableau.tournees(); }, function (d) { dessinerTournees(z, d); }); },
                    actualiser: function (z, st, ctx, s) { return charger(z, function () { return API.tableau.tournees(); }, function (d) { dessinerTournees(z, d); }, s); } });
    C.enregistrer({ id: 'depenses', ordre: 165, filtres: [], ouvrir: avecBase('depenses', function (a) { return a.finance; }),
                    rendre: function (z, st) { z.innerHTML = '<p class="cc-intro">' + e(t('c-dep-intro')) + '</p>' + formDepenses(st) + '<div id="cc-dep-resultat" aria-live="polite"></div>'; chargerDepenses(z, st); },
                    actualiser: function (z, st, ctx, s) { return chargerDepenses(z, st, s); } });
    C.enregistrer({ id: 'pointage', ordre: 190, filtres: [], ouvrir: avecBase('pointage', function () { return true; }),
                    rendre: function (z, st, ctx) { z.innerHTML = ''; rendrePointage(z, st, ctx); }, actualiser: function (z, st, ctx, s) { return rendrePointage(z, st, ctx, s); },
                    clic: clicPointage, quitter: function () { etatPt.session = null; } });
    C.enregistrer({ id: 'mes-missions', ordre: 96, filtres: [], ouvrir: function (acces) { var a = accesTableau(); return !!((acces && acces.driver) || (a && a.driver)); },
                    rendre: function (z) { charger(z, function () { return API.tableau.mesMissions(); }, function (l) { dessinerMissions(z, l); }); },
                    actualiser: function (z, st, ctx, s) { return charger(z, function () { return API.tableau.mesMissions(); }, function (l) { dessinerMissions(z, l); }, s); } });
    // Les formulaires du pointage : le centre écoute déjà « submit » pour ses filtres (celui des dépenses en est un) ; on passe avant lui.
    document.addEventListener('submit', function (ev) {
      if (ev.target.closest && ev.target.closest('#cc-racine') && soumettrePointage(ev)) ev.stopPropagation();
    }, true);
  }

  C.modulesVues = { dessinerSites: dessinerSites, dessinerUnites: dessinerUnites, dessinerCartes: dessinerCartes, dessinerVehicules: dessinerVehicules, dessinerTournees: dessinerTournees, dessinerDepenses: dessinerDepenses,
                    dessinerPersonnel: dessinerPersonnel, dessinerReleve: dessinerReleve, dessinerColis: dessinerColis, dessinerSession: dessinerSession, dessinerMissions: dessinerMissions };
})();
