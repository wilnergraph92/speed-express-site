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

     Sans base configurée, ou si le numéro est inconnu, la page garde le
     parcours d'exemple de la maquette et le dit clairement.               */
  function suivi() {
    var form = document.querySelector('[data-ses-form="suivi"]');
    if (!form) return;
    var champ = form.querySelector('[data-ses-input="suivi"]') || form.querySelector('input');
    var resultat = bloc('trackResult') || bloc('result');
    var API = window.SES_API;

    function afficher(ref, colis) {
      var cible = resultat && resultat.querySelector('[data-ses-ref]');
      if (cible) cible.textContent = colis ? colis.numero : ref;

      var zoneStatut = resultat && resultat.querySelector('[data-ses-statut]');
      var zoneMaj = resultat && resultat.querySelector('[data-ses-maj]');
      if (colis && zoneStatut) {
        var dernier = (colis.historique || [])[(colis.historique || []).length - 1];
        zoneStatut.textContent = (t('statut-' + colis.statut) || colis.statut) +
          (dernier && dernier.lieu ? ' · ' + dernier.lieu : '');
      }
      if (colis && zoneMaj) {
        zoneMaj.textContent = t('suivi-maj', { date: quandDate(colis.maj_le) });
      }
      montrer(resultat);
      if (resultat) resultat.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function chercher(ref) {
      if (!ref) {
        erreur(champ, 'Entrez d’abord votre numéro de colis.');
        return;
      }
      if (!API || API.mode === 'off' || !API.suivre) {
        afficher(ref, null);       // pas de base : le parcours d'exemple reste
        return;
      }
      var bouton = form.querySelector('button[type="submit"], button:not([type])');
      var avant = bouton ? bouton.textContent : '';
      if (bouton) { bouton.disabled = true; bouton.textContent = t('suivi-recherche') || avant; }

      API.suivre(ref).then(function (colis) {
        if (bouton) { bouton.disabled = false; bouton.textContent = avant; }
        if (!colis || !colis.numero) {
          erreur(champ, t('suivi-introuvable') ||
            'Aucun colis ne porte ce numéro.');
          cacher(resultat);
          return;
        }
        afficher(ref, colis);
      }).catch(function () {
        if (bouton) { bouton.disabled = false; bouton.textContent = avant; }
        afficher(ref, null);       // réseau coupé : on garde le parcours d'exemple
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
      if (champ) champ.value = demande;
      chercher(demande);
    }
  }

  /* --- Formulaire de contact -------------------------------------------- */
  function contact() {
    var form = document.querySelector('[data-ses-form="contact"]');
    if (!form) return;
    var blocForm = bloc('notSent');
    var blocEnvoye = bloc('sent');
    var reset = document.querySelector('[data-ses-reset="contact"]');

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!form.reportValidity()) return;
      var d = new FormData(form);
      var lignes = [];
      d.forEach(function (v, k) { if (String(v).trim()) lignes.push(k + ' : ' + v); });
      var corps = 'Demande de devis — Speed Express Shipping\n\n' + lignes.join('\n');

      function confirme() {
        cacher(blocForm);
        montrer(blocEnvoye);
        if (blocEnvoye) blocEnvoye.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }

      if (C.formEndpoint) {
        fetch(C.formEndpoint, {
          method: 'POST',
          headers: { Accept: 'application/json' },
          body: d
        }).then(confirme).catch(function () {
          erreur(form.querySelector('textarea'),
            'L’envoi a échoué. Écrivez-nous sur WhatsApp au ' + (C.telephone || '') + '.');
        });
      } else if (C.whatsapp) {
        window.open('https://wa.me/' + C.whatsapp + '?text=' + encodeURIComponent(corps), '_blank', 'noopener');
        confirme();
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
