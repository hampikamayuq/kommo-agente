# Kommo Agente

Agente de atendimento para Kommo com FastAPI, integração com OpenAI/Anthropic, histórico em SQLite e máquina de estados para controlar quando o bot responde automaticamente.

---

## 1) Visão geral

Este serviço recebe webhooks do Kommo, identifica o tipo de evento e:

- responde mensagens de pacientes com IA;
- pausa resposta automática quando humano interno ou SalesBot assume;
- retoma automaticamente após timeout configurável;
- registra histórico para contexto de conversa;
- aplica ações no Kommo (nota, tag, tarefa).

Arquivos principais:

- `main.py`: API HTTP, roteamento de eventos e endpoints de controle.
- `agent.py`: prompt, chamada ao provedor de IA e parser de resposta JSON.
- `knowledge_base.py`: busca de contexto relevante em `knowledge_base.md`.
- `conversation.py`: banco SQLite (histórico + estado do lead).
- `kommo_client.py`: operações na API do Kommo.
- `config.py`: variáveis de ambiente e defaults.
- `tests/test_knowledge_base.py`: testes unitários da relevância da KB.

---

## 2) Requisitos

- Python 3.11+ (recomendado)
- Conta Kommo com token de API
- Chave OpenAI **ou** Anthropic

---

## 3) Instalação (passo a passo)

### 3.1 Clonar e entrar no projeto

```bash
git clone <url-do-repo>
cd kommo-agente
```

### 3.2 Criar ambiente virtual

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3.3 Instalar dependências

```bash
pip install -r requirements.txt
```

### 3.4 Criar arquivo `.env`

Crie um `.env` na raiz do projeto (mesmo nível do `main.py`) com base no exemplo abaixo.

---

## 4) Variáveis de ambiente (`.env`)

### Exemplo completo

```env
# Kommo
KOMMO_SUBDOMAIN=seu_subdominio
KOMMO_API_TOKEN=seu_token_kommo
KOMMO_BOT_USER_ID=11783975

# IA
AI_PROVIDER=openai
OPENAI_API_KEY=sua_openai_api_key
OPENAI_MODEL=gpt-4o-mini
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-6

# Segurança
WEBHOOK_SECRET=segredo_webhook
API_KEY=segredo_api_interna

# Serviço
PORT=8000
DB_PATH=conversations.db
MAX_HISTORY_TURNS=20

# Timeouts de retomada automática
HUMAN_TIMEOUT_HOURS=4
BOT_TIMEOUT_MINUTES=3
```

### Referência das variáveis

- `KOMMO_SUBDOMAIN`: subdomínio da conta Kommo (sem `https://` e sem `.kommo.com`).
- `KOMMO_API_TOKEN`: token bearer para API v4 do Kommo.
- `KOMMO_BOT_USER_ID`: ID do SalesBot para detectar mensagens automáticas.
- `AI_PROVIDER`: `openai` ou `anthropic`.
- `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`: chave do provedor selecionado.
- `OPENAI_MODEL` / `ANTHROPIC_MODEL`: modelo usado para resposta.
- `WEBHOOK_SECRET`: segredo validado no payload do webhook.
- `API_KEY`: chave para endpoints manuais (`/send`, `/resume`, `/pause`).
- `PORT`: porta HTTP da aplicação.
- `DB_PATH`: caminho do SQLite local.
- `MAX_HISTORY_TURNS`: quantidade de turnos (user+assistant) mantida no contexto.
- `HUMAN_TIMEOUT_HOURS`: tempo de pausa após intervenção humana.
- `BOT_TIMEOUT_MINUTES`: tempo de pausa após mensagem do SalesBot.

---

## 5) Executar localmente

### Desenvolvimento

```bash
python main.py
```

ou

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

### Health check

```bash
curl http://localhost:8000/health
```

---

## 6) Endpoints e exemplos

## `POST /webhook`

Endpoint principal para eventos do Kommo (form data).

### Exemplo: mensagem de paciente

