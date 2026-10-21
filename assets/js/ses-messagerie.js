/* ==========================================================================
   Speed Express Shipping — la messagerie du tableau de bord (étape 032)
   --------------------------------------------------------------------------
   Une section du centre de commande, module « Messagerie » : à gauche les
   conversations (messages directs, groupes, clients), à droite le fil et la
   saisie (texte, colis cité, photo). Les MÊMES fonctions que les deux
   applications (SES_API.messagerie → public.lg_chat_*) : aucune règle ici.
   Qui lit, qui écrit, qui gère un groupe, combien de non-lus : la base.

   Le temps réel : la base glisse un signal SANS donnée dans
   public.ses_chat_signal ; on relit la boîte (et le fil ouvert), et la
   pastille de l'onglet. Rien ne se relit sous les doigts de quelqu'un qui
   écrit : la saisie n'est jamais redessinée.

   Les photos ne s'ouvrent que par une adresse signée de courte durée,
   demandée au moment de les montrer.
   ========================================================================== */
(function () {
  'use strict';

  var C = window.SES_CENTRE;
  var API = window.SES_API;
  var UI = window.SES_UI;
  if (!C || !API || !API.messagerie || !C.enregistrer) return;
  C.actions = C.actions || {};

  var t = function (k, v) { return C.t ? C.t(k, v) : k; };
  var e = function (x) { return C.e ? C.e(x) : String(x); };
  var date = function (v) { return C.date ? C.date(v) : (v || ''); };

  var boite = null;          // la dernière boîte lue (lg_chat_inbox)
  var fil = null;            // le fil ouvert (lg_chat_messages)
  var anciens = [];          // les messages plus anciens chargés à la demande, devant le fil
  var adresses = {};         // photo → { url, jusqua } : une adresse signée sert huit minutes
  var zoneCourante = null;
  var arreter = null;

  function moduleOuvert() { var m = C.modules ? C.modules() : null; return !m || m.indexOf('messagerie') >= 0; }
  function convCourante(st) { var c = st && st.filtres && st.filtres.c; return /^[0-9a-f-]{36}$/i.test(String(c || '')) ? String(c) : null; }

  /* --- La pastille de l'onglet : le nombre de messages non lus ----------- */
  function pastille(n) {
    var b = document.getElementById('ses-o-messagerie');
    if (!b) return;
    var p = b.querySelector('.cc-msg-pastille');
    if (!n) { if (p) p.remove(); b.removeAttribute('aria-description'); return; }
    if (!p) { p = document.createElement('span'); p.className = 'cc-msg-pastille'; p.setAttribute('aria-hidden', 'true'); b.appendChild(p); }
    p.textContent = n > 99 ? '99+' : String(n);
    b.setAttribute('aria-description', t('c-msg-non-lus', { n: n }));
  }
  function relirePastille() { API.messagerie.nonLus().then(function (r) { pastille(r && r.unread || 0); }, function () { /* sans réseau : la pastille attend */ }); }

  /* --- La liste des conversations ---------------------------------------- */
  function genre(x) {
    if (x.kind === 'CUSTOMER') return '<span class="cc-msg-genre cc-msg-genre-client">' + e(t('c-msg-genre-client')) + '</span>';
    if (x.kind === 'GROUP') return '<span class="cc-msg-genre">' + e(t('c-msg-genre-groupe')) + '</span>';
    return '';
  }
  function apercu(l) {
    if (!l) return t('c-msg-aucun-message');
    var qui = l.mine ? t('c-msg-vous') + ' : ' : (l.author ? l.author + ' : ' : '');
    var quoi = l.body || (l.photo ? t('c-msg-photo') : (l.parcel ? l.parcel : ''));
    return qui + quoi;
  }
  function dessinerListe(zone, courante) {
    var cible = zone.querySelector('#cc-msg-convs');
    if (!cible || !boite) return;
    cible.removeAttribute('aria-busy');
    var filtre = String((zone.querySelector('#cc-msg-filtre') || {}).value || '').trim().toLowerCase();
    var items = (boite.items || []).filter(function (x) {
      return !filtre || String(x.title || '').toLowerCase().indexOf(filtre) >= 0 || String(x.customer && x.customer.code || '').toLowerCase().indexOf(filtre) >= 0;
    });
    cible.innerHTML = items.length ? items.map(function (x) {
      var actif = x.conversation_id === courante;
      return '<li><button type="button" class="cc-msg-conv' + (actif ? ' cc-msg-conv-actif' : '') + (x.unread ? ' cc-msg-conv-nonlu' : '') + '" data-conv="' + e(x.conversation_id) + '"' +
        (actif ? ' aria-current="true"' : '') + '>' +
        '<span class="cc-msg-conv-haut"><strong>' + e(x.title || '—') + '</strong>' + (x.last ? '<span class="cc-petit">' + e(date(x.last.at)) + '</span>' : '') + '</span>' +
        '<span class="cc-msg-conv-bas">' + genre(x) + (x.archived ? '<span class="cc-msg-genre">' + e(t('c-msg-archive')) + '</span>' : '') +
        '<span class="cc-msg-apercu">' + e(apercu(x.last)) + '</span>' +
        (x.unread ? '<span class="cc-msg-nonlu" aria-label="' + e(t('c-msg-non-lus', { n: x.unread })) + '">' + e(String(x.unread)) + '</span>' : '') + '</span>' +
        '</button></li>';
    }).join('') : '<li class="cc-rien">' + e(t(filtre ? 'c-msg-aucune-trouvee' : 'c-msg-aucune-conv')) + '</li>';
  }

  /* --- Le fil d'une conversation ------------------------------------------ */
  function corps(texte) { return e(texte || '').replace(/\n/g, '<br>'); }
  function message(m) {
    var auteur = m.mine ? t('c-msg-vous') : (m.author && m.author.name) || '—';
    return '<li class="cc-msg-bulle' + (m.mine ? ' cc-msg-moi' : '') + (m.author && m.author.kind === 'CUSTOMER' ? ' cc-msg-du-client' : '') + '" data-id="' + e(String(m.id)) + '">' +
      '<span class="cc-msg-qui">' + e(auteur) + ' · <time datetime="' + e(m.at) + '">' + e(date(m.at)) + '</time></span>' +
      (m.body ? '<span class="cc-msg-texte">' + corps(m.body) + '</span>' : '') +
      (m.photo_path ? '<span class="cc-msg-photo"><img alt="' + e(t('c-msg-photo')) + '" data-photo="' + e(m.photo_path) + '" loading="lazy"></span>' : '') +
      (m.parcel ? '<button type="button" class="cc-msg-colis ses-mono" data-act="colis" data-numero="' + e(m.parcel.tracking_number) + '">' + e(m.parcel.tracking_number) + '</button>' : '') +
      '</li>';
  }
  function entete(c) {
    var sous = c.kind === 'CUSTOMER' && c.customer ? (c.customer.code || '') : (c.kind === 'GROUP' ? t('c-msg-membres', { n: (c.members || []).length }) : t('c-msg-direct'));
    return '<div class="cc-msg-fil-entete"><div><h3>' + e(c.title || '—') + '</h3><p class="cc-petit">' + e(sous) + (c.archived ? ' · ' + e(t('c-msg-archive')) : '') + '</p></div>' +
      (c.can_manage ? '<button type="button" class="ses-bouton ses-bouton-mini ses-bouton-second" data-act="msg-gerer">' + e(t('c-msg-gerer')) + '</button>' : '') + '</div>';
  }
  function saisie(c) {
    if (!c.can_send) return '<p class="cc-note">' + e(t('c-msg-archive-lecture')) + '</p>';
    return '<form id="cc-msg-saisie" class="cc-msg-saisie" novalidate>' +
      '<label class="sr-only" for="cc-msg-texte">' + e(t('c-msg-votre-message')) + '</label>' +
      '<textarea id="cc-msg-texte" name="texte" rows="2" maxlength="4000" placeholder="' + e(t('c-msg-ecrire')) + '"></textarea>' +
      '<div class="cc-msg-saisie-options">' +
        '<label class="cc-msg-option"><span>' + e(t('c-msg-citer-colis')) + '</span><input name="colis" maxlength="20" autocomplete="off" placeholder="SES-…" class="ses-mono"></label>' +
        '<label class="cc-msg-option"><span>' + e(t('c-msg-joindre-photo')) + '</span><input name="photo" type="file" accept="image/jpeg,image/png,image/webp"></label>' +
        '<button type="submit" class="ses-bouton ses-bouton-principal">' + e(t('c-msg-envoyer')) + '</button>' +
      '</div><div id="cc-msg-erreur" class="cc-form-msg" role="alert" hidden></div></form>';
  }
  function dessinerMessages(zone) {
    var ol = zone.querySelector('#cc-msg-messages');
    if (!ol || !fil) return;
    var tous = anciens.concat(fil.items || []);
    var basAvant = ol.scrollHeight - ol.scrollTop - ol.clientHeight < 40;
    ol.innerHTML = (fil.has_more || anciens.length && anciens.plus ? '<li class="cc-msg-plus"><button type="button" class="ses-bouton ses-bouton-mini ses-bouton-second" data-act="msg-anciens">' + e(t('c-msg-anciens')) + '</button></li>' : '') +
      (tous.length ? tous.map(message).join('') : '<li class="cc-rien">' + e(t('c-msg-premier')) + '</li>');
    montrerPhotos(ol);
    if (basAvant || !ol.getAttribute('data-vu')) { ol.scrollTop = ol.scrollHeight; ol.setAttribute('data-vu', '1'); }
  }
  function montrerPhotos(racine) {
    Array.prototype.forEach.call(racine.querySelectorAll('img[data-photo]'), function (img) {
      var chemin = img.getAttribute('data-photo'), connu = adresses[chemin];
      if (connu && connu.jusqua > Date.now()) { img.src = connu.url; return; }
      API.messagerie.adressePhoto(chemin).then(function (url) {
        if (!url) return;
        adresses[chemin] = { url: url, jusqua: Date.now() + 8 * 60 * 1000 };
        img.src = url;
      }, function () { img.alt = t('c-msg-photo-indisponible'); });
    });
  }
  function dessinerFil(zone) {
    var cible = zone.querySelector('#cc-msg-fil');
    if (!cible || !fil) return;
    cible.removeAttribute('aria-busy');
    cible.innerHTML = entete(fil.conversation) + '<ol id="cc-msg-messages" class="cc-msg-messages" aria-live="polite"></ol>' + saisie(fil.conversation);
    dessinerMessages(zone);
    brancherSaisie(zone);
  }
  // Ce qui est lu est marqué lu : jusqu'au dernier message affiché.
  function marquerLu() {
    if (!fil || !fil.unread || !(fil.items || []).length) return;
    var dernier = fil.items[fil.items.length - 1].id, conv = fil.conversation.conversation_id;
    API.messagerie.marquerLu(conv, dernier).then(function () {
      fil.unread = 0;
      (boite && boite.items || []).forEach(function (x) { if (x.conversation_id === conv) x.unread = 0; });
      if (zoneCourante) dessinerListe(zoneCourante, conv);
      relirePastille();
    }, function () { /* sera marqué au prochain passage */ });
  }

  function chargerFil(zone, conv, silencieux) {
    var cible = zone.querySelector('#cc-msg-fil');
    if (!cible) return Promise.resolve();
    if (!conv) { cible.innerHTML = '<p class="cc-msg-vide">' + e(t('c-msg-choisir')) + '</p>'; fil = null; return Promise.resolve(); }
    if (!silencieux) { anciens = []; C.etat(cible, 'chargement'); }
    return API.messagerie.messages(conv).then(function (d) {
      var meme = fil && fil.conversation.conversation_id === conv && zone.querySelector('#cc-msg-saisie, .cc-note');
      fil = d;
      if (silencieux && meme) dessinerMessages(zone); else dessinerFil(zone);
      marquerLu();
    }, function (err) { if (!silencieux) C.erreur(cible, err, function () { chargerFil(zone, conv); }); });
  }
  function chargerBoite(zone, st, silencieux) {
    var cible = zone.querySelector('#cc-msg-convs');
    if (!silencieux && cible) C.etat(cible, 'chargement');
    return API.messagerie.boite().then(function (d) {
      boite = d;
      var outils = zone.querySelector('#cc-msg-outils-actions');
      if (outils) outils.innerHTML = (d.can && d.can.direct ? '<button type="button" class="ses-bouton ses-bouton-mini ses-bouton-principal" data-act="msg-nouveau">' + e(t('c-msg-nouveau')) + '</button>' : '') +
        (d.can && d.can.groups ? '<button type="button" class="ses-bouton ses-bouton-mini ses-bouton-second" data-act="msg-groupe">' + e(t('c-msg-nouveau-groupe')) + '</button>' : '');
      dessinerListe(zone, convCourante(st));
      pastille(d.unread || 0);
    }, function (err) { if (!silencieux && cible) C.erreur(cible, err, function () { chargerBoite(zone, st); }); });
  }

  function rendre(zone, st) {
    zoneCourante = zone;
    zone.innerHTML = '<p class="cc-intro">' + e(t('c-msg-intro')) + '</p>' +
      '<div class="cc-msg">' +
        '<div class="cc-msg-liste"><div class="cc-msg-outils">' +
          '<label class="sr-only" for="cc-msg-filtre">' + e(t('c-msg-filtrer')) + '</label>' +
          '<input id="cc-msg-filtre" type="search" autocomplete="off" placeholder="' + e(t('c-msg-filtrer')) + '">' +
          '<div id="cc-msg-outils-actions" class="cc-msg-outils-actions"></div></div>' +
          '<ul id="cc-msg-convs" class="cc-msg-convs"></ul></div>' +
        '<section id="cc-msg-fil" class="cc-msg-fil" aria-label="' + e(t('c-msg-fil')) + '"></section>' +
      '</div>';
    zone.querySelector('#cc-msg-filtre').addEventListener('input', function () { dessinerListe(zone, convCourante(st)); });
    chargerBoite(zone, st);
    chargerFil(zone, convCourante(st));
  }
  function actualiser(zone, st, ctx, silencieux) {
    if (!zone.querySelector('#cc-msg-convs')) return rendre(zone, st);
    return Promise.all([chargerBoite(zone, st, silencieux), chargerFil(zone, convCourante(st), true)]);
  }

  /* --- Écrire --------------------------------------------------------------- */
  function brancherSaisie(zone) {
    var f = zone.querySelector('#cc-msg-saisie');
    if (!f) return;
    var msg = f.querySelector('#cc-msg-erreur');
    // Entrée envoie ; Maj + Entrée passe à la ligne.
    f.elements.texte.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) { ev.preventDefault(); if (f.requestSubmit) f.requestSubmit(); else f.dispatchEvent(new Event('submit', { cancelable: true })); }
    });
    f.addEventListener('submit', function (ev) {
      ev.preventDefault();
      if (!fil) return;
      var texte = String(f.elements.texte.value || '').trim(), colis = String(f.elements.colis.value || '').trim(), photo = f.elements.photo.files && f.elements.photo.files[0];
      if (!texte && !photo) { msg.hidden = false; msg.textContent = t('c-msg-vide'); return; }
      msg.hidden = true;
      // La même clé tant que ce message n'est pas parti : un nouvel essai ne fait jamais deux messages.
      if (!f.getAttribute('data-cle')) f.setAttribute('data-cle', API.cleMessage());
      var cle = f.getAttribute('data-cle'), conv = fil.conversation.conversation_id;
      var fin = UI.occuper(f.querySelector('button[type=submit]'), t('c-envoi'));
      (photo ? API.messagerie.deposerPhoto(conv, photo, cle) : Promise.resolve(null)).then(function (chemin) {
        return API.messagerie.envoyer(conv, texte, cle, colis, chemin);
      }).then(function () {
        fin();
        f.reset();
        f.removeAttribute('data-cle');
        f.elements.texte.focus();
        return chargerFil(zone, conv, true);
      }, function (err) { fin(); msg.hidden = false; msg.textContent = C.message(err); });
    });
  }

  /* --- Ouvrir une conversation, en commencer une --------------------------- */
  function ouvrir(conv) { if (C.fermerDialogue) C.fermerDialogue(); C.aller('messagerie', { c: conv }); }
  function ligneMembre(x, coche) {
    return '<li><label class="cc-msg-membre"><input type="checkbox" name="membre" value="' + e(x.user_id) + '"' + (coche ? ' checked' : '') + '> <span>' + e(x.name) +
      '</span> <span class="cc-petit">' + e([x.staff_code, x.branch, x.driver ? t('c-msg-chauffeur') : ''].filter(Boolean).join(' · ')) + '</span></label></li>';
  }
  C.actions['msg-nouveau'] = function () {
    var z = C.dialogue('c-msg-nouveau', '<div class="cc-form-grille"><label class="ses-champ"><span>' + e(t('c-msg-chercher')) + '</span><input id="cc-msg-qui" type="search" autocomplete="off"></label></div>' +
      '<div id="cc-msg-annuaire" aria-live="polite"></div>', 'etroit');
    if (!z) return;
    var cible = z.querySelector('#cc-msg-annuaire'), champ = z.querySelector('#cc-msg-qui'), attente = null;
    function lire() {
      var q = champ.value;
      C.charger(cible, function () { return API.messagerie.annuaire(q); }, function (d) {
        var clients = d.customers || [], equipe = d.staff || [];
        cible.innerHTML = '<h3 class="cc-sous-titre">' + e(t('c-msg-equipe')) + '</h3>' + (equipe.length ? '<ul class="cc-msg-annuaire">' + equipe.map(function (x) {
          return '<li><button type="button" class="cc-lien-bouton" data-act="msg-direct" data-membre="' + e(x.user_id) + '">' + e(x.name) + '</button> <span class="cc-petit">' +
            e([x.staff_code, x.branch, x.driver ? t('c-msg-chauffeur') : ''].filter(Boolean).join(' · ')) + '</span></li>';
        }).join('') + '</ul>' : '<p class="cc-rien">' + e(t('c-msg-personne')) + '</p>') +
          (boite && boite.can && boite.can.customers ? '<h3 class="cc-sous-titre">' + e(t('c-msg-clients')) + '</h3>' + (clients.length ? '<ul class="cc-msg-annuaire">' + clients.map(function (x) {
            return '<li><button type="button" class="cc-lien-bouton" data-act="msg-client" data-client="' + e(x.customer_id) + '">' + e(x.name) + '</button> <span class="cc-petit">' +
              e([x.code, x.city].filter(Boolean).join(' · ')) + '</span></li>';
          }).join('') + '</ul>' : '<p class="cc-rien">' + e(t(String(q || '').trim().length < 2 ? 'c-msg-clients-aide' : 'c-msg-personne')) + '</p>') : '');
      });
    }
    champ.addEventListener('input', function () { clearTimeout(attente); attente = setTimeout(lire, 300); });
    lire();
    champ.focus();
  };
  C.actions['msg-direct'] = function (b) {
    API.messagerie.ouvrirDirect(b.getAttribute('data-membre')).then(function (r) { ouvrir(r.conversation_id); }, function (err) { C.annoncer(C.message(err), 'erreur'); });
  };
  C.actions['msg-client'] = function (b) {
    API.messagerie.ouvrirClient(b.getAttribute('data-client')).then(function (r) { ouvrir(r.conversation_id); }, function (err) { C.annoncer(C.message(err), 'erreur'); });
  };
  function formGroupe(titre, coches) {
    return '<form id="cc-msg-form-groupe" novalidate><div class="cc-form-grille"><label class="ses-champ"><span>' + e(t('c-msg-nom-groupe')) + '</span>' +
      '<input name="titre" maxlength="80" required value="' + e(titre || '') + '"></label></div>' +
      '<h3 class="cc-sous-titre">' + e(t('c-msg-membres-titre')) + '</h3><ul id="cc-msg-choix" class="cc-msg-annuaire"><li class="cc-rien">' + e(t('c-chargement')) + '</li></ul>' +
      (coches ? '<label class="cc-msg-membre"><input type="checkbox" name="archive"' + (fil && fil.conversation.archived ? ' checked' : '') + '> <span>' + e(t('c-msg-archiver')) + '</span></label>' : '') +
      '<div id="cc-form-msg" role="alert" class="cc-form-msg" hidden></div>' +
      '<div class="cc-form-actions"><button type="button" class="ses-bouton ses-bouton-second" data-fermer>' + e(t('c-gst-annuler')) + '</button>' +
      '<button type="submit" class="ses-bouton ses-bouton-principal">' + e(t(coches ? 'c-msg-enregistrer' : 'c-msg-creer')) + '</button></div></form>';
  }
  function dialogueGroupe(titreCle, titre, membres, envoyer) {
    var z = C.dialogue(titreCle, formGroupe(titre, membres), 'etroit');
    var f = z && z.querySelector('#cc-msg-form-groupe');
    if (!f) return;
    var ids = (membres || []).map(function (m) { return m.user_id; }), moi = boite && boite.me && boite.me.user_id;
    f.querySelector('[data-fermer]').addEventListener('click', function () { C.fermerDialogue(); });
    API.messagerie.annuaire().then(function (d) {
      var liste = (d.staff || []).slice();
      // Les membres actuels d'abord ; soi-même n'est pas dans l'annuaire (on reste dans le groupe qu'on gère).
      (membres || []).forEach(function (m) { if (m.user_id !== moi && !liste.some(function (x) { return x.user_id === m.user_id; })) liste.unshift(m); });
      f.querySelector('#cc-msg-choix').innerHTML = liste.length ? liste.map(function (x) { return ligneMembre(x, ids.indexOf(x.user_id) >= 0); }).join('') : '<li class="cc-rien">' + e(t('c-msg-personne')) + '</li>';
    }, function (err) { f.querySelector('#cc-msg-choix').innerHTML = '<li class="cc-rien">' + e(C.message(err)) + '</li>'; });
    f.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var msg = f.querySelector('#cc-form-msg');
      var choisis = Array.prototype.filter.call(f.querySelectorAll('input[name=membre]'), function (x) { return x.checked; }).map(function (x) { return x.value; });
      if (String(f.elements.titre.value || '').trim().length < 2) { msg.hidden = false; msg.textContent = t('c-msg-nom-obligatoire'); return; }
      var fin = UI.occuper(f.querySelector('button[type=submit]'), t('c-envoi'));
      envoyer(String(f.elements.titre.value).trim(), choisis, ids, f.elements.archive ? f.elements.archive.checked : null).then(function (r) {
        fin(); C.fermerDialogue(); C.annoncer(t('c-msg-groupe-ok'), 'succes'); ouvrir(r.conversation_id);
      }, function (err) { fin(); msg.hidden = false; msg.textContent = C.message(err); });
    });
  }
  C.actions['msg-groupe'] = function () {
    dialogueGroupe('c-msg-nouveau-groupe', '', null, function (titre, choisis) { return API.messagerie.creerGroupe(titre, choisis); });
  };
  C.actions['msg-gerer'] = function () {
    if (!fil) return;
    var c = fil.conversation;
    dialogueGroupe('c-msg-gerer', c.title, c.members || [], function (titre, choisis, avant, archive) {
      var moi = boite && boite.me && boite.me.user_id;
      return API.messagerie.modifierGroupe(c.conversation_id, {
        titre: titre !== c.title ? titre : null,
        ajouter: choisis.filter(function (x) { return avant.indexOf(x) < 0; }),
        retirer: avant.filter(function (x) { return x !== moi && choisis.indexOf(x) < 0; }),
        archive: archive === c.archived ? null : archive
      });
    });
  };
  C.actions['msg-anciens'] = function () {
    if (!fil || !zoneCourante) return;
    var premier = (anciens[0] || (fil.items || [])[0] || {}).id;
    if (!premier) return;
    API.messagerie.messages(fil.conversation.conversation_id, premier).then(function (d) {
      anciens = (d.items || []).concat(anciens);
      anciens.plus = d.has_more;
      fil.has_more = false;
      var ol = zoneCourante.querySelector('#cc-msg-messages'), hauteur = ol ? ol.scrollHeight : 0;
      dessinerMessages(zoneCourante);
      if (ol) ol.scrollTop = ol.scrollHeight - hauteur;
    }, function (err) { C.annoncer(C.message(err), 'erreur'); });
  };

  function clic(ev, st) {
    var b = ev.target.closest && ev.target.closest('.cc-msg-conv');
    if (b) { ev.preventDefault(); C.aller('messagerie', { c: b.getAttribute('data-conv') }); }
  }

  C.enregistrer({
    id: 'messagerie', ordre: 125, filtres: [],
    ouvrir: function () { return moduleOuvert(); },
    rendre: rendre, actualiser: actualiser, clic: clic,
    quitter: function () { zoneCourante = null; fil = null; anciens = []; }
  });

  /* Le temps réel et la pastille : dès que le module existe pour ce compte, même quand la section n'est pas ouverte. */
  document.addEventListener('ses-modules-prets', function () {
    if (arreter || !moduleOuvert() || !document.getElementById('ses-o-messagerie') || document.getElementById('ses-o-messagerie').hidden) return;
    relirePastille();
    var attente = null;
    arreter = API.messagerie.surveiller(function () {
      clearTimeout(attente);
      attente = setTimeout(function () {
        if (zoneCourante && document.body.contains(zoneCourante)) {
          var st = { filtres: { c: fil && fil.conversation && fil.conversation.conversation_id } };
          chargerBoite(zoneCourante, st, true);
          if (st.filtres.c) chargerFil(zoneCourante, st.filtres.c, true);
        } else relirePastille();
      }, 400);
    });
  });
  UI.surLangue(function () { if (zoneCourante && document.body.contains(zoneCourante) && boite) { dessinerListe(zoneCourante, fil && fil.conversation.conversation_id); if (fil) dessinerMessages(zoneCourante); } });

  C.messagerieVues = { dessinerListe: dessinerListe, dessinerFil: dessinerFil, message: message, apercu: apercu,
                       poser: function (b, f) { boite = b; fil = f; anciens = []; } };
})();
