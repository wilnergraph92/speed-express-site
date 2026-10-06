/* ==========================================================================
   Speed Express Shipping — le centre de commande de l'équipe : le socle
   --------------------------------------------------------------------------
   Un onglet du tableau de bord, « Centre de commande », qui s'ouvre sur les
   chiffres du jour et sur ce qui attend l'équipe, puis donne accès à dix-neuf
   sections (colis, expéditions, entrepôt, consolidations, transport,
   chauffeurs, enlèvements, livraisons, douane, incidents, notifications,
   clients, support, facturation, paiements, utilisateurs, journal d'audit,
   réglages, rapports), chacune dans ses filtres.

   Règle d'or : AUCUNE statistique n'est calculée ici. Chaque chiffre, chaque
   total, chaque retard vient d'une fonction de la base (public.lg_cc_*, voir
   outils/logistique/009-centre-de-commande.sql) par SES_API.centre. Ce fichier
   dessine ; la base compte, filtre, trie et contrôle les droits. Quelqu'un qui
   modifierait cette page ne gagnerait aucun pouvoir : le serveur refuserait.

   Ce fichier fournit ce que les sections partagent : l'adresse de chaque
   section (#centre/colis?statut=ON_HOLD, donc le bouton « précédent » marche et
   un chiffre peut renvoyer vers sa liste), les filtres, la pagination, les
   trois états d'un écran — chargement, vide, erreur — avec leur bouton
   « Réessayer », les pastilles, l'actualisation. Les sections elles-mêmes sont
   dans ses-centre-vues.js et s'inscrivent ici : SES_CENTRE.enregistrer({...}).

   Le centre ne s'ouvre que si l'interrupteur « centreNoyau » de config.js est
   allumé ET que la base répond ET que le compte a un droit de lecture. Sinon
   l'onglet reste caché et le tableau de bord d'avant continue seul.
   ========================================================================== */
