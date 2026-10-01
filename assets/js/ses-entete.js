/* ==========================================================================
   Speed Express Shipping — le bouton de l'entête suit le visiteur
   --------------------------------------------------------------------------
   « Créer un compte » pour qui n'en a pas ; « Mon espace » pour qui est déjà
   connecté. Le bouton est le même sur les 28 pages : c'est ici qu'il change.

   Volontairement sans appel réseau et sans charger la bibliothèque Supabase :
   ce script tourne sur toutes les pages du site, y compris celles qui n'ont
   rien à voir avec l'espace client. Il se contente de regarder si une session
   est rangée dans le navigateur, et laisse le serveur décider du reste — un
   jeton périmé ou trafiqué ne donne accès à rien, il ferait seulement
   apparaître un bouton qui renvoie vers la page de connexion.
   ========================================================================== */
(function () {
  'use strict';

  /* Le nom du projet Supabase, tiré de son adresse :
     https://ltbqqchtyzlyakcsxxis.supabase.co → « ltbqqchtyzlyakcsxxis ».

     Il n'est pas décoratif. Ce site et Goship Express sont tous deux publiés
     sur wilnergraph92.github.io : même origine, donc même localStorage. Une
     session ouverte sur l'un est visible depuis l'autre. Sans ce filtre, un
     visiteur connecté chez Goship verrait ici « Mon espace » et se
     retrouverait, en cliquant, devant la page de connexion de Speed Express.
     On ne reconnaît donc que le jeton de NOTRE projet. */
  function projetSupabase() {
    var url = (window.SES_CONFIG || {}).supabaseUrl || '';
    var m = url.match(/^https?:\/\/([^.]+)\./);
    return m ? m[1] : null;
  }

  function sessionOuverte() {
    var projet = projetSupabase();
    var attendue = projet ? 'sb-' + projet + '-auth-token' : null;
    try {
      // Mode démonstration (sur l'ordinateur, sans base configurée)
      if (localStorage.getItem('ses-session')) return true;
      if (!attendue) return false;

      var brut = localStorage.getItem(attendue);
      if (!brut) return false;
      var jeton = JSON.parse(brut);
      if (!jeton || !jeton.access_token) return false;
      // Jeton périmé : autant proposer de se connecter.
      if (jeton.expires_at && jeton.expires_at * 1000 < Date.now()) return false;
      return true;
    } catch (e) {
      // Stockage bloqué (navigation privée) ou valeur illisible : on ne
      // change rien, l'en-tête garde son bouton « Créer un compte ».
      return false;
    }
  }

  function adapter() {
    if (!sessionOuverte()) return;
    var bouton = document.querySelector('.ses-entete .ses-actions a[href="creer-un-compte.html"]');
    if (!bouton) return;
    bouton.href = 'espace-client.html';
    bouton.textContent = 'Mon espace';   // traduit comme le reste de la page
  }

  /* Navigation mobile non modale : Tab suit l'ordre du document ; Escape
     ferme le panneau et rend le focus au bouton qui l'a ouvert. */
  function navigation() {
    var entete = document.querySelector('.ses-entete');
    var bouton = entete && entete.querySelector('.ses-burger');
    if (!bouton) return;
    function libelle() {
      var texte = entete.classList.contains('ses-ouvert') ? 'Fermer le menu' : 'Ouvrir le menu';
      var i = { en: 0, es: 1, ht: 2 }[document.documentElement.lang];
      var traduit = (window.SES_DICT || {})[texte];
      bouton.setAttribute('aria-label', i !== undefined && traduit ? traduit[i] : texte);
    }
    function fermer(retour) {
      entete.classList.remove('ses-ouvert');
      bouton.setAttribute('aria-expanded', 'false');
      libelle();
      if (retour) bouton.focus();
    }
    bouton.addEventListener('click', function () {
      var ouvert = entete.classList.toggle('ses-ouvert');
      bouton.setAttribute('aria-expanded', ouvert ? 'true' : 'false');
      libelle();
    });
    entete.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Escape' || !entete.classList.contains('ses-ouvert')) return;
      ev.preventDefault();
      ev.stopPropagation();
      fermer(true);
    });
    Array.prototype.forEach.call(entete.querySelectorAll('nav a'), function (lien) {
      lien.addEventListener('click', function () { fermer(false); });
    });
    document.addEventListener('click', function (ev) {
      if (entete.classList.contains('ses-ouvert') && !entete.contains(ev.target)) fermer(false);
    });
    window.addEventListener('ses-lang', libelle);
    var large = window.matchMedia('(min-width:1051px)');
    function redimensionner(ev) { if (ev.matches) fermer(false); }
    if (large.addEventListener) large.addEventListener('change', redimensionner);
    else large.addListener(redimensionner);
  }
  function demarrer() { adapter(); navigation(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', demarrer);
  else demarrer();
})();
