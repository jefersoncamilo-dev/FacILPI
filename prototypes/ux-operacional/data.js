// Dados 100% sintéticos. Nomes fictícios; nenhuma relação com pessoas reais.
// Horários são gerados relativos ao momento de abertura do protótipo.
(function () {
  const agora = new Date();
  agora.setSeconds(0, 0);
  const min = (m) => new Date(agora.getTime() + m * 60000);

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

  // origem: 'cuidado' (formulário de cuidado) | 'medicacao' (fluxo próprio, só referência)
  const itens = [];
  let seq = 1;
  const add = (residenteId, atividade, origem, prevista, extra) =>
    itens.push(Object.assign({ id: 'o' + seq++, residenteId, atividade, origem, prevista }, extra || {}));

  ['r1', 'r2', 'r3', 'r4', 'r5', 'r6'].forEach((r) => add(r, 'Café da manhã', 'cuidado', min(-10), { grupo: 'cafe' }));
  add('r3', 'Troca de fralda', 'cuidado', min(-95), { herdada: 'Noite 19–07' });
  ['r1', 'r3', 'r4'].forEach((r) => add(r, 'Troca de fralda', 'cuidado', min(-25)));
  ['r3', 'r4'].forEach((r) => add(r, 'Mudança de decúbito', 'cuidado', min(15), { grupo: 'decubito' }));
  ['r2', 'r5', 'r6'].forEach((r) => add(r, 'Hidratação', 'cuidado', min(40), { grupo: 'hidratacao' }));
  ['r1', 'r2'].forEach((r) => add(r, 'Higiene oral', 'cuidado', min(70), { grupo: 'higiene' }));
  add('r2', 'Losartana 50 mg · 1 comprimido', 'medicacao', min(-5));
  add('r5', 'Metformina 500 mg · 1 comprimido', 'medicacao', min(30));

  // Dois registros já existentes no café da manhã.
  const registros = {
    o1: { resultado: 'executada', ocorridoEm: min(-18), registradoEm: min(-16), executor: 'f2', ajudante: null, justificativa: null, observacao: null, idem: 'seed-1' },
    o2: { resultado: 'recusada', ocorridoEm: min(-15), registradoEm: min(-14), executor: 'f2', ajudante: null, justificativa: 'Disse estar sem fome; aceitou suco.', observacao: null, idem: 'seed-2' },
  };

  const herdada = itens.find((i) => i.herdada);
  const passagemRecebida = {
    id: 'p1',
    turno: 'Noite 19–07',
    area: 'Ala B',
    entreguePor: 'f4',
    entregueEm: min(-120),
    situacao: 'entregue',
    pendencias: [
      { itemId: herdada.id, texto: 'Sem registro no turno anterior', residenteId: 'r3', responsavel: 'Turno da manhã · Ala B', prazo: '09:00' },
    ],
    intercorrencias: [
      { residenteId: 'r4', texto: 'Queda sem lesão aparente às 03:40 · gravidade moderada · em observação', responsavel: 'Carla Mendes (téc. de enfermagem)', prazo: 'reavaliar até 10:00' },
    ],
    ausencias: [{ residenteId: 'r6', texto: 'Consulta externa · retorno previsto 11:00' }],
    notas: [{ categoria: 'Alimentação', texto: 'Maria Aparecida recusou a ceia; oferecer lanche reforçado no café.' }],
  };

  window.PROTO_DATA = { agora, equipe, residentes, itens, registros, passagemRecebida };
})();
