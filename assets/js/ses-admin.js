/* ==========================================================================
   Speed Express Shipping — tableau de bord (administration et employés)
   --------------------------------------------------------------------------
   Colis, factures, clients et rôles. Chaque bouton n'apparaît que si le
   compte connecté a le droit correspondant ; le serveur refait le même
   contrôle de son côté, et c'est celui-là qui fait foi.
   ========================================================================== */
(function () {
  'use strict';

  var API = window.SES_API;
  var UI = window.SES_UI;
  if (!API || !UI || !document.getElementById('ses-liste-colis')) return;

  var moi = null;
  var droits = [];
  var PAR_PAGE = 20;

  var etat = {
    colis: { page: 0, statut: '', recherche: '', client_id: '', total: 0, lignes: [] },
    factures: { page: 0, statut: '', recherche: '', total: 0, lignes: [] },
    clients: { page: 0, role: '', recherche: '', total: 0, lignes: [] }
  };

  function $(s) { return document.querySelector(s); }
  function e(v) { return UI.echapper(v); }
  function peut(d) { return droits.indexOf(d) >= 0; }

  /* ======================================================================
     Mise en place
     ====================================================================== */
  function poserIdentite() {
    $('#ses-identite').textContent = UI.t('identite', {
      nom: moi.nom_complet || moi.email,
      role: UI.t('role-' + moi.role) || moi.role
    });
    // Un employé ne voit que les onglets qui lui servent.
    if (!peut('factures.lire')) cacherOnglet('ses-o-factures');
    if (!peut('clients.lire')) cacherOnglet('ses-o-clients');
    if (!peut('colis.creer')) $('#ses-nouveau-colis').hidden = true;
    var nf = $('#ses-nouvelle-facture');
    if (nf && !peut('factures.creer')) nf.hidden = true;
  }

  function cacherOnglet(id) {
    var b = document.getElementById(id);
    if (!b) return;
    b.hidden = true;
    document.getElementById(b.getAttribute('aria-controls')).hidden = true;
  }

  function onglets() {
    var boutons = document.querySelectorAll('[role="tab"]');
    Array.prototype.forEach.call(boutons, function (b) {
      b.addEventListener('click', function () {
        Array.prototype.forEach.call(boutons, function (x) {
          var actif = x === b;
          x.setAttribute('aria-selected', actif ? 'true' : 'false');
          document.getElementById(x.getAttribute('aria-controls')).hidden = !actif;
        });
        if (b.id === 'ses-o-factures' && !etat.factures.lignes.length) chargerFactures();
        if (b.id === 'ses-o-clients' && !etat.clients.lignes.length) chargerClients();
      });
    });
  }

  /* ======================================================================
     Chiffres
     ====================================================================== */
  function chiffres() {
    API.admin.statistiques().then(function (s) {
      var statuts = s.statuts || {};
      $('#ses-chiffres').innerHTML = [
        carte(s.clients || 0, UI.t('chiffre-clients')),
        carte(s.colis === undefined ? total(statuts) : s.colis, UI.t('chiffre-colis')),
        carte(statuts.disponible || 0, UI.t('chiffre-disponibles'), statuts.disponible ? '#0b7a19' : null),
        carte(statuts.action || 0, UI.t('chiffre-action'), statuts.action ? '#b60d14' : null),
        carte(s.factures_impayees || 0, UI.t('chiffre-impayees'),
          s.factures_impayees ? '#b60d14' : null,
          s.montant_impaye ? UI.montant(s.montant_impaye) : null)
      ].join('');
      if (window.SES_ANIM) window.SES_ANIM.reveler($('#ses-chiffres'));
    }).catch(function () { $('#ses-chiffres').innerHTML = ''; });
  }

  function total(statuts) {
    return Object.keys(statuts).reduce(function (a, k) { return a + statuts[k]; }, 0);
  }

  function carte(valeur, libelle, couleur, detail) {
    return '<div class="ses-chiffre ses-carte ses-lueur" data-ses-reveal="0">' +
      '<b' + (couleur ? ' style="color:' + couleur + '"' : '') + '>' + valeur + '</b>' +
      '<span>' + e(libelle) + (detail ? ' · ' + e(detail) : '') + '</span></div>';
  }

  /* ======================================================================
     Filtres, recherche et pagination
     ====================================================================== */
  function filtres() {
    rendreFiltres($('#ses-filtres-colis'), [''].concat(API.STATUTS).map(function (s) {
      return [s, s ? UI.nomStatut(s) : UI.t('tous')];
    }), etat.colis.statut, function (v) {
      etat.colis.statut = v; etat.colis.page = 0; chargerColis();
    });

    rendreFiltres($('#ses-filtres-factures'), [
      ['', UI.t('tous')], ['impayee', UI.t('facture-impayee')], ['payee', UI.t('facture-payee')]
    ], etat.factures.statut, function (v) {
      etat.factures.statut = v; etat.factures.page = 0; chargerFactures();
    });

    rendreFiltres($('#ses-filtres-clients'), [
      ['', UI.t('tous')], ['client', UI.t('role-client')],
      ['employe', UI.t('role-employe')], ['admin', UI.t('role-admin')]
    ], etat.clients.role, function (v) {
      etat.clients.role = v; etat.clients.page = 0; chargerClients();
    });

    chercher('#ses-chercher-colis', function (v) {
      etat.colis.recherche = v; etat.colis.client_id = ''; etat.colis.page = 0; chargerColis();
    });
    chercher('#ses-chercher-factures', function (v) {
      etat.factures.recherche = v; etat.factures.page = 0; chargerFactures();
    });
    chercher('#ses-chercher-clients', function (v) {
      etat.clients.recherche = v; etat.clients.page = 0; chargerClients();
    });
  }

  function rendreFiltres(zone, paires, actif, choisi) {
    if (!zone) return;
    zone.innerHTML = paires.map(function (p) {
      return '<button type="button" class="ses-filtre" data-valeur="' + e(p[0]) + '" aria-pressed="' +
        (p[0] === actif ? 'true' : 'false') + '">' + e(p[1]) + '</button>';
    }).join('');
    if (zone.dataset.branche) return;
    zone.dataset.branche = '1';
    zone.addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-valeur]');
      if (b) choisi(b.getAttribute('data-valeur'));
    });
  }

  function chercher(selecteur, action) {
    var champ = $(selecteur);
    if (!champ) return;
    var minuteur;
    champ.addEventListener('input', function () {
      clearTimeout(minuteur);
      minuteur = setTimeout(function () { action(champ.value.trim()); }, 220);
    });
  }

  function pagination(zone, info, recharger) {
    if (info.total <= PAR_PAGE) { zone.innerHTML = ''; return; }
    var de = info.page * PAR_PAGE + 1;
    var a = Math.min(info.total, (info.page + 1) * PAR_PAGE);
    zone.innerHTML =
      '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-pas="-1"' +
        (info.page === 0 ? ' disabled' : '') + '>' + e(UI.t('page-precedente')) + '</button>' +
      '<span>' + e(UI.t('page-position', { de: de, a: a, total: info.total })) + '</span>' +
      '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-pas="1"' +
        (a >= info.total ? ' disabled' : '') + '>' + e(UI.t('page-suivante')) + '</button>';
    zone.querySelectorAll('[data-pas]').forEach(function (b) {
      b.addEventListener('click', function () {
        info.page += Number(b.getAttribute('data-pas'));
        recharger();
      });
    });
  }

  /* ======================================================================
     Colis
     ====================================================================== */
  function chargerColis() {
    return API.admin.colis({
      page: etat.colis.page, parPage: PAR_PAGE,
      statut: etat.colis.statut, recherche: etat.colis.recherche, client_id: etat.colis.client_id
    }).then(function (r) {
      etat.colis.lignes = r.lignes;
      etat.colis.total = r.total;
      listeColis();
      pagination($('#ses-pages-colis'), etat.colis, chargerColis);
    }).catch(erreurGenerale);
  }

  function listeColis() {
    var zone = $('#ses-liste-colis');
    if (!etat.colis.lignes.length) {
      var filtre = etat.colis.statut || etat.colis.recherche || etat.colis.client_id;
      zone.innerHTML = '<div class="ses-bloc">' +
        UI.vide(UI.t(filtre ? 'colis-vide-filtre' : 'colis-vide'), '▢') + '</div>';
      return;
    }
    zone.innerHTML = '<table class="ses-tableau"><thead><tr>' +
      ['colonne-numero', 'colonne-client', 'colonne-contenu', 'colonne-statut', 'colonne-maj']
        .map(function (k) { return '<th>' + e(UI.t(k)) + '</th>'; }).join('') +
      '<th style="text-align:right">' + e(UI.t('colonne-actions')) + '</th></tr></thead><tbody>' +
      etat.colis.lignes.map(function (c) {
        return '<tr class="ses-ligne">' +
          '<td data-libelle="' + e(UI.t('colonne-numero')) + '" class="ses-mono">' + e(c.numero) + '</td>' +
          '<td data-libelle="' + e(UI.t('colonne-client')) + '">' +
            '<span class="ses-mono" style="font-size:13.5px">' + e(c.code_client || '—') + '</span>' +
            (c.nom_client ? '<br><span style="color:#6b7280;font-size:13.5px">' + e(c.nom_client) + '</span>' : '') +
          '</td>' +
          '<td data-libelle="' + e(UI.t('colonne-contenu')) + '">' + e(c.description || '—') + '</td>' +
          '<td data-libelle="' + e(UI.t('colonne-statut')) + '">' + UI.pastille(c.statut, { petite: true }) + '</td>' +
          '<td data-libelle="' + e(UI.t('colonne-maj')) + '" style="color:#6b7280;font-size:13.5px">' +
            e(UI.date(c.maj_le, true)) + '</td>' +
          '<td><div class="ses-actions-ligne">' +
            bouton('fiche', c.id, 'second') +
            (peut('colis.statut') ? bouton('statut', c.id, 'second') : '') +
            (peut('colis.modifier') ? bouton('modifier', c.id, 'second') : '') +
            (peut('colis.supprimer') ? bouton('supprimer', c.id, 'danger') : '') +
          '</div></td></tr>';
      }).join('') + '</tbody></table>';
  }

  function bouton(action, id, genre) {
    return '<button type="button" class="ses-bouton ses-bouton-' + genre + ' ses-bouton-mini" ' +
      'data-action="' + action + '" data-id="' + e(id) + '">' + e(UI.t('action-' + action)) + '</button>';
  }

  /* --- Fiche d'un colis : codes, détails et historique -------------------- */
  function ouvrirFiche(id) {
    Promise.all([API.admin.colisParId(id), API.admin.historique(id)]).then(function (r) {
      var c = r[0], histo = r[1] || [];
      if (!c) return erreurGenerale({ code: 'colis-inconnu' });
      c.historique = histo;

      $('#ses-fiche-contenu').innerHTML =
        '<h2 id="ses-fiche-titre" style="font-size:22px;padding-right:40px">' +
          e(UI.t('fiche-titre', { numero: c.numero })) + '</h2>' +
        '<div style="margin-top:8px">' + UI.pastille(c.statut) + '</div>' +

        '<div style="margin-top:22px;display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:20px">' +
          '<dl style="margin:0;display:grid;gap:13px;font-size:14px">' +
            ligne(UI.t('colis-client'), (c.code_client || '—') + (c.nom_client ? ' · ' + c.nom_client : '')) +
            ligne(UI.t('colis-contenu'), c.description) +
            ligne(UI.t('colis-expediteur'), c.expediteur) +
            ligne(UI.t('colis-service'), UI.t('service-' + c.service) || c.service) +
            ligne(UI.t('colis-poids'), c.poids_lb ? c.poids_lb + ' lb' : '') +
            ligne(UI.t('colis-valeur'), c.valeur_declaree ? UI.montant(c.valeur_declaree) : '') +
            ligne(UI.t('colis-destination'), UI.lieuLivraison(c)) +
            ligne(UI.t('colis-livraison'), c.adresse_livraison) +
            ligne(UI.t('colis-cree'), UI.date(c.cree_le, true)) +
            ligne(UI.t('colis-maj'), UI.date(c.maj_le, true)) +
          '</dl>' +

          '<div style="background:var(--smoke);border:1px solid var(--line);border-radius:14px;padding:18px;text-align:center">' +
            '<p style="margin:0 0 12px;font-size:11px;letter-spacing:.1em;color:#6b7280;font-weight:700">' +
              e(UI.t('fiche-qr')) + '</p>' +
            '<div style="display:inline-block;background:#fff;padding:8px;border-radius:10px">' +
              UI.qr(c, 148) + '</div>' +
            '<p style="margin:16px 0 8px;font-size:11px;letter-spacing:.1em;color:#6b7280;font-weight:700">' +
              e(UI.t('fiche-barres')) + '</p>' +
            '<div style="background:#fff;padding:10px 8px;border-radius:10px">' +
              UI.codeBarres(c, { module: 1.8, hauteur: 52 }) +
              '<p style="margin:4px 0 0;font-family:\'IBM Plex Mono\',monospace;font-size:13px;' +
              'font-weight:600;letter-spacing:.14em">' + e(c.numero) + '</p></div>' +
            '<button type="button" class="ses-bouton ses-bouton-principal ses-bouton-mini" ' +
              'data-action="etiquette" data-id="' + e(c.id) + '" style="margin-top:14px;width:100%">' +
              e(UI.t('fiche-imprimer-etiquette')) + '</button>' +
            (peut('factures.creer') ? '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" ' +
              'data-action="facturer" data-id="' + e(c.id) + '" style="margin-top:8px;width:100%">' +
              e(UI.t('action-facturer')) + '</button>' : '') +
          '</div>' +
        '</div>' +

        '<div style="margin-top:24px;padding-top:20px;border-top:1px solid var(--line)">' +
          '<p style="margin:0 0 14px;font-size:11.5px;letter-spacing:.1em;color:#6b7280;font-weight:700">' +
            e(UI.t('colis-historique')) + ' (' + histo.length + ')</p>' +
          '<ul class="ses-historique">' +
            histo.slice().reverse().map(function (h, n, tout) {
              return UI.ligneHistorique(h, { dernier: n === tout.length - 1 });
            }).join('') +
          '</ul>' +
        '</div>';

      $('#ses-fiche').showModal();
    }).catch(erreurGenerale);
  }

  function ligne(libelle, valeur) {
    if (!valeur) return '';
    return '<div><dt style="font-size:11px;letter-spacing:.09em;color:#6b7280;font-weight:700">' +
      e(libelle) + '</dt><dd style="margin:3px 0 0;font-weight:600">' + e(valeur) + '</dd></div>';
  }

  /* --- Formulaire d'un colis --------------------------------------------- */
  function preparerFormColis() {
    var form = $('#ses-colis');
    remplirStatuts(form.elements.statut);
    completionClient(form, '#ses-clients-trouves', '#ses-client-choisi');

    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      UI.effacerErreurs(form);
      var message = $('#ses-message-colis');
      UI.annonce(message, '');

      if (!form.elements.client_id.value) {
        UI.erreurChamp(form.elements.client_recherche, UI.t('client-requis'));
        return;
      }
      if (!String(form.elements.description.value || '').trim()) {
        UI.erreurChamp(form.elements.description, UI.t('champ-requis'));
        return;
      }

      var champs = {};
      ['client_id', 'description', 'expediteur', 'destinataire', 'poids_lb', 'service',
       'pays_destination', 'ville_destination', 'adresse_livraison', 'valeur_declaree',
       'statut', 'lieu', 'note'].forEach(function (k) {
        if (form.elements[k]) champs[k] = form.elements[k].value;
      });

      var id = form.elements.id.value;
      var rendre = UI.occuper(form.querySelector('button[type="submit"]'), UI.t('attente'));
      var promesse = id ? API.admin.modifierColis(id, champs) : API.admin.creerColis(champs);

      promesse.then(function (c) {
        rendre();
        $('#ses-form-colis').close();
        annoncer(UI.t(id ? 'colis-modifie' : 'colis-cree-ok', { numero: c.numero }), 'succes');
        rafraichir();
        if (!id) setTimeout(function () { ouvrirFiche(c.id); }, 250);
      }).catch(function (err) {
        rendre();
        UI.annonce(message, UI.messageErreur(err), 'erreur');
      });
    });
  }

  function remplirStatuts(select) {
    if (!select) return;
    select.innerHTML = API.STATUTS.map(function (s) {
      return '<option value="' + s + '">' + e(UI.nomStatut(s)) + '</option>';
    }).join('');
  }

  function ouvrirFormColis(colis) {
    var form = $('#ses-colis');
    form.reset();
    UI.effacerErreurs(form);
    UI.annonce($('#ses-message-colis'), '');
    $('#ses-clients-trouves').hidden = true;
    form.elements.id.value = colis ? colis.id : '';
    $('#ses-client-choisi').textContent = '';

    if (colis) {
      ['description', 'expediteur', 'destinataire', 'poids_lb', 'service', 'pays_destination',
       'ville_destination', 'adresse_livraison', 'valeur_declaree', 'statut', 'lieu', 'note'].forEach(function (k) {
        if (form.elements[k]) form.elements[k].value = colis[k] === null || colis[k] === undefined ? '' : colis[k];
      });
      form.elements.client_id.value = colis.client_id || '';
      form.elements.client_recherche.value = colis.code_client || '';
      $('#ses-client-choisi').textContent = [colis.code_client, colis.nom_client].filter(Boolean).join(' · ');
    }
    $('#ses-form-colis-titre').textContent = UI.t(colis ? 'action-modifier' : 'colis-nouveau') ||
      (colis ? 'Modifier le colis' : 'Enregistrer un colis');
    $('#ses-form-colis').showModal();
  }

  /* --- Changement de statut ---------------------------------------------- */
  function preparerFormStatut() {
    var form = $('#ses-statut');
    remplirStatuts(form.elements.statut);
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var message = $('#ses-message-statut');
      UI.annonce(message, '');
      var rendre = UI.occuper(form.querySelector('button[type="submit"]'), UI.t('attente'));
      var id = form.elements.id.value;
      var statut = form.elements.statut.value;
      API.admin.changerStatut(id, statut, form.elements.lieu.value, form.elements.note.value)
        .then(function () {
          rendre();
          $('#ses-form-statut').close();
          var c = etat.colis.lignes.filter(function (x) { return x.id === id; })[0] || {};
          annoncer(UI.t('statut-change', { numero: c.numero || '', statut: UI.nomStatut(statut) }), 'succes');
          rafraichir();
        }).catch(function (err) {
          rendre();
          UI.annonce(message, UI.messageErreur(err), 'erreur');
        });
    });
  }

  function ouvrirFormStatut(colis) {
    var form = $('#ses-statut');
    form.reset();
    UI.annonce($('#ses-message-statut'), '');
    form.elements.id.value = colis.id;
    form.elements.statut.value = colis.statut;
    form.elements.lieu.value = colis.lieu || '';
    form.elements.note.value = colis.note || '';
    $('#ses-statut-colis').textContent = colis.numero;
    $('#ses-form-statut').showModal();
  }

  /* ======================================================================
     Factures
     ====================================================================== */
  function chargerFactures() {
    if (!peut('factures.lire')) return Promise.resolve();
    return API.admin.factures({
      page: etat.factures.page, parPage: PAR_PAGE,
      statut: etat.factures.statut, recherche: etat.factures.recherche
    }).then(function (r) {
      etat.factures.lignes = r.lignes;
      etat.factures.total = r.total;
      listeFactures();
      pagination($('#ses-pages-factures'), etat.factures, chargerFactures);
    }).catch(erreurGenerale);
  }

  function listeFactures() {
    var zone = $('#ses-liste-factures');
    if (!etat.factures.lignes.length) {
      var filtre = etat.factures.statut || etat.factures.recherche;
      zone.innerHTML = '<div class="ses-bloc">' +
        UI.vide(UI.t(filtre ? 'factures-vide-filtre' : 'factures-vide'), '▤') + '</div>';
      return;
    }
    zone.innerHTML = '<table class="ses-tableau"><thead><tr>' +
      ['colonne-numero', 'colonne-client', 'colonne-colis', 'colonne-date', 'colonne-montant', 'colonne-statut']
        .map(function (k) { return '<th>' + e(UI.t(k)) + '</th>'; }).join('') +
      '<th style="text-align:right">' + e(UI.t('colonne-actions')) + '</th></tr></thead><tbody>' +
      etat.factures.lignes.map(function (f) {
        var paye = f.statut === 'payee';
        return '<tr class="ses-ligne">' +
          '<td data-libelle="' + e(UI.t('colonne-numero')) + '" class="ses-mono">' + e(f.numero) + '</td>' +
          '<td data-libelle="' + e(UI.t('colonne-client')) + '">' +
            '<span class="ses-mono" style="font-size:13.5px">' + e(f.code_client || '—') + '</span>' +
            (f.nom_client ? '<br><span style="color:#6b7280;font-size:13.5px">' + e(f.nom_client) + '</span>' : '') + '</td>' +
          '<td data-libelle="' + e(UI.t('colonne-colis')) + '" class="ses-mono">' + e(f.numero_colis || '—') + '</td>' +
          '<td data-libelle="' + e(UI.t('colonne-date')) + '" style="color:#6b7280;font-size:13.5px">' +
            e(UI.date(f.cree_le)) + '</td>' +
          '<td data-libelle="' + e(UI.t('colonne-montant')) + '" class="ses-mono">' +
            e(UI.montant(f.montant, f.devise)) + '</td>' +
          '<td data-libelle="' + e(UI.t('colonne-statut')) + '">' +
            '<span style="display:inline-flex;border-radius:999px;padding:5px 13px;font-weight:700;font-size:13px;' +
            (paye ? 'background:rgba(19,192,44,.12);color:#0b7a19' : 'background:rgba(232,18,27,.1);color:#b60d14') + '">' +
            e(UI.t(paye ? 'facture-payee' : 'facture-impayee')) + '</span></td>' +
          '<td><div class="ses-actions-ligne">' +
            '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" ' +
              'data-action="imprimer-facture" data-id="' + e(f.id) + '">' + e(UI.t('action-imprimer')) + '</button>' +
            (peut('factures.modifier') ?
              '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" ' +
              'data-action="basculer-facture" data-id="' + e(f.id) + '">' +
              e(UI.t(paye ? 'action-impayee' : 'action-payee')) + '</button>' +
              '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" ' +
              'data-action="modifier-facture" data-id="' + e(f.id) + '">' + e(UI.t('action-modifier')) + '</button>' : '') +
            (peut('factures.supprimer') ?
              '<button type="button" class="ses-bouton ses-bouton-danger ses-bouton-mini" ' +
              'data-action="supprimer-facture" data-id="' + e(f.id) + '">' + e(UI.t('action-supprimer')) + '</button>' : '') +
          '</div></td></tr>';
      }).join('') + '</tbody></table>';
  }

  function preparerFormFacture() {
    var form = $('#ses-facture');
    if (!form) return;
    completionClient(form, '#ses-clients-trouves-f', '#ses-client-choisi-f', function (client) {
      // Les colis du client choisi deviennent proposables.
      API.admin.colis({ client_id: client.id, parPage: 100 }).then(function (r) {
        form.elements.colis_id.innerHTML = '<option value="">—</option>' +
          r.lignes.map(function (c) {
            return '<option value="' + e(c.id) + '">' + e(c.numero + ' · ' + (c.description || '')) + '</option>';
          }).join('');
      }).catch(function () {});
    });

    $('#ses-ajouter-ligne').addEventListener('click', function () { ajouterLigne(); });

    form.addEventListener('input', function (ev) {
      if (ev.target.closest('#ses-lignes')) totaliser();
    });

    $('#ses-lignes').addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-retirer]');
      if (!b) return;
      b.closest('.ses-ligne-facture').remove();
      if (!$('#ses-lignes').children.length) ajouterLigne();
      totaliser();
    });

    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var message = $('#ses-message-facture');
      UI.effacerErreurs(form);
      UI.annonce(message, '');

      if (!form.elements.client_id.value) {
        UI.erreurChamp(form.elements.client_recherche, UI.t('client-requis'));
        return;
      }
      var lignes = lignesSaisies();
      if (!lignes.length) {
        UI.annonce(message, UI.t('lignes-requises'), 'erreur');
        return;
      }

      var champs = {
        client_id: form.elements.client_id.value,
        colis_id: form.elements.colis_id.value || null,
        lignes: lignes,
        montant: lignes.reduce(function (a, l) { return a + l.montant; }, 0),
        statut: form.elements.statut.value,
        echeance_le: form.elements.echeance_le.value || null,
        note: form.elements.note.value
      };
      var id = form.elements.id.value;
      var rendre = UI.occuper(form.querySelector('button[type="submit"]'), UI.t('attente'));
      var promesse = id ? API.admin.modifierFacture(id, champs) : API.admin.creerFacture(champs);

      promesse.then(function (f) {
        rendre();
        $('#ses-form-facture').close();
        annoncer(UI.t(id ? 'facture-modifiee' : 'facture-creee', { numero: f.numero }), 'succes');
        chargerFactures();
        chiffres();
      }).catch(function (err) {
        rendre();
        UI.annonce(message, UI.messageErreur(err), 'erreur');
      });
    });
  }

  function ajouterLigne(libelle, montant) {
    var bloc = document.createElement('div');
    bloc.className = 'ses-ligne-facture';
    bloc.style.cssText = 'display:grid;grid-template-columns:1fr 140px auto;gap:10px;align-items:end';
    bloc.innerHTML =
      '<label class="ses-champ"><span style="font-size:12px;color:#6b7280">' + e(UI.t('ligne-libelle')) + '</span>' +
        '<input type="text" class="ses-l-libelle" maxlength="160" value="' + e(libelle || '') + '"></label>' +
      '<label class="ses-champ"><span style="font-size:12px;color:#6b7280">' + e(UI.t('ligne-montant')) + '</span>' +
        '<input type="number" class="ses-l-montant" min="0" step="0.01" value="' +
        (montant === undefined ? '' : e(montant)) + '"></label>' +
      '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-retirer="1" ' +
        'style="height:47px" aria-label="' + e(UI.t('ligne-retirer')) + '">✕</button>';
    $('#ses-lignes').appendChild(bloc);
  }

  function lignesSaisies() {
    return Array.prototype.map.call($('#ses-lignes').children, function (b) {
      return {
        libelle: b.querySelector('.ses-l-libelle').value.trim(),
        montant: Number(b.querySelector('.ses-l-montant').value || 0)
      };
    }).filter(function (l) { return l.libelle || l.montant; });
  }

  function totaliser() {
    var somme = lignesSaisies().reduce(function (a, l) { return a + l.montant; }, 0);
    $('#ses-facture').elements.total_affiche.value = UI.montant(somme);
  }

  function ouvrirFormFacture(facture, colis) {
    var form = $('#ses-facture');
    form.reset();
    UI.effacerErreurs(form);
    UI.annonce($('#ses-message-facture'), '');
    $('#ses-clients-trouves-f').hidden = true;
    $('#ses-lignes').innerHTML = '';
    form.elements.id.value = facture ? facture.id : '';
    form.elements.colis_id.innerHTML = '<option value="">—</option>';

    var poserClient = function (id, code, nom) {
      form.elements.client_id.value = id || '';
      form.elements.client_recherche.value = code || '';
      $('#ses-client-choisi-f').textContent = [code, nom].filter(Boolean).join(' · ');
      if (!id) return;
      API.admin.colis({ client_id: id, parPage: 100 }).then(function (r) {
        form.elements.colis_id.innerHTML = '<option value="">—</option>' +
          r.lignes.map(function (c) {
            return '<option value="' + e(c.id) + '"' +
              ((facture && facture.colis_id === c.id) || (colis && colis.id === c.id) ? ' selected' : '') + '>' +
              e(c.numero + ' · ' + (c.description || '')) + '</option>';
          }).join('');
      }).catch(function () {});
    };

    if (facture) {
      poserClient(facture.client_id, facture.code_client, facture.nom_client);
      (facture.lignes && facture.lignes.length ? facture.lignes : [{ libelle: '', montant: facture.montant }])
        .forEach(function (l) { ajouterLigne(l.libelle, l.montant); });
      form.elements.statut.value = facture.statut;
      form.elements.note.value = facture.note || '';
      if (facture.echeance_le) form.elements.echeance_le.value = String(facture.echeance_le).slice(0, 10);
    } else {
      if (colis) {
        poserClient(colis.client_id, colis.code_client, colis.nom_client);
        ajouterLigne(UI.t('facture-ligne-transport', { numero: colis.numero }), '');
      } else {
        $('#ses-client-choisi-f').textContent = '';
        ajouterLigne();
      }
    }
    totaliser();
    $('#ses-form-facture-titre').textContent = UI.t(facture ? 'action-modifier' : 'facture-nouvelle') ||
      (facture ? 'Modifier la facture' : 'Créer une facture');
    $('#ses-form-facture').showModal();
  }

  /* ======================================================================
     Clients et rôles
     ====================================================================== */
  function chargerClients() {
    if (!peut('clients.lire')) return Promise.resolve();
    return API.admin.clients({
      page: etat.clients.page, parPage: PAR_PAGE,
      role: etat.clients.role, recherche: etat.clients.recherche
    }).then(function (r) {
      etat.clients.lignes = r.lignes;
      etat.clients.total = r.total;
      listeClients();
      pagination($('#ses-pages-clients'), etat.clients, chargerClients);
    }).catch(erreurGenerale);
  }

  function listeClients() {
    var zone = $('#ses-liste-clients');
    if (!etat.clients.lignes.length) {
      zone.innerHTML = '<div class="ses-bloc">' + UI.vide(UI.t('clients-vide'), '◻') + '</div>';
      return;
    }
    zone.innerHTML = '<table class="ses-tableau"><thead><tr>' +
      ['colonne-numero', 'colonne-nom', 'colonne-email', 'colonne-ville', 'colonne-role']
        .map(function (k) { return '<th>' + e(UI.t(k)) + '</th>'; }).join('') +
      '<th style="text-align:right">' + e(UI.t('colonne-actions')) + '</th></tr></thead><tbody>' +
      etat.clients.lignes.map(function (c) {
        return '<tr class="ses-ligne">' +
          '<td data-libelle="' + e(UI.t('colonne-numero')) + '" class="ses-mono">' + e(c.code || '—') + '</td>' +
          '<td data-libelle="' + e(UI.t('colonne-nom')) + '">' + e(c.nom_complet || '—') + '</td>' +
          '<td data-libelle="' + e(UI.t('colonne-email')) + '" style="color:#6b7280;font-size:13.5px">' +
            e(c.email || '') + '</td>' +
          '<td data-libelle="' + e(UI.t('colonne-ville')) + '" style="font-size:13.5px">' +
            e([c.ville, c.pays].filter(Boolean).join(' · ')) + '</td>' +
          '<td data-libelle="' + e(UI.t('colonne-role')) + '">' + roleBadge(c) + '</td>' +
          '<td><div class="ses-actions-ligne">' +
            (peut('colis.lire') ?
              '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" ' +
              'data-action="colis-client" data-id="' + e(c.id) + '">' + e(UI.t('action-colis-du-client')) + '</button>' : '') +
            (peut('roles.gerer') ?
              '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" ' +
              'data-action="role" data-id="' + e(c.id) + '">' + e(UI.t('action-role')) + '</button>' : '') +
          '</div></td></tr>';
      }).join('') + '</tbody></table>';
  }

  function roleBadge(c) {
    var couleurs = {
      client: ['rgba(32,36,42,.08)', '#20242a'],
      employe: ['rgba(26,46,210,.1)', '#1a2ed2'],
      admin: ['rgba(232,18,27,.1)', '#b60d14']
    }[c.role] || ['rgba(32,36,42,.08)', '#20242a'];
    var n = c.role === 'employe' ? (c.droits || []).length : null;
    return '<span style="display:inline-flex;border-radius:999px;padding:5px 13px;font-weight:700;font-size:13px;' +
      'background:' + couleurs[0] + ';color:' + couleurs[1] + '">' +
      e(UI.t('role-' + c.role) || c.role) + (n !== null ? ' · ' + n : '') + '</span>';
  }

  function preparerFormRole() {
    var form = $('#ses-role');
    if (!form) return;
    $('#ses-droits').innerHTML = API.DROITS.map(function (d) {
      return '<label style="display:flex;align-items:center;gap:10px;font-size:14.5px;cursor:pointer">' +
        '<input type="checkbox" value="' + d + '" style="width:17px;height:17px;accent-color:var(--red)">' +
        e(UI.t('droit-' + d) || d) + '</label>';
    }).join('');

    form.elements.role.addEventListener('change', function () {
      $('#ses-bloc-droits').hidden = form.elements.role.value !== 'employe';
    });

    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var message = $('#ses-message-role');
      UI.annonce(message, '');
      var coches = Array.prototype.filter.call($('#ses-droits').querySelectorAll('input'),
        function (i) { return i.checked; }).map(function (i) { return i.value; });
      var rendre = UI.occuper(form.querySelector('button[type="submit"]'), UI.t('attente'));

      API.admin.definirRole(form.elements.id.value, form.elements.role.value, coches)
        .then(function (c) {
          rendre();
          $('#ses-form-role').close();
          annoncer(UI.t('role-change', {
            nom: c.nom_complet || c.email,
            role: UI.t('role-' + c.role) || c.role
          }), 'succes');
          chargerClients();
        }).catch(function (err) {
          rendre();
          UI.annonce(message, UI.messageErreur(err), 'erreur');
        });
    });
  }

  function ouvrirFormRole(compte) {
    var form = $('#ses-role');
    UI.annonce($('#ses-message-role'), '');
    form.elements.id.value = compte.id;
    form.elements.role.value = compte.role;
    $('#ses-bloc-droits').hidden = compte.role !== 'employe';
    var actifs = compte.droits || [];
    Array.prototype.forEach.call($('#ses-droits').querySelectorAll('input'), function (i) {
      i.checked = actifs.indexOf(i.value) >= 0;
    });
    $('#ses-role-compte').textContent = [compte.code, compte.nom_complet, compte.email]
      .filter(Boolean).join(' · ');
    $('#ses-form-role').showModal();
  }

  /* ======================================================================
     Recherche d'un client dans les formulaires
     ====================================================================== */
  function completionClient(form, selecteurListe, selecteurChoisi, apresChoix) {
    var champ = form.elements.client_recherche;
    var liste = $(selecteurListe);
    var minuteur;

    function fermer() {
      liste.hidden = true;
      champ.setAttribute('aria-expanded', 'false');
    }

    champ.addEventListener('input', function () {
      form.elements.client_id.value = '';
      $(selecteurChoisi).textContent = '';
      clearTimeout(minuteur);
      var texte = champ.value.trim();
      if (texte.length < 2) return fermer();
      minuteur = setTimeout(function () {
        API.admin.clients({ recherche: texte, parPage: 8 }).then(function (r) {
          if (!r.lignes.length) {
            liste.innerHTML = '<p style="margin:0;padding:12px 14px;font-size:14px;color:#6b7280">' +
              e(UI.t('client-aucun')) + '</p>';
          } else {
            liste.innerHTML = r.lignes.map(function (c) {
              return '<button type="button" role="option" data-client="' + e(c.id) + '" ' +
                'data-code="' + e(c.code || '') + '" data-nom="' + e(c.nom_complet || '') + '">' +
                '<strong class="ses-mono">' + e(c.code || '—') + '</strong> · ' + e(c.nom_complet || c.email) +
                '<br><span style="color:#6b7280;font-size:13px">' + e(c.email) + '</span></button>';
            }).join('');
          }
          liste.hidden = false;
          champ.setAttribute('aria-expanded', 'true');
        }).catch(function () { fermer(); });
      }, 220);
    });

    liste.addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-client]');
      if (!b) return;
      var id = b.getAttribute('data-client');
      var code = b.getAttribute('data-code');
      var nom = b.getAttribute('data-nom');
      form.elements.client_id.value = id;
      champ.value = code || nom;
      $(selecteurChoisi).textContent = [code, nom].filter(Boolean).join(' · ');
      fermer();
      if (apresChoix) apresChoix({ id: id, code: code, nom_complet: nom });
    });

    document.addEventListener('click', function (ev) {
      if (!liste.contains(ev.target) && ev.target !== champ) fermer();
    });
  }

  /* ======================================================================
     Confirmation d'une suppression
     ====================================================================== */
  var aConfirmer = null;
  function confirmer(texte, action) {
    aConfirmer = action;
    $('#ses-confirmer-texte').textContent = texte;
    $('#ses-confirmer').showModal();
  }

  function preparerConfirmation() {
    $('#ses-confirmer-non').addEventListener('click', function () {
      aConfirmer = null;
      $('#ses-confirmer').close();
    });
    $('#ses-confirmer-oui').addEventListener('click', function () {
      var action = aConfirmer;
      aConfirmer = null;
      $('#ses-confirmer').close();
      if (action) action();
    });
  }

  /* ======================================================================
     Actions groupées
     ====================================================================== */
  function actions() {
    document.addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-action]');
      if (b) {
        var id = b.getAttribute('data-id');
        var action = b.getAttribute('data-action');
        var c = etat.colis.lignes.filter(function (x) { return x.id === id; })[0];
        var f = etat.factures.lignes.filter(function (x) { return x.id === id; })[0];

        if (action === 'fiche') return ouvrirFiche(id);
        if (action === 'statut' && c) return ouvrirFormStatut(c);
        if (action === 'modifier' && c) return ouvrirFormColis(c);
        if (action === 'supprimer' && c) {
          return confirmer(UI.t('confirmer-colis', { numero: c.numero }), function () {
            API.admin.supprimerColis(id).then(function () {
              annoncer(UI.t('colis-supprime'), 'succes');
              rafraichir();
            }).catch(erreurGenerale);
          });
        }
        if (action === 'etiquette') {
          return API.admin.colisParId(id).then(function (colis) {
            if (colis) UI.imprimer(UI.etiquette(colis), 'etiquette');
          }).catch(erreurGenerale);
        }
        if (action === 'facturer') {
          return API.admin.colisParId(id).then(function (colis) {
            $('#ses-fiche').close();
            ouvrirFormFacture(null, colis);
          }).catch(erreurGenerale);
        }
        if (action === 'imprimer-facture' && f) {
          return UI.imprimer(UI.facture(f, null, null), 'facture');
        }
        if (action === 'basculer-facture' && f) {
          return API.admin.modifierFacture(id, { statut: f.statut === 'payee' ? 'impayee' : 'payee' })
            .then(function (x) {
              annoncer(UI.t('facture-modifiee', { numero: x.numero }), 'succes');
              chargerFactures();
              chiffres();
            }).catch(erreurGenerale);
        }
        if (action === 'modifier-facture' && f) return ouvrirFormFacture(f);
        if (action === 'supprimer-facture' && f) {
          return confirmer(UI.t('confirmer-facture', { numero: f.numero }), function () {
            API.admin.supprimerFacture(id).then(function () {
              annoncer(UI.t('facture-supprimee'), 'succes');
              chargerFactures();
              chiffres();
            }).catch(erreurGenerale);
          });
        }
        if (action === 'role') {
          var compte = etat.clients.lignes.filter(function (x) { return x.id === id; })[0];
          if (compte) return ouvrirFormRole(compte);
        }
        if (action === 'colis-client') {
          etat.colis.client_id = id;
          etat.colis.recherche = '';
          etat.colis.statut = '';
          etat.colis.page = 0;
          $('#ses-chercher-colis').value = '';
          document.getElementById('ses-o-colis').click();
          return chargerColis().then(function () { filtres(); });
        }
      }

      if (ev.target.closest('#ses-nouveau-colis')) return ouvrirFormColis(null);
      if (ev.target.closest('#ses-nouvelle-facture')) return ouvrirFormFacture(null);
      if (ev.target.closest('.ses-annuler')) {
        var dlg = ev.target.closest('dialog');
        if (dlg) dlg.close();
        return;
      }
      if (ev.target.closest('#ses-deconnexion')) {
        API.deconnecter().then(function () { location.replace('connexion.html'); });
      }
    });
  }

  /* ======================================================================
     Réglages
     ====================================================================== */
  function reglages() {
    $('#ses-mode-detail').textContent = UI.t('mode-' + API.mode);
    $('#ses-liste-statuts').innerHTML = API.STATUTS.map(function (s) {
      return '<li>' + UI.pastille(s, { petite: true }) + '</li>';
    }).join('');

    if (API.mode !== 'demo' || !API.admin.remplirDemo) return;
    $('#ses-outils-demo').hidden = false;
    $('#ses-remplir').addEventListener('click', function () {
      var rendre = UI.occuper($('#ses-remplir'), UI.t('attente'));
      API.admin.remplirDemo().then(function (fait) {
        rendre();
        annoncer(UI.t(fait ? 'demo-rempli' : 'demo-deja'), fait ? 'succes' : 'info');
        rafraichir();
        chargerFactures();
        chargerClients();
      }).catch(function (err) { rendre(); erreurGenerale(err); });
    });
    $('#ses-effacer').addEventListener('click', function () {
      confirmer(UI.t('confirmer-demo'), function () {
        API.admin.effacerDemo().then(function () { location.replace('connexion.html'); });
      });
    });
  }

  /* ====================================================================== */
  function annoncer(texte, genre) {
    var zone = $('#ses-message');
    UI.annonce(zone, texte, genre);
    zone.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    clearTimeout(annoncer.minuteur);
    annoncer.minuteur = setTimeout(function () { UI.annonce(zone, ''); }, 6000);
  }

  function erreurGenerale(err) {
    annoncer(UI.messageErreur(err), 'erreur');
  }

  function rafraichir() {
    chargerColis();
    chiffres();
  }

  function demarrer() {
    // Sans le droit de voir les colis, ce tableau de bord n'a rien à montrer.
    API.exigerProfil({ droit: 'colis.lire' }).then(function (p) {
      if (!p) return;
      moi = p;
      droits = API.droitsDe(p);
      poserIdentite();
      onglets();
      filtres();
      actions();
      preparerFormColis();
      preparerFormStatut();
      preparerFormFacture();
      preparerFormRole();
      preparerConfirmation();
      reglages();
      chiffres();
      UI.surLangue(function () {
        poserIdentite();
        filtres();
        reglages();
        chiffres();
        listeColis();
        if (etat.factures.lignes.length) listeFactures();
        if (etat.clients.lignes.length) listeClients();
      });
      return chargerColis();
    }).then(function () {
      if (moi) API.surveiller(function () { chargerColis(); chiffres(); });
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', demarrer);
  else demarrer();
})();
