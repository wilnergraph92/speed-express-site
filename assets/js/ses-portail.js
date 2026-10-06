/* ==========================================================================
   Speed Express Shipping — le portail client : le socle
   --------------------------------------------------------------------------
   Quatorze sections (tableau de bord, colis, expéditions, suivi,
   consolidations, factures, paiements, documents, adresses, enlèvement,
   livraison, notifications, support, profil), chacune dans son fichier, qui
   s'inscrivent ici : SES_PORTAIL.enregistrer({ id, ordre, rendre }).

   Ce fichier fournit ce qu'elles partagent : la navigation (une adresse par
   section, donc le bouton « précédent » du navigateur fonctionne), les trois
   états d'un écran — chargement, vide, erreur — avec leur bouton
   « Réessayer », la frise d'étapes, le suivi daté, les pastilles, les
   champs de formulaire.

   Règle d'or : AUCUNE règle métier ici. Les statuts, les étapes, les soldes,
   les droits viennent de la base (voir outils/logistique/008-portail-client.sql),
   par SES_API.portail. Le portail ne fait que les montrer : un client qui
   modifierait cette page ne gagnerait aucun pouvoir, le serveur refuserait.

   Le portail ne s'ouvre que si ses-espace.js l'y invite (interrupteur
   « portailNoyau » de config.js allumé, base à jour). Sinon l'espace client
   d'avant continue de fonctionner, sans que ce fichier ne fasse rien.
   ========================================================================== */
