"""Testes de geração de PDF e histórico local (SQLite)."""
import config
from database.local_history import HistoricoLocal
from services import pdf_generator


ORCAMENTO_EXEMPLO = {
    "numero": "123", "cliente": "Cliente Teste", "placa": "ABC1D23",
    "veiculo": "VW Gol 1.6", "data": "07/07/2026", "consultor": "João",
    "tipo_ficha": "motor", "gerado_em": "07/07/2026 10:00",
    "observacoes": "Cliente traz o cabeçote.",
    "pecas": [
        {"peca": "Junta do cabeçote", "quantidade": 1, "grupo": "Cabeçote", "origem": "estoque"},
        {"peca": "Bronzinas de biela", "quantidade": 4, "grupo": "Bloco", "origem": "estoque"},
        {"peca": "Óleo do motor", "quantidade": 4, "grupo": "Outros", "origem": "cliente"},
    ],
}


def test_gerar_pdf_cria_arquivo():
    nome = pdf_generator.gerar_pdf(ORCAMENTO_EXEMPLO)
    caminho = config.PASTA_PDFS / nome
    assert caminho.exists()
    assert caminho.stat().st_size > 1000
    assert caminho.read_bytes()[:5] == b"%PDF-"


def test_mensagem_whatsapp():
    texto = pdf_generator.mensagem_whatsapp(ORCAMENTO_EXEMPLO)
    assert "OS 123" in texto
    assert "Junta do cabeçote" in texto
    assert "Cliente deve trazer" in texto
    assert "Óleo do motor" in texto


def test_historico_salva_e_lista():
    historico = HistoricoLocal(config.BANCO_LOCAL)
    historico.registrar_pdf("123", "Cliente Teste", "ABC1D23", "Gol",
                            "motor", "orcamento_123.pdf", "obs")
    registros = historico.listar()
    assert len(registros) == 1
    assert registros[0]["numero_os"] == "123"
    assert registros[0]["arquivo_pdf"] == "orcamento_123.pdf"


def test_rascunho_salva_e_carrega():
    historico = HistoricoLocal(config.BANCO_LOCAL)
    historico.salvar_rascunho("abc", {"numero": "9", "tipo_ficha": "motor"})
    assert historico.carregar_rascunho("abc")["numero"] == "9"
    historico.salvar_rascunho("abc", {"numero": "10", "tipo_ficha": "motor"})
    assert historico.carregar_rascunho("abc")["numero"] == "10"
    assert historico.carregar_rascunho("nao-existe") is None


def test_fluxo_completo_gerar_pdf_pela_api(cliente_com_rascunho):
    resposta = cliente_com_rascunho.post("/api/gerar_pdf", json={
        "pecas": [{"peca": "Junta do cabeçote", "quantidade": 1,
                   "grupo": "Cabeçote", "origem": "estoque"}],
        "observacoes": "teste"})
    dados = resposta.get_json()
    assert dados["ok"] is True
    # o PDF aparece no histórico
    assert b"orcamento_123" in cliente_com_rascunho.get("/historico").data


def test_gerar_pdf_sem_pecas_e_bloqueado(cliente_com_rascunho):
    resposta = cliente_com_rascunho.post("/api/gerar_pdf",
                                         json={"pecas": [], "observacoes": ""})
    assert resposta.status_code == 400
