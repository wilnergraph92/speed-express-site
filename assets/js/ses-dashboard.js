/* Speed Express Shipping — vue d'ensemble du tableau de bord.
   --------------------------------------------------------------------------
   Aucune donnée de démonstration, aucun repli local : tout vient des fonctions
   `dashboard_*_ses` de la base, et seuls les chiffres réellement lus sont
   affichés. Les couleurs sont celles du logo — rouge #e8121b, noir #0b0c0e,
   bleu #1a2ed2, jaune #e8b111, vert #13c02c. */
(function () {
  'use strict';
  var API = window.SES_API, UI = window.SES_UI, started = false, rights = [];
  var f = {}, generations = {}, page = 0, cache = {}, timer;
  var zone = (window.SES_CONFIG || {}).fuseauHoraire || 'America/Santo_Domingo';
  function $(id) { return document.getElementById(id); }
  function e(v) { return UI.echapper(v == null ? '' : String(v)); }
  function t(k) { return UI.t('dash-' + k); }
  function allowed(d) { return rights.indexOf(d + '.lire') >= 0; }
  function number(n) { return Number(n).toLocaleString(document.documentElement.lang || 'fr'); }
  function date(d) { return new Intl.DateTimeFormat(document.documentElement.lang || 'fr', { timeZone: zone, dateStyle: 'short', timeStyle: 'short' }).format(new Date(d)); }
  function localDay() {
    var parts = new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
    var o = {}; parts.forEach(function (p) { o[p.type] = p.value; });
    return o.year + '-' + o.month + '-' + o.day;
  }
  function state(id, key, retry) {
    var el = $(id); el.removeAttribute('aria-busy');
    el.innerHTML = '<div class="dash-state">' + e(t(key)) + (retry ? '<button type="button" class="ses-bouton ses-bouton-second" data-dash-retry="' + e(retry) + '">' + e(t('retry')) + '</button>' : '') + '</div>';
  }
  function loading(id) { $(id).setAttribute('aria-busy', 'true'); $(id).innerHTML = '<div class="dash-skeleton" aria-hidden="true"></div><span class="dash-muted">' + e(t('loading')) + '</span>'; }
  function request(key, ids, call, render) {
    var version = (generations[key] || 0) + 1; generations[key] = version;
    delete cache[key]; ids.forEach(loading);
    if (API.mode !== 'supabase') { ids.forEach(function (id) { state(id, 'real'); }); return; }
    Promise.resolve().then(call).then(function (data) {
      if (version !== generations[key]) return;
      ids.forEach(function (id) { $(id).removeAttribute('aria-busy'); });
      cache[key] = { data: data, render: render }; render(data);
    }).catch(function (err) {
      if (version !== generations[key]) return;
      var keyMessage = err && err.code === 'periode-invalide' ? 'invalid-period' : err && err.code === 'base-a-mettre-a-jour' ? 'migration' : err && err.code === 'non-autorise' ? 'denied' : 'error';
      delete cache[key];
      ids.forEach(function (id) { state(id, keyMessage, key); });
      if (key === 'colis') $('dash-periode-info').textContent = t(keyMessage);
    });
  }
  function comparison(d) {
    var p = d.periode;
    return '<p class="dash-comparison">' + (d.precedent > 0 ? e(((d.total - d.precedent) / d.precedent * 100).toLocaleString(document.documentElement.lang, { maximumFractionDigits: 1 })) + '% · ' + e(t('comparison')) : e(t('no-comparison'))) + '</p>' +
      '<p class="dash-comparison">' + e(date(p.precedent_debut)) + ' → ' + e(date(p.precedent_fin)) + ' · ' + e(t('exclusive')) + '</p>';
  }
  /* Variation réelle entre la période et la précédente, en pastille. */
  function variation(d) {
    if (!d.precedent) return '<span class="dash-delta dash-delta-neutre">' + e(t('no-comparison')) + '</span>';
    var pct = (d.total - d.precedent) / d.precedent * 100;
    var sens = pct > 0 ? 'haut' : pct < 0 ? 'bas' : 'neutre';
    return '<span class="dash-delta dash-delta-' + sens + '">' + (pct > 0 ? '↗ ' : pct < 0 ? '↘ ' : '= ') +
      e(Math.abs(pct).toLocaleString(document.documentElement.lang, { maximumFractionDigits: 1 })) + '% ' +
      '<em>' + e(t('vs-precedent')) + '</em></span>';
  }

  /* ======================================================================
     Destinations : position réelle des villes, projetées sur la carte
     ======================================================================
     La carte `assets/img/ses-carte-monde.svg` est fabriquée par
     `outils/carte-monde.py` : projection équirectangulaire, cadrée de 78°N à
     58°S. Les deux formules ci-dessous sont les mêmes que celles du script ;
     changer l'une oblige à changer l'autre. */
  function cle(v) {
    return String(v == null ? '' : v).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, ' ').trim();
  }
  function placer(lat, lon) { return { x: (lon + 180) / 360 * 100, y: (78 - lat) / 136 * 100 }; }
  var VILLES = {
    /* États-Unis et Porto Rico */
    'new york': [40.71, -74.01], 'brooklyn': [40.68, -73.94], 'newark': [40.74, -74.17],
    'miami': [25.76, -80.19], 'orlando': [28.54, -81.38], 'tampa': [27.95, -82.46],
    'jacksonville': [30.33, -81.66], 'atlanta': [33.75, -84.39], 'boston': [42.36, -71.06],
    'philadelphie': [39.95, -75.17], 'washington': [38.91, -77.04], 'charlotte': [35.23, -80.84],
    'chicago': [41.88, -87.63], 'detroit': [42.33, -83.05], 'minneapolis': [44.98, -93.27],
    'houston': [29.76, -95.37], 'dallas': [32.78, -96.8], 'denver': [39.74, -104.99],
    'phoenix': [33.45, -112.07], 'las vegas': [36.17, -115.14], 'los angeles': [34.05, -118.24],
    'san francisco': [37.77, -122.42], 'seattle': [47.61, -122.33], 'savannah': [32.08, -81.09],
    'san antonio': [29.42, -98.49], 'san diego': [32.72, -117.16],
    'san juan': [18.47, -66.11], 'ponce': [18.01, -66.61],
    /* République dominicaine */
    'santo domingo': [18.49, -69.93], 'santo domingo este': [18.49, -69.79],
    'santiago': [19.45, -70.7], 'santiago de los caballeros': [19.45, -70.7],
    'la romana': [18.43, -68.97], 'puerto plata': [19.79, -70.69], 'san pedro de macoris': [18.46, -69.29],
    'higuey': [18.61, -68.71], 'la vega': [19.22, -70.53], 'san cristobal': [18.42, -70.11],
    'barahona': [18.21, -71.1], 'moca': [19.39, -70.52], 'bonao': [18.94, -70.41],
    'nagua': [19.38, -69.85], 'azua': [18.45, -70.73], 'bani': [18.28, -70.33],
    'monte cristi': [19.85, -71.65], 'samana': [19.21, -69.33], 'jarabacoa': [19.12, -70.64],
    'bavaro': [18.68, -68.45], 'punta cana': [18.58, -68.4],
    /* Haïti */
    'port au prince': [18.54, -72.34], 'petion ville': [18.51, -72.29], 'petionville': [18.51, -72.29],
    'cap haitien': [19.76, -72.2], 'gonaives': [19.45, -72.69], 'les cayes': [18.19, -73.75],
    'jacmel': [18.23, -72.53], 'jeremie': [18.65, -74.12], 'saint marc': [19.11, -72.7],
    'petit goave': [18.43, -72.87], 'hinche': [19.15, -72.01], 'fort liberte': [19.66, -71.84],
    'miragoane': [18.46, -73.09],
    /* Caraïbes et Amériques */
    'la havane': [23.11, -82.37], 'havane': [23.11, -82.37], 'guantanamo': [20.14, -75.21],
    'toronto': [43.65, -79.38], 'montreal': [45.5, -73.57], 'vancouver': [49.28, -123.12],
    'mexico': [19.43, -99.13], 'cancun': [21.16, -86.85], 'panama': [8.98, -79.52],
    'bogota': [4.71, -74.07], 'medellin': [6.25, -75.56], 'caracas': [10.48, -66.9],
    'lima': [-12.05, -77.04], 'santiago du chili': [-33.45, -70.67], 'buenos aires': [-34.6, -58.38],
    'sao paulo': [-23.55, -46.63], 'rio de janeiro': [-22.91, -43.17], 'brasilia': [-15.79, -47.88],
    'saint domingue': [18.49, -69.93], 'nassau': [25.05, -77.35],
    /* Europe */
    'madrid': [40.42, -3.7], 'barcelone': [41.39, 2.17], 'paris': [48.86, 2.35],
    'londres': [51.51, -0.13], 'london': [51.51, -0.13], 'amsterdam': [52.37, 4.9],
    'bruxelles': [50.85, 4.35], 'francfort': [50.11, 8.68], 'frankfurt': [50.11, 8.68],
    'milan': [45.46, 9.19], 'rome': [41.9, 12.5], 'geneve': [46.2, 6.14],
    'lisbonne': [38.72, -9.14], 'berlin': [52.52, 13.4], 'munich': [48.14, 11.58],
    'istanbul': [41.01, 28.98], 'moscou': [55.75, 37.62],
    /* Afrique et Moyen-Orient */
    'casablanca': [33.57, -7.59], 'le caire': [30.04, 31.24], 'lagos': [6.52, 3.38],
    'accra': [5.6, -0.19], 'johannesburg': [-26.2, 28.05], 'dakar': [14.72, -17.47],
    'abidjan': [5.35, -4.02], 'dubai': [25.2, 55.27], 'doha': [25.29, 51.53],
    /* Asie et Océanie */
    'pekin': [39.9, 116.4], 'shanghai': [31.23, 121.47], 'guangzhou': [23.13, 113.26],
    'yiwu': [29.31, 120.08], 'shenzhen': [22.54, 114.06], 'hong kong': [22.32, 114.17],
    'tokyo': [35.68, 139.69], 'seoul': [37.57, 126.98], 'mumbai': [19.08, 72.88],
    'new delhi': [28.61, 77.21], 'singapour': [1.35, 103.82], 'bangkok': [13.76, 100.5],
    'jakarta': [-6.21, 106.85], 'manille': [14.6, 120.98], 'sydney': [-33.87, 151.21],
    'melbourne': [-37.81, 144.96], 'auckland': [-36.85, 174.76]
  };
  var PAYS = {
    DO: [18.8, -70.2], HT: [19.0, -72.6], US: [39.0, -98.0], CA: [56.1, -106.3],
    MX: [23.6, -102.6], PR: [18.2, -66.5], CU: [21.5, -77.8], JM: [18.1, -77.3],
    TT: [10.7, -61.2], PA: [8.5, -80.8], CR: [9.7, -83.8], GT: [15.8, -90.2],
    CO: [4.6, -74.3], VE: [6.4, -66.6], EC: [-1.8, -78.2], PE: [-9.2, -75.0],
    BO: [-16.3, -63.6], CL: [-35.7, -71.5], AR: [-38.4, -63.6], BR: [-14.2, -51.9],
    UY: [-32.5, -55.8], PY: [-23.4, -58.4], BR2: [-14.2, -51.9],
    ES: [40.5, -3.7], FR: [46.6, 2.2], GB: [54.0, -2.0], IE: [53.4, -8.2],
    PT: [39.4, -8.2], DE: [51.2, 10.4], IT: [41.9, 12.6], NL: [52.1, 5.3],
    BE: [50.5, 4.5], CH: [46.8, 8.2], AT: [47.5, 14.6], SE: [62.2, 17.6],
    PL: [51.9, 19.1], RO: [45.9, 25.0], GR: [39.1, 21.8], TR: [39.0, 35.2],
    RU: [61.5, 60.0], UA: [48.4, 31.2],
    MA: [31.8, -7.1], DZ: [28.0, 1.7], TN: [33.9, 9.6], EG: [26.8, 30.8],
    SN: [14.5, -14.5], CI: [7.5, -5.5], GH: [7.9, -1.0], NG: [9.1, 8.7],
    CM: [7.4, 12.4], ZA: [-30.6, 22.9], KE: [0.2, 37.9], TZ: [-6.4, 34.9],
    AE: [23.4, 53.8], SA: [23.9, 45.1], QA: [25.3, 51.2], IL: [31.0, 34.8],
    IN: [20.6, 79.0], PK: [30.4, 69.3], BD: [23.7, 90.4], CN: [35.9, 104.2],
    HK: [22.3, 114.2], TW: [23.7, 120.9], JP: [36.2, 138.3], KR: [35.9, 127.8],
    TH: [15.9, 100.9], VN: [14.1, 108.3], MY: [4.2, 101.9], SG: [1.35, 103.8],
    ID: [-0.8, 113.9], PH: [12.9, 121.8], AU: [-25.3, 133.8], NZ: [-40.9, 174.9]
  };
  /* Rend la position et sa précision : ville connue, ou centre du pays quand
     la ville n'est pas au carnet. L'étiquette suit cette précision — jamais
     un nom de ville posé sur un point qui n'est pas le sien. */
  function position(pays, ville) {
    var v = VILLES[cle(ville)];
    if (v) return { point: v, precis: true };
    var p = PAYS[String(pays || '').toUpperCase()];
    return p ? { point: p, precis: false } : null;
  }
  function nomLieu(r) {
    var ville = String(r.ville == null ? '' : r.ville);
    var pays = UI.nomPays ? UI.nomPays(r.pays) : r.pays;
    if (!ville || ville === '—') return pays || r.pays;
    return ville + ' · ' + (pays || r.pays);
  }
  /* Un seul bloc HTML pour la carte : le fond en pointillés, puis un repère
     par ville desservie, placé par pourcentage. Les villes absentes du carnet
     d'adresses restent dans la liste, jamais sur la carte à une fausse place. */
  function carte(rows) {
    var reperes = [], restes = [];
    /* Du plus petit au plus grand : le repère le plus fourni reste au-dessus,
       et c'est son étiquette qu'on lit quand deux villes se touchent. */
    rows.slice().sort(function (a, b) { return a.n - b.n; }).forEach(function (r, i, tous) {
      var p = position(r.pays, r.ville);
      if (!p) { restes.push(r); return; }
      var xy = placer(p.point[0], p.point[1]);
      var rang = tous.length - 1 - i;
      /* Six étiquettes seulement, une ligne sur deux au-dessus : au-delà, les
         villes voisines se recouvriraient. Les autres gardent leur texte, lu
         par les lecteurs d'écran et affiché au survol. */
      var classe = 'dash-map-nom' + (rang > 5 ? ' dash-map-nom-cache' : (rang % 2 ? ' dash-map-nom-haut' : ''));
      reperes.push('<li class="dash-map-repere" style="left:' + xy.x.toFixed(2) + '%;top:' + xy.y.toFixed(2) + '%" title="' + e(nomLieu(r)) + ' · ' + e(number(r.n)) + '">' +
        '<span class="dash-map-point" aria-hidden="true"></span>' +
        '<span class="' + classe + '">' + e(p.precis ? nomCourt(r) : (UI.nomPays ? UI.nomPays(r.pays) : r.pays)) + ' · ' + e(number(r.n)) +
        '<span class="sr-only"> · ' + e(UI.nomPays ? UI.nomPays(r.pays) : r.pays) + '</span></span></li>');
    });
    /* Aucune ville reconnue : des barres plutôt qu'une carte vide. */
    if (!reperes.length) return bars(rows);
    return '<div class="dash-map">' +
      '<img class="dash-map-fond" src="assets/img/ses-carte-monde.svg" width="720" height="272" alt="" aria-hidden="true">' +
      '<ul class="dash-map-liste" aria-label="' + e(t('map')) + '">' + reperes.join('') + '</ul>' +
      '</div>' + listeDestinations(rows) +
      (restes.length ? '<p class="dash-muted">' + e(t('map-hors')) + ' ' + restes.map(function (r) { return e(nomLieu(r)) + ' (' + e(number(r.n)) + ')'; }).join(' · ') + '</p>' : '');
  }
  /* Titre court pour la carte : la ville, ou le pays quand la ville manque. */
  function nomCourt(r) {
    var ville = String(r.ville == null ? '' : r.ville);
    if (!ville || ville === '—') return UI.nomPays ? UI.nomPays(r.pays) : r.pays;
    return ville;
  }
  function listeDestinations(rows) {
    return '<details class="dash-details"><summary>' + e(t('list')) + '</summary>' + bars(rows) + '</details>';
  }
  function bars(rows) {
    var max = Math.max.apply(null, rows.map(function (r) { return r.n; }).concat([1]));
    return '<div class="dash-bars">' + rows.map(function (r) {
      return '<div><div class="dash-bar-label"><span>' + e(r.label) + '</span><b>' + e(number(r.n)) + '</b></div><div class="dash-track" aria-hidden="true"><i style="width:' + Math.max(0, Math.min(100, r.n / max * 100)) + '%"></i></div></div>';
    }).join('') + '</div>';
  }

  /* ======================================================================
     Graphique « Colis enregistrés »
     ======================================================================
     Peu de créneaux : des colonnes, comme une semaine jour par jour. Beaucoup
     de créneaux : une courbe, sinon les colonnes deviennent des traits. Le
     maximum est mis en rouge, jamais une valeur inventée. */
  function libelle(r, d) { return r.date.replace('T', ' ').slice(0, d.periode.grain === 'hour' ? 16 : 10); }
  function etiquetteCourt(r, d) {
    var s = libelle(r, d);
    return d.periode.grain === 'hour' ? s.slice(-5) : s.slice(-5).replace('-', '/');
  }
  function chart(d) {
    if (!d.total) { state('dash-serie', 'empty'); return; }
    var rows = d.serie, max = Math.max.apply(null, rows.map(function (r) { return r.n; }).concat([1]));
    var W = 600, H = 250, L = 44, R = 14, T = 16, B = 34;
    var svg = '<svg class="dash-chart" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + e(t('chart')) + '"><title>' + e(t('chart')) + '</title>';
    [0, 0.5, 1].forEach(function (v) {
      var y = T + (1 - v) * (H - T - B);
      svg += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y.toFixed(1) + '" y2="' + y.toFixed(1) + '" stroke="#eceef3" class="dash-grille"/>' +
        '<text x="' + (L - 10) + '" y="' + (y + 4).toFixed(1) + '" text-anchor="end">' + e(number(Math.round(max * v))) + '</text>';
    });
    if (rows.length <= 10) {
      var pas = (W - L - R) / rows.length, largeur = Math.min(52, pas * 0.52);
      rows.forEach(function (r, i) {
        var h = Math.max(3, r.n / max * (H - T - B));
        var x = L + i * pas + (pas - largeur) / 2, y = H - B - h;
        svg += '<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + largeur.toFixed(1) + '" height="' + h.toFixed(1) +
          '" rx="' + Math.min(9, largeur / 2).toFixed(1) + '" fill="' + (r.n === max ? '#e8121b' : '#e8eaef') + '"></rect>' +
          '<text x="' + (x + largeur / 2).toFixed(1) + '" y="' + (H - B + 18) + '" text-anchor="middle">' + e(etiquetteCourt(r, d)) + '</text>';
      });
    } else {
      var pts = rows.map(function (r, i) { return (L + i * (W - L - R) / (rows.length - 1)).toFixed(1) + ',' + (H - B - r.n / max * (H - T - B)).toFixed(1); });
      svg += '<polygon points="' + pts[0].split(',')[0] + ',' + (H - B) + ' ' + pts.join(' ') + ' ' + pts[pts.length - 1].split(',')[0] + ',' + (H - B) + '" fill="rgba(232,18,27,.08)"></polygon>' +
        '<polyline points="' + pts.join(' ') + '" fill="none" stroke="#e8121b" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"></polyline>';
      rows.forEach(function (r, i) {
        if (rows.length > 24 && i % Math.ceil(rows.length / 8) !== 0 && i !== rows.length - 1) return;
        svg += '<circle cx="' + (L + i * (W - L - R) / (rows.length - 1)).toFixed(1) + '" cy="' + (H - B - r.n / max * (H - T - B)).toFixed(1) + '" r="3.6" fill="#fff" stroke="#e8121b" stroke-width="2.4"></circle>';
      });
      svg += '<text x="' + L + '" y="' + (H - B + 18) + '">' + e(libelle(rows[0], d)) + '</text>' +
        '<text x="' + (W - R) + '" y="' + (H - B + 18) + '" text-anchor="end">' + e(libelle(rows[rows.length - 1], d)) + '</text>';
    }
    svg += '</svg>';
    $('dash-serie').innerHTML = '<div class="dash-chiffre-tete"><div class="dash-chiffre-grand">' + e(number(d.total)) + '</div>' +
      '<p class="dash-comparison">' + e(t('period-colis')) + '</p></div>' +
      (d.precedent > 0 ? '<p class="dash-comparison">' + e(((d.total - d.precedent) / d.precedent * 100).toLocaleString(document.documentElement.lang, { maximumFractionDigits: 1 })) + '% · ' + e(t('comparison')) + '</p>' : '') + svg +
      '<p class="dash-muted">' + e(number(d.stock.total)) + ' ' + e(t('stock-total')) + '</p>' +
      '<details class="dash-details"><summary>' + e(t('values')) + '</summary><div class="dash-scroll"><table class="dash-table"><caption>' + e(zone) + '</caption><thead><tr><th scope="col">' + e(t('date')) + '</th><th scope="col">' + e(t('count')) + '</th></tr></thead><tbody>' + rows.map(function (r) { return '<tr><td>' + e(libelle(r, d)) + '</td><td>' + e(number(r.n)) + '</td></tr>'; }).join('') + '</tbody></table></div></details>';
  }

  /* Anneau des statuts : des graduations comme sur un compteur, une couleur
     réelle par statut, et le total au centre. La liste à droite porte les
     chiffres — l'anneau lui-même est décoratif pour les lecteurs d'écran. */
  var COULEURS_STATUT = { confirme: '#1a2ed2', expedie: '#231f20', disponible: '#13c02c', livre: '#0b7a19', action: '#e8121b' };
  function anneau(d) {
    var total = d.stock.total, couleurs = [], cumul = 0;
    API.STATUTS.forEach(function (s) { couleurs.push({ nom: s, n: d.stock.statuts[s] || 0, couleur: COULEURS_STATUT[s] || '#8b93a1' }); });
    var parts = couleurs.map(function (c) { var part = total ? c.n / total * 100 : 0; cumul += part; return { c: c, fin: cumul }; });
    var ticks = '', i;
    for (i = 0; i < 64; i++) {
      var fraction = (i + 0.5) / 64 * 100, trouve = null;
      for (var j = 0; j < parts.length; j++) { if (fraction <= parts[j].fin) { trouve = parts[j].c; break; } }
      ticks += '<line x1="60" y1="16" x2="60" y2="30" transform="rotate(' + (i * 360 / 64).toFixed(2) + ' 60 60)" stroke="' + (trouve ? trouve.couleur : '#eceef3') + '" stroke-width="5.4" stroke-linecap="round"></line>';
    }
    if (!total) { state('dash-statuts', 'empty'); return; }
    $('dash-statuts').innerHTML = '<div class="dash-status-layout">' +
      '<svg class="dash-donut" viewBox="0 0 120 120" aria-hidden="true">' + ticks +
      '<text class="dash-donut-total" x="60" y="60" text-anchor="middle">' + e(number(total)) + '</text>' +
      '<text class="dash-donut-mot" x="60" y="76" text-anchor="middle">' + e(t('count')) + '</text></svg>' +
      '<div class="dash-legend">' + couleurs.map(function (c) {
        var part = total ? c.n / total * 100 : 0;
        return '<div><i class="dash-dot" style="background:' + c.couleur + '" aria-hidden="true"></i><span>' + e(UI.nomStatut(c.nom)) + '</span><b>' + e(number(c.n)) + ' <em>' + e(part.toLocaleString(document.documentElement.lang, { maximumFractionDigits: 1 })) + '%</em></b></div>';
      }).join('') + '</div></div>';
  }

  /* ======================================================================
     Vue d'ensemble
     ====================================================================== */
  function renderColis(d) {
    if (!d || d.version !== 1 || !d.stock || !Array.isArray(d.serie)) throw new Error('Invalid dashboard response');
    var services = d.stock.services;
    var enCours = (services.aerien || 0) + (services.maritime || 0) + (services.terrestre || 0);
    var cellules = [
      { cle: 'periode', valeur: d.total, icone: 'boite', teinte: 'rouge', pied: variation(d) },
      { cle: 'aerien', valeur: services.aerien || 0, icone: 'avion', teinte: 'bleu', pied: part(enCours, services.aerien || 0) },
      { cle: 'maritime', valeur: services.maritime || 0, icone: 'navire', teinte: 'noir', pied: part(enCours, services.maritime || 0) },
      { cle: 'terrestre', valeur: services.terrestre || 0, icone: 'camion', teinte: 'vert', pied: part(enCours, services.terrestre || 0) }
    ];
    $('ses-chiffres').innerHTML = cellules.map(function (c) {
      return '<div class="dash-kpi"><div class="dash-kpi-tete"><span class="dash-kpi-label">' + e(t(c.cle)) + '</span>' +
        '<span class="dash-ico dash-ico-' + c.teinte + '" aria-hidden="true">' + icone(c.icone) + '</span></div>' +
        '<strong>' + e(number(c.valeur)) + '</strong>' + c.pied + '</div>';
    }).join('');
    $('dash-periode-info').textContent = date(d.periode.debut) + ' → ' + date(d.periode.fin_effective) + ' · ' + t('exclusive') + ' · ' + t('updated') + ' ' + date(d.periode.reference) + ' · ' + zone;
    chart(d);
    anneau(d);
    var destinations = d.destinations.map(function (r) { return { label: r.pays + ' · ' + r.ville, ville: r.ville, pays: r.pays, n: r.n }; });
    if (!destinations.length) state('dash-destinations', 'empty');
    else $('dash-destinations').innerHTML = carte(destinations) + '<p class="dash-muted">' + e(number(destinations.length)) + ' / ' + e(number(d.destinations_nombre)) + ' · ' + e(t('destinations')) + '</p>';
    $('dash-inline-destinations').textContent = number(d.destinations_nombre);
    $('dash-inline-colis').textContent = number(d.total);
  }
  /* Part réelle d'un transport dans les colis en cours, jamais une estimation. */
  function part(total, n) {
    if (!total) return '<span class="dash-delta dash-delta-neutre">' + e(t('ongoing')) + '</span>';
    return '<span class="dash-delta dash-delta-neutre">' + e((n / total * 100).toLocaleString(document.documentElement.lang, { maximumFractionDigits: 1 })) + '% ' +
      '<em>' + e(t('share')) + '</em></span>';
  }
  function icone(nom) {
    var d = {
      boite: '<path d="M21 8.4 12 3.2 3 8.4v7.2L12 20.8l9-5.2V8.4Z"></path><path d="M3 8.4 12 13.6l9-5.2"></path><path d="M12 13.6v7.2"></path>',
      avion: '<path d="M21.4 3.6 2.6 11.2l5.4 2.3 2.2 6.3 3-5.6 8.2-10.6Z"></path><path d="M8 13.5 5.4 18.6"></path>',
      navire: '<path d="M3.4 14.4h17.2l-2.2 5.2H5.6l-2.2-5.2Z"></path><path d="M6.2 14.4V9.2h11.6v5.2"></path><path d="M12 9.2V5.6"></path>',
      camion: '<path d="M3 16.4V6.8h9.6v9.6"></path><path d="M12.6 9.6h3.8l3.6 3.4v3.4h-7.4"></path><circle cx="7" cy="17.8" r="1.9"></circle><circle cx="17" cy="17.8" r="1.9"></circle>'
    };
    return '<svg viewBox="0 0 24 24">' + (d[nom] || '') + '</svg>';
  }
  function aggregates() {
    if (allowed('colis')) request('colis', ['ses-chiffres', 'dash-serie', 'dash-statuts', 'dash-destinations'], function () { return API.admin.dashboard('colis', f); }, renderColis);
    if (allowed('clients')) request('clients', ['dash-clients'], function () { return API.admin.dashboard('clients', f); }, function (d) {
      if (!d || d.version !== 1) throw new Error('Invalid dashboard response');
      $('dash-clients').innerHTML = '<div class="dash-chiffre-grand">' + e(number(d.total)) + '</div>' + variation(d) + comparison(d);
      $('dash-inline-clients').textContent = number(d.total);
    });
  }
  function recent() {
    if (!allowed('colis')) return;
    var form = $('dash-recherche'), tri = form.elements.tri.value.split(':');
    $('dash-pages').innerHTML = '';
    request('recents', ['dash-recents'], function () { return API.admin.dashboardRecents({ page: page, recherche: form.elements.recherche.value.trim(), statut: form.elements.statut.value, tri: tri[0], asc: tri[1] === 'asc' }); }, function (d) {
      if (page > 0 && page * 20 >= d.total) { page = Math.max(0, Math.ceil(d.total / 20) - 1); recent(); return; }
      if (!d.lignes.length) { state('dash-recents', 'empty'); return; }
      $('dash-recents').innerHTML = '<table class="dash-table"><caption>' + e(number(d.total)) + ' · ' + e(t('count')) + '</caption><thead><tr>' + ['reference', 'recipient', 'destination', 'weight', 'service', 'status', 'date', 'action'].map(function (k) { return '<th scope="col">' + e(t(k)) + '</th>'; }).join('') + '</tr></thead><tbody>' + d.lignes.map(function (c) {
        return '<tr><th scope="row">' + e(c.numero) + '</th><td>' + e(c.destinataire || '—') + '</td><td>' + e(c.pays_destination + ' · ' + (c.ville_destination || '—')) + '</td><td>' + (c.poids_lb == null ? '—' : e(number(c.poids_lb)) + ' lb') + '</td><td>' + e(t(c.service)) + '</td><td>' + UI.pastille(c.statut, { petite: true }) + '</td><td>' + e(date(c.cree_le)) + '</td><td><button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-action="fiche" data-id="' + e(c.id) + '">' + e(t('open')) + '</button></td></tr>';
      }).join('') + '</tbody></table>';
      $('dash-pages').innerHTML = '<button type="button" class="ses-bouton ses-bouton-second" data-dash-page="-1"' + (page === 0 ? ' disabled' : '') + '>' + e(t('previous')) + '</button><span>' + (page + 1) + ' / ' + Math.ceil(d.total / 20) + '</span><button type="button" class="ses-bouton ses-bouton-second" data-dash-page="1"' + ((page + 1) * 20 >= d.total ? ' disabled' : '') + '>' + e(t('next')) + '</button>';
    });
  }
  function activity() {
    if (!allowed('colis')) return;
    request('activite', ['dash-activite'], function () { return API.admin.dashboardActivite(); }, function (rows) {
      if (!rows.length) { state('dash-activite', 'empty'); return; }
      $('dash-activite').innerHTML = '<ol class="dash-events">' + rows.map(function (r) {
        return '<li><span class="dash-event-mark" aria-hidden="true">↗</span><div><p><strong>' + e(r.colis && r.colis.numero || '—') + '</strong> · ' + e(UI.nomStatut(r.statut)) + '</p><small>' + e([r.lieu, r.auteur].filter(Boolean).join(' · ')) + '</small></div><time datetime="' + e(r.cree_le) + '">' + e(date(r.cree_le)) + '</time></li>';
      }).join('') + '</ol>';
    });
  }
  function apply() {
    var form = $('dash-filtres');
    if (!window.SES_A11Y.valider(form)) return;
    var next = {}; new FormData(form).forEach(function (v, k) { next[k] = v; });
    if (next.debut && next.fin && next.fin <= next.debut) {
      window.SES_A11Y.erreurChamp(form.elements.fin, t('invalid'));
      return;
    }
    f = next;
    var rapide = $('dash-periode-rapide');
    if (rapide) rapide.value = next.periode;
    $('dash-periode-info').textContent = t('loading'); aggregates();
  }
  function menu(open) {
    $('dash-navigation').classList.toggle('is-open', open); $('dash-voile').hidden = !open;
    $('dash-menu').setAttribute('aria-expanded', String(open));
    if (open) $('dash-navigation').querySelector('a').focus(); else $('dash-menu').focus();
  }
  function init(p) {
    if (started) return; started = true; rights = API.droitsDe(p);
    document.querySelectorAll('[data-domain]').forEach(function (el) { el.hidden = !allowed(el.dataset.domain); });
    $('dash-filtres').hidden = !allowed('colis') && !allowed('clients');
    $('dash-vue-bloc').hidden = $('dash-filtres').hidden;
    $('dash-topsearch').hidden = !allowed('colis');
    if (API.mode !== 'supabase') { $('dash-mode').hidden = false; $('dash-mode').textContent = t('real'); }
    var form = $('dash-filtres'); form.noValidate = true; form.elements.date.value = localDay();
    form.elements.periode.addEventListener('change', function () {
      var custom = ['heures', 'personnalise'].indexOf(this.value) >= 0;
      $('dash-date-label').hidden = custom; form.elements.date.disabled = custom;
      ['debut', 'fin'].forEach(function (k) { $('dash-' + k + '-label').hidden = !custom; form.elements[k].disabled = !custom; form.elements[k].required = custom; });
    });
    form.addEventListener('submit', function (ev) { ev.preventDefault(); apply(); });
    /* Le sélecteur de période de la barre du haut pilote le formulaire : une
       seule source de vérité pour les filtres, jamais deux états à recoller. */
    $('dash-periode-rapide').addEventListener('change', function () {
      var select = form.elements.periode;
      select.value = this.value;
      select.dispatchEvent(new Event('change'));
      /* Une période personnalisée a besoin de ses deux dates : on découvre les
         champs et on attend « Appliquer », plutôt que d'envoyer une requête
         qu'on sait incomplète. */
      if (select.value !== 'personnalise') apply();
    });
    $('dash-refresh').addEventListener('click', function () { aggregates(); recent(); activity(); });
    /* La recherche vit dans la barre du haut ; elle alimente la liste des
       colis récents, qui porte ses propres filtres de statut et de tri. */
    var haut = $('dash-top-recherche');
    haut.addEventListener('input', function () {
      clearTimeout(timer); generations.recents = (generations.recents || 0) + 1;
      $('dash-recherche').elements.recherche.value = haut.value;
      timer = setTimeout(function () { page = 0; recent(); }, 250);
    });
    haut.addEventListener('keydown', function (ev) { if (ev.key === 'Enter') ev.preventDefault(); });
    $('dash-recherche').addEventListener('submit', function (ev) { ev.preventDefault(); clearTimeout(timer); page = 0; recent(); });
    $('dash-recherche').addEventListener('change', function () { clearTimeout(timer); page = 0; recent(); });
    $('ses-p-dashboard').addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-dash-retry],[data-dash-page]'); if (!b) return;
      if (b.dataset.dashPage) { page += Number(b.dataset.dashPage); recent(); }
      else if (b.dataset.dashRetry === 'recents') recent(); else if (b.dataset.dashRetry === 'activite') activity(); else aggregates();
    });
    $('dash-menu').addEventListener('click', function () { menu(this.getAttribute('aria-expanded') !== 'true'); });
    $('dash-voile').addEventListener('click', function () { menu(false); });
    $('dash-navigation').addEventListener('click', function (ev) { if (ev.target.closest('[role=tab]') && !$('dash-voile').hidden) menu(false); });
    document.addEventListener('keydown', function (ev) {
      if ($('dash-voile').hidden) return;
      if (ev.key === 'Escape') { ev.preventDefault(); menu(false); }
      if (ev.key === 'Tab') {
        var items = Array.from($('dash-navigation').querySelectorAll('a,button')).filter(function (b) { return !b.hidden && b.getClientRects().length; });
        var first = items[0], last = items[items.length - 1];
        if (ev.shiftKey && document.activeElement === first) { ev.preventDefault(); last.focus(); }
        else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); first.focus(); }
      }
    });
    window.matchMedia('(min-width:901px)').addEventListener('change', function (ev) { if (ev.matches) { $('dash-voile').hidden = true; $('dash-navigation').classList.remove('is-open'); $('dash-menu').setAttribute('aria-expanded', 'false'); } });
    UI.surLangue(function () { Object.keys(cache).forEach(function (k) { cache[k].render(cache[k].data); }); });
    document.addEventListener('visibilitychange', function () { if (!document.hidden) refresh(); });
    apply(); recent(); activity();
  }
  var refreshTimer;
  function refresh(domain) {
    if (!started) return;
    clearTimeout(refreshTimer); refreshTimer = setTimeout(function () {
      if (domain !== 'factures') { aggregates(); recent(); activity(); }
    }, 350);
  }
  window.SES_DASHBOARD = { init: init, refresh: refresh };
})();
