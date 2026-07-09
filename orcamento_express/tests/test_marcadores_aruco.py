"""Testes do alinhamento por marcadores ArUco.

O teste `test_alinhamento_resiste_a_mesa_de_madeira_e_perspectiva_real` é uma
salvaguarda direta contra o bug encontrado em produção: os marcadores ficam
MARGEM unidades para dentro da borda do papel (por causa da margem de
impressão), não exatamente no canto (0,0) da página. Tratar o canto do
marcador como se fosse o canto da página introduz um erro de escala que
cresce com a distância dos marcadores — na prática, isso fazia um bloco
inteiro de itens do meio/fim da lista sair com a marcação errada, mesmo com
os 4 marcadores detectados corretamente (o erro não era de detecção, era de
correspondência geométrica).
"""
import cv2
import numpy as np
import pytest

from services import marcadores_aruco


def test_marcador_gerado_e_detectado_com_precisao_subpixel():
    """Gera um marcador, cola num fundo branco e confere que a biblioteca
    acha exatamente o ID certo com posição precisa (sem nenhuma distorção)."""
    bitmap = marcadores_aruco.gerar_imagem_marcador(marcadores_aruco.ID_SUP_ESQ, 300)
    tela = np.full((500, 500), 255, dtype=np.uint8)
    tela[100:400, 100:400] = bitmap
    tela_bgr = cv2.cvtColor(tela, cv2.COLOR_GRAY2BGR)

    corners, ids, _ = marcadores_aruco._detector().detectMarkers(
        cv2.cvtColor(tela_bgr, cv2.COLOR_BGR2GRAY))
    assert ids is not None
    assert int(np.asarray(ids).ravel()[0]) == marcadores_aruco.ID_SUP_ESQ
    # o canto TL do marcador (corners[0][0]) deve bater com onde ele foi colado
    assert corners[0][0][0] == pytest.approx((100, 100), abs=3)


def test_sem_marcadores_nao_inventa_homografia():
    """Sem nenhum marcador na imagem, não deve inventar alinhamento."""
    imagem_em_branco = np.full((600, 400, 3), 255, dtype=np.uint8)
    H, quantidade = marcadores_aruco.estimar_homografia(imagem_em_branco, 1000, 1414)
    assert H is None
    assert quantidade == 0


def _colar_marcador(tela, id_marcador, x, y, tamanho):
    bitmap = marcadores_aruco.gerar_imagem_marcador(id_marcador, tamanho)
    tela[y:y + tamanho, x:x + tamanho] = bitmap


def test_homografia_com_apenas_2_marcadores():
    """Cada marcador contribui com seus 4 cantos, então 2 marcadores (8
    pontos) bastam para estimar a homografia — sem cair para o método de
    contorno, que em foto real desalinhou e fabricou marcações."""
    ref_w, ref_h = 1000, 1414
    pos = marcadores_aruco.posicoes_referencia(ref_w, ref_h)
    # monta uma "foto" já no espaço de referência com só 2 marcadores opostos
    tela = np.full((ref_h, ref_w), 255, dtype=np.uint8)
    for id_ in (marcadores_aruco.ID_SUP_ESQ, marcadores_aruco.ID_INF_DIR):
        x, y, w, h = pos[id_]
        _colar_marcador(tela, id_, int(x), int(y), int(w))
    imagem = cv2.cvtColor(tela, cv2.COLOR_GRAY2BGR)

    H, quantidade = marcadores_aruco.estimar_homografia(imagem, ref_w, ref_h)
    assert quantidade == 2
    assert H is not None
    # a imagem já está alinhada, então a homografia deve ser ~identidade:
    # os cantos dos marcadores devem ser mapeados quase neles mesmos
    origem = np.array([[[float(pos[0][0]), float(pos[0][1])]]], dtype=np.float32)
    mapeado = cv2.perspectiveTransform(origem, H)[0][0]
    assert mapeado == pytest.approx((pos[0][0], pos[0][1]), abs=4)


