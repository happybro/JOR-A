"""
Marcadores de alinhamento (ArUco) impressos nos 4 cantos da ficha.

Por que: detectar "a folha branca sobre a mesa" pelo contorno (maior
quadrilátero claro na foto) funciona bem em condição controlada, mas falha
em fotos reais de oficina — mesa de madeira, luz de lâmpada de um lado,
ângulo da câmera, sombra do celular etc. podem fazer o algoritmo escolher
o contorno errado, o que desalinha TODOS os quadrados de marcação de uma
vez (o efeito visto na prática: um bloco inteiro de itens errado).

ArUco é a técnica padrão (biblioteca já embutida no OpenCV, sem custo, sem
internet) para achar cantos com precisão em qualquer fundo/iluminação: cada
marcador tem um ID codificado no próprio desenho, então a detecção não
depende de contraste com o fundo — só do próprio marcador.

Convenção: 4 marcadores pequenos, um em cada canto da ficha, com IDs fixos:
  0 = canto superior esquerdo   1 = canto superior direito
  3 = canto inferior esquerdo   2 = canto inferior direito
(ordem 0,1,2,3 = sentido horário, como cv2.aruco já numera os cantos de UM
marcador — útil pra não confundir os dois níveis de "canto".)
"""
import logging

import cv2
import numpy as np

log = logging.getLogger("orcamento_express.aruco")

DICIONARIO = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)

ID_SUP_ESQ, ID_SUP_DIR, ID_INF_DIR, ID_INF_ESQ = 0, 1, 2, 3

# Geometria no espaço de referência da ficha (mesma unidade de x/y/w/h dos
# quadrados de peça). A margem até a borda do papel (18 unidades ≈ 3,8mm)
# fica fora da faixa que muitas impressoras não conseguem imprimir — não
# deixe menor que isso. Ver services/ficha_pdf.py e
# services/template_mapper.RODAPE_RESERVADO para o espaço reservado ao
# redor pra não brigar com cabeçalho/rodapé.
MARGEM = 18
TAMANHO = 55


def posicoes_referencia(ref_largura, ref_altura):
    """Retorna {id_marcador: (x, y, w, h)} no espaço de referência da ficha."""
    return {
        ID_SUP_ESQ: (MARGEM, MARGEM, TAMANHO, TAMANHO),
        ID_SUP_DIR: (ref_largura - MARGEM - TAMANHO, MARGEM, TAMANHO, TAMANHO),
        ID_INF_DIR: (ref_largura - MARGEM - TAMANHO, ref_altura - MARGEM - TAMANHO, TAMANHO, TAMANHO),
        ID_INF_ESQ: (MARGEM, ref_altura - MARGEM - TAMANHO, TAMANHO, TAMANHO),
    }


def gerar_imagem_marcador(id_marcador, tamanho_px=300):
    """Gera o bitmap (numpy, escala de cinza) de um marcador ArUco pra imprimir."""
    return cv2.aruco.generateImageMarker(DICIONARIO, id_marcador, tamanho_px)


def _detector():
    parametros = cv2.aruco.DetectorParameters()
    # refinamento sub-pixel dos cantos: importante em foto de WhatsApp
    # (baixa resolução), onde 1 pixel de erro no canto já desloca a página
    parametros.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    return cv2.aruco.ArucoDetector(DICIONARIO, parametros)


def _detectar_uma_escala(cinza, escala):
    """Detecta marcadores numa versão redimensionada e devolve os cantos já
    convertidos de volta para as coordenadas originais."""
    if escala != 1.0:
        cinza = cv2.resize(cinza, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
    corners, ids, _ = _detector().detectMarkers(cinza)
    if ids is None:
        return {}
    ids_achatado = np.asarray(ids).ravel()  # coluna (N,1) em cv2 antigo, vetor (N,) no 5.x
    return {int(id_): c[0] / escala for id_, c in zip(ids_achatado, corners)
            if int(id_) in (ID_SUP_ESQ, ID_SUP_DIR, ID_INF_DIR, ID_INF_ESQ)}


def detectar_marcadores(imagem_bgr):
    """Detecta os marcadores da página e devolve {id: 4 cantos (float32)}.

    Fotos de WhatsApp chegam recomprimidas e pequenas (~720px de largura),
    onde cada marcador tem ~40px — no limite do detector. Por isso, se
    algum dos 4 não aparecer na escala original, tenta de novo com a
    imagem ampliada (2x) e com contraste local reforçado (CLAHE), mesclando
    apenas os marcadores que faltavam.
    """
    cinza = cv2.cvtColor(imagem_bgr, cv2.COLOR_BGR2GRAY)
    achados = _detectar_uma_escala(cinza, 1.0)
    if len(achados) < 4:
        for tentativa in ("2x", "clahe"):
            if tentativa == "2x":
                novos = _detectar_uma_escala(cinza, 2.0)
            else:
                clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(cinza)
                novos = _detectar_uma_escala(clahe, 2.0)
            for id_, cantos in novos.items():
                achados.setdefault(id_, cantos)
            if len(achados) == 4:
                break
    if len(achados) < 4:
        faltando = sorted(set([ID_SUP_ESQ, ID_SUP_DIR, ID_INF_DIR, ID_INF_ESQ]) - set(achados))
        log.warning("Marcadores ArUco não encontrados: %s (achados: %s)",
                    faltando, sorted(achados))
    return achados


def _cantos_impressos_do_marcador(id_marcador, ref_largura, ref_altura):
    """Cantos (TL, TR, BR, BL) de UM marcador no espaço de referência da
    ficha — exatamente onde ele foi impresso por services/ficha_pdf.py."""
    x, y, w, h = posicoes_referencia(ref_largura, ref_altura)[id_marcador]
    return np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], dtype="float32")


def estimar_homografia(imagem_bgr, ref_largura, ref_altura):
    """Estima a transformação foto→ficha usando TODOS os cantos de TODOS os
    marcadores encontrados (cada marcador contribui 4 pontos).

    É isso que permite alinhar com precisão mesmo quando só 2 ou 3 dos 4
    marcadores aparecem (canto cortado na foto, reflexo, resolução baixa do
    WhatsApp): 2 marcadores = 8 correspondências, 3 = 12 — o suficiente
    para uma homografia estável, sem precisar cair para o método de
    contorno (que em foto real já desalinhou e fabricou marcações).

    Retorna (H, quantidade_de_marcadores) ou (None, quantidade).
    """
    achados = detectar_marcadores(imagem_bgr)
    if len(achados) < 2:
        return None, len(achados)

    pontos_foto, pontos_ficha = [], []
    for id_, cantos in achados.items():
        pontos_foto.extend(cantos)
        pontos_ficha.extend(_cantos_impressos_do_marcador(id_, ref_largura, ref_altura))
    pontos_foto = np.asarray(pontos_foto, dtype=np.float32)
    pontos_ficha = np.asarray(pontos_ficha, dtype=np.float32)

    H, mascara = cv2.findHomography(pontos_foto, pontos_ficha, cv2.RANSAC, 8.0)
    if H is None:
        return None, len(achados)
    inliers = int(mascara.sum()) if mascara is not None else 0
    if inliers < len(pontos_foto) * 0.7:
        log.warning("Homografia dos marcadores instável (%d/%d inliers) — descartada.",
                    inliers, len(pontos_foto))
        return None, len(achados)
    return H, len(achados)
