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

    Retorna (imagem_alinhada, metodo):
      - "marcadores": 3 ou 4 marcadores usados — alinhamento de confiança
        total (a leitura automática pode marcar itens sozinha);
      - "marcadores_parcial": só 2 marcadores — alinha bem na região deles,
        mas pode derivar no lado oposto da folha; a leitura vira sugestão;
      - "contorno": método reserva (adivinhando a borda da folha) — em foto
        real de oficina já desalinhou e fabricou marcações, então a leitura
        NUNCA marca sozinha nesse modo, só sugere em amarelo;
      - "nenhum": nada encontrado, apenas redimensiona.
    """
    def _com_mascara_de_validade(matriz):
        """Devolve também a máscara de quais pixels do espaço de referência
        vieram DE DENTRO da foto original.

        Quando a foto corta um pedaço da folha (enquadramento apertado,
        papel dobrado saindo do quadro), o warp preenche a área que faltou
        com PRETO — e preto vira "tinta" na medição, fabricando marcação em
        itens cujo quadrado nem aparece na foto (visto em foto real da
        oficina). Com a máscara, esses quadrados são identificados e caem
        em conferência manual em vez de serem lidos.
        """
        alinhada = cv2.warpPerspective(imagem, matriz, (largura_ref, altura_ref))
        origem_valida = np.full(imagem.shape[:2], 255, dtype=np.uint8)
        mascara = cv2.warpPerspective(origem_valida, matriz, (largura_ref, altura_ref))
        return alinhada, mascara

    H, n_marcadores = marcadores_aruco.estimar_homografia(imagem, largura_ref, altura_ref)
    if H is not None:
        alinhada, mascara = _com_mascara_de_validade(H)
        metodo = "marcadores" if n_marcadores >= 3 else "marcadores_parcial"
        return alinhada, metodo, mascara

    cantos = _encontrar_folha(imagem)
    if cantos is not None:
        destino_pagina = np.array([[0, 0], [largura_ref - 1, 0],
                                   [largura_ref - 1, altura_ref - 1], [0, altura_ref - 1]],
                                  dtype="float32")
        matriz = cv2.getPerspectiveTransform(cantos, destino_pagina)
        alinhada, mascara = _com_mascara_de_validade(matriz)
        return alinhada, "contorno", mascara
    log.warning("Folha não detectada na foto (nem marcadores nem contorno); "
               "usando redimensionamento simples.")
    mascara_cheia = np.full((altura_ref, largura_ref), 255, dtype=np.uint8)
    return cv2.resize(imagem, (largura_ref, altura_ref)), "nenhum", mascara_cheia


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
    """Converte para preto/branco realçando TUDO que é escuro (tinta impressa
    e de caneta). Usada para localizar a borda impressa dos quadrados."""
    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
    nitidez = _medir_nitidez(cinza)
    cinza = _corrigir_iluminacao(cinza)
    cinza = cv2.GaussianBlur(cinza, (3, 3), 0)
    binaria = cv2.adaptiveThreshold(
        cinza, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 31, 12)  # tinta vira branco (255)
    return binaria, nitidez


def _mascara_tinta(imagem):
    """Máscara de TINTA DE CANETA, ignorando sujeira leve de oficina.

    A folha passa na mão do mecânico: dedo de graxa, poeira e amassado
    deixam manchas ACINZENTADAS e fracas. Tinta de caneta é diferente:
    ou é bem mais escura que o papel ao redor (caneta preta/azul escura),
    ou tem cor saturada (azul/vermelha). Esta máscara só aceita pixels com
    uma dessas duas assinaturas — mancha cinza clara de sujeira fica fora,
    mesmo que caia em cima de um quadrado.
    """
    hsv = cv2.cvtColor(imagem, cv2.COLOR_BGR2HSV)
    saturacao = hsv[:, :, 1].astype(np.int16)
    brilho = hsv[:, :, 2].astype(np.int16)
    # brilho local do papel (desfoque largo acompanha sombra/gradiente de luz)
    papel = cv2.GaussianBlur(hsv[:, :, 2], (0, 0),
                             sigmaX=imagem.shape[1] / 12).astype(np.int16)
    bem_escura = brilho < papel - config.DETECCAO_DELTA_ESCURO
    colorida = (saturacao > config.DETECCAO_SATURACAO_TINTA) & (brilho < papel - 20)
    mascara = ((bem_escura | colorida).astype(np.uint8)) * 255
    # Religa fragmentos do mesmo traço: em foto de WhatsApp (recomprimida e
    # pequena), a tinta azul se mistura com o branco do papel e a máscara
    # quebra o rabisco em pedacinhos — sem isso, o "maior traço" sai pequeno
    # e uma marcação real cai injustamente para conferência manual.
    return cv2.morphologyEx(mascara, cv2.MORPH_CLOSE,
                            np.ones((3, 3), np.uint8), iterations=2)


def _corrigir_grade(binaria, itens):
    """Corrige o deslocamento residual da grade de quadrados por CONSENSO.

    Papel dobrado na mão (caso comum: mecânico segura a folha pra
    fotografar) desloca os quadrados vários pixels de forma suave ao longo
    da página — mais do que uma busca local por quadrado consegue tolerar
    sem risco de "capturar" o quadrado do item vizinho (visto em foto real:
    a marca de um item foi parar no item de baixo).

    Solução: encontrar TODOS os contornos do tamanho de um quadrado na
    página, casar cada um com o quadrado esperado mais próximo e ajustar
    uma transformação afim por RANSAC (consenso da grade inteira — casamentos
    errados viram outliers e são ignorados). O resultado é um campo de
    correção suave aplicado a todos os itens, inclusive os que não foram
    encontrados individualmente.

    Retorna uma lista (na ordem dos itens) de dicionários:
      - "pos": (x, y) onde medir o quadrado deste item;
      - "confirmado": True quando o quadrado foi FISICAMENTE encontrado
        perto de onde a geometria da página previa (resíduo pequeno em
        relação ao ajuste da grade). Itens não confirmados estão em região
        onde a grade não bate (quadrado cortado da foto, dobra forte,
        casamento com o quadrado do vizinho) — a leitura deles não é
        confiável e nunca vira marcação automática.
    """
    resultados = [{"pos": (float(item["x"]), float(item["y"])), "confirmado": False}
                  for item in itens]
    if not itens:
        return resultados
    w_tipico = float(np.median([item["w"] for item in itens]))
    h_tipico = float(np.median([item["h"] for item in itens]))

    # fecha microfalhas na borda impressa (JPEG de WhatsApp quebra linhas
    # finas), senão quadrados reais não viram candidatos e o consenso enxerga
    # menos grade do que existe
    fechada = cv2.morphologyEx(binaria, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contornos, _ = cv2.findContours(fechada, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    candidatos = []
    for contorno in contornos:
        bx, by, bw, bh = cv2.boundingRect(contorno)
        if 0.6 * w_tipico <= bw <= 1.7 * w_tipico and 0.6 * h_tipico <= bh <= 1.7 * h_tipico:
            candidatos.append((bx + bw / 2.0, by + bh / 2.0))
    if not candidatos:
        return resultados
    candidatos_np = np.asarray(candidatos, dtype=np.float32)

    # casamento bruto: quadrado esperado -> candidato físico mais próximo
    matches = []  # (indice_do_item, centro_esperado, centro_candidato)
    raio_maximo = max(w_tipico, h_tipico) * 1.6
    for i, item in enumerate(itens):
        ex = item["x"] + item["w"] / 2.0
        ey = item["y"] + item["h"] / 2.0
        distancias = np.hypot(candidatos_np[:, 0] - ex, candidatos_np[:, 1] - ey)
        j = int(np.argmin(distancias))
        if distancias[j] <= raio_maximo:
            matches.append((i, (ex, ey), tuple(candidatos_np[j])))

    limiar_residuo = config.DETECCAO_RESIDUO_GRADE
    if len(matches) >= 6:
        origem = np.asarray([m[1] for m in matches], dtype=np.float32)
        destino = np.asarray([m[2] for m in matches], dtype=np.float32)
        matriz, inliers = cv2.estimateAffinePartial2D(
            origem, destino, method=cv2.RANSAC, ransacReprojThreshold=8.0)
        if matriz is not None and inliers is not None and int(inliers.sum()) >= 6:
            # posição prevista pela grade para TODOS os itens (mesmo os que
            # não casaram — dobra suave é extrapolada de forma consistente)
            cantos = np.asarray([[item["x"], item["y"]] for item in itens],
                                dtype=np.float32).reshape(-1, 1, 2)
            corrigidos = cv2.transform(cantos, matriz).reshape(-1, 2)
            for i, (px, py) in enumerate(corrigidos):
                resultados[i]["pos"] = (float(px), float(py))
            # confirmação por resíduo: quadrado físico perto de onde a grade
            # previa (dobra suave passa; casamento com vizinho, ~1 linha de
            # distância, é rejeitado com folga)
            previstos = cv2.transform(origem.reshape(-1, 1, 2), matriz).reshape(-1, 2)
            confirmados = 0
            for (i, _, cand), (vx, vy) in zip(matches, previstos):
                residuo = float(np.hypot(vx - cand[0], vy - cand[1]))
                if residuo <= limiar_residuo:
                    item = itens[i]
                    resultados[i] = {"pos": (cand[0] - item["w"] / 2.0,
                                             cand[1] - item["h"] / 2.0),
                                     "confirmado": True}
                    confirmados += 1
            log.info("Grade: %d/%d quadrados confirmados fisicamente.",
                     confirmados, len(itens))
    else:
        # poucos casamentos para um ajuste de grade: confirma só quem está
        # praticamente em cima da posição esperada
        for i, (ex, ey), cand in matches:
            if float(np.hypot(ex - cand[0], ey - cand[1])) <= limiar_residuo:
                item = itens[i]
                resultados[i] = {"pos": (cand[0] - item["w"] / 2.0,
                                         cand[1] - item["h"] / 2.0),
                                 "confirmado": True}
    return resultados


def _refinar_posicao_quadrado(binaria, x, y, w, h):
    """Encontra a borda impressa do quadrado PERTO da posição esperada.

    Mesmo com o alinhamento global perfeito (marcadores nos cantos) e a
    correção de grade, sobra um resíduo local de alguns pixels (papel
    ondulado, escala da impressora). Sem este ajuste fino, a borda impressa
    do próprio quadrado "vaza" para dentro da área medida e vira falso
    positivo.

    A janela de busca é PEQUENA de propósito (45% do quadrado): a correção
    de grade já posicionou perto do certo, e uma janela grande poderia
    capturar o quadrado do item vizinho em papel dobrado.
    """
    altura_img, largura_img = binaria.shape
    folga = int(max(w, h) * 0.45)
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


def _entorno_e_papel(cinza, papel_global, x, y, w, h):
    """Confere se o ENTORNO do quadrado é papel branco de verdade.

    Papel muito dobrado (segurado na mão) pode puxar o fundo da foto (mesa,
    teclado, dedo) para dentro da área onde um quadrado deveria estar — e
    fundo escuro vira "tinta" falsa. Um X de caneta legítimo está sempre
    cercado de papel claro; se o entorno está escuro, a medição não é
    confiável e o item deve cair em conferência manual, nunca ser marcado.

    Olha três lados (esquerda, cima, baixo) — a direita tem o texto impresso
    do item, que naturalmente contém tinta.
    """
    altura_img, largura_img = cinza.shape
    folga = max(4, int(max(w, h) * 0.45))
    x0, y0 = int(x), int(y)
    x1, y1 = int(x + w), int(y + h)
    faixas = [
        cinza[max(0, y0):min(altura_img, y1), max(0, x0 - folga):max(0, x0)],
        cinza[max(0, y0 - folga):max(0, y0), max(0, x0):min(largura_img, x1)],
        cinza[min(altura_img, y1):min(altura_img, y1 + folga), max(0, x0):min(largura_img, x1)],
    ]
    pixels = np.concatenate([f.ravel() for f in faixas if f.size > 0]) if any(
        f.size > 0 for f in faixas) else np.array([])
    if pixels.size == 0:
        return False
    return float(np.median(pixels)) >= papel_global - config.DETECCAO_DELTA_AMBIENTE


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
    alinhada, alinhamento_metodo, mascara_valida = alinhar_folha(imagem, largura_ref, altura_ref)
    folha_detectada = alinhamento_metodo != "nenhum"
    # Só o alinhamento por 3+ marcadores dá confiança para marcar sozinho.
    # Com 2 marcadores ou contorno, a leitura vira SUGESTÃO (amarelo,
    # desmarcado) — em foto real, o contorno já desalinhou e fabricou
    # marcações, então nunca mais se marca nada automaticamente nesses modos.
    alinhamento_confiavel = alinhamento_metodo == "marcadores"
    alinhamento_impreciso = not alinhamento_confiavel and folha_detectada
    binaria, nitidez = _binarizar(alinhada)
    tinta = _mascara_tinta(alinhada)
    foto_borrada = nitidez < config.DETECCAO_NITIDEZ_MINIMA

    # Sem NENHUMA correção de perspectiva (nem marcadores, nem contorno), as
    # coordenadas dos quadrados não têm como bater com a foto — não vale a
    # pena tentar medir preenchimento, cairia tudo em conferência manual.
    calibrada = (bool(ficha.get("calibrada")) and not foto_borrada
                and alinhamento_metodo != "nenhum")
    itens_ficha = ficha.get("itens", [])
    indices_calibrados = [i for i, item in enumerate(itens_ficha) if item.get("x") is not None]

    # Leitura em três estágios por quadrado:
    #   1) correção de GRADE por consenso (papel dobrado na mão desloca a
    #      grade inteira suavemente — corrigir item a item capturaria o
    #      quadrado do vizinho);
    #   2) snap local fino na borda impressa (resíduo de poucos pixels);
    #   3) mede TINTA DE CANETA (não sujeira de graxa) e o maior traço;
    # classificação por evidência absoluta — dúvida fica DESMARCADA e
    # sinalizada, nunca pré-marcada.
    def _caixa_dentro_da_foto(x, y, w, h):
        """O quadrado (com folga) veio inteiro de dentro da foto original?

        Se a foto cortou essa região da folha, o warp preencheu com preto e
        qualquer medição ali é lixo — precisa cair em conferência manual."""
        folga = max(4, int(max(w, h) * 0.3))
        x0, y0 = max(0, int(x - folga)), max(0, int(y - folga))
        x1 = min(largura_ref, int(x + w + folga))
        y1 = min(altura_ref, int(y + h + folga))
        regiao = mascara_valida[y0:y1, x0:x1]
        return regiao.size > 0 and int(regiao.min()) > 0

    medidas = {}
    itens_fora_da_foto = 0
    if calibrada:
        cinza_raw = cv2.cvtColor(alinhada, cv2.COLOR_BGR2GRAY)
        # papel_global: mediana só da área que veio da foto (a área "de fora"
        # é preta e puxaria a mediana para baixo numa foto muito cortada)
        pixels_validos = cinza_raw[mascara_valida > 0]
        papel_global = float(np.median(pixels_validos)) if pixels_validos.size else 255.0
        itens_com_pos = [itens_ficha[i] for i in indices_calibrados]
        grade = _corrigir_grade(binaria, itens_com_pos)
        for i, info in zip(indices_calibrados, grade):
            item = itens_ficha[i]
            px, py = info["pos"]
            qx, qy, qw, qh = _refinar_posicao_quadrado(
                binaria, px, py, item["w"], item["h"])
            preenchimento, maior_traco = _medir_marcacao(tinta, qx, qy, qw, qh)
            marcado, status = _classificar_marcacao(preenchimento, maior_traco)
            if marcado and not alinhamento_confiavel:
                marcado, status = False, "conferir"

            if not info["confirmado"] or not _caixa_dentro_da_foto(qx, qy, qw, qh):
                # ou o quadrado deste item não foi confirmado fisicamente na
                # grade (cortado da foto, dobra forte, casou com o vizinho),
                # ou a região veio de fora do enquadramento — o que se mede
                # ali não é confiável e NÃO pode virar marcação automática
                itens_fora_da_foto += 1
                marcado, status = False, "conferir"
            elif not _entorno_e_papel(cinza_raw, papel_global, qx, qy, qw, qh):
                # fundo/dedo/sombra pesada invadindo a região: nada de
                # marcar automaticamente — nem confiar que está vazio
                marcado, status = False, "conferir"
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
        "alinhamento_confiavel": alinhamento_confiavel,
        "alinhamento_impreciso": alinhamento_impreciso,
        "ficha_calibrada": calibrada,
        "foto_borrada": foto_borrada,
        "qualidade_baixa": qualidade_baixa,
        "itens_fora_da_foto": itens_fora_da_foto,
        "nitidez": round(nitidez, 1),
    }
