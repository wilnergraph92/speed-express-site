/* ==========================================================================
   Speed Express Shipping — comportements du site
   ==========================================================================
   Deux choses seulement : le suivi de colis et le formulaire de contact.
   Tout le reste du site est du HTML et du CSS, sans JavaScript.
   ========================================================================== */
(function () {
  'use strict';

  var C = window.SES_CONFIG || {};

  function bloc(nom) { return document.querySelector('[data-ses-if="' + nom + '"]'); }
  function montrer(el) { if (el) el.hidden = false; }
  function cacher(el) { if (el) el.hidden = true; }

  /* Affiche un message d'erreur sous un champ, et l'efface à la saisie. */
  function erreur(champ, texte) {
    if (!champ) return;
    var msg = champ.parentNode.querySelector('.ses-erreur');
    if (!msg) {
      msg = document.createElement('p');
      msg.className = 'ses-erreur';
      msg.style.cssText = 'margin:8px 0 0;font-size:14px;color:#e8121b';
      champ.parentNode.appendChild(msg);
    }
    msg.textContent = texte;
    champ.setAttribute('aria-invalid', 'true');
    champ.addEventListener('input', function eff() {
      msg.remove();
      champ.removeAttribute('aria-invalid');
      champ.removeEventListener('input', eff);
    });
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
      if (resultat) resultat.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    /* Pas de base, ou réseau coupé : on l'annonce, on ne montre rien. */
    function indisponible() {
      erreur(champ, t('suivi-indisponible') ||
        'Le suivi est momentanément indisponible. Réessayez dans un instant, ou écrivez-nous sur WhatsApp.');
      cacher(resultat);
    }

    function chercher(ref, jeton) {
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
      var avant = bouton ? bouton.textContent : '';
      if (bouton) { bouton.disabled = true; bouton.textContent = t('suivi-recherche') || avant; }

      API.suivre(ref, jeton || null).then(function (colis) {
        if (bouton) { bouton.disabled = false; bouton.textContent = avant; }
        if (!colis || !colis.numero) {
          erreur(champ, t('suivi-introuvable') ||
            'Aucun colis ne porte ce numéro.');
          cacher(resultat);
          return;
        }
        afficher(colis);
      }).catch(function () {
        if (bouton) { bouton.disabled = false; bouton.textContent = avant; }
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
    var reset = document.querySelector('[data-ses-reset="contact"]');
    var bouton = form.querySelector('button[type="submit"], button:not([type])');

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
      bouton.disabled = true;
      bouton.setAttribute('aria-busy', 'true');
      bouton.style.opacity = '0.65';
    }

    function liberer() {
      if (!bouton) return;
      bouton.disabled = false;
      bouton.removeAttribute('aria-busy');
      bouton.style.opacity = '';
    }

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!form.reportValidity()) return;
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
        if (blocEnvoye) blocEnvoye.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }

      function echoue(texte) {
        liberer();
        erreur(form.querySelector('textarea'), texte);
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
        blocForm && blocForm.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
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
