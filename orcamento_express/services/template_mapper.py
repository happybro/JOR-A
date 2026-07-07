"""
Carrega os modelos de ficha (ficha_templates/*.json) e calcula o layout dos
quadrados de marcação.

Os tipos de ficha são descobertos **dinamicamente**: basta colocar um novo
arquivo `ficha_templates/<tipo>.json` (uma peças de câmbio, diferencial,
outro modelo de motor etc.) que ele aparece automaticamente no sistema —
não é preciso alterar código.

Cada modelo tem:
  - nome / titulo_impressao;
  - dimensões de referência (ref_largura x ref_altura, na proporção do A4);
  - lista de itens (peças), cada um com nome, quantidade padrão e,
    opcionalmente, coordenadas (x, y, w, h) do quadrado de marcação.

**Duas formas de calibração:**
  1. Automática (padrão): como a ficha impressa pelo próprio sistema
     (`/ficha/<tipo>/imprimir`) tem posição conhecida para cada item, as
     coordenadas são calculadas automaticamente por `calcular_layout_automatico`
     — não é preciso calibrar manualmente.
  2. Manual: se a oficina usar uma ficha pré-existente (fora do sistema),
     ainda é possível calibrar manualmente (tela de calibração), clicando
     nos quadrados na foto. Coordenadas salvas no JSON sempre têm prioridade
     sobre as automáticas.
"""
import json
import logging
import math
from pathlib import Path

import config

log = logging.getLogger("orcamento_express.templates")

# Geometria do layout automático, no espaço de referência (proporção A4)
MARGEM = 40
GUTTER = 24
TOPO_RESERVADO = 300    # espaço para cabeçalho (OS, cliente, placa, veículo...)
RODAPE_RESERVADO = 90   # espaço para assinatura/rodapé


def caminho_ficha(tipo: str) -> Path:
    return Path(config.PASTA_FICHAS) / f"{tipo}.json"


def listar_tipos() -> list:
    """Descobre os tipos de ficha disponíveis (um por arquivo .json)."""
    if not Path(config.PASTA_FICHAS).exists():
        return []
    return sorted(p.stem for p in Path(config.PASTA_FICHAS).glob("*.json"))


def listar_fichas() -> dict:
    """Retorna {tipo: ficha} para todos os tipos disponíveis."""
    return {tipo: carregar_ficha(tipo) for tipo in listar_tipos()}


def calcular_layout_automatico(quantidade_itens: int, ref_largura: int, ref_altura: int):
    """Calcula posições de quadrados em duas colunas, distribuídas na página.

    Determinístico: a mesma quantidade de itens sempre gera as mesmas
    coordenadas — por isso não precisa persistir nada para ser consistente
    entre a impressão da ficha e a leitura da foto depois.
    """
    if quantidade_itens <= 0:
        return [], {}
    linhas_por_coluna = math.ceil(quantidade_itens / 2)
    largura_util = ref_largura - 2 * MARGEM - GUTTER
    col_largura = largura_util / 2
    altura_util = ref_altura - TOPO_RESERVADO - RODAPE_RESERVADO
    linha_altura = max(24, min(altura_util / linhas_por_coluna, 42))
    caixa = max(14, min(20, linha_altura - 8))

    layout = []
    for i in range(quantidade_itens):
        coluna = 0 if i < linhas_por_coluna else 1
        linha = i if coluna == 0 else i - linhas_por_coluna
        x = MARGEM + coluna * (col_largura + GUTTER)
        y = TOPO_RESERVADO + linha * linha_altura
        layout.append({
            "indice": i, "coluna": coluna, "linha": linha,
            "x": round(x), "y": round(y), "w": round(caixa), "h": round(caixa),
        })
    meta = {
        "margem": MARGEM, "gutter": GUTTER, "topo": TOPO_RESERVADO,
        "rodape": RODAPE_RESERVADO, "col_largura": round(col_largura),
        "linha_altura": round(linha_altura), "linhas_por_coluna": linhas_por_coluna,
        "caixa": round(caixa),
    }
    return layout, meta


def carregar_ficha(tipo: str) -> dict:
    """Carrega o modelo da ficha, preenchendo coordenadas automáticas quando
    o item não tiver calibração manual salva."""
    arquivo = caminho_ficha(tipo)
    if not arquivo.exists():
        raise ValueError(f"Tipo de ficha desconhecido: {tipo}")
    ficha = json.loads(arquivo.read_text(encoding="utf-8"))
    ficha.setdefault("ref_largura", 1000)
    ficha.setdefault("ref_altura", 1414)
    itens = ficha.get("itens", [])

    calibrada_manualmente = any(item.get("x") is not None for item in itens)
    if not calibrada_manualmente:
        layout, meta = calcular_layout_automatico(len(itens), ficha["ref_largura"], ficha["ref_altura"])
        for item, pos in zip(itens, layout):
            item["x"], item["y"], item["w"], item["h"] = pos["x"], pos["y"], pos["w"], pos["h"]
        ficha["_layout_meta"] = meta

    ficha["calibrada_manualmente"] = calibrada_manualmente
    ficha["calibrada"] = True  # sempre há coordenadas: automáticas ou manuais
    return ficha


def salvar_ficha(tipo: str, ficha: dict):
    arquivo = caminho_ficha(tipo)
    dados = {k: v for k, v in ficha.items()
            if k not in ("calibrada", "calibrada_manualmente", "_layout_meta")}
    arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Ficha '%s' salva (%d itens).", tipo, len(dados.get("itens", [])))


def salvar_calibracao(tipo: str, caixas: list, ref_largura: int, ref_altura: int):
    """Aplica caixas desenhadas manualmente (sobrepõe o layout automático).

    `caixas` é uma lista de {"indice": i, "x":..., "y":..., "w":..., "h":...}.
    """
    ficha = carregar_ficha(tipo)
    ficha["ref_largura"] = int(ref_largura)
    ficha["ref_altura"] = int(ref_altura)
    for item in ficha["itens"]:
        for chave in ("x", "y", "w", "h"):
            item[chave] = None
    for caixa in caixas:
        i = int(caixa["indice"])
        if 0 <= i < len(ficha["itens"]):
            ficha["itens"][i].update(
                x=int(caixa["x"]), y=int(caixa["y"]),
                w=int(caixa["w"]), h=int(caixa["h"]))
    salvar_ficha(tipo, ficha)
    return carregar_ficha(tipo)
