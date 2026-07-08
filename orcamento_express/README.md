# Orçamento Express Oficina (BF Trucks / MecAuto)

Sistema web local para agilizar o pedido de peças de recondicionamento de
motor, câmbio e diferencial: o consultor busca a OS no MecAuto, o mecânico
marca a ficha impressa pelo próprio celular, o sistema lê as marcações
automaticamente, você confere na tela e gera um PDF profissional pronto
para o grupo do WhatsApp.

**Regra número 1:** este sistema **não interfere no MecAuto/JJSoft**. Ele
roda em outra porta (padrão 5055), acessa o banco (`CICOM.CDB`) **somente
para SELECT** em transação somente leitura, e guarda tudo que é dele
(histórico, PDFs, fotos) em pastas e banco SQLite próprios.

## Como funciona (visão geral)

1. Busca a OS/orçamento no MecAuto pelo número (cliente, placa, veículo, motor…).
2. Escolhe o tipo de ficha (ex.: *Motor FH D13 — Recondicionamento Parcial*).
3. **Imprime a ficha pelo próprio sistema** (botão na tela de captura) —
   ela já sai com a lista de peças e um quadrado de marcação ao lado de
   cada item, na posição exata que o sistema também vai procurar na foto.
4. O mecânico marca com X as peças necessárias na folha impressa.
5. Você fotografa a ficha marcada pelo celular, pelo navegador.
6. O sistema alinha a folha e lê os quadrados marcados automaticamente.
7. Tela de **conferência** — nunca gera PDF sem revisão humana.
8. Gera o PDF final do pedido de peças, com botão de copiar mensagem para o WhatsApp.
9. Fica salvo no histórico local.

## Por que a ficha é impressa pelo próprio sistema?

A planilha original (`OR_AMENTO_MOTOR_FH_D13_PARCIAL_2026.xlsx`) é só uma
lista de texto com bordas — não tem quadrados de marcação em posição fixa
para calibrar. Em vez de depender de calibração manual (clicar quadrado por
quadrado numa foto), o sistema **desenha o próprio quadrado de marcação**
ao gerar a ficha para impressão — assim ele sempre sabe exatamente onde
cada marcação deveria estar, sem precisar calibrar nada. Isso foi testado
de ponta a ponta (ficha real de 41 peças, foto simulada com rotação) com
100% de acerto nas peças marcadas.

Se a oficina preferir usar uma ficha própria fora do sistema, a calibração
manual (clicar nos quadrados numa foto) continua disponível em
Configurações → Calibrar manualmente.

### Marcadores nos 4 cantos — não corte nem cubra

A ficha impressa tem um pequeno quadrado preto/branco em cada canto
(marcador ArUco). É assim que o sistema encontra a folha na foto com
precisão, mesmo em cima de mesa de madeira, luz de lâmpada ou foto em
ângulo — muito mais confiável que tentar adivinhar "qual é o contorno da
folha" numa foto real. **Ao imprimir e fotografar, garanta que os 4 cantos
apareçam inteiros na foto** (sem cortar, dobrar ou tampar com o dedo). Se
algum marcador não for encontrado, o sistema avisa na tela de conferência
e usa um método reserva (menos preciso).

## Instalação

Requisitos: Python 3.10+ no computador da oficina (Windows).

```bat
cd orcamento_express
pip install -r requirements.txt
```

> O MecAuto roda em **Firebird 2.5**, então o driver usado é o `fdb`
> (já incluso no requirements.txt). Você também precisa ter o
> `fbclient.dll` do Firebird 2.5 instalado (normalmente já vem com o
> próprio MecAuto/Firebird Server).

## Configuração

```bat
copy .env.example .env
```

Edite o `.env`:

| Chave | O que é |
|---|---|
| `OE_PORTA` | Porta do sistema (padrão **5055** — nunca use a porta do MecAuto/JJSoft) |
| `OE_NOME_OFICINA` | Nome que aparece nas telas e no PDF |
| `OE_RESPONSAVEL_COMPRAS` / `OE_TELEFONE_COMPRAS` | Rodapé do pedido (setor de compras) |
| `MECAUTO_MODO_DEMO` | `true` = dados fictícios (testar sem banco); `false` = banco real |
| `MECAUTO_DSN` | Ex.: `192.168.1.250:C:\CICOM\MECAUTO\DB\CICOM.CDB` |
| `MECAUTO_USUARIO` / `MECAUTO_SENHA` | Credenciais de leitura do Firebird (padrão SYSDBA/masterkey) |
| `MECAUTO_CHARSET` | `WIN1252` (senão acentos vêm quebrados) |
| `MECAUTO_CAMINHO_CDB_ORIGEM` / `_COPIA` | Opcional: fallback que copia o `.CDB` localmente se a conexão direta falhar (evita lock com o MecAuto em uso) |

