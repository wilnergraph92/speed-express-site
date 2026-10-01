/* The existing icons already have the correct canvas/crop: lossless re-encoding.
   No unnecessary 512px icon: site has no web-app manifest.
   NODE_PATH=/external/node_modules node outils/optimiser-favicons.cjs */
const sharp=require('sharp'),fs=require('node:fs');
(async()=>{for(const size of [32,180]){
 const file='assets/img/favicon-'+size+'.png';const old=fs.readFileSync(file);
 const metadata=await sharp(old).metadata();if(metadata.width!==size||metadata.height!==size)throw new Error('Unexpected icon dimensions');
 const next=await sharp(old).png({compressionLevel:9,effort:10}).toBuffer();
 if(next.length<old.length)fs.writeFileSync(file,next);
 console.log(size,old.length,fs.statSync(file).size);
}})();
