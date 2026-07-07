"""Configuração dos testes: pastas temporárias e app Flask de teste."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402


@pytest.fixture(autouse=True)
def ambiente_temporario(tmp_path, monkeypatch):
    """Redireciona todas as pastas de trabalho para diretórios temporários."""
    monkeypatch.setattr(config, "PASTA_UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(config, "PASTA_PROCESSADAS", tmp_path / "processed")
    monkeypatch.setattr(config, "PASTA_PDFS", tmp_path / "pdfs")
    monkeypatch.setattr(config, "PASTA_LOGS", tmp_path / "logs")
    monkeypatch.setattr(config, "BANCO_LOCAL", tmp_path / "data" / "teste.db")
    monkeypatch.setattr(config, "MECAUTO_MODO_DEMO", True)
    config.garantir_pastas()
    yield tmp_path


@pytest.fixture()
def cliente():
    from app import criar_app
    app = criar_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture()
def cliente_com_rascunho(cliente):
    """Cliente com um orçamento iniciado (rascunho na sessão)."""
    resposta = cliente.post("/api/iniciar_orcamento", json={
        "numero": "123", "cliente": "Teste", "placa": "ABC1D23",
        "veiculo": "Volvo FH 540", "tipo_ficha": "motor_fh_d13_parcial"})
    assert resposta.get_json()["ok"]
    return cliente
