/* Reproducible derivatives of existing Speed Express images; originals retained.
   Run: NODE_PATH=/path/to/external/node_modules node outils/optimiser-images.cjs
   Requires sharp@0.35.5. No runtime/CDN dependency. */
const sharp = require('sharp'), fs = require('node:fs');
(async function () {
  for (const name of ['ses-truck', 'hero-avion', 'hero-navire']) {
    const file='assets/img/'+name+'.jpg', meta=await sharp(file).metadata();
    for (const width of [480,800,1200,meta.width]) {
      const out='assets/img/'+name+(width===meta.width?'':'-'+width)+'.webp';
      await sharp(file).resize({width,withoutEnlargement:true}).webp({quality:82,effort:6}).toFile(out);
      console.log(out,fs.statSync(out).size);
    }
  }
  // Existing 1280px artwork displayed up to ~600 CSS px; choose by DPR.
  for (const width of [480,800]) {
    const out='assets/img/ses-camion-colis-'+width+'.webp';
    await sharp('assets/img/ses-camion-colis.webp').resize({width}).webp({quality:82,effort:6}).toFile(out);
    console.log(out,fs.statSync(out).size);
  }
})();
