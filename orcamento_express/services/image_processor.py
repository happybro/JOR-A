"""
Processamento da foto da ficha com OpenCV.

Etapas:
  1. Carrega a foto enviada pelo celular.
  2. Tenta localizar o contorno da folha (maior quadrilátero claro) e
     corrige a perspectiva ("destorce" a foto).
  3. Redimensiona para o espaço de referência do modelo da ficha.
  4. Para cada quadrado de marcação calibrado, mede a fração de pixels
     escuros (tinta) dentro dele:
       - acima de DETECCAO_LIMIAR_MARCADO  -> marcado (confiança alta);
       - abaixo de DETECCAO_LIMIAR_VAZIO   -> não marcado (confiança alta);
       - entre os dois                     -> incerto ("conferir manualmente").
  5. Salva a imagem processada (com os quadrados desenhados) para a tela
     de conferência.

Nada aqui depende de serviço externo ou IA paga.
"""
import logging
import time
from pathlib import Path

import cv2
import numpy as np

import config

log = logging.getLogger("orcamento_express.imagem")


class ErroProcessamentoImagem(Exception):
    """Erro amigável de processamento (mensagem segura para exibir)."""


def _ordenar_cantos(pontos):
    """Ordena 4 pontos como: sup-esq, sup-dir, inf-dir, inf-esq."""
    pontos = pontos.reshape(4, 2).astype("float32")
    soma = pontos.sum(axis=1)
    dif = np.diff(pontos, axis=1).ravel()
    return np.array([
        pontos[np.argmin(soma)],   # superior esquerdo
        pontos[np.argmin(dif)],    # superior direito
        pontos[np.argmax(soma)],   # inferior direito
        pontos[np.argmax(dif)],    # inferior esquerdo
    ], dtype="float32")


def _encontrar_folha(imagem):
    """Procura o maior quadrilátero na imagem (a folha). Retorna cantos ou None."""
    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
    borrada = cv2.GaussianBlur(cinza, (5, 5), 0)
    bordas = cv2.Canny(borrada, 50, 150)
    bordas = cv2.dilate(bordas, np.ones((3, 3), np.uint8), iterations=2)
    contornos, _ = cv2.findContours(bordas, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contornos:
        return None
    area_imagem = imagem.shape[0] * imagem.shape[1]
    for contorno in sorted(contornos, key=cv2.contourArea, reverse=True)[:5]:
        if cv2.contourArea(contorno) < area_imagem * 0.25:
            break  # folha precisa ocupar boa parte da foto
        perimetro = cv2.arcLength(contorno, True)
        aproximado = cv2.approxPolyDP(contorno, 0.02 * perimetro, True)
        if len(aproximado) == 4:
            return _ordenar_cantos(aproximado)
    return None


def alinhar_folha(imagem, largura_ref, altura_ref):
    """Corrige perspectiva e devolve a folha alinhada no tamanho de referência.

    Se não encontrar a folha, apenas redimensiona (com aviso de baixa confiança).
    Retorna (imagem_alinhada, folha_detectada: bool).
    """
    cantos = _encontrar_folha(imagem)
    destino = np.array([[0, 0], [largura_ref - 1, 0],
                        [largura_ref - 1, altura_ref - 1], [0, altura_ref - 1]],
                       dtype="float32")
    if cantos is not None:
        matriz = cv2.getPerspectiveTransform(cantos, destino)
        return cv2.warpPerspective(imagem, matriz, (largura_ref, altura_ref)), True
    log.warning("Folha não detectada na foto; usando redimensionamento simples.")
    return cv2.resize(imagem, (largura_ref, altura_ref)), False


def _binarizar(imagem):
    """Converte para preto/branco realçando a tinta (marcações)."""
    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
    cinza = cv2.GaussianBlur(cinza, (3, 3), 0)
    return cv2.adaptiveThreshold(
        cinza, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 31, 12)  # tinta vira branco (255)


def _medir_preenchimento(binaria, x, y, w, h):
    """Fração de pixels de tinta dentro do quadrado, ignorando a borda impressa."""
    altura_img, largura_img = binaria.shape
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(largura_img, int(x + w)), min(altura_img, int(y + h))
    if x1 <= x0 or y1 <= y0:
        return 0.0
    # margem interna de 25% para não contar a borda impressa do quadrado
    # (quadrados pequenos + leve desalinhamento na foto fazem a própria borda
    # impressa "vazar" pixels escuros perto da margem, se ela for pequena demais)
    mx, my = int((x1 - x0) * 0.25), int((y1 - y0) * 0.25)
    recorte = binaria[y0 + my:y1 - my, x0 + mx:x1 - mx]
    if recorte.size == 0:
        return 0.0
    return float(np.count_nonzero(recorte)) / recorte.size


def processar_foto(caminho_foto, ficha: dict):
    """Processa a foto da ficha e devolve o resultado da detecção.

    Retorna dicionário com:
      - itens: lista com {indice, peca, grupo, marcado, confianca, status}
      - imagem_processada: nome do arquivo salvo em PASTA_PROCESSADAS
      - folha_detectada: bool
      - ficha_calibrada: bool
    """
    imagem = cv2.imread(str(caminho_foto))
    if imagem is None:
        raise ErroProcessamentoImagem(
            "Não consegui ler a imagem enviada. Envie uma foto JPG ou PNG válida.")

    largura_ref = int(ficha.get("ref_largura", 1000))
    altura_ref = int(ficha.get("ref_altura", 1414))
    alinhada, folha_detectada = alinhar_folha(imagem, largura_ref, altura_ref)
    binaria = _binarizar(alinhada)

    calibrada = bool(ficha.get("calibrada"))
    visual = alinhada.copy()
    itens_resultado = []
    for i, item in enumerate(ficha.get("itens", [])):
        resultado = {
            "indice": i,
            "peca": item.get("peca", ""),
            "grupo": item.get("grupo", ""),
            "codigo_interno": item.get("codigo_interno", ""),
            "quantidade": item.get("quantidade_padrao") or 1,
            "marcado": False,
            "confianca": None,
            "status": "manual",  # manual | ok | conferir
        }
        if calibrada and item.get("x") is not None:
            preenchimento = _medir_preenchimento(
                binaria, item["x"], item["y"], item["w"], item["h"])
            resultado["confianca"] = round(preenchimento, 3)
            if preenchimento >= config.DETECCAO_LIMIAR_MARCADO:
                resultado["marcado"], resultado["status"] = True, "ok"
                cor = (0, 170, 0)      # verde: marcado
            elif preenchimento <= config.DETECCAO_LIMIAR_VAZIO:
                resultado["status"] = "ok"
                cor = (160, 160, 160)  # cinza: vazio
            else:
                resultado["marcado"], resultado["status"] = True, "conferir"
                cor = (0, 180, 255)    # amarelo: conferir manualmente
            cv2.rectangle(visual, (int(item["x"]), int(item["y"])),
                          (int(item["x"] + item["w"]), int(item["y"] + item["h"])),
                          cor, 3)
        itens_resultado.append(resultado)

    nome_arquivo = f"processada_{int(time.time())}.jpg"
    destino = Path(config.PASTA_PROCESSADAS) / nome_arquivo
    cv2.imwrite(str(destino), visual, [cv2.IMWRITE_JPEG_QUALITY, 82])
    log.info("Foto processada: %s | folha_detectada=%s | calibrada=%s",
             nome_arquivo, folha_detectada, calibrada)

    return {
        "itens": itens_resultado,
        "imagem_processada": nome_arquivo,
        "folha_detectada": folha_detectada,
        "ficha_calibrada": calibrada,
    }
