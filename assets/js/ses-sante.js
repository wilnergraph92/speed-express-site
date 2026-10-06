/* ==========================================================================
   Speed Express Shipping — la santé du système, dans le centre de commande (phase 17, ADR 0015)
   --------------------------------------------------------------------------
   Pour la direction : l'état général, chaque contrôle avec sa valeur, ses
   seuils et son verdict (OK, alerte, échec), le dernier battement de cœur de
   chaque travail planifié (sauvegarde, vérification de restauration,
   notifications, analytique) et les dernières erreurs remontées par les
   navigateurs, déjà nettoyées par la base.

   Tout vient de public.lg_ops_status (013-exploitation.sql) : l'écran ne juge
   rien, il affiche les verdicts de la base. Il se relit avec l'actualisation
   automatique du centre (lecture seule : rien à perdre).
   ========================================================================== */
(function () {
  'use strict';

  var C = window.SES_CENTRE = window.SES_CENTRE || {};
  var API = window.SES_API;
  var t = function (k, v) { return C.t ? C.t(k, v) : k; };
  var e = function (x) { return C.e ? C.e(x) : String(x); };
  var GENRE = { OK: 'ok', WARN: 'warn', FAIL: 'bad' };

  function locale() { return ({ fr: 'fr-FR', en: 'en-US', es: 'es-ES', ht: 'fr-HT' })[(document.documentElement.lang || 'fr').slice(0, 2)] || 'fr-FR'; }
  function pastille(statut) { return '<span class="ses-pastille ses-pastille-' + (GENRE[statut] || 'neutre') + '">' + e(t('c-sa-s-' + statut) || statut) + '</span>'; }
  function nombre(v, unite) {
    if (v === null || v === undefined) return '—';
    return Number(v).toLocaleString(locale(), { maximumFractionDigits: 1 }) + (unite && unite !== 'count' && unite !== 'level' ? ' ' + t('c-sa-u-' + unite) : '');
  }

  function controles(etat) {
    return '<div class="cc-table-zone"><table class="ses-tableau cc-table"><caption class="sr-only">' + e(t('c-sa-controles')) + '</caption><thead><tr>' +
      ['c-sa-col-controle', 'c-sa-col-etat', 'c-sa-col-valeur', 'c-sa-col-seuils'].map(function (k) { return '<th scope="col">' + e(t(k)) + '</th>'; }).join('') + '</tr></thead><tbody>' +
      (etat.checks || []).map(function (c) {
        var seuils = c.warn_at === null || c.warn_at === undefined ? '—' : t('c-sa-seuils', { alerte: nombre(c.warn_at, c.unit), echec: nombre(c.fail_at, c.unit) });
        return '<tr><th scope="row">' + e(t('c-sa-c-' + c.code)) + '</th><td data-label="' + e(t('c-sa-col-etat')) + '">' + pastille(c.status) + '</td>' +
          '<td data-label="' + e(t('c-sa-col-valeur')) + '">' + e(c.detail === 'never' ? t('c-sa-jamais') : nombre(c.value, c.unit)) + '</td>' +
          '<td data-label="' + e(t('c-sa-col-seuils')) + '">' + e(seuils) + '</td></tr>';
      }).join('') + '</tbody></table></div>';
  }

  function battements(etat) {
    var l = etat.heartbeats || [];
    if (!l.length) return '<p class="cc-rien">' + e(t('c-sa-aucun-battement')) + '</p>';
    return '<ul class="cc-sous-liste">' + l.map(function (h) {
      return '<li>' + e(t('c-sa-h-' + h.source)) + ' · ' + pastille(h.status) + ' · ' + e(C.date ? C.date(h.reported_at) : h.reported_at) + '</li>';
    }).join('') + '</ul>';
  }

  function erreurs(etat) {
    var l = etat.recent_client_errors || [];
    if (!l.length) return '<p class="cc-rien">' + e(t('c-sa-aucune-erreur')) + '</p>';
    return '<div class="cc-table-zone"><table class="ses-tableau cc-table"><caption class="sr-only">' + e(t('c-sa-erreurs')) + '</caption><thead><tr>' +
      ['c-sa-col-quand', 'c-sa-col-page', 'c-sa-col-message', 'c-sa-col-ref'].map(function (k) { return '<th scope="col">' + e(t(k)) + '</th>'; }).join('') + '</tr></thead><tbody>' +
      l.map(function (x) {
        return '<tr><td data-label="' + e(t('c-sa-col-quand')) + '">' + e(C.date ? C.date(x.reported_at) : x.reported_at) + '</td><td data-label="' + e(t('c-sa-col-page')) + '"><span class="ses-mono">' + e(x.page) + '</span></td>' +
          '<td data-label="' + e(t('c-sa-col-message')) + '">' + e(x.message) + (x.source ? ' <span class="cc-petit ses-mono">' + e(x.source) + '</span>' : '') + '</td>' +
          '<td data-label="' + e(t('c-sa-col-ref')) + '"><span class="ses-mono">' + e(x.request_id) + '</span></td></tr>';
      }).join('') + '</tbody></table></div>';
  }

  function dessiner(zone, etat) {
    zone.innerHTML = '<p class="cc-intro">' + e(t('c-sa-intro')) + '</p>' +
      '<p class="cc-poste-dernier ' + (etat.overall === 'OK' ? 'cc-poste-ok' : 'cc-poste-ko') + '" role="status">' + e(t('c-sa-general', { etat: t('c-sa-s-' + etat.overall) })) + '</p>' +
      '<p class="cc-petit">' + e(t('c-sa-genere', { date: C.date ? C.date(etat.generated_at) : etat.generated_at, niveau: etat.schema_level })) + '</p>' +
      '<h3 class="cc-sous-titre">' + e(t('c-sa-controles')) + '</h3>' + controles(etat) +
      '<h3 class="cc-sous-titre">' + e(t('c-sa-battements')) + '</h3>' + battements(etat) +
      '<h3 class="cc-sous-titre">' + e(t('c-sa-erreurs')) + '</h3>' + erreurs(etat);
  }

  function charger(zone, st, ctx, silencieux) {
    return C.charger(zone, function () { return API.exploitation.etat(); }, function (etat) { dessiner(zone, etat); }, { silencieux: silencieux });
  }

  if (C.enregistrer) {
    C.enregistrer({
      id: 'sante', ordre: 195, filtres: [],
      ouvrir: function (acces) { return !!(acces && acces.direction); },
      rendre: function (zone, st, ctx) { charger(zone, st, ctx, false); },
      actualiser: charger
    });
  }

  C.sante = { controles: controles, battements: battements, erreurs: erreurs, dessiner: dessiner, nombre: nombre };
})();
