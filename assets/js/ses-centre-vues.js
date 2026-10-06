/* ==========================================================================
   Speed Express Shipping — le centre de commande : les sections
   --------------------------------------------------------------------------
   Chaque section est une DÉFINITION (colonnes, filtres, statuts), pas un
   programme : le socle (ses-centre.js) sait charger, filtrer, paginer, dire
   « chargement / vide / erreur ». Ici, on dit seulement quoi montrer.

   Aucune règle métier, aucune statistique : les noms de statut viennent de la
   base (et sont traduits), les totaux, les retards et les soldes aussi. Les
   fiches (colis, ticket) et le traitement des demandes passent par
   SES_API.centre ; le serveur contrôle les droits de chaque action.
   ========================================================================== */
(function () {
  'use strict';

  var C = window.SES_CENTRE;
  var API = window.SES_API;
  var UI = window.SES_UI;
  if (!C || !API || !API.centre) return;

  var t = C.t;
  var e = C.e;

  /* Les statuts que chaque liste propose en filtre : écrits ici seulement pour l'ORDRE d'affichage ; le test (centre-contrat.cjs) vérifie qu'ils
     existent tous dans la base et qu'aucun statut de la base n'est resté sans nom. */
  var STATUTS_COLIS = ['CREATED', 'RECEIVED', 'VERIFIED', 'STORED', 'CONSOLIDATION_PENDING', 'CONSOLIDATED', 'READY_FOR_EXPORT', 'IN_TRANSIT', 'ARRIVED', 'CUSTOMS_PROCESSING', 'CUSTOMS_CLEARED',
                       'AT_DESTINATION_HUB', 'DELIVERY_ASSIGNED', 'OUT_FOR_DELIVERY', 'DELIVERED', 'ON_HOLD', 'DAMAGED', 'LOST', 'CANCELLED', 'RETURNED'];
  var STATUTS_EXPEDITION = ['DRAFT', 'READY', 'DISPATCHED', 'IN_TRANSIT', 'ARRIVED', 'CUSTOMS_PROCESSING', 'CUSTOMS_CLEARED', 'AT_HUB', 'CLOSED', 'CANCELLED'];
  var STATUTS_TRANSPORT = ['PLANNED', 'DEPARTED', 'ARRIVED', 'CANCELLED'];
  var STATUTS_DOUANE = ['DRAFT', 'SUBMITTED', 'UNDER_REVIEW', 'CLEARED', 'REJECTED'];
  var STATUTS_INCIDENT = ['OPEN', 'IN_PROGRESS', 'RESOLVED', 'CANCELLED'];
  var STATUTS_FACTURE = ['ISSUED', 'PARTIALLY_PAID', 'PAID', 'OVERDUE', 'CANCELLED', 'REFUNDED'];
  var STATUTS_TICKET = ['OPEN', 'ANSWERED', 'CLOSED'];
  var STATUTS_NOTIF = ['PENDING', 'SENT', 'FAILED'];
  var ETAPES_DEMANDE = ['requested', 'scheduled', 'on_the_way', 'completed', 'missed', 'rejected', 'cancelled'];
  var ETAPES_LIVRAISON = ['requested', 'scheduled', 'on_the_way', 'delivered', 'missed', 'rejected', 'cancelled'];
  var ROLES = ['admin', 'manager', 'employee'];

  function s(v) { return v === null || v === undefined || v === '' ? '—' : e(v); }
  function mono(v) { return '<span class="ses-mono">' + s(v) + '</span>'; }
  function client(l) { return l.customer_code ? '<span class="cc-client"><strong>' + s(l.customer_name) + '</strong><span class="ses-mono cc-petit">' + e(l.customer_code) + '</span></span>' : '—'; }
  function service(m) { return m ? e(t('c-svc-' + m)) : '—'; }
  function lieu(ville, pays) { return [ville, pays ? C.pays(pays) : ''].filter(Boolean).map(e).join(', ') || '—'; }
  function poids(v) { return v === null || v === undefined ? '—' : e(C.nombre(v)) + ' lb'; }
  function lienColis(numero) { return numero ? '<button type="button" class="cc-lien ses-mono" data-act="colis" data-numero="' + e(numero) + '">' + e(numero) + '</button>' : '—'; }
  function pastille(prefixe, code) { return code ? C.pastille(prefixe + code, code) : '—'; }
  function deuxLignes(haut, bas) { return '<span class="cc-deux"><span>' + haut + '</span><span class="cc-petit">' + bas + '</span></span>'; }
  function badgeRetard(retard) { return retard ? ' <span class="ses-pastille ses-pastille-bad">' + e(t('c-retard')) + '</span>' : ''; }
  function montantDe(l) { return l.amount === null || l.amount === undefined ? '—' : C.montant(l.amount, l.currency); }

  /* ======================================================================
     Le centre de commande : chiffres du jour, ce qui attend l'équipe, le flux
     ====================================================================== */
  // [clé de l'indicateur, section vers laquelle il renvoie, filtres du lien]
  var CARTES = {
    colis: { t: 'c-kpi-grp-colis', bloc: 'operations', cartes: [
      ['parcels_received_today', null], ['parcels_in_warehouse', 'entrepot'], ['parcels_at_hub', 'colis', { statut: 'AT_DESTINATION_HUB' }], ['parcels_on_hold', 'colis', { statut: 'ON_HOLD' }]] },
    expeditions: { t: 'c-kpi-grp-expeditions', bloc: 'operations', cartes: [
      ['consolidations_open', 'consolidations', { statut: 'OPEN' }], ['shipments_ready', 'expeditions', { statut: 'READY' }], ['shipments_in_transit', 'expeditions', { statut: 'IN_TRANSIT' }], ['shipments_customs', 'douane']] },
    livraisons: { t: 'c-kpi-grp-livraisons', bloc: 'operations', cartes: [
      ['deliveries_today', 'livraisons', { du: 'AUJOURDHUI', au: 'AUJOURDHUI' }], ['deliveries_in_progress', 'livraisons', { statut: 'on_the_way' }], ['deliveries_delayed', 'livraisons']] },
    alertes: { t: 'c-kpi-grp-alertes', bloc: 'operations', cartes: [
      ['incidents_open', 'incidents', { statut: 'ACTIVE' }], ['incidents_high', 'incidents', { statut: 'ACTIVE' }], ['pickup_requests_pending', 'enlevements', { statut: 'requested' }],
      ['delivery_requests_pending', 'livraisons', { statut: 'requested' }]] },
    support: { t: 'c-kpi-grp-support', bloc: 'support', cartes: [['tickets_open', 'support', { statut: 'ACTIVE' }], ['tickets_waiting_staff', 'support', { statut: 'OPEN' }]] }
  };
  // Les filtres de l'écran d'accueil qui suivent le lien d'un chiffre vers sa liste (ceux que la liste sait appliquer)
  var FILTRES_TRANSMIS = ['pays', 'ville', 'entrepot', 'service', 'client', 'du', 'au'];

  function carte(cle, valeur, cible, filtres, accueil, jour) {
    var f = {};
    if (cible) {
      var vue = C.vues.filter(function (v) { return v.id === cible; })[0];
      Object.keys(filtres || {}).forEach(function (k) { f[k] = filtres[k] === 'AUJOURDHUI' ? jour : filtres[k]; });
      FILTRES_TRANSMIS.forEach(function (k) {
        if (accueil[k] && vue && (vue.filtres || []).indexOf(k) >= 0 && !f[k] && !(k === 'du' || k === 'au')) f[k] = accueil[k];
      });
    }
    var href = cible ? C.lien(cible, f) : '';
    var corps = '<span class="cc-kpi-etiquette">' + e(t('c-kpi-' + cle)) + '</span><strong class="cc-kpi-valeur">' + e(C.nombre(valeur)) + '</strong>';
    return '<li>' + (href ? '<a class="cc-kpi cc-kpi-lien" href="' + e(href) + '">' + corps + '</a>' : '<div class="cc-kpi">' + corps + '</div>') + '</li>';
  }

  function dessinerAccueil(zone, donnees, st) {
    var k = donnees.kpis, att = donnees.att, flux = donnees.flux;
    var jour = k.today;
    var html = '';
    if (st.filtres.du || st.filtres.au) html += '<p class="cc-note" role="note">' + e(t('c-note-periode')) + '</p>';
    var blocs = {operations: k.operations, support: k.support};
    Object.keys(CARTES).forEach(function (g) {
      var def = CARTES[g], valeurs = blocs[def.bloc];
      if (!valeurs) return;
      html += '<section class="cc-groupe" aria-labelledby="cc-g-' + g + '"><h3 id="cc-g-' + g + '">' + e(t(def.t)) + '</h3><ul class="cc-kpis">' +
        def.cartes.map(function (c) { return carte(c[0], valeurs[c[0]], c[1], c[2], st.filtres, jour); }).join('') + '</ul></section>';
    });
    if (k.money) {
      var m = k.money;
      var cartesArgent = [
        '<li><div class="cc-kpi"><span class="cc-kpi-etiquette">' + e(t('c-kpi-revenue_today_usd')) + '</span><strong class="cc-kpi-valeur">' + e(C.montant(m.revenue_today_usd, 'USD')) + '</strong><span class="cc-petit">' + e(t('c-date-comptable', { date: C.jour(m.revenue_date) })) + '</span></div></li>',
        '<li><div class="cc-kpi"><span class="cc-kpi-etiquette">' + e(t('c-kpi-revenue_month_usd')) + '</span><strong class="cc-kpi-valeur">' + e(C.montant(m.revenue_month_usd, 'USD')) + '</strong></div></li>'];
      if (m.revenue_period_usd !== undefined) cartesArgent.push('<li><div class="cc-kpi"><span class="cc-kpi-etiquette">' + e(t('c-kpi-revenue_period_usd')) + '</span><strong class="cc-kpi-valeur">' + e(C.montant(m.revenue_period_usd, 'USD')) + '</strong></div></li>');
      (m.unpaid || []).forEach(function (u) {
        var href = C.lien('facturation', { statut: 'UNPAID' });
        var corps = '<span class="cc-kpi-etiquette">' + e(t('c-kpi-unpaid', { devise: u.currency })) + '</span><strong class="cc-kpi-valeur">' + e(C.montant(u.balance, u.currency)) + '</strong><span class="cc-petit">' + e(t('c-kpi-unpaid-detail', { factures: C.nombre(u.invoices), clients: C.nombre(u.customers) })) + '</span>';
        cartesArgent.push('<li>' + (href ? '<a class="cc-kpi cc-kpi-lien" href="' + e(href) + '">' + corps + '</a>' : '<div class="cc-kpi">' + corps + '</div>') + '</li>');
      });
      var hrefR = C.lien('facturation', { statut: 'OVERDUE' });
      var corpsR = '<span class="cc-kpi-etiquette">' + e(t('c-kpi-overdue_invoices')) + '</span><strong class="cc-kpi-valeur">' + e(C.nombre(m.overdue_invoices)) + '</strong>';
      cartesArgent.push('<li>' + (hrefR ? '<a class="cc-kpi cc-kpi-lien" href="' + e(hrefR) + '">' + corpsR + '</a>' : '<div class="cc-kpi">' + corpsR + '</div>') + '</li>');
      html += '<section class="cc-groupe" aria-labelledby="cc-g-argent"><h3 id="cc-g-argent">' + e(t('c-kpi-grp-argent')) + '</h3><ul class="cc-kpis">' + cartesArgent.join('') + '</ul></section>';
    }
    html += attente(att);
    if (flux) html += apercuFlux(flux);
    zone.innerHTML = html;
  }

  /* Ce qui attend l'équipe, du plus pressé au moins pressé tel que la base le range, avec depuis quand ça attend. */
  var CIBLES_ATTENTE = {
    pickup_requests: ['enlevements', { statut: 'requested' }], delivery_requests: ['livraisons', { statut: 'requested' }], deliveries_delayed: ['livraisons'],
    incidents_high: ['incidents', { statut: 'ACTIVE' }], parcels_on_hold: ['colis', { statut: 'ON_HOLD' }], shipments_late: ['transport'],
    tickets_waiting: ['support', { statut: 'OPEN' }], invoices_overdue: ['facturation', { statut: 'OVERDUE' }]
  };
  function attente(att) {
    var items = (att && att.items) || [];
    var corps = items.length ? '<ul class="cc-attente">' + items.map(function (i) {
      var c = CIBLES_ATTENTE[i.kind] || [];
      var href = c[0] ? C.lien(c[0], c[1]) : '';
      var txt = '<span class="cc-attente-n">' + e(C.nombre(i.count)) + '</span><span class="cc-attente-t">' + e(t('c-att-' + i.kind)) + '</span><span class="cc-petit">' + e(t('c-att-depuis', { age: C.age(i.oldest_at) })) + '</span>';
      return '<li>' + (href ? '<a class="cc-attente-lien" href="' + e(href) + '">' + txt + '</a>' : '<div class="cc-attente-lien">' + txt + '</div>') + '</li>';
    }).join('') + '</ul>' : '<p class="cc-rien">' + e(t('c-att-rien')) + '</p>';
    return '<section class="cc-groupe" aria-labelledby="cc-g-att"><h3 id="cc-g-att">' + e(t('c-att-titre')) + '</h3>' + corps + '</section>';
  }

  function apercuFlux(flux) {
    var items = flux.items || [];
    var lien = C.lien('flux', {});
    return '<section class="cc-groupe" aria-labelledby="cc-g-flux"><div class="cc-groupe-entete"><h3 id="cc-g-flux">' + e(t('c-flux-titre')) + '</h3>' +
      (lien ? '<a href="' + e(lien) + '" class="cc-voir-tout">' + e(t('c-voir-tout')) + '</a>' : '') + '</div>' +
      (items.length ? C.tableau(COLONNES_FLUX, items, { cleLigne: function (l) { return l.shipment; }, legende: 'c-sec-flux' }) : '<p class="cc-rien">' + e(t('c-flux-vide')) + '</p>') + '</section>';
  }

  function chargerAccueil(zone, st, ctx, silencieux) {
    var acces = C.acces() || { sections: [] };
    var avecFlux = C.peutOuvrir('flux');
    var racine = zone;
    if (!racine._pret || racine._pret !== JSON.stringify(st.filtres)) {
      racine.innerHTML = C.barreFiltres(DEF_ACCUEIL, st.filtres) + '<div id="cc-accueil" aria-live="polite"></div>';
      racine._pret = JSON.stringify(st.filtres);
    }
    var cible = racine.querySelector('#cc-accueil');
    return C.charger(cible, function () {
      return Promise.all([API.centre.indicateurs(st.filtres), API.centre.aTraiter(), avecFlux ? API.centre.liste('flux', st.filtres, { limite: 8, decalage: 0 }) : Promise.resolve(null)])
        .then(function (r) { return { kpis: r[0], att: r[1], flux: r[2] }; });
    }, function (donnees) { dessinerAccueil(cible, donnees, st); }, { silencieux: silencieux });
  }

  var DEF_ACCUEIL = { id: 'commande', filtres: ['pays', 'ville', 'entrepot', 'service', 'client', 'du', 'au'] };
  C.enregistrer({
    id: 'commande', ordre: 0, filtres: DEF_ACCUEIL.filtres,
    rendre: function (zone, st, ctx) { zone._pret = null; chargerAccueil(zone, st, ctx, false); },
    actualiser: function (zone, st, ctx, silencieux) { return chargerAccueil(zone, st, ctx, silencieux); }
  });

  /* ======================================================================
     Flux : expédition → transport → hub → livraison → chauffeur
     ====================================================================== */
  function colisParStatut(p) {
    var par = (p && p.by_status) || {};
    var cles = Object.keys(par).sort();
    return cles.length ? '<span class="cc-petit">' + cles.map(function (k) { return e(t('c-colis-' + k)) + ' ' + e(C.nombre(par[k])); }).join(' · ') + '</span>' : '';
  }
  var COLONNES_FLUX = [
    { t: 'c-col-expedition', rendre: function (l) { return deuxLignes(mono(l.shipment), service(l.mode)); } },
    { t: 'c-col-statut', rendre: function (l) { return pastille('c-exp-', l.status); } },
    { t: 'c-col-transport', rendre: function (l) {
      if (!l.transport) return '<span class="cc-petit">' + e(t('c-pas-de-transport')) + '</span>';
      var x = l.transport;
      return deuxLignes(s(x.reference) + ' · ' + s(x.carrier), pastille('c-trans-', x.status) + ' ' + (x.arrived_at ? e(t('c-arrive-le', { date: C.date(x.arrived_at) })) : (x.planned_arrival_at ? e(t('c-arrivee-prevue', { date: C.date(x.planned_arrival_at) })) : '')));
    } },
    { t: 'c-col-hub', rendre: function (l) { return deuxLignes(s(l.hub), l.country ? e(C.pays(l.country)) : '—'); } },
    { t: 'c-col-colis', rendre: function (l) { return deuxLignes(e(C.nombre(l.parcels.total)), colisParStatut(l.parcels)); } },
    { t: 'c-col-livraisons', rendre: function (l) {
      var d = l.deliveries || [];
      if (!d.length) return '<span class="cc-petit">' + e(t('c-aucune')) + '</span>';
      return '<ul class="cc-sous-liste">' + d.map(function (x) {
        return '<li>' + e(t('c-livraison-ligne', { colis: C.nombre(x.parcels), date: C.jour(x.scheduled_date) })) + ' · ' + e(x.driver || t('c-sans-chauffeur')) + ' ' + C.pastille('c-miss-' + x.status, x.status) + '</li>';
      }).join('') + '</ul>';
    } },
    { t: 'c-col-cree', rendre: function (l) { return e(C.date(l.created_at)); } }
  ];
  C.enregistrer({
    id: 'flux', ordre: 10, vue: 'flux', filtres: ['statut', 'pays', 'service', 'ville', 'entrepot', 'client', 'du', 'au'],
    statuts: ['ACTIVE'].concat(STATUTS_EXPEDITION.filter(function (x) { return x !== 'DRAFT' && x !== 'CANCELLED'; })), prefixeStatut: 'c-exp-', intro: 'c-flux-intro',
    colonnes: COLONNES_FLUX, cle: function (l) { return l.shipment; }
  });

  /* ======================================================================
     Colis
     ====================================================================== */
  C.enregistrer({
    id: 'colis', ordre: 20, vue: 'colis', filtres: ['statut', 'pays', 'service', 'ville', 'entrepot', 'client', 'du', 'au'], statuts: STATUTS_COLIS, prefixeStatut: 'c-colis-',
    colonnes: [
      { t: 'c-col-numero', rendre: function (l) { return lienColis(l.tracking_number); } },
      { t: 'c-col-client', rendre: client },
      { t: 'c-col-destination', rendre: function (l) { return lieu(l.destination_city, l.destination_country); } },
      { t: 'c-col-service', rendre: function (l) { return service(l.service_mode); } },
      { t: 'c-col-statut', rendre: function (l) { return pastille('c-colis-', l.status) + (l.prohibited ? ' <span class="ses-pastille ses-pastille-bad">' + e(t('c-interdit')) + '</span>' : ''); } },
      { t: 'c-col-ou', rendre: function (l) { return l.warehouse ? deuxLignes(s(l.warehouse), l.location ? mono(l.location) : '—') : '—'; } },
      { t: 'c-col-poids', rendre: function (l) { return poids(l.weight_lb); } },
      { t: 'c-col-maj', rendre: function (l) { return e(C.date(l.updated_at)); } }
    ], cle: function (l) { return l.tracking_number; }
  });

  /* ======================================================================
     Expéditions
     ====================================================================== */
  C.enregistrer({
    id: 'expeditions', ordre: 30, vue: 'expeditions', filtres: ['statut', 'pays', 'service', 'ville', 'entrepot', 'client', 'du', 'au'], statuts: STATUTS_EXPEDITION, prefixeStatut: 'c-exp-',
    colonnes: [
      { t: 'c-col-expedition', rendre: function (l) { return deuxLignes(mono(l.code), service(l.mode)); } },
      { t: 'c-col-statut', rendre: function (l) { return pastille('c-exp-', l.status); } },
      { t: 'c-col-trajet', rendre: function (l) { return deuxLignes(s(l.origin), '→ ' + s(l.destination)); } },
      { t: 'c-col-transport', rendre: function (l) { return s(l.transport); } },
      { t: 'c-col-colis', rendre: function (l) { return deuxLignes(e(C.nombre(l.parcels)), poids(l.weight_lb)); } },
      { t: 'c-col-depart', rendre: function (l) { return e(C.date(l.dispatched_at)); } },
      { t: 'c-col-arrivee', rendre: function (l) { return e(C.date(l.arrived_at)); } }
    ], cle: function (l) { return l.code; }
  });

  /* ======================================================================
     Entrepôt (une vue en cartes, pas une liste paginée)
     ====================================================================== */
  function dessinerEntrepot(zone, d) {
    var ws = d.warehouses || [];
    var html = ws.length ? '<ul class="cc-cartes">' + ws.map(function (w) {
      var par = Object.keys(w.by_status || {}).sort();
      return '<li class="cc-carte"><h3>' + e(w.code) + ' — ' + e(w.name) + '</h3><p class="cc-petit">' + s(w.branch) + '</p><dl class="cc-dl">' +
        '<dt>' + e(t('c-ent-colis')) + '</dt><dd>' + e(C.nombre(w.parcels)) + '</dd>' +
        '<dt>' + e(t('c-ent-recus')) + '</dt><dd>' + e(C.nombre(w.received_today)) + '</dd>' +
        '<dt>' + e(t('c-ent-scans')) + '</dt><dd>' + e(C.nombre(w.scans_today)) + ' (' + e(t('c-ent-refuses', { nombre: C.nombre(w.scans_rejected_today) })) + ')</dd>' +
        '<dt>' + e(t('c-ent-incidents')) + '</dt><dd>' + e(C.nombre(w.open_incidents)) + '</dd>' +
        '<dt>' + e(t('c-ent-emplacements')) + '</dt><dd>' + e(C.nombre(w.locations)) + '</dd></dl>' +
        (par.length ? '<p class="cc-petit">' + par.map(function (k) { return e(t('c-colis-' + k)) + ' ' + e(C.nombre(w.by_status[k])); }).join(' · ') + '</p>' : '') + '</li>';
    }).join('') + '</ul>' : UI.vide(t('c-ent-vide'), '▢');
    var scans = d.recent_scans || [];
    html += '<h3 class="cc-sous-titre">' + e(t('c-ent-derniers-scans')) + '</h3>' + (scans.length ? C.tableau([
      { t: 'c-col-date', rendre: function (l) { return e(C.date(l.at)); } }, { t: 'c-col-code', rendre: function (l) { return mono(l.code); } },
      { t: 'c-col-but', rendre: function (l) { return e(t('c-but-' + l.purpose)); } }, { t: 'c-col-resultat', rendre: function (l) { return C.pastille('c-scan-' + l.result, l.result === 'ACCEPTED' ? 'SENT' : 'FAILED'); } },
      { t: 'c-col-entrepot', rendre: function (l) { return s(l.warehouse); } }], scans, { legende: 'c-ent-derniers-scans' }) : '<p class="cc-rien">' + e(t('c-ent-aucun-scan')) + '</p>');
    zone.innerHTML = html;
  }
  function chargerEntrepot(zone, st, ctx, silencieux) {
    if (!zone.querySelector('#cc-liste')) zone.innerHTML = C.barreFiltres(DEF_ENTREPOT, st.filtres) + '<div id="cc-liste" aria-live="polite"></div>';
    var cible = zone.querySelector('#cc-liste');
    return C.charger(cible, function () { return API.centre.entrepot(st.filtres); }, function (d) { dessinerEntrepot(cible, d); }, { silencieux: silencieux });
  }
  var DEF_ENTREPOT = { id: 'entrepot', filtres: ['pays', 'entrepot'] };
  C.enregistrer({ id: 'entrepot', ordre: 40, filtres: DEF_ENTREPOT.filtres, rendre: function (zone, st, ctx) { zone.innerHTML = ''; chargerEntrepot(zone, st, ctx, false); }, actualiser: chargerEntrepot });

  /* ======================================================================
     Consolidations, transport, chauffeurs
     ====================================================================== */
  C.enregistrer({
    id: 'consolidations', ordre: 50, vue: 'consolidations', filtres: ['statut', 'pays', 'service', 'entrepot', 'client', 'du', 'au'], statuts: ['OPEN', 'CLOSED', 'CANCELLED'], prefixeStatut: 'c-cons-',
    colonnes: [
      { t: 'c-col-consolidation', rendre: function (l) { return deuxLignes(mono(l.code), service(l.mode)); } },
      { t: 'c-col-statut', rendre: function (l) { return pastille('c-cons-', l.status); } },
      { t: 'c-col-destination', rendre: function (l) { return s(l.destination_country ? C.pays(l.destination_country) : ''); } },
      { t: 'c-col-entrepot', rendre: function (l) { return s(l.warehouse); } },
      { t: 'c-col-colis', rendre: function (l) { return deuxLignes(e(C.nombre(l.parcels)), e(t('c-n-clients', { nombre: C.nombre(l.customers) })) + ' · ' + poids(l.weight_lb)); } },
      { t: 'c-col-expedition', rendre: function (l) { return l.shipment ? mono(l.shipment) : '<span class="cc-petit">' + e(t('c-pas-expediee')) + '</span>'; } },
      { t: 'c-col-ouverte', rendre: function (l) { return e(C.date(l.opened_at)); } },
      { t: 'c-col-fermee', rendre: function (l) { return e(C.date(l.closed_at)); } }
    ], cle: function (l) { return l.code; }
  });

  C.enregistrer({
    id: 'transport', ordre: 60, vue: 'transport', filtres: ['statut', 'service', 'pays', 'du', 'au'], statuts: STATUTS_TRANSPORT, prefixeStatut: 'c-trans-',
    colonnes: [
      { t: 'c-col-reference', rendre: function (l) { return deuxLignes(mono(l.reference), s(l.carrier)); } },
      { t: 'c-col-service', rendre: function (l) { return service(l.mode); } },
      { t: 'c-col-statut', rendre: function (l) { return pastille('c-trans-', l.status) + badgeRetard(l.late); } },
      { t: 'c-col-trajet', rendre: function (l) { return deuxLignes(s(l.origin), '→ ' + s(l.destination)); } },
      { t: 'c-col-depart', rendre: function (l) { return deuxLignes(e(C.date(l.actual_departure_at)), '<span title="' + e(t('c-prevu')) + '">' + e(t('c-prevu-le', { date: C.date(l.planned_departure_at) })) + '</span>'); } },
      { t: 'c-col-arrivee', rendre: function (l) { return deuxLignes(e(C.date(l.actual_arrival_at)), '<span title="' + e(t('c-prevu')) + '">' + e(t('c-prevu-le', { date: C.date(l.planned_arrival_at) })) + '</span>'); } },
      { t: 'c-col-expeditions', rendre: function (l) { return e(C.nombre(l.shipments)); } }
    ], cle: function (l) { return l.reference; }
  });

  C.enregistrer({
    id: 'chauffeurs', ordre: 70, vue: 'chauffeurs', filtres: ['statut', 'pays', 'ville'], statuts: ['ACTIVE', 'ON_LEAVE', 'INACTIVE'], prefixeStatut: 'c-chauf-',
    colonnes: [
      { t: 'c-col-nom', rendre: function (l) { return deuxLignes('<strong>' + s(l.name) + '</strong>', s(l.phone)); } },
      { t: 'c-col-statut', rendre: function (l) { return pastille('c-chauf-', l.status) + ' ' + (l.available_today ? '<span class="ses-pastille ses-pastille-ok">' + e(t('c-disponible')) + '</span>' : '<span class="ses-pastille ses-pastille-neutre">' + e(t('c-indisponible')) + '</span>'); } },
      { t: 'c-col-vehicule', rendre: function (l) { return s(l.vehicle); } },
      { t: 'c-col-zones', rendre: function (l) { return (l.zones || []).length ? (l.zones || []).map(function (z) { return '<span class="ses-mono cc-etiquette">' + e(z) + '</span>'; }).join(' ') : '—'; } },
      { t: 'c-col-missions-jour', rendre: function (l) { return deuxLignes(e(t('c-faites-sur', { faites: C.nombre(l.completed_today), total: C.nombre(l.tasks_today) })), l.failed_today ? e(t('c-echouees', { nombre: C.nombre(l.failed_today) })) : ''); } },
      { t: 'c-col-ouvertes', rendre: function (l) { return e(C.nombre(l.tasks_open)); } },
      { t: 'c-col-position', rendre: function (l) { return l.position_age_min === null || l.position_age_min === undefined ? '<span class="cc-petit">' + e(t('c-pas-de-position')) + '</span>' : e(t('c-il-y-a-min', { nombre: C.nombre(l.position_age_min) })); } }
    ], cle: function (l) { return l.driver_id; }
  });

  /* ======================================================================
     Enlèvements et livraisons : l'équipe traite les demandes des clients
     ====================================================================== */
  function boutonTraiter(l) {
    if (l.request_status !== 'REQUESTED') return '';
    return '<button type="button" class="ses-bouton ses-bouton-principal ses-bouton-mini" data-act="traiter" data-id="' + e(l.request_id) + '" data-kind="enlevement">' + e(t('c-traiter')) + '</button>';
  }
  C.enregistrer({
    id: 'enlevements', ordre: 80, vue: 'enlevements', filtres: ['statut', 'pays', 'ville', 'client', 'du', 'au'], statuts: ETAPES_DEMANDE, prefixeStatut: 'c-etape-', intro: 'c-enl-intro',
    colonnes: [
      { t: 'c-col-numero', rendre: function (l) { return deuxLignes(mono(l.number), e(t(l.source === 'REQUEST' ? 'c-source-demande' : 'c-source-equipe'))); } },
      { t: 'c-col-client', rendre: client },
      { t: 'c-col-adresse', rendre: function (l) { return deuxLignes(s(l.address), lieu(l.city, l.country)); } },
      { t: 'c-col-date', rendre: function (l) { return deuxLignes(e(C.jour(l.date)), l.window && l.window !== 'ANY' ? e(t('c-creneau-' + l.window)) : ''); } },
      { t: 'c-col-colis-attendus', rendre: function (l) { return e(C.nombre(l.parcels_expected)); } },
      { t: 'c-col-etape', rendre: function (l) { return pastille('c-etape-', l.stage) + (l.review_message ? '<span class="cc-petit cc-bloc">' + s(l.review_message) + '</span>' : ''); } },
      { t: 'c-col-chauffeur', rendre: function (l) { return s(l.driver); } },
      { t: 'c-col-actions', rendre: function (l) { return boutonTraiter(l) || ''; } }
    ], cle: function (l) { return l.request_id; }
  });

  C.enregistrer({
    id: 'livraisons', ordre: 90, vue: 'livraisons', filtres: ['statut', 'pays', 'ville', 'entrepot', 'client', 'du', 'au'], statuts: ETAPES_LIVRAISON, prefixeStatut: 'c-etape-', intro: 'c-liv-intro',
    resume: function (d) { return d.delayed ? '<p class="cc-note cc-note-alerte" role="status">' + e(t('c-liv-en-retard', { nombre: C.nombre(d.delayed) })) + '</p>' : ''; },
    colonnes: [
      { t: 'c-col-numero', rendre: function (l) { return deuxLignes(mono(l.number), e(t(l.kind === 'REQUEST' ? 'c-source-demande' : 'c-source-mission'))); } },
      { t: 'c-col-client', rendre: client },
      { t: 'c-col-adresse', rendre: function (l) { return s(l.address); } },
      { t: 'c-col-date', rendre: function (l) { return deuxLignes(e(C.jour(l.date)), l.window_start || l.window_end ? e(C.date(l.window_start)) + ' → ' + e(C.date(l.window_end)) : ''); } },
      { t: 'c-col-colis', rendre: function (l) { return e(C.nombre(l.parcels)); } },
      { t: 'c-col-etape', rendre: function (l) { return pastille('c-etape-', l.stage) + badgeRetard(l.delayed); } },
      { t: 'c-col-chauffeur', rendre: function (l) { return l.kind === 'REQUEST' ? '—' : (l.driver ? s(l.driver) : '<span class="cc-petit">' + e(t('c-sans-chauffeur')) + '</span>'); } },
      { t: 'c-col-actions', rendre: function (l) { return l.request_status === 'REQUESTED' ? '<button type="button" class="ses-bouton ses-bouton-principal ses-bouton-mini" data-act="traiter" data-id="' + e(l.ref_id) + '" data-kind="livraison">' + e(t('c-traiter')) + '</button>' : ''; } }
    ], cle: function (l) { return l.ref_id; }
  });

  /* ======================================================================
     Douane, incidents, notifications
     ====================================================================== */
  C.enregistrer({
    id: 'douane', ordre: 100, vue: 'douane', filtres: ['statut', 'pays', 'service', 'du', 'au'], statuts: STATUTS_DOUANE, prefixeStatut: 'c-dou-',
    colonnes: [
      { t: 'c-col-expedition', rendre: function (l) { return deuxLignes(mono(l.shipment), service(l.mode)); } },
      { t: 'c-col-reference', rendre: function (l) { return mono(l.reference); } },
      { t: 'c-col-statut', rendre: function (l) { return pastille('c-dou-', l.status) + (l.status === 'REJECTED' && l.rejected_reason ? '<span class="cc-petit cc-bloc">' + s(l.rejected_reason) + '</span>' : ''); } },
      { t: 'c-col-courtier', rendre: function (l) { return s(l.broker); } },
      { t: 'c-col-trajet', rendre: function (l) { return deuxLignes(s(l.origin_country ? C.pays(l.origin_country) : ''), '→ ' + s(l.destination_country ? C.pays(l.destination_country) : '')); } },
      { t: 'c-col-valeur', rendre: function (l) { return l.declared_value === null || l.declared_value === undefined ? '—' : C.montant(l.declared_value, l.currency); } },
      { t: 'c-col-colis', rendre: function (l) { return e(C.nombre(l.parcels)); } },
      { t: 'c-col-deposee', rendre: function (l) { return e(C.date(l.submitted_at)); } },
      { t: 'c-col-attente', rendre: function (l) { return l.waiting_days === null || l.waiting_days === undefined ? (l.cleared_at ? e(t('c-dedouane-le', { date: C.date(l.cleared_at) })) : '—') : e(t('c-jours', { nombre: C.nombre(l.waiting_days) })); } }
    ], cle: function (l) { return l.reference; }
  });

  C.enregistrer({
    id: 'incidents', ordre: 110, vue: 'incidents', filtres: ['statut', 'pays', 'service', 'entrepot', 'client', 'du', 'au'], statuts: ['ACTIVE'].concat(STATUTS_INCIDENT), prefixeStatut: 'c-incst-',
    colonnes: [
      { t: 'c-col-date', rendre: function (l) { return e(C.date(l.created_at)); } },
      { t: 'c-col-type', rendre: function (l) { return e(t('c-inc-' + l.type)); } },
      { t: 'c-col-gravite', rendre: function (l) { return pastille('c-grav-', l.severity); } },
      { t: 'c-col-statut', rendre: function (l) { return pastille('c-incst-', l.status); } },
      { t: 'c-col-colis', rendre: function (l) { return lienColis(l.tracking_number); } },
      { t: 'c-col-client', rendre: function (l) { return l.customer_code ? mono(l.customer_code) : '—'; } },
      { t: 'c-col-entrepot', rendre: function (l) { return s(l.warehouse); } },
      { t: 'c-col-description', rendre: function (l) { return s(l.description) + (l.resolution ? '<span class="cc-petit cc-bloc">' + e(t('c-resolution')) + ' : ' + e(l.resolution) + '</span>' : ''); } }
    ], cle: function (l) { return l.incident_id; }
  });

  /* La santé des envois (phase 13) : par canal, ce qui attend, part, échoue — rien de personnel. Absente tant que la migration 010 n'est pas passée. */
  function sante(zone) {
    if (!API.notifications || !API.notifications.sante) return;
    var bloc = document.createElement('section');
    bloc.className = 'cc-groupe cc-sante';
    bloc.setAttribute('aria-labelledby', 'cc-g-sante');
    zone.insertBefore(bloc, zone.firstChild);
    API.notifications.sante().then(function (h) {
      var canaux = h.channels || [], err = h.recent_errors || [], ev = h.events || {};
      bloc.innerHTML = '<h3 id="cc-g-sante">' + e(t('c-sante-titre')) + '</h3>' + C.tableau([
        { t: 'c-col-canal', rendre: function (c) { return e(t('c-canal-' + c.channel)) + ' ' + (c.enabled ? '<span class="ses-pastille ses-pastille-ok">' + e(t('c-actif')) + '</span>' : '<span class="ses-pastille ses-pastille-neutre">' + e(t('c-inactif')) + '</span>'); } },
        { t: 'c-sante-attente', rendre: function (c) { return deuxLignes(e(C.nombre(c.pending)), c.oldest_pending_at ? e(t('c-att-depuis', { age: C.age(c.oldest_pending_at) })) : ''); } },
        { t: 'c-sante-en-cours', rendre: function (c) { return e(C.nombre(c.sending)); } },
        { t: 'c-sante-envoyees', rendre: function (c) { return e(C.nombre(c.sent_24h)); } },
        { t: 'c-sante-relances', rendre: function (c) { return e(C.nombre(c.retries_24h)); } },
        { t: 'c-sante-echecs', rendre: function (c) { return c.failed_24h ? '<strong>' + e(C.nombre(c.failed_24h)) + '</strong>' : '0'; } }], canaux, { legende: 'c-sante-titre' }) +
        '<p class="cc-petit">' + e(t('c-sante-file', { attente: C.nombre(ev.pending), mortes: C.nombre(ev.dead) })) + '</p>' +
        (err.length ? '<h4 class="cc-sous-titre">' + e(t('c-sante-erreurs')) + '</h4><ul class="cc-sous-liste">' + err.map(function (x) {
          return '<li><span class="cc-petit">' + e(C.date(x.at)) + ' · ' + e(t('c-canal-' + x.channel)) + ' · ' + e(x.template) + '</span><br>' + pastille('c-sante-', x.outcome) + ' ' + s(x.error) + '</li>';
        }).join('') + '</ul>' : '');
    }, function () { if (bloc.parentNode) bloc.parentNode.removeChild(bloc); });
  }

  C.enregistrer({
    id: 'notifications', ordre: 120, vue: 'notifications', filtres: ['statut', 'client', 'du', 'au'], statuts: STATUTS_NOTIF, prefixeStatut: 'c-nst-', intro: 'c-notif-intro', apres: sante,
    colonnes: [
      { t: 'c-col-date', rendre: function (l) { return e(C.date(l.created_at)); } },
      { t: 'c-col-canal', rendre: function (l) { return e(t('c-canal-' + l.channel)); } },
      { t: 'c-col-modele', rendre: function (l) { return mono(l.template); } },
      { t: 'c-col-statut', rendre: function (l) { return pastille('c-nst-', l.status); } },
      { t: 'c-col-client', rendre: client },
      { t: 'c-col-envoyee', rendre: function (l) { return e(C.date(l.sent_at)); } }
    ], cle: function (l) { return String(l.id); }
  });

  /* ======================================================================
     Clients, support, facturation, paiements
     ====================================================================== */
  C.enregistrer({
    id: 'clients', ordre: 130, vue: 'clients', filtres: ['pays', 'ville', 'client', 'du', 'au'], intro: 'c-cli-intro',
    colonnes: [
      { t: 'c-col-client', rendre: function (l) { return deuxLignes('<strong>' + s(l.name) + '</strong>' + (l.staff_account ? ' <span class="ses-pastille ses-pastille-warn">' + e(t('c-compte-equipe')) + '</span>' : ''), mono(l.customer_code)); } },
      { t: 'c-col-contact', rendre: function (l) { return deuxLignes(s(l.email), s(l.phone)); } },
      { t: 'c-col-lieu', rendre: function (l) { return s([l.city, l.country].filter(Boolean).join(', ')); } },
      { t: 'c-col-colis', rendre: function (l) { return deuxLignes(e(C.nombre(l.parcels)), e(t('c-n-ouverts', { nombre: C.nombre(l.parcels_open) }))); } },
      { t: 'c-col-impayes', rendre: function (l) { return l.unpaid === null || l.unpaid === undefined ? '<span class="cc-petit">' + e(t('c-non-autorise')) + '</span>' : (l.unpaid.length ? l.unpaid.map(function (u) { return e(C.montant(u.balance, u.currency)) + ' <span class="cc-petit">(' + e(C.nombre(u.invoices)) + ')</span>'; }).join('<br>') : '—'); } },
      { t: 'c-col-tickets', rendre: function (l) { return e(C.nombre(l.tickets_open)); } },
      { t: 'c-col-dernier-colis', rendre: function (l) { return e(C.date(l.last_parcel_at)); } },
      { t: 'c-col-actions', rendre: function (l) {
        var h = C.lien('colis', { client: l.customer_code });
        return h ? '<a class="ses-bouton ses-bouton-second ses-bouton-mini" href="' + e(h) + '">' + e(t('c-voir-colis')) + '</a>' : '';
      } }
    ], cle: function (l) { return l.customer_code; }
  });

  C.enregistrer({
    id: 'support', ordre: 140, vue: 'tickets', filtres: ['statut', 'client', 'du', 'au'], statuts: ['ACTIVE'].concat(STATUTS_TICKET), prefixeStatut: 'c-tk-', intro: 'c-sup-intro',
    colonnes: [
      { t: 'c-col-numero', rendre: function (l) { return '<button type="button" class="cc-lien ses-mono" data-act="ticket" data-id="' + e(l.ticket_id) + '">' + e(l.number) + '</button>'; } },
      { t: 'c-col-sujet', rendre: function (l) { return deuxLignes(s(l.subject), e(t('c-tkcat-' + l.category))); } },
      { t: 'c-col-client', rendre: client },
      { t: 'c-col-statut', rendre: function (l) { return pastille('c-tk-', l.status); } },
      { t: 'c-col-dernier-message', rendre: function (l) { return deuxLignes(e(t(l.last_author === 'STAFF' ? 'c-auteur-equipe' : 'c-auteur-client')), l.waiting_hours === null || l.waiting_hours === undefined ? '' : e(t('c-attend-depuis-h', { nombre: C.nombre(l.waiting_hours) }))); } },
      { t: 'c-col-messages', rendre: function (l) { return e(C.nombre(l.messages)); } },
      { t: 'c-col-maj', rendre: function (l) { return e(C.date(l.updated_at)); } }
    ], cle: function (l) { return l.ticket_id; }
  });

  C.enregistrer({
    id: 'facturation', ordre: 150, vue: 'factures', filtres: ['statut', 'client', 'du', 'au'], statuts: ['UNPAID'].concat(STATUTS_FACTURE), prefixeStatut: 'c-fact-', intro: 'c-fac-intro',
    resume: function (d) {
      var tot = d.totals || [];
      return tot.length ? '<ul class="cc-totaux" aria-label="' + e(t('c-totaux')) + '">' + tot.map(function (x) {
        return '<li><span class="cc-kpi-etiquette">' + e(t('c-tot-facture', { devise: x.currency })) + '</span><strong>' + e(C.montant(x.invoiced, x.currency)) + '</strong></li>' +
          '<li><span class="cc-kpi-etiquette">' + e(t('c-tot-impaye', { devise: x.currency })) + '</span><strong>' + e(C.montant(x.balance, x.currency)) + '</strong><span class="cc-petit">' + e(t('c-tot-impaye-n', { nombre: C.nombre(x.unpaid_invoices) })) + '</span></li>';
      }).join('') + '</ul>' : '';
    },
    colonnes: [
      { t: 'c-col-numero', rendre: function (l) { return deuxLignes(mono(l.number), e(t(l.grouped ? 'c-groupee' : 'c-simple'))); } },
      { t: 'c-col-client', rendre: client },
      { t: 'c-col-statut', rendre: function (l) { return pastille('c-fact-', l.status); } },
      { t: 'c-col-total', rendre: function (l) { return C.montant(l.total, l.currency); } },
      { t: 'c-col-paye', rendre: function (l) { return deuxLignes(C.montant(l.paid, l.currency), (Number(l.credited) ? e(t('c-avoir-de', { montant: C.montant(l.credited, l.currency) })) : '') + (Number(l.refunded) ? ' ' + e(t('c-rembourse-de', { montant: C.montant(l.refunded, l.currency) })) : '')); } },
      { t: 'c-col-solde', rendre: function (l) { return '<strong>' + e(C.montant(l.balance, l.currency)) + '</strong>'; } },
      { t: 'c-col-emise', rendre: function (l) { return deuxLignes(e(C.date(l.issued_at)), l.due_date ? e(t('c-echeance', { date: C.jour(l.due_date) })) : ''); } }
    ], cle: function (l) { return l.number; }
  });

  C.enregistrer({
    id: 'paiements', ordre: 160, vue: 'paiements', filtres: ['statut', 'client', 'du', 'au'], statuts: ['PAYMENT', 'REFUND', 'CREDIT'], prefixeStatut: 'c-paie-', intro: 'c-pai-intro',
    resume: function (d) {
      return '<ul class="cc-totaux" aria-label="' + e(t('c-totaux')) + '"><li><span class="cc-kpi-etiquette">' + e(t('c-pai-encaisse')) + '</span><strong>' + e(C.montant(d.collected_usd, 'USD')) + '</strong></li>' +
        '<li><span class="cc-kpi-etiquette">' + e(t('c-pai-rembourse')) + '</span><strong>' + e(C.montant(d.refunded_usd, 'USD')) + '</strong></li></ul>';
    },
    colonnes: [
      { t: 'c-col-date', rendre: function (l) { return e(C.date(l.at)); } },
      { t: 'c-col-genre', rendre: function (l) { return pastille('c-paie-', l.kind).replace('ses-pastille-neutre', l.kind === 'PAYMENT' ? 'ses-pastille-ok' : 'ses-pastille-warn'); } },
      { t: 'c-col-numero', rendre: function (l) { return mono(l.number); } },
      { t: 'c-col-facture', rendre: function (l) { return mono(l.invoice); } },
      { t: 'c-col-client', rendre: client },
      { t: 'c-col-montant', rendre: function (l) { return deuxLignes('<strong>' + e(montantDe(l)) + '</strong>', l.base_amount_usd === null || l.base_amount_usd === undefined ? '' : e(t('c-equivalent-usd', { montant: C.montant(l.base_amount_usd, 'USD') }))); } },
      { t: 'c-col-detail', rendre: function (l) { return l.method ? e(t('c-moyen-' + l.method)) : (l.reason ? s(l.reason) : '—'); } }
    ], cle: function (l) { return l.number; }
  });

  /* ======================================================================
     Direction : utilisateurs, journal d'audit, réglages
     ====================================================================== */
  C.enregistrer({
    id: 'utilisateurs', ordre: 170, vue: 'utilisateurs', filtres: ['statut', 'client'], statuts: ROLES.concat(['INACTIVE']), prefixeStatut: 'c-role-', intro: 'c-usr-intro',
    colonnes: [
      { t: 'c-col-email', rendre: function (l) { return s(l.email); } },
      { t: 'c-col-role', rendre: function (l) { return e(t('c-role-' + l.role)) + (l.driver ? ' <span class="ses-pastille ses-pastille-info">' + e(t('c-chauffeur')) + '</span>' : ''); } },
      { t: 'c-col-droits', rendre: function (l) { return (l.rights || []).length ? (l.rights || []).map(function (d) { return '<span class="ses-mono cc-etiquette">' + e(d) + '</span>'; }).join(' ') : '<span class="cc-petit">' + e(t('c-aucun-droit')) + '</span>'; } },
      { t: 'c-col-actif', rendre: function (l) { return l.active ? '<span class="ses-pastille ses-pastille-ok">' + e(t('c-actif')) + '</span>' : '<span class="ses-pastille ses-pastille-neutre">' + e(t('c-inactif')) + '</span>'; } },
      { t: 'c-col-succursale', rendre: function (l) { return s(l.branch); } },
      { t: 'c-col-derniere-connexion', rendre: function (l) { return e(C.date(l.last_sign_in_at)); } },
      { t: 'c-col-cree', rendre: function (l) { return e(C.date(l.created_at)); } }
    ], cle: function (l) { return l.user_id; }
  });

  C.enregistrer({
    id: 'audit', ordre: 180, vue: 'audit', filtres: ['statut', 'client', 'du', 'au'], statutLibre: 'c-aud-action-aide', intro: 'c-aud-intro',
    colonnes: [
      { t: 'c-col-date', rendre: function (l) { return e(C.date(l.at)); } },
      { t: 'c-col-acteur', rendre: function (l) { return s(l.actor); } },
      { t: 'c-col-action', rendre: function (l) { return mono(l.action); } },
      { t: 'c-col-objet', rendre: function (l) { return deuxLignes(s(l.entity_type), mono(String(l.entity_id || '').slice(0, 13))); } },
      { t: 'c-col-changement', rendre: function (l) {
        var av = l.before && l.before.status, ap = l.after && l.after.status, n = l.metadata && l.metadata.number;
        return deuxLignes(av || ap ? s(av) + ' → ' + s(ap) : '—', n ? mono(n) : '');
      } },
      { t: 'c-col-correlation', rendre: function (l) { return mono(String(l.correlation_id || '').slice(0, 8)); } }
    ], cle: function (l) { return String(l.id); }
  });

  function dessinerReglages(zone, d) {
    var o = d.organization || {}, p = d.pricing || {}, dl = d.delivery || {}, ev = d.events || {};
    function dl2(paires) { return '<dl class="cc-dl">' + paires.map(function (x) { return '<dt>' + e(t(x[0])) + '</dt><dd>' + x[1] + '</dd>'; }).join('') + '</dl>'; }
    function liste(items, rendre) { return items.length ? '<ul class="cc-sous-liste">' + items.map(rendre).join('') + '</ul>' : '<p class="cc-rien">' + e(t('c-aucune')) + '</p>'; }
    zone.innerHTML = '<p class="cc-intro">' + e(t('c-reg-intro')) + '</p><div class="cc-cartes-reglages">' +
      '<section class="cc-carte"><h3>' + e(t('c-reg-organisation')) + '</h3>' + dl2([['c-reg-nom', s(o.name)], ['c-reg-devise', s(o.default_currency)]]) + '</section>' +
      '<section class="cc-carte"><h3>' + e(t('c-reg-succursales')) + '</h3>' + liste(d.branches || [], function (b) { return '<li><span class="ses-mono">' + e(b.code) + '</span> ' + e(b.name) + ' · ' + e(t('c-bk-' + b.kind)) + ' · ' + e(C.pays(b.country)) + (b.active ? '' : ' <span class="ses-pastille ses-pastille-neutre">' + e(t('c-inactif')) + '</span>') + '</li>'; }) + '</section>' +
      '<section class="cc-carte"><h3>' + e(t('c-reg-entrepots')) + '</h3>' + liste(d.warehouses || [], function (w) { return '<li><span class="ses-mono">' + e(w.code) + '</span> ' + e(w.name) + ' · ' + s(w.branch) + (w.active ? '' : ' <span class="ses-pastille ses-pastille-neutre">' + e(t('c-inactif')) + '</span>') + '</li>'; }) + '</section>' +
      '<section class="cc-carte"><h3>' + e(t('c-reg-modes')) + '</h3>' + liste(d.transport_modes || [], function (m) { return '<li>' + e(t('c-svc-' + m.code)) + (m.active ? '' : ' <span class="ses-pastille ses-pastille-neutre">' + e(t('c-inactif')) + '</span>') + '</li>'; }) + '</section>' +
      '<section class="cc-carte"><h3>' + e(t('c-reg-tarification')) + '</h3>' + dl2([['c-reg-grilles', e(C.nombre(p.rate_cards_active))], ['c-reg-zones-tarif', e(C.nombre(p.zones_active))], ['c-reg-surtaxes', e(C.nombre(p.surcharges_active))],
        ['c-reg-regles', e(C.nombre(p.rules_active))], ['c-reg-taxes', e(C.nombre(p.taxes_active))]]) +
        '<h4>' + e(t('c-reg-frais')) + '</h4>' + liste(p.service_fee || [], function (f) { return '<li><span class="ses-mono">' + e(f.code) + '</span> ' + e(C.montant(f.amount, f.currency)) + '</li>'; }) +
        '<h4>' + e(t('c-reg-taux')) + '</h4>' + liste(p.exchange_rates || [], function (r) { return '<li>1 ' + e(r.from) + ' = ' + e(C.nombre(r.rate)) + ' ' + e(r.to) + ' <span class="cc-petit">' + e(t('c-depuis', { date: C.jour(r.valid_from) })) + '</span></li>'; }) + '</section>' +
      '<section class="cc-carte"><h3>' + e(t('c-reg-livraison')) + '</h3>' + dl2([['c-reg-zones', e(C.nombre(dl.zones))], ['c-reg-vehicules', e(C.nombre(dl.vehicles))], ['c-reg-chauffeurs', e(C.nombre(dl.drivers))]]) + '</section>' +
      '<section class="cc-carte"><h3>' + e(t('c-reg-evenements')) + '</h3>' + dl2([['c-reg-en-attente', e(C.nombre(ev.pending))], ['c-reg-en-echec', e(C.nombre(ev.dead))]]) + '</section></div>';
  }
  function chargerReglages(zone, st, ctx, silencieux) {
    return C.charger(zone, function () { return API.centre.reglages(); }, function (d) { dessinerReglages(zone, d); }, { silencieux: silencieux });
  }
  C.enregistrer({ id: 'parametres', ordre: 190, filtres: [], rendre: function (zone, st, ctx) { chargerReglages(zone, st, ctx, false); }, actualiser: chargerReglages });

  /* « Rapports » : les rapports par période de la vue d'ensemble du tableau de bord (des chiffres réels de la base). Un lien, pas une section. */
  C.enregistrer({ id: 'rapports', ordre: 200, filtres: [] });

  /* ======================================================================
     Les fiches et les actions
     ====================================================================== */
  C.actions = C.actions || {};

  /* --- Fiche d'un colis, POUR L'ÉQUIPE : tout le journal, les auteurs, les motifs --- */
  function ficheColis(d) {
    var p = d.parcel || {};
    var html = '<div class="cc-fiche-entete"><p class="ses-mono cc-fiche-numero">' + e(p.tracking_number) + '</p>' + pastille('c-colis-', p.status) + (p.prohibited ? ' <span class="ses-pastille ses-pastille-bad">' + e(t('c-interdit')) + '</span>' : '') + '</div>' +
      '<dl class="cc-dl cc-dl-2">' +
      '<dt>' + e(t('c-col-client')) + '</dt><dd>' + (p.customer_code ? s(p.customer_name) + ' <span class="ses-mono cc-petit">' + e(p.customer_code) + '</span>' : '—') + '</dd>' +
      '<dt>' + e(t('c-col-service')) + '</dt><dd>' + service(p.service_mode) + '</dd>' +
      '<dt>' + e(t('c-col-destination')) + '</dt><dd>' + lieu(p.destination_city, p.destination_country) + '</dd>' +
      '<dt>' + e(t('c-fiche-adresse')) + '</dt><dd>' + s(p.delivery_address) + '</dd>' +
      '<dt>' + e(t('c-fiche-expediteur')) + '</dt><dd>' + s(p.sender_name) + '</dd>' +
      '<dt>' + e(t('c-fiche-destinataire')) + '</dt><dd>' + s(p.recipient_name) + '</dd>' +
      '<dt>' + e(t('c-col-poids')) + '</dt><dd>' + poids(p.weight_lb) + '</dd>' +
      '<dt>' + e(t('c-fiche-valeur')) + '</dt><dd>' + (p.declared_value === null || p.declared_value === undefined ? '—' : e(C.montant(p.declared_value, 'USD'))) + '</dd>' +
      '<dt>' + e(t('c-col-ou')) + '</dt><dd>' + s(p.warehouse) + (p.location ? ' · <span class="ses-mono">' + e(p.location) + '</span>' : '') + '</dd>' +
      '<dt>' + e(t('c-fiche-etat')) + '</dt><dd>' + (p.condition ? e(t('c-etat-' + p.condition)) : '—') + '</dd>' +
      '<dt>' + e(t('c-fiche-autorite')) + '</dt><dd>' + e(t('c-aut-' + p.authority)) + '</dd>' +
      '<dt>' + e(t('c-col-description')) + '</dt><dd>' + s(p.description) + '</dd></dl>';
    var ex = d.shipments || [], dl = d.deliveries || [];
    if (ex.length) html += '<h3 class="cc-sous-titre">' + e(t('c-fiche-expeditions')) + '</h3><ul class="cc-sous-liste">' + ex.map(function (x) { return '<li><span class="ses-mono">' + e(x.code) + '</span> ' + service(x.mode) + ' ' + pastille('c-exp-', x.status) + '</li>'; }).join('') + '</ul>';
    if (dl.length) html += '<h3 class="cc-sous-titre">' + e(t('c-fiche-livraisons')) + '</h3><ul class="cc-sous-liste">' + dl.map(function (x) { return '<li>' + e(C.jour(x.scheduled_date)) + ' · ' + e(x.driver || t('c-sans-chauffeur')) + ' ' + pastille('c-miss-', x.status) + '</li>'; }).join('') + '</ul>';
    if ((d.incidents || []).length) html += '<h3 class="cc-sous-titre">' + e(t('c-fiche-incidents')) + '</h3><ul class="cc-sous-liste">' + d.incidents.map(function (x) { return '<li>' + e(t('c-inc-' + x.type)) + ' ' + pastille('c-grav-', x.severity) + ' ' + pastille('c-incst-', x.status) + ' <span class="cc-petit">' + e(C.date(x.at)) + '</span><br>' + s(x.description) + '</li>'; }).join('') + '</ul>';
    var tl = d.timeline || [];
    html += '<h3 class="cc-sous-titre">' + e(t('c-fiche-journal')) + '</h3>' + (tl.length ? '<ol class="cc-journal">' + tl.map(function (x) {
      return '<li><span class="cc-journal-date">' + e(C.date(x.at)) + '</span><strong class="ses-mono">' + e(x.event) + '</strong>' + (x.to ? ' ' + pastille('c-colis-', x.to) : '') +
        '<span class="cc-petit cc-bloc">' + [x.actor, x.source, x.location].filter(Boolean).map(e).join(' · ') + '</span>' + (x.reason ? '<span class="cc-petit cc-bloc">' + e(t('c-motif')) + ' : ' + e(x.reason) + '</span>' : '') + '</li>';
    }).join('') + '</ol>' : '<p class="cc-rien">' + e(t('c-fiche-journal-vide')) + '</p>');
    var sc = d.scans || [];
    if (sc.length) html += '<h3 class="cc-sous-titre">' + e(t('c-fiche-scans')) + '</h3><ul class="cc-sous-liste">' + sc.map(function (x) { return '<li>' + e(C.date(x.at)) + ' · ' + e(t('c-but-' + x.purpose)) + ' · ' + e(t('c-scan-' + x.result)) + '</li>'; }).join('') + '</ul>';
    return html;
  }
  C.actions.colis = function (b) {
    var zone = C.dialogue('c-fiche-titre', '<div id="cc-fiche"></div>');
    var cible = zone && zone.querySelector('#cc-fiche');
    if (!cible) return;
    C.charger(cible, function () { return API.centre.colisDetail(b.getAttribute('data-numero')); }, function (d) { cible.innerHTML = ficheColis(d); });
  };

  /* --- Un ticket : lire, répondre, fermer --- */
  function ficheTicket(d) {
    var c = d.customer || {};
    var fermé = d.status === 'CLOSED';
    return '<div class="cc-fiche-entete"><p class="ses-mono cc-fiche-numero">' + e(d.number) + '</p>' + pastille('c-tk-', d.status) + '</div><h3 class="cc-sujet">' + s(d.subject) + '</h3>' +
      '<dl class="cc-dl cc-dl-2"><dt>' + e(t('c-col-client')) + '</dt><dd>' + s(c.name) + ' <span class="ses-mono cc-petit">' + e(c.code) + '</span></dd><dt>' + e(t('c-col-contact')) + '</dt><dd>' + s(c.email) + ' · ' + s(c.phone) + '</dd>' +
      '<dt>' + e(t('c-tkcat')) + '</dt><dd>' + e(t('c-tkcat-' + d.category)) + '</dd>' + (d.parcel ? '<dt>' + e(t('c-col-colis')) + '</dt><dd>' + lienColis(d.parcel) + '</dd>' : '') + (d.invoice ? '<dt>' + e(t('c-col-facture')) + '</dt><dd>' + mono(d.invoice) + '</dd>' : '') + '</dl>' +
      '<ol class="cc-messages" aria-label="' + e(t('c-fiche-messages')) + '">' + (d.messages || []).map(function (m) {
        return '<li class="cc-message cc-message-' + (m.author === 'STAFF' ? 'equipe' : 'client') + '"><span class="cc-petit">' + e(t(m.author === 'STAFF' ? 'c-auteur-equipe' : 'c-auteur-client')) + (m.staff ? ' · ' + e(m.staff) : '') + ' · ' + e(C.date(m.at)) + '</span><p>' + e(m.body) + '</p></li>';
      }).join('') + '</ol>' + (fermé ? '<p class="cc-rien">' + e(t('c-tk-ferme')) + '</p>' :
      '<form id="cc-reponse" novalidate><label class="ses-champ"><span>' + e(t('c-reponse')) + '</span><textarea name="message" rows="4" maxlength="4000" required></textarea></label><div id="cc-form-msg" role="alert" class="cc-form-msg" hidden></div>' +
      '<div class="cc-form-actions"><button type="button" class="ses-bouton ses-bouton-danger ses-bouton-mini" data-fermer-ticket>' + e(t('c-fermer-ticket')) + '</button><button type="submit" class="ses-bouton ses-bouton-principal">' + e(t('c-envoyer')) + '</button></div></form>');
  }
  C.actions.ticket = function (b) {
    var id = b.getAttribute('data-id');
    var zone = C.dialogue('c-ticket-titre', '<div id="cc-fiche"></div>');
    var cible = zone && zone.querySelector('#cc-fiche');
    if (!cible) return;
    function ouvrir() {
      return C.charger(cible, function () { return API.centre.ticket(id); }, function (d) {
        cible.innerHTML = ficheTicket(d);
        var f = cible.querySelector('#cc-reponse');
        if (!f) return;
        var msg = cible.querySelector('#cc-form-msg');
        function echec(err) { msg.hidden = false; msg.textContent = C.message(err); }
        f.addEventListener('submit', function (ev) {
          ev.preventDefault();
          var texte = String(f.elements.message.value || '').trim();
          if (!texte) { msg.hidden = false; msg.textContent = t('c-reponse-vide'); return; }
          msg.hidden = true;
          var envoi = f.querySelector('button[type=submit]');
          var fin = UI.occuper(envoi, t('c-envoi'));
          API.centre.repondreTicket(id, texte).then(function () { fin(); C.annoncer(t('c-reponse-envoyee'), 'succes'); ouvrir(); C.rafraichir(); }, function (err) { fin(); echec(err); });
        });
        cible.querySelector('[data-fermer-ticket]').addEventListener('click', function () {
          msg.hidden = true;
          API.centre.fermerTicket(id).then(function () { C.annoncer(t('c-ticket-ferme'), 'succes'); C.fermerDialogue(); C.rafraichir(); }, echec);
        });
      });
    }
    ouvrir();
  };

  /* --- Traiter une demande d'enlèvement ou de livraison --- */
  C.actions.traiter = function (b) {
    var id = b.getAttribute('data-id');
    var livraison = b.getAttribute('data-kind') === 'livraison';
    var zone = C.dialogue(livraison ? 'c-trait-liv-titre' : 'c-trait-enl-titre',
      '<p class="cc-intro">' + e(t(livraison ? 'c-trait-liv-intro' : 'c-trait-enl-intro')) + '</p>' +
      '<form id="cc-traiter" novalidate><div class="cc-form-grille"><label class="ses-champ"><span>' + e(t('c-trait-date')) + '</span><input type="date" name="date"></label></div>' +
      '<label class="ses-champ"><span>' + e(t('c-trait-message')) + '</span><textarea name="message" rows="3" maxlength="500"></textarea><small>' + e(t('c-trait-message-aide')) + '</small></label>' +
      '<div id="cc-form-msg" role="alert" class="cc-form-msg" hidden></div>' +
      '<div class="cc-form-actions"><button type="button" class="ses-bouton ses-bouton-danger ses-bouton-mini" data-refuser>' + e(t('c-refuser')) + '</button><button type="submit" class="ses-bouton ses-bouton-principal">' + e(t('c-approuver')) + '</button></div></form>', 'etroit');
    var f = zone && zone.querySelector('#cc-traiter');
    if (!f) return;
    var msg = zone.querySelector('#cc-form-msg');
    function envoyer(approuver, bouton) {
      var message = String(f.elements.message.value || '').trim();
      var date = String(f.elements.date.value || '').trim();
      if (!approuver && !message) { msg.hidden = false; msg.textContent = t('c-trait-motif-obligatoire'); return; }
      msg.hidden = true;
      var fin = UI.occuper(bouton, t('c-envoi'));
      var appel = livraison ? API.centre.traiterLivraison(id, { approuver: approuver, message: message, date: date }) : API.centre.traiterEnlevement(id, { approuver: approuver, message: message, date: date });
      appel.then(function () { fin(); C.fermerDialogue(); C.annoncer(t(approuver ? 'c-trait-approuvee' : 'c-trait-refusee'), 'succes'); C.rafraichir(); }, function (err) { fin(); msg.hidden = false; msg.textContent = C.message(err); });
    }
    f.addEventListener('submit', function (ev) { ev.preventDefault(); envoyer(true, f.querySelector('button[type=submit]')); });
    f.querySelector('[data-refuser]').addEventListener('click', function (ev) { envoyer(false, ev.currentTarget); });
  };

  /* Un seul écouteur pour tous les boutons d'action des tableaux et des fiches (ils sont redessinés à chaque chargement). */
  document.addEventListener('click', function (ev) {
    var b = ev.target.closest && ev.target.closest('#ses-p-centre [data-act], #cc-dialogue [data-act]');
    if (!b) return;
    var a = C.actions[b.getAttribute('data-act')];
    if (a) { ev.preventDefault(); a(b); }
  });
})();
