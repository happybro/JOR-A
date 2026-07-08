"""
Gera a FICHA PARA IMPRESSÃO (o papel que o mecânico marca com X).

Diferente do fluxo original imaginado (calibrar uma ficha pré-impressa
externa), aqui o próprio sistema desenha o quadrado de marcação de cada
peça em uma posição conhecida — por isso a leitura da foto depois não
precisa de calibração manual: as coordenadas usadas para desenhar o
quadrado no papel são as MESMAS usadas por `image_processor` para procurar
a marcação (ver `services/template_mapper.calcular_layout_automatico`).

O espaço de referência da ficha (`ref_largura` x `ref_altura`) é
proporcional ao A4 (1000:1414 ≈ 210:297mm), então a conversão para pontos
do PDF é uma escala simples, sem distorção.
"""
import io
import logging
import time
from pathlib import Path

import cv2
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

import config
from services import marcadores_aruco

log = logging.getLogger("orcamento_express.ficha_pdf")

LARGURA_A4, ALTURA_A4 = A4


def _imagem_marcador_para_reportlab(id_marcador):
    """Gera o bitmap do marcador ArUco e devolve como ImageReader (PNG em memória)."""
    bitmap = marcadores_aruco.gerar_imagem_marcador(id_marcador)
    ok, codificado = cv2.imencode(".png", bitmap)
    if not ok:
        raise RuntimeError(f"Falha ao gerar o marcador ArUco {id_marcador}")
    return ImageReader(io.BytesIO(codificado.tobytes()))


def _desenhar_marcadores(c, ref_largura, ref_altura):
    """Desenha os 4 marcadores de alinhamento nos cantos da ficha."""
    escala = LARGURA_A4 / ref_largura
    for id_marcador, (x, y, w, h) in marcadores_aruco.posicoes_referencia(ref_largura, ref_altura).items():
        px, py, pw, ph = _conv(x, y, w, h, ref_largura, ref_altura)
        c.drawImage(_imagem_marcador_para_reportlab(id_marcador), px, py, pw, ph)


def _conv(x, y, w, h, ref_largura, ref_altura):
    """Converte um retângulo do espaço de referência (y para baixo) para
    coordenadas do canvas do ReportLab (origem embaixo à esquerda)."""
    escala = LARGURA_A4 / ref_largura
    px = x * escala
    pw = w * escala
    ph = h * escala
    py = ALTURA_A4 - (y * escala) - ph
    return px, py, pw, ph