(function () {
  'use strict';

  var API = window.SES_API;
  var UI = window.SES_UI;
  if (!API || !UI || !API.portail) return;

  var t = UI.t;
  var e = UI.echapper;
  var P = window.SES_PORTAIL = window.SES_PORTAIL || {};
  P.sections = P.sections || [];
  P.t = t;
  P.e = e;

  var moi = null;
  var ctx = null;
  var courante = null;      // { id, cle } : la section affichée et ses paramètres
  var rendus = {};          // id → clé des paramètres déjà dessinés
  var actif = false;
  var automatique = false;  // vrai pendant que route() active un onglet lui-même (et non à la demande de l'utilisateur)

  function $(s, racine) { return (racine || document).querySelector(s); }

  /* --- Inscription des sections ------------------------------------------ */
  P.enregistrer = function (def) {
    P.sections = P.sections.filter(function (s) { return s.id !== def.id; });
    P.sections.push(def);
    P.sections.sort(function (a, b) { return a.ordre - b.ordre; });
  };

  /* --- Les trois états d'un écran ---------------------------------------- */
  P.etat = function (zone, genre, texte) {
    if (genre === 'chargement') {
      zone.setAttribute('aria-busy', 'true');
      zone.innerHTML = '<div class="ses-etat" role="status"><span class="ses-spin" aria-hidden="true"></span>' +
        '<span>' + e(texte || t('p-chargement')) + '</span></div>';
      return;
    }
    zone.removeAttribute('aria-busy');
    if (genre === 'vide') {
      zone.innerHTML = '<div class="ses-bloc">' + UI.vide(texte, '▢') + '</div>';
    }
  };

  /* Un message d'erreur dans la langue du client. Les messages de la base sont
     en français : on ne les montre qu'à un lecteur français, et seulement quand
     ils disent ce qui ne va pas (« la date doit être comprise entre… »). */
  P.message = function (err) {
    var code = err && err.code ? err.code : 'inconnu';
    var base = UI.messageErreur(err);
    var fr = (document.documentElement.lang || 'fr').slice(0, 2) === 'fr';
    if (fr && (code === 'donnee-invalide' || code === 'etat-incompatible') && err.message && err.message !== code) return base + ' ' + err.message;
    return base;
  };

  P.erreur = function (zone, err, reessayer) {
    zone.removeAttribute('aria-busy');
    zone.innerHTML = '<div class="ses-etat ses-etat-erreur" role="alert"><p>' + e(P.message(err)) + '</p>' +
      (reessayer ? '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-reessayer>' + e(t('p-reessayer')) + '</button>' : '') + '</div>';
    var b = $('[data-reessayer]', zone);
    if (b && reessayer) b.addEventListener('click', reessayer);
  };

  /* Charge, affiche, et sait se redessiner quand la langue change. Une réponse
     tardive d'un chargement abandonné est ignorée. */
  var numero = 0;
  P.charger = function (zone, appel, dessiner, options) {
    var mien = ++numero;
    zone._v = mien;
    if (!options || !options.silencieux) P.etat(zone, 'chargement');
    return appel().then(function (donnees) {
      if (zone._v !== mien) return;
      zone.removeAttribute('aria-busy');
      zone._rendu = function () { dessiner(donnees); };
      dessiner(donnees);
    }, function (err) {
      if (zone._v !== mien) return;
      zone._rendu = null;
      P.erreur(zone, err, function () { P.charger(zone, appel, dessiner); });
    });
  };

  /* --- Petits outils d'affichage ------------------------------------------ */
  var GENRES = {
    registered: 'info', received: 'info', in_transit: 'info', customs: 'warn', at_hub: 'ok', out_for_delivery: 'ok', delivered: 'ok', on_hold: 'warn',
    incident: 'bad', lost: 'bad', cancelled: 'neutre', returned: 'neutre', preparing: 'info', closed: 'neutre',
    requested: 'info', scheduled: 'ok', on_the_way: 'ok', completed: 'ok', missed: 'bad', rejected: 'bad'
  };
  P.pastille = function (cle, genre) {
    return '<span class="ses-pastille ses-pastille-' + (genre || 'neutre') + '">' + e(t(cle) || cle) + '</span>';
  };
  /* L'étape d'un colis, d'une expédition ou d'une demande. Le texte dit toujours l'étape : la couleur ne la porte jamais seule. */
  P.pastilleEtape = function (etape, famille) {
    return P.pastille((famille || 'stage') + '-' + etape, GENRES[etape]);
  };

  P.pays = function (code) { return code ? (UI.nomPays(code) || code) : ''; };
  P.nombre = UI.nombre;
  P.date = UI.date;
  P.montant = UI.montant;

  /* Les sept étapes du parcours d'un colis, dans l'ordre. L'étape elle-même
     vient de la base ; seul l'ordre d'affichage est ici. */
  var PARCOURS = ['registered', 'received', 'in_transit', 'customs', 'at_hub', 'out_for_delivery', 'delivered'];
  P.PARCOURS = PARCOURS;
  P.frise = function (etape) {
    var rang = PARCOURS.indexOf(etape);
    if (rang < 0) {
      // Un arrêt (en attente, incident, perdu, annulé, retourné) : pas de progression à montrer, un message clair.
      return '<p class="ses-arret ses-arret-' + (GENRES[etape] || 'neutre') + '" role="status">' + e(t('p-arret-' + etape)) + '</p>';
    }
    return '<ol class="ses-etapes ses-etapes7" aria-label="' + e(t('p-frise')) + '">' + PARCOURS.map(function (s, i) {
      var cls = i <= rang ? 'ses-faite' : '';
      return '<li class="' + cls + '"' + (i === rang ? ' aria-current="step"' : '') + '>' + e(t('stage-' + s)) +
        (i === rang ? '<span class="sr-only"> — ' + e(t('p-etape-actuelle')) + '</span>' : '') + '</li>';
    }).join('') + '</ol>';
  };

  /* Le suivi daté d'un colis : le vrai journal du noyau, le plus récent en haut. */
  P.suivi = function (evenements) {
    if (!evenements || !evenements.length) return '<p style="margin:0;color:var(--muted-2)">' + e(t('p-suivi-vide')) + '</p>';
    var liste = evenements.slice().reverse();
    return '<ol class="ses-suivi" aria-label="' + e(t('p-suivi-titre')) + '">' + liste.map(function (ev, i) {
      var etape = ev.stage || '';
      var titre = ev.event === 'ParcelStatusChanged' ? t('stage-' + etape) : (t('evt-' + ev.event) || t('stage-' + etape) || ev.event);
      return '<li class="ses-suivi-ligne' + (i === 0 ? ' ses-suivi-dernier' : '') + '">' +
        '<span class="ses-suivi-point ses-suivi-' + (GENRES[etape] || 'neutre') + '" aria-hidden="true"></span>' +
        '<p class="ses-suivi-titre">' + e(titre) + (i === 0 ? ' <span class="ses-suivi-etiquette">' + e(t('p-dernier-etat')) + '</span>' : '') + '</p>' +
        '<p class="ses-suivi-meta"><time datetime="' + e(ev.at) + '">' + e(UI.date(ev.at, true)) + '</time>' + (ev.place ? ' · ' + e(ev.place) : '') + '</p>' +
        (ev.note ? '<p class="ses-suivi-note">' + e(ev.note) + '</p>' : '') + '</li>';
    }).join('') + '</ol>';
  };

  P.detail = function (libelle, valeur) {
    if (valeur === null || valeur === undefined || valeur === '') return '';
    return '<div><dt>' + e(libelle) + '</dt><dd>' + e(valeur) + '</dd></div>';
  };

  P.titre = function (cle, sous) {
    return '<header class="ses-ph"><h2 tabindex="-1">' + e(t(cle)) + '</h2>' + (sous ? '<p>' + e(t(sous)) + '</p>' : '') + '</header>';
  };

  /* Un champ de formulaire accessible : libellé relié, aide et erreur reliées. */
  P.champ = function (o) {
    var id = o.id, aide = o.aide ? '<small id="' + id + '-aide" class="ses-aide">' + e(o.aide) + '</small>' : '';
    var attrs = ' id="' + id + '" name="' + e(o.nom) + '"' + (o.requis ? ' required aria-required="true"' : '') + (o.max ? ' maxlength="' + o.max + '"' : '') +
      (o.aide ? ' aria-describedby="' + id + '-aide"' : '') + (o.auto ? ' autocomplete="' + o.auto + '"' : '') + (o.placeholder ? ' placeholder="' + e(o.placeholder) + '"' : '');
    var corps;
    if (o.type === 'select') {
      corps = '<select' + attrs + '>' + o.options.map(function (op) {
        return '<option value="' + e(op[0]) + '"' + (String(op[0]) === String(o.valeur) ? ' selected' : '') + '>' + e(op[1]) + '</option>';
      }).join('') + '</select>';
    } else if (o.type === 'textarea') {
      corps = '<textarea' + attrs + ' rows="' + (o.lignes || 4) + '">' + e(o.valeur || '') + '</textarea>';
    } else {
      corps = '<input type="' + (o.type || 'text') + '"' + attrs + (o.min !== undefined ? ' min="' + o.min + '"' : '') + (o.maxNombre !== undefined ? ' max="' + o.maxNombre + '"' : '') +
        ' value="' + e(o.valeur === undefined || o.valeur === null ? '' : o.valeur) + '">';
    }
    return '<label class="ses-champ" for="' + id + '"><span>' + e(t(o.libelle)) + (o.requis ? '<i aria-hidden="true">*</i>' : '') + '</span>' + corps + aide + '</label>';
  };

  P.options = function (valeurs, cle) {
    return valeurs.map(function (v) { return [v, t(cle + v)]; });
  };

  /* Les dates des formulaires sont envoyées telles quelles ; la base garde le dernier mot (aujourd'hui à +60 jours). */
  P.jour = function (decalage) {
    var d = new Date(Date.now() + (decalage || 0) * 86400000);
    return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2);
  };

  /* Un envoi de formulaire : la même clé est rejouée si le réseau a échoué, jamais pour un envoi différent. */
  P.cleEnvoi = function (form) {
    if (!form._cle) form._cle = API.cleEnvoi();
    return form._cle;
  };
  P.nouvelleCle = function (form) { form._cle = null; };

  /* Une action du client : bouton occupé, message de réussite ou d'erreur, puis ce qui suit. */
  P.agir = function (bouton, zoneMessage, appel, succes, apres) {
    var rendre = UI.occuper(bouton, t('p-attente'));
    return appel().then(function (r) {
      rendre();
      if (succes) UI.annonce(zoneMessage, t(succes), 'succes');
      if (apres) apres(r);
      return r;
    }, function (err) {
      rendre();
      UI.annonce(zoneMessage, P.message(err), 'erreur');
    });
  };

  /* Un ancrage vers une autre section, sans recharger la page. */
  P.lien = function (section, param) {
    return '#/' + section + (param ? '/' + encodeURIComponent(param) : '');
  };
  P.aller = function (section, param) {
    var cible = P.lien(section, param);
    if (location.hash === cible) route();
    else location.hash = cible;
  };

  P.confirmer = function (cle, valeurs) {
    return window.confirm(t(cle, valeurs));
  };

  /* Ce que les sections peuvent demander au portail. */
  P.profil = function () { return moi; };
  P.tableau = function () { return ctx ? ctx.tableau : null; };
  P.recharger = function () {
    return API.portail.tableau().then(function (tb) { ctx.tableau = tb; badges(); return tb; }, function () { return null; });
  };

  /* --- La navigation ------------------------------------------------------ */
  function analyser() {
    var h = String(location.hash || '').replace(/^#\/?/, '');
    var morceaux = h.split('/');
    var id = morceaux[0] || 'tableau';
    var param = morceaux.length > 1 ? decodeURIComponent(morceaux.slice(1).join('/')) : '';
    return { id: id, param: param };
  }

  function section(id) {
    return P.sections.filter(function (s) { return s.id === id; })[0] || null;
  }

  function libelles() {
    P.sections.forEach(function (s) {
      var b = document.getElementById('ses-t-' + s.id);
      if (b) $('.ses-pnav-txt', b).textContent = t('p-nav-' + s.id);
    });
    var nav = $('.ses-portail-nav');
    if (nav) nav.setAttribute('aria-label', t('p-nav-titre'));
    badges();
  }

  function badges() {
    if (!ctx || !ctx.tableau) return;
    var n = ctx.tableau;
    pose('notifications', n.notifications ? n.notifications.unread : 0, 'p-nav-non-lues');
    pose('support', n.tickets ? n.tickets.open : 0, 'p-nav-ouverts');
  }
  function pose(id, n, cle) {
    var b = document.getElementById('ses-t-' + id);
    if (!b) return;
    var pastille = $('.ses-pnav-n', b);
    pastille.hidden = !n;
    pastille.textContent = n ? String(n) : '';
    if (n) b.setAttribute('aria-label', t('p-nav-' + id) + ' — ' + t(cle, { nombre: n })); else b.removeAttribute('aria-label');
  }

  function route() {
    if (!actif) return;
    var r = analyser();
    var s = section(r.id);
    if (!s) { location.replace('#/tableau'); return; }
    var bouton = document.getElementById('ses-t-' + s.id);
    // L'adresse a changé (précédent, lien, saisie) : on active l'onglet SANS toucher à l'adresse, paramètre compris.
    if (bouton && bouton.getAttribute('aria-selected') !== 'true') {
      automatique = true;
      try { bouton.click(); } finally { automatique = false; }
    }
    // Sur téléphone la barre d'onglets défile : l'onglet ouvert doit rester visible.
    var barre = bouton && bouton.parentNode;
    if (barre && barre.scrollWidth > barre.clientWidth) barre.scrollLeft = Math.max(0, bouton.offsetLeft - (barre.clientWidth - bouton.offsetWidth) / 2);
    var zone = document.getElementById('ses-s-' + s.id);
    var cle = s.id + '|' + r.param;
    var nouveau = !courante || courante.id !== s.id;
    courante = { id: s.id, cle: cle };
    if (rendus[s.id] === cle && !s.toujours) return;
    rendus[s.id] = cle;
    var p = s.rendre(zone, r.param, ctx);
    if (p && p.then) p.then(function () { if (nouveau || r.param) focaliser(zone); });
    else if (nouveau || r.param) focaliser(zone);
  }

  /* Après un changement de section, le titre reçoit le focus : un lecteur d'écran annonce où l'on est arrivé. */
  var premierAffichage = true;
  function focaliser(zone) {
    if (premierAffichage) { premierAffichage = false; return; }
    var h = $('h2', zone);
    if (h) h.focus({ preventScroll: false });
  }

  P.dessiner = function (id) { delete rendus[id]; route(); };

  function construire() {
    var racine = document.getElementById('ses-portail');
    var nav = $('.ses-portail-nav', racine);
    var panneaux = $('.ses-portail-panneaux', racine);
    P.sections.forEach(function (s) {
      nav.insertAdjacentHTML('beforeend', '<button type="button" role="tab" id="ses-t-' + s.id + '" aria-controls="ses-s-' + s.id + '" aria-selected="false" tabindex="-1" ' +
        'class="ses-onglet ses-pnav" data-section="' + s.id + '"><span class="ses-pnav-txt"></span><span class="ses-pnav-n" hidden></span></button>');
      if (!document.getElementById('ses-s-' + s.id)) {
        panneaux.insertAdjacentHTML('beforeend', '<section role="tabpanel" id="ses-s-' + s.id + '" aria-labelledby="ses-t-' + s.id + '" hidden tabindex="-1" class="ses-portail-panneau" data-section="' + s.id + '"></section>');
      }
    });
    libelles();
    window.SES_A11Y.onglets(nav, {
      apresActivation: function (b) {
        if (automatique) return;
        // Un clic de l'utilisateur sur un onglet va toujours à la LISTE de la section (même depuis une fiche).
        var cible = '#/' + b.getAttribute('data-section');
        if (location.hash === cible) route();
        else location.hash = cible;
      }
    });
    window.addEventListener('hashchange', route);
    // Revenir sur l'onglet du navigateur après un moment : le tableau de bord se remet à jour.
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible' && actif) P.recharger();
    });
    UI.surLangue(function () {
      libelles();
      var zone = courante && document.getElementById('ses-s-' + courante.id);
      if (zone && zone._rendu) zone._rendu();
      else if (courante) P.dessiner(courante.id);
    });
  }

  /* --- Mise en route : appelée par ses-espace.js -------------------------- */
  P.demarrer = function (contexte) {
    moi = contexte.moi;
    ctx = { tableau: contexte.tableau, moi: moi };
    actif = true;
    P.actif = true;
    document.body.classList.add('ses-mode-noyau');
    document.getElementById('ses-portail').hidden = false;
    construire();
    if (!location.hash) location.replace('#/tableau');
    route();
    // Le temps réel (phase 13) : la base signale « vos colis ou vos factures ont changé » ; on relit les compteurs, et on redessine les
    // écrans qui ne sont que de la lecture (jamais un formulaire en cours de saisie). Plusieurs signaux rapprochés : une seule relecture.
    if (API.notifications && API.notifications.surveiller) {
      var enAttente = null;
      API.notifications.surveiller('customer', function () {
        clearTimeout(enAttente);
        enAttente = setTimeout(function () {
          if (!actif || document.visibilityState !== 'visible') return;
          P.recharger();
          if (courante && ['tableau', 'colis', 'expeditions', 'consolidations', 'factures', 'paiements', 'documents', 'notifications'].indexOf(courante.id) >= 0) P.dessiner(courante.id);
        }, 1500);
      });
    }
  };
})();
