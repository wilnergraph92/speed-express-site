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

  var ROLES = ['client', 'employe', 'admin'];

  /* Droits confiables à un employé. L'administrateur les a tous. */
  var DROITS = [
    'colis.lire', 'colis.creer', 'colis.modifier', 'colis.statut', 'colis.supprimer',
    'factures.lire', 'factures.creer', 'factures.modifier', 'factures.supprimer',
    'clients.lire', 'roles.gerer'
  ];

  var CHAMPS_PROFIL = ['nom_complet', 'pays', 'region', 'ville', 'adresse', 'telephone', 'langue'];
  var CHAMPS_COLIS = ['client_id', 'description', 'expediteur', 'destinataire', 'poids_lb', 'service',
                      'pays_destination', 'ville_destination', 'adresse_livraison', 'valeur_declaree',
                      'statut', 'lieu', 'note'];
  var CHAMPS_FACTURE = ['client_id', 'colis_id', 'montant', 'devise', 'statut', 'note', 'echeance_le', 'lignes'];

  var MDP_MINIMUM = 8;

  function Erreur(code, detail) {
    var e = new Error(detail || code);
    e.code = code;
    return e;
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
     jeton tiré au hasard, qui rend son adresse de suivi impossible à deviner :
     deux colis n'ont jamais le même. Voir SES_UI.etiquette(). */
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
    if (profil.role === 'admin') return DROITS.slice();
    if (profil.role === 'employe') {
      var d = profil.droits || [];
      return DROITS.filter(function (x) { return d.indexOf(x) >= 0; });
    }
    return [];
  }

  function peutFaire(profil, droit) {
    return droitsDe(profil).indexOf(droit) >= 0;
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
      nettoyerAdresse();
      return sb().then(function (c) { return c.auth.getSession(); })
        .then(function (r) { return r.data && r.data.session ? r.data.session : null; })
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

    suivre: function (numero) {
      return sb().then(function (c) { return c.rpc('suivre_colis', { p_numero: String(numero || '').trim() }); })
        .then(resultat);
    },

    admin: {
      statistiques: function () {
        return sb().then(function (c) { return c.rpc('statistiques_ses'); }).then(resultat);
      },

      colis: function (o) {
        o = o || {};
        return sb().then(function (c) {
          var q = c.from('colis_details').select('*', { count: 'exact' });
          if (o.statut) q = q.eq('statut', o.statut);
          if (o.client_id) q = q.eq('client_id', o.client_id);
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
          return c.from('colis').insert(choisir(d, CHAMPS_COLIS)).select('*').single().then(resultat);
        });
      },

      modifierColis: function (id, champs) {
        return sb().then(function (c) {
          return c.from('colis').update(choisir(champs, CHAMPS_COLIS)).eq('id', id)
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
          if (o.role) q = q.eq('role', o.role);
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
          return c.from('clients').select('*').eq('code', c2).maybeSingle().then(resultat);
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

      factures: function (o) {
        o = o || {};
        return sb().then(function (c) {
          var q = c.from('factures_details').select('*', { count: 'exact' });
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
          return c.from('factures').insert(choisir(d, CHAMPS_FACTURE)).select('*').single().then(resultat);
        });
      },

      modifierFacture: function (id, champs) {
        return sb().then(function (c) {
          return c.from('factures').update(choisir(champs, CHAMPS_FACTURE)).eq('id', id)
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

    /* Suivi public : statut et étapes, sans nom, adresse ni note interne. */
    suivre: function (numero) {
      return preparer().then(function (d) {
        var n = String(numero || '').trim().toUpperCase();
        if (n.length < 4) return plusTard(null);
        var trouve = null;
        d.colis.forEach(function (c) { if (c.numero === n) trouve = c; });
        if (!trouve) return plusTard(null);
        return plusTard({
          numero: trouve.numero, statut: trouve.statut, service: trouve.service,
          pays_destination: trouve.pays_destination, maj_le: trouve.maj_le,
          historique: d.historique.filter(function (h) { return h.colis_id === trouve.id; })
            .map(function (h) { return { statut: h.statut, lieu: h.lieu, cree_le: h.cree_le }; })
            .sort(function (a, b) { return new Date(a.cree_le) - new Date(b.cree_le); })
        });
      });
    },

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

      creerColis: function (entree) {
        return preparer().then(function (d) {
          var moi = exiger(d, 'colis.creer');
          var champs = choisir(entree, CHAMPS_COLIS);
          if (!champs.client_id) throw Erreur('client-manquant');
          if (!d.comptes.some(function (c) { return c.id === champs.client_id; })) throw Erreur('client-inconnu');
          if (champs.statut && STATUTS.indexOf(champs.statut) < 0) throw Erreur('statut-inconnu');
          d.seqColis += 1;
          var pays = texteCourt(champs.pays_destination, 2).toUpperCase() || 'DO';
          var c = {
            id: identifiant(),
            numero: 'SES-' + d.seqColis + '-' + pays,
            jeton: alea(10),
            client_id: champs.client_id,
            description: texteCourt(champs.description, 200),
            expediteur: texteCourt(champs.expediteur, 120),
            destinataire: texteCourt(champs.destinataire, 120),
            poids_lb: champs.poids_lb === '' || champs.poids_lb === undefined ? null : Number(champs.poids_lb),
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
          ecrireDonnees(d);
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
            if (k === 'poids_lb' || k === 'valeur_declaree') {
              c[k] = champs[k] === '' || champs[k] === null || champs[k] === undefined ? null : Number(champs[k]);
            } else if (k === 'client_id') {
              c[k] = champs[k];
            } else {
              c[k] = texteCourt(champs[k], 400);
            }
          });
          // Le numéro et le jeton ne changent jamais : l'étiquette imprimée reste valable.
          c.maj_le = maintenant();
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
          if (o.role) lignes = lignes.filter(function (c) { return c.role === o.role; });
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
          var c = d.comptes.filter(function (x) { return x.code === c2; })[0];
          return plusTard(sansMdp(c) || null);
        });
      },

      definirRole: function (id, role, droits) {
        return preparer().then(function (d) {
          var moi = exiger(d, 'roles.gerer');
          if (ROLES.indexOf(role) < 0) throw Erreur('role-inconnu');
          var c = d.comptes.filter(function (x) { return x.id === id; })[0];
          if (!c) throw Erreur('compte-inconnu');
          // Personne ne se retire ses propres droits d'administration : sans cette
          // règle, un dernier administrateur pourrait fermer la porte de l'intérieur.
          if (c.id === moi.id && role !== 'admin') throw Erreur('pas-soi-meme');
          c.role = role;
          c.droits = role === 'admin' ? DROITS.slice()
            : (role === 'employe' ? (droits || []).filter(function (x) { return DROITS.indexOf(x) >= 0; }) : []);
          // L'identifiant client est conservé quel que soit le rôle : un employé peut
          // lui aussi recevoir des colis, et ses anciens colis gardent leur référence.
          if (!c.code) c.code = nouveauCode(d.comptes);
          ecrireDonnees(d);
          return plusTard(sansMdp(c));
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
          d.seqFacture += 1;
          var lignes = (champs.lignes || []).map(function (l) {
            return { libelle: texteCourt(l.libelle, 160), montant: Number(l.montant || 0) };
          });
          var total = champs.montant !== undefined && champs.montant !== ''
            ? Number(champs.montant)
            : lignes.reduce(function (a, l) { return a + l.montant; }, 0);
          var f = {
            id: identifiant(),
            numero: 'FAC-' + new Date().getFullYear() + '-' + String(d.seqFacture).padStart(4, '0'),
            client_id: champs.client_id,
            colis_id: champs.colis_id || null,
            montant: total,
            devise: texteCourt(champs.devise, 3).toUpperCase() || (CFG.devise || 'USD'),
            statut: champs.statut === 'payee' ? 'payee' : 'impayee',
            note: texteCourt(champs.note, 400),
            lignes: lignes,
            echeance_le: champs.echeance_le || null,
            cree_le: maintenant(),
            payee_le: champs.statut === 'payee' ? maintenant() : null
          };
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
          Object.keys(champs).forEach(function (k) {
            if (k === 'montant') f[k] = Number(champs[k] || 0);
            else if (k === 'lignes') f[k] = (champs[k] || []).map(function (l) {
              return { libelle: texteCourt(l.libelle, 160), montant: Number(l.montant || 0) };
            });
            else f[k] = champs[k];
          });
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
              { c: 0, desc: 'Chaussures de sport — 2 paires', exp: 'Amazon', poids: 4.2, service: 'aerien',
                etapes: [['confirme', 9, 'Entrepôt de Miami'], ['expedie', 6, 'Miami → Port-au-Prince'],
                         ['disponible', 2, 'Agence de Pétion-Ville', 'Retrait du lundi au samedi, 8 h – 18 h.']] },
              { c: 0, desc: 'Téléphone et accessoires', exp: 'Walmart', poids: 1.1, service: 'aerien',
                etapes: [['confirme', 2, 'Entrepôt de Miami']] },
              { c: 0, desc: 'Vêtements', exp: 'SHEIN', poids: 2.6, service: 'aerien',
                etapes: [['confirme', 22, 'Entrepôt de Miami'], ['expedie', 18, 'Miami → Port-au-Prince'],
                         ['disponible', 15, 'Agence de Pétion-Ville'], ['livre', 13, 'Pétion-Ville', 'Remis en main propre.']] },
              { c: 1, desc: 'Pièces automobiles (amortisseurs)', exp: 'RockAuto', poids: 18, service: 'maritime',
                etapes: [['confirme', 12, 'Entrepôt de Miami'], ['expedie', 7, 'Port de Miami → Caucedo']] },
              { c: 1, desc: 'Ordinateur portable', exp: 'Best Buy', poids: 5.4, service: 'aerien',
                etapes: [['confirme', 5, 'Entrepôt de Miami'], ['expedie', 3, 'Miami → Santo Domingo'],
                         ['action', 1, 'Douane de Santo Domingo', 'Facture d’achat demandée par la douane : envoyez-la-nous sur WhatsApp.']] }
            ];
            parcours.forEach(function (p) {
              var client = d.comptes.filter(function (c) { return c.id === ids[p.c]; })[0];
              var pays = client.pays === 'Haïti' ? 'HT' : 'DO';
              d.seqColis += 1;
              var c = {
                id: identifiant(), numero: 'SES-' + d.seqColis + '-' + pays, jeton: alea(10),
                client_id: client.id, description: p.desc, expediteur: p.exp,
                destinataire: client.nom_complet, poids_lb: p.poids, service: p.service,
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
            });

            [[0, 'payee', 46.5], [1, 'impayee', 128]].forEach(function (f, i) {
              d.seqFacture += 1;
              var client = d.comptes.filter(function (c) { return c.id === ids[f[0]]; })[0];
              var colisClient = d.colis.filter(function (c) { return c.client_id === client.id; })[0];
              d.factures.push({
                id: identifiant(),
                numero: 'FAC-' + new Date().getFullYear() + '-' + String(d.seqFacture).padStart(4, '0'),
                client_id: client.id, colis_id: colisClient ? colisClient.id : null,
                montant: f[2], devise: CFG.devise || 'USD', statut: f[1],
                note: '', lignes: [{ libelle: 'Transport ' + (colisClient ? colisClient.numero : ''), montant: f[2] }],
                echeance_le: null, cree_le: jours(10 - i * 4),
                payee_le: f[1] === 'payee' ? jours(6) : null
              });
            });

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
    admin: {}
  };

  /* ====================================================================== */
  var api = MODE === 'supabase' ? supabaseAPI : (MODE === 'demo' ? demoAPI : offAPI);

  api.mode = MODE;
  api.STATUTS = STATUTS;
  api.ETAPES = ETAPES;
  api.ROLES = ROLES;
  api.DROITS = DROITS;
  api.MDP_MINIMUM = MDP_MINIMUM;
  api.normaliserCode = normaliserCode;
  api.droitsDe = droitsDe;
  api.peut = peutFaire;
  api.avecWebCrypto = Empreinte.webcrypto;

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