def gerar_ficha_impressao(ficha: dict, dados_os: dict) -> str:
    """Gera o PDF da ficha em branco (com quadrados) pronta para impressão.

    `dados_os` traz o que foi encontrado/preenchido na tela de novo
    orçamento (numero, cliente, placa, veiculo, data...). Campos ausentes
    ficam em branco para preenchimento manual.
    """
    ref_largura = ficha["ref_largura"]
    ref_altura = ficha["ref_altura"]
    escala = LARGURA_A4 / ref_largura

    nome_arquivo = f"ficha_{ficha['tipo']}_{dados_os.get('numero', 'sn')}_{int(time.time())}.pdf"
    caminho = Path(config.PASTA_PDFS) / nome_arquivo
    c = canvas.Canvas(str(caminho), pagesize=A4)

    def y_pdf(y_ref):
        return ALTURA_A4 - y_ref * escala

    # --- Marcadores de alinhamento (cantos) ---
    _desenhar_marcadores(c, ref_largura, ref_altura)

    # --- Cabeçalho ---
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(LARGURA_A4 / 2, y_pdf(50), config.NOME_OFICINA)
    c.setFont("Helvetica-Bold", 11)
    titulo = ficha.get("titulo_impressao") or ficha.get("nome", "")
    c.drawCentredString(LARGURA_A4 / 2, y_pdf(78), titulo)

    c.setFont("Helvetica", 9.5)
    tipo_os = dados_os.get("cm_tip", "OS")
    linha1 = f"{tipo_os} Nº: {dados_os.get('numero', '_______')}      Data: {dados_os.get('data', '____/____/______')}"
    linha2 = f"Cliente: {dados_os.get('cliente', '')}"
    linha3 = (f"Placa: {dados_os.get('placa', '')}      "
             f"Veículo: {dados_os.get('veiculo_completo') or dados_os.get('veiculo', '')}      "
             f"Motor: {dados_os.get('motor', '')}")
    c.drawString(40 * escala, y_pdf(115), linha1)
    c.drawString(40 * escala, y_pdf(135), linha2)
    c.drawString(40 * escala, y_pdf(155), linha3)
    c.line(40 * escala, y_pdf(170), (ref_largura - 40) * escala, y_pdf(170))

    c.setFont("Helvetica-Bold", 9)
    c.drawString(40 * escala, y_pdf(200), "PEÇAS A COMPRAR:")
    c.setFont("Helvetica", 7.5)
    c.drawString(40 * escala, y_pdf(216),
                "Marque com X o quadrado das peças necessárias. Ajuste a quantidade se for diferente da sugerida.")

    # --- Itens (checkbox + texto), coordenadas vindas do layout automático/manual ---
    FONTE_ITEM = "Helvetica"
    TAM_ITEM = 8.3
    c.setFont(FONTE_ITEM, TAM_ITEM)
    xs_colunas = sorted({item["x"] for item in ficha["itens"] if item.get("x") is not None})
    for item in ficha["itens"]:
        if item.get("x") is None:
            continue
        px, py, pw, ph = _conv(item["x"], item["y"], item["w"], item["h"], ref_largura, ref_altura)
        c.rect(px, py, pw, ph)  # quadrado de marcação
        texto_x = px + pw + 4
        texto_y = py + ph * 0.28
        qtd_padrao = item.get("quantidade_padrao", 1)
        codigo = f" ({item['codigo_interno']})" if item.get("codigo_interno") else ""
        texto = f"{qtd_padrao:02d} - {item['peca']}{codigo}"

        # Não deixa o texto invadir a próxima coluna: encolhe com reticências
        # até caber na largura disponível (medida de verdade, não chute por nº de caracteres).
        proximas = [x for x in xs_colunas if x > item["x"]]
        escala_px = LARGURA_A4 / ref_largura
        limite_x = (min(proximas) - 10) * escala_px if proximas else (ref_largura - 40) * escala_px
        largura_disponivel = limite_x - texto_x
        base = texto
        while c.stringWidth(texto, FONTE_ITEM, TAM_ITEM) > largura_disponivel and len(base) > 4:
            base = base[:-1]
            texto = base.rstrip() + "…"
        c.drawString(texto_x, texto_y, texto)

    # --- Rodapé --- (fica todo ACIMA da faixa ocupada pelos marcadores
    # inferiores, com folga — ver services/template_mapper.RODAPE_RESERVADO)
    c.setFont("Helvetica", 8)
    c.line(40 * escala, y_pdf(ref_altura - 140), (ref_largura - 40) * escala, y_pdf(ref_altura - 140))
    responsavel = config.OE_RESPONSAVEL_COMPRAS or "___________________________"
    telefone = f" - {config.OE_TELEFONE_COMPRAS}" if config.OE_TELEFONE_COMPRAS else ""
    c.drawString(40 * escala, y_pdf(ref_altura - 122), f"* {responsavel}{telefone}")
    c.drawString(40 * escala, y_pdf(ref_altura - 105), config.OE_DEPARTAMENTO_COMPRAS)
    c.drawRightString((ref_largura - 40) * escala, y_pdf(ref_altura - 105),
                      "Mecânico responsável: _______________")

    c.showPage()
    c.save()
    log.info("Ficha para impressão gerada: %s (%d itens)", nome_arquivo, len(ficha["itens"]))
    return nome_arquivo
