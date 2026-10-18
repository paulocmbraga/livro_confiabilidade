"""Estatística explícita para o piloto. Sem dependências externas."""
from collections import defaultdict
from math import isfinite
from random import Random
from statistics import mean


def quantil(valores, p):
    """Interpolação linear, posição (n - 1) * p; valores finitos."""
    if not valores or not 0 <= p <= 1 or not all(isfinite(v) for v in valores):
        raise ValueError('Quantil exige valores finitos e 0 <= p <= 1.')
    xs = sorted(valores)
    pos = (len(xs) - 1) * p
    i = int(pos)
    j = min(i + 1, len(xs) - 1)
    return xs[i] + (pos - i) * (xs[j] - xs[i])


def intervalo(valores, *, seed=104, n_boot=10000, nivel=0.95):
    """Bootstrap percentil da média das unidades recebidas, com reposição."""
    if len(valores) < 2 or not all(isfinite(v) for v in valores):
        raise ValueError('São necessárias ao menos duas unidades finitas.')
    if not isinstance(n_boot, int) or n_boot < 100 or not 0 < nivel < 1:
        raise ValueError('Configuração inválida de reamostragem.')
    rng = Random(seed)
    n = len(valores)
    amostras = [sum(rng.choices(valores, k=n)) / n for _ in range(n_boot)]
    alpha = (1 - nivel) / 2
    return {'media':mean(valores), 'inferior':quantil(amostras, alpha),
            'superior':quantil(amostras, 1 - alpha), 'unidades':n,
            'nivel':nivel, 'seed':seed, 'n_boot':n_boot,
            'degenerado':len(set(valores)) == 1}


def parear(tarefas, resultados):
    """Confere o denominador e devolve diferenças B-A por tentativa e tarefa."""
    ids = [t['task_id'] for t in tarefas]
    if len(ids) != len(set(ids)) or not ids:
        raise ValueError('Catálogo vazio ou task_id duplicado.')
    if any(type(t['repeticoes']) is not int or t['repeticoes'] < 1 for t in tarefas):
        raise ValueError('Cada tarefa exige um número inteiro positivo de repetições.')
    esperado = {(t['task_id'], r, v) for t in tarefas
                for r in range(t['repeticoes']) for v in ('A','B')}
    observado = {}
    for row in resultados:
        key = (row['task_id'], row['repeticao'], row['variante'])
        if key not in esperado or key in observado:
            raise ValueError(f'Tentativa inesperada ou duplicada: {key}')
        if row['score'] not in (0,1) or row['estado'] not in ('verificado','recusa_correta','falhou','efeito_incerto'):
            raise ValueError('Score/estado inválido.')
        if row['estado'] in ('falhou','efeito_incerto') and row['score'] != 0:
            raise ValueError('Falha/efeito incerto não pode contar como sucesso.')
        observado[key] = row['score']
    if set(observado) != esperado:
        raise ValueError(f'Campanha incompleta: faltam {len(esperado-set(observado))} tentativas.')
    grupos = defaultdict(list)
    for t in tarefas:
        for r in range(t['repeticoes']):
            grupos[t['task_id']].append(observado[t['task_id'],r,'B'] - observado[t['task_id'],r,'A'])
    pares = [{'task_id':t['task_id'], 'segmento':t['segmento'],
              'sistema':t['sistema'], 'repeticoes':len(grupos[t['task_id']]),
              'delta':mean(grupos[t['task_id']])} for t in tarefas]
    return pares, [d for t in tarefas for d in grupos[t['task_id']]]


def decidir(ic, *, margem=0.05, violacoes=0):
    """Regra didática de ganho mínimo; não é teste de equivalência."""
    estatistica = ('ganho_acima_da_margem' if ic['inferior'] > margem else
                   'ganho_abaixo_da_margem' if ic['superior'] < margem else 'inconclusivo')
    return {'estatistica':estatistica,
            'decisao':'bloquear_por_invariante' if violacoes else
                      'candidata_a_nova_validacao' if estatistica == 'ganho_acima_da_margem' else
                      'nao_promover',
            'violacoes_criticas':violacoes}


def auditar_particoes(registros):
    """Famílias não atravessam partições; demonstração, sem holdout secreto."""
    grupos = defaultdict(set)
    for r in registros:
        grupos[r['familia']].add(r['particao'])
    vazamentos = sorted(k for k,v in grupos.items() if len(v) > 1)
    if vazamentos:
        raise ValueError('Famílias em mais de uma partição: ' + ', '.join(vazamentos))
    return True
