# L18 — protocolo para coleta posterior

Estado: **não iniciada**. Dois revisores independentes, ainda não atribuídos; doze itens por revisor, 24 julgamentos planejados, zero coletado. Não contatar pessoas automaticamente. A autorização do autor nesta etapa é preparar o pacote e manter a coleta pendente.

Origem: `output/parte_v_principal_v02/avaliacao_humana`. Entregar a cada revisor somente `itens_cegos.json`, seu formulário e este protocolo. A `chave_restrita.json` identifica casos e notas do oráculo fechado; mantê-la separada até o encerramento dos votos. Os arquivos originais ficam imutáveis. Salvar o preenchimento em diretório novo, com data, identificação consentida e versão da rubrica.

## Rubrica e procedimento

1. Ler tarefa e resposta sem consultar o modelo gerador, o juiz ou o voto do outro revisor.
2. Correção: marcar `correct`, `incorrect`, `underdetermined` ou `not_applicable`, com justificativa. Distinguir quantidade correta com unidade extra de quantidade incorreta. A exigência de saída numérica é uma dimensão de formato separada no comentário.
3. Suporte: marcar `supported`, `unsupported` ou `ambiguous`. Considerar somente informação fornecida e operações explicitamente admitidas pela tarefa.
4. Clareza: marcar `clear`, `misleading` ou `insufficient`, apontando o trecho. A resposta UNKNOWN pode ser adequada ao contrato fechado e inadequada como experiência conversacional; registrar essa distinção.
5. Decisão: `answer`, `clarify` ou `abstain`. Uma pergunta impossível não autoriza inventar uma quantidade. Explicar qual dado faltante resolveria uma ambiguidade.
6. Registrar dúvida sobre o item; não alterar silenciosamente o enunciado nem consultar o gabarito para eliminar desacordo.

Após os dois votos, registrar discordâncias e adjudicação com preservação dos originais. Os doze itens são um piloto de rubrica, não amostra suficiente para qualificar um juiz em respostas abertas. Não usar os mesmos itens para ajustar prompt/limiar e afirmar desempenho em reserva. Uma etapa posterior deve construir novos casos, congelar a rubrica, definir consequências e avaliar risco por segmento.

O campo `comment` é obrigatório para erro, ambiguidade ou desacordo com o contrato de formato. Campos nulos significam não avaliado, nunca concordância. A chave de liberação operacional continua falsa até evidência independente, reserva adjudicada, escopo compatível e limiar validado.
