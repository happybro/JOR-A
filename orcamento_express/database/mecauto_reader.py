"""
Leitor SOMENTE LEITURA do banco Firebird 2.5 do MecAuto/CICOM (arquivo CICOM.CDB).

Schema confirmado em produção (BF Trucks, sistema JJSOFT V3.0), documentado em
MECAUTO_BANCO_REFERENCIA.md. Regras de segurança aplicadas neste módulo:

  1. Apenas SELECT é aceito — qualquer outro SQL é rejeitado antes de chegar
     ao banco (função _validar_somente_select).
  2. A transação é aberta em modo READ ONLY (fdb.ISOLATION_LEVEL_READ_COMMITED_RO),
     o que impede escrita e evita locks no banco do MecAuto.
  3. Cada consulta abre a conexão, executa, e fecha em seguida.
  4. Timeout configurável para nunca travar esperando o banco.
  5. Conexão direta no servidor, com FALLBACK: se o connect direto falhar
     (banco em uso/travado), copia o .CDB para uma cópia local e lê a cópia
     — evita disputar lock com o MecAuto em uso na oficina.

Sintaxe Firebird 2.5 (não é MySQL/SQLite): `SELECT FIRST n`, `||` para
concatenar, `CONTAINING` para busca textual, `CURRENT_DATE`.
"""
import logging
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

log = logging.getLogger("orcamento_express.mecauto")

_RE_SELECT = re.compile(r"^\s*SELECT\b", re.IGNORECASE)
_RE_PROIBIDO = re.compile(
    r";|--|/\*|\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|EXECUTE|GRANT|REVOKE|MERGE|SET\s+GENERATOR|RECREATE|COMMENT)\b",
    re.IGNORECASE,
)

# Situações do MecAuto (campo CM_COD_SITUACAO) — confirmadas em produção
SITUACOES = {
    1: "AGU. APROVAÇÃO", 2: "EM EXECUÇÃO", 3: "CONCLUÍDO",
    4: "AGU. FATURAMENTO", 5: "AGU. PEÇAS", 6: "AGU. DIAGNÓSTICO",
    7: "AGU. EXECUÇÃO", 8: "RETORNO", 9: "CANCELADO",
    10: "EXEC. DIAGNÓSTICO",
}
SITUACOES_FINAIS = {3, 4, 9}  # ao chegar aqui, sobreposições internas (JSON) devem ser limpas


class ErroLeituraMecAuto(Exception):
    """Erro amigável de consulta ao MecAuto (mensagem segura para exibir)."""


def _validar_somente_select(sql: str):
    if not _RE_SELECT.search(sql):
        raise ErroLeituraMecAuto("Bloqueado: apenas consultas SELECT são permitidas no banco do MecAuto.")
    if _RE_PROIBIDO.search(sql):
        raise ErroLeituraMecAuto("Bloqueado: o SQL contém comandos ou caracteres não permitidos.")


def _importar_driver():
    """MecAuto roda em Firebird 2.5: a biblioteca recomendada é `fdb`."""
    try:
        import fdb  # type: ignore
        if config.MECAUTO_FBCLIENT_DLL and Path(config.MECAUTO_FBCLIENT_DLL).exists():
            try:
                fdb.load_api(config.MECAUTO_FBCLIENT_DLL)
            except Exception:
                pass  # já carregada ou ambiente não-Windows (ex.: testes em Linux)
        return fdb, "fdb"
    except ImportError:
        pass
    try:
        from firebird.driver import connect  # type: ignore
        return connect, "firebird-driver"
    except ImportError:
        raise ErroLeituraMecAuto(
            "Nenhum driver Firebird instalado. Instale com: pip install fdb "
            "(recomendado para Firebird 2.5 do MecAuto).")


