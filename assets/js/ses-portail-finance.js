/* ==========================================================================
   Portail client — factures, paiements, documents
   --------------------------------------------------------------------------
   Les montants, les soldes et les statuts viennent de la base (moteur
   financier, outils/logistique/007-finance.sql). Ici on les montre : aucun
   total n'est recalculé, aucune facture ne se modifie. Une facture émise est
   figée ; un client qui veut la contester écrit au support.
   ========================================================================== */
(function () {
  'use strict';
  var P = window.SES_PORTAIL, API = window.SES_API, UI = window.SES_UI;
  if (!P || !API || !UI) return;
  var t = P.t, e = P.e;
  var CFG = window.SES_CONFIG || {};

  var GENRE_FACTURE = { PAID: 'ok', REFUNDED: 'neutre', CANCELLED: 'neutre', OVERDUE: 'bad', PARTIALLY_PAID: 'warn', ISSUED: 'info' };
  function pastilleFacture(statut) { return P.pastille('inv-' + statut, GENRE_FACTURE[statut]); }

  function lienWhatsapp() {
    if (!CFG.whatsapp) return '';
    var m = P.profil() || {};
    return 'https://wa.me/' + CFG.whatsapp + '?text=' + encodeURIComponent('Bonjour, je suis ' + (m.nom_complet || '') + ' (' + (m.code || '') + ').');
  }

  /* ----------------------------------------------------------------------
     La facture imprimable (les montants sont ceux de la base, ligne par ligne)
     ---------------------------------------------------------------------- */
  function ligneTotal(libelle, valeur, fort, couleur) {
    return '<tr><td style="padding:' + (fort ? '9px 11px' : '5px 11px') + ';text-align:right;' + (fort ? 'font-weight:800;font-size:15px;border-top:1px solid #e6e6e6;' : 'color:#4b5563;') + '">' + e(libelle) + '</td>' +
      '<td style="padding:' + (fort ? '9px 11px' : '5px 11px') + ';text-align:right;width:34%;font-family:\'IBM Plex Mono\',monospace;' + (fort ? 'font-weight:800;font-size:15px;border-top:1px solid #e6e6e6;' : '') +
      (couleur ? 'color:' + couleur + ';' : '') + '">' + e(valeur) + '</td></tr>';
  }

  function facturePage(f) {
    var m = P.profil() || {}, dev = f.currency, solde = Number(f.balance);
    var paye = f.status === 'PAID' || f.status === 'REFUNDED';
    return '<div class="ses-facture-page" style="font-family:Manrope,system-ui,sans-serif;color:#0b0c0e;font-size:13px;line-height:1.55">' +
      '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:24px;border-bottom:3px solid #e8121b;padding-bottom:14px">' +
        '<div><img src="assets/img/ses-logo.png" alt="Speed Express Shipping" style="display:block;height:46px;width:auto;margin:0 0 9px">' +
        '<p style="margin:0;font-size:12px;color:#4b5563">' + e(CFG.factureAdresse || '') + '<br>' + e(t('facture-tel')) + ' ' + e(CFG.factureTelephone || '') + ' · ' + e(t('facture-rnc')) + ' ' + e(CFG.factureRNC || '') + '</p></div>' +
        '<div style="text-align:right"><p style="margin:0;font-family:Saira,Manrope,sans-serif;font-size:20px;font-weight:800">' + e(t('facture-titre')) + '</p>' +
        '<p style="margin:2px 0 0;font-family:\'IBM Plex Mono\',monospace;font-size:13px">' + e(f.number) + '</p>' +
        '<p style="margin:6px 0 0;display:inline-block;border-radius:999px;padding:4px 12px;font-weight:700;font-size:12px;' +
        (paye ? 'background:rgba(19,192,44,.14);color:#0b7a19' : 'background:rgba(232,18,27,.12);color:#b60d14') + '">' + e(t('inv-' + f.status)) + '</p></div></div>' +
      '<div style="display:flex;gap:28px;margin-top:18px"><div style="flex:1"><p style="margin:0 0 4px;font-size:10px;letter-spacing:.12em;color:#6b7280">' + e(t('facture-client')) + '</p>' +
        '<p style="margin:0;font-weight:700">' + e(m.nom_complet || '—') + '</p><p style="margin:0;font-family:\'IBM Plex Mono\',monospace">' + e(m.code || '—') + '</p>' +
        '<p style="margin:2px 0 0;color:#4b5563">' + e(m.email || '') + '<br>' + e(m.telephone || '') + '</p></div>' +
        '<div style="flex:1"><p style="margin:0 0 4px;font-size:10px;letter-spacing:.12em;color:#6b7280">' + e(t('facture-details')) + '</p>' +
        '<p style="margin:0">' + e(t('facture-emise')) + ' : ' + e(UI.date(f.issued_at)) + '</p>' +
        (f.due_date ? '<p style="margin:0">' + e(t('facture-echeance')) + ' : ' + e(UI.date(f.due_date)) + '</p>' : '') + '</div></div>' +
      '<table style="width:100%;border-collapse:collapse;margin-top:20px"><thead><tr style="background:#f6f6f6">' +
        ['p-f-description', 'facture-quantite', 'facture-montant'].map(function (cle, i) {
          return '<th style="text-align:' + (i === 0 ? 'left' : 'right') + ';padding:9px 11px;font-size:10.5px;letter-spacing:.08em;color:#4b5563;border-bottom:1px solid #e6e6e6;white-space:nowrap">' + e(t(cle)) + '</th>';
        }).join('') + '</tr></thead><tbody>' + f.items.map(function (l) {
          var c = 'padding:9px 11px;border-bottom:1px solid #f0f0f0;', mono = 'font-family:\'IBM Plex Mono\',monospace;text-align:right;';
          return '<tr><td style="' + c + '">' + e(l.description || t('line-' + l.kind)) + '<br><span style="font-size:11px;color:#6b7280">' + e(t('line-' + l.kind)) + '</span></td>' +
            '<td style="' + c + mono + '">' + (l.kind === 'FREIGHT' ? e(UI.nombre(l.quantity)) : '') + '</td><td style="' + c + mono + '">' + e(UI.montant(l.amount, dev)) + '</td></tr>';
        }).join('') + '</tbody></table>' +
      '<div style="display:flex;justify-content:flex-end;margin-top:14px"><table style="border-collapse:collapse;min-width:290px">' +
        ligneTotal(t('facture-grand-total'), UI.montant(f.total, dev), true) +
        (Number(f.credited) ? ligneTotal(t('p-f-avoirs'), UI.montant(f.credited, dev)) : '') +
        ligneTotal(t('facture-paye'), UI.montant(f.paid, dev)) + (Number(f.refunded) ? ligneTotal(t('p-f-rembourse'), UI.montant(f.refunded, dev)) : '') +
        ligneTotal(t('facture-balance'), UI.montant(solde, dev), true, solde > 0 ? '#b60d14' : '#0b7a19') + '</table></div>' +
      '<div class="ses-facture-pied" style="margin:30px 0 0;border-top:1px solid #e6e6e6;padding-top:12px;text-align:center;font-size:12.5px;color:#4b5563">' + e(t('facture-pied')) + '</div></div>';
  }

  /* ----------------------------------------------------------------------
     Factures
     ---------------------------------------------------------------------- */
  var filtreFactures = '';

  function dessinerFactures(zone, d) {
    var factures = d.factures, soldes = d.soldes;
    var dus = soldes.filter(function (s) { return Number(s.balance) > 0; });
    var lignes = factures.filter(function (f) {
      if (!filtreFactures) return true;
      return filtreFactures === 'due' ? Number(f.balance) > 0 : Number(f.balance) <= 0;
    });
    zone.innerHTML = P.titre('p-nav-factures', 'p-f-intro') +
      '<div class="ses-chiffres">' + (dus.length ? dus.map(function (s) {
        return '<div class="ses-chiffre ses-carte"><b class="ses-chiffre-bad">' + e(UI.montant(s.balance, s.currency)) + '</b><span>' + e(t('p-f-solde-du')) + '</span></div>';
      }).join('') : '<div class="ses-chiffre ses-carte"><b class="ses-chiffre-ok">' + e(UI.montant(0)) + '</b><span>' + e(t('p-f-rien-du')) + '</span></div>') + '</div>' +
      '<div class="ses-filtres" role="group" aria-label="' + e(t('p-filtrer-factures')) + '" style="margin-top:20px">' +
        [['', t('tous')], ['due', t('p-f-a-regler')], ['soldee', t('p-f-soldees')]].map(function (c) {
          return '<button type="button" class="ses-filtre" data-f="' + c[0] + '" aria-pressed="' + (c[0] === filtreFactures ? 'true' : 'false') + '">' + e(c[1]) + '</button>';
        }).join('') + '</div><div style="margin-top:18px">' + (lignes.length ? '<table class="ses-tableau"><caption class="sr-only">' + e(t('p-nav-factures')) + '</caption><thead><tr>' +
        ['facture-numero', 'p-f-emise', 'p-f-echeance', 'facture-montant', 'p-f-paye', 'p-f-reste', 'facture-statut'].map(function (k) { return '<th scope="col">' + e(t(k)) + '</th>'; }).join('') +
        '<th scope="col"><span class="sr-only">' + e(t('colonne-actions')) + '</span></th></tr></thead><tbody>' + lignes.map(function (f) {
          return '<tr><td data-libelle="' + e(t('facture-numero')) + '" class="ses-mono">' + e(f.number) + '</td>' +
            '<td data-libelle="' + e(t('p-f-emise')) + '">' + e(UI.date(f.issued_at)) + '</td><td data-libelle="' + e(t('p-f-echeance')) + '">' + e(f.due_date ? UI.date(f.due_date) : '—') + '</td>' +
            '<td data-libelle="' + e(t('facture-montant')) + '" class="ses-mono">' + e(UI.montant(f.total, f.currency)) + '</td><td data-libelle="' + e(t('p-f-paye')) + '" class="ses-mono">' + e(UI.montant(f.paid, f.currency)) + '</td>' +
            '<td data-libelle="' + e(t('p-f-reste')) + '" class="ses-mono">' + e(UI.montant(f.balance, f.currency)) + '</td><td data-libelle="' + e(t('facture-statut')) + '">' + pastilleFacture(f.status) + '</td>' +
            '<td><div class="ses-actions-ligne"><a class="ses-bouton ses-bouton-second ses-bouton-mini" href="' + P.lien('factures', f.number) + '">' + e(t('p-f-voir')) + '</a></div></td></tr>';
        }).join('') + '</tbody></table>' : '<div class="ses-bloc">' + UI.vide(t(factures.length ? 'factures-vide-filtre' : 'factures-vide'), '▤') + '</div>') + '</div>';
    zone.querySelector('.ses-filtres').addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-f]');
      if (!b) return;
      filtreFactures = b.getAttribute('data-f');
      dessinerFactures(zone, d);
      var n = zone.querySelector('[data-f="' + filtreFactures + '"]');
      if (n) n.focus();
    });
  }

  function dessinerFacture(zone, f) {
    zone.innerHTML = '<p class="ses-retour"><a href="' + P.lien('factures') + '">← ' + e(t('p-f-retour')) + '</a></p>' +
      '<header class="ses-ph"><h2 tabindex="-1"><span class="ses-mono">' + e(f.number) + '</span></h2><p>' + pastilleFacture(f.status) + '</p></header>' +
      '<div class="ses-deux"><section class="ses-carte ses-bloc"><h3>' + e(t('p-f-lignes')) + '</h3><table class="ses-tableau"><caption class="sr-only">' + e(t('p-f-lignes')) + '</caption><thead><tr>' +
      ['p-f-description', 'facture-quantite', 'facture-montant'].map(function (k) { return '<th scope="col">' + e(t(k)) + '</th>'; }).join('') + '</tr></thead><tbody>' + f.items.map(function (l) {
        return '<tr><td data-libelle="' + e(t('p-f-description')) + '">' + e(l.description || t('line-' + l.kind)) + '<br><span class="ses-muet">' + e(t('line-' + l.kind)) + '</span></td>' +
          '<td data-libelle="' + e(t('facture-quantite')) + '" class="ses-mono">' + (l.kind === 'FREIGHT' ? e(UI.nombre(l.quantity)) : '') + '</td>' +
          '<td data-libelle="' + e(t('facture-montant')) + '" class="ses-mono">' + e(UI.montant(l.amount, f.currency)) + '</td></tr>';
      }).join('') + '</tbody></table></section><div style="display:grid;gap:18px;align-content:start"><section class="ses-carte ses-bloc"><h3>' + e(t('p-f-resume')) + '</h3><dl class="ses-dl">' +
      P.detail(t('p-f-emise'), UI.date(f.issued_at)) + P.detail(t('p-f-echeance'), f.due_date ? UI.date(f.due_date) : '') +
      P.detail(t('facture-montant'), UI.montant(f.total, f.currency)) + (Number(f.credited) ? P.detail(t('p-f-avoirs'), UI.montant(f.credited, f.currency)) : '') +
      P.detail(t('p-f-paye'), UI.montant(f.paid, f.currency)) + (Number(f.refunded) ? P.detail(t('p-f-rembourse'), UI.montant(f.refunded, f.currency)) : '') +
      P.detail(t('p-f-reste'), UI.montant(f.balance, f.currency)) + '</dl>' +
      '<p style="margin:16px 0 0;display:flex;flex-wrap:wrap;gap:10px"><button type="button" class="ses-bouton ses-bouton-principal ses-bouton-mini" data-imprimer>' + e(t('imprimer')) + '</button>' +
      '<a class="ses-bouton ses-bouton-second ses-bouton-mini" href="' + P.lien('support', 'nouveau-facture/' + f.number) + '">' + e(t('p-f-question')) + '</a></p></section>' +
      (Number(f.balance) > 0 ? '<section class="ses-carte ses-bloc"><h3>' + e(t('p-f-comment-payer')) + '</h3><p>' + e(t('p-f-payer-texte')) + '</p>' +
        (lienWhatsapp() ? '<p><a class="ses-bouton ses-bouton-second ses-bouton-mini" href="' + e(lienWhatsapp()) + '" rel="noopener">' + e(t('p-f-payer-whatsapp')) + '</a></p>' : '') + '</section>' : '') +
      '</div></div>';
    zone.querySelector('[data-imprimer]').addEventListener('click', function () { UI.imprimer(facturePage(f), 'facture'); });
  }

  P.enregistrer({
    id: 'factures', ordre: 60,
    rendre: function (zone, param) {
      return P.charger(zone, function () {
        return Promise.all([API.portail.factures(), API.portail.solde()]).then(function (r) { return { factures: r[0], soldes: r[1] }; });
      }, function (d) {
        if (!param) { dessinerFactures(zone, d); return; }
        var f = d.factures.filter(function (x) { return x.number === param; })[0];
        if (f) dessinerFacture(zone, f);
        else { zone.innerHTML = P.titre('p-nav-factures') + '<div class="ses-bloc">' + UI.vide(t('p-f-introuvable'), '▤') + '</div><p><a href="' + P.lien('factures') + '">← ' + e(t('p-f-retour')) + '</a></p>'; }
      });
    }
  });

  /* ----------------------------------------------------------------------
     Paiements
     ---------------------------------------------------------------------- */
  function tableau(titreCle, colonnes, lignes) {
    return '<section class="ses-carte ses-bloc" style="margin-top:18px"><h3>' + e(t(titreCle)) + '</h3>' + (lignes.length ? '<table class="ses-tableau"><caption class="sr-only">' + e(t(titreCle)) + '</caption><thead><tr>' +
      colonnes.map(function (c) { return '<th scope="col">' + e(t(c[0])) + '</th>'; }).join('') + '</tr></thead><tbody>' + lignes.map(function (l) {
        return '<tr>' + colonnes.map(function (c) { return '<td data-libelle="' + e(t(c[0])) + '"' + (c[2] ? ' class="ses-mono"' : '') + '>' + c[1](l) + '</td>'; }).join('') + '</tr>';
      }).join('') + '</tbody></table>' : '<p class="ses-muet">' + e(t('p-pay-aucun')) + '</p>') + '</section>';
  }

  P.enregistrer({
    id: 'paiements', ordre: 70,
    rendre: function (zone) {
      return P.charger(zone, function () { return API.portail.paiements(); }, function (d) {
        var wa = lienWhatsapp();
        zone.innerHTML = P.titre('p-nav-paiements', 'p-pay-intro') +
          tableau('p-pay-recus', [['p-pay-date', function (p) { return e(UI.date(p.paid_at, true)); }], ['p-pay-numero', function (p) { return e(p.number); }, true], ['p-pay-facture', function (p) { return '<a href="' + P.lien('factures', p.invoice) + '">' + e(p.invoice) + '</a>'; }, true],
            ['p-pay-mode', function (p) { return e(t('method-' + p.method)); }], ['facture-montant', function (p) {
              return e(UI.montant(p.amount, p.currency)) + (p.tendered_currency !== p.currency ? '<br><span class="ses-muet">' + e(t('p-pay-remis', { montant: UI.montant(p.tendered_amount, p.tendered_currency) })) + '</span>' : '');
            }, true]], d.payments) +
          (d.credits.length ? tableau('p-pay-avoirs', [['p-pay-date', function (c) { return e(UI.date(c.issued_at)); }], ['p-pay-numero', function (c) { return e(c.number); }, true], ['p-pay-facture', function (c) { return e(c.invoice); }, true],
            ['p-pay-motif', function (c) { return e(c.reason); }], ['facture-montant', function (c) { return e(UI.montant(c.amount, c.currency)); }, true]], d.credits) : '') +
          (d.refunds.length ? tableau('p-pay-remboursements', [['p-pay-date', function (r) { return e(UI.date(r.refunded_at)); }], ['p-pay-numero', function (r) { return e(r.number); }, true], ['p-pay-facture', function (r) { return e(r.invoice); }, true],
            ['p-pay-mode', function (r) { return e(t('method-' + r.method)); }], ['facture-montant', function (r) { return e(UI.montant(r.amount, r.currency)); }, true]], d.refunds) : '') +
          '<section class="ses-carte ses-bloc" style="margin-top:18px"><h3>' + e(t('p-f-comment-payer')) + '</h3><p>' + e(t('p-f-payer-texte')) + '</p>' +
          (wa ? '<p><a class="ses-bouton ses-bouton-second ses-bouton-mini" href="' + e(wa) + '" rel="noopener">' + e(t('p-f-payer-whatsapp')) + '</a></p>' : '') + '</section>';
      });
    }
  });

  /* ----------------------------------------------------------------------
     Documents
     ---------------------------------------------------------------------- */
  var filtreDocs = '';
  var GENRE_DOC = { INVOICE: 'info', CREDIT_NOTE: 'warn', QUOTE: 'neutre', DELIVERY_RECEIPT: 'ok' };

  function dessinerDocuments(zone, docs) {
    var genres = ['INVOICE', 'CREDIT_NOTE', 'QUOTE', 'DELIVERY_RECEIPT'].filter(function (g) { return docs.some(function (d) { return d.kind === g; }); });
    var lignes = docs.filter(function (d) { return !filtreDocs || d.kind === filtreDocs; });
    zone.innerHTML = P.titre('p-nav-documents', 'p-doc-intro') +
      '<div class="ses-filtres" role="group" aria-label="' + e(t('p-doc-filtrer')) + '">' + [''].concat(genres).map(function (g) {
        return '<button type="button" class="ses-filtre" data-g="' + g + '" aria-pressed="' + (g === filtreDocs ? 'true' : 'false') + '">' + e(g ? t('doc-' + g) : t('tous')) + '</button>';
      }).join('') + '</div><div style="margin-top:18px">' + (lignes.length ? lignes.map(function (d) {
        var x = d.extra || {}, detail = '';
        if (d.kind === 'INVOICE') detail = '<a class="ses-bouton ses-bouton-second ses-bouton-mini" href="' + P.lien('factures', d.number) + '">' + e(t('p-f-voir')) + '</a>';
        if (d.kind === 'CREDIT_NOTE') detail = '<p class="ses-muet">' + e(t('p-doc-sur-facture', { numero: x.invoice })) + ' — ' + e(x.reason) + '</p>';
        if (d.kind === 'QUOTE') detail = '<details><summary>' + e(t('p-doc-lignes')) + ' · ' + e(t('p-doc-valide', { date: UI.date(x.valid_until) })) + '</summary><ul class="ses-liste-simple">' +
          (x.lines || []).map(function (l) { return '<li>' + e(l.description || t('line-' + l.kind)) + ' — <span class="ses-mono">' + e(UI.montant(l.amount, d.currency)) + '</span></li>'; }).join('') + '</ul></details>';
        if (d.kind === 'DELIVERY_RECEIPT') detail = '<p class="ses-muet">' + e(t('p-d-recu-par')) + ' : ' + e(x.recipient_name) + ' · ' + (x.parcels || []).map(function (n) { return '<a href="' + P.lien('colis', n) + '">' + e(n) + '</a>'; }).join(', ') + '</p>';
        return '<article class="ses-carte ses-bloc ses-fiche"><div class="ses-fiche-tete"><div><p class="ses-mono ses-fiche-num">' + e(d.number) + '</p><p class="ses-fiche-desc">' + e(UI.date(d.date, true)) +
          (d.amount !== null && d.amount !== undefined ? ' · ' + e(UI.montant(d.amount, d.currency)) : '') + '</p></div><div style="text-align:right">' + P.pastille('doc-' + d.kind, GENRE_DOC[d.kind]) +
          (d.kind === 'INVOICE' ? ' ' + pastilleFacture(d.status) : (d.kind === 'QUOTE' ? ' ' + P.pastille('quote-' + d.status, d.status === 'OFFERED' ? 'info' : 'neutre') : '')) + '</div></div>' + detail + '</article>';
      }).join('') : '<div class="ses-bloc">' + UI.vide(t('p-doc-vide'), '▤') + '</div>') + '</div>';
    zone.querySelector('.ses-filtres').addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-g]');
      if (!b) return;
      filtreDocs = b.getAttribute('data-g');
      dessinerDocuments(zone, docs);
      var n = zone.querySelector('[data-g="' + filtreDocs + '"]');
      if (n) n.focus();
    });
  }

  P.enregistrer({
    id: 'documents', ordre: 80,
    rendre: function (zone) {
      return P.charger(zone, function () { return API.portail.documents(); }, function (docs) { dessinerDocuments(zone, docs); });
    }
  });
})();
