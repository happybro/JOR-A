"""
Configurações do Orçamento Express Oficina (BF Trucks / MecAuto).

Todas as configurações podem ser sobrescritas por variáveis de ambiente
ou por um arquivo .env na raiz do projeto (veja .env.example).

IMPORTANTE: este sistema NUNCA escreve no banco do MecAuto (CICOM.CDB).
As credenciais abaixo são usadas apenas para consultas SELECT.
"""
import os
import shutil
import sys
from pathlib import Path

# Diretório dos recursos empacotados (templates, static, fichas padrão).
# Quando rodando como .exe (PyInstaller onefile), isso aponta para a pasta
# temporária onde o executável se extrai — correto para LER recursos
# embutidos, mas essa pasta some quando o programa fecha.
RECURSOS_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

# Diretório onde o sistema GRAVA dados (histórico, PDFs, fotos, logs).
# Quando rodando como .exe, isso é a pasta onde o .exe está (persiste entre
# execuções) — NUNCA a pasta temporária do PyInstaller, que é apagada ao
# fechar o programa e faria o histórico "sumir" a cada reinício.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent


def _carregar_env():
    """Carrega variáveis de um arquivo .env simples (chave=valor), se existir.

    Não usa biblioteca externa para manter a instalação leve.
    Variáveis já definidas no ambiente têm prioridade sobre o .env.
    """
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for linha in env_path.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        chave = chave.strip()
        valor = valor.strip().strip('"').strip("'")
        os.environ.setdefault(chave, valor)


_carregar_env()


def _bool(nome, padrao="false"):
    return os.environ.get(nome, padrao).strip().lower() in ("1", "true", "sim", "yes", "on")


# ---------------------------------------------------------------------------
# Servidor web (NUNCA usar a mesma porta do MecAuto/JJSoft)
# ---------------------------------------------------------------------------
HOST = os.environ.get("OE_HOST", "0.0.0.0")          # 0.0.0.0 = acessível pelo celular na rede
PORTA = int(os.environ.get("OE_PORTA", "5055"))
DEBUG = _bool("OE_DEBUG", "false")
SECRET_KEY = os.environ.get("OE_SECRET_KEY", "troque-esta-chave-em-producao")

# Nome da oficina exibido nas telas e no PDF
NOME_OFICINA = os.environ.get("OE_NOME_OFICINA", "BF Trucks")
# Rodapé do pedido de peças (setor de compras) — ajuste para a sua oficina
OE_RESPONSAVEL_COMPRAS = os.environ.get("OE_RESPONSAVEL_COMPRAS", "")
OE_TELEFONE_COMPRAS = os.environ.get("OE_TELEFONE_COMPRAS", "")
OE_DEPARTAMENTO_COMPRAS = os.environ.get("OE_DEPARTAMENTO_COMPRAS", "DPTO. DE COMPRAS")

# ---------------------------------------------------------------------------
# Banco Firebird do MecAuto (CICOM.CDB) — SOMENTE LEITURA
# ---------------------------------------------------------------------------
# DSN direto no servidor da rede, ex.: 192.168.1.250:C:\CICOM\MECAUTO\DB\CICOM.CDB
MECAUTO_DSN = os.environ.get("MECAUTO_DSN", "")
# DSN de uma cópia local (fallback), ex.: 127.0.0.1:C:\CICOM\MECAUTO\DB\CICOM_DASH.CDB
MECAUTO_DSN_COPIA = os.environ.get("MECAUTO_DSN_COPIA", "")
# Caminho de origem do .CDB para copiar (necessário só se usar o fallback de cópia)
MECAUTO_CAMINHO_CDB_ORIGEM = os.environ.get("MECAUTO_CAMINHO_CDB_ORIGEM", "")
MECAUTO_CAMINHO_CDB_COPIA = os.environ.get("MECAUTO_CAMINHO_CDB_COPIA", "")
MECAUTO_USUARIO = os.environ.get("MECAUTO_USUARIO", "SYSDBA")
MECAUTO_SENHA = os.environ.get("MECAUTO_SENHA", "masterkey")
MECAUTO_CHARSET = os.environ.get("MECAUTO_CHARSET", "WIN1252")
# Caminho do fbclient.dll (Firebird 2.5), usado por fdb.load_api() no Windows
MECAUTO_FBCLIENT_DLL = os.environ.get(
    "MECAUTO_FBCLIENT_DLL", r"C:\Program Files\Firebird\Firebird_2_5\bin\fbclient.dll")
# Timeout (segundos) para conexão/consulta, para nunca travar o MecAuto
MECAUTO_TIMEOUT = int(os.environ.get("MECAUTO_TIMEOUT", "10"))
# Modo demo: retorna dados fictícios sem tocar em banco nenhum.
MECAUTO_MODO_DEMO = _bool("MECAUTO_MODO_DEMO", "true")

# ---------------------------------------------------------------------------
# Pastas de trabalho (todas locais, fora do MecAuto)
# ---------------------------------------------------------------------------
PASTA_UPLOADS = Path(os.environ.get("OE_PASTA_UPLOADS", BASE_DIR / "uploads"))
PASTA_PROCESSADAS = Path(os.environ.get("OE_PASTA_PROCESSADAS", BASE_DIR / "processed"))
PASTA_PDFS = Path(os.environ.get("OE_PASTA_PDFS", BASE_DIR / "pdfs"))
PASTA_LOGS = Path(os.environ.get("OE_PASTA_LOGS", BASE_DIR / "logs"))
PASTA_FICHAS = Path(os.environ.get("OE_PASTA_FICHAS", BASE_DIR / "ficha_templates"))
# Banco SQLite local, usado APENAS pelo novo sistema (histórico e rascunhos)
BANCO_LOCAL = Path(os.environ.get("OE_BANCO_LOCAL", BASE_DIR / "data" / "orcamento_express.db"))

# Tamanho máximo de upload de foto (em MB)
UPLOAD_MAX_MB = int(os.environ.get("OE_UPLOAD_MAX_MB", "20"))

# ---------------------------------------------------------------------------
# Detecção de marcações na foto
# ---------------------------------------------------------------------------
# Fração de pixels escuros dentro do quadrado para considerar MARCADO
DETECCAO_LIMIAR_MARCADO = float(os.environ.get("OE_LIMIAR_MARCADO", "0.18"))
# Abaixo deste valor é considerado NÃO marcado; entre os dois = incerto
DETECCAO_LIMIAR_VAZIO = float(os.environ.get("OE_LIMIAR_VAZIO", "0.07"))


def garantir_pastas():
    """Cria as pastas de trabalho se não existirem.

    Se as fichas padrão (embutidas no .exe) ainda não tiverem sido copiadas
    para a pasta persistente ao lado do executável, copia-as agora — depois
    disso, quem manda é a cópia persistente (o usuário pode editar/adicionar
    fichas ali sem precisar gerar um novo .exe).
    """
    for pasta in (PASTA_UPLOADS, PASTA_PROCESSADAS, PASTA_PDFS,
                  PASTA_LOGS, PASTA_FICHAS, BANCO_LOCAL.parent):
        pasta.mkdir(parents=True, exist_ok=True)

    fichas_embutidas = RECURSOS_DIR / "ficha_templates"
    if fichas_embutidas != PASTA_FICHAS and fichas_embutidas.exists():
        for arquivo in fichas_embutidas.glob("*.json"):
            destino = PASTA_FICHAS / arquivo.name
            if not destino.exists():
                shutil.copy2(arquivo, destino)
