"""Testes do leitor MecAuto: garante o isolamento SOMENTE LEITURA."""
import pytest

from database import mecauto_reader


def test_select_simples_passa_na_validacao():
    mecauto_reader._validar_somente_select("SELECT * FROM TAB_CAD_OS")
    mecauto_reader._validar_somente_select("  select first 1 CM_NOM_CLI from TAB_CAD_OS where CM_NUM_OS = ?")


@pytest.mark.parametrize("sql", [
    "UPDATE TAB_CAD_OS SET CM_NOM_CLI='X'",
    "DELETE FROM TAB_CAD_OS",
    "INSERT INTO TAB_CAD_OS VALUES (1)",
    "DROP TABLE TAB_CAD_OS",
    "ALTER TABLE TAB_CAD_OS ADD CAMPO INT",
    "CREATE TABLE NOVA (ID INT)",
    "EXECUTE PROCEDURE APAGA_TUDO",
    "SELECT * FROM TAB_CAD_OS; DELETE FROM TAB_CAD_OS",  # empilhamento de comandos
    "SELECT * FROM TAB_CAD_OS -- comentario",            # comentário
    "GRANT ALL ON TAB_CAD_OS TO PUBLIC",
])
def test_sql_perigoso_e_bloqueado(sql):
    with pytest.raises(mecauto_reader.ErroLeituraMecAuto):
        mecauto_reader._validar_somente_select(sql)


def test_consultar_rejeita_nao_select_antes_de_conectar():
    # Mesmo sem banco configurado, o bloqueio acontece antes da conexão.
    with pytest.raises(mecauto_reader.ErroLeituraMecAuto):
        mecauto_reader.consultar("DELETE FROM TAB_CAD_OS")


def test_busca_em_modo_demo_nao_conecta():
    dados = mecauto_reader.buscar_os_por_numero("42")
    assert dados["encontrado"] is True
    assert dados["origem"] == "demo"
    assert dados["cliente"]
    assert dados["situacao"]


def test_busca_numero_invalido():
    dados = mecauto_reader.buscar_os_por_numero("abc")
    assert dados["encontrado"] is False


def test_situacoes_finais_para_limpeza_de_sobreposicao():
    # 3=CONCLUÍDO, 4=AGU. FATURAMENTO, 9=CANCELADO — conforme documentação do MecAuto
    assert mecauto_reader.SITUACOES_FINAIS == {3, 4, 9}
    assert mecauto_reader.SITUACOES[1] == "AGU. APROVAÇÃO"
