# Materiais de consulta e reprodução

Material da primeira prova integral de *Engenharia de Confiabilidade para Sistemas de IA*, de Paulo Cesar Braga.

[fichas_reproducao.json](fichas_reproducao.json) identifica os 24 laboratórios, suas capturas canônicas, hashes dos manifestos e manuscritos. Os caminhos partem de `confiabilidade_ia`. `planned_tracks` registra planejamento, sem afirmar que todas as trilhas foram executadas. Não houve inferência de LLM nem participantes humanos. L00, de preparação, é indicado separadamente.

| Modelo | Uso |
| --- | --- |
| [contrato_campanha.json](modelos/contrato_campanha.json) | População, candidata, catálogo e orçamento |
| [ficha_avaliador.json](modelos/ficha_avaliador.json) | Rubrica, calibração e validação |
| [anotacoes.csv](modelos/anotacoes.csv) | Cabeçalho de um caderno de anotação |
| [objetivo_servico.json](modelos/objetivo_servico.json) | Indicador, meta e pendências |
| [runbook.md](modelos/runbook.md) | Gatilho, ação, autoridade e retorno |
| [revisao_incidente.md](modelos/revisao_incidente.md) | Cronologia, consequências e contraprovas |
| [dossie_decisao.md](modelos/dossie_decisao.md) | Alegações, evidências e decisão |
| [errata.md](modelos/errata.md) | Correção e evidências a renovar |

Copie o modelo para sua campanha antes de preenchê-lo. `null`, listas vazias e “pendente” significam ausência de decisão ou evidência. Os JSONs documentam contratos desta obra; não são adaptadores automaticamente compatíveis com todos os laboratórios. O CSV contém apenas cabeçalho. Os modelos não concedem autoridade externa.

Execute os laboratórios seguindo os capítulos, em pasta nova. Para conferir uma captura existente, use `--conferir` no módulo correspondente. Conserve a pasta inteira, pois o resumo não substitui entradas e evidências.

Para conferir as oito capturas, execute `python conferir_capturas.py` na raiz deste pacote. Os geradores editoriais e manuscritos privados não estão incluídos.
