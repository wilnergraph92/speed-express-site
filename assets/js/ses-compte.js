/* ==========================================================================
   Speed Express Shipping — inscription, connexion, mot de passe
   --------------------------------------------------------------------------
   Un seul fichier pour les trois pages d'entrée : chaque fonction ne
   s'active que si son formulaire est présent dans la page.
   ========================================================================== */
(function () {
  'use strict';

  var API = window.SES_API;
  var UI = window.SES_UI;
  var CFG = window.SES_CONFIG || {};
  if (!API || !UI) return;

  function $(sel) { return document.querySelector(sel); }
  function valeur(form, nom) {
    var el = form.elements[nom];
    return el ? String(el.value || '').trim() : '';
  }

  /* --- Afficher / masquer un mot de passe -------------------------------- */
  function boutonsMotDePasse() {
    Array.prototype.forEach.call(document.querySelectorAll('.ses-voir-mdp'), function (b) {
      b.addEventListener('click', function () {
        var champ = b.parentNode.querySelector('input');
        if (!champ) return;
        var montre = champ.type === 'password';
        champ.type = montre ? 'text' : 'password';
        b.setAttribute('aria-pressed', montre ? 'true' : 'false');
        b.textContent = UI.t(montre ? 'masquer' : 'afficher') || (montre ? 'Masquer' : 'Afficher');
      });
    });
  }

  /* --- Bandeau de mode --------------------------------------------------- */
  function bandeauMode() {
    var zone = $('#ses-mode');
    if (!zone || API.mode === 'supabase') return;
    var texte = UI.t(API.mode === 'demo' ? 'mode-demo' : 'mode-off');
    if (!texte) return;
    UI.annonce(zone, texte, API.mode === 'demo' ? 'info' : 'erreur');
    zone.style.marginBottom = '22px';
  }

  /* --- Contrôles de saisie communs --------------------------------------- */
  function champVide(form, noms) {
    for (var i = 0; i < noms.length; i++) {
      var el = form.elements[noms[i]];
      if (el && !String(el.value || '').trim()) {
        UI.erreurChamp(el, UI.t('champ-requis'));
        return true;
      }
    }
    return false;
  }

  function emailValide(form) {
    var el = form.elements.email;
    if (el && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(String(el.value || '').trim())) {
      UI.erreurChamp(el, UI.t('email-invalide'));
      return false;
    }
    return true;
  }

  /* --- Page d'inscription ------------------------------------------------ */
  function inscription() {
    var form = $('#ses-inscription');
    if (!form) return;
    var message = $('#ses-message');

    // « Autre pays » : le menu déroulant laisse la place à un champ libre.
    var pays = form.elements.pays;
    if (pays) {
      pays.addEventListener('change', function () {
        if (pays.value !== 'autre') return;
        var libre = document.createElement('input');
        libre.type = 'text';
        libre.name = 'pays';
        libre.required = true;
        libre.maxLength = 60;
        libre.placeholder = UI.t('pays-libre') || 'Entrez votre pays';
        libre.autocomplete = 'country-name';
        pays.parentNode.replaceChild(libre, pays);
        libre.focus();
      });
    }

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      UI.effacerErreurs(form);
      UI.annonce(message, '');

      if (champVide(form, ['nom_complet', 'pays', 'adresse', 'region', 'ville', 'telephone', 'email', 'motDePasse'])) return;
      if (!emailValide(form)) return;
      if (valeur(form, 'motDePasse').length < API.MDP_MINIMUM) {
        UI.erreurChamp(form.elements.motDePasse, UI.t('mdp-court'));
        return;
      }

      var bouton = form.querySelector('button[type="submit"]');
      var rendre = UI.occuper(bouton, UI.t('attente'));

      API.inscrire({
        nom_complet: valeur(form, 'nom_complet'),
        pays: valeur(form, 'pays'),
        adresse: valeur(form, 'adresse'),
        region: valeur(form, 'region'),
        ville: valeur(form, 'ville'),
        telephone: valeur(form, 'telephone'),
        email: valeur(form, 'email'),
        motDePasse: valeur(form, 'motDePasse')
      }).then(function (r) {
        rendre();
        accueillir(r, valeur(form, 'email'));
      }).catch(function (err) {
        rendre();
        UI.annonce(message, UI.messageErreur(err), 'erreur');
        message.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      });
    });
  }

  /* Le compte est créé : on montre l'identifiant, qui est la seule chose que
     le client doit retenir. */
  function accueillir(r, email) {
    var form = $('#ses-inscription');
    var bienvenue = $('#ses-bienvenue');
    var code = $('#ses-code-client');
    if (!bienvenue) return;
    form.hidden = true;
    bienvenue.hidden = false;

    if (r.profil && r.profil.code) {
      code.textContent = r.profil.code;
    } else {
      code.hidden = true;
    }
    if (r.confirmation) {
      var mot = $('#ses-confirmation');
      mot.hidden = false;
      mot.textContent = UI.t('confirmation', { email: email });
    }
    if (window.SES_ANIM) window.SES_ANIM.reveler(bienvenue);
    bienvenue.scrollIntoView({ behavior: 'smooth', block: 'center' });

    var copier = $('#ses-copier-code');
    if (copier && code && code.textContent) {
      copier.addEventListener('click', function () {
        copie(code.textContent, copier);
      });
    }
  }

  function copie(texte, bouton) {
    var fait = function () {
      var avant = bouton.textContent;
      bouton.textContent = UI.t('copie') || 'Copié';
      setTimeout(function () { bouton.textContent = avant; }, 1800);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(texte).then(fait, function () {});
      return;
    }
    var zone = document.createElement('textarea');
    zone.value = texte;
    zone.style.cssText = 'position:fixed;opacity:0';
    document.body.appendChild(zone);
    zone.select();
    try { document.execCommand('copy'); fait(); } catch (e) {}
    zone.remove();
  }

  /* --- Page de connexion ------------------------------------------------- */
  function connexion() {
    var form = $('#ses-connexion');
    if (!form) return;
    var message = $('#ses-message');

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      UI.effacerErreurs(form);
      UI.annonce(message, '');
      if (champVide(form, ['email', 'motDePasse'])) return;
      if (!emailValide(form)) return;

      var bouton = form.querySelector('button[type="submit"]');
      var rendre = UI.occuper(bouton, UI.t('attente'));

      API.connecter(valeur(form, 'email'), valeur(form, 'motDePasse'))
        .then(function () { location.href = suite(); })
        .catch(function (err) {
          rendre();
          UI.annonce(message, UI.messageErreur(err), 'erreur');
        });
    });

    var oubli = $('#ses-oubli');
    if (oubli) {
      oubli.addEventListener('click', function () {
        UI.effacerErreurs(form);
        var email = valeur(form, 'email');
        if (!email) {
          UI.annonce(message, UI.t('oubli-demande'), 'info');
          form.elements.email.focus();
          return;
        }
        var rendre = UI.occuper(oubli, UI.t('attente'));
        API.envoyerLienMotDePasse(email).then(function () {
          rendre();
          UI.annonce(message, UI.t('oubli-envoye', { email: email }), 'succes');
        }).catch(function (err) {
          rendre();
          UI.annonce(message, UI.messageErreur(err), 'erreur');
        });
      });
    }
  }

  /* Page demandée avant la connexion, si elle fait partie du site. */
  function suite() {
    var p = new URLSearchParams(location.search).get('suite') || '';
    return /^[a-z0-9-]+\.html$/.test(p) ? p : 'espace-client.html';
  }

  /* --- Page « nouveau mot de passe » ------------------------------------- */
  function nouveauMotDePasse() {
    var form = $('#ses-nouveau-mdp');
    if (!form) return;
    var message = $('#ses-message');
    var retour = $('#ses-retour');

    API.attendreRecuperation().then(function (ok) {
      if (!ok) {
        UI.annonce(message, UI.t('sans-lien'), 'erreur');
        retour.hidden = false;
        return;
      }
      form.hidden = false;
    });

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      UI.effacerErreurs(form);
      UI.annonce(message, '');
      if (champVide(form, ['motDePasse', 'confirmation'])) return;
      var mdp = valeur(form, 'motDePasse');
      if (mdp.length < API.MDP_MINIMUM) {
        UI.erreurChamp(form.elements.motDePasse, UI.t('mdp-court'));
        return;
      }
      if (mdp !== valeur(form, 'confirmation')) {
        UI.erreurChamp(form.elements.confirmation, UI.t('differents'));
        return;
      }
      var bouton = form.querySelector('button[type="submit"]');
      var rendre = UI.occuper(bouton, UI.t('attente'));
      API.changerMotDePasse(mdp).then(function () {
        rendre();
        form.hidden = true;
        retour.hidden = false;
        UI.annonce(message, UI.t('fait'), 'succes');
      }).catch(function (err) {
        rendre();
        UI.annonce(message, UI.messageErreur(err), 'erreur');
      });
    });
  }

  /* --- Déjà connecté : inutile de redemander ----------------------------- */
  function siDejaConnecte() {
    if (!$('#ses-connexion') && !$('#ses-inscription')) return;
    API.profil().then(function (p) {
      if (p) location.replace('espace-client.html');
    }).catch(function () {});
  }

  function demarrer() {
    boutonsMotDePasse();
    bandeauMode();
    inscription();
    connexion();
    nouveauMotDePasse();
    siDejaConnecte();
    var wa = document.getElementById('ses-whatsapp');
    if (wa && CFG.whatsapp) wa.href = 'https://wa.me/' + CFG.whatsapp;
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', demarrer);
  else demarrer();
})();
