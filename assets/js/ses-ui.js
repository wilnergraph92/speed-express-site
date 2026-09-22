/* ==========================================================================
   Speed Express Shipping — affichage partagé de l'espace client
   --------------------------------------------------------------------------
   Ce que les deux tableaux de bord ont en commun : le vocabulaire des
   statuts, les dates, les montants, les messages, l'étiquette d'expédition
   (QR code + code-barres) et la facture imprimable.

   Les textes affichés sont écrits dans la page, dans un <template
   data-textes>, pour que le sélecteur de langue les traduise comme le reste :
   aucun texte visible n'est enfermé dans ce fichier.
   ========================================================================== */
(function () {
  'use strict';

  var CFG = window.SES_CONFIG || {};
  var API = window.SES_API;

  /* --- Textes de la page ------------------------------------------------- */
  var textes = null, langueLue = null;
  function t(cle, valeurs) {
    var langue = document.documentElement.lang || 'fr';
    if (!textes || langueLue !== langue) {
      textes = {};
      langueLue = langue;
      var modele = document.querySelector('template[data-textes]');
      if (modele) {
        Array.prototype.forEach.call(modele.content.querySelectorAll('[data-t]'), function (el) {
          textes[el.getAttribute('data-t')] = el.textContent.trim();
        });
      }
    }
    var s = textes[cle] === undefined ? '' : textes[cle];
    Object.keys(valeurs || {}).forEach(function (k) { s = s.split('{' + k + '}').join(valeurs[k]); });
    return s;
  }

  /* --- Statuts ----------------------------------------------------------- */
  var COULEURS = {
    confirme:   { fond: 'rgba(26,46,210,.10)',  trait: 'rgba(26,46,210,.30)',  texte: '#1a2ed2' },
    expedie:    { fond: 'rgba(32,36,42,.09)',   trait: 'rgba(32,36,42,.22)',   texte: '#20242a' },
    disponible: { fond: 'rgba(19,192,44,.12)',  trait: 'rgba(19,192,44,.35)',  texte: '#0b7a19' },
    livre:      { fond: 'rgba(11,122,25,.10)',  trait: 'rgba(11,122,25,.30)',  texte: '#0b7a19' },
    action:     { fond: 'rgba(232,18,27,.10)',  trait: 'rgba(232,18,27,.30)',  texte: '#e8121b' }
  };

  function nomStatut(statut) { return t('statut-' + statut) || statut; }

  function pastille(statut, options) {
    var c = COULEURS[statut] || COULEURS.expedie;
    var o = options || {};
    return '<span class="ses-pastille" style="display:inline-flex;align-items:center;gap:7px;' +
      'background:' + c.fond + ';border:1px solid ' + c.trait + ';color:' + c.texte + ';' +
      'border-radius:999px;padding:' + (o.petite ? '4px 11px' : '6px 14px') + ';' +
      'font-weight:700;font-size:' + (o.petite ? '12.5px' : '13.5px') + ';white-space:nowrap">' +
      '<span style="width:7px;height:7px;border-radius:50%;background:' + c.texte + ';flex:none"></span>' +
      echapper(nomStatut(statut)) + '</span>';
  }

  /* --- Dates et montants ------------------------------------------------- */
  var LOCALES = { fr: 'fr-FR', en: 'en-US', es: 'es-DO', ht: 'fr-FR' };
  function locale() { return LOCALES[(document.documentElement.lang || 'fr').slice(0, 2)] || 'fr-FR'; }

  function date(iso, avecHeure) {
    if (!iso) return '—';
    var d = new Date(iso);
    if (isNaN(d)) return '—';
    var options = { day: '2-digit', month: 'short', year: 'numeric' };
    if (avecHeure) { options.hour = '2-digit'; options.minute = '2-digit'; }
    try { return d.toLocaleDateString(locale(), options); }
    catch (e) { return d.toISOString().slice(0, avecHeure ? 16 : 10).replace('T', ' '); }
  }

  function montant(valeur, devise) {
    var n = Number(valeur || 0);
    var d = devise || CFG.devise || 'USD';
    try { return n.toLocaleString(locale(), { style: 'currency', currency: d, minimumFractionDigits: 2 }); }
    catch (e) { return d + ' ' + n.toFixed(2); }
  }

  function echapper(v) {
    return String(v === undefined || v === null ? '' : v)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  /* --- Messages ---------------------------------------------------------- */
  /* Un seul endroit pour les erreurs : le même code donne la même phrase
     partout, et une erreur oubliée ne laisse jamais l'écran muet. */
  function messageErreur(e) {
    var code = e && e.code ? e.code : 'inconnu';
    return t('erreur-' + code) || t('erreur-inconnu') || 'Une erreur est survenue.';
  }

  function annonce(zone, texte, genre) {
    if (!zone) return;
    if (!texte) { zone.hidden = true; zone.innerHTML = ''; return; }
    var couleurs = {
      erreur: ['rgba(232,18,27,.08)', 'rgba(232,18,27,.3)', '#b60d14'],
      succes: ['rgba(19,192,44,.10)', 'rgba(19,192,44,.35)', '#0b7a19'],
      info:   ['rgba(26,46,210,.07)', 'rgba(26,46,210,.25)', '#1a2ed2']
    }[genre || 'info'];
    zone.hidden = false;
    zone.setAttribute('role', genre === 'erreur' ? 'alert' : 'status');
    zone.style.cssText = 'background:' + couleurs[0] + ';border:1px solid ' + couleurs[1] +
      ';color:' + couleurs[2] + ';border-radius:12px;padding:14px 16px;font-size:15px;font-weight:600';
    zone.textContent = texte;
  }

  /* Erreur sous un champ, effacée dès que le visiteur corrige. */
  function erreurChamp(champ, texte) {
    if (!champ) return;
    var msg = champ.parentNode.querySelector('.ses-erreur');
    if (!msg) {
      msg = document.createElement('p');
      msg.className = 'ses-erreur';
      msg.style.cssText = 'margin:7px 0 0;font-size:13.5px;color:#e8121b;font-weight:600';
      champ.parentNode.appendChild(msg);
    }
    msg.textContent = texte;
    champ.setAttribute('aria-invalid', 'true');
    champ.addEventListener('input', function eff() {
      msg.remove();
      champ.removeAttribute('aria-invalid');
      champ.removeEventListener('input', eff);
    });
    champ.focus();
  }

  function effacerErreurs(form) {
    Array.prototype.forEach.call(form.querySelectorAll('.ses-erreur'), function (e) { e.remove(); });
    Array.prototype.forEach.call(form.querySelectorAll('[aria-invalid]'), function (e) {
      e.removeAttribute('aria-invalid');
    });
  }

  /* Bouton occupé : le libellé revient tel qu'il était, quoi qu'il arrive. */
  function occuper(bouton, texteAttente) {
    if (!bouton) return function () {};
    var avant = bouton.innerHTML;
    bouton.disabled = true;
    bouton.setAttribute('aria-busy', 'true');
    if (texteAttente) bouton.textContent = texteAttente;
    return function () {
      bouton.disabled = false;
      bouton.removeAttribute('aria-busy');
      bouton.innerHTML = avant;
    };
  }

  /* --- Étape du parcours (1 à 4 ; « action requise » garde l'étape atteinte) */
  function etapeDe(statut, historique) {
    if (statut !== 'action') return API.ETAPES[statut] || 1;
    var derniere = 1;
    (historique || []).forEach(function (h) {
      if (API.ETAPES[h.statut]) derniere = Math.max(derniere, API.ETAPES[h.statut]);
    });
    return derniere;
  }

  /* --- Codes du colis ----------------------------------------------------
     Le QR code mène à la page de suivi du colis, jeton compris : deux colis
     n'ont jamais la même adresse, et le jeton ne se devine pas. Le
     code-barres porte le numéro seul, celui que les scanners d'entrepôt
     lisent et que l'on retape à la main au besoin.                        */
  function lienSuivi(colis) {
    var base = CFG.siteUrl ? String(CFG.siteUrl).replace(/\/+$/, '') + '/' : '';
    if (!base) {
      try { base = new URL('.', location.href).href; } catch (e) { base = ''; }
    }
    return base + 'suivi.html?colis=' + encodeURIComponent(colis.numero) +
      (colis.jeton ? '&j=' + encodeURIComponent(colis.jeton) : '');
  }

  function qr(colis, taille) {
    if (!window.SES_CODES) return '';
    try { return window.SES_CODES.qrSVG(lienSuivi(colis), { taille: taille || 150, marge: 2 }); }
    catch (e) { return ''; }
  }

  function codeBarres(colis, options) {
    if (!window.SES_CODES) return '';
    try {
      return window.SES_CODES.code128SVG(colis.numero,
        { module: (options && options.module) || 2, hauteur: (options && options.hauteur) || 64, marge: 6 });
    } catch (e) { return ''; }
  }

  /* --- Impression --------------------------------------------------------
     Pas de fenêtre surgissante (les navigateurs les bloquent) : le document à
     imprimer est posé dans la page, le reste est masqué le temps de
     l'impression, puis tout revient en place.                              */
  /* Chrome et Safari n'attendent pas le chargement des images pour ouvrir la
     boîte d'impression : une étiquette lancée trop tôt sort sans son logo.
     On patiente donc, avec un délai de garde pour ne jamais bloquer. */
  function imagesPretes(boite) {
    var restantes = [].slice.call(boite.querySelectorAll('img')).filter(function (i) {
      return !i.complete || !i.naturalWidth;
    });
    if (!restantes.length) return Promise.resolve();
    return new Promise(function (fini) {
      var compte = restantes.length, sonne = false;
      var une = function () {
        if (!sonne && !--compte) { sonne = true; fini(); }
      };
      restantes.forEach(function (i) {
        i.addEventListener('load', une);
        i.addEventListener('error', une);
      });
      setTimeout(function () { if (!sonne) { sonne = true; fini(); } }, 2500);
    });
  }

  function imprimer(html, format) {
    var boite = document.getElementById('ses-impression');
    if (!boite) {
      boite = document.createElement('div');
      boite.id = 'ses-impression';
      document.body.appendChild(boite);
    }
    var style = document.getElementById('ses-impression-css');
    if (!style) {
      style = document.createElement('style');
      style.id = 'ses-impression-css';
      document.head.appendChild(style);
    }
    var page = format === 'etiquette' ? '@page{size:101.6mm 152.4mm;margin:4mm}' : '@page{size:A4;margin:14mm}';
    style.textContent = page + '\n' +
      '#ses-impression{display:none}\n' +
      '@media print{body>*{display:none !important}' +
      'body>#ses-impression{display:block !important}' +
      // Sans cette ligne, le navigateur laisse les aplats en blanc : le bandeau
      // noir de l'étiquette disparaîtrait, et son texte blanc avec lui.
      '#ses-impression,#ses-impression *{-webkit-print-color-adjust:exact;print-color-adjust:exact}' +
      'html,body{background:#fff !important;margin:0 !important}}';
    boite.innerHTML = html;
    var apres = function () {
      boite.innerHTML = '';
      window.removeEventListener('afterprint', apres);
    };
    imagesPretes(boite).then(function () {
      window.addEventListener('afterprint', apres);
      window.print();
      // Certains navigateurs n'émettent pas « afterprint » : filet de sécurité.
      setTimeout(function () { if (boite.innerHTML) apres(); }, 3000);
    });
  }

  /* --- Étiquette d'expédition -------------------------------------------- */
  function etiquette(colis) {
    var s = 'font-family:Manrope,system-ui,sans-serif;color:#0b0c0e';
    return '<div style="' + s + ';width:100%;border:2px solid #0b0c0e;border-radius:6px;overflow:hidden">' +
      '<div style="display:flex;align-items:center;justify-content:space-between;gap:10px;' +
      'background:#0b0c0e;color:#fff;padding:8px 10px">' +
        // Version monochrome du logo : une imprimante thermique n'imprime qu'en
        // noir, elle tramerait le rouge et le jaune en gris pointillé.
        '<span style="flex:none;background:#fff;border-radius:5px;padding:5px 8px;line-height:0">' +
          '<img src="assets/img/ses-logo-mono.png" alt="Speed Express Shipping" ' +
          'style="display:block;height:36px;width:auto">' +
        '</span>' +
        '<span style="font-size:11px;letter-spacing:.12em;text-align:right">' + echapper(t('etiquette-service-' + colis.service) || colis.service).toUpperCase() + '</span>' +
      '</div>' +

      '<div style="display:flex;gap:12px;padding:12px;border-bottom:1px dashed #9aa1ac">' +
        '<div style="flex:1;min-width:0">' +
          '<p style="margin:0 0 3px;font-size:9.5px;letter-spacing:.14em;color:#6b7280">' + echapper(t('etiquette-destinataire')) + '</p>' +
          '<p style="margin:0;font-size:16px;font-weight:800;line-height:1.25">' + echapper(colis.destinataire || colis.nom_client || '—') + '</p>' +
          '<p style="margin:3px 0 0;font-size:12.5px;line-height:1.45">' +
            echapper(colis.adresse_livraison || '') + (colis.adresse_livraison ? '<br>' : '') +
            echapper(colis.ville_destination || '') + ' · ' + echapper(colis.pays_destination || '') + '</p>' +
        '</div>' +
        '<div style="flex:none;text-align:center">' + qr(colis, 108) +
          '<p style="margin:2px 0 0;font-size:8.5px;color:#6b7280">' + echapper(t('etiquette-scanner')) + '</p>' +
        '</div>' +
      '</div>' +

      '<div style="display:flex;gap:10px;padding:10px 12px;font-size:11.5px;border-bottom:1px dashed #9aa1ac">' +
        '<span style="flex:1"><strong style="display:block;font-size:9.5px;letter-spacing:.12em;color:#6b7280">' +
          echapper(t('etiquette-client')) + '</strong>' + echapper(colis.code_client || '—') + '</span>' +
        '<span style="flex:1"><strong style="display:block;font-size:9.5px;letter-spacing:.12em;color:#6b7280">' +
          echapper(t('etiquette-poids')) + '</strong>' + (colis.poids_lb ? colis.poids_lb + ' lb' : '—') + '</span>' +
        '<span style="flex:1"><strong style="display:block;font-size:9.5px;letter-spacing:.12em;color:#6b7280">' +
          echapper(t('etiquette-date')) + '</strong>' + echapper(date(colis.cree_le)) + '</span>' +
      '</div>' +

      '<div style="padding:10px 12px;font-size:12px;border-bottom:1px dashed #9aa1ac;min-height:34px">' +
        '<strong style="display:block;font-size:9.5px;letter-spacing:.12em;color:#6b7280">' +
          echapper(t('etiquette-contenu')) + '</strong>' + echapper(colis.description || '—') + '</div>' +

      '<div style="padding:12px;text-align:center">' +
        '<div style="max-width:100%">' + codeBarres(colis, { module: 2, hauteur: 58 }) + '</div>' +
        '<p style="margin:5px 0 0;font-family:\'IBM Plex Mono\',monospace;font-size:16px;' +
        'font-weight:600;letter-spacing:.16em">' + echapper(colis.numero) + '</p>' +
      '</div>' +
    '</div>';
  }

  /* --- Facture imprimable ------------------------------------------------ */
  function facture(f, client, colis) {
    var lignes = (f.lignes && f.lignes.length ? f.lignes
      : [{ libelle: t('facture-ligne-transport', { numero: f.numero_colis || (colis && colis.numero) || '' }), montant: f.montant }]);
    var total = lignes.reduce(function (a, l) { return a + Number(l.montant || 0); }, 0) || Number(f.montant || 0);
    var paye = f.statut === 'payee';

    return '<div style="font-family:Manrope,system-ui,sans-serif;color:#0b0c0e;font-size:13px;line-height:1.55">' +
      '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:24px;' +
      'border-bottom:3px solid #e8121b;padding-bottom:14px">' +
        '<div><img src="assets/img/ses-logo.png" alt="Speed Express Shipping" ' +
        'style="display:block;height:46px;width:auto;margin:0 0 9px">' +
        '<p style="margin:0;font-size:12px;color:#4b5563">C. Fausto Cejas Rodriguez #89 k12, Las Américas<br>' +
        'Santo Domingo Este, ' + echapper(t('facture-pays')) + '<br>' +
        echapper(CFG.telephone || '') + ' · ' + echapper(CFG.email || '') + '</p></div>' +
        '<div style="text-align:right">' +
          '<p style="margin:0;font-family:Saira,Manrope,sans-serif;font-size:20px;font-weight:800">' +
            echapper(t('facture-titre')) + '</p>' +
          '<p style="margin:2px 0 0;font-family:\'IBM Plex Mono\',monospace;font-size:14px">' + echapper(f.numero) + '</p>' +
          '<p style="margin:6px 0 0;display:inline-block;border-radius:999px;padding:4px 12px;font-weight:700;font-size:12px;' +
            (paye ? 'background:rgba(19,192,44,.14);color:#0b7a19' : 'background:rgba(232,18,27,.12);color:#b60d14') + '">' +
            echapper(t(paye ? 'facture-payee' : 'facture-impayee')) + '</p>' +
        '</div>' +
      '</div>' +

      '<div style="display:flex;gap:28px;margin-top:18px">' +
        '<div style="flex:1"><p style="margin:0 0 4px;font-size:10px;letter-spacing:.12em;color:#6b7280">' +
          echapper(t('facture-client')) + '</p>' +
          '<p style="margin:0;font-weight:700">' + echapper((client && client.nom_complet) || f.nom_client || '—') + '</p>' +
          '<p style="margin:0;font-family:\'IBM Plex Mono\',monospace">' + echapper((client && client.code) || f.code_client || '—') + '</p>' +
          '<p style="margin:2px 0 0;color:#4b5563">' + echapper((client && client.email) || f.email_client || '') + '<br>' +
            echapper((client && client.telephone) || '') + '</p></div>' +
        '<div style="flex:1"><p style="margin:0 0 4px;font-size:10px;letter-spacing:.12em;color:#6b7280">' +
          echapper(t('facture-details')) + '</p>' +
          '<p style="margin:0">' + echapper(t('facture-emise')) + ' : ' + echapper(date(f.cree_le)) + '</p>' +
          (f.echeance_le ? '<p style="margin:0">' + echapper(t('facture-echeance')) + ' : ' + echapper(date(f.echeance_le)) + '</p>' : '') +
          (f.payee_le ? '<p style="margin:0">' + echapper(t('facture-reglee')) + ' : ' + echapper(date(f.payee_le)) + '</p>' : '') +
          ((f.numero_colis || (colis && colis.numero)) ? '<p style="margin:0">' + echapper(t('facture-colis')) + ' : ' +
            echapper(f.numero_colis || colis.numero) + '</p>' : '') +
        '</div>' +
      '</div>' +

      '<table style="width:100%;border-collapse:collapse;margin-top:20px">' +
        '<thead><tr style="background:#f5f6f8">' +
          '<th style="text-align:left;padding:9px 11px;font-size:10.5px;letter-spacing:.1em;color:#4b5563;border-bottom:1px solid #e2e5ea">' +
            echapper(t('facture-designation')) + '</th>' +
          '<th style="text-align:right;padding:9px 11px;font-size:10.5px;letter-spacing:.1em;color:#4b5563;border-bottom:1px solid #e2e5ea">' +
            echapper(t('facture-montant')) + '</th>' +
        '</tr></thead><tbody>' +
        lignes.map(function (l) {
          return '<tr><td style="padding:9px 11px;border-bottom:1px solid #eef0f3">' + echapper(l.libelle) + '</td>' +
            '<td style="padding:9px 11px;border-bottom:1px solid #eef0f3;text-align:right;' +
            'font-family:\'IBM Plex Mono\',monospace">' + echapper(montant(l.montant, f.devise)) + '</td></tr>';
        }).join('') +
        '</tbody><tfoot><tr>' +
          '<td style="padding:12px 11px;font-weight:800;font-size:15px">' + echapper(t('facture-total')) + '</td>' +
          '<td style="padding:12px 11px;text-align:right;font-weight:800;font-size:15px;' +
          'font-family:\'IBM Plex Mono\',monospace">' + echapper(montant(total, f.devise)) + '</td>' +
        '</tr></tfoot>' +
      '</table>' +

      (f.note ? '<p style="margin:16px 0 0;padding:11px 13px;background:#f5f6f8;border-radius:8px">' +
        echapper(f.note) + '</p>' : '') +
      '<p style="margin:26px 0 0;font-size:11px;color:#6b7280;border-top:1px solid #e2e5ea;padding-top:10px">' +
        echapper(t('facture-pied')) + '</p>' +
    '</div>';
  }

  /* Le sélecteur de langue traduit le texte déjà posé dans la page, mais pas
     les phrases que le JavaScript compose lui-même (« Marie Jean · Client »,
     « Statut de SES-10001-HT : Colis livré »). Les tableaux de bord se
     redessinent donc quand la langue change. */
  function surLangue(rappel) {
    var langue = document.documentElement.lang;
    if (!window.MutationObserver) return;
    new MutationObserver(function () {
      var maintenant = document.documentElement.lang;
      if (maintenant === langue) return;
      langue = maintenant;
      rappel(maintenant);
    }).observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
  }

  /* --- Petits outils de gabarit ------------------------------------------ */
  function vide(message, icone) {
    return '<div style="text-align:center;padding:42px 20px;color:#6b7280">' +
      '<p style="margin:0;font-size:34px;opacity:.5">' + (icone || '□') + '</p>' +
      '<p style="margin:8px 0 0;font-size:15px">' + echapper(message) + '</p></div>';
  }

  function ligneHistorique(h, options) {
    var c = COULEURS[h.statut] || COULEURS.expedie;
    var o = options || {};
    return '<li style="position:relative;padding:0 0 18px 26px;border-left:2px solid ' +
      (o.dernier ? 'transparent' : '#e2e5ea') + '">' +
      '<span style="position:absolute;left:-7px;top:3px;width:12px;height:12px;border-radius:50%;' +
      'background:' + c.texte + ';box-shadow:0 0 0 3px #fff"></span>' +
      '<p style="margin:0;font-weight:700;font-size:14.5px;color:' + c.texte + '">' + echapper(nomStatut(h.statut)) + '</p>' +
      '<p style="margin:1px 0 0;font-size:13px;color:#6b7280">' + echapper(date(h.cree_le, true)) +
        (h.lieu ? ' · ' + echapper(h.lieu) : '') + '</p>' +
      (h.note ? '<p style="margin:5px 0 0;font-size:13.5px">' + echapper(h.note) + '</p>' : '') +
      '</li>';
  }

  window.SES_UI = {
    t: t,
    surLangue: surLangue,
    echapper: echapper,
    nomStatut: nomStatut,
    pastille: pastille,
    couleurStatut: function (s) { return COULEURS[s] || COULEURS.expedie; },
    date: date,
    montant: montant,
    messageErreur: messageErreur,
    annonce: annonce,
    erreurChamp: erreurChamp,
    effacerErreurs: effacerErreurs,
    occuper: occuper,
    etapeDe: etapeDe,
    lienSuivi: lienSuivi,
    qr: qr,
    codeBarres: codeBarres,
    imprimer: imprimer,
    etiquette: etiquette,
    facture: facture,
    vide: vide,
    ligneHistorique: ligneHistorique
  };
})();
