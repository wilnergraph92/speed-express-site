/* ==========================================================================
   Portail client — adresses, enlèvement, livraison, notifications, support, profil
   --------------------------------------------------------------------------
   Ici le client AGIT : il enregistre une adresse, demande un enlèvement ou une
   livraison, écrit au support. Chaque action passe par une fonction de la base
   qui lit le compte connecté et applique SES règles (dates, plafonds, droits).
   Les contrôles de ce fichier ne servent qu'à répondre vite et dans la langue
   du client : ils ne protègent rien — le serveur a toujours le dernier mot.
   ========================================================================== */
(function () {
  'use strict';
  var P = window.SES_PORTAIL, API = window.SES_API, UI = window.SES_UI;
  if (!P || !API || !UI) return;
  var t = P.t, e = P.e;
  var PAYS = ['HT', 'DO', 'US'];
  var CRENEAUX = ['ANY', 'MORNING', 'AFTERNOON'];

  function payeOptions() { return PAYS.map(function (c) { return [c, t('pays-' + c)]; }); }
  function formValeur(form, nom) { return form.elements[nom] ? String(form.elements[nom].value || '').trim() : ''; }

  /* ----------------------------------------------------------------------
     Un bloc d'adresse commun aux demandes d'enlèvement et de livraison :
     une adresse enregistrée, ou une adresse saisie sur place.
     ---------------------------------------------------------------------- */
  function blocAdresse(id, adresses) {
    var defaut = adresses.filter(function (a) { return a.is_default; })[0] || adresses[0];
    var options = adresses.map(function (a) { return [a.address_id, (a.label ? a.label + ' — ' : '') + a.address + (a.city ? ', ' + a.city : '')]; }).concat([['', t('p-adr-autre')]]);
    return P.champ({ id: id + '-adresse', nom: 'adresseId', libelle: 'p-adr-choisir', type: 'select', options: options, valeur: defaut ? defaut.address_id : '' }) +
      '<div class="ses-adresse-libre" hidden><div class="ses-grille2">' +
        P.champ({ id: id + '-libre', nom: 'adresse', libelle: 'p-adr-adresse', max: 200, auto: 'street-address' }) +
        P.champ({ id: id + '-ville', nom: 'ville', libelle: 'p-adr-ville', max: 80, auto: 'address-level2' }) + '</div>' +
        P.champ({ id: id + '-pays', nom: 'pays', libelle: 'p-adr-pays', type: 'select', options: payeOptions(), valeur: 'HT' }) + '</div>';
  }
  function brancherAdresse(form) {
    var s = form.elements.adresseId, libre = form.querySelector('.ses-adresse-libre');
    function maj() { libre.hidden = !!s.value; }
    s.addEventListener('change', maj);
    maj();
  }
  /* Lit le bloc : soit l'identifiant d'une adresse enregistrée, soit l'adresse saisie. Rend null (et marque le champ) si elle manque. */
  function lireAdresse(form) {
    if (form.elements.adresseId.value) return { adresseId: form.elements.adresseId.value };
    var a = formValeur(form, 'adresse');
    if (!a) { UI.erreurChamp(form.elements.adresse, t('p-err-adresse')); return null; }
    return { adresse: a, ville: formValeur(form, 'ville'), pays: form.elements.pays.value };
  }
  function lireDate(form) {
    var c = form.elements.date, v = c.value;
    if (!v || v < P.jour(0) || v > P.jour(60)) { UI.erreurChamp(c, t('p-err-date')); return null; }
    return v;
  }

  /* ----------------------------------------------------------------------
     Adresses
     ---------------------------------------------------------------------- */
  function formulaireAdresse(zone, a, adresses) {
    var nouvelle = !a;
    a = a || { country: 'HT', is_default: !adresses.length };
    zone.innerHTML = '<p class="ses-retour"><a href="' + P.lien('adresses') + '">← ' + e(t('p-adr-retour')) + '</a></p>' + P.titre(nouvelle ? 'p-adr-nouvelle' : 'p-adr-modifier') +
      '<form class="ses-carte ses-bloc" novalidate><div id="ses-p-adr-msg" hidden style="margin-bottom:16px"></div>' +
        '<div class="ses-grille2">' + P.champ({ id: 'ses-a-label', nom: 'etiquette', libelle: 'p-adr-etiquette', max: 40, valeur: a.label, placeholder: t('p-adr-etiquette-ex') }) +
        P.champ({ id: 'ses-a-dest', nom: 'destinataire', libelle: 'p-adr-destinataire', max: 120, valeur: a.recipient_name, auto: 'name' }) + '</div>' +
        '<div class="ses-grille2" style="margin-top:14px">' + P.champ({ id: 'ses-a-tel', nom: 'telephone', libelle: 'p-adr-telephone', type: 'tel', max: 40, valeur: a.phone, auto: 'tel' }) +
        P.champ({ id: 'ses-a-pays', nom: 'pays', libelle: 'p-adr-pays', type: 'select', options: payeOptions(), valeur: a.country, requis: true }) + '</div>' +
        '<div class="ses-grille2" style="margin-top:14px">' + P.champ({ id: 'ses-a-region', nom: 'region', libelle: 'p-adr-region', max: 80, valeur: a.region, auto: 'address-level1' }) +
        P.champ({ id: 'ses-a-ville', nom: 'ville', libelle: 'p-adr-ville', max: 80, valeur: a.city, auto: 'address-level2' }) + '</div>' +
        '<div style="margin-top:14px">' + P.champ({ id: 'ses-a-adresse', nom: 'adresse', libelle: 'p-adr-adresse', max: 200, valeur: a.address, requis: true, auto: 'street-address' }) + '</div>' +
        '<div style="margin-top:14px">' + P.champ({ id: 'ses-a-consignes', nom: 'consignes', libelle: 'p-adr-consignes', type: 'textarea', lignes: 3, max: 300, valeur: a.instructions, aide: t('p-adr-consignes-aide') }) + '</div>' +
        '<label class="ses-case" style="margin-top:14px"><input type="checkbox" name="parDefaut"' + (a.is_default ? ' checked' : '') + '><span>' + e(t('p-adr-defaut')) + '</span></label>' +
        '<p style="margin:20px 0 0;display:flex;flex-wrap:wrap;gap:10px"><button type="submit" class="ses-bouton ses-bouton-principal">' + e(t('p-enregistrer')) + '</button>' +
        '<a class="ses-bouton ses-bouton-second" href="' + P.lien('adresses') + '">' + e(t('p-annuler')) + '</a></p></form>';
    var form = zone.querySelector('form'), msg = zone.querySelector('#ses-p-adr-msg');
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      UI.effacerErreurs(form);
      if (!formValeur(form, 'adresse')) { UI.erreurChamp(form.elements.adresse, t('p-err-adresse')); return; }
      var tel = formValeur(form, 'telephone');
      if (tel && !UI.telephoneValide(tel)) { UI.erreurChamp(form.elements.telephone, t('telephone-invalide')); return; }
      P.agir(form.querySelector('button[type="submit"]'), msg, function () {
        return API.portail.enregistrerAdresse({ id: a.address_id, pays: form.elements.pays.value, adresse: formValeur(form, 'adresse'), etiquette: formValeur(form, 'etiquette'), destinataire: formValeur(form, 'destinataire'),
          telephone: tel, region: formValeur(form, 'region'), ville: formValeur(form, 'ville'), consignes: formValeur(form, 'consignes'), parDefaut: form.elements.parDefaut.checked });
      }, null, function () { P.dessiner('adresses'); P.aller('adresses'); });
    });
  }

  P.enregistrer({
    id: 'adresses', ordre: 90,
    rendre: function (zone, param) {
      return P.charger(zone, function () { return API.portail.adresses(); }, function (liste) {
        if (param) {
          var a = param === 'nouvelle' ? null : liste.filter(function (x) { return x.address_id === param; })[0];
          if (param === 'nouvelle' || a) { formulaireAdresse(zone, a, liste); return; }
        }
        zone.innerHTML = P.titre('p-nav-adresses', 'p-adr-intro') + '<div id="ses-p-adr-liste-msg" hidden style="margin-bottom:14px"></div>' +
          '<p style="margin:0 0 16px"><a class="ses-bouton ses-bouton-principal" href="' + P.lien('adresses', 'nouvelle') + '">' + e(t('p-adr-ajouter')) + '</a></p>' +
          (liste.length ? liste.map(function (a) {
            return '<article class="ses-carte ses-bloc ses-fiche"><div class="ses-fiche-tete"><div><p class="ses-fiche-num">' + e(a.label || a.address) + '</p>' +
              '<p class="ses-fiche-desc">' + e(a.address) + (a.city ? ', ' + e(a.city) : '') + (a.region ? ', ' + e(a.region) : '') + ' — ' + e(P.pays(a.country)) + '</p></div>' +
              (a.is_default ? P.pastille('p-adr-par-defaut', 'ok') : '') + '</div><dl class="ses-dl" style="margin-top:10px">' + P.detail(t('p-adr-destinataire'), a.recipient_name) + P.detail(t('p-adr-telephone'), a.phone) +
              P.detail(t('p-adr-consignes'), a.instructions) + '</dl><p style="margin:12px 0 0;display:flex;gap:8px;flex-wrap:wrap"><a class="ses-bouton ses-bouton-second ses-bouton-mini" href="' + P.lien('adresses', a.address_id) + '">' + e(t('p-modifier')) + '</a>' +
              '<button type="button" class="ses-bouton ses-bouton-danger ses-bouton-mini" data-supprimer="' + e(a.address_id) + '">' + e(t('p-supprimer')) + '</button></p></article>';
          }).join('') : '<div class="ses-bloc">' + UI.vide(t('p-adr-vide'), '⌂') + '</div>');
        zone.addEventListener('click', function suppr(ev) {
          var b = ev.target.closest('[data-supprimer]');
          if (!b) return;
          if (!P.confirmer('p-adr-confirmer')) return;
          P.agir(b, zone.querySelector('#ses-p-adr-liste-msg'), function () { return API.portail.supprimerAdresse(b.getAttribute('data-supprimer')); }, 'p-adr-supprimee', function () { zone.removeEventListener('click', suppr); P.dessiner('adresses'); });
        });
      });
    }
  });

  /* ----------------------------------------------------------------------
     Enlèvement
     ---------------------------------------------------------------------- */
  function ligneDemande(r, annuler) {
    return '<article class="ses-carte ses-bloc ses-fiche"><div class="ses-fiche-tete"><div><p class="ses-mono ses-fiche-num">' + e(r.number) + '</p><p class="ses-fiche-desc">' + e(r.address) + (r.city ? ', ' + e(r.city) : '') +
      (r.country ? ' — ' + e(P.pays(r.country)) : '') + '</p></div>' + P.pastilleEtape(r.stage, 'req') + '</div><dl class="ses-dl" style="margin-top:10px">' +
      P.detail(t('p-date'), r.date ? UI.date(r.date) : '') + P.detail(t('p-creneau'), r.window ? t('win-' + r.window) : '') +
      (r.parcels_expected ? P.detail(t('p-colis-prevus'), r.parcels_expected) : '') +
      (r.parcels ? P.detail(t('p-colis'), r.parcels.join(', ')) : '') + P.detail(t('p-notes'), r.notes) + P.detail(t('p-message-equipe'), r.message) + '</dl>' +
      (annuler && r.request_status === 'REQUESTED' ? '<p style="margin:12px 0 0"><button type="button" class="ses-bouton ses-bouton-danger ses-bouton-mini" data-annuler="' + e(r.pickup_id || r.request_id) + '">' + e(t('p-annuler-demande')) + '</button></p>' : '') + '</article>';
  }

  P.enregistrer({
    id: 'enlevements', ordre: 100,
    rendre: function (zone) {
      return P.charger(zone, function () { return Promise.all([API.portail.enlevements(), API.portail.adresses()]); }, function (r) {
        var liste = r[0], adresses = r[1];
        zone.innerHTML = P.titre('p-nav-enlevements', 'p-enl-intro') +
          '<form class="ses-carte ses-bloc" novalidate><h3>' + e(t('p-enl-nouveau')) + '</h3><div id="ses-p-enl-msg" hidden style="margin-bottom:14px"></div>' + blocAdresse('ses-e', adresses) +
          '<div class="ses-grille2" style="margin-top:14px">' + P.champ({ id: 'ses-e-date', nom: 'date', libelle: 'p-date-souhaitee', type: 'date', requis: true, min: P.jour(0), maxNombre: P.jour(60), valeur: P.jour(1) }) +
          P.champ({ id: 'ses-e-creneau', nom: 'creneau', libelle: 'p-creneau', type: 'select', options: P.options(CRENEAUX, 'win-'), valeur: 'ANY' }) + '</div>' +
          '<div class="ses-grille2" style="margin-top:14px">' + P.champ({ id: 'ses-e-colis', nom: 'colis', libelle: 'p-colis-prevus', type: 'number', min: 1, maxNombre: 100, valeur: 1, requis: true }) +
          P.champ({ id: 'ses-e-contact', nom: 'telephone', libelle: 'p-telephone-contact', type: 'tel', max: 40, auto: 'tel' }) + '</div>' +
          '<div style="margin-top:14px">' + P.champ({ id: 'ses-e-notes', nom: 'notes', libelle: 'p-notes', type: 'textarea', lignes: 3, max: 500, aide: t('p-notes-aide-enl') }) + '</div>' +
          '<p style="margin:18px 0 0"><button type="submit" class="ses-bouton ses-bouton-principal">' + e(t('p-enl-envoyer')) + '</button></p></form>' +
          '<h3 style="margin:28px 0 12px">' + e(t('p-enl-mes-demandes')) + '</h3><div class="ses-liste-demandes">' + (liste.length ? liste.map(function (x) { return ligneDemande(x, true); }).join('') : '<div class="ses-bloc">' + UI.vide(t('p-enl-vide'), '⇪') + '</div>') + '</div>';
        var form = zone.querySelector('form'), msg = zone.querySelector('#ses-p-enl-msg');
        brancherAdresse(form);
        form.addEventListener('submit', function (ev) {
          ev.preventDefault();
          UI.effacerErreurs(form);
          var adr = lireAdresse(form), date = lireDate(form), n = Number(form.elements.colis.value);
          if (!adr || !date) return;
          if (!n || n < 1 || n > 100) { UI.erreurChamp(form.elements.colis, t('p-err-colis')); return; }
          var tel = formValeur(form, 'telephone');
          if (tel && !UI.telephoneValide(tel)) { UI.erreurChamp(form.elements.telephone, t('telephone-invalide')); return; }
          var corps = { date: date, colis: n, creneau: form.elements.creneau.value, notes: formValeur(form, 'notes'), telephone: tel || undefined, cle: P.cleEnvoi(form) };
          Object.keys(adr).forEach(function (k) { corps[k] = adr[k]; });
          P.agir(form.querySelector('button[type="submit"]'), msg, function () { return API.portail.demanderEnlevement(corps); }, null, function () { P.nouvelleCle(form); P.recharger(); P.dessiner('enlevements'); });
        });
        zone.querySelector('.ses-liste-demandes').addEventListener('click', function (ev) {
          var b = ev.target.closest('[data-annuler]');
          if (!b || !P.confirmer('p-annuler-confirmer')) return;
          P.agir(b, msg, function () { return API.portail.annulerEnlevement(b.getAttribute('data-annuler')); }, null, function () { P.recharger(); P.dessiner('enlevements'); });
        });
      });
    }
  });

  /* ----------------------------------------------------------------------
     Livraison
     ---------------------------------------------------------------------- */
  P.enregistrer({
    id: 'livraisons', ordre: 110,
    rendre: function (zone) {
      return P.charger(zone, function () { return Promise.all([API.portail.livraisons(), API.portail.adresses()]); }, function (r) {
        var d = r[0], adresses = r[1];
        var carteForm = d.at_hub.length ?
          '<form class="ses-carte ses-bloc" novalidate><h3>' + e(t('p-liv-nouveau')) + '</h3><p class="ses-muet">' + e(t('p-liv-aide')) + '</p><div id="ses-p-liv-msg" hidden style="margin-bottom:14px"></div>' +
          '<fieldset class="ses-groupe"><legend>' + e(t('p-liv-colis-au-hub')) + '</legend>' + d.at_hub.map(function (c, i) {
            return '<label class="ses-case"><input type="checkbox" name="colis" value="' + e(c.tracking_number) + '"' + (d.at_hub.length === 1 ? ' checked' : '') + '><span><span class="ses-mono">' + e(c.tracking_number) + '</span> — ' + e(c.description || '') + '</span></label>';
          }).join('') + '</fieldset>' + '<div style="margin-top:14px">' + blocAdresse('ses-l', adresses) + '</div>' +
          '<div class="ses-grille2" style="margin-top:14px">' + P.champ({ id: 'ses-l-date', nom: 'date', libelle: 'p-date-souhaitee', type: 'date', requis: true, min: P.jour(0), maxNombre: P.jour(60), valeur: P.jour(1) }) +
          P.champ({ id: 'ses-l-creneau', nom: 'creneau', libelle: 'p-creneau', type: 'select', options: P.options(CRENEAUX, 'win-'), valeur: 'ANY' }) + '</div>' +
          '<div style="margin-top:14px">' + P.champ({ id: 'ses-l-notes', nom: 'notes', libelle: 'p-notes', type: 'textarea', lignes: 3, max: 500, aide: t('p-notes-aide-liv') }) + '</div>' +
          '<p style="margin:18px 0 0"><button type="submit" class="ses-bouton ses-bouton-principal">' + e(t('p-liv-envoyer')) + '</button></p></form>' :
          '<div class="ses-bloc">' + UI.vide(t('p-liv-rien-au-hub'), '⇩') + '</div>';
        zone.innerHTML = P.titre('p-nav-livraisons', 'p-liv-intro') + carteForm +
          '<h3 style="margin:28px 0 12px">' + e(t('p-liv-mes-demandes')) + '</h3><div class="ses-liste-demandes">' + (d.requests.length ? d.requests.map(function (x) { return ligneDemande(x, true); }).join('') : '<p class="ses-muet">' + e(t('p-liv-aucune-demande')) + '</p>') + '</div>' +
          '<h3 style="margin:28px 0 12px">' + e(t('p-liv-livraisons')) + '</h3>' + (d.deliveries.length ? d.deliveries.map(function (l) {
            var fenetre = l.window_start && l.window_end ? UI.date(l.window_start, true) + ' – ' + UI.date(l.window_end, true) : '';
            return '<article class="ses-carte ses-bloc ses-fiche"><div class="ses-fiche-tete"><div><p class="ses-fiche-desc">' + e(l.address) + '</p></div>' + P.pastilleEtape(l.stage, 'req') + '</div><dl class="ses-dl" style="margin-top:10px">' +
              P.detail(t('p-date'), l.date ? UI.date(l.date) : '') + P.detail(t('p-d-fenetre'), fenetre) + P.detail(t('p-colis'), l.parcels.join(', ')) +
              P.detail(t('p-d-code-livraison'), l.otp_required ? t(l.otp_issued ? 'p-d-code-envoye' : 'p-d-code-exige') : '') + P.detail(t('p-d-incident'), l.failure ? t('incident-' + l.failure) || l.failure : '') +
              P.detail(t('p-d-recu-par'), l.proof ? l.proof.recipient_name : '') + P.detail(t('p-d-recu-le'), l.proof ? UI.date(l.proof.delivered_at, true) : '') + '</dl></article>';
          }).join('') : '<p class="ses-muet">' + e(t('p-liv-aucune')) + '</p>');
        var form = zone.querySelector('form'), msg = zone.querySelector('#ses-p-liv-msg');
        if (form) {
          brancherAdresse(form);
          form.addEventListener('submit', function (ev) {
            ev.preventDefault();
            UI.effacerErreurs(form);
            var choisis = Array.prototype.map.call(form.querySelectorAll('input[name="colis"]:checked'), function (c) { return c.value; });
            if (!choisis.length) { UI.annonce(msg, t('p-err-choisir-colis'), 'erreur'); return; }
            var adr = lireAdresse(form), date = lireDate(form);
            if (!adr || !date) return;
            var corps = { colis: choisis, date: date, creneau: form.elements.creneau.value, notes: formValeur(form, 'notes'), cle: P.cleEnvoi(form) };
            Object.keys(adr).forEach(function (k) { corps[k] = adr[k]; });
            P.agir(form.querySelector('button[type="submit"]'), msg, function () { return API.portail.demanderLivraison(corps); }, null, function () { P.nouvelleCle(form); P.recharger(); P.dessiner('livraisons'); });
          });
        }
        zone.querySelector('.ses-liste-demandes').addEventListener('click', function (ev) {
          var b = ev.target.closest('[data-annuler]');
          if (!b || !P.confirmer('p-annuler-confirmer')) return;
          P.agir(b, msg || zone, function () { return API.portail.annulerLivraison(b.getAttribute('data-annuler')); }, null, function () { P.recharger(); P.dessiner('livraisons'); });
        });
      });
    }
  });

  /* ----------------------------------------------------------------------
     Notifications
     ---------------------------------------------------------------------- */
  function texteNotification(n) {
    var cle = 'notif-' + n.template;
    var texte = t(cle, n.payload || {});
    return texte || t('p-notif-autre');
  }

  P.enregistrer({
    id: 'notifications', ordre: 120, toujours: true,
    rendre: function (zone) {
      return P.charger(zone, function () { return API.portail.notifications({ limite: 100 }); }, function (r) {
        zone.innerHTML = P.titre('p-nav-notifications', 'p-notif-intro') + '<div id="ses-p-notif-msg" hidden></div>' +
          (r.items.length ? '<p style="margin:0 0 14px;display:flex;align-items:center;gap:12px;flex-wrap:wrap"><span class="ses-muet">' + e(t('p-notif-non-lues', { nombre: r.unread })) + '</span>' +
            (r.unread ? '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-tout>' + e(t('p-notif-tout-lire')) + '</button>' : '') + '</p><ul class="ses-notifs">' +
            r.items.map(function (n) {
              var lien = n.payload && n.payload.tracking_number ? ' <a href="' + P.lien('colis', n.payload.tracking_number) + '">' + e(n.payload.tracking_number) + '</a>' : '';
              return '<li class="ses-notif' + (n.read_at ? '' : ' ses-notif-nouvelle') + '"><p>' + (n.read_at ? '' : '<span class="sr-only">' + e(t('p-notif-nouvelle')) + ' — </span>') + e(texteNotification(n)) + lien + '</p>' +
                '<p class="ses-muet">' + e(UI.date(n.created_at, true)) + '</p>' + (n.read_at ? '' : '<button type="button" class="ses-lien" data-lire="' + n.id + '">' + e(t('p-notif-lire')) + '</button>') + '</li>';
            }).join('') + '</ul>' : '<div class="ses-bloc">' + UI.vide(t('p-notif-vide'), '🔔') + '</div>');
        function apres() { P.recharger(); P.dessiner('notifications'); }
        zone.addEventListener('click', function sur(ev) {
          var un = ev.target.closest('[data-lire]'), tout = ev.target.closest('[data-tout]');
          if (!un && !tout) return;
          zone.removeEventListener('click', sur);
          API.portail.lireNotifications(un ? [Number(un.getAttribute('data-lire'))] : undefined).then(apres, function (err) { UI.annonce(zone.querySelector('#ses-p-notif-msg'), P.message(err), 'erreur'); });
        });
      });
    }
  });

  /* ----------------------------------------------------------------------
     Support
     ---------------------------------------------------------------------- */
  var CATEGORIES = ['PARCEL', 'INVOICE', 'PICKUP', 'DELIVERY', 'ACCOUNT', 'OTHER'];

  function formulaireTicket(zone, prefill) {
    zone.innerHTML = '<p class="ses-retour"><a href="' + P.lien('support') + '">← ' + e(t('p-sup-retour')) + '</a></p>' + P.titre('p-sup-nouveau') +
      '<form class="ses-carte ses-bloc" novalidate><div id="ses-p-tk-msg" hidden style="margin-bottom:16px"></div>' +
      P.champ({ id: 'ses-k-cat', nom: 'categorie', libelle: 'p-sup-categorie', type: 'select', options: P.options(CATEGORIES, 'cat-'), valeur: prefill.categorie || (prefill.colis ? 'PARCEL' : (prefill.facture ? 'INVOICE' : 'OTHER')) }) +
      '<div style="margin-top:14px">' + P.champ({ id: 'ses-k-sujet', nom: 'sujet', libelle: 'p-sup-sujet', requis: true, max: 120 }) + '</div>' +
      '<div class="ses-grille2" style="margin-top:14px">' + P.champ({ id: 'ses-k-colis', nom: 'colis', libelle: 'p-sup-colis-facultatif', max: 40, valeur: prefill.colis, placeholder: 'SES-10001-HT' }) +
      P.champ({ id: 'ses-k-facture', nom: 'facture', libelle: 'p-sup-facture-facultatif', max: 40, valeur: prefill.facture }) + '</div>' +
      '<div style="margin-top:14px">' + P.champ({ id: 'ses-k-msg', nom: 'message', libelle: 'p-sup-message', type: 'textarea', lignes: 6, requis: true, max: 4000 }) + '</div>' +
      '<p style="margin:18px 0 0"><button type="submit" class="ses-bouton ses-bouton-principal">' + e(t('p-sup-envoyer')) + '</button></p></form>';
    var form = zone.querySelector('form'), msg = zone.querySelector('#ses-p-tk-msg');
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      UI.effacerErreurs(form);
      var sujet = formValeur(form, 'sujet'), message = formValeur(form, 'message');
      if (sujet.length < 3) { UI.erreurChamp(form.elements.sujet, t('p-err-sujet')); return; }
      if (!message) { UI.erreurChamp(form.elements.message, t('p-err-message')); return; }
      P.agir(form.querySelector('button[type="submit"]'), msg, function () {
        return API.portail.ouvrirTicket({ sujet: sujet, categorie: form.elements.categorie.value, message: message, colis: formValeur(form, 'colis') || undefined, facture: formValeur(form, 'facture') || undefined, cle: P.cleEnvoi(form) });
      }, null, function (r) { P.recharger(); P.aller('support', r.ticket_id); });
    });
  }

  function dessinerTicket(zone, tk) {
    var ferme = tk.status === 'CLOSED';
    zone.innerHTML = '<p class="ses-retour"><a href="' + P.lien('support') + '">← ' + e(t('p-sup-retour')) + '</a></p>' +
      '<header class="ses-ph"><h2 tabindex="-1">' + e(tk.subject) + '</h2><p><span class="ses-mono">' + e(tk.number) + '</span> · ' + P.pastille('tk-' + tk.status, ferme ? 'neutre' : (tk.status === 'ANSWERED' ? 'ok' : 'info')) + ' · ' + e(t('cat-' + tk.category)) + '</p></header>' +
      '<div class="ses-carte ses-bloc"><p class="ses-muet" style="margin-top:0">' + (tk.parcel ? e(t('p-colis')) + ' : <a href="' + P.lien('colis', tk.parcel) + '">' + e(tk.parcel) + '</a> ' : '') +
      (tk.invoice ? e(t('p-sup-facture')) + ' : <a href="' + P.lien('factures', tk.invoice) + '">' + e(tk.invoice) + '</a>' : '') + '</p><ol class="ses-fil" aria-label="' + e(t('p-sup-messages')) + '">' + tk.messages.map(function (m) {
        return '<li class="ses-msg ses-msg-' + (m.author === 'STAFF' ? 'equipe' : 'client') + '"><p class="ses-msg-qui">' + e(t('tk-author-' + m.author)) + ' <span class="ses-muet">· ' + e(UI.date(m.at, true)) + '</span></p><p class="ses-msg-corps">' + e(m.body) + '</p></li>';
      }).join('') + '</ol></div>' + (ferme ? '<p class="ses-muet" style="margin-top:14px">' + e(t('p-sup-ferme')) + '</p>' :
        '<form class="ses-carte ses-bloc" novalidate style="margin-top:18px"><div id="ses-p-rep-msg" hidden style="margin-bottom:14px"></div>' + P.champ({ id: 'ses-k-rep', nom: 'message', libelle: 'p-sup-repondre', type: 'textarea', lignes: 4, requis: true, max: 4000 }) +
        '<p style="margin:16px 0 0;display:flex;gap:10px;flex-wrap:wrap"><button type="submit" class="ses-bouton ses-bouton-principal">' + e(t('p-sup-envoyer-reponse')) + '</button>' +
        '<button type="button" class="ses-bouton ses-bouton-second" data-fermer>' + e(t('p-sup-fermer')) + '</button></p></form>');
    var form = zone.querySelector('form');
    if (!form) return;
    var msg = zone.querySelector('#ses-p-rep-msg');
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      UI.effacerErreurs(form);
      var m = formValeur(form, 'message');
      if (!m) { UI.erreurChamp(form.elements.message, t('p-err-message')); return; }
      P.agir(form.querySelector('button[type="submit"]'), msg, function () { return API.portail.repondreTicket(tk.ticket_id, m); }, null, function () { P.recharger(); P.dessiner('support'); });
    });
    form.querySelector('[data-fermer]').addEventListener('click', function (ev) {
      if (!P.confirmer('p-sup-fermer-confirmer')) return;
      P.agir(ev.currentTarget, msg, function () { return API.portail.fermerTicket(tk.ticket_id); }, null, function () { P.recharger(); P.dessiner('support'); });
    });
  }

  P.enregistrer({
    id: 'support', ordre: 130,
    rendre: function (zone, param) {
      if (param && param.indexOf('nouveau') === 0) {
        var morceaux = param.split('/'), prefill = {};
        if (morceaux[1]) { if (morceaux[0] === 'nouveau-facture') prefill.facture = morceaux[1]; else prefill.colis = morceaux[1]; }
        formulaireTicket(zone, prefill);
        return Promise.resolve();
      }
      if (param) return P.charger(zone, function () { return API.portail.ticket(param); }, function (tk) { dessinerTicket(zone, tk); });
      return P.charger(zone, function () { return API.portail.tickets(); }, function (liste) {
        var wa = CFGWhatsapp();
        zone.innerHTML = P.titre('p-nav-support', 'p-sup-intro') + '<p style="margin:0 0 16px;display:flex;gap:10px;flex-wrap:wrap"><a class="ses-bouton ses-bouton-principal" href="' + P.lien('support', 'nouveau') + '">' + e(t('p-sup-nouveau')) + '</a>' +
          (wa ? '<a class="ses-bouton ses-bouton-second" href="' + e(wa) + '" rel="noopener">' + e(t('p-sup-whatsapp')) + '</a>' : '') + '</p>' +
          (liste.length ? liste.map(function (k) {
            return '<article class="ses-carte ses-bloc ses-fiche"><div class="ses-fiche-tete"><div style="min-width:0"><p class="ses-fiche-num"><a href="' + P.lien('support', k.ticket_id) + '">' + e(k.subject) + '</a></p>' +
              '<p class="ses-fiche-desc"><span class="ses-mono">' + e(k.number) + '</span> · ' + e(t('cat-' + k.category)) + ' · ' + e(t('p-sup-n-messages', { nombre: k.messages })) + '</p></div>' +
              P.pastille('tk-' + k.status, k.status === 'CLOSED' ? 'neutre' : (k.status === 'ANSWERED' ? 'ok' : 'info')) + '</div><p class="ses-muet" style="margin:10px 0 0">' + e(t('p-sup-maj', { date: UI.date(k.updated_at, true) })) +
              (k.last_author === 'STAFF' && k.status !== 'CLOSED' ? ' · <strong>' + e(t('p-sup-reponse-equipe')) + '</strong>' : '') + '</p></article>';
          }).join('') : '<div class="ses-bloc">' + UI.vide(t('p-sup-vide'), '✉') + '</div>');
      });
    }
  });
  function CFGWhatsapp() {
    var CFG = window.SES_CONFIG || {}, m = P.profil() || {};
    return CFG.whatsapp ? 'https://wa.me/' + CFG.whatsapp + '?text=' + encodeURIComponent('Bonjour, je suis ' + (m.nom_complet || '') + ' (' + (m.code || '') + ').') : '';
  }

  /* ----------------------------------------------------------------------
     Profil : le panneau « Mon compte » de l'espace d'avant, tel quel (mêmes
     formulaires, mêmes règles) — il est déplacé ici, pas recopié.
     ---------------------------------------------------------------------- */
  /* Comment être prévenu (phase 13) : un interrupteur par canal que la base sait servir. Le portail ne se coupe pas ; un canal sans
     fournisseur (SMS, WhatsApp) se demande, et servira dès qu'il sera ouvert. La base garde le choix et le trace. */
  var CANAUX_TEXTE = { email: 'p-pref-email', push: 'p-pref-push', sms: 'p-pref-sms', whatsapp: 'p-pref-whatsapp', in_app: 'p-pref-in_app' };
  function preferences(zone) {
    if (!API.notifications || !API.notifications.preferences) return;
    var bloc = zone.querySelector('#ses-p-prefs');
    if (!bloc) {
      bloc = document.createElement('section');
      bloc.id = 'ses-p-prefs';
      bloc.className = 'ses-bloc';
      bloc.style.marginTop = '20px';
      bloc.setAttribute('aria-labelledby', 'ses-p-prefs-titre');
      zone.appendChild(bloc);
    }
    function dessiner(liste) {
      bloc.innerHTML = '<h3 id="ses-p-prefs-titre" style="margin:0 0 6px;font-size:18px">' + e(t('p-pref-titre')) + '</h3><p class="ses-muet" style="margin:0 0 12px">' + e(t('p-pref-intro')) + '</p>' +
        '<div id="ses-p-prefs-msg" hidden></div><ul class="ses-liste-simple">' + liste.map(function (p) {
          var id = 'ses-pref-' + p.channel;
          return '<li><label for="' + id + '" style="display:flex;gap:10px;align-items:center"><input type="checkbox" id="' + id + '" data-canal="' + e(p.channel) + '"' +
            (p.enabled ? ' checked' : '') + (p.locked ? ' disabled' : '') + '> <span>' + e(t(CANAUX_TEXTE[p.channel] || 'p-pref-in_app')) + '</span>' +
            (p.locked ? ' <span class="ses-muet">' + e(t('p-pref-toujours')) + '</span>' : (p.available ? '' : ' <span class="ses-muet">' + e(t('p-pref-bientot')) + '</span>')) + '</label></li>';
        }).join('') + '</ul>';
      Array.prototype.forEach.call(bloc.querySelectorAll('input[data-canal]'), function (c) {
        c.addEventListener('change', function () {
          c.disabled = true;
          API.notifications.reglerPreference(c.getAttribute('data-canal'), c.checked).then(function (l) {
            dessiner(l);
            UI.annonce(bloc.querySelector('#ses-p-prefs-msg'), t('p-pref-enregistre'), 'succes');
          }, function (err) {
            c.disabled = false; c.checked = !c.checked;
            UI.annonce(bloc.querySelector('#ses-p-prefs-msg'), P.message(err), 'erreur');
          });
        });
      });
    }
    API.notifications.preferences().then(function (l) { if (l && l.length) dessiner(l); else bloc.hidden = true; }, function () { bloc.hidden = true; });
  }

  P.enregistrer({
    id: 'profil', ordre: 140, toujours: true,
    rendre: function (zone) {
      var compte = document.getElementById('ses-p-compte');
      if (!compte) return Promise.resolve();
      if (!zone.querySelector('.ses-ph')) zone.innerHTML = P.titre('p-nav-profil', 'p-profil-intro');
      compte.removeAttribute('role'); compte.removeAttribute('aria-labelledby'); compte.removeAttribute('tabindex');
      compte.hidden = false;
      compte.style.marginTop = '20px';
      if (compte.parentNode !== zone) zone.appendChild(compte);
      preferences(zone);
      return Promise.resolve();
    }
  });
})();
