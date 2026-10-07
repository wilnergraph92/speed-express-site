/* Speed Express Shipping — sélecteur de langue <lang-switcher>
   Shadow DOM (invisible à React). Les dictionnaires ne sont téléchargés
   qu'à la demande : une visite en français ne paie rien. */
(function () {
  if (customElements.get('lang-switcher')) return;

  var KEY = 'ses-lang';
  var FLAGS = {
    en: '<svg aria-hidden="true" focusable="false" viewBox="0 0 60 40" width="26" height="18"><rect width="60" height="40" fill="#012169"/><path d="M0 0l60 40M60 0L0 40" stroke="#fff" stroke-width="8"/><path d="M0 0l60 40M60 0L0 40" stroke="#C8102E" stroke-width="4"/><path d="M30 0v40M0 20h60" stroke="#fff" stroke-width="13"/><path d="M30 0v40M0 20h60" stroke="#C8102E" stroke-width="8"/></svg>',
    es: '<svg aria-hidden="true" focusable="false" viewBox="0 0 60 40" width="26" height="18"><rect width="60" height="40" fill="#AA151B"/><rect y="10" width="60" height="20" fill="#F1BF00"/></svg>',
    fr: '<svg aria-hidden="true" focusable="false" viewBox="0 0 60 40" width="26" height="18"><rect width="60" height="40" fill="#fff"/><rect width="20" height="40" fill="#002395"/><rect x="40" width="20" height="40" fill="#ED2939"/></svg>',
    ht: '<svg aria-hidden="true" focusable="false" viewBox="0 0 60 40" width="26" height="18"><rect width="60" height="40" fill="#00209F"/><rect y="20" width="60" height="20" fill="#D21034"/><rect x="22" y="12" width="16" height="16" fill="#fff"/><circle cx="30" cy="20" r="3.4" fill="#00209F"/><path d="M30 13.5v13M25 20h10" stroke="#F1B517" stroke-width="1.4"/></svg>'
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
  var V = '40';
  /* Chaque page ne reçoit que son propre dictionnaire. Les entrées vraiment
     communes ont été remontées dans lang-dict.js pour ne pas charger une
     partie entière simplement pour deux mots du menu. */
  var PAGE_PARTS = {
    'index.html': ['lang-dict-2.js', 'lang-dict-3.js'],
    'nos-services.html': ['lang-dict-3.js'],
    'a-propos.html': ['lang-dict-3.js'],
    'suivi.html': ['lang-dict-3.js'],
    'blog.html': ['lang-dict-3.js'],
    'contacts.html': ['lang-dict-3.js'],
    'confidentialite.html': ['lang-dict-4.js'],
    'support.html': ['lang-dict-4.js'],
    'fermer-un-compte.html': ['lang-dict-4.js'],
    'termes-et-conditions.html': ['lang-dict-5.js'],
    'marchandises-dangereuses.html': ['lang-dict-5.js'],
    'article-boutiques-chinoises.html': ['lang-dict-10.js'],
    'article-conseils-livraison.html': ['lang-dict-7.js'],
    'article-entreprise-fiable.html': ['lang-dict-9.js'],
    'article-impact-ecommerce.html': ['lang-dict-8.js'],
    'article-maritime-vs-aerien.html': ['lang-dict-9.js'],
    'article-optimiser-expeditions.html': ['lang-dict-10.js'],
    'article-partenaire-colis-etranger.html': ['lang-dict-6.js'],
    'article-pourquoi-speed-express.html': ['lang-dict-6.js'],
    'article-premiere-livraison.html': ['lang-dict-6.js'],
    'article-service-de-messagerie.html': ['lang-dict-8.js'],
    'article-tendances-2026.html': ['lang-dict-7.js'],
    'connexion.html': ['lang-dict-11.js'],
    'creer-un-compte.html': ['lang-dict-11.js'],
    'nouveau-mot-de-passe.html': ['lang-dict-11.js'],
    'espace-client.html': ['lang-dict-11.js'],
    'tableau-de-bord.html': ['lang-dict-11.js']
  };
  var page = location.pathname.replace(/\/+$/, '').split('/').pop() || 'index.html';
  if (page.indexOf('.html') === -1) page = 'index.html';
  var PARTS = ['lang-dict.js'].concat(PAGE_PARTS[page] || []).map(function (f) {
    return 'assets/js/' + f + '?v=' + V;
  });
  var dictionnairesPrets = PARTS.length === 0;
  var traductionInitialeFaite = false;
  var chargementParties = null;
  var partiesChargees = new Set();

  function current() {
    try { var code = localStorage.getItem(KEY); return ['fr','en','es','ht'].indexOf(code) >= 0 ? code : 'fr'; } catch (e) { return 'fr'; }
  }
  function norm(s) { return s.replace(/[\u2018\u2019]/g, "'").replace(/\s+/g, ' ').trim(); }

  /* ---------- traduction : lit/écrit uniquement nodeValue (React tolère) ---------- */
  var busy = false, mo = null;
  /* Le titre de l'onglet (<title>) : il vit dans <head>, hors du <body> que le
     parcours ci-dessous explore, et n'était donc jamais traduit. On retient son
     texte français d'origine une fois, et on le retraduit à chaque changement. */
  var TITRE_FR = null;
  function traduireTitre(i, dict) {
    if (TITRE_FR === null) TITRE_FR = document.title;
    var hit = i !== undefined ? dict[norm(TITRE_FR)] : null;
    var out = hit && hit[i] ? hit[i] : TITRE_FR;
    if (document.title !== out) document.title = out;
  }
  function translate(lang, racines) {
    if ((!dictionnairesPrets && lang !== 'fr') || busy || !document.body) return;
    busy = true;
    if (mo) mo.disconnect();
    var dict = window.SES_DICT || {};
    var i = IDX[lang];
    var roots = racines || [document.body];
    var list = [];
    roots.forEach(function (root) {
    if (root.nodeType === Node.TEXT_NODE) {
      if (root.parentElement && !/^(SCRIPT|STYLE|TEXTAREA)$/.test(root.parentElement.nodeName)) list.push(root);
      return;
    }
    var w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function (n) {
        var p = n.parentElement;
        if (!p) return NodeFilter.FILTER_REJECT;
        var t = p.nodeName;
        if (t === 'SCRIPT' || t === 'STYLE' || t === 'TEXTAREA') return NodeFilter.FILTER_REJECT;
        return n.nodeValue && n.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      }
    });
    var n;
    while ((n = w.nextNode())) list.push(n);
    });
    /* Le contenu d'un <template> vit hors de l'arbre : le parcours ci-dessus
       ne l'atteint pas. Les pages de l'espace client y rangent leurs textes
       (statuts, messages, colonnes) — ils doivent suivre la langue eux aussi. */
    if (!racines) traduireTitre(i, dict);
    if (!racines) document.querySelectorAll('template[data-textes]').forEach(function (modele) {
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
    var elements = [];
    roots.forEach(function (root) {
      if (root.nodeType !== Node.ELEMENT_NODE) return;
      if (root.matches('[placeholder],[title],[aria-label],[alt]')) elements.push(root);
      root.querySelectorAll('[placeholder],[title],[aria-label],[alt]').forEach(function (el) { elements.push(el); });
    });
    elements.forEach(function (el) {
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
    var timer, pending = new Set();
    mo = new MutationObserver(function (records) {
      if (busy) return;
      records.forEach(function (record) {
        if (record.type === 'characterData') { ORIG.delete(record.target); pending.add(record.target); }
        else record.addedNodes.forEach(function (node) {
          if (node.nodeType === Node.TEXT_NODE || node.nodeType === Node.ELEMENT_NODE) pending.add(node);
        });
      });
      if (current() === 'fr') { pending.clear(); return; }
      clearTimeout(timer);
      timer = setTimeout(function () {
        var nodes = Array.from(pending).filter(function (node) { return node.isConnected; });
        pending.clear();
        nodes = nodes.filter(function (node) { return !nodes.some(function (other) { return other !== node && other.contains(node); }); });
        if (nodes.length) translate(current(), nodes);
      }, 140);
    });
    mo.observe(document.body, { childList: true, subtree: true, characterData: true });
  }

  /* Un seul parcours initial, une fois toutes les parties utiles chargées.
     Sans partie complémentaire, le composant déclenche ce même parcours au
     premier rendu. */
  function initialiserTraduction() {
    if (traductionInitialeFaite || !document.body || (current() !== 'fr' && !dictionnairesPrets)) return;
    traductionInitialeFaite = true;
    if (current() !== 'fr') translate(current());
    else document.documentElement.lang = 'fr';
    watch();
  }

  /* French source is already rendered: page dictionaries are fetched only
     on a non-French visit or a user language choice. Common dictionary stays
     available to existing code. One promise shares downloads across switchers. */
  function chargerParties() {
    if (chargementParties) return chargementParties;
    chargementParties = Promise.all(PARTS.map(function (src) {
      if (partiesChargees.has(src)) return Promise.resolve(true);
      return new Promise(function (resolve) {
        var s = document.createElement('script');
        s.src = src; s.async = false;
        s.onload = function () { partiesChargees.add(src); resolve(true); };
        s.onerror = function () { s.remove(); resolve(false); };
        (document.head || document.documentElement).appendChild(s);
      });
    })).then(function (results) {
      dictionnairesPrets = results.every(Boolean);
      if (!dictionnairesPrets) chargementParties = null; // next choice retries failed load
      return dictionnairesPrets;
    });
    return chargementParties;
  }
  if (current() !== 'fr') chargerParties().then(function (ok) {
    if (ok) initialiserTraduction();
  });

  /* ---------- composant : menu bouton conforme au parcours clavier ---------- */
  class LangSwitcher extends HTMLElement {
    connectedCallback() {
      if (this._root) return;
      this._root = this.attachShadow({ mode: 'open' });
      this.render();
      this._out = function (ev) {
        if (this._open && !ev.composedPath().includes(this)) this.toggle(false);
      }.bind(this);
      document.addEventListener('click', this._out);
      this._sync = function () { this.render(); }.bind(this);
      window.addEventListener('ses-lang', this._sync);
      var self = this;
      requestAnimationFrame(function () { initialiserTraduction(); self.render(); });
    }
    disconnectedCallback() {
      document.removeEventListener('click', this._out);
      window.removeEventListener('ses-lang', this._sync);
    }
    toggle(v, retour, position) {
      this._open = v === undefined ? !this._open : v;
      var menu = this._root.querySelector('.menu');
      var bouton = this._root.querySelector('.btn');
      bouton.setAttribute('aria-expanded', this._open ? 'true' : 'false');
      menu.classList.toggle('open', this._open);
      this._root.querySelector('.chev').classList.toggle('up', this._open);
      if (this._open) {
        menu.style.marginLeft = '0px';
        var r = menu.getBoundingClientRect(), over = r.right - (window.innerWidth - 14);
        if (over > 0) menu.style.marginLeft = -Math.min(over, r.left - 14) + 'px';
        var items = this._root.querySelectorAll('.item');
        var actif = this._root.querySelector('.item.on') || items[0];
        (position === undefined ? actif : items[position]).focus();
      } else if (retour) bouton.focus();
    }
    pick(code) {
      var self = this;
      if (code === current() && document.documentElement.lang === code && (code === 'fr' || dictionnairesPrets)) {
        this.toggle(false, true);
        return;
      }
      try { localStorage.setItem(KEY, code); } catch (e) {}
      this.toggle(false, true);
      function appliquer() {
        if (current() !== code) return;
        translate(code);
        self.render();
        watch();
        window.dispatchEvent(new CustomEvent('ses-lang', { detail: code }));
      }
      if (code === 'fr') appliquer();
      else chargerParties().then(function (ok) { if (ok) appliquer(); });
    }
    render() {
      /* Changer la langue reconstruit le Shadow DOM : le nouveau bouton doit
         remplacer l'ancien dans le parcours, sans perdre le focus sur body. */
      var avaitFocus = !!this._root.activeElement;
      if (this._clavier) this._root.removeEventListener('keydown', this._clavier);
      if (this._sortieFocus) this._root.removeEventListener('focusout', this._sortieFocus);
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
        ';border:1px solid ' + (dark ? 'rgba(255,255,255,.22)' : 'rgba(11,12,14,.16)') +
        ';border-radius:999px;padding:8px 14px;cursor:pointer;color:' + (dark ? '#fff' : '#14161a') +
        ';font-weight:700;font-size:14.5px;line-height:1;white-space:nowrap;font-family:inherit;transition:background .2s,border-color .2s}' +
        '.btn:hover{background:' + (dark ? 'rgba(255,255,255,.16)' : '#f5f6f8') + ';border-color:#e8121b}' +
        '.chev{width:7px;height:7px;border-right:2px solid currentColor;border-bottom:2px solid currentColor;transform:rotate(45deg);transition:transform .2s;margin:-3px 0 0 2px}' +
        '.chev.up{transform:rotate(-135deg);margin-top:2px}' +
        '.menu{position:absolute;top:calc(100% + 12px);left:0;min-width:246px;background:#fff;border-radius:26px;box-shadow:0 28px 64px -20px rgba(11,12,14,.55);padding:18px 16px;display:grid;gap:6px;opacity:0;visibility:hidden;pointer-events:none;transform:translateY(-8px);transition:opacity .18s,transform .18s;z-index:300}' +
        '.menu.open{opacity:1;visibility:visible;pointer-events:auto;transform:translateY(0)}' +
        '.item{display:flex;align-items:center;gap:16px;width:100%;background:transparent;border:0;border-radius:14px;padding:13px 16px;cursor:pointer;color:#14161a;font-weight:700;font-size:17px;text-align:left;font-family:inherit;transition:background .15s}' +
        '.item:hover,.item:focus{background:#f5f6f8}' +
        '.item.on{background:#f1f2f4;color:#b60d14}' +
        ':focus-visible{outline:3px solid #0b0c0e;outline-offset:3px;box-shadow:0 0 0 3px #fff}' +
        '@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}}' +
        '</style>' +
        '<button class="btn" type="button" aria-haspopup="menu" aria-expanded="false" aria-controls="ses-lang-menu" aria-label="' + WORD[cur] + ' : ' + active.label + '">' + FLAGS[cur] +
        '<span>' + WORD[cur] + '</span><span class="chev" aria-hidden="true"></span></button>' +
        '<div id="ses-lang-menu" class="menu" role="menu" aria-label="' + WORD[cur] + '">' +
        LANGS.map(function (l) {
          return '<button class="item' + (l.code === cur ? ' on' : '') + '" type="button" tabindex="-1" data-code="' + l.code + '" role="menuitemradio" aria-checked="' + (l.code === cur ? 'true' : 'false') + '">' +
            FLAGS[l.code] + '<span>' + l.label + '</span></button>';
        }).join('') + '</div>';
      var bouton = this._root.querySelector('.btn');
      bouton.addEventListener('click', function (ev) { ev.stopPropagation(); self.toggle(); });
      var items = Array.prototype.slice.call(this._root.querySelectorAll('.item'));
      items.forEach(function (b) {
        b.addEventListener('click', function (ev) { ev.stopPropagation(); self.pick(b.dataset.code); });
      });
      if (this._clavier) this._root.removeEventListener('keydown', this._clavier);
      this._clavier = function (ev) {
        if (ev.target === bouton && (ev.key === 'ArrowDown' || ev.key === 'ArrowUp')) {
          ev.preventDefault();
          self.toggle(true, false, ev.key === 'ArrowDown' ? 0 : items.length - 1);
          return;
        }
        if (!self._open) return;
        if (ev.key === 'Escape') {
          ev.preventDefault();
          ev.stopPropagation(); // ne ferme pas aussi le menu de navigation mobile
          self.toggle(false, true);
        } else if (ev.key === 'Tab') {
          // Laisser le Tab natif sortir, depuis le bouton désormais visible.
          self.toggle(false, true);
        } else if (['ArrowDown', 'ArrowUp', 'Home', 'End'].indexOf(ev.key) >= 0) {
          ev.preventDefault();
          var i = items.indexOf(self._root.activeElement);
          var prochain = ev.key === 'Home' ? 0 : ev.key === 'End' ? items.length - 1 :
            (i + (ev.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
          items[prochain].focus();
        }
      };
      this._root.addEventListener('keydown', this._clavier);
      if (this._sortieFocus) this._root.removeEventListener('focusout', this._sortieFocus);
      this._sortieFocus = function (ev) {
        if (!self._root.contains(ev.relatedTarget)) self.toggle(false);
      };
      this._root.addEventListener('focusout', this._sortieFocus);
      this._open = false;
      if (avaitFocus) bouton.focus();
    }
  }
  customElements.define('lang-switcher', LangSwitcher);
})();
