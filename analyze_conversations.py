"""
analyze_conversations.py — Analisa exports JSON do WhatsApp do Kommo.

Uso:
  python analyze_conversations.py --dir /caminho/para/jsons
  python analyze_conversations.py --dir . --output qa_pairs.json
  python analyze_conversations.py --dir . --summary

Gera:
  - Resumo estatístico (intenções, horários, palavras-chave)
  - Pares Q&A por tópico para enriquecer a base de conhecimento
  - Arquivo JSON com pares prontos para fine-tuning ou few-shot examples
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


INTENT_KEYWORDS = {
    "agendar":        ["agendar", "marcar", "consulta", "agendamento", "horário", "disponível"],
    "valor":          ["valor", "preço", "quanto", "custa", "custo"],
    "convenio":       ["convenio", "convênio", "plano", "reembolso", "amil", "unimed", "bradesco"],
    "duvida_clinica": ["micose", "queda", "cabelo", "psoríase", "dermatite", "unha", "pele",
                       "mancha", "acne", "verruga", "cisto", "pinta", "lipoma", "hidradenite"],
    "retorno":        ["retorno", "voltar", "acompanhamento"],
    "cancelar":       ["cancelar", "desmarcar", "remarcar", "adiar", "imprevisto"],
    "localizacao":    ["endereço", "localização", "onde fica", "estacionamento", "vaga"],
    "teleconsulta":   ["online", "teleconsulta", "video", "remota"],
    "pagamento":      ["pix", "cartão", "crédito", "débito", "pagamento", "pagar"],
    "cadastro":       ["cpf", "nome completo", "data de nascimento", "e-mail", "cep"],
}

STOP_WORDS = {
    "a","o","e","de","da","do","para","que","com","em","se","me","por","um","uma",
    "na","no","ao","às","os","as","é","não","sim","já","mais","mas","ou","foi",
    "ser","ter","tem","eu","você","oi","olá","boa","bom","tarde","noite","dia",
    "pode","teria","há","aqui","isso","essa","esse","tudo","bem","como","quando",
    "qual","queria","gostaria","quero","então","ainda","sobre","muito","obrigada",
    "obrigado","favor","estou","está","este","esta","pelo","pela","pelos","pelas",
}


def load_messages(directory: Path) -> list[dict]:
    msgs = []
    for f in sorted(directory.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        batch = data.get("mensagens", [])
        msgs.extend(batch)
    return msgs


def classify_intent(text: str) -> str:
    tl = text.lower()
    for intent, kws in INTENT_KEYWORDS.items():
        if any(k in tl for k in kws):
            return intent
    return "outro"


def build_threads(msgs: list[dict]) -> dict[int, list[dict]]:
    threads: dict[int, list[dict]] = defaultdict(list)
    for m in msgs:
        threads[m["Chat_ID"]].append(m)
    return threads


def extract_qa_pairs(threads: dict, max_per_topic: int = 20) -> dict[str, list[dict]]:
    """Find patient-question → clinic-answer pairs grouped by topic."""
    topic_qa: dict[str, list[dict]] = defaultdict(list)
    for msgs in threads.values():
        sorted_msgs = sorted(msgs, key=lambda x: x["Data_Hora_Completa"])
        for i, msg in enumerate(sorted_msgs):
            if msg["De_Mim"] != "Não" or len(msg["Mensagem"]) < 15:
                continue
            intent = classify_intent(msg["Mensagem"])
            if len(topic_qa[intent]) >= max_per_topic:
                continue
            for j in range(i + 1, min(i + 5, len(sorted_msgs))):
                nxt = sorted_msgs[j]
                if nxt["De_Mim"] == "Sim" and len(nxt["Mensagem"]) > 20:
                    topic_qa[intent].append({
                        "question": msg["Mensagem"],
                        "answer": nxt["Mensagem"],
                        "chat_id": msg["Chat_ID"],
                        "timestamp": msg["Data_Hora_Completa"],
                    })
                    break
    return dict(topic_qa)


def compute_stats(msgs: list[dict]) -> dict:
    from_clinic = [m for m in msgs if m["De_Mim"] == "Sim"]
    from_patient = [m for m in msgs if m["De_Mim"] == "Não"]

    # Hourly distribution
    hour_dist: Counter = Counter()
    for m in from_patient:
        hour_dist[int(m["Hora"][:2])] += 1

    # Intent distribution
    intent_dist: Counter = Counter()
    for m in from_patient:
        intent_dist[classify_intent(m["Mensagem"])] += 1

    # Top patient keywords
    all_text = " ".join(m["Mensagem"] for m in from_patient if len(m["Mensagem"]) > 5).lower()
    words = re.findall(r"\b[a-záéíóúãõêâôü]{4,}\b", all_text)
    keyword_freq = Counter(w for w in words if w not in STOP_WORDS)

    # Top clinic templates (by first 60 chars)
    template_counter: Counter = Counter()
    templates: dict = {}
    for m in from_clinic:
        text = m["Mensagem"].strip()
        if len(text) > 30:
            key = text[:60]
            template_counter[key] += 1
            if key not in templates:
                templates[key] = text

    return {
        "total_messages": len(msgs),
        "from_clinic": len(from_clinic),
        "from_patient": len(from_patient),
        "unique_chats": len(set(m["Chat_ID"] for m in msgs)),
        "intent_distribution": dict(intent_dist.most_common()),
        "patient_keywords_top20": dict(keyword_freq.most_common(20)),
        "hourly_patient_messages": dict(sorted(hour_dist.items())),
        "top_clinic_templates": [
            {"count": c, "preview": templates[k][:200]}
            for k, c in template_counter.most_common(10)
        ],
    }


def print_summary(stats: dict, qa_pairs: dict) -> None:
    print(f"\n{'='*60}")
    print("RESUMO DAS CONVERSAS — CLÍNICA QARA")
    print(f"{'='*60}")
    print(f"Total de mensagens : {stats['total_messages']:,}")
    print(f"Da clínica         : {stats['from_clinic']:,}")
    print(f"Dos pacientes      : {stats['from_patient']:,}")
    print(f"Chats únicos       : {stats['unique_chats']:,}")

    print(f"\n{'─'*40}")
    print("INTENÇÕES DOS PACIENTES:")
    for intent, count in sorted(stats["intent_distribution"].items(), key=lambda x: -x[1]):
        bar = "█" * min(count // 100, 30)
        print(f"  {intent:<20} {bar} {count}")

    print(f"\n{'─'*40}")
    print("HORÁRIO DE PICO DOS PACIENTES:")
    for h, c in sorted(stats["hourly_patient_messages"].items()):
        bar = "█" * (c // 80)
        print(f"  {h:02d}h: {bar} {c}")

    print(f"\n{'─'*40}")
    print("PALAVRAS-CHAVE MAIS USADAS PELOS PACIENTES:")
    for word, count in list(stats["patient_keywords_top20"].items())[:15]:
        print(f"  {word}: {count}")

    print(f"\n{'─'*40}")
    print(f"PARES Q&A EXTRAÍDOS: {sum(len(v) for v in qa_pairs.values())}")
    for topic, pairs in sorted(qa_pairs.items(), key=lambda x: -len(x[1])):
        print(f"  {topic}: {len(pairs)} pares")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analisa conversas WhatsApp da Clínica Qara")
    parser.add_argument("--dir", default=".", help="Diretório com arquivos JSON")
    parser.add_argument("--output", default=None, help="Salvar pares Q&A em arquivo JSON")
    parser.add_argument("--summary", action="store_true", default=True)
    parser.add_argument("--max-qa", type=int, default=20, help="Max pares Q&A por tópico")
    args = parser.parse_args()

    directory = Path(args.dir)
    print(f"Carregando mensagens de: {directory.resolve()}")

    msgs = load_messages(directory)
    if not msgs:
        print("Nenhuma mensagem encontrada. Verifique o diretório.")
        return

    print(f"{len(msgs):,} mensagens carregadas.")
    threads = build_threads(msgs)
    stats = compute_stats(msgs)
    qa_pairs = extract_qa_pairs(threads, max_per_topic=args.max_qa)

    if args.summary:
        print_summary(stats, qa_pairs)

    if args.output:
        output_path = Path(args.output)
        output_data = {
            "stats": stats,
            "qa_pairs": qa_pairs,
        }
        output_path.write_text(json.dumps(output_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nResultados salvos em: {output_path}")


if __name__ == "__main__":
    main()
