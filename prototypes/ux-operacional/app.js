// Protótipo isolado — nada aqui chama o backend. Respostas, permissões e idempotência são simuladas.
(function () {
  'use strict';
  const D = window.PROTO_DATA;
  const $ = (s, el) => (el || document).querySelector(s);

  // ---------- armazenamento de conveniência (pode falhar) ----------
  const store = {
    get(k, d) { try { const v = sessionStorage.getItem('proto-ux-' + k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
    set(k, v) { try { sessionStorage.setItem('proto-ux-' + k, JSON.stringify(v)); } catch (e) { /* sem armazenamento */ } },
  };

  // ---------- estado ----------
  let db, passagem, minhaPassagem, forms, colForms, loaded;
  const ui = Object.assign({ filtro: 'todos', visao: 'residente', scrollY: 0 }, store.get('ui', {}));
  let listScroll = 0;
  function reset() {
    db = { itens: D.itens.map((i) => Object.assign({}, i)), registros: structuredClone(D.registros) };
    passagem = structuredClone(D.passagemRecebida);
    minhaPassagem = { nota: '', entregueEm: null, status: 'idle' };
    forms = {};
    colForms = {};
    loaded = false;
  }
  reset();
  const saveUi = () => store.set('ui', ui);

  // ---------- utilidades ----------
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const hhmm = (d) => d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  const agoraHHMM = () => hhmm(new Date());
  function fromHHMM(v) {
    if (!/^\d{2}:\d{2}$/.test(v || '')) return null;
    const d = new Date(); const [h, m] = v.split(':').map(Number); d.setHours(h, m, 0, 0); return d;
  }
  const noFuturo = (d) => d && d.getTime() <= Date.now() + 60000;
  const res = (id) => D.residentes.find((r) => r.id === id);
  const pessoa = (id) => D.equipe.find((p) => p.id === id);
  const item = (id) => db.itens.find((i) => i.id === id);
  const iniciais = (n) => n.split(' ').filter((p) => p.length > 2).slice(0, 2).map((p) => p[0]).join('').toUpperCase();
  const uid = () => Math.random().toString(36).slice(2) + Date.now().toString(36);
  const slug = (s) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-');
  const grupoKey = (i) => slug(i.atividade) + '-' + hhmm(i.prevista).replace(':', '');

  const RESULTADOS = {
    executada: { label: 'Realizado', curto: 'Realizado', cls: 'b-ok', icon: 'check' },
    recusada: { label: 'Recusado pelo residente', curto: 'Recusou', cls: 'b-recusa', icon: 'x' },
    omitida: { label: 'Não realizado', curto: 'Não realizado', cls: 'b-nao', icon: 'ban' },
  };
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
    return { tipo: i.prevista.getTime() < Date.now() ? 'atrasado' : 'pendente' };
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
    back: '<path d="m15 18-6-6 6-6"/>',
    lock: '<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    loader: '<path d="M21 12a9 9 0 1 1-6.219-8.56"/>',
    pill: '<path d="m10.5 20.5 10-10a4.95 4.95 0 1 0-7-7l-10 10a4.95 4.95 0 1 0 7 7Z"/><path d="m8.5 8.5 7 7"/>',
    wifiOff: '<path d="M12 20h.01"/><path d="M8.5 16.43a5 5 0 0 1 7 0"/><path d="M2 8.82a15 15 0 0 1 4.17-2.65"/><path d="M10.66 5c4.01-.36 8.14.9 11.34 3.76"/><path d="M16.85 11.25a10 10 0 0 1 2.22 1.68"/><path d="M5 13a10 10 0 0 1 5.24-2.76"/><path d="m2 2 20 20"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    inbox: '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    away: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="22" x2="16" y1="11" y2="11"/>',
  };
  function icon(n) { return `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n] || ''}</svg>`; }

  // ---------- API simulada ----------
  function consumirFalha() {
    const sel = $('#sim-falha'); const v = sel.value; sel.value = 'none'; return v;
  }
  const api = {
    // Espelha o contrato de POST /api/execucoes-cuidado: um registro vigente por ocorrência (409 na repetição).
    // A chave de idempotência é proposta; o backend atual devolve 409 e a tela passa a mostrar o registro existente.
    salvarExecucao(itemId, payload, idem) {
      const modo = consumirFalha();
      return new Promise((resolve, reject) => {
        setTimeout(() => {
          if (modo === 'antes') return reject(new Error('rede'));
          const existente = db.registros[itemId];
          if (existente) return resolve({ jaExistia: true, reg: existente });
          const reg = Object.assign({}, payload, { registradoEm: new Date(), executor: 'f1', idem });
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
    if (nome === 'passagem') return { nome };
    return { nome: 'plantao' };
  }
  const temPassagem = () => $('#sim-perfil').value === 'com';

  function renderNav(r) {
    const itens = [{ href: '#/plantao', label: 'Meu Plantão', icon: 'clipboard', ativo: r.nome !== 'passagem' }];
    // P0-4 (proposta): o menu segue a permissão de passagem, não plantao:ler.
    if (temPassagem()) itens.push({ href: '#/passagem', label: 'Passagem', icon: 'swap', ativo: r.nome === 'passagem' });
    const html = itens.map((n) => `<a href="${n.href}"${n.ativo ? ' aria-current="page"' : ''}>${icon(n.icon)}<span>${n.label}</span></a>`).join('');
    $('#nav-side').innerHTML = html;
    $('#nav-bottom').innerHTML = html;
  }

  // ---------- Meu Plantão (lista) ----------
  function filtrados() {
    return db.itens.filter((i) => {
      if (ui.filtro === 'cuidado') return i.origem === 'cuidado';
      if (ui.filtro === 'medicacao') return i.origem === 'medicacao';
      if (ui.filtro === 'atrasados') return status(i).tipo === 'atrasado';
      return true;
    }).sort((a, b) => a.prevista - b.prevista);
  }
  function ordemNavegacao() {
    // mesma ordem visual da visão por residente
    const lista = filtrados();
    return D.residentes.flatMap((r) => lista.filter((i) => i.residenteId === r.id));
  }

  function listaHTML(atualId) {
    const contagem = {
      todos: db.itens.length,
      cuidado: db.itens.filter((i) => i.origem === 'cuidado').length,
      medicacao: db.itens.filter((i) => i.origem === 'medicacao').length,
      atrasados: db.itens.filter((i) => status(i).tipo === 'atrasado').length,
    };
    const chip = (k, l) => `<button type="button" class="chip" data-filtro="${k}" aria-pressed="${ui.filtro === k}">${l} <span aria-hidden="true">·</span> ${contagem[k]}</button>`;
    let html = `
      <div class="toolbar">
        <div class="chips" role="group" aria-label="Filtrar itens">
          ${chip('todos', 'Todos')}${chip('cuidado', 'Cuidados')}${chip('medicacao', 'Medicação')}${chip('atrasados', 'Atrasados')}
        </div>
        <div class="seg" role="group" aria-label="Organizar lista">
          <button type="button" data-visao="residente" aria-pressed="${ui.visao === 'residente'}">Por residente</button>
          <button type="button" data-visao="atividade" aria-pressed="${ui.visao === 'atividade'}">Por atividade</button>
        </div>
      </div>
      ${insp('existe', 'GET /api/meu-plantao/ e /api/plantao/ (itens de cuidado, medicação, intercorrência)')}
      ${insp('proposta', 'filtros, visão e rolagem preservados ao voltar (sessionStorage)')}`;

    if (!loaded) {
      return html + [1, 2, 3].map(() => `<div class="card res-card" aria-hidden="true"><div class="sk" style="height:40px;width:60%"></div><div class="sk" style="height:14px;margin-top:10px"></div><div class="sk" style="height:14px;margin-top:8px;width:80%"></div></div>`).join('') + '<p class="sr-only">Carregando o plantão…</p>';
    }
    const lista = filtrados();
    if (!lista.length) {
      const nomes = { todos: 'Todos', cuidado: 'Cuidados', medicacao: 'Medicação', atrasados: 'Atrasados' };
      return html + `<div class="card state">${icon('inbox')}<strong>Nenhum item em “${nomes[ui.filtro]}” agora.</strong><span class="hint">Isso não é um erro: o filtro não tem itens neste momento.</span><button type="button" class="btn btn-outline" data-filtro="todos">Ver todos</button></div>`;
    }
    if (ui.visao === 'residente') {
      html += D.residentes.map((r) => {
        const its = lista.filter((i) => i.residenteId === r.id);
        if (!its.length) return '';
        return `<section class="card res-card" aria-label="${esc(r.nome)}">
          <div class="res-head">
            <span class="avatar" aria-hidden="true">${iniciais(r.nome)}</span>
            <div class="item-main"><div class="res-name">${esc(r.nome)}</div>
              <div class="res-meta">Quarto ${r.quarto} · Leito ${r.leito} · ${r.idade} anos</div></div>
            ${r.ausente ? `<span class="badge b-info">${icon('away')}Ausente</span>` : ''}
          </div>
          ${its.map((i) => itemHTML(i, atualId)).join('')}
        </section>`;
      }).join('');
    } else {
      const grupos = {};
      lista.filter((i) => i.origem === 'cuidado').forEach((i) => { (grupos[grupoKey(i)] = grupos[grupoKey(i)] || []).push(i); });
      html += Object.entries(grupos).map(([k, its]) => {
        const feitos = its.filter((i) => db.registros[i.id]).length;
        const atras = its.filter((i) => status(i).tipo === 'atrasado').length;
        const pend = its.length - feitos;
        const acao = its.length > 1
          ? (pend ? `<a class="btn btn-primary btn-sm" href="#/coletivo/${k}">${icon('users')}Registrar em grupo</a>` : `<a class="btn btn-ghost btn-sm" href="#/coletivo/${k}">Ver grupo</a>`)
          : `<a class="btn ${pend ? 'btn-primary' : 'btn-ghost'} btn-sm" href="#/registro/${its[0].id}">${pend ? 'Registrar' : 'Ver'}</a>`;
        return `<section class="card group-card${atualId === k ? ' current' : ''}" aria-label="${esc(its[0].atividade)}">
          <div class="item-main">
            <div class="item-title">${esc(its[0].atividade)}${its[0].herdada ? ' <span class="badge b-info">Herdada</span>' : ''}</div>
            <div class="item-sub">Previsto ${hhmm(its[0].prevista)} · ${feitos} de ${its.length} registrados${atras ? ` · <strong>${atras} atrasado${atras > 1 ? 's' : ''}</strong>` : ''}</div>
            <div class="progress" aria-hidden="true"><span style="width:${Math.round((feitos / its.length) * 100)}%"></span></div>
          </div>${acao}</section>`;
      }).join('');
      const meds = lista.filter((i) => i.origem === 'medicacao');
      if (meds.length) {
        html += `<h2 class="section-title">Medicação · fluxo próprio</h2><div class="card res-card">${meds.map((i) => itemHTML(i, atualId, true)).join('')}</div>`;
      }
    }
    return html;
  }

  function itemHTML(i, atualId, comNome) {
    const s = status(i);
    const sub = [`Previsto ${hhmm(i.prevista)}`];
    if (i.herdada) sub.push(`herdada da ${i.herdada}`);
    if (comNome) sub.unshift(res(i.residenteId).nome);
    let acao;
    if (i.origem === 'medicacao') {
      acao = `<button type="button" class="btn btn-ghost btn-sm" data-med="${i.id}">${icon('pill')}Medicação</button>`;
    } else if (s.tipo === 'registrado') {
      acao = `<a class="btn btn-ghost btn-sm" href="#/registro/${i.id}" aria-label="Ver registro de ${esc(i.atividade)}">Ver</a>`;
    } else {
      acao = `<a class="btn btn-primary btn-sm" href="#/registro/${i.id}" aria-label="Registrar ${esc(i.atividade)} de ${esc(res(i.residenteId).nome)}">Registrar</a>`;
    }
    return `<div class="item${atualId === i.id ? ' current' : ''}">
      <div class="item-main"><div class="item-title">${esc(i.atividade)}</div>
        <div class="item-sub">${esc(sub.join(' · '))}</div><div style="margin-top:4px">${badge(i)}</div></div>
      ${acao}</div>`;
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
    const p = { ocorrencia_id: id, resultado: f.resultado || '(escolha)', ocorrido_em: (fromHHMM(f.hora) || new Date()).toISOString() };
    const j = justificativa(f); if (j) p.justificativa = j;
    if (f.obs.trim()) p.observacao = f.obs.trim();
    return p;
  }

  function cabecalhoResidente(r) {
    return `<div class="res-sticky">
      <span class="avatar" aria-hidden="true">${iniciais(r.nome)}</span>
      <div class="item-main"><div class="res-name">${esc(r.nome)}</div>
      <div class="res-meta">Quarto ${r.quarto} · Leito ${r.leito} · ${r.idade} anos</div></div>
      ${r.ausente ? `<span class="badge b-info">${icon('away')}Ausente</span>` : ''}
    </div>`;
  }

  function registroHTML(id) {
    const i = item(id);
    if (!i) return `<div class="card state">${icon('info')}<strong>Item não encontrado.</strong><a class="btn btn-outline" href="#/plantao">Voltar ao Meu Plantão</a></div>`;
    const r = res(i.residenteId);
    let html = `<a class="back" href="#/plantao">${icon('back')}Meu Plantão</a>${cabecalhoResidente(r)}`;
    html += `<div class="card form-card">
      <div><h1 tabindex="-1" id="h-detalhe" style="font-size:20px">${esc(i.atividade)}</h1>
        <div class="item-sub" style="margin-top:4px">Previsto ${hhmm(i.prevista)} ${badge(i)} ${i.herdada ? `<span class="badge b-info">Herdada da ${esc(i.herdada)}</span>` : ''}</div>
        ${r.ausente ? `<p class="hint" style="margin:6px 0 0">${esc(r.ausente)}</p>` : ''}
      </div>`;
    if (i.origem === 'medicacao') {
      return html + `<div class="alert alert-info">${icon('pill')}<div><strong>Medicação tem fluxo próprio.</strong><p>Doses são registradas pela administração de medicamentos, com quantidade obrigatória. Este protótipo não substitui esse fluxo.</p></div></div></div>`;
    }
    // Enquanto o envio não tiver confirmação, a tela não presume sucesso (mesmo que o servidor simulado tenha gravado).
    const pendenteConfirmacao = forms[id] && forms[id].status !== 'idle';
    const reg = db.registros[id];
    if (reg && !pendenteConfirmacao) {
      const R = RESULTADOS[reg.resultado];
      const ex = pessoa(reg.executor);
      html += `<div class="alert alert-ok">${icon('check')}<div><strong>Registrado: ${R.label}</strong>
        <p>Horário real: <strong>${hhmm(reg.ocorridoEm)}</strong> · Registro gravado às ${hhmm(reg.registradoEm)} por ${esc(ex ? ex.nome : '—')}${ex && ex.voce ? ' (você)' : ''}</p>
        ${reg.justificativa ? `<p>Motivo: ${esc(reg.justificativa)}</p>` : ''}
        ${reg.ajudante ? `<p>Ajudante: ${esc(pessoa(reg.ajudante).nome)}</p>` : ''}
        ${reg.observacao ? `<p>Observação: ${esc(reg.observacao)}</p>` : ''}</div></div>
        <p class="hint" style="margin:0">Correção: estorno com motivo, que mantém o registro original visível. ${insp('existe', 'POST /api/execucoes-cuidado/{id}/estornar')} ${insp('proposta', 'tela de estorno')}</p>
        <div class="actions"><a class="btn btn-outline" href="#/plantao">Voltar à lista</a>${proximo(id) ? `<a class="btn btn-primary" href="#/registro/${proximo(id).id}">Próximo pendente</a>` : ''}</div></div>`;
      return html;
    }

    const f = formDe(id);
    const salvando = f.status === 'saving';
    const opt = (v, cls) => `<label class="opt ${cls || ''}"><input type="radio" name="resultado" id="r-${v}" value="${v}" ${f.resultado === v ? 'checked' : ''} ${salvando ? 'disabled' : ''}><span>${icon(RESULTADOS[v].icon)}${RESULTADOS[v].label}</span></label>`;
    const ajudantes = D.equipe.filter((p) => p.emPlantao && !p.voce);
    html += `
      ${f.erro ? `<div class="alert alert-err" id="erro-envio" tabindex="-1">${icon('wifiOff')}<div><strong>Não foi possível salvar.</strong><p>${esc(f.erro)} O que você preencheu continua aqui.</p></div></div>` : ''}
      <fieldset>
        <legend class="legend">Resultado <span class="hint">(obrigatório — nada vem marcado)</span></legend>
        <div class="opts" role="radiogroup" aria-describedby="${f.erros.resultado ? 'e-res' : ''}">${opt('executada')}${opt('recusada', 'recusa')}${opt('omitida', 'nao')}</div>
        ${f.erros.resultado ? `<div class="err-txt" id="e-res">${f.erros.resultado}</div>` : ''}
        ${insp('existe', 'executada | recusada | omitida; justificativa obrigatória fora de executada')}
      </fieldset>
      ${f.resultado === 'recusada' ? `<div class="field"><label for="f-motivo">Motivo da recusa (obrigatório)</label>
        <textarea class="input" id="f-motivo" data-campo="motivo" ${f.erros.motivo ? 'aria-invalid="true" aria-describedby="e-motivo"' : ''} ${salvando ? 'disabled' : ''}>${esc(f.motivo)}</textarea>
        ${f.erros.motivo ? `<div class="err-txt" id="e-motivo">${f.erros.motivo}</div>` : ''}</div>` : ''}
      ${f.resultado === 'omitida' ? `<div class="row2"><div class="field"><label for="f-motivocod">Por que não foi realizado? (obrigatório)</label>
        <select class="input" id="f-motivocod" data-campo="motivoCod" ${f.erros.motivoCod ? 'aria-invalid="true" aria-describedby="e-mcod"' : ''} ${salvando ? 'disabled' : ''}>
          <option value="">Selecione…</option>${MOTIVOS_NAO.map(([k, l]) => `<option value="${k}" ${f.motivoCod === k ? 'selected' : ''}>${l}</option>`).join('')}</select>
        ${f.erros.motivoCod ? `<div class="err-txt" id="e-mcod">${f.erros.motivoCod}</div>` : ''}</div>
        <div class="field"><label for="f-detalhe">Detalhe ${f.motivoCod === 'outro' ? '(obrigatório)' : '(opcional)'}</label>
        <input class="input" id="f-detalhe" data-campo="detalhe" value="${esc(f.detalhe)}" ${f.erros.detalhe ? 'aria-invalid="true" aria-describedby="e-det"' : ''} ${salvando ? 'disabled' : ''}>
        ${f.erros.detalhe ? `<div class="err-txt" id="e-det">${f.erros.detalhe}</div>` : ''}</div></div>
        ${insp('existe', 'grava como omitida + justificativa (texto)')}` : ''}
      <div class="row2">
        <div class="field"><label for="f-hora">Horário real do cuidado</label>
          <div class="time-row"><input type="time" class="input" id="f-hora" data-campo="hora" value="${esc(f.hora)}" ${f.erros.hora ? 'aria-invalid="true" aria-describedby="e-hora"' : 'aria-describedby="h-hora"'} ${salvando ? 'disabled' : ''}>
          <button type="button" class="btn btn-outline btn-sm" data-agora ${salvando ? 'disabled' : ''}>Agora</button></div>
          ${f.erros.hora ? `<div class="err-txt" id="e-hora">${f.erros.hora}</div>` : `<span class="hint" id="h-hora">Quando aconteceu. O horário do registro é gravado pelo servidor.</span>`}
          ${insp('existe', 'ocorrido_em ≠ registrado_em; futuro = 422')}
        </div>
        <div class="field"><label for="f-ajudante">Ajudante (opcional)</label>
          <select class="input" id="f-ajudante" data-campo="ajudante" ${salvando ? 'disabled' : ''}><option value="">Sem ajudante</option>
          ${ajudantes.map((p) => `<option value="${p.id}" ${f.ajudante === p.id ? 'selected' : ''}>${esc(p.nome)} · ${esc(p.funcao)}</option>`).join('')}</select>
          <span class="hint">Colegas em plantão agora.</span>
          ${insp('proposta', 'campo novo; exige migration (ExecucaoCuidado não tem ajudante)')}
        </div>
      </div>
      <div class="field"><label for="f-obs">Observação (opcional)</label>
        <textarea class="input" id="f-obs" data-campo="obs" ${salvando ? 'disabled' : ''}>${esc(f.obs)}</textarea></div>
      <div class="actions">
        <button type="button" class="btn btn-outline" data-salvar="lista" ${!f.resultado || salvando ? 'disabled' : ''}>${salvando ? icon('loader').replace('class="i"', 'class="i spin"') + 'Salvando…' : (f.erro ? 'Tentar novamente' : 'Salvar')}</button>
        <button type="button" class="btn btn-primary" data-salvar="proximo" ${!f.resultado || salvando ? 'disabled' : ''}>${salvando ? 'Aguarde…' : (f.erro ? 'Tentar e ir ao próximo' : 'Salvar e próximo')}</button>
      </div>
      ${insp('proposta', 'botões travados durante o envio; repetição reaproveita a mesma chave ' + f.idem.slice(0, 6) + '…')}
      <pre class="insp existe">POST /api/execucoes-cuidado\n${esc(JSON.stringify(payloadDe(id, f), null, 2))}</pre>
    </div>`;
    return html;
  }

  function proximo(id) {
    const ordem = ordemNavegacao().filter((i) => i.origem === 'cuidado');
    const idx = ordem.findIndex((i) => i.id === id);
    const seq = ordem.slice(idx + 1).concat(ordem.slice(0, Math.max(idx, 0)));
    return seq.find((i) => i.id !== id && !db.registros[i.id]) || null;
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
      rerender();
      const alvo = $('[aria-invalid="true"]') || $('input[name="resultado"]');
      if (alvo) alvo.focus();
      anunciar('Revise os campos destacados.');
      return;
    }
    f.status = 'saving'; f.erro = null; rerender();
    const payload = { resultado: f.resultado, ocorridoEm: fromHHMM(f.hora), justificativa: justificativa(f), observacao: f.obs.trim() || null, ajudante: f.ajudante || null };
    try {
      const out = await api.salvarExecucao(id, payload, f.idem);
      delete forms[id];
      const i = item(id);
      if (out.jaExistia) {
        toast(`Este cuidado já estava registrado às ${hhmm(out.reg.registradoEm)}. Nenhum registro duplicado foi criado.`);
      } else {
        toast(`${i.atividade} de ${res(i.residenteId).nome.split(' ')[0]}: ${RESULTADOS[out.reg.resultado].curto} às ${hhmm(out.reg.ocorridoEm)}.`);
      }
      const prox = destino === 'proximo' ? proximo(id) : null;
      location.hash = prox ? '#/registro/' + prox.id : '#/plantao';
      if (destino === 'proximo' && !prox) anunciar('Não há mais cuidados pendentes neste filtro.');
    } catch (e) {
      f.status = 'error';
      f.erro = 'Sem conexão com o servidor. Nada foi confirmado.';
      rerender();
      const a = $('#erro-envio'); if (a) a.focus();
    }
  }

  // ---------- Registro coletivo ----------
  function grupoItens(key) { return db.itens.filter((i) => i.origem === 'cuidado' && grupoKey(i) === key).sort((a, b) => D.residentes.findIndex((r) => r.id === a.residenteId) - D.residentes.findIndex((r) => r.id === b.residenteId)); }
  function colDe(key) {
    if (!colForms[key]) colForms[key] = { padrao: agoraHHMM(), linhas: {}, status: 'idle', resumo: null };
    return colForms[key];
  }
  function linhaDe(c, id) {
    if (!c.linhas[id]) c.linhas[id] = { resultado: '', motivo: '', motivoCod: '', detalhe: '', hora: '', ajudante: '', idem: uid(), erro: null, erros: {} };
    return c.linhas[id];
  }

  function coletivoHTML(key) {
    const its = grupoItens(key);
    if (!its.length) return `<div class="card state">${icon('info')}<strong>Grupo não encontrado.</strong><a class="btn btn-outline" href="#/plantao">Voltar</a></div>`;
    const c = colDe(key);
    const salvando = c.status === 'saving';
    const pend = its.filter((i) => !db.registros[i.id] || (c.linhas[i.id] && c.linhas[i.id].erro));
    const comRes = pend.filter((i) => linhaDe(c, i.id).resultado);
    const ajudantes = D.equipe.filter((p) => p.emPlantao && !p.voce);
    let html = `<a class="back" href="#/plantao">${icon('back')}Meu Plantão</a>
      <div class="card form-card" style="margin-bottom:12px">
        <div><h1 tabindex="-1" id="h-detalhe" style="font-size:20px">${esc(its[0].atividade)} · em grupo</h1>
        <div class="item-sub">Previsto ${hhmm(its[0].prevista)} · ${its.length} residentes · ${its.length - pend.length} já registrados</div></div>
        <div class="row2"><div class="field"><label for="c-padrao">Horário real padrão</label>
          <input type="time" class="input" id="c-padrao" data-col-padrao value="${esc(c.padrao)}" aria-describedby="h-padrao" ${salvando ? 'disabled' : ''}>
          <span class="hint" id="h-padrao">Vale para as linhas sem horário próprio.</span></div>
          <div class="alert alert-info" style="align-self:end">${icon('info')}<div><p style="margin:0">Marque cada residente. Linhas sem resultado <strong>continuam sem registro</strong>, nada é marcado automaticamente.</p></div></div>
        </div>
        ${insp('proposta', 'tela coletiva; cada linha envia 1 POST /api/execucoes-cuidado (existe), sem mudança no backend')}
        ${c.resumo ? `<div class="alert ${c.resumo.falhas ? 'alert-warn' : 'alert-ok'}" id="col-resumo" tabindex="-1">${icon(c.resumo.falhas ? 'alert' : 'check')}<div><strong>${c.resumo.ok} salvo${c.resumo.ok === 1 ? '' : 's'}${c.resumo.falhas ? ` · ${c.resumo.falhas} não salvo${c.resumo.falhas === 1 ? '' : 's'}` : ''}${c.resumo.dup ? ` · ${c.resumo.dup} já estava${c.resumo.dup === 1 ? '' : 'm'} registrado${c.resumo.dup === 1 ? '' : 's'}` : ''}.</strong>
          <p>${c.resumo.falhas ? 'As linhas com falha mantêm o preenchimento; salve de novo pelo botão no rodapé.' : ''} ${c.resumo.sem ? `${c.resumo.sem} continua${c.resumo.sem === 1 ? '' : 'm'} sem registro.` : ''}</p></div></div>` : ''}
      </div>`;

    html += its.map((i) => {
      const r = res(i.residenteId);
      const semConfirmacao = c.linhas[i.id] && c.linhas[i.id].erro;
      const reg = semConfirmacao ? null : db.registros[i.id];
      const head = `<div class="res-head" style="margin:0"><span class="avatar sm" aria-hidden="true">${iniciais(r.nome)}</span>
        <div class="item-main"><div class="res-name">${esc(r.nome)}</div><div class="res-meta">Quarto ${r.quarto} · Leito ${r.leito}</div></div>
        ${r.ausente ? `<span class="badge b-info">${icon('away')}Ausente</span>` : ''}</div>`;
      if (reg) {
        const R = RESULTADOS[reg.resultado];
        return `<div class="card col-row done">${head}<div><span class="badge ${R.cls}">${icon(R.icon)}${R.curto} · ${hhmm(reg.ocorridoEm)}</span>
          <span class="hint"> por ${esc(pessoa(reg.executor).nome)}${reg.ajudante ? ' com ' + esc(pessoa(reg.ajudante).nome) : ''}</span></div></div>`;
      }
      const l = linhaDe(c, i.id);
      const nm = 'c-' + i.id;
      const o = (v, cls) => `<label class="opt ${cls || ''}"><input type="radio" name="${nm}" id="${nm}-${v}" value="${v}" data-linha="${i.id}" ${l.resultado === v ? 'checked' : ''} ${salvando ? 'disabled' : ''}><span>${RESULTADOS[v].curto}</span></label>`;
      return `<fieldset class="card col-row${l.erro ? ' failed' : ''}">${head}
        <legend class="sr-only">Resultado para ${esc(r.nome)}</legend>
        ${l.erro ? `<div class="alert alert-err">${icon('wifiOff')}<div><strong>Não salvou.</strong><p>${esc(l.erro)} Dados mantidos.</p></div></div>` : ''}
        <div class="col-opts">${o('executada')}${o('recusada', 'recusa')}${o('omitida', 'nao')}</div>
        ${l.erros.resultado ? `<div class="err-txt">${l.erros.resultado}</div>` : ''}
        ${l.resultado === 'recusada' ? `<div class="field"><label for="m-${i.id}">Motivo da recusa (obrigatório)</label><input class="input" id="m-${i.id}" data-linha-campo="motivo" data-linha="${i.id}" value="${esc(l.motivo)}" ${l.erros.motivo ? 'aria-invalid="true"' : ''} ${salvando ? 'disabled' : ''}>${l.erros.motivo ? `<div class="err-txt">${l.erros.motivo}</div>` : ''}</div>` : ''}
        ${l.resultado === 'omitida' ? `<div class="row2"><div class="field"><label for="mc-${i.id}">Motivo (obrigatório)</label><select class="input" id="mc-${i.id}" data-linha-campo="motivoCod" data-linha="${i.id}" ${l.erros.motivoCod ? 'aria-invalid="true"' : ''} ${salvando ? 'disabled' : ''}><option value="">Selecione…</option>${MOTIVOS_NAO.map(([k, t]) => `<option value="${k}" ${l.motivoCod === k ? 'selected' : ''}>${t}</option>`).join('')}</select>${l.erros.motivoCod ? `<div class="err-txt">${l.erros.motivoCod}</div>` : ''}</div>
          <div class="field"><label for="md-${i.id}">Detalhe ${l.motivoCod === 'outro' ? '(obrigatório)' : '(opcional)'}</label><input class="input" id="md-${i.id}" data-linha-campo="detalhe" data-linha="${i.id}" value="${esc(l.detalhe)}" ${l.erros.detalhe ? 'aria-invalid="true"' : ''} ${salvando ? 'disabled' : ''}>${l.erros.detalhe ? `<div class="err-txt">${l.erros.detalhe}</div>` : ''}</div></div>` : ''}
        ${l.resultado ? `<div class="col-extra">
          <div class="field"><label for="h-${i.id}">Horário</label><input type="time" class="input" id="h-${i.id}" data-linha-campo="hora" data-linha="${i.id}" value="${esc(l.hora || c.padrao)}" ${l.erros.hora ? 'aria-invalid="true"' : ''} ${salvando ? 'disabled' : ''}>${l.erros.hora ? `<div class="err-txt">${l.erros.hora}</div>` : ''}</div>
          <div class="field"><label for="a-${i.id}">Ajudante deste residente</label><select class="input" id="a-${i.id}" data-linha-campo="ajudante" data-linha="${i.id}" ${salvando ? 'disabled' : ''}><option value="">Sem ajudante</option>${ajudantes.map((p) => `<option value="${p.id}" ${l.ajudante === p.id ? 'selected' : ''}>${esc(p.nome)}</option>`).join('')}</select>${insp('proposta', 'ajudante por residente; exige migration')}</div>
        </div>
        <div><button type="button" class="btn btn-ghost btn-sm" data-limpar="${i.id}" ${salvando ? 'disabled' : ''}>Limpar resultado</button></div>` : ''}
      </fieldset>`;
    }).join('');

    const sem = pend.length - comRes.length;
    html += `<div class="sticky-foot">
      <div class="count" aria-live="polite"><strong>${comRes.length} de ${pend.length}</strong> com resultado${sem ? ` · ${sem} continuará${sem > 1 ? 'ão' : ''} sem registro` : ''}</div>
      <button type="button" class="btn btn-primary" data-col-salvar="${key}" ${!comRes.length || salvando ? 'disabled' : ''}>${salvando ? icon('loader').replace('class="i"', 'class="i spin"') + 'Salvando…' : `Salvar ${comRes.length} registro${comRes.length === 1 ? '' : 's'}`}</button>
    </div>`;
    return html;
  }

  async function salvarColetivo(key) {
    const c = colDe(key);
    if (c.status === 'saving') return;
    const its = grupoItens(key).filter((i) => !db.registros[i.id] || (c.linhas[i.id] && c.linhas[i.id].erro));
    const alvo = its.filter((i) => linhaDe(c, i.id).resultado);
    let invalido = false;
    alvo.forEach((i) => {
      const l = linhaDe(c, i.id);
      l.erros = validar(Object.assign({}, l, { hora: l.hora || c.padrao }));
      if (Object.keys(l.erros).length) invalido = true;
    });
    if (invalido) { rerender(); const a = $('[aria-invalid="true"]'); if (a) a.focus(); anunciar('Revise as linhas destacadas.'); return; }
    c.status = 'saving'; c.resumo = null; rerender();
    const resumo = { ok: 0, falhas: 0, dup: 0, sem: its.length - alvo.length };
    for (const i of alvo) {
      const l = linhaDe(c, i.id);
      try {
        const out = await api.salvarExecucao(i.id, { resultado: l.resultado, ocorridoEm: fromHHMM(l.hora || c.padrao), justificativa: justificativa(l), observacao: null, ajudante: l.ajudante || null }, l.idem);
        if (out.jaExistia) resumo.dup++; else resumo.ok++;
        delete c.linhas[i.id];
      } catch (e) {
        l.erro = 'Sem conexão com o servidor.'; resumo.falhas++;
      }
    }
    c.status = 'idle'; c.resumo = resumo; rerender();
    const r = $('#col-resumo'); if (r) r.focus();
    anunciar(`${resumo.ok} salvos, ${resumo.falhas} com falha.`);
  }

  // ---------- Passagem ----------
  function passagemHTML() {
    if (!temPassagem()) {
      return `<div class="card state" role="alert">${icon('lock')}<h1 tabindex="-1" id="h-detalhe" style="font-size:18px">Sem acesso à passagem de plantão</h1>
        <p class="hint" style="margin:0;max-width:420px">Seu perfil não inclui a permissão de passagem. Peça liberação ao administrador da ILPI. Seus cuidados continuam disponíveis no Meu Plantão.</p>
        <a class="btn btn-outline" href="#/plantao">Ir para o Meu Plantão</a>
        ${insp('existe', 'servidor responde 403 em /api/passagens (passagem_plantao:ler); a tela atual já trata')}
        ${insp('proposta', 'menu oculto sem passagem_plantao:ler (hoje usa plantao:ler)')}</div>`;
    }
    const P = passagem;
    const recebida = P.situacao === 'recebida';
    const linhaRes = (rid) => { const r = res(rid); return `<strong>${esc(r.nome)}</strong> <span class="res-meta">· Quarto ${r.quarto} · Leito ${r.leito}</span>`; };
    const pendAbertas = P.pendencias.filter((p) => !db.registros[p.itemId]).length;

    let html = `<h1 tabindex="-1" id="h-detalhe" class="section-title" style="margin-top:4px">Passagem a receber</h1>
      <section class="card pass-card" aria-label="Passagem da ${esc(P.turno)}">
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;justify-content:space-between">
          <div><div class="res-name">${esc(P.turno)} · ${esc(P.area)}</div>
          <div class="res-meta">Entregue por ${esc(pessoa(P.entreguePor).nome)} às ${hhmm(P.entregueEm)}</div></div>
          ${recebida ? `<span class="badge b-ok">${icon('check')}Recebida por você às ${hhmm(P.recebidaEm)}</span>` : `<span class="badge b-atrasado">${icon('clock')}Aguardando seu recebimento</span>`}
        </div>
        ${insp('existe', 'GET /api/passagens/ (itens automáticos montados pelo servidor + notas)')}

        <h2 class="section-title">Pendências herdadas</h2>
        ${P.pendencias.map((p) => {
          const i = item(p.itemId); const reg = db.registros[p.itemId];
          return `<div class="pass-line"><div class="item-main">${linhaRes(p.residenteId)}<div>${esc(i.atividade)} · prevista ${hhmm(i.prevista)} · ${esc(p.texto)}</div>
            <div class="item-sub">Responsável: ${esc(p.responsavel)} · Prazo: ${esc(p.prazo)}</div></div>
            ${reg ? `<span class="badge ${RESULTADOS[reg.resultado].cls}">${icon('check')}Registrado ${hhmm(reg.ocorridoEm)}</span>`
              : `<span class="badge b-atrasado">${icon('alert')}Continua pendente</span><a class="btn btn-outline btn-sm" href="#/registro/${p.itemId}">Registrar</a>`}</div>`;
        }).join('')}

        <h2 class="section-title">Intercorrências em aberto</h2>
        ${P.intercorrencias.map((x) => `<div class="pass-line"><div class="item-main">${linhaRes(x.residenteId)}<div>${esc(x.texto)}</div>
          <div class="item-sub">Responsável: ${esc(x.responsavel)} · ${esc(x.prazo)}</div></div><span class="badge b-crit">${icon('alert')}Em aberto</span></div>`).join('')}

        <h2 class="section-title">Ausências</h2>
        ${P.ausencias.map((x) => `<div class="pass-line"><div class="item-main">${linhaRes(x.residenteId)}<div>${esc(x.texto)}</div></div><span class="badge b-info">${icon('away')}Ausente</span></div>`).join('')}

        <h2 class="section-title">Notas do turno</h2>
        ${P.notas.map((n) => `<div class="pass-line"><div class="item-main"><span class="badge b-pendente">${esc(n.categoria)}</span> ${esc(n.texto)}</div></div>`).join('')}

        <div class="receipt">
          ${recebida
            ? `<div class="alert alert-ok" id="recibo" tabindex="-1">${icon('check')}<div><strong>Recebimento confirmado às ${hhmm(P.recebidaEm)}.</strong><p>${pendAbertas ? `${pendAbertas} pendência${pendAbertas > 1 ? 's continuam abertas' : ' continua aberta'} no seu Meu Plantão. Receber não conclui cuidados.` : 'Todas as pendências herdadas já têm registro.'}</p></div></div>`
            : `<p style="margin:0"><strong>Confirmar recebimento</strong> registra que você leu esta passagem. <strong>Não conclui</strong> nenhuma pendência: elas continuam no seu Meu Plantão.</p>
               <div><button type="button" class="btn btn-primary" data-receber>Confirmar recebimento</button></div>`}
          ${insp('existe', 'POST /api/passagens/{id}/receber · quem entregou não recebe · 2º recebimento = 409')}
        </div>
      </section>`;

    // Passar meu plantão
    const meus = db.itens.filter((i) => i.origem === 'cuidado' && !db.registros[i.id]).sort((a, b) => a.prevista - b.prevista);
    const atras = meus.filter((i) => status(i).tipo === 'atrasado').length;
    html += `<h2 class="section-title">Passar meu plantão</h2>
      <section class="card pass-card" aria-label="Passar meu plantão">
        <p style="margin:0 0 6px">Prévia automática: <strong>${meus.length} cuidado${meus.length === 1 ? '' : 's'} sem registro</strong>${atras ? `, ${atras} atrasado${atras > 1 ? 's' : ''}` : ''}. Eles seguem para o próximo turno com responsável e prazo.</p>
        ${meus.slice(0, 4).map((i) => `<div class="pass-line"><div class="item-main">${linhaRes(i.residenteId)}<div>${esc(i.atividade)} · previsto ${hhmm(i.prevista)}</div></div>${badge(i)}</div>`).join('')}
        ${meus.length > 4 ? `<p class="hint">+ ${meus.length - 4} outros na prévia.</p>` : ''}
        ${insp('existe', 'GET /api/passagens/previa')}
        ${minhaPassagem.entregueEm
          ? `<div class="alert alert-ok" style="margin-top:10px">${icon('check')}<div><strong>Entregue às ${hhmm(minhaPassagem.entregueEm)}.</strong><p>Aguardando recebimento pelo próximo turno. Quem entrega não pode confirmar o próprio recebimento.</p></div></div>`
          : `<div class="field" style="margin-top:10px"><label for="p-nota">Nota para o próximo turno (opcional)</label>
             <textarea class="input" id="p-nota" maxlength="280" data-pnota aria-describedby="p-cont">${esc(minhaPassagem.nota)}</textarea>
             <span class="hint" id="p-cont">${minhaPassagem.nota.length}/280 caracteres</span></div>
             <div style="margin-top:10px"><button type="button" class="btn btn-outline" data-entregar ${minhaPassagem.status === 'saving' ? 'disabled' : ''}>${minhaPassagem.status === 'saving' ? 'Entregando…' : 'Entregar passagem'}</button></div>`}
        ${insp('existe', 'POST /api/passagens/ (nota ≤ 280 caracteres)')}
      </section>`;
    return html;
  }

  // ---------- render ----------
  let rotaAnterior = null;
  function render() {
    const r = rota();
    renderNav(r);
    const view = $('#view');
    const lst = view.querySelector('.split-list');
    if (lst) listScroll = lst.scrollTop;

    const titulos = { plantao: 'Meu Plantão', registro: 'Registrar cuidado', coletivo: 'Registrar em grupo', passagem: 'Passagem de plantão' };
    $('#page-title').textContent = titulos[r.nome];
    $('#page-sub').textContent = 'Manhã 07–13 · Ala B';
    document.title = titulos[r.nome] + ' · Protótipo FacILPI';

    if (r.nome === 'passagem') {
      view.innerHTML = passagemHTML();
    } else {
      const atual = r.nome === 'registro' ? r.id : r.nome === 'coletivo' ? r.key : null;
      const detalhe = r.nome === 'registro' ? registroHTML(r.id)
        : r.nome === 'coletivo' ? coletivoHTML(r.key)
        : `<div class="card placeholder">${icon('clipboard')}<p>Escolha um cuidado na lista para registrar.<br>Use “Por atividade” para registrar em grupo.</p></div>`;
      view.innerHTML = `<div class="split${r.nome === 'plantao' ? ' home' : ''}">
        <div class="split-list" aria-label="Lista do plantão">${listaHTML(atual)}</div>
        <div class="split-detail">${detalhe}</div></div>`;
      const nl = view.querySelector('.split-list');
      if (nl) nl.scrollTop = listScroll;
    }
    rotaAnterior = r;
  }

  function rerender() {
    const ativo = document.activeElement && document.activeElement.id;
    const y = window.scrollY;
    render();
    window.scrollTo(0, y);
    if (ativo) { const el = document.getElementById(ativo); if (el && !el.disabled) el.focus({ preventScroll: true }); }
  }

  function aoMudarRota() {
    if (rotaAnterior && rotaAnterior.nome === 'plantao') { ui.scrollY = window.scrollY; saveUi(); }
    render();
    const r = rota();
    if (r.nome === 'plantao') {
      window.scrollTo(0, ui.scrollY || 0);
      const alvo = $('#view');
      alvo.focus({ preventScroll: true });
    } else {
      window.scrollTo(0, 0);
      const h = $('#h-detalhe'); if (h) h.focus({ preventScroll: true });
    }
  }

  // ---------- feedback ----------
  let toastTimer;
  function toast(msg) {
    const t = $('#toast'); t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 5000);
  }
  function anunciar(msg) { const l = $('#live'); l.textContent = ''; setTimeout(() => { l.textContent = msg; }, 30); }

  function dialogo(titulo, corpo, okLabel, soOk) {
    const dlg = $('#dlg');
    $('#dlg-title').textContent = titulo;
    $('#dlg-body').innerHTML = corpo;
    $('#dlg-ok').textContent = okLabel || 'Confirmar';
    dlg.querySelector('button[value="cancel"]').hidden = !!soOk;
    dlg.returnValue = '';
    return new Promise((resolve) => {
      dlg.addEventListener('close', () => resolve(dlg.returnValue === 'ok'), { once: true });
      dlg.showModal();
    });
  }

  // ---------- eventos ----------
  const view = $('#view');
  view.addEventListener('click', async (ev) => {
    const b = ev.target.closest('button');
    if (!b) return;
    const r = rota();
    if (b.dataset.filtro) { ui.filtro = b.dataset.filtro; saveUi(); rerender(); return; }
    if (b.dataset.visao) { ui.visao = b.dataset.visao; saveUi(); rerender(); return; }
    if (b.dataset.med) {
      const i = item(b.dataset.med);
      await dialogo('Medicação tem fluxo próprio', `<p><strong>${esc(i.atividade)}</strong> para ${esc(res(i.residenteId).nome)}, previsto ${hhmm(i.prevista)}.</p><p class="hint">Doses são registradas pela administração de medicamentos (com quantidade), não pelo formulário de cuidados. Este protótipo apenas referencia esse fluxo.</p>`, 'Entendi', true);
      return;
    }
    if (b.hasAttribute('data-agora')) { const f = formDe(r.id); f.hora = agoraHHMM(); delete f.erros.hora; rerender(); return; }
    if (b.dataset.salvar) { salvarIndividual(r.id, b.dataset.salvar); return; }
    if (b.dataset.limpar) { const c = colDe(r.key); delete c.linhas[b.dataset.limpar]; rerender(); return; }
    if (b.dataset.colSalvar) { salvarColetivo(b.dataset.colSalvar); return; }
    if (b.hasAttribute('data-receber')) {
      const abertas = passagem.pendencias.filter((p) => !db.registros[p.itemId]).length;
      const ok = await dialogo('Confirmar recebimento?', `<p>Você confirma que leu a passagem da <strong>${esc(passagem.turno)}</strong>.</p><p>${abertas ? `${abertas} pendência${abertas > 1 ? 's continuam abertas' : ' continua aberta'} e sob responsabilidade do seu turno.` : ''} Nenhum cuidado será marcado como realizado.</p>`, 'Confirmar recebimento');
      if (ok) { passagem.situacao = 'recebida'; passagem.recebidaEm = new Date(); rerender(); const rc = $('#recibo'); if (rc) rc.focus(); }
      return;
    }
    if (b.hasAttribute('data-entregar')) {
      minhaPassagem.status = 'saving'; rerender();
      setTimeout(() => { minhaPassagem.status = 'idle'; minhaPassagem.entregueEm = new Date(); rerender(); anunciar('Passagem entregue.'); }, 700);
    }
  });

  view.addEventListener('input', (ev) => {
    const el = ev.target; const r = rota();
    if (el.dataset.campo && r.nome === 'registro') {
      const f = formDe(r.id); f[el.dataset.campo] = el.value;
      const pre = view.querySelector('pre.insp'); if (pre) pre.textContent = 'POST /api/execucoes-cuidado\n' + JSON.stringify(payloadDe(r.id, f), null, 2);
    }
    if (el.dataset.linhaCampo && r.nome === 'coletivo') { linhaDe(colDe(r.key), el.dataset.linha)[el.dataset.linhaCampo] = el.value; }
    if (el.hasAttribute('data-col-padrao')) { colDe(r.key).padrao = el.value; }
    if (el.hasAttribute('data-pnota')) { minhaPassagem.nota = el.value; const c = $('#p-cont'); if (c) c.textContent = el.value.length + '/280 caracteres'; }
  });

  view.addEventListener('change', (ev) => {
    const el = ev.target; const r = rota();
    if (r.nome === 'registro' && el.name === 'resultado') { const f = formDe(r.id); f.resultado = el.value; f.erros = {}; rerender(); return; }
    if (r.nome === 'registro' && el.dataset.campo === 'motivoCod') { formDe(r.id).motivoCod = el.value; rerender(); return; }
    if (r.nome === 'coletivo' && el.dataset.linha && el.type === 'radio') { const l = linhaDe(colDe(r.key), el.dataset.linha); l.resultado = el.value; l.erros = {}; rerender(); return; }
    if (r.nome === 'coletivo' && el.dataset.linhaCampo === 'motivoCod') { linhaDe(colDe(r.key), el.dataset.linha).motivoCod = el.value; rerender(); return; }
    if (r.nome === 'coletivo' && el.hasAttribute('data-col-padrao')) { rerender(); }
  });

  $('#btn-inspecao').addEventListener('click', (e) => {
    const on = document.body.classList.toggle('inspect');
    e.currentTarget.setAttribute('aria-pressed', String(on));
  });
  $('#sim-perfil').addEventListener('change', () => rerender());
  $('#sim-reset').addEventListener('click', () => { reset(); render(); setTimeout(() => { loaded = true; render(); }, 450); toast('Dados sintéticos reiniciados.'); });
  window.addEventListener('hashchange', aoMudarRota);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { const d = $('.proto-sim[open]'); if (d) d.open = false; } });

  if (!location.hash) history.replaceState(null, '', '#/plantao');
  render();
  setTimeout(() => { loaded = true; rerender(); if (rota().nome === 'plantao') window.scrollTo(0, ui.scrollY || 0); }, 450);
})();
