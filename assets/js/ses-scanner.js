/* ==========================================================================
   Speed Express Shipping — ScannerService
   --------------------------------------------------------------------------
   Une seule abstraction pour tous les lecteurs : caméra du téléphone, QR, code-barres, scanner
   USB (qui se comporte comme un clavier), poste de bureau, saisie à la main. Le métier
   (public.lg_scan_parcel) reçoit toujours la même chose — un texte, un genre, un appareil — et ne
   sait pas, et n'a pas à savoir, quel lecteur l'a lu.

   Brancher un nouveau lecteur = écrire un « adaptateur » (un nom, démarrer(emettre), arreter()).
   Rien d'autre ne change : ni le service, ni le métier, ni la base.

   JavaScript ES5, sans dépendance : il se copie tel quel dans l'application Opérations (Expo/React
   Native) et dans le bureau (navigateur). Il se teste seul : outils/tests/scanner.cjs.
   ========================================================================== */
(function (racine, fabrique) {
  if (typeof module === 'object' && module.exports) module.exports = fabrique();
  else racine.SES_SCANNER = fabrique();
}(this, function () {
  'use strict';

  var GENRES = ['barcode', 'qr', 'manual', 'rfid', 'unknown'];

  function maintenantParDefaut() { return Date.now(); }

  /* Ce que la base accepte de lire : on nettoie ici ce qui vient d'un lecteur capricieux
     (retour chariot, espaces, caractères de contrôle), sans jamais deviner le contenu. */
  function normaliser(brut, longueurMin, longueurMax) {
    if (brut === null || brut === undefined) return null;
    var t = String(brut).replace(/[\u0000-\u001f\u007f]/g, '').replace(/^\s+|\s+$/g, '');
    if (t.length < (longueurMin || 4) || t.length > (longueurMax || 500)) return null;
    return t;
  }

  function hachage(texte) {            // empreinte courte et stable (pas de sécurité : une clé d'idempotence)
    var h = 5381;
    for (var i = 0; i < texte.length; i++) h = ((h << 5) + h + texte.charCodeAt(i)) | 0;
    return (h >>> 0).toString(36);
  }

  /* --- Le service ------------------------------------------------------------------------------ */
  function creerService(options) {
    var o = options || {};
    var maintenant = o.maintenant || maintenantParDefaut;
    var fenetre = o.debounceMs === undefined ? 1500 : o.debounceMs;
    var longueurMin = o.longueurMin || 4, longueurMax = o.longueurMax || 500;
    var appareilId = o.appareilId || null;
    var adaptateurs = [], abonnes = [], abonnesErreur = [];
    var demarre = false, dernier = {}, ignorees = 0, recues = 0;

    function erreur(e, source) {
      for (var i = 0; i < abonnesErreur.length; i++) { try { abonnesErreur[i](e, source); } catch (x) { /* une erreur dans un abonné d'erreurs n'en provoque pas d'autre */ } }
    }

    /* Un lecteur a lu quelque chose. */
    function emettre(brut, genre, source) {
      if (!demarre) return false;
      var code = normaliser(brut, longueurMin, longueurMax);
      if (code === null) { ignorees++; return false; }
      var t = maintenant();
      // Une caméra voit le même QR sur vingt images de suite : un même code, tous lecteurs confondus,
      // ne compte qu'une fois par fenêtre.
      if (dernier[code] !== undefined && t - dernier[code] < fenetre) { ignorees++; return false; }
      dernier[code] = t;
      recues++;
      var lecture = { code: code, genre: GENRES.indexOf(genre) >= 0 ? genre : 'unknown', source: source || 'inconnu', appareilId: appareilId, horodatage: t };
      for (var i = 0; i < abonnes.length; i++) { try { abonnes[i](lecture); } catch (e) { erreur(e, source); } }
      return true;
    }

    var service = {
      ajouterAdaptateur: function (a) {
        if (!a || typeof a.demarrer !== 'function' || typeof a.arreter !== 'function') throw new Error('Adaptateur invalide : demarrer() et arreter() sont obligatoires.');
        adaptateurs.push(a);
        if (demarre) a.demarrer(function (code, genre) { return emettre(code, genre, a.nom); });
        return service;
      },
      surLecture: function (cb) { abonnes.push(cb); return function () { var i = abonnes.indexOf(cb); if (i >= 0) abonnes.splice(i, 1); }; },
      surErreur: function (cb) { abonnesErreur.push(cb); return service; },
      demarrer: function () {
        if (demarre) return service;
        demarre = true;
        adaptateurs.forEach(function (a) { try { a.demarrer(function (code, genre) { return emettre(code, genre, a.nom); }); } catch (e) { erreur(e, a.nom); } });
        return service;
      },
      arreter: function () {
        demarre = false;
        adaptateurs.forEach(function (a) { try { a.arreter(); } catch (e) { erreur(e, a.nom); } });
        return service;
      },
      /* Saisie à la main : même chemin que n'importe quel lecteur. */
      soumettre: function (code) { return emettre(code, 'manual', 'manuel'); },
      oublier: function () { dernier = {}; },
      statistiques: function () { return { recues: recues, ignorees: ignorees, adaptateurs: adaptateurs.length, demarre: demarre }; }
    };
    return service;
  }

  /* --- Ce qu'on envoie à la base ------------------------------------------------------------------ */
  /* La clé d'idempotence se déduit de la lecture : si le réseau coupe et que l'application renvoie la
     MÊME lecture, la base reconnaît la même clé et ne compte pas le scan deux fois. */
  function argumentsRpc(lecture, contexte) {
    return {
      p_code: lecture.code,
      p_purpose: contexte.intention,
      p_warehouse_id: contexte.entrepotId,
      p_location_id: contexte.emplacementId || null,
      p_device_id: lecture.appareilId || null,
      p_code_kind: lecture.genre,
      p_idempotency_key: 'sc-' + (lecture.appareilId || 'x') + '-' + lecture.horodatage + '-' + hachage(lecture.code + '|' + contexte.intention)
    };
  }

  /* --- Adaptateurs --------------------------------------------------------------------------------- */

  /* Scanner USB ou Bluetooth « clavier » : il tape le code très vite puis appuie sur Entrée. Un humain
     ne tape pas à moins de 50 ms par touche : c'est ce qui permet de distinguer les deux. */
  function adaptateurClavier(cible, opts) {
    var p = opts || {};
    var delaiMax = p.delaiMaxMs || 50, longueurMin = p.longueurMin || 4;
    var terminateurs = p.terminateurs || ['Enter', 'Tab'];
    var maintenant = p.maintenant || maintenantParDefaut;
    var tampon = '', dernierT = 0, ecoute = null, emettre = null;

    function surTouche(ev) {
      var t = maintenant();
      var touche = ev.key;
      if (tampon !== '' && t - dernierT > delaiMax) tampon = '';           // trop lent : c'est une frappe humaine
      dernierT = t;
      if (terminateurs.indexOf(touche) >= 0) {
        var code = tampon; tampon = '';
        if (code.length >= longueurMin && emettre) emettre(code, 'barcode');
        return;
      }
      if (touche && touche.length === 1) tampon += touche;
    }
    return {
      nom: 'clavier',
      demarrer: function (e) { emettre = e; ecoute = surTouche; cible.addEventListener('keydown', ecoute); },
      arreter: function () { if (ecoute) cible.removeEventListener('keydown', ecoute); ecoute = null; emettre = null; tampon = ''; }
    };
  }

  /* Caméra : un « détecteur » (BarcodeDetector du navigateur, ou la bibliothèque de la caméra d'Expo)
     reçoit une image et rend une liste de { rawValue, format }. Le service n'a pas à savoir lequel. */
  function adaptateurCamera(detecteur) {
    var emettre = null;
    return {
      nom: 'camera',
      demarrer: function (e) { emettre = e; },
      arreter: function () { emettre = null; },
      /* L'application appelle ceci pour chaque image de la caméra. */
      image: function (image) {
        if (!emettre) return Promise.resolve([]);
        return Promise.resolve(detecteur.detect(image)).then(function (trouves) {
          (trouves || []).forEach(function (t) { emettre(t.rawValue, /qr/i.test(t.format || '') ? 'qr' : 'barcode'); });
          return trouves || [];
        });
      }
    };
  }

  /* Un lecteur quelconque qu'on pilote à la main : tests, lecteurs RFID, futurs matériels. */
  function adaptateurProgrammable(nom, genre) {
    var emettre = null;
    return {
      nom: nom,
      demarrer: function (e) { emettre = e; },
      arreter: function () { emettre = null; },
      lire: function (code) { return emettre ? emettre(code, genre || 'unknown') : false; }
    };
  }

  return { creerService: creerService, normaliser: normaliser, argumentsRpc: argumentsRpc,
           adaptateurClavier: adaptateurClavier, adaptateurCamera: adaptateurCamera, adaptateurProgrammable: adaptateurProgrammable };
}));
