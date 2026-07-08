# Checklist de Teste Manual — Orçamento Express Oficina (BF Trucks)

Marque cada item ao validar a instalação na oficina.

## Preparação
- [ ] 1. Iniciar o sistema: `python app.py` (ou `iniciar.bat`) — mostra a porta 5055 sem erro.
- [ ] 2. Abrir no navegador do PC: `http://localhost:5055` — tela inicial aparece.
- [ ] 3. Abrir no celular (mesma rede Wi-Fi): `http://IP-DO-PC:5055`.
      Se não abrir: conferir IP (`ipconfig`) e liberar a porta 5055 no firewall.

## Fluxo principal
- [ ] 4. Tocar em "Gerar novo orçamento", digitar um número de OS e "Buscar no MecAuto".
      - Em modo demo: preenche com dados fictícios e avisa que é demo.
      - Com banco real (`MECAUTO_MODO_DEMO=false`): traz cliente/placa/veículo/motor corretos.
      - Número inexistente: mensagem "Não encontrei essa OS no banco."
- [ ] 5. Escolher o tipo de ficha (ex.: Motor FH D13 Parcial) e continuar.
- [ ] 6. Na tela de captura, tocar em "Imprimir ficha para o mecânico marcar" —
      confirma que abre um PDF com cabeçalho da OS, quadrados ao lado de cada
      peça e um marcador quadrado pequeno em cada um dos 4 cantos da folha.
- [ ] 7. Imprimir essa ficha de verdade, marcar algumas peças com X à caneta.
      Garanta que os 4 cantos (com o marcador) fiquem visíveis no papel —
      não deixe a impressora cortar a margem.
- [ ] 8. Tirar foto da ficha marcada pelo celular (folha inteira COM os 4
      cantos visíveis, boa luz, qualquer mesa/fundo) e ver a prévia.
- [ ] 9. Processar a foto — abre a conferência sem erro, com as peças marcadas
      já selecionadas (verde) e o restante desmarcado. Se aparecer o aviso
      "não encontrei os marcadores dos 4 cantos", tire a foto de novo
      garantindo que os cantos apareçam inteiros.
      Testar também com uma foto ruim de propósito (tremida/torta): o sistema
      deve avisar ("Conferir este item manualmente" ou "foto borrada"), não travar.
- [ ] 10. Conferir itens: marcar/desmarcar, mudar quantidade, editar nome,
      adicionar peça manual, escolher "Cliente traz", escrever observação.
- [ ] 11. Gerar PDF — abrir o arquivo, conferir dados, imprimir,
      testar "Copiar mensagem para WhatsApp" e colar no WhatsApp.
- [ ] 12. Abrir o Histórico — o PDF gerado aparece com data, OS, cliente e placa.

## Calibração manual (opcional, só se usar ficha externa)
- [ ] 13. Configurações → Calibrar manualmente → enviar ficha em branco →
      desenhar os quadrados → salvar.

## Não interferência com o MecAuto/JJSoft (obrigatório)
- [ ] 14. Com o Orçamento Express rodando, usar o MecAuto/JJSOFT normalmente
      (abrir OS, salvar, imprimir) — tudo deve continuar funcionando.
- [ ] 15. Fazer várias buscas seguidas no Orçamento Express enquanto alguém
      usa o MecAuto — sem travamento ou lentidão anormal.
- [ ] 16. Conferir `logs/app.log`: consultas registradas, sem senha exposta.
