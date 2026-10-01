// Protótipo isolado — nada aqui chama o backend. Respostas, permissões e idempotência são simuladas.
(function () {
  'use strict';
  const D = window.PROTO_DATA;
  const $ = (s, el) => (el || document).querySelector(s);
  const mqWide = window.matchMedia('(min-width: 1024px)');

  // ---------- armazenamento de conveniência (pode falhar) ----------
  const store = {
    get(k, d) { try { const v = sessionStorage.getItem('proto-ux2-' + k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
    set(k, v) { try { sessionStorage.setItem('proto-ux2-' + k, JSON.stringify(v)); } catch (e) { /* sem armazenamento */ } },
  };

  // ---------- estado ----------
  let db, passagem, minhaPassagem, forms, colForms, loaded;
  const ui = Object.assign({ origem: 'todos', estado: 'todos', residente: '', visao: 'residente', scroll: {} }, store.get('ui', {}));
  if (!ui.scroll) ui.scroll = {};
  const saveUi = () => store.set('ui', ui);
  function reset() {
    db = { itens: D.itens.map((i) => Object.assign({}, i)), registros: structuredClone(D.registros) };
    passagem = structuredClone(D.passagemRecebida);
    minhaPassagem = { nota: '', entregueEm: null, status: 'idle' };
    forms = {};
    colForms = {};
    loaded = false;
  }
  reset();

  // Navegação/Sheet
  let baseRoute = 'plantao';        // última tela principal (fica por baixo do Sheet no celular)
  let renderedKey = null, renderedBase = null;
  let sheetTipo = null, sheetCtx = null; // 'rota' | 'aux'
  let aux = null;                   // 'filtros' | 'notificacoes'
  let origemInterna = false;        // o Sheet foi aberto a partir de um toque dentro do app?
  let opener = null;                // seletor do elemento que abriu o Sheet (para devolver o foco)
  let aposRender = null;

  // ---------- utilidades ----------
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const hhmm = (d) => d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  const agora = () => D.relogio(); // relógio simulado (data.js)
  const agoraHHMM = () => hhmm(agora());
  function fromHHMM(v) {
    if (!/^\d{2}:\d{2}$/.test(v || '')) return null;
    const d = agora(); const [h, m] = v.split(':').map(Number); d.setHours(h, m, 0, 0); return d;
  }
  const noFuturo = (d) => d && d.getTime() <= agora().getTime() + 60000;
  const res = (id) => D.residentes.find((r) => r.id === id);
  const pessoa = (id) => D.equipe.find((p) => p.id === id);
  const item = (id) => db.itens.find((i) => i.id === id);
  const iniciais = (n) => n.split(' ').filter((p) => p.length > 2).slice(0, 2).map((p) => p[0]).join('').toUpperCase();
  const primeiroNome = (n) => n.split(' ')[0];
  const uid = () => Math.random().toString(36).slice(2) + Date.now().toString(36);
  const slug = (s) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-');
  const grupoKey = (i) => slug(i.atividade) + '-' + hhmm(i.prevista).replace(':', '');
  const plural = (n, s, p) => `${n} ${n === 1 ? s : p}`;

  const RESULTADOS = {
    executada: { label: 'Realizado', curto: 'Realizado', cls: 'b-ok', icon: 'check' },
    recusada: { label: 'Recusado pelo residente', curto: 'Recusou', cls: 'b-recusa', icon: 'x' },
    omitida: { label: 'Não realizado', curto: 'Não realizado', cls: 'b-nao', icon: 'ban' },
  };
  const OPT_LABEL = { executada: 'Realizado', recusada: 'Recusado', omitida: 'Não realizado' };
  const MOTIVOS_NAO = [
    ['ausente', 'Residente fora do quarto/ausente'],
    ['dormindo', 'Residente dormindo'],
    ['contraindicacao', 'Contraindicação observada'],
    ['material', 'Falta de material'],
    ['outro', 'Outro motivo'],
  ];

  function status(i) {
    const r = db.registros[i.id];
    if (r) return { tipo: 'registrado', reg: r };
    return { tipo: i.prevista.getTime() < agora().getTime() ? 'atrasado' : 'pendente' };
  }
  function estadoTexto(i) {
    const s = status(i);
    if (s.tipo === 'registrado') return `${RESULTADOS[s.reg.resultado].curto} às ${hhmm(s.reg.ocorridoEm)}`;
    return s.tipo === 'atrasado' ? 'Atrasado' : 'Pendente';
  }
  function badge(i) {
    const s = status(i);
    if (s.tipo === 'registrado') {
      const R = RESULTADOS[s.reg.resultado];
      return `<span class="badge ${R.cls}">${icon(R.icon)}${R.curto} · ${hhmm(s.reg.ocorridoEm)}</span>`;
    }
    if (s.tipo === 'atrasado') return `<span class="badge b-atrasado">${icon('alert')}Atrasado</span>`;
    return `<span class="badge b-pendente">${icon('clock')}Pendente</span>`;
  }
  const insp = (tipo, txt) => `<span class="insp ${tipo}">${tipo === 'existe' ? 'existe hoje' : 'proposta'} · ${esc(txt)}</span>`;

  // ---------- ícones (traços do Lucide) ----------
  const ICONS = {
    clipboard: '<rect width="8" height="4" x="8" y="2" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="M12 11h4"/><path d="M12 16h4"/><path d="M8 11h.01"/><path d="M8 16h.01"/>',
    swap: '<path d="m16 3 4 4-4 4"/><path d="M20 7H4"/><path d="m8 21-4-4 4-4"/><path d="M4 17h16"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    ban: '<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
    clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    chevron: '<path d="m9 18 6-6-6-6"/>',
    lock: '<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    loader: '<path d="M21 12a9 9 0 1 1-6.219-8.56"/>',
    pill: '<path d="m10.5 20.5 10-10a4.95 4.95 0 1 0-7-7l-10 10a4.95 4.95 0 1 0 7 7Z"/><path d="m8.5 8.5 7 7"/>',
    wifiOff: '<path d="M12 20h.01"/><path d="M8.5 16.43a5 5 0 0 1 7 0"/><path d="M2 8.82a15 15 0 0 1 4.17-2.65"/><path d="M10.66 5c4.01-.36 8.14.9 11.34 3.76"/><path d="M16.85 11.25a10 10 0 0 1 2.22 1.68"/><path d="M5 13a10 10 0 0 1 5.24-2.76"/><path d="m2 2 20 20"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    inbox: '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    away: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="22" x2="16" y1="11" y2="11"/>',
    bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    sliders: '<line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/><line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/><line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/><line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="16" x2="16" y1="18" y2="22"/>',
  };
  function icon(n, cls) { return `<svg class="i${cls ? ' ' + cls : ''}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n] || ''}</svg>`; }

  // ---------- API simulada ----------
  function consumirFalha() { const sel = $('#sim-falha'); const v = sel.value; sel.value = 'none'; return v; }
  const api = {
    // Espelha POST /api/execucoes-cuidado: um registro vigente por ocorrência (409 na repetição).
    // A chave de idempotência é proposta; o backend atual responde 409 e a tela mostra o registro existente.
    salvarExecucao(itemId, payload, idem) {
      const modo = consumirFalha();
      return new Promise((resolve, reject) => {
        setTimeout(() => {
          if (modo === 'antes') return reject(new Error('rede'));
          const existente = db.registros[itemId];
          if (existente) return resolve({ jaExistia: true, reg: existente });
          const reg = Object.assign({}, payload, { registradoEm: agora(), executor: 'f1', idem });
          db.registros[itemId] = reg;
          if (modo === 'resposta') return reject(new Error('rede'));
          resolve({ jaExistia: false, reg });
        }, 800);
      });
    },
  };

  // ---------- rotas ----------
  function rota() {
    const h = location.hash.replace(/^#\/?/, '');
    const [nome, arg] = h.split('/');
    if (nome === 'registro' && arg) return { nome, id: arg };
    if (nome === 'coletivo' && arg) return { nome, key: arg };
    if (nome === 'passagem' || nome === 'residentes') return { nome };
    return { nome: 'plantao' };
  }
  const ehDetalhe = (r) => r.nome === 'registro' || r.nome === 'coletivo';
  const temPassagem = () => $('#sim-perfil').value === 'com';

  // ---------- filtros ----------
  function filtrados() {
    return db.itens.filter((i) => {
      if (ui.origem !== 'todos' && i.origem !== ui.origem) return false;
      if (ui.residente && i.residenteId !== ui.residente) return false;
      if (ui.estado !== 'todos' && status(i).tipo !== ui.estado) return false;
      return true;
    }).sort((a, b) => a.prevista - b.prevista);
  }
  function ordemNavegacao() {
    const lista = filtrados();
    return D.residentes.flatMap((r) => lista.filter((i) => i.residenteId === r.id));
  }
  // "Salvar e próximo": só cuidados elegíveis (sem registro), dentro dos filtros ativos. Medicação nunca entra.
  function proximo(id) {
    const ordem = ordemNavegacao().filter((i) => i.origem === 'cuidado');
    const idx = ordem.findIndex((i) => i.id === id);
    const seq = idx >= 0 ? ordem.slice(idx + 1).concat(ordem.slice(0, idx)) : ordem;
    return seq.find((i) => i.id !== id && !db.registros[i.id]) || null;
  }
  const filtrosExtras = () => (ui.residente ? 1 : 0) + (ui.estado === 'pendente' || ui.estado === 'registrado' ? 1 : 0);

  // ---------- cromo: cabeçalho, navegação, sino ----------
  function notificacoes() {
    const atrasados = db.itens.filter((i) => status(i).tipo === 'atrasado').sort((a, b) => a.prevista - b.prevista);
    const pass = temPassagem() && passagem.situacao === 'entregue';
    return { atrasados, pass, total: atrasados.length + (pass ? 1 : 0) };
  }
  function renderCromo(r, base) {
    const titulos = { plantao: 'Meu Plantão', residentes: 'Residentes', passagem: 'Passagem de plantão' };
    $('#page-title').textContent = titulos[base] || 'Meu Plantão';
    $('#page-sub').textContent = `Manhã 07–13 · Ala B · ${agoraHHMM()}`;
    $('#page-sub').title = 'Relógio simulado do protótipo';
    document.title = (titulos[base] || 'Meu Plantão') + ' · Protótipo FacILPI';
    const n = notificacoes().total;
    const sino = $('#btn-sino');
    sino.innerHTML = icon('bell') + (n ? `<span class="bell-count" aria-hidden="true">${n}</span>` : '');
    sino.setAttribute('aria-label', n ? `Notificações: ${n} pedem ação` : 'Notificações: nada pendente');
    const ativo = ehDetalhe(r) ? (mqWide.matches ? 'plantao' : base) : r.nome;
    const itens = [
      { k: 'plantao', href: '#/plantao', label: 'Plantão', icon: 'clipboard' },
      { k: 'residentes', href: '#/residentes', label: 'Residentes', icon: 'users' },
    ];
    // P0-4 (proposta): o menu segue a permissão de passagem, não plantao:ler.
    if (temPassagem()) itens.push({ k: 'passagem', href: '#/passagem', label: 'Passagem', icon: 'swap' });
    const html = itens.map((n2) => `<a href="${n2.href}"${ativo === n2.k ? ' aria-current="page"' : ''}><span class="pill">${icon(n2.icon)}</span><span>${n2.label}</span></a>`).join('');
    $('#nav-side').innerHTML = html;
    $('#nav-bottom').innerHTML = html;
  }

  // ---------- Lista do plantão ----------
  function chipsHTML() {
    const base = db.itens.filter((i) => !ui.residente || i.residenteId === ui.residente);
    const n = {
      todos: base.length,
      atrasados: base.filter((i) => status(i).tipo === 'atrasado').length,
      cuidado: base.filter((i) => i.origem === 'cuidado').length,
      medicacao: base.filter((i) => i.origem === 'medicacao').length,
    };
    const chip = (k, l, on) => `<button type="button" class="chip" id="chip-${k}" data-chip="${k}" aria-pressed="${on}"><span>${l} <b>${n[k]}</b></span></button>`;
    return chip('todos', 'Todos', ui.origem === 'todos' && ui.estado === 'todos')
      + chip('atrasados', 'Atrasados', ui.estado === 'atrasado')
      + chip('cuidado', 'Cuidados', ui.origem === 'cuidado')
      + chip('medicacao', 'Medicação', ui.origem === 'medicacao');
  }
  function ativosHTML() {
    const out = [];
    if (ui.residente) out.push(`<button type="button" class="chip removivel" data-remover="residente" aria-label="Remover filtro de residente ${esc(res(ui.residente).nome)}"><span>${esc(res(ui.residente).nome.split(' ').slice(0, 2).join(' '))} ${icon('x')}</span></button>`);
    if (ui.estado === 'pendente' || ui.estado === 'registrado') out.push(`<button type="button" class="chip removivel" data-remover="estado" aria-label="Remover filtro de estado"><span>${ui.estado === 'pendente' ? 'Pendentes' : 'Registrados'} ${icon('x')}</span></button>`);
    return out.length ? `<div class="ativos">${out.join('')}</div>` : '';
  }
  function listaHTML() {
    const nExtra = filtrosExtras();
    let html = `<div class="toolbar">
      <div class="chips-wrap" id="chips-wrap"><div class="chips" id="chips" role="group" aria-label="Filtros rápidos (deslize para ver mais)">${chipsHTML()}</div><span class="chips-seta" aria-hidden="true">${icon('chevron')}</span></div>
      <div class="toolbar-row">
        <div class="seg" role="group" aria-label="Organizar lista">
          <button type="button" id="vis-residente" data-visao="residente" aria-pressed="${ui.visao === 'residente'}">Por residente</button>
          <button type="button" id="vis-atividade" data-visao="atividade" aria-pressed="${ui.visao === 'atividade'}">Por atividade</button>
        </div>
        <button type="button" class="btn-filtros" id="btn-filtros" data-aux="filtros">${icon('sliders')}Filtros${nExtra ? ` <span class="count">${nExtra}</span>` : ''}</button>
      </div>
      ${ativosHTML()}
    </div>
    ${insp('existe', 'GET /api/meu-plantao/ e /api/plantao/')}${insp('proposta', 'filtros, visão e rolagem preservados (sessionStorage)')}`;

    if (!loaded) {
      return html + [1, 2, 3].map(() => `<div class="rcard" aria-hidden="true" style="padding:10px"><div class="sk" style="height:32px;width:60%"></div><div class="sk" style="height:14px;margin-top:10px"></div><div class="sk" style="height:14px;margin-top:8px;width:80%"></div></div>`).join('') + '<p class="sr-only">Carregando o plantão…</p>';
    }
    const lista = filtrados();
    if (!lista.length) {
      return html + `<div class="card state">${icon('inbox')}<strong>Nenhum item com estes filtros agora.</strong><span class="hint">Isso não é um erro: não há itens que correspondam aos filtros.</span><button type="button" class="btn btn-outline" data-limpar-filtros>Limpar filtros</button></div>`;
    }
    if (ui.visao === 'residente') {
      html += D.residentes.map((r) => {
        const its = lista.filter((i) => i.residenteId === r.id);
        if (!its.length) return '';
        return `<section class="rcard" aria-label="${esc(r.nome)}">
          <div class="rcard-head"><span class="avatar sm" aria-hidden="true">${iniciais(r.nome)}</span>
            <div class="row-main"><div class="rname">${esc(r.nome)}</div><div class="rmeta">Quarto ${r.quarto} · Leito ${r.leito} · ${r.idade} anos</div></div>
            ${r.ausente ? `<span class="badge b-info">${icon('away')}Ausente</span>` : ''}</div>
          ${its.map((i) => rowHTML(i, false)).join('')}
        </section>`;
      }).join('');
    } else {
      const grupos = {};
      lista.filter((i) => i.origem === 'cuidado').forEach((i) => { (grupos[grupoKey(i)] = grupos[grupoKey(i)] || []).push(i); });
      html += Object.entries(grupos).map(([k, its]) => grupoHTML(k, its)).join('');
      const meds = lista.filter((i) => i.origem === 'medicacao');
      if (meds.length) html += `<h2 class="section-title">Medicação · registro em módulo específico</h2><div class="rcard">${meds.map((i) => rowHTML(i, true)).join('')}</div>`;
    }
    return html;
  }

  function rowHTML(i, comNome) {
    const r = res(i.residenteId);
    const med = i.origem === 'medicacao';
    const sub = [];
    if (comNome) sub.push(`${r.nome} · Q${r.quarto}·${r.leito}`);
    if (i.herdada) sub.push(`Herdada da ${i.herdada}`);
    const rotulo = `${i.atividade}, ${r.nome}, previsto ${hhmm(i.prevista)}, ${estadoTexto(i)}${med ? ', registro em módulo específico' : ''}`;
    const abre = med
      ? `<div class="row row-static" id="row-${i.id}" role="group" aria-label="${esc(rotulo)}">`
      : `<button type="button" class="row" id="row-${i.id}" data-open="${i.id}" aria-label="${esc(rotulo)}">`;
    return `${abre}
      <span class="row-time">${hhmm(i.prevista)}</span>
      <span class="row-main"><span class="row-title">${med ? icon('pill') : ''}${esc(i.atividade)}</span>
        ${sub.length ? `<span class="row-sub">${esc(sub.join(' · '))}</span>` : ''}<span>${badge(i)}</span></span>
      ${med ? '<span class="row-note">Registro em módulo específico</span></div>' : icon('chevron', 'chev') + '</button>'}`;
  }

  function grupoHTML(k, its) {
    const feitos = its.filter((i) => db.registros[i.id]).length;
    const atras = its.filter((i) => status(i).tipo === 'atrasado').length;
    const pend = its.length - feitos;
    const acao = its.length > 1
      ? `<button type="button" class="btn ${pend ? 'btn-primary' : 'btn-ghost'} btn-sm" data-grupo="${k}">${pend ? icon('users') + 'Em grupo' : 'Ver grupo'}</button>`
      : `<button type="button" class="btn ${pend ? 'btn-primary' : 'btn-ghost'} btn-sm" data-open="${its[0].id}">${pend ? 'Registrar' : 'Ver'}</button>`;
    return `<section class="gcard" id="grp-${k}" aria-label="${esc(its[0].atividade)} ${hhmm(its[0].prevista)}">
      <div class="g-main">
        <div class="row-title"><span class="row-time" style="width:auto">${hhmm(its[0].prevista)}</span> ${esc(its[0].atividade)}${its[0].herdada ? ' <span class="badge b-info">Herdada</span>' : ''}</div>
        <div class="row-sub">${feitos} de ${its.length} registrados${atras ? ` · <strong style="color:hsl(var(--alerta-forte))">${plural(atras, 'atrasado', 'atrasados')}</strong>` : ''}</div>
        <div class="progress" aria-hidden="true"><span style="width:${Math.round((feitos / its.length) * 100)}%"></span></div>
      </div>${acao}</section>`;
  }

  // ---------- Residentes (mesma fonte, visão por pessoa) ----------
  function residentesHTML() {
    return `<h2 class="section-title" style="margin-top:4px">Residentes do setor · ${D.residentes.length}</h2>
      ${insp('proposta', 'atalho: tocar filtra o Meu Plantão pelo residente (sem tela nova)')}
      ${D.residentes.map((r) => {
        const its = db.itens.filter((i) => i.residenteId === r.id);
        const atr = its.filter((i) => status(i).tipo === 'atrasado').length;
        const pend = its.filter((i) => status(i).tipo === 'pendente').length;
        const badges = [
          atr ? `<span class="badge b-atrasado">${icon('alert')}${plural(atr, 'atrasado', 'atrasados')}</span>` : '',
          pend ? `<span class="badge b-pendente">${icon('clock')}${plural(pend, 'pendente', 'pendentes')}</span>` : '',
          !atr && !pend ? `<span class="badge b-ok">${icon('check')}Em dia</span>` : '',
          r.ausente ? `<span class="badge b-info">${icon('away')}Ausente</span>` : '',
        ].join('');
        return `<button type="button" class="res-row" id="res-${r.id}" data-residente="${r.id}" aria-label="${esc(r.nome)}, quarto ${r.quarto} leito ${r.leito}: ${atr} atrasados, ${pend} pendentes. Ver cuidados">
          <span class="avatar" aria-hidden="true">${iniciais(r.nome)}</span>
          <span class="row-main"><span class="row-title">${esc(r.nome)}</span><span class="row-sub">Quarto ${r.quarto} · Leito ${r.leito} · ${r.idade} anos</span><span class="badges">${badges}</span></span>
          ${icon('chevron', 'chev')}</button>`;
      }).join('')}`;
  }

  // ---------- Registro individual ----------
  function formDe(id) {
    if (!forms[id]) forms[id] = { resultado: '', motivo: '', motivoCod: '', detalhe: '', hora: agoraHHMM(), ajudante: '', obs: '', idem: uid(), status: 'idle', erro: null, erros: {} };
    return forms[id];
  }
  function justificativa(f) {
    if (f.resultado === 'recusada') return f.motivo.trim();
    if (f.resultado === 'omitida') {
      const m = MOTIVOS_NAO.find((x) => x[0] === f.motivoCod);
      return m ? m[1] + (f.detalhe.trim() ? ': ' + f.detalhe.trim() : '') : '';
    }
    return null;
  }
  function payloadDe(id, f) {
    const p = { ocorrencia_id: id, resultado: f.resultado || '(escolha)', ocorrido_em: (fromHHMM(f.hora) || agora()).toISOString() };
    const j = justificativa(f); if (j) p.justificativa = j;
    if (f.obs.trim()) p.observacao = f.obs.trim();
    return p;
  }
  function cabecalho(r, titulo, sub) {
    return `<div class="sh-id"><span class="avatar" aria-hidden="true">${iniciais(r.nome)}</span>
      <div class="sh-txt"><h2 id="sheet-title" tabindex="-1">${esc(titulo)}</h2>
        <div class="sh-res"><strong>${esc(r.nome)}</strong></div>
        <div class="sh-loc">Quarto ${r.quarto} · Leito ${r.leito}</div>
        <div class="sh-sub">${sub}</div></div></div>`;
  }

  function registroParts(id) {
    const i = item(id);
    if (!i) return { head: `<div class="sh-txt"><h2 id="sheet-title" tabindex="-1">Item não encontrado</h2></div>`, body: `<p>Este item não está no plantão.</p>`, foot: `<button type="button" class="btn btn-outline" data-close>Fechar</button>` };
    const r = res(i.residenteId);
    const head = cabecalho(r, i.atividade, `Previsto ${hhmm(i.prevista)} ${badge(i)}${i.herdada ? ` <span class="badge b-info">Herdada da ${esc(i.herdada)}</span>` : ''}${r.ausente ? ` <span class="badge b-info">${icon('away')}Ausente</span>` : ''}`);
    if (i.origem === 'medicacao') {
      return { head, body: `<div class="alert alert-info">${icon('pill')}<div><strong>Medicação tem fluxo próprio.</strong><p>Doses são registradas pela administração de medicamentos, com quantidade obrigatória.</p></div></div>`, foot: `<button type="button" class="btn btn-outline" data-close>Fechar</button>` };
    }
    // Enquanto o envio não tiver confirmação, a tela não presume sucesso (mesmo que o servidor simulado tenha gravado).
    const pendenteConfirmacao = forms[id] && forms[id].status !== 'idle';
    const reg = db.registros[id];
    if (reg && !pendenteConfirmacao) {
      const R = RESULTADOS[reg.resultado];
      const ex = pessoa(reg.executor);
      const prox = proximo(id);
      return {
        head,
        body: `<div class="alert alert-ok">${icon('check')}<div><strong>Registrado: ${R.label}</strong>
          <p>Horário real: <strong>${hhmm(reg.ocorridoEm)}</strong> · Registro gravado às ${hhmm(reg.registradoEm)} por ${esc(ex ? ex.nome : '—')}${ex && ex.voce ? ' (você)' : ''}</p>
          ${reg.justificativa ? `<p>Motivo: ${esc(reg.justificativa)}</p>` : ''}${reg.ajudante ? `<p>Auxiliado por: ${esc(pessoa(reg.ajudante).nome)}</p>` : ''}${reg.observacao ? `<p>Observação: ${esc(reg.observacao)}</p>` : ''}</div></div>
          <p class="hint" style="margin:0">Correção: estorno com motivo, que mantém o registro original visível. ${insp('existe', 'POST /api/execucoes-cuidado/{id}/estornar')} ${insp('proposta', 'tela de estorno')}</p>`,
        foot: `<button type="button" class="btn btn-outline" data-close>Fechar</button>${prox ? `<button type="button" class="btn btn-primary" data-ir="${prox.id}">Próximo pendente</button>` : ''}`,
      };
    }
    const f = formDe(id);
    const s = f.status === 'saving';
    const dis = s ? 'disabled' : '';
    const opt = (v, cls) => `<label class="opt ${cls || ''}"><input type="radio" name="resultado" id="r-${v}" value="${v}" ${f.resultado === v ? 'checked' : ''} ${dis}><span>${icon(RESULTADOS[v].icon)}${OPT_LABEL[v]}</span></label>`;
    const ajudantes = D.equipe.filter((p) => p.emPlantao && !p.voce);
    const inv = (k, eid) => (f.erros[k] ? `aria-invalid="true" aria-describedby="${eid}"` : '');
    const body = `
      ${f.erro ? `<div class="alert alert-err" id="erro-envio" tabindex="-1" role="alert">${icon('wifiOff')}<div><strong>Não foi possível salvar.</strong><p>${esc(f.erro)} O que você preencheu continua aqui.</p></div></div>` : ''}
      <fieldset>
        <legend class="legend">Resultado obrigatório</legend>
        <div class="opts">${opt('executada')}${opt('recusada', 'recusa')}${opt('omitida', 'nao')}</div>
        ${f.erros.resultado ? `<div class="err-txt" id="e-res">${f.erros.resultado}</div>` : ''}
        ${insp('existe', 'executada | recusada | omitida; justificativa obrigatória fora de executada')}
      </fieldset>
      ${f.resultado === 'recusada' ? `<div class="field"><label for="f-motivo">Motivo da recusa (obrigatório)</label>
        <textarea class="input" id="f-motivo" data-campo="motivo" ${inv('motivo', 'e-motivo')} ${dis}>${esc(f.motivo)}</textarea>
        ${f.erros.motivo ? `<div class="err-txt" id="e-motivo">${f.erros.motivo}</div>` : ''}</div>` : ''}
      ${f.resultado === 'omitida' ? `<div class="row2"><div class="field"><label for="f-motivocod">Por que não foi realizado? (obrigatório)</label>
        <select class="input" id="f-motivocod" data-campo="motivoCod" ${inv('motivoCod', 'e-mcod')} ${dis}>
          <option value="">Selecione…</option>${MOTIVOS_NAO.map(([k, l]) => `<option value="${k}" ${f.motivoCod === k ? 'selected' : ''}>${l}</option>`).join('')}</select>
        ${f.erros.motivoCod ? `<div class="err-txt" id="e-mcod">${f.erros.motivoCod}</div>` : ''}</div>
        <div class="field"><label for="f-detalhe">Detalhe ${f.motivoCod === 'outro' ? '(obrigatório)' : '(opcional)'}</label>
        <input class="input" id="f-detalhe" data-campo="detalhe" value="${esc(f.detalhe)}" ${inv('detalhe', 'e-det')} ${dis}>
        ${f.erros.detalhe ? `<div class="err-txt" id="e-det">${f.erros.detalhe}</div>` : ''}</div></div>
        ${insp('existe', 'grava como omitida + justificativa (texto)')}` : ''}
      <div class="row2">
        <div class="field"><label for="f-hora">Horário real do cuidado</label>
          <div class="time-row"><input type="time" class="input" id="f-hora" data-campo="hora" value="${esc(f.hora)}" ${f.erros.hora ? 'aria-invalid="true" aria-describedby="e-hora"' : 'aria-describedby="h-hora"'} ${dis}>
          <button type="button" class="btn btn-outline btn-sm" id="btn-agora" data-agora ${dis}>Agora</button></div>
          ${f.erros.hora ? `<div class="err-txt" id="e-hora">${f.erros.hora}</div>` : `<span class="hint" id="h-hora">Informe quando o cuidado aconteceu.</span>`}
          ${insp('existe', 'ocorrido_em ≠ registrado_em; futuro = 422')}
        </div>
        <div class="field"><label for="f-ajudante">Profissional que auxiliou (opcional)</label>
          <select class="input" id="f-ajudante" data-campo="ajudante" ${dis}><option value="">Sem auxílio</option>
          ${ajudantes.map((p) => `<option value="${p.id}" ${f.ajudante === p.id ? 'selected' : ''}>${esc(p.nome)} · ${esc(p.funcao)}</option>`).join('')}</select>
          ${insp('proposta', 'campo novo; exige migration (ExecucaoCuidado não tem ajudante)')}
        </div>
      </div>
      <div class="field"><label for="f-obs">Observação (opcional)</label>
        <textarea class="input" id="f-obs" data-campo="obs" ${dis}>${esc(f.obs)}</textarea></div>
      ${insp('proposta', 'botões travados durante o envio; repetição reaproveita a chave ' + f.idem.slice(0, 6) + '…')}
      <pre class="insp existe" id="payload">POST /api/execucoes-cuidado\n${esc(JSON.stringify(payloadDe(id, f), null, 2))}</pre>`;
    const semRes = !f.resultado || s;
    const foot = `
      <button type="button" class="btn btn-outline" id="btn-salvar" data-salvar="lista" ${semRes ? 'disabled' : ''}>${s ? icon('loader', 'spin') + 'Salvando…' : (f.erro ? 'Tentar de novo' : 'Salvar')}</button>
      <button type="button" class="btn btn-primary" id="btn-salvar-prox" data-salvar="proximo" ${semRes ? 'disabled' : ''}>${s ? 'Aguarde…' : (f.erro ? 'Tentar e próximo' : 'Salvar e próximo')}</button>`;
    return { head, body, foot, tall: true };
  }

  function validar(f) {
    const e = {};
    if (!f.resultado) e.resultado = 'Escolha o resultado.';
    if (f.resultado === 'recusada' && !f.motivo.trim()) e.motivo = 'Descreva o motivo da recusa.';
    if (f.resultado === 'omitida' && !f.motivoCod) e.motivoCod = 'Escolha o motivo.';
    if (f.resultado === 'omitida' && f.motivoCod === 'outro' && !f.detalhe.trim()) e.detalhe = 'Descreva o motivo.';
    const d = fromHHMM(f.hora);
    if (!d) e.hora = 'Informe o horário.'; else if (!noFuturo(d)) e.hora = 'O horário não pode estar no futuro.';
    return e;
  }

  async function salvarIndividual(id, destino) {
    const f = formDe(id);
    if (f.status === 'saving') return; // evita duplo toque
    f.erros = validar(f);
    if (Object.keys(f.erros).length) {
      renderDetalhe();
      const alvo = $('#sheet-body [aria-invalid="true"], #detalhe [aria-invalid="true"]') || $('#r-executada');
      if (alvo) alvo.focus();
      anunciar('Revise os campos destacados.');
      return;
    }
    f.status = 'saving'; f.erro = null; renderDetalhe();
    anunciar('Salvando…');
    const payload = { resultado: f.resultado, ocorridoEm: fromHHMM(f.hora), justificativa: justificativa(f), observacao: f.obs.trim() || null, ajudante: f.ajudante || null };
    try {
      const out = await api.salvarExecucao(id, payload, f.idem);
      delete forms[id];
      const i = item(id);
      const msg = out.jaExistia
        ? `Já estava registrado às ${hhmm(out.reg.registradoEm)}. Nenhum registro duplicado foi criado.`
        : `${i.atividade} · ${primeiroNome(res(i.residenteId).nome)}: ${RESULTADOS[out.reg.resultado].curto} às ${hhmm(out.reg.ocorridoEm)}.`;
      atualizarItem(id);
      if (destino === 'proximo') {
        const prox = proximo(id);
        if (prox) { toast(msg); irPara(prox.id); return; }
        toast(msg + ' Não há mais cuidados pendentes neste filtro.');
      } else {
        toast(msg);
      }
      fecharDetalhe(() => atualizarItem(id));
    } catch (e) {
      f.status = 'error';
      f.erro = 'Sem conexão com o servidor. Nada foi confirmado.';
      renderDetalhe();
      const a = $('#erro-envio'); if (a) a.focus();
    }
  }

  // ---------- Registro coletivo ----------
  function grupoItens(key) {
    let its = db.itens.filter((i) => i.origem === 'cuidado' && grupoKey(i) === key);
    if (!its.length) its = db.itens.filter((i) => i.origem === 'cuidado' && i.grupo === key); // endereço estável (#/coletivo/cafe)
    return its
      .sort((a, b) => D.residentes.findIndex((r) => r.id === a.residenteId) - D.residentes.findIndex((r) => r.id === b.residenteId));
  }
  function colDe(key) { if (!colForms[key]) colForms[key] = { padrao: agoraHHMM(), linhas: {}, status: 'idle', resumo: null }; return colForms[key]; }
  function linhaDe(c, id) { if (!c.linhas[id]) c.linhas[id] = { resultado: '', motivo: '', motivoCod: '', detalhe: '', hora: '', ajudante: '', idem: uid(), erro: null, erros: {} }; return c.linhas[id]; }
  const semConfirmacao = (c, id) => c.linhas[id] && c.linhas[id].erro;

  function coletivoParts(key) {
    const its = grupoItens(key);
    if (!its.length) return { head: `<div class="sh-txt"><h2 id="sheet-title" tabindex="-1">Grupo não encontrado</h2></div>`, body: '', foot: `<button type="button" class="btn btn-outline" data-close>Fechar</button>` };
    const c = colDe(key);
    const s = c.status === 'saving';
    const dis = s ? 'disabled' : '';
    const pend = its.filter((i) => !db.registros[i.id] || semConfirmacao(c, i.id));
    const comRes = pend.filter((i) => linhaDe(c, i.id).resultado);
    const ajudantes = D.equipe.filter((p) => p.emPlantao && !p.voce);
    const head = `<div class="sh-id"><span class="avatar" aria-hidden="true">${icon('users')}</span><div class="sh-txt">
      <h2 id="sheet-title" tabindex="-1">${esc(its[0].atividade)} · em grupo</h2>
      <div class="sh-res">Previsto ${hhmm(its[0].prevista)} · ${its.length} residentes</div>
      <div class="sh-sub">${its.length - pend.length} já registrados · linhas vazias continuam sem registro</div></div></div>`;
    let body = `
      <div class="field"><label for="c-padrao">Horário real padrão</label>
        <input type="time" class="input" id="c-padrao" data-col-padrao value="${esc(c.padrao)}" aria-describedby="h-padrao" ${dis}>
        <span class="hint" id="h-padrao">Vale para as linhas sem horário próprio. Nada é marcado automaticamente.</span></div>
      ${insp('proposta', 'tela coletiva; cada linha envia 1 POST /api/execucoes-cuidado (existe)')}
      ${c.resumo ? `<div class="alert ${c.resumo.falhas ? 'alert-warn' : 'alert-ok'}" id="col-resumo" tabindex="-1" role="status">${icon(c.resumo.falhas ? 'alert' : 'check')}<div><strong>${plural(c.resumo.ok, 'salvo', 'salvos')}${c.resumo.falhas ? ` · ${c.resumo.falhas} não salvo${c.resumo.falhas === 1 ? '' : 's'}` : ''}${c.resumo.dup ? ` · ${c.resumo.dup} já estava${c.resumo.dup === 1 ? '' : 'm'} registrado${c.resumo.dup === 1 ? '' : 's'}` : ''}.</strong>
        <p>${c.resumo.falhas ? 'As linhas com falha mantêm o preenchimento; salve de novo pelo botão abaixo.' : ''} ${c.resumo.sem ? `${c.resumo.sem} continua${c.resumo.sem === 1 ? '' : 'm'} sem registro.` : ''}</p></div></div>` : ''}`;
    body += its.map((i) => {
      const r = res(i.residenteId);
      const reg = semConfirmacao(c, i.id) ? null : db.registros[i.id];
      const h = `<div class="crow-head"><span class="avatar sm" aria-hidden="true">${iniciais(r.nome)}</span>
        <div class="row-main"><div class="rname">${esc(r.nome)}</div><div class="rmeta">Quarto ${r.quarto} · Leito ${r.leito}</div></div>
        ${r.ausente ? `<span class="badge b-info">${icon('away')}Ausente</span>` : ''}</div>`;
      if (reg) {
        const R = RESULTADOS[reg.resultado];
        return `<div class="crow done">${h}<div><span class="badge ${R.cls}">${icon(R.icon)}${R.curto} · ${hhmm(reg.ocorridoEm)}</span>
          <span class="hint"> por ${esc(pessoa(reg.executor).nome)}${reg.ajudante ? ' com ' + esc(pessoa(reg.ajudante).nome) : ''}</span></div></div>`;
      }
      const l = linhaDe(c, i.id);
      const nm = 'c-' + i.id;
      const o = (v, cls) => `<label class="opt ${cls || ''}"><input type="radio" name="${nm}" id="${nm}-${v}" value="${v}" data-linha="${i.id}" ${l.resultado === v ? 'checked' : ''} ${dis}><span>${OPT_LABEL[v]}</span></label>`;
      return `<fieldset class="crow${l.erro ? ' failed' : ''}" id="crow-${i.id}">${h}
        <legend class="sr-only">Resultado para ${esc(r.nome)}</legend>
        ${l.erro ? `<div class="alert alert-err">${icon('wifiOff')}<div><strong>Não salvou.</strong><p>${esc(l.erro)} Dados mantidos.</p></div></div>` : ''}
        <div class="col-opts">${o('executada')}${o('recusada', 'recusa')}${o('omitida', 'nao')}</div>
        ${l.resultado === 'recusada' ? `<div class="field"><label for="m-${i.id}">Motivo da recusa (obrigatório)</label><input class="input" id="m-${i.id}" data-linha-campo="motivo" data-linha="${i.id}" value="${esc(l.motivo)}" ${l.erros.motivo ? 'aria-invalid="true"' : ''} ${dis}>${l.erros.motivo ? `<div class="err-txt">${l.erros.motivo}</div>` : ''}</div>` : ''}
        ${l.resultado === 'omitida' ? `<div class="field"><label for="mc-${i.id}">Motivo (obrigatório)</label><select class="input" id="mc-${i.id}" data-linha-campo="motivoCod" data-linha="${i.id}" ${l.erros.motivoCod ? 'aria-invalid="true"' : ''} ${dis}><option value="">Selecione…</option>${MOTIVOS_NAO.map(([k, t]) => `<option value="${k}" ${l.motivoCod === k ? 'selected' : ''}>${t}</option>`).join('')}</select>${l.erros.motivoCod ? `<div class="err-txt">${l.erros.motivoCod}</div>` : ''}</div>
          ${l.motivoCod === 'outro' ? `<div class="field"><label for="md-${i.id}">Detalhe (obrigatório)</label><input class="input" id="md-${i.id}" data-linha-campo="detalhe" data-linha="${i.id}" value="${esc(l.detalhe)}" ${l.erros.detalhe ? 'aria-invalid="true"' : ''} ${dis}>${l.erros.detalhe ? `<div class="err-txt">${l.erros.detalhe}</div>` : ''}</div>` : ''}` : ''}
        ${l.resultado ? `<div class="crow-extra">
          <div class="field"><label for="h-${i.id}">Horário</label><input type="time" class="input" id="h-${i.id}" data-linha-campo="hora" data-linha="${i.id}" value="${esc(l.hora || c.padrao)}" ${l.erros.hora ? 'aria-invalid="true"' : ''} ${dis}>${l.erros.hora ? `<div class="err-txt">${l.erros.hora}</div>` : ''}</div>
          <div class="field"><label for="a-${i.id}">Profissional que auxiliou</label><select class="input" id="a-${i.id}" data-linha-campo="ajudante" data-linha="${i.id}" ${dis}><option value="">Sem auxílio</option>${ajudantes.map((p) => `<option value="${p.id}" ${l.ajudante === p.id ? 'selected' : ''}>${esc(p.nome)}</option>`).join('')}</select></div>
        </div>
        <div><button type="button" class="link-btn" id="limpar-${i.id}" data-limpar="${i.id}" ${dis}>Limpar resultado</button> ${insp('proposta', 'ajudante por residente; exige migration')}</div>` : ''}
      </fieldset>`;
    }).join('');
    const sem = pend.length - comRes.length;
    const foot = `<div class="count" aria-live="polite"><strong>${comRes.length} de ${pend.length}</strong> com resultado${sem ? ` · ${sem} ${sem > 1 ? 'continuarão' : 'continuará'} sem registro` : ''}</div>
      <button type="button" class="btn btn-outline" data-close>Fechar</button>
      <button type="button" class="btn btn-primary" id="btn-col-salvar" data-col-salvar="${key}" ${!comRes.length || s ? 'disabled' : ''}>${s ? icon('loader', 'spin') + 'Salvando…' : `Salvar ${comRes.length} registro${comRes.length === 1 ? '' : 's'}`}</button>`;
    return { head, body, foot, tall: true };
  }

  async function salvarColetivo(key) {
    const c = colDe(key);
    if (c.status === 'saving') return;
    const its = grupoItens(key).filter((i) => !db.registros[i.id] || semConfirmacao(c, i.id));
    const alvo = its.filter((i) => linhaDe(c, i.id).resultado);
    let invalido = false;
    alvo.forEach((i) => {
      const l = linhaDe(c, i.id);
      l.erros = validar(Object.assign({}, l, { hora: l.hora || c.padrao }));
      if (Object.keys(l.erros).length) invalido = true;
    });
    if (invalido) { renderDetalhe(); const a = $('#sheet-body [aria-invalid="true"], #detalhe [aria-invalid="true"]'); if (a) a.focus(); anunciar('Revise as linhas destacadas.'); return; }
    c.status = 'saving'; c.resumo = null; renderDetalhe();
    const resumo = { ok: 0, falhas: 0, dup: 0, sem: its.length - alvo.length };
    for (const i of alvo) {
      const l = linhaDe(c, i.id);
      l.erro = null;
      try {
        const out = await api.salvarExecucao(i.id, { resultado: l.resultado, ocorridoEm: fromHHMM(l.hora || c.padrao), justificativa: justificativa(l), observacao: null, ajudante: l.ajudante || null }, l.idem);
        if (out.jaExistia) resumo.dup++; else resumo.ok++;
        delete c.linhas[i.id];
        atualizarItem(i.id);
      } catch (e) {
        l.erro = 'Sem conexão com o servidor.'; resumo.falhas++;
      }
    }
    c.status = 'idle'; c.resumo = resumo; renderDetalhe({ topo: true });
    const r = $('#col-resumo'); if (r) r.focus();
    anunciar(`${resumo.ok} salvos, ${resumo.falhas} com falha.`);
  }

  // ---------- Passagem ----------
  function passagemHTML() {
    if (!temPassagem()) {
      return `<div class="card state" role="alert">${icon('lock')}<h2 style="font-size:17px">Sem acesso à passagem de plantão</h2>
        <p class="hint" style="margin:0;max-width:420px;font-size:14px">Seu perfil não inclui a permissão de passagem. Peça liberação ao administrador da ILPI. Seus cuidados continuam no Meu Plantão.</p>
        <a class="btn btn-outline" href="#/plantao">Ir para o Meu Plantão</a>
        ${insp('existe', 'servidor responde 403 em /api/passagens (passagem_plantao:ler)')}${insp('proposta', 'menu oculto sem passagem_plantao:ler')}</div>`;
    }
    const P = passagem;
    const recebida = P.situacao === 'recebida';
    const linhaRes = (rid) => { const r = res(rid); return `<span class="row-title">${esc(r.nome)}</span><span class="row-sub">Quarto ${r.quarto} · Leito ${r.leito}</span>`; };
    const kv = (pares) => `<dl class="kv">${pares.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join('')}</dl>`;
    const pendAbertas = P.pendencias.filter((p) => !db.registros[p.itemId]).length;
    let html = `<h2 class="section-title" style="margin-top:4px">Passagem a receber</h2>
      <section class="card pass-card" aria-label="Passagem da ${esc(P.turno)}">
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;justify-content:space-between">
          <div><div class="rname">${esc(P.turno)} · ${esc(P.area)}</div><div class="rmeta">Entregue por ${esc(pessoa(P.entreguePor).nome)} às ${hhmm(P.entregueEm)}</div></div>
          ${recebida ? `<span class="badge b-ok">${icon('check')}Recebida às ${hhmm(P.recebidaEm)}</span>` : `<span class="badge b-atrasado">${icon('clock')}Aguardando recebimento</span>`}
        </div>
        <div class="receipt">
          ${recebida
            ? `<div class="alert alert-ok" id="recibo" tabindex="-1">${icon('check')}<div><strong>Recebimento confirmado às ${hhmm(P.recebidaEm)}.</strong><p>${pendAbertas ? `${pendAbertas} pendência${pendAbertas > 1 ? 's continuam abertas' : ' continua aberta'} no seu Meu Plantão. Receber não conclui cuidados.` : 'Todas as pendências herdadas já têm registro.'}</p></div></div>`
            : `<p style="margin:0;font-size:14px">Leia a passagem e confirme o recebimento. <strong>Confirmar não conclui</strong> nenhuma pendência: elas continuam no seu Meu Plantão.</p>
               <button type="button" class="btn btn-primary btn-receber" id="btn-receber" data-receber>${icon('check')}Confirmar recebimento</button>`}
          ${insp('existe', 'POST /api/passagens/{id}/receber · quem entregou não recebe · 2º recebimento = 409')}
        </div>
        ${insp('existe', 'GET /api/passagens/ (itens automáticos + notas)')}
        <h3 class="section-title">Pendências herdadas</h3>
        ${P.pendencias.map((p) => {
          const i = item(p.itemId); const reg = db.registros[p.itemId];
          return `<div class="pass-item"><div class="pass-head"><div class="row-main">${linhaRes(p.residenteId)}</div>
              ${reg ? `<span class="badge ${RESULTADOS[reg.resultado].cls}">${icon('check')}Registrado ${hhmm(reg.ocorridoEm)}</span>` : `<span class="badge b-atrasado">${icon('alert')}Continua pendente</span>`}</div>
            ${kv([['Atividade', esc(i.atividade)], ['Previsto', `${hhmm(i.prevista)} · ${esc(p.texto)}`], ['Responsável', esc(p.responsavel)], ['Prazo', esc(p.prazo)]])}
            ${reg ? '' : `<div class="pass-acoes"><button type="button" class="btn btn-outline btn-sm" data-open="${p.itemId}" id="pass-reg-${p.itemId}">Registrar cuidado</button></div>`}</div>`;
        }).join('')}
        <h3 class="section-title">Intercorrências em aberto</h3>
        ${P.intercorrencias.map((x) => `<div class="pass-item"><div class="pass-head"><div class="row-main">${linhaRes(x.residenteId)}</div><span class="badge b-crit">${icon('alert')}Em aberto</span></div>
          ${kv([['Ocorrência', `${esc(x.texto)} · ${esc(x.quando)}`], ['Situação', esc(x.detalhe)], ['Responsável', esc(x.responsavel)], ['Prazo', esc(x.prazo)]])}</div>`).join('')}
        <h3 class="section-title">Ausências</h3>
        ${P.ausencias.map((x) => `<div class="pass-line"><div class="row-main">${linhaRes(x.residenteId)}<span>${esc(x.texto)}</span></div><span class="badge b-info">${icon('away')}Ausente</span></div>`).join('')}
        <h3 class="section-title">Notas do turno</h3>
        ${P.notas.map((n) => `<div class="pass-line"><div class="row-main"><span><span class="badge b-pendente">${esc(n.categoria)}</span> ${esc(n.texto)}</span></div></div>`).join('')}
      </section>`;
    const meus = db.itens.filter((i) => i.origem === 'cuidado' && !db.registros[i.id]).sort((a, b) => a.prevista - b.prevista);
    const atras = meus.filter((i) => status(i).tipo === 'atrasado').length;
    html += `<h2 class="section-title">Passar meu plantão</h2>
      <section class="card pass-card" aria-label="Passar meu plantão">
        <p style="margin:0 0 4px;font-size:14px">Prévia automática: <strong>${plural(meus.length, 'cuidado sem registro', 'cuidados sem registro')}</strong>${atras ? `, ${atras} atrasado${atras > 1 ? 's' : ''}` : ''}. Seguem para o próximo turno com responsável e prazo.</p>
        ${meus.slice(0, 4).map((i) => `<div class="pass-line"><div class="row-main">${linhaRes(i.residenteId)}<span>${esc(i.atividade)} · previsto ${hhmm(i.prevista)}</span></div>${badge(i)}</div>`).join('')}
        ${meus.length > 4 ? `<p class="hint">+ ${meus.length - 4} outros na prévia.</p>` : ''}
        ${insp('existe', 'GET /api/passagens/previa')}
        ${minhaPassagem.entregueEm
          ? `<div class="alert alert-ok" style="margin-top:10px">${icon('check')}<div><strong>Entregue às ${hhmm(minhaPassagem.entregueEm)}.</strong><p>Aguardando recebimento pelo próximo turno. Quem entrega não pode confirmar o próprio recebimento.</p></div></div>`
          : `<div class="field" style="margin-top:10px"><label for="p-nota">Nota para o próximo turno (opcional)</label>
             <textarea class="input" id="p-nota" maxlength="280" data-pnota aria-describedby="p-cont">${esc(minhaPassagem.nota)}</textarea>
             <span class="hint" id="p-cont">${minhaPassagem.nota.length}/280 caracteres</span></div>
             <div style="margin-top:10px"><button type="button" class="btn btn-outline" id="btn-entregar" data-entregar ${minhaPassagem.status === 'saving' ? 'disabled' : ''}>${minhaPassagem.status === 'saving' ? 'Entregando…' : 'Entregar passagem'}</button></div>`}
        ${insp('existe', 'POST /api/passagens/ (nota ≤ 280 caracteres)')}
      </section>`;
    return html;
  }

  // ---------- Sheets auxiliares ----------
  function auxParts(tipo) {
    if (tipo === 'filtros') {
      const n = filtrados().length;
      const est = (v, l) => `<label class="opt"><input type="radio" name="f-estado" id="fe-${v}" value="${v}" ${ui.estado === v ? 'checked' : ''}><span>${l}</span></label>`;
      return {
        head: `<div class="sh-txt"><h2 id="sheet-title" tabindex="-1">Filtros</h2><div class="sh-sub">Aplicados na hora; ficam salvos ao voltar.</div></div>`,
        body: `<fieldset><legend class="legend">Estado</legend><div class="opts" style="grid-template-columns:repeat(2,minmax(0,1fr))">${est('todos', 'Todos')}${est('pendente', 'Pendentes')}${est('atrasado', 'Atrasados')}${est('registrado', 'Registrados')}</div></fieldset>
          <div class="field"><label for="f-res">Residente</label><select class="input" id="f-res"><option value="">Todos os residentes</option>${D.residentes.map((r) => `<option value="${r.id}" ${ui.residente === r.id ? 'selected' : ''}>${esc(r.nome)} · Q${r.quarto}·${r.leito}</option>`).join('')}</select></div>`,
        foot: `<button type="button" class="btn btn-outline" id="f-limpar" data-limpar-filtros>Limpar</button><button type="button" class="btn btn-primary" id="f-ver" data-close>Ver ${plural(n, 'item', 'itens')}</button>`,
      };
    }
    const nt = notificacoes();
    return {
      head: `<div class="sh-txt"><h2 id="sheet-title" tabindex="-1">Notificações</h2><div class="sh-sub">O que pede ação agora. Tocar leva ao lugar onde se resolve.</div></div>`,
      body: `${insp('existe', 'GET /api/central-alertas (visibilidade por permissão da origem)')}
        ${nt.pass ? `<div class="rcard"><button type="button" class="row" data-goto="#/passagem" id="nt-pass"><span class="row-time">${icon('swap')}</span><span class="row-main"><span class="row-title">Passagem da ${esc(passagem.turno)}</span><span class="row-sub">Aguardando seu recebimento</span></span>${icon('chevron', 'chev')}</button></div>` : ''}
        ${nt.atrasados.length ? `<h3 class="section-title" style="margin-top:0">Atrasados · ${nt.atrasados.length}</h3><div class="rcard">${nt.atrasados.map((i) => rowHTML(i, true).replace(`id="row-${i.id}"`, `id="nt-${i.id}"`)).join('')}</div>` : ''}
        ${!nt.total ? `<div class="state">${icon('inbox')}<strong>Nada pedindo ação agora.</strong></div>` : ''}`,
      foot: '',
    };
  }

  // ---------- Montagem do Sheet ----------
  function setInert(on) {
    ['#view', '.topbar', '#nav-bottom', '.sidebar'].forEach((s) => { const el = $(s); if (el) el.inert = on; });
  }
  function montarSheet(parts, tipo, ctx, opts) {
    const root = $('#sheet-root');
    const jaAberto = sheetTipo !== null;
    const mesmo = jaAberto && sheetCtx === ctx;
    const bodyAnt = $('#sheet-body');
    const st = mesmo && bodyAnt ? bodyAnt.scrollTop : 0;
    const ativo = mesmo && document.activeElement ? document.activeElement.id : null;
    root.innerHTML = `<div class="sheet-backdrop${jaAberto ? ' static' : ''}" data-close></div>
      <section id="sheet" class="sheet${jaAberto ? ' static' : ''}${parts.tall ? ' tall' : ''}" role="dialog" aria-modal="true" aria-labelledby="sheet-title">
        <div class="sheet-head"><div class="grip" aria-hidden="true"></div><div class="sheet-head-row">${parts.head}
          <button type="button" class="icon-btn" id="sheet-fechar" data-close aria-label="Fechar">${icon('x')}</button></div></div>
        <div class="sheet-body${jaAberto && !mesmo ? ' swap' : ''}" id="sheet-body">${parts.body}</div>
        ${parts.foot ? `<div class="sheet-foot">${parts.foot}</div>` : ''}
      </section>`;
    sheetTipo = tipo; sheetCtx = ctx;
    document.body.classList.add('sheet-open');
    setInert(true);
    const body = $('#sheet-body');
    if (mesmo) {
      body.scrollTop = (opts && opts.topo) ? 0 : st;
      if (ativo) { const el = document.getElementById(ativo); if (el && !el.disabled) el.focus({ preventScroll: true }); }
    } else {
      $('#sheet-title').focus({ preventScroll: true });
    }
  }
  function desmontarSheet(devolverFoco) {
    if (!sheetTipo) return;
    $('#sheet-root').innerHTML = '';
    sheetTipo = null; sheetCtx = null;
    document.body.classList.remove('sheet-open');
    setInert(false);
    if (devolverFoco) devolverFocoOpener();
  }
  function devolverFocoOpener() {
    if (!opener) return;
    const el = $(opener);
    if (el) el.focus({ preventScroll: true });
  }

  function renderDetalhe(opts) {
    const r = rota();
    if (!ehDetalhe(r)) return;
    const parts = r.nome === 'registro' ? registroParts(r.id) : coletivoParts(r.key);
    const ctx = r.nome + ':' + (r.id || r.key);
    if (mqWide.matches) {
      const el = $('#detalhe'); if (!el) return;
      const ativo = document.activeElement && el.contains(document.activeElement) ? document.activeElement.id : null;
      const bAnt = el.querySelector('.dcard-body'); const st = bAnt && el.dataset.ctx === ctx ? bAnt.scrollTop : 0;
      el.innerHTML = `<div class="card dcard"><div class="dcard-head">${parts.head}<button type="button" class="icon-btn" data-close aria-label="Fechar">${icon('x')}</button></div>
        <div class="dcard-body">${parts.body}</div>${parts.foot ? `<div class="dcard-foot">${parts.foot}</div>` : ''}</div>`;
      const nb = el.querySelector('.dcard-body'); nb.scrollTop = (opts && opts.topo) ? 0 : st;
      if (el.dataset.ctx !== ctx) { el.dataset.ctx = ctx; const t = $('#sheet-title'); if (t) t.focus({ preventScroll: true }); }
      else if (ativo) { const a = document.getElementById(ativo); if (a && !a.disabled) a.focus({ preventScroll: true }); }
      document.querySelectorAll('.row.current, .gcard.current').forEach((e) => e.classList.remove('current'));
      const atual = $('#row-' + (r.id || '')) || $('#grp-' + (r.key || ''));
      if (atual) atual.classList.add('current');
    } else {
      montarSheet(parts, 'rota', ctx, opts);
    }
  }

  // ---------- render ----------
  function renderBase(nome) {
    const view = $('#view');
    if (nome === 'passagem') view.innerHTML = passagemHTML();
    else if (nome === 'residentes') view.innerHTML = residentesHTML();
    else view.innerHTML = `<div class="split"><div class="split-list" id="lista" aria-label="Lista do plantão">${listaHTML()}</div><div class="split-detail" id="detalhe"></div></div>`;
    requestAnimationFrame(marcarChips);
  }
  function render() {
    const r = rota();
    const wide = mqWide.matches;
    const det = ehDetalhe(r);
    if (!det) baseRoute = r.nome;
    const base = det ? (wide ? 'plantao' : baseRoute) : r.nome;
    const key = (wide ? 'W:' : 'M:') + base;
    if (key !== renderedKey) {
      if (renderedBase) ui.scroll[renderedBase] = window.scrollY;
      renderBase(base);
      renderedKey = key; renderedBase = base;
      window.scrollTo(0, ui.scroll[base] || 0);
      saveUi();
    }
    renderCromo(r, base);
    if (det) {
      if (!wide && aux) aux = null;
      renderDetalhe();
    } else {
      if (sheetTipo === 'rota') desmontarSheet(true);
      if (wide && base === 'plantao') {
        const el = $('#detalhe');
        if (el) { el.dataset.ctx = ''; el.innerHTML = `<div class="card placeholder">${icon('clipboard')}<p style="margin:0">Escolha um cuidado na lista para registrar.<br>Use “Por atividade” para registrar em grupo.</p></div>`; }
        document.querySelectorAll('.row.current, .gcard.current').forEach((e) => e.classList.remove('current'));
      }
    }
    renderAux();
  }
  function renderAux() {
    if (aux && sheetTipo !== 'rota') montarSheet(auxParts(aux), 'aux', 'aux:' + aux);
    else if (!aux && sheetTipo === 'aux') desmontarSheet(true);
  }

  function preservando(fn) {
    const y = window.scrollY;
    const lst = $('#lista'); const st = lst ? lst.scrollTop : 0;
    const ativo = document.activeElement && document.activeElement.id;
    fn();
    const nl = $('#lista'); if (nl) nl.scrollTop = st;
    window.scrollTo(0, y);
    if (ativo && !sheetTipo) { const el = document.getElementById(ativo); if (el) el.focus({ preventScroll: true }); }
  }
  function marcarChips() {
    const c = $('#chips'); const w = $('#chips-wrap'); if (!c || !w) return;
    w.classList.toggle('mais', c.scrollLeft + c.clientWidth < c.scrollWidth - 4);
  }
  const rerenderLista = () => { preservando(() => { const el = $('#lista'); if (el) el.innerHTML = listaHTML(); }); marcarChips(); };
  const rerenderBase = () => preservando(() => renderBase(renderedBase));

  // Atualiza só o que depende do item salvo: linha, grupo, contadores, sino. A posição da lista não muda.
  function flash(el) { if (!el) return; el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash'); }
  function atualizarItem(id) {
    renderCromo(rota(), renderedBase);
    if (renderedBase !== 'plantao') { rerenderBase(); return; }
    const chips = $('#chips'); if (chips) { chips.innerHTML = chipsHTML(); marcarChips(); }
    const i = item(id);
    const row = $('#row-' + id);
    if (row) { row.outerHTML = rowHTML(i, ui.visao === 'atividade'); flash($('#row-' + id)); }
    const k = grupoKey(i);
    const g = document.getElementById('grp-' + k);
    if (g) {
      const its = filtrados().filter((x) => x.origem === 'cuidado' && grupoKey(x) === k);
      g.outerHTML = grupoHTML(k, its.length ? its : grupoItens(k)); flash(document.getElementById('grp-' + k));
    }
    if (mqWide.matches) { const r = rota(); const atual = $('#row-' + (r.id || '')) || $('#grp-' + (r.key || '')); if (atual) atual.classList.add('current'); }
    if (sheetTipo === 'aux') renderAux();
    if (!sheetTipo && document.activeElement === document.body) devolverFocoOpener();
  }

  // ---------- navegação ----------
  function abrirDetalhe(hash, origemSel) {
    opener = origemSel;
    if (sheetTipo === 'aux') { aux = null; desmontarSheet(false); }
    origemInterna = true;
    location.hash = hash;
  }
  function irPara(id) { location.replace('#/registro/' + id); } // troca o conteúdo do Sheet sem empilhar histórico
  function fecharDetalhe(depois) {
    aposRender = depois || null;
    if (!mqWide.matches && origemInterna) { origemInterna = false; history.back(); }
    else { origemInterna = false; location.hash = '#/' + (mqWide.matches ? 'plantao' : baseRoute); }
  }
  function fecharTopo() {
    if (sheetTipo === 'aux') { aux = null; renderAux(); return; }
    fecharDetalhe();
  }

  window.addEventListener('hashchange', () => {
    const r = rota();
    if (!ehDetalhe(r)) origemInterna = false;
    render();
    if (aposRender) { const f = aposRender; aposRender = null; f(); }
    if (!ehDetalhe(r) && !sheetTipo) {
      if (document.activeElement === document.body || !document.activeElement) {
        if (opener && $(opener)) devolverFocoOpener(); else $('#view').focus({ preventScroll: true });
      }
    }
  });
  mqWide.addEventListener('change', () => { renderedKey = null; if (sheetTipo === 'rota') desmontarSheet(false); render(); });

  // ---------- feedback ----------
  let toastTimer;
  function toast(msg) {
    const t = $('#toast'); t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 4500);
  }
  function anunciar(msg) { const l = $('#live'); l.textContent = ''; setTimeout(() => { l.textContent = msg; }, 30); }
  function dialogo(titulo, corpo, okLabel, soOk) {
    const dlg = $('#dlg');
    $('#dlg-title').textContent = titulo;
    $('#dlg-body').innerHTML = corpo;
    $('#dlg-ok').textContent = okLabel || 'Confirmar';
    dlg.querySelector('button[value="cancel"]').hidden = !!soOk;
    dlg.returnValue = '';
    return new Promise((resolve) => { dlg.addEventListener('close', () => resolve(dlg.returnValue === 'ok'), { once: true }); dlg.showModal(); });
  }

  // ---------- eventos ----------
  document.addEventListener('click', async (ev) => {
    const b = ev.target.closest('button, [data-close]');
    if (!b || b.closest('dialog') || b.closest('.proto-strip')) return;
    const r = rota();
    if (b.hasAttribute('data-close')) { fecharTopo(); return; }
    if (b.dataset.open) { abrirDetalhe('#/registro/' + b.dataset.open, b.id ? '#' + b.id : null); return; }
    if (b.dataset.grupo) { abrirDetalhe('#/coletivo/' + b.dataset.grupo, '#grp-' + b.dataset.grupo + ' button'); return; }
    if (b.dataset.ir) { irPara(b.dataset.ir); return; }
    if (b.dataset.goto) { aux = null; desmontarSheet(false); opener = '#btn-sino'; location.hash = b.dataset.goto; return; }
    if (b.dataset.aux) { opener = '#' + b.id; aux = b.dataset.aux; renderAux(); return; }
    if (b.dataset.chip) {
      const k = b.dataset.chip;
      if (k === 'todos') { ui.origem = 'todos'; ui.estado = 'todos'; }
      else if (k === 'atrasados') ui.estado = ui.estado === 'atrasado' ? 'todos' : 'atrasado';
      else ui.origem = ui.origem === k ? 'todos' : k;
      saveUi(); rerenderLista(); return;
    }
    if (b.dataset.visao) { ui.visao = b.dataset.visao; saveUi(); rerenderLista(); return; }
    if (b.dataset.remover) { if (b.dataset.remover === 'residente') ui.residente = ''; else ui.estado = 'todos'; saveUi(); rerenderLista(); const f = $('#btn-filtros'); if (f) f.focus(); return; }
    if (b.hasAttribute('data-limpar-filtros')) { ui.origem = 'todos'; ui.estado = 'todos'; ui.residente = ''; saveUi(); rerenderLista(); if (sheetTipo === 'aux') renderAux(); return; }
    if (b.dataset.residente) { ui.residente = b.dataset.residente; ui.visao = 'residente'; ui.scroll.plantao = 0; saveUi(); opener = '#btn-filtros'; renderedKey = null; location.hash = '#/plantao'; return; }
    if (b.dataset.med) {
      const i = item(b.dataset.med);
      await dialogo('Medicação tem fluxo próprio', `<p><strong>${esc(i.atividade)}</strong> para ${esc(res(i.residenteId).nome)}, previsto ${hhmm(i.prevista)}.</p><p class="hint">Doses são registradas pela administração de medicamentos (com quantidade), não pelo formulário de cuidados. Este protótipo apenas referencia esse fluxo.</p>`, 'Entendi', true);
      b.focus(); return;
    }
    if (b.hasAttribute('data-agora')) { const f = formDe(r.id); f.hora = agoraHHMM(); delete f.erros.hora; renderDetalhe(); return; }
    if (b.dataset.salvar) { salvarIndividual(r.id, b.dataset.salvar); return; }
    if (b.dataset.limpar) { delete colDe(r.key).linhas[b.dataset.limpar]; renderDetalhe(); const x = document.getElementById('c-' + b.dataset.limpar + '-executada'); if (x) x.focus(); return; }
    if (b.dataset.colSalvar) { salvarColetivo(b.dataset.colSalvar); return; }
    if (b.hasAttribute('data-receber')) {
      const abertas = passagem.pendencias.filter((p) => !db.registros[p.itemId]).length;
      const ok = await dialogo('Confirmar recebimento?', `<p>Você confirma que leu a passagem da <strong>${esc(passagem.turno)}</strong>.</p><p>${abertas ? `${abertas} pendência${abertas > 1 ? 's continuam abertas' : ' continua aberta'} e sob responsabilidade do seu turno.` : ''} Nenhum cuidado será marcado como realizado.</p>`, 'Confirmar recebimento');
      if (ok) { passagem.situacao = 'recebida'; passagem.recebidaEm = agora(); rerenderBase(); renderCromo(rota(), renderedBase); const rc = $('#recibo'); if (rc) rc.focus(); }
      return;
    }
    if (b.hasAttribute('data-entregar')) {
      minhaPassagem.status = 'saving'; rerenderBase();
      setTimeout(() => { minhaPassagem.status = 'idle'; minhaPassagem.entregueEm = agora(); rerenderBase(); anunciar('Passagem entregue.'); }, 700);
    }
  });

  document.addEventListener('input', (ev) => {
    const el = ev.target; const r = rota();
    if (el.dataset.campo && r.nome === 'registro') {
      const f = formDe(r.id); f[el.dataset.campo] = el.value;
      const pre = $('#payload'); if (pre) pre.textContent = 'POST /api/execucoes-cuidado\n' + JSON.stringify(payloadDe(r.id, f), null, 2);
    }
    if (el.dataset.linhaCampo && r.nome === 'coletivo') linhaDe(colDe(r.key), el.dataset.linha)[el.dataset.linhaCampo] = el.value;
    if (el.hasAttribute('data-col-padrao')) colDe(r.key).padrao = el.value;
    if (el.hasAttribute('data-pnota')) { minhaPassagem.nota = el.value; const c = $('#p-cont'); if (c) c.textContent = el.value.length + '/280 caracteres'; }
  });

  document.addEventListener('change', (ev) => {
    const el = ev.target; const r = rota();
    if (r.nome === 'registro' && el.name === 'resultado') { const f = formDe(r.id); f.resultado = el.value; f.erros = {}; renderDetalhe(); return; }
    if (r.nome === 'registro' && el.dataset.campo === 'motivoCod') { formDe(r.id).motivoCod = el.value; renderDetalhe(); return; }
    if (r.nome === 'coletivo' && el.dataset.linha && el.type === 'radio') { const l = linhaDe(colDe(r.key), el.dataset.linha); l.resultado = el.value; l.erros = {}; renderDetalhe(); return; }
    if (r.nome === 'coletivo' && el.dataset.linhaCampo === 'motivoCod') { linhaDe(colDe(r.key), el.dataset.linha).motivoCod = el.value; renderDetalhe(); return; }
    if (r.nome === 'coletivo' && el.hasAttribute('data-col-padrao')) { renderDetalhe(); return; }
    if (el.name === 'f-estado') { ui.estado = el.value; saveUi(); rerenderLista(); renderAux(); return; }
    if (el.id === 'f-res') { ui.residente = el.value; saveUi(); rerenderLista(); renderAux(); }
  });

  // Teclado: Esc fecha o Sheet; Tab fica preso dentro dele.
  document.addEventListener('keydown', (e) => {
    if ($('#dlg').open) return;
    if (e.key === 'Escape') {
      const d = $('.proto-sim[open]'); if (d) { d.open = false; return; }
      if (sheetTipo || (mqWide.matches && ehDetalhe(rota()))) { e.preventDefault(); fecharTopo(); }
      return;
    }
    if (e.key === 'Tab' && sheetTipo) {
      const f = [...$('#sheet').querySelectorAll('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled])')].filter((x) => x.offsetParent !== null || x.type === 'radio');
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && (document.activeElement === first || !$('#sheet').contains(document.activeElement))) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && (document.activeElement === last || !$('#sheet').contains(document.activeElement))) { e.preventDefault(); first.focus(); }
    }
  });

  // Teclado virtual (proposta): acompanha o visualViewport e mantém o campo focado visível.
  function ajustarViewport() {
    const vv = window.visualViewport; if (!vv) return;
    const kb = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
    document.documentElement.style.setProperty('--kb', kb + 'px');
    document.documentElement.style.setProperty('--vvh', vv.height + 'px');
  }
  if (window.visualViewport) { window.visualViewport.addEventListener('resize', ajustarViewport); window.visualViewport.addEventListener('scroll', ajustarViewport); ajustarViewport(); }
  document.addEventListener('focusin', (e) => {
    if (e.target.closest && e.target.closest('#sheet-body') && e.target.matches('input, select, textarea')) {
      setTimeout(() => e.target.scrollIntoView({ block: 'nearest' }), 250);
    }
  });

  document.addEventListener('scroll', (e) => { if (e.target && e.target.id === 'chips') marcarChips(); }, true);
  window.addEventListener('resize', marcarChips);
  setInterval(() => { if (!sheetTipo) renderCromo(rota(), renderedBase); }, 30000);

  // Controles do protótipo
  $('#btn-inspecao').addEventListener('click', (e) => { const on = document.body.classList.toggle('inspect'); e.currentTarget.setAttribute('aria-pressed', String(on)); });
  $('#sim-perfil').addEventListener('change', () => { renderCromo(rota(), renderedBase); if (renderedBase === 'passagem') rerenderBase(); if (sheetTipo === 'aux') renderAux(); });
  $('#sim-reset').addEventListener('click', () => { reset(); aux = null; desmontarSheet(false); renderedKey = null; render(); setTimeout(() => { loaded = true; rerenderLista(); }, 450); toast('Dados sintéticos reiniciados.'); });

  // Início
  if (!location.hash) history.replaceState(null, '', location.pathname + location.search + '#/plantao');
  // ?captura: só para gerar imagens estáticas — sem atraso de carregamento nem animações.
  const captura = new URLSearchParams(location.search).has('captura');
  if (captura) { document.documentElement.classList.add('captura'); loaded = true; }
  render();
  setTimeout(() => {
    loaded = true;
    if (renderedBase === 'plantao') { rerenderLista(); window.scrollTo(0, ui.scroll.plantao || 0); }
    renderCromo(rota(), renderedBase);
    // Somente para capturas/demonstração: ?sheet=filtros|notificacoes abre o Sheet auxiliar.
    const q = new URLSearchParams(location.search).get('sheet');
    if ((q === 'filtros' || q === 'notificacoes') && !ehDetalhe(rota())) { opener = q === 'filtros' ? '#btn-filtros' : '#btn-sino'; aux = q; renderAux(); }
  }, captura ? 0 : 450);
})();
