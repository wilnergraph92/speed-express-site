/* ==========================================================================
   Speed Express Shipping — l'analytique du centre de commande (phase 16, ADR 0014 ; complétée par l'étape 029)
   --------------------------------------------------------------------------
   Rapports quotidien, hebdomadaire, mensuel, trimestriel, annuel ou sur une
   période choisie ; cinq familles de chiffres (opérations, transport, dernier
   kilomètre, finance, clientèle) ; le détail par chauffeur, zone et tournée ;
   les alertes ; l'export CSV et PDF ; et la traçabilité : d'où viennent les
   chiffres (exécutions, version du calcul, empreintes), quels jours n'ont
   jamais été calculés, et la vérification qu'un calcul passé se refait à
   l'identique.

   Aucun chiffre n'est calculé ici, pas même une addition : les totaux par
   période, les stocks de fin de période, les clients distincts, les taux, les
   délais, le facturé et la marge viennent de la base (SES_API.analytique,
   public.lg_an_*). L'écran ne fait que choisir, mettre en forme et exporter.
   Seules les BORNES d'un rapport type (le lundi de la semaine, le premier du
   mois…) sont posées ici : des dates, pas des chiffres.
   ========================================================================== */
(function () {
  'use strict';

  var C = window.SES_CENTRE = window.SES_CENTRE || {};
  var API = window.SES_API;
  var t = function (k, v) { return C.t ? C.t(k, v) : k; };
  var e = function (x) { return C.e ? C.e(x) : String(x); };

  /* Les familles, dans l'ordre de lecture, et le domaine de droits dont chacune dépend. */
  var FAMILLES = ['operations', 'transport', 'last_mile', 'finance', 'customers'];
  var DOMAINE = { operations: 'ops', transport: 'ops', last_mile: 'ops', finance: 'finance', customers: 'customers' };
  /* Les cartes du haut : les mesures qui se lisent d'un coup d'œil, puis les indicateurs dérivés calculés par la base. */
  var CARTES = {
    operations: { mesures: ['parcels_received', 'parcels_delivered', 'parcels_in_transit', 'parcels_late', 'parcels_returned', 'incidents_opened'], ratios: ['avg_transit_hours', 'scan_rejection_pct'] },
    transport: { mesures: ['shipments_created', 'shipments_dispatched', 'shipments_arrived', 'shipments_late'], ratios: ['shipment_on_time_pct', 'avg_shipment_transit_hours'] },
    last_mile: { mesures: ['deliveries_completed_driver', 'deliveries_failed_driver', 'tasks_completed'], ratios: ['delivery_success_pct', 'delivery_on_time_pct'] },
    finance: { mesures: ['revenue_net_usd', 'payments_usd', 'receivables_usd', 'expenses_usd', 'refunds_usd'], ratios: ['invoiced_usd', 'collection_pct', 'net_collected_usd', 'margin_usd', 'margin_pct'] },
    customers: { mesures: ['customers_new', 'customers_active', 'customers_shipping', 'tickets_opened'], ratios: ['parcels_per_customer'] }
  };
  /* L'ordre de lecture des lignes : le chemin d'un colis, le transport, le dernier kilomètre, l'argent, la clientèle. */
  var ORDRE = ['parcels_received', 'parcels_on_hold', 'parcels_in_transit', 'parcels_late', 'parcels_delivered', 'parcels_damaged', 'parcels_lost', 'parcels_returned',
               'transit_hours_sum', 'transit_count', 'scans_total', 'scans_rejected', 'scans_by_purpose', 'incidents_opened',
               'shipments_created', 'shipments_dispatched', 'shipments_arrived', 'shipments_late', 'shipments_arrived_planned', 'shipments_arrived_on_time',
               'shipment_transit_hours_sum', 'shipment_transit_count',
               'tasks_completed', 'tasks_failed', 'deliveries_completed_driver', 'deliveries_failed_driver', 'deliveries_on_time',
               'deliveries_completed_zone', 'deliveries_failed_zone', 'deliveries_completed_route', 'deliveries_failed_route',
               'revenue_net_usd', 'revenue_tax_usd', 'payments_usd', 'payments_count', 'refunds_usd', 'expenses_usd', 'receivables_usd',
               'customers_new', 'customers_active', 'customers_shipping', 'tickets_opened'];
  function rang(code) { var i = ORDRE.indexOf(code); return i < 0 ? ORDRE.length : i; }
  /* Les indicateurs dérivés : leur unité et leur famille (la base les calcule ; l'écran les range). */
  var RATIOS = {
    avg_transit_hours: ['hours', 'operations'], scan_rejection_pct: ['pct', 'operations'],
    shipment_on_time_pct: ['pct', 'transport'], avg_shipment_transit_hours: ['hours', 'transport'],
    delivery_success_pct: ['pct', 'last_mile'], delivery_on_time_pct: ['pct', 'last_mile'],
    invoiced_usd: ['usd', 'finance'], collection_pct: ['pct', 'finance'], net_collected_usd: ['usd', 'finance'], margin_usd: ['usd', 'finance'], margin_pct: ['pct', 'finance'],
    parcels_per_customer: ['ratio', 'customers']
  };
  /* Le détail par zone et par tournée a son propre tableau : ces mesures ne se répètent pas dans celui de la famille. */
  var DANS_LE_DETAIL = ['zone', 'route'];
  /* Les rapports types : leurs bornes (jusqu'à aujourd'hui) et le regroupement qui se lit le mieux. */
  var RAPPORTS = ['daily', 'weekly', 'monthly', 'quarterly', 'yearly', 'custom'];
  var GRAIN_DU_RAPPORT = { daily: 'day', weekly: 'day', monthly: 'week', quarterly: 'month', yearly: 'month' };

  var etat = { rapport: 'yearly', grain: 'month', du: null, au: null, verdicts: {} };

  function locale() { return ({ fr: 'fr-FR', en: 'en-US', es: 'es-ES', ht: 'fr-HT' })[(document.documentElement.lang || 'fr').slice(0, 2)] || 'fr-FR'; }
  function aujourdhui() { var a = C.acces && C.acces(); return (a && a.today) || new Date().toISOString().slice(0, 10); }

  /* Une valeur selon son unité. null : la base n'a pas pu la calculer (division par zéro, stock d'un jour jamais calculé) — « — », jamais « 0 ». */
  function valeur(v, unite) {
    if (v === null || v === undefined || v === '') return '—';
    var n = Number(v);
    if (unite === 'usd') return C.montant ? C.montant(n, 'USD') : String(n);
    if (unite === 'pct') return n.toLocaleString(locale(), { maximumFractionDigits: 1 }) + ' %';
    if (unite === 'hours') return n.toLocaleString(locale(), { maximumFractionDigits: 1 }) + ' h';
    return n.toLocaleString(locale(), { maximumFractionDigits: 2 });
  }
  function uniteMesure(code) { return /_usd$/.test(code) ? 'usd' : /_hours_sum$/.test(code) ? 'hours' : 'count'; }

  /* Le nom d'une période, selon le grain (le calcul de la période elle-même vient de la base). */
  function nomPeriode(iso, grain) {
    var d = new Date(iso + 'T12:00:00');
    if (grain === 'day') return C.jour ? C.jour(iso) : iso;
    if (grain === 'week') return t('c-an-semaine', { date: C.jour ? C.jour(iso) : iso });
    if (grain === 'month') return d.toLocaleDateString(locale(), { month: 'long', year: 'numeric' });
    if (grain === 'quarter') return t('c-an-trimestre', { numero: Math.floor(d.getMonth() / 3) + 1, annee: d.getFullYear() });
    return String(d.getFullYear());
  }

  /* Les bornes d'un rapport type, jusqu'à la date de référence (incluse). Des dates en texte AAAA-MM-JJ, sans fuseau : celui d'Haïti est
     déjà dans « aujourd'hui » (donné par la base). */
  function bornes(rapport, ref) {
    var d = new Date(ref + 'T12:00:00Z'), iso = function (x) { return x.toISOString().slice(0, 10); };
    if (rapport === 'daily') return { du: ref, au: ref };
    if (rapport === 'weekly') { var w = new Date(d); w.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7)); return { du: iso(w), au: ref }; }
    if (rapport === 'monthly') return { du: ref.slice(0, 8) + '01', au: ref };
    if (rapport === 'quarterly') { var m = Math.floor(d.getUTCMonth() / 3) * 3 + 1; return { du: ref.slice(0, 5) + (m < 10 ? '0' : '') + m + '-01', au: ref }; }
    return { du: ref.slice(0, 5) + '01-01', au: ref };
  }

  /* --- L'export --- */
  function celluleCsv(v) {
    var s = v === null || v === undefined ? '' : String(v);
    if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
    return '"' + s.replace(/"/g, '""') + '"';
  }
  function libelleDimension(rap, metrique, dim) {
    var genre = (rap.metrics || []).filter(function (m) { return m.code === metrique; }).map(function (m) { return m.dimension_kind; })[0];
    var l = rap.labels && genre && rap.labels[genre];
    return (l && l[dim]) || '';
  }
  /* Le CSV d'un rapport : d'abord d'où il vient (période, horodatage, version, empreinte, statut, exécutions), puis les lignes telles que la
     base les rend (période, mesure, dimension, son nom, valeur, unité), puis les indicateurs dérivés de chaque période. */
  function csv(rapport) {
    var l = [];
    var meta = [[t('c-an-col-periode'), rapport.from + ' → ' + rapport.to], [t('c-an-genere-le'), rapport.generated_at], [t('c-an-version'), rapport.calc_version],
                [t('c-an-empreinte-rapport'), rapport.report_checksum], [t('c-an-statut'), t('c-an-st-' + rapport.status)],
                [t('c-an-source'), (rapport.runs || []).map(function (r) { return 'n° ' + r.run_id + ' (' + r.calc_version + ', ' + String(r.checksum || '').slice(0, 12) + ')'; }).join(' ; ')]];
    meta.forEach(function (x) { l.push(x.map(celluleCsv).join(',')); });
    l.push('');
    l.push([t('c-an-col-periode'), t('c-an-mesure'), t('c-an-dimension'), t('c-an-libelle'), t('c-an-valeur'), t('c-an-unite')].map(celluleCsv).join(','));
    var unites = {};
    (rapport.metrics || []).forEach(function (m) { unites[m.code] = m.unit; });
    (rapport.rows || []).forEach(function (r) { l.push([r.period, r.metric, r.dimension, libelleDimension(rapport, r.metric, r.dimension), r.value, unites[r.metric] || ''].map(celluleCsv).join(',')); });
    (rapport.derived || []).forEach(function (d) {
      Object.keys(d.values || {}).sort().forEach(function (k) { l.push([d.period, k, '', '', d.values[k], (RATIOS[k] || [''])[0]].map(celluleCsv).join(',')); });
    });
    return '﻿' + l.join('\r\n') + '\r\n';
  }
  function telecharger(nom, contenu) {
    var url = URL.createObjectURL(new Blob([contenu], { type: 'text/csv;charset=utf-8' }));
    var a = document.createElement('a');
    a.href = url; a.download = nom; document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 1000);
  }

  /* --- Les morceaux de l'écran --- */
  function familles(domaines) { return FAMILLES.filter(function (f) { return (domaines || []).indexOf(DOMAINE[f]) >= 0; }); }

  function cartes(k) {
    var html = '';
    familles(k.domains).forEach(function (fam) {
      var def = CARTES[fam];
      html += '<section class="cc-groupe"><h3 class="cc-sous-titre">' + e(t('c-an-f-' + fam)) + '</h3><div class="cc-kpis">';
      def.mesures.forEach(function (m) {
        var u = uniteMesure(m);
        html += '<div class="cc-kpi"><span class="cc-kpi-etiquette">' + e(t('c-an-m-' + m)) + '</span><span class="cc-kpi-valeur">' + e(valeur(k.current && k.current[m], u)) + '</span>' +
          '<span class="cc-petit">' + e(t('c-an-precedente', { valeur: valeur(k.previous && k.previous[m], u) })) + '</span></div>';
      });
      def.ratios.forEach(function (r) {
        html += '<div class="cc-kpi"><span class="cc-kpi-etiquette">' + e(t('c-an-r-' + r)) + '</span><span class="cc-kpi-valeur">' + e(valeur(k.ratios_current && k.ratios_current[r], RATIOS[r][0])) + '</span>' +
          '<span class="cc-petit">' + e(t('c-an-precedente', { valeur: valeur(k.ratios_previous && k.ratios_previous[r], RATIOS[r][0]) })) + '</span></div>';
      });
      html += '</div></section>';
    });
    return html;
  }

  function tableaux(rap) {
    var totaux = {}, derives = {};
    (rap.totals || []).forEach(function (x) { totaux[x.period + '|' + x.metric] = x.value; });
    (rap.derived || []).forEach(function (d) { derives[d.period] = d.values || {}; });
    var periodes = rap.periods || [];
    var parFamille = {};
    (rap.metrics || []).slice().sort(function (x, y) { return rang(x.code) - rang(y.code); }).forEach(function (m) {
      if (DANS_LE_DETAIL.indexOf(m.dimension_kind) >= 0) return;
      (parFamille[m.family] = parFamille[m.family] || []).push(m);
    });
    var entete = '<thead><tr><th scope="col">' + e(t('c-an-mesure')) + '</th>' + periodes.map(function (p) { return '<th scope="col">' + e(nomPeriode(p, rap.grain)) + '</th>'; }).join('') + '</tr></thead>';
    return familles(rap.domains).map(function (fam) {
      var mesures = parFamille[fam] || [];
      var ratios = Object.keys(RATIOS).filter(function (r) { return RATIOS[r][1] === fam && periodes.length && derives[periodes[0]] && (r in derives[periodes[0]]); });
      return '<h3 class="cc-sous-titre">' + e(t('c-an-f-' + fam)) + '</h3><div class="cc-table-zone"><table class="ses-tableau cc-table cc-an-table"><caption class="sr-only">' + e(t('c-an-f-' + fam)) + '</caption>' +
        entete + '<tbody>' +
        mesures.map(function (m) {
          return '<tr><th scope="row" title="' + e(m.definition) + '">' + e(t('c-an-m-' + m.code)) + '</th>' + periodes.map(function (p) {
            var v = totaux[p + '|' + m.code];
            // Un jour calculé sans activité n'a pas de ligne : c'est un vrai zéro. Un stock inconnu arrive « null » de la base : « — ».
            return '<td data-label="' + e(nomPeriode(p, rap.grain)) + '">' + e(valeur(v === undefined ? 0 : v, m.unit)) + '</td>';
          }).join('') + '</tr>';
        }).join('') +
        ratios.map(function (r) {
          return '<tr class="cc-an-derive"><th scope="row">' + e(t('c-an-r-' + r)) + '</th>' + periodes.map(function (p) {
            return '<td data-label="' + e(nomPeriode(p, rap.grain)) + '">' + e(valeur(derives[p] ? derives[p][r] : null, RATIOS[r][0])) + '</td>';
          }).join('') + '</tr>';
        }).join('') + '</tbody></table></div>';
    }).join('');
  }

  /* Le détail du dernier kilomètre, sur toute la période : par chauffeur, par zone, par tournée (réussies, échouées, taux : de la base). */
  function detail(rap) {
    var b = rap.breakdown;
    if (!b) return '';
    return ['driver', 'zone', 'route'].map(function (axe) {
      var lignes = b[axe] || [];
      if (!lignes.length) return '';
      return '<h3 class="cc-sous-titre">' + e(t('c-an-detail-' + axe)) + '</h3><div class="cc-table-zone"><table class="ses-tableau cc-table"><caption class="sr-only">' + e(t('c-an-detail-' + axe)) + '</caption><thead><tr>' +
        ['c-an-col-' + axe, 'c-an-col-reussies', 'c-an-col-echouees', 'c-an-r-delivery_success_pct'].map(function (k) { return '<th scope="col">' + e(t(k)) + '</th>'; }).join('') + '</tr></thead><tbody>' +
        lignes.map(function (x) {
          var nom = x.key === '' ? t('c-an-sans-' + axe) : (x.label || x.key);
          return '<tr><th scope="row">' + e(nom) + (x.key && axe !== 'driver' && x.label ? ' <span class="ses-mono cc-petit">' + e(x.key) + '</span>' : '') + '</th>' +
            '<td data-label="' + e(t('c-an-col-reussies')) + '">' + e(valeur(x.completed, 'count')) + '</td>' +
            '<td data-label="' + e(t('c-an-col-echouees')) + '">' + e(valeur(x.failed, 'count')) + '</td>' +
            '<td data-label="' + e(t('c-an-r-delivery_success_pct')) + '">' + e(valeur(x.success_pct, 'pct')) + '</td></tr>';
        }).join('') + '</tbody></table></div>';
    }).join('');
  }

  /* D'où vient ce rapport : statut, horodatage, version du calcul, empreinte du rapport, exécutions. */
  function entete(rap) {
    var runs = rap.runs || [];
    var classe = rap.status === 'COMPLETE' ? 'ok' : rap.status === 'PROVISIONAL' ? 'info' : 'warn';
    return '<div class="cc-an-entete"><p><span class="ses-pastille ses-pastille-' + classe + '">' + e(t('c-an-st-' + rap.status)) + '</span> ' +
      e(t('c-an-meta', { du: C.jour ? C.jour(rap.from) : rap.from, au: C.jour ? C.jour(rap.to) : rap.to, date: C.date ? C.date(rap.generated_at) : rap.generated_at, version: rap.calc_version })) + '</p>' +
      '<p class="cc-petit">' + e(t('c-an-empreinte-rapport')) + ' <span class="ses-mono">' + e(String(rap.report_checksum || '').slice(0, 16)) + '</span>' +
      (runs.length ? ' · ' + e(t('c-an-source')) + ' ' + runs.map(function (r) {
        return '<span class="ses-mono">n° ' + e(r.run_id) + ' · ' + e(r.calc_version) + ' · ' + e(String(r.checksum || '').slice(0, 8)) + '</span>';
      }).join(', ') : '') + '</p></div>';
  }

  function notes(rap, direction) {
    var html = '';
    var manquants = rap.missing_days || [], anciens = rap.stale_days || [];
    if (manquants.length) {
      html += '<p class="cc-note cc-note-alerte" role="status">' + e(t('c-an-manquants', { nombre: manquants.length })) +
        (direction ? ' <button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-an-calculer>' + e(t('c-an-calculer')) + '</button>' : '') + '</p>';
    }
    if (anciens.length) {
      html += '<p class="cc-note cc-note-alerte" role="status">' + e(t('c-an-anciens', { nombre: anciens.length })) +
        (direction && !manquants.length ? ' <button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-an-calculer>' + e(t('c-an-calculer')) + '</button>' : '') + '</p>';
    }
    if (rap.partial) html += '<p class="cc-note">' + e(t('c-an-provisoire')) + '</p>';
    return html;
  }

  /* Le nom de ce sur quoi porte une alerte : un indicateur dérivé, une mesure, ou un sujet propre aux alertes. */
  function nomSujet(s) { return RATIOS[s] ? t('c-an-r-' + s) : ORDRE.indexOf(s) >= 0 ? t('c-an-m-' + s) : t('c-an-s-' + s); }
  function detailAlerte(a) {
    var d = a.detail || {};
    if (a.code === 'ANOMALY') return t('c-an-a-ecart', { valeur: valeur(d.value, uniteMesure(a.subject)), moyenne: valeur(d.mean, uniteMesure(a.subject)), jours: d.days });
    if (d.count !== undefined) return t('c-an-a-nombre', { nombre: d.count });
    if (a.code === 'REFRESH_NOT_RUN') return d.hours_since_last === null || d.hours_since_last === undefined ? t('c-an-a-jamais') : t('c-an-a-depuis', { heures: valeur(d.hours_since_last, 'count') });
    return '';
  }
  function alertes(liste, direction) {
    var items = (liste && liste.items) || [];
    if (!items.length) return '<p class="cc-rien">' + e(t('c-an-aucune-alerte')) + '</p>';
    return '<ul class="cc-an-alertes">' + items.map(function (a) {
      return '<li class="cc-an-alerte"><span class="ses-pastille ses-pastille-' + (a.severity === 'FAIL' ? 'bad' : 'warn') + '">' + e(t('c-an-a-' + a.code)) + '</span> ' +
        '<strong>' + e(nomSujet(a.subject)) + '</strong>' + (a.day ? ' · ' + e(C.jour ? C.jour(a.day) : a.day) : '') +
        (detailAlerte(a) ? ' · <span class="cc-petit">' + e(detailAlerte(a)) + '</span>' : '') +
        (a.acked_at ? ' <span class="cc-petit">' + e(t('c-an-acquittee')) + (a.note ? ' — ' + e(a.note) : '') + '</span>'
          : direction ? ' <button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-an-acquitter="' + e(a.id) + '">' + e(t('c-an-acquitter')) + '</button>' : '') + '</li>';
    }).join('') + '</ul>';
  }

  function journal(runs, direction) {
    if (!runs || !runs.length) return '<p class="cc-rien">' + e(t('c-an-aucune')) + '</p>';
    return '<div class="cc-table-zone"><table class="ses-tableau cc-table"><caption class="sr-only">' + e(t('c-an-executions')) + '</caption><thead><tr>' +
      ['c-an-col-n', 'c-an-col-periode', 'c-an-col-genere', 'c-an-col-par', 'c-an-col-source', 'c-an-version', 'c-an-statut', 'c-an-col-lignes', 'c-an-col-empreinte'].map(function (k) { return '<th scope="col">' + e(t(k)) + '</th>'; }).join('') +
      (direction ? '<th scope="col"><span class="sr-only">' + e(t('c-an-verifier')) + '</span></th>' : '') + '</tr></thead><tbody>' +
      runs.map(function (r) {
        var verdict = etat.verdicts[r.run_id];
        return '<tr><td data-label="' + e(t('c-an-col-n')) + '">' + e(r.run_id) + '</td>' +
          '<td data-label="' + e(t('c-an-col-periode')) + '">' + e((C.jour ? C.jour(r.period_start) : r.period_start) + ' → ' + (C.jour ? C.jour(r.period_end) : r.period_end)) + '</td>' +
          '<td data-label="' + e(t('c-an-col-genere')) + '">' + e(C.date ? C.date(r.generated_at) : r.generated_at) + '</td>' +
          '<td data-label="' + e(t('c-an-col-par')) + '">' + e(r.generated_by === 'system' ? t('c-an-systeme') : r.generated_by) + '</td>' +
          '<td data-label="' + e(t('c-an-col-source')) + '">' + e(t('c-an-src-' + r.source)) + '</td>' +
          '<td data-label="' + e(t('c-an-version')) + '">' + e(r.calc_version) + (r.current_version ? '' : ' <span class="ses-pastille ses-pastille-warn">' + e(t('c-an-ancienne')) + '</span>') + '</td>' +
          '<td data-label="' + e(t('c-an-statut')) + '"><span class="ses-pastille ses-pastille-' + (r.status === 'COMPLETE' ? 'ok' : 'info') + '">' + e(t('c-an-st-' + r.status)) + '</span>' +
            (r.alerts ? ' <span class="cc-petit">' + e(t('c-an-alertes-levees', { nombre: r.alerts })) + '</span>' : '') + '</td>' +
          '<td data-label="' + e(t('c-an-col-lignes')) + '">' + e(valeur(r.rows, 'count')) + '</td>' +
          '<td data-label="' + e(t('c-an-col-empreinte')) + '"><span class="ses-mono">' + e(String(r.checksum || '').slice(0, 12)) + '</span></td>' +
          (direction ? '<td>' + (verdict ? '<span class="ses-pastille ses-pastille-' + (verdict === 'REPRODUCIBLE' ? 'ok' : 'warn') + '">' + e(t('c-an-v-' + verdict)) + '</span>'
            : '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-an-verifier="' + e(r.run_id) + '">' + e(t('c-an-verifier')) + '</button>') + '</td>' : '') + '</tr>';
      }).join('') + '</tbody></table></div>';
  }

  /* Le PDF : le même rapport, mis en page pour une feuille A4, avec son en-tête de traçabilité. Le navigateur (ou l'application de bureau)
     l'imprime ou l'enregistre « en PDF » : aucune bibliothèque, aucun envoi. */
  function pdf(rap, k) {
    return '<div class="cc-an-pdf" style="font:12px/1.4 system-ui,sans-serif;color:#111">' +
      '<h1 style="font-size:18px;margin:0 0 4px">' + e(t('c-an-pdf-titre', { du: C.jour ? C.jour(rap.from) : rap.from, au: C.jour ? C.jour(rap.to) : rap.to })) + '</h1>' +
      entete(rap) + notes(rap, false) + cartes(k) + tableaux(rap) + detail(rap) +
      '<p class="cc-petit" style="margin-top:12px">' + e(t('c-an-pdf-pied')) + '</p></div>';
  }

  /* --- La section --- */
  var zoneCourante = null, dernierRapport = null, derniersIndicateurs = null;

  function dessiner(zone) {
    zoneCourante = zone;
    var a = C.acces ? C.acces() : null, direction = !!(a && a.direction);
    if (!etat.au) { var b = bornes(etat.rapport, aujourdhui()); etat.du = b.du; etat.au = b.au; }
    zone.innerHTML = '<p class="cc-intro">' + e(t('c-an-intro')) + '</p>' +
      '<form id="cc-an-form" class="cc-form-grille" novalidate>' +
        '<label class="ses-champ" for="cc-an-rapport"><span>' + e(t('c-an-rapport')) + '</span><select id="cc-an-rapport" name="rapport">' +
          RAPPORTS.map(function (r) { return '<option value="' + e(r) + '"' + (r === etat.rapport ? ' selected' : '') + '>' + e(t('c-an-type-' + r)) + '</option>'; }).join('') + '</select></label>' +
        '<label class="ses-champ" for="cc-an-grain"><span>' + e(t('c-an-grain')) + '</span><select id="cc-an-grain" name="grain">' +
          API.GRAINS_ANALYTIQUE.map(function (g) { return '<option value="' + e(g) + '"' + (g === etat.grain ? ' selected' : '') + '>' + e(t('c-an-g-' + g)) + '</option>'; }).join('') + '</select></label>' +
        '<label class="ses-champ" for="cc-an-du"><span>' + e(t('c-an-du')) + '</span><input id="cc-an-du" name="du" type="date" required value="' + e(etat.du) + '"></label>' +
        '<label class="ses-champ" for="cc-an-au"><span>' + e(t('c-an-au')) + '</span><input id="cc-an-au" name="au" type="date" required value="' + e(etat.au) + '"></label>' +
        '<div class="cc-form-actions"><button type="submit" class="ses-bouton ses-bouton-principal ses-bouton-mini">' + e(t('c-an-afficher')) + '</button>' +
        '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-an-exporter>' + e(t('c-an-exporter')) + '</button>' +
        '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-an-pdf>' + e(t('c-an-exporter-pdf')) + '</button>' +
        (direction ? '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-an-recalculer>' + e(t('c-an-recalculer')) + '</button>' : '') + '</div>' +
      '</form>' +
      '<div id="cc-an-msg" class="cc-form-msg" role="alert" hidden></div>' +
      '<h3 class="cc-sous-titre">' + e(t('c-an-alertes')) + '</h3><div id="cc-an-alertes"></div>' +
      '<div id="cc-an-corps"></div>' +
      '<h3 class="cc-sous-titre">' + e(t('c-an-executions')) + '</h3><div id="cc-an-runs"></div>';
    brancher(zone, direction);
    charger(zone, direction);
  }

  function message(zone, texte) {
    var m = zone.querySelector('#cc-an-msg');
    if (!m) return;
    m.hidden = !texte; m.textContent = texte || '';
  }

  function charger(zone, direction) {
    var corps = zone.querySelector('#cc-an-corps');
    C.charger(corps, function () {
      return Promise.all([API.analytique.indicateurs(etat.du, etat.au), API.analytique.rapport(etat.grain, etat.du, etat.au)]);
    }, function (d) {
      derniersIndicateurs = d[0]; dernierRapport = d[1];
      corps.innerHTML = entete(d[1]) + notes(d[1], direction) + cartes(d[0]) + tableaux(d[1]) + detail(d[1]);
    });
    chargerAlertes(zone, direction);
    chargerJournal(zone, direction);
  }
  function chargerAlertes(zone, direction) {
    var z = zone.querySelector('#cc-an-alertes');
    C.charger(z, function () { return API.analytique.alertes(false); }, function (l) { z.innerHTML = alertes(l, direction); }, { silencieux: true });
  }
  function chargerJournal(zone, direction) {
    var z = zone.querySelector('#cc-an-runs');
    C.charger(z, function () { return API.analytique.executions(15); }, function (runs) { z.innerHTML = journal(runs, direction); }, { silencieux: true });
  }

  /* Recalculer une période, au plus tard aujourd'hui (la base refuse l'avenir et plus de 367 jours d'un coup : elle le dit). */
  function recalculer(zone, direction, bouton) {
    var au = etat.au > aujourdhui() ? aujourdhui() : etat.au;
    bouton.disabled = true;
    API.analytique.recalculer(etat.du, au).then(function (r) {
      C.annoncer(t('c-an-recalcul-fait', { numero: r.run_id }), 'succes');
      charger(zone, direction);
    }, function (err) { message(zone, C.message(err)); }).then(function () { bouton.disabled = false; });
  }

  function brancher(zone, direction) {
    var f = zone.querySelector('#cc-an-form');
    // Un rapport type pose ses bornes et son regroupement ; toucher une date ou le regroupement, c'est passer en période personnalisée.
    f.elements.rapport.addEventListener('change', function () {
      var r = f.elements.rapport.value;
      if (r === 'custom') return;
      var b = bornes(r, aujourdhui());
      f.elements.du.value = b.du; f.elements.au.value = b.au; f.elements.grain.value = GRAIN_DU_RAPPORT[r];
    });
    ['du', 'au', 'grain'].forEach(function (n) { f.elements[n].addEventListener('change', function () { f.elements.rapport.value = 'custom'; }); });
    f.addEventListener('submit', function (ev) {
      ev.preventDefault();
      if (!f.elements.du.value || !f.elements.au.value || f.elements.au.value < f.elements.du.value) return message(zone, t('c-an-periode-invalide'));
      message(zone, '');
      etat.rapport = f.elements.rapport.value; etat.grain = f.elements.grain.value; etat.du = f.elements.du.value; etat.au = f.elements.au.value;
      charger(zone, direction);
    });
    zone.addEventListener('click', function (ev) {
      var b;
      if (ev.target.closest('[data-an-exporter]')) {
        if (!dernierRapport) return;
        return telecharger('rapport-' + dernierRapport.grain + '-' + dernierRapport.from + '-' + dernierRapport.to + '.csv', csv(dernierRapport));
      }
      if (ev.target.closest('[data-an-pdf]')) {
        if (!dernierRapport || !derniersIndicateurs || !window.SES_UI) return;
        return window.SES_UI.imprimer(pdf(dernierRapport, derniersIndicateurs), 'a4');
      }
      if ((b = ev.target.closest('[data-an-recalculer]')) || (b = ev.target.closest('[data-an-calculer]'))) return recalculer(zone, direction, b);
      if ((b = ev.target.closest('[data-an-acquitter]'))) {
        b.disabled = true;
        API.analytique.acquitter(b.getAttribute('data-an-acquitter'), '').then(function () {
          C.annoncer(t('c-an-acquittee'), 'succes');
          chargerAlertes(zone, direction);
        }, function (err) { b.disabled = false; message(zone, C.message(err)); });
        return;
      }
      if ((b = ev.target.closest('[data-an-verifier]'))) {
        b.disabled = true;
        API.analytique.verifier(b.getAttribute('data-an-verifier')).then(function (v) {
          etat.verdicts[v.run_id] = v.verdict;
          chargerJournal(zone, direction);
        }, function (err) { b.disabled = false; message(zone, C.message(err)); });
      }
    });
  }

  if (C.enregistrer) {
    C.enregistrer({
      id: 'analytique', ordre: 8, filtres: [],
      // Ouverte dès qu'un domaine est lisible ; la base ne rend ensuite que les mesures de ces domaines.
      ouvrir: function (acces) { return !!(acces && (acces.ops || acces.finance || acces.customers)); },
      rendre: function (zone) { dessiner(zone); },
      actualiser: function (zone, st, ctx, silencieux) { if (zoneCourante === zone && silencieux) return; dessiner(zone); }
    });
  }

  C.analytique = { ORDRE: ORDRE, CARTES: CARTES, RATIOS: RATIOS, FAMILLES: FAMILLES, RAPPORTS: RAPPORTS, csv: csv, valeur: valeur, nomPeriode: nomPeriode, bornes: bornes,
                   cartes: cartes, tableaux: tableaux, detail: detail, entete: entete, notes: notes, alertes: alertes, journal: journal, pdf: pdf, nomSujet: nomSujet, etat: etat };
})();
