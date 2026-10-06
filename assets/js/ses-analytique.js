/* ==========================================================================
   Speed Express Shipping — l'analytique du centre de commande (phase 16, ADR 0014)
   --------------------------------------------------------------------------
   Rapports du jour à l'année, indicateurs de la période et de la précédente,
   et la traçabilité : de quelles exécutions viennent les chiffres, quels jours
   n'ont jamais été calculés, et la vérification qu'un calcul passé se refait à
   l'identique.

   Aucun chiffre n'est calculé ici, pas même une addition : les totaux par
   période, les taux et les délais viennent de la base (SES_API.analytique,
   public.lg_an_*). L'écran ne fait que choisir, mettre en forme et exporter.
   ========================================================================== */
(function () {
  'use strict';

  var C = window.SES_CENTRE = window.SES_CENTRE || {};
  var API = window.SES_API;
  var t = function (k, v) { return C.t ? C.t(k, v) : k; };
  var e = function (x) { return C.e ? C.e(x) : String(x); };

  /* Les cartes du haut, par domaine : les mesures qui se lisent d'un coup d'œil, puis les rapports calculés par la base. */
  var CARTES = {
    ops: { mesures: ['parcels_received', 'parcels_delivered', 'tasks_completed', 'incidents_opened'], ratios: ['delivery_success_pct', 'avg_transit_hours', 'scan_rejection_pct'] },
    finance: { mesures: ['revenue_net_usd', 'payments_usd', 'refunds_usd'], ratios: ['collection_pct'] },
    customers: { mesures: ['customers_new', 'tickets_opened'], ratios: [] }
  };
  /* L'ordre de lecture des lignes : le chemin d'un colis, puis les missions, l'entrepôt, les incidents ; l'argent ; la clientèle. */
  var ORDRE = ['parcels_received', 'parcels_on_hold', 'parcels_delivered', 'parcels_damaged', 'parcels_lost', 'parcels_returned', 'transit_hours_sum', 'transit_count',
               'shipments_dispatched', 'shipments_arrived', 'tasks_completed', 'tasks_failed', 'scans_total', 'scans_rejected', 'incidents_opened',
               'revenue_net_usd', 'revenue_tax_usd', 'payments_usd', 'payments_count', 'refunds_usd', 'customers_new', 'tickets_opened'];
  function rang(code) { var i = ORDRE.indexOf(code); return i < 0 ? ORDRE.length : i; }
  var UNITES_RATIO = { delivery_success_pct: 'pct', avg_transit_hours: 'hours', scan_rejection_pct: 'pct', collection_pct: 'pct' };

  var etat = { grain: 'month', du: null, au: null, verdicts: {} };

  function locale() { return ({ fr: 'fr-FR', en: 'en-US', es: 'es-ES', ht: 'fr-HT' })[(document.documentElement.lang || 'fr').slice(0, 2)] || 'fr-FR'; }
  function aujourdhui() { var a = C.acces && C.acces(); return (a && a.today) || new Date().toISOString().slice(0, 10); }

  /* Une valeur selon son unité. null : la base n'a pas pu la calculer (division par zéro) — on l'écrit « — », jamais « 0 ». */
  function valeur(v, unite) {
    if (v === null || v === undefined || v === '') return '—';
    var n = Number(v);
    if (unite === 'usd') return C.montant ? C.montant(n, 'USD') : String(n);
    if (unite === 'pct') return n.toLocaleString(locale(), { maximumFractionDigits: 1 }) + ' %';
    if (unite === 'hours') return n.toLocaleString(locale(), { maximumFractionDigits: 1 }) + ' h';
    return n.toLocaleString(locale(), { maximumFractionDigits: 2 });
  }

  /* Le nom d'une période, selon le grain (le calcul de la période elle-même vient de la base). */
  function nomPeriode(iso, grain) {
    var d = new Date(iso + 'T12:00:00');
    if (grain === 'day') return C.jour ? C.jour(iso) : iso;
    if (grain === 'week') return t('c-an-semaine', { date: C.jour ? C.jour(iso) : iso });
    if (grain === 'month') return d.toLocaleDateString(locale(), { month: 'long', year: 'numeric' });
    if (grain === 'quarter') return t('c-an-trimestre', { numero: Math.floor(d.getMonth() / 3) + 1, annee: d.getFullYear() });
    return String(d.getFullYear());
  }

  function celluleCsv(v) {
    var s = v === null || v === undefined ? '' : String(v);
    if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
    return '"' + s.replace(/"/g, '""') + '"';
  }
  /* Le CSV d'un rapport : les lignes telles que la base les rend (période, mesure, dimension, valeur), avec un en-tête traduit. */
  function csv(rapport) {
    var lignes = [[t('c-an-col-periode'), t('c-an-mesure'), t('c-an-dimension'), t('c-an-valeur'), t('c-an-unite')].map(celluleCsv).join(',')];
    var unites = {};
    (rapport.metrics || []).forEach(function (m) { unites[m.code] = m.unit; });
    (rapport.rows || []).forEach(function (r) { lignes.push([r.period, r.metric, r.dimension, r.value, unites[r.metric] || ''].map(celluleCsv).join(',')); });
    return '﻿' + lignes.join('\r\n') + '\r\n';
  }
  function telecharger(nom, contenu) {
    var url = URL.createObjectURL(new Blob([contenu], { type: 'text/csv;charset=utf-8' }));
    var a = document.createElement('a');
    a.href = url; a.download = nom; document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 1000);
  }

  /* --- Les morceaux de l'écran --- */
  function cartes(k) {
    var html = '';
    (k.domains || []).forEach(function (dom) {
      var def = CARTES[dom];
      if (!def) return;
      html += '<section class="cc-groupe"><h3 class="cc-sous-titre">' + e(t('c-an-d-' + dom)) + '</h3><div class="cc-kpis">';
      def.mesures.forEach(function (m) {
        var unite = /_usd$/.test(m) ? 'usd' : 'count';
        html += '<div class="cc-kpi"><span class="cc-kpi-etiquette">' + e(t('c-an-m-' + m)) + '</span><span class="cc-kpi-valeur">' + e(valeur(k.current && k.current[m], unite)) + '</span>' +
          '<span class="cc-petit">' + e(t('c-an-precedente', { valeur: valeur(k.previous && k.previous[m], unite) })) + '</span></div>';
      });
      def.ratios.forEach(function (r) {
        html += '<div class="cc-kpi"><span class="cc-kpi-etiquette">' + e(t('c-an-r-' + r)) + '</span><span class="cc-kpi-valeur">' + e(valeur(k.ratios_current && k.ratios_current[r], UNITES_RATIO[r])) + '</span>' +
          '<span class="cc-petit">' + e(t('c-an-precedente', { valeur: valeur(k.ratios_previous && k.ratios_previous[r], UNITES_RATIO[r]) })) + '</span></div>';
      });
      html += '</div></section>';
    });
    return html;
  }

  function tableaux(rap) {
    var totaux = {};
    (rap.totals || []).forEach(function (x) { totaux[x.period + '|' + x.metric] = x.value; });
    var periodes = rap.periods || [];
    var parDomaine = {};
    (rap.metrics || []).slice().sort(function (x, y) { return rang(x.code) - rang(y.code); }).forEach(function (m) { (parDomaine[m.domain] = parDomaine[m.domain] || []).push(m); });
    return (rap.domains || []).map(function (dom) {
      var mesures = parDomaine[dom] || [];
      return '<h3 class="cc-sous-titre">' + e(t('c-an-d-' + dom)) + '</h3><div class="cc-table-zone"><table class="ses-tableau cc-table cc-an-table"><caption class="sr-only">' + e(t('c-an-d-' + dom)) + '</caption>' +
        '<thead><tr><th scope="col">' + e(t('c-an-mesure')) + '</th>' + periodes.map(function (p) { return '<th scope="col">' + e(nomPeriode(p, rap.grain)) + '</th>'; }).join('') + '</tr></thead><tbody>' +
        mesures.map(function (m) {
          return '<tr><th scope="row">' + e(t('c-an-m-' + m.code)) + '</th>' + periodes.map(function (p) {
            var v = totaux[p + '|' + m.code];
            // Un jour calculé sans activité n'a pas de ligne : c'est un vrai zéro (les jours jamais calculés sont signalés au-dessus).
            return '<td data-label="' + e(nomPeriode(p, rap.grain)) + '">' + e(valeur(v === undefined ? 0 : v, m.unit)) + '</td>';
          }).join('') + '</tr>';
        }).join('') + '</tbody></table></div>';
    }).join('');
  }

  function notes(rap, direction) {
    var html = '';
    var manquants = rap.missing_days || [];
    if (manquants.length) {
      html += '<p class="cc-note cc-note-alerte" role="status">' + e(t('c-an-manquants', { nombre: manquants.length })) +
        (direction ? ' <button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-an-calculer>' + e(t('c-an-calculer')) + '</button>' : '') + '</p>';
    }
    if (rap.partial) html += '<p class="cc-note">' + e(t('c-an-provisoire')) + '</p>';
    var runs = rap.runs || [];
    if (runs.length) {
      html += '<p class="cc-petit">' + e(t('c-an-source')) + ' ' + runs.map(function (r) { return '<span class="ses-mono">n° ' + e(r.run_id) + ' · ' + e(String(r.checksum || '').slice(0, 8)) + '</span>'; }).join(', ') + '</p>';
    }
    return html;
  }

  function journal(runs, direction) {
    if (!runs || !runs.length) return '<p class="cc-rien">' + e(t('c-an-aucune')) + '</p>';
    return '<div class="cc-table-zone"><table class="ses-tableau cc-table"><caption class="sr-only">' + e(t('c-an-executions')) + '</caption><thead><tr>' +
      ['c-an-col-n', 'c-an-col-periode', 'c-an-col-genere', 'c-an-col-par', 'c-an-col-lignes', 'c-an-col-empreinte'].map(function (k) { return '<th scope="col">' + e(t(k)) + '</th>'; }).join('') +
      (direction ? '<th scope="col"><span class="sr-only">' + e(t('c-an-verifier')) + '</span></th>' : '') + '</tr></thead><tbody>' +
      runs.map(function (r) {
        var verdict = etat.verdicts[r.run_id];
        return '<tr><td data-label="' + e(t('c-an-col-n')) + '">' + e(r.run_id) + '</td>' +
          '<td data-label="' + e(t('c-an-col-periode')) + '">' + e((C.jour ? C.jour(r.period_start) : r.period_start) + ' → ' + (C.jour ? C.jour(r.period_end) : r.period_end)) + (r.partial ? ' <span class="ses-pastille ses-pastille-warn">' + e(t('c-an-provisoire-court')) + '</span>' : '') + '</td>' +
          '<td data-label="' + e(t('c-an-col-genere')) + '">' + e(C.date ? C.date(r.generated_at) : r.generated_at) + '</td>' +
          '<td data-label="' + e(t('c-an-col-par')) + '">' + e(r.generated_by === 'system' ? t('c-an-systeme') : r.generated_by) + '</td>' +
          '<td data-label="' + e(t('c-an-col-lignes')) + '">' + e(valeur(r.rows, 'count')) + '</td>' +
          '<td data-label="' + e(t('c-an-col-empreinte')) + '"><span class="ses-mono">' + e(String(r.checksum || '').slice(0, 12)) + '</span></td>' +
          (direction ? '<td>' + (verdict ? '<span class="ses-pastille ses-pastille-' + (verdict === 'REPRODUCIBLE' ? 'ok' : 'warn') + '">' + e(t('c-an-v-' + verdict)) + '</span>'
            : '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-an-verifier="' + e(r.run_id) + '">' + e(t('c-an-verifier')) + '</button>') + '</td>' : '') + '</tr>';
      }).join('') + '</tbody></table></div>';
  }

  /* --- La section --- */
  var zoneCourante = null, dernierRapport = null;

  function dessiner(zone) {
    zoneCourante = zone;
    var a = C.acces ? C.acces() : null, direction = !!(a && a.direction);
    if (!etat.au) { etat.au = aujourdhui(); etat.du = etat.au.slice(0, 4) + '-01-01'; }
    zone.innerHTML = '<p class="cc-intro">' + e(t('c-an-intro')) + '</p>' +
      '<form id="cc-an-form" class="cc-form-grille" novalidate>' +
        '<label class="ses-champ" for="cc-an-grain"><span>' + e(t('c-an-grain')) + '</span><select id="cc-an-grain" name="grain">' +
          API.GRAINS_ANALYTIQUE.map(function (g) { return '<option value="' + e(g) + '"' + (g === etat.grain ? ' selected' : '') + '>' + e(t('c-an-g-' + g)) + '</option>'; }).join('') + '</select></label>' +
        '<label class="ses-champ" for="cc-an-du"><span>' + e(t('c-an-du')) + '</span><input id="cc-an-du" name="du" type="date" required value="' + e(etat.du) + '"></label>' +
        '<label class="ses-champ" for="cc-an-au"><span>' + e(t('c-an-au')) + '</span><input id="cc-an-au" name="au" type="date" required value="' + e(etat.au) + '"></label>' +
        '<div class="cc-form-actions"><button type="submit" class="ses-bouton ses-bouton-principal ses-bouton-mini">' + e(t('c-an-afficher')) + '</button>' +
        '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-an-exporter>' + e(t('c-an-exporter')) + '</button>' +
        (direction ? '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-an-recalculer>' + e(t('c-an-recalculer')) + '</button>' : '') + '</div>' +
      '</form>' +
      '<div id="cc-an-msg" class="cc-form-msg" role="alert" hidden></div>' +
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
      dernierRapport = d[1];
      corps.innerHTML = notes(d[1], direction) + cartes(d[0]) + tableaux(d[1]);
    });
    chargerJournal(zone, direction);
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
    zone.querySelector('#cc-an-form').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var f = ev.target;
      if (!f.elements.du.value || !f.elements.au.value || f.elements.au.value < f.elements.du.value) return message(zone, t('c-an-periode-invalide'));
      message(zone, '');
      etat.grain = f.elements.grain.value; etat.du = f.elements.du.value; etat.au = f.elements.au.value;
      charger(zone, direction);
    });
    zone.addEventListener('click', function (ev) {
      var b;
      if (ev.target.closest('[data-an-exporter]')) {
        if (!dernierRapport) return;
        return telecharger('rapport-' + dernierRapport.grain + '-' + dernierRapport.from + '-' + dernierRapport.to + '.csv', csv(dernierRapport));
      }
      if ((b = ev.target.closest('[data-an-recalculer]')) || (b = ev.target.closest('[data-an-calculer]'))) return recalculer(zone, direction, b);
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

  C.analytique = { ORDRE: ORDRE, csv: csv, valeur: valeur, nomPeriode: nomPeriode, cartes: cartes, tableaux: tableaux, notes: notes, journal: journal, etat: etat, CARTES: CARTES };
})();
