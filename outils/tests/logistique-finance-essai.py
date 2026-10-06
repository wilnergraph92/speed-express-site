#!/usr/bin/env python3
"""Noyau logistique, phase 10 : le moteur financier — sur un vrai PostgreSQL jetable.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-finance-essai.py

Jamais la production. Le cœur de l'épreuve : un MODÈLE DE RÉFÉRENCE écrit ici, en arithmétique décimale, qui refait chaque calcul de prix
(tranches, tarif négocié, volume, remises, surcharges, frais, taxes, devises) ; la base doit donner exactement les mêmes lignes, sur une
grille de plusieurs centaines de cas dont toutes les bornes de tranches. Puis le cycle de vie d'une facture, les paiements (y compris en
autre devise), les avoirs, les remboursements, l'immuabilité, le solde client, les dépenses, la synthèse et le contrôle d'intégrité."""
import itertools
import json
import os
import sys
from decimal import Decimal as D, ROUND_HALF_UP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

N = [0]


class R(str):
    """Fragment SQL brut."""


def ok(c, m):
    if not c:
        raise AssertionError(m)
    N[0] += 1


def jb(obj):
    return R("'%s'::jsonb" % json.dumps(obj, default=str).replace("'", "''"))


def val(v):
    if v is None:
        return 'null'
    if isinstance(v, R):
        return str(v)
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float, D)):
        return str(v)
    return "'%s'" % str(v).replace("'", "''")


def appel(nom, **kw):
    return "select public.%s(%s)" % (nom, ', '.join('%s => %s' % (k, val(v)) for k, v in kw.items()))


