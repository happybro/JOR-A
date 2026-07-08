"""
Orçamento Express Oficina — aplicativo Flask (BF Trucks / MecAuto).

Roda em porta própria (padrão 5055), separado do MecAuto/JJSoft, acessível
pelo celular na mesma rede. Consulta o banco do MecAuto apenas em modo leitura.

Para iniciar:  python app.py
"""
import logging
import uuid
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import (Flask, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)

import config
from database import mecauto_reader
from database.local_history import HistoricoLocal
from services import ficha_pdf, image_processor, pdf_generator, template_mapper

EXTENSOES_IMAGEM = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def configurar_logs():
    config.garantir_pastas()
    formato = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    arquivo = RotatingFileHandler(Path(config.PASTA_LOGS) / "app.log",
                                  maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    arquivo.setFormatter(formato)
    raiz = logging.getLogger("orcamento_express")
    raiz.setLevel(logging.INFO)
    raiz.addHandler(arquivo)
    return logging.getLogger("orcamento_express.app")


log = configurar_logs()


def criar_app():
    app = Flask(__name__,
               template_folder=str(config.RECURSOS_DIR / "templates"),
               static_folder=str(config.RECURSOS_DIR / "static"))
    app.secret_key = config.SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"] = config.UPLOAD_MAX_MB * 1024 * 1024
    historico = HistoricoLocal(config.BANCO_LOCAL)

    # ------------------------- ajuda de rascunho -------------------------
    def rascunho_atual():
        """Carrega o orçamento em andamento da sessão (ou None)."""
        id_r = session.get("rascunho_id")
        return historico.carregar_rascunho(id_r) if id_r else None

    def salvar_rascunho(dados):
        id_r = session.get("rascunho_id") or uuid.uuid4().hex
        session["rascunho_id"] = id_r
        historico.salvar_rascunho(id_r, dados)
        return dados

    def montar_itens_manual(ficha):
        return [
            {"indice": i, "peca": item["peca"], "grupo": item.get("grupo", ""),
             "codigo_interno": item.get("codigo_interno", ""),
             "quantidade": item.get("quantidade_padrao") or 1,
             "marcado": False, "confianca": None, "status": "manual"}
            for i, item in enumerate(ficha["itens"])]

    # ------------------------------- telas -------------------------------
    @app.get("/")
    def index():
        return render_template("index.html", oficina=config.NOME_OFICINA)

    @app.get("/novo")
    def novo_orcamento():
        tipos = {tipo: ficha["nome"] for tipo, ficha in template_mapper.listar_fichas().items()}
        return render_template("novo_orcamento.html", tipos=tipos,
                               modo_demo=config.MECAUTO_MODO_DEMO)

    @app.get("/captura")
    def captura():
        rascunho = rascunho_atual()
        if not rascunho:
            return redirect(url_for("novo_orcamento"))
        ficha = template_mapper.carregar_ficha(rascunho["tipo_ficha"])
        return render_template("captura.html", rascunho=rascunho,
                               calibrada_manualmente=ficha["calibrada_manualmente"])

    @app.get("/ficha/<tipo>/imprimir")
    def ficha_imprimir(tipo):
        """Gera e serve a ficha em branco (com quadrados) para o mecânico marcar."""
        rascunho = rascunho_atual() or {}
        try:
            ficha = template_mapper.carregar_ficha(tipo)
        except ValueError:
            return redirect(url_for("novo_orcamento"))
        nome_pdf = ficha_pdf.gerar_ficha_impressao(ficha, rascunho)
        return redirect(url_for("servir_pdf", nome=nome_pdf))

    @app.get("/conferencia")
    def conferencia():
        rascunho = rascunho_atual()
        if not rascunho:
            return redirect(url_for("novo_orcamento"))
        if "itens" not in rascunho:  # chegou sem foto: monta lista manual
            ficha = template_mapper.carregar_ficha(rascunho["tipo_ficha"])
            rascunho["itens"] = montar_itens_manual(ficha)
            salvar_rascunho(rascunho)
        return render_template("conferencia.html", rascunho=rascunho)

    @app.get("/pdf_gerado")
    def pdf_gerado():
        rascunho = rascunho_atual()
        if not rascunho or not rascunho.get("arquivo_pdf"):
            return redirect(url_for("novo_orcamento"))
        return render_template("pdf_gerado.html", rascunho=rascunho)

    @app.get("/historico")
    def historico_tela():
        return render_template("historico.html", registros=historico.listar())

    @app.get("/configuracoes")
    def configuracoes():
        fichas = template_mapper.listar_fichas()
        return render_template("configuracoes.html", fichas=fichas,
                               porta=config.PORTA, modo_demo=config.MECAUTO_MODO_DEMO,
                               dsn_configurado=bool(config.MECAUTO_DSN))

    @app.get("/calibracao/<tipo>")
    def calibracao(tipo):
        try:
            ficha = template_mapper.carregar_ficha(tipo)
        except ValueError:
            return redirect(url_for("configuracoes"))
        return render_template("calibracao.html", ficha=ficha, tipo=tipo)

    # ----------------------------- arquivos ------------------------------
    @app.get("/arquivos/pdf/<path:nome>")
    def servir_pdf(nome):
        return send_from_directory(config.PASTA_PDFS, nome)

    @app.get("/arquivos/processadas/<path:nome>")
    def servir_processada(nome):
        return send_from_directory(config.PASTA_PROCESSADAS, nome)

    # -------------------------------- API --------------------------------
    @app.post("/api/buscar_os")
    def api_buscar_os():
        numero = (request.json or {}).get("numero", "").strip()
        if not numero:
            return jsonify({"encontrado": False, "erro": "Digite o número da OS/orçamento."})
        try:
            dados = mecauto_reader.buscar_os_por_numero(numero)
        except mecauto_reader.ErroLeituraMecAuto as exc:
            log.error("Busca de OS %s falhou: %s", numero, exc)
            return jsonify({"encontrado": False, "erro": str(exc)})
        return jsonify(dados)

    @app.post("/api/iniciar_orcamento")
    def api_iniciar_orcamento():
        corpo = request.json or {}
        tipo = corpo.get("tipo_ficha", "")
        if tipo not in template_mapper.listar_tipos():
            return jsonify({"ok": False, "erro": "Escolha o tipo de ficha."}), 400
        ficha = template_mapper.carregar_ficha(tipo)
        rascunho = {
            "cm_tip": corpo.get("cm_tip", "OS").strip() or "OS",
            "numero": corpo.get("numero", "").strip(),
            "cliente": corpo.get("cliente", "").strip(),
            "placa": corpo.get("placa", "").strip(),
            "veiculo": corpo.get("veiculo", "").strip(),
            "veiculo_completo": corpo.get("veiculo", "").strip(),
            "motor": corpo.get("motor", "").strip(),
            "consultor": corpo.get("consultor", "").strip(),
            "data": corpo.get("data", "").strip() or datetime.now().strftime("%d/%m/%Y"),
            "tipo_ficha": tipo,
            "tipo_ficha_nome": ficha["nome"],
            "observacoes": "",
        }
        session.pop("rascunho_id", None)  # novo orçamento = novo rascunho
        salvar_rascunho(rascunho)
        return jsonify({"ok": True, "proxima": url_for("captura")})

    @app.post("/api/processar_foto")
    def api_processar_foto():
        rascunho = rascunho_atual()
        if not rascunho:
            return jsonify({"ok": False, "erro": "Inicie um orçamento antes de enviar a foto."}), 400
        arquivo = request.files.get("foto")
        if not arquivo or not arquivo.filename:
            return jsonify({"ok": False, "erro": "Nenhuma foto recebida."}), 400
        extensao = Path(arquivo.filename).suffix.lower()
        if extensao not in EXTENSOES_IMAGEM:
            return jsonify({"ok": False, "erro": "Formato inválido. Envie JPG ou PNG."}), 400

        destino = Path(config.PASTA_UPLOADS) / f"foto_{uuid.uuid4().hex}{extensao}"
        arquivo.save(destino)
        try:
            ficha = template_mapper.carregar_ficha(rascunho["tipo_ficha"])
            resultado = image_processor.processar_foto(destino, ficha)
        except image_processor.ErroProcessamentoImagem as exc:
            return jsonify({"ok": False, "erro": str(exc)}), 400
        except Exception:
            log.exception("Erro inesperado ao processar a foto %s", destino.name)
            return jsonify({"ok": False, "erro": "Erro ao processar a foto. "
                            "Tente novamente com uma foto mais nítida."}), 500

        rascunho["itens"] = resultado["itens"]
        rascunho["imagem_processada"] = resultado["imagem_processada"]
        rascunho["folha_detectada"] = resultado["folha_detectada"]
        rascunho["ficha_calibrada"] = resultado["ficha_calibrada"]
        rascunho["foto_borrada"] = resultado["foto_borrada"]
        rascunho["qualidade_baixa"] = resultado["qualidade_baixa"]
        salvar_rascunho(rascunho)
        return jsonify({"ok": True, "proxima": url_for("conferencia"),
                        "folha_detectada": resultado["folha_detectada"],
                        "ficha_calibrada": resultado["ficha_calibrada"],
                        "foto_borrada": resultado["foto_borrada"],
                        "qualidade_baixa": resultado["qualidade_baixa"]})

    @app.post("/api/pular_foto")
    def api_pular_foto():
        """Permite seguir para a conferência sem foto (marcação manual)."""
        rascunho = rascunho_atual()
        if not rascunho:
            return jsonify({"ok": False, "erro": "Inicie um orçamento primeiro."}), 400
        rascunho.pop("itens", None)
        rascunho.pop("imagem_processada", None)
        salvar_rascunho(rascunho)
        return jsonify({"ok": True, "proxima": url_for("conferencia")})

    @app.post("/api/gerar_pdf")
    def api_gerar_pdf():
        rascunho = rascunho_atual()
        if not rascunho:
            return jsonify({"ok": False, "erro": "Nenhum orçamento em andamento."}), 400
        corpo = request.json or {}

        # A tela de conferência envia o estado final revisado pelo usuário —
        # o PDF nunca é gerado sem passar por ela.
        pecas = [p for p in corpo.get("pecas", []) if p.get("peca", "").strip()]
        if not pecas:
            return jsonify({"ok": False, "erro": "Selecione ao menos uma peça antes de gerar o PDF."}), 400
        rascunho["observacoes"] = corpo.get("observacoes", "").strip()
        rascunho["pecas"] = pecas
        rascunho["gerado_em"] = datetime.now().strftime("%d/%m/%Y %H:%M")

        try:
            nome_pdf = pdf_generator.gerar_pdf(rascunho)
        except Exception:
            log.exception("Erro ao gerar PDF da OS %s", rascunho.get("numero"))
            return jsonify({"ok": False, "erro": "Erro ao gerar o PDF. Veja o log."}), 500

        rascunho["arquivo_pdf"] = nome_pdf
        rascunho["mensagem_whatsapp"] = pdf_generator.mensagem_whatsapp(rascunho)
        salvar_rascunho(rascunho)
        historico.registrar_pdf(
            rascunho.get("numero", ""), rascunho.get("cliente", ""),
            rascunho.get("placa", ""), rascunho.get("veiculo", ""),
            rascunho.get("tipo_ficha_nome") or rascunho.get("tipo_ficha", ""),
            nome_pdf, rascunho["observacoes"])
        return jsonify({"ok": True, "proxima": url_for("pdf_gerado")})

    @app.post("/api/calibracao/<tipo>")
    def api_calibracao(tipo):
        corpo = request.json or {}
        try:
            ficha = template_mapper.salvar_calibracao(
                tipo, corpo.get("caixas", []),
                corpo.get("ref_largura", 1000), corpo.get("ref_altura", 1414))
        except (ValueError, KeyError, TypeError) as exc:
            log.error("Calibração inválida (%s): %s", tipo, exc)
            return jsonify({"ok": False, "erro": "Dados de calibração inválidos."}), 400
        return jsonify({"ok": True, "calibrada": ficha["calibrada"]})

    @app.post("/api/calibracao/<tipo>/imagem")
    def api_calibracao_imagem(tipo):
        """Recebe a foto/scan da ficha em branco e devolve a folha alinhada."""
        try:
            ficha = template_mapper.carregar_ficha(tipo)
        except ValueError:
            return jsonify({"ok": False, "erro": "Tipo de ficha desconhecido."}), 400
        arquivo = request.files.get("foto")
        if not arquivo or not arquivo.filename:
            return jsonify({"ok": False, "erro": "Nenhuma imagem recebida."}), 400
        destino = Path(config.PASTA_UPLOADS) / f"calibracao_{uuid.uuid4().hex}{Path(arquivo.filename).suffix.lower()}"
        arquivo.save(destino)
        try:
            imagem = image_processor.ler_imagem(destino)
            if imagem is None:
                raise image_processor.ErroProcessamentoImagem("Imagem inválida.")
            alinhada, _ = image_processor.alinhar_folha(
                imagem, ficha["ref_largura"], ficha["ref_altura"])
            nome = f"calibracao_{tipo}.jpg"
            image_processor.salvar_imagem(Path(config.PASTA_PROCESSADAS) / nome, alinhada)
        except image_processor.ErroProcessamentoImagem as exc:
            return jsonify({"ok": False, "erro": str(exc)}), 400
        return jsonify({"ok": True, "imagem": url_for("servir_processada", nome=nome)})

    return app


app = criar_app()

if __name__ == "__main__":
    log.info("Iniciando Orçamento Express Oficina em %s:%s (debug=%s, demo=%s)",
             config.HOST, config.PORTA, config.DEBUG, config.MECAUTO_MODO_DEMO)
    print(f"\n  Orçamento Express Oficina rodando em http://{config.HOST}:{config.PORTA}")
    print("  No celular, acesse http://IP-DO-COMPUTADOR:%d (mesma rede Wi-Fi)\n" % config.PORTA)
    app.run(host=config.HOST, port=config.PORTA, debug=config.DEBUG)
