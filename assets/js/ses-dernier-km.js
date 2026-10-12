/* ==========================================================================
   Speed Express Shipping — le dernier kilomètre, dans le centre de commande (phase 5)
   --------------------------------------------------------------------------
   Le tableau temps réel de la livraison : missions du jour par état, livraisons
   en cours, chauffeurs actifs (disponibilité, véhicule, charge, position),
   échecs du jour, incidents ouverts, respect des délais (SLA) et preuves de
   livraison manquantes. Un bouton propose d'affecter automatiquement la journée.

   Tout vient de public.lg_cc_last_mile (017-dernier-kilometre-complet.sql) :
   l'écran ne compte rien, n'additionne rien, ne juge rien (la cible du SLA et
   son verdict viennent de la base). Il se relit seul, comme tout le centre, à
   chaque signal temps réel (un chauffeur accepte, une remise est enregistrée…)
   et avec l'actualisation automatique.
   ========================================================================== */
(function () {
  'use strict';

  var C = window.SES_CENTRE = window.SES_CENTRE || {};
  var API = window.SES_API;
  var t = function (k, v) { return C.t ? C.t(k, v) : k; };
  var e = function (x) { return C.e ? C.e(x) : String(x); };
  var date = function (iso) { return C.date ? C.date(iso) : (iso || '—'); };
  var pastille = function (cle, code) { return C.pastille ? C.pastille(cle, code) : e(code); };

  function locale() { return ({ fr: 'fr-FR', en: 'en-US', es: 'es-ES', ht: 'fr-HT' })[(document.documentElement.lang || 'fr').slice(0, 2)] || 'fr-FR'; }
  function nombre(v) { return v === null || v === undefined ? '—' : Number(v).toLocaleString(locale(), { maximumFractionDigits: 1 }); }
  function taux(v) { return v === null || v === undefined ? t('c-dk-sans-objet') : (Number(v) * 100).toLocaleString(locale(), { maximumFractionDigits: 1 }) + ' %'; }

  function carte(etiquette, valeur, detail) {
    return '<li><div class="cc-kpi"><span class="cc-kpi-etiquette">' + e(etiquette) + '</span><strong class="cc-kpi-valeur">' + e(valeur) + '</strong>' +
      (detail ? '<span class="cc-petit">' + e(detail) + '</span>' : '') + '</div></li>';
  }
  function groupe(id, titreCle, cartes) {
    return '<section class="cc-groupe" aria-labelledby="cc-dk-' + id + '"><h3 id="cc-dk-' + id + '">' + e(t(titreCle)) + '</h3><ul class="cc-kpis">' + cartes.join('') + '</ul></section>';
  }
  function tableau(legendeCle, colonnes, lignes, videCle) {
    if (!lignes.length) return '<p class="cc-rien">' + e(t(videCle)) + '</p>';
    return '<div class="cc-table-zone"><table class="ses-tableau cc-table"><caption class="sr-only">' + e(t(legendeCle)) + '</caption><thead><tr>' +
      colonnes.map(function (k) { return '<th scope="col">' + e(t(k)) + '</th>'; }).join('') + '</tr></thead><tbody>' +
      lignes.map(function (cellules) {
        return '<tr>' + cellules.map(function (c, i) {
          return i === 0 ? '<th scope="row">' + c + '</th>' : '<td data-label="' + e(t(colonnes[i])) + '">' + c + '</td>';
        }).join('') + '</tr>';
      }).join('') + '</tbody></table></div>';
  }
  function genre(k) { return t(k === 'PICKUP' ? 'c-dk-enlevement' : 'c-dk-livraison'); }
  function ref(id) { return '<span class="ses-mono">' + e(String(id || '').slice(0, 8).toUpperCase()) + '</span>'; }

  function dessiner(zone, d, message) {
    var m = d.tasks, s = d.sla, ch = d.drivers, inc = d.incidents, pod = d.missing_pod;
    var html = '<p class="cc-intro">' + e(t('c-dk-intro')) + '</p>' +
      '<div class="cc-form-actions" style="margin:0 0 14px"><p class="cc-petit" style="margin:0">' + e(t('c-dk-jour', { date: C.jour ? C.jour(d.date) : d.date })) + '</p>' +
      '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-dk="affecter">' + e(t('c-dk-affecter')) + '</button></div>' +
      '<p class="cc-form-msg" role="status" data-dk="message"' + (message ? '' : ' hidden') + '>' + e(message || '') + '</p>';

    html += groupe('missions', 'c-dk-g-missions', [
      carte(t('c-dk-total'), nombre(m.total), t('c-dk-livraison') + ' ' + nombre(m.deliveries) + ' · ' + t('c-dk-enlevement') + ' ' + nombre(m.pickups)),
      carte(t('c-dk-non-affectees'), nombre(m.unassigned)),
      carte(t('c-miss-STARTED'), nombre(m.by_status.STARTED)),
      carte(t('c-dk-terminees'), nombre(m.by_status.COMPLETED)),
      carte(t('c-dk-echouees'), nombre(m.by_status.FAILED)),
      carte(t('c-dk-en-retard'), nombre(m.late))]);

    html += groupe('sla', 'c-dk-g-sla', [
      carte(t('c-dk-a-l-heure'), taux(s.on_time_rate), t('c-dk-cible', { cible: taux(s.target) }) + (s.met === null || s.met === undefined ? '' : ' · ' + t(s.met ? 'c-dk-cible-atteinte' : 'c-dk-cible-manquee'))),
      carte(t('c-dk-reussite'), taux(s.success_rate)),
      carte(t('c-dk-premier'), taux(s.first_attempt_rate)),
      carte(t('c-dk-livrees'), nombre(s.completed)),
      carte(t('c-dk-livrees-tard'), nombre(s.late_completed))]);

    html += groupe('chauffeurs', 'c-dk-g-chauffeurs', [
      carte(t('c-dk-actifs'), nombre(ch.active)), carte(t('c-dk-disponibles'), nombre(ch.available_today)), carte(t('c-dk-en-service'), nombre(ch.on_duty))]);
    html += tableau('c-dk-g-chauffeurs', ['c-dk-col-chauffeur', 'c-dk-col-vehicule', 'c-dk-col-jour', 'c-dk-col-charge', 'c-dk-col-position'],
        ch.items.map(function (x) {
          var v = x.vehicle;
          return [e(x.name) + (x.on_duty ? ' ' + pastille('c-dk-en-service', 'ACTIVE') : ''),
                  v ? e(v.plate) + ' ' + pastille('c-veh-' + v.status, v.status === 'ACTIVE' ? 'ACTIVE' : 'ON_LEAVE') : '—',
                  e(nombre(x.completed_today) + ' / ' + nombre(x.failed_today) + ' / ' + nombre(x.tasks_today)),
                  e(nombre(x.load_lb) + ' lb' + (v ? ' / ' + nombre(v.capacity_lb) + ' lb' : '') + ' · ' + nombre(x.open) + ' / ' + nombre(x.max_stops)),
                  e(x.position_age_min === null || x.position_age_min === undefined ? t('c-dk-jamais') : t('c-dk-minutes', { n: nombre(x.position_age_min) }))];
        }), 'c-dk-aucun-chauffeur');

    html += '<h3 class="cc-sous-titre">' + e(t('c-dk-g-cours')) + '</h3>' +
      tableau('c-dk-g-cours', ['c-dk-col-mission', 'c-dk-col-adresse', 'c-dk-col-chauffeur', 'c-dk-col-depuis', 'c-dk-col-fin', 'c-dk-col-colis'],
        d.in_progress.map(function (x) {
          return [ref(x.task_id) + ' ' + e(genre(x.kind)) + (x.late ? ' ' + pastille('c-dk-retard', 'OVERDUE') : ''), e(x.address), e(x.driver || '—'), e(date(x.started_at)),
                  e(x.window_end ? date(x.window_end) : '—'), e(nombre(x.parcels))];
        }), 'c-dk-aucune-cours');


    html += '<h3 class="cc-sous-titre">' + e(t('c-dk-g-echecs')) + ' (' + e(nombre(d.failed.count)) + ')</h3>' +
      tableau('c-dk-g-echecs', ['c-dk-col-mission', 'c-dk-col-quand', 'c-dk-col-motif', 'c-dk-col-chauffeur', 'c-dk-col-maintenant'],
        d.failed.items.map(function (x) {
          return [ref(x.task_id) + ' ' + e(x.address), e(date(x.at)), e(t('c-inc-' + x.reason) || x.reason || '—'), e(x.driver || '—'), pastille('c-miss-' + x.now, x.now)];
        }), 'c-dk-aucun-echec');

    html += groupe('incidents', 'c-dk-g-incidents', [carte(t('c-dk-g-incidents'), nombre(inc.open)), carte(t('c-dk-graves'), nombre(inc.high))].concat(
      Object.keys(inc.by_type).sort().map(function (k) { return carte(t('c-inc-' + k) || k, nombre(inc.by_type[k])); })));
    html += tableau('c-dk-g-incidents', ['c-dk-col-numero', 'c-dk-col-genre', 'c-dk-col-gravite', 'c-dk-col-quand'],
      inc.recent.map(function (x) {
        return ['<span class="ses-mono">' + e(x.tracking_number || '—') + '</span>', e(t('c-inc-' + x.type) || x.type), pastille('c-grav-' + x.severity, x.severity === 'HIGH' ? 'OVERDUE' : 'PENDING'), e(date(x.at))];
      }), 'c-dk-aucun-incident');

    html += groupe('preuves', 'c-dk-g-preuves', [carte(t('c-dk-derogations'), nombre(pod.derogations_today), t('c-dk-derogations-30') + ' : ' + nombre(pod.derogations_30_days)),
                                                 carte(t('c-dk-anomalies'), nombre(pod.anomalies + pod.completed_tasks_without_proof))]);
    html += tableau('c-dk-g-preuves', ['c-dk-col-numero', 'c-dk-col-quand', 'c-dk-col-motif'],
      pod.items.map(function (x) { return ['<span class="ses-mono">' + e(x.tracking_number) + '</span>', e(date(x.at)), e(x.reason || '—')]; }), 'c-dk-aucune-derogation');

    zone.innerHTML = html;
    var b = zone.querySelector('[data-dk="affecter"]');
    if (b) b.addEventListener('click', function () { affecter(zone, d.date, b); });
  }

  function affecter(zone, jour, bouton) {
    bouton.disabled = true;
    API.dernierKm.affecterJournee(jour).then(function (r) {
      charger(zone, null, null, true, t('c-dk-affecte', { n: nombre(r.assigned), reste: nombre((r.unassigned || []).length) }));
    }, function (err) {
      bouton.disabled = false;
      var z = zone.querySelector('[data-dk="message"]');
      if (z) z.textContent = (window.SES_UI && window.SES_UI.messageErreur) ? window.SES_UI.messageErreur(err) : String(err && err.message || err);
    });
  }

  function charger(zone, st, ctx, silencieux, message) {
    return C.charger(zone, function () { return API.dernierKm.tableau(); }, function (d) { dessiner(zone, d, message); }, { silencieux: silencieux });
  }

  if (C.enregistrer) {
    C.enregistrer({
      id: 'dernierkm', ordre: 95, filtres: [],
      // Ouverte à qui lit les colis (la base le revérifie à chaque appel).
      ouvrir: function (acces) { return !!(acces && acces.ops); },
      rendre: function (zone, st, ctx) { charger(zone, st, ctx, false); },
      actualiser: function (zone, st, ctx, silencieux) { return charger(zone, st, ctx, silencieux); }
    });
  }

  C.dernierKm = { dessiner: dessiner };
})();
