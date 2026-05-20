# Kommo Agente

Agente de atendimento para Kommo (FastAPI) com integração a provedores de IA (OpenAI/Anthropic), máquina de estados por lead e contexto dinâmico via base de conhecimento.

## Status de atualização

Este repositório está atualizado com as últimas melhorias implementadas, incluindo:

- otimização da busca de contexto da base de conhecimento com pré-cálculo de tokens por seção;
- testes automatizados para garantir o comportamento da relevância da KB;
- fluxo de webhook com controle de estado (`active`, `paused_human`, `bot_scheduling`).

## Estrutura principal

- `main.py`: endpoints FastAPI (`/webhook`, `/send`, `/resume`, `/pause`, `/health`) e roteamento de eventos do Kommo.
- `agent.py`: montagem do prompt, chamada ao provedor de IA e parsing da resposta JSON.
- `knowledge_base.py`: carregamento de `knowledge_base.md` e seleção de seções relevantes por sobreposição de palavras.
- `conversation.py`: persistência SQLite de histórico e estado dos leads.
- `kommo_client.py`: chamadas à API Kommo.
- `tests/test_knowledge_base.py`: testes unitários da relevância da KB.

## Testes

```bash
python -m pytest -q
```

## Dependências

Instale com:

```bash
pip install -r requirements.txt
```

## Observação

Se quiser, posso também gerar um `README` mais detalhado com:
- variáveis de ambiente (`.env`),
- instruções de deploy,
- exemplos de payload do webhook,
- troubleshooting.
