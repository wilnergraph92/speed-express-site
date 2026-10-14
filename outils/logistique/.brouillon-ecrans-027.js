
  /* ====================================================================== tarifs, devis, préparation de la bascule (étapes 007, 018, 027)
     Le noyau calcule chaque prix ; le navigateur n'additionne rien (finance-navigateur.cjs). Tant que la bascule n'est pas faite,
     l'ANCIENNE facturation reste la seule source de l'argent : ces écrans configurent les prix, font des devis et préparent la bascule,
     ils n'émettent aucune facture et n'encaissent rien. La bascule elle-même n'est pas proposée ici. */
  var DEVISES_PRIX = ['USD', 'DOP', 'HTG'];
  var PAYS_PRIX = ['HT', 'DO', 'US'];
  var ASSIETTES_TAXE = ['FREIGHT', 'SURCHARGE', 'SERVICE_FEE', 'ALL'];
  var VERDICTS_BLOQUANTS = ['UNEXPLAINED', 'NO_PRICING', 'SERVICE_FEE', 'NO_PARCEL', 'CURRENCY'];
  var etatTarifs = { d: null };
  function argent(v, devise) { return v === null || v === undefined ? '—' : (C.montant ? C.montant(v, devise) : String(v)); }
  function nombreSaisi(v) { var s = String(v === undefined || v === null ? '' : v).trim().replace(',', '.'); return s === '' ? null : Number(s); }
  function peutFacturer() { var a = accesTableau(); return !!(a && (a.finance || a.direction)); }
  function actifBouton(genre, id, actif, code) { return bouton('prix-actif', actif ? 'c-site-desactiver' : 'c-site-reactiver', { genre: genre, id: id, actif: actif, code: code }); }

  function dessinerTarifs(zone, d) {
    etatTarifs.d = d;
    var g = !!(d && d.can_manage), manque = (d.coverage || []).filter(function (c) { return !c.rate_card; });
    zone.innerHTML = '<p class="cc-intro">' + e(t('c-prix-intro')) + '</p>' +
      '<p>' + pastille('c-prix-mode-' + d.finance_mode, d.finance_mode === 'core' ? 'ACTIVE' : 'PENDING') + ' <span class="cc-petit">' + e(t('c-prix-mode-aide-' + d.finance_mode)) + '</span></p>' +
      (g ? '<div class="cc-barre-actions">' + bouton('prix-grille', 'c-prix-g-grille', null, true) + bouton('prix-zone', 'c-prix-g-zone', null) + bouton('prix-taxe', 'c-prix-g-taxe', null) +
           bouton('prix-change', 'c-prix-g-change', null) + '</div>' : '') +
      '<h3>' + e(t('c-prix-couverture')) + '</h3>' +
      (manque.length ? '<p class="cc-form-msg">' + e(t('c-prix-manque', { n: nombre(manque.length) })) + '</p>' : '') +
      ((d.coverage || []).length ? C.tableau([
        { t: 'c-exp-mode', rendre: function (c) { return e(t('c-svc-' + c.mode)); } },
        { t: 'c-col-destination', rendre: function (c) { return e(C.pays ? C.pays(c.country) : c.country); } },
        { t: 'c-col-colis', rendre: function (c) { return e(nombre(c.parcels)); } },
        { t: 'c-prix-zone', rendre: function (c) { return c.zone ? '<span class="ses-mono">' + e(c.zone) + '</span>' : pastille('c-prix-manquante', 'PENDING'); } },
        { t: 'c-prix-grille-du-jour', rendre: function (c) { return c.rate_card ? '<span class="ses-mono">' + e(c.rate_card) + '</span>' : pastille('c-prix-manquante', 'PENDING'); } }
      ], d.coverage, { legende: 'c-prix-couverture' }) : '<p class="cc-rien">' + e(t('c-prix-aucun-colis')) + '</p>') +
      '<h3>' + e(t('c-prix-grilles')) + '</h3>' +
      ((d.rate_cards || []).length ? (d.rate_cards || []).map(function (r) {
        return '<section class="cc-carte cc-site"><div class="cc-site-tete"><div><h3><span class="ses-mono">' + e(r.code) + '</span>' + (r.name ? ' · ' + e(r.name) : '') + '</h3>' +
          '<p class="cc-petit">' + e(t('c-svc-' + r.mode)) + ' · ' + e(r.zone.code) + ' (' + e(C.pays ? C.pays(r.zone.country) : r.zone.country) + ') · ' + e(r.currency) + ' · ' +
          e(t('c-prix-validite', { du: jour(r.valid_from), au: r.valid_to ? jour(r.valid_to) : '…' })) + (r.lb_per_ft3 ? ' · ' + e(t('c-prix-volumetrique', { n: nombre(r.lb_per_ft3) })) : '') + ' ' +
          (r.current ? pastille('c-prix-du-jour', 'ACTIVE') : actifPastille(r.active)) + '</p></div>' +
          (g ? '<div class="cc-site-actions">' + actifBouton('rate_card', r.rate_card_id, r.active, r.code) + '</div>' : '') + '</div>' +
          C.tableau([
            { t: 'c-prix-tranche', rendre: function (b) { return e(b.max_lb === null || b.max_lb === undefined ? t('c-prix-tranche-plus', { de: nombre(b.min_lb) }) : t('c-prix-tranche-de-a', { de: nombre(b.min_lb), a: nombre(b.max_lb) })); } },
            { t: 'c-prix-par-lb', rendre: function (b) { return e(argent(b.price_per_lb, r.currency)); } },
            { t: 'c-prix-forfait', rendre: function (b) { return e(argent(b.flat_fee, r.currency)); } },
            { t: 'c-prix-minimum', rendre: function (b) { return e(argent(b.min_charge, r.currency)); } }
          ], r.brackets || [], { legende: 'c-prix-grilles' }) + '</section>';
      }).join('') : '<p class="cc-rien">' + e(t('c-prix-aucune-grille')) + '</p>') +
      '<h3>' + e(t('c-prix-zones')) + '</h3>' +
      ((d.zones || []).length ? '<ul class="cc-site-emplacements">' + d.zones.map(function (z) {
        return '<li><span class="ses-mono">' + e(z.code) + '</span>' + (z.name ? ' · ' + e(z.name) : '') + ' · ' + e(C.pays ? C.pays(z.country) : z.country) + ' ' + actifPastille(z.active) +
          (g ? ' ' + actifBouton('pricing_zone', z.zone_id, z.active, z.code) : '') + '</li>';
      }).join('') + '</ul>' : '<p class="cc-rien">' + e(t('c-prix-aucune-zone')) + '</p>') +
      '<h3>' + e(t('c-prix-frais-taxes')) + '</h3><ul class="cc-site-emplacements">' +
      (d.service_fees || []).map(function (f) {
        return '<li>' + e(t('c-prix-frais-service', { montant: argent(f.amount, f.currency) })) + ' · ' + e(t('c-prix-validite', { du: jour(f.valid_from), au: f.valid_to ? jour(f.valid_to) : '…' })) + ' ' + actifPastille(f.active) + '</li>';
      }).join('') +
      (d.taxes || []).map(function (x) {
        return '<li><span class="ses-mono">' + e(x.code) + '</span> · ' + e(x.name || '') + ' · ' + e(nombre(x.rate_percent)) + ' % · ' + e(t('c-prix-assiette-' + x.applies_to)) +
          (x.country ? ' · ' + e(C.pays ? C.pays(x.country) : x.country) : '') + ' ' + actifPastille(x.active) + (g ? ' ' + actifBouton('tax', x.tax_id, x.active, x.code) : '') + '</li>';
      }).join('') +
      (d.surcharges || []).map(function (x) { return '<li><span class="ses-mono">' + e(x.code) + '</span> · ' + e(x.name || '') + ' ' + actifPastille(x.active) + '</li>'; }).join('') +
      (d.rules || []).map(function (x) {
        return '<li><span class="ses-mono">' + e(x.code) + '</span> · ' + e(x.name || '') + (x.customer ? ' · ' + e(x.customer.code) : '') + ' · ' + e(x.reason || '') + ' ' + actifPastille(x.active) + '</li>';
      }).join('') + '</ul>' +
      '<h3>' + e(t('c-prix-change')) + '</h3>' +
      ((d.exchange_rates || []).length ? '<ul class="cc-site-emplacements">' + d.exchange_rates.map(function (x) {
        return '<li>' + e(t('c-prix-taux', { de: x.from, vers: x.to, taux: nombre(x.rate), date: jour(x.valid_from) })) + '</li>';
      }).join('') + '</ul>' : '<p class="cc-rien">' + e(t('c-prix-aucun-taux')) + '</p>');
  }
  function chargerTarifs(z, st, ctx, s) { return charger(z, function () { return API.tableau.tarifs(); }, function (d) { dessinerTarifs(z, d); }, s); }

  C.actions['prix-actif'] = function (b) {
    var l = ligneDe(b);
    b.disabled = true;
    API.tableau.activerTarif(l.genre, l.id, !l.actif).then(function () { C.annoncer(t('c-gst-enregistre'), 'succes'); C.rafraichir(); },
      function (err) { b.disabled = false; C.annoncer(C.message(err), 'erreur'); });
  };
  C.actions['prix-zone'] = function () {
    dialogueGestion('c-prix-g-zone', 'cc-prix-zone', '<p class="cc-intro">' + e(t('c-prix-zone-intro')) + '</p><div class="cc-form-grille">' +
      champ('c-site-code', '<input name="code" maxlength="20" autocomplete="off" required>') + champ('c-col-nom', '<input name="nom" maxlength="120" autocomplete="off">') +
      champ('c-site-pays', choix('pays', PAYS_PRIX.map(function (x) { return { valeur: x, libelle: C.pays ? C.pays(x) : x }; }), '', 'HT')) + '</div>',
      'c-gst-ajouter', function (f) {
        if (!String(f.elements.code.value || '').trim()) return 'c-site-code-obligatoire';
        return API.tableau.creerZone({ code: f.elements.code.value, nom: f.elements.nom.value, pays: f.elements.pays.value });
      }, 'c-gst-enregistre');
  };
  function ligneTranche(i) {
    return '<li class="cc-prix-tranche" data-tranche><div class="cc-form-grille">' +
      champ('c-prix-de-lb', '<input name="min" inputmode="decimal" autocomplete="off" value="' + (i === 0 ? '0' : '') + '">') +
      champ('c-prix-a-lb', '<input name="max" inputmode="decimal" autocomplete="off">', 'c-prix-a-lb-aide') +
      champ('c-prix-par-lb', '<input name="prix" inputmode="decimal" autocomplete="off">') +
      champ('c-prix-forfait', '<input name="forfait" inputmode="decimal" autocomplete="off" value="0">') +
      champ('c-prix-minimum', '<input name="minimum" inputmode="decimal" autocomplete="off" value="0">') + '</div></li>';
  }
  C.actions['prix-grille'] = function () {
    var d = etatTarifs.d || {}, zones = (d.zones || []).filter(function (z) { return z.active; });
    var f = dialogueGestion('c-prix-g-grille', 'cc-prix-grille', '<p class="cc-intro">' + e(t('c-prix-grille-intro')) + '</p><div class="cc-form-grille">' +
      champ('c-site-code', '<input name="code" maxlength="30" autocomplete="off" required>') + champ('c-col-nom', '<input name="nom" maxlength="120" autocomplete="off">') +
      champ('c-exp-mode', choix('mode', MODES, 'c-svc-', 'air')) +
      champ('c-prix-zone', '<select name="zone" required><option value="">' + e(t(zones.length ? 'c-gst-choisir' : 'c-prix-aucune-zone')) + '</option>' +
        zones.map(function (z) { return '<option value="' + e(z.zone_id) + '">' + e(z.code + ' · ' + (C.pays ? C.pays(z.country) : z.country)) + '</option>'; }).join('') + '</select>') +
      champ('c-prix-devise', choix('devise', DEVISES_PRIX.map(function (x) { return { valeur: x, libelle: x }; }), '', 'USD')) +
      champ('c-prix-du', '<input name="du" type="date" value="' + e(aujourdhui()) + '">') +
      champ('c-prix-volumetrique-champ', '<input name="vol" inputmode="decimal" autocomplete="off">', 'c-prix-volumetrique-aide') + '</div>' +
      '<fieldset class="cc-exp-contenu"><legend>' + e(t('c-prix-tranches')) + '</legend><ul class="cc-prix-tranches" id="cc-prix-tranches">' + ligneTranche(0) + '</ul>' +
      '<button type="button" class="cc-lien" data-ajouter-tranche>' + e(t('c-prix-ajouter-tranche')) + '</button></fieldset>',
      'c-gst-ajouter', function (f) {
        if (!String(f.elements.code.value || '').trim()) return 'c-site-code-obligatoire';
        if (!f.elements.zone.value) return 'c-prix-zone-obligatoire';
        var tranches = [], faux = false;
        [].slice.call(f.querySelectorAll('[data-tranche]')).forEach(function (li) {
          var v = function (n) { return nombreSaisi(li.querySelector('[name=' + n + ']').value); };
          var x = { min_lb: v('min'), max_lb: v('max'), price_per_lb: v('prix'), flat_fee: v('forfait') || 0, min_charge: v('minimum') || 0 };
          if (x.min_lb === null && x.price_per_lb === null && x.max_lb === null) return;
          if (x.min_lb === null || x.price_per_lb === null || isNaN(x.min_lb) || isNaN(x.price_per_lb) || (x.max_lb !== null && isNaN(x.max_lb)) || isNaN(x.flat_fee) || isNaN(x.min_charge)) faux = true;
          tranches.push(x);
        });
        if (faux) return 'c-prix-tranche-invalide';
        if (!tranches.length) return 'c-prix-tranche-obligatoire';
        var vol = nombreSaisi(f.elements.vol.value);
        if (vol !== null && !(vol > 0)) return 'c-prix-tranche-invalide';
        return API.tableau.creerGrille({ code: f.elements.code.value, nom: f.elements.nom.value, mode: f.elements.mode.value, zone: f.elements.zone.value,
                                         devise: f.elements.devise.value, du: f.elements.du.value || null, volumetrique: vol, tranches: tranches });
      }, 'c-gst-enregistre');
    if (!f) return;
    f.querySelector('[data-ajouter-tranche]').addEventListener('click', function () {
      var ul = f.querySelector('#cc-prix-tranches');
      ul.insertAdjacentHTML('beforeend', ligneTranche(ul.children.length));
    });
  };
  C.actions['prix-taxe'] = function () {
    dialogueGestion('c-prix-g-taxe', 'cc-prix-taxe', '<p class="cc-intro">' + e(t('c-prix-taxe-intro')) + '</p><div class="cc-form-grille">' +
      champ('c-site-code', '<input name="code" maxlength="20" autocomplete="off" required>') + champ('c-col-nom', '<input name="nom" maxlength="120" autocomplete="off">') +
      champ('c-prix-taux-pct', '<input name="taux" inputmode="decimal" autocomplete="off" required>') +
      champ('c-prix-assiette', choix('assiette', ASSIETTES_TAXE, 'c-prix-assiette-', 'ALL')) +
      champ('c-site-pays', choix('pays', PAYS_PRIX.map(function (x) { return { valeur: x, libelle: C.pays ? C.pays(x) : x }; }), '', '', ['', 'c-prix-tous-pays'])) +
      champ('c-prix-du', '<input name="du" type="date" value="' + e(aujourdhui()) + '">') + '</div>',
      'c-gst-ajouter', function (f) {
        var x = nombreSaisi(f.elements.taux.value);
        if (!String(f.elements.code.value || '').trim()) return 'c-site-code-obligatoire';
        if (x === null || isNaN(x) || x < 0 || x > 100) return 'c-prix-taux-invalide';
        return API.tableau.creerTaxe({ code: f.elements.code.value, nom: f.elements.nom.value, taux: x, assiette: f.elements.assiette.value, pays: f.elements.pays.value || null, du: f.elements.du.value || null });
      }, 'c-gst-enregistre');
  };
  C.actions['prix-change'] = function () {
    dialogueGestion('c-prix-g-change', 'cc-prix-change', '<p class="cc-intro">' + e(t('c-prix-change-intro')) + '</p><div class="cc-form-grille">' +
      champ('c-prix-de-devise', choix('de', DEVISES_PRIX.map(function (x) { return { valeur: x, libelle: x }; }), '', 'USD')) +
      champ('c-prix-vers-devise', choix('vers', DEVISES_PRIX.map(function (x) { return { valeur: x, libelle: x }; }), '', 'HTG')) +
      champ('c-prix-taux-change', '<input name="taux" inputmode="decimal" autocomplete="off" required>', 'c-prix-taux-change-aide') +
      champ('c-prix-du', '<input name="du" type="date" value="' + e(aujourdhui()) + '">') + '</div>',
      'c-gst-enregistrer', function (f) {
        var x = nombreSaisi(f.elements.taux.value);
        if (f.elements.de.value === f.elements.vers.value) return 'c-prix-devises-identiques';
        if (x === null || isNaN(x) || !(x > 0)) return 'c-prix-taux-invalide';
        return API.tableau.tauxChange({ de: f.elements.de.value, vers: f.elements.vers.value, taux: x, du: f.elements.du.value || null });
      }, 'c-gst-enregistre');
  };

  /* --- les devis --- */
  function dessinerDevis(zone, d) {
    var l = (d && d.items) || [], creer = peutFacturer();
    zone.innerHTML = '<p class="cc-intro">' + e(t('c-devis-intro')) + '</p>' +
      (creer ? '<div class="cc-barre-actions">' + bouton('devis-nouveau', 'c-devis-g-nouveau', null, true) + '</div>' : '') +
      (l.length ? C.tableau([
        { t: 'c-devis-numero', rendre: function (x) { return '<span class="ses-mono">' + e(x.number) + '</span><br><span class="cc-petit">' + e(date(x.created_at)) + '</span>'; } },
        { t: 'c-col-client', rendre: function (x) { return '<span class="ses-mono">' + e(x.customer.code) + '</span><br><span class="cc-petit">' + e(x.customer.name || '') + '</span>'; } },
        { t: 'c-col-colis', rendre: function (x) { return e(nombre(x.items)); } },
        { t: 'c-devis-total', rendre: function (x) { return '<strong>' + e(argent(x.total, x.currency)) + '</strong><br><span class="cc-petit">' + e(t('c-devis-dont-frais', { frais: argent(x.service_fee, x.currency), taxes: argent(x.tax_total, x.currency) })) + '</span>'; } },
        { t: 'c-devis-valide', rendre: function (x) { return e(jour(x.valid_until)); } },
        { t: 'c-col-statut', rendre: function (x) { return pastille('c-devis-' + x.status, x.status === 'OFFERED' ? 'REQUESTED' : (x.status === 'INVOICED' ? 'ACTIVE' : 'INACTIVE')) + (x.cancel_reason ? '<br><span class="cc-petit">' + e(x.cancel_reason) + '</span>' : ''); } }
      ].concat(creer ? [{ t: 'c-gst-col-actions', rendre: function (x) { return x.status === 'OFFERED' ? bouton('devis-annuler', 'c-devis-g-annuler', { id: x.quote_id, numero: x.number }) : ''; } }] : []),
      l, { legende: 'c-sec-devis' }) : '<p class="cc-rien">' + e(t('c-devis-aucun')) + '</p>');
  }
  function chargerDevis(z, st, ctx, s) { return charger(z, function () { return API.tableau.devis(); }, function (d) { dessinerDevis(z, d); }, s); }
  function ligneDevis() {
    return '<li data-ligne-devis><div class="cc-form-grille">' + champ('c-devis-poids', '<input name="poids" inputmode="decimal" autocomplete="off" required>') +
      champ('c-exp-mode', choix('mode', MODES, 'c-svc-', 'air')) +
      champ('c-col-destination', choix('pays', PAYS_PRIX.map(function (x) { return { valeur: x, libelle: C.pays ? C.pays(x) : x }; }), '', 'HT')) + '</div></li>';
  }
  function lignesDevis(f) {
    var l = [], faux = false;
    [].slice.call(f.querySelectorAll('[data-ligne-devis]')).forEach(function (li) {
      var p = nombreSaisi(li.querySelector('[name=poids]').value);
      if (p === null) return;
      if (isNaN(p) || !(p > 0)) faux = true;
      l.push({ weight_lb: p, service_mode: li.querySelector('[name=mode]').value, destination_country: li.querySelector('[name=pays]').value });
    });
    return faux ? 'c-devis-poids-invalide' : (l.length ? l : 'c-devis-poids-obligatoire');
  }
  C.actions['devis-nouveau'] = function () {
    var f = dialogueGestion('c-devis-g-nouveau', 'cc-devis', '<p class="cc-intro">' + e(t('c-devis-nouveau-intro')) + '</p><div class="cc-form-grille">' +
      champ('c-col-client', '<input name="client" maxlength="20" autocomplete="off" placeholder="SES-00000">', 'c-devis-client-aide') +
      champ('c-prix-devise', choix('devise', DEVISES_PRIX.map(function (x) { return { valeur: x, libelle: x }; }), '', 'USD')) +
      champ('c-devis-validite', '<input name="jours" inputmode="numeric" autocomplete="off" value="15">') + '</div>' +
      '<fieldset class="cc-exp-contenu"><legend>' + e(t('c-devis-colis')) + '</legend><ul class="cc-prix-tranches" id="cc-devis-lignes">' + ligneDevis() + '</ul>' +
      '<button type="button" class="cc-lien" data-ajouter-ligne>' + e(t('c-devis-ajouter-colis')) + '</button></fieldset>' +
      '<div class="cc-barre-actions"><button type="button" class="ses-bouton ses-bouton-mini ses-bouton-second" data-calculer>' + e(t('c-devis-calculer')) + '</button></div>' +
      '<div id="cc-devis-apercu" aria-live="polite"></div>',
      'c-devis-g-creer', function (f) {
        var l = lignesDevis(f), jours = nombreSaisi(f.elements.jours.value);
        if (typeof l === 'string') return l;
        if (!String(f.elements.client.value || '').trim()) return 'c-devis-client-obligatoire';
        if (jours === null || isNaN(jours) || jours < 0 || jours > 365 || Math.floor(jours) !== jours) return 'c-devis-validite-invalide';
        return API.tableau.creerDevis({ client: f.elements.client.value, devise: f.elements.devise.value, colis: l, jours: jours });
      }, 'c-devis-cree');
    if (!f) return;
    f.querySelector('[data-ajouter-ligne]').addEventListener('click', function () { f.querySelector('#cc-devis-lignes').insertAdjacentHTML('beforeend', ligneDevis()); });
    f.querySelector('[data-calculer]').addEventListener('click', function () {
      var zone = f.querySelector('#cc-devis-apercu'), l = lignesDevis(f);
      if (typeof l === 'string') { zone.innerHTML = '<p class="cc-form-msg">' + e(t(l)) + '</p>'; return; }
      zone.innerHTML = '<p class="cc-petit">' + e(t('c-gst-chargement')) + '</p>';
      API.tableau.apercuDevis({ client: f.elements.client.value, devise: f.elements.devise.value, colis: l }).then(function (c) {
        zone.innerHTML = '<ul class="cc-site-emplacements">' + (c.lines || []).map(function (x) {
          return '<li>' + e(x.description || x.kind) + (x.item ? ' · ' + e(t('c-devis-colis-n', { n: x.item })) : '') + ' · <strong>' + e(argent(x.amount, c.currency)) + '</strong></li>';
        }).join('') + '</ul><p><strong>' + e(t('c-devis-total-calcule', { total: argent(c.total, c.currency) })) + '</strong></p>';
      }, function (err) { zone.innerHTML = '<p class="cc-form-msg">' + e(C.message(err)) + '</p>'; });
    });
  };
  C.actions['devis-annuler'] = function (b) {
    var l = ligneDe(b);
    dialogueGestion('c-devis-g-annuler', 'cc-devis-ann', '<p class="cc-intro">' + e(t('c-devis-annuler-intro', { numero: l.numero || '' })) + '</p>' +
      champ('c-motif', '<textarea name="motif" rows="2" maxlength="300" required></textarea>'), 'c-exp-confirmer', function (f) {
        var m = String(f.elements.motif.value || '').trim();
        if (!m) return 'c-gst-motif-obligatoire';
        return API.tableau.annulerDevis(l.id, m);
      }, 'c-gst-enregistre');
  };

  /* --- préparer la bascule : chaque écart de l'ancienne facturation, examiné un par un (direction) --- */
  function dessinerBascule(zone, r) {
    var rap = r[0] || {}, ecarts = r[1] || [], par = rap.parity || {};
    var verdicts = par.by_verdict || {};
    zone.innerHTML = '<p class="cc-intro">' + e(t('c-bas-intro')) + '</p>' +
      '<p>' + pastille(rap.ready ? 'c-bas-pret' : 'c-bas-pas-pret', rap.ready ? 'ACTIVE' : 'PENDING') + ' ' + pastille('c-prix-mode-' + rap.mode, rap.mode === 'core' ? 'ACTIVE' : 'PENDING') + '</p>' +
      '<ul class="cc-puces">' +
      '<li><span class="cc-puce">' + e(t('c-bas-factures')) + ' <strong>' + e(nombre(par.total)) + '</strong></span></li>' +
      Object.keys(verdicts).sort().map(function (k) { return '<li><span class="cc-puce">' + e(t('c-bas-v-' + k)) + ' <strong>' + e(nombre(verdicts[k])) + '</strong></span></li>'; }).join('') +
      '<li><span class="cc-puce">' + e(t('c-bas-bloquants')) + ' <strong>' + e(nombre(rap.parity_blocking)) + '</strong></span></li>' +
      '<li><span class="cc-puce">' + e(t('c-bas-examines')) + ' <strong>' + e(nombre(par.reviewed)) + '</strong></span></li>' +
      '<li><span class="cc-puce">' + e(t('c-bas-noyau')) + ' <strong>' + e(nombre(rap.core && rap.core.problems)) + '</strong></span></li>' +
      '<li><span class="cc-puce">' + e(t('c-bas-paiements')) + ' <strong>' + e(nombre(rap.payments && rap.payments.blocking)) + '</strong></span></li>' +
      '<li><span class="cc-puce">' + e(t('c-bas-copie')) + ' <strong>' + e(nombre(rap.copy_differences)) + '</strong></span></li></ul>' +
      (ecarts.length ? C.tableau([
        { t: 'c-bas-facture', rendre: function (x) { return '<span class="ses-mono">' + e(x.number) + '</span>'; } },
        { t: 'c-bas-ancien', rendre: function (x) { return e(argent(x.legacy_total, 'USD')); } },
        { t: 'c-bas-calcul-noyau', rendre: function (x) { return e(argent(x.core_total, 'USD')); } },
        { t: 'c-bas-verdict', rendre: function (x) { return pastille('c-bas-v-' + x.verdict, x.blocking ? 'OVERDUE' : (VERDICTS_BLOQUANTS.indexOf(x.verdict) >= 0 ? 'ACTIVE' : 'REQUESTED')) + (x.detail ? '<br><span class="cc-petit">' + e(x.detail) + '</span>' : ''); } },
        { t: 'c-bas-examen', rendre: function (x) {
          return x.review ? '<span class="cc-petit">' + e(x.review.note) + ' — ' + e(x.review.by || '') + ', ' + e(date(x.review.at)) + '</span>'
            : (x.blocking ? bouton('bas-examiner', 'c-bas-g-examiner', { id: x.legacy_invoice_id, numero: x.number, verdict: x.verdict }) : '—');
        } }
      ], ecarts, { legende: 'c-sec-bascule' }) : '<p class="cc-rien">' + e(t('c-bas-aucun-ecart')) + '</p>');
  }
  function chargerBascule(z, st, ctx, s) {
    return charger(z, function () { return Promise.all([API.tableau.bascule(), API.tableau.ecartsParite()]); }, function (r) { dessinerBascule(z, r); }, s);
  }
  C.actions['bas-examiner'] = function (b) {
    var l = ligneDe(b);
    dialogueGestion('c-bas-g-examiner', 'cc-bas-exam', '<p class="cc-intro">' + e(t('c-bas-examiner-intro', { numero: l.numero || '', verdict: t('c-bas-v-' + l.verdict) })) + '</p>' +
      champ('c-bas-note', '<textarea name="note" rows="3" maxlength="2000" required></textarea>'), 'c-exp-confirmer', function (f) {
        var n = String(f.elements.note.value || '').trim();
        if (!n) return 'c-bas-note-obligatoire';
        return API.tableau.examinerEcart(l.id, n);
      }, 'c-gst-enregistre');
  };
