/* ==========================================================================
   Speed Express Shipping — réglages du site
   ==========================================================================
   Un seul fichier à modifier pour changer les coordonnées partout.

   whatsapp      Numéro WhatsApp, chiffres uniquement, indicatif compris.
   telephone     Numéro affiché et composé par les liens « Appeler ».
   email         Adresse qui reçoit les demandes de devis.
   formEndpoint  Adresse d'un service de formulaires (ex. Formspree :
                 'https://formspree.io/f/xxxxxxx'). Laissé vide, le
                 formulaire de contact prépare le message dans WhatsApp.
   siteUrl       Adresse publique du site, une fois en ligne. Elle sert au
                 QR code des étiquettes : sans elle, le QR renvoie à
                 l'adresse depuis laquelle l'étiquette a été imprimée.

   supabaseUrl   Espace client (comptes, identifiants SES, colis, factures) :
   supabaseKey   adresse du projet Supabase et sa clé publique
                 (« Publishable key » ou « anon public »), dans Supabase >
                 Project Settings > API Keys. Voir README.md, « Espace
                 client ». Tant qu'ils sont vides, l'espace client fonctionne
                 en démonstration sur votre ordinateur (les comptes restent
                 dans le navigateur) et reste fermé une fois en ligne.

   devise        Devise des factures (USD par défaut).
   ========================================================================== */
window.SES_CONFIG = {
  whatsapp: '18292653727',
  telephone: '+18292653727',
  email: 'speedexpresshipping@gmail.com',
  formEndpoint: '',
  siteUrl: 'https://wilnergraph92.github.io/speed-express-site',
  supabaseUrl: 'https://ltbqqchtyzlyakcsxxis.supabase.co',
  supabaseKey: 'sb_publishable_my2D1qeEVY2P1L0bO1mr4g_YOaF2sZf',
  devise: 'USD',
  // Mentions légales portées par les factures. Elles appartiennent à Speed
  // Express Shipping et à personne d'autre : le site frère Goship Express a
  // les siennes, dans son propre dépôt. Ne jamais recopier les unes chez
  // l'autre.
  factureAdresse: 'C. Fausto Cejas Rodríguez Km12, Las Americas SDO Este',
  factureTelephone: '829 265-3727',
  factureRNC: '1-33-40588-1'
};
