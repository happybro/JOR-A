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


# ---------------------------------------------------------------------------
# Detecção adaptativa: robustez sob condições reais de foto (iluminação,
# marca fraca, borrão, folha em branco). Ver services/image_processor.py.
# ---------------------------------------------------------------------------

def _folha_com_marcas(ficha, indices_marcados, intensidade=(0, 0, 0), espessura=3):
    """Monta a folha em branco (impressa pelo próprio sistema) já com X nos
    índices indicados, no espaço de referência da ficha."""
    ref_w, ref_h = ficha["ref_largura"], ficha["ref_altura"]
    folha = np.full((ref_h, ref_w, 3), 255, dtype=np.uint8)
    for item in ficha["itens"]:
        if item.get("x") is not None:
            cv2.rectangle(folha, (item["x"], item["y"]),
                          (item["x"] + item["w"], item["y"] + item["h"]), (0, 0, 0), 2)
    for i in indices_marcados:
        item = ficha["itens"][i]
        x, y, w, h = item["x"], item["y"], item["w"], item["h"]
        cv2.line(folha, (x + 2, y + 2), (x + w - 2, y + h - 2), intensidade, espessura)
        cv2.line(folha, (x + w - 2, y + 2), (x + 2, y + h - 2), intensidade, espessura)
    return folha


def _compor_foto(tmp_path, folha, ref_w, ref_h, nome, rotacao=2, gradiente=False, blur=0):
    """Simula uma foto de celular: folha sobre mesa escura, levemente torta,
    com iluminação e nitidez opcionalmente degradadas."""
    alt_foto, larg_foto = int(ref_h * 1.35), int(ref_w * 1.35)
    foto = np.full((alt_foto, larg_foto, 3), 35, dtype=np.uint8)
    off_x, off_y = (larg_foto - ref_w) // 2, (alt_foto - ref_h) // 2
    foto[off_y:off_y + ref_h, off_x:off_x + ref_w] = folha
    if gradiente:
        grad = np.tile(np.linspace(0.55, 1.0, larg_foto), (alt_foto, 1)).astype(np.float32)
        for c in range(3):
            foto[:, :, c] = np.clip(foto[:, :, c].astype(np.float32) * grad, 0, 255).astype(np.uint8)
    matriz = cv2.getRotationMatrix2D((larg_foto / 2, alt_foto / 2), rotacao, 1.0)
    foto = cv2.warpAffine(foto, matriz, (larg_foto, alt_foto), borderValue=(35, 35, 35))
    if blur > 0:
        foto = cv2.GaussianBlur(foto, (0, 0), sigmaX=blur)
    caminho = tmp_path / nome
    cv2.imwrite(str(caminho), foto, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return caminho


INDICES_MARCADOS = [0, 4, 12, 20, 21, 30]


def test_deteccao_resiste_a_iluminacao_desigual(tmp_path):
    """Uma sombra/gradiente de luz de um lado da mesa não pode confundir a
    leitura — a correção de iluminação + comparação por foto cuidam disso."""
    ficha = template_mapper.carregar_ficha("motor_fh_d13_parcial")
    folha = _folha_com_marcas(ficha, INDICES_MARCADOS)
    caminho = _compor_foto(tmp_path, folha, ficha["ref_largura"], ficha["ref_altura"],
                           "gradiente.jpg", rotacao=2, gradiente=True)
    resultado = image_processor.processar_foto(caminho, ficha)
    marcados = sorted(it["indice"] for it in resultado["itens"] if it["marcado"])
    assert marcados == INDICES_MARCADOS
    assert resultado["qualidade_baixa"] is False


def test_deteccao_reconhece_marca_fraca(tmp_path):
    """Marca de lápis clara (não só caneta forte) ainda deve ser detectada:
    a comparação é relativa à própria foto, não a um contraste fixo."""
    ficha = template_mapper.carregar_ficha("motor_fh_d13_parcial")
    folha = _folha_com_marcas(ficha, INDICES_MARCADOS, intensidade=(90, 90, 90), espessura=2)
    caminho = _compor_foto(tmp_path, folha, ficha["ref_largura"], ficha["ref_altura"],
                           "fraca.jpg", rotacao=2)
    resultado = image_processor.processar_foto(caminho, ficha)
    marcados = sorted(it["indice"] for it in resultado["itens"] if it["marcado"])
    assert marcados == INDICES_MARCADOS


def test_foto_borrada_desativa_deteccao_automatica(tmp_path):
    """Foto tremida/desfocada: melhor recusar a leitura automática do que
    arriscar marcar peça errada — cai tudo em conferência manual."""
    ficha = template_mapper.carregar_ficha("motor_fh_d13_parcial")
    folha = _folha_com_marcas(ficha, INDICES_MARCADOS)
    caminho = _compor_foto(tmp_path, folha, ficha["ref_largura"], ficha["ref_altura"],
                           "borrada.jpg", rotacao=1, blur=6)
    resultado = image_processor.processar_foto(caminho, ficha)
    assert resultado["foto_borrada"] is True
    assert resultado["ficha_calibrada"] is False
    assert all(not it["marcado"] for it in resultado["itens"])


def test_folha_em_branco_nao_inventa_marcacao(tmp_path):
    """Se ninguém marcou nada, o sistema não pode "inventar" uma separação
    estatística em puro ruído — precisa avisar e pedir conferência manual."""
    ficha = template_mapper.carregar_ficha("motor_fh_d13_parcial")
    folha = _folha_com_marcas(ficha, [])  # nenhuma marcação
    caminho = _compor_foto(tmp_path, folha, ficha["ref_largura"], ficha["ref_altura"], "branca.jpg")
    resultado = image_processor.processar_foto(caminho, ficha)
    assert resultado["qualidade_baixa"] is True
    assert all(not it["marcado"] for it in resultado["itens"])


def test_ficha_curta_usa_piso_absoluto_em_vez_de_comparacao(tmp_path):
    """Com poucos quadrados (ex.: ficha de Diferencial com poucas peças), a
    mediana/desvio da própria foto não é uma base confiável — o sistema usa
    só o piso absoluto nesse caso."""
    ficha = {
        "tipo": "curta", "ref_largura": 1000, "ref_altura": 1414, "calibrada": True,
        "itens": [
            {"peca": "Peça A", "grupo": "", "x": 100, "y": 300, "w": 30, "h": 30},
            {"peca": "Peça B", "grupo": "", "x": 100, "y": 360, "w": 30, "h": 30},
            {"peca": "Peça C", "grupo": "", "x": 100, "y": 420, "w": 30, "h": 30},
            {"peca": "Peça D", "grupo": "", "x": 100, "y": 480, "w": 30, "h": 30},
        ],
    }
    folha = _folha_com_marcas(ficha, [1])  # só a peça B
    caminho = _compor_foto(tmp_path, folha, ficha["ref_largura"], ficha["ref_altura"], "curta.jpg")
    resultado = image_processor.processar_foto(caminho, ficha)
    marcados = [it["indice"] for it in resultado["itens"] if it["marcado"]]
    assert marcados == [1]
