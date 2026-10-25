"""IVF didático com vetores float32 integrais. Não utiliza Faiss/HNSW."""
import math
import numpy as np


def order(vectors, query, indices, ids):
    return sorted([{'id': ids[i], 'score': float(vectors[i] @ query)} for i in indices],
                  key=lambda r: (-r['score'], r['id']))


def approximate(vectors, query, allowed, ids, centers, labels, nprobe, k=3):
    if not 1 <= nprobe <= len(centers): raise ValueError('nprobe inválido')
    distances = ((centers-query)**2).sum(axis=1)
    cells = sorted(range(len(centers)), key=lambda i: (float(distances[i]), i))[:nprobe]
    candidates = [i for i in allowed if int(labels[i]) in cells]
    return {'cells': cells, 'scanned': len(candidates), 'ranking': order(vectors, query, candidates, ids)[:k]}


def ann_recall(actual, exact, k=3):
    denominator = min(k, len(exact))
    if denominator == 0: return None
    return len(set(actual[:k]) & set(exact[:k])) / denominator


def judged_metrics(ids, judgments, k=3):
    ranked = ids[:k]
    if len(ranked) != len(set(ranked)): raise ValueError('IDs repetidos')
    gains = [judgments.get(x, 0) for x in ranked]
    if any(type(g) is not int or not 0 <= g <= 2 for g in judgments.values()):
        raise ValueError('Grau de relevância inválido')
    dcg = sum((2**g-1)/math.log2(i+2) for i, g in enumerate(gains))
    ideal = sorted(judgments.values(), reverse=True)[:k]
    idcg = sum((2**g-1)/math.log2(i+2) for i, g in enumerate(ideal))
    return {'ndcg_unjudged_as_zero': dcg/idcg if idcg else None,
            'unjudged': sum(x not in judgments for x in ranked), 'returned': len(ranked)}


def exact_cache_key(tenant, activation, auth_epoch, bundle_hash, prompt, generator, question):
    from laboratorios.parte_i.common import digest
    return digest([tenant, activation, auth_epoch, bundle_hash, prompt, generator, question])


def semantic_compatible(query, candidate, tenant, candidate_tenant, activation, candidate_activation, threshold=.9):
    # Similaridade só propõe reutilização; condição necessária, não suficiência semântica.
    return (tenant == candidate_tenant and activation == candidate_activation and
            float(np.dot(query, candidate)) >= threshold)
