# Engenharia de Confiabilidade para Sistemas de IA — segunda edição

Paulo Cesar Braga. Material complementar de 44 capítulos e dos apêndices A a H.

Este pacote é separado do material da primeira edição. Abra esta pasta como raiz
de trabalho. Nos comandos do livro ela é chamada `confiabilidade_ia_2ed`; neste
repositório sua pasta é `segunda_edicao`.

## Começar

Use Python 3.12. Escolha o perfil da parte antes de instalar dependências. Os locks
de cada parte não são intercambiáveis. Modelos, ambientes virtuais e Docker não
estão incluídos. Instruções por parte e URLs dos modelos estão no livro e nos
README dos laboratórios e materiais. Consulte o [guia de ambientes e execução](GUIA_LABORATORIOS.md)
para instalar o perfil correto e preparar os modelos. Execute os comandos depois
de entrar em `segunda_edicao`.

O primeiro ensaio de consulta usa somente biblioteca padrão:

```powershell
python -m unittest testes.test_apendices -v
python -m laboratorios.apendices.campaign --out output/minha_consulta_v01
```

## Conteúdo e evidência

- `laboratorios/`: implementações, adaptadores e verificadores.
- `testes/`: verificações automatizadas; consulte requisitos antes de executar.
- `materiais/`: casos, planos, rubricas, dados e referências de licenças.
- `output/`: capturas autorais, incluindo controles, diagnósticos e tentativas
  anteriores. Leia o capítulo para identificar a captura principal; não some
  execuções de versões diferentes como se fossem casos independentes.
- `requirements*.txt`: perfis de dependências dos laboratórios.

Preserve as capturas e execute campanhas em pastas novas. Mecanismos locais,
inferência real, simulação, custos assumidos e serviços externos são evidências
distintas. A coleta humana e a reprodução independente dos pacotes preparados
continuam pendentes. Os formulários não contêm avaliações humanas inventadas.

Execute `python conferir_pacote.py` para conferir o inventário atual em
`MANIFESTO_PUBLICO.json`. O arquivo `MANIFESTO_PACOTE.json` conserva o inventário
histórico do primeiro ZIP privado; não é o inventário final desta distribuição.
A publicação inclui 20 bancos SQLite sintéticos ausentes naquele ZIP, quatro
preparadores/verificadores necessários aos laboratórios e este guia de execução.
Foram executados 726 testes em 13 grupos no Windows/Python 3.12, com os ambientes
autoriais existentes. Não se trata de instalação independente nem de nova
execução de todas as campanhas de inferência.

O livro, o EPUB, capas e compositores editoriais não fazem parte deste pacote.
Todos os direitos reservados ao autor, com permissões para consulta e estudo;
componentes de terceiros conservam suas respectivas licenças. Este texto não
concede licença aberta sobre conteúdo de terceiros.