(function () {
  'use strict';

  var API = window.SES_API;
  var UI = window.SES_UI;
  if (!API || !UI || !API.centre || !document.getElementById('ses-p-centre')) return;

  var t = UI.t;
  var e = UI.echapper;
  var C = window.SES_CENTRE = window.SES_CENTRE || {};
  C.vues = C.vues || [];
  C.t = t;
  C.e = e;

  var PAR_PAGE = 25;
  var ACTUALISATION_MS = 60000;
  var acces = null;           // ce que la base répond à lg_cc_access : sections, rôle, drapeaux
  var courante = null;        // { id, filtres, page } : la section affichée
  var etats = {};             // id → { filtres, page } : on retrouve ses filtres en revenant sur une section
  var actif = false;
  var entrepots = null;       // les entrepôts, pour le filtre (chargés une fois, seulement si le droit y est)
  var minuteur = null;
  var numeroChargement = 0;
  // L'adresse demandée à l'ouverture : le tableau de bord la remplace par « #dashboard » tant que l'onglet est caché (il l'est jusqu'à la réponse de la base).
  var adresseInitiale = window.SES_ADRESSE_INITIALE !== undefined ? window.SES_ADRESSE_INITIALE : String(location.hash || '');

  function $(s, racine) { return (racine || document).querySelector(s); }
  function $$(s, racine) { return Array.prototype.slice.call((racine || document).querySelectorAll(s)); }

  /* --- Inscription des sections ------------------------------------------ */
  C.enregistrer = function (def) {
    C.vues = C.vues.filter(function (v) { return v.id !== def.id; });
    C.vues.push(def);
    C.vues.sort(function (a, b) { return a.ordre - b.ordre; });
  };
  function vueDe(id) { return C.vues.filter(function (v) { return v.id === id; })[0]; }

  /* Les sections que ce compte peut ouvrir : celles que la base annonce, et que ce site sait dessiner. « Rapports » renvoie vers la vue d'ensemble.
     Une section peut aussi s'ouvrir sur un droit que la base annonce déjà (def.ouvrir(acces), ex. le poste de scan sur « ops ») : la base
     contrôle ensuite chacun de ses appels. */
  function sectionsOuvertes() {
    if (!acces) return [];
    var ids = (acces.sections || []).slice();
    ids.push('rapports');
    return C.vues.filter(function (v) { return ids.indexOf(v.id) >= 0 || (typeof v.ouvrir === 'function' && v.ouvrir(acces) === true); });
  }
  C.peutOuvrir = function (id) { return sectionsOuvertes().some(function (v) { return v.id === id; }); };
  C.acces = function () { return acces; };

  /* --- Les trois états d'un écran ---------------------------------------- */
  C.etat = function (zone, genre, texte) {
    if (genre === 'chargement') {
      zone.setAttribute('aria-busy', 'true');
      zone.innerHTML = '<div class="ses-etat" role="status"><span class="ses-spin" aria-hidden="true"></span><span>' + e(texte || t('c-chargement')) + '</span></div>';
      return;
    }
    zone.removeAttribute('aria-busy');
    if (genre === 'vide') zone.innerHTML = '<div class="ses-bloc">' + UI.vide(texte, '▢') + '</div>';
  };

  C.message = function (err) {
    var code = err && err.code ? err.code : 'inconnu';
    var base = UI.messageErreur(err);
    var fr = (document.documentElement.lang || 'fr').slice(0, 2) === 'fr';
    if (fr && (code === 'donnee-invalide' || code === 'etat-incompatible') && err.message && err.message !== code) return base + ' ' + err.message;
    return base;
  };

  C.erreur = function (zone, err, reessayer) {
    zone.removeAttribute('aria-busy');
    zone.innerHTML = '<div class="ses-etat ses-etat-erreur" role="alert"><p>' + e(C.message(err)) + '</p>' +
      (reessayer ? '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-reessayer>' + e(t('c-reessayer')) + '</button>' : '') + '</div>';
    var b = $('[data-reessayer]', zone);
    if (b && reessayer) b.addEventListener('click', reessayer);
  };

  /* Charge, dessine, sait se redessiner quand la langue change. Une réponse tardive d'un chargement abandonné est ignorée. */
  C.charger = function (zone, appel, dessiner, options) {
    var mien = ++numeroChargement;
    zone._v = mien;
    if (!options || !options.silencieux) C.etat(zone, 'chargement');
    return appel().then(function (donnees) {
      if (zone._v !== mien) return;
      zone.removeAttribute('aria-busy');
      zone._rendu = function () { dessiner(donnees); };
      dessiner(donnees);
      miseAJour();
    }, function (err) {
      if (zone._v !== mien) return;
      zone._rendu = null;
      C.erreur(zone, err, function () { C.charger(zone, appel, dessiner); });
    });
  };

  /* --- Petits outils d'affichage ------------------------------------------ */
  var GENRES = {
    OPEN: 'warn', IN_PROGRESS: 'info', RESOLVED: 'ok', CANCELLED: 'neutre', HIGH: 'bad', MEDIUM: 'warn', LOW: 'neutre',
    PAID: 'ok', ISSUED: 'info', PARTIALLY_PAID: 'warn', OVERDUE: 'bad', REFUNDED: 'neutre', DRAFT: 'neutre',
    SENT: 'ok', PENDING: 'warn', FAILED: 'bad', ACTIVE: 'ok', ON_LEAVE: 'warn', INACTIVE: 'neutre',
    CLEARED: 'ok', SUBMITTED: 'warn', UNDER_REVIEW: 'warn', REJECTED: 'bad', APPROVED: 'ok', REQUESTED: 'info',
    requested: 'info', scheduled: 'ok', on_the_way: 'ok', completed: 'ok', delivered: 'ok', missed: 'bad', rejected: 'bad', cancelled: 'neutre',
    DELIVERED: 'ok', ON_HOLD: 'warn', DAMAGED: 'bad', LOST: 'bad', RETURNED: 'neutre', ANSWERED: 'ok', CLOSED: 'neutre', AT_DESTINATION_HUB: 'ok', AT_HUB: 'ok'
  };
  /* Une pastille dit toujours le statut en toutes lettres : la couleur ne le porte jamais seule. */
  C.pastille = function (cle, code) {
    var texte = t(cle);
    return '<span class="ses-pastille ses-pastille-' + (GENRES[code] || 'neutre') + '">' + e(texte || code) + '</span>';
  };
  C.pays = function (code) { return code ? (UI.nomPays(code) || code) : ''; };
  C.nombre = UI.nombre;
  C.date = function (iso) { return iso ? UI.date(iso, true) : '—'; };
  C.jour = function (iso) { return iso ? UI.date(iso) : '—'; };
  C.montant = UI.montant;
  C.vide = function (v) { return v === null || v === undefined || v === '' ? '—' : e(v); };

  /* Depuis combien de temps : une mise en forme, pas un calcul métier (la base fournit la date, et le décompte « en retard » ou « en attente »). */
  C.age = function (iso) {
    if (!iso) return '';
    var min = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
    if (min < 60) return t('c-age-min', { nombre: min });
    if (min < 2880) return t('c-age-h', { nombre: Math.round(min / 60) });
    return t('c-age-j', { nombre: Math.round(min / 1440) });
  };

  /* --- Adresse d'une section : #centre/colis?statut=ON_HOLD&pays=DO ------- */
  function lireAdresse() {
    var h = String(location.hash || '').replace(/^#/, '');
    if (h.split('/')[0] !== 'centre') return null;
    var reste = h.slice('centre'.length).replace(/^\//, '');
    var i = reste.indexOf('?');
    var id = (i < 0 ? reste : reste.slice(0, i)) || 'commande';
    var f = {};
    if (i >= 0) reste.slice(i + 1).split('&').forEach(function (p) {
      var k = p.split('=')[0], v = p.indexOf('=') >= 0 ? p.slice(p.indexOf('=') + 1) : '';
      if (k && v) { try { f[decodeURIComponent(k)] = decodeURIComponent(v.replace(/\+/g, ' ')); } catch (x) { /* adresse mal formée : on l'ignore */ } }
    });
    return { id: id, filtres: f };
  }
  function ecrireAdresse(id, filtres, remplacer) {
    var q = Object.keys(filtres || {}).filter(function (k) { return filtres[k] !== '' && filtres[k] !== undefined && filtres[k] !== null; })
      .map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(filtres[k]); }).join('&');
    var h = '#centre' + (id && id !== 'commande' || q ? '/' + (id || 'commande') : '') + (q ? '?' + q : '');
    if (location.hash === h) return;
    if (remplacer) history.replaceState(null, '', h); else history.pushState(null, '', h);
  }
  /* Le lien d'un chiffre vers sa liste filtrée. Rend '' si ce compte ne peut pas ouvrir la section (le chiffre n'est alors pas un lien). */
  C.lien = function (id, filtres) {
    if (!C.peutOuvrir(id)) return '';
    if (id === 'rapports') return '#dashboard';
    var q = Object.keys(filtres || {}).filter(function (k) { return filtres[k]; }).map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(filtres[k]); }).join('&');
    return '#centre/' + id + (q ? '?' + q : '');
  };

  /* --- Les filtres communs ------------------------------------------------ */
  var CHAMPS = {
    statut: { cle: 'statut', t: 'c-f-statut' }, pays: { cle: 'pays', t: 'c-f-pays' }, service: { cle: 'service', t: 'c-f-service' }, ville: { cle: 'ville', t: 'c-f-ville' },
    entrepot: { cle: 'entrepot', t: 'c-f-entrepot' }, client: { cle: 'client', t: 'c-f-client' }, du: { cle: 'du', t: 'c-f-du' }, au: { cle: 'au', t: 'c-f-au' }
  };
  var PAYS = ['HT', 'DO', 'US'];
  var SERVICES = ['air', 'sea', 'ground'];

  function options(valeurs, courant, libelle, tous) {
    return '<option value="">' + e(t(tous || 'c-f-tous')) + '</option>' + valeurs.map(function (v) {
      return '<option value="' + e(v) + '"' + (String(courant || '') === String(v) ? ' selected' : '') + '>' + e(libelle(v)) + '</option>';
    }).join('');
  }

  function champ(def, nom, valeur) {
    var id = 'cc-f-' + nom;
    var lib = '<span>' + e(t(CHAMPS[nom].t)) + '</span>';
    if (nom === 'statut') {
      if (def.statutLibre) return '<label class="ses-champ" for="' + id + '">' + lib + '<input id="' + id + '" name="statut" type="text" maxlength="40" value="' + e(valeur || '') + '" placeholder="' + e(t(def.statutLibre)) + '"></label>';
      return '<label class="ses-champ" for="' + id + '">' + lib + '<select id="' + id + '" name="statut">' + options(def.statuts || [], valeur, function (v) { return t(def.prefixeStatut + v) || v; }) + '</select></label>';
    }
    if (nom === 'pays') return '<label class="ses-champ" for="' + id + '">' + lib + '<select id="' + id + '" name="pays">' + options(PAYS, valeur, function (v) { return C.pays(v); }) + '</select></label>';
    if (nom === 'service') return '<label class="ses-champ" for="' + id + '">' + lib + '<select id="' + id + '" name="service">' + options(SERVICES, valeur, function (v) { return t('c-svc-' + v); }) + '</select></label>';
    if (nom === 'entrepot') {
      var liste = entrepots || [];
      return '<label class="ses-champ" for="' + id + '">' + lib + '<select id="' + id + '" name="entrepot">' + options(liste.map(function (w) { return w.warehouse_id; }), valeur, function (v) {
        var w = liste.filter(function (x) { return x.warehouse_id === v; })[0]; return w ? w.code + ' — ' + w.name : v;
      }) + '</select></label>';
    }
    if (nom === 'du' || nom === 'au') return '<label class="ses-champ" for="' + id + '">' + lib + '<input id="' + id + '" name="' + nom + '" type="date" value="' + e(valeur || '') + '"></label>';
    var aide = nom === 'client' ? ' placeholder="' + e(t('c-f-client-aide')) + '"' : '';
    return '<label class="ses-champ" for="' + id + '">' + lib + '<input id="' + id + '" name="' + nom + '" type="text" maxlength="80" value="' + e(valeur || '') + '"' + aide + '></label>';
  }

  /* La barre de filtres d'une section : seulement les champs qu'elle déclare, et seulement ceux dont ce compte peut remplir la liste. */
  C.barreFiltres = function (def, filtres) {
    var noms = (def.filtres || []).filter(function (n) { return n !== 'entrepot' || (entrepots && entrepots.length); });
    if (!noms.length) return '';
    // Repliés sur un petit écran tant qu'aucun filtre n'est actif : la liste reste à portée de pouce.
    var actifs = noms.filter(function (n) { return filtres[n]; }).length;
    var ouvert = actifs > 0 || !(window.matchMedia && window.matchMedia('(max-width: 900px)').matches);
    return '<details class="cc-filtres-boite"' + (ouvert ? ' open' : '') + '><summary>' + e(t('c-filtres-titre')) + (actifs ? ' · ' + e(t('c-filtres-actifs', { nombre: actifs })) : '') + '</summary>' +
      '<form class="cc-filtres" novalidate aria-label="' + e(t('c-filtres-titre')) + '">' + noms.map(function (n) { return champ(def, n, filtres[n]); }).join('') +
      '<div class="cc-filtres-actions"><button type="submit" class="ses-bouton ses-bouton-principal ses-bouton-mini">' + e(t('c-appliquer')) + '</button>' +
      '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-raz>' + e(t('c-raz')) + '</button></div></form></details>';
  };

  C.lireFiltres = function (form) {
    var f = {};
    $$('input,select', form).forEach(function (c) { if (c.name && String(c.value).trim() !== '') f[c.name] = String(c.value).trim(); });
    return f;
  };

  /* --- Tableaux et pagination -------------------------------------------- */
  C.tableau = function (colonnes, lignes, opts) {
    opts = opts || {};
    return '<div class="cc-table-zone"><table class="ses-tableau cc-table"><caption class="sr-only">' + e(t(opts.legende || 'c-tableau')) + '</caption><thead><tr>' +
      colonnes.map(function (c) { return '<th scope="col"' + (c.classe ? ' class="' + e(c.classe) + '"' : '') + '>' + e(t(c.t)) + '</th>'; }).join('') +
      '</tr></thead><tbody>' + lignes.map(function (l, i) {
        return '<tr' + (opts.cleLigne ? ' data-cle="' + e(opts.cleLigne(l)) + '"' : '') + ' data-i="' + i + '">' + colonnes.map(function (c) {
          return '<td' + (c.classe ? ' class="' + e(c.classe) + '"' : '') + (c.t ? ' data-label="' + e(t(c.t)) + '"' : '') + '>' + c.rendre(l, i) + '</td>';
        }).join('') + '</tr>';
      }).join('') + '</tbody></table></div>';
  };

  function pagination(total, page, nb) {
    var debut = nb ? page * PAR_PAGE + 1 : 0, fin = page * PAR_PAGE + nb;
    return '<nav class="cc-pagination" aria-label="' + e(t('c-pagination')) + '"><span aria-live="polite">' + e(t('c-page-info', { debut: C.nombre(debut), fin: C.nombre(fin), total: C.nombre(total) })) + '</span>' +
      '<span class="cc-pagination-boutons"><button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-page="-1"' + (page <= 0 ? ' disabled' : '') + '>' + e(t('c-precedent')) + '</button>' +
      '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-page="1"' + (fin >= total ? ' disabled' : '') + '>' + e(t('c-suivant')) + '</button></span></nav>';
  }

  /* Les comptes par statut que la base rend (« by_status ») : des pastilles qui filtrent d'un clic. */
  function puces(def, donnees, filtres) {
    var par = donnees && (donnees.by_status || donnees.by_stage);
    if (!par || !def.prefixeStatut) return '';
    var cles = Object.keys(par).sort();
    if (!cles.length) return '';
    return '<ul class="cc-puces" aria-label="' + e(t('c-par-statut')) + '">' + cles.map(function (k) {
      var actifP = filtres.statut === k;
      return '<li><button type="button" class="cc-puce' + (actifP ? ' cc-puce-actif' : '') + '" data-statut="' + e(k) + '" aria-pressed="' + (actifP ? 'true' : 'false') + '">' +
        e(t(def.prefixeStatut + k) || k) + ' <strong>' + e(C.nombre(par[k])) + '</strong></button></li>';
    }).join('') + '</ul>';
  }

  /* --- Une section en liste : la mécanique commune ----------------------- */
  function dessinerListe(zone, def, st, donnees) {
    var lignes = donnees.items || [];
    var html = '';
    if (def.resume) html += def.resume(donnees, st.filtres) || '';
    html += puces(def, donnees, st.filtres);
    if (!lignes.length) html += '<div class="ses-bloc">' + UI.vide(t(def.vide || 'c-vide'), '▢') + '</div>';
    else html += C.tableau(def.colonnes, lignes, { cleLigne: def.cle, legende: 'c-sec-' + def.id }) + pagination(donnees.total, st.page, lignes.length);
    zone.innerHTML = html;
    zone._lignes = lignes;
    if (def.apres) def.apres(zone, donnees);
  }

  function chargerListe(def, st, silencieux) {
    var zone = $('#cc-liste');
    if (!zone) return;
    return C.charger(zone, function () {
      return API.centre.liste(def.vue, st.filtres, { limite: PAR_PAGE, decalage: st.page * PAR_PAGE });
    }, function (donnees) { dessinerListe(zone, def, st, donnees); }, { silencieux: silencieux });
  }

  function ouvrirListe(def, st) {
    var racine = $('#cc-contenu');
    racine.innerHTML = (def.intro ? '<p class="cc-intro">' + e(t(def.intro)) + '</p>' : '') + C.barreFiltres(def, st.filtres) + '<div id="cc-liste" aria-live="polite"></div>';
    chargerListe(def, st);
  }

  /* --- Navigation entre sections ----------------------------------------- */
  var GROUPES = [
    { id: 'pilotage', t: 'c-grp-pilotage', sections: ['commande', 'rapports'] },
    { id: 'operations', t: 'c-grp-operations', sections: ['flux', 'colis', 'expeditions', 'entrepot', 'consolidations', 'transport', 'chauffeurs', 'enlevements', 'livraisons', 'douane', 'incidents', 'notifications'] },
    { id: 'clients', t: 'c-grp-clients', sections: ['clients', 'support', 'facturation', 'paiements'] },
    { id: 'direction', t: 'c-grp-direction', sections: ['utilisateurs', 'audit', 'parametres'] }
  ];

  function dessinerNav() {
    var nav = $('#cc-nav');
    if (!nav) return;
    var ouvertes = sectionsOuvertes();
    nav.innerHTML = GROUPES.map(function (g) {
      var vues = g.sections.map(vueDe).filter(function (v) { return v && ouvertes.indexOf(v) >= 0; });
      if (!vues.length) return '';
      return '<div class="cc-nav-groupe"><h3>' + e(t(g.t)) + '</h3><ul>' + vues.map(function (v) {
        var cur = courante && courante.id === v.id;
        return '<li><a class="cc-nav-lien' + (cur ? ' cc-nav-actif' : '') + '" href="' + e(v.id === 'rapports' ? '#dashboard' : '#centre/' + v.id) + '"' + (cur ? ' aria-current="page"' : '') + '>' + e(t('c-sec-' + v.id)) + '</a></li>';
      }).join('') + '</ul></div>';
    }).join('');
    // Sur un petit écran, la navigation défile en largeur : la section ouverte reste visible.
    var cur = nav.querySelector('.cc-nav-actif');
    if (cur && nav.scrollWidth > nav.clientWidth) nav.scrollLeft = Math.max(0, cur.offsetLeft - nav.clientWidth / 2 + cur.offsetWidth / 2);
  }

  function miseAJour() {
    var z = $('#cc-maj');
    if (z) z.textContent = t('c-maj', { heure: new Date().toLocaleTimeString(UI_locale(), { hour: '2-digit', minute: '2-digit' }) });
  }
  function UI_locale() { return ({ fr: 'fr-FR', en: 'en-US', es: 'es-ES', ht: 'fr-HT' })[(document.documentElement.lang || 'fr').slice(0, 2)] || 'fr-FR'; }

  function monter() {
    var racine = $('#cc-racine');
    if (racine.getAttribute('data-pret')) return;
    racine.setAttribute('data-pret', 'oui');
    racine.innerHTML =
      '<div class="cc-entete"><div><h2 id="cc-titre" tabindex="-1"></h2><p id="cc-maj" class="cc-maj" aria-live="off"></p></div>' +
      '<div class="cc-entete-actions"><label class="cc-auto"><input type="checkbox" id="cc-auto" checked> <span></span></label>' +
      '<button type="button" id="cc-actualiser" class="ses-bouton ses-bouton-second ses-bouton-mini"></button></div></div>' +
      '<div class="cc-corps"><nav id="cc-nav" class="cc-nav" aria-label=""></nav><div class="cc-zone"><div id="cc-contenu"></div></div></div>';
    $('#cc-actualiser').addEventListener('click', function () { actualiser(false); });
    $('#cc-auto').addEventListener('change', function () { reglerMinuteur(); });
    racine.addEventListener('click', clics);
    racine.addEventListener('submit', function (ev) {
      var f = ev.target.closest('.cc-filtres');
      if (!f) return;
      ev.preventDefault();
      aller(courante.id, C.lireFiltres(f));
    });
    document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') fermerDialogue(); });
    libelles();
  }

  function libelles() {
    var racine = $('#cc-racine');
    if (!racine || !racine.getAttribute('data-pret')) return;
    $('#cc-nav').setAttribute('aria-label', t('c-nav-titre'));
    $('#cc-actualiser').textContent = t('c-actualiser');
    $('.cc-auto span').textContent = t('c-auto');
    if (courante) $('#cc-titre').textContent = t('c-sec-' + courante.id);
  }

  function clics(ev) {
    var b;
    if ((b = ev.target.closest('[data-raz]'))) { ev.preventDefault(); return aller(courante.id, {}); }
    if ((b = ev.target.closest('[data-page]'))) {
      var st = etats[courante.id];
      st.page = Math.max(0, st.page + Number(b.getAttribute('data-page')));
      var def = vueDe(courante.id);
      chargerListe(def, st);
      var z = $('#cc-contenu');
      if (z && z.scrollIntoView) z.scrollIntoView({ block: 'start', behavior: 'smooth' });
      return;
    }
    if ((b = ev.target.closest('.cc-puce'))) {
      var f = {}, s = etats[courante.id];
      Object.keys(s.filtres).forEach(function (k) { f[k] = s.filtres[k]; });
      if (f.statut === b.getAttribute('data-statut')) delete f.statut; else f.statut = b.getAttribute('data-statut');
      return aller(courante.id, f);
    }
    if ((b = ev.target.closest('.cc-nav-lien')) && b.getAttribute('href').indexOf('#centre') === 0) {
      ev.preventDefault();
      return aller(b.getAttribute('href').replace(/^#centre\/?/, '').split('?')[0] || 'commande', {});
    }
    var def2 = courante && vueDe(courante.id);
    if (def2 && def2.clic) def2.clic(ev, etats[courante.id], { recharger: function () { actualiser(true); } });
  }

  /* Aller à une section avec des filtres : l'adresse change (précédent/suivant fonctionnent), puis la section se dessine. */
  function aller(id, filtres) {
    var def = vueDe(id);
    if (!def || !C.peutOuvrir(id)) id = 'commande';
    etats[id] = { filtres: filtres || {}, page: 0 };
    ecrireAdresse(id, etats[id].filtres, false);
    afficher(id, etats[id]);
  }
  C.aller = aller;

  function afficher(id, st) {
    var def = vueDe(id);
    if (!def) return;
    if (def.id === 'rapports') { location.hash = '#dashboard'; return; }
    // La section qu'on quitte range ce qu'elle a branché (le poste de scan arrête d'écouter le scanner USB).
    var avant = courante && vueDe(courante.id);
    if (avant && avant.id !== id && typeof avant.quitter === 'function') { try { avant.quitter(); } catch (x) { /* elle ne bloque jamais la navigation */ } }
    courante = { id: id };
    dessinerNav();
    libelles();
    var titre = $('#cc-titre');
    if (titre) titre.textContent = t('c-sec-' + id);
    if (def.rendre) def.rendre($('#cc-contenu'), st, C);
    else ouvrirListe(def, st);
    reglerMinuteur();
  }

  /* L'adresse a changé (clic sur un lien, précédent, suivant, lien d'un chiffre) : on affiche ce qu'elle désigne. */
  function suivreAdresse() {
    var a = lireAdresse();
    if (!a || !actif) return;
    var id = vueDe(a.id) && C.peutOuvrir(a.id) ? a.id : 'commande';
    etats[id] = { filtres: a.filtres, page: (etats[id] && JSON.stringify(etats[id].filtres) === JSON.stringify(a.filtres)) ? etats[id].page : 0 };
    monter();
    afficher(id, etats[id]);
  }

  /* --- Actualisation ------------------------------------------------------ */
  function actualiser(silencieux) {
    if (!courante) return;
    var def = vueDe(courante.id), st = etats[courante.id];
    if (!def) return;
    if (def.actualiser) return def.actualiser($('#cc-contenu'), st, C, silencieux);
    if (def.vue) return chargerListe(def, st, silencieux);
  }
  function reglerMinuteur() {
    clearInterval(minuteur);
    minuteur = null;
    var auto = $('#cc-auto');
    if (!auto || !auto.checked || !courante) return;
    minuteur = setInterval(function () {
      var onglet = document.getElementById('ses-o-centre');
      if (document.visibilityState !== 'visible' || !onglet || onglet.getAttribute('aria-selected') !== 'true') return;
      if ($('#cc-dialogue') && $('#cc-dialogue').open) return;   // jamais sous les doigts de quelqu'un qui écrit
      actualiser(true);
    }, ACTUALISATION_MS);
  }

  /* --- La boîte de dialogue commune --------------------------------------- */
  var dernierFocus = null;
  C.dialogue = function (titreCle, html, largeur) {
    var d = $('#cc-dialogue');
    if (!d) return null;
    dernierFocus = document.activeElement;
    d.className = 'ses-dialogue' + (largeur === 'etroit' ? ' ses-dialogue-etroit' : '');
    $('#cc-dialogue-titre').textContent = t(titreCle);
    $('#cc-dialogue-contenu').innerHTML = html;
    if (!d.open) d.showModal();
    return $('#cc-dialogue-contenu');
  };
  function fermerDialogue() {
    var d = $('#cc-dialogue');
    if (d && d.open) d.close();
    if (dernierFocus && dernierFocus.focus) { try { dernierFocus.focus(); } catch (x) { /* l'élément a disparu avec le rechargement */ } }
  }
  C.fermerDialogue = fermerDialogue;

  C.annoncer = function (texte, genre) {
    var zone = document.getElementById('ses-message');
    if (!zone) return;
    UI.annonce(zone, texte, genre);
    clearTimeout(C._annonce);
    C._annonce = setTimeout(function () { UI.annonce(zone, ''); }, 6000);
  };

  /* --- Mise en route ------------------------------------------------------ */
  function charger_entrepots() {
    if (!acces || (acces.sections || []).indexOf('entrepot') < 0) return Promise.resolve();
    return API.centre.entrepot({}).then(function (r) { entrepots = (r && r.warehouses) || []; }, function () { entrepots = []; });
  }
  C.entrepots = function () { return entrepots || []; };

  function demarrer() {
    API.profil().then(function (p) {
      if (!p || API.ROLES_EQUIPE.indexOf(p.role) < 0) return null;
      return API.centre.disponible();
    }).then(function (d) {
      if (!d || !d.actif) return;
      acces = d.acces;
      return charger_entrepots().then(function () {
        actif = true;
        var b = document.getElementById('ses-o-centre');
        if (b) b.hidden = false;
        // L'adresse change (précédent, suivant, lien d'un chiffre) : le tableau de bord réactive l'onglet, et c'est ce clic qui dessine la section.
        b.addEventListener('click', function () { monter(); suivreAdresseOuAccueil(); });
        // Le temps réel (phase 13) : un signal « quelque chose a changé » arrive de la base ; on relit la section ouverte, sans bruit, et pas
        // sous les doigts de quelqu'un qui écrit dans une fiche. Plusieurs signaux rapprochés ne font qu'une relecture.
        if (API.notifications && API.notifications.surveiller) {
          var enAttente = null;
          API.notifications.surveiller('staff', function () {
            clearTimeout(enAttente);
            enAttente = setTimeout(function () {
              var onglet = document.getElementById('ses-o-centre');
              if (!onglet || onglet.getAttribute('aria-selected') !== 'true' || document.visibilityState !== 'visible') return;
              if ($('#cc-dialogue') && $('#cc-dialogue').open) return;
              actualiser(true);
            }, 1500);
          });
        }
        UI.surLangue(function () {
          if (!courante) return;
          // Tout se redessine dans la nouvelle langue : filtres, pastilles, en-têtes — et les chiffres sont relus (une seule requête de plus).
          libelles();
          afficher(courante.id, etats[courante.id]);
        });
        // Une adresse #centre/… ouverte avant que l'onglet soit disponible : on la remet, puis le tableau de bord la relit et choisit l'onglet.
        if (/^#centre/.test(adresseInitiale) && !/^#centre/.test(location.hash) && (location.hash === '' || location.hash === '#dashboard')) history.replaceState(null, '', adresseInitiale);
        if (/^#centre/.test(location.hash)) window.dispatchEvent(new Event('hashchange'));
      });
    }).catch(function () { /* au moindre doute, le tableau de bord d'avant reste seul */ });
  }
  function suivreAdresseOuAccueil() {
    var a = lireAdresse();
    if (a) return suivreAdresse();
    if (!courante) aller('commande', {}); else afficher(courante.id, etats[courante.id]);
  }

  C.etats = etats;
  C.rafraichir = function () { actualiser(true); };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', demarrer);
  else demarrer();
})();
