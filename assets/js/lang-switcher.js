/* Speed Express Shipping — sélecteur de langue <lang-switcher>
   Shadow DOM (invisible à React). Charge lang-dict.js avant ce fichier. */
(function () {
  if (customElements.get('lang-switcher')) return;

  var KEY = 'ses-lang';
  var FLAGS = {
    en: '<svg viewBox="0 0 60 40" width="26" height="18"><rect width="60" height="40" fill="#012169"/><path d="M0 0l60 40M60 0L0 40" stroke="#fff" stroke-width="8"/><path d="M0 0l60 40M60 0L0 40" stroke="#C8102E" stroke-width="4"/><path d="M30 0v40M0 20h60" stroke="#fff" stroke-width="13"/><path d="M30 0v40M0 20h60" stroke="#C8102E" stroke-width="8"/></svg>',
    es: '<svg viewBox="0 0 60 40" width="26" height="18"><rect width="60" height="40" fill="#AA151B"/><rect y="10" width="60" height="20" fill="#F1BF00"/></svg>',
    fr: '<svg viewBox="0 0 60 40" width="26" height="18"><rect width="60" height="40" fill="#fff"/><rect width="20" height="40" fill="#002395"/><rect x="40" width="20" height="40" fill="#ED2939"/></svg>',
    ht: '<svg viewBox="0 0 60 40" width="26" height="18"><rect width="60" height="40" fill="#00209F"/><rect y="20" width="60" height="20" fill="#D21034"/><rect x="22" y="12" width="16" height="16" fill="#fff"/><circle cx="30" cy="20" r="3.4" fill="#00209F"/><path d="M30 13.5v13M25 20h10" stroke="#F1B517" stroke-width="1.4"/></svg>'
  };
  var LANGS = [
    { code: 'en', label: 'English' },
    { code: 'es', label: 'Spanish' },
    { code: 'fr', label: 'French' },
    { code: 'ht', label: 'Creole' }
  ];
  var IDX = { en: 0, es: 1, ht: 2 };
  var WORD = { en: 'Language', es: 'Idioma', fr: 'Langue', ht: 'Lang' };
  var ORIG = new WeakMap();
  var ORIGA = new WeakMap();
  var ATTRS = ['placeholder', 'title', 'aria-label', 'alt'];
  /* Numéro de version : à augmenter après chaque modification des
     dictionnaires, pour que les navigateurs rechargent les nouveaux textes
     au lieu de servir leur copie en cache. */
  var V = '8';
  var PARTS = ['assets/js/lang-dict-2.js', 'assets/js/lang-dict-3.js', 'assets/js/lang-dict-4.js',
               'assets/js/lang-dict-5.js', 'assets/js/lang-dict-6.js', 'assets/js/lang-dict-7.js',
               'assets/js/lang-dict-8.js', 'assets/js/lang-dict-9.js', 'assets/js/lang-dict-10.js',
               'assets/js/lang-dict-11.js']
              .map(function (f) { return f + '?v=' + V; });

  function current() {
    try { return localStorage.getItem(KEY) || 'fr'; } catch (e) { return 'fr'; }
  }
  function norm(s) { return s.replace(/[\u2018\u2019]/g, "'").replace(/\s+/g, ' ').trim(); }

  /* ---------- traduction : lit/écrit uniquement nodeValue (React tolère) ---------- */
  var busy = false, mo = null;
  function translate(lang) {
    if (busy || !document.body) return;
    busy = true;
    if (mo) mo.disconnect();
    var dict = window.SES_DICT || {};
    var i = IDX[lang];
    var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode: function (n) {
        var p = n.parentElement;
        if (!p) return NodeFilter.FILTER_REJECT;
        var t = p.nodeName;
        if (t === 'SCRIPT' || t === 'STYLE' || t === 'TEXTAREA') return NodeFilter.FILTER_REJECT;
        return n.nodeValue && n.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      }
    });
    var list = [], n;
    while ((n = w.nextNode())) list.push(n);
    /* Le contenu d'un <template> vit hors de l'arbre : le parcours ci-dessus
       ne l'atteint pas. Les pages de l'espace client y rangent leurs textes
       (statuts, messages, colonnes) — ils doivent suivre la langue eux aussi. */
    document.querySelectorAll('template[data-textes]').forEach(function (modele) {
      var wt = document.createTreeWalker(modele.content, NodeFilter.SHOW_TEXT, null);
      var m;
      while ((m = wt.nextNode())) if (m.nodeValue && m.nodeValue.trim()) list.push(m);
    });
    list.forEach(function (node) {
      if (!ORIG.has(node)) ORIG.set(node, node.nodeValue);
      var fr = ORIG.get(node), out = fr;
      if (i !== undefined) {
        var hit = dict[norm(fr)];
        if (hit && hit[i]) out = fr.match(/^\s*/)[0] + hit[i] + fr.match(/\s*$/)[0];
      }
      if (node.nodeValue !== out) node.nodeValue = out;
    });
    document.querySelectorAll('[placeholder],[title],[aria-label],[alt]').forEach(function (el) {
      var store = ORIGA.get(el);
      if (!store) { store = {}; ORIGA.set(el, store); }
      ATTRS.forEach(function (a) {
        if (!el.hasAttribute(a)) return;
        if (!(a in store)) store[a] = el.getAttribute(a) || '';
        var fr = store[a], out = fr;
        if (i !== undefined) {
          var hit = dict[norm(fr)];
          if (hit && hit[i]) out = hit[i];
        }
        if (el.getAttribute(a) !== out) el.setAttribute(a, out);
      });
    });
    document.documentElement.lang = lang;
    busy = false;
    if (mo) mo.observe(document.body, { childList: true, subtree: true, characterData: true });
  }

  /* React re-rend : on retraduit les nœuds recréés */
  function watch() {
    if (mo || !window.MutationObserver || !document.body) return;
    var t;
    mo = new MutationObserver(function () {
      if (busy) return;
      clearTimeout(t);
      t = setTimeout(function () { translate(current()); }, 140);
    });
    mo.observe(document.body, { childList: true, subtree: true, characterData: true });
  }

  /* dictionnaires complémentaires (contenu des pages) */
  PARTS.forEach(function (src) {
    var s = document.createElement('script');
    s.src = src;
    s.async = true;
    s.onload = function () { translate(current()); };
    (document.head || document.documentElement).appendChild(s);
  });

  /* ---------- composant ---------- */
  class LangSwitcher extends HTMLElement {
    connectedCallback() {
      if (this._root) return;
      this._root = this.attachShadow({ mode: 'open' });
      this.render();
      this._out = function (e) { if (this._open && !e.composedPath().includes(this)) this.toggle(false); }.bind(this);
      document.addEventListener('click', this._out);
      this._sync = function () { this.render(); }.bind(this);
      window.addEventListener('ses-lang', this._sync);
      var self = this;
      requestAnimationFrame(function () { translate(current()); watch(); self.render(); });
    }
    disconnectedCallback() {
      document.removeEventListener('click', this._out);
      window.removeEventListener('ses-lang', this._sync);
    }
    toggle(v) {
      this._open = v === undefined ? !this._open : v;
      var m = this._root.querySelector('.menu');
      if (m) {
        m.classList.toggle('open', this._open);
        if (this._open) {
          m.style.marginLeft = '0px';
          var r = m.getBoundingClientRect(), over = r.right - (window.innerWidth - 14);
          if (over > 0) m.style.marginLeft = -Math.min(over, r.left - 14) + 'px';
        }
      }
      var c = this._root.querySelector('.chev');
      if (c) c.classList.toggle('up', this._open);
    }
    pick(code) {
      try { localStorage.setItem(KEY, code); } catch (e) {}
      this.toggle(false);
      translate(code);
      this.render();
      window.dispatchEvent(new CustomEvent('ses-lang', { detail: code }));
    }
    render() {
      var cur = current();
      var active = LANGS.filter(function (l) { return l.code === cur; })[0] || LANGS[2];
      var dark = this.getAttribute('theme') !== 'light';
      var self = this;

      this._root.innerHTML =
        '<style>' +
        ':host{position:relative;display:inline-block;vertical-align:middle;font-family:Manrope,system-ui,sans-serif}' +
        'svg{display:block;border-radius:3px;flex:none}' +
        '.item svg{width:30px;height:21px}' +
        '.btn{display:flex;align-items:center;gap:9px;background:' + (dark ? 'rgba(255,255,255,.08)' : '#fff') +
        ';border:1px solid ' + (dark ? 'rgba(255,255,255,.22)' : 'rgba(13,43,107,.16)') +
        ';border-radius:999px;padding:8px 14px;cursor:pointer;color:' + (dark ? '#fff' : '#14161a') +
        ';font-weight:700;font-size:14.5px;line-height:1;white-space:nowrap;font-family:inherit;transition:background .2s,border-color .2s}' +
        '.btn:hover{background:' + (dark ? 'rgba(255,255,255,.16)' : '#f5f6f8') + ';border-color:#e8121b}' +
        '.chev{width:7px;height:7px;border-right:2px solid currentColor;border-bottom:2px solid currentColor;transform:rotate(45deg);transition:transform .2s;margin:-3px 0 0 2px}' +
        '.chev.up{transform:rotate(-135deg);margin-top:2px}' +
        '.menu{position:absolute;top:calc(100% + 12px);left:0;min-width:246px;background:#fff;border-radius:26px;box-shadow:0 28px 64px -20px rgba(3,15,43,.55);padding:18px 16px;display:grid;gap:6px;opacity:0;visibility:hidden;pointer-events:none;transform:translateY(-8px);transition:opacity .18s,transform .18s;z-index:300}' +
        '.menu.open{opacity:1;visibility:visible;pointer-events:auto;transform:translateY(0)}' +
        '.item{display:flex;align-items:center;gap:16px;width:100%;background:transparent;border:0;border-radius:14px;padding:13px 16px;cursor:pointer;color:#14161a;font-weight:700;font-size:17px;text-align:left;font-family:inherit;transition:background .15s}' +
        '.item:hover{background:#f5f6f8}' +
        '.item.on{background:#f1f2f4;color:#e8121b}' +
        '</style>' +
        '<button class="btn" type="button" aria-haspopup="true">' + FLAGS[cur] +
        '<span>' + WORD[cur] + '</span><span class="chev"></span></button>' +
        '<div class="menu" role="menu">' +
        LANGS.map(function (l) {
          return '<button class="item' + (l.code === cur ? ' on' : '') + '" type="button" data-code="' + l.code + '" role="menuitem">' +
            FLAGS[l.code] + '<span>' + l.label + '</span></button>';
        }).join('') + '</div>';

      this._root.querySelector('.btn').addEventListener('click', function (e) { e.stopPropagation(); self.toggle(); });
      this._root.querySelectorAll('.item').forEach(function (b) {
        b.addEventListener('click', function (e) { e.stopPropagation(); self.pick(b.dataset.code); });
      });
      this._open = false;
    }
  }
  customElements.define('lang-switcher', LangSwitcher);
})();
