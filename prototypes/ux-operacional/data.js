// Dados 100% sintéticos. Nomes fictícios; nenhuma relação com pessoas reais.
// Relógio simulado: o protótipo começa às 09:40 do turno Manhã 07–13 e avança no ritmo real a partir daí,
// para que os estados de atraso sejam coerentes em qualquer horário em que for aberto.
(function () {
  const inicioSimulado = new Date();
  inicioSimulado.setHours(9, 40, 0, 0);
  const abertoEm = Date.now();
  const relogio = () => new Date(inicioSimulado.getTime() + (Date.now() - abertoEm));
  const as = (h, m) => { const d = new Date(inicioSimulado); d.setHours(h, m, 0, 0); return d; };

  const equipe = [
    { id: 'f1', nome: 'Ana Souza', funcao: 'Cuidadora', emPlantao: true, voce: true },
    { id: 'f2', nome: 'Bruno Lima', funcao: 'Cuidador', emPlantao: true },
    { id: 'f3', nome: 'Carla Mendes', funcao: 'Téc. de enfermagem', emPlantao: true },
    { id: 'f4', nome: 'Paula Reis', funcao: 'Téc. de enfermagem', emPlantao: false },
  ];

  const residentes = [
    { id: 'r1', nome: 'Maria Aparecida Lopes', quarto: '12', leito: 'B', idade: 84 },
    { id: 'r2', nome: 'José Carlos Pereira', quarto: '12', leito: 'A', idade: 79 },
    { id: 'r3', nome: 'Helena Martins', quarto: '14', leito: 'A', idade: 91 },
    { id: 'r4', nome: 'Antônio Ribeiro', quarto: '14', leito: 'B', idade: 88 },
    { id: 'r5', nome: 'Lúcia Fernandes', quarto: '15', leito: 'A', idade: 76 },
    { id: 'r6', nome: 'Sebastião Nunes', quarto: '15', leito: 'B', idade: 82, ausente: 'Consulta externa · retorno previsto 11:00' },
  ];

  // origem: 'cuidado' (formulário de cuidado) | 'medicacao' (registro em módulo específico, só referência)
  // Tudo dentro do turno 07–13, exceto a pendência herdada da noite (06:00).
  const itens = [];
  let seq = 1;
  const add = (residenteId, atividade, origem, prevista, extra) =>
    itens.push(Object.assign({ id: 'o' + seq++, residenteId, atividade, origem, prevista }, extra || {}));

  ['r1', 'r2', 'r3', 'r4', 'r5', 'r6'].forEach((r) => add(r, 'Café da manhã', 'cuidado', as(8, 0), { grupo: 'cafe' }));
  add('r3', 'Troca de fralda', 'cuidado', as(6, 0), { herdada: 'Noite 19–07' });
  ['r1', 'r3', 'r4'].forEach((r) => add(r, 'Troca de fralda', 'cuidado', as(9, 0)));
  ['r3', 'r4'].forEach((r) => add(r, 'Mudança de decúbito', 'cuidado', as(10, 0), { grupo: 'decubito' }));
  ['r2', 'r5', 'r6'].forEach((r) => add(r, 'Hidratação', 'cuidado', as(10, 30), { grupo: 'hidratacao' }));
  ['r1', 'r2'].forEach((r) => add(r, 'Higiene oral', 'cuidado', as(11, 0), { grupo: 'higiene' }));
  add('r2', 'Losartana 50 mg · 1 comprimido', 'medicacao', as(9, 30));
  add('r5', 'Metformina 500 mg · 1 comprimido', 'medicacao', as(12, 0));

  // Dois registros já existentes no café da manhã.
  const registros = {
    o1: { resultado: 'executada', ocorridoEm: as(8, 5), registradoEm: as(8, 7), executor: 'f2', ajudante: null, justificativa: null, observacao: null, idem: 'seed-1' },
    o2: { resultado: 'recusada', ocorridoEm: as(8, 10), registradoEm: as(8, 12), executor: 'f2', ajudante: null, justificativa: 'Disse estar sem fome; aceitou suco.', observacao: null, idem: 'seed-2' },
  };

  const herdada = itens.find((i) => i.herdada);
  const passagemRecebida = {
    id: 'p1',
    turno: 'Noite 19–07',
    area: 'Ala B',
    entreguePor: 'f4',
    entregueEm: as(7, 5),
    situacao: 'entregue',
    pendencias: [
      { itemId: herdada.id, texto: 'Sem registro no turno anterior', residenteId: 'r3', responsavel: 'Turno da manhã · Ala B', prazo: 'até 10:00' },
    ],
    intercorrencias: [
      { residenteId: 'r4', texto: 'Queda sem lesão aparente', quando: '03:40', detalhe: 'Gravidade moderada · em observação', responsavel: 'Carla Mendes (téc. de enfermagem)', prazo: 'reavaliar até 10:00' },
    ],
    ausencias: [{ residenteId: 'r6', texto: 'Consulta externa · retorno previsto 11:00' }],
    notas: [{ categoria: 'Alimentação', texto: 'Maria Aparecida recusou a ceia; oferecer lanche reforçado no café.' }],
  };

  window.PROTO_DATA = { relogio, agora: inicioSimulado, equipe, residentes, itens, registros, passagemRecebida };
})();
