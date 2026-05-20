import importlib


def test_get_relevant_context_returns_top_sections(monkeypatch):
    kb = importlib.import_module("knowledge_base")

    monkeypatch.setattr(
        kb,
        "_sections",
        [
            ("agendamento", "**Agendamento**\nAgendar consulta presencial", {"agendar", "consulta", "presencial"}),
            ("horarios", "**Horários**\nAtendimento de segunda a sexta", {"atendimento", "segunda", "sexta"}),
            ("pagamento", "**Pagamento**\nAceitamos pix e cartão", {"aceitamos", "pix", "cartão"}),
        ],
    )

    result = kb.get_relevant_context("Quero agendar consulta e saber atendimento")

    assert result is not None
    assert "**Agendamento**" in result
    assert "**Horários**" in result


def test_get_relevant_context_returns_none_when_no_overlap(monkeypatch):
    kb = importlib.import_module("knowledge_base")
    monkeypatch.setattr(kb, "_sections", [("x", "body", {"foo"})])

    assert kb.get_relevant_context("bar baz") is None
