"""
Processamento da foto da ficha com OpenCV.

Etapas:
  1. Carrega a foto enviada pelo celular.
  2. Alinha a folha pelos marcadores ArUco impressos nos 4 cantos (com
     fallback por contorno para fichas antigas sem marcadores).
  3. Corrige iluminação desigual (sombra de um lado da folha, por exemplo)
     "achatando" o fundo antes de binarizar.
  4. Para CADA quadrado de marcação, primeiro encontra a borda impressa de
     verdade perto da posição esperada (papel curvado e escala da
     impressora deslocam alguns pixels mesmo com alinhamento global bom).
  5. Mede duas coisas no miolo do quadrado: fração de tinta E o tamanho da
     maior mancha conectada. Marcação de caneta forma UM traço grande;
     ruído de sombra/textura/JPEG vira pixels espalhados — exigir o traço
     é o que elimina os falsos positivos em foto real.
  6. Classificação conservadora: só marca com evidência forte; qualquer
     dúvida fica DESMARCADA e destacada em amarelo ("conferir") — o
     sistema nunca marca uma peça sozinho sem certeza.
  7. Mede a nitidez da folha alinhada; fotos muito borradas desativam a
     leitura automática (tudo cai em conferência manual).

Nada aqui depende de serviço externo ou IA paga.
"""
import logging
import time
from pathlib import Path

import cv2
import numpy as np

import config
from services import marcadores_aruco

log = logging.getLogger("orcamento_express.imagem")


class ErroProcessamentoImagem(Exception):
    """Erro amigável de processamento (mensagem segura para exibir)."""


def ler_imagem(caminho):
    """Lê uma imagem do disco de forma segura para caminhos com acentos.

    cv2.imread() usa fopen() internamente e falha silenciosamente (retorna
    None) em caminhos com acentuação no Windows — por exemplo
    "C:\\Users\\João\\..." ou uma pasta "Área de Trabalho". Isso é comum no
    Brasil e é uma causa frequente do erro "não consegui ler a imagem"
    mesmo com um arquivo válido. np.fromfile + cv2.imdecode não tem esse
    problema porque abre o arquivo pelo Python (que lida bem com Unicode).
    """
    caminho = Path(caminho)
    try:
        dados = np.fromfile(str(caminho), dtype=np.uint8)
    except OSError:
        return None
    if dados.size == 0:
        return None
    return cv2.imdecode(dados, cv2.IMREAD_COLOR)


