import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import { Layout } from './components/Layout'
import { PrivateRoute } from './components/PrivateRoute'
import { Login } from './pages/Login'
import { PrimeiroAcesso } from './pages/PrimeiroAcesso'
import { Register } from './pages/Register'
import { Dashboard } from './pages/Dashboard'
import { Residentes } from './pages/Residentes'
import { MeuPlantao } from './pages/MeuPlantao'
import { Placeholder } from './pages/Placeholder'
import { Equipe } from './pages/Equipe'

function Protected({ children }: { children: React.ReactNode }) {
  return <PrivateRoute><Layout>{children}</Layout></PrivateRoute>
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/primeiro-acesso" element={<PrivateRoute><PrimeiroAcesso /></PrivateRoute>} />
          <Route path="/register" element={<Register />} />
          <Route path="/" element={<Protected><Dashboard /></Protected>} />
          <Route path="/plantao" element={<Protected><MeuPlantao /></Protected>} />
          <Route path="/residentes" element={<Protected><Residentes /></Protected>} />
          <Route path="/admissoes" element={<Protected><Placeholder title="Admissões" desc="Fluxo Pré-cadastro → Triagem → Documentação → Avaliações → Contrato → Quarto → Plano → Concluída" /></Protected>} />
          <Route path="/avaliacoes" element={<Protected><Placeholder title="Avaliações" desc="Katz, Lawton, Braden, Morse — com grau de dependência e histórico" /></Protected>} />
          <Route path="/plano" element={<Protected><Placeholder title="Plano de Cuidados / PAIS" desc="Rascunho → Em revisão → Aprovado → Vigente → Encerrado, com versão e aprovações" /></Protected>} />
          <Route path="/cuidados" element={<Protected><Placeholder title="Cuidados Diários" desc="Banho, higiene, alimentação, hidratação, mobilidade — com percentuais" /></Protected>} />
          <Route path="/medicacao" element={<Protected><Placeholder title="Medicação" desc="Prescrição → Aprazamento → Administração com executor autenticado" /></Protected>} />
          <Route path="/sinais" element={<Protected><Placeholder title="Sinais Vitais" desc="Temperatura, PA, FC, FR, saturação, glicemia, peso com alertas" /></Protected>} />
          <Route path="/intercorrencias" element={<Protected><Placeholder title="Intercorrências" desc="SBAR, gravidade, providências, desfecho e evento sentinela" /></Protected>} />
          <Route path="/agenda" element={<Protected><Placeholder title="Agenda Clínica" desc="Compromissos com detecção de conflito" /></Protected>} />
          <Route path="/passagem" element={<Protected><Placeholder title="Passagem de Plantão" desc="Resumo automático do turno + pendências" /></Protected>} />
          <Route path="/quartos" element={<Protected><Placeholder title="Quartos e Leitos" desc="Mapa de ocupação com disponibilidade" /></Protected>} />
          <Route path="/equipe" element={<Protected><Equipe /></Protected>} />
          <Route path="/estoque" element={<Protected><Placeholder title="Estoque" desc="Entradas/saídas, lote, validade, saldo" /></Protected>} />
          <Route path="/financeiro" element={<Protected><Placeholder title="Financeiro" desc="Cobranças, pagamentos, inadimplência" /></Protected>} />
          <Route path="/familia" element={<Protected><Placeholder title="Portal da Família" /></Protected>} />
          <Route path="/relatorios" element={<Protected><Placeholder title="Relatórios" desc="Indicadores de adesão, atraso, recusa, ocupação" /></Protected>} />
          <Route path="/supervisao" element={<Protected><Placeholder title="Supervisão" /></Protected>} />
          <Route path="/compliance" element={<Protected><Placeholder title="Compliance e Fiscalização" /></Protected>} />
          <Route path="/auditoria" element={<Protected><Placeholder title="Auditoria" desc="Logs de criação, alteração, execução com valores antes/depois" /></Protected>} />
          <Route path="/config" element={<Protected><Placeholder title="Configurações" desc="Parâmetros regulatórios com histórico" /></Protected>} />
          <Route path="/alertas" element={<Protected><Placeholder title="Alertas" /></Protected>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
