/* Speed Express — read-only dashboard. No demo fallback, no local business data. */
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
  function bars(rows) {
    var max = Math.max.apply(null, rows.map(function (r) { return r.n; }).concat([1]));
    return '<div class="dash-bars">' + rows.map(function (r) {
      return '<div><div class="dash-bar-label"><span>' + e(r.label) + '</span><b>' + e(number(r.n)) + '</b></div><div class="dash-track" aria-hidden="true"><i style="width:' + Math.max(0, Math.min(100, r.n / max * 100)) + '%"></i></div></div>';
    }).join('') + '</div>';
  }
  function chart(d) {
    if (!d.total) { state('dash-serie', 'empty'); return; }
    var rows = d.serie, max = Math.max.apply(null, rows.map(function (r) { return r.n; }).concat([1]));
    var points = rows.map(function (r, i) { return (40 + (rows.length === 1 ? 250 : i * 500 / (rows.length - 1))) + ',' + (170 - r.n / max * 140); });
    function label(r) { return r.date.replace('T', ' ').slice(0, d.periode.grain === 'hour' ? 16 : 10); }
    var svg = '<svg class="dash-chart" viewBox="0 0 580 215" role="img" aria-label="' + e(t('chart')) + '"><title>' + e(t('chart')) + '</title>';
    [0, .5, 1].forEach(function (v) {
      var y = 170 - 140 * v;
      svg += '<line x1="40" x2="540" y1="' + y + '" y2="' + y + '" stroke="#eaecf0"/><text x="30" y="' + (y + 4) + '" text-anchor="end">' + e(number(Math.round(max * v))) + '</text>';
    });
    svg += '<polyline points="' + points.join(' ') + '" fill="none" stroke="#e8121b" stroke-width="3" stroke-linejoin="round"/>';
    if (rows.length === 1) svg += '<circle cx="290" cy="' + (170 - rows[0].n / max * 140) + '" r="4" fill="#e8121b"/>';
    svg += '<text x="40" y="200">' + e(label(rows[0])) + '</text><text x="540" y="200" text-anchor="end">' + e(label(rows[rows.length-1])) + '</text></svg>';
    $('dash-serie').innerHTML = '<div class="dash-number">' + e(number(d.total)) + '</div>' + comparison(d) + svg +
      '<details><summary>' + e(t('values')) + '</summary><div class="dash-scroll"><table class="dash-table"><caption>America/Santo_Domingo</caption><thead><tr><th scope="col">' + e(t('date')) + '</th><th scope="col">' + e(t('count')) + '</th></tr></thead><tbody>' + rows.map(function (r) { return '<tr><td>' + e(label(r)) + '</td><td>' + e(number(r.n)) + '</td></tr>'; }).join('') + '</tbody></table></div></details>';
  }
  function renderColis(d) {
    if (!d || d.version !== 1 || !d.stock || !Array.isArray(d.serie)) throw new Error('Invalid dashboard response');
    var services = d.stock.services;
    $('ses-chiffres').innerHTML = [['total', d.stock.total], ['aerien', services.aerien || 0], ['maritime', services.maritime || 0], ['terrestre', services.terrestre || 0]].map(function (r) {
      return '<div class="dash-kpi"><strong>' + e(number(r[1])) + '</strong><span>' + e(t(r[0])) + '</span><small>' + e(t(r[0] === 'total' ? 'stock' : 'ongoing')) + '</small></div>';
    }).join('');
    $('dash-periode-info').textContent = date(d.periode.debut) + ' → ' + date(d.periode.fin_effective) + ' · ' + t('exclusive') + ' · ' + t('updated') + ' ' + date(d.periode.reference) + ' · America/Santo_Domingo';
    chart(d);
    var colors = ['#b60d14','#df6115','#2765a5','#197344','#777f8c'];
    var offset = 0, circles = '', legend = '';
    API.STATUTS.forEach(function (s, i) {
      var n = d.stock.statuts[s] || 0, percent = d.stock.total ? n / d.stock.total * 100 : 0;
      circles += '<circle cx="60" cy="60" r="45" fill="none" stroke="' + colors[i] + '" stroke-width="12" pathLength="100" stroke-dasharray="' + percent + ' ' + (100-percent) + '" stroke-dashoffset="' + (-offset) + '" transform="rotate(-90 60 60)"/>';
      offset += percent;
      legend += '<div><i class="dash-dot" style="background:' + colors[i] + '" aria-hidden="true"></i><span>' + e(UI.nomStatut(s)) + '</span><b>' + e(number(n)) + ' · ' + e(percent.toLocaleString(document.documentElement.lang, { maximumFractionDigits: 1 })) + '%</b></div>';
    });
    if (!d.stock.total) state('dash-statuts', 'empty');
    else $('dash-statuts').innerHTML = '<div class="dash-status-layout"><svg class="dash-donut" viewBox="0 0 120 120" aria-hidden="true">' + circles + '</svg><div class="dash-legend">' + legend + '</div></div>';
    if (!d.destinations.length) state('dash-destinations', 'empty');
    else $('dash-destinations').innerHTML = bars(d.destinations.map(function (r) { return { label:r.pays + ' · ' + r.ville, n:r.n }; })) + '<p class="dash-muted">' + e(number(d.destinations.length)) + ' / ' + e(number(d.destinations_nombre)) + ' · ' + e(t('destinations')) + '</p>';
  }
  function aggregates() {
    if (allowed('colis')) request('colis', ['ses-chiffres','dash-serie','dash-statuts','dash-destinations'], function () { return API.admin.dashboard('colis', f); }, renderColis);
    if (allowed('clients')) request('clients', ['dash-clients'], function () { return API.admin.dashboard('clients', f); }, function (d) {
      if (!d || d.version !== 1) throw new Error('Invalid dashboard response');
      $('dash-clients').innerHTML = '<div class="dash-number">' + e(number(d.total)) + '</div>' + comparison(d) + '<p class="dash-comparison">' + e(date(d.periode.debut)) + ' → ' + e(date(d.periode.fin_effective)) + '</p>';
    });
  }
  function recent() {
    if (!allowed('colis')) return;
    var form = $('dash-recherche'), tri = form.elements.tri.value.split(':');
    $('dash-pages').innerHTML = '';
    request('recents', ['dash-recents'], function () { return API.admin.dashboardRecents({ page:page, recherche:form.elements.recherche.value.trim(), statut:form.elements.statut.value, tri:tri[0], asc:tri[1]==='asc' }); }, function (d) {
      if (page > 0 && page * 20 >= d.total) { page = Math.max(0, Math.ceil(d.total / 20)-1); recent(); return; }
      if (!d.lignes.length) { state('dash-recents', 'empty'); return; }
      $('dash-recents').innerHTML = '<table class="dash-table"><caption>' + e(number(d.total)) + ' · ' + e(t('count')) + '</caption><thead><tr>' + ['reference','recipient','destination','weight','service','status','date','action'].map(function (k) { return '<th scope="col">' + e(t(k)) + '</th>'; }).join('') + '</tr></thead><tbody>' + d.lignes.map(function (c) {
        return '<tr><th scope="row">' + e(c.numero) + '</th><td>' + e(c.destinataire || '—') + '</td><td>' + e(c.pays_destination + ' · ' + (c.ville_destination || '—')) + '</td><td>' + (c.poids_lb == null ? '—' : e(number(c.poids_lb)) + ' lb') + '</td><td>' + e(t(c.service)) + '</td><td>' + UI.pastille(c.statut, { petite:true }) + '</td><td>' + e(date(c.cree_le)) + '</td><td><button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini" data-action="fiche" data-id="' + e(c.id) + '">' + e(t('open')) + '</button></td></tr>';
      }).join('') + '</tbody></table>';
      $('dash-pages').innerHTML = '<button type="button" class="ses-bouton ses-bouton-second" data-dash-page="-1"' + (page === 0 ? ' disabled' : '') + '>' + e(t('previous')) + '</button><span>' + (page+1) + ' / ' + Math.ceil(d.total/20) + '</span><button type="button" class="ses-bouton ses-bouton-second" data-dash-page="1"' + ((page+1)*20>=d.total ? ' disabled' : '') + '>' + e(t('next')) + '</button>';
    });
  }
  function activity() {
    if (!allowed('colis')) return;
    request('activite', ['dash-activite'], function () { return API.admin.dashboardActivite(); }, function (rows) {
      if (!rows.length) { state('dash-activite', 'empty'); return; }
      $('dash-activite').innerHTML = '<ol class="dash-events">' + rows.map(function (r) {
        return '<li><span class="dash-event-mark" aria-hidden="true">↗</span><div><p><strong>' + e(r.colis && r.colis.numero || '—') + '</strong> · ' + e(UI.nomStatut(r.statut)) + '</p><small>' + e([r.lieu,r.auteur].filter(Boolean).join(' · ')) + '</small></div><time datetime="' + e(r.cree_le) + '">' + e(date(r.cree_le)) + '</time></li>';
      }).join('') + '</ol>';
    });
  }
  function apply() {
    var form = $('dash-filtres');
    if (!window.SES_A11Y.valider(form)) return;
    var next = {}; new FormData(form).forEach(function (v,k) { next[k] = v; });
    if (next.debut && next.fin && next.fin <= next.debut) {
      window.SES_A11Y.erreurChamp(form.elements.fin, t('invalid'));
      return;
    }
    f = next; $('dash-periode-info').textContent = t('loading'); aggregates();
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
    if (API.mode !== 'supabase') { $('dash-mode').hidden = false; $('dash-mode').textContent = t('real'); }
    var form = $('dash-filtres'); form.noValidate = true; form.elements.date.value = localDay();
    form.elements.periode.addEventListener('change', function () {
      var custom = ['heures','personnalise'].indexOf(this.value) >= 0;
      $('dash-date-label').hidden = custom; form.elements.date.disabled = custom;
      ['debut','fin'].forEach(function (k) { $('dash-'+k+'-label').hidden = !custom; form.elements[k].disabled = !custom; form.elements[k].required = custom; });
    });
    form.addEventListener('submit', function (ev) { ev.preventDefault(); apply(); });
    $('dash-refresh').addEventListener('click', function () { aggregates(); recent(); activity(); });
    $('dash-recherche').addEventListener('submit', function (ev) { ev.preventDefault(); clearTimeout(timer); page=0; recent(); });
    $('dash-recherche').addEventListener('input', function () { clearTimeout(timer); generations.recents=(generations.recents||0)+1; timer=setTimeout(function () { page=0; recent(); },250); });
    $('ses-p-dashboard').addEventListener('click', function (ev) {
      var b=ev.target.closest('[data-dash-retry],[data-dash-page]'); if (!b) return;
      if (b.dataset.dashPage) { page+=Number(b.dataset.dashPage); recent(); }
      else if (b.dataset.dashRetry==='recents') recent(); else if (b.dataset.dashRetry==='activite') activity(); else aggregates();
    });
    $('dash-menu').addEventListener('click',function () { menu(this.getAttribute('aria-expanded')!=='true'); });
    $('dash-voile').addEventListener('click',function () { menu(false); });
    $('dash-navigation').addEventListener('click',function (ev) { if(ev.target.closest('[role=tab]') && !$('dash-voile').hidden) menu(false); });
    document.addEventListener('keydown',function (ev) {
      if ($('dash-voile').hidden) return;
      if(ev.key==='Escape') { ev.preventDefault(); menu(false); }
      if(ev.key==='Tab') {
        var items=Array.from($('dash-navigation').querySelectorAll('a,button')).filter(function (b) {return !b.hidden && b.getClientRects().length;});
        var first=items[0],last=items[items.length-1];
        if(ev.shiftKey && document.activeElement===first) {ev.preventDefault();last.focus();}
        else if(!ev.shiftKey && document.activeElement===last) {ev.preventDefault();first.focus();}
      }
    });
    window.matchMedia('(min-width:901px)').addEventListener('change',function (ev) { if(ev.matches) { $('dash-voile').hidden=true; $('dash-navigation').classList.remove('is-open'); $('dash-menu').setAttribute('aria-expanded','false'); } });
    UI.surLangue(function () { Object.keys(cache).forEach(function (k) { cache[k].render(cache[k].data); }); });
    document.addEventListener('visibilitychange',function () { if(!document.hidden) refresh(); });
    apply(); recent(); activity();
  }
  var refreshTimer;
  function refresh(domain) {
    if (!started) return;
    clearTimeout(refreshTimer); refreshTimer=setTimeout(function () {
      if (domain !== 'factures') { aggregates(); recent(); activity(); }
    },350);
  }
  window.SES_DASHBOARD = { init:init, refresh:refresh };
})();
