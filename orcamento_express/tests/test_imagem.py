"""Testes do processamento de imagem e do upload de foto."""
import io

import cv2
import numpy as np
import pytest

import config
from services import image_processor, template_mapper


def _foto_ficha_sintetica(tmp_path, marcar=True):
    """Gera uma 'foto' de ficha: folha branca com um quadrado, sobre fundo escuro."""
    foto = np.full((1600, 1200, 3), 40, dtype=np.uint8)          # fundo escuro
    cv2.rectangle(foto, (100, 100), (1100, 1500), (255, 255, 255), -1)  # folha
    # quadrado de marcação impresso (nas coordenadas de referência ~ (100,200) 40x40)
    cv2.rectangle(foto, (190, 320), (240, 370), (0, 0, 0), 2)
    if marcar:
        cv2.line(foto, (195, 325), (235, 365), (0, 0, 0), 4)     # X do mecânico
        cv2.line(foto, (235, 325), (195, 365), (0, 0, 0), 4)
    caminho = tmp_path / "foto.jpg"
    cv2.imwrite(str(caminho), foto)
    return caminho


def test_imagem_invalida_nao_quebra(tmp_path):
    caminho = tmp_path / "lixo.jpg"
    caminho.write_bytes(b"isto nao e uma imagem")
    ficha = template_mapper.carregar_ficha("motor_fh_d13_parcial")
    with pytest.raises(image_processor.ErroProcessamentoImagem):
        image_processor.processar_foto(caminho, ficha)


def test_ficha_real_usa_layout_automatico(tmp_path):
    """A ficha real (gerada da planilha) já vem com coordenadas automáticas —
    não depende de calibração manual para funcionar."""
    caminho = _foto_ficha_sintetica(tmp_path)
    ficha = template_mapper.carregar_ficha("motor_fh_d13_parcial")
    assert ficha["calibrada"] is True
    assert ficha["calibrada_manualmente"] is False
    assert all(item["x"] is not None for item in ficha["itens"])

    resultado = image_processor.processar_foto(caminho, ficha)
    assert len(resultado["itens"]) == len(ficha["itens"])
    assert all(item["status"] in ("ok", "conferir") for item in resultado["itens"])
    assert (config.PASTA_PROCESSADAS / resultado["imagem_processada"]).exists()


def test_processa_ficha_sem_coordenadas_cai_no_modo_manual(tmp_path):
    """Uma ficha sem calibração (nenhuma coordenada) é processada no modo
    manual, sem quebrar — quem decide o que foi marcado é o usuário."""
    caminho = _foto_ficha_sintetica(tmp_path)
    ficha = {"tipo": "sem_layout", "ref_largura": 1000, "ref_altura": 1414,
            "calibrada": False,
            "itens": [{"peca": "Peça sem coordenada", "grupo": "", "x": None}]}
    resultado = image_processor.processar_foto(caminho, ficha)
    assert resultado["ficha_calibrada"] is False
    assert resultado["itens"][0]["status"] == "manual"


def test_detecta_marcacao_com_ficha_calibrada(tmp_path):
    caminho_marcada = _foto_ficha_sintetica(tmp_path, marcar=True)
    ficha = {
        "tipo": "teste", "ref_largura": 1000, "ref_altura": 1414, "calibrada": True,
        "itens": [{"peca": "Peça teste", "grupo": "G",
                   "x": 85, "y": 215, "w": 60, "h": 60}],
    }
    resultado = image_processor.processar_foto(caminho_marcada, ficha)
    assert resultado["folha_detectada"] is True
    assert resultado["itens"][0]["marcado"] is True

    caminho_vazia = _foto_ficha_sintetica(tmp_path, marcar=False)
    resultado_vazio = image_processor.processar_foto(caminho_vazia, ficha)
    assert resultado_vazio["itens"][0]["marcado"] is False


def test_upload_de_foto_pela_api(cliente_com_rascunho, tmp_path):
    caminho = _foto_ficha_sintetica(tmp_path)
    dados = {"foto": (io.BytesIO(caminho.read_bytes()), "ficha.jpg")}
    resposta = cliente_com_rascunho.post("/api/processar_foto", data=dados,
                                         content_type="multipart/form-data")
    assert resposta.status_code == 200
    assert resposta.get_json()["ok"] is True


def test_upload_formato_invalido(cliente_com_rascunho):
    dados = {"foto": (io.BytesIO(b"abc"), "arquivo.exe")}
    resposta = cliente_com_rascunho.post("/api/processar_foto", data=dados,
                                         content_type="multipart/form-data")
    assert resposta.status_code == 400
