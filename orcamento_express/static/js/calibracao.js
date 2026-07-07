// Calibração: desenhar retângulos sobre os quadrados de marcação da ficha.
// Fluxo: envia imagem da ficha em branco -> servidor alinha e devolve ->
// usuário arrasta um retângulo por peça -> salva coordenadas no JSON da ficha.
const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
let imagem = new Image();
let caixas = [];         // {indice, x, y, w, h} no espaço de referência
let indiceAtual = 0;
let arrastando = null;   // {x0, y0, x1, y1} em pixels do canvas

document.getElementById('arquivo').addEventListener('change', async (e) => {
  const arquivo = e.target.files[0];
  if (!arquivo) return;
  document.getElementById('status-imagem').textContent = 'Enviando e alinhando a imagem...';
  const dados = new FormData();
  dados.append('foto', arquivo);
  const resposta = await fetch(`/api/calibracao/${TIPO}/imagem`, {method: 'POST', body: dados});
  const r = await resposta.json();
  if (!r.ok) return avisar(r.erro || 'Erro ao carregar a imagem.', 'erro');
  imagem.onload = () => {
    canvas.width = imagem.width;
    canvas.height = imagem.height;
    document.getElementById('area-calibracao').classList.remove('oculto');
    document.getElementById('status-imagem').textContent =
      'Imagem alinhada. Desenhe o quadrado de cada peça.';
    atualizar();
  };
  imagem.src = r.imagem + '?t=' + Date.now();
});

function atualizar() {
  ctx.drawImage(imagem, 0, 0);
  const ex = canvas.width / REF_LARGURA, ey = canvas.height / REF_ALTURA;
  ctx.lineWidth = 3;
  for (const c of caixas) {
    ctx.strokeStyle = '#2E7D32';
    ctx.strokeRect(c.x * ex, c.y * ey, c.w * ex, c.h * ey);
  }
  if (arrastando) {
    ctx.strokeStyle = '#1565C0';
    ctx.strokeRect(arrastando.x0, arrastando.y0,
                   arrastando.x1 - arrastando.x0, arrastando.y1 - arrastando.y0);
  }
  const item = ITENS[indiceAtual];
  document.getElementById('peca-atual').textContent =
    item ? item.peca : 'Concluído! Toque em Salvar calibração.';
  document.getElementById('progresso').textContent = Math.min(indiceAtual, ITENS.length);
}

function posicao(e) {
  const r = canvas.getBoundingClientRect();
  const t = e.touches ? e.touches[0] : e;
  return {x: (t.clientX - r.left) * canvas.width / r.width,
          y: (t.clientY - r.top) * canvas.height / r.height};
}

function iniciar(e) {
  if (indiceAtual >= ITENS.length) return;
  const p = posicao(e);
  arrastando = {x0: p.x, y0: p.y, x1: p.x, y1: p.y};
  e.preventDefault();
}
function mover(e) {
  if (!arrastando) return;
  const p = posicao(e);
  arrastando.x1 = p.x; arrastando.y1 = p.y;
  atualizar();
  e.preventDefault();
}
function terminar(e) {
  if (!arrastando) return;
  const ex = canvas.width / REF_LARGURA, ey = canvas.height / REF_ALTURA;
  const x = Math.min(arrastando.x0, arrastando.x1) / ex;
  const y = Math.min(arrastando.y0, arrastando.y1) / ey;
  const w = Math.abs(arrastando.x1 - arrastando.x0) / ex;
  const h = Math.abs(arrastando.y1 - arrastando.y0) / ey;
  arrastando = null;
  if (w > 4 && h > 4) {  // ignora toques acidentais
    caixas = caixas.filter(c => c.indice !== indiceAtual);
    caixas.push({indice: indiceAtual, x: Math.round(x), y: Math.round(y),
                 w: Math.round(w), h: Math.round(h)});
    indiceAtual++;
  }
  atualizar();
  if (e) e.preventDefault();
}

canvas.addEventListener('mousedown', iniciar);
canvas.addEventListener('mousemove', mover);
canvas.addEventListener('mouseup', terminar);
canvas.addEventListener('touchstart', iniciar, {passive: false});
canvas.addEventListener('touchmove', mover, {passive: false});
canvas.addEventListener('touchend', terminar, {passive: false});

document.getElementById('btn-pular-item').onclick = () => {
  if (indiceAtual < ITENS.length) { indiceAtual++; atualizar(); }
};
document.getElementById('btn-voltar-item').onclick = () => {
  if (indiceAtual > 0) {
    indiceAtual--;
    caixas = caixas.filter(c => c.indice !== indiceAtual);
    atualizar();
  }
};

document.getElementById('btn-salvar').onclick = async () => {
  if (!caixas.length) return avisar('Desenhe ao menos um quadrado antes de salvar.', 'atencao');
  const r = await postJSON(`/api/calibracao/${TIPO}`,
    {caixas, ref_largura: REF_LARGURA, ref_altura: REF_ALTURA});
  if (r.ok) {
    avisar(`Calibração salva! ${caixas.length} quadrado(s) mapeado(s).`, 'ok');
    setTimeout(() => location.href = '/configuracoes', 1200);
  } else avisar(r.erro || 'Erro ao salvar calibração.', 'erro');
};
