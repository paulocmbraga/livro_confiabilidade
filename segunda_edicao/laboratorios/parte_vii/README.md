# L25, L27 e L28 — Parte VII

Leia o [guia dos laboratórios](../../GUIA_LABORATORIOS.md#parte-vii) para instalar, executar e conferir. L26 permanece em ../l26 e usa sua captura histórica.

`campaign.py`: 48 episódios L25 e 48 L28; inferência real local, sem API paga. `destination.py`: processo HTTP/SQLite da reserva didática. `protocol_server.py` e `protocol_campaign.py`: SDKs MCP/A2A reais e callback HTTP da aplicação. `core.py`: contratos, quórum e contabilidade. `verify.py`: observador offline. `waiter.py`: processo deliberadamente bloqueado antes da inferência.

Capturas finais: output/parte_vii_principal_v02 e output/parte_vii_protocolos_v02. Os manifestos preservam solicitações, respostas, SQLite, estado final e logs. Não altere capturas para fazer a conferência passar. Cada repetição requer diretório novo. Credenciais lab-mcp, lab-a2a e lab-callback são fixtures públicas de loopback, sem valor de autenticação de produção.

O redutor de callbacks pressupõe eventos validados; sua memória e o TaskStore A2A não sobrevivem a reinício. Push nativo A2A não foi ensaiado. O destino L25 não substitui o contrato transacional L26. Modelos, runtime e ambientes ficam fora do Git; veja os locks.
