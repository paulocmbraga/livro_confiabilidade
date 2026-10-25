"""Parser restrito ao contrato HTML autoral; não é extrator universal."""
from html.parser import HTMLParser
from collections import defaultdict
from laboratorios.parte_i.common import digest


class PolicyHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}; self.units = []; self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'article':
            self.meta = {k[5:]: v for k, v in attrs.items() if k.startswith('data-')}
        if tag in ('p', 'tr') and 'data-unit' in attrs:
            if self.current is not None:
                raise ValueError('Unidades aninhadas fora do contrato')
            self.current = {'id': attrs['data-unit'], 'tag': tag,
                            'kind': attrs.get('data-kind', 'rule'),
                            'requires': attrs.get('data-requires', '').split(), 'pieces': []}

    def handle_data(self, text):
        if self.current is not None and text.strip():
            self.current['pieces'].append(text.strip())

    def handle_endtag(self, tag):
        if self.current is not None and tag == self.current['tag']:
            u = self.current; self.current = None
            u['text'] = ' | '.join(u.pop('pieces')); self.units.append(u)

    def result(self):
        required = {'tenant', 'policy', 'version', 'from', 'until', 'license'}
        if self.current is not None or not required.issubset(self.meta):
            raise ValueError('Fonte incompleta')
        ids = [u['id'] for u in self.units]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError('Unidades ausentes/duplicadas')
        if any(r not in ids for u in self.units for r in u['requires']):
            raise ValueError('Dependência inexistente')
        return {'metadata': self.meta, 'units': self.units}


def parse(source):
    p = PolicyHTML(); p.feed(source); p.close(); return p.result()


def chunks(document, strategy):
    units = document['units']; byid = {u['id']: u for u in units}
    if strategy == 'body_only':
        groups = [[u] for u in units if u['kind'] != 'footnote']
    elif strategy == 'independent':
        groups = [[u] for u in units]
    elif strategy == 'linked':
        groups = []
        for u in units:
            selected = set(); pending = [u['id']]
            while pending:
                key = pending.pop()
                if key in selected: continue
                selected.add(key); pending.extend(byid[key]['requires'])
            groups.append([v for v in units if v['id'] in selected])
    else:
        raise ValueError('Estratégia desconhecida')
    result = []
    for group in groups:
        payload = {'metadata': document['metadata'], 'units': [u['id'] for u in group],
                   'text': '\n'.join(u['text'] for u in group), 'strategy': strategy}
        result.append(dict(payload, id=digest(payload)))
    return result


def assess(chunks_, references):
    # Âncoras autorais independentes do parser. Não é julgador semântico geral.
    seen = [u for u in references if any(all(a in c['text'] for a in u['anchors']) for c in chunks_)]
    closed = [u for u in references if any(all(a in c['text'] for a in u['closure_anchors']) for c in chunks_)]
    return {'units': len(references), 'recoverable': len(seen), 'closed_in_one_chunk': len(closed),
            'missing': [u['id'] for u in references if u not in seen],
            'open': [u['id'] for u in references if u not in closed]}


def eligible(meta, tenant, date):
    return meta['tenant'] == tenant and meta['from'] <= date and (not meta['until'] or date < meta['until'])


def catalog(documents):
    seen = {}; duplicates = []; conflicts = []; accepted = []
    identities = defaultdict(set)
    for name, doc in documents:
        meta = doc['metadata']; scope = (meta['tenant'], meta['policy'], meta['version'], meta['from'], meta['until'])
        content = digest(doc['units']); identity = (*scope, content)
        if identity in seen:
            duplicates.append({'source': name, 'same_as': seen[identity]}); continue
        seen[identity] = name; accepted.append(name); identities[scope].add(content)
    for scope, values in identities.items():
        if len(values) > 1: conflicts.append({'identity': list(scope), 'contents': sorted(values)})
    return {'retained': accepted, 'duplicates': duplicates, 'conflicts': conflicts,
            'publishable': not conflicts}
