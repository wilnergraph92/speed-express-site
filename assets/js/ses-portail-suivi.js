/* ==========================================================================
   Portail client — tableau de bord, colis, suivi, expéditions, consolidations
   --------------------------------------------------------------------------
   Tout ce que le client voit ici vient de SES_API.portail (la base) : le
   suivi est le vrai journal du noyau, les étapes sont celles que la base
   calcule. Voir ses-portail.js pour les règles communes.
   ========================================================================== */
(function () {
  'use strict';
  var P = window.SES_PORTAIL, API = window.SES_API, UI = window.SES_UI;
  if (!P || !API || !UI) return;
  var t = P.t, e = P.e;
  var PAGE = 20;

  function lienColis(numero) {
    return '<a class="ses-lien-colis" href="' + P.lien('colis', numero) + '">' + e(numero) + '</a>';
  }

  /* ----------------------------------------------------------------------
     Tableau de bord
     ---------------------------------------------------------------------- */
  function carte(valeur, libelle, genre, detail, lien) {
    var corps = '<b' + (genre ? ' class="ses-chiffre-' + genre + '"' : '') + '>' + e(valeur) + '</b><span>' + e(libelle) + (detail ? ' · ' + e(detail) : '') + '</span>';
    return lien ? '<a class="ses-chiffre ses-carte ses-chiffre-lien" href="' + lien + '">' + corps + '</a>' : '<div class="ses-chiffre ses-carte">' + corps + '</div>';
  }

  function dessinerTableau(zone, tb) {
    var par = (tb.parcels && tb.parcels.by_stage) || {};
    var factures = tb.invoices || {};
    var soldes = (factures.balances || []).filter(function (b) { return Number(b.balance) > 0; }).map(function (b) { return UI.montant(b.balance, b.currency); }).join(' + ');
    var html = P.titre('p-nav-tableau') +
      '<div class="ses-chiffres">' +
        carte(par.in_transit || 0, t('stage-in_transit'), '', '', P.lien('colis')) +
        carte(par.at_hub || 0, t('stage-at_hub'), (par.at_hub ? 'ok' : ''), '', P.lien('livraisons')) +
        carte(par.out_for_delivery || 0, t('stage-out_for_delivery'), '', '', P.lien('livraisons')) +
        carte(par.delivered || 0, t('stage-delivered'), '', '', P.lien('colis')) +
        carte(factures.unpaid || 0, t('p-tb-impayees'), (factures.unpaid ? 'bad' : ''), soldes, P.lien('factures')) +
        carte(tb.pickups ? tb.pickups.open : 0, t('p-tb-enlevements'), '', '', P.lien('enlevements')) +
        carte(tb.notifications ? tb.notifications.unread : 0, t('p-tb-non-lues'), '', '', P.lien('notifications')) +
        carte(tb.tickets ? tb.tickets.open : 0, t('p-tb-tickets'), '', '', P.lien('support')) +
      '</div>';

    var prochaines = (tb.deliveries && tb.deliveries.upcoming) || [];
    html += '<div class="ses-deux">' +
      '<section class="ses-carte ses-bloc" aria-labelledby="ses-tb-liv"><h3 id="ses-tb-liv">' + e(t('p-tb-prochaines')) + '</h3>' +
        (prochaines.length ? '<ul class="ses-liste-simple">' + prochaines.map(function (l) {
          return '<li><strong>' + e(UI.date(l.scheduled_date)) + '</strong> · ' + e(t('p-colis-n', { nombre: l.parcels })) + ' ' +
            P.pastilleEtape(l.status === 'STARTED' ? 'on_the_way' : 'scheduled', 'req') + '</li>';
        }).join('') + '</ul>' : '<p class="ses-muet">' + e(t('p-tb-aucune-livraison')) + '</p>') +
      '</section>' +
      '<section class="ses-carte ses-bloc" aria-labelledby="ses-tb-evt"><h3 id="ses-tb-evt">' + e(t('p-tb-derniers')) + '</h3>' +
        ((tb.recent_events || []).length ? '<ul class="ses-liste-simple">' + tb.recent_events.map(function (ev) {
          var titre = ev.event === 'ParcelStatusChanged' ? t('stage-' + ev.stage) : (t('evt-' + ev.event) || t('stage-' + ev.stage));
          return '<li>' + lienColis(ev.tracking_number) + ' — ' + e(titre) + '<br><span class="ses-muet">' + e(UI.date(ev.at, true)) + '</span></li>';
        }).join('') + '</ul>' : '<p class="ses-muet">' + e(t('p-tb-aucun-evenement')) + '</p>') +
      '</section></div>' +
      '<section class="ses-bloc" aria-labelledby="ses-tb-act" style="margin-top:18px"><h3 id="ses-tb-act">' + e(t('p-tb-actions')) + '</h3><div class="ses-actions">' +
        '<a class="ses-bouton ses-bouton-principal" href="' + P.lien('enlevements') + '">' + e(t('p-tb-demander-enlevement')) + '</a>' +
        '<a class="ses-bouton ses-bouton-second" href="' + P.lien('livraisons') + '">' + e(t('p-tb-demander-livraison')) + '</a>' +
        '<a class="ses-bouton ses-bouton-second" href="' + P.lien('suivi') + '">' + e(t('p-tb-suivre')) + '</a>' +
        '<a class="ses-bouton ses-bouton-second" href="' + P.lien('support') + '">' + e(t('p-tb-support')) + '</a></div></section>';
    zone.innerHTML = html;
  }

  P.enregistrer({
    id: 'tableau', ordre: 10, toujours: true,
    rendre: function (zone) {
      return P.charger(zone, function () { return API.portail.tableau(); }, function (tb) { dessinerTableau(zone, tb); });
    }
  });

  /* ----------------------------------------------------------------------
     Le détail d'un colis et son suivi (partagé par « Mes colis » et « Suivi »)
     ---------------------------------------------------------------------- */
  function blocExpedition(s) {
    if (!s) return '';
    return '<section class="ses-sous" aria-labelledby="ses-d-exp"><h3 id="ses-d-exp">' + e(t('p-d-expedition')) + '</h3>' +
      '<p>' + P.pastilleEtape(s.stage) + '</p><dl class="ses-dl">' +
      P.detail(t('p-d-code'), s.code) + P.detail(t('p-d-service'), t('mode-' + s.mode)) +
      P.detail(t('p-d-trajet'), s.origin && s.destination ? s.origin + ' → ' + s.destination : '') +
      P.detail(t('p-d-transporteur'), [s.carrier, s.reference].filter(Boolean).join(' · ')) +
      P.detail(t('p-d-depart'), s.dispatched_at ? UI.date(s.dispatched_at, true) : '') +
      P.detail(t('p-d-arrivee-prevue'), s.planned_arrival_at && !s.arrived_at ? UI.date(s.planned_arrival_at) : '') +
      P.detail(t('p-d-arrivee'), s.arrived_at ? UI.date(s.arrived_at, true) : '') +
      P.detail(t('p-d-douane'), s.customs ? t('customs-' + s.customs) : '') + '</dl></section>';
  }
  function blocLivraison(l) {
    if (!l) return '';
    var fenetre = l.window_start && l.window_end ? UI.date(l.window_start, true) + ' – ' + UI.date(l.window_end, true) : '';
    return '<section class="ses-sous" aria-labelledby="ses-d-liv"><h3 id="ses-d-liv">' + e(t('p-d-livraison')) + '</h3>' +
      '<p>' + P.pastilleEtape(l.stage, 'req') + '</p><dl class="ses-dl">' +
      P.detail(t('p-d-date-prevue'), l.scheduled_date ? UI.date(l.scheduled_date) : '') + P.detail(t('p-d-fenetre'), fenetre) +
      P.detail(t('p-d-code-livraison'), l.otp_required ? t(l.otp_issued ? 'p-d-code-envoye' : 'p-d-code-exige') : '') +
      P.detail(t('p-d-incident'), l.failure ? t('incident-' + l.failure) || l.failure : '') +
      P.detail(t('p-d-recu-par'), l.proof ? l.proof.recipient_name : '') + P.detail(t('p-d-recu-le'), l.proof ? UI.date(l.proof.delivered_at, true) : '') + '</dl></section>';
  }

  function dessinerDetail(zone, d, retour) {
    var html = (retour ? '<p class="ses-retour"><a href="' + P.lien('colis') + '">← ' + e(t('p-retour-colis')) + '</a></p>' : '') +
      '<header class="ses-ph"><h2 tabindex="-1"><span class="ses-mono">' + e(d.tracking_number) + '</span></h2><p>' + e(d.description || '') + '</p></header>' +
      '<div class="ses-carte ses-bloc"><div class="ses-ligne-pastille">' + P.pastilleEtape(d.stage) +
        (d.place ? '<span class="ses-muet">' + e(t('p-d-actuellement')) + ' ' + e(d.place) + '</span>' : '') + '</div>' + P.frise(d.stage) + '</div>' +
      '<div class="ses-deux" style="margin-top:18px"><div>' +
        '<section class="ses-carte ses-bloc"><h3>' + e(t('p-d-suivi')) + '</h3>' + P.suivi(d.timeline) + '</section></div><div style="display:grid;gap:18px;align-content:start">' +
        '<section class="ses-carte ses-bloc"><h3>' + e(t('p-d-infos')) + '</h3><dl class="ses-dl">' +
          P.detail(t('colis-expediteur'), d.sender_name) + P.detail(t('p-d-destinataire'), d.recipient_name) + P.detail(t('colis-service'), t('mode-' + d.service_mode)) +
          P.detail(t('colis-poids'), d.weight_lb !== null && d.weight_lb !== undefined ? UI.nombre(d.weight_lb) + ' lb' : '') +
          P.detail(t('p-d-valeur'), d.declared_value ? UI.montant(d.declared_value) : '') +
          P.detail(t('colis-destination'), [d.destination_city, P.pays(d.destination_country)].filter(Boolean).join(', ')) + P.detail(t('colis-livraison'), d.delivery_address) +
          P.detail(t('colis-maj'), UI.date(d.updated_at, true)) + '</dl></section>' +
        blocExpedition(d.shipment) +
        (d.consolidation ? '<section class="ses-carte ses-bloc"><h3>' + e(t('p-d-consolidation')) + '</h3><dl class="ses-dl">' + P.detail(t('p-d-code'), d.consolidation.code) +
          P.detail(t('p-d-etat'), t('cons-' + d.consolidation.status)) + '</dl></section>' : '') +
        (d.delivery ? '<section class="ses-carte ses-bloc">' + blocLivraison(d.delivery).replace(/^<section[^>]*>/, '').replace(/<\/section>$/, '') + '</section>' : '') +
        ((d.invoices || []).length ? '<section class="ses-carte ses-bloc"><h3>' + e(t('p-d-factures')) + '</h3><ul class="ses-liste-simple">' + d.invoices.map(function (f) {
          return '<li><a href="' + P.lien('factures', f.number) + '">' + e(f.number) + '</a> · ' + e(UI.montant(f.total, f.currency)) + ' ' + P.pastille('inv-' + f.status, f.status === 'PAID' ? 'ok' : 'warn') + '</li>';
        }).join('') + '</ul></section>' : '') +
        '<p><a class="ses-bouton ses-bouton-second ses-bouton-mini" href="' + P.lien('support', 'nouveau/' + d.tracking_number) + '">' + e(t('p-d-ecrire-support')) + '</a></p>' +
      '</div></div>';
    zone.innerHTML = html;
  }

  /* ----------------------------------------------------------------------
     Mes colis
     ---------------------------------------------------------------------- */
  var etat = { etape: '', recherche: '', items: [], total: 0, parEtape: {} };

  function dessinerListeColis(zone) {
    var chips = [['', t('tous')]].concat(P.PARCOURS.concat(['on_hold', 'incident', 'lost', 'cancelled', 'returned']).filter(function (s) {
      return etat.parEtape[s];
    }).map(function (s) { return [s, t('stage-' + s)]; }));
    var tousN = 0;
    Object.keys(etat.parEtape).forEach(function (k) { tousN += etat.parEtape[k]; });
    var liste = zone.querySelector('.ses-liste-colis');
    liste.innerHTML = etat.items.length ? etat.items.map(function (c) {
      return '<article class="ses-carte ses-bloc ses-fiche"><div class="ses-fiche-tete"><div style="min-width:0">' +
        '<p class="ses-mono ses-fiche-num"><a href="' + P.lien('colis', c.tracking_number) + '">' + e(c.tracking_number) + '</a></p>' +
        '<p class="ses-fiche-desc">' + e(c.description || '—') + '</p></div>' + P.pastilleEtape(c.stage) + '</div>' +
        '<p class="ses-muet">' + (c.place ? e(c.place) + ' · ' : '') + e(UI.date(c.updated_at, true)) + ' · ' + e(P.pays(c.destination_country)) + '</p>' +
        '<p style="margin:10px 0 0"><a class="ses-bouton ses-bouton-second ses-bouton-mini" href="' + P.lien('colis', c.tracking_number) + '">' + e(t('p-voir-suivi')) + '</a></p></article>';
    }).join('') : '<div class="ses-bloc">' + UI.vide(t(etat.recherche || etat.etape ? 'colis-vide-filtre' : 'colis-vide'), '▢') + '</div>';
    var filtres = zone.querySelector('.ses-filtres');
    filtres.innerHTML = chips.map(function (c) {
      return '<button type="button" class="ses-filtre" data-etape="' + e(c[0]) + '" aria-pressed="' + (c[0] === etat.etape ? 'true' : 'false') + '">' + e(c[1]) + (c[0] ? ' (' + etat.parEtape[c[0]] + ')' : ' (' + tousN + ')') + '</button>';
    }).join('');
    var pied = zone.querySelector('.ses-pagination');
    pied.innerHTML = etat.items.length ? '<span>' + e(t('p-colis-affiches', { nombre: etat.items.length, total: etat.total })) + '</span>' +
      (etat.items.length < etat.total ? '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-plus>' + e(t('p-afficher-plus')) + '</button>' : '') : '';
  }

  function chargerColis(zone, ajouter) {
    var liste = zone.querySelector('.ses-liste-colis');
    var decalage = ajouter ? etat.items.length : 0;
    liste.setAttribute('aria-busy', 'true');
    return API.portail.colis({ etape: etat.etape || undefined, recherche: etat.recherche || undefined, limite: PAGE, decalage: decalage }).then(function (r) {
      liste.removeAttribute('aria-busy');
      etat.items = ajouter ? etat.items.concat(r.items) : r.items;
      etat.total = r.total;
      etat.parEtape = r.by_stage || {};
      dessinerListeColis(zone);
    }, function (err) { liste.removeAttribute('aria-busy'); P.erreur(liste, err, function () { chargerColis(zone, ajouter); }); });
  }

  function squeletteColis(zone) {
    zone.innerHTML = P.titre('p-nav-colis') +
      '<div class="ses-barre"><label class="ses-champ ses-recherche"><span class="sr-only">' + e(t('p-chercher-colis-libelle')) + '</span>' +
      '<input type="search" id="ses-p-chercher" placeholder="' + e(t('p-chercher-colis')) + '" maxlength="80" autocomplete="off" value="' + e(etat.recherche) + '"></label>' +
      '<div class="ses-filtres" role="group" aria-label="' + e(t('p-filtrer-etape')) + '"></div></div>' +
      '<div class="ses-liste-colis" aria-live="polite" style="margin-top:18px"></div><div class="ses-pagination"></div>';
    var champ = zone.querySelector('#ses-p-chercher'), minuteur;
    champ.addEventListener('input', function () {
      clearTimeout(minuteur);
      minuteur = setTimeout(function () { etat.recherche = champ.value.trim(); chargerColis(zone, false); }, 250);
    });
    zone.querySelector('.ses-filtres').addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-etape]');
      if (!b) return;
      etat.etape = b.getAttribute('data-etape');
      chargerColis(zone, false).then(function () { var n = zone.querySelector('[data-etape="' + etat.etape + '"]'); if (n) n.focus(); });
    });
    zone.querySelector('.ses-pagination').addEventListener('click', function (ev) {
      if (ev.target.closest('[data-plus]')) chargerColis(zone, true);
    });
  }

  P.enregistrer({
    id: 'colis', ordre: 20,
    rendre: function (zone, param) {
      if (param) return P.charger(zone, function () { return API.portail.colisDetail(param); }, function (d) { dessinerDetail(zone, d, true); });
      zone._v = (zone._v || 0) + 1;
      zone._rendu = function () { squeletteColis(zone); dessinerListeColis(zone); };
      squeletteColis(zone);
      etat.items = []; etat.total = 0; etat.parEtape = {};
      return chargerColis(zone, false);
    }
  });

  /* ----------------------------------------------------------------------
     Suivi : un numéro, son parcours
     ---------------------------------------------------------------------- */
  P.enregistrer({
    id: 'suivi', ordre: 40,
    rendre: function (zone, param) {
      var recents = [];
      function squelette() {
        zone.innerHTML = P.titre('p-nav-suivi', 'p-suivi-intro') +
          '<form class="ses-carte ses-bloc ses-form-suivi" novalidate><div id="ses-p-suivi-msg" hidden></div><div class="ses-barre">' +
          P.champ({ id: 'ses-p-numero', nom: 'numero', libelle: 'p-numero-colis', requis: true, max: 40, valeur: param || '', placeholder: 'SES-10001-HT' }) +
          '<button type="submit" class="ses-bouton ses-bouton-principal">' + e(t('p-suivre')) + '</button></div>' +
          (recents.length ? '<p class="ses-muet" style="margin-top:12px">' + e(t('p-recents')) + ' ' + recents.map(function (c) {
            return '<a class="ses-lien-colis" href="' + P.lien('suivi', c.tracking_number) + '">' + e(c.tracking_number) + '</a>';
          }).join(' · ') + '</p>' : '') + '</form><div class="ses-resultat-suivi" aria-live="polite" style="margin-top:18px"></div>';
        var form = zone.querySelector('form');
        form.addEventListener('submit', function (ev) {
          ev.preventDefault();
          UI.effacerErreurs(form);
          var n = form.elements.numero.value.trim();
          if (!n) { UI.erreurChamp(form.elements.numero, t('p-numero-requis')); return; }
          P.aller('suivi', n);
        });
      }
      return API.portail.colis({ limite: 5 }).then(function (r) { recents = r.items; }, function () { recents = []; }).then(function () {
        squelette();
        if (!param) return;
        var cible = zone.querySelector('.ses-resultat-suivi'), msg = zone.querySelector('#ses-p-suivi-msg');
        function lancer() {
          P.etat(cible, 'chargement');
          return API.portail.colisDetail(param).then(function (d) {
            cible.removeAttribute('aria-busy');
            cible._rendu = function () { dessinerDetail(cible, d, false); };
            dessinerDetail(cible, d, false);
          }, function (err) {
            cible._rendu = null;
            if (err && err.code === 'introuvable') {
              // Un numéro qui n'est pas au client dit « introuvable », comme un numéro qui n'existe pas : on ne peut pas deviner ceux des autres.
              cible.innerHTML = '';
              UI.annonce(msg, t('p-suivi-introuvable'), 'erreur');
            } else P.erreur(cible, err, lancer);
          });
        }
        return lancer();
      });
    }
  });

  /* ----------------------------------------------------------------------
     Expéditions
     ---------------------------------------------------------------------- */
  P.enregistrer({
    id: 'expeditions', ordre: 30,
    rendre: function (zone) {
      return P.charger(zone, function () { return API.portail.expeditions(); }, function (liste) {
        zone.innerHTML = P.titre('p-nav-expeditions', 'p-exp-intro') + (liste.length ? liste.map(function (s) {
          return '<article class="ses-carte ses-bloc ses-fiche"><div class="ses-fiche-tete"><div><p class="ses-mono ses-fiche-num">' + e(s.code) + '</p>' +
            '<p class="ses-fiche-desc">' + e(t('mode-' + s.mode)) + (s.origin && s.destination ? ' · ' + e(s.origin) + ' → ' + e(s.destination) : '') + '</p></div>' + P.pastilleEtape(s.stage) + '</div>' +
            P.frise(s.stage === 'preparing' ? 'received' : (s.stage === 'closed' ? 'at_hub' : s.stage)) +
            '<dl class="ses-dl" style="margin-top:14px">' + P.detail(t('p-d-transporteur'), [s.carrier, s.reference].filter(Boolean).join(' · ')) +
            P.detail(t('p-d-depart'), s.dispatched_at ? UI.date(s.dispatched_at, true) : '') + P.detail(t('p-d-arrivee-prevue'), s.planned_arrival_at && !s.arrived_at ? UI.date(s.planned_arrival_at) : '') +
            P.detail(t('p-d-arrivee'), s.arrived_at ? UI.date(s.arrived_at, true) : '') + P.detail(t('p-d-douane'), s.customs ? t('customs-' + s.customs) : '') + '</dl>' +
            '<p class="ses-muet" style="margin:14px 0 6px">' + e(t('p-exp-mes-colis')) + '</p><ul class="ses-liste-simple">' + s.my_parcels.map(function (c) {
              return '<li>' + lienColis(c.tracking_number) + ' ' + P.pastilleEtape(c.stage) + '</li>';
            }).join('') + '</ul></article>';
        }).join('') : '<div class="ses-bloc">' + UI.vide(t('p-exp-vide'), '✈') + '</div>');
      });
    }
  });

  /* ----------------------------------------------------------------------
     Consolidations
     ---------------------------------------------------------------------- */
  P.enregistrer({
    id: 'consolidations', ordre: 50,
    rendre: function (zone) {
      return P.charger(zone, function () { return API.portail.consolidations(); }, function (liste) {
        zone.innerHTML = P.titre('p-nav-consolidations', 'p-cons-intro') + (liste.length ? liste.map(function (c) {
          return '<article class="ses-carte ses-bloc ses-fiche"><div class="ses-fiche-tete"><div><p class="ses-mono ses-fiche-num">' + e(c.code) + '</p>' +
            '<p class="ses-fiche-desc">' + e(t('mode-' + c.mode)) + ' · ' + e(P.pays(c.destination_country)) + (c.origin ? ' · ' + e(c.origin) : '') + '</p></div>' +
            P.pastille('cons-' + c.status, c.status === 'OPEN' ? 'info' : 'ok') + '</div>' +
            '<dl class="ses-dl" style="margin-top:12px">' + P.detail(t('p-cons-ouverte'), UI.date(c.opened_at)) + P.detail(t('p-cons-fermee'), c.closed_at ? UI.date(c.closed_at) : '') +
            P.detail(t('p-cons-expedition'), c.shipment) + P.detail(t('p-cons-mes-colis'), t('p-colis-n', { nombre: c.my_count })) + '</dl>' +
            '<ul class="ses-liste-simple" style="margin-top:10px">' + c.my_parcels.map(function (n) { return '<li>' + lienColis(n) + '</li>'; }).join('') + '</ul></article>';
        }).join('') : '<div class="ses-bloc">' + UI.vide(t('p-cons-vide'), '▦') + '</div>');
      });
    }
  });
})();
