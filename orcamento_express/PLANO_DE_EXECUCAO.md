# Plano de Execução — Orçamento Express Oficina (BF Trucks / MecAuto)

Data: 07/07/2026 · Status: **MVP implementado, testado e validado ponta a ponta**

## 1. O que foi encontrado

- **Documentação do banco** (`MECAUTO_BANCO_REFERENCIA.md`, anexada): schema
  Firebird 2.5 confirmado em produção, tabela central `TAB_CAD_OS` com FKs
  para cliente, veículo/chassi, peças/serviços já lançados e histórico de
  situação. Regra de ouro: `SELECT FIRST n`, `CM_NUM_OS` (visível) ≠
  `CM_COD_OS` (chave interna, nunca mostrar ao usuário).
- **Planilha modelo** (`OR_AMENTO_MOTOR_FH_D13_PARCIAL_2026.xlsx`, anexada):
  uma aba única, "PEDIDO DE PEÇAS", com 41 itens no formato
  `QUANTIDADE - DESCRIÇÃO (código opcional)`, título
  "RELAÇÃO DE PEÇAS P/ RECONDICIONAMENTO PARCIAL DE MOTOR" e rodapé com
  contato do setor de compras. **Não tem grade de quadrados de marcação** —
  é uma lista de texto com borda simples em cada linha.

## 2. Decisão de arquitetura mais importante

Como a planilha não tem posições fixas de marcação para calibrar, a
alternativa seria pedir para você calibrar manualmente cada uma das 41
peças clicando numa foto — viável, mas repetitivo e frágil (se a folha for
fotocopiada torta, a calibração pode não bater mais).

**Decisão tomada:** o próprio sistema **imprime a ficha** (mesmo conteúdo
da planilha, mesmo texto, mesmas quantidades sugeridas) já com um quadrado
de marcação ao lado de cada peça, numa posição que ele mesmo escolhe e
depois usa como referência para ler a foto. Isso elimina a calibração
manual para esse fluxo (ela continua disponível como opção, caso a oficina
prefira usar uma ficha externa).

Validado com teste automatizado que simula uma foto real (ficha impressa,
marcada com X, fotografada com leve rotação, sobre fundo escuro): **6 de 6
peças marcadas foram lidas corretamente, 0 falsos positivos** entre as
outras 35 peças, após calibrar o limiar de detecção (margem interna do
quadrado de 15%→25%, necessária porque quadrados pequenos "vazavam" pixels
da própria borda impressa para a leitura).

**Atualização — detecção adaptativa por foto:** o limiar fixo inicial
funcionava bem só na condição de luz/exposição usada para calibrá-lo. Como
cada foto de celular varia (sombra, exposição automática, distância), a
classificação de cada quadrado passou a comparar com a MEDIANA e o desvio
robusto (MAD) da própria foto, em vez de um número fixo global — além de:
- correção de iluminação desigual (achata sombra/gradiente de luz antes de binarizar);
- detecção de foto borrada (variância do Laplaciano) — abaixo do mínimo, desativa a leitura automática e pede conferência manual;
- salvaguarda contra "inventar" marcação em folha em branco (se a foto inteira não tem separação estatística confiável, tudo cai em conferência manual);
- piso absoluto ainda vale para fichas com poucos itens (< 5 quadrados), onde a comparação estatística não é confiável.

Testado com 6 cenários (luz uniforme, gradiente de luz, marca fraca de
lápis, marca fraca + gradiente combinados, foto borrada, folha em branco) —
100% de acerto nos casos com marcação real, e as duas salvaguardas (foto
borrada / folha em branco) recusaram a leitura automática corretamente em
vez de arriscar.

**Atualização — marcadores de alinhamento (ArUco), a correção mais
importante até agora:** você testou com uma foto real (mesa de madeira, luz
de lâmpada, ângulo de câmera) e a detecção saiu **totalmente errada** — um
bloco inteiro de peças não marcadas apareceu como marcado, e peças
realmente marcadas ficaram de fora. A causa raiz não era o limiar de
detecção: era a etapa de **alinhar a foto**, que até então tentava adivinhar
"qual contorno claro na imagem é a folha de papel" — funciona numa foto de
teste com fundo escuro uniforme, mas falha numa mesa de madeira de verdade
com textura e luz desigual.

