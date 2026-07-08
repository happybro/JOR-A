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


def pontos_destino_referencia(ref_largura, ref_altura):
    """Pontos (TL, TR, BR, BL), no espaço de referência, que correspondem ao
    canto de CADA MARCADOR que fica voltado para fora da página — não ao
    canto (0,0)/(ref_largura,0)/etc. da própria página!

    Isso importa porque os marcadores ficam a MARGEM unidades para dentro
    da borda (por causa da margem de impressão), não exatamente no canto.
    Passar esses pontos (em vez do retângulo cheio 0..ref_largura) como
    destino do cv2.getPerspectiveTransform é o que faz o alinhamento bater
    certo — usar (0,0) etc. por engano introduz um erro de escala que cresce
    à medida que se afasta dos marcadores (efeito visto na prática: itens
    do meio/fim da lista saindo com a marcação errada).
    """
    return np.array([
        [MARGEM, MARGEM],
        [ref_largura - MARGEM, MARGEM],
        [ref_largura - MARGEM, ref_altura - MARGEM],
        [MARGEM, ref_altura - MARGEM],
    ], dtype="float32")


def gerar_imagem_marcador(id_marcador, tamanho_px=300):
    """Gera o bitmap (numpy, escala de cinza) de um marcador ArUco pra imprimir."""
    return cv2.aruco.generateImageMarker(DICIONARIO, id_marcador, tamanho_px)


def _detector():
    parametros = cv2.aruco.DetectorParameters()
    return cv2.aruco.ArucoDetector(DICIONARIO, parametros)


def detectar_cantos_da_folha(imagem_bgr):
    """Localiza os 4 marcadores na foto e devolve os 4 cantos da folha
    (ordem TL, TR, BR, BL), ou None se algum marcador não foi encontrado.

    Cada marcador devolve seus PRÓPRIOS 4 cantos (a biblioteca já resolve a
    orientação certa lendo o padrão do marcador, então corners[0] é sempre
    o canto superior-esquerdo DAQUELE marcador, não importa a rotação da
    foto). Como cada marcador foi impresso exatamente no canto da folha,
    pegamos o canto DELE que corresponde ao canto DA PÁGINA:
      - marcador superior-esquerdo  -> seu próprio canto superior-esquerdo
      - marcador superior-direito   -> seu próprio canto superior-direito
      - marcador inferior-direito   -> seu próprio canto inferior-direito
      - marcador inferior-esquerdo  -> seu próprio canto inferior-esquerdo
    """
    cinza = cv2.cvtColor(imagem_bgr, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = _detector().detectMarkers(cinza)
    if ids is None:
        return None
    # ids vem como coluna (N,1) em versões antigas do OpenCV e como vetor
    # (N,) em versões mais novas (5.x) — achatar cobre os dois casos.
    ids_achatado = np.asarray(ids).ravel()
    achados = {int(id_): c[0] for id_, c in zip(ids_achatado, corners)}

    # índice do canto DENTRO do próprio marcador (a lib devolve sempre
    # [TL, TR, BR, BL] do marcador, já resolvendo a rotação da foto) que
    # corresponde ao canto DA PÁGINA — por coincidência de convenção, é o
    # mesmo número do ID (0=TL, 1=TR, 2=BR, 3=BL)
    indice_canto_por_id = {ID_SUP_ESQ: 0, ID_SUP_DIR: 1, ID_INF_DIR: 2, ID_INF_ESQ: 3}
    if not all(id_ in achados for id_ in indice_canto_por_id):
        faltando = [id_ for id_ in indice_canto_por_id if id_ not in achados]
        log.warning("Marcadores ArUco não encontrados: %s (achados: %s)",
                    faltando, sorted(achados.keys()))
        return None

    cantos = np.array([
        achados[id_][indice] for id_, indice in indice_canto_por_id.items()
    ], dtype="float32")
    return cantos
