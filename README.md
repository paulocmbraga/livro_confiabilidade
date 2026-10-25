# Engenharia de Confiabilidade para Sistemas de IA — laboratórios

## Escolha a edição

- **[Segunda edição — revista e ampliada](segunda_edicao/README.md):** materiais dos 44 capítulos e dos apêndices A a H, com guia de ambientes, código, testes e capturas autorais.
- **Primeira edição:** materiais preservados na raiz deste repositório. As instruções abaixo continuam correspondendo à primeira edição.

Cada edição tem sua própria raiz de trabalho. Para a segunda edição, entre em `segunda_edicao` antes de executar os comandos do seu guia.

Material de apoio ao livro de Paulo Cesar Braga: L00 a L24, código Python, testes, oito capturas canônicas e modelos reutilizáveis.

## Preparação

Use Python 3.12, somente biblioteca padrão. A reprodução editorial utiliza Windows; os caminhos alternativos de Linux/macOS não significam ensaio nesses sistemas.

```powershell
git clone https://github.com/paulocmbraga/livro_confiabilidade.git confiabilidade_ia
cd confiabilidade_ia
python -m venv --without-pip .venv
.venv\Scripts\python.exe -m unittest discover -s testes -v
.venv\Scripts\python.exe conferir_capturas.py
```

Se recebeu o ZIP, extraia sua pasta `confiabilidade_ia` e execute os comandos a partir dela. Não é necessário instalar pacotes nem configurar chaves de provedor. Não execute os comandos de clone sobre a pasta já extraída.

## Conferir e reproduzir

`conferir_capturas.py` verifica as oito capturas fornecidas e seus vínculos com os módulos. Para gerar resultados novos, utilize uma pasta ainda inexistente:

```powershell
.venv\Scripts\python.exe -m laboratorios.parte_i --saida output/minha_parte_i
.venv\Scripts\python.exe -m laboratorios.parte_i --saida output/minha_parte_i --conferir
```

| Laboratórios | Módulo | Captura canônica |
| --- | --- | --- |
| L00–L03 | laboratorios.parte_i | output/parte_i_v03 |
| L04 | laboratorios.piloto04 | output/piloto04_v02 |
| L05–L08 | laboratorios.parte_ii | output/parte_ii_v03 |
| L09–L12 | laboratorios.parte_iii | output/parte_iii_v01 |
| L13, L14, L16 | laboratorios.parte_iv | output/parte_iv_v02 |
| L15 | laboratorios.piloto15 | output/piloto15_v02 |
| L17–L20 | laboratorios.parte_v | output/parte_v_v01 |
| L21–L24 | laboratorios.parte_vi | output/parte_vi_v02 |

Consulte `--help` de cada módulo antes de gerar uma campanha. As partes IV e VI também leem evidências anteriores; preserve todas as capturas. O laboratório 15 usa processos, HTTP em loopback e SQLite. Não envia operações a serviços comerciais.

## Limites da evidência

Entradas, identidades, respostas e rubricas preparadas não representam inferência de LLM ou julgamento de participantes humanos. Medições locais não são estimativas de produção. As trilhas M, H e O planejadas nas fichas não devem ser lidas como campanhas concluídas. As durações e os caminhos nas capturas pertencem ao ambiente original.

O livro, EPUB, PDF, capas e fontes editoriais não fazem parte deste pacote. Comandos `producao/*` citados no livro são ferramentas editoriais privadas; não são necessários para executar os laboratórios. O verificador aqui incluído funciona sem os manuscritos.

`materiais/fichas_reproducao.json` conserva hashes e referências dos manuscritos para rastreabilidade; os manuscritos não estão incluídos. Os modelos são pontos de partida e não concedem autoridade nem constituem adaptadores prontos para produção.

© 2026 Paulo Cesar Braga. Os termos de licença de redistribuição ainda devem ser definidos pelo autor; nenhuma licença de código aberto é presumida.
