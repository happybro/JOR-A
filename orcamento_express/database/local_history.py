"""
Banco SQLite LOCAL do Orçamento Express.

Guarda apenas dados do novo sistema: histórico de PDFs gerados e rascunhos
de orçamento em andamento. Não tem nenhuma relação com o banco do JJSoft.
"""
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

log = logging.getLogger("orcamento_express.historico")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS historico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em TEXT NOT NULL,
    numero_os TEXT,
    cliente TEXT,
    placa TEXT,
    veiculo TEXT,
    tipo_ficha TEXT,
    arquivo_pdf TEXT NOT NULL,
    observacoes TEXT
);
CREATE TABLE IF NOT EXISTS rascunhos (
    id TEXT PRIMARY KEY,
    atualizado_em TEXT NOT NULL,
    dados TEXT NOT NULL
);
"""


class HistoricoLocal:
    def __init__(self, caminho_db: Path):
        self.caminho_db = Path(caminho_db)
        self.caminho_db.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as con:
            con.executescript(_SCHEMA)

    def _conn(self):
        con = sqlite3.connect(self.caminho_db, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    # ------------------------------ histórico ------------------------------
    def registrar_pdf(self, numero_os, cliente, placa, veiculo, tipo_ficha,
                      arquivo_pdf, observacoes=""):
        with self._conn() as con:
            con.execute(
                "INSERT INTO historico (criado_em, numero_os, cliente, placa, "
                "veiculo, tipo_ficha, arquivo_pdf, observacoes) VALUES (?,?,?,?,?,?,?,?)",
                (datetime.now().strftime("%d/%m/%Y %H:%M"), numero_os, cliente,
                 placa, veiculo, tipo_ficha, arquivo_pdf, observacoes),
            )
        log.info("PDF registrado no histórico: %s (OS %s)", arquivo_pdf, numero_os)

    def listar(self, limite=200):
        with self._conn() as con:
            linhas = con.execute(
                "SELECT * FROM historico ORDER BY id DESC LIMIT ?", (limite,)
            ).fetchall()
        return [dict(l) for l in linhas]

    # ------------------------------ rascunhos ------------------------------
    def salvar_rascunho(self, id_rascunho: str, dados: dict):
        with self._conn() as con:
            con.execute(
                "INSERT INTO rascunhos (id, atualizado_em, dados) VALUES (?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET atualizado_em=excluded.atualizado_em, "
                "dados=excluded.dados",
                (id_rascunho, datetime.now().isoformat(),
                 json.dumps(dados, ensure_ascii=False)),
            )

    def carregar_rascunho(self, id_rascunho: str):
        with self._conn() as con:
            linha = con.execute(
                "SELECT dados FROM rascunhos WHERE id = ?", (id_rascunho,)
            ).fetchone()
        return json.loads(linha["dados"]) if linha else None
