// ScannerService : les lecteurs changent, la lecture reste la même. Aucun navigateur, aucune caméra : des faux.
const assert = require('node:assert/strict');
const { creerService, normaliser, argumentsRpc, adaptateurClavier, adaptateurCamera, adaptateurProgrammable } =
  require('../../assets/js/ses-scanner.js');
let n = 0; const ok = (c, m) => { assert.ok(c, m); n++; };
const horloge = () => { let t = 1_000_000; return { maintenant: () => t, avance: (ms) => { t += ms; } }; };
const fauxClavier = () => { const l = {}; return { addEventListener: (e, f) => { l[e] = f; }, removeEventListener: (e) => { delete l[e]; }, touche: (key) => l.keydown && l.keydown({ key }), ecoute: () => !!l.keydown }; };
const taper = (clavier, h, texte, pasMs, fin) => { for (const c of texte) { clavier.touche(c); h.avance(pasMs); } if (fin !== null) { clavier.touche(fin || 'Enter'); } };

// 1. normalisation
ok(normaliser('  SES-10001-HT\r\n') === 'SES-10001-HT', 'retour chariot et espaces retirés');
ok(normaliser('SES\u0000-1\u0007') === 'SES-1', 'caractères de contrôle retirés');
ok(normaliser('ab') === null && normaliser('') === null && normaliser(null) === null && normaliser('x'.repeat(501)) === null, 'trop court, vide, absent, trop long : refusés');

// 2. scanner USB « clavier »
{
  const h = horloge(), k = fauxClavier(), lectures = [];
  const s = creerService({ maintenant: h.maintenant, appareilId: 'dev-usb' }).ajouterAdaptateur(adaptateurClavier(k, { maintenant: h.maintenant }));
  s.surLecture((l) => lectures.push(l)); s.demarrer();
  ok(k.ecoute(), 'le service écoute le clavier une fois démarré');
  taper(k, h, 'SES-10001-HT', 8);
  ok(lectures.length === 1 && lectures[0].code === 'SES-10001-HT' && lectures[0].genre === 'barcode' && lectures[0].source === 'clavier' && lectures[0].appareilId === 'dev-usb',
     'rafale rapide + Entrée : UNE lecture, avec genre, source et appareil');
  h.avance(3000); taper(k, h, 'tapé à la main par un humain', 200);
  ok(lectures.length === 1, 'une frappe HUMAINE (200 ms par touche) n\'est jamais prise pour un scan');
  h.avance(3000); taper(k, h, 'SES-10002-DO', 8, null);
  ok(lectures.length === 1, 'sans terminateur, rien n\'est émis');
  k.touche('Enter');
  ok(lectures.length === 2 && lectures[1].code === 'SES-10002-DO', 'le terminateur déclenche la lecture');
  h.avance(3000); taper(k, h, 'AB', 8);
  ok(lectures.length === 2, 'une rafale trop courte (< 4 caractères) est ignorée');
  h.avance(3000); taper(k, h, 'SES-10003-US', 8, 'Tab');
  ok(lectures.length === 3, 'la touche Tab termine aussi (réglage courant des scanners)');
  h.avance(3000); k.touche('Z'); h.avance(500); taper(k, h, 'SES-10004-HT', 8);
  ok(lectures.length === 4 && lectures[3].code === 'SES-10004-HT', 'une touche tapée AVANT la rafale ne pollue pas la lecture');
  s.arreter();
  ok(!k.ecoute(), 'arrêté : le service n\'écoute plus');
  h.avance(3000); taper(k, h, 'SES-10005-HT', 8);
  ok(lectures.length === 4, 'arrêté : plus aucune lecture');
}

