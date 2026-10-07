/* ==========================================================================
   Speed Express Shipping — comptes clients, colis et factures
   --------------------------------------------------------------------------
   Une seule interface (window.SES_API) pour tout le site, trois
   fonctionnements selon ce qui est renseigné dans config.js :

   « supabase »  adresse et clé Supabase renseignées : les comptes, les colis
                 et les factures sont enregistrés en ligne. Les mots de passe
                 sont confiés à Supabase (jamais stockés par le site), et
                 chaque requête est filtrée par le serveur : un client ne peut
                 pas lire les données d'un autre, même en modifiant la page.

   « demo »      sans configuration, sur votre ordinateur (fichier ouvert
                 directement, localhost, réseau local). Tout reste dans ce
                 navigateur : de quoi essayer tous les parcours avant la mise
                 en ligne. Les mots de passe y sont dérivés par PBKDF2-SHA-256
                 (150 000 tours, sel tiré au hasard pour chaque compte) :
                 jamais en clair, même dans ce mode d'essai.

   « off »       sans configuration, sur un vrai nom de domaine. L'espace
                 client reste fermé : aucun compte, aucune donnée fictive.

   Le mode est lisible dans SES_API.mode, et la page d'inscription comme le
   tableau de bord l'indiquent à l'écran.
   ========================================================================== */
