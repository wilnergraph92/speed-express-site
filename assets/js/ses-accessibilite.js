/* ==========================================================================
   Speed Express Shipping — primitives d'accessibilité partagées
   --------------------------------------------------------------------------
   Sans dépendance ni modification des données : un même comportement clavier
   et les mêmes associations d'erreurs sur le site public et l'espace client.
   ========================================================================== */
(function () {
  'use strict';

  var compteur = 0;
  function identifiant(prefixe) {
    var id;
    do { id = prefixe + '-' + (++compteur); } while (document.getElementById(id));
    return id;
  }

  function mouvementReduit() {
    return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  /* La préférence est relue à chaque action : elle peut changer sans recharger
     la page. Le CSS couvre les ancres ; ceci couvre les défilements JavaScript. */
  function defiler(zone, position) {
    if (zone) zone.scrollIntoView({ behavior: mouvementReduit() ? 'auto' : 'smooth', block: position || 'nearest' });
  }

  /* Un onglet par Tab, flèches circulaires et Home/End. Les panneaux locaux
     s'activent immédiatement ; les vues qui chargent des données utilisent
     l'activation manuelle (Enter/Espace sont déjà fournis par <button>). */
  function onglets(liste, options) {
    if (!liste || liste.getAttribute('data-ses-clavier')) return;
    liste.setAttribute('data-ses-clavier', 'true');
    options = options || {};
    var boutons = Array.prototype.slice.call(liste.querySelectorAll('[role="tab"]'));
    function visibles() {
      return boutons.filter(function (b) { return !b.hidden && !b.disabled && b.getAttribute('aria-disabled') !== 'true'; });
    }
    function indexTab(cible) {
      boutons.forEach(function (b) { b.tabIndex = b === cible ? 0 : -1; });
    }
    function activer(b, notifier) {
      if (!b || visibles().indexOf(b) < 0) return;
      boutons.forEach(function (x) {
        var actif = x === b;
        x.setAttribute('aria-selected', actif ? 'true' : 'false');
        if (x.classList.contains('rsn__onglet')) x.classList.toggle('rsn__onglet--actif', actif);
        var panneau = document.getElementById(x.getAttribute('aria-controls'));
        if (panneau) {
          panneau.hidden = !actif;
          panneau.tabIndex = 0;
          if (panneau.classList.contains('rsn__panneau')) panneau.classList.toggle('rsn__panneau--actif', actif);
        }
      });
      indexTab(b);
      if (notifier !== false && options.apresActivation) options.apresActivation(b);
    }
    boutons.forEach(function (b) {
      b.addEventListener('click', function () { activer(b); });
    });
    liste.addEventListener('keydown', function (ev) {
      var b = ev.target.closest('[role="tab"]');
      if (!b || boutons.indexOf(b) < 0) return;
      var vertical = liste.getAttribute('aria-orientation') === 'vertical';
      var sens = ev.key === 'ArrowRight' || (vertical && ev.key === 'ArrowDown') ? 1 :
        ev.key === 'ArrowLeft' || (vertical && ev.key === 'ArrowUp') ? -1 : 0;
      if (!sens && ev.key !== 'Home' && ev.key !== 'End') return;
      ev.preventDefault();
      var choix = visibles(), i = choix.indexOf(b);
      if (!choix.length) return;
      var suivant = ev.key === 'Home' ? 0 : ev.key === 'End' ? choix.length - 1 :
        (i + sens + choix.length) % choix.length;
      indexTab(choix[suivant]);
      choix[suivant].focus();
      if (options.automatique) activer(choix[suivant]);
    });
    liste.addEventListener('focusout', function (ev) {
      if (liste.contains(ev.relatedTarget)) return;
      indexTab(boutons.filter(function (b) { return b.getAttribute('aria-selected') === 'true'; })[0]);
    });
    activer(boutons.filter(function (b) { return b.getAttribute('aria-selected') === 'true' && !b.hidden; })[0] || visibles()[0], false);
    return activer;
  }

  function decrire(champ, id, ajouter) {
    var ids = (champ.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
    ids = ids.filter(function (x) { return x !== id; });
    if (ajouter) ids.push(id);
    if (ids.length) champ.setAttribute('aria-describedby', ids.join(' '));
    else champ.removeAttribute('aria-describedby');
  }

  function effacerErreur(champ) {
    var id = champ.getAttribute('data-ses-erreur');
    if (!id) return;
    var msg = document.getElementById(id);
    if (msg) msg.remove();
    decrire(champ, id, false);
    champ.removeAttribute('data-ses-erreur');
    champ.removeAttribute('aria-invalid');
    champ.removeEventListener('input', corriger);
    champ.removeEventListener('change', corriger);
  }
  function corriger(ev) { effacerErreur(ev.currentTarget); }

  /* Seules les erreurs effectives sont des alertes. L'identifiant appartient
     au champ, pas à son parent (qui peut contenir plusieurs champs). Les aides
     déjà présentes dans aria-describedby sont conservées, puis restaurées. */
  function erreurChamp(champ, texte, focus) {
    if (!champ) return;
    /* Dans un label enveloppant, l'erreur ne doit pas devenir une partie du
       nom du champ. Le libellé visible reste la source, donc reste traduisible. */
    var etiquette = champ.labels && champ.labels[0];
    if (etiquette && etiquette.contains(champ) && !champ.hasAttribute('aria-labelledby') && !champ.hasAttribute('aria-label')) {
      var libelle = etiquette.querySelector('span');
      if (!libelle || libelle.contains(champ)) {
        libelle = document.createElement('span');
        Array.prototype.slice.call(etiquette.childNodes).forEach(function (noeud) {
          if (noeud.nodeType === 3 && noeud.nodeValue.trim()) libelle.appendChild(noeud);
        });
        etiquette.insertBefore(libelle, etiquette.firstChild);
      }
      if (!libelle.id) libelle.id = identifiant('ses-libelle');
      champ.setAttribute('aria-labelledby', libelle.id);
      Array.prototype.forEach.call(etiquette.querySelectorAll('small'), function (aide) {
        if (!aide.id) aide.id = identifiant('ses-aide');
        decrire(champ, aide.id, true);
      });
    }
    var id = champ.getAttribute('data-ses-erreur');
    var msg = id && document.getElementById(id);
    if (!msg) {
      msg = document.createElement('p');
      msg.id = identifiant('ses-erreur');
      msg.className = 'ses-erreur';
      msg.setAttribute('role', 'alert');
      msg.setAttribute('aria-atomic', 'true');
      (champ.closest('.ses-champ') || champ.parentNode).appendChild(msg);
      champ.setAttribute('data-ses-erreur', msg.id);
      champ.addEventListener('input', corriger);
      champ.addEventListener('change', corriger);
    }
    decrire(champ, msg.id, true);
    champ.setAttribute('aria-invalid', 'true');
    if (!texte) {
      var defaut = 'Valeur incorrecte.';
      var i = { en: 0, es: 1, ht: 2 }[document.documentElement.lang];
      var traduit = (window.SES_DICT || {})[defaut];
      texte = champ.validationMessage || (i !== undefined && traduit ? traduit[i] : defaut);
    }
    msg.textContent = texte;
    if (focus !== false) champ.focus();
  }

  function effacerErreurs(form) {
    if (!form) return;
    Array.prototype.forEach.call(form.querySelectorAll('[data-ses-erreur]'), effacerErreur);
  }

  /* Le message natif suit la langue du navigateur ; une seule erreur à la
     fois évite de déplacer le focus et d'annoncer plusieurs alertes en rafale. */
  function valider(form) {
    effacerErreurs(form);
    var champs = form.elements;
    for (var i = 0; i < champs.length; i++) {
      if (champs[i].willValidate && !champs[i].validity.valid) {
        erreurChamp(champs[i], champs[i].validationMessage);
        return false;
      }
    }
    return true;
  }

  function demarrer() {
    Array.prototype.forEach.call(document.querySelectorAll('.rsn__onglets'), function (liste) {
      onglets(liste, { automatique: true });
    });
    Array.prototype.forEach.call(document.querySelectorAll('dialog'), function (dialogue) {
      dialogue.addEventListener('keydown', function (ev) {
        if (ev.key !== 'Tab') return;
        var champs = Array.prototype.slice.call(dialogue.querySelectorAll('a[href],button,input,select,textarea,[tabindex]')).filter(function (el) {
          return !el.matches(':disabled') && el.tabIndex >= 0 && el.getClientRects().length;
        });
        if (!champs.length) return;
        var premier = champs[0], dernier = champs[champs.length - 1];
        if (ev.shiftKey && document.activeElement === premier) { ev.preventDefault(); dernier.focus(); }
        else if (!ev.shiftKey && document.activeElement === dernier) { ev.preventDefault(); premier.focus(); }
      });
      dialogue.addEventListener('close', function () {
        // Le dialog natif rend normalement le focus à son ouvreur. Si une
        // liste a supprimé cet ouvreur, revenir à une section encore visible.
        if (document.activeElement !== document.body) return;
        var retour = document.querySelector('[role="tab"][aria-selected="true"]') || document.getElementById('contenu');
        if (retour && retour.getClientRects().length) retour.focus();
      });
    });
    var saut = document.querySelector('.ses-skip-link');
    if (saut) saut.addEventListener('click', function () {
      var contenu = document.getElementById('contenu');
      if (contenu) contenu.focus({ preventScroll: true });
    });
  }
  window.SES_A11Y = {
    onglets: onglets, erreurChamp: erreurChamp, effacerErreur: effacerErreur, effacerErreurs: effacerErreurs,
    valider: valider, decrire: decrire, defiler: defiler, mouvementReduit: mouvementReduit
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', demarrer);
  else demarrer();
})();
