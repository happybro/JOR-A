"""
Geração do PDF do pedido de peças/orçamento com ReportLab.

Layout limpo em A4, pensado para leitura fácil no WhatsApp e impressão:
cabeçalho com dados da OS, tabela de peças (separando "estoque fornece" e
"cliente traz"), observações, assinaturas e rodapé.

OBS: quando o modelo Excel oficial da oficina for anexado ao projeto, este
layout deve ser ajustado para reproduzir o padrão visual dele.
"""
import logging
import time
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (HRFlowable, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

import config

log = logging.getLogger("orcamento_express.pdf")

CINZA_ESCURO = colors.HexColor("#37474F")
CINZA_CLARO = colors.HexColor("#ECEFF1")
AZUL = colors.HexColor("#1565C0")
VERDE = colors.HexColor("#2E7D32")

ESTILO_TITULO = ParagraphStyle("titulo", fontName="Helvetica-Bold", fontSize=15,
                               textColor=CINZA_ESCURO, spaceAfter=2)
ESTILO_SUB = ParagraphStyle("sub", fontName="Helvetica", fontSize=10,
                            textColor=colors.HexColor("#607D8B"))
ESTILO_SECAO = ParagraphStyle("secao", fontName="Helvetica-Bold", fontSize=11,
                              textColor=AZUL, spaceBefore=8, spaceAfter=4)
ESTILO_NORMAL = ParagraphStyle("normal", fontName="Helvetica", fontSize=9.5, leading=13)
ESTILO_RODAPE = ParagraphStyle("rodape", fontName="Helvetica", fontSize=8,
                               textColor=colors.HexColor("#90A4AE"))


def _tabela_pecas(titulo, pecas):
    """Monta a tabela de peças de uma seção (estoque ou cliente)."""
    elementos = [Paragraph(titulo, ESTILO_SECAO)]
    if not pecas:
        elementos.append(Paragraph("— nenhuma peça nesta seção —", ESTILO_NORMAL))
        return elementos
    dados = [["Qtd", "Peça", "Grupo"]]
    for p in pecas:
        dados.append([str(p.get("quantidade", 1)),
                      Paragraph(p.get("peca", ""), ESTILO_NORMAL),
                      p.get("grupo", "")])
    tabela = Table(dados, colWidths=[14 * mm, 118 * mm, 38 * mm], repeatRows=1)
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), CINZA_ESCURO),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, CINZA_CLARO]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B0BEC5")),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elementos.append(tabela)
    return elementos


def gerar_pdf(orcamento: dict) -> str:
    """Gera o PDF do orçamento e retorna o nome do arquivo criado.

    `orcamento` deve conter: numero, cliente, placa, veiculo, data,
    consultor, tipo_ficha, pecas (lista com peca/quantidade/grupo/origem),
    observacoes.
    """
    numero = str(orcamento.get("numero", "")) or "sem-numero"
    nome_arquivo = f"orcamento_{numero}_{int(time.time())}.pdf"
    caminho = Path(config.PASTA_PDFS) / nome_arquivo

    doc = SimpleDocTemplate(str(caminho), pagesize=A4,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            title=f"Pedido de Peças - OS {numero}")

    pecas = orcamento.get("pecas", [])
    pecas_estoque = [p for p in pecas if p.get("origem", "estoque") != "cliente"]
    pecas_cliente = [p for p in pecas if p.get("origem") == "cliente"]

    tipo = orcamento.get("tipo_ficha_nome") or orcamento.get("tipo_ficha", "") or "—"
    corpo = [
        Paragraph(config.NOME_OFICINA, ESTILO_TITULO),
        Paragraph(f"Pedido de Peças / Orçamento — Ficha: {tipo}", ESTILO_SUB),
        Spacer(1, 4 * mm),
    ]

    # Bloco de dados da OS
    dados = [
        ["OS / Orçamento:", numero, "Data:", orcamento.get("data", "")],
        ["Cliente:", orcamento.get("cliente", ""), "Placa:", orcamento.get("placa", "")],
        ["Veículo:", orcamento.get("veiculo", ""), "Consultor:", orcamento.get("consultor", "")],
    ]
    tabela_dados = Table(dados, colWidths=[30 * mm, 78 * mm, 22 * mm, 40 * mm])
    tabela_dados.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("BACKGROUND", (0, 0), (-1, -1), CINZA_CLARO),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#B0BEC5")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CFD8DC")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    corpo.append(tabela_dados)

    corpo += _tabela_pecas("PEÇAS NECESSÁRIAS (estoque fornece)", pecas_estoque)
    corpo += _tabela_pecas("PEÇAS PARA O CLIENTE TRAZER", pecas_cliente)

    observacoes = (orcamento.get("observacoes") or "").strip()
    corpo.append(Paragraph("OBSERVAÇÕES", ESTILO_SECAO))
    corpo.append(Paragraph(observacoes.replace("\n", "<br/>") or "—", ESTILO_NORMAL))

    corpo += [
        Spacer(1, 14 * mm),
        Table([[
            "_______________________________\nConferido por (estoque)",
            "_______________________________\nConsultor",
        ]], colWidths=[85 * mm, 85 * mm],
            style=TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8.5),
                              ("ALIGN", (0, 0), (-1, -1), "CENTER")])),
        Spacer(1, 6 * mm),
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#B0BEC5")),
        Paragraph(
            f"Gerado pelo Orçamento Express Oficina em "
            f"{orcamento.get('gerado_em', '')} — documento interno de orçamento.",
            ESTILO_RODAPE),
    ]
    if config.OE_RESPONSAVEL_COMPRAS:
        contato = config.OE_RESPONSAVEL_COMPRAS
        if config.OE_TELEFONE_COMPRAS:
            contato += f" - {config.OE_TELEFONE_COMPRAS}"
        corpo.append(Paragraph(f"* {contato} — {config.OE_DEPARTAMENTO_COMPRAS}", ESTILO_RODAPE))

    doc.build(corpo)
    log.info("PDF gerado: %s (%d peças)", nome_arquivo, len(pecas))
    return nome_arquivo


def mensagem_whatsapp(orcamento: dict) -> str:
    """Monta o texto pronto para colar no grupo do WhatsApp."""
    pecas = orcamento.get("pecas", [])
    pecas_cliente = [p for p in pecas if p.get("origem") == "cliente"]
    linhas = [
        f"*Pedido de Peças — OS {orcamento.get('numero', '')}*",
        f"Cliente: {orcamento.get('cliente', '')}",
        f"Veículo: {orcamento.get('veiculo', '')} — Placa {orcamento.get('placa', '')}",
        f"Ficha: {orcamento.get('tipo_ficha_nome') or orcamento.get('tipo_ficha', '')}",
        "",
        "*Peças necessárias:*",
    ]
    for p in pecas:
        if p.get("origem") != "cliente":
            linhas.append(f"• {p.get('quantidade', 1)}x {p.get('peca', '')}")
    if pecas_cliente:
        linhas += ["", "*Cliente deve trazer:*"]
        linhas += [f"• {p.get('quantidade', 1)}x {p.get('peca', '')}" for p in pecas_cliente]
    observacoes = (orcamento.get("observacoes") or "").strip()
    if observacoes:
        linhas += ["", f"Obs: {observacoes}"]
    return "\n".join(linhas)