```bash
curl -X POST http://localhost:8000/webhook \
  -F "secret=segredo_webhook" \
  -F "message[add][0][element_id]=12345" \
  -F "message[add][0][element_type]=1" \
  -F "message[add][0][created_by]=0" \
  -F "message[add][0][text]=Olá, quero agendar uma consulta"
```

### Exemplo: novo lead

```bash
curl -X POST http://localhost:8000/webhook \
  -F "secret=segredo_webhook" \
  -F "leads[add][0][id]=12345"
```

### Exemplo: mudança de status

```bash
curl -X POST http://localhost:8000/webhook \
  -F "secret=segredo_webhook" \
  -F "leads[status][0][id]=12345" \
  -F "leads[status][0][status_id]=999"
```

## `POST /send`

Envia mensagem manual para um lead.

```bash
curl -X POST http://localhost:8000/send \
  -H "Content-Type: application/json" \
  -H "x-api-key: segredo_api_interna" \
  -d '{"lead_id":"12345","message":"Olá!"}'
```

## `POST /resume/{lead_id}`

Reativa agente para o lead.

```bash
curl -X POST http://localhost:8000/resume/12345 -H "x-api-key: segredo_api_interna"
```

## `POST /pause/{lead_id}`

Pausa agente para o lead.

```bash
curl -X POST http://localhost:8000/pause/12345 -H "x-api-key: segredo_api_interna"
```

---

## 7) Testes

Rodar suíte de testes:

```bash
python -m pytest -q
```

Atualmente cobre principalmente a lógica de relevância da KB (`knowledge_base.py`).

---

## 8) Deploy (instruções práticas)

## Opção A: systemd + uvicorn (VM Linux)

1. Instale dependências e configure `.env`.
2. Crie um serviço systemd apontando para `uvicorn main:app`.
3. Configure restart automático (`Restart=always`).
4. Publique com Nginx/Caddy como reverse proxy com HTTPS.

Comando típico de execução do app no servidor:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

## Opção B: Docker

- Empacote o projeto em imagem Python slim.
- Monte `.env` via secrets/env vars da plataforma.
- Exponha a porta `8000`.
- Configure health check via `/health`.

> Este repositório inclui `Dockerfile` e `render.yaml` prontos para deploy no Render.

---

## 9) Manutenção operacional

### Rotina recomendada

- Verificar logs diariamente para erros de integração Kommo/IA.
- Validar tamanho e rotação do arquivo SQLite (`DB_PATH`).
- Revisar custos/token usage do modelo periodicamente.
- Revisar qualidade da `knowledge_base.md` com novas perguntas reais.

### Atualização de dependências

```bash
pip install -U -r requirements.txt
python -m pytest -q
```

### Backup

- Faça backup regular de `conversations.db` (ou do caminho definido em `DB_PATH`).
- Mantenha histórico de versão do `.env` **sem** segredos em texto puro.

---

## 10) Troubleshooting

### 401 no Kommo

- Verifique `KOMMO_API_TOKEN` e `KOMMO_SUBDOMAIN`.
- Confirme permissões do token na API v4.

### Webhook retorna `forbidden`

- Confira se `secret` enviado no form data é igual ao `WEBHOOK_SECRET`.

### Erro de autenticação nos endpoints manuais

- Confirme header `x-api-key` igual a `API_KEY`.

### Agente não responde mensagem do paciente

- Verifique se lead está em estado `paused_human` ou `bot_scheduling`.
- Aguarde timeout (`HUMAN_TIMEOUT_HOURS` / `BOT_TIMEOUT_MINUTES`) ou use `/resume/{lead_id}`.

### IA responde fora de formato

- O parser possui fallback para texto bruto, mas é recomendado revisar prompt e modelo em `agent.py`.

### Falha ao enviar mensagem no Kommo

- `send_message` tenta `/messages`; em algumas contas cai para nota (`note_type=4`) como fallback.

---

## 11) Melhorias futuras sugeridas

- Adicionar testes para webhook/endpoints (`TestClient`).
- Adicionar `Dockerfile` e `docker-compose` oficial.
- Implementar métricas (latência, taxa de erro, intents).
- Persistir deduplicação em cache distribuído (para múltiplas réplicas).