// 3. caméra
(async () => {
  const h = horloge(), lectures = [];
  let images = 0; const detecteur = { detect: async (image) => { images++; return image.codes; } };
  const cam = adaptateurCamera(detecteur);
  const s = creerService({ maintenant: h.maintenant, debounceMs: 1500 }).ajouterAdaptateur(cam);
  s.surLecture((l) => lectures.push(l)); s.demarrer();
  const qr = [{ rawValue: 'https://x.test/suivi.html?colis=SES-10001-HT&j=abc', format: 'qr_code' }];
  for (let i = 0; i < 20; i++) { await cam.image({ codes: qr }); h.avance(33); }          // 20 images du même QR en 0,66 s
  ok(images === 20 && lectures.length === 1, '20 images du même QR : UNE seule lecture');
  ok(lectures[0].genre === 'qr' && lectures[0].code.indexOf('colis=SES-10001-HT') > 0, 'le QR est lu comme tel (le contenu complet est transmis, la base l\'interprète)');
  await cam.image({ codes: [{ rawValue: 'SES-10009-HT', format: 'code_128' }] });
  ok(lectures.length === 2 && lectures[1].genre === 'barcode', 'un code-barres Code 128 : genre « barcode »');
  h.avance(2000); await cam.image({ codes: qr });
  ok(lectures.length === 3, 'le même QR après la fenêtre (1,5 s) compte de nouveau');
  await cam.image({ codes: [] }); await cam.image({ codes: null });
  ok(lectures.length === 3, 'une image sans code : rien');
  // 4. TOUS les lecteurs ensemble : même code vu par la caméra ET le scanner USB = une lecture
  const k = fauxClavier(); const h2 = horloge(), l2 = [];
  const cam2 = adaptateurCamera(detecteur);
  const s2 = creerService({ maintenant: h2.maintenant }).ajouterAdaptateur(adaptateurClavier(k, { maintenant: h2.maintenant })).ajouterAdaptateur(cam2).ajouterAdaptateur(adaptateurProgrammable('rfid', 'rfid'));
  s2.surLecture((l) => l2.push(l)); s2.demarrer();
  await cam2.image({ codes: [{ rawValue: 'SES-10020-HT', format: 'qr_code' }] }); taper(k, h2, 'SES-10020-HT', 8);
  ok(l2.length === 1, 'la même étiquette vue par la caméra puis le scanner USB : UNE lecture (fenêtre commune)');
  s2.soumettre('  ses-10021-ht ');
  ok(l2.length === 2 && l2[1].genre === 'manual' && l2[1].code === 'ses-10021-ht', 'saisie à la main : même chemin, genre « manual »');
  const rfid = s2.statistiques(); ok(rfid.adaptateurs === 3, 'trois lecteurs de natures différentes branchés sur le même service');
  // 5. ajouter un lecteur en cours de route
  const tard = adaptateurProgrammable('douchette', 'barcode'); s2.ajouterAdaptateur(tard);
  ok(tard.lire('SES-10022-DO') === true && l2.length === 3 && l2[2].source === 'douchette', 'un lecteur ajouté après le démarrage est aussitôt actif');
  // 6. isolement des erreurs
  const s3 = creerService({}); const e3 = [], l3 = [];
  s3.surErreur((e, src) => e3.push(src)); s3.surLecture(() => { throw new Error('abonné cassé'); }); s3.surLecture((l) => l3.push(l.code));
  const p = adaptateurProgrammable('p'); s3.ajouterAdaptateur(p).demarrer(); p.lire('SES-10030-HT');
  ok(l3.length === 1 && e3.length === 1, 'un abonné qui plante n\'empêche pas les autres, et l\'erreur est signalée');
  const cassé = { nom: 'cassé', demarrer() { throw new Error('pas de caméra'); }, arreter() { throw new Error('x'); } };
  const s4 = creerService({}); const e4 = []; s4.surErreur((e, src) => e4.push(src)); s4.ajouterAdaptateur(cassé).ajouterAdaptateur(adaptateurProgrammable('bon')).demarrer(); s4.arreter();
  ok(e4.length === 2 && e4[0] === 'cassé', 'un lecteur défaillant (caméra refusée) n\'arrête pas les autres');
  assert.throws(() => s4.ajouterAdaptateur({}), /Adaptateur invalide/); n++;
  // 7. ce qu'on envoie à la base : le même, quel que soit le lecteur
  const ctx = { intention: 'receive', entrepotId: 'W1', emplacementId: null };
  const a = argumentsRpc({ code: 'SES-10001-HT', genre: 'barcode', appareilId: 'D1', horodatage: 42 }, ctx);
  const b = argumentsRpc({ code: 'SES-10001-HT', genre: 'barcode', appareilId: 'D1', horodatage: 42 }, ctx);
  const c = argumentsRpc({ code: 'SES-10001-HT', genre: 'qr', appareilId: 'D2', horodatage: 43 }, ctx);
  ok(a.p_idempotency_key === b.p_idempotency_key, 'la MÊME lecture renvoyée produit la MÊME clé d\'idempotence (la base ne la compte pas deux fois)');
  ok(a.p_idempotency_key !== c.p_idempotency_key, 'une autre lecture produit une autre clé');
  ok(JSON.stringify(Object.keys(a)) === JSON.stringify(Object.keys(c)) && a.p_code === c.p_code && a.p_purpose === 'receive' && a.p_location_id === null && a.p_warehouse_id === 'W1',
     'les arguments ont la même forme, quel que soit le lecteur : le métier n\'en voit pas la nature');
  console.log('PASS ScannerService : ' + n + ' vérifications — scanner USB (rafale vs frappe humaine), caméra (anti-rebond), saisie manuelle, lecteurs multiples, erreurs isolées, arguments identiques pour le métier.');
})().catch((e) => { console.error('ÉCHEC ScannerService :', e.message); process.exit(1); });
