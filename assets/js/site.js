/* ==========================================================================
   Speed Express Shipping — comportements du site
   ==========================================================================
   Deux choses seulement : le suivi de colis et le formulaire de contact.
   Tout le reste du site est du HTML et du CSS, sans JavaScript.
   ========================================================================== */
(function () {
  'use strict';

  /* Si le CDN d'images ne répond pas, la photo locale du camion garde un
     visuel cohérent sans refaire la requête distante en boucle. */
  document.addEventListener('error', function (e) {
    var image = e.target;
    if (!image || image.tagName !== 'IMG' || !image.getAttribute('data-fallback') ||
        image.getAttribute('data-ses-fallback-applique')) return;
    image.setAttribute('data-ses-fallback-applique', '1');
    image.removeAttribute('srcset');
    image.setAttribute('src', image.getAttribute('data-fallback'));
  }, true);

  var C = window.SES_CONFIG || {};

  function bloc(nom) { return document.querySelector('[data-ses-if="' + nom + '"]'); }
  function montrer(el) { if (el) el.hidden = false; }
  function cacher(el) { if (el) el.hidden = true; }

  /* Les erreurs publiques partagent les mêmes IDs, descriptions et annonces
     que les comptes : pas de message orphelin ni d'écouteurs empilés. */
  function erreur(champ, texte) {
    window.SES_A11Y.erreurChamp(champ, texte);
  }

  /* --- Textes de la page (traduits avec elle) --------------------------- */
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
    var out = textes[cle] === undefined ? '' : textes[cle];
    Object.keys(valeurs || {}).forEach(function (k) { out = out.split('{' + k + '}').join(valeurs[k]); });
    return out;
  }

  function quandDate(iso) {
    var d = new Date(iso);
    if (!iso || isNaN(d)) return '';
    var locales = { fr: 'fr-FR', en: 'en-US', es: 'es-DO', ht: 'fr-FR' };
    var l = locales[(document.documentElement.lang || 'fr').slice(0, 2)] || 'fr-FR';
    try {
      return d.toLocaleDateString(l, { day: '2-digit', month: 'short', year: 'numeric',
                                       hour: '2-digit', minute: '2-digit' });
    } catch (e) { return d.toISOString().slice(0, 16).replace('T', ' '); }
  }

  /* --- Suivi de colis ---------------------------------------------------
     La page interroge la base par SES_API.suivre() : c'est elle que vise le
     QR code des étiquettes (suivi.html?colis=SES-10001-HT). La réponse ne
     contient que le numéro, le statut et les étapes — ni nom, ni adresse :
     ce formulaire est ouvert à tout le monde.

     Le bloc de résultat ne s'affiche que pour un vrai colis trouvé dans la
     base. Sans base configurée, si le réseau est coupé ou si le numéro est
     inconnu, la page le dit clairement au lieu d'inventer un parcours. */
  function suivi() {
    var form = document.querySelector('[data-ses-form="suivi"]');
    if (!form) return;
    var champ = form.querySelector('[data-ses-input="suivi"]') || form.querySelector('input');
    var resultat = bloc('trackResult') || bloc('result');
    var API = window.SES_API;
    var annonce = document.getElementById('ses-suivi-annonce');

    function afficher(colis) {
      var cible = resultat && resultat.querySelector('[data-ses-ref]');
      if (cible) cible.textContent = colis.numero;

      var zoneStatut = resultat && resultat.querySelector('[data-ses-statut]');
      var zoneMaj = resultat && resultat.querySelector('[data-ses-maj]');
      if (zoneStatut) {
        var dernier = (colis.historique || [])[(colis.historique || []).length - 1];
        zoneStatut.textContent = (t('statut-' + colis.statut) || colis.statut) +
          (dernier && dernier.lieu ? ' · ' + dernier.lieu : '');
      }
      if (zoneMaj) {
        zoneMaj.textContent = t('suivi-maj', { date: quandDate(colis.maj_le) });
      }
      montrer(resultat);
      if (annonce) annonce.textContent = [colis.numero, zoneStatut && zoneStatut.textContent, zoneMaj && zoneMaj.textContent].filter(Boolean).join(' · ');
      if (resultat) window.SES_A11Y.defiler(resultat, 'nearest');
    }

    /* Pas de base, ou réseau coupé : on l'annonce, on ne montre rien. */
    function indisponible() {
      erreur(champ, t('suivi-indisponible') ||
        'Le suivi est momentanément indisponible. Réessayez dans un instant, ou écrivez-nous sur WhatsApp.');
      cacher(resultat);
    }

    function chercher(ref, jeton) {
      window.SES_A11Y.effacerErreurs(form);
      if (annonce) annonce.textContent = '';
      if (!ref) {
        erreur(champ, t('suivi-vide') ||
          'Saisissez votre numéro de suivi pour voir où est votre colis.');
        cacher(resultat);
        return;
      }
      if (!API || API.mode === 'off' || !API.suivre) {
        indisponible();
        return;
      }
      var bouton = form.querySelector('button[type="submit"], button:not([type])');
      var avant = bouton ? bouton.innerHTML : '';
      var avaitFocus = document.activeElement === bouton;
      function libererBouton() {
        if (!bouton) return;
        bouton.disabled = false;
        bouton.removeAttribute('aria-busy');
        bouton.innerHTML = avant;
        if (avaitFocus && document.activeElement === document.body) bouton.focus({ preventScroll: true });
      }
      if (bouton) {
        bouton.disabled = true;
        bouton.setAttribute('aria-busy', 'true');
        bouton.textContent = t('suivi-recherche') || bouton.textContent;
      }

      API.suivre(ref, jeton || null).then(function (colis) {
        libererBouton();
        if (!colis || !colis.numero) {
          erreur(champ, t('suivi-introuvable') ||
            'Aucun colis ne porte ce numéro.');
          cacher(resultat);
          return;
        }
        afficher(colis);
      }).catch(function () {
        libererBouton();
        indisponible();
      });
    }

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      chercher((champ && champ.value || '').trim().toUpperCase());
    });

    /* Numéro passé dans l'adresse (QR code d'une étiquette) : on remplit le
       champ et on lance la recherche tout de suite. */
    var demande = new URLSearchParams(location.search).get('colis');
    if (demande) {
      demande = demande.trim().toUpperCase().slice(0, 40);
      // Le QR code ajoute &j=… : on le transmet pour vérification. Sans lui
      // (saisie à la main), la recherche reste publique, comme documenté.
      var jeton = (new URLSearchParams(location.search).get('j') || '').trim().slice(0, 64);
      if (champ) champ.value = demande;
      chercher(demande, jeton || null);
    }
  }

  /* --- Formulaire de contact --------------------------------------------
     Un seul envoi à la fois : le bouton se désactive pendant le traitement,
     pour ne jamais envoyer deux fois. Si le navigateur bloque la fenêtre
     WhatsApp, on le dit au visiteur au lieu de faire semblant d'avoir
     envoyé son message. */
  function contact() {
    var form = document.querySelector('[data-ses-form="contact"]');
    if (!form) return;
    var blocForm = bloc('notSent');
    var blocEnvoye = bloc('sent');
    var message = document.getElementById('ses-contact-erreur');
    var reset = document.querySelector('[data-ses-reset="contact"]');
    var bouton = form.querySelector('button[type="submit"], button:not([type])');
    var avaitFocus = false;

    /* Le service peut arriver dans l'adresse (?service=entreprise, depuis
       « Compte entreprise » ou « Fermer un compte ») : on présélectionne la
       liste. La comparaison se fait sur value, jamais sur le libellé. */
    (function preselectionner() {
      var liste = form.querySelector('select[name="Service"]');
      var voulu = null;
      try { voulu = new URLSearchParams(location.search).get('service'); } catch (e) { voulu = null; }
      if (!liste || !voulu) return;
      for (var i = 0; i < liste.options.length; i++) {
        if (liste.options[i].value === voulu) { liste.selectedIndex = i; return; }
      }
    })();

    /* État d'envoi : bouton désactivé, occupé et légèrement estompé ; libéré
       après succès comme après échec. */
    function occuper() {
      if (!bouton) return;
      avaitFocus = document.activeElement === bouton;
      bouton.disabled = true;
      bouton.setAttribute('aria-busy', 'true');
      bouton.style.opacity = '0.65';
    }

    function liberer() {
      if (!bouton) return;
      bouton.disabled = false;
      bouton.removeAttribute('aria-busy');
      bouton.style.opacity = '';
      if (avaitFocus && document.activeElement === document.body) bouton.focus({ preventScroll: true });
    }

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (message) { message.hidden = true; message.textContent = ''; }
      if (!window.SES_A11Y.valider(form)) return;
      occuper();
      var d = new FormData(form);
      /* La liste envoie un code stable (value) : on réécrit le libellé lisible,
         pour que le message reçu reste exactement le même qu'avant. */
      var liste = form.querySelector('select[name="Service"]');
      if (liste && liste.selectedIndex >= 0 && liste.options[liste.selectedIndex]) {
        d.set('Service', liste.options[liste.selectedIndex].text);
      }
      var lignes = [];
      d.forEach(function (v, k) { if (String(v).trim()) lignes.push(k + ' : ' + v); });
      var corps = 'Demande de devis — Speed Express Shipping\n\n' + lignes.join('\n');

      function confirme() {
        liberer();
        cacher(blocForm);
        montrer(blocEnvoye);
        if (blocEnvoye) blocEnvoye.focus({ preventScroll: true });
        if (blocEnvoye) window.SES_A11Y.defiler(blocEnvoye, 'nearest');
      }

      function echoue(texte) {
        liberer();
        if (message) {
          message.setAttribute('role', 'alert');
          message.setAttribute('aria-atomic', 'true');
          message.hidden = false;
          message.textContent = texte;
        }
      }

      /* Service d'envoi (config.js) : https uniquement, et succès seulement si
         le service répond 2xx — sinon on le dit au lieu de faire semblant
         d'avoir envoyé. Sans endpoint : WhatsApp, puis e-mail. */
      var endpoint = C.formEndpoint || '';
      if (endpoint && !/^https:\/\//i.test(endpoint)) {
        if (window.console) window.console.warn('Speed Express : formEndpoint ignoré, https requise.');
        endpoint = '';
      }
      if (endpoint) {
        fetch(endpoint, {
          method: 'POST',
          headers: { Accept: 'application/json' },
          body: d
        }).then(function (reponse) {
          if (!reponse || !reponse.ok) throw new Error('endpoint');
          confirme();
        }).catch(function () {
          echoue('L’envoi a échoué. Écrivez-nous sur WhatsApp au ' + (C.telephone || '') + '.');
        });
      } else if (C.whatsapp) {
        var fenetre = window.open('https://wa.me/' + C.whatsapp + '?text=' + encodeURIComponent(corps), '_blank', 'noopener');
        if (fenetre) {
          confirme();
        } else {
          echoue('Votre navigateur a bloqué l\'ouverture de WhatsApp. Autorisez les fenêtres popup pour ce site, puis réessayez.');
        }
      } else {
        window.location.href = 'mailto:' + (C.email || '') +
          '?subject=' + encodeURIComponent('Demande de devis') +
          '&body=' + encodeURIComponent(corps);
        confirme();
      }
    });

    if (reset) {
      reset.addEventListener('click', function () {
        form.reset();
        liberer();
        cacher(blocEnvoye);
        montrer(blocForm);
        window.SES_A11Y.effacerErreurs(form);
        if (form.elements[0]) form.elements[0].focus({ preventScroll: true });
        blocForm && window.SES_A11Y.defiler(blocForm, 'nearest');
      });
    }
  }

  function demarrer() { suivi(); contact(); }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', demarrer);
  } else {
    demarrer();
  }
})();
