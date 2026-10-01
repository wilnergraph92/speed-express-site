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
tete,pied=g['shell'](); assembled=g['assembler'](page,tete,pied)
assert '<body class="ses-admin-page">' in assembled
assert 'assets/css/ses-dashboard.css?v=28' in assembled
assert 'assets/js/ses-dashboard.js?v=28' in assembled
keys=set(re.findall(r'data-t="(dash-[^"]+)"',html))
js=Path('assets/js/ses-dashboard.js').read_text()
for k in re.findall(r"\bt\('([^']+)'\)",js):assert 'dash-'+k in keys,k
print('PASS static: JS/Python syntax, unique IDs, links, fragment, generator in memory, literal translation keys')
