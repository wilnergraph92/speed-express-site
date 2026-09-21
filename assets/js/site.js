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

  /* --- Suivi de colis ---------------------------------------------------
     Il n'y a pas encore de base de données : le suivi affiche la référence
     saisie et les étapes de démonstration prévues dans la maquette. Le
     bouton WhatsApp reste le moyen d'avoir le statut réel.                */
  function suivi() {
    var form = document.querySelector('[data-ses-form="suivi"]');
    if (!form) return;
    var champ = form.querySelector('[data-ses-input="suivi"]') || form.querySelector('input');
    var resultat = bloc('trackResult') || bloc('result');

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var ref = (champ && champ.value || '').trim().toUpperCase();
      if (!ref) {
        erreur(champ, 'Entrez d’abord votre numéro de colis.');
        return;
      }
      var cible = resultat && resultat.querySelector('[data-ses-ref]');
      if (cible) cible.textContent = ref;
      montrer(resultat);
      if (resultat) resultat.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
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
