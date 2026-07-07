// Captura/seleção da foto da ficha e envio para processamento.
let fotoSelecionada = null;

function aoEscolherArquivo(evento) {
  const arquivo = evento.target.files[0];
  if (!arquivo) return;
  fotoSelecionada = arquivo;
  const previa = document.getElementById('previa');
  previa.src = URL.createObjectURL(arquivo);
  previa.classList.remove('oculto');
  document.getElementById('btn-processar').classList.remove('oculto');
  document.getElementById('dica').textContent =
    'Confira se a folha aparece inteira e nítida. Depois toque em Processar foto.';
}

document.getElementById('arquivo-camera').addEventListener('change', aoEscolherArquivo);
document.getElementById('arquivo-galeria').addEventListener('change', aoEscolherArquivo);

document.getElementById('btn-processar').onclick = async () => {
  if (!fotoSelecionada) return avisar('Escolha ou tire uma foto primeiro.', 'atencao');
  avisar('Processando a foto... aguarde.', 'info');
  const dados = new FormData();
  dados.append('foto', fotoSelecionada);
  try {
    const resposta = await fetch('/api/processar_foto', {method: 'POST', body: dados});
    const r = await resposta.json();
    if (!r.ok) return avisar(r.erro || 'Erro ao processar a foto.', 'erro');
    if (r.foto_borrada) avisar('Foto borrada — abrindo em modo de conferência manual.', 'atencao');
    else if (!r.folha_detectada)
      avisar('Não consegui detectar as bordas da folha; confira os itens com atenção.', 'atencao');
    location.href = r.proxima;
  } catch (e) {
    avisar('Falha de comunicação com o servidor. Tente novamente.', 'erro');
  }
};

document.getElementById('btn-pular').onclick = async () => {
  const r = await postJSON('/api/pular_foto', {});
  if (r.ok) location.href = r.proxima; else avisar(r.erro, 'erro');
};
