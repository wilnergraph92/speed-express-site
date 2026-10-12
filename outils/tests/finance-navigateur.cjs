// « Le navigateur ne calcule jamais » (phase 6) : ni total, ni taxe, ni remise, ni solde, ni paiement, ni remboursement, ni conversion.
//
// (1) Les écrans du MOTEUR FINANCIER (portail client, centre de commande, dernier kilomètre) affichent les montants que la base rend :
//     aucune opération arithmétique sur un montant, aucun arrondi, aucune somme. (2) L'ancienne facturation, encore en service tant
//     que la bascule n'est pas faite, calcule à quelques endroits connus (affichage d'une facture héritée, aperçu du prix d'un colis,
//     regroupement d'anciennes factures) : la liste est FIGÉE ici — un nouveau calcul ailleurs fait échouer ce test, et ces calculs
//     disparaissent avec la bascule (docs/architecture/FINANCE.md §8).
const fs = require('node:fs'), assert = require('node:assert/strict');
let n = 0; const ok = (c, m) => { assert.ok(c, m); n++; };

const ARGENT = '(?:amount|total|balance|paid|subtotal|tax|discount|credited|refunded|fee|price|montant|solde|frais|taxe|remise|prix|tarif)';
// une opération arithmétique (- * /) ou un arrondi appliqués à un nom de montant ; « + » est exclu : c'est aussi la concaténation de texte
const OPERATION = new RegExp('\\b\\w*' + ARGENT + '\\w*\\s*\\)?\\s*[-*/]\\s*[\\w(]|[-*/]\\s*\\(?\\s*\\w*' + ARGENT + '\\w*\\b', 'i');
const ARRONDI = /Math\.round\(|toFixed\(|\.reduce\(/;
const MOT_ARGENT = new RegExp(ARGENT, 'i');
// un calcul : une opération sur un montant, ou un arrondi / une somme sur une ligne qui parle d'argent (pas l'âge d'une position en minutes)
// le texte entre guillemets (clés de traduction « facture-montant », styles) n'est pas du calcul : on l'efface avant d'analyser
const sansTextes = (l) => l.replace(/'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"/g, "''");
const CALCUL = { test: (brut) => { const l = sansTextes(brut); return OPERATION.test(l) || (ARRONDI.test(l) && MOT_ARGENT.test(l)); } };
const sansCommentaires = (src) => src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');

// 1. les écrans du noyau
for (const f of ['assets/js/ses-portail-finance.js', 'assets/js/ses-portail.js', 'assets/js/ses-portail-suivi.js', 'assets/js/ses-portail-services.js',
                 'assets/js/ses-centre.js', 'assets/js/ses-centre-vues.js', 'assets/js/ses-dernier-km.js', 'assets/js/ses-analytique.js']) {
  const lignes = sansCommentaires(fs.readFileSync(f, 'utf8')).split('\n');
  const fautes = lignes.map((l, i) => [i + 1, l]).filter(([, l]) => CALCUL.test(l));
  ok(fautes.length === 0, f + ' : un montant calculé dans le navigateur — ' + fautes.slice(0, 3).map(([i, l]) => i + ': ' + l.trim().slice(0, 120)).join(' | '));
}

// 2. l'ancienne facturation : ses calculs connus, et seulement eux
const CONNUS = {
  'assets/js/ses-ui.js': ['totauxFacture', 'regrouper'],
  'assets/js/ses-admin.js': ['calculerPrix', 'preparerFormFacture', 'prixColis', 'totaliser']
};
for (const [f, fonctions] of Object.entries(CONNUS)) {
  const src = sansCommentaires(fs.readFileSync(f, 'utf8'));
  const vues = [];
  // chaque fonction qui contient un calcul sur un montant
  for (const m of src.matchAll(/function\s+(\w+)\s*\([^)]*\)\s*\{/g)) {
    let i = m.index + m[0].length, prof = 1;
    while (i < src.length && prof > 0) { if (src[i] === '{') prof++; else if (src[i] === '}') prof--; i++; }
    const corps = src.slice(m.index + m[0].length, i - 1);
    if (corps.split('\n').some((l) => CALCUL.test(l) && /Math\.round\(|\.reduce\(|[-*]\s*\(?\s*Number\(/.test(l))) vues.push(m[1]);
  }
  ok(JSON.stringify([...new Set(vues)].sort()) === JSON.stringify(fonctions.slice().sort()),
     f + ' : les calculs de l\'ancienne facturation sont exactement ' + fonctions.join(', ') + ' (vu : ' + [...new Set(vues)].join(', ') + ')');
}
console.log('PASS finance dans le navigateur : ' + n + ' vérifications — les écrans du moteur financier ne calculent aucun montant ; les calculs de l\'ancienne facturation sont connus, figés, à retirer à la bascule.');
