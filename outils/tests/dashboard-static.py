"""Read-only static integrity checks. Run from repository root."""
from pathlib import Path
import ast, subprocess, collections, re, runpy
from html.parser import HTMLParser
for p in Path('assets/js').rglob('*.js'):
    subprocess.run(['node', '--check', str(p)], check=True)
for p in Path('outils').rglob('*.py'):
    ast.parse(p.read_text())
class Scan(HTMLParser):
    def __init__(self):
        super().__init__(); self.ids=[]; self.links=[]
    def handle_starttag(self, tag, attrs):
        d=dict(attrs)
        if d.get('id'): self.ids.append(d['id'])
        for k in ['src','href']:
            if d.get(k): self.links.append(d[k])
html=Path('tableau-de-bord.html').read_text()
s=Scan();s.feed(html)
assert not [i for i,n in collections.Counter(s.ids).items() if n>1]
for u in s.links:
    if u.startswith(('http:','https:','#','data:','tel:','mailto:')):continue
    assert Path(u.split('?')[0].split('#')[0]).exists(),u
assert Path('outils/espace/tableau-de-bord.html').read_text().strip() in html
# Generator is loaded but its main() is NOT called; output stays in memory.
g=runpy.run_path('outils/pages-espace.py',run_name='integrity_test')
page=next(p for p in g['PAGES'] if p['nom']=='tableau-de-bord.html')
assembled=g['assembler'](page)
assert assembled == html, 'La page doit correspondre à ses sources'
assert '<body class="ses-admin-page">' in assembled
assert 'assets/css/ses-dashboard.css?v='+g['VERSION'] in assembled
assert 'assets/js/ses-dashboard.js?v='+g['VERSION'] in assembled
keys=set(re.findall(r'data-t="(dash-[^"]+)"',html))
js=Path('assets/js/ses-dashboard.js').read_text()
for k in re.findall(r"\bt\('([^']+)'\)",js):assert 'dash-'+k in keys,k

# La carte du monde est dessinée deux fois : le fond en pointillés par
# outils/carte-monde.py, les repères de villes par ses-dashboard.js. La
# projection doit rester la même des deux côtés, sinon chaque ville se
# retrouve à côté de sa vraie position sans que rien ne le signale.
carte=Path('outils/carte-monde.py').read_text()
haut,bas=(float(v) for v in re.search(r'CROPE_LAT_HAUT, CROPE_LAT_BAS = ([-\d.]+), ([-\d.]+)',carte).groups())
attendus=re.search(r'\((\d+) - lat\) / (\d+) \* 100',js)
assert attendus, 'formule de projection absente de ses-dashboard.js'
assert (float(attendus.group(1)),float(attendus.group(2)))==(haut,haut-bas),'projections divergentes'
svg=Path('assets/img/ses-carte-monde.svg').read_text()
x,y,largeur,hauteur=(float(v) for v in re.search(r'viewBox="([\d.\- ]+)"',svg).group(1).split())
assert (x,largeur)==(0,720) and abs(y-(90-haut)/150*300)<0.1 and abs(hauteur-(haut-bas)/150*300)<0.1,'cadre du SVG incohérent'
assert f'width="720" height="{hauteur:.0f}"' in js,'la carte posée par le script ne suit pas le SVG'
print('PASS static: JS/Python syntax, unique IDs, links, fragment, generator in memory, literal translation keys, projection de la carte')