@pytest.mark.parametrize("usar_fitz", [True])
def test_alinhamento_resiste_a_mesa_de_madeira_e_perspectiva_real(tmp_path, usar_fitz):
    """Reproduz o cenário que falhou em produção: ficha real impressa (com
    marcadores), fotografada sobre fundo texturizado (mesa de madeira), com
    perspectiva de câmera de verdade (homografia, não só rotação) e luz de
    lâmpada desigual. Todas as 6 peças marcadas devem ser lidas certas, e
    NENHUMA das outras 35 pode ser marcada por engano.
    """
    fitz = pytest.importorskip("fitz", reason="pymupdf não instalado — teste pulado")
    import config
    from services import ficha_pdf, image_processor, template_mapper

    ficha = template_mapper.carregar_ficha("motor_fh_d13_parcial")
    ref_w, ref_h = ficha["ref_largura"], ficha["ref_altura"]
    dados_os = {"numero": "14744", "cm_tip": "OS", "cliente": "Cliente Teste", "placa": "ABC1D23"}
    nome_pdf = ficha_pdf.gerar_ficha_impressao(ficha, dados_os)
    caminho_pdf = config.PASTA_PDFS / nome_pdf

    doc = fitz.open(str(caminho_pdf))
    escala = ref_w / 595.27
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(escala, escala))
    caminho_png = tmp_path / "folha_ref.png"
    pix.save(str(caminho_png))
    folha = cv2.imread(str(caminho_png))
    folha = cv2.resize(folha, (ref_w, ref_h))

    indices_marcados = [0, 4, 12, 20, 21, 30]
    for i in indices_marcados:
        item = ficha["itens"][i]
        x, y, w, h = item["x"], item["y"], item["w"], item["h"]
        cv2.line(folha, (x + 2, y + 2), (x + w - 2, y + h - 2), (0, 0, 0), 3)
        cv2.line(folha, (x + w - 2, y + 2), (x + 2, y + h - 2), (0, 0, 0), 3)

    # Fundo texturizado (não uniforme) simulando mesa de madeira
    np.random.seed(7)
    alt_foto, larg_foto = int(ref_h * 1.4), int(ref_w * 1.4)
    base = np.full((alt_foto, larg_foto), 90, dtype=np.float32)
    base += np.tile(np.sin(np.linspace(0, 40, larg_foto)) * 12, (alt_foto, 1))
    base += np.random.normal(0, 8, (alt_foto, larg_foto))
    base = cv2.GaussianBlur(base, (0, 0), sigmaX=3)
    textura = np.clip(base, 40, 160).astype(np.uint8)
    foto = np.zeros((alt_foto, larg_foto, 3), dtype=np.uint8)
    foto[:, :, 0] = (textura * 0.35).astype(np.uint8)
    foto[:, :, 1] = (textura * 0.55).astype(np.uint8)
    foto[:, :, 2] = (textura * 0.75).astype(np.uint8)

    # Perspectiva real de câmera (homografia, não rotação simples)
    off_x, off_y = (larg_foto - ref_w) // 2, (alt_foto - ref_h) // 2
    origem = np.array([[0, 0], [ref_w, 0], [ref_w, ref_h], [0, ref_h]], dtype=np.float32)
    destino = np.array([
        [off_x + 25, off_y + 45], [off_x + ref_w - 5, off_y + 10],
        [off_x + ref_w - 40, off_y + ref_h - 15], [off_x + 10, off_y + ref_h - 55],
    ], dtype=np.float32)
    H = cv2.getPerspectiveTransform(origem, destino)
    folha_persp = cv2.warpPerspective(folha, H, (larg_foto, alt_foto), borderValue=(0, 0, 0))
    mascara = cv2.warpPerspective(np.full((ref_h, ref_w), 255, np.uint8), H, (larg_foto, alt_foto))
    foto[mascara > 0] = folha_persp[mascara > 0]

    # Luz de lâmpada desigual (gradiente radial de um canto)
    yy, xx = np.mgrid[0:alt_foto, 0:larg_foto]
    dist = np.sqrt((xx - larg_foto * 0.15) ** 2 + (yy - alt_foto * 0.1) ** 2)
    fator_luz = (1.25 - 0.55 * (dist / dist.max())).astype(np.float32)
    for c in range(3):
        foto[:, :, c] = np.clip(foto[:, :, c].astype(np.float32) * fator_luz, 0, 255).astype(np.uint8)

    caminho_foto = tmp_path / "foto_realista.jpg"
    cv2.imwrite(str(caminho_foto), foto, [cv2.IMWRITE_JPEG_QUALITY, 88])

    resultado = image_processor.processar_foto(caminho_foto, ficha)
    assert resultado["alinhamento_metodo"] == "marcadores"
    marcados = sorted(it["indice"] for it in resultado["itens"] if it["marcado"])
    assert marcados == indices_marcados