(function () {
  'use strict';

  var CFG = window.SES_CONFIG || {};

  /* Bibliothèque Supabase rangée dans le site : aucun script extérieur ne
     s'exécute dans les pages des clients. */
  var SUPABASE_JS = (function () {
    var moi = document.currentScript;
    var base = moi && moi.src ? moi.src.replace(/[^/]*$/, '') : 'assets/js/';
    return base + 'vendor/supabase-2.116.0.js';
  })();

  var LOCAL = location.protocol === 'file:' ||
    /^(localhost|127(\.\d+){3}|\[::1\]|10(\.\d+){3}|192\.168(\.\d+){2}|172\.(1[6-9]|2\d|3[01])(\.\d+){2}|[\w-]+\.local)$/
      .test(location.hostname);

  var MODE = CFG.supabaseUrl && CFG.supabaseKey ? 'supabase' : (LOCAL ? 'demo' : 'off');

  /* --- Vocabulaire commun ------------------------------------------------
     Les cinq états d'un colis, dans l'ordre du parcours. « action » n'est pas
     une étape : c'est un arrêt qui demande quelque chose au client.        */
  var STATUTS = ['confirme', 'expedie', 'disponible', 'livre', 'action'];
  var ETAPES = { confirme: 1, expedie: 2, disponible: 3, livre: 4 };

  /* Quatre rôles, du moins au plus de pouvoir. Le même ordre que dans la base
     (voir la fonction a_droit dans outils/supabase.sql) : la base décide, ce
     fichier ne fait que refléter sa décision pour l'affichage. */
  var ROLES = ['client', 'employe', 'gerant', 'admin'];

  /* Ceux qui travaillent dans l'équipe. Un client n'en fait JAMAIS partie : il
     n'entre pas dans le tableau de bord, quels que soient les droits que sa
     fiche prétendrait porter. */
  var ROLES_EQUIPE = ['employe', 'gerant', 'admin'];

  /* La direction : l'administrateur et le gérant ont tous les droits d'activité
     sans qu'on les leur coche. Seul l'administrateur nomme ou modifie l'un
     d'eux. */
  var ROLES_DIRECTION = ['gerant', 'admin'];

  /* Le tableau de bord s'ouvre à qui peut lire au moins l'un de ces domaines. */
  var DROITS_TABLEAU_DE_BORD = ['colis.lire', 'factures.lire', 'clients.lire'];

  /* Droits confiables à un employé. L'administrateur les a tous. */
  var DROITS = [
    'colis.lire', 'colis.creer', 'colis.modifier', 'colis.statut', 'colis.supprimer',
    'factures.lire', 'factures.creer', 'factures.modifier', 'factures.supprimer',
    'clients.lire', 'roles.gerer'
  ];

  var CHAMPS_PROFIL = ['nom_complet', 'pays', 'region', 'ville', 'adresse', 'telephone', 'langue'];
  var CHAMPS_COLIS = ['client_id', 'description', 'expediteur', 'destinataire',
                      'telephone_destinataire', 'poids_lb', 'tarif_lb', 'service',
                      'pays_destination', 'ville_destination', 'adresse_livraison', 'valeur_declaree',
                      'statut', 'lieu', 'note'];
  var CHAMPS_FACTURE = ['client_id', 'colis_id', 'montant', 'frais_service', 'montant_paye',
                        'devise', 'statut', 'note', 'echeance_le', 'lignes', 'groupee'];

  /* Frais de service, fixes, ajoutés une fois par facture. Ils ne se règlent
     pas depuis le formulaire : la base les pose elle-même (voir la fonction
     facturer_colis dans outils/supabase.sql), et cette constante sert au mode
     démo et à l'affichage. */
  var FRAIS_SERVICE = 10;

  var MDP_MINIMUM = 8;

  /* Les méthodes du portail client : les trois implémentations les ont TOUTES (voir outils/tests/portail-contrat.cjs). */
  var METHODES_PORTAIL = ['disponible', 'tableau', 'colis', 'colisDetail', 'expeditions', 'consolidations', 'factures', 'solde', 'paiements', 'documents', 'adresses',
                          'enregistrerAdresse', 'supprimerAdresse', 'enlevements', 'demanderEnlevement', 'annulerEnlevement', 'livraisons', 'demanderLivraison',
                          'annulerLivraison', 'notifications', 'lireNotifications', 'tickets', 'ticket', 'ouvrirTicket', 'repondreTicket', 'fermerTicket'];

  /* Le centre de commande de l'équipe (outils/logistique/009-centre-de-commande.sql). Les trois implémentations ont les mêmes méthodes (voir
     outils/tests/centre-contrat.cjs) ; seule la version en ligne répond : voir le commentaire de « centre » plus bas. */
  var METHODES_CENTRE = ['disponible', 'acces', 'indicateurs', 'aTraiter', 'liste', 'entrepot', 'colisDetail', 'ticket', 'reglages',
                         'traiterEnlevement', 'traiterLivraison', 'repondreTicket', 'fermerTicket'];
  /* Quelle fonction de la base sert quelle vue : l'unique table de correspondance, relue par le test contre les signatures réelles de la base. */
  var VUES_CENTRE = { flux: 'lg_cc_flow', colis: 'lg_cc_parcels', expeditions: 'lg_cc_shipments', consolidations: 'lg_cc_consolidations', transport: 'lg_cc_transports',
                      chauffeurs: 'lg_cc_drivers', enlevements: 'lg_cc_pickups', livraisons: 'lg_cc_deliveries', douane: 'lg_cc_customs', incidents: 'lg_cc_incidents',
                      notifications: 'lg_cc_notifications', clients: 'lg_cc_customers', factures: 'lg_cc_invoices', paiements: 'lg_cc_payments', tickets: 'lg_cc_tickets',
                      utilisateurs: 'lg_cc_users', audit: 'lg_cc_audit' };
  /* Notifications et temps réel (outils/logistique/010-notifications.sql) : préférences du client, santé des envois pour l'équipe, et le
     signal « relisez » (public.ses_signal). Mêmes méthodes dans les trois implémentations (voir outils/tests/notifications-contrat.cjs). */
  var METHODES_NOTIFICATIONS = ['preferences', 'reglerPreference', 'sante', 'surveiller'];
  var CANAUX_NOTIFICATION = ['email', 'in_app', 'push', 'sms', 'whatsapp'];
  /* Le poste de scan du bureau (phase 15, ADR 0013) : qui je suis pour l'entrepôt (outils/logistique/011-applications.sql) et un scan
     (004-entrepot.sql). Comme le centre qui l'accueille, il n'existe qu'en ligne : la démonstration et le site fermé répondent « fermé »
     (voir outils/tests/poste-contrat.cjs). Les intentions proposées : celles qui n'exigent pas d'emplacement. */
  var METHODES_POSTE = ['profil', 'scanner'];
  var INTENTIONS_POSTE = ['receive', 'verify', 'consolidate', 'dispatch', 'lookup'];
  /* L'analytique (phase 16, outils/logistique/012-analytique.sql, ADR 0014) : rapports du jour à l'année, indicateurs, exécutions tracées.
     Seulement en ligne : des chiffres de démonstration seraient trompeurs (même exception que le centre ; voir analytique-contrat.cjs). */
  var METHODES_ANALYTIQUE = ['rapport', 'indicateurs', 'executions', 'recalculer', 'verifier'];
  var GRAINS_ANALYTIQUE = ['day', 'week', 'month', 'quarter', 'year'];
  /* L'exploitation (phase 17, 013-exploitation.sql, ADR 0015) : la sonde, l'état détaillé pour la direction, le signalement des erreurs. */
  var METHODES_EXPLOITATION = ['sante', 'etat', 'signalerErreur'];

  /* Les filtres de l'écran portent des noms français ; la base attend les siens. Un filtre vide n'est pas envoyé. */
  var FILTRES_CENTRE = { pays: 'country', ville: 'city', entrepot: 'warehouse_id', statut: 'status', service: 'service', client: 'customer', du: 'from', au: 'to' };

  function Erreur(code, detail) {
    var e = new Error(detail || code);
    e.code = code;
    return e;
  }

  /* Un champ numérique laissé vide dans un formulaire arrive ici sous la forme
     d'une chaîne vide. PostgreSQL ne sait pas lire '' comme un nombre : il
     refuse la ligne entière, et le site n'affichait qu'« une erreur est
     survenue ». On traduit donc le vide avant l'envoi — rien du tout pour les
     colonnes qui acceptent l'absence, zéro pour celles qui exigent un nombre. */
  var NOMBRES_FACULTATIFS = ['poids_lb', 'valeur_declaree'];
  var NOMBRES_OBLIGATOIRES = ['tarif_lb', 'montant', 'frais_service', 'montant_paye'];

  function vide(v) { return v === '' || v === null || v === undefined; }

  /* Un nombre demandé, ou son défaut quand il est absent. Zéro est une VRAIE valeur : « limite : 0 » n'est pas « pas de limite ». */
  function nombre(v, defaut) { return vide(v) || isNaN(Number(v)) ? defaut : Number(v); }

  function normaliserNombres(champs) {
    var sortie = {};
    Object.keys(champs || {}).forEach(function (cle) {
      var v = champs[cle];
      if (NOMBRES_FACULTATIFS.indexOf(cle) >= 0) {
        sortie[cle] = vide(v) ? null : Number(v);
      } else if (NOMBRES_OBLIGATOIRES.indexOf(cle) >= 0) {
        sortie[cle] = vide(v) ? 0 : Number(v);
      } else {
        sortie[cle] = v;
      }
    });
    return sortie;
  }

  function choisir(source, champs) {
    var out = {};
    champs.forEach(function (k) { if (source[k] !== undefined) out[k] = source[k]; });
    return out;
  }

  function texteCourt(v, max) {
    return String(v === undefined || v === null ? '' : v).trim().slice(0, max || 200);
  }

  /* Identifiant client : « SES- » suivi de cinq chiffres (SES-67491). */
  function normaliserCode(code) {
    var n = String(code || '').replace(/\D/g, '');
    if (n.length < 4) return '';
    return 'SES-' + n;
  }

  function nettoyer(texte) {
    return String(texte || '').replace(/[,()*%\\:"']/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 60);
  }

  function trierHistorique(colis) {
    colis.historique = (colis.historique || colis.colis_historique || []).slice().sort(function (a, b) {
      return new Date(a.cree_le) - new Date(b.cree_le);
    });
    delete colis.colis_historique;
    return colis;
  }

  /* Un colis porte deux codes fabriqués une fois pour toutes, à
     l'enregistrement : son numéro (lisible, imprimé en code-barres) et un
     jeton tiré au hasard, écrit dans le QR code et vérifié à la lecture :
     un lien falsifié ne résout plus. Le numéro seul reste cherchable à la
     main (suivi public : statut et étapes) — le jeton garantit l'intégrité
     du lien, pas un accès réservé. Voir SES_UI.etiquette(). */
  function alea(n) {
    var lettres = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789', out = '';
    var tampon = new Uint32Array(n);
    if (window.crypto && window.crypto.getRandomValues) window.crypto.getRandomValues(tampon);
    else for (var k = 0; k < n; k++) tampon[k] = Math.floor(Math.random() * 0xffffffff);
    for (var i = 0; i < n; i++) out += lettres[tampon[i] % lettres.length];
    return out;
  }

  /* ======================================================================
     Empreintes de mots de passe (mode démonstration)
     ----------------------------------------------------------------------
     PBKDF2-SHA-256, sel de 16 octets tiré au hasard, 150 000 tours. Le mot
     de passe lui-même n'est jamais écrit : seule l'empreinte l'est, au format
     pbkdf2$tours$sel$empreinte. WebCrypto s'en charge quand il est là ; sinon
     (navigateur ancien, page ouverte hors contexte sûr) la même dérivation
     est refaite en JavaScript, avec moins de tours pour rester utilisable.
     ====================================================================== */
  var Empreinte = (function () {
    function b64(octets) {
      var s = '';
      for (var i = 0; i < octets.length; i++) s += String.fromCharCode(octets[i]);
      return btoa(s);
    }
    function deB64(t) {
      var s = atob(t), o = new Uint8Array(s.length);
      for (var i = 0; i < s.length; i++) o[i] = s.charCodeAt(i);
      return o;
    }
    function sel() {
      var s = new Uint8Array(16);
      if (window.crypto && window.crypto.getRandomValues) window.crypto.getRandomValues(s);
      else for (var i = 0; i < 16; i++) s[i] = Math.floor(Math.random() * 256);
      return s;
    }
    var webcrypto = !!(window.crypto && window.crypto.subtle && window.crypto.subtle.importKey);

    /* --- SHA-256 en JavaScript (solution de repli) --- */
    var K = [];
    (function () {
      var k = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
               0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
               0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
               0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
               0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
               0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
               0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
               0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
      K = k;
    })();
    function sha256(octets) {
      var h = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
      var l = octets.length;
      var tailleBits = l * 8;
      var n = ((l + 9 + 63) >> 6) << 6;
      var m = new Uint8Array(n);
      m.set(octets);
      m[l] = 0x80;
      var vue = new DataView(m.buffer);
      vue.setUint32(n - 4, tailleBits >>> 0);
      vue.setUint32(n - 8, Math.floor(tailleBits / 0x100000000));
      var w = new Uint32Array(64);
      for (var bloc = 0; bloc < n; bloc += 64) {
        var i;
        for (i = 0; i < 16; i++) w[i] = vue.getUint32(bloc + i * 4);
        for (i = 16; i < 64; i++) {
          var s0 = rot(w[i-15],7) ^ rot(w[i-15],18) ^ (w[i-15] >>> 3);
          var s1 = rot(w[i-2],17) ^ rot(w[i-2],19) ^ (w[i-2] >>> 10);
          w[i] = (w[i-16] + s0 + w[i-7] + s1) >>> 0;
        }
        var a=h[0],b=h[1],c=h[2],d=h[3],e=h[4],f=h[5],g=h[6],x=h[7];
        for (i = 0; i < 64; i++) {
          var S1 = rot(e,6) ^ rot(e,11) ^ rot(e,25);
          var ch = (e & f) ^ (~e & g);
          var t1 = (x + S1 + ch + K[i] + w[i]) >>> 0;
          var S0 = rot(a,2) ^ rot(a,13) ^ rot(a,22);
          var maj = (a & b) ^ (a & c) ^ (b & c);
          var t2 = (S0 + maj) >>> 0;
          x=g; g=f; f=e; e=(d+t1)>>>0; d=c; c=b; b=a; a=(t1+t2)>>>0;
        }
        h[0]=(h[0]+a)>>>0; h[1]=(h[1]+b)>>>0; h[2]=(h[2]+c)>>>0; h[3]=(h[3]+d)>>>0;
        h[4]=(h[4]+e)>>>0; h[5]=(h[5]+f)>>>0; h[6]=(h[6]+g)>>>0; h[7]=(h[7]+x)>>>0;
      }
      var out = new Uint8Array(32), v2 = new DataView(out.buffer);
      for (var j = 0; j < 8; j++) v2.setUint32(j * 4, h[j]);
      return out;
    }
    function rot(x, n) { return ((x >>> n) | (x << (32 - n))) >>> 0; }

    function hmac(cle, message) {
      var bloc = new Uint8Array(64);
      if (cle.length > 64) bloc.set(sha256(cle)); else bloc.set(cle);
      var i = new Uint8Array(64), o = new Uint8Array(64);
      for (var k = 0; k < 64; k++) { i[k] = bloc[k] ^ 0x36; o[k] = bloc[k] ^ 0x5c; }
      var a = new Uint8Array(64 + message.length);
      a.set(i); a.set(message, 64);
      var interne = sha256(a);
      var b = new Uint8Array(96);
      b.set(o); b.set(interne, 64);
      return sha256(b);
    }

    function pbkdf2JS(motDePasse, selOctets, tours) {
      var mdp = new TextEncoder().encode(motDePasse);
      var bloc = new Uint8Array(selOctets.length + 4);
      bloc.set(selOctets);
      bloc[selOctets.length + 3] = 1;
      var u = hmac(mdp, bloc), resultat = u.slice();
      for (var t = 1; t < tours; t++) {
        u = hmac(mdp, u);
        for (var j = 0; j < 32; j++) resultat[j] ^= u[j];
      }
      return resultat;
    }

    function deriver(motDePasse, selOctets, tours) {
      if (!webcrypto) return Promise.resolve(pbkdf2JS(motDePasse, selOctets, tours));
      var enc = new TextEncoder().encode(motDePasse);
      return window.crypto.subtle.importKey('raw', enc, 'PBKDF2', false, ['deriveBits'])
        .then(function (cle) {
          return window.crypto.subtle.deriveBits(
            { name: 'PBKDF2', salt: selOctets, iterations: tours, hash: 'SHA-256' }, cle, 256);
        })
        .then(function (bits) { return new Uint8Array(bits); })
        .catch(function () { return pbkdf2JS(motDePasse, selOctets, TOURS_JS); });
    }

    var TOURS = 150000;
    var TOURS_JS = 15000;   // la même dérivation, sans WebCrypto : moins de tours pour rester utilisable

    return {
      /* Empreinte d'un nouveau mot de passe. */
      creer: function (motDePasse) {
        var s = sel(), tours = webcrypto ? TOURS : TOURS_JS;
        return deriver(motDePasse, s, tours).then(function (bits) {
          return 'pbkdf2$' + tours + '$' + b64(s) + '$' + b64(bits);
        });
      },
      /* Comparaison à une empreinte enregistrée, sans jamais la déchiffrer. */
      verifier: function (motDePasse, enregistree) {
        var p = String(enregistree || '').split('$');
        if (p.length !== 4 || p[0] !== 'pbkdf2') return Promise.resolve(false);
        var tours = parseInt(p[1], 10);
        if (!(tours > 0)) return Promise.resolve(false);
        return deriver(motDePasse, deB64(p[2]), tours).then(function (bits) {
          var attendue = deB64(p[3]);
          if (attendue.length !== bits.length) return false;
          var diff = 0;
          for (var i = 0; i < bits.length; i++) diff |= bits[i] ^ attendue[i];
          return diff === 0;
        });
      },
      webcrypto: webcrypto
    };
  })();

  /* ======================================================================
     Droits — la même lecture partout
     ====================================================================== */
  function droitsDe(profil) {
    if (!profil) return [];
    if (ROLES_DIRECTION.indexOf(profil.role) >= 0) return DROITS.slice();
    if (profil.role === 'employe') {
      var d = profil.droits || [];
      return DROITS.filter(function (x) { return d.indexOf(x) >= 0; });
    }
    return [];
  }

  function peutFaire(profil, droit) {
    return droitsDe(profil).indexOf(droit) >= 0;
  }

  /* Qui entre dans le tableau de bord. La règle est écrite UNE fois, ici, et
     fermée par défaut : il faut être de l'équipe ET pouvoir lire quelque chose.
     Avant, deux fichiers la recopiaient chacun à sa façon (« a-t-il un droit ? »
     d'un côté, « n'est-il pas client ? » de l'autre) ; un rôle ajouté demain
     aurait pu passer par l'un sans passer par l'autre. Cette règle n'est que le
     confort de l'écran : la sécurité, elle, est dans la base. */
  function accesTableauDeBord(profil) {
    if (!profil || ROLES_EQUIPE.indexOf(profil.role) < 0) return false;
    return DROITS_TABLEAU_DE_BORD.some(function (d) { return peutFaire(profil, d); });
  }

  /* ======================================================================
     Supabase
     ====================================================================== */
  var promesseClient = null;

  function chargerScript(src) {
    return new Promise(function (ok, ko) {
      var s = document.createElement('script');
      s.src = src;
      s.async = true;
      s.onload = ok;
      s.onerror = function () { s.remove(); ko(Erreur('reseau')); };
      document.head.appendChild(s);
    });
  }

  function sb() {
    if (!promesseClient) {
      promesseClient = (window.supabase && window.supabase.createClient ? Promise.resolve() : chargerScript(SUPABASE_JS))
        .then(function () {
          if (!window.supabase || !window.supabase.createClient) throw Erreur('reseau');
          return window.supabase.createClient(String(CFG.supabaseUrl).replace(/\/+$/, ''), CFG.supabaseKey, {
            auth: { flowType: 'implicit', persistSession: true, autoRefreshToken: true, detectSessionInUrl: true }
          });
        });
      promesseClient.catch(function () { promesseClient = null; });
    }
    return promesseClient;
  }

  /* Les liens reçus par e-mail déposent les jetons dans l'adresse de la page.
     Une fois la session enregistrée, ils n'ont plus rien à y faire. */
  function nettoyerAdresse() {
    if (!/(access_token|refresh_token|provider_token)=/.test(location.hash)) return;
    try { history.replaceState(null, '', location.pathname + location.search); } catch (e) {}
  }

  function erreurSupabase(e) {
    if (!e) return Erreur('inconnu');
    if (e.code && /^(identifiants|email-existe|reseau|non-autorise|ferme)$/.test(e.code)) return e;
    var code = String(e.code || ''), msg = String(e.message || '').toLowerCase(), statut = e.status;
    if (code === 'invalid_credentials' || msg.indexOf('invalid login') >= 0) return Erreur('identifiants');
    if (code === 'user_already_exists' || code === 'email_exists' || msg.indexOf('already registered') >= 0) return Erreur('email-existe');
    if (code === 'same_password' || msg.indexOf('different from the old') >= 0) return Erreur('meme-mot-de-passe');
    if (code === 'over_email_send_rate_limit' || statut === 429) return Erreur('trop-de-demandes');
    if (statut === 401 || statut === 403 || code === '42501') return Erreur('non-autorise');
    // 42703 : colonne inconnue de PostgreSQL. PGRST204 : colonne absente du
    // cache de schéma de PostgREST. Dans les deux cas le site envoie un champ
    // que la base ne connaît pas encore — il manque une mise à jour.
    if (code === '42703' || code === 'PGRST204' || msg.indexOf('does not exist') >= 0) {
      return Erreur('base-a-mettre-a-jour', e.message);
    }
    // Les codes du noyau logistique (outils/logistique) : stables, documentés dans INTEGRATION-CONTRACT.md.
    // PGRST202 : la fonction n'existe pas — les migrations du noyau n'ont pas été passées.
    if (code === 'LG002') return Erreur('introuvable', e.message);
    if (code === 'LG003') return Erreur('non-autorise', e.message);
    if (code === 'LG004') return Erreur('etat-incompatible', e.message);
    if (code === 'LG005') return Erreur('donnee-invalide', e.message);
    if (code === 'LG006') return Erreur('doublon', e.message);
    // LG007 : un plafond de débit de la base (outils/logistique/013-exploitation.sql) — même message qu'une limite de l'authentification.
    if (code === 'LG007') return Erreur('trop-de-demandes', e.message);
    if (code === 'PGRST202' || msg.indexOf('could not find the function') >= 0) return Erreur('noyau-absent', e.message);
    // 23514 sur le rôle : la base refuse « gerant » parce qu'elle ne connaît
    // encore que trois rôles. Même remède que pour une colonne manquante.
    if (code === '23514' && msg.indexOf('clients_role_check') >= 0) {
      return Erreur('base-a-mettre-a-jour', e.message);
    }
    // SE001 / SE002 : les deux règles « l'équipe n'est pas la clientèle » de la base
    // (voir definir_role et verifier_client_rattache dans outils/supabase.sql).
    if (code === 'SE001') return Erreur('compte-a-des-colis', e.message);
    if (code === 'SE002') return Erreur('client-invalide', e.message);
    // 22P02 : une valeur n'a pas le type attendu par la colonne.
    if (code === '22P02' || msg.indexOf('invalid input syntax') >= 0) {
      return Erreur('champ-mal-rempli', e.message);
    }
    if (msg.indexOf('failed to fetch') >= 0 || msg.indexOf('networkerror') >= 0) return Erreur('reseau');
    return Erreur('inconnu', e.message);
  }

  function resultat(res) {
    if (res.error) throw erreurSupabase(res.error);
    return res.data;
  }

  function urlPage(nom) {
    return new URL(nom, location.href).href.split('#')[0];
  }

  var supabaseAPI = {
    session: function () {
      return sb().then(function (c) { return c.auth.getSession(); })
        .then(function (r) {
          /* Les jetons ne quittent l'adresse qu'une fois la session lue : les
             effacer avant empêcherait le client de les trouver. */
          nettoyerAdresse();
          return r.data && r.data.session ? r.data.session : null;
        })
        .catch(function () { return null; });
    },

    profil: function () {
      return sb().then(function (c) {
        return c.auth.getUser().then(function (u) {
          if (!u.data || !u.data.user) return null;
          return c.from('clients').select('*').eq('id', u.data.user.id).maybeSingle().then(resultat);
        });
      }).catch(function (e) { if (e && e.code === 'reseau') throw e; return null; });
    },

    inscrire: function (d) {
      return sb().then(function (c) {
        return c.auth.signUp({
          email: texteCourt(d.email, 160).toLowerCase(),
          password: d.motDePasse,
          options: {
            emailRedirectTo: urlPage('espace-client.html'),
            data: {
              nom_complet: texteCourt(d.nom_complet, 120),
              pays: texteCourt(d.pays, 60),
              region: texteCourt(d.region, 80),
              ville: texteCourt(d.ville, 80),
              adresse: texteCourt(d.adresse, 200),
              telephone: texteCourt(d.telephone, 40),
              langue: (document.documentElement.lang || 'fr').slice(0, 2)
            }
          }
        });
      }).then(function (r) {
        if (r.error) throw erreurSupabase(r.error);
        // Sans session, Supabase attend la confirmation de l'adresse e-mail.
        return { confirmation: !r.data.session, profil: null };
      }).then(function (etat) {
        if (etat.confirmation) return etat;
        return supabaseAPI.profil().then(function (p) { return { confirmation: false, profil: p }; });
      });
    },

    connecter: function (email, motDePasse) {
      return sb().then(function (c) {
        return c.auth.signInWithPassword({ email: String(email || '').trim().toLowerCase(), password: motDePasse });
      }).then(function (r) {
        if (r.error) throw erreurSupabase(r.error);
        return supabaseAPI.profil();
      });
    },

    deconnecter: function () {
      return sb().then(function (c) { return c.auth.signOut(); }).then(function () { return true; });
    },

    envoyerLienMotDePasse: function (email) {
      return sb().then(function (c) {
        return c.auth.resetPasswordForEmail(String(email || '').trim().toLowerCase(),
          { redirectTo: urlPage('nouveau-mot-de-passe.html') });
      }).then(function (r) { if (r.error) throw erreurSupabase(r.error); return true; });
    },

    /* Récupération (lien e-mail, visiteur déconnecté) : le lien contient une
       session (#access_token=…) que le client lit à sa création ; si elle est
       là, la page « nouveau mot de passe » s'ouvre. À ne pas confondre avec le
       changement de mot de passe d'un client déjà connecté (espace client),
       qui passe directement par changerMotDePasse. */
    attendreRecuperation: function () {
      return supabaseAPI.session().then(function (s) { return !!s; });
    },

    changerMotDePasse: function (motDePasse) {
      return sb().then(function (c) { return c.auth.updateUser({ password: motDePasse }); })
        .then(function (r) { if (r.error) throw erreurSupabase(r.error); return true; });
    },

    modifierProfil: function (champs) {
      return sb().then(function (c) {
        return c.auth.getUser().then(function (u) {
          if (!u.data || !u.data.user) throw Erreur('non-autorise');
          return c.from('clients').update(choisir(champs, CHAMPS_PROFIL))
            .eq('id', u.data.user.id).select('*').single().then(resultat);
        });
      });
    },

    mesColis: function () {
      return sb().then(function (c) {
        return c.from('colis').select('*, colis_historique(statut,lieu,note,cree_le)')
          .order('maj_le', { ascending: false }).then(resultat);
      }).then(function (lignes) { return (lignes || []).map(trierHistorique); });
    },

    mesFactures: function () {
      return sb().then(function (c) {
        // Le numéro du colis est joint ici : le client doit voir à quoi se
        // rapporte chaque facture, sans avoir à croiser deux écrans.
        return c.from('factures').select('*, colis:colis_id(numero)')
          .order('cree_le', { ascending: false }).then(resultat);
      }).then(function (l) {
        return (l || []).map(function (f) {
          f.numero_colis = f.colis ? f.colis.numero : null;
          delete f.colis;
          return f;
        });
      });
    },

    /* Le serveur pousse les changements : le tableau de bord du client se met
       à jour sans rien demander, et sans jamais voir les lignes des autres
       (les règles de sécurité s'appliquent aussi au temps réel). */
    surveiller: function (rappel) {
      var canal = null, vivant = true;
      sb().then(function (c) {
        if (!vivant) return;
        canal = c.channel('ses-' + Math.random().toString(36).slice(2))
          .on('postgres_changes', { event: '*', schema: 'public', table: 'colis' }, function () { rappel('colis'); })
          .on('postgres_changes', { event: '*', schema: 'public', table: 'colis_historique' }, function () { rappel('colis'); })
          .on('postgres_changes', { event: '*', schema: 'public', table: 'factures' }, function () { rappel('factures'); })
          .subscribe();
      }).catch(function () {});
      return function () {
        vivant = false;
        if (canal) sb().then(function (c) { c.removeChannel(canal); }).catch(function () {});
      };
    },

    /* Le jeton du QR (&j=…) est transmis pour vérification : un lien falsifié
       ne résout plus. Sans jeton (saisie à la main), la recherche reste
       publique — statut et étapes seulement, comme documenté. */
    suivre: function (numero, jeton) {
      var args = { p_numero: String(numero || '').trim() };
      if (jeton) args.p_jeton = String(jeton).trim();
      return sb().then(function (c) { return c.rpc('suivre_colis', args); })
        .then(resultat)
        .catch(function (e) {
          /* Base pas encore migrée (RPC à un seul paramètre) : on rejoue sans
             jeton, en recherche publique. Le temps de passer la migration
             supabase-maj-jeton.sql — ensuite ce repli ne sert plus. */
          if (args.p_jeton && e && /suivre_colis/i.test(e.message || '')) {
            return sb().then(function (c) {
              return c.rpc('suivre_colis', { p_numero: args.p_numero });
            }).then(resultat);
          }
          throw e;
        });
    },

    /* ====================================================================
       Le portail client — tout ce que le CLIENT voit vient du noyau logistique.
       --------------------------------------------------------------------
       Chaque méthode appelle une fonction de la base (public.lg_*, voir
       outils/logistique/008-portail-client.sql). Aucune ne prend d'identité en
       paramètre : la base lit le compte connecté. Rien n'est calculé ici — ni
       statut, ni solde, ni étape — et un identifiant qui n'est pas au client
       répond comme un identifiant qui n'existe pas.

       Le portail ne lit le noyau que si l'interrupteur « portailNoyau » de
       config.js est allumé ET que la base répond ET que le noyau est à jour
       pour ce client (« in_sync ») : sinon l'espace client reste celui d'avant,
       qui lit l'ancien schéma. Allumer l'interrupteur avant d'avoir passé les
       migrations ne casse donc rien.
       ==================================================================== */
    portail: (function () {
      function appeler(nom, args) {
        return sb().then(function (c) { return c.rpc(nom, args || {}); }).then(resultat);
      }
      /* « undefined » n'est pas envoyé : la base applique alors la valeur par défaut de son paramètre. */
      function arguments_(o) {
        var s = {};
        Object.keys(o).forEach(function (k) { if (o[k] !== undefined) s[k] = o[k]; });
        return s;
      }
      function d(o, cle) { return o && o[cle] !== undefined && o[cle] !== '' ? o[cle] : undefined; }

      return {
        disponible: function () {
          if (!CFG.portailNoyau) return Promise.resolve({ actif: false, raison: 'drapeau' });
          return appeler('lg_my_dashboard').then(function (t) {
            if (!t || !t.linked) return { actif: false, raison: 'non-relie' };
            if (!t.in_sync) return { actif: false, raison: 'en-retard' };
            return { actif: true, tableau: t };
          }, function (e) {
            // Au moindre doute, l'espace d'avant : il fonctionne sans le noyau.
            return { actif: false, raison: e && e.code === 'noyau-absent' ? 'absent' : 'erreur' };
          });
        },
        tableau: function () { return appeler('lg_my_dashboard'); },
        colis: function (o) {
          o = o || {};
          return appeler('lg_my_parcels', arguments_({ p_stage: d(o, 'etape'), p_search: d(o, 'recherche'), p_limit: nombre(o.limite, 50), p_offset: nombre(o.decalage, 0) }));
        },
        colisDetail: function (numero) { return appeler('lg_my_parcel', { p_tracking: String(numero || '') }); },
        expeditions: function () { return appeler('lg_my_shipments'); },
        consolidations: function () { return appeler('lg_my_consolidations'); },
        factures: function () { return appeler('lg_my_invoices'); },
        solde: function () { return appeler('lg_my_balance'); },
        paiements: function () { return appeler('lg_my_payments'); },
        documents: function () { return appeler('lg_my_documents'); },
        adresses: function () { return appeler('lg_my_addresses'); },
        enregistrerAdresse: function (a) {
          return appeler('lg_save_address', arguments_({
            p_id: d(a, 'id'), p_country: a.pays, p_address: a.adresse, p_label: a.etiquette, p_recipient_name: a.destinataire, p_phone: a.telephone,
            p_region: a.region, p_city: a.ville, p_instructions: a.consignes, p_default: a.parDefaut === undefined ? undefined : !!a.parDefaut
          }));
        },
        supprimerAdresse: function (id) { return appeler('lg_delete_address', { p_id: id }); },
        enlevements: function () { return appeler('lg_my_pickups'); },
        demanderEnlevement: function (e) {
          return appeler('lg_request_pickup', arguments_({
            p_preferred_date: e.date, p_parcels_expected: e.colis, p_address_id: d(e, 'adresseId'), p_address: d(e, 'adresse'), p_city: d(e, 'ville'), p_country: d(e, 'pays'),
            p_window: e.creneau, p_notes: d(e, 'notes'), p_contact_name: d(e, 'contact'), p_contact_phone: d(e, 'telephone'), p_idempotency_key: e.cle
          }));
        },
        annulerEnlevement: function (id) { return appeler('lg_cancel_pickup_request', { p_id: id }); },
        livraisons: function () { return appeler('lg_my_deliveries'); },
        demanderLivraison: function (l) {
          return appeler('lg_request_delivery', arguments_({
            p_tracking_numbers: l.colis, p_preferred_date: l.date, p_address_id: d(l, 'adresseId'), p_address: d(l, 'adresse'), p_city: d(l, 'ville'), p_country: d(l, 'pays'),
            p_window: l.creneau, p_notes: d(l, 'notes'), p_contact_name: d(l, 'contact'), p_contact_phone: d(l, 'telephone'), p_idempotency_key: l.cle
          }));
        },
        annulerLivraison: function (id) { return appeler('lg_cancel_delivery_request', { p_id: id }); },
        notifications: function (o) {
          o = o || {};
          return appeler('lg_my_notifications', arguments_({ p_unread_only: !!o.nonLuesSeulement, p_limit: nombre(o.limite, 50) }));
        },
        lireNotifications: function (ids) { return appeler('lg_mark_notifications_read', arguments_({ p_ids: ids && ids.length ? ids : undefined })); },
        tickets: function () { return appeler('lg_my_tickets'); },
        ticket: function (id) { return appeler('lg_my_ticket', { p_id: id }); },
        ouvrirTicket: function (t) {
          return appeler('lg_open_ticket', arguments_({ p_subject: t.sujet, p_category: t.categorie, p_body: t.message, p_tracking: d(t, 'colis'), p_invoice_number: d(t, 'facture'), p_idempotency_key: t.cle }));
        },
        repondreTicket: function (id, message) { return appeler('lg_reply_ticket', { p_id: id, p_body: message }); },
        fermerTicket: function (id) { return appeler('lg_close_my_ticket', { p_id: id }); }
      };
    })(),

    /* ====================================================================
       Le centre de commande de l'équipe — tout chiffre vient de la base.
       --------------------------------------------------------------------
       Chaque méthode appelle une fonction de la base (public.lg_cc_*). Aucune ne
       prend d'identité en paramètre : la base lit le compte connecté et contrôle
       ses droits. Rien n'est calculé ici — ni total, ni indicateur, ni retard.

       EXCEPTION ASSUMÉE à la règle « toute méthode existe dans les deux
       implémentations » (la même que pour admin.dashboard*) : le mode démo n'a
       PAS de centre de commande. Ses chiffres ne montrent que des données
       réelles ; en inventer pour la démonstration serait trompeur. Les trois
       implémentations ont pourtant les mêmes noms de méthodes, et celles de la
       démonstration répondent « fermé » (voir centre-contrat.cjs).

       Le centre ne s'ouvre que si l'interrupteur « centreNoyau » de config.js est
       allumé ET que la base répond ET que le compte a au moins un droit de
       lecture. Au moindre doute, le tableau de bord d'avant reste seul.
       ==================================================================== */
    centre: (function () {
      function appeler(nom, args) {
        return sb().then(function (c) { return c.rpc(nom, args || {}); }).then(resultat);
      }
      /* Les filtres de l'écran → ceux de la base, sans les vides. */
      function filtresBase(f) {
        var sortie = {};
        Object.keys(FILTRES_CENTRE).forEach(function (cle) {
          var v = f && f[cle];
          if (v !== undefined && v !== null && String(v).trim() !== '') sortie[FILTRES_CENTRE[cle]] = String(v).trim();
        });
        return sortie;
      }
      function avecFiltres(f, o) {
        var a = { p_filters: filtresBase(f) };
        if (o && o.limite !== undefined) a.p_limit = nombre(o.limite, 50);
        if (o && o.decalage !== undefined) a.p_offset = nombre(o.decalage, 0);
        return a;
      }

      return {
        disponible: function () {
          if (!CFG.centreNoyau) return Promise.resolve({ actif: false, raison: 'drapeau' });
          return appeler('lg_cc_access').then(function (a) { return { actif: true, acces: a }; }, function (e) {
            // Au moindre doute, le tableau de bord d'avant : il fonctionne sans le noyau.
            return { actif: false, raison: e && e.code === 'noyau-absent' ? 'absent' : (e && e.code === 'non-autorise' ? 'refuse' : 'erreur') };
          });
        },
        acces: function () { return appeler('lg_cc_access'); },
        indicateurs: function (f) { return appeler('lg_cc_kpis', { p_filters: filtresBase(f) }); },
        aTraiter: function () { return appeler('lg_cc_attention'); },
        liste: function (vue, f, o) {
          if (!VUES_CENTRE[vue]) return Promise.reject(Erreur('donnee-invalide', vue));
          return appeler(VUES_CENTRE[vue], avecFiltres(f, o || {}));
        },
        entrepot: function (f) { return appeler('lg_cc_warehouse', { p_filters: filtresBase(f) }); },
        colisDetail: function (numero) { return appeler('lg_cc_parcel', { p_tracking: String(numero || '') }); },
        ticket: function (id) { return appeler('lg_cc_ticket', { p_id: id }); },
        reglages: function () { return appeler('lg_cc_settings'); },
        traiterEnlevement: function (id, o) {
          o = o || {};
          var a = { p_id: id, p_approve: !!o.approuver };
          if (o.message) a.p_message = o.message;
          if (o.date) a.p_date = o.date;
          return appeler('lg_cc_review_pickup', a);
        },
        traiterLivraison: function (id, o) {
          o = o || {};
          var a = { p_id: id, p_approve: !!o.approuver };
          if (o.message) a.p_message = o.message;
          if (o.hub) a.p_hub_branch = o.hub;
          if (o.date) a.p_date = o.date;
          return appeler('lg_cc_review_delivery', a);
        },
        repondreTicket: function (id, message) { return appeler('lg_cc_reply_ticket', { p_id: id, p_body: message }); },
        fermerTicket: function (id) { return appeler('lg_cc_close_ticket', { p_id: id }); }
      };
    })(),

    /* ====================================================================
       Poste de scan du bureau
       --------------------------------------------------------------------
       La base décide de tout : le profil (entrepôts du compte), le verdict du
       scan, l'état du colis. Le navigateur n'envoie qu'un texte lu, l'intention,
       l'entrepôt, le genre de lecteur et une clé d'idempotence : la même lecture
       renvoyée après une coupure n'est pas comptée deux fois.
       ==================================================================== */
    poste: {
      profil: function () { return sb().then(function (c) { return c.rpc('lg_my_staff_profile', {}); }).then(resultat); },
      scanner: function (l) {
        l = l || {};
        if (INTENTIONS_POSTE.indexOf(l.intention) < 0 || !l.entrepot || !l.cle) return Promise.reject(Erreur('donnee-invalide'));
        return sb().then(function (c) {
          return c.rpc('lg_scan_parcel', {
            p_code: String(l.code || ''), p_purpose: l.intention, p_warehouse_id: l.entrepot,
            p_code_kind: ['barcode', 'qr', 'manual'].indexOf(l.genre) >= 0 ? l.genre : 'unknown',
            p_idempotency_key: String(l.cle), p_metadata: { source: 'desktop', recorded_at: l.horodatage || new Date().toISOString() }
          });
        }).then(resultat);
      }
    },

    /* ====================================================================
       Analytique et rapports
       --------------------------------------------------------------------
       Tous les chiffres, totaux et rapports (taux, délais) viennent de la base ;
       le navigateur ne fait qu'afficher. Chaque rapport dit de quelles
       exécutions il vient, et quels jours n'ont jamais été calculés.
       ==================================================================== */
    analytique: (function () {
      function appeler(nom, args) { return sb().then(function (c) { return c.rpc(nom, args || {}); }).then(resultat); }
      function jour(d) { return /^\d{4}-\d{2}-\d{2}$/.test(String(d || '')) ? String(d) : null; }
      function periode(du, au) { return jour(du) && jour(au) ? null : Promise.reject(Erreur('donnee-invalide')); }
      return {
        rapport: function (grain, du, au) {
          if (GRAINS_ANALYTIQUE.indexOf(grain) < 0) return Promise.reject(Erreur('donnee-invalide'));
          return periode(du, au) || appeler('lg_an_report', { p_grain: grain, p_from: du, p_to: au });
        },
        indicateurs: function (du, au) { return periode(du, au) || appeler('lg_an_kpis', { p_from: du, p_to: au }); },
        executions: function (limite) { return appeler('lg_an_runs', { p_limit: nombre(limite, 30) }); },
        recalculer: function (du, au) { return periode(du, au) || appeler('lg_an_refresh', { p_from: du, p_to: au }); },
        verifier: function (id) {
          var n = Number(id);
          if (!(n > 0) || Math.floor(n) !== n) return Promise.reject(Erreur('donnee-invalide'));
          return appeler('lg_an_verify', { p_run_id: n });
        }
      };
    })(),

    /* ====================================================================
       Exploitation : santé, état détaillé, erreurs des navigateurs
       --------------------------------------------------------------------
       « signalerErreur » ne lève jamais d'erreur : un signalement raté ne doit
       pas en provoquer un autre. La base nettoie et plafonne ce qu'elle reçoit.
       ==================================================================== */
    exploitation: {
      sante: function () { return sb().then(function (c) { return c.rpc('ses_health', {}); }).then(resultat); },
      etat: function () { return sb().then(function (c) { return c.rpc('lg_ops_status', {}); }).then(resultat); },
      signalerErreur: function (o) {
        o = o || {};
        return sb().then(function (c) {
          return c.rpc('lg_report_client_error', { p_page: String(o.page || '').slice(0, 200), p_message: String(o.message || '').slice(0, 600),
                                                   p_source: String(o.source || '').slice(0, 200), p_request_id: String(o.requete || '').slice(0, 40) });
        }).then(function (r) { return !r.error; }, function () { return false; });
      }
    },

    /* ====================================================================
       Notifications et temps réel
       --------------------------------------------------------------------
       « surveiller » écoute les insertions de public.ses_signal : un signal ne
       porte AUCUNE donnée, seulement le domaine qui a changé ; la base ne laisse
       lire à chacun que les siens (un client : les siens ; l'équipe : ceux de
       l'équipe). L'écran relit alors par les fonctions qui contrôlent les droits.
       ==================================================================== */
    notifications: {
      preferences: function () { return sb().then(function (c) { return c.rpc('lg_my_notification_prefs', {}); }).then(resultat); },
      reglerPreference: function (canal, actif) {
        return sb().then(function (c) { return c.rpc('lg_set_notification_pref', { p_channel: String(canal || ''), p_enabled: !!actif }); }).then(resultat);
      },
      sante: function () { return sb().then(function (c) { return c.rpc('lg_cc_notification_health', {}); }).then(resultat); },
      surveiller: function (audience, rappel) {
        var canal = null, vivant = true;
        sb().then(function (c) {
          if (!vivant) return;
          canal = c.channel('ses-signal-' + Math.random().toString(36).slice(2))
            .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'ses_signal', filter: 'audience=eq.' + (audience === 'staff' ? 'staff' : 'customer') },
              function (m) { rappel(m && m.new && m.new.topic ? String(m.new.topic) : ''); })
            .subscribe();
        }).catch(function () {});
        return function () {
          vivant = false;
          if (canal) sb().then(function (c) { c.removeChannel(canal); }).catch(function () {});
        };
      }
    },

    admin: {
      dashboard: function (domaine, filtres) {
        if (['colis', 'clients'].indexOf(domaine) < 0) return Promise.reject(Erreur('non-autorise'));
        var f = filtres || {};
        var args = { p_periode: f.periode || 'mois', p_date: f.date || null,
          p_debut: f.debut || null, p_fin: f.fin || null };
        if (domaine === 'colis') {
          args.p_service = f.service || null; args.p_pays = f.pays || null; args.p_statut = f.statut || null;
        }
        return sb().then(function (c) { return c.rpc('dashboard_' + domaine + '_ses', args); })
          .then(function (r) {
            if (r.error && r.error.code === '22023') throw Erreur('periode-invalide');
            if (r.error && ['PGRST202', '42883'].indexOf(r.error.code) >= 0) throw Erreur('base-a-mettre-a-jour');
            return resultat(r);
          });
      },

      dashboardRecents: function (o) {
        o = o || {};
        return sb().then(function (c) {
          var q = c.from('colis').select('id,numero,cree_le,expediteur,destinataire,pays_destination,ville_destination,poids_lb,service,statut', { count: 'exact' });
          if (o.statut) q = q.eq('statut', o.statut);
          if (o.service) q = q.eq('service', o.service);
          if (o.pays) q = q.eq('pays_destination', o.pays);
          var t = nettoyer(o.recherche || '');
          if (t) q = q.or('numero.ilike.%' + t + '%,destinataire.ilike.%' + t + '%,expediteur.ilike.%' + t + '%');
          var tri = ['cree_le', 'numero', 'poids_lb'].indexOf(o.tri) >= 0 ? o.tri : 'cree_le';
          var page = Math.max(0, Math.floor(Number(o.page) || 0));
          return q.order(tri, { ascending: o.asc === true, nullsFirst: false })
            .order('id', { ascending: o.asc === true }).range(page * 20, page * 20 + 19);
        }).then(function (r) {
          if (r.error) throw erreurSupabase(r.error);
          return { lignes: r.data || [], total: r.count || 0 };
        });
      },

      dashboardActivite: function () {
        return sb().then(function (c) {
          return c.from('colis_historique').select('id,colis_id,statut,lieu,cree_le,auteur,colis:colis_id(numero)')
            .order('cree_le', { ascending: false }).order('id', { ascending: false }).limit(8);
        }).then(resultat);
      },

      statistiques: function () {
        return sb().then(function (c) { return c.rpc('statistiques_ses'); }).then(resultat);
      },

      colis: function (o) {
        o = o || {};
        return sb().then(function (c) {
          var q = c.from('colis_details').select('*', { count: 'exact' });
          if (o.statut) q = q.eq('statut', o.statut);
          if (o.client_id) q = q.eq('client_id', o.client_id);
          if (o.id) q = q.eq('id', o.id);
          if (o.recherche) {
            var t = nettoyer(o.recherche);
            if (t) {
              q = q.or(['numero.ilike.%' + t + '%', 'description.ilike.%' + t + '%',
                        'destinataire.ilike.%' + t + '%', 'code_client.ilike.%' + t + '%',
                        'nom_client.ilike.%' + t + '%'].join(','));
            }
          }
          var parPage = o.parPage || 25, p = o.page || 0;
          return q.order('maj_le', { ascending: false }).range(p * parPage, p * parPage + parPage - 1);
        }).then(function (r) {
          if (r.error) throw erreurSupabase(r.error);
          return { lignes: r.data || [], total: r.count || 0 };
        });
      },

      colisParId: function (id) {
        return sb().then(function (c) {
          return c.from('colis_details').select('*').eq('id', id).maybeSingle().then(resultat);
        });
      },

      historique: function (id) {
        return sb().then(function (c) {
          return c.from('colis_historique').select('*').eq('colis_id', id)
            .order('cree_le', { ascending: true }).then(resultat);
        }).then(function (l) { return l || []; });
      },

      creerColis: function (d) {
        return sb().then(function (c) {
          return c.from('colis').insert(normaliserNombres(choisir(d, CHAMPS_COLIS)))
            .select('*').single().then(resultat);
        });
      },

      modifierColis: function (id, champs) {
        return sb().then(function (c) {
          return c.from('colis').update(normaliserNombres(choisir(champs, CHAMPS_COLIS))).eq('id', id)
            .select('*').single().then(resultat);
        });
      },

      changerStatut: function (ids, statut, lieu, note) {
        if (STATUTS.indexOf(statut) < 0) return Promise.reject(Erreur('statut-inconnu'));
        return sb().then(function (c) {
          var champs = { statut: statut };
          if (lieu !== undefined) champs.lieu = texteCourt(lieu, 120);
          if (note !== undefined) champs.note = texteCourt(note, 400);
          return c.from('colis').update(champs).in('id', [].concat(ids)).select('id').then(resultat);
        });
      },

      supprimerColis: function (id) {
        return sb().then(function (c) { return c.from('colis').delete().eq('id', id).then(resultat); })
          .then(function () { return true; });
      },

      clients: function (o) {
        o = o || {};
        return sb().then(function (c) {
          var q = c.from('clients').select('*', { count: 'exact' });
          // « equipe » : les trois rôles de l'équipe d'un coup (onglet « Équipe »).
          if (o.role === 'equipe') q = q.in('role', ROLES_EQUIPE);
          else if (o.role) q = q.eq('role', o.role);
          if (o.recherche) {
            var t = nettoyer(o.recherche);
            if (t) q = q.or(['code.ilike.%' + t + '%', 'nom_complet.ilike.%' + t + '%',
                             'email.ilike.%' + t + '%', 'telephone.ilike.%' + t + '%'].join(','));
          }
          var parPage = o.parPage || 25, p = o.page || 0;
          return q.order('cree_le', { ascending: false }).range(p * parPage, p * parPage + parPage - 1);
        }).then(function (r) {
          if (r.error) throw erreurSupabase(r.error);
          return { lignes: r.data || [], total: r.count || 0 };
        });
      },

      chercherClient: function (code) {
        var c2 = normaliserCode(code);
        if (!c2) return Promise.resolve(null);
        return sb().then(function (c) {
          // Un client seulement : un compte d'équipe ne reçoit pas de colis.
          return c.from('clients').select('*').eq('code', c2).eq('role', 'client').maybeSingle().then(resultat);
        });
      },

      definirRole: function (id, role, droits) {
        if (ROLES.indexOf(role) < 0) return Promise.reject(Erreur('role-inconnu'));
        return sb().then(function (c) {
          return c.rpc('definir_role', {
            p_id: id, p_role: role,
            p_droits: (droits || []).filter(function (d) { return DROITS.indexOf(d) >= 0; })
          }).then(resultat);
        });
      },

      /* Ce qu'ajoute supabase-maj.sql est-il là ? Les colonnes du colis : sans
         elles, enregistrer un colis échoue, et le message par défaut ne dit pas
         pourquoi. Et la fonction du rôle « gérant » : sans elle, nommer un
         gérant échouerait. Deux requêtes minuscules, une fois par ouverture du
         tableau de bord. */
      baseAJour: function () {
        return sb().then(function (c) {
          return Promise.all([
            c.from('colis').select('tarif_lb,telephone_destinataire').limit(1),
            c.rpc('est_direction')
          ]);
        }).then(function (r) {
          var colonnes = !(r[0].error && String(r[0].error.code) === '42703');
          // PGRST202 : fonction introuvable pour PostgREST ; 42883 : pour PostgreSQL.
          var roles = !(r[1].error && ['PGRST202', '42883'].indexOf(String(r[1].error.code)) >= 0);
          return colonnes && roles;
        }).catch(function () {
          return true;   // panne réseau : inutile de crier à la mise à jour
        });
      },

      resumeClients: function (ids) {
        if (!ids || !ids.length) return Promise.resolve({});
        return sb().then(function (c) {
          return Promise.all([
            c.from('colis_details').select('client_id,statut,poids_lb,maj_le').in('client_id', ids),
            c.from('factures_details').select('client_id,montant,montant_paye').in('client_id', ids)
          ]);
        }).then(function (r) {
          if (r[0].error) throw erreurSupabase(r[0].error);
          if (r[1].error) throw erreurSupabase(r[1].error);
          return resumerClients(r[0].data, r[1].data);
        });
      },

      factures: function (o) {
        o = o || {};
        return sb().then(function (c) {
          var q = c.from('factures_details').select('*', { count: 'exact' });
          if (o.colis_id) q = q.eq('colis_id', o.colis_id);
          if (o.statut) q = q.eq('statut', o.statut);
          if (o.client_id) q = q.eq('client_id', o.client_id);
          if (o.recherche) {
            var t = nettoyer(o.recherche);
            if (t) q = q.or(['numero.ilike.%' + t + '%', 'code_client.ilike.%' + t + '%',
                             'nom_client.ilike.%' + t + '%'].join(','));
          }
          var parPage = o.parPage || 25, p = o.page || 0;
          return q.order('cree_le', { ascending: false }).range(p * parPage, p * parPage + parPage - 1);
        }).then(function (r) {
          if (r.error) throw erreurSupabase(r.error);
          return { lignes: r.data || [], total: r.count || 0 };
        });
      },

      creerFacture: function (d) {
        return sb().then(function (c) {
          return c.from('factures').insert(normaliserNombres(choisir(d, CHAMPS_FACTURE)))
            .select('*').single().then(resultat);
        });
      },

      modifierFacture: function (id, champs) {
        return sb().then(function (c) {
          return c.from('factures').update(normaliserNombres(choisir(champs, CHAMPS_FACTURE))).eq('id', id)
            .select('*').single().then(resultat);
        });
      },

      supprimerFacture: function (id) {
        return sb().then(function (c) { return c.from('factures').delete().eq('id', id).then(resultat); })
          .then(function () { return true; });
      }
    }
  };

  /* ======================================================================
     Démonstration — les données restent dans ce navigateur
     ====================================================================== */
  var CLE_DONNEES = 'ses-donnees-v1';
  var CLE_SESSION = 'ses-session';
  var ADMIN_DEMO = { email: 'admin@speedexpress.demo', motDePasse: 'speed2026' };
  var abonnes = [];

  var memoire = {};
  var stockageBloque = false;
  function stockage(action, cle, valeur) {
    if (!stockageBloque) {
      try {
        if (action === 'lire') return localStorage.getItem(cle);
        if (action === 'ecrire') localStorage.setItem(cle, valeur);
        if (action === 'effacer') localStorage.removeItem(cle);
        return null;
      } catch (e) { stockageBloque = true; }
    }
    if (action === 'lire') return Object.prototype.hasOwnProperty.call(memoire, cle) ? memoire[cle] : null;
    if (action === 'ecrire') memoire[cle] = String(valeur);
    if (action === 'effacer') delete memoire[cle];
    return null;
  }

  function identifiant() { return 'd' + Date.now().toString(36) + alea(6).toLowerCase(); }
  /* Le numéro d'un colis, comme la base (preparer_colis) : « SES- » et dix chiffres au hasard, le premier
     jamais nul, jamais deux fois le même. Les colis de démonstration d'avant gardent leur ancien numéro. */
  function numeroColis(d) {
    var n;
    do { n = 'SES-' + (1000000000 + Math.floor(Math.random() * 9000000000)); }
    while (d.colis.some(function (c) { return c.numero === n; }));
    return n;
  }
  function maintenant() { return new Date().toISOString(); }

  function vides() {
    return { v: 1, seqColis: 10000, seqFacture: 0, comptes: [], colis: [], historique: [], factures: [] };
  }

  function lireDonnees() {
    try {
      var d = JSON.parse(stockage('lire', CLE_DONNEES));
      if (d && d.v === 1) return d;
    } catch (e) { /* données illisibles : on repart de zéro */ }
    return vides();
  }

  function ecrireDonnees(d) {
    stockage('ecrire', CLE_DONNEES, JSON.stringify(d));
    prevenir('colis');
  }

  function prevenir(quoi) { abonnes.slice().forEach(function (a) { a(quoi); }); }

  window.addEventListener('storage', function (e) {
    if (e.key === CLE_DONNEES) prevenir('colis');
  });

  /* Le compte d'administration d'essai est créé au premier usage : son mot de
     passe passe par la même dérivation que les autres.

     « preparer » ne fait que cette mise en place, une seule fois ; les données
     elles-mêmes sont relues à chaque appel. Sans cela, une page gardait en
     mémoire l'état du démarrage : ce qu'une autre fenêtre du navigateur
     enregistrait n'arrivait jamais jusqu'à elle, et le premier enregistrement
     venu l'aurait écrasé. */
  var pretInit = null;
  function preparer() {
    if (!pretInit) {
      pretInit = new Promise(function (ok) {
        var d = lireDonnees();
        if (d.comptes.length) return ok(true);
        Empreinte.creer(ADMIN_DEMO.motDePasse).then(function (mdp) {
          d.comptes.push({
            id: 'admin-demo', email: ADMIN_DEMO.email, mdp: mdp, role: 'admin', droits: DROITS.slice(),
            code: null, nom_complet: 'Équipe Speed Express Shipping',
            pays: 'République dominicaine', region: 'Santo Domingo', ville: 'Santo Domingo Este',
            adresse: 'C. Fausto Cejas Rodriguez #89 k12, Las Américas',
            telephone: '+1 829 265-3727', langue: 'fr', cree_le: maintenant()
          });
          stockage('ecrire', CLE_DONNEES, JSON.stringify(d));
          ok(true);
        });
      });
    }
    return pretInit.then(lireDonnees);
  }

  function nouveauCode(comptes) {
    var code, essais = 0;
    do {
      code = 'SES-' + (10000 + Math.floor(Math.random() * 90000));
      essais++;
      if (essais > 400) throw Erreur('plus-de-code');
    } while (comptes.some(function (c) { return c.code === code; }));
    return code;
  }

  function sansMdp(compte) {
    if (!compte) return null;
    var p = {};
    Object.keys(compte).forEach(function (k) { if (k !== 'mdp') p[k] = compte[k]; });
    return p;
  }

  function compteConnecte(d) {
    var id = stockage('lire', CLE_SESSION);
    if (!id) return null;
    for (var i = 0; i < d.comptes.length; i++) if (d.comptes[i].id === id) return d.comptes[i];
    return null;
  }

  function trouverCompte(d, email) {
    email = String(email || '').trim().toLowerCase();
    for (var i = 0; i < d.comptes.length; i++) if (d.comptes[i].email === email) return d.comptes[i];
    return null;
  }

  function avecHistorique(d, c) {
    var x = JSON.parse(JSON.stringify(c));
    x.historique = d.historique.filter(function (h) { return h.colis_id === c.id; });
    return trierHistorique(x);
  }

  function detailsColis(d, c) {
    var x = JSON.parse(JSON.stringify(c)), cl = null;
    for (var i = 0; i < d.comptes.length; i++) if (d.comptes[i].id === c.client_id) cl = d.comptes[i];
    x.code_client = cl ? cl.code : null;
    x.nom_client = cl ? cl.nom_complet : null;
    x.telephone_client = cl ? cl.telephone : null;
    x.email_client = cl ? cl.email : null;
    x.ville_client = cl ? cl.ville : null;
    x.pays_client = cl ? cl.pays : null;
    return x;
  }

  function historiser(d, c, auteur, date) {
    d.historique.push({
      id: d.historique.length + 1, colis_id: c.id, statut: c.statut,
      lieu: c.lieu || '', note: c.note || '', auteur: auteur || '', cree_le: date || maintenant()
    });
  }

  /* Les lignes d'une facture sont un instantané : elles gardent le poids, le
     tarif et le montant tels qu'ils étaient au moment de la facturation. Les
     factures écrites avant ce système n'ont qu'un « libelle » : il devient la
     description, et leur montant reste celui qu'elles portaient. */
  function nettoyerLignes(lignes) {
    return (lignes || []).map(function (l) {
      return {
        colis_id: l.colis_id || null,
        numero: texteCourt(l.numero, 40),
        description: texteCourt(l.description === undefined ? l.libelle : l.description, 200),
        quantite: Number(l.quantite || 1),
        poids_lb: Number(l.poids_lb || 0),
        tarif_lb: Number(l.tarif_lb || 0),
        montant: Number(l.montant || 0)
      };
    });
  }

  /* Ce que chaque client représente en ce moment : colis en cours, poids,
     montants dus et réglés. Le calcul est écrit une fois et sert aux deux
     modes — les deux tableaux de bord affichent donc les mêmes chiffres. */
  function resumerClients(colis, factures) {
    var r = {};
    function pour(id) {
      if (!r[id]) {
        r[id] = { colis: 0, en_cours: 0, poids: 0, statuts: {},
                  total: 0, paye: 0, balance: 0, maj_le: null };
      }
      return r[id];
    }
    (colis || []).forEach(function (c) {
      if (!c.client_id) return;
      var x = pour(c.client_id);
      x.colis += 1;
      if (c.statut !== 'livre') x.en_cours += 1;
      x.poids += Number(c.poids_lb || 0);
      x.statuts[c.statut] = (x.statuts[c.statut] || 0) + 1;
      if (!x.maj_le || new Date(c.maj_le) > new Date(x.maj_le)) x.maj_le = c.maj_le;
    });
    (factures || []).forEach(function (f) {
      if (!f.client_id) return;
      var x = pour(f.client_id);
      x.total += Number(f.montant || 0);
      x.paye += Number(f.montant_paye || 0);
    });
    Object.keys(r).forEach(function (id) {
      var x = r[id];
      x.poids = Math.round(x.poids * 100) / 100;
      x.total = Math.round(x.total * 100) / 100;
      x.paye = Math.round(x.paye * 100) / 100;
      x.balance = Math.round((x.total - x.paye) * 100) / 100;
    });
    return r;
  }

  function numeroFacture(d) {
    d.seqFacture += 1;
    return 'FAC-' + new Date().getFullYear() + '-' + String(d.seqFacture).padStart(4, '0');
  }

  /* La contrepartie, en mode démonstration, du déclencheur facturer_colis :
     à l'enregistrement, le colis reçoit sa facture ; ensuite, tant qu'aucun
     paiement n'est entré, la facture se met à jour avec lui. Un paiement la
     fige — c'est ce qui garantit qu'une facture ancienne ne bouge plus. */
  function facturerColis(d, c) {
    if (!c.client_id) return;
    var total = Math.round(Number(c.poids_lb || 0) * Number(c.tarif_lb || 0) * 100) / 100;
    var ligne = {
      colis_id: c.id, numero: c.numero, description: c.description || '',
      quantite: 1, poids_lb: Number(c.poids_lb || 0), tarif_lb: Number(c.tarif_lb || 0),
      montant: total
    };
    var f = d.factures.filter(function (x) { return x.colis_id === c.id; })[0];
    if (!f) {
      d.factures.push({
        id: identifiant(), numero: numeroFacture(d),
        client_id: c.client_id, colis_id: c.id,
        montant: total + FRAIS_SERVICE, frais_service: FRAIS_SERVICE, montant_paye: 0,
        devise: CFG.devise || 'USD', statut: 'impayee', note: '', lignes: [ligne],
        echeance_le: null, cree_le: maintenant(), payee_le: null
      });
      return;
    }
    if (f.statut === 'payee' || Number(f.montant_paye || 0) > 0) return;
    f.lignes = [ligne];
    f.client_id = c.client_id;
    f.montant = total + Number(f.frais_service || 0);
  }

  /* Le contrôle des droits, côté démonstration. En ligne, le même contrôle est
     refait par le serveur : c'est celui-là qui fait foi. */
  function exiger(d, droit) {
    var moi = compteConnecte(d);
    if (!moi || !peutFaire(moi, droit)) throw Erreur('non-autorise');
    return moi;
  }

  function contient(valeurs, texte) {
    texte = texte.toLowerCase();
    return valeurs.some(function (v) { return v && String(v).toLowerCase().indexOf(texte) >= 0; });
  }

  function page(lignes, o) {
    var parPage = o.parPage || 25, p = o.page || 0;
    return { lignes: lignes.slice(p * parPage, p * parPage + parPage), total: lignes.length };
  }

  /* Petit délai : les écrans de chargement se voient comme en ligne. */
  function plusTard(valeur) {
    return new Promise(function (ok) { setTimeout(function () { ok(valeur); }, 120 + Math.random() * 160); });
  }
  function echec(code) {
    return new Promise(function (ok, ko) { setTimeout(function () { ko(Erreur(code)); }, 160); });
  }

  var demoAPI = {
    identifiantsAdmin: ADMIN_DEMO,

    session: function () {
      return preparer().then(function (d) {
        var moi = compteConnecte(d);
        return moi ? { user: { id: moi.id, email: moi.email } } : null;
      });
    },

    profil: function () {
      return preparer().then(function (d) { return sansMdp(compteConnecte(d)); });
    },

    inscrire: function (entree) {
      return preparer().then(function (d) {
        if (String(entree.motDePasse || '').length < MDP_MINIMUM) throw Erreur('mot-de-passe-court');
        var email = texteCourt(entree.email, 160).toLowerCase();
        if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) throw Erreur('email-invalide');
        if (trouverCompte(d, email)) throw Erreur('email-existe');
        return Empreinte.creer(entree.motDePasse).then(function (mdp) {
          var compte = {
            id: identifiant(), email: email, mdp: mdp, role: 'client', droits: [],
            code: nouveauCode(d.comptes),
            nom_complet: texteCourt(entree.nom_complet, 120),
            pays: texteCourt(entree.pays, 60),
            region: texteCourt(entree.region, 80),
            ville: texteCourt(entree.ville, 80),
            adresse: texteCourt(entree.adresse, 200),
            telephone: texteCourt(entree.telephone, 40),
            langue: (document.documentElement.lang || 'fr').slice(0, 2),
            cree_le: maintenant()
          };
          d.comptes.push(compte);
          ecrireDonnees(d);
          stockage('ecrire', CLE_SESSION, compte.id);
          return plusTard({ confirmation: false, profil: sansMdp(compte) });
        });
      });
    },

    connecter: function (email, motDePasse) {
      return preparer().then(function (d) {
        var compte = trouverCompte(d, email);
        if (!compte) return echec('identifiants');
        return Empreinte.verifier(motDePasse, compte.mdp).then(function (ok) {
          if (!ok) return echec('identifiants');
          stockage('ecrire', CLE_SESSION, compte.id);
          return plusTard(sansMdp(compte));
        });
      });
    },

    deconnecter: function () {
      stockage('effacer', CLE_SESSION);
      return plusTard(true);
    },

    envoyerLienMotDePasse: function () { return echec('demo-sans-email'); },
    attendreRecuperation: function () { return Promise.resolve(false); },

    changerMotDePasse: function (motDePasse) {
      return preparer().then(function (d) {
        var moi = compteConnecte(d);
        if (!moi) throw Erreur('non-autorise');
        if (String(motDePasse || '').length < MDP_MINIMUM) throw Erreur('mot-de-passe-court');
        return Empreinte.creer(motDePasse).then(function (mdp) {
          moi.mdp = mdp;
          ecrireDonnees(d);
          return plusTard(true);
        });
      });
    },

    modifierProfil: function (champs) {
      return preparer().then(function (d) {
        var moi = compteConnecte(d);
        if (!moi) throw Erreur('non-autorise');
        var propres = choisir(champs, CHAMPS_PROFIL);
        Object.keys(propres).forEach(function (k) { moi[k] = texteCourt(propres[k], 200); });
        ecrireDonnees(d);
        return plusTard(sansMdp(moi));
      });
    },

    /* Un client ne reçoit que ses colis : le filtre est ici, comme les règles
       de sécurité le font côté serveur en ligne. */
    mesColis: function () {
      return preparer().then(function (d) {
        var moi = compteConnecte(d);
        if (!moi) throw Erreur('non-autorise');
        var miens = d.colis.filter(function (c) { return c.client_id === moi.id; });
        miens.sort(function (a, b) { return new Date(b.maj_le) - new Date(a.maj_le); });
        return plusTard(miens.map(function (c) { return avecHistorique(d, c); }));
      });
    },

    mesFactures: function () {
      return preparer().then(function (d) {
        var moi = compteConnecte(d);
        if (!moi) throw Erreur('non-autorise');
        var miennes = d.factures.filter(function (f) { return f.client_id === moi.id; })
          .map(function (f) {
            var x = JSON.parse(JSON.stringify(f));
            var co = d.colis.filter(function (c) { return c.id === f.colis_id; })[0];
            x.numero_colis = co ? co.numero : null;
            return x;
          });
        miennes.sort(function (a, b) { return new Date(b.cree_le) - new Date(a.cree_le); });
        return plusTard(miennes);
      });
    },

    surveiller: function (rappel) {
      abonnes.push(rappel);
      return function () {
        var i = abonnes.indexOf(rappel);
        if (i >= 0) abonnes.splice(i, 1);
      };
    },

    /* Suivi public : statut et étapes, sans nom, adresse ni note interne.
       Le jeton, quand il est fourni (&j=… du QR), doit correspondre. */
    suivre: function (numero, jeton) {
      return preparer().then(function (d) {
        var n = String(numero || '').trim().toUpperCase();
        if (n.length < 4) return plusTard(null);
        var trouve = null;
        d.colis.forEach(function (c) { if (c.numero === n) trouve = c; });
        if (!trouve) return plusTard(null);
        if (jeton && trouve.jeton !== String(jeton).trim()) return plusTard(null);
        return plusTard({
          numero: trouve.numero, statut: trouve.statut, service: trouve.service,
          pays_destination: trouve.pays_destination, maj_le: trouve.maj_le,
          historique: d.historique.filter(function (h) { return h.colis_id === trouve.id; })
            .map(function (h) { return { statut: h.statut, lieu: h.lieu, cree_le: h.cree_le }; })
            .sort(function (a, b) { return new Date(a.cree_le) - new Date(b.cree_le); })
        });
      });
    },

    /* ====================================================================
       Le portail client, en démonstration : mêmes méthodes, mêmes formes de
       réponse que la version en ligne (une clé de plus ou de moins est une
       erreur : voir outils/tests/portail-contrat.cjs).
       Les colis et les factures viennent des données de démonstration ; les
       adresses, demandes et tickets sont enregistrés pour de bon, dans ce
       navigateur. Il n'y a PAS de personnel pour traiter une demande ni
       répondre à un ticket : elles restent « en attente » — la démonstration
       n'invente rien d'autre. Expéditions, consolidations, notifications :
       vides, parce qu'aucun colis de démonstration ne voyage dans une vraie
       expédition.
       ==================================================================== */
    portail: (function () {
      var ETAPE_DE = { confirme: 'registered', expedie: 'in_transit', disponible: 'at_hub', livre: 'delivered', action: 'on_hold' };
      var STATUT_DE = { confirme: 'CREATED', expedie: 'IN_TRANSIT', disponible: 'AT_DESTINATION_HUB', livre: 'DELIVERED', action: 'ON_HOLD' };
      var SERVICE_DE = { aerien: 'air', maritime: 'sea', terrestre: 'ground' };
      var CRENEAUX = ['MORNING', 'AFTERNOON', 'ANY'];
      var CATEGORIES = ['PARCEL', 'INVOICE', 'PICKUP', 'DELIVERY', 'ACCOUNT', 'OTHER'];

      function contexte() {
        return preparer().then(function (d) {
          var moi = compteConnecte(d);
          if (!moi || ROLES_EQUIPE.indexOf(moi.role) >= 0) throw Erreur('non-autorise');
          if (!d.portail) d.portail = {};
          if (!d.portail[moi.id]) d.portail[moi.id] = { adresses: [], enlevements: [], livraisons: [], notifications: [], tickets: [], seq: 0 };
          return { d: d, moi: moi, p: d.portail[moi.id] };
        });
      }
      function refuse(message) { throw Erreur('donnee-invalide', message); }
      function aujourdhui(n) { return new Date(Date.now() + (n || 0) * 86400000).toISOString().slice(0, 10); }
      function numeroDe(c, prefixe) { c.p.seq += 1; return prefixe + '-' + new Date().getFullYear() + '-' + ('000000' + c.p.seq).slice(-6); }
      function copie(x) { return JSON.parse(JSON.stringify(x)); }
      function mesColis(c) { return c.d.colis.filter(function (x) { return x.client_id === c.moi.id; }); }
      function mesFactures(c) { return c.d.factures.filter(function (x) { return x.client_id === c.moi.id; }); }

      function carte(co) {
        return {
          tracking_number: co.numero, public_token: co.jeton || '', status: STATUT_DE[co.statut] || 'CREATED', stage: ETAPE_DE[co.statut] || 'registered',
          service_mode: SERVICE_DE[co.service] || 'air', destination_country: co.pays_destination, destination_city: co.ville_destination || '',
          description: co.description || '', sender_name: co.expediteur || '', recipient_name: co.destinataire || '', delivery_address: co.adresse_livraison || '',
          weight_lb: co.poids_lb === null || co.poids_lb === undefined ? null : Number(co.poids_lb), declared_value: co.valeur_declaree === null || co.valeur_declaree === undefined ? null : Number(co.valeur_declaree),
          place: co.lieu || null, created_at: co.cree_le, updated_at: co.maj_le
        };
      }
      function suivi(d, co) {
        return d.historique.filter(function (h) { return h.colis_id === co.id; })
          .sort(function (a, b) { return new Date(a.cree_le) - new Date(b.cree_le); })
          .map(function (h) {
            return { at: h.cree_le, event: 'ParcelStatusChanged', status: STATUT_DE[h.statut] || 'CREATED', stage: ETAPE_DE[h.statut] || 'registered', place: h.lieu || null, note: h.note || null };
          });
      }
      function statutFacture(f) { return f.statut === 'payee' ? 'PAID' : (Number(f.montant_paye || 0) > 0 ? 'PARTIALLY_PAID' : 'ISSUED'); }
      function factureNoyau(f) {
        var lignes = (f.lignes || []).map(function (l) {
          return { kind: 'FREIGHT', description: l.description || '', quantity: Number(l.quantite || 1), unit_price: l.tarif_lb === undefined ? null : Number(l.tarif_lb), amount: Number(l.montant || 0) };
        });
        if (Number(f.frais_service || 0) > 0) lignes.push({ kind: 'SERVICE_FEE', description: 'Frais de service', quantity: 1, unit_price: Number(f.frais_service), amount: Number(f.frais_service) });
        var total = Number(f.montant || 0), paye = Number(f.montant_paye || 0);
        return { number: f.numero, status: statutFacture(f), currency: f.devise || 'USD', total: total, paid: paye, credited: 0, refunded: 0, balance: total - paye,
                 issued_at: f.cree_le, due_date: f.echeance_le || null, items: lignes };
      }
      function ouvertes(c, type) { return c.p[type].filter(function (r) { return r.request_status === 'REQUESTED'; }); }

      function resoudreAdresse(c, e) {
        if (e.adresseId) {
          var a = c.p.adresses.filter(function (x) { return x.address_id === e.adresseId && x.active; })[0];
          if (!a) throw Erreur('introuvable', 'Adresse introuvable.');
          return { address_id: a.address_id, address: a.address, city: a.city, country: a.country };
        }
        if (!String(e.adresse || '').trim()) refuse('L\'adresse est obligatoire.');
        if (String(e.adresse).length > 200 || String(e.ville || '').length > 80) refuse('Une partie de l\'adresse est trop longue.');
        if (['HT', 'DO', 'US'].indexOf(e.pays) < 0) refuse('Pays inconnu (HT, DO ou US).');
        return { address_id: null, address: String(e.adresse).trim(), city: String(e.ville || '').trim(), country: e.pays };
      }
      function verifierDemande(e) {
        if (!e.date || e.date < aujourdhui(0) || e.date > aujourdhui(60)) refuse('La date souhaitée doit être comprise entre aujourd\'hui et dans 60 jours.');
        if (CRENEAUX.indexOf(e.creneau || 'ANY') < 0) refuse('Créneau inconnu.');
        if (String(e.notes || '').length > 500) refuse('Un texte est trop long.');
      }
      function etape(statut) { return statut === 'REQUESTED' ? 'requested' : (statut === 'CANCELLED' ? 'cancelled' : 'scheduled'); }
      function ligneEnlevement(r) {
        return { pickup_id: r.pickup_id, number: r.number, source: 'REQUEST', stage: etape(r.request_status), request_status: r.request_status, address: r.address, city: r.city, country: r.country,
                 date: r.date, window: r.window, parcels_expected: r.parcels_expected, notes: r.notes, message: null, created_at: r.created_at };
      }
      function ligneLivraison(r) {
        return { request_id: r.request_id, number: r.number, stage: etape(r.request_status), request_status: r.request_status, address: r.address, city: r.city, country: r.country,
                 date: r.date, window: r.window, notes: r.notes, message: null, created_at: r.created_at, parcels: r.parcels.slice() };
      }
      function resumeTicket(t) {
        var dernier = t.messages[t.messages.length - 1];
        return { ticket_id: t.ticket_id, number: t.number, subject: t.subject, category: t.category, status: t.status, created_at: t.created_at, updated_at: t.updated_at,
                 messages: t.messages.length, last_author: dernier ? dernier.author : null };
      }
      function trouver(liste, cle, id) {
        var r = liste.filter(function (x) { return x[cle] === id; })[0];
        if (!r) throw Erreur('introuvable');
        return r;
      }

      return {
        disponible: function () {
          if (!CFG.portailNoyau) return Promise.resolve({ actif: false, raison: 'drapeau' });
          return contexte().then(function () { return { actif: true, tableau: null }; }, function () { return { actif: false, raison: 'non-relie' }; });
        },
        tableau: function () {
          return contexte().then(function (c) {
            var mes = mesColis(c), par = {}, solde = {}, impayees = 0;
            mes.forEach(function (x) { var e = ETAPE_DE[x.statut] || 'registered'; par[e] = (par[e] || 0) + 1; });
            mesFactures(c).forEach(function (f) {
              var b = Number(f.montant || 0) - Number(f.montant_paye || 0);
              var dev = f.devise || 'USD';
              solde[dev] = (solde[dev] || 0) + b;
              if (b > 0) impayees += 1;
            });
            var evts = [];
            mes.forEach(function (x) { suivi(c.d, x).forEach(function (t) { evts.push({ tracking_number: x.numero, at: t.at, event: t.event, stage: t.stage }); }); });
            evts.sort(function (a, b) { return new Date(b.at) - new Date(a.at); });
            return plusTard({
              linked: true, in_sync: true, customer: { code: c.moi.code, full_name: c.moi.nom_complet, language: c.moi.langue || 'fr' },
              parcels: { total: mes.length, by_stage: par },
              invoices: { unpaid: impayees, overdue: 0, balances: Object.keys(solde).sort().map(function (k) { return { currency: k, balance: solde[k] }; }) },
              deliveries: { upcoming: [] },
              pickups: { open: ouvertes(c, 'enlevements').length },
              notifications: { unread: c.p.notifications.filter(function (n) { return !n.read_at; }).length },
              tickets: { open: c.p.tickets.filter(function (t) { return t.status !== 'CLOSED'; }).length },
              recent_events: evts.slice(0, 5)
            });
          });
        },
        colis: function (o) {
          o = o || {};
          return contexte().then(function (c) {
            var q = String(o.recherche || '').trim().toLowerCase();
            var lim = Math.min(Math.max(nombre(o.limite, 50), 1), 200), dec = Math.max(nombre(o.decalage, 0), 0);
            var m = mesColis(c).filter(function (x) {
              return !q || [x.numero, x.description, x.destinataire].some(function (v) { return v && String(v).toLowerCase().indexOf(q) >= 0; });
            });
            var par = {};
            m.forEach(function (x) { var e = ETAPE_DE[x.statut] || 'registered'; par[e] = (par[e] || 0) + 1; });
            var f = m.filter(function (x) { return !o.etape || ETAPE_DE[x.statut] === o.etape; });
            f.sort(function (a, b) { return new Date(b.maj_le) - new Date(a.maj_le) || (a.numero < b.numero ? -1 : 1); });
            return plusTard({ total: f.length, by_stage: par, items: f.slice(dec, dec + lim).map(carte) });
          });
        },
        colisDetail: function (numero) {
          return contexte().then(function (c) {
            var n = String(numero || '').trim().toUpperCase();
            var co = mesColis(c).filter(function (x) { return x.numero === n; })[0];
            if (!co) throw Erreur('introuvable', 'Colis introuvable.');
            var r = carte(co);
            r.timeline = suivi(c.d, co);
            r.shipment = null; r.consolidation = null; r.delivery = null;
            r.invoices = mesFactures(c).filter(function (f) { return f.colis_id === co.id; }).map(function (f) {
              return { number: f.numero, status: statutFacture(f), total: Number(f.montant || 0), currency: f.devise || 'USD' };
            });
            return plusTard(r);
          });
        },
        expeditions: function () { return contexte().then(function () { return plusTard([]); }); },
        consolidations: function () { return contexte().then(function () { return plusTard([]); }); },
        factures: function () { return contexte().then(function (c) { return plusTard(mesFactures(c).map(factureNoyau)); }); },
        solde: function () {
          return contexte().then(function (c) {
            var s = {};
            mesFactures(c).forEach(function (f) {
              var k = f.devise || 'USD';
              s[k] = s[k] || { currency: k, invoiced: 0, paid: 0, balance: 0 };
              s[k].invoiced += Number(f.montant || 0); s[k].paid += Number(f.montant_paye || 0); s[k].balance += Number(f.montant || 0) - Number(f.montant_paye || 0);
            });
            return plusTard(Object.keys(s).sort().map(function (k) { return s[k]; }));
          });
        },
        paiements: function () {
          return contexte().then(function (c) {
            var pay = mesFactures(c).filter(function (f) { return Number(f.montant_paye || 0) > 0; }).map(function (f, i) {
              return { number: 'PAY-DEMO-' + ('000' + (i + 1)).slice(-4), invoice: f.numero, amount: Number(f.montant_paye), currency: f.devise || 'USD', method: 'CASH',
                       tendered_amount: Number(f.montant_paye), tendered_currency: f.devise || 'USD', paid_at: f.payee_le || f.cree_le };
            });
            return plusTard({ payments: pay, refunds: [], credits: [] });
          });
        },
        documents: function () {
          return contexte().then(function (c) {
            var docs = mesFactures(c).map(function (f) {
              return { kind: 'INVOICE', number: f.numero, date: f.cree_le, amount: Number(f.montant || 0), currency: f.devise || 'USD', status: statutFacture(f), extra: null };
            });
            docs.sort(function (a, b) { return new Date(b.date) - new Date(a.date); });
            return plusTard(docs);
          });
        },
        adresses: function () {
          return contexte().then(function (c) {
            var l = c.p.adresses.filter(function (a) { return a.active; }).sort(function (a, b) {
              return (b.is_default ? 1 : 0) - (a.is_default ? 1 : 0) || new Date(a.created_at) - new Date(b.created_at);
            });
            return plusTard(l.map(function (a) {
              return { address_id: a.address_id, label: a.label, recipient_name: a.recipient_name, phone: a.phone, country: a.country, region: a.region, city: a.city,
                       address: a.address, instructions: a.instructions, is_default: a.is_default, created_at: a.created_at };
            }));
          });
        },
        enregistrerAdresse: function (a) {
          return contexte().then(function (c) {
            if (['HT', 'DO', 'US'].indexOf(a.pays) < 0) refuse('Pays inconnu (HT, DO ou US).');
            if (!String(a.adresse || '').trim()) refuse('L\'adresse est obligatoire.');
            if (String(a.adresse).length > 200 || String(a.etiquette || '').length > 40 || String(a.ville || '').length > 80 || String(a.region || '').length > 80 ||
                String(a.destinataire || '').length > 120 || String(a.telephone || '').length > 40 || String(a.consignes || '').length > 300) refuse('Un champ de l\'adresse est trop long.');
            var actives = c.p.adresses.filter(function (x) { return x.active; });
            var veut = !!a.parDefaut, adr;
            if (!a.id) {
              if (actives.length >= 20) refuse('Vous avez atteint le maximum de 20 adresses : supprimez-en une.');
              if (!actives.length) veut = true;
              adr = { address_id: identifiant(), active: true, is_default: false, created_at: maintenant() };
              c.p.adresses.push(adr);
            } else {
              adr = actives.filter(function (x) { return x.address_id === a.id; })[0];
              if (!adr) throw Erreur('introuvable', 'Adresse introuvable.');
              if (a.parDefaut === undefined) veut = adr.is_default;
            }
            if (veut) c.p.adresses.forEach(function (x) { x.is_default = false; });
            adr.label = String(a.etiquette || '').trim(); adr.recipient_name = String(a.destinataire || '').trim(); adr.phone = String(a.telephone || '').trim();
            adr.country = a.pays; adr.region = String(a.region || '').trim(); adr.city = String(a.ville || '').trim(); adr.address = String(a.adresse).trim();
            adr.instructions = String(a.consignes || '').trim(); adr.is_default = veut;
            ecrireDonnees(c.d);
            return plusTard({ address_id: adr.address_id, is_default: adr.is_default });
          });
        },
        supprimerAdresse: function (id) {
          return contexte().then(function (c) {
            var adr = c.p.adresses.filter(function (x) { return x.address_id === id && x.active; })[0];
            if (!adr) throw Erreur('introuvable', 'Adresse introuvable.');
            adr.active = false;
            var etait = adr.is_default; adr.is_default = false;
            if (etait) {
              var reste = c.p.adresses.filter(function (x) { return x.active; }).sort(function (a, b) { return new Date(b.created_at) - new Date(a.created_at); })[0];
              if (reste) reste.is_default = true;
            }
            ecrireDonnees(c.d);
            return plusTard({ address_id: id, deleted: true });
          });
        },
        enlevements: function () {
          return contexte().then(function (c) {
            return plusTard(c.p.enlevements.slice().sort(function (a, b) { return new Date(b.created_at) - new Date(a.created_at); }).map(ligneEnlevement));
          });
        },
        demanderEnlevement: function (e) {
          return contexte().then(function (c) {
            verifierDemande(e);
            var n = Number(e.colis);
            if (!n || n < 1 || n > 100) refuse('Le nombre de colis doit être compris entre 1 et 100.');
            if (ouvertes(c, 'enlevements').length >= 5) refuse('Vous avez déjà 5 demandes d\'enlèvement en attente : attendez leur traitement ou annulez-en une.');
            var a = resoudreAdresse(c, e);
            var r = { pickup_id: identifiant(), number: numeroDe(c, 'PKR'), request_status: 'REQUESTED', address: a.address, city: a.city, country: a.country, date: e.date,
                      window: e.creneau || 'ANY', parcels_expected: n, notes: String(e.notes || '').trim(), created_at: maintenant() };
            c.p.enlevements.push(r);
            ecrireDonnees(c.d);
            return plusTard({ pickup_id: r.pickup_id, number: r.number, stage: 'requested', correlation_id: identifiant() });
          });
        },
        annulerEnlevement: function (id) {
          return contexte().then(function (c) {
            var r = trouver(c.p.enlevements, 'pickup_id', id);
            if (r.request_status !== 'REQUESTED') throw Erreur('etat-incompatible', 'Cette demande est déjà traitée.');
            r.request_status = 'CANCELLED';
            ecrireDonnees(c.d);
            return plusTard({ pickup_id: id, stage: 'cancelled' });
          });
        },
        livraisons: function () {
          return contexte().then(function (c) {
            var prises = {};
            ouvertes(c, 'livraisons').forEach(function (r) { r.parcels.forEach(function (n) { prises[n] = true; }); });
            return plusTard({
              requests: c.p.livraisons.slice().sort(function (a, b) { return new Date(b.created_at) - new Date(a.created_at); }).map(ligneLivraison),
              deliveries: [],
              at_hub: mesColis(c).filter(function (x) { return x.statut === 'disponible' && !prises[x.numero]; })
                .sort(function (a, b) { return a.numero < b.numero ? -1 : 1; }).map(function (x) { return { tracking_number: x.numero, description: x.description || '' }; })
            });
          });
        },
        demanderLivraison: function (l) {
          return contexte().then(function (c) {
            var liste = (l.colis || []).map(function (n) { return String(n).trim().toUpperCase(); }).filter(function (n, i, t) { return n && t.indexOf(n) === i; });
            if (!liste.length) refuse('Choisissez au moins un colis.');
            if (liste.length > 50) refuse('Au plus 50 colis par demande.');
            verifierDemande(l);
            if (ouvertes(c, 'livraisons').length >= 5) refuse('Vous avez déjà 5 demandes de livraison en attente : attendez leur traitement ou annulez-en une.');
            var a = resoudreAdresse(c, l), mes = mesColis(c), prises = {};
            ouvertes(c, 'livraisons').forEach(function (r) { r.parcels.forEach(function (n) { prises[n] = true; }); });
            liste.forEach(function (n) {
              var co = mes.filter(function (x) { return x.numero === n; })[0];
              if (!co) throw Erreur('introuvable', 'Colis introuvable : ' + n + '.');
              if (co.statut !== 'disponible') refuse('Le colis ' + n + ' n\'est pas au hub : seul un colis au hub peut être livré.');
              if (prises[n]) refuse('Le colis ' + n + ' est déjà dans une demande ou une livraison en cours.');
            });
            var r = { request_id: identifiant(), number: numeroDe(c, 'DLR'), request_status: 'REQUESTED', address: a.address, city: a.city, country: a.country, date: l.date,
                      window: l.creneau || 'ANY', notes: String(l.notes || '').trim(), created_at: maintenant(), parcels: liste.sort() };
            c.p.livraisons.push(r);
            ecrireDonnees(c.d);
            return plusTard({ request_id: r.request_id, number: r.number, stage: 'requested', parcels: liste.length, correlation_id: identifiant() });
          });
        },
        annulerLivraison: function (id) {
          return contexte().then(function (c) {
            var r = trouver(c.p.livraisons, 'request_id', id);
            if (r.request_status !== 'REQUESTED') throw Erreur('etat-incompatible', 'Cette demande est déjà traitée.');
            r.request_status = 'CANCELLED';
            ecrireDonnees(c.d);
            return plusTard({ request_id: id, stage: 'cancelled' });
          });
        },
        notifications: function (o) {
          o = o || {};
          return contexte().then(function (c) {
            var tout = c.p.notifications.slice().sort(function (a, b) { return new Date(b.created_at) - new Date(a.created_at); });
            var liste = tout.filter(function (n) { return !o.nonLuesSeulement || !n.read_at; }).slice(0, Math.min(Math.max(nombre(o.limite, 50), 1), 200));
            return plusTard({ unread: tout.filter(function (n) { return !n.read_at; }).length, items: liste.map(copie) });
          });
        },
        lireNotifications: function (ids) {
          return contexte().then(function (c) {
            var n = 0;
            c.p.notifications.forEach(function (x) { if (!x.read_at && (!ids || !ids.length || ids.indexOf(x.id) >= 0)) { x.read_at = maintenant(); n += 1; } });
            ecrireDonnees(c.d);
            return plusTard({ marked: n });
          });
        },
        tickets: function () {
          return contexte().then(function (c) {
            return plusTard(c.p.tickets.slice().sort(function (a, b) { return new Date(b.updated_at) - new Date(a.updated_at); }).map(resumeTicket));
          });
        },
        ticket: function (id) {
          return contexte().then(function (c) {
            var t = trouver(c.p.tickets, 'ticket_id', id);
            return plusTard({ ticket_id: t.ticket_id, number: t.number, subject: t.subject, category: t.category, status: t.status, created_at: t.created_at, closed_at: t.closed_at || null,
                              parcel: t.parcel || null, invoice: t.invoice || null, messages: copie(t.messages) });
          });
        },
        ouvrirTicket: function (t) {
          return contexte().then(function (c) {
            var sujet = String(t.sujet || '').trim(), message = String(t.message || '').trim();
            if (sujet.length < 3 || sujet.length > 120) refuse('Le sujet doit compter de 3 à 120 caractères.');
            if (message.length < 1 || message.length > 4000) refuse('Le message doit compter de 1 à 4000 caractères.');
            if (CATEGORIES.indexOf(t.categorie) < 0) refuse('Catégorie inconnue.');
            if (c.p.tickets.filter(function (x) { return x.status !== 'CLOSED'; }).length >= 10) refuse('Vous avez déjà 10 tickets ouverts : attendez nos réponses ou fermez-en.');
            if (c.p.tickets.filter(function (x) { return Date.now() - new Date(x.created_at) < 86400000; }).length >= 5) refuse('Trop de tickets en 24 heures : réessayez demain, ou écrivez-nous sur WhatsApp.');
            var colis = String(t.colis || '').trim().toUpperCase(), facture = String(t.facture || '').trim();
            if (colis && !mesColis(c).some(function (x) { return x.numero === colis; })) throw Erreur('introuvable', 'Colis introuvable.');
            if (facture && !mesFactures(c).some(function (f) { return f.numero === facture; })) throw Erreur('introuvable', 'Facture introuvable.');
            var maintenantIso = maintenant();
            var tk = { ticket_id: identifiant(), number: numeroDe(c, 'SUP'), subject: sujet, category: t.categorie, status: 'OPEN', created_at: maintenantIso, updated_at: maintenantIso, closed_at: null,
                       parcel: colis || null, invoice: facture || null, messages: [{ author: 'CUSTOMER', body: message, at: maintenantIso }] };
            c.p.tickets.push(tk);
            ecrireDonnees(c.d);
            return plusTard({ ticket_id: tk.ticket_id, number: tk.number, status: 'OPEN', correlation_id: identifiant() });
          });
        },
        repondreTicket: function (id, message) {
          return contexte().then(function (c) {
            var m = String(message || '').trim();
            if (m.length < 1 || m.length > 4000) refuse('Le message doit compter de 1 à 4000 caractères.');
            var t = trouver(c.p.tickets, 'ticket_id', id);
            if (t.status === 'CLOSED') throw Erreur('etat-incompatible', 'Ce ticket est fermé : ouvrez-en un nouveau.');
            if (t.messages.length >= 100) refuse('Ce ticket a atteint 100 messages : ouvrez-en un nouveau.');
            t.messages.push({ author: 'CUSTOMER', body: m, at: maintenant() });
            t.status = 'OPEN'; t.updated_at = maintenant();
            ecrireDonnees(c.d);
            return plusTard({ ticket_id: id, status: 'OPEN' });
          });
        },
        fermerTicket: function (id) {
          return contexte().then(function (c) {
            var t = trouver(c.p.tickets, 'ticket_id', id);
            if (t.status === 'CLOSED') throw Erreur('etat-incompatible', 'Ce ticket est déjà fermé.');
            t.status = 'CLOSED'; t.closed_at = maintenant(); t.updated_at = t.closed_at;
            ecrireDonnees(c.d);
            return plusTard({ ticket_id: id, status: 'CLOSED' });
          });
        }
      };
    })(),

    /* Notifications en démonstration : les préférences du client vivent dans ce navigateur (mêmes formes que la base) ; pas d'équipe pour
       envoyer quoi que ce soit, donc pas de santé des envois ni de signal temps réel (la démonstration ne simule pas un serveur). */
    notifications: {
      preferences: function () {
        return preparer().then(function (d) {
          var moi = compteConnecte(d);
          if (!moi) throw Erreur('non-autorise');
          if (ROLES_EQUIPE.indexOf(moi.role) >= 0) return [];
          var pref = (d.preferences && d.preferences[moi.id]) || {};
          return plusTard(CANAUX_NOTIFICATION.map(function (ch) {
            var dispo = ch === 'in_app' || ch === 'push' || ch === 'email';
            return { channel: ch, available: dispo, enabled: ch === 'in_app' ? true : (pref[ch] !== undefined ? pref[ch] : (ch === 'push' || ch === 'email')), locked: ch === 'in_app' };
          }));
        });
      },
      reglerPreference: function (canal, actif) {
        var self = this;
        return preparer().then(function (d) {
          var moi = compteConnecte(d);
          if (!moi || ROLES_EQUIPE.indexOf(moi.role) >= 0) throw Erreur('non-autorise');
          if (['push', 'email', 'sms', 'whatsapp'].indexOf(canal) < 0) throw Erreur('donnee-invalide', 'Canal inconnu, ou qui ne se coupe pas.');
          if (typeof actif !== 'boolean') throw Erreur('donnee-invalide', 'Choisissez : oui ou non.');
          d.preferences = d.preferences || {};
          d.preferences[moi.id] = d.preferences[moi.id] || {};
          d.preferences[moi.id][canal] = actif;
          ecrireDonnees(d);
          return self.preferences();
        });
      },
      sante: function () { return Promise.reject(Erreur('non-autorise')); },
      surveiller: function () { return function () {}; }
    },

    /* Pas d'exploitation en démonstration : il n'y a pas de base à surveiller. Un signalement d'erreur y est simplement ignoré. */
    exploitation: {
      sante: function () { return Promise.reject(Erreur('non-autorise')); },
      etat: function () { return Promise.reject(Erreur('non-autorise')); },
      signalerErreur: function () { return Promise.resolve(false); }
    },

    /* Pas d'analytique en démonstration : ses chiffres ne seraient pas réels. */
    analytique: (function () {
      var a = {};
      METHODES_ANALYTIQUE.forEach(function (m) { a[m] = function () { return Promise.reject(Erreur('non-autorise')); }; });
      return a;
    })(),

    /* Pas de poste de scan en démonstration : il vit dans le centre de commande, qui n'y existe pas. */
    poste: (function () {
      var p = {};
      METHODES_POSTE.forEach(function (m) { p[m] = function () { return Promise.reject(Erreur('non-autorise')); }; });
      return p;
    })(),

    /* Pas de centre de commande en démonstration (voir « centre » dans la version en ligne) : mêmes méthodes, toutes fermées. */
    centre: (function () {
      var c = { disponible: function () { return Promise.resolve({ actif: false, raison: 'demo' }); } };
      METHODES_CENTRE.forEach(function (m) { if (m !== 'disponible') c[m] = function () { return Promise.reject(Erreur('non-autorise')); }; });
      return c;
    })(),

    admin: {
      statistiques: function () {
        return preparer().then(function (d) {
          exiger(d, 'colis.lire');
          var statuts = {};
          d.colis.forEach(function (c) { statuts[c.statut] = (statuts[c.statut] || 0) + 1; });
          return plusTard({
            clients: d.comptes.filter(function (c) { return c.role === 'client'; }).length,
            colis: d.colis.length,
            statuts: statuts,
            factures_impayees: d.factures.filter(function (f) { return f.statut === 'impayee'; }).length,
            montant_impaye: d.factures.filter(function (f) { return f.statut === 'impayee'; })
              .reduce(function (a, f) { return a + Number(f.montant || 0); }, 0)
          });
        });
      },

      colis: function (o) {
        o = o || {};
        return preparer().then(function (d) {
          exiger(d, 'colis.lire');
          var lignes = d.colis.map(function (c) { return detailsColis(d, c); });
          if (o.statut) lignes = lignes.filter(function (c) { return c.statut === o.statut; });
          if (o.client_id) lignes = lignes.filter(function (c) { return c.client_id === o.client_id; });
          if (o.recherche) {
            var t = nettoyer(o.recherche);
            if (t) lignes = lignes.filter(function (c) {
              return contient([c.numero, c.description, c.destinataire, c.code_client, c.nom_client,
                               c.ville_destination, c.expediteur], t);
            });
          }
          lignes.sort(function (a, b) { return new Date(b.maj_le) - new Date(a.maj_le); });
          return plusTard(page(lignes, o));
        });
      },

      colisParId: function (id) {
        return preparer().then(function (d) {
          exiger(d, 'colis.lire');
          var c = d.colis.filter(function (x) { return x.id === id; })[0];
          return plusTard(c ? detailsColis(d, c) : null);
        });
      },

      historique: function (id) {
        return preparer().then(function (d) {
          exiger(d, 'colis.lire');
          return plusTard(d.historique.filter(function (h) { return h.colis_id === id; })
            .sort(function (a, b) { return new Date(a.cree_le) - new Date(b.cree_le); }));
        });
      },

      /* Même règle qu'en base : tout colis enregistré reçoit sa facture, et
         celle-ci suit le colis tant que rien n'a été réglé. Écrit deux fois,
         faute de quoi le mode démo mentirait sur le comportement réel. */
      creerColis: function (entree) {
        return preparer().then(function (d) {
          var moi = exiger(d, 'colis.creer');
          var champs = choisir(entree, CHAMPS_COLIS);
          if (!champs.client_id) throw Erreur('client-manquant');
          if (!d.comptes.some(function (c) { return c.id === champs.client_id; })) throw Erreur('client-inconnu');
          // Comme la base : un colis ne se rattache qu'à un compte client.
          if (!d.comptes.some(function (c) { return c.id === champs.client_id && c.role === 'client'; })) throw Erreur('client-invalide');
          if (champs.statut && STATUTS.indexOf(champs.statut) < 0) throw Erreur('statut-inconnu');
          var pays = texteCourt(champs.pays_destination, 2).toUpperCase() || 'DO';
          var c = {
            id: identifiant(),
            numero: numeroColis(d),
            jeton: alea(10),
            client_id: champs.client_id,
            description: texteCourt(champs.description, 200),
            expediteur: texteCourt(champs.expediteur, 120),
            destinataire: texteCourt(champs.destinataire, 120),
            telephone_destinataire: texteCourt(champs.telephone_destinataire, 40),
            poids_lb: champs.poids_lb === '' || champs.poids_lb === undefined ? null : Number(champs.poids_lb),
            tarif_lb: Number(champs.tarif_lb || 0),
            service: ['aerien', 'maritime', 'terrestre'].indexOf(champs.service) >= 0 ? champs.service : 'aerien',
            pays_destination: pays,
            ville_destination: texteCourt(champs.ville_destination, 80),
            adresse_livraison: texteCourt(champs.adresse_livraison, 200),
            valeur_declaree: champs.valeur_declaree === '' || champs.valeur_declaree === undefined ? null : Number(champs.valeur_declaree),
            statut: champs.statut || 'confirme',
            lieu: texteCourt(champs.lieu, 120),
            note: texteCourt(champs.note, 400),
            cree_le: maintenant(), maj_le: maintenant()
          };
          d.colis.push(c);
          historiser(d, c, moi.email);
          facturerColis(d, c);
          ecrireDonnees(d);
          prevenir('factures');
          return plusTard(JSON.parse(JSON.stringify(c)));
        });
      },

      modifierColis: function (id, entree) {
        return preparer().then(function (d) {
          var moi = exiger(d, 'colis.modifier');
          var c = d.colis.filter(function (x) { return x.id === id; })[0];
          if (!c) throw Erreur('colis-inconnu');
          var champs = choisir(entree, CHAMPS_COLIS);
          if (champs.statut && STATUTS.indexOf(champs.statut) < 0) throw Erreur('statut-inconnu');
          var avant = { statut: c.statut, lieu: c.lieu, note: c.note };
          Object.keys(champs).forEach(function (k) {
            if (k === 'tarif_lb') {
              c[k] = Number(champs[k] || 0);
            } else if (k === 'poids_lb' || k === 'valeur_declaree') {
              c[k] = champs[k] === '' || champs[k] === null || champs[k] === undefined ? null : Number(champs[k]);
            } else if (k === 'client_id') {
              c[k] = champs[k];
            } else {
              c[k] = texteCourt(champs[k], 400);
            }
          });
          // Le numéro et le jeton ne changent jamais : l'étiquette imprimée reste valable.
          c.maj_le = maintenant();
          facturerColis(d, c);
          if (avant.statut !== c.statut || avant.lieu !== c.lieu || avant.note !== c.note) {
            historiser(d, c, moi.email);
          }
          ecrireDonnees(d);
          return plusTard(JSON.parse(JSON.stringify(c)));
        });
      },

      changerStatut: function (ids, statut, lieu, note) {
        return preparer().then(function (d) {
          var moi = exiger(d, 'colis.statut');
          if (STATUTS.indexOf(statut) < 0) throw Erreur('statut-inconnu');
          var liste = [].concat(ids), touches = 0;
          liste.forEach(function (id) {
            var c = d.colis.filter(function (x) { return x.id === id; })[0];
            if (!c) return;
            c.statut = statut;
            if (lieu !== undefined) c.lieu = texteCourt(lieu, 120);
            if (note !== undefined) c.note = texteCourt(note, 400);
            c.maj_le = maintenant();
            historiser(d, c, moi.email);
            touches++;
          });
          ecrireDonnees(d);
          return plusTard(touches);
        });
      },

      supprimerColis: function (id) {
        return preparer().then(function (d) {
          exiger(d, 'colis.supprimer');
          d.colis = d.colis.filter(function (c) { return c.id !== id; });
          d.historique = d.historique.filter(function (h) { return h.colis_id !== id; });
          d.factures.forEach(function (f) { if (f.colis_id === id) f.colis_id = null; });
          ecrireDonnees(d);
          return plusTard(true);
        });
      },

      clients: function (o) {
        o = o || {};
        return preparer().then(function (d) {
          exiger(d, 'clients.lire');
          var lignes = d.comptes.map(sansMdp);
          if (o.role === 'equipe') lignes = lignes.filter(function (c) { return ROLES_EQUIPE.indexOf(c.role) >= 0; });
          else if (o.role) lignes = lignes.filter(function (c) { return c.role === o.role; });
          if (o.recherche) {
            var t = nettoyer(o.recherche);
            if (t) lignes = lignes.filter(function (c) {
              return contient([c.code, c.nom_complet, c.email, c.telephone, c.ville], t);
            });
          }
          lignes.sort(function (a, b) { return new Date(b.cree_le) - new Date(a.cree_le); });
          return plusTard(page(lignes, o));
        });
      },

      chercherClient: function (code) {
        return preparer().then(function (d) {
          exiger(d, 'clients.lire');
          var c2 = normaliserCode(code);
          if (!c2) return plusTard(null);
          var c = d.comptes.filter(function (x) { return x.code === c2 && x.role === 'client'; })[0];
          return plusTard(sansMdp(c) || null);
        });
      },

      definirRole: function (id, role, droits) {
        return preparer().then(function (d) {
          var moi = exiger(d, 'roles.gerer');
          if (ROLES.indexOf(role) < 0) throw Erreur('role-inconnu');
          var c = d.comptes.filter(function (x) { return x.id === id; })[0];
          if (!c) throw Erreur('compte-inconnu');
          // La hiérarchie de la fonction definir_role() de la base, à l'identique :
          // le mode démo ne doit pas permettre ce que la vraie base refuse.
          // Personne ne modifie son propre rôle (un administrateur qui se
          // « remet » administrateur ne change rien).
          if (c.id === moi.id && !(c.role === 'admin' && role === 'admin')) throw Erreur('pas-soi-meme');
          // Seul un administrateur nomme, modifie ou retire un gérant ou un administrateur.
          if ((ROLES_DIRECTION.indexOf(role) >= 0 || ROLES_DIRECTION.indexOf(c.role) >= 0) && moi.role !== 'admin') {
            throw Erreur('non-autorise');
          }
          // L'équipe n'est pas la clientèle (comme la base) : un client qui a des
          // colis ou des factures reste un client, ils perdraient leur propriétaire.
          var liens = d.colis.some(function (x) { return x.client_id === c.id; }) ||
                      d.factures.some(function (x) { return x.client_id === c.id; });
          if (c.role === 'client' && role !== 'client' && liens) throw Erreur('compte-a-des-colis');
          c.role = role;
          // Seul l'employé a une liste de droits à cocher : le gérant et
          // l'administrateur reçoivent les leurs de leur rôle.
          c.droits = role === 'admin' ? DROITS.slice()
            : (role === 'employe' ? (droits || []).filter(function (x) { return DROITS.indexOf(x) >= 0; }) : []);
          // Un membre de l'équipe n'a pas d'identifiant client (ni espace client, ni
          // colis) ; redevenir client en reçoit un nouveau. Un compte d'équipe qui
          // porte encore des colis garde le sien : on ne coupe pas ce lien en silence.
          if (role === 'client') { if (!c.code) c.code = nouveauCode(d.comptes); }
          else if (!liens) c.code = null;
          ecrireDonnees(d);
          return plusTard(sansMdp(c));
        });
      },

      // En mode démonstration, les données vivent dans le navigateur : elles
      // suivent toujours le code.
      baseAJour: function () { return Promise.resolve(true); },

      resumeClients: function (ids) {
        return preparer().then(function (d) {
          exiger(d, 'clients.lire');
          var vise = {};
          (ids || []).forEach(function (i) { vise[i] = true; });
          return plusTard(resumerClients(
            d.colis.filter(function (c) { return vise[c.client_id]; }),
            d.factures.filter(function (f) { return vise[f.client_id]; })));
        });
      },

      factures: function (o) {
        o = o || {};
        return preparer().then(function (d) {
          exiger(d, 'factures.lire');
          var lignes = d.factures.map(function (f) {
            var x = JSON.parse(JSON.stringify(f));
            var cl = d.comptes.filter(function (c) { return c.id === f.client_id; })[0];
            var co = d.colis.filter(function (c) { return c.id === f.colis_id; })[0];
            x.code_client = cl ? cl.code : null;
            x.nom_client = cl ? cl.nom_complet : null;
            x.email_client = cl ? cl.email : null;
            x.numero_colis = co ? co.numero : null;
            return x;
          });
          if (o.statut) lignes = lignes.filter(function (f) { return f.statut === o.statut; });
          if (o.client_id) lignes = lignes.filter(function (f) { return f.client_id === o.client_id; });
          if (o.colis_id) lignes = lignes.filter(function (f) { return f.colis_id === o.colis_id; });
          if (o.recherche) {
            var t = nettoyer(o.recherche);
            if (t) lignes = lignes.filter(function (f) {
              return contient([f.numero, f.code_client, f.nom_client, f.numero_colis], t);
            });
          }
          lignes.sort(function (a, b) { return new Date(b.cree_le) - new Date(a.cree_le); });
          return plusTard(page(lignes, o));
        });
      },

      creerFacture: function (entree) {
        return preparer().then(function (d) {
          exiger(d, 'factures.creer');
          var champs = choisir(entree, CHAMPS_FACTURE);
          if (!champs.client_id) throw Erreur('client-manquant');
          // Comme la base : une facture ne se rattache qu'à un compte client.
          if (!d.comptes.some(function (c) { return c.id === champs.client_id && c.role === 'client'; })) throw Erreur('client-invalide');
          var lignes = nettoyerLignes(champs.lignes);
          var frais = champs.frais_service === undefined ? 0 : Number(champs.frais_service || 0);
          var totalColis = lignes.reduce(function (a, l) { return a + l.montant; }, 0);
          var total = champs.montant !== undefined && champs.montant !== ''
            ? Number(champs.montant)
            : totalColis + frais;
          var paye = champs.statut === 'payee' ? total : Number(champs.montant_paye || 0);
          var f = {
            id: identifiant(),
            numero: numeroFacture(d),
            client_id: champs.client_id,
            colis_id: champs.colis_id || null,
            montant: total,
            frais_service: frais,
            montant_paye: paye,
            devise: texteCourt(champs.devise, 3).toUpperCase() || (CFG.devise || 'USD'),
            statut: total > 0 && paye >= total ? 'payee' : 'impayee',
            groupee: !!champs.groupee,
            note: texteCourt(champs.note, 400),
            lignes: lignes,
            echeance_le: champs.echeance_le || null,
            cree_le: maintenant(),
            payee_le: null
          };
          f.payee_le = f.statut === 'payee' ? maintenant() : null;
          d.factures.push(f);
          ecrireDonnees(d);
          prevenir('factures');
          return plusTard(JSON.parse(JSON.stringify(f)));
        });
      },

      modifierFacture: function (id, entree) {
        return preparer().then(function (d) {
          exiger(d, 'factures.modifier');
          var f = d.factures.filter(function (x) { return x.id === id; })[0];
          if (!f) throw Erreur('facture-inconnue');
          var champs = choisir(entree, CHAMPS_FACTURE);
          if (champs.statut && ['impayee', 'payee'].indexOf(champs.statut) < 0) throw Erreur('statut-inconnu');
          var statutDemande = champs.statut && champs.statut !== f.statut ? champs.statut : null;
          Object.keys(champs).forEach(function (k) {
            if (k === 'montant' || k === 'frais_service' || k === 'montant_paye') f[k] = Number(champs[k] || 0);
            else if (k === 'lignes') f[k] = nettoyerLignes(champs[k]);
            else f[k] = champs[k];
          });
          // Basculer le statut à la main vaut règlement complet, ou remise à
          // zéro ; sinon c'est le montant payé qui décide du statut.
          if (statutDemande) {
            f.statut = statutDemande;
            f.montant_paye = statutDemande === 'payee' ? Number(f.montant || 0) : 0;
          } else {
            f.statut = Number(f.montant) > 0 && Number(f.montant_paye || 0) >= Number(f.montant)
              ? 'payee' : 'impayee';
          }
          f.payee_le = f.statut === 'payee' ? (f.payee_le || maintenant()) : null;
          ecrireDonnees(d);
          prevenir('factures');
          return plusTard(JSON.parse(JSON.stringify(f)));
        });
      },

      supprimerFacture: function (id) {
        return preparer().then(function (d) {
          exiger(d, 'factures.supprimer');
          d.factures = d.factures.filter(function (f) { return f.id !== id; });
          ecrireDonnees(d);
          prevenir('factures');
          return plusTard(true);
        });
      },

      /* Jeu d'essai : deux clients, un employé, des colis à tous les stades et
         deux factures. Utile pour voir les écrans pleins avant la mise en ligne. */
      remplirDemo: function () {
        return preparer().then(function (d) {
          exiger(d, 'colis.creer');
          if (d.colis.length) return plusTard(false);
          function jours(n) { return new Date(Date.now() - n * 86400000).toISOString(); }
          return Promise.all([
            Empreinte.creer('client2026'), Empreinte.creer('client2026'), Empreinte.creer('employe2026')
          ]).then(function (mdp) {
            var gens = [
              { email: 'marie.jean@exemple.com', nom: 'Marie Jean', pays: 'Haïti', region: 'Ouest',
                ville: 'Pétion-Ville', adresse: '12, rue Grégoire', tel: '+509 3720 1188', role: 'client' },
              { email: 'luis.perez@exemple.com', nom: 'Luis Pérez', pays: 'République dominicaine',
                region: 'Santo Domingo', ville: 'Santo Domingo Este', adresse: 'Av. Las Américas 45',
                tel: '+1 809 555-0142', role: 'client' },
              { email: 'agent@speedexpresshipping.com', nom: 'Rose-Marie Célestin',
                pays: 'République dominicaine', region: 'Santo Domingo', ville: 'Santo Domingo Este',
                adresse: 'C. Fausto Cejas Rodriguez #89 k12', tel: '+1 829 265-3728', role: 'employe' }
            ];
            var ids = gens.map(function (g, i) {
              var compte = {
                id: identifiant(), email: g.email, mdp: mdp[i], role: g.role,
                droits: g.role === 'employe' ? ['colis.lire', 'colis.creer', 'colis.statut', 'clients.lire', 'factures.lire'] : [],
                code: g.role === 'client' ? nouveauCode(d.comptes) : null,
                nom_complet: g.nom, pays: g.pays, region: g.region, ville: g.ville,
                adresse: g.adresse, telephone: g.tel, langue: 'fr', cree_le: jours(40 - i * 5)
              };
              d.comptes.push(compte);
              return compte.id;
            });

            var parcours = [
              { c: 0, desc: 'Chaussures de sport — 2 paires', exp: 'Amazon', poids: 4.2, tarif: 5, service: 'aerien',
                etapes: [['confirme', 9, 'Entrepôt de Miami'], ['expedie', 6, 'Miami → Port-au-Prince'],
                         ['disponible', 2, 'Agence de Pétion-Ville', 'Retrait du lundi au samedi, 8 h – 18 h.']] },
              { c: 0, desc: 'Téléphone et accessoires', exp: 'Walmart', poids: 1.1, tarif: 7, service: 'aerien',
                etapes: [['confirme', 2, 'Entrepôt de Miami']] },
              { c: 0, desc: 'Vêtements', exp: 'SHEIN', poids: 2.6, tarif: 5, service: 'aerien',
                etapes: [['confirme', 22, 'Entrepôt de Miami'], ['expedie', 18, 'Miami → Port-au-Prince'],
                         ['disponible', 15, 'Agence de Pétion-Ville'], ['livre', 13, 'Pétion-Ville', 'Remis en main propre.']] },
              { c: 1, desc: 'Pièces automobiles (amortisseurs)', exp: 'RockAuto', poids: 18, tarif: 3.5, service: 'maritime',
                etapes: [['confirme', 12, 'Entrepôt de Miami'], ['expedie', 7, 'Port de Miami → Caucedo']] },
              { c: 1, desc: 'Ordinateur portable', exp: 'Best Buy', poids: 5.4, tarif: 6, service: 'aerien',
                etapes: [['confirme', 5, 'Entrepôt de Miami'], ['expedie', 3, 'Miami → Santo Domingo'],
                         ['action', 1, 'Douane de Santo Domingo', 'Facture d’achat demandée par la douane : envoyez-la-nous sur WhatsApp.']] }
            ];
            parcours.forEach(function (p) {
              var client = d.comptes.filter(function (c) { return c.id === ids[p.c]; })[0];
              var pays = client.pays === 'Haïti' ? 'HT' : 'DO';
              var c = {
                id: identifiant(), numero: numeroColis(d), jeton: alea(10),
                client_id: client.id, description: p.desc, expediteur: p.exp,
                destinataire: client.nom_complet, telephone_destinataire: client.telephone,
                poids_lb: p.poids, tarif_lb: p.tarif, service: p.service,
                pays_destination: pays, ville_destination: client.ville,
                adresse_livraison: client.adresse, valeur_declaree: null,
                statut: 'confirme', lieu: '', note: ''
              };
              p.etapes.forEach(function (e) {
                c.statut = e[0]; c.lieu = e[2]; c.note = e[3] || '';
                c.maj_le = jours(e[1]);
                historiser(d, c, 'admin@speedexpress.demo', c.maj_le);
              });
              c.cree_le = jours(p.etapes[0][1]);
              d.colis.push(c);
              // Comme en vrai : chaque colis fait naître sa facture.
              facturerColis(d, c);
            });

            // Un colis réglé et un autre payé à moitié, pour voir les deux cas.
            var reglee = d.factures[0], partielle = d.factures[3];
            if (reglee) { reglee.montant_paye = reglee.montant; reglee.statut = 'payee'; reglee.payee_le = jours(6); }
            if (partielle) { partielle.montant_paye = Math.round(partielle.montant / 2 * 100) / 100; }
            d.factures.forEach(function (fa, i) { fa.cree_le = jours(12 - i); });

            ecrireDonnees(d);
            prevenir('factures');
            return plusTard(true);
          });
        });
      },

      effacerDemo: function () {
        stockage('effacer', CLE_DONNEES);
        stockage('effacer', CLE_SESSION);
        pretInit = null;
        prevenir('colis');
        return plusTard(true);
      }
    }
  };

  /* ======================================================================
     Espace fermé — site en ligne sans configuration
     ====================================================================== */
  function ferme() { return Promise.reject(Erreur('ferme')); }
  var offAPI = {
    session: function () { return Promise.resolve(null); },
    profil: function () { return Promise.resolve(null); },
    inscrire: ferme, connecter: ferme,
    deconnecter: function () { return Promise.resolve(true); },
    envoyerLienMotDePasse: ferme,
    attendreRecuperation: function () { return Promise.resolve(false); },
    changerMotDePasse: ferme, modifierProfil: ferme,
    mesColis: ferme, mesFactures: ferme,
    surveiller: function () { return function () {}; },
    suivre: ferme,
    portail: (function () {
      var p = { disponible: function () { return Promise.resolve({ actif: false, raison: 'off' }); } };
      METHODES_PORTAIL.forEach(function (m) { if (m !== 'disponible') p[m] = ferme; });
      return p;
    })(),
    notifications: { preferences: ferme, reglerPreference: ferme, sante: ferme, surveiller: function () { return function () {}; } },
    poste: { profil: ferme, scanner: ferme },
    analytique: { rapport: ferme, indicateurs: ferme, executions: ferme, recalculer: ferme, verifier: ferme },
    exploitation: { sante: ferme, etat: ferme, signalerErreur: function () { return Promise.resolve(false); } },
    centre: (function () {
      var c = { disponible: function () { return Promise.resolve({ actif: false, raison: 'off' }); } };
      METHODES_CENTRE.forEach(function (m) { if (m !== 'disponible') c[m] = ferme; });
      return c;
    })(),
    admin: {}
  };

  /* ====================================================================== */
  var api = MODE === 'supabase' ? supabaseAPI : (MODE === 'demo' ? demoAPI : offAPI);

  api.mode = MODE;
  api.STATUTS = STATUTS;
  api.ETAPES = ETAPES;
  api.ROLES = ROLES;
  api.ROLES_EQUIPE = ROLES_EQUIPE;
  api.ROLES_DIRECTION = ROLES_DIRECTION;
  api.accesTableauDeBord = accesTableauDeBord;
  api.DROITS = DROITS;
  api.MDP_MINIMUM = MDP_MINIMUM;
  api.normaliserCode = normaliserCode;
  api.droitsDe = droitsDe;
  api.peut = peutFaire;
  api.FRAIS_SERVICE = FRAIS_SERVICE;
  api.avecWebCrypto = Empreinte.webcrypto;
  api.METHODES_PORTAIL = METHODES_PORTAIL;
  api.METHODES_CENTRE = METHODES_CENTRE;
  api.METHODES_NOTIFICATIONS = METHODES_NOTIFICATIONS;
  api.METHODES_POSTE = METHODES_POSTE;
  api.INTENTIONS_POSTE = INTENTIONS_POSTE;
  api.METHODES_ANALYTIQUE = METHODES_ANALYTIQUE;
  api.GRAINS_ANALYTIQUE = GRAINS_ANALYTIQUE;
  api.METHODES_EXPLOITATION = METHODES_EXPLOITATION;
  /* L'identifiant de CETTE page ouverte : joint à chaque erreur signalée, il permet de retrouver « ce qui s'est passé chez ce client ». */
  api.idPage = 'p' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);

  /* Les erreurs JavaScript non rattrapées, signalées à la base (phase 17) — seulement en ligne, seulement si le client Supabase est DÉJÀ
     chargé (jamais pour ça sur une page publique) et qu'une session existe ; cinq au plus par page, sans doublon ; jamais celles d'un script
     d'une autre origine (extensions du navigateur : « Script error. »). */
  (function () {
    if (MODE !== 'supabase' || !window.addEventListener) return;
    var envoyees = 0, vus = {};
    function signaler(message, source) {
      message = String(message || '');
      if (!message || /^Script error\.?$/i.test(message) || envoyees >= 5 || vus[message] || !promesseClient) return;
      vus[message] = true; envoyees += 1;
      promesseClient.then(function (c) { return c.auth.getSession(); }).then(function (r) {
        if (!r || !r.data || !r.data.session) return;
        api.exploitation.signalerErreur({ page: location.pathname, message: message, source: source, requete: api.idPage });
      }).catch(function () {});
    }
    window.addEventListener('error', function (ev) {
      if (ev && ev.filename && ev.filename.indexOf(location.origin) !== 0) return;
      signaler(ev && ev.message, ev && ev.filename ? ev.filename.replace(location.origin, '') + ':' + ev.lineno : '');
    });
    window.addEventListener('unhandledrejection', function (ev) {
      var r = ev && ev.reason;
      // une erreur métier déjà présentée à l'écran (refus, réseau…) n'est pas un défaut du site
      if (r && r.code && r.code !== 'inconnu') return;
      signaler(r && (r.message || String(r)), 'promesse');
    });
  })();
  api.VUES_CENTRE = VUES_CENTRE;
  api.FILTRES_CENTRE = FILTRES_CENTRE;
  /* Une clé qui identifie UN envoi de formulaire : rejouée telle quelle après une erreur réseau, elle empêche la base de créer la demande deux fois. */
  api.cleEnvoi = function () { return 'w' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10); };

  /* Raccourci commun aux pages protégées : renvoie le profil, ou renvoie le
     visiteur vers la page de connexion. Le contrôle sérieux reste celui du
     serveur — celui-ci ne fait qu'éviter d'afficher une page vide. */
  api.exigerProfil = function (options) {
    options = options || {};
    return api.profil().then(function (p) {
      if (!p) {
        var vers = options.vers || 'connexion.html';
        location.replace(vers + '?suite=' + encodeURIComponent(location.pathname.split('/').pop() || 'index.html'));
        return null;
      }
      if (options.droit && !peutFaire(p, options.droit)) {
        location.replace('espace-client.html');
        return null;
      }
      return p;
    });
  };

  window.SES_API = api;
})();
