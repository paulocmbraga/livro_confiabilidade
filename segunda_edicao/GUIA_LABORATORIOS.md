# Guia dos materiais da segunda edição

Paulo Cesar Braga. Use esta pasta como raiz de trabalho. Ela corresponde à pasta
`confiabilidade_ia_2ed` citada no livro. O material da primeira edição permanece
na raiz do repositório; seus módulos e ambientes não devem ser misturados.

## Instalação e escolhas de ambiente

O ambiente autoral é Windows x64 e Python 3.12. Os locks conservam versões
efetivamente utilizadas. Não há afirmação de execução em Linux/macOS. Os
laboratórios de inferência usam CPU e modelos locais; não exigem API paga.
Downloads de modelos e imagens Docker requerem rede e espaço adicional.

Crie um ambiente separado para a parte desejada. Exemplo da Parte III:

```powershell
py -3.12 -m venv .venv-parte-iii
& .venv-parte-iii/Scripts/python.exe -m pip install -r requirements-l11.txt
& .venv-parte-iii/Scripts/python.exe -m pip check
& .venv-parte-iii/Scripts/python.exe -m unittest testes.test_parte_iii testes.test_l11 -v
```

Nos comandos abreviados abaixo, `python` significa o executável do ambiente
correto, por exemplo `& .venv-parte-iii/Scripts/python.exe` no PowerShell.

| Parte / laboratório | Perfil Python | Para repetir a campanha completa |
| --- | --- | --- |
| I, capítulos 1–4 | Biblioteca padrão | Processos locais, HTTP/SQLite sintéticos |
| II, capítulos 5–8 | Biblioteca padrão | Treino pequeno e simulação autoral |
| III e L11 | `requirements-l11.txt` | Preparador de modelos 11 para L11 |
| IV, capítulos 13–16 | `requirements-l11.txt` | Treino/calibração locais |
| V, capítulos 17–20 | `requirements-parte-v.lock.txt` | Preparadores 11 e Parte V; OCR/Whisper |
| VI e L23 | `requirements.lock.txt` | PyTorch CPU, embedding, reranker e geradores |
| VII, L25/L27/L28 | `requirements-parte-vii.lock.txt` | Preparador 11; serviços MCP/A2A locais |
| L26 | `requirements-l26.txt` | Docker/PostgreSQL fixado pela bancada |
| VIII, capítulos 29–32 | `requirements-parte-viii.lock.txt` | Docker/PostgreSQL/Redis |
| IX, capítulos 33–36 | `requirements-parte-ix.lock.txt` | Preparador 11 e Collector em Docker |
| X, capítulos 37–40 | `requirements-parte-x.lock.txt` | Biblioteca padrão, cenários sintéticos |
| XI, capítulos 41–44 | `requirements-parte-xi.lock.txt` | Preparador 11 e serviços locais |
| Apêndices | Biblioteca padrão | Campanha de consulta sem modelos |

Os locks não são intercambiáveis. Em especial, o ambiente MCP/A2A da Parte VII
não inclui automaticamente Psycopg do L26. Conserve os perfis separados.

## Preparar modelos

Estes quatro scripts em `producao/` são ferramentas de laboratório, incluídas
porque os comandos do livro dependem delas. Os compositores de PDF/EPUB não
fazem parte do repositório público.

Para L11, Partes III, V, VII, IX e XI, no ambiente correspondente:

```powershell
python producao/preparar_modelos11.py --runtime .modelos/l11
```

O script verifica os hashes dos pesos Qwen/SmolLM2 e do runtime llama.cpp.
Para OCR/transcrição da Parte V, depois de instalar o lock específico:

```powershell
python producao/preparar_modelos_parte_v.py
```

Para L23 e Parte VI, prepare o ambiente separado:

```powershell
py -3.12 -m venv .venv
& .venv/Scripts/python.exe -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
& .venv/Scripts/python.exe -m pip install -r requirements.lock.txt
& .venv/Scripts/python.exe -m pip check
& .venv/Scripts/python.exe producao/preparar_modelos23.py --runtime .modelos/l11
& .venv/Scripts/python.exe producao/preparar_modelos11.py --runtime .modelos/l11
```