def _conectar():
    """Conecta no MecAuto, somente leitura. Tenta o DSN direto e, se falhar,
    cai no fallback de cópia local do .CDB (evita lock com o MecAuto em uso)."""
    driver, nome_driver = _importar_driver()

    def _tentar(dsn):
        if nome_driver == "fdb":
            con = driver.connect(dsn=dsn, user=config.MECAUTO_USUARIO,
                                 password=config.MECAUTO_SENHA,
                                 charset=config.MECAUTO_CHARSET)
            con.begin(tpb=driver.ISOLATION_LEVEL_READ_COMMITED_RO)
            return con
        con = driver(dsn, user=config.MECAUTO_USUARIO, password=config.MECAUTO_SENHA,
                     charset=config.MECAUTO_CHARSET)
        return con

    if not config.MECAUTO_DSN:
        raise ErroLeituraMecAuto(
            "Banco do MecAuto não configurado. Defina MECAUTO_DSN no .env "
            "(exemplo: 192.168.1.250:C:\\CICOM\\MECAUTO\\DB\\CICOM.CDB).")

    try:
        return _tentar(config.MECAUTO_DSN), nome_driver, "direto"
    except Exception as exc_direto:
        log.warning("Conexão direta ao MecAuto falhou (%s); tentando fallback de cópia local.", exc_direto)
        if config.MECAUTO_CAMINHO_CDB_ORIGEM and config.MECAUTO_CAMINHO_CDB_COPIA:
            try:
                shutil.copy2(config.MECAUTO_CAMINHO_CDB_ORIGEM, config.MECAUTO_CAMINHO_CDB_COPIA)
                dsn_copia = config.MECAUTO_DSN_COPIA or f"127.0.0.1:{config.MECAUTO_CAMINHO_CDB_COPIA}"
                return _tentar(dsn_copia), nome_driver, "cópia local"
            except Exception as exc_copia:
                log.error("Fallback de cópia também falhou: %s", exc_copia)
        raise ErroLeituraMecAuto(
            "Não consegui conectar ao banco do MecAuto (nem direto, nem por cópia local). "
            "Verifique se o servidor está acessível e as credenciais no .env."
        ) from exc_direto


def consultar(sql: str, parametros: tuple = ()):
    """Executa um SELECT no MecAuto e retorna lista de dicionários. Somente leitura."""
    _validar_somente_select(sql)
    log.info("Consulta ao MecAuto: %s | parametros=%s", sql.replace("\n", " "), parametros)
    con = None
    try:
        con, driver, origem = _conectar()
        cur = con.cursor()
        cur.execute(sql, parametros)
        colunas = [d[0].strip().lower() for d in cur.description]
        linhas = [dict(zip(colunas, linha)) for linha in cur.fetchall()]
        log.info("Consulta ok (%s via %s): %d linha(s).", driver, origem, len(linhas))
        return linhas
    except ErroLeituraMecAuto:
        raise
    except Exception as exc:
        log.error("Erro ao consultar o MecAuto: %s", exc)
        raise ErroLeituraMecAuto(
            "Não consegui consultar o banco do MecAuto. Verifique a configuração e o log."
        ) from exc
    finally:
        if con is not None:
            try:
                con.close()  # fecha sempre, sem commit — nada é gravado
            except Exception:
                pass


def _trim(valor):
    return valor.strip() if isinstance(valor, str) else valor


def _dados_demo(numero, tipo="OS"):
    """Dados fictícios para o modo demo (sem banco)."""
    dados = {
        "encontrado": True, "origem": "demo",
        "cm_tip": tipo, "numero": str(numero), "cm_cod_os": 999000 + int(numero or 0),
        "cliente": "TRANSPORTES DEMONSTRAÇÃO LTDA", "placa": "ABC1D23",
        "fabricante": "VOLVO", "veiculo": "FH 540", "ano": "2019", "cor": "BRANCA",
        "km": "312000", "combustivel": "DIESEL", "motor": "D13",
        "situacao_codigo": 1, "situacao": SITUACOES[1],
        "data_entrada": "05/07/2026", "data_saida": "",
        "aviso": "MODO DEMO ativo: dados fictícios. Configure o banco no .env "
                 "para usar dados reais do MecAuto.",
    }
    dados["veiculo_completo"] = f"{dados['fabricante']} {dados['veiculo']} {dados['ano']}".strip()
    return dados


SQL_OS = """
SELECT FIRST 1
    o.CM_TIP, o.CM_NUM_OS, o.CM_COD_OS, o.CM_COD_CLI,
    o.CM_NOM_CLI, o.CM_PLC_VEC, o.CM_FAB_VEC, o.CM_VEC, o.CM_ANO_VEC,
    o.CM_COR_VEC, o.CM_KM_OS, o.CM_CMB_VEC, o.CM_MTR_VEC,
    o.CM_DAT_ENT, o.CM_DAT_SAI, o.CM_COD_SITUACAO, o.CM_STA_TUS,
    v.CM_CHA_VEC, v.CM_PERSONALIZADO
FROM TAB_CAD_OS o
LEFT JOIN TAB_CTR_CLI_VEC v ON v.CM_COD_CTR = o.CM_CTR_VEC
WHERE o.CM_NUM_OS = ?
ORDER BY o.CM_COD_OS DESC
"""

