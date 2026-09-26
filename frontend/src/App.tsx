import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import { Layout } from './components/Layout'
import { PrivateRoute } from './components/PrivateRoute'
import { Login } from './pages/Login'
import { PrimeiroAcesso } from './pages/PrimeiroAcesso'
import { Dashboard } from './pages/Dashboard'
import { Residentes } from './pages/Residentes'
import { ResidenteProntuario } from './pages/ResidenteProntuario'
import { MeuPlantao } from './pages/MeuPlantao'
import { SinaisVitais } from './pages/SinaisVitais'
import { Intercorrencias } from './pages/Intercorrencias'
import { Documentos } from './pages/Documentos'
import { Placeholder } from './pages/Placeholder'
import { Admissoes } from './pages/Admissoes'
import { AdmissaoDetalhe } from './pages/AdmissaoDetalhe'
import { QuartosLeitos } from './pages/QuartosLeitos'
import { Pais } from './pages/Pais'
import { PaisDetalhe } from './pages/PaisDetalhe'
import { ErrorBoundary } from './components/ui/states'
import { Equipe } from './pages/Equipe'
import { PlatformRoute } from './components/PlatformRoute'
import { PlatformLayout } from './components/PlatformLayout'
import { PlatformInstituicoes } from './pages/PlatformInstituicoes'
import { PlatformInstituicaoNova } from './pages/PlatformInstituicaoNova'
import { PlatformInstituicaoDetalhe } from './pages/PlatformInstituicaoDetalhe'

function Protected({ children }: { children: React.ReactNode }) {
  return <PrivateRoute><Layout>{children}</Layout></PrivateRoute>
}

/** Central FACILPI: experiência do operador da plataforma, separada da ILPI. */
function Platform({ children }: { children: React.ReactNode }) {
  return <PlatformRoute><PlatformLayout>{children}</PlatformLayout></PlatformRoute>
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <ErrorBoundary>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/primeiro-acesso" element={<PrivateRoute><PrimeiroAcesso /></PrivateRoute>} />
          <Route path="/platform" element={<Navigate to="/platform/instituicoes" replace />} />
          <Route path="/platform/instituicoes" element={<Platform><PlatformInstituicoes /></Platform>} />
          <Route path="/platform/instituicoes/nova" element={<Platform><PlatformInstituicaoNova /></Platform>} />
          <Route path="/platform/instituicoes/:id" element={<Platform><PlatformInstituicaoDetalhe /></Platform>} />
          <Route path="/" element={<Protected><Dashboard /></Protected>} />
          <Route path="/plantao" element={<Protected><MeuPlantao /></Protected>} />
          <Route path="/residentes" element={<Protected><Residentes /></Protected>} />
          <Route path="/residentes/:id" element={<Protected><ResidenteProntuario /></Protected>} />
          <Route path="/admissoes" element={<Protected><Admissoes /></Protected>} />
          <Route path="/admissoes/:id" element={<Protected><AdmissaoDetalhe /></Protected>} />
          <Route path="/avaliacoes" element={<Protected><Placeholder title="Avaliações" emConstrucao /></Protected>} />
          <Route path="/plano" element={<Protected><Pais /></Protected>} />
          <Route path="/plano/:id" element={<Protected><PaisDetalhe /></Protected>} />
          <Route path="/cuidados" element={<Protected><Placeholder title="Cuidados Diários" /></Protected>} />
          <Route path="/medicacao" element={<Protected><Placeholder title="Medicação" /></Protected>} />
          <Route path="/sinais" element={<Protected><SinaisVitais /></Protected>} />
          <Route path="/intercorrencias" element={<Protected><Intercorrencias /></Protected>} />
          <Route path="/documentos" element={<Protected><Documentos /></Protected>} />
          <Route path="/agenda" element={<Protected><Placeholder title="Agenda Clínica" /></Protected>} />
          <Route path="/passagem" element={<Protected><Placeholder title="Passagem de Plantão" emConstrucao /></Protected>} />
          <Route path="/quartos" element={<Protected><QuartosLeitos /></Protected>} />
          <Route path="/equipe" element={<Protected><Equipe /></Protected>} />
          <Route path="/estoque" element={<Protected><Placeholder title="Estoque" /></Protected>} />
          <Route path="/financeiro" element={<Protected><Placeholder title="Financeiro" /></Protected>} />
          <Route path="/familia" element={<Protected><Placeholder title="Portal da Família" /></Protected>} />
          <Route path="/relatorios" element={<Protected><Placeholder title="Relatórios" /></Protected>} />
          <Route path="/supervisao" element={<Protected><Placeholder title="Supervisão" /></Protected>} />
          <Route path="/compliance" element={<Protected><Placeholder title="Compliance e Fiscalização" /></Protected>} />
          <Route path="/auditoria" element={<Protected><Placeholder title="Auditoria" /></Protected>} />
          <Route path="/config" element={<Protected><Placeholder title="Configurações" /></Protected>} />
          <Route path="/alertas" element={<Protected><Placeholder title="Alertas" /></Protected>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        </ErrorBoundary>
      </BrowserRouter>
    </AuthProvider>
  )
}
