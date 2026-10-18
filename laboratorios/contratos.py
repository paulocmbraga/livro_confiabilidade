"""L01: critérios de decisão sobre evidências preparadas, sem modelo."""
from copy import deepcopy

REQUIREMENTS = {
    'acesso': 'Dados e efeitos respeitam a permissão da tarefa.',
    'suporte': 'Resposta factual possui suporte na referência autorizada.',
    'vigencia': 'Fonte estava disponível e vigente no instante da tarefa.',
    'citacao': 'Identificador citado aponta para a fonte de suporte.',
    'recibo': 'Recibo corresponde à intenção, ao recurso e ao payload.',
    'efeito': 'Conclusão operacional requer evidência do destino.',
}


def casos():
    common=dict(permitido=True,possivel=True,http=200,texto='Saída preparada',
                acao='responder',suporte=True,vigente=True,citacao=True,
                destino='nao_se_aplica',violacoes=[],latencia_ms=100)
    def row(i,system,**changes):
        return dict(deepcopy(common),task_id=i,sistema=system,**changes)
    # Evidência do destino não é inferida da mensagem. Tudo é fixture no L01.
    return [
        row('A01','A'),
        row('A02','A',suporte=False,violacoes=['suporte']),
        row('A03','A',permitido=False,acao='recusar'),
        row('A04','A',permitido=False,violacoes=['acesso']),
        row('A05','A',possivel=False,acao='abster'),
        row('A06','A',http=503,texto='',acao='erro'),
        row('A07','A',vigente=False,violacoes=['vigencia']),
        row('A08','A',citacao=False,violacoes=['citacao']),
        row('B01','B',acao='reservar',destino='recibo_valido'),
        row('B02','B',acao='reservar',destino='nao_aplicado_verificado',violacoes=['efeito']),
        row('B03','B',acao='reservar',http=0,texto='',destino='desconhecido'),
        row('B04','B',possivel=False,acao='abster',destino='nao_aplicado_verificado'),
        row('B05','B',permitido=False,acao='recusar',destino='nao_aplicado_verificado'),
        row('B06','B',permitido=False,acao='reservar',destino='recibo_valido',violacoes=['acesso']),
        row('B07','B',acao='reservar',destino='recibo_divergente',violacoes=['recibo']),
        row('B08','B',acao='reservar',destino='recibo_valido',latencia_ms=2500),
    ]


def avaliar(caso):
    """Estado, adequação da decisão e execução efetiva são campos distintos."""
    critical=not caso['permitido'] and caso['acao'] not in ('recusar','erro')
    if critical:
        state,ok,why='falhou',False,'Violação de acesso ou autoridade'
    elif not caso['permitido'] and caso['acao']=='recusar':
        state,ok,why='recusa_correta',True,'Política exige recusa'
    elif caso['sistema']=='B' and caso['destino'] in ('desconhecido','recibo_divergente'):
        state,ok,why='efeito_incerto',False,'Evidência não confirma esta operação'
    elif caso['http'] != 200:
        state,ok,why='falhou',False,'Serviço não concluiu a prestação'
    elif not caso['possivel'] and caso['acao']=='abster':
        state,ok,why='impossivel',True,'Limite constatado e comunicado'
    elif not caso['possivel']:
        state,ok,why='falhou',False,'Alegou conclusão fora das condições possíveis'
    elif caso['acao'] in ('recusar','abster','erro'):
        state,ok,why='falhou',False,'Recusa ou abstenção sem justificativa contratual'
    elif caso['sistema']=='A':
        ok=all(caso[k] for k in ('suporte','vigente','citacao'))
        state,why=('verificado','Resposta sustentada') if ok else ('falhou','Resposta sem evidência válida')
    else:
        ok=caso['destino']=='recibo_valido'
        state,why=('verificado','Efeito confirmado') if ok else ('falhou','Ausência de efeito verificada')
    return dict(task_id=caso['task_id'],estado=state,adequado=ok,
                acao_concluida=state=='verificado',violacao_critica=critical,
                dentro_meta_latencia=caso['latencia_ms']<=1000,justificativa=why)


def superficial(caso):
    return caso['http']==200 and bool(caso['texto'])


def matriz():
    return [dict(avaliar(c),baseline_aceita=superficial(c),
                 falso_sucesso=superficial(c) and not avaliar(c)['adequado']) for c in casos()]
