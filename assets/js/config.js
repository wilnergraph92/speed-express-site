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
  siteUrl: '',
  supabaseUrl: '',
  supabaseKey: '',
  devise: 'USD'
};