Troquei essa etapa por **marcadores ArUco** (biblioteca já embutida no
OpenCV, offline, sem custo): 4 marcadores pequenos, um em cada canto da
ficha impressa, com ID codificado no próprio desenho. A detecção não
depende mais de contraste com o fundo — só do marcador em si — e funciona
com precisão sub-pixel mesmo em fundo texturizado e luz desigual.

No caminho, encontrei e corrigi um segundo bug (de correspondência
geométrica, não de detecção): os marcadores ficam a 18 unidades da borda do
papel (margem de impressão seguro), e o código estava tratando esse ponto
como se fosse o canto absoluto (0,0) da página — isso introduzia um erro de
escala que crescia com a distância dos marcadores, explicando por que só
alguns itens (os mais pertos dos marcadores) saíam certos.

Revalidei com o cenário mais hostil que consegui simular (mesa de madeira
texturizada, luz de lâmpada em gradiente, perspectiva de câmera real via
homografia — não só rotação): **6 de 6 peças marcadas corretas, 0 falsos
positivos entre as outras 35**, com confiança consistente em toda a página
(antes variava de 0.0 a 0.7 dependendo da posição — agora fica estável em
~0.68-0.72 em qualquer lugar da ficha). Confirmado também pela interface
real (upload → conferência → PDF), não só pelo teste isolado.

Se os marcadores não forem encontrados numa foto (canto cortado, dobrado,
reflexo de luz em cima), o sistema cai para o método antigo (contorno) como
reserva, avisando na tela que a leitura pode ser menos precisa — nunca
finge confiança que não tem.

**Atualização — leitura por quadrado à prova de mundo real:** mesmo com os
marcadores, a foto real seguinte (ficha impressa de verdade) ainda mostrou
falsos positivos. Causa: papel levemente curvado na mesa + escala da
impressora deslocam cada quadrado alguns milímetros em relação ao
alinhamento global — a borda impressa do próprio quadrado "vazava" para
dentro da área medida e virava tinta falsa. Três mudanças estruturais:

1. **Snap local por quadrado**: antes de medir, o sistema encontra a borda
   impressa DE VERDADE de cada quadrado perto da posição esperada e mede
   dentro do quadrado encontrado — imune a papel ondulado e margem de
   impressora.
2. **Detecção por traço, não por pixels soltos**: além da fração de tinta,
   mede o tamanho da maior mancha conectada. Um X ou rabisco de caneta
   forma UM traço grande; ruído de sombra/textura/compressão JPEG vira
   pixels espalhados. Exigir o traço elimina os falsos positivos.
3. **Nunca pré-marcar dúvida**: a regra antiga pré-marcava itens de "zona
   cinzenta" (com aviso amarelo) — era justamente o que gerava peças
   marcadas sem estar. Agora dúvida fica DESMARCADA + amarelo; o sistema
   só marca sozinho com evidência forte.

Além disso, os quadrados da ficha impressa ficaram maiores (≈5,5mm), mais
fáceis de marcar e de ler.

Bateria de validação (todos com mesa de madeira, luz de lâmpada em
gradiente, perspectiva real de câmera E papel ondulado): um único rabisco
de preenchimento (o caso da foto real), seis X de caneta, folha em branco,
mistura X + rabisco, curvatura extrema, JPEG qualidade 45 (recompressão de
WhatsApp) e lápis fraco — **zero falsos positivos e zero peças perdidas em
todos**. Confirmado também pela interface real: 1 de 41 marcado na tela de
conferência para a foto com um único rabisco.

## 3. Arquitetura

- **Flask** em porta própria (5055), acessível pelo celular na rede local.
- **MecAuto**: `database/mecauto_reader.py` — só SELECT (validado por
  regex antes de qualquer conexão), transação read-only
  (`ISOLATION_LEVEL_READ_COMMITED_RO`), fallback de cópia local do `.CDB`
  se a conexão direta falhar (evita lock com o MecAuto em uso). Usa `fdb`
  (Firebird 2.5, conforme documentado).
- **Modo demo** (`MECAUTO_MODO_DEMO=true`, padrão): dados fictícios para
  testar todo o fluxo sem banco.
