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

  function sessionOuverte() {
    try {
      for (var i = 0; i < localStorage.length; i++) {
        var cle = localStorage.key(i);

        // Mode démonstration (sur l'ordinateur, sans base configurée)
        if (cle === 'ses-session' && localStorage.getItem(cle)) return true;

        // Mode Supabase : la session est rangée sous « sb-<projet>-auth-token »
        if (!/^sb-.+-auth-token$/.test(cle)) continue;
        var brut = localStorage.getItem(cle);
        if (!brut) continue;
        try {
          var jeton = JSON.parse(brut);
          if (!jeton || !jeton.access_token) continue;
          // Jeton périmé : autant proposer de se connecter.
          if (jeton.expires_at && jeton.expires_at * 1000 < Date.now()) continue;
          return true;
        } catch (e) { /* valeur illisible : on l'ignore */ }
      }
    } catch (e) { /* stockage bloqué (navigation privée) : on ne change rien */ }
    return false;
  }

  function adapter() {
    if (!sessionOuverte()) return;
    var bouton = document.querySelector('.ses-entete .ses-actions a[href="creer-un-compte.html"]');
    if (!bouton) return;
    bouton.href = 'espace-client.html';
    bouton.textContent = 'Mon espace';   // traduit comme le reste de la page
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', adapter);
  else adapter();
})();