## Como rodar

```bat
python app.py
```

- **No PC:** abra `http://localhost:5055`.
- **No celular** (mesma rede Wi-Fi): descubra o IP do computador
  (`ipconfig` → "Endereço IPv4") e abra `http://IP-DO-COMPUTADOR:5055`.
  Se não abrir, libere a porta 5055 no Firewall do Windows.

Veja também `iniciar.bat` (duplo clique, sem digitar comando) e
`gerar_executavel.bat` (gera um `.exe` standalone) na raiz desta pasta.

## Fichas de peças (`ficha_templates/`)

Cada tipo de ficha é um arquivo `.json` nessa pasta — o sistema descobre
os tipos automaticamente, não precisa mexer em código para adicionar um
novo modelo (outro motor, câmbio, diferencial etc.).

Já incluído: `motor_fh_d13_parcial.json` (41 peças, extraído da planilha
anexada). Para criar um novo, copie o formato:

```json
{
  "tipo": "cambio_ishift",
  "nome": "Câmbio I-Shift — Recondicionamento",
  "titulo_impressao": "RELAÇÃO DE PEÇAS P/ RECONDICIONAMENTO DE CÂMBIO",
  "ref_largura": 1000, "ref_altura": 1414,
  "itens": [
    {"peca": "NOME DA PEÇA", "codigo_interno": "12345678", "quantidade_padrao": 1,
     "grupo": "", "x": null, "y": null, "w": null, "h": null}
  ]
}
```

Deixe `x/y/w/h` como `null` — o sistema calcula a posição do quadrado
automaticamente. Reinicie o servidor para o novo tipo aparecer.

## Banco MecAuto/CICOM — o que este sistema consulta

Baseado no `MECAUTO_BANCO_REFERENCIA.md` fornecido (schema confirmado em
produção): `TAB_CAD_OS` (OS/orçamento — cliente, placa, veículo, motor,
situação), com `TAB_CTR_CLI_VEC` para chassi. Apenas leitura, sempre com
`CM_NUM_OS` (número visível) — nunca `CM_COD_OS` (chave interna) é exposto
na tela.

### Garantias de não interferência

- Somente `SELECT`: qualquer outro SQL é bloqueado no código antes de chegar ao banco.
- Transação **read-only** (`ISOLATION_LEVEL_READ_COMMITED_RO`).
- Conexão aberta e fechada a cada consulta, com timeout.
- **Fallback de cópia local**: se a conexão direta falhar (banco em uso),
  o sistema copia o `.CDB` e lê a cópia — evita disputar lock com o
  MecAuto em uso na oficina (configurável, opcional).
- Porta própria; nenhum processo do MecAuto/JJSoft é tocado.
- Nada é instalado como serviço do Windows.

## Gerando o executável (.exe)

Este projeto foi desenvolvido em um ambiente Linux, então não é possível
gerar o `.exe` do Windows diretamente aqui. Rode **no computador Windows
da oficina**, uma única vez:

```bat
gerar_executavel.bat
```

Isso usa o PyInstaller para empacotar `app.py` + templates + static +
fichas num único `OrcamentoExpress.exe` em `dist/`. Depois é só copiar a
pasta `dist/` (com o `.env` ao lado) para onde quiser rodar.

## Testes

```bat
python -m pytest tests -v
```

37 testes cobrindo: subida do app, rotas, bloqueio de SQL não-SELECT, modo
demo, geração da ficha para impressão, processamento de imagem (com foto
inválida), upload, geração de PDF final e histórico SQLite. Veja também
`CHECKLIST_TESTE_MANUAL.md`.

## Backup

Copie a pasta `orcamento_express/` inteira (ou, no mínimo: `data/`,
`pdfs/`, `ficha_templates/` e `.env`). Nada do sistema fica dentro do MecAuto.

## Estrutura do projeto

```
orcamento_express/
  app.py                     # rotas Flask
  config.py                  # configurações (.env)
  database/
    mecauto_reader.py        # leitura SOMENTE SELECT do Firebird/MecAuto
    local_history.py         # SQLite local (histórico + rascunhos)
  services/
    image_processor.py       # OpenCV: alinhar folha + detectar marcações
    template_mapper.py       # descoberta de fichas + layout automático
    ficha_pdf.py              # gera a ficha para impressão (com quadrados)
    pdf_generator.py          # PDF final do pedido + mensagem WhatsApp
  ficha_templates/            # um .json por tipo de ficha
  templates/ static/          # telas mobile-first
  tests/                      # testes automatizados
iniciar.bat                   # duplo clique para rodar (Windows)
gerar_executavel.bat          # gera o .exe standalone (rodar no Windows)
```
