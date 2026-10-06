/* ==========================================================================
   Speed Express Shipping — protection contre l'affichage dans le cadre d'un autre site
   --------------------------------------------------------------------------
   Sur les pages où l'on se connecte ou agit, la page est cachée dès le départ (voir
   outils/securite.py). Ce script la montre seulement s'il constate qu'elle n'est PAS
   dans un cadre. Dans un cadre, elle reste invisible et on tente d'ouvrir la vraie page
   en pleine fenêtre : un site tiers ne peut donc pas la montrer sous un faux bouton
   pour piéger un clic (« clickjacking »).

   GitHub Pages n'envoie pas l'en-tête qui le ferait proprement (frame-ancestors) ; ce
   remplaçant échoue dans le bon sens : sans ce script, la page reste invisible.
   ========================================================================== */
(function () {
  var style = document.getElementById('ses-anti-cadre');
  if (window.top === window.self) {
    if (style && style.parentNode) style.parentNode.removeChild(style);
    return;
  }
  try { window.top.location = window.self.location; } catch (e) { /* cadre cloisonné : on reste invisible */ }
})();