No piloto L23, o argumento `--runtime` da campanha deve apontar para essa pasta
escolhida. A Parte VI usa `.modelos/l11`. Os locks em `materiais/` identificam
artefatos, revisões e fontes. Pesos e executáveis não são redistribuídos aqui.

## Conferir as capturas sem repetir inferência

`conferir_pacote.py` usa apenas biblioteca padrão e confere os arquivos da
distribuição. As verificações relacionais abaixo examinam as capturas autorais
com o ambiente indicado na tabela.

```powershell
python conferir_pacote.py
python -m laboratorios.parte_i.verify output/parte_i_principal_v01
python -m laboratorios.parte_ii.verify output/parte_ii_principal_v01
python -m laboratorios.parte_iii.verify output/parte_iii_principal_v02
python -m laboratorios.l11.verify output/l11_principal_v01
python -m laboratorios.parte_iv.verify output/parte_iv_principal_v01
python -m laboratorios.parte_v.verify --out output/parte_v_principal_v02
python -m laboratorios.parte_vi.verify --out output/parte_vi_principal_v01
python -m laboratorios.l23.campaign verify --out output/l23_principal_v01
python producao/verificar_capturas_parte_vii.py
python -m laboratorios.l26.verify output/l26_principal_v02
python -m laboratorios.parte_viii.verify output/parte_viii_principal_v02
python -m laboratorios.parte_ix.verify output/parte_ix_principal_v01
python -m laboratorios.parte_x.campaign verify --out output/parte_x_principal_v01
python -m laboratorios.parte_xi.verify output/parte_xi_principal_v01
```

Execute cada linha no perfil correspondente, não todas no mesmo ambiente.
Conferir os arquivos não equivale a obter novas respostas de modelo ou a
reproduzir o experimento em outro computador. Os bancos SQLite sintéticos são
parte da evidência; não os apague nem os substitua por bancos vazios.

## Testes e novas campanhas

As suítes têm os nomes `testes.test_parte_i` até `testes.test_parte_xi`, além
de `testes.test_l11`, `testes.test_l23`, `testes.test_l26`,
`testes.test_capture_integrity` e `testes.test_apendices`. Use `python -m unittest`
no perfil adequado. Os testes usam cópias temporárias para mutações e alguns
iniciam processos locais; não substituem todas as campanhas de inferência.

Comece por um ensaio leve:

```powershell
python -m unittest testes.test_apendices -v
python -m laboratorios.apendices.campaign --out output/minha_consulta_v01
```

Para uma parte, consulte `python -m laboratorios.parte_i.campaign --help`,
trocando o módulo pela parte escolhida. A Parte X e o piloto L23 usam a ação
`run` antes de `--out`; a Parte VII tem também `protocol_campaign` para L27.
As demais preparações e o alcance dos resultados estão nos capítulos do livro.
Sempre use uma pasta nova: não sobrescreva as capturas autorais.

## Parte VII

Após instalar seu lock e preparar os modelos:

```powershell
python -m laboratorios.parte_vii.campaign --out output/minha_parte_vii
python -m laboratorios.parte_vii.protocol_campaign --out output/meus_protocolos_v01
python producao/verificar_capturas_parte_vii.py
```

O piloto L26 possui ambiente próprio e captura própria. As credenciais
`lab-mcp`, `lab-a2a` e `lab-callback` são fixtures públicas de loopback, sem valor
de autenticação em produção. Docker só é necessário nas campanhas que o usam;
essas bancadas trabalham com contêineres e dados sintéticos próprios. Não as
aponte para serviços, bancos ou filas de produção.

## Evidência, avaliação humana e licenças

Capturas anteriores e diagnósticos são mantidos para rastreabilidade. Use as
versões principais acima, sem somar execuções de versões diferentes. Os pacotes
humanos distinguem participantes e coordenação; não distribua a chave de
adjudicação aos participantes antes dos julgamentos. Coleta humana e reprodução
independente continuam pendentes. Nomes de revisão não são prova de aprovação.

O livro, os manuscritos, o EPUB, o PDF, as capas, os modelos e os ambientes
virtuais não acompanham este material. © 2026 Paulo Cesar Braga. Nenhuma licença
de código aberto é presumida; componentes de terceiros mantêm suas licenças.
