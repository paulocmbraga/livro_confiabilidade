"""Fluxo preparado, seleção anterior aos rótulos e relógio em dias lógicos."""
import random
from .dados_ii import write, lines, table


def stream():
    rows = []
    for day in range(4):
        easy = 30 if day == 1 else 40
        for i in range(50):
            hard = i >= easy
            j = i-easy if hard else i
            correct = (j % 5 != 0) if hard else (j % 10 != 0)
            if hard and day >= 2:
                correct = j % 5 == 0
            # Feedback seletivo é uma intervenção explícita do gerador.
            responds = (i % 2 == 0) if day < 2 else bool(correct)
            rows.append(dict(task=f'C{day}-T{i:02}', cohort=day,
                 segment='dificil' if hard else 'simples', correct=correct,
                 label_day=day+(3 if hard else 1), responds=responds,
                 input_version='nova' if day == 1 else 'original'))
    return rows


def select_audit(rows, seed=18):
    rng = random.Random(seed); selected = set()
    for cohort in sorted({r['cohort'] for r in rows}):
        for segment in ('simples', 'dificil'):
            ids = sorted(r['task'] for r in rows if r['cohort'] == cohort
                         and r['segment'] == segment)
            selected.update(rng.sample(ids, min(20, len(ids))))
    return selected


def cohorts(rows, selected, asof):
    result = []
    for c in sorted({r['cohort'] for r in rows if r['cohort'] <= asof}):
        for segment in ('simples', 'dificil'):
            population = [r for r in rows if r['cohort'] == c and r['segment'] == segment]
            sample = [r for r in population if r['task'] in selected]
            arrived = [r for r in sample if r['label_day'] <= asof]
            result.append(dict(asof=asof, cohort=c, segment=segment,
                  population=len(population), assigned=len(sample), labels=len(arrived),
                  inclusion_probability=len(sample)/len(population),
                  coverage=len(arrived)/len(sample), complete=len(arrived)==len(sample),
                  error=(sum(not r['correct'] for r in arrived)/len(arrived)
                         if arrived else None)))
    return result


def monitor(rows, selected):
    decisions = []
    for day in range(7):
        for c in sorted({r['cohort'] for r in rows if r['cohort'] == day}):
            source = [r for r in rows if r['cohort'] == c]
            if any(r['input_version'] == 'nova' for r in source):
                decisions.append(dict(day=day, cohort=c, kind='mudanca_entrada',
                    hypothesis='mudança de mistura; qualidade ainda desconhecida',
                    owner='dados', action='auditar coorte', next_check=day+3))
        for r in cohorts(rows, selected, day):
            if (r['segment'] == 'dificil' and r['complete'] and r['labels'] >= 8
                    and r['error'] > .3 and day == r['cohort']+3):
                decisions.append(dict(day=day, cohort=r['cohort'], kind='qualidade',
                    hypothesis='erro do segmento difícil acima do limiar didático',
                    owner='qualidade', action='conter segmento e revisar casos',
                    next_check=day+1))
    return decisions


def summarize(rows, selected):
    out = []
    for c in range(4):
        group = [r for r in rows if r['cohort'] == c]
        feedback = [r for r in group if r['responds']]
        mature = cohorts(rows, selected, c+3)
        mature = [r for r in mature if r['cohort'] == c]
        out.append(dict(cohort=c, tasks=len(group), votes=len(feedback),
                        feedback_quality=sum(r['correct'] for r in feedback)/len(feedback),
                        fixture_quality=sum(r['correct'] for r in group)/len(group),
                        weighted_audit_quality=1-sum(r['error']*r['population']
                                                   for r in mature)/len(group)))
    return out


def capture(folder):
    folder.mkdir(); rows=stream(); selected=select_audit(rows)
    lines(folder/'fixture_truth.jsonl', rows)
    lines(folder/'audit_assignment.jsonl', [dict(task=r['task'], cohort=r['cohort'],
          segment=r['segment'], selected=r['task'] in selected) for r in rows])
    table(folder/'cohorts.csv', [r for day in range(7) for r in cohorts(rows,selected,day)])
    decisions=monitor(rows,selected);lines(folder/'alert_decisions.jsonl',decisions)
    result=summarize(rows,selected);table(folder/'feedback_comparison.csv',result)
    write(folder/'stream_manifest.json', dict(tasks=len(rows),seed=18,logical_days=7,
          labels='preparados; sem participantes humanos', audit='estratificada sem reposição',
          threshold='erro difícil > 0.3; mínimo 8 rótulos; coorte completa',
          change_day=2, first_quality_alert=5, detection_delay=3,
          quality_false_alarms_before_change=0))
    return dict(tasks=len(rows),assigned=len(selected),cohorts=result,alerts=decisions)
