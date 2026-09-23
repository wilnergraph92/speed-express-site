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

  /* --- Textes de la page -------------------------------------------------
     Le sélecteur de langue traduit le contenu du gabarit, mais il le fait
     après avoir chargé ses dictionnaires — donc parfois après que le tableau
     de bord se soit déjà dessiné. Sans surveillance, le premier appel fait
     avant la traduction figerait le français pour toute la visite, sur une
     page ouverte directement en anglais. On observe donc le gabarit : quand
     il change, le cache tombe et ce qui est déjà affiché est redessiné. */
  var textes = null, langueLue = null, surveille = false;
  var abonnes = [];

  function surveillerGabarit(modele) {
    if (surveille || !modele || !window.MutationObserver) return;
    surveille = true;
    new MutationObserver(function () {
      textes = null;
      abonnes.forEach(function (rappel) {
        try { rappel(document.documentElement.lang); } catch (e) { /* un abonné fautif n'arrête pas les autres */ }
      });
    }).observe(modele.content, { childList: true, subtree: true, characterData: true });
  }

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
        surveillerGabarit(modele);
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

  /* Le pays est rangé en deux lettres, parce que le numéro du colis s'en sert
     (SES-10001-HT). Partout où on le montre, on écrit son nom en entier. */
  function nomPays(code) { return code ? (t('pays-' + code) || code) : ''; }

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

  /* Un poids s'écrit « 4,2 » et non « 4,20 » : deux décimales seulement quand
     elles servent. */
  function nombre(valeur) {
    var n = Number(valeur || 0);
    try { return n.toLocaleString(locale(), { maximumFractionDigits: 2 }); }
    catch (e) { return String(Math.round(n * 100) / 100); }
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
    /* Marges de page à zéro, et les marges vraies posées à l'intérieur.
       Ce n'est pas un détail de mise en page : tant que @page garde une
       marge, le navigateur y imprime ses propres en-têtes — la date, le
       titre de l'onglet (« Tableau de bord — Speed Express Shipping »),
       l'adresse du site et le numéro de page. Rien de tout cela n'a sa
       place sur une facture remise au client. À zéro, il n'a plus la place
       de les écrire et les abandonne. */
    var page = format === 'etiquette'
      ? '@page{size:101.6mm 152.4mm;margin:0}\n#ses-impression{padding:4mm}'
      : '@page{size:A4;margin:0}\n#ses-impression{padding:14mm}';
    style.textContent = page + '\n' +
      '#ses-impression{display:none}\n' +
      '@media print{body>*{display:none !important}' +
      'body>#ses-impression{display:block !important}' +
      // La facture occupe toute la hauteur utile (297 mm moins les marges),
      // ce qui envoie son pied de page au bas du papier plutôt qu'à la suite
      // du tableau.
      (format === 'etiquette' ? '' :
        '.ses-facture-page{min-height:269mm;display:flex;flex-direction:column}' +
        '.ses-facture-pied{margin-top:auto !important}') +
      // Sans cette ligne, le navigateur laisse les aplats en blanc : la facture
      // perdrait l'en-tête de son tableau et sa pastille « payée / impayée ».
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
  function lieuLivraison(colis) {
    return [colis.ville_destination, nomPays(colis.pays_destination)]
      .filter(Boolean).join(' · ');
  }

  /* Le destinataire n'est pas toujours le titulaire du compte : le colis porte
     son propre numéro. Vide, on retombe sur celui du client, qui est le cas
     courant — c'est lui qui vient chercher son colis. */
  function telephoneDestinataire(colis) {
    return colis.telephone_destinataire || colis.telephone_client || '';
  }

  function etiquette(colis) {
    var s = 'font-family:Manrope,system-ui,sans-serif;color:#0b0c0e';
    return '<div style="' + s + ';width:100%;border:2px solid #0b0c0e;border-radius:6px;overflow:hidden">' +
      // En-tête sans aplat : le logo monochrome se suffit, et une imprimante
      // thermique sort un trait net là où elle peinait sur un grand à-plat noir.
      '<div style="display:flex;align-items:center;justify-content:space-between;gap:10px;' +
      'padding:11px 12px;border-bottom:2px solid #0b0c0e">' +
        '<img src="assets/img/ses-logo-mono.png" alt="Speed Express Shipping" ' +
        'style="display:block;height:38px;width:auto;flex:none">' +
        '<span style="font-size:11px;font-weight:700;letter-spacing:.12em;text-align:right">' + echapper(t('etiquette-service-' + colis.service) || colis.service).toUpperCase() + '</span>' +
      '</div>' +

      '<div style="display:flex;gap:12px;padding:12px;border-bottom:1px dashed #9aa1ac">' +
        '<div style="flex:1;min-width:0">' +
          '<p style="margin:0 0 3px;font-size:9.5px;letter-spacing:.14em;color:#6b7280">' + echapper(t('etiquette-destinataire')) + '</p>' +
          '<p style="margin:0;font-size:16px;font-weight:800;line-height:1.25">' + echapper(colis.destinataire || colis.nom_client || '—') + '</p>' +
          // Le livreur appelle avant de se déplacer : le numéro passe devant
          // l'adresse postale, qui reste dans la fiche du colis.
          (telephoneDestinataire(colis)
            ? '<p style="margin:5px 0 0;font-size:15.5px;font-weight:800;letter-spacing:.01em">' +
              '<span style="font-size:9.5px;font-weight:700;letter-spacing:.12em;color:#6b7280">' +
              echapper(t('etiquette-tel')) + '</span> ' + echapper(telephoneDestinataire(colis)) + '</p>'
            : '') +
          // La ville et le pays : le séparateur ne s'affiche que si les deux
          // sont renseignés.
          '<p style="margin:4px 0 0;font-size:13.5px;font-weight:700;line-height:1.35">' +
            echapper(lieuLivraison(colis)) + '</p>' +
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

  /* --- Facture imprimable ------------------------------------------------
     Une facture ne recalcule rien à partir des colis : elle lit ses propres
     lignes, figées au moment de la facturation. C'est ce qui garantit qu'un
     tarif changé demain ne réécrit pas une facture d'hier. */

  function totauxFacture(f, colis) {
    var lignes = lignesFacture(f, colis);
    var colis = lignes.reduce(function (a, l) { return a + Number(l.montant || 0); }, 0);
    var frais = Number(f.frais_service || 0);
    var grand = Math.round((colis + frais) * 100) / 100;
    var paye = Number(f.montant_paye || 0);
    return {
      lignes: lignes, colis: Math.round(colis * 100) / 100, frais: frais, grand: grand,
      paye: paye, balance: Math.round((grand - paye) * 100) / 100
    };
  }

  /* Les factures écrites avant la facturation au poids ne portent pas le poids
     dans leurs lignes : elles afficheraient un tiret. Quand le colis est sous
     la main, on va le chercher chez lui plutôt que d'inventer une valeur. Le
     montant, lui, n'est jamais recalculé — une facture ancienne garde le sien. */
  function indexerColis(colis) {
    var index = {};
    if (!colis) return index;
    (colis.length === undefined ? [colis] : colis).forEach(function (c) {
      if (!c) return;
      if (c.id) index[c.id] = c;
      if (c.numero) index[c.numero] = c;
    });
    return index;
  }

  function lignesFacture(f, colis) {
    var index = indexerColis(colis);
    var seul = f.colis_id ? index[f.colis_id] : null;
    return (f.lignes || []).map(function (l) {
      var c = index[l.colis_id] || index[l.numero] || seul || null;
      return {
        numero: l.numero || (c ? c.numero : '') || '',
        description: l.description === undefined ? (l.libelle || '') : l.description,
        quantite: Number(l.quantite || 1),
        poids_lb: Number(l.poids_lb || (c ? c.poids_lb : 0) || 0),
        tarif_lb: Number(l.tarif_lb || (c ? c.tarif_lb : 0) || 0),
        montant: Number(l.montant || 0)
      };
    });
  }

  /* Plusieurs colis d'un même client sur une seule facture : les lignes sont
     reprises telles quelles — chaque colis garde donc son propre tarif — et
     les frais de service ne sont comptés qu'une fois. */
  function regrouper(factures, devise, colis) {
    var lignes = [], paye = 0, frais = 0, numeros = [];
    factures.forEach(function (f) {
      lignes = lignes.concat(lignesFacture(f, colis));
      paye += Number(f.montant_paye || 0);
      frais = Math.max(frais, Number(f.frais_service || 0));
      if (f.numero) numeros.push(f.numero);
    });
    var colis = lignes.reduce(function (a, l) { return a + Number(l.montant || 0); }, 0);
    return {
      numero: numeros.join(' · '), groupee: true, lignes: lignes,
      frais_service: frais, montant_paye: paye,
      montant: Math.round((colis + frais) * 100) / 100,
      devise: devise || (factures[0] && factures[0].devise) || CFG.devise || 'USD',
      statut: paye >= colis + frais && colis + frais > 0 ? 'payee' : 'impayee',
      cree_le: new Date().toISOString()
    };
  }

  function ligneTotal(libelle, valeur, options) {
    var o = options || {};
    return '<tr>' +
      '<td style="padding:' + (o.fort ? '9px 11px' : '5px 11px') + ';text-align:right;' +
        (o.fort ? 'font-weight:800;font-size:15px;' : 'color:#4b5563;') +
        (o.trait ? 'border-top:1px solid #e2e5ea;' : '') + '">' + echapper(libelle) + '</td>' +
      '<td style="padding:' + (o.fort ? '9px 11px' : '5px 11px') + ';text-align:right;width:34%;' +
        'font-family:\'IBM Plex Mono\',monospace;' +
        (o.fort ? 'font-weight:800;font-size:15px;' : '') +
        (o.trait ? 'border-top:1px solid #e2e5ea;' : '') +
        (o.couleur ? 'color:' + o.couleur + ';' : '') + '">' + echapper(valeur) + '</td></tr>';
  }

  function facture(f, client, colis) {
    var T = totauxFacture(f, colis);
    var paye = f.statut === 'payee' || T.balance <= 0;
    var devise = f.devise;

    // « ses-facture-page » sert à l'impression : la feuille de style posée par
    // imprimer() s'en sert pour pousser le pied de page au bas du papier.
    return '<div class="ses-facture-page" style="font-family:Manrope,system-ui,sans-serif;' +
      'color:#0b0c0e;font-size:13px;line-height:1.55">' +

      /* --- En-tête ------------------------------------------------------- */
      '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:24px;' +
      'border-bottom:3px solid #e8121b;padding-bottom:14px">' +
        '<div><img src="assets/img/ses-logo.png" alt="Speed Express Shipping" ' +
        'style="display:block;height:46px;width:auto;margin:0 0 9px">' +
        '<p style="margin:0;font-size:12px;color:#4b5563">' + echapper(CFG.factureAdresse || '') + '<br>' +
        echapper(t('facture-tel')) + ' ' + echapper(CFG.factureTelephone || '') +
        ' · ' + echapper(t('facture-rnc')) + ' ' + echapper(CFG.factureRNC || '') + '</p></div>' +
        '<div style="text-align:right">' +
          '<p style="margin:0;font-family:Saira,Manrope,sans-serif;font-size:20px;font-weight:800">' +
            echapper(t('facture-titre')) + '</p>' +
          '<p style="margin:2px 0 0;font-family:\'IBM Plex Mono\',monospace;font-size:13px">' + echapper(f.numero) + '</p>' +
          '<p style="margin:6px 0 0;display:inline-block;border-radius:999px;padding:4px 12px;font-weight:700;font-size:12px;' +
            (paye ? 'background:rgba(19,192,44,.14);color:#0b7a19' : 'background:rgba(232,18,27,.12);color:#b60d14') + '">' +
            echapper(t(paye ? 'facture-payee' : 'facture-impayee')) + '</p>' +
        '</div>' +
      '</div>' +

      /* --- Client et dates ----------------------------------------------- */
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
          ((f.numero_colis || (colis && colis.numero)) && !f.groupee ? '<p style="margin:0">' + echapper(t('facture-colis')) + ' : ' +
            echapper(f.numero_colis || colis.numero) + '</p>' : '') +
          (f.groupee ? '<p style="margin:0">' + echapper(t('facture-nb-colis', { nombre: T.lignes.length })) + '</p>' : '') +
        '</div>' +
      '</div>' +

      /* --- Le détail, colis par colis ------------------------------------ */
      '<table style="width:100%;border-collapse:collapse;margin-top:20px">' +
        '<thead><tr style="background:#f5f6f8">' +
        // Le tarif au livre reste dans les données et dans le calcul, mais il
        // ne s'imprime pas : le client paie un montant, pas un barème.
        ['facture-quantite', 'facture-poids', 'facture-designation', 'facture-montant']
          .map(function (cle, i) {
            return '<th style="text-align:' + (i === 2 ? 'left' : 'right') + ';padding:9px 11px;font-size:10.5px;' +
              'letter-spacing:.08em;color:#4b5563;border-bottom:1px solid #e2e5ea;white-space:nowrap">' +
              echapper(t(cle)) + '</th>';
          }).join('') +
        '</tr></thead><tbody>' +
        T.lignes.map(function (l) {
          var c = 'padding:9px 11px;border-bottom:1px solid #eef0f3;';
          var m = 'font-family:\'IBM Plex Mono\',monospace;text-align:right;';
          return '<tr>' +
            '<td style="' + c + m + '">' + echapper(l.quantite || 1) + '</td>' +
            '<td style="' + c + m + '">' + (l.poids_lb ? echapper(nombre(l.poids_lb)) : '—') + '</td>' +
            '<td style="' + c + '">' + echapper(l.description || '—') +
              (l.numero ? '<br><span style="font-family:\'IBM Plex Mono\',monospace;font-size:11.5px;color:#6b7280">' +
                echapper(l.numero) + '</span>' : '') + '</td>' +
            '<td style="' + c + m + '">' + echapper(montant(l.montant, devise)) + '</td></tr>';
        }).join('') +
        '</tbody></table>' +

      /* --- Les totaux ----------------------------------------------------- */
      '<div style="display:flex;justify-content:flex-end;margin-top:14px">' +
        '<table style="border-collapse:collapse;min-width:290px">' +
          ligneTotal(t('facture-total-colis'), montant(T.colis, devise)) +
          ligneTotal(t('facture-frais'), montant(T.frais, devise)) +
          ligneTotal(t('facture-grand-total'), montant(T.grand, devise), { fort: true, trait: true }) +
          ligneTotal(t('facture-paye'), montant(T.paye, devise)) +
          ligneTotal(t('facture-balance'), montant(T.balance, devise),
            { fort: true, trait: true, couleur: T.balance > 0 ? '#b60d14' : '#0b7a19' }) +
        '</table>' +
      '</div>' +

      (f.note ? '<p style="margin:16px 0 0;padding:11px 13px;background:#f5f6f8;border-radius:8px">' +
        echapper(f.note) + '</p>' : '') +

      /* --- Signature ------------------------------------------------------
         L'image apparaît dès qu'elle est déposée ; sans elle, il reste le
         trait à signer à la main. */
      '<div style="display:flex;justify-content:flex-end;margin-top:34px">' +
        '<div style="width:250px;text-align:center">' +
          '<img src="assets/img/ses-signature.png" alt="" ' +
          'style="display:block;height:64px;width:auto;margin:0 auto 2px;object-fit:contain" ' +
          'onerror="this.style.visibility=\'hidden\'">' +
          '<div style="border-top:1px solid #0b0c0e;padding-top:6px;font-size:11.5px;' +
          'letter-spacing:.1em;color:#4b5563">' + echapper(t('facture-signature')) + '</div>' +
        '</div>' +
      '</div>' +

      /* --- Pied de page ----------------------------------------------------
         Une ligne, et rien d'autre : l'adresse, le téléphone et le RNC sont
         déjà en tête. À l'impression, la règle « ses-facture-pied » le pousse
         au bas de la feuille. */
      '<div class="ses-facture-pied" style="margin:30px 0 0;border-top:1px solid #e2e5ea;' +
        'padding-top:12px;text-align:center;font-size:12.5px;color:#4b5563">' +
        echapper(t('facture-pied')) +
      '</div>' +
    '</div>';
  }

  /* Le sélecteur de langue traduit le texte déjà posé dans la page, mais pas
     les phrases que le JavaScript compose lui-même (« Marie Jean · Client »,
     « Statut de SES-10001-HT : Colis livré »). Les tableaux de bord se
     redessinent donc quand la langue change. */
  function surLangue(rappel) {
    var langue = document.documentElement.lang;
    if (!window.MutationObserver) return;
    abonnes.push(rappel);
    surveillerGabarit(document.querySelector('template[data-textes]'));
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
    nombre: nombre,
    totauxFacture: totauxFacture,
    lignesFacture: lignesFacture,
    indexerColis: indexerColis,
    regrouper: regrouper,
    nomPays: nomPays,
    lieuLivraison: lieuLivraison,
    telephoneDestinataire: telephoneDestinataire,
    imprimer: imprimer,
    etiquette: etiquette,
    facture: facture,
    vide: vide,
    ligneHistorique: ligneHistorique
  };
})();
