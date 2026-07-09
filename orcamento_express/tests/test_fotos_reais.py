"""Regressão com FOTOS REAIS da oficina (WhatsApp, ficha impressa de verdade).

Estas fotos vieram do usuário: ficha impressa pelo sistema, marcada de caneta
azul nos itens 17 (JUNTAS COLETOR DE ESCAPE), 27 (LT ADITIVO RADIADOR) e
34 (LT DE THINNER), fotografada de celular em cima de mesa/teclado e
recomprimida pelo WhatsApp (~720px de largura).

São o teste final de mundo real: se algo aqui quebrar, a mudança quebrou o
uso na oficina — não importa o que os testes sintéticos digam.
"""
from pathlib import Path

import pytest

from services import image_processor, template_mapper

PASTA_DADOS = Path(__file__).resolve().parent / "dados_reais"
MARCADOS_DE_VERDADE = [17, 27, 34]


def _processar(nome_arquivo):
    caminho = PASTA_DADOS / nome_arquivo
    if not caminho.exists():
        pytest.skip(f"foto real não disponível: {nome_arquivo}")
    ficha = template_mapper.carregar_ficha("motor_fh_d13_parcial")
    return image_processor.processar_foto(caminho, ficha)


@pytest.mark.parametrize("nome_arquivo", [
    "foto_boa_4_marcadores.jpeg",
    "foto_boa_3_marcadores.jpeg",  # 1 canto não detectado (resolução WhatsApp)
])
def test_foto_real_boa_leitura_perfeita(nome_arquivo):
    """Foto razoável (folha inteira no quadro): leitura automática EXATA —
    as 3 peças certas marcadas, nenhuma outra."""
    resultado = _processar(nome_arquivo)
    marcados = sorted(it["indice"] for it in resultado["itens"] if it["marcado"])
    assert marcados == MARCADOS_DE_VERDADE


def test_foto_real_dificil_nunca_inventa_marcacao():
    """Foto ruim de verdade: papel dobrado na mão, quadrados da parte de
    baixo da coluna esquerda cortados do enquadramento. O sistema NÃO tem
    como ler o que não está na foto — o contrato é: NENHUM falso positivo,
    e todo item ilegível vai para amarelo ('conferir') com aviso."""
    resultado = _processar("foto_dificil_papel_dobrado.jpeg")
    marcados = sorted(it["indice"] for it in resultado["itens"] if it["marcado"])
    conferir = sorted(it["indice"] for it in resultado["itens"]
                      if it["status"] == "conferir")

    falsos = [i for i in marcados if i not in MARCADOS_DE_VERDADE]
    assert falsos == [], f"falsos positivos em foto real: {falsos}"

    # tudo que não foi marcado automaticamente precisa estar sinalizado
    perdidos = [i for i in MARCADOS_DE_VERDADE if i not in marcados]
    sem_aviso = [i for i in perdidos if i not in conferir]
    assert sem_aviso == [], f"itens marcados de verdade sumiram sem aviso: {sem_aviso}"

    # e o usuário é avisado de que houve itens sem leitura confiável
    assert resultado["itens_fora_da_foto"] > 0
