/* ==========================================================================
   Speed Express Shipping — comportements propres à la page d'accueil
   --------------------------------------------------------------------------
   Ce code était écrit dans la page. Il vit dans un fichier à part pour que la
   politique de sécurité du site (script-src 'self') puisse interdire tout script
   écrit dans une page, ce qui ferme la porte à l'injection de code.
   ========================================================================== */
/* Entête : menu repliable, et fond qui se densifie au défilement. */
(function () {
  var entete = document.querySelector('.ses-entete');
  if (entete) {
    var bas = false;
    var onScroll = function () {
      var veutu = (window.scrollY || 0) > 8;
      if (veutu !== bas) { bas = veutu; entete.classList.toggle('ses-entete--bas', bas); }
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  /* Newsletter : le message est confirmé à l'écran, sans service tiers. */
  var news = document.querySelector('[data-ses-form="newsletter"]');
  if (news) {
    news.addEventListener('submit', function (e) {
      e.preventDefault();
      var champ = news.querySelector('input[type="email"]');
      var bouton = news.querySelector('button');
      if (!champ || !champ.value || !champ.checkValidity()) { champ && champ.focus(); return; }
      var avant = bouton ? bouton.textContent : '';
      if (bouton) { bouton.disabled = true; bouton.textContent = 'Merci !'; }
      champ.value = '';
      window.setTimeout(function () { if (bouton) { bouton.disabled = false; bouton.textContent = avant; } }, 2600);
    });
  }
})();
