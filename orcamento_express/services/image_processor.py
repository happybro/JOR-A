"""
Processamento da foto da ficha com OpenCV.

Etapas:
  1. Carrega a foto enviada pelo celular.
  2. Localiza o contorno da folha (o maior quadrilátero claro sobre o fundo
     escuro) e corrige a perspectiva; se não achar um quadrilátero limpo,
     cai para o retângulo rotacionado do maior contorno (foto mais torta/
     com dobra) antes de desistir e apenas redimensionar.
  3. Corrige iluminação desigual (sombra de um lado da folha, por exemplo)
     "achatando" o fundo antes de binarizar.
  4. Para cada quadrado de marcação, mede a fração de pixels escuros (tinta).
  5. Classifica cada quadrado comparando com a MEDIANA e o desvio robusto
     (MAD) da própria foto — não com um número fixo. Isso adapta a leitura
     à iluminação/exposição/nitidez de cada foto específica, em vez de
     assumir que toda foto tem o mesmo contraste da que foi usada para
     calibrar um limiar fixo.
  6. Mede a nitidez da folha alinhada; fotos muito borradas geram aviso de
     baixa qualidade e todos os itens caem em conferência manual (a leitura
     automática só é confiável em foco razoável).

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


def _canny_automatico(cinza_borrada, sigma=0.33):
    """Limiares de Canny calculados a partir do próprio brilho da imagem, em
    vez de valores fixos — se adapta a fotos mais claras/escuras."""
    mediana = float(np.median(cinza_borrada))
    inferior = int(max(0, (1.0 - sigma) * mediana))
    superior = int(min(255, (1.0 + sigma) * mediana))
    return cv2.Canny(cinza_borrada, inferior, superior)


def _encontrar_folha(imagem):
    """Procura o quadrilátero da folha na imagem. Retorna cantos ou None.

    Tenta primeiro um contorno de 4 lados bem definido (approxPolyDP). Se a
    folha estiver com canto dobrado/sombra e isso falhar, cai para o
    retângulo rotacionado do maior contorno relevante — pior que um
    quadrilátero exato, mas ainda bem melhor que não corrigir nada.
    """
    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
    borrada = cv2.GaussianBlur(cinza, (5, 5), 0)
    bordas = _canny_automatico(borrada)
    bordas = cv2.dilate(bordas, np.ones((3, 3), np.uint8), iterations=2)
    contornos, _ = cv2.findContours(bordas, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contornos:
        return None
    area_imagem = imagem.shape[0] * imagem.shape[1]
    candidatos = sorted(contornos, key=cv2.contourArea, reverse=True)[:5]

    for contorno in candidatos:
        if cv2.contourArea(contorno) < area_imagem * 0.25:
            break  # folha precisa ocupar boa parte da foto
        perimetro = cv2.arcLength(contorno, True)
        aproximado = cv2.approxPolyDP(contorno, 0.02 * perimetro, True)
        if len(aproximado) == 4:
            return _ordenar_cantos(aproximado)

    # Fallback: nenhum quadrilátero limpo — usa o retângulo rotacionado do
    # maior contorno grande o bastante (folha torta, canto dobrado, sombra
    # cortando um dos lados etc.)
    maior = candidatos[0]
    if cv2.contourArea(maior) >= area_imagem * 0.25:
        pontos = cv2.boxPoints(cv2.minAreaRect(maior))
        return _ordenar_cantos(np.array(pontos))
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


def _medir_nitidez(cinza):
    """Variância do Laplaciano: quanto menor, mais borrada está a imagem."""
    return float(cv2.Laplacian(cinza, cv2.CV_64F).var())


def _corrigir_iluminacao(cinza):
    """Achata sombras/gradiente de luz na folha antes de binarizar.

    Estima o "fundo" (papel) com um desfoque bem largo e divide a imagem por
    ele — o mesmo truque usado para digitalizar documentos fotografados sob
    luz desigual (ex.: luminária de um lado só, sombra da mão/celular).
    """
    fundo = cv2.GaussianBlur(cinza, (0, 0), sigmaX=cinza.shape[1] / 12)
    normalizada = cv2.divide(cinza.astype(np.float32), fundo.astype(np.float32) + 1e-3,
                             scale=255)
    return np.clip(normalizada, 0, 255).astype(np.uint8)


def _binarizar(imagem):
    """Converte para preto/branco realçando a tinta (marcações)."""
    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
    nitidez = _medir_nitidez(cinza)
    cinza = _corrigir_iluminacao(cinza)
    cinza = cv2.GaussianBlur(cinza, (3, 3), 0)
    binaria = cv2.adaptiveThreshold(
        cinza, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 31, 12)  # tinta vira branco (255)
    return binaria, nitidez


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


def _classificar_marcacoes(valores):
    """Decide marcado/vazio/incerto comparando cada quadrado com a MEDIANA e
    o desvio robusto (MAD) da própria foto, em vez de um limiar fixo global.

    Por quê: cada foto tem sua própria exposição, sombra e nitidez. Um
    quadrado com 15% de preenchimento pode ser "claramente marcado" numa
    foto bem exposta e "ruído de fundo" noutra mais escura. Comparar cada
    quadrado com a distribuição da MESMA foto se adapta a isso.

    Ainda assim, mantém dois pisos absolutos (config.DETECCAO_LIMIAR_MARCADO
    e DETECCAO_LIMIAR_VAZIO) como salvaguarda: numa folha totalmente em
    branco (nada marcado), a mediana/MAD sozinhas poderiam "inventar" uma
    separação em puro ruído — os pisos evitam falso-positivo nesse caso.

    Com poucos quadrados (fichas curtas, tipo Diferencial com 3-5 peças) a
    mediana/MAD de uma amostra tão pequena não é confiável — nesse caso a
    comparação relativa é desligada e sobra só o piso/teto absolutos.

    Retorna (lista_status, lista_marcado, qualidade_baixa: bool) onde status
    é "ok" (confiável) ou "conferir" (zona cinzenta / ambíguo).
    """
    valores = np.asarray(valores, dtype=float)
    amostra_suficiente = len(valores) >= config.DETECCAO_MINIMO_ITENS_PARA_COMPARACAO

    if amostra_suficiente:
        mediana = float(np.median(valores))
        mad = float(np.median(np.abs(valores - mediana))) * 1.4826  # ~desvio padrão robusto
        margem_relativa = max(config.DETECCAO_MAD_MULTIPLICADOR * mad, config.DETECCAO_MARGEM_MINIMA)
        limiar_relativo = mediana + margem_relativa
    else:
        mad = 0.0
        limiar_relativo = config.DETECCAO_LIMIAR_MARCADO  # sem base pra comparar: só o piso absoluto vale
    # Só é "marcado com confiança" quando SE DESTACA desta foto em particular
    # (sinal relativo) E passa do piso absoluto (sinal independente da foto).
    piso_confiavel_marcado = max(config.DETECCAO_LIMIAR_MARCADO, limiar_relativo)

    marcados, status = [], []
    for valor in valores:
        valor = float(valor)  # tira do numpy antes de guardar (senão não serializa em JSON)
        if valor <= config.DETECCAO_LIMIAR_VAZIO:
            marcados.append(False)
            status.append("ok")
        elif valor >= piso_confiavel_marcado:
            marcados.append(True)
            status.append("ok")
        else:
            # zona cinzenta: pré-marca se ao menos se destacar da própria
            # foto, mas sempre pede conferência humana
            marcados.append(bool(valor >= limiar_relativo))
            status.append("conferir")

    # Se a foto inteira tem pouquíssima variação entre quadrados, não dá pra
    # confiar em nenhuma marca (provável foto ruim ou ninguém marcou nada
    # visível) — melhor avisar do que arriscar.
    qualidade_baixa = bool(mad < 0.01 and (valores.max() - valores.min()) < config.DETECCAO_MARGEM_MINIMA)
    return status, marcados, qualidade_baixa


def processar_foto(caminho_foto, ficha: dict):
    """Processa a foto da ficha e devolve o resultado da detecção.

    Retorna dicionário com:
      - itens: lista com {indice, peca, grupo, marcado, confianca, status}
      - imagem_processada: nome do arquivo salvo em PASTA_PROCESSADAS
      - folha_detectada: bool
      - ficha_calibrada: bool
      - foto_borrada: bool (nitidez abaixo do mínimo confiável)
      - qualidade_baixa: bool (não deu para separar marcado/vazio com confiança)
    """
    imagem = cv2.imread(str(caminho_foto))
    if imagem is None:
        raise ErroProcessamentoImagem(
            "Não consegui ler a imagem enviada. Envie uma foto JPG ou PNG válida.")

    largura_ref = int(ficha.get("ref_largura", 1000))
    altura_ref = int(ficha.get("ref_altura", 1414))
    alinhada, folha_detectada = alinhar_folha(imagem, largura_ref, altura_ref)
    binaria, nitidez = _binarizar(alinhada)
    foto_borrada = nitidez < config.DETECCAO_NITIDEZ_MINIMA

    calibrada = bool(ficha.get("calibrada")) and not foto_borrada
    itens_ficha = ficha.get("itens", [])
    indices_calibrados = [i for i, item in enumerate(itens_ficha) if item.get("x") is not None]

    valores = {}
    if calibrada:
        for i in indices_calibrados:
            item = itens_ficha[i]
            valores[i] = _medir_preenchimento(binaria, item["x"], item["y"], item["w"], item["h"])

    qualidade_baixa = False
    status_por_indice, marcado_por_indice = {}, {}
    if valores:
        status_lista, marcado_lista, qualidade_baixa = _classificar_marcacoes(list(valores.values()))
        for i, status, marcado in zip(valores.keys(), status_lista, marcado_lista):
            status_por_indice[i] = "conferir" if qualidade_baixa else status
            marcado_por_indice[i] = marcado

    visual = alinhada.copy()
    itens_resultado = []
    for i, item in enumerate(itens_ficha):
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
        if i in valores:
            resultado["confianca"] = round(valores[i], 3)
            resultado["marcado"] = marcado_por_indice[i]
            resultado["status"] = status_por_indice[i]
            cor = (0, 170, 0) if resultado["status"] == "ok" and resultado["marcado"] else \
                  (0, 180, 255) if resultado["status"] == "conferir" else (160, 160, 160)
            cv2.rectangle(visual, (int(item["x"]), int(item["y"])),
                          (int(item["x"] + item["w"]), int(item["y"] + item["h"])),
                          cor, 3)
        itens_resultado.append(resultado)

    nome_arquivo = f"processada_{int(time.time())}.jpg"
    destino = Path(config.PASTA_PROCESSADAS) / nome_arquivo
    cv2.imwrite(str(destino), visual, [cv2.IMWRITE_JPEG_QUALITY, 82])
    log.info("Foto processada: %s | folha_detectada=%s | calibrada=%s | "
             "nitidez=%.1f | borrada=%s | qualidade_baixa=%s",
             nome_arquivo, folha_detectada, calibrada, nitidez, foto_borrada, qualidade_baixa)

    return {
        "itens": itens_resultado,
        "imagem_processada": nome_arquivo,
        "folha_detectada": folha_detectada,
        "ficha_calibrada": calibrada,
        "foto_borrada": foto_borrada,
        "qualidade_baixa": qualidade_baixa,
        "nitidez": round(nitidez, 1),
    }
