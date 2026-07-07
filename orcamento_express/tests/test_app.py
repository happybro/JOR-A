"""Testes das rotas principais do app Flask."""


def test_app_sobe_sem_erro(cliente):
    assert cliente is not None


def test_rota_inicial_responde(cliente):
    resposta = cliente.get("/")
    assert resposta.status_code == 200
    assert "Orçamento Express".encode() in resposta.data


def test_telas_principais_respondem(cliente):
    for rota in ["/novo", "/historico", "/configuracoes", "/calibracao/motor_fh_d13_parcial"]:
        assert cliente.get(rota).status_code == 200, rota


def test_captura_sem_rascunho_redireciona(cliente):
    resposta = cliente.get("/captura")
    assert resposta.status_code == 302  # volta para /novo


def test_busca_os_modo_demo(cliente):
    resposta = cliente.post("/api/buscar_os", json={"numero": "123"})
    dados = resposta.get_json()
    assert dados["encontrado"] is True
    assert dados["origem"] == "demo"
    assert dados["cliente"]


def test_busca_os_sem_numero(cliente):
    dados = cliente.post("/api/buscar_os", json={"numero": ""}).get_json()
    assert dados["encontrado"] is False


def test_iniciar_orcamento_exige_tipo(cliente):
    resposta = cliente.post("/api/iniciar_orcamento", json={"numero": "1", "tipo_ficha": "aviao"})
    assert resposta.status_code == 400


def test_conferencia_manual_sem_foto(cliente_com_rascunho):
    resposta = cliente_com_rascunho.get("/conferencia")
    assert resposta.status_code == 200
    assert "Confira os itens".encode() in resposta.data


def test_ficha_imprimir_gera_pdf(cliente_com_rascunho):
    resposta = cliente_com_rascunho.get("/ficha/motor_fh_d13_parcial/imprimir")
    assert resposta.status_code == 302
    assert "/arquivos/pdf/" in resposta.headers["Location"]


def test_calibracao_tipo_desconhecido_redireciona(cliente):
    resposta = cliente.get("/calibracao/nao-existe")
    assert resposta.status_code == 302
