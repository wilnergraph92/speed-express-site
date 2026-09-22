/* ==========================================================================
   Speed Express Shipping — QR codes et codes-barres
   --------------------------------------------------------------------------
   Deux générateurs écrits ici même, sans bibliothèque extérieure : les
   étiquettes se fabriquent dans le navigateur, hors ligne, et aucun script
   étranger ne s'exécute dans les pages du tableau de bord.

     SES_CODES.qrSVG(texte, options)      QR code (ISO/IEC 18004, niveau M)
     SES_CODES.code128SVG(texte, options) code-barres Code 128 (variante B)

   Les deux rendent une chaîne SVG : elle s'affiche à l'écran, s'imprime net
   à n'importe quelle taille, et se copie dans une étiquette sans image.
   ========================================================================== */
(function (racine) {
  'use strict';

  /* ======================================================================
     1. QR code
     ====================================================================== */

  /* Corps de Galois GF(256) : l'arithmétique des codes de Reed-Solomon. */
  var EXP = new Uint8Array(512);
  var LOG = new Uint8Array(256);
  (function () {
    var x = 1;
    for (var i = 0; i < 255; i++) {
      EXP[i] = x;
      LOG[x] = i;
      x <<= 1;
      if (x & 0x100) x ^= 0x11d;
    }
    for (var j = 255; j < 512; j++) EXP[j] = EXP[j - 255];
  })();

  function mul(a, b) {
    if (a === 0 || b === 0) return 0;
    return EXP[LOG[a] + LOG[b]];
  }

  /* Polynôme générateur de degré n (produit des (x - a^i)). */
  function generateur(n) {
    var g = [1];
    for (var i = 0; i < n; i++) {
      var suivant = new Array(g.length + 1).fill(0);
      for (var j = 0; j < g.length; j++) {
        suivant[j] ^= g[j];
        suivant[j + 1] ^= mul(g[j], EXP[i]);
      }
      g = suivant;
    }
    return g;
  }

  /* Mots de correction d'un bloc de données. */
  function correction(donnees, nbEc) {
    var g = generateur(nbEc);
    var reste = new Array(nbEc).fill(0);
    for (var i = 0; i < donnees.length; i++) {
      var facteur = donnees[i] ^ reste[0];
      reste.shift();
      reste.push(0);
      if (facteur !== 0) {
        for (var j = 0; j < nbEc; j++) reste[j] ^= mul(g[j + 1], facteur);
      }
    }
    return reste;
  }

  /* Structure des blocs au niveau M, versions 1 à 10 :
     [mots de correction par bloc, blocs du groupe 1, données par bloc,
      blocs du groupe 2, données par bloc]. */
  var BLOCS_M = [
    null,
    [10, 1, 16, 0, 0],
    [16, 1, 28, 0, 0],
    [26, 1, 44, 0, 0],
    [18, 2, 32, 0, 0],
    [24, 2, 43, 0, 0],
    [16, 4, 27, 0, 0],
    [18, 4, 31, 0, 0],
    [22, 2, 38, 2, 39],
    [22, 3, 36, 2, 37],
    [26, 4, 43, 1, 44]
  ];

  /* Centres des motifs d'alignement, versions 1 à 10. */
  var ALIGNEMENT = [
    null, [], [6, 18], [6, 22], [6, 26], [6, 30],
    [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50]
  ];

  function motsDonnees(v) {
    var b = BLOCS_M[v];
    return b[1] * b[2] + b[3] * b[4];
  }

  /* Nombre d'octets que la version v peut porter en mode « octets ». */
  function capacite(v) {
    var bits = motsDonnees(v) * 8 - 4 - (v < 10 ? 8 : 16);
    return Math.floor(bits / 8);
  }

  /* Texte -> octets UTF-8 (les accents comptent double : c'est voulu). */
  function octets(texte) {
    var s = unescape(encodeURIComponent(String(texte)));
    var out = new Array(s.length);
    for (var i = 0; i < s.length; i++) out[i] = s.charCodeAt(i) & 0xff;
    return out;
  }

  /* Suite de bits, écrite au fur et à mesure. */
  function Bits() {
    this.octets = [];
    this.n = 0;
  }
  Bits.prototype.ajouter = function (valeur, largeur) {
    for (var i = largeur - 1; i >= 0; i--) {
      var bit = (valeur >>> i) & 1;
      var index = this.n >> 3;
      if (this.octets.length <= index) this.octets.push(0);
      if (bit) this.octets[index] |= 0x80 >>> (this.n & 7);
      this.n++;
    }
  };

  /* Codage des données : en-tête, contenu, terminateur, remplissage. */
  function codewords(donnees, v) {
    var mots = motsDonnees(v);
    var b = new Bits();
    b.ajouter(4, 4);                              // mode « octets »
    b.ajouter(donnees.length, v < 10 ? 8 : 16);   // nombre d'octets
    for (var i = 0; i < donnees.length; i++) b.ajouter(donnees[i], 8);
    var reste = mots * 8 - b.n;
    b.ajouter(0, Math.min(4, reste));             // terminateur
    if (b.n & 7) b.ajouter(0, 8 - (b.n & 7));     // fin de l'octet courant
    var tampon = [0xec, 0x11], t = 0;
    while (b.octets.length < mots) b.octets.push(tampon[t++ & 1]);
    return b.octets;
  }

  /* Découpage en blocs, correction d'erreurs, puis entrelacement. */
  function blocs(mots, v) {
    var s = BLOCS_M[v], ec = s[0];
    var groupes = [];
    var i = 0, k;
    for (k = 0; k < s[1]; k++) { groupes.push(mots.slice(i, i + s[2])); i += s[2]; }
    for (k = 0; k < s[3]; k++) { groupes.push(mots.slice(i, i + s[4])); i += s[4]; }
    var corrections = groupes.map(function (g) { return correction(g, ec); });

    var sortie = [];
    var maxDonnees = Math.max.apply(null, groupes.map(function (g) { return g.length; }));
    for (var c = 0; c < maxDonnees; c++) {
      for (k = 0; k < groupes.length; k++) if (c < groupes[k].length) sortie.push(groupes[k][c]);
    }
    for (c = 0; c < ec; c++) {
      for (k = 0; k < corrections.length; k++) sortie.push(corrections[k][c]);
    }
    return sortie;
  }

  /* --- Trame ------------------------------------------------------------
     Chaque case vaut 0 (clair), 1 (sombre) ou null (encore vide).
     « reserve » marque les zones de service, que les données évitent.     */
  function trame(v) {
    var n = v * 4 + 17;
    var m = [], r = [], i, j;
    for (i = 0; i < n; i++) {
      m.push(new Array(n).fill(null));
      r.push(new Array(n).fill(false));
    }

    function bloc(x, y, l, h, valeur) {
      for (var a = 0; a < h; a++) {
        for (var b2 = 0; b2 < l; b2++) {
          var yy = y + a, xx = x + b2;
          if (yy < 0 || xx < 0 || yy >= n || xx >= n) continue;
          m[yy][xx] = valeur;
          r[yy][xx] = true;
        }
      }
    }

    /* Motifs de repère des trois angles, séparateurs compris. */
    function repere(x, y) {
      bloc(x - 1, y - 1, 9, 9, 0);
      bloc(x, y, 7, 7, 1);
      bloc(x + 1, y + 1, 5, 5, 0);
      bloc(x + 2, y + 2, 3, 3, 1);
    }
    repere(0, 0);
    repere(n - 7, 0);
    repere(0, n - 7);

    /* Lignes de cadence. */
    for (i = 8; i < n - 8; i++) {
      var t = i % 2 === 0 ? 1 : 0;
      m[6][i] = t; r[6][i] = true;
      m[i][6] = t; r[i][6] = true;
    }

    /* Motifs d'alignement. */
    var centres = ALIGNEMENT[v];
    for (i = 0; i < centres.length; i++) {
      for (j = 0; j < centres.length; j++) {
        var cx = centres[j], cy = centres[i];
        if ((cx === 6 && cy === 6) || (cx === 6 && cy === n - 7) || (cx === n - 7 && cy === 6)) continue;
        bloc(cx - 2, cy - 2, 5, 5, 1);
        bloc(cx - 1, cy - 1, 3, 3, 0);
        bloc(cx, cy, 1, 1, 1);
      }
    }

    /* Case toujours sombre, et emplacements du format. */
    m[n - 8][8] = 1; r[n - 8][8] = true;
    for (i = 0; i < 9; i++) {
      if (!r[8][i] || i === 6) { r[8][i] = true; if (m[8][i] === null) m[8][i] = 0; }
      if (!r[i][8] || i === 6) { r[i][8] = true; if (m[i][8] === null) m[i][8] = 0; }
    }
    for (i = 0; i < 8; i++) {
      r[8][n - 1 - i] = true; if (m[8][n - 1 - i] === null) m[8][n - 1 - i] = 0;
      r[n - 1 - i][8] = true; if (m[n - 1 - i][8] === null) m[n - 1 - i][8] = 0;
    }

    /* Emplacements de la version (à partir de la version 7). */
    if (v >= 7) {
      bloc(n - 11, 0, 3, 6, 0);
      bloc(0, n - 11, 6, 3, 0);
    }

    return { m: m, r: r, n: n };
  }

  /* Pose des bits, deux colonnes à la fois, en serpentant du bas à droite. */
  function poser(t, mots) {
    var n = t.n, bit = 0, total = mots.length * 8;
    function lire() {
      if (bit >= total) return 0;
      var b = (mots[bit >> 3] >>> (7 - (bit & 7))) & 1;
      bit++;
      return b;
    }
    var montant = true;
    for (var col = n - 1; col > 0; col -= 2) {
      if (col === 6) col--;                       // la colonne de cadence ne compte pas
      for (var pas = 0; pas < n; pas++) {
        var ligne = montant ? n - 1 - pas : pas;
        for (var d = 0; d < 2; d++) {
          var x = col - d;
          if (t.r[ligne][x]) continue;
          t.m[ligne][x] = lire();
        }
      }
      montant = !montant;
    }
  }

  var MASQUES = [
    function (i, j) { return (i + j) % 2 === 0; },
    function (i) { return i % 2 === 0; },
    function (i, j) { return j % 3 === 0; },
    function (i, j) { return (i + j) % 3 === 0; },
    function (i, j) { return (Math.floor(i / 2) + Math.floor(j / 3)) % 2 === 0; },
    function (i, j) { return ((i * j) % 2) + ((i * j) % 3) === 0; },
    function (i, j) { return (((i * j) % 2) + ((i * j) % 3)) % 2 === 0; },
    function (i, j) { return (((i + j) % 2) + ((i * j) % 3)) % 2 === 0; }
  ];

  /* Information de format : niveau de correction + masque, protégés par un
     code BCH(15,5), puis brouillés par le motif fixe 101010000010010. */
  function bitsFormat(masque) {
    var donnees = (0x00 << 3) | masque;           // 00 = niveau M
    var v = donnees << 10;
    for (var i = 4; i >= 0; i--) {
      if (v & (1 << (i + 10))) v ^= 0x537 << i;
    }
    return ((donnees << 10) | v) ^ 0x5412;
  }

  /* Information de version, code BCH(18,6). */
  function bitsVersion(version) {
    var v = version << 12;
    for (var i = 5; i >= 0; i--) {
      if (v & (1 << (i + 12))) v ^= 0x1f25 << i;
    }
    return (version << 12) | v;
  }

  function ecrireFormat(m, n, masque) {
    var bits = bitsFormat(masque), i, b;
    /* Colonne 8, de haut en bas (la ligne 6 est celle de la cadence). */
    for (i = 0; i < 15; i++) {
      b = (bits >> i) & 1;
      if (i < 6) m[i][8] = b;
      else if (i < 8) m[i + 1][8] = b;
      else m[n - 15 + i][8] = b;
    }
    /* Ligne 8, de droite à gauche (la colonne 6 est celle de la cadence). */
    for (i = 0; i < 15; i++) {
      b = (bits >> i) & 1;
      if (i < 8) m[8][n - 1 - i] = b;
      else if (i < 9) m[8][15 - i] = b;
      else m[8][14 - i] = b;
    }
    m[n - 8][8] = 1;
  }

  function ecrireVersion(m, n, version) {
    if (version < 7) return;
    var bits = bitsVersion(version);
    for (var i = 0; i < 18; i++) {
      var b = (bits >> i) & 1;
      m[Math.floor(i / 3)][n - 11 + (i % 3)] = b;
      m[n - 11 + (i % 3)][Math.floor(i / 3)] = b;
    }
  }

  /* Les quatre pénalités de la norme : la trame retenue est la moins pénalisée. */
  function penalite(m, n) {
    var score = 0, i, j, k;

    /* 1. Suites de cinq cases ou plus de même teinte. */
    for (i = 0; i < n; i++) {
      for (var sens = 0; sens < 2; sens++) {
        var precedent = -1, suite = 0;
        for (j = 0; j < n; j++) {
          var val = sens ? m[j][i] : m[i][j];
          if (val === precedent) {
            suite++;
            if (suite === 5) score += 3;
            else if (suite > 5) score += 1;
          } else {
            precedent = val;
            suite = 1;
          }
        }
      }
    }

    /* 2. Carrés de 2 x 2 de même teinte. */
    for (i = 0; i < n - 1; i++) {
      for (j = 0; j < n - 1; j++) {
        var a = m[i][j];
        if (a === m[i][j + 1] && a === m[i + 1][j] && a === m[i + 1][j + 1]) score += 3;
      }
    }

    /* 3. Motif 1:1:3:1:1 entouré de quatre cases claires. */
    var motif = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0];
    var motifInverse = [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1];
    for (i = 0; i < n; i++) {
      for (j = 0; j <= n - 11; j++) {
        var okH = true, okV = true, okHi = true, okVi = true;
        for (k = 0; k < 11; k++) {
          if (m[i][j + k] !== motif[k]) okH = false;
          if (m[i][j + k] !== motifInverse[k]) okHi = false;
          if (m[j + k][i] !== motif[k]) okV = false;
          if (m[j + k][i] !== motifInverse[k]) okVi = false;
        }
        if (okH) score += 40;
        if (okHi) score += 40;
        if (okV) score += 40;
        if (okVi) score += 40;
      }
    }

    /* 4. Écart entre la proportion de sombre et la moitié. */
    var sombres = 0;
    for (i = 0; i < n; i++) for (j = 0; j < n; j++) if (m[i][j]) sombres++;
    var pourcent = (sombres * 100) / (n * n);
    score += Math.floor(Math.abs(pourcent - 50) / 5) * 10;

    return score;
  }

  /* Trame finale : tableau de 0 et de 1, sans marge. */
  function qrMatrice(texte) {
    var donnees = octets(texte);
    var v = 1;
    while (v <= 10 && capacite(v) < donnees.length) v++;
    if (v > 10) throw new Error('Contenu trop long pour un QR code de version 10 (' + donnees.length + ' octets).');

    var mots = blocs(codewords(donnees, v), v);
    var base = trame(v);
    poser(base, mots);

    var meilleur = null, meilleurScore = Infinity;
    for (var masque = 0; masque < 8; masque++) {
      var m = base.m.map(function (ligne) { return ligne.slice(); });
      for (var i = 0; i < base.n; i++) {
        for (var j = 0; j < base.n; j++) {
          if (!base.r[i][j] && MASQUES[masque](i, j)) m[i][j] ^= 1;
        }
      }
      ecrireFormat(m, base.n, masque);
      ecrireVersion(m, base.n, v);
      var score = penalite(m, base.n);
      if (score < meilleurScore) { meilleurScore = score; meilleur = m; }
    }
    return meilleur;
  }

  /* SVG du QR code. Le chemin unique garde le fichier léger et net à l'impression. */
  function qrSVG(texte, options) {
    var o = options || {};
    var m = qrMatrice(texte);
    var n = m.length;
    var marge = o.marge === undefined ? 4 : o.marge;      // 4 cases : la « zone calme » de la norme
    var cote = n + marge * 2;
    var chemin = [];
    for (var i = 0; i < n; i++) {
      var j = 0;
      while (j < n) {
        if (!m[i][j]) { j++; continue; }
        var debut = j;
        while (j < n && m[i][j]) j++;
        chemin.push('M' + (debut + marge) + ' ' + (i + marge) + 'h' + (j - debut) + 'v1h-' + (j - debut) + 'z');
      }
    }
    var taille = o.taille ? ' width="' + o.taille + '" height="' + o.taille + '"' : '';
    var fond = o.fond === null ? '' :
      '<rect width="' + cote + '" height="' + cote + '" fill="' + (o.fond || '#fff') + '"/>';
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + cote + ' ' + cote + '"' + taille +
      ' shape-rendering="crispEdges" role="img" aria-label="' + echapper(o.titre || texte) + '">' +
      fond + '<path d="' + chemin.join('') + '" fill="' + (o.couleur || '#0b0c0e') + '"/></svg>';
  }

  /* ======================================================================
     2. Code-barres Code 128 (variante B)
     ====================================================================== */

  var C128 = [
    '212222', '222122', '222221', '121223', '121322', '131222', '122213', '122312',
    '132212', '221213', '221312', '231212', '112232', '122132', '122231', '113222',
    '123122', '123221', '223211', '221132', '221231', '213212', '223112', '312131',
    '311222', '321122', '321221', '312212', '322112', '322211', '212123', '212321',
    '232121', '111323', '131123', '131321', '112313', '132113', '132311', '211313',
    '231113', '231311', '112133', '112331', '132131', '113123', '113321', '133121',
    '313121', '211331', '231131', '213113', '213311', '213131', '311123', '311321',
    '331121', '312113', '312311', '332111', '314111', '221411', '431111', '111224',
    '111422', '121124', '121421', '141122', '141221', '112214', '112412', '122114',
    '122411', '142112', '142211', '241211', '221114', '413111', '241112', '134111',
    '111242', '121142', '121241', '114212', '124112', '124211', '411212', '421112',
    '421211', '212141', '214121', '412121', '111143', '111341', '131141', '114113',
    '114311', '411113', '411311', '113141', '114131', '311141', '411131', '211412',
    '211214', '211232', '2331112'
  ];

  /* Suite des largeurs de barres et d'espaces, départ et clé de contrôle comprises. */
  function code128Largeurs(texte) {
    var s = String(texte);
    var valeurs = [];
    for (var i = 0; i < s.length; i++) {
      var c = s.charCodeAt(i);
      if (c < 32 || c > 126) throw new Error('Caractère hors du Code 128 B : « ' + s[i] + ' ».');
      valeurs.push(c - 32);
    }
    var somme = 104;                               // valeur du départ B
    for (i = 0; i < valeurs.length; i++) somme += valeurs[i] * (i + 1);
    var suite = [104].concat(valeurs, [somme % 103], [106]);
    var largeurs = [];
    for (i = 0; i < suite.length; i++) {
      var motif = C128[suite[i]];
      for (var j = 0; j < motif.length; j++) largeurs.push(parseInt(motif[j], 10));
    }
    return largeurs;                               // barre, espace, barre, espace…
  }

  /* SVG du code-barres. Hauteur et module en unités SVG : l'impression reste nette. */
  function code128SVG(texte, options) {
    var o = options || {};
    var largeurs = code128Largeurs(texte);
    var module = o.module || 2;
    var hauteur = o.hauteur || 70;
    var marge = o.marge === undefined ? 10 : o.marge;
    var total = largeurs.reduce(function (a, b) { return a + b; }, 0);
    var barres = [];
    var x = marge;
    for (var i = 0; i < largeurs.length; i++) {
      var l = largeurs[i] * module;
      if (i % 2 === 0) barres.push('M' + x + ' 0h' + l + 'v' + hauteur + 'h-' + l + 'z');
      x += l;
    }
    var largeurTotale = total * module + marge * 2;
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + largeurTotale + ' ' + hauteur + '"' +
      (o.taille ? ' width="' + o.taille + '"' : '') +
      ' preserveAspectRatio="none" shape-rendering="crispEdges" role="img" aria-label="' +
      echapper(o.titre || texte) + '"><path d="' + barres.join('') +
      '" fill="' + (o.couleur || '#0b0c0e') + '"/></svg>';
  }

  function echapper(t) {
    return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  racine.SES_CODES = {
    qrSVG: qrSVG,
    qrMatrice: qrMatrice,
    code128SVG: code128SVG,
    code128Largeurs: code128Largeurs
  };
})(typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis : this));