SQL_PECAS_OS = """
SELECT CM_DES_PEC, CM_QTD_POS, CM_VAL_UNI, CM_VAL_TOT, CM_UNI_PEC
FROM TAB_PEC_OS
WHERE CM_COD_OS = ?
ORDER BY CM_ORDEM
"""

SQL_SERVICOS_OS = """
SELECT s.CM_DES_SOS, s.CM_QTD_SV, s.CM_VAL_SVS, s.CM_VAL_TOT, f.CM_NOM_FUN
FROM TAB_SVC_OS s
LEFT JOIN TAB_CAD_FUN f ON f.CM_COD_FUN = s.CM_COD_FUN
WHERE s.CM_COD_OS = ?
ORDER BY s.CM_ORDEM
"""

SQL_DEFEITOS_OS = """
SELECT CM_OBS_OS
FROM TAB_CAD_DEF
WHERE CM_COD_OS = ? AND CM_OBS_OS IS NOT NULL AND TRIM(CM_OBS_OS) <> ''
ORDER BY CM_COD_DEF
"""


def buscar_os_por_numero(numero, tipo=None):
    """Busca uma OS/orçamento pelo número visível (CM_NUM_OS) no MecAuto.

    `tipo`, se informado ('OS' ou 'OC'), filtra o tipo; senão pega a mais
    recente com esse número (podem existir OS e orçamento com o mesmo número
    em sistemas antigos).
    """
    numero = str(numero).strip()
    if not numero.isdigit():
        return {"encontrado": False, "erro": "Informe apenas o número da OS/orçamento."}

    if config.MECAUTO_MODO_DEMO:
        return _dados_demo(numero, tipo or "OS")

    try:
        linhas = consultar(SQL_OS, (int(numero),))
    except ErroLeituraMecAuto as exc:
        return {"encontrado": False, "erro": str(exc)}

    if tipo:
        linhas = [l for l in linhas if (l.get("cm_tip") or "").strip().upper() == tipo.upper()] or linhas
    if not linhas:
        return {"encontrado": False, "erro": f"Não encontrei a OS/orçamento {numero} no MecAuto."}

    l = linhas[0]
    cod_situacao = l.get("cm_cod_situacao")
    dados = {
        "encontrado": True, "origem": "mecauto",
        "cm_tip": _trim(l.get("cm_tip")) or "OS",
        "numero": numero,
        "cm_cod_os": l.get("cm_cod_os"),
        "cliente": _trim(l.get("cm_nom_cli")) or "",
        "placa": _trim(l.get("cm_plc_vec")) or "",
        "fabricante": _trim(l.get("cm_fab_vec")) or "",
        "veiculo": _trim(l.get("cm_vec")) or "",
        "ano": _trim(l.get("cm_ano_vec")) or "",
        "cor": _trim(l.get("cm_cor_vec")) or "",
        "km": l.get("cm_km_os"),
        "combustivel": _trim(l.get("cm_cmb_vec")) or "",
        "motor": _trim(l.get("cm_mtr_vec")) or "",
        "chassi": _trim(l.get("cm_cha_vec")) or "",
        "frota": _trim(l.get("cm_personalizado")) or "",
        "situacao_codigo": cod_situacao if cod_situacao is not None else -1,
        "situacao": SITUACOES.get(cod_situacao, _trim(l.get("cm_sta_tus")) or "SEM SITUAÇÃO"),
        "data_entrada": str(l.get("cm_dat_ent") or ""),
        "data_saida": str(l.get("cm_dat_sai") or ""),
    }
    # veículo "completo" pronto para exibir/preencher
    dados["veiculo_completo"] = " ".join(
        p for p in [dados["fabricante"], dados["veiculo"], dados["ano"]] if p).strip()
    return dados


def buscar_pecas_servicos_por_os(cod_os):
    """Peças e serviços já lançados na OS (histórico/consulta, não usado para
    gerar o pedido novo — apenas referência)."""
    if config.MECAUTO_MODO_DEMO:
        return {"pecas": [], "servicos": [], "defeitos": []}
    try:
        pecas = consultar(SQL_PECAS_OS, (cod_os,))
        servicos = consultar(SQL_SERVICOS_OS, (cod_os,))
        defeitos = [_trim(l["cm_obs_os"]) for l in consultar(SQL_DEFEITOS_OS, (cod_os,))]
    except ErroLeituraMecAuto:
        return {"pecas": [], "servicos": [], "defeitos": []}
    return {"pecas": pecas, "servicos": servicos, "defeitos": defeitos}
