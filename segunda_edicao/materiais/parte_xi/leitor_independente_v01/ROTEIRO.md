# Reprodução por leitor independente

Etapa pendente: nenhuma pessoa executou este roteiro nesta entrega. Use uma cópia identificada do livro2 e não reutilize a captura autoral como se fosse sua.

1. Registre commit, ambiente e consentimento no formulário. Leia preparacao.md da Parte XI.
2. Crie ambiente Python 3.12 com requirements-parte-xi.lock.txt; execute pip check. Prepare modelos com producao/preparar_modelos11.py e confira seus hashes.
3. Execute unittest testes.test_parte_xi -v. Os testes de captura usam o ensaio de engenharia histórico; isso não substitui sua execução.
4. Execute python -m laboratorios.parte_xi.campaign --out output/leitor_SEU_ID_v01. Nunca sobrescreva tentativas.
5. Execute python -m laboratorios.parte_xi.verify output/leitor_SEU_ID_v01. Guarde logs, manifestos e falhas.
6. Confira independentemente 800 pedidos de serving, 84 inferências, um recibo fault-43, migração bloqueada antes da conciliação, contrato antigo recusado e cinco épocas. Leia o conteúdo de negócio da ferramenta, além de isError.
7. Compare diferenças de decisões e conteúdo. PIDs, portas, tempos e memória não precisam ser iguais. Modelos podem produzir texto diferente; avalie o efeito sobre segurança e utilidade.
8. Registre adaptações e divergências. Outro host ou runtime é reprodução adaptada, com identidade própria. Não declare disponibilidade anual nem validação humana a partir desta execução.

Os arquivos permanecem locais até uma decisão explícita de compartilhamento; este roteiro não envia mensagens nem publica material.
