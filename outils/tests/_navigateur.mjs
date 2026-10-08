// Lancer le navigateur des essais « *-browser.mjs ».
// Par défaut, le Chromium de @sparticuz/chromium (un binaire Linux : machines de CI, serveurs) ; avec SES_CHROME, le Chrome ou
// Chromium installé sur le poste (un Mac, par exemple, où le binaire Linux ne démarre pas) :
//   SES_TEST_DEPS=/dossier/avec/playwright SES_CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" node outils/tests/qualite-browser.mjs
// Le navigateur ne change rien à l'isolement : chaque essai coupe lui-même tout ce qui ne vient pas du poste et remplace config.js.
export async function lancerNavigateur(deps, garderProcessusUnique) {
  const {chromium:pw} = await import(deps + '/node_modules/playwright/index.mjs');
  if (process.env.SES_CHROME) return pw.launch({executablePath:process.env.SES_CHROME, headless:true});
  const {default:chromium} = await import(deps + '/node_modules/@sparticuz/chromium/build/index.js');
  const args = garderProcessusUnique ? chromium.args : chromium.args.filter(a => a !== '--single-process');
  return pw.launch({executablePath:await chromium.executablePath(), args, headless:true});
}