def salvar_imagem(caminho, imagem, qualidade_jpeg=90):
    """Salva uma imagem no disco de forma segura para caminhos com acentos
    (mesmo motivo do ler_imagem: cv2.imwrite falha silenciosamente em
    caminhos com Unicode no Windows)."""
    caminho = Path(caminho)
    extensao = caminho.suffix or ".jpg"
    parametros = [cv2.IMWRITE_JPEG_QUALITY, qualidade_jpeg] if extensao.lower() in (".jpg", ".jpeg") else []
    ok, codificada = cv2.imencode(extensao, imagem, parametros)
    if not ok:
        raise ErroProcessamentoImagem("Não consegui salvar a imagem processada.")
    codificada.tofile(str(caminho))


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

    Tenta primeiro os marcadores ArUco impressos nos 4 cantos da ficha —
    muito mais confiáveis que adivinhar "qual contorno é a folha" numa foto
    real (mesa de madeira, luz de lâmpada, sombra do celular etc. confundem
    a detecção por contorno). Só cai para o contorno se os marcadores não
    forem encontrados (ex.: ficha impressa antes dessa versão, ou canto
    cortado/dobrado na foto) e, na ausência de qualquer um dos dois, apenas
    redimensiona sem corrigir perspectiva.

    Retorna (imagem_alinhada, metodo) onde metodo é "marcadores", "contorno"
    ou "nenhum" — usado para decidir se a leitura automática é confiável.
    """
    destino_pagina = np.array([[0, 0], [largura_ref - 1, 0],
                               [largura_ref - 1, altura_ref - 1], [0, altura_ref - 1]],
                              dtype="float32")

    cantos = marcadores_aruco.detectar_cantos_da_folha(imagem)
    if cantos is not None:
        metodo = "marcadores"
        # os marcadores ficam ENTRE a borda da página e o miolo (margem de
        # impressão) — o destino tem que ser o ponto de referência de CADA
        # marcador, não o canto (0,0) da página, senão o alinhamento fica
        # com um erro de escala que cresce ao longe dos marcadores.
        destino = marcadores_aruco.pontos_destino_referencia(largura_ref, altura_ref)
    else:
        cantos = _encontrar_folha(imagem)
        metodo = "contorno"
        destino = destino_pagina

    if cantos is not None:
        matriz = cv2.getPerspectiveTransform(cantos, destino)
        return cv2.warpPerspective(imagem, matriz, (largura_ref, altura_ref)), metodo
    log.warning("Folha não detectada na foto (nem marcadores nem contorno); "
               "usando redimensionamento simples.")
    return cv2.resize(imagem, (largura_ref, altura_ref)), "nenhum"


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


def _refinar_posicao_quadrado(binaria, x, y, w, h):
    """Encontra a borda impressa do quadrado PERTO da posição esperada.

    Mesmo com o alinhamento global perfeito (marcadores nos cantos), papel
    levemente curvado sobre a mesa e a escala da impressora deslocam cada
    quadrado alguns pixels. Sem este ajuste, a borda impressa do próprio
    quadrado "vaza" para dentro da área medida e vira falso positivo — a
    principal causa de peças não marcadas aparecendo como marcadas em fotos
    reais.

    Procura, numa janela ao redor da posição esperada, o contorno com
    caixa envolvente do tamanho aproximado do quadrado impresso, e devolve
    (x, y, w, h) refinados. Se não encontrar (ex.: rabisco cobrindo a borda
    toda), devolve a posição original — nesse caso o preenchimento alto
    já denuncia a marcação de qualquer forma.
    """
    altura_img, largura_img = binaria.shape
    folga = int(max(w, h) * 0.7)
    x0, y0 = max(0, int(x - folga)), max(0, int(y - folga))
    x1 = min(largura_img, int(x + w + folga))
    y1 = min(altura_img, int(y + h + folga))
    janela = binaria[y0:y1, x0:x1]
    if janela.size == 0:
        return int(x), int(y), int(w), int(h)

    contornos, _ = cv2.findContours(janela, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    melhor, melhor_erro = None, None
    for contorno in contornos:
        bx, by, bw, bh = cv2.boundingRect(contorno)
        if not (0.6 * w <= bw <= 1.5 * w and 0.6 * h <= bh <= 1.5 * h):
            continue
        erro = (abs((x0 + bx) - x) + abs((y0 + by) - y)
                + abs(bw - w) + abs(bh - h))
        if melhor_erro is None or erro < melhor_erro:
            melhor, melhor_erro = (x0 + bx, y0 + by, bw, bh), erro
    return melhor if melhor is not None else (int(x), int(y), int(w), int(h))


def _medir_marcacao(binaria, x, y, w, h):
    """Mede a tinta DENTRO do quadrado. Retorna (preenchimento, maior_traco).

    - preenchimento: fração de pixels de tinta no miolo do quadrado
      (margem interna de 25% para excluir a borda impressa);
    - maior_traco: fração ocupada pela MAIOR mancha conectada de tinta.

    A segunda métrica é o que separa marcação real de ruído: um X ou
    rabisco de caneta forma UM traço grande e conectado; ruído de sombra,
    textura de papel e serrilhado de compressão JPEG viram pixels
    espalhados em manchinhas minúsculas. Exigir um traço grande elimina
    quase todos os falsos positivos que a fração de pixels sozinha deixa
    passar.
    """
    altura_img, largura_img = binaria.shape
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(largura_img, int(x + w)), min(altura_img, int(y + h))
    if x1 <= x0 or y1 <= y0:
        return 0.0, 0.0
    mx, my = int((x1 - x0) * 0.25), int((y1 - y0) * 0.25)
    recorte = binaria[y0 + my:y1 - my, x0 + mx:x1 - mx]
    if recorte.size == 0:
        return 0.0, 0.0
    preenchimento = float(np.count_nonzero(recorte)) / recorte.size

    quantidade, _, stats, _ = cv2.connectedComponentsWithStats(recorte, connectivity=8)
    maior_area = 0
    for i in range(1, quantidade):  # 0 é o fundo
        maior_area = max(maior_area, int(stats[i, cv2.CC_STAT_AREA]))
    return preenchimento, float(maior_area) / recorte.size


def _classificar_marcacao(preenchimento, maior_traco):
    """Classifica UM quadrado por evidência absoluta, sem pré-marcar dúvida.

    Regra de ouro (pedida explicitamente pelo usuário depois dos falsos
    positivos em foto real): NUNCA marcar um item sem evidência forte.
      - marcado ("ok"): tem tinta suficiente E ela forma um traço grande
        conectado (assinatura de caneta, não de ruído);
      - "conferir": tem alguma tinta acima do nível de ruído, mas sem a
        assinatura de traço — fica DESMARCADO e destacado em amarelo para
        o usuário decidir;
      - vazio ("ok"): abaixo do nível de ruído.

    Retorna (marcado: bool, status: str).
    """
    if (preenchimento >= config.DETECCAO_LIMIAR_MARCADO
            and maior_traco >= config.DETECCAO_LIMIAR_TRACO):
        return True, "ok"
    if (preenchimento >= config.DETECCAO_LIMIAR_SUSPEITA
            or maior_traco >= config.DETECCAO_LIMIAR_TRACO * 0.6):
        return False, "conferir"
    return False, "ok"


def processar_foto(caminho_foto, ficha: dict):
    """Processa a foto da ficha e devolve o resultado da detecção.

    Retorna dicionário com:
      - itens: lista com {indice, peca, grupo, marcado, confianca, status}
      - imagem_processada: nome do arquivo salvo em PASTA_PROCESSADAS
      - folha_detectada: bool
      - alinhamento_metodo: "marcadores" | "contorno" | "nenhum"
      - alinhamento_impreciso: bool (achou a folha, mas sem os marcadores —
        menos confiável que alinhamento por marcadores)
      - ficha_calibrada: bool
      - foto_borrada: bool (nitidez abaixo do mínimo confiável)
      - qualidade_baixa: bool (não deu para separar marcado/vazio com confiança)
    """
    imagem = ler_imagem(caminho_foto)
    if imagem is None:
        tamanho = Path(caminho_foto).stat().st_size if Path(caminho_foto).exists() else -1
        log.error("Falha ao decodificar imagem: %s (tamanho=%d bytes)", caminho_foto, tamanho)
        raise ErroProcessamentoImagem(
            "Não consegui ler a imagem enviada. Envie uma foto JPG ou PNG válida "
            "(fotos em formato HEIC do iPhone não são suportadas — configure o "
            "celular para salvar fotos como \"Mais compatível\"/JPG).")

    largura_ref = int(ficha.get("ref_largura", 1000))
    altura_ref = int(ficha.get("ref_altura", 1414))
    alinhada, alinhamento_metodo = alinhar_folha(imagem, largura_ref, altura_ref)
    folha_detectada = alinhamento_metodo != "nenhum"
    alinhamento_impreciso = alinhamento_metodo == "contorno"
    binaria, nitidez = _binarizar(alinhada)
    foto_borrada = nitidez < config.DETECCAO_NITIDEZ_MINIMA

    # Sem NENHUMA correção de perspectiva (nem marcadores, nem contorno), as
    # coordenadas dos quadrados não têm como bater com a foto — não vale a
    # pena tentar medir preenchimento, cairia tudo em conferência manual.
    calibrada = (bool(ficha.get("calibrada")) and not foto_borrada
                and alinhamento_metodo != "nenhum")
    itens_ficha = ficha.get("itens", [])
    indices_calibrados = [i for i, item in enumerate(itens_ficha) if item.get("x") is not None]

    # Para cada quadrado: 1) acha a borda impressa DE VERDADE perto da posição
    # esperada (papel curvado/escala de impressora deslocam alguns pixels);
    # 2) mede tinta e maior traço no miolo; 3) classifica por evidência
    # absoluta — dúvida fica DESMARCADA e sinalizada, nunca pré-marcada.
    medidas = {}
    if calibrada:
        for i in indices_calibrados:
            item = itens_ficha[i]
            qx, qy, qw, qh = _refinar_posicao_quadrado(
                binaria, item["x"], item["y"], item["w"], item["h"])
            preenchimento, maior_traco = _medir_marcacao(binaria, qx, qy, qw, qh)
            marcado, status = _classificar_marcacao(preenchimento, maior_traco)
            medidas[i] = {
                "caixa": (qx, qy, qw, qh),
                "preenchimento": preenchimento,
                "maior_traco": maior_traco,
                "marcado": marcado,
                "status": status,
            }

    itens_conferir = sum(1 for m in medidas.values() if m["status"] == "conferir")
    qualidade_baixa = bool(medidas) and itens_conferir > max(3, len(medidas) * 0.3)

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
        if i in medidas:
            medida = medidas[i]
            resultado["confianca"] = round(medida["preenchimento"], 3)
            resultado["marcado"] = medida["marcado"]
            resultado["status"] = medida["status"]
            cor = (0, 170, 0) if resultado["status"] == "ok" and resultado["marcado"] else \
                  (0, 180, 255) if resultado["status"] == "conferir" else (160, 160, 160)
            qx, qy, qw, qh = medida["caixa"]
            cv2.rectangle(visual, (qx, qy), (qx + qw, qy + qh), cor, 3)
        itens_resultado.append(resultado)

    nome_arquivo = f"processada_{int(time.time())}.jpg"
    destino = Path(config.PASTA_PROCESSADAS) / nome_arquivo
    salvar_imagem(destino, visual, qualidade_jpeg=82)
    log.info("Foto processada: %s | alinhamento=%s | calibrada=%s | "
             "nitidez=%.1f | borrada=%s | qualidade_baixa=%s",
             nome_arquivo, alinhamento_metodo, calibrada, nitidez, foto_borrada, qualidade_baixa)

    return {
        "itens": itens_resultado,
        "imagem_processada": nome_arquivo,
        "folha_detectada": folha_detectada,
        "alinhamento_metodo": alinhamento_metodo,
        "alinhamento_impreciso": alinhamento_impreciso,
        "ficha_calibrada": calibrada,
        "foto_borrada": foto_borrada,
        "qualidade_baixa": qualidade_baixa,
        "nitidez": round(nitidez, 1),
    }
