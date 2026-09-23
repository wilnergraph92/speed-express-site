/* ==========================================================================
   Speed Express Shipping — espace client
   --------------------------------------------------------------------------
   Ce que le client voit de son compte : ses colis, leur parcours, l'historique
   daté de chaque étape, ses factures payées et impayées, ses informations.

   Rien d'autre : la page ne demande jamais les données d'un autre compte, et
   le serveur les refuserait de toute façon (voir outils/supabase.sql).
   ========================================================================== */
(function () {
  'use strict';

  var API = window.SES_API;
  var UI = window.SES_UI;
  var CFG = window.SES_CONFIG || {};
  if (!API || !UI || !document.getElementById('ses-liste-colis')) return;

  var moi = null;
  var colis = [];
  var factures = [];
  var filtreColis = '';
  var filtreFactures = '';
  var recherche = '';

  function $(s) { return document.querySelector(s); }
  function e(v) { return UI.echapper(v); }

  /* --- Entête du compte -------------------------------------------------- */
  function poserIdentite() {
    $('#ses-bonjour').textContent = UI.t('bonjour', { nom: moi.nom_complet || moi.email });
    $('#ses-identite').textContent = UI.t('identite', {
      role: UI.t('role-' + moi.role) || moi.role,
      date: UI.date(moi.cree_le)
    });
    if (moi.code) {
      $('#ses-bloc-code').hidden = false;
      $('#ses-code-client').textContent = moi.code;
    }
    if (API.droitsDe(moi).length) $('#ses-lien-admin').hidden = false;

    var copier = $('#ses-copier-code');
    if (copier) copier.addEventListener('click', function () {
      copie(moi.code, copier.querySelector('span:last-child'));
    });

    var wa = $('#ses-whatsapp');
    if (wa && CFG.whatsapp) {
      wa.href = 'https://wa.me/' + CFG.whatsapp + '?text=' +
        encodeURIComponent('Bonjour, je suis ' + (moi.nom_complet || '') + ' (' + (moi.code || '') + ').');
    }
  }

  function copie(texte, cible) {
    var avant = cible ? cible.textContent : '';
    var fait = function () {
      if (!cible) return;
      cible.textContent = UI.t('copie');
      setTimeout(function () { cible.textContent = avant; }, 1800);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(texte).then(fait, function () {});
    }
  }

  /* --- Chiffres ---------------------------------------------------------- */
  function chiffres() {
    var enCours = colis.filter(function (c) { return c.statut !== 'livre'; }).length;
    var dispo = colis.filter(function (c) { return c.statut === 'disponible'; }).length;
    var livres = colis.filter(function (c) { return c.statut === 'livre'; }).length;
    var impayees = factures.filter(function (f) { return f.statut !== 'payee'; });
    var du = impayees.reduce(function (a, f) { return a + Number(f.montant || 0); }, 0);

    $('#ses-chiffres').innerHTML = [
      carte(enCours, UI.t('chiffre-en-cours')),
      carte(dispo, UI.t('chiffre-disponibles'), dispo ? '#0b7a19' : null),
      carte(livres, UI.t('chiffre-livres')),
      carte(impayees.length, UI.t('chiffre-impayees'),
        impayees.length ? '#b60d14' : null, impayees.length ? UI.montant(du) : null)
    ].join('');
  }

  function carte(valeur, libelle, couleur, detail) {
    return '<div class="ses-chiffre ses-carte ses-lueur" data-ses-reveal="0">' +
      '<b' + (couleur ? ' style="color:' + couleur + '"' : '') + '>' + valeur + '</b>' +
      '<span>' + e(libelle) + (detail ? ' · ' + e(detail) : '') + '</span></div>';
  }

  /* --- Onglets ----------------------------------------------------------- */
  function onglets() {
    var boutons = document.querySelectorAll('[role="tab"]');
    Array.prototype.forEach.call(boutons, function (b) {
      b.addEventListener('click', function () {
        Array.prototype.forEach.call(boutons, function (x) {
          var actif = x === b;
          x.setAttribute('aria-selected', actif ? 'true' : 'false');
          document.getElementById(x.getAttribute('aria-controls')).hidden = !actif;
        });
      });
    });
  }

  /* --- Filtres ----------------------------------------------------------- */
  function filtres() {
    var zone = $('#ses-filtres-colis');
    zone.innerHTML = [''].concat(API.STATUTS).map(function (s) {
      return '<button type="button" class="ses-filtre" data-statut="' + s + '" aria-pressed="' +
        (s === filtreColis ? 'true' : 'false') + '">' +
        e(s ? UI.nomStatut(s) : UI.t('tous')) + '</button>';
    }).join('');
    // « filtres » est rappelé à chaque clic et à chaque changement de langue :
    // sans ce garde-fou, un écouteur de plus s'empilerait sur la même zone.
    if (!zone.dataset.branche) {
      zone.dataset.branche = '1';
      zone.addEventListener('click', function (ev) {
        var b = ev.target.closest('[data-statut]');
        if (!b) return;
        filtreColis = b.getAttribute('data-statut');
        filtres();
        listeColis();
      });
    }

    var zf = $('#ses-filtres-factures');
    zf.innerHTML = [['', UI.t('tous')], ['impayee', UI.t('facture-impayee')], ['payee', UI.t('facture-payee')]]
      .map(function (p) {
        return '<button type="button" class="ses-filtre" data-facture="' + p[0] + '" aria-pressed="' +
          (p[0] === filtreFactures ? 'true' : 'false') + '">' + e(p[1]) + '</button>';
      }).join('');
    if (!zf.dataset.branche) {
      zf.dataset.branche = '1';
      zf.addEventListener('click', function (ev) {
        var b = ev.target.closest('[data-facture]');
        if (!b) return;
        filtreFactures = b.getAttribute('data-facture');
        filtres();
        listeFactures();
      });
    }

    var champ = $('#ses-chercher-colis');
    if (!champ.dataset.branche) {
      champ.dataset.branche = '1';
      var minuteur;
      champ.addEventListener('input', function () {
        clearTimeout(minuteur);
        minuteur = setTimeout(function () {
          recherche = champ.value.trim().toLowerCase();
          listeColis();
        }, 180);
      });
    }
  }

  /* --- Liste des colis --------------------------------------------------- */
  function listeColis() {
    var lignes = colis.filter(function (c) {
      if (filtreColis && c.statut !== filtreColis) return false;
      if (!recherche) return true;
      return [c.numero, c.description, c.expediteur, c.ville_destination, c.lieu]
        .some(function (v) { return v && String(v).toLowerCase().indexOf(recherche) >= 0; });
    });

    var zone = $('#ses-liste-colis');
    if (!lignes.length) {
      zone.innerHTML = '<div class="ses-bloc">' +
        UI.vide(UI.t(colis.length ? 'colis-vide-filtre' : 'colis-vide'), '▢') + '</div>';
      return;
    }
    zone.innerHTML = lignes.map(fiche).join('');
    if (window.SES_ANIM) window.SES_ANIM.reveler(zone);
  }

  function fiche(c, i) {
    var etape = UI.etapeDe(c.statut, c.historique);
    var derniere = (c.historique || [])[c.historique.length - 1];

    return '<article class="ses-carte ses-bloc" data-ses-reveal="' + (i % 6) + '" style="margin-bottom:14px">' +
      '<div style="display:flex;flex-wrap:wrap;gap:12px 18px;align-items:center;justify-content:space-between">' +
        '<div style="min-width:0">' +
          '<p style="margin:0;font-family:\'IBM Plex Mono\',monospace;font-size:17px;font-weight:600;letter-spacing:.06em">' +
            e(c.numero) + '</p>' +
          '<p style="margin:3px 0 0;font-size:15px;color:#4b5563">' + e(c.description || '—') + '</p>' +
        '</div>' +
        UI.pastille(c.statut) +
      '</div>' +

      '<ol class="ses-etapes" style="margin-top:22px">' +
        [1, 2, 3, 4].map(function (n) {
          return '<li class="' + (n <= etape ? 'ses-faite' : '') + '">' + e(UI.t('etape-' + n)) + '</li>';
        }).join('') +
      '</ol>' +

      (c.statut === 'action' && c.note ?
        '<p style="margin-top:18px;background:rgba(232,18,27,.07);border:1px solid rgba(232,18,27,.25);' +
        'border-radius:11px;padding:13px 15px;font-size:14.5px;color:#b60d14;font-weight:600">' +
        e(c.note) + '</p>' : '') +

      '<dl style="margin:20px 0 0;display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px 20px;font-size:14px">' +
        detail(UI.t('colis-expediteur'), c.expediteur) +
        detail(UI.t('colis-service'), UI.t('service-' + c.service) || c.service) +
        detail(UI.t('colis-poids'), c.poids_lb ? c.poids_lb + ' lb' : '') +
        detail(UI.t('colis-destination'), UI.lieuLivraison(c)) +
        detail(UI.t('colis-livraison'), c.adresse_livraison) +
        detail(UI.t('colis-maj'), UI.date(c.maj_le, true) + (derniere && derniere.lieu ? ' · ' + derniere.lieu : '')) +
      '</dl>' +

      '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini ses-voir-histo" ' +
        'data-colis="' + e(c.id) + '" aria-expanded="false" style="margin-top:18px">' +
        e(UI.t('colis-voir-historique')) + ' (' + (c.historique || []).length + ')</button>' +

      '<div class="ses-histo" data-colis="' + e(c.id) + '" hidden style="margin-top:18px;padding-top:18px;border-top:1px solid var(--line)">' +
        '<p style="margin:0 0 14px;font-size:11.5px;letter-spacing:.1em;color:#6b7280;font-weight:700">' +
          e(UI.t('colis-historique')) + '</p>' +
        '<ul class="ses-historique">' +
          (c.historique || []).slice().reverse().map(function (h, n, tout) {
            return UI.ligneHistorique(h, { dernier: n === tout.length - 1 });
          }).join('') +
        '</ul>' +
      '</div>' +
    '</article>';
  }

  function detail(libelle, valeur) {
    if (!valeur) return '';
    return '<div><dt style="font-size:11px;letter-spacing:.09em;color:#6b7280;font-weight:700">' +
      e(libelle) + '</dt><dd style="margin:3px 0 0;font-weight:600">' + e(valeur) + '</dd></div>';
  }

  /* --- Liste des factures ------------------------------------------------ */
  function listeFactures() {
    var lignes = factures.filter(function (f) {
      return !filtreFactures || f.statut === filtreFactures;
    });
    var zone = $('#ses-liste-factures');
    if (!lignes.length) {
      zone.innerHTML = '<div class="ses-bloc">' +
        UI.vide(UI.t(factures.length ? 'factures-vide-filtre' : 'factures-vide'), '▤') + '</div>';
      return;
    }
    zone.innerHTML = '<table class="ses-tableau"><thead><tr>' +
      ['facture-numero', 'facture-date', 'facture-colis', 'facture-montant', 'facture-statut']
        .map(function (k) { return '<th>' + e(UI.t(k)) + '</th>'; }).join('') +
      '<th></th></tr></thead><tbody>' +
      lignes.map(function (f) {
        var paye = f.statut === 'payee';
        return '<tr class="ses-ligne">' +
          '<td data-libelle="' + e(UI.t('facture-numero')) + '" class="ses-mono">' + e(f.numero) + '</td>' +
          '<td data-libelle="' + e(UI.t('facture-date')) + '">' + e(UI.date(f.cree_le)) + '</td>' +
          '<td data-libelle="' + e(UI.t('facture-colis')) + '" class="ses-mono">' + e(f.numero_colis || '—') + '</td>' +
          '<td data-libelle="' + e(UI.t('facture-montant')) + '" class="ses-mono">' + e(UI.montant(f.montant, f.devise)) + '</td>' +
          '<td data-libelle="' + e(UI.t('facture-statut')) + '">' +
            '<span style="display:inline-flex;align-items:center;gap:7px;border-radius:999px;padding:5px 13px;' +
            'font-weight:700;font-size:13px;' +
            (paye ? 'background:rgba(19,192,44,.12);color:#0b7a19' : 'background:rgba(232,18,27,.1);color:#b60d14') + '">' +
            e(UI.t(paye ? 'facture-payee' : 'facture-impayee')) + '</span></td>' +
          '<td><div class="ses-actions-ligne">' +
            '<button type="button" class="ses-bouton ses-bouton-second ses-bouton-mini ses-imprimer" ' +
            'data-facture="' + e(f.id) + '">' + e(UI.t('imprimer')) + '</button></div></td>' +
        '</tr>';
      }).join('') + '</tbody></table>';
  }

  /* --- Formulaires du compte --------------------------------------------- */
  function formulaireProfil() {
    var form = $('#ses-profil');
    var message = $('#ses-message-profil');
    ['nom_complet', 'pays', 'region', 'ville', 'telephone', 'adresse', 'email'].forEach(function (k) {
      if (form.elements[k]) form.elements[k].value = moi[k] || '';
    });

    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      UI.effacerErreurs(form);
      var rendre = UI.occuper(form.querySelector('button[type="submit"]'), UI.t('attente'));
      API.modifierProfil({
        nom_complet: form.elements.nom_complet.value,
        pays: form.elements.pays.value,
        region: form.elements.region.value,
        ville: form.elements.ville.value,
        telephone: form.elements.telephone.value,
        adresse: form.elements.adresse.value
      }).then(function (p) {
        rendre();
        moi = p || moi;
        poserIdentite();
        UI.annonce(message, UI.t('profil-enregistre'), 'succes');
      }).catch(function (err) {
        rendre();
        UI.annonce(message, UI.messageErreur(err), 'erreur');
      });
    });
  }

  function formulaireMotDePasse() {
    var form = $('#ses-mdp');
    var message = $('#ses-message-mdp');
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      UI.effacerErreurs(form);
      var mdp = String(form.elements.motDePasse.value || '');
      if (mdp.length < API.MDP_MINIMUM) {
        UI.erreurChamp(form.elements.motDePasse, UI.t('mdp-court'));
        return;
      }
      var rendre = UI.occuper(form.querySelector('button[type="submit"]'), UI.t('attente'));
      API.changerMotDePasse(mdp).then(function () {
        rendre();
        form.reset();
        UI.annonce(message, UI.t('mdp-enregistre'), 'succes');
      }).catch(function (err) {
        rendre();
        UI.annonce(message, UI.messageErreur(err), 'erreur');
      });
    });
  }

  /* --- Clics groupés ----------------------------------------------------- */
  function clics() {
    document.addEventListener('click', function (ev) {
      var histo = ev.target.closest('.ses-voir-histo');
      if (histo) {
        var id = histo.getAttribute('data-colis');
        var bloc = document.querySelector('.ses-histo[data-colis="' + id + '"]');
        var ouvert = !bloc.hidden;
        bloc.hidden = ouvert;
        histo.setAttribute('aria-expanded', ouvert ? 'false' : 'true');
        var n = (colis.filter(function (c) { return c.id === id; })[0] || {}).historique || [];
        histo.textContent = UI.t(ouvert ? 'colis-voir-historique' : 'colis-cacher-historique') + ' (' + n.length + ')';
        return;
      }

      var imprimer = ev.target.closest('.ses-imprimer');
      if (imprimer) {
        var f = factures.filter(function (x) { return x.id === imprimer.getAttribute('data-facture'); })[0];
        // Les colis du client sont déjà chargés : la facture y retrouve le
        // poids, même si sa ligne ne le porte pas (factures anciennes).
        if (f) UI.imprimer(UI.facture(f, moi, colis), 'facture');
        return;
      }

      if (ev.target.closest('#ses-deconnexion')) {
        API.deconnecter().then(function () { location.replace('connexion.html'); });
      }
    });

    Array.prototype.forEach.call(document.querySelectorAll('.ses-voir-mdp'), function (b) {
      b.addEventListener('click', function () {
        var champ = b.parentNode.querySelector('input');
        var montre = champ.type === 'password';
        champ.type = montre ? 'text' : 'password';
        b.setAttribute('aria-pressed', montre ? 'true' : 'false');
        b.textContent = UI.t(montre ? 'masquer' : 'afficher');
      });
    });
  }

  /* --- Chargement des données -------------------------------------------- */
  function charger(silencieux) {
    return Promise.all([API.mesColis(), API.mesFactures()]).then(function (r) {
      colis = r[0] || [];
      factures = r[1] || [];
      chiffres();
      listeColis();
      listeFactures();
      if (!silencieux) UI.annonce($('#ses-message'), '');
    }).catch(function (err) {
      UI.annonce($('#ses-message'), UI.messageErreur(err), 'erreur');
    });
  }

  function demarrer() {
    API.exigerProfil().then(function (p) {
      if (!p) return;
      moi = p;
      poserIdentite();
      onglets();
      filtres();
      clics();
      formulaireProfil();
      formulaireMotDePasse();
      UI.surLangue(function () {
        poserIdentite();
        filtres();
        chiffres();
        listeColis();
        listeFactures();
      });
      return charger();
    }).then(function () {
      if (!moi) return;
      // Ce que l'administration change se voit ici sans recharger la page.
      API.surveiller(function () { charger(true); });
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', demarrer);
  else demarrer();
})();