- **Fichas dinâmicas**: qualquer `.json` em `ficha_templates/` vira um tipo
  de ficha automaticamente — sem alterar código para adicionar câmbio,
  diferencial ou outro modelo de motor.
- **Layout automático** (`services/template_mapper.calcular_layout_automatico`):
  calcula posição de quadrado em duas colunas, de forma determinística
  (mesma quantidade de itens → mesmas coordenadas), usada tanto para
  desenhar a ficha impressa (`services/ficha_pdf.py`) quanto para ler a
  foto depois (`services/image_processor.py`).
- **OpenCV**: localiza o contorno da folha, corrige perspectiva, binariza e
  mede o preenchimento de cada quadrado. Três faixas: marcado / vazio /
  **incerto → "Conferir este item manualmente"**.
- **ReportLab** para os dois PDFs (ficha para impressão + pedido final);
  **SQLite** local para histórico e rascunhos; logs rotativos.

## 4. Etapas do MVP (todas concluídas)

1. ✅ Estrutura, config por `.env`, logs.
2. ✅ Leitor MecAuto somente leitura, com fallback de cópia local + modo demo.
3. ✅ Telas: início, novo orçamento, captura (com botão de imprimir ficha),
   conferência, PDF gerado, histórico, configurações, calibração manual opcional.
4. ✅ Geração da ficha para impressão com quadrados auto-posicionados.
5. ✅ Processamento de imagem (alinhamento + detecção calibrada automaticamente).
6. ✅ Geração de PDF final + mensagem WhatsApp + histórico local.
7. ✅ 37 testes automatizados + checklist manual + documentação.
8. ✅ **Validação ponta a ponta**: fluxo completo dirigido via navegador
   (Playwright), com foto simulada da ficha real marcada — captura,
   detecção, conferência e PDF final todos conferidos visualmente.

## 5. Limitações conhecidas

- Só existe o template real de **Motor FH D13 Parcial** (41 peças, vindo da
  planilha anexada). Câmbio e diferencial ainda não têm planilha equivalente
  — quando você mandar, crio os `.json` do mesmo jeito.
- A busca no MecAuto está mapeada conforme o `.md` de referência; como não
  há acesso ao banco real neste ambiente, a consulta só foi validada em
  **modo demo**. Recomendo testar a busca real na oficina antes de confiar
  100% (ver checklist manual, item 4).
- Detecção depende de a ficha ser impressa **pelo próprio sistema** (as
  coordenadas só batem com o layout que ele mesmo gerou). Fichas
  fotocopiadas de fora exigem calibração manual.
- OCR de texto manuscrito (observações do mecânico) não é feito — só
  marcação por quadrado. Observações continuam sendo digitadas na conferência.

## 6. Próximos passos sugeridos

1. Testar a busca real no MecAuto na oficina (`MECAUTO_MODO_DEMO=false` +
   `MECAUTO_DSN` correto) e confirmar que os campos batem com o que aparece
   no MecAuto/JJSOFT.
2. Imprimir a ficha real numa impressora da oficina (não só visualizar em
   PDF) e testar a foto com a câmera de um celular de verdade — a simulação
   usou uma composição sintética; vale confirmar com papel físico.
3. Mandar as planilhas de câmbio e diferencial (mesmo formato) para eu gerar
   os templates correspondentes.
4. Rodar `gerar_executavel.bat` no Windows da oficina para obter o `.exe`.
5. (Futuro, se quiser) iniciar junto com o Windows, HTTPS local, múltiplos
   usuários.

## 7. Pontos que precisam da sua confirmação

| # | Pergunta | Situação atual |
|---|---|---|
| 1 | IP do servidor MecAuto e caminho real do `CICOM.CDB` | Modo demo ativo até configurar |
| 2 | Usuário/senha reais do Firebird (se diferentes de SYSDBA/masterkey) | Usando padrão do `.md` |
| 3 | Planilhas de câmbio/diferencial, quando tiver | Só motor FH D13 parcial implementado |
| 4 | Nome/telefone reais do responsável por compras (se diferente de Marcos Nunes) | Preenchido conforme a planilha anexada |
| 5 | A ficha impressa pelo sistema substitui a planilha atual no dia a dia? | Recomendado, mas a calibração manual continua disponível se preferir manter a ficha antiga |

Nenhuma dessas pendências impede de usar o sistema hoje em modo demo.
