"""Contratos pequenos, explícitos e independentes de modelos externos."""
from collections import Counter
from datetime import datetime
from hashlib import sha256
from math import ceil, isfinite, log, sqrt
from pathlib import Path
from random import Random
import json
import sqlite3


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError('Número finito requerido')
    return value


def wilson(k, n, z=1.959963984540054):
    if type(n) is not int or type(k) is not int or n <= 0 or not 0 <= k <= n:
        raise ValueError('Contagens inválidas')
    if finite(z) <= 0:
        raise ValueError('Quantil inválido')
    p = k/n
    den = 1 + z*z/n
    center = (p + z*z/(2*n))/den
    half = z*sqrt(p*(1-p)/n + z*z/(4*n*n))/den
    return max(0., center-half), min(1., center+half)


def zero_failure_n(limit, alpha=.05):
    if not 0 < finite(limit) < 1 or not 0 < finite(alpha) < 1:
        raise ValueError('Probabilidades fora de (0, 1)')
    return ceil(log(alpha)/log(1-limit))


def grouped_bootstrap(groups, repetitions=2000, seed=729):
    """Média de diferenças por família; todas as famílias têm peso igual."""
    if len(groups) < 2 or type(repetitions) is not int or repetitions < 100:
        raise ValueError('Famílias ou réplicas insuficientes')
    values = []
    for rows in groups.values():
        if not rows:
            raise ValueError('Família vazia')
        values.append(sum(finite(x) for x in rows)/len(rows))
    rng = Random(seed)
    draws = sorted(sum(rng.choices(values, k=len(values)))/len(values)
                   for _ in range(repetitions))
    return dict(estimate=sum(values)/len(values),
                low=draws[int(.025*(repetitions-1))],
                high=draws[int(.975*(repetitions-1))],
                families=len(values), repetitions=repetitions, seed=seed)


def outcome_bounds(good, bad, unknown):
    if any(type(x) is not int or x < 0 for x in (good,bad,unknown)):
        raise ValueError('Contagem inválida')
    n = good+bad+unknown
    if n == 0:
        raise ValueError('População vazia')
    return dict(n=n, lower=good/n, upper=(good+unknown)/n,
                coverage=(good+bad)/n)


def validate_case(row):
    required = {'id','family','event_at','available_at','predict_at','unit','value'}
    if not required <= row.keys() or not row['id'] or not row['family']:
        raise ValueError('Identidade incompleta')
    stamps = [datetime.fromisoformat(row[k]) for k in ('event_at','available_at','predict_at')]
    if any(x.utcoffset() is None for x in stamps):
        raise ValueError('Fuso ausente')
    if max(stamps[:2]) > stamps[2] or row['unit'] != 'hour':
        raise ValueError('Informação futura ou unidade incompatível')
    if not 0 <= finite(row['value']) <= 168:
        raise ValueError('Valor fora do domínio')
    return row


class Receipts:
    """Um destino SQLite local; não equivale a transação entre serviços."""
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS effects '
                        '(key TEXT PRIMARY KEY, digest TEXT NOT NULL, receipt TEXT NOT NULL)')
        self.db.commit()

    def commit(self, key, payload):
        if not key:
            raise ValueError('Chave vazia')
        body = json.dumps(payload,sort_keys=True,ensure_ascii=False,
                          separators=(',',':'),allow_nan=False)
        digest = sha256(body.encode()).hexdigest()
        receipt = 'r-' + sha256((key+':'+digest).encode()).hexdigest()[:24]
        self.db.execute('BEGIN IMMEDIATE')
        try:
            old = self.db.execute('SELECT digest,receipt FROM effects WHERE key=?',(key,)).fetchone()
            if old:
                if old[0] != digest:
                    raise ValueError('Chave reutilizada com outra intenção')
                result = old[1]
            else:
                self.db.execute('INSERT INTO effects VALUES (?,?,?)',(key,digest,receipt))
                result = receipt
            self.db.commit()
            return result
        except BaseException:
            self.db.rollback()
            raise

    def lookup(self,key):
        row = self.db.execute('SELECT receipt FROM effects WHERE key=?',(key,)).fetchone()
        return row[0] if row else None

    def close(self):
        self.db.close()


def reconcile(expected, events):
    """expected vem do ingresso independente do coletor."""
    ids = list(expected)
    if len(set(ids)) != len(ids):
        raise ValueError('Ingresso duplicado')
    statuses = {}
    duplicates = 0
    for event in events:
        key, state = event['id'],event['state']
        if key not in ids or state not in ('good','bad'):
            raise ValueError('Evento fora do contrato')
        if key in statuses:
            if statuses[key] != state:
                raise ValueError('Conclusões conflitantes')
            duplicates += 1
        statuses[key] = state
    counts = Counter(statuses.values())
    return {**outcome_bounds(counts['good'],counts['bad'],len(ids)-len(statuses)),
            'good':counts['good'],'bad':counts['bad'],
            'unknown':len(ids)-len(statuses),'duplicates':duplicates}


def burn(bad, total, slo):
    if type(total) is not int or type(bad) is not int or total <= 0 or not 0 <= bad <= total:
        raise ValueError('Janela inválida')
    if not 0 < finite(slo) < 1:
        raise ValueError('SLO inválido')
    return (bad/total)/(1-slo)


def assess(evidence, now):
    """Gate didático: requisitos cumulativos e ausência de evidência explícita."""
    now = datetime.fromisoformat(now)
    until = datetime.fromisoformat(evidence['valid_until'])
    if now.utcoffset() is None or until.utcoffset() is None:
        raise ValueError('Fuso obrigatório')
    required = ['identity_ok','population_ok','semantic_review','recovery_ok']
    reasons = [name for name in required if evidence.get(name) is not True]
    if now > until:
        reasons.append('expired')
    return dict(decision='eligible' if not reasons else 'hold', reasons=reasons)


def unit_cost(compute, review, recovery, useful):
    if any(finite(x) < 0 for x in (compute,review,recovery)):
        raise ValueError('Custo negativo')
    if type(useful) is not int or useful < 0:
        raise ValueError('Denominador inválido')
    total = compute+review+recovery
    return dict(total=total, useful=useful, per_useful=total/useful if useful else None,
                status='defined' if useful else 'undefined')
