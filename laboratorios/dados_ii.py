"""Corpus autoral comum de L05/L06. Fatos estruturados são anotações, não NLP."""
from copy import deepcopy
import csv
import hashlib
import json
import re
import unicodedata
from pathlib import Path

DAY = '2026-09-30'


def document(doc_id, text, facts, group='publico', start='2026-01-01', end='2026-12-31'):
    return dict(doc_id=doc_id, revision=1, text=text, facts=facts, group=group,
                valid_from=start, valid_to=end, origin='Horizonte: corpus didático autoral')


DOCUMENTS = [
    document('D01', 'Troca de produto intacto: prazo de 30 dias. Consulte a exceção para personalizados.',
             {'troca_comum': '30 dias'}),
    document('D02', 'Exceção: produto personalizado não admite troca por preferência, mesmo intacto.',
             {'troca_personalizado': 'não admitida por preferência'}),
    document('D03', 'Reembolso aprovado: prazo de 5 dias úteis para processamento.',
             {'reembolso_prazo': '5 dias úteis'}),
    document('D04', 'Frete padrão: entrega em 7 dias úteis.', {'frete_prazo': '7 dias úteis'}),
    document('D05', 'Desconto interno: clientes ouro recebem 15 por cento.',
             {'desconto_ouro': '15%'}, group='comercial'),
    document('D06', 'Troca de produto intacto: prazo antigo de 60 dias.',
             {'troca_comum': '60 dias'}, start='2025-01-01', end='2025-12-31'),
    document('D07', 'Frete padrão: entrega em 3 dias úteis a partir de novembro.',
             {'frete_prazo': '3 dias úteis'}, start='2026-11-01'),
    document('D08', 'Atendimento por chat: das 9 às 18 horas em dias úteis.',
             {'chat_horario': '9 às 18 horas em dias úteis'}),
    document('D09', 'Rastreamento de encomenda exige código de envio.',
             {'rastreio_requisito': 'código de envio'}),
    document('D10', 'Comunicado A: crédito de cortesia de 10 reais.', {'credito': '10 reais'}),
    document('D11', 'Reembolso aprovado usa o meio de pagamento original.',
             {'reembolso_meio': 'pagamento original'}),
    document('D12', 'Comunicado B: crédito de cortesia de 20 reais. Mesma autoridade do comunicado A.',
             {'credito': '20 reais'}),
]


def corpus():
    return deepcopy(DOCUMENTS)


def allowed(doc, identity='suporte', day=DAY):
    return (doc['group'] == 'publico' or doc['group'] == identity) and doc['valid_from'] <= day <= doc['valid_to']


def tokens(text):
    normal = unicodedata.normalize('NFKD', text.lower())
    return re.findall(r'[a-z0-9]+', ''.join(c for c in normal if not unicodedata.combining(c)))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def lines(path, rows):
    Path(path).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf8')


def readlines(path):
    return [json.loads(r) for r in Path(path).read_text(encoding='utf8').splitlines()]


def table(path, rows):
    with Path(path).open('w', encoding='utf8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
