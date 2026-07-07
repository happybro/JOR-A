// Tela de conferência: revisar itens detectados, ajustar e gerar o PDF.
const lista = document.getElementById('lista-itens');
let itens = ITENS.map(i => ({...i, origem: i.origem || 'estoque'}));

function render() {
  lista.innerHTML = '';
  let grupoAtual = null;
  itens.forEach((item, i) => {
    if (item.grupo !== grupoAtual) {
      grupoAtual = item.grupo;
      if (grupoAtual) {
        const h = document.createElement('div');
        h.className = 'grupo-titulo';
        h.textContent = grupoAtual;
        lista.appendChild(h);
      }
    }
    const linha = document.createElement('div');
    linha.className = 'item' + (item.marcado ? ' item-marcado' : '') +
      (item.status === 'conferir' ? ' item-conferir' : '');
    linha.innerHTML = `
      <label class="item-check">
        <input type="checkbox" ${item.marcado ? 'checked' : ''} data-i="${i}" data-acao="marcar">
      </label>
      <div class="item-nome">
        <input class="campo campo-fino" value="${item.peca.replace(/"/g, '&quot;')}"
               data-i="${i}" data-acao="nome">
        ${item.codigo_interno ? `<span class="etiqueta">cód. ${item.codigo_interno}</span>` : ''}
        ${item.status === 'conferir' ? '<span class="etiqueta atencao">Conferir este item manualmente</span>' : ''}
        ${item.confianca !== null && item.confianca !== undefined
          ? `<span class="etiqueta">preenchimento ${(item.confianca * 100).toFixed(0)}%</span>` : ''}
      </div>
      <input type="number" class="campo campo-qtd" min="1" value="${item.quantidade || 1}"
             data-i="${i}" data-acao="qtd" ${item.marcado ? '' : 'disabled'}>
      <select class="campo campo-origem" data-i="${i}" data-acao="origem" ${item.marcado ? '' : 'disabled'}>
        <option value="estoque" ${item.origem !== 'cliente' ? 'selected' : ''}>Estoque</option>
        <option value="cliente" ${item.origem === 'cliente' ? 'selected' : ''}>Cliente traz</option>
      </select>`;
    lista.appendChild(linha);
  });
}

lista.addEventListener('change', (e) => {
  const i = +e.target.dataset.i;
  switch (e.target.dataset.acao) {
    case 'marcar': itens[i].marcado = e.target.checked; itens[i].status = 'ok'; render(); break;
    case 'qtd': itens[i].quantidade = Math.max(1, +e.target.value || 1); break;
    case 'origem': itens[i].origem = e.target.value; break;
    case 'nome': itens[i].peca = e.target.value; break;
  }
});

document.getElementById('btn-add').onclick = () => {
  const nome = prompt('Nome da peça:');
  if (!nome || !nome.trim()) return;
  itens.push({peca: nome.trim(), grupo: 'Adicionadas manualmente', quantidade: 1,
              marcado: true, confianca: null, status: 'manual', origem: 'estoque'});
  render();
  window.scrollTo(0, document.body.scrollHeight);
};

document.getElementById('btn-gerar').onclick = async () => {
  const pecas = itens.filter(i => i.marcado).map(i => ({
    peca: i.codigo_interno ? `${i.peca} (${i.codigo_interno})` : i.peca,
    quantidade: i.quantidade || 1, grupo: i.grupo || '', origem: i.origem}));
  if (!pecas.length) return avisar('Selecione ao menos uma peça antes de gerar o PDF.', 'atencao');
  avisar('Gerando PDF...', 'info');
  const r = await postJSON('/api/gerar_pdf', {
    pecas, observacoes: document.getElementById('observacoes').value});
  if (r.ok) location.href = r.proxima; else avisar(r.erro, 'erro');
};

render();
