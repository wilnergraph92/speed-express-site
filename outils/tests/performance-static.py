"""Read-only assertions for scoped performance generators and all pages."""
from pathlib import Path
import runpy,re,ast,subprocess
from html.parser import HTMLParser
root=Path('.')
g=runpy.run_path('outils/mise-en-page.py',run_name='test_performance')
duplicate='<html><head><script src="assets/js/ses-anim.js?v=22" defer></script><script src="assets/js/ses-anim.js?v=28" defer></script></head><body></body></html>'
one=g['animations'](duplicate)
assert one.count('assets/js/ses-anim.js')==1
assert g['animations'](one)==one
thumb='<html><body><template id="__bundler_thumbnail"><img src="bad.jpg"></template><p>Conservé</p></body></html>'
assert '__bundler_thumbnail' not in g['retirer_template_bundler'](thumb)
assert '<p>Conservé</p>' in g['retirer_template_bundler'](thumb)
legacy=g['CAMION']
assert '<source media="(min-width: 900px)"' in legacy
assert 'src="data:image/' in legacy and '1280w' in legacy
lazy='<head></head><body><img src="https://images.unsplash.com/x" loading="lazy"></body>'
assert 'rel="preconnect"' not in g['preconnect_images_externes'](lazy)
eager=lazy.replace(' loading="lazy"','')
assert g['preconnect_images_externes'](eager).count('rel="preconnect"')==1
class Scan(HTMLParser):
 def __init__(self):super().__init__();self.imgs=[];self.scripts=[];self.links=[]
 def handle_endtag(self,tag):pass
 def handle_starttag(self,tag,attrs):
  d=dict(attrs)
  if tag=='img':self.imgs.append(d)
  if tag=='script' and 'src' in d:self.scripts.append(d['src'])
  if tag in ('source','link','img'):self.links.append(d)
for p in root.glob('*.html'):
 html=p.read_text();scan=Scan();scan.feed(html)
 assert len([s for s in scan.scripts if 'ses-anim.js' in s])==1,p
 assert len(scan.scripts)==len(set(scan.scripts)),p
 assert not any('lang-dict.js' in s for s in scan.scripts),p
 assert any('lang-switcher.js' in s for s in scan.scripts),(p,'lang-switcher required to load dictionaries')
 assert "dictionnaires_differe" in g and g["dictionnaires_differe"]('<head><script src="assets/js/lang-dict.js?v=28" defer></script></head>').count('script')==0
 assert '__bundler_thumbnail' not in html,p
 for img in scan.imgs:
  if img.get('src','').startswith('https://images.unsplash.com/'):
   assert img.get('referrerpolicy')=='no-referrer',p
   assert Path(img['data-fallback']).exists(),p
 for tag in scan.links:
  for key in ['src','href']:
   u=tag.get(key,'')
   if u.startswith('assets/'):assert Path(u.split('?')[0]).exists(),(p,u)
  for key in ['srcset','imagesrcset']:
   for item in tag.get(key,'').split(','):
    u=item.strip().split(' ')[0]
    if u.startswith('assets/'):assert Path(u).exists(),(p,u)
 for name in ['performance_images','preconnect_images_externes','version_scripts','dictionnaires_differe']:
  assert g[name](html)==html,(p,name,'not idempotent')
for p in root.glob('assets/js/**/*.js'):subprocess.run(['node','--check',str(p)],check=True)
for p in Path('outils').rglob('*.py'):ast.parse(p.read_text())
print('PASS all 28 pages: unique scripts/resources, no thumbnail, remote policies & fallback, existing derivatives, scoped generator idempotence; injected duplicate/template/legacy media fixtures; JS/Python syntax')
