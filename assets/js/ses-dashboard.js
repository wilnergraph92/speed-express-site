/* Speed Express — read-only dashboard. No demo fallback, no local business data.
   Habillage repris de la maquette ShipFast (jetons officiels du logo SES) :
   quatre chiffres, courbe cumulée, barres quotidiennes, cadran des statuts,
   croissance clients, destinations — tout vient de l'API Supabase existante. */
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
  function pourcent(n) { return n.toLocaleString(document.documentElement.lang || 'fr', { maximumFractionDigits: 1 }); }
  function date(d) { return new Intl.DateTimeFormat(document.documentElement.lang || 'fr', { timeZone: zone, dateStyle: 'short', timeStyle: 'short' }).format(new Date(d)); }
  function localDay() {
    var parts = new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
    var o = {}; parts.forEach(function (p) { o[p.type] = p.value; });
    return o.year + '-' + o.month + '-' + o.day;
  }
  function state(id, key, retry) {
    var el = $(id); if (!el) return;
    el.removeAttribute('aria-busy');
    el.innerHTML = '<div class="dash-state">' + e(t(key)) + (retry ? '<button type="button" class="ses-bouton ses-bouton-second" data-dash-retry="' + e(retry) + '">' + e(t('retry')) + '</button>' : '') + '</div>';
  }
  function loading(id) { var el = $(id); if (!el) return; el.setAttribute('aria-busy', 'true'); el.innerHTML = '<div class="dash-skeleton" aria-hidden="true"></div><span class="dash-muted">' + e(t('loading')) + '</span>'; }
  function viderTete() {
    var total = $('dash-periode-total'), pastille = $('dash-periode-pastille');
    if (total) total.textContent = '—';
    if (pastille) pastille.innerHTML = '';
  }
  function request(key, ids, call, render) {
    var version = (generations[key] || 0) + 1; generations[key] = version;
    delete cache[key]; ids.forEach(loading);
    if (API.mode !== 'supabase') { ids.forEach(function (id) { state(id, 'real'); }); if (key === 'colis') viderTete(); return; }
    Promise.resolve().then(call).then(function (data) {
      if (version !== generations[key]) return;
      ids.forEach(function (id) { $(id).removeAttribute('aria-busy'); });
      cache[key] = { data: data, render: render }; render(data);
    }).catch(function (err) {
      if (version !== generations[key]) return;
      var keyMessage = err && err.code === 'periode-invalide' ? 'invalid-period' : err && err.code === 'base-a-mettre-a-jour' ? 'migration' : err && err.code === 'non-autorise' ? 'denied' : 'error';
      delete cache[key];
      ids.forEach(function (id) { state(id, keyMessage, key); });
      if (key === 'colis') { viderTete(); $('dash-periode-info').textContent = t(keyMessage); }
    });
  }

  /* ---------- Icônes lucide (mêmes tracés que la maquette) ---------- */
  var ICONE_ATTR = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
  function svg(paths, sw) {
    return '<svg ' + ICONE_ATTR + ' stroke-width="' + (sw || 2) + '">' + paths + '</svg>';
  }
  var ICONE_BOITES = svg('<path d="M2.97 12.92A2 2 0 0 0 2 14.63v3.24a2 2 0 0 0 .97 1.71l3 1.8a2 2 0 0 0 2.06 0L12 19v-5.5l-5-3-4.03 2.42Z"></path><path d="m7 16.5-4.74-2.85"></path><path d="m7 16.5 5-3"></path><path d="M7 16.5v5.17"></path><path d="M12 13.5V19l3.97 2.38a2 2 0 0 0 2.06 0l3-1.8a2 2 0 0 0 .97-1.71v-3.24a2 2 0 0 0-.97-1.71L17 10.5l-5 3Z"></path><path d="m17 16.5-5-3"></path><path d="m17 16.5 4.74-2.85"></path><path d="M17 16.5v5.17"></path><path d="M7.97 4.42A2 2 0 0 0 7 6.13v4.37l5 3 5-3V6.13a2 2 0 0 0-.97-1.71l-3-1.8a2 2 0 0 0-2.06 0l-3 1.8Z"></path><path d="M12 8 7.26 5.15"></path><path d="m12 8 4.74-2.85"></path><path d="M12 13.5V8"></path>', 1.9);
  var ICONE_AVION = svg('<path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z"></path>', 1.9);
  var ICONE_NAVIRE = svg('<path d="M12 2v2"></path><path d="M12 9.189V13"></path><path d="M19 12V6a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2v6"></path><path d="M19.38 19A11.6 11.6 0 0 0 21 13l-8.188-3.639a2 2 0 0 0-1.624 0L3 13.001a11.6 11.6 0 0 0 2.81 7.76"></path><path d="M2 20c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1s1.2 1 2.5 1c2.5 0 2.5-2 5-2"></path>', 1.9);
  var ICONE_CAMION = svg('<path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2"></path><path d="M15 18H9"></path><path d="M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.624l-3.48-4.35A1 1 0 0 0 17.52 8H14"></path><circle cx="17" cy="18" r="2"></circle><circle cx="7" cy="18" r="2"></circle>', 1.9);
  var ICONE_GLOBE = svg('<circle cx="12" cy="12" r="10"></circle><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"></path><path d="M2 12h20"></path>', 2);
  var ICONE_HAUSSE = svg('<path d="M7 7h10v10"></path><path d="M7 17 17 7"></path>', 3.2);
  var ICONE_BAISSE = svg('<path d="m7 7 10 10"></path><path d="M17 7v10H7"></path>', 3.2);

  /* ---------- Courbe cumulée (carte « Colis enregistrés ») ---------- */
  function cheminLisse(points) {
    if (points.length < 2) return '';
    var d = 'M ' + points[0][0] + ' ' + points[0][1];
    for (var i = 0; i < points.length - 1; i++) {
      var prec = points[Math.max(0, i - 1)], cur = points[i], suiv = points[i + 1], après = points[Math.min(points.length - 1, i + 2)];
      var x1 = cur[0] + (suiv[0] - prec[0]) / 6, y1 = cur[1] + (suiv[1] - prec[1]) / 6;
      var x2 = suiv[0] - (après[0] - cur[0]) / 6, y2 = suiv[1] - (après[1] - cur[1]) / 6;
      d += ' C ' + x1.toFixed(1) + ' ' + y1.toFixed(1) + ', ' + x2.toFixed(1) + ' ' + y2.toFixed(1) + ', ' + suiv[0] + ' ' + suiv[1];
    }
    return d;
  }
  function libellesTenus(rows, max) {
    if (rows.length <= 7) return rows.map(function (r, i) { return i; });
    var prises = {}, total = Math.min(7, rows.length);
    for (var j = 0; j < total; j++) prises[Math.round(j * (rows.length - 1) / (total - 1))] = true;
    return Object.keys(prises).map(Number);
  }
  function labelTranche(r, grain) { return r.date.replace('T', ' ').slice(0, grain === 'hour' ? 16 : 10); }
  function pastilleDelta(precedent, actuel) {
    if (!(precedent > 0)) return '';
    var pct = (actuel - precedent) / precedent * 100;
    var hausse = pct >= 0;
    return '<span class="dash-pastille ' + (hausse ? 'is-hausse' : 'is-baisse') + '">' + svg(hausse ? '<path d="M7 7h10v10"></path><path d="M7 17 17 7"></path>' : '<path d="m7 7 10 10"></path><path d="M17 7v10H7"></path>', 3.2) + pourcent(pct) + '%</span>';
  }
  function chart(d) {
    if (!d.total) { state('dash-serie', 'empty'); return; }
    var rows = d.serie, cumul = 0, valeurs = rows.map(function (r) { return (cumul += Number(r.n) || 0); });
    var max = valeurs[valeurs.length - 1] || 1;
    var points = valeurs.map(function (v, i) {
      var x = rows.length === 1 ? 290 : 24 + i * (556 - 24) / (rows.length - 1);
      return [Math.round(x * 10) / 10, Math.round((168 - v / max * 142) * 10) / 10];
    });
    var svgHtml = '<svg class="dash-courbe" viewBox="0 0 580 190" preserveAspectRatio="none" role="img" aria-label="' + e(t('chart')) + '">';
    points.forEach(function (p) {
      svgHtml += '<line x1="' + p[0] + '" y1="8" x2="' + p[0] + '" y2="168" stroke="#E9EAF4" stroke-width="1" stroke-dasharray="3 5"/>';
    });
    if (rows.length === 1) {
      svgHtml += '<circle cx="290" cy="' + points[0][1] + '" r="5" fill="#e8121b"/>';
    } else {
      svgHtml += '<path d="' + cheminLisse(points) + '" fill="none" stroke="#e8121b" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" pathLength="1" class="line-draw" vector-effect="non-scaling-stroke"/>';
    }
    svgHtml += '</svg>';
    var indices = libellesTenus(rows, max);
    var axe = '<div class="dash-axe-x" aria-hidden="true">' + indices.map(function (i) {
      return '<span>' + e(labelTranche(rows[i], d.periode.grain)) + '</span>';
    }).join('') + '</div>';
    var tableau = '<details><summary>' + e(t('values')) + '</summary><div class="dash-scroll"><table class="dash-table"><caption>America/Santo_Domingo</caption><thead><tr><th scope="col">' + e(t('date')) + '</th><th scope="col">' + e(t('count')) + '</th></tr></thead><tbody>' +
      rows.map(function (r, i) { return '<tr><td>' + e(labelTranche(r, d.periode.grain)) + '</td><td>' + e(number(r.n)) + '</td></tr>'; }).join('') +
      '</tbody></table></div></details>';
    $('dash-serie').innerHTML = '<div class="dash-courbe-zone-inner">' + svgHtml + axe + tableau + '</div>';
  }

  /* ---------- Barres quotidiennes (carte « Colis au fil du temps ») ---------- */
  function barres(d) {
    if (!d.total) { state('dash-bars', 'empty'); return; }
    var rows = d.serie, cumul = 0;
    var max = Math.max.apply(null, rows.map(function (r) { return Number(r.n) || 0; }).concat([1]));
    var cumuls = rows.map(function (r) { return (cumul += Number(r.n) || 0); });
    var chaud = rows.reduce(function (mi, r, i) { return (Number(r.n) || 0) > (Number(rows[mi].n) || 0) ? i : mi; }, 0);
    var echelle = [100, 80, 60, 40, 20, 0];
    var axeY = '<div class="dash-axe-y" aria-hidden="true">' + echelle.map(function (v) {
      return '<span style="top:' + (100 - v) + '%">' + e(number(Math.round(max * v / 100))) + '</span>';
    }).join('') + '</div>';
    var grille = '<div class="dash-barres-grille" aria-hidden="true">' + echelle.map(function (v) {
      return '<i style="top:' + (100 - v) + '%"></i>';
    }).join('') + '</div>';
    var groupes = rows.map(function (r, i) {
      var h = Math.round((Number(r.n) || 0) / max * 100);
      var isChaud = i === chaud && Number(r.n) > 0;
      var queue = i >= rows.length - 2;
      return '<div class="dash-barre-groupe' + (isChaud ? ' is-chaude' : '') + '">' +
        '<div class="dash-barre bar' + (isChaud ? ' is-chaude' : '') + '" style="height:' + h + '%;--i:' + i + '"></div>' +
        '<div class="dash-astuce ' + (queue ? 'is-gauche' : 'is-droite') + '" role="tooltip">' +
        '<p><span>' + e(t('colis-jour')) + '</span><b>' + e(number(r.n)) + '</b></p>' +
        '<p><span>' + e(t('cumul')) + '</span><b>' + e(number(cumuls[i])) + '</b></p>' +
        '</div></div>';
    }).join('');
    var indices = libellesTenus(rows, max);
    var jours = '<div class="dash-barres-jours" aria-hidden="true">' + indices.map(function (i) {
      return '<span>' + e(labelTranche(rows[i], d.periode.grain)) + '</span>';
    }).join('') + '</div>';
    $('dash-bars').innerHTML = '<div class="dash-barres-zone">' + axeY +
      '<div class="dash-barres-piste">' + grille + '<div class="dash-barres">' + groupes + '</div></div>' +
      '</div>' + jours;
  }

  /* ---------- Cadran à graduations des cinq statuts ---------- */
  function melange(c1, c2, t0) {
    function rgb(c) { return [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)]; }
    var a = rgb(c1), b = rgb(c2);
    return '#' + a.map(function (v, i) {
      var m = Math.round(v + (b[i] - v) * t0).toString(16);
      return m.length === 1 ? '0' + m : m;
    }).join('');
  }
  function statuts(d) {
    if (!d.stock.total) { state('dash-statuts', 'empty'); return; }
    var couleurs = ['#b60d14', '#df6115', '#2765a5', '#197344', '#777f8c'];
    var total = d.stock.total, legend = '', i;
    API.STATUTS.forEach(function (s, k) {
      var n = d.stock.statuts[s] || 0, pct = n / total * 100;
      legend += '<span><i style="background:' + couleurs[k] + '" aria-hidden="true"></i>' + e(UI.nomStatut(s)) + ' <b>' + e(number(n)) + ' · ' + e(pourcent(pct)) + '%</b></span>';
    });
    var ticks = '';
    for (i = 0; i < 56; i++) {
      var angle = i * 360 / 56;
      var pos = angle / 360 * 5, seg = Math.min(4, Math.floor(pos)), frac = pos - seg;
      var couleur = melange(couleurs[seg], couleurs[(seg + 1) % 5], frac);
      var alpha = (0.32 + 0.68 * Math.min(1, Math.min(angle, 360 - angle) / 95)).toFixed(2);
      ticks += '<rect x="127.25" y="20" width="5.5" height="27" rx="2.75" fill="' + couleur + '" transform="rotate(' + angle.toFixed(2) + ' 130 130)" class="dash-aiguille" style="--o:' + alpha + ';--i:' + i + '"></rect>';
    }
    var livres = d.stock.statuts.livre || 0;
    var part = livres / total * 100;
    var pied = d.precedent > 0
      ? '<b>' + e(pourcent((d.total - d.precedent) / d.precedent * 100)) + '%</b> · ' + e(t('comparison'))
      : e(t('no-comparison'));
    $('dash-statuts').innerHTML =
      '<div class="dash-legende">' + legend + '</div>' +
      '<div class="dash-cadran"><svg viewBox="0 0 260 260" role="img" aria-label="' + e(t('livres')) + ' ' + e(pourcent(part)) + '%">' + ticks + '</svg>' +
      '<div class="dash-cadran-centre"><strong>' + e(pourcent(part)) + '%</strong><span>' + e(t('livres')) + '</span></div></div>' +
      '<p class="dash-cadran-pied">' + pied + '</p>';
  }

  /* ---------- Destinations réelles (sans carte inventée) ---------- */
  function destinations(d) {
    // Colis en cours = tout le stock moins les colis déjà livrés (quel que soit
    // le mode de transport, les services ci-dessus comptent aussi les livrés).
    var enCours = Math.max(0, d.stock.total - (d.stock.statuts.livre || 0));
    var trio = '<div class="dash-trio">' +
      '<div class="dash-trio-cell"><span class="is-rouge">' + ICONE_GLOBE + '</span><strong>' + e(number(d.destinations_nombre)) + '</strong><span>' + e(t('destinations')) + '</span></div>' +
      '<div class="dash-trio-cell"><span class="is-bleu">' + ICONE_CAMION + '</span><strong>' + e(number(enCours)) + '</strong><span>' + e(t('en-cours')) + '</span></div>' +
      '<div class="dash-trio-cell"><span class="is-vert">' + ICONE_BOITES + '</span><strong>' + e(number(d.total)) + '</strong><span>' + e(t('sur-periode')) + '</span></div>' +
      '</div>';
    if (!d.destinations.length) {
      $('dash-destinations').innerHTML = trio + '<div class="dash-destinations-zone"><div class="dash-state">' + e(t('empty')) + '</div></div>';
      return;
    }
    var max = Math.max.apply(null, d.destinations.map(function (r) { return r.n; }).concat([1]));
    var liste = '<div class="dash-bars">' + d.destinations.map(function (r) {
      return '<div><div class="dash-bar-label"><span>' + e(r.pays + ' · ' + r.ville) + '</span><b>' + e(number(r.n)) + '</b></div>' +
        '<div class="dash-track" aria-hidden="true"><i style="width:' + Math.max(0, Math.min(100, r.n / max * 100)) + '%"></i></div></div>';
    }).join('') + '</div>' +
      '<p class="dash-muted" style="margin-top:14px">' + e(number(d.destinations.length)) + ' / ' + e(number(d.destinations_nombre)) + ' · ' + e(t('destinations')) + '</p>';
    $('dash-destinations').innerHTML = trio + '<div class="dash-destinations-zone">' + liste + '</div>';
  }

  function renderColis(d) {
    if (!d || d.version !== 1 || !d.stock || !Array.isArray(d.serie)) throw new Error('Invalid dashboard response');
    var services = d.stock.services;
    $('ses-chiffres').innerHTML = [
      { k: 'total', n: d.stock.total, icone: ICONE_BOITES, cls: 'kpi-total', tint: 'is-total' },
      { k: 'aerien', n: services.aerien || 0, icone: ICONE_AVION, cls: 'kpi-air', tint: 'is-aerien' },
      { k: 'maritime', n: services.maritime || 0, icone: ICONE_NAVIRE, cls: 'kpi-ocean', tint: 'is-maritime' },
      { k: 'terrestre', n: services.terrestre || 0, icone: ICONE_CAMION, cls: 'kpi-route', tint: 'is-terrestre' }
    ].map(function (r) {
      return '<div class="dash-kpi ' + r.cls + '">' +
        '<div class="dash-kpi-haut"><p class="dash-kpi-label">' + e(t(r.k)) + '</p>' +
        '<span class="dash-kpi-icone ' + r.tint + '">' + r.icone + '</span></div>' +
        '<p class="dash-kpi-valeur">' + e(number(r.n)) + '</p>' +
        '<div class="dash-kpi-pied"><span class="dash-muted">' + e(t('stock')) + '</span></div>' +
        '</div>';
    }).join('');
    $('dash-periode-info').textContent = date(d.periode.debut) + ' → ' + date(d.periode.fin_effective) + ' · ' + t('exclusive') + ' · ' + t('updated') + ' ' + date(d.periode.reference) + ' · America/Santo_Domingo';
    $('dash-periode-total').textContent = number(d.total);
    $('dash-periode-pastille').innerHTML = pastilleDelta(d.precedent, d.total);
    chart(d);
    barres(d);
    statuts(d);
    destinations(d);
  }

  function renderClients(d) {
    if (!d || d.version !== 1) throw new Error('Invalid dashboard response');
    var pct = d.precedent > 0 ? (d.total - d.precedent) / d.precedent * 100 : null;
    var gros = pct == null ? number(d.total) : (pct >= 0 ? '+' : '') + pourcent(pct) + '%';
    var badge = pct == null ? '' : '<span class="dash-croissance-badge' + (pct < 0 ? ' is-baisse' : '') + '">' +
      svg(pct >= 0 ? '<path d="M7 7h10v10"></path><path d="M7 17 17 7"></path>' : '<path d="m7 7 10 10"></path><path d="M17 7v10H7"></path>', 3.2) + number(d.total) + '</span>';
    var corps;
    if (pct == null) {
      corps = '<div class="dash-croissance-haut"><strong>' + e(number(d.total)) + '</strong></div>' +
        '<p class="dash-croissance-note">' + e(t('no-comparison')) + '</p>';
    } else {
      var remplissage = Math.max(0, Math.min(100, Math.abs(pct)));
      corps = '<div class="dash-croissance-haut"><strong>' + e(gros) + '</strong>' + badge + '</div>' +
        '<div class="dash-jauge-piste" aria-hidden="true"><div class="dash-jauge-remplissage' + (pct < 0 ? ' is-baisse' : '') + '" style="--fill:' + remplissage + '%"></div></div>';
    }
    $('dash-clients').innerHTML = corps;
  }

  function aggregates() {
    if (allowed('colis')) request('colis', ['ses-chiffres', 'dash-serie', 'dash-bars', 'dash-statuts', 'dash-destinations'], function () { return API.admin.dashboard('colis', f); }, renderColis);
    if (allowed('clients')) request('clients', ['dash-clients'], function () { return API.admin.dashboard('clients', f); }, renderClients);
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

  /* ---------- Filtres de période et menus déroulants ---------- */
  function appliquerChampsPeriode(form) {
    var custom = ['heures', 'personnalise'].indexOf(form.elements.periode.value) >= 0;
    $('dash-date-label').hidden = custom; form.elements.date.disabled = custom;
    ['debut', 'fin'].forEach(function (k) {
      $('dash-' + k + '-label').hidden = !custom; form.elements[k].disabled = !custom; form.elements[k].required = custom;
    });
  }
  function synchroniserLibelles() {
    var source = $('dash-filtres').elements.periode;
    var libelle = source.options[source.selectedIndex];
    document.querySelectorAll('[data-dash-periode-libelle]').forEach(function (el) { el.textContent = libelle.textContent; });
  }
  function choisirPeriode(valeur) {
    var source = $('dash-filtres').elements.periode;
    source.value = valeur;
    source.dispatchEvent(new Event('change'));
    synchroniserLibelles();
    apply();
  }
  function fermerMenus(avecFocus) {
    document.querySelectorAll('[data-dash-periode-menu]').forEach(function (menu) {
      var bouton = menu.querySelector('button');
      if (bouton.getAttribute('aria-expanded') === 'true') {
        bouton.setAttribute('aria-expanded', 'false');
        var liste = menu.querySelector('.dash-menu-liste');
        if (liste) liste.remove();
        if (avecFocus) bouton.focus();
      }
    });
  }
  function menusPeriode() {
    document.querySelectorAll('[data-dash-periode-menu]').forEach(function (menu) {
      var bouton = menu.querySelector('button');
      if (menu.dataset.pret) return;
      menu.dataset.pret = '1';
      bouton.addEventListener('click', function () {
        var ouvert = bouton.getAttribute('aria-expanded') === 'true';
        fermerMenus(false);
        if (ouvert) return;
        var source = $('dash-filtres').elements.periode;
        var liste = document.createElement('ul');
        liste.className = 'dash-menu-liste is-droite';
        liste.setAttribute('role', 'listbox');
        liste.setAttribute('aria-label', 'Période');
        Array.from(source.options).forEach(function (opt) {
          var li = document.createElement('li');
          var b = document.createElement('button');
          b.type = 'button';
          b.setAttribute('role', 'option');
          b.setAttribute('aria-selected', String(opt.value === source.value));
          b.textContent = opt.textContent;
          b.addEventListener('click', function () { fermerMenus(false); choisirPeriode(opt.value); });
          li.appendChild(b);
          liste.appendChild(li);
        });
        bouton.setAttribute('aria-expanded', 'true');
        menu.appendChild(liste);
        var actif = liste.querySelector('[aria-selected=true]') || liste.querySelector('button');
        if (actif) actif.focus();
      });
    });
    document.addEventListener('click', function (ev) {
      if (!ev.target.closest('[data-dash-periode-menu]')) fermerMenus(false);
    });
    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape' && document.querySelector('[data-dash-periode-menu] button[aria-expanded=true]')) {
        ev.preventDefault(); fermerMenus(true);
      }
    });
  }

  /* ---------- Apparitions animées (IntersectionObserver) ---------- */
  function revelations() {
    var cibles = Array.from(document.querySelectorAll('.dash-reveal'));
    if (!cibles.length) return;
    if (window.matchMedia('(prefers-reduced-motion:reduce)').matches || !('IntersectionObserver' in window)) {
      cibles.forEach(function (el) { el.classList.add('reveal', 'reveal-in'); });
      return;
    }
    var observateur = new IntersectionObserver(function (entrees) {
      entrees.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add('reveal', 'reveal-in'); observateur.unobserve(en.target); }
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -32px 0px' });
    cibles.forEach(function (el) { el.classList.add('reveal'); observateur.observe(el); });
  }

  function apply() {
    var form = $('dash-filtres');
    if (!window.SES_A11Y.valider(form)) return;
    var next = {}; new FormData(form).forEach(function (v, k) { next[k] = v; });
    if (next.debut && next.fin && next.fin <= next.debut) {
      window.SES_A11Y.erreurChamp(form.elements.fin, t('invalid'));
      return;
    }
    f = next; $('dash-periode-info').textContent = t('loading'); aggregates();
  }
  function menu(open) {
    var desktop = window.matchMedia('(min-width:1024px)').matches;
    var principal = $('dash-navigation').closest('.ses-dashboard');
    if (desktop) {
      principal.classList.toggle('is-reduit', !open);
      $('dash-voile').hidden = true;
    } else {
      $('dash-navigation').classList.toggle('is-open', open);
      $('dash-voile').hidden = !open;
    }
    $('dash-menu').setAttribute('aria-expanded', String(open));
    if (open) $('dash-navigation').querySelector('a').focus();
    else $('dash-menu').focus();
  }
  function init(p) {
    if (started) return; started = true; rights = API.droitsDe(p);
    document.querySelectorAll('[data-domain]').forEach(function (el) { el.hidden = !allowed(el.dataset.domain); });
    $('dash-filtres').hidden = !allowed('colis') && !allowed('clients');
    if (API.mode !== 'supabase') { $('dash-mode').hidden = false; $('dash-mode').textContent = t('real'); }
    var form = $('dash-filtres'); form.noValidate = true; form.elements.date.value = localDay();
    form.elements.periode.addEventListener('change', function () { appliquerChampsPeriode(form); synchroniserLibelles(); });
    form.addEventListener('submit', function (ev) { ev.preventDefault(); apply(); });
    synchroniserLibelles();
    menusPeriode();
    revelations();
    $('dash-refresh').addEventListener('click', function () { aggregates(); recent(); activity(); });
    $('dash-vers-reglages').addEventListener('click', function () { $('ses-o-reglages').click(); });
    $('dash-vers-clients').addEventListener('click', function () { if (allowed('clients')) $('ses-o-clients').click(); });
    $('dash-recherche-entete').addEventListener('submit', function (ev) {
      ev.preventDefault();
      if (!allowed('colis')) return;
      var cible = $('ses-chercher-colis');
      cible.value = this.elements.recherche.value;
      cible.dispatchEvent(new Event('input', { bubbles: true }));
      $('ses-o-colis').click();
    });
    $('dash-recherche').addEventListener('submit', function (ev) { ev.preventDefault(); clearTimeout(timer); page = 0; recent(); });
    $('dash-recherche').addEventListener('input', function () { clearTimeout(timer); generations.recents = (generations.recents || 0) + 1; timer = setTimeout(function () { page = 0; recent(); }, 250); });
    $('ses-p-dashboard').addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-dash-retry],[data-dash-page]'); if (!b) return;
      if (b.dataset.dashPage) { page += Number(b.dataset.dashPage); recent(); }
      else if (b.dataset.dashRetry === 'recents') recent(); else if (b.dataset.dashRetry === 'activite') activity(); else aggregates();
    });
    $('dash-menu').addEventListener('click', function () { menu(this.getAttribute('aria-expanded') !== 'true'); });
    $('dash-reduire').addEventListener('click', function () { menu(false); });
    $('dash-fermer').addEventListener('click', function () { menu(false); });
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
    $('dash-menu').setAttribute('aria-expanded', String(window.matchMedia('(min-width:1024px)').matches));
    window.matchMedia('(min-width:1024px)').addEventListener('change', function (ev) {
      if (ev.matches) {
        $('dash-voile').hidden = true;
        $('dash-navigation').classList.remove('is-open');
        $('dash-menu').setAttribute('aria-expanded', String(!$('dash-navigation').closest('.ses-dashboard').classList.contains('is-reduit')));
      } else {
        $('dash-navigation').closest('.ses-dashboard').classList.remove('is-reduit');
        $('dash-voile').hidden = true;
        $('dash-navigation').classList.remove('is-open');
        $('dash-menu').setAttribute('aria-expanded', 'false');
      }
    });
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
