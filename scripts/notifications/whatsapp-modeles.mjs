#!/usr/bin/env node
// =============================================================================
// Speed Express Shipping — soumettre les modèles WhatsApp à Meta (phase 11)
// -----------------------------------------------------------------------------
// WhatsApp n'envoie, hors d'une conversation ouverte par le client, que des modèles APPROUVÉS par Meta. Ce script soumet ceux de
// whatsapp-modeles.json (écrit par outils/portail-textes.py : les mêmes textes que le portail, paramètres nommés), et seulement ceux qui
// n'existent pas encore. À lancer côté serveur (dépôt privé, ou le poste du propriétaire), jamais dans un navigateur :
//
//   SES_WHATSAPP_TOKEN=… SES_WHATSAPP_WABA_ID=… node scripts/notifications/whatsapp-modeles.mjs            # liste ce qui serait soumis
//   SES_WHATSAPP_TOKEN=… SES_WHATSAPP_WABA_ID=… node scripts/notifications/whatsapp-modeles.mjs --soumettre
//
// SES_WHATSAPP_WABA_ID : l'identifiant du compte WhatsApp Business (pas un secret) ; SES_WHATSAPP_TOKEN : SECRET. Meta répond en quelques
// minutes à quelques heures ; tant qu'un modèle n'est pas approuvé, le travailleur reçoit l'erreur 132001 pour lui (échec, sans nouvel essai).
// =============================================================================
import { readFileSync } from 'node:fs';

export function aSoumettre(modeles, existants) {
  const deja = new Set(existants.map((m) => m.name + '|' + m.language));
  return modeles.filter((m) => !deja.has(m.name + '|' + m.language));
}

async function principal() {
  const jeton = String(process.env.SES_WHATSAPP_TOKEN || '').trim(), waba = String(process.env.SES_WHATSAPP_WABA_ID || '').trim();
  const version = String(process.env.SES_WHATSAPP_VERSION || 'v23.0');
  if (!jeton || !/^[0-9]{6,30}$/.test(waba) || !/^v[0-9]{1,2}\.[0-9]$/.test(version)) { console.error('SES_WHATSAPP_TOKEN et SES_WHATSAPP_WABA_ID sont requis.'); process.exit(2); }
  const { modeles } = JSON.parse(readFileSync(new URL('./whatsapp-modeles.json', import.meta.url), 'utf8'));
  const base = 'https://graph.facebook.com/' + version + '/' + waba + '/message_templates';
  const existants = [];
  let suite = base + '?fields=name,language,status&limit=100';
  while (suite) {
    const r = await fetch(suite, { headers: { Authorization: 'Bearer ' + jeton } });
    const j = await r.json();
    if (!r.ok) { console.error('Meta refuse la liste : ' + r.status + ' ' + JSON.stringify(j.error || {}).slice(0, 200)); process.exit(1); }
    existants.push(...(j.data || []));
    suite = j.paging && j.paging.next ? j.paging.next : null;
  }
  const liste = aSoumettre(modeles, existants);
  for (const m of existants.filter((x) => /^ses_/.test(x.name))) console.log('déjà chez Meta : ' + m.name + ' (' + m.language + ') — ' + m.status);
  if (!process.argv.includes('--soumettre')) { liste.forEach((m) => console.log('à soumettre : ' + m.name + ' (' + m.language + ')')); return; }
  for (const m of liste) {
    const r = await fetch(base, { method: 'POST', headers: { Authorization: 'Bearer ' + jeton, 'Content-Type': 'application/json' }, body: JSON.stringify(m) });
    const j = await r.json();
    console.log((r.ok ? 'soumis : ' : 'REFUSÉ : ') + m.name + ' (' + m.language + ')' + (r.ok ? ' — ' + (j.status || '') : ' — ' + JSON.stringify(j.error || {}).slice(0, 200)));
  }
}

if (import.meta.url === 'file://' + process.argv[1]) principal().catch((e) => { console.error(String(e && e.message || e)); process.exit(1); });