def q2(x):
    return x.quantize(D('0.01'), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- la configuration : écrite UNE fois, servie à la base ET au modèle
RATES = [('USD', 'DOP', D('58.5'), '2020-01-01'), ('USD', 'HTG', D('131.25'), '2020-01-01'), ('USD', 'DOP', D('60'), '2026-06-01'), ('USD', 'HTG', D('140'), '2099-01-01')]
CARDS = [
    dict(code='AIR-HT', mode='air', zone='HT', cur='USD', lb=None, brackets=[(0, 5, '3.00', '0', '5'), (5, 20, '2.50', '0', '0'), (20, 100, '2.00', '5', '0'), (100, None, '1.50', '10', '0')]),
    dict(code='SEA-HT', mode='sea', zone='HT', cur='USD', lb=D('10.5'), brackets=[(0, None, '1.20', '0', '15')]),
    dict(code='AIR-DO', mode='air', zone='DO', cur='DOP', lb=None, brackets=[(0, None, '120.00', '0', '500')]),
    dict(code='GND-DO', mode='ground', zone='DO', cur='USD', lb=None, brackets=[(10, None, '1.00', '0', '0')]),
]
SURCH = [
    dict(code='FUEL', kind='PERCENT', value='3', cur=None, flag=None, minw=None, minvol=None, mode=None, zone=None, taxable=True),
    dict(code='DG', kind='FLAT', value='15', cur='USD', flag='DANGEROUS', minw=None, minvol=None, mode=None, zone=None, taxable=True),
    dict(code='OVERSIZE', kind='PER_LB', value='0.25', cur='USD', flag=None, minw='50', minvol=None, mode=None, zone=None, taxable=False),
    dict(code='REMOTE', kind='FLAT', value='600', cur='DOP', flag='REMOTE', minw=None, minvol=None, mode=None, zone='DO', taxable=True),
    dict(code='BULKY', kind='FLAT', value='7.5', cur='USD', flag=None, minw=None, minvol='3', mode='sea', zone=None, taxable=True),
]
RULES = [
    dict(code='NEGO20', kind='RATE_OVERRIDE', value='1.90', cur='USD', cust='A', mode='air', zone='HT', minw='20', prio=5),
    dict(code='NEGO5', kind='RATE_OVERRIDE', value='2.10', cur='USD', cust='A', mode='air', zone='HT', minw='5', prio=10),
    dict(code='DISC10', kind='DISCOUNT_PERCENT', value='10', cur=None, cust='A', mode=None, zone=None, minw='10', prio=50),
    dict(code='DISCFLAT', kind='DISCOUNT_FLAT', value='4', cur='USD', cust=None, mode='sea', zone=None, minw=None, prio=60),
    dict(code='DISCBIG', kind='DISCOUNT_FLAT', value='30', cur='USD', cust='A', mode='sea', zone=None, minw=None, prio=70),
]
TAXES = [
    dict(code='TCA', rate='10', applies='ALL', country='HT'),
    dict(code='DOFRET', rate='18', applies='FREIGHT', country='DO'),
    dict(code='FEETAX', rate='2', applies='SERVICE_FEE', country=None),
    dict(code='SURTAX', rate='5', applies='SURCHARGE', country=None),
]
FEE = ('USD', D('10'))


class RefErr(Exception):
    pass


def conv(a, frm, to, on):
    if frm == to:
        return q2(a)
    best = [x for x in RATES if x[0] == frm and x[1] == to and x[3] <= on]
    if best:
        return q2(a * max(best, key=lambda x: x[3])[2])
    best = [x for x in RATES if x[0] == to and x[1] == frm and x[3] <= on]
    if best:
        return q2(a / max(best, key=lambda x: x[3])[2])
    raise RefErr('taux')


def ref_price(items, cur, cust, on, can_override=False):
    """Le modèle de référence : MÊMES règles que logistics.compute_quote, écrites autrement."""
    lines, bases, ftot, dtot, stot = [], [], D(0), D(0), D(0)
    first_country = None
    for n, it in enumerate(items, 1):
        w = D(str(it['weight_lb'])); vol = D(str(it['volume_ft3'])) if it.get('volume_ft3') is not None else None
        mode, country, flags = it['service_mode'], it['destination_country'], it.get('flags', [])
        first_country = first_country or country
        card = next((c for c in CARDS if c['mode'] == mode and c['zone'] == country), None)
        if card is None:
            raise RefErr('grille')
        chg = max(w, q2(vol * card['lb'])) if card['lb'] is not None and vol is not None else w
        br = next((b for b in card['brackets'] if b[0] <= chg and (b[1] is None or chg < b[1])), None)
        if it.get('rate_override') is not None:
            if not can_override:
                raise RefErr('droit')
            src, rate, code = 'OVERRIDE', D(str(it['rate_override'])), 'OVERRIDE'
        else:
            src = None
        if src is None and br is None:
            raise RefErr('tranche')
        if src == 'OVERRIDE':
            freight = q2(w * rate); chg = w
        else:
            rules = sorted([r for r in RULES if r['kind'] == 'RATE_OVERRIDE' and r['cur'] == card['cur'] and r['cust'] in (None, cust) and r['mode'] in (None, mode)
                            and r['zone'] in (None, country) and (r['minw'] is None or chg >= D(r['minw']))], key=lambda r: r['prio'])
            if rules:
                src, rate, code = 'RULE', D(rules[0]['value']), rules[0]['code']
            else:
                src, rate, code = 'CARD', D(br[2]), card['code']
            fc = max(D(br[4]), q2(D(br[3]) + chg * rate))
            freight = conv(fc, card['cur'], cur, on)
        lines.append(dict(kind='FREIGHT', code=code, amount=freight))
        ftot += freight; run = freight
        for r in sorted([r for r in RULES if r['kind'] != 'RATE_OVERRIDE' and r['cust'] in (None, cust) and r['mode'] in (None, mode) and r['zone'] in (None, country)
                         and (r['minw'] is None or chg >= D(r['minw']))], key=lambda r: r['prio']):
            amt = q2(run * D(r['value']) / 100) if r['kind'] == 'DISCOUNT_PERCENT' else min(run, conv(D(r['value']), r['cur'], cur, on))
            if amt > 0:
                run -= amt; dtot += amt; lines.append(dict(kind='DISCOUNT', code=r['code'], amount=-amt))
        surt = D(0)
        for s in sorted([s for s in SURCH if s['mode'] in (None, mode) and s['zone'] in (None, country) and (s['minw'] is None or chg >= D(s['minw']))
                         and (s['minvol'] is None or (vol or D(0)) >= D(s['minvol'])) and (s['flag'] is None or s['flag'] in flags)], key=lambda s: s['code']):
            amt = (q2(run * D(s['value']) / 100) if s['kind'] == 'PERCENT' else conv(D(s['value']), s['cur'], cur, on) if s['kind'] == 'FLAT'
                   else conv(q2(chg * D(s['value'])), s['cur'], cur, on))
            if amt > 0:
                stot += amt; surt += amt if s['taxable'] else D(0); lines.append(dict(kind='SURCHARGE', code=s['code'], amount=amt))
        bases.append((country, run, surt))
    fee = conv(FEE[1], FEE[0], cur, on)
    if fee > 0:
        lines.append(dict(kind='SERVICE_FEE', code='SERVICE', amount=fee))
    ttot = D(0)
    for t in sorted(TAXES, key=lambda t: t['code']):
        bf = sum((b[1] for b in bases if t['country'] in (None, b[0])), D(0)); bs = sum((b[2] for b in bases if t['country'] in (None, b[0])), D(0))
        feeb = fee if t['country'] in (None, first_country) else D(0)
        base = {'FREIGHT': bf, 'SURCHARGE': bs, 'SERVICE_FEE': feeb, 'ALL': bf + bs + feeb}[t['applies']]
        amt = q2(base * D(t['rate']) / 100)
        if amt > 0:
            ttot += amt; lines.append(dict(kind='TAX', code=t['code'], amount=amt))
    return dict(lines=lines, freight=ftot, discount=dtot, surcharge=stot, subtotal=ftot - dtot + stot, fee=fee, tax=ttot, total=ftot - dtot + stot + fee + ttot)


def main():
    with P.Cluster() as cl:
        B = 'ses'
        q = lambda sql, **kw: cl.un(B, sql, **kw)   # noqa: E731
        P.monter_historique(cl, B)
        for f_ in ('001-modele-de-domaine', '002-retroremplissage', '003-machine-d-etats', '004-entrepot', '005-transport-douane', '006-dernier-kilometre'):
            cl.run(B, P.lire_sql('outils/logistique/%s.sql' % f_))
        # Le caissier : un employé à qui l'on a coché les droits de facturation (et rien d'autre).
        q("update public.clients set droits = array['colis.lire','factures.lire','factures.creer','factures.modifier'] where email = 'client4@essai.test'")
        avant_legacy = P.empreintes_historiques(cl, B)
        cl.run(B, P.lire_sql('outils/logistique/007-finance.sql'))
        compte = lambda: tuple(q('select count(*) from logistics.%s' % t) for t in ('invoice_transition', 'event_type', 'service_fee'))   # noqa: E731
        c1 = compte()
        cl.run(B, P.lire_sql('outils/logistique/007-finance.sql'))
        ok(c1 == compte() and c1[2] == '1', '007 rejouée : aucune ligne en double, un seul frais de service (le seul fait connu : 10 $)')
        ok(avant_legacy == P.empreintes_historiques(cl, B), 'les anciennes tables n\'ont pas bougé d\'un octet')
        q('select logistics.backfill_from_legacy()')
        ok(q("select count(*) from logistics.reconcile_with_legacy()") == '0', 'la réconciliation avec l\'ancien schéma reste à 0 écart')
        ok(q("select count(*) from logistics.invoice where source = 'legacy_backfill'") != '0', 'des factures héritées existent (elles ne doivent pas être touchées)')

        uid = lambda n: q("select id from public.clients where email = 'client%d@essai.test'" % n)   # noqa: E731
        admin, gerant, op, caissier, sansdroit, cli = uid(1), uid(2), uid(3), uid(4), uid(6), uid(9)
        q("insert into logistics.app_user (id, organization_id, role, rights) select '%s', id, 'employee', '{}' from logistics.organization" % sansdroit)
        ok(q("select rights::text from logistics.app_user where id = '%s'" % caissier) == '{colis.lire,factures.lire,factures.creer,factures.modifier}', 'le caissier a exactement les droits de facturation')
        customers = cl.lignes(B, "select id from logistics.customer where auth_user_id is not null order by code limit 3")
        ca, cb, cc = customers[0], customers[1], customers[2]
        ua, ub, uc = (q("select auth_user_id from logistics.customer where id = '%s'" % c) for c in (ca, cb, cc))
        org = q('select id from logistics.organization')
        TODAY = q("select current_date::text")
        YEAR = q("select extract(year from now())::int")

        def rev_tax(devis, devise):
            """Revenu net (hors taxe) et taxe, en dollars, d'un devis : recalculés ICI, ligne par ligne, sans regarder les écritures de la base."""
            cats_ = {}
            for l in devis['calculation']['lines']:
                k = 'FREIGHT' if l['kind'] in ('FREIGHT', 'DISCOUNT') else l['kind']
                cats_[k] = cats_.get(k, D(0)) + l['amount']
            t = cats_.pop('TAX', D(0))
            c_ = (lambda x: x) if devise == 'USD' else (lambda x: q2(x / D('60')))
            return sum((c_(v) for v in cats_.values()), D(0)), c_(t)

        def f(nom, acteur=caissier, **kw):
            code, sortie = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur)
            return json.loads(sortie, parse_float=D) if sortie.startswith(('{', '[')) else sortie

        def fr(nom, etat, msg, acteur=caissier, **kw):
            code, texte = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur, expect_error=True)
            ok(code != 0 and etat in texte, '%s : attendu %s, obtenu : %s' % (msg, etat, texte[-200:].replace('\n', ' ')))

        def refuse(sql, etat, msg):
            code, texte = cl.run(B, sql, expect_error=True)
            ok(code != 0 and etat in texte, '%s : attendu %s, obtenu : %s' % (msg, etat, texte[-200:].replace('\n', ' ')))

        # ============================================================== A. la configuration : droits, validations, immuabilité
        for fn, kw in (('lg_create_pricing_zone', dict(p_code='X', p_name='x', p_country='HT')), ('lg_set_exchange_rate', dict(p_from='USD', p_to='DOP', p_rate=1)),
                       ('lg_create_service_fee', dict(p_code='Y', p_name='y', p_amount=1, p_currency='USD')), ('lg_create_tax', dict(p_code='Z', p_name='z', p_rate_percent=1, p_applies_to='ALL')),
                       ('lg_create_rate_card', dict(p_code='C', p_name='c', p_mode='air', p_zone=R("gen_random_uuid()"), p_currency='USD', p_brackets=jb([dict(min_lb=0, price_per_lb=1)]))),
                       ('lg_create_surcharge', dict(p_code='S', p_name='s', p_kind='FLAT', p_value=1, p_currency='USD')),
                       ('lg_create_pricing_rule', dict(p_code='R', p_name='r', p_kind='DISCOUNT_PERCENT', p_value=1, p_reason='essai'))):
            for who, nom in ((caissier, 'le caissier'), (op, 'un employé sans droit de facturation'), (sansdroit, 'un employé sans aucun droit'), (cli, 'un client')):
                fr(fn, 'LG003', '%s ne peut pas appeler %s' % (nom, fn), acteur=who, **kw)
        zones = {}
        for pays in ('HT', 'DO'):
            zones[pays] = f('lg_create_pricing_zone', acteur=admin, p_code='z-' + pays.lower(), p_name='Zone ' + pays, p_country=pays)
        refuse("insert into logistics.pricing_zone (code, country) values ('DOUBLON', 'HT')", '23505', 'deux zones actives pour le même pays')
        for fr_, to, rate, vf in RATES:
            f('lg_set_exchange_rate', acteur=gerant, p_from=fr_, p_to=to, p_rate=rate, p_valid_from=vf)
        refuse("update logistics.exchange_rate set rate = 1", 'LG004', 'modifier un taux de change')
        refuse("delete from logistics.exchange_rate", 'LG004', 'supprimer un taux de change')
        fr('lg_set_exchange_rate', '23514', 'taux nul', acteur=admin, p_from='USD', p_to='DOP', p_rate=0)
        fr('lg_set_exchange_rate', '23514', 'même devise des deux côtés', acteur=admin, p_from='USD', p_to='USD', p_rate=1)
        fr('lg_set_exchange_rate', '23514', 'devise inconnue', acteur=admin, p_from='EUR', p_to='USD', p_rate=1)
        fr('lg_set_exchange_rate', '23505', 'deux taux pour la même paire et la même date', acteur=admin, p_from='USD', p_to='DOP', p_rate=61, p_valid_from='2026-06-01')
        for c in CARDS:
            f('lg_create_rate_card', acteur=admin, p_code=c['code'], p_name=c['code'], p_mode=c['mode'], p_zone=zones[c['zone']], p_currency=c['cur'], p_lb_per_ft3=c['lb'], p_valid_from='2020-01-01',
              p_brackets=jb([dict(min_lb=b[0], max_lb=b[1], price_per_lb=b[2], flat_fee=b[3], min_charge=b[4]) for b in c['brackets']]))
        ok(q("select count(*) from logistics.weight_bracket") == str(sum(len(c['brackets']) for c in CARDS)), 'toutes les tranches sont enregistrées')
        fr('lg_create_rate_card', 'LG005', 'une grille sans tranche', acteur=admin, p_code='VIDE', p_name='v', p_mode='ground', p_zone=zones['HT'], p_currency='USD', p_brackets=jb([]))
        fr('lg_create_rate_card', 'LG005', 'une deuxième grille active pour le même mode et la même zone', acteur=admin, p_code='AIR-HT2', p_name='x', p_mode='air', p_zone=zones['HT'], p_currency='USD',
           p_valid_from='2025-01-01', p_brackets=jb([dict(min_lb=0, price_per_lb=1)]))
        fr('lg_create_rate_card', 'LG005', 'deux tranches qui se recouvrent', acteur=admin, p_code='CHEVAUCHE', p_name='x', p_mode='ground', p_zone=zones['HT'], p_currency='USD',
           p_brackets=jb([dict(min_lb=0, max_lb=10, price_per_lb=1), dict(min_lb=5, max_lb=20, price_per_lb=1)]))
        ok(q("select count(*) from logistics.rate_card where code = 'CHEVAUCHE'") == '0', 'la grille refusée n\'a rien laissé derrière elle (tout ou rien)')
        fr('lg_create_rate_card', '23514', 'une tranche à l\'envers', acteur=admin, p_code='ENVERS', p_name='x', p_mode='ground', p_zone=zones['HT'], p_currency='USD', p_brackets=jb([dict(min_lb=10, max_lb=5, price_per_lb=1)]))
        fr('lg_create_rate_card', '23514', 'un prix négatif', acteur=admin, p_code='NEG', p_name='x', p_mode='ground', p_zone=zones['HT'], p_currency='USD', p_brackets=jb([dict(min_lb=0, price_per_lb=-1)]))
        refuse("update logistics.rate_card set currency = 'HTG' where code = 'AIR-HT'", 'LG004', 'modifier une grille')
        refuse("update logistics.weight_bracket set price_per_lb = 1", 'LG004', 'modifier une tranche')
        refuse("delete from logistics.weight_bracket", 'LG004', 'supprimer une tranche')
        refuse("delete from logistics.rate_card", 'LG004', 'supprimer une grille')
        for s in SURCH:
            f('lg_create_surcharge', acteur=admin, p_code=s['code'], p_name='Surcharge ' + s['code'], p_kind=s['kind'], p_value=s['value'], p_currency=s['cur'], p_trigger_flag=s['flag'], p_min_weight_lb=s['minw'],
              p_min_volume_ft3=s['minvol'], p_service_mode=s['mode'], p_zone=zones[s['zone']] if s['zone'] else None, p_taxable=s['taxable'], p_valid_from='2020-01-01')
        fr('lg_create_surcharge', '23514', 'un pourcentage avec une devise', acteur=admin, p_code='X1', p_name='x', p_kind='PERCENT', p_value=1, p_currency='USD')
        fr('lg_create_surcharge', '23514', 'un montant fixe sans devise', acteur=admin, p_code='X2', p_name='x', p_kind='FLAT', p_value=1)
        fr('lg_create_surcharge', '23514', 'un pourcentage au-delà de 1000', acteur=admin, p_code='X3', p_name='x', p_kind='PERCENT', p_value=1001)
        for r in RULES:
            f('lg_create_pricing_rule', acteur=admin, p_code=r['code'], p_name='Règle ' + r['code'], p_kind=r['kind'], p_value=r['value'], p_reason='accord commercial d\'essai', p_currency=r['cur'],
              p_customer=ca if r['cust'] == 'A' else None, p_service_mode=r['mode'], p_zone=zones[r['zone']] if r['zone'] else None, p_min_weight_lb=r['minw'], p_priority=r['prio'], p_valid_from='2020-01-01')
        fr('lg_create_pricing_rule', 'LG005', 'une règle sans motif', acteur=admin, p_code='SANSMOTIF', p_name='x', p_kind='DISCOUNT_PERCENT', p_value=5, p_reason=' ')
        fr('lg_create_pricing_rule', '23514', 'une remise de plus de 100 %', acteur=admin, p_code='TROP', p_name='x', p_kind='DISCOUNT_PERCENT', p_value=101, p_reason='x')
        for t in TAXES:
            f('lg_create_tax', acteur=admin, p_code=t['code'], p_name='Taxe ' + t['code'], p_rate_percent=t['rate'], p_applies_to=t['applies'], p_country=t['country'], p_valid_from='2020-01-01')
        fr('lg_create_tax', '23514', 'une taxe de 101 %', acteur=admin, p_code='X', p_name='x', p_rate_percent=101, p_applies_to='ALL')
        refuse("update logistics.tax set rate_percent = 0", 'LG004', 'modifier une taxe')
        refuse("update logistics.service_fee set amount = 0", 'LG004', 'modifier le frais de service')
        refuse("update logistics.surcharge set value = 0", 'LG004', 'modifier une surcharge')
        refuse("update logistics.pricing_rule set value = 0", 'LG004', 'modifier une règle')
        refuse("delete from logistics.tax", 'LG004', 'supprimer une taxe')
        ok(q("select event_type || ':' || count(*) from logistics.domain_event where event_type = 'PricingConfigured' group by event_type") == 'PricingConfigured:%d' % (
            len(RATES) + len(CARDS) + len(SURCH) + len(RULES) + len(TAXES) + 2), 'chaque configuration posée est un événement')
        ok(q("select count(*) from logistics.audit_log where action = 'pricing.configure'") == str(len(RATES) + len(CARDS) + len(SURCH) + len(RULES) + len(TAXES) + 2), '…et une trace d\'audit')

        # ============================================================== B. le calcul : la base contre le modèle de référence, sur une grille
        ON = '2026-07-01'
        pesées = ['0.5', '4.99', '5', '5.01', '12.5', '19.99', '20', '49.99', '50', '99.99', '100', '250.5']
        cas = []
        for w, (mode, pays), cust, cur, flags in itertools.product(pesées, (('air', 'HT'), ('sea', 'HT'), ('air', 'DO')), (None, 'A'), ('USD', 'DOP', 'HTG'), ([], ['DANGEROUS'], ['REMOTE', 'DANGEROUS'])):
            if pays == 'DO' and cur == 'HTG':
                continue   # la grille dominicaine est en pesos : DOP → HTG n'a pas de taux (refus éprouvé plus bas, sans triangulation)
            cas.append((w, mode, pays, cust, cur, flags))
        # Un échantillon déterministe (un cas sur trois) ; TOUTES les bornes de tranches (5, 20, 50, 100) sont gardées pour chaque mode, client, devise et drapeau.
        cas = [c for i, c in enumerate(cas) if i % 3 == 0 or c[0] in ('5', '20', '50', '100')]
        vols = {'sea': '4', 'air': None}
        items_sql, attendus = [], []
        for (w, mode, pays, cust, cur, flags) in cas:
            it = dict(weight_lb=w, service_mode=mode, destination_country=pays, flags=flags)
            if vols[mode]:
                it['volume_ft3'] = vols[mode]
            try:
                att = ref_price([it], cur, cust, ON)
            except RefErr:
                att = None
            attendus.append((it, cur, cust, att))
        sqls = []
        for it, cur, cust, att in attendus:
            sqls.append("select coalesce((select logistics.compute_quote(%s, '%s', '[%s]'::jsonb, date '%s', false)::text), 'x')" % (
                "'%s'" % ca if cust else 'null', cur, json.dumps(it).replace("'", "''"), ON))
        # Les cas sans grille (ground) lèvent une erreur : on les passe un par un seulement s'ils existent (aucun dans cette grille).
        sortie = cl.lignes(B, ';\n'.join(sqls))
        ok(len(sortie) == len(attendus) > 300, 'la grille compte %d cas' % len(attendus))
        ecarts = []
        for (it, cur, cust, att), brut in zip(attendus, sortie):
            r = json.loads(brut, parse_float=D)
            got = [(l['kind'], l['code'], l['amount']) for l in r['lines']]
            exp = [(l['kind'], l['code'], l['amount']) for l in att['lines']]
            if got != exp or r['total'] != att['total'] or r['subtotal'] != att['subtotal'] or r['tax_total'] != att['tax'] or sum((l['amount'] for l in r['lines']), D(0)) != r['total']:
                ecarts.append((it, cur, cust, got, exp))
        ok(not ecarts, 'écarts entre la base et le modèle de référence (%d sur %d) : %s' % (len(ecarts), len(attendus), ecarts[:1]))
        # Les propriétés qui doivent tenir pour TOUS les cas : le total est la somme des lignes arrondies ; rien n'est négatif ; une seule ligne de frais.
        nb_frais = [sum(1 for l in json.loads(b)['lines'] if l['kind'] == 'SERVICE_FEE') for b in sortie]
        ok(set(nb_frais) == {1}, 'une seule ligne de frais de service par devis, dans les %d cas' % len(sortie))
        ok(all(json.loads(b, parse_float=D)['total'] >= 0 for b in sortie), 'aucun total négatif')
        usage = {c['code']: 0 for c in CARDS}
        for b in sortie:
            for l in json.loads(b)['lines']:
                if l['kind'] == 'FREIGHT':
                    usage[l['code']] = usage.get(l['code'], 0) + 1
        ok(all(usage.get(k, 0) > 0 for k in ('AIR-HT', 'SEA-HT', 'AIR-DO', 'NEGO20', 'NEGO5')), 'la grille a exercé les grilles ET les règles de tarif négocié : %s' % usage)
        lignes_vues = {(l['kind'], l['code']) for b in sortie for l in json.loads(b)['lines']}
        ok({('DISCOUNT', 'DISC10'), ('DISCOUNT', 'DISCFLAT'), ('DISCOUNT', 'DISCBIG'), ('SURCHARGE', 'FUEL'), ('SURCHARGE', 'DG'), ('SURCHARGE', 'OVERSIZE'), ('SURCHARGE', 'REMOTE'), ('SURCHARGE', 'BULKY'), ('TAX', 'TCA'), ('TAX', 'DOFRET'), ('TAX', 'FEETAX'), ('TAX', 'SURTAX')} <= lignes_vues,
           'et chaque remise, chaque surcharge, chaque taxe : %s' % sorted(lignes_vues))

        # -- quelques valeurs écrites À LA MAIN (elles ne dépendent pas du modèle)
        un = lambda w, mode='air', pays='HT', cur='USD', cust=None, flags=(), vol=None: json.loads(q(  # noqa: E731
            "select logistics.compute_quote(%s, '%s', '[%s]'::jsonb, date '%s', false)::text" % ("'%s'" % cust if cust else 'null', cur, json.dumps(dict(
                weight_lb=w, service_mode=mode, destination_country=pays, flags=list(flags), **({'volume_ft3': vol} if vol else {}))), ON)), parse_float=D)
        r = un('4')   # tranche [0,5[ : 4 × 3,00 = 12,00 < minimum 5 ? non : 12,00 ; FUEL 3 % = 0,36 ; frais 10 ; taxes : TCA 10 % de (12 + 0,36 + 10) ; FEETAX 2 % de 10 ; SURTAX 5 % de 0,36
        ok([(l['kind'], l['code'], l['amount']) for l in r['lines']] == [('FREIGHT', 'AIR-HT', D('12.00')), ('SURCHARGE', 'FUEL', D('0.36')), ('SERVICE_FEE', 'SERVICE', D('10.00')),
                                                                           ('TAX', 'FEETAX', D('0.20')), ('TAX', 'SURTAX', D('0.02')), ('TAX', 'TCA', D('2.24'))] and r['total'] == D('24.82'),
           'à la main : 4 lb en tranche 1 → 12,00 + 0,36 + 10,00 + taxes 0,20 + 0,02 + 2,24 = 24,82 : %s' % r['total'])
        r = un('1')
        ok(r['lines'][0]['amount'] == D('5.00'), 'à la main : 1 lb → 3,00 mais le MINIMUM de la tranche est 5,00')
        r = un('5')
        ok(r['lines'][0]['amount'] == D('12.50') and r['items'][0]['rate'] == D('2.50'), 'à la main : 5 lb est la borne BASSE de la 2e tranche (2,50/lb → 12,50)')
        r = un('4.99')
        ok(r['lines'][0]['amount'] == D('14.97'), 'à la main : 4,99 lb reste dans la 1re tranche (3,00/lb → 14,97)')
        r = un('20')
        ok(r['lines'][0]['amount'] == D('45.00'), 'à la main : 20 lb → tranche 3 : 5,00 de fixe + 20 × 2,00 = 45,00')
        r = un('100')
        ok(r['lines'][0]['amount'] == D('160.00'), 'à la main : 100 lb → tranche 4 : 10,00 + 100 × 1,50 = 160,00')
        r = un('12', cust=ca)
        ok(r['lines'][0]['code'] == 'NEGO5' and r['lines'][0]['amount'] == D('25.20'), 'à la main : le client négocié paie 12 × 2,10 = 25,20 (règle NEGO5)')
        ok(r['lines'][1]['kind'] == 'DISCOUNT' and r['lines'][1]['amount'] == D('-2.52'), 'à la main : puis 10 % de remise = −2,52')
        r = un('25', cust=ca)
        ok(r['lines'][0]['code'] == 'NEGO20' and r['lines'][0]['amount'] == D('52.50'), 'à la main : deux règles s\'appliquent à 25 lb : la plus PRIORITAIRE (priorité 5) gagne ; la tranche garde son fixe : 5,00 + 25 × 1,90 = 52,50')
        r = un('10', 'sea', vol='2')
        ok(r['items'][0]['chargeable_lb'] == D('21.00') and r['lines'][0]['amount'] == D('25.20'), 'à la main : poids volumétrique : max(10 lb, 2 pi³ × 10,5) = 21 lb → 25,20')
        r = un('3', 'sea', vol='0.1')
        ok(r['lines'][0]['amount'] == D('15.00'), 'à la main : la mer facture au moins 15,00')
        r = un('3', 'sea', vol='0.1', cust=ca)
        ok([(l['code'], l['amount']) for l in r['lines'][:3]] == [('SEA-HT', D('15.00')), ('DISCFLAT', D('-4.00')), ('DISCBIG', D('-11.00'))], 'à la main : une remise plus grande que le fret le ramène à ZÉRO, jamais en dessous : 15,00 − 4,00 − 11,00 (et non 30,00)')
        r = un('12', cur='DOP')
        ok(r['lines'][0]['amount'] == D('1800.00') and r['service_fee'] == D('600.00'), 'à la main : 30,00 USD en pesos au taux de 60 (en vigueur depuis le 1er juin 2026) = 1 800,00 ; frais 10 USD = 600,00')
        ok(un('12', cur='HTG')['service_fee'] == D('1312.50'), 'à la main : frais de service en gourdes (10 × 131,25) = 1 312,50')
        r = json.loads(q("select logistics.compute_quote(null, 'DOP', '[%s]'::jsonb, date '2026-07-01', false)::text" % json.dumps(dict(weight_lb='3', service_mode='air', destination_country='DO')) ), parse_float=D)
        ok(r['service_fee'] == D('600.00'), 'à la main : le taux change le 1er juin 2026 (58,5 → 60) : à la date du devis, 10 USD = 600,00 DOP')
        r = json.loads(q("select logistics.compute_quote(null, 'DOP', '[%s]'::jsonb, date '2026-05-01', false)::text" % json.dumps(dict(weight_lb='3', service_mode='air', destination_country='DO'))), parse_float=D)
        ok(r['service_fee'] == D('585.00'), 'à la main : avant le 1er juin, 10 USD = 585,00 DOP')
        r = json.loads(q("select logistics.compute_quote(null, 'DOP', '[%s]'::jsonb, date '2026-07-01', false)::text" % json.dumps(dict(weight_lb='3', service_mode='air', destination_country='DO'))), parse_float=D)
        ok(r['lines'][0]['amount'] == D('500.00'), 'à la main : 3 lb × 120 DOP = 360 mais le minimum de la grille est 500 DOP')
        r = un('12', flags=['DANGEROUS'])
        ok(any(l['code'] == 'DG' and l['amount'] == D('15.00') for l in r['lines']), 'à la main : le drapeau DANGEROUS ajoute 15,00')
        ok(not any(l['code'] == 'DG' for l in un('12')['lines']), 'à la main : sans le drapeau, pas de surcharge')
        r = un('60', 'air')
        ok(any(l['code'] == 'OVERSIZE' and l['amount'] == D('15.00') for l in r['lines']), 'à la main : surcharge au livre dès 50 lb : 60 × 0,25 = 15,00')
        ok(not any(l['kind'] == 'TAX' and l['code'] == 'SURTAX' and l['amount'] > D('0.5') for l in r['lines']), 'une surcharge NON taxable n\'entre pas dans la base de la taxe sur surcharges')
        ok(any(l['code'] == 'BULKY' for l in un('10', 'sea', vol='3')['lines']) and not any(l['code'] == 'BULKY' for l in un('10', 'sea', vol='2.9')['lines']), 'la surcharge de volume part à 3 pi³ exactement')
        # -- plusieurs colis, une seule fois les frais
        multi = json.loads(q("select logistics.compute_quote('%s', 'USD', '[%s,%s,%s]'::jsonb, date '2026-07-01', false)::text" % (ca, json.dumps(dict(weight_lb='12', service_mode='air', destination_country='HT')),
                     json.dumps(dict(weight_lb='30', service_mode='air', destination_country='HT')), json.dumps(dict(weight_lb='10', volume_ft3='4', service_mode='sea', destination_country='HT')))), parse_float=D)
        ref = ref_price([dict(weight_lb='12', service_mode='air', destination_country='HT'), dict(weight_lb='30', service_mode='air', destination_country='HT'), dict(weight_lb='10', volume_ft3='4', service_mode='sea', destination_country='HT')], 'USD', 'A', ON)
        ok(multi['total'] == ref['total'] and sum(1 for l in multi['lines'] if l['kind'] == 'SERVICE_FEE') == 1, 'un devis de trois colis : UNE seule fois les frais de service (%s)' % multi['total'])
        ok(sum((l['amount'] for l in multi['lines']), D(0)) == multi['total'], 'le total est la somme des lignes arrondies')

        # -- les refus du calcul
        pre = lambda items, cur='USD', cust=None, acteur=caissier: cl.run(B, appel('lg_price_preview', p_customer=cust, p_currency=cur, p_items=jb(items), p_on=ON), role='authenticated', claims=acteur, expect_error=True)   # noqa: E731
        for items, cur, etat, msg in (
            ([dict(weight_lb=0, service_mode='air', destination_country='HT')], 'USD', 'LG005', 'poids nul'),
            ([dict(weight_lb=-3, service_mode='air', destination_country='HT')], 'USD', 'LG005', 'poids négatif'),
            ([dict(service_mode='air', destination_country='HT')], 'USD', 'LG005', 'poids absent'),
            ([dict(weight_lb=5, service_mode='bateau', destination_country='HT')], 'USD', 'LG005', 'mode inconnu'),
            ([dict(weight_lb=5, service_mode='air', destination_country='FR')], 'USD', 'LG005', 'pays inconnu'),
            ([dict(weight_lb=5, service_mode='air', destination_country='US')], 'USD', 'LG005', 'aucune zone tarifaire pour les États-Unis'),
            ([dict(weight_lb=5, service_mode='ground', destination_country='HT')], 'USD', 'LG005', 'aucune grille terrestre pour Haïti'),
            ([dict(weight_lb=5, service_mode='ground', destination_country='DO')], 'USD', 'LG005', 'aucune tranche pour 5 lb (la grille commence à 10)'),
            ([dict(weight_lb=5, service_mode='air', destination_country='HT')], 'EUR', 'LG005', 'devise inconnue'),
            ([], 'USD', 'LG005', 'devis sans colis'),
            ([dict(weight_lb=5, service_mode='air', destination_country='DO')], 'HTG', 'LG005', 'aucun taux DOP → HTG (pas de triangulation)'),
            ([dict(weight_lb=5, service_mode='air', destination_country='HT', rate_override=1.5, override_reason='x')], 'USD', 'LG003', 'imposer un tarif sans être direction'),
        ):
            code, texte = pre(items, cur)
            ok(code != 0 and etat in texte, '%s : attendu %s, obtenu : %s' % (msg, etat, texte[-160:].replace('\n', ' ')))
        code, texte = pre([dict(weight_lb=5, service_mode='air', destination_country='HT')], acteur=op)
        ok(code != 0 and 'LG003' in texte, 'un employé sans droit de facturation ne calcule pas de prix')
        code, texte = cl.run(B, appel('lg_price_preview', p_customer=None, p_currency='USD', p_items=jb([dict(weight_lb=5, service_mode='air', destination_country='HT', rate_override=1.5)]), p_on=ON), role='authenticated', claims=admin, expect_error=True)
        ok(code != 0 and 'LG005' in texte and 'motif' in texte, 'imposer un tarif sans motif')
        code, sortie = cl.run(B, appel('lg_price_preview', p_customer=None, p_currency='USD', p_items=jb([dict(weight_lb='5', service_mode='air', destination_country='HT', rate_override='1.5', override_reason='tarif convenu')]), p_on=ON), role='authenticated', claims=admin)
        r = json.loads(sortie, parse_float=D)
        ok(r['items'][0]['rate_source'] == 'OVERRIDE' and r['lines'][0]['amount'] == D('7.50'), 'la direction impose 1,50 $/lb avec un motif : 7,50 (pas de minimum de tranche)')
        ok(q("select count(*) from logistics.quote") == '0', 'un aperçu n\'enregistre aucun devis')
        # -- le tarif enregistré sur le colis (l'ancien « tarif_lb », en dollars)
        n_p = [0]

        def colis(cust, mode='air', pays='HT', poids='12', tarif='0', verifie=None, dims=None, statut='AT_DESTINATION_HUB'):
            n_p[0] += 1
            d = dims or (None, None, None)
            return q("insert into logistics.parcel (organization_id, tracking_number, public_token, customer_id, destination_country, service_mode, status, status_authority, source, weight_lb, verified_weight_lb, length_in, width_in, height_in, rate_per_lb, declared_value, description, recipient_name) "
                     "values ('%s', 'F-%d', 'tok', '%s', '%s', '%s', '%s', 'core', 'legacy_backfill', %s, %s, %s, %s, %s, %s, 100, 'colis %d', 'Dest') returning id" % (
                         org, n_p[0], cust, pays, mode, statut, poids, verifie or 'null', d[0] or 'null', d[1] or 'null', d[2] or 'null', tarif, n_p[0]))
        pt = colis(ca, poids='12', tarif='1.75')
        r = json.loads(cl.run(B, appel('lg_price_preview', p_customer=ca, p_currency='USD', p_items=jb([dict(parcel_id=pt)]), p_on=ON), role='authenticated', claims=caissier)[1], parse_float=D)
        ok(r['items'][0]['rate_source'] == 'PARCEL' and r['lines'][0]['amount'] == D('21.00'), 'le tarif enregistré sur le colis (1,75 $/lb) l\'emporte : 12 × 1,75 = 21,00')
        r = json.loads(cl.run(B, appel('lg_price_preview', p_customer=ca, p_currency='DOP', p_items=jb([dict(parcel_id=pt)]), p_on=ON), role='authenticated', claims=caissier)[1], parse_float=D)
        ok(r['items'][0]['rate_source'] != 'PARCEL', 'ce tarif est en dollars : un devis en pesos ne l\'utilise pas')
        pv = colis(cb, poids='10', verifie='25')
        r = json.loads(cl.run(B, appel('lg_price_preview', p_customer=cb, p_currency='USD', p_items=jb([dict(parcel_id=pv)]), p_on=ON), role='authenticated', claims=caissier)[1], parse_float=D)
        ok(r['items'][0]['weight_lb'] == D('25.00'), 'le poids VÉRIFIÉ à l\'entrepôt remplace le poids déclaré')
        r = json.loads(cl.run(B, appel('lg_price_preview', p_customer=cb, p_currency='USD', p_items=jb([dict(parcel_id=colis(cb, 'sea', poids='10', dims=(24, 24, 12)))]), p_on=ON), role='authenticated', claims=caissier)[1], parse_float=D)
        ok(r['items'][0]['chargeable_lb'] == D('42.00'), 'le volume du colis (24×24×12 po = 4 pi³) donne 42 lb facturées en mer')
        code, texte = cl.run(B, appel('lg_price_preview', p_customer=ca, p_currency='USD', p_items=jb([dict(parcel_id=pv)]), p_on=ON), role='authenticated', claims=caissier, expect_error=True)
        ok(code != 0 and 'LG005' in texte, 'le colis d\'un AUTRE client ne se facture pas à ce client')

        # ============================================================== C. le devis : figé, validité, annulation
        fr('lg_create_quote', 'LG003', 'un devis sans droit de facturation', acteur=op, p_customer=ca, p_currency='USD', p_items=jb([dict(weight_lb='5', service_mode='air', destination_country='HT')]))
        fr('lg_create_quote', 'LG002', 'un devis pour un client inconnu', p_customer=R("gen_random_uuid()"), p_currency='USD', p_items=jb([dict(weight_lb='5', service_mode='air', destination_country='HT')]))
        fr('lg_create_quote', 'LG005', 'une validité négative', p_customer=ca, p_currency='USD', p_items=jb([dict(weight_lb='5', service_mode='air', destination_country='HT')]), p_valid_days=-1)
        pa1, pa2, pa3 = colis(ca, poids='12'), colis(ca, poids='30'), colis(ca, 'sea', poids='10', dims=(24, 24, 12))
        items_a = [dict(parcel_id=pa1), dict(parcel_id=pa2), dict(parcel_id=pa3)]
        qa = f('lg_create_quote', p_customer=ca, p_currency='USD', p_items=jb(items_a), p_on=TODAY)
        ref_a = ref_price([dict(weight_lb='12', service_mode='air', destination_country='HT'), dict(weight_lb='30', service_mode='air', destination_country='HT'),
                           dict(weight_lb='10', volume_ft3='4', service_mode='sea', destination_country='HT')], 'USD', 'A', TODAY)
        ok(qa['total'] == ref_a['total'] and qa['status'] == 'OFFERED', 'le devis de trois colis donne le total du modèle : %s' % qa['total'])
        ok(qa['number'] == 'QUO-%s-000001' % YEAR, 'numéro de devis : %s' % qa['number'])
        qid = qa['quote_id']
        refuse("update logistics.quote set total = 1 where id = '%s'" % qid, 'LG004', 'modifier le total d\'un devis')
        refuse("update logistics.quote set calculation = '{}' where id = '%s'" % qid, 'LG004', 'modifier le calcul d\'un devis')
        refuse("delete from logistics.quote", 'LG004', 'supprimer un devis')
        # (le devis facturé ne revient pas en arrière : vérifié plus bas, une fois la facture créée)
        # le devis est FIGÉ : on désactive la grille aérienne, le calcul reste
        f('lg_set_pricing_active', acteur=admin, p_kind='rate_card', p_id=q("select id from logistics.rate_card where code = 'AIR-HT'"), p_active=False)
        code, texte = pre([dict(weight_lb=5, service_mode='air', destination_country='HT')], cur='USD')
        ok(code != 0 and 'LG005' in texte, 'grille désactivée : plus de prix pour le fret aérien vers Haïti')
        ok(q("select total::text from logistics.quote where id = '%s'" % qid) == str(qa['total']) and json.loads(q("select calculation::text from logistics.quote where id = '%s'" % qid), parse_float=D)['total'] == qa['total'], 'le devis déjà émis est INCHANGÉ (tarif gelé)')
        f('lg_set_pricing_active', acteur=admin, p_kind='rate_card', p_id=q("select id from logistics.rate_card where code = 'AIR-HT'"), p_active=True)
        fr('lg_set_pricing_active', 'LG003', 'désactiver sans être direction', acteur=caissier, p_kind='tax', p_id=R("gen_random_uuid()"), p_active=False)
        fr('lg_set_pricing_active', 'LG005', 'type de configuration inconnu', acteur=admin, p_kind='factures', p_id=R("gen_random_uuid()"), p_active=False)
        fr('lg_set_pricing_active', 'LG002', 'élément introuvable', acteur=admin, p_kind='tax', p_id=R("gen_random_uuid()"), p_active=False)
        q2c = f('lg_create_quote', p_customer=cb, p_currency='USD', p_items=jb([dict(weight_lb='5', service_mode='air', destination_country='HT')]), p_on=TODAY)
        fr('lg_cancel_quote', 'LG005', 'annuler un devis sans motif', p_quote=q2c['quote_id'], p_reason=' ')
        ok(f('lg_cancel_quote', p_quote=q2c['quote_id'], p_reason='le client renonce')['status'] == 'CANCELLED', 'devis annulé')
        fr('lg_cancel_quote', 'LG004', 'annuler deux fois', p_quote=q2c['quote_id'], p_reason='x')
        fr('lg_invoice_from_quote', 'LG004', 'facturer un devis annulé', p_quote=q2c['quote_id'])
        qold = f('lg_create_quote', p_customer=cb, p_currency='USD', p_items=jb([dict(weight_lb='5', service_mode='air', destination_country='HT')]), p_valid_days=0, p_on='2026-01-10')
        fr('lg_invoice_from_quote', 'LG004', 'facturer un devis expiré', p_quote=qold['quote_id'])
        fr('lg_expire_quotes', 'LG003', 'expirer les devis sans droit', acteur=op)
        ok(f('lg_expire_quotes') == '1', 'un seul devis était périmé : il est marqué « expiré »')
        ok(q("select status from logistics.quote where id = '%s'" % qold['quote_id']) == 'EXPIRED' and f('lg_expire_quotes') == '0', 'et rejouer n\'en expire aucun de plus')

        # ============================================================== D. la facture : brouillon, émission, immuabilité
        fr('lg_invoice_from_quote', 'LG003', 'facturer sans droit', acteur=op, p_quote=qid)
        inv = f('lg_invoice_from_quote', p_quote=qid, p_due_days=30)
        iid = inv['invoice_id']
        ok(inv['status'] == 'DRAFT' and inv['grouped'] is True and inv['total'] == qa['total'], 'FACTURE créée en brouillon, groupée (3 colis, un même client)')
        ok(q("select number from logistics.invoice where id = '%s'" % iid).startswith('DRAFT-'), 'un brouillon porte un numéro PROVISOIRE')
        ok(q("select status from logistics.quote where id = '%s'" % qid) == 'INVOICED', 'le devis est « facturé »')
        refuse("update logistics.quote set status = 'OFFERED' where id = '%s'" % qid, 'LG001', 'un devis facturé ne redevient pas offert')
        fr('lg_invoice_from_quote', 'LG004', 'facturer deux fois le même devis', p_quote=qid)
        lignes = json.loads(q("select jsonb_agg(jsonb_build_object('k', kind, 'c', code, 'a', amount) order by position)::text from logistics.invoice_item where invoice_id = '%s'" % iid), parse_float=D)
        ok([(l['k'], l['c'], l['a']) for l in lignes] == [(l['kind'], l['code'], l['amount']) for l in qa['calculation']['lines']], 'les lignes de la facture reprennent EXACTEMENT celles du devis')
        ok(q("select (select sum(amount) from logistics.invoice_item where invoice_id = '%s') = total from logistics.invoice where id = '%s'" % (iid, iid)) == 't', 'somme des lignes = total')
        ok(q("select count(*) from logistics.invoice_item where invoice_id = '%s' and kind = 'SERVICE_FEE'" % iid) == '1', 'une seule ligne de frais de service sur la facture groupée')
        ok(q("select count(*) from logistics.invoice_item where invoice_id = '%s' and parcel_id is not null and kind = 'FREIGHT'" % iid) == '3', 'une ligne de fret par colis')
        # un autre devis sur les mêmes colis : refusé tant que la facture vit
        qb = f('lg_create_quote', p_customer=ca, p_currency='USD', p_items=jb([dict(parcel_id=pa1)]), p_on=TODAY)
        fr('lg_invoice_from_quote', 'LG005', 'un colis déjà facturé (même en brouillon)', p_quote=qb['quote_id'])
        # le brouillon ne se retouche pas non plus directement
        refuse("update logistics.invoice set total = 1 where id = '%s'" % iid, 'LG004', 'modifier un brouillon directement')
        refuse("update logistics.invoice_item set amount = 1 where invoice_id = '%s'" % iid, 'LG004', 'modifier une ligne de brouillon')
        refuse("insert into logistics.invoice_item (invoice_id, kind, description, amount) values ('%s', 'FREIGHT', 'x', 1)" % iid, 'LG004', 'ajouter une ligne')
        refuse("delete from logistics.invoice_item where invoice_id = '%s'" % iid, 'LG004', 'supprimer une ligne')
        refuse("delete from logistics.invoice where id = '%s'" % iid, 'LG004', 'supprimer une facture')
        refuse("update logistics.invoice set status = 'PAID' where id = '%s'" % iid, 'LG004', 'forcer le statut à la main')
        refuse("insert into logistics.invoice (organization_id, number, customer_id, status, status_authority, source) values ('%s', 'X-1', '%s', 'DRAFT', 'core', 'native')" % (org, ca), 'LG004', 'créer une facture native sans devis')
        fr('lg_issue_invoice', 'LG003', 'émettre sans droit', acteur=op, p_invoice=iid)
        fr('lg_issue_invoice', 'LG005', 'une échéance de plus d\'un an', p_invoice=iid, p_due_days=400)
        fr('lg_record_payment', 'LG004', 'encaisser sur un brouillon', p_invoice=iid, p_amount=1, p_method='CASH')
        fr('lg_issue_credit_note', 'LG004', 'un avoir sur un brouillon', acteur=admin, p_invoice=iid, p_amount=1, p_reason='x')
        em = f('lg_issue_invoice', p_invoice=iid, p_due_days=30)
        ok(em['status'] == 'ISSUED' and em['number'] == 'INV-%s-000001' % YEAR, 'facture ÉMISE, numéro officiel : %s' % em['number'])
        ok(q("select due_date::text from logistics.invoice where id = '%s'" % iid) == q("select (current_date + 30)::text"), 'échéance à 30 jours')
        fr('lg_issue_invoice', 'LG004', 'émettre deux fois', p_invoice=iid)
        # -- figée
        for col, v in (('total', '1'), ('subtotal', '1'), ('tax_total', '1'), ('service_fee', '1'), ('currency', "'DOP'"), ('number', "'X'"), ('customer_id', "'%s'" % cb), ('is_grouped', 'false')):
            refuse("update logistics.invoice set %s = %s where id = '%s'" % (col, v, iid), 'LG004', 'modifier %s d\'une facture émise' % col)
        for col, v in (('paid_amount', '999'), ('credited_amount', '5'), ('refunded_amount', '5'), ('status', "'PAID'"), ('due_date', "current_date + 400")):
            refuse("update logistics.invoice set %s = %s where id = '%s'" % (col, v, iid), 'LG004', 'modifier %s à la main' % col)
        refuse("update logistics.invoice_item set amount = 1 where invoice_id = '%s'" % iid, 'LG004', 'modifier une ligne émise')
        refuse("delete from logistics.invoice_item where invoice_id = '%s'" % iid, 'LG004', 'supprimer une ligne émise')
        refuse("insert into logistics.invoice_item (invoice_id, kind, description, amount) values ('%s', 'FREIGHT', 'x', 1)" % iid, 'LG004', 'ajouter une ligne émise')
        refuse("update logistics.invoice set status_authority = 'legacy' where id = '%s'" % iid, 'LG004', 'rendre une facture du noyau à l\'ancien schéma')
        # -- même avec le drapeau interne ACTIF (un bogue futur dans le moteur), les montants d'une facture émise restent figés
        flag = lambda sql: cl.run(B, "select set_config('logistics.finance_op', 'on', false); %s" % sql, expect_error=True)   # noqa: E731
        for col, v in (('total', '1'), ('subtotal', '1'), ('tax_total', '1'), ('service_fee', '1'), ('currency', "'DOP'"), ('number', "'X'"), ('customer_id', "'%s'" % cb), ('is_grouped', 'false'), ('discount_total', '1')):
            code, texte = flag("update logistics.invoice set %s = %s where id = '%s'" % (col, v, iid))
            ok(code != 0 and 'LG004' in texte and 'finalisée' in texte, 'drapeau actif : modifier %s d\'une facture émise reste refusé : %s' % (col, texte[-120:].replace('\n', ' ')))
        code, texte = flag("update logistics.invoice set status = 'PAID' where id = '%s'" % iid)
        ok(code != 0 and 'LG001' in texte, 'drapeau actif : le statut ne change que par une transition (LG001)')
        code, texte = flag("insert into logistics.invoice_item (invoice_id, kind, description, amount) values ('%s', 'FREIGHT', 'x', 1)" % iid)
        ok(code != 0 and 'LG004' in texte, 'drapeau actif : on n\'ajoute pas de ligne à une facture émise')
        code, texte = flag("delete from logistics.invoice where id = '%s'" % iid)
        ok(code != 0 and 'LG004' in texte, 'drapeau actif : une facture ne se supprime jamais')
        qd = f('lg_create_quote', p_customer=cb, p_currency='USD', p_items=jb([dict(parcel_id=colis(cb, poids='6'))]), p_on=TODAY)
        idd = f('lg_invoice_from_quote', p_quote=qd['quote_id'])['invoice_id']
        code, texte = flag("update logistics.invoice_item set amount = 1 where invoice_id = '%s'" % idd)
        ok(code != 0 and 'LG004' in texte, 'drapeau actif : une ligne ne se MODIFIE jamais, même en brouillon (on la recrée)')
        code, texte = cl.run(B, "begin; alter table logistics.invoice_item disable trigger guard_invoice_item; update logistics.invoice_item set amount = amount + 1 where id = (select id from logistics.invoice_item where invoice_id = '%s' limit 1); "
                             "set role authenticated; select set_config('request.jwt.claim.sub', '%s', true); select public.lg_issue_invoice('%s'); rollback;" % (idd, caissier, idd), expect_error=True)
        ok(code != 0 and 'LG005' in texte and 'totalisent' in texte, 'un brouillon dont les lignes ne font plus le total ne s\'ÉMET pas : %s' % texte[-120:].replace('\n', ' '))
        ok(q("select status from logistics.invoice where id = '%s'" % idd) == 'DRAFT', 'le brouillon est resté brouillon')
        # -- le tarif est gelé avec la facture
        f('lg_set_pricing_active', acteur=admin, p_kind='tax', p_id=q("select id from logistics.tax where code = 'TCA'"), p_active=False)
        ok(q("select total::text from logistics.invoice where id = '%s'" % iid) == str(qa['total']) and q("select (select sum(amount) from logistics.invoice_item where invoice_id = '%s')::text" % iid) == str(qa['total']), 'taxe désactivée après l\'émission : la facture ne bouge pas (tarif gelé)')
        f('lg_set_pricing_active', acteur=admin, p_kind='tax', p_id=q("select id from logistics.tax where code = 'TCA'"), p_active=True)
        # -- revenus reconnus à l'émission
        cats = {}
        for l in qa['calculation']['lines']:
            k = 'FREIGHT' if l['kind'] in ('FREIGHT', 'DISCOUNT') else l['kind']
            cats[k] = cats.get(k, D(0)) + l['amount']
        tax_a = cats.pop('TAX')
        got = {r_.split('|')[0]: (D(r_.split('|')[1]), D(r_.split('|')[2])) for r_ in cl.lignes(B, "select category || '|' || net_amount || '|' || tax_amount from logistics.revenue_entry where invoice_id = '%s'" % iid)}
        ok(got == {**{k: (v, D(0)) for k, v in cats.items()}, 'TAX': (D(0), tax_a)}, 'écritures de revenu à l\'émission : fret, surcharges, frais (hors taxe) et la taxe à part : %s' % got)
        E = dict(rev=sum(cats.values(), D(0)), tax=tax_a, coll=D(0), refd=D(0), net_total_usd=D(0))
        ok(q("select count(*) from logistics.domain_event where aggregate_id = '%s' and event_type in ('InvoiceCreated','InvoiceIssued')" % iid) == '2', 'événements : créée, émise')

        # ============================================================== E. paiements
        tot = qa['total']
        fr('lg_record_payment', 'LG003', 'encaisser sans droit', acteur=op, p_invoice=iid, p_amount=10, p_method='CASH')
        fr('lg_record_payment', 'LG005', 'un montant nul', p_invoice=iid, p_amount=0, p_method='CASH')
        fr('lg_record_payment', 'LG005', 'un montant négatif', p_invoice=iid, p_amount=-5, p_method='CASH')
        fr('lg_record_payment', 'LG005', 'un mode de paiement inconnu', p_invoice=iid, p_amount=5, p_method='TROC')
        fr('lg_record_payment', 'LG005', 'un paiement qui DÉPASSE le solde', p_invoice=iid, p_amount=tot + D('0.01'), p_method='CASH')
        ok(q("select paid_amount::text from logistics.invoice where id = '%s'" % iid) == '0.00', 'les refus n\'ont rien encaissé')
        p1 = f('lg_record_payment', p_invoice=iid, p_amount='100', p_method='CASH', p_reference='reçu 001', p_idempotency_key='pay-1')
        ok(p1['invoice_status'] == 'PARTIALLY_PAID' and p1['balance'] == tot - 100, 'paiement partiel : PARTIELLEMENT PAYÉE, solde %s' % p1['balance'])
        p1b = f('lg_record_payment', p_invoice=iid, p_amount='100', p_method='CASH', p_reference='reçu 001', p_idempotency_key='pay-1')
        ok(p1b['replayed'] is True and q("select count(*) from logistics.payment where invoice_id = '%s'" % iid) == '1', 'même clé rejouée : un seul paiement')
        fr('lg_record_payment', 'LG006', 'la même clé pour une AUTRE demande', p_invoice=iid, p_amount='50', p_method='CASH', p_reference='reçu 001', p_idempotency_key='pay-1')
        ok(q("select number from logistics.payment where id = '%s'" % p1['payment_id']) == 'PAY-%s-000001' % YEAR, 'numéro de paiement')
        E['coll'] += D(100)
        p2 = f('lg_record_payment', p_invoice=iid, p_amount=tot - 100, p_method='TRANSFER', p_reference='virement 7')
        ok(p2['invoice_status'] == 'PAID' and p2['balance'] == 0, 'le solde est payé : PAYÉE')
        E['coll'] += tot - 100
        ok(q("select paid_at is not null from logistics.invoice where id = '%s'" % iid) == 't', 'date de paiement posée')
        fr('lg_record_payment', 'LG004', 'encaisser sur une facture payée', p_invoice=iid, p_amount='1', p_method='CASH')
        # -- avoir puis remboursement : la seule façon de rendre de l'argent
        fr('lg_refund_payment', 'LG003', 'rembourser sans être direction', acteur=caissier, p_payment=p2['payment_id'], p_amount=5, p_reason='x')
        fr('lg_refund_payment', 'LG005', 'rembourser une facture VALABLE (rien n\'a été payé en trop)', acteur=admin, p_payment=p2['payment_id'], p_amount='5', p_reason='geste commercial')
        fr('lg_issue_credit_note', 'LG003', 'un avoir sans être direction', acteur=caissier, p_invoice=iid, p_amount=5, p_reason='x')
        fr('lg_issue_credit_note', 'LG005', 'un avoir sans motif', acteur=admin, p_invoice=iid, p_amount=5, p_reason='  ')
        fr('lg_issue_credit_note', 'LG005', 'un avoir plus grand que la facture', acteur=admin, p_invoice=iid, p_amount=tot + 1, p_reason='x')
        fr('lg_issue_credit_note', 'LG005', 'un avoir nul', acteur=admin, p_invoice=iid, p_amount=0, p_reason='x')
        cr1 = f('lg_issue_credit_note', acteur=admin, p_invoice=iid, p_amount='33.33', p_reason='colis arrivé abîmé : remise de 33,33')
        ok(cr1['net_amount'] + cr1['tax_amount'] == D('33.33') and cr1['invoice_status'] == 'PAID' and cr1['balance'] == D('-33.33'), 'avoir de 33,33 : réparti en net + taxe, facture toujours PAYÉE, solde −33,33 (excédent à rendre)')
        tax_part = q2(D('33.33') * tax_a / tot)
        ok(cr1['tax_amount'] == tax_part, 'la taxe de l\'avoir est proportionnelle : %s' % tax_part)
        E['rev'] -= cr1['net_amount']; E['tax'] -= cr1['tax_amount']
        fr('lg_refund_payment', 'LG005', 'rembourser plus que l\'excédent (33,33)', acteur=admin, p_payment=p2['payment_id'], p_amount='33.34', p_reason='x')
        fr('lg_refund_payment', 'LG005', 'rembourser sans motif', acteur=admin, p_payment=p2['payment_id'], p_amount='10', p_reason=' ')
        rf1 = f('lg_refund_payment', acteur=admin, p_payment=p2['payment_id'], p_amount='20', p_reason='remboursement partiel de l\'avoir', p_method='CASH')
        ok(rf1['invoice_status'] == 'PAID', 'remboursement partiel : la facture reste payée')
        E['refd'] += D(20)
        ok(q("select number from logistics.refund where id = '%s'" % rf1['refund_id']) == 'REF-%s-000001' % YEAR, 'numéro de remboursement')
        # -- renversement total : avoir du reste puis remboursement du reste
        reste = tot - D('33.33')
        cr2 = f('lg_issue_credit_note', acteur=gerant, p_invoice=iid, p_amount=reste, p_reason='perte du colis : facture annulée par avoir')
        ok(cr2['tax_amount'] == tax_a - cr1['tax_amount'] and cr2['net_amount'] + cr1['net_amount'] == sum(cats.values(), D(0)), 'le DERNIER avoir reprend exactement la taxe restante : aucun centime ne reste')
        E['rev'] -= cr2['net_amount']; E['tax'] -= cr2['tax_amount']
        ok(cr2['invoice_status'] == 'PAID' and cr2['balance'] == -(tot - D('20')), 'crédité en totalité mais l\'argent est encore là : PAYÉE en attente du remboursement')
        fr('lg_issue_credit_note', 'LG005', 'un avoir de plus : il ne reste rien à créditer', acteur=admin, p_invoice=iid, p_amount='0.01', p_reason='x')
        fr('lg_refund_payment', 'LG005', 'rembourser plus que ce qui reste sur ce paiement', acteur=admin, p_payment=p2['payment_id'], p_amount=tot - 100 - D('20') + D('0.01'), p_reason='x')
        rf2 = f('lg_refund_payment', acteur=admin, p_payment=p2['payment_id'], p_amount=tot - 100 - D('20'), p_reason='solde du paiement 2', p_method='TRANSFER')
        E['refd'] += tot - 100 - D('20')
        ok(rf2['invoice_status'] == 'PAID', 'le solde du paiement 2 est rendu ; reste le paiement 1')
        rf3 = f('lg_refund_payment', acteur=admin, p_payment=p1['payment_id'], p_amount='100', p_reason='solde du paiement 1', p_method='CASH')
        E['refd'] += D(100)
        ok(rf3['invoice_status'] == 'REFUNDED' and q("select status from logistics.invoice where id = '%s'" % iid) == 'REFUNDED', 'tout est rendu et tout est crédité : REMBOURSÉE (terminal)')
        ok(q("select credited_amount = total and paid_amount = refunded_amount from logistics.invoice where id = '%s'" % iid) == 't', 'avoirs = total ; remboursé = payé')
        ok(q("select coalesce(sum(net_amount),0) || '/' || coalesce(sum(tax_amount),0) from logistics.revenue_entry where invoice_id = '%s'" % iid) == '0.00/0.00', 'le revenu net ET la taxe de cette facture reviennent à zéro')
        fr('lg_record_payment', 'LG004', 'encaisser sur une facture remboursée', p_invoice=iid, p_amount='1', p_method='CASH')
        fr('lg_issue_credit_note', 'LG004', 'un avoir sur une facture remboursée', acteur=admin, p_invoice=iid, p_amount='1', p_reason='x')
        # les colis d'une facture remboursée se refacturent
        qr = f('lg_create_quote', p_customer=ca, p_currency='USD', p_items=jb([dict(parcel_id=pa1)]), p_on=TODAY)
        ok(f('lg_invoice_from_quote', p_quote=qr['quote_id'])['status'] == 'DRAFT', 'le colis d\'une vente renversée peut être refacturé')
        ok(f('lg_cancel_invoice', p_invoice=q("select id from logistics.invoice where quote_id = '%s'" % qr['quote_id']), p_reason='essai')['status'] == 'CANCELLED', 'un brouillon s\'annule (droit de facturation suffit)')
        # le brouillon annulé libère ses colis ; les revenus de la facture remboursée ne comptent plus
        ok(E['rev'] == 0 and E['tax'] == 0, 'le cumul indépendant du test : une vente émise puis entièrement créditée ne laisse AUCUN centime de revenu ni de taxe')
        # ============================================================== F. annulations, retard, toutes les transitions
        def facture(cust, items, cur='USD', jours=30, emettre=True, on=TODAY):
            qq = f('lg_create_quote', p_customer=cust, p_currency=cur, p_items=jb(items), p_on=on)
            r_ = f('lg_invoice_from_quote', p_quote=qq['quote_id'], p_due_days=jours, p_issue=emettre)
            if emettre:
                net_, tx_ = rev_tax(qq, cur); E['rev'] += net_; E['tax'] += tx_
            return r_['invoice_id'], qq
        # ISSUED → CANCELLED (direction, aucun paiement)
        ic, qc = facture(cb, [dict(parcel_id=colis(cb, poids='8'))])
        fr('lg_cancel_invoice', 'LG005', 'annuler sans motif', acteur=admin, p_invoice=ic, p_reason=' ')
        fr('lg_cancel_invoice', 'LG003', 'annuler une facture ÉMISE sans être direction', acteur=caissier, p_invoice=ic, p_reason='erreur')
        ok(f('lg_cancel_invoice', acteur=admin, p_invoice=ic, p_reason='erreur de saisie')['status'] == 'CANCELLED', 'facture émise et impayée annulée par la direction')
        net_, tx_ = rev_tax(qc, 'USD'); E['rev'] -= net_; E['tax'] -= tx_
        ok(q("select coalesce(sum(net_amount),0) || '/' || coalesce(sum(tax_amount),0) from logistics.revenue_entry where invoice_id = '%s'" % ic) == '0.00/0.00' and q("select count(*) from logistics.revenue_entry where invoice_id = '%s' and category = 'CANCELLATION'" % ic) == '1', 'son revenu est inversé par une écriture négative')
        fr('lg_cancel_invoice', 'LG004', 'annuler une facture déjà annulée', acteur=admin, p_invoice=ic, p_reason='x')
        # ISSUED → PAID direct (paiement du total en une fois)
        ip, qp = facture(cb, [dict(parcel_id=colis(cb, poids='8'))])
        ok(f('lg_record_payment', p_invoice=ip, p_amount=qp['total'], p_method='CARD')['invoice_status'] == 'PAID', 'paiement du total en une fois : ISSUED → PAID')
        E['coll'] += qp['total']
        # ISSUED → OVERDUE, PARTIALLY_PAID → OVERDUE, OVERDUE → PAID, OVERDUE → CANCELLED
        io1, qo1 = facture(cb, [dict(parcel_id=colis(cb, poids='9'))], jours=10)
        io2, qo2 = facture(cb, [dict(parcel_id=colis(cb, poids='9.5'))], jours=10)
        io3, qo3 = facture(cb, [dict(parcel_id=colis(cb, poids='11'))], jours=10)
        io4, qo4 = facture(cb, [dict(parcel_id=colis(cb, poids='13'))], jours=90)
        f('lg_record_payment', p_invoice=io2, p_amount='5', p_method='CASH'); E['coll'] += D(5)
        fr('lg_mark_overdue', 'LG003', 'marquer les retards sans droit', acteur=op, p_date='2099-01-01')
        r = f('lg_mark_overdue', p_date=q("select (current_date + 11)::text"))
        ok(r['marked'] == 3 and q("select status from logistics.invoice where id = '%s'" % io1) == 'OVERDUE' and q("select status from logistics.invoice where id = '%s'" % io2) == 'OVERDUE', 'trois factures en retard (ISSUED → OVERDUE et PARTIALLY_PAID → OVERDUE)')
        ok(q("select status from logistics.invoice where id = '%s'" % io4) == 'ISSUED' and q("select status from logistics.invoice where id = '%s'" % ip) == 'PAID', 'une facture non échue et une facture payée ne sont pas touchées')
        ok(f('lg_mark_overdue', p_date=q("select (current_date + 11)::text"))['marked'] == 0, 'rejouer ne change rien')
        ib5, qb5 = facture(cb, [dict(parcel_id=colis(cb, poids='7'))], jours=20)
        ok(f('lg_mark_overdue', p_date=q("select (current_date + 20)::text"))['marked'] == 0, 'le jour même de l\'échéance, la facture n\'est pas encore en retard')
        ok(f('lg_mark_overdue', p_date=q("select (current_date + 21)::text"))['marked'] == 1 and q("select status from logistics.invoice where id = '%s'" % ib5) == 'OVERDUE', 'le lendemain, elle l\'est')
        iz, qz = facture(cb, [dict(parcel_id=colis(cb, poids='5.5'))], jours=0)
        ok(f('lg_record_payment', p_invoice=iz, p_amount='1', p_method='CASH')['invoice_status'] == 'PARTIALLY_PAID', 'une facture dont l\'échéance est AUJOURD\'HUI n\'est pas en retard : un paiement partiel la laisse « partiellement payée »')
        E['coll'] += D(1)
        ok(f('lg_record_payment', p_invoice=io2, p_amount='1', p_method='CASH')['invoice_status'] == 'OVERDUE', 'un paiement partiel ne sort pas une facture du retard'); E['coll'] += D(1)
        ok(f('lg_record_payment', p_invoice=io1, p_amount=qo1['total'], p_method='CASH')['invoice_status'] == 'PAID', 'OVERDUE → PAID'); E['coll'] += qo1['total']
        ok(f('lg_cancel_invoice', acteur=admin, p_invoice=io3, p_reason='client introuvable')['status'] == 'CANCELLED', 'OVERDUE → CANCELLED')
        net_, tx_ = rev_tax(qo3, 'USD'); E['rev'] -= net_; E['tax'] -= tx_
        fr('lg_cancel_invoice', 'LG004', 'annuler une facture partiellement payée', acteur=admin, p_invoice=io2, p_reason='x')
        # ISSUED → CANCELLED par un avoir total (rien n'a été payé)
        ia, qa2 = facture(cb, [dict(parcel_id=colis(cb, poids='14'))])
        cra = f('lg_issue_credit_note', acteur=admin, p_invoice=ia, p_amount=qa2['total'], p_reason='doublon')
        ok(cra['invoice_status'] == 'CANCELLED', 'avoir total sur une facture impayée : elle s\'ANNULE')
        E['rev'] -= cra['net_amount']; E['tax'] -= cra['tax_amount']
        ok(q("select coalesce(sum(net_amount),0) || '/' || coalesce(sum(tax_amount),0) from logistics.revenue_entry where invoice_id = '%s'" % ia) == '0.00/0.00', 'et son revenu revient à zéro')
        # PARTIALLY_PAID → PAID, par un avoir cette fois
        ib, qb2 = facture(cb, [dict(parcel_id=colis(cb, poids='15'))])
        f('lg_record_payment', p_invoice=ib, p_amount='10', p_method='CASH'); E['coll'] += D(10)
        crb = f('lg_issue_credit_note', acteur=admin, p_invoice=ib, p_amount=qb2['total'] - 10, p_reason='remise commerciale')
        ok(crb['invoice_status'] == 'PAID', 'PARTIALLY_PAID → PAID par un avoir qui couvre le solde')
        E['rev'] -= crb['net_amount']; E['tax'] -= crb['tax_amount']
        # -- un renversement en TROIS avoirs : arrondis séparément, leurs taxes dériveraient d'un centime ; le dernier avoir doit rattraper
        w3 = None
        for w in range(6, 60):
            ref3 = ref_price([dict(weight_lb=str(w), service_mode='air', destination_country='HT')], 'USD', None, TODAY)
            t3, x3 = ref3['total'], ref3['tax']
            c1_ = q2(t3 / 3); c2_ = q2(t3 / 3); c3_ = t3 - c1_ - c2_
            if q2(c1_ * x3 / t3) + q2(c2_ * x3 / t3) + q2(c3_ * x3 / t3) != x3:
                w3 = w
                break
        ok(w3 is not None, 'il existe un cas où trois avoirs arrondis séparément DÉRIVERAIENT d\'un centime (facture de %s lb : total %s, taxes %s)' % (w3, t3, x3))
        id3, q3 = facture(cb, [dict(parcel_id=colis(cb, poids=str(w3)))])
        ok(q3['total'] == t3 and q3['calculation']['tax_total'] == x3, 'la facture de ce cas concorde avec le modèle')
        pay3 = f('lg_record_payment', p_invoice=id3, p_amount=t3, p_method='CASH'); E['coll'] += t3
        parts = []
        for montant in (c1_, c2_, c3_):
            r3 = f('lg_issue_credit_note', acteur=admin, p_invoice=id3, p_amount=montant, p_reason='renversement en trois avoirs')
            parts.append(r3); E['rev'] -= r3['net_amount']; E['tax'] -= r3['tax_amount']
        ok(sum((p_['tax_amount'] for p_ in parts), D(0)) == x3, 'la taxe des trois avoirs fait EXACTEMENT la taxe de la facture (%s) : le dernier rattrape la dérive' % x3)
        ok(sum((p_['net_amount'] for p_ in parts), D(0)) == t3 - x3, 'et le net aussi : plus aucun centime de revenu ne reste')
        ok(f('lg_refund_payment', acteur=admin, p_payment=pay3['payment_id'], p_amount=t3, p_reason='renversement total')['invoice_status'] == 'REFUNDED', 'trois avoirs puis le remboursement : REMBOURSÉE'); E['refd'] += t3
        vues = q("select string_agg(f || '>' || t, ',' order by f, t) from (select distinct coalesce(from_status, '-') f, to_status t from logistics.invoice_status_history where from_status is not null) x")
        ok(vues == 'DRAFT>CANCELLED,DRAFT>ISSUED,ISSUED>CANCELLED,ISSUED>OVERDUE,ISSUED>PAID,ISSUED>PARTIALLY_PAID,OVERDUE>CANCELLED,OVERDUE>PAID,PAID>REFUNDED,PARTIALLY_PAID>OVERDUE,PARTIALLY_PAID>PAID',
           'les ONZE transitions autorisées ont toutes été empruntées : %s' % vues)
        # les transitions interdites sont refusées par la machine elle-même
        mv = lambda i, to: cl.run(B, "select logistics.move_invoice('%s', '%s', null, gen_random_uuid())" % (i, to), expect_error=True)   # noqa: E731
        for i_, to, msg in ((iid, 'ISSUED', 'REFUNDED → ISSUED'), (iid, 'PAID', 'REFUNDED → PAID'), (ic, 'ISSUED', 'CANCELLED → ISSUED'), (ip, 'ISSUED', 'PAID → ISSUED'), (ip, 'PARTIALLY_PAID', 'PAID → PARTIALLY_PAID'),
                            (ip, 'OVERDUE', 'PAID → OVERDUE'), (io4, 'DRAFT', 'ISSUED → DRAFT'), (io4, 'REFUNDED', 'ISSUED → REFUNDED'), (io2, 'ISSUED', 'OVERDUE → ISSUED'), (io2, 'PARTIALLY_PAID', 'OVERDUE → PARTIALLY_PAID')):
            code, texte = mv(i_, to)
            ok(code != 0 and 'LG001' in texte, 'transition interdite %s : %s' % (msg, texte[-120:].replace('\n', ' ')))
        ok(q("select count(*) from logistics.invoice_transition") == '11', 'la machine de la facture compte 11 transitions')

        # ============================================================== G. plusieurs devises
        ipeso, qpeso = facture(cb, [dict(weight_lb='7', service_mode='air', destination_country='DO')], cur='DOP')
        ok(q("select currency from logistics.invoice where id = '%s'" % ipeso) == 'DOP', 'une facture en pesos')
        ref_dop = ref_price([dict(weight_lb='7', service_mode='air', destination_country='DO')], 'DOP', None, TODAY)
        ok(qpeso['total'] == ref_dop['total'], 'son total est celui du modèle (%s DOP)' % qpeso['total'])
        fr('lg_record_payment', 'LG005', 'payer des pesos en gourdes sans taux DOP → HTG', p_invoice=ipeso, p_amount='1000', p_method='CASH', p_currency='HTG')
        f('lg_set_exchange_rate', acteur=admin, p_from='DOP', p_to='HTG', p_rate='2.25', p_valid_from='2026-01-01')
        pp = f('lg_record_payment', p_invoice=ipeso, p_amount='450', p_method='MOBILE_MONEY', p_currency='HTG', p_reference='MonCash')
        ok(pp['amount'] == D('200.00'), 'à la main : 450 HTG au taux DOP→HTG de 2,25 = 200,00 DOP imputés (%s)' % pp['amount'])
        ligne_p = q("select tendered_amount || ' ' || tendered_currency || ' → ' || amount || ' ' || currency || ' (' || base_amount_usd || ' USD, taux ' || rate_used || ')' from logistics.payment where id = '%s'" % pp['payment_id'])
        ok(ligne_p.startswith('450.00 HTG → 200.00 DOP (3.33 USD'), 'le paiement garde ce qui a été remis, ce qui est imputé, l\'équivalent en dollars et le taux : %s' % ligne_p)
        E['coll'] += q2(D('200') / D('60'))
        ok(pp['balance'] == qpeso['total'] - 200, 'solde en pesos')
        # ============================================================== H. les factures héritées ne sont pas touchées
        leg = q("select id from logistics.invoice where source = 'legacy_backfill' and status <> 'PAID' limit 1")
        for fn, kw in (('lg_record_payment', dict(p_invoice=leg, p_amount=1, p_method='CASH')), ('lg_issue_invoice', dict(p_invoice=leg)), ('lg_cancel_invoice', dict(p_invoice=leg, p_reason='x'))):
            fr(fn, 'LG004', '%s sur une facture héritée' % fn, acteur=admin, **kw)
        fr('lg_issue_credit_note', 'LG004', 'un avoir sur une facture héritée', acteur=admin, p_invoice=leg, p_amount=1, p_reason='x')
        refuse("update logistics.invoice set status_authority = 'core' where id = '%s'" % leg, 'LG004', 'faire reprendre une facture héritée par le moteur')
        ok(q("update logistics.invoice set note = note where id = '%s' returning 'ok'" % leg) == 'ok', 'le rattrapage de l\'ancien schéma peut toujours écrire sur une facture héritée')
        ok(q("select count(*) from logistics.invoice where source = 'legacy_backfill' and (credited_amount <> 0 or refunded_amount <> 0)") == '0', 'aucune facture héritée n\'a d\'avoir ni de remboursement')
        ok(q("select count(*) from logistics.reconcile_finance() where entity = 'invoice' and id in (select id::text from logistics.invoice where source = 'legacy_backfill')") == '0', 'le contrôle ne signale aucune facture héritée')

        # ============================================================== I. le solde client et la lecture par le client
        for c_, nom in ((ca, 'A'), (cb, 'B')):
            att = {r_.split('|')[0]: D(r_.split('|')[1]) for r_ in cl.lignes(B, "select currency || '|' || sum((total - credited_amount) - (paid_amount - refunded_amount)) from logistics.invoice where customer_id = '%s' and status not in ('DRAFT','CANCELLED') group by currency" % c_)}
            sol = {b['currency']: b['balance'] for b in f('lg_customer_balance', p_customer=c_)}
            ok(att == sol, 'solde du client %s (par devise) : la vue concorde avec le calcul direct : %s' % (nom, sol))
        sol_b = {b['currency']: b['balance'] for b in f('lg_customer_balance', p_customer=cb)}
        ok(sol_b['DOP'] == qpeso['total'] - 200, 'solde en pesos du client B')
        usd_b = [b for b in f('lg_customer_balance', p_customer=cb) if b['currency'] == 'USD'][0]
        ok(usd_b['invoices'] == int(q("select count(*) from logistics.invoice where customer_id = '%s' and currency = 'USD' and status not in ('DRAFT','CANCELLED')" % cb))
           and usd_b['invoices'] < int(q("select count(*) from logistics.invoice where customer_id = '%s' and currency = 'USD'" % cb)), 'le solde ne compte ni les brouillons ni les factures annulées (%d sur %s)' % (usd_b['invoices'], q("select count(*) from logistics.invoice where customer_id = '%s' and currency = 'USD'" % cb)))
        ok(q("select (total - credited_amount) - (paid_amount - refunded_amount) from logistics.invoice where id = '%s'" % iid) == '0.00', 'la facture remboursée du client A pèse 0 dans son solde (les factures héritées de ce client, elles, y figurent aussi)')
        ok(f('lg_customer_balance', p_customer=ca)[0]['invoices'] == int(q("select count(*) from logistics.invoice where customer_id = '%s' and status not in ('DRAFT','CANCELLED') and currency = 'USD'" % ca)), 'le décompte des factures du solde (héritées incluses)')
        fr('lg_customer_balance', 'LG003', 'le solde d\'un client demandé sans droit de lecture', acteur=op, p_customer=ca)
        mine = f('lg_my_invoices', acteur=ub)
        ok(len(mine) > 0 and all(i_['status'] != 'DRAFT' for i_ in mine) and q("select number from logistics.invoice where id = '%s'" % idd) not in {i_['number'] for i_ in mine}, 'le client B voit ses factures émises, jamais un brouillon (il en existe un à son nom)')
        ok(set(i_['number'] for i_ in mine) <= set(cl.lignes(B, "select number from logistics.invoice where customer_id = '%s'" % cb)), 'et seulement les siennes')
        ok(f('lg_my_invoices', acteur=ua) != mine and all(i_['number'] in cl.lignes(B, "select number from logistics.invoice where customer_id = '%s'" % ca) for i_ in f('lg_my_invoices', acteur=ua)), 'le client A voit les siennes')
        ok(all(len(i_['items']) > 0 for i_ in mine), 'chaque facture montre ses lignes au client')
        vues_c = {i_['number'] for i_ in f('lg_my_invoices', acteur=uc)}
        ok(vues_c <= set(cl.lignes(B, "select number from logistics.invoice where customer_id = '%s'" % cc)) and not vues_c & set(cl.lignes(B, "select number from logistics.invoice where customer_id in ('%s','%s')" % (ca, cb))),
           'un troisième client ne voit RIEN des factures des deux autres (seulement les siennes héritées : %d)' % len(vues_c))
        code, texte = cl.run(B, appel('lg_my_invoices'), role='authenticated', expect_error=True)
        ok(code != 0 and '42501' in texte, 'sans connexion : refusé')
        mb = f('lg_my_balance', acteur=ub)
        ok({b['currency']: b['balance'] for b in mb} == sol_b, 'le client voit son propre solde, le même que celui du personnel')
        d = f('lg_invoice_detail', p_invoice=ip)
        ok(d['invoice']['status'] == 'PAID' and len(d['items']) > 0 and len(d['payments']) == 1 and d['balance'] == 0 and [h['to'] for h in d['history']] == ['ISSUED', 'PAID'], 'détail d\'une facture : lignes, paiements, historique')
        fr('lg_invoice_detail', 'LG003', 'détail sans droit de lecture', acteur=op, p_invoice=ip)

        # ============================================================== J. dépenses, synthèse
        fr('lg_record_expense', 'LG003', 'une dépense sans droit', acteur=op, p_category='FUEL', p_amount=10, p_currency='USD')
        fr('lg_record_expense', 'LG005', 'montant nul', p_category='FUEL', p_amount=0, p_currency='USD')
        fr('lg_record_expense', 'LG005', 'catégorie inconnue', p_category='VACANCES', p_amount=10, p_currency='USD')
        fr('lg_record_expense', 'LG005', 'devise inconnue', p_category='FUEL', p_amount=10, p_currency='EUR')
        fr('lg_record_expense', 'LG005', 'dépense datée du futur', p_category='FUEL', p_amount=10, p_currency='USD', p_incurred_on='2099-01-01')
        fr('lg_record_expense', 'LG002', 'expédition inconnue', p_category='TRANSPORT', p_amount=10, p_currency='USD', p_shipment=R("gen_random_uuid()"))
        e1 = f('lg_record_expense', p_category='FUEL', p_amount='120.50', p_currency='USD', p_description='carburant des camionnettes')
        e2 = f('lg_record_expense', p_category='TRANSPORT', p_amount='6000', p_currency='DOP', p_description='fret local', p_supplier='Transport Rapido')
        e3 = f('lg_record_expense', p_category='RENT', p_amount='900', p_currency='USD')
        e4 = f('lg_record_expense', p_category='OTHER', p_amount='55', p_currency='USD', p_incurred_on=q("select (current_date - 40)::text"))
        ok(e1['number'] == 'EXP-%s-000001' % YEAR and e1['status'] == 'RECORDED', 'numéro de dépense')
        ok(q("select base_amount_usd::text from logistics.expense where id = '%s'" % e2['expense_id']) == '100.00', 'une dépense de 6 000 DOP vaut 100,00 USD au taux du jour (60)')
        refuse("update logistics.expense set amount = 1 where id = '%s'" % e1['expense_id'], 'LG004', 'modifier une dépense')
        refuse("delete from logistics.expense", 'LG004', 'supprimer une dépense')
        fr('lg_void_expense', 'LG003', 'annuler une dépense sans être direction', p_expense=e3['expense_id'], p_reason='doublon')
        fr('lg_void_expense', 'LG005', 'annuler sans motif', acteur=admin, p_expense=e3['expense_id'], p_reason=' ')
        ok(f('lg_void_expense', acteur=admin, p_expense=e3['expense_id'], p_reason='saisie en double')['status'] == 'VOIDED', 'dépense annulée')
        fr('lg_void_expense', 'LG004', 'annuler deux fois', acteur=admin, p_expense=e3['expense_id'], p_reason='x')
        fr('lg_finance_summary', 'LG003', 'la synthèse sans être direction', acteur=caissier, p_from=TODAY, p_to=TODAY)
        fr('lg_finance_summary', 'LG005', 'une période à l\'envers', acteur=admin, p_from=TODAY, p_to='2020-01-01')
        # revenus attendus (en dollars), recalculés ICI à partir des lignes de chaque devis, indépendamment des écritures
        sB = f('lg_finance_summary', acteur=admin, p_from=TODAY, p_to=TODAY)
        net_sql = D(q("select coalesce(sum(net_base_usd), 0) from logistics.revenue_entry where entry_date = current_date"))
        ok(sB['revenue_base'] == E['rev'] and sB['tax_collected_base'] == E['tax'], 'revenu %s et taxe collectée %s : IDENTIQUES au cumul tenu indépendamment par le test (à partir des lignes de chaque devis)' % (sB['revenue_base'], sB['tax_collected_base']))
        ok(sB['revenue_base'] == net_sql and sum(sB['revenue_by_category_base'].values(), D(0)) == sB['revenue_base'], 'la synthèse reprend les écritures du jour, et ses catégories s\'additionnent au total')
        ok(sB['revenue_by_category_base'].get('CREDIT_NOTE', 0) < 0 and sB['revenue_by_category_base'].get('CANCELLATION', 0) < 0, 'les avoirs et les annulations sont des écritures NÉGATIVES')
        ok(sB['expenses_base'] == D('220.50'), 'dépenses du jour : 120,50 + 100,00 (les 900 annulés et les 55 d\'il y a 40 jours n\'y sont pas) : %s' % sB['expenses_base'])
        ok(sB['expenses_by_category_base'] == {'FUEL': D('120.50'), 'TRANSPORT': D('100.00')}, 'par catégorie')
        ok(sB['expenses_by_currency'] == {'USD': D('120.50'), 'DOP': D('6000.00')}, 'et dans la devise d\'origine')
        ok(sB['margin_base'] == sB['revenue_base'] - sB['expenses_base'], 'marge = revenu − dépenses')
        ok(sB['collected_base'] == E['coll'] and sB['refunded_base'] == E['refd'] and sB['net_collected_base'] == E['coll'] - E['refd'], 'encaissé %s, remboursé %s : identiques au cumul tenu par le test' % (sB['collected_base'], sB['refunded_base']))
        ok(sB['tax_collected_base'] == D(q("select coalesce(sum(tax_base_usd), 0) from logistics.revenue_entry")), 'taxe collectée')
        ok(sB['revenue_by_category_base'].get('FREIGHT', 0) > 0 and 'TAX' not in sB['revenue_by_category_base'], 'la taxe n\'est PAS un revenu : elle a sa propre ligne')
        sP = f('lg_finance_summary', acteur=admin, p_from=q("select (current_date - 60)::text"), p_to=q("select (current_date - 30)::text"))
        ok(sP['expenses_base'] == D('55.00') and sP['revenue_base'] == 0 and sP['collected_base'] == 0, 'une autre période ne montre que la dépense d\'il y a 40 jours')
        ok(sB['receivable_now_by_currency'].get('USD', 0) > 0 and sB['receivable_now_by_currency'].get('DOP', 0) > 0, 'à recevoir, par devise')

        # ============================================================== K. numérotation, ajout seul, audit, événements
        ok(cl.run(B, "begin; select logistics.next_number('essai', 'ESS'); rollback; select logistics.next_number('essai', 'ESS')")[1] == 'ESS-%s-000001' % YEAR, 'la numérotation est SANS TROU : un numéro pris puis annulé est rendu')
        for kind, prefix in (('invoice', 'INV'), ('payment', 'PAY'), ('credit', 'CRN'), ('refund', 'REF'), ('quote', 'QUO'), ('expense', 'EXP')):
            ns = cl.lignes(B, "select last_value from logistics.finance_counter where kind = '%s'" % kind)
            nb = {'invoice': "select count(*) from logistics.invoice where number like 'INV-%'", 'payment': 'select count(*) from logistics.payment', 'credit': 'select count(*) from logistics.credit',
                  'refund': 'select count(*) from logistics.refund', 'quote': 'select count(*) from logistics.quote', 'expense': 'select count(*) from logistics.expense'}[kind]
            ok(ns == [q(nb)], 'compteur « %s » : %s numéros émis, autant de documents' % (kind, ns[0]))
        for t, col in (('payment', 'reference'), ('refund', 'reason'), ('credit', 'reason'), ('revenue_entry', 'ref_id'), ('invoice_status_history', 'reason')):
            refuse("update logistics.%s set %s = 'x'" % (t, col), 'LG004', 'modifier %s' % t)
            refuse("delete from logistics.%s" % t, 'LG004', 'supprimer %s' % t)
        refuse("update logistics.payment set amount = amount", 'LG004', 'réécrire un paiement')
        refuse("insert into logistics.payment (number, invoice_id, customer_id, amount, currency, base_amount_usd, tendered_amount, tendered_currency, rate_used, method, correlation_id) values ('P', '%s', '%s', 0, 'USD', 0, 1, 'USD', 1, 'CASH', gen_random_uuid())" % (ip, cb), '23514', 'un paiement nul')
        refuse("insert into logistics.refund (number, payment_id, invoice_id, customer_id, amount, currency, base_amount_usd, method, reason, correlation_id) values ('R', '%s', '%s', '%s', 1, 'USD', 1, 'CASH', ' ', gen_random_uuid())" % (p1['payment_id'], iid, ca), '23514', 'un remboursement sans motif')
        # chaque opération d'argent a sa trace d'audit ET son événement, sous une même corrélation
        for action, evt, n_ in (('payment.record', 'PaymentReceived', q("select count(*) from logistics.payment")), ('invoice.credit', 'CreditIssued', q("select count(*) from logistics.credit")),
                                ('payment.refund', 'RefundIssued', q("select count(*) from logistics.refund")), ('quote.create', 'QuoteCreated', q("select count(*) from logistics.quote")),
                                ('expense.record', 'ExpenseRecorded', q("select count(*) from logistics.expense"))):
            ok(q("select count(*) from logistics.audit_log where action = '%s'" % action) == n_ and q("select count(*) from logistics.domain_event where event_type = '%s'" % evt) == n_, '%s : %s traces d\'audit et autant d\'événements « %s »' % (action, n_, evt))
        ok(q("select count(*) from logistics.audit_log where action = 'invoice.transition'") == q("select count(*) from logistics.invoice_status_history where from_status is not null"), 'chaque transition de facture : historique ET audit')
        ok(q("select count(distinct p.id) from logistics.payment p join logistics.domain_event e on e.correlation_id = p.correlation_id and e.event_type = 'PaymentReceived'") == q("select count(*) from logistics.payment"), 'le paiement et son événement partagent la corrélation')
        ok(q("select count(*) from logistics.domain_event where event_type in ('InvoicePartiallyPaid','InvoicePaid','InvoiceOverdue','InvoiceCancelled','InvoiceRefunded','InvoiceIssued')") ==
           q("select count(*) from logistics.invoice_status_history where from_status is not null"), 'une transition de facture = un événement')
        ok(q("select count(*) from logistics.audit_log where actor_user_id is null and action in ('payment.record','payment.refund','invoice.credit','invoice.create','invoice.transition','quote.create','quote.cancel','expense.record','expense.void','pricing.configure')") == '0', 'toute opération d\'argent a un auteur dans l\'audit')

        # ============================================================== L. le contrôle d'intégrité : propre, puis il SAIT échouer
        ok(q("select count(*) from logistics.reconcile_finance()") == '0', 'après tout ce parcours : AUCUNE anomalie')
        code, sortie = cl.run(B, "select count(*) from public.lg_reconcile_finance()", role='authenticated', claims=admin)
        ok(code == 0 and sortie == '0', 'le contrôle, appelé par la direction par la façade : aucune anomalie (obtenu : %s %s)' % (code, sortie[-300:]))
        code, texte = cl.run(B, "select count(*) from public.lg_reconcile_finance()", role='authenticated', claims=caissier, expect_error=True)
        ok(code != 0 and 'LG003' in texte, 'le contrôle sans être direction : refusé')
        corrompre = lambda sql: cl.run(B, "begin; alter table logistics.invoice disable trigger guard_invoice; alter table logistics.invoice_item disable trigger guard_invoice_item; %s; select string_agg(problem, ',' order by problem) from logistics.reconcile_finance(); rollback;" % sql)[1]   # noqa: E731
        ok('paid_mismatch' in corrompre("update logistics.invoice set paid_amount = paid_amount + 1 where id = '%s'" % ip), 'le contrôle voit un montant payé qui ne correspond plus aux paiements')
        ok('credited_mismatch' in corrompre("update logistics.invoice set credited_amount = credited_amount + 1 where id = '%s'" % ip), '…un avoir fantôme')
        ok('refunded_mismatch' in corrompre("update logistics.invoice set refunded_amount = refunded_amount + 1 where id = '%s'" % ip), '…un remboursement fantôme')
        ok('items_mismatch' in corrompre("update logistics.invoice_item set amount = amount + 1 where id = (select id from logistics.invoice_item where invoice_id = '%s' limit 1)" % ip), '…des lignes qui ne font plus le total')
        ok('total_mismatch' in corrompre("update logistics.invoice set total = total + 1 where id = '%s'" % ip), '…un total incohérent avec ses composantes')
        ok('status_mismatch' in corrompre("update logistics.invoice set status = 'ISSUED' where id = '%s'" % ip), '…un statut qui ne découle plus des montants')
        ok('overdue_not_marked' in corrompre("update logistics.invoice set due_date = current_date - 3 where id = '%s'" % io4), '…un retard non marqué')
        ok('revenue_mismatch' in cl.run(B, "begin; alter table logistics.revenue_entry disable trigger revenue_entry_append_only; update logistics.revenue_entry set net_amount = net_amount + 1 where id = (select id from logistics.revenue_entry where invoice_id = '%s' limit 1); select string_agg(problem, ',') from logistics.reconcile_finance(); rollback;" % ip)[1], '…un revenu qui ne correspond plus à la facture')
        ok('customer_mismatch' in cl.run(B, "begin; alter table logistics.payment disable trigger payment_append_only; update logistics.payment set customer_id = '%s' where invoice_id = '%s'; select string_agg(problem, ',') from logistics.reconcile_finance(); rollback;" % (ca, ip))[1], '…un paiement attribué à un autre client')
        ok('refund_exceeds_payment' in cl.run(B, "begin; alter table logistics.refund disable trigger refund_append_only; update logistics.refund set amount = amount + 1000 where id = '%s'; select string_agg(problem, ',') from logistics.reconcile_finance(); rollback;" % rf3['refund_id'])[1], '…un remboursement supérieur au paiement')
        ok(q("select count(*) from logistics.reconcile_finance()") == '0', 'et la base est restée intacte après ces simulations')

        # ============================================================== L bis. le rattrapage de l'ancien schéma ne touche JAMAIS aux factures natives
        empreinte = lambda: q("select md5(coalesce((select string_agg(md5(i::text), '' order by i.number) from logistics.invoice i where i.source = 'native'), '') || "
                              "coalesce((select string_agg(md5(t::text), '' order by t.id) from logistics.invoice_item t join logistics.invoice i on i.id = t.invoice_id where i.source = 'native'), ''))")   # noqa: E731
        avant_natives = empreinte()
        q('select logistics.backfill_from_legacy()')
        ok(avant_natives == empreinte() and q("select count(*) from logistics.invoice where source = 'native'") != '0', 'rejouer le rattrapage de l\'ancien schéma laisse les factures natives (et leurs lignes) INTACTES')
        ok(q("select count(*) from logistics.reconcile_with_legacy()") == '0', 'et la réconciliation avec l\'ancien schéma reste à 0 écart, factures natives présentes')
        ok(q("select count(*) from logistics.invoice where source = 'native' and legacy_invoice_id is not null") == '0', 'aucune facture native n\'est rattachée à une facture héritée')

        # ============================================================== M. portes fermées
        ok(q("select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname like 'lg\\_%' and (has_function_privilege('anon', p.oid, 'execute') or has_function_privilege('public', p.oid, 'execute'))") == '0', 'AUCUNE façade lg_* n\'est ouverte à l\'anonyme')
        ok(q("select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'logistics' and (has_function_privilege('anon', p.oid, 'execute') or has_function_privilege('authenticated', p.oid, 'execute'))") == '0', 'aucune fonction interne n\'est appelable par un compte connecté')
        ok(q("select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace where n.nspname = 'logistics' and c.relkind = 'r' and (not c.relrowsecurity or has_table_privilege('authenticated', c.oid, 'select') or has_table_privilege('anon', c.oid, 'select'))") == '0', 'toutes les tables du noyau (dont les 17 de la phase 10) : RLS active, aucun accès direct')
        ok(q("select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace where n.nspname = 'logistics' and c.relkind = 'v' and (has_table_privilege('authenticated', c.oid, 'select') or has_table_privilege('anon', c.oid, 'select'))") == '0', 'la vue « customer_balance » n\'est lisible ni par un client ni par un anonyme')
        for fn in ('lg_my_invoices', 'lg_finance_summary', 'lg_record_payment', 'lg_create_quote'):
            code, texte = cl.run(B, "select public.%s()" % fn, role='anon', expect_error=True)
            ok(code != 0 and ('permission' in texte.lower() or '42501' in texte or 'does not exist' in texte or '42883' in texte), 'anonyme : %s refusé' % fn)
        ok(P.empreintes_historiques(cl, B)['public.factures'] == avant_legacy['public.factures'] and all(P.empreintes_historiques(cl, B)[t] == avant_legacy[t] for t in ('public.colis', 'public.colis_historique', 'public.appareils', 'public.clients')),
           'tout au long de la phase 10, les anciennes tables (colis, historique, FACTURES, clients, appareils) n\'ont pas bougé')

    print('%d vérifications — phase 10 (moteur financier) : OK' % N[0])


if __name__ == '__main__':
    main()
