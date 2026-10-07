/* ==========================================================================
   Speed Express Shipping — les pré-alertes, dans le tableau de bord
   --------------------------------------------------------------------------
   Le client annonce un achat depuis l'application (magasin, contenu, numéro
   de suivi du magasin) ; l'équipe le retrouve ici, le marque reçu quand le
   carton arrive à Miami, ou annulé. L'onglet n'apparaît qu'à un membre de
   l'équipe qui a le droit « colis.lire », et seulement si la base connaît les
   pré-alertes (outils/supabase-maj-prix-prealertes.sql passé). Les boutons de
   traitement demandent « colis.statut » ou « colis.modifier » ; la base refait
   ces contrôles, et ce sont les siens qui font foi.
   ========================================================================== */
(function () {
  'use strict';

  var API = window.SES_API;
  var UI = window.SES_UI;
  if (!API || !UI || !API.prealertes || !document.getElementById('ses-p-prealertes')) return;

  var PAR_PAGE = window.SES_REGLAGES ? window.SES_REGLAGES.lire().lignes : 25;
  var COULEURS = { attendue: ['#fff7e6', '#b45309'], recue: ['#e9f8ec', '#0b7a19'], annulee: ['#f1f2f4', '#5b6470'] };
  var etat = { page: 0, statut: 'attendue', recherche: '', total: 0, lignes: [], peutTraiter: false, charge: false };

  function $(s) { return document.querySelector(s); }
  function e(v) { return UI.echapper(v); }

  function pastille(statut) {
    var c = COULEURS[statut] || COULEURS.annulee;
    return '<span style="display:inline-block;padding:3px 10px;border-radius:999px;font-size:12.5px;font-weight:700;' +
      'background:' + c[0] + ';color:' + c[1] + '">' + e(UI.t('pa-statut-' + statut)) + '</span>';
  }

  function filtres() {
    var zone = $('#ses-filtres-prealertes');
    zone.innerHTML = [''].concat(API.STATUTS_PREALERTE).map(function (s) {
      var actif = s === etat.statut;
      return '<button type="button" class="ses-filtre" aria-pressed="' + actif + '" data-statut="' + s + '">' +
        e(s ? UI.t('pa-statut-' + s) : UI.t('pa-toutes')) + '</button>';
    }).join('');
  }

  function liste() {
    var zone = $('#ses-liste-prealertes');
    if (!etat.lignes.length) {
      zone.innerHTML = '<div class="ses-bloc">' + UI.vide(UI.t('pa-vide'), '◻') + '</div>';
      $('#ses-pages-prealertes').innerHTML = '';
      return;
    }
    var entetes = ['pa-col-date', 'pa-col-client', 'pa-col-achat', 'pa-col-suivi', 'pa-col-valeur', 'pa-col-statut'];
    zone.innerHTML = '<table class="ses-tableau"><thead><tr>' +
      entetes.map(function (k) { return '<th>' + e(UI.t(k)) + '</th>'; }).join('') +
      (etat.peutTraiter ? '<th style="text-align:right">' + e(UI.t('colonne-actions')) + '</th>' : '') + '</tr></thead><tbody>' +
      etat.lignes.map(function (p) {
        var cl = p.clients || {};
        var actions = '';
        if (etat.peutTraiter) {
          var b = function (statut, cle) {
            return '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-id="' + e(p.id) +
              '" data-statut="' + statut + '">' + e(UI.t(cle)) + '</button>';
          };
          actions = '<td><div class="ses-actions-ligne">' +
            (p.statut !== 'recue' ? b('recue', 'pa-marquer-recue') : '') +
            (p.statut !== 'annulee' ? b('annulee', 'pa-annuler') : '') +
            (p.statut !== 'attendue' ? b('attendue', 'pa-remettre') : '') + '</div></td>';
        }
        return '<tr class="ses-ligne">' +
          '<td data-libelle="' + e(UI.t('pa-col-date')) + '" style="color:var(--muted-2);font-size:13.5px">' + e(UI.date(p.cree_le, true)) + '</td>' +
          '<td data-libelle="' + e(UI.t('pa-col-client')) + '"><span class="ses-mono" style="font-size:13.5px">' + e(cl.code || '—') + '</span>' +
            (cl.nom_complet ? '<br><span style="color:var(--muted-2);font-size:13.5px">' + e(cl.nom_complet) + '</span>' : '') + '</td>' +
          '<td data-libelle="' + e(UI.t('pa-col-achat')) + '"><strong>' + e(p.magasin) + '</strong><br>' +
            '<span style="color:var(--muted-2);font-size:13.5px">' + e(p.contenu) + ' · ' + e(UI.t('service-' + p.service) || p.service) + '</span>' +
            (p.note ? '<br><span style="font-size:12.5px;color:var(--muted-2)">' + e(p.note) + '</span>' : '') + '</td>' +
          '<td data-libelle="' + e(UI.t('pa-col-suivi')) + '" class="ses-mono" style="font-size:13.5px">' + e(p.numero_suivi || '—') + '</td>' +
          '<td data-libelle="' + e(UI.t('pa-col-valeur')) + '" class="ses-mono" style="font-size:13.5px">' +
            (p.valeur !== null && p.valeur !== undefined ? e(UI.montant(p.valeur)) : '—') + '</td>' +
          '<td data-libelle="' + e(UI.t('pa-col-statut')) + '">' + pastille(p.statut) + '</td>' +
          actions + '</tr>';
      }).join('') + '</tbody></table>';
    var debut = etat.page * PAR_PAGE;
    var de = etat.page * PAR_PAGE + 1, a = Math.min(etat.total, (etat.page + 1) * PAR_PAGE);
    $('#ses-pages-prealertes').innerHTML = etat.total <= PAR_PAGE ? '' :
      '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-page="-1"' + (etat.page ? '' : ' disabled') + '>' + e(UI.t('page-precedente')) + '</button>' +
      '<span>' + e(UI.t('page-position', { de: de, a: a, total: etat.total })) + '</span>' +
      '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-page="1"' + (a >= etat.total ? ' disabled' : '') + '>' + e(UI.t('page-suivante')) + '</button>';
  }

  function annoncer(texte, genre) {
    var zone = document.getElementById('ses-message');
    if (zone) UI.annonce(zone, texte, genre);
  }

  function charger() {
    etat.charge = true;
    return API.prealertes.lister({ page: etat.page, parPage: PAR_PAGE, statut: etat.statut, recherche: etat.recherche })
      .then(function (r) { etat.lignes = r.lignes; etat.total = r.total; filtres(); liste(); })
      .catch(function (err) { annoncer(UI.messageErreur(err), 'erreur'); });
  }

  function brancher() {
    $('#ses-filtres-prealertes').addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-statut]');
      if (!b) return;
      etat.statut = b.getAttribute('data-statut');
      etat.page = 0;
      charger();
    });
    var minuterie = null;
    $('#ses-chercher-prealertes').addEventListener('input', function (ev) {
      clearTimeout(minuterie);
      minuterie = setTimeout(function () { etat.recherche = ev.target.value; etat.page = 0; charger(); }, 300);
    });
    $('#ses-pages-prealertes').addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-page]');
      if (!b || b.disabled) return;
      etat.page = Math.max(0, etat.page + Number(b.getAttribute('data-page')));
      charger();
    });
    $('#ses-liste-prealertes').addEventListener('click', function (ev) {
      var b = ev.target.closest('button[data-id]');
      if (!b) return;
      b.disabled = true;
      API.prealertes.traiter(b.getAttribute('data-id'), { statut: b.getAttribute('data-statut') })
        .then(function () { annoncer(UI.t('pa-traitee'), 'succes'); return charger(); })
        .catch(function (err) { b.disabled = false; annoncer(UI.messageErreur(err), 'erreur'); });
    });
    document.getElementById('ses-o-prealertes').addEventListener('click', function () { if (!etat.charge) charger(); });
    UI.surLangue(function () { if (etat.charge) { filtres(); liste(); } });
    if (window.SES_REGLAGES) window.SES_REGLAGES.surChange(function (cle, r) {
      if ((cle === 'lignes' || cle === '*') && r.lignes !== PAR_PAGE) { PAR_PAGE = r.lignes; etat.page = 0; if (etat.charge) charger(); }
    });
  }

  function demarrer() {
    API.profil().then(function (p) {
      if (!p || API.ROLES_EQUIPE.indexOf(p.role) < 0 || !API.peut(p, 'colis.lire')) return;
      etat.peutTraiter = API.peut(p, 'colis.statut') || API.peut(p, 'colis.modifier');
      return API.prealertes.disponible().then(function (ok) {
        if (!ok) return;
        var b = document.getElementById('ses-o-prealertes');
        b.hidden = false;
        brancher();
        // ouverte directement par son adresse (#prealertes) : le tableau de bord a choisi un autre onglet faute de la voir
        if ((window.SES_ADRESSE_INITIALE || '').split('/')[0] === '#prealertes') b.click();
      });
    }).catch(function () { /* sans profil lisible, l'onglet reste caché */ });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', demarrer);
  else demarrer();
})();
