import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, devices } from '@playwright/test'

// E2E do fluxo crítico (#222). Banco DISPOSABLE_TEST: SQLite num diretório
// temporário fora do repositório, migrado e semeado por backend/tests/e2e_seed.py
// com os guards da suíte. Senha das contas e JWT_SECRET são gerados aqui, a cada
// execução, e só vivem no ambiente dos processos — nada vai para o repositório.
//
// O arquivo de config é avaliado de novo em cada worker; E2E_DIR no ambiente
// herdado impede um segundo seed.
const FRONTEND = path.dirname(fileURLToPath(import.meta.url))
const BACKEND = path.resolve(FRONTEND, '..', 'backend')
const PYTHON = process.env.E2E_PYTHON ?? (process.platform === 'win32' ? 'python' : 'python3')

if (!process.env.E2E_DIR) {
  process.env.E2E_DIR = mkdtempSync(path.join(tmpdir(), 'facilpi-e2e-'))
  process.env.E2E_PASSWORD = randomBytes(24).toString('base64url')
  process.env.E2E_JWT_SECRET = randomBytes(48).toString('base64url')
  execFileSync(PYTHON, ['-m', 'tests.e2e_seed', process.env.E2E_DIR], {
    cwd: BACKEND,
    stdio: 'inherit',
    env: { ...process.env, JWT_SECRET: process.env.E2E_JWT_SECRET, ENVIRONMENT: 'test' },
  })
}

const dir = process.env.E2E_DIR
const backendEnv = {
  DATABASE_URL: `sqlite+aiosqlite:///${path.join(dir, 'e2e.db').replace(/\\/g, '/')}`,
  JWT_SECRET: process.env.E2E_JWT_SECRET!,
  ENVIRONMENT: 'test',
  STORAGE_PATH: path.join(dir, 'storage'),
  UPLOAD_ROOT: path.join(dir, 'uploads'),
}

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.e2e.ts',
  // Um fluxo encadeado sobre um único banco: serial e sem paralelismo.
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    locale: 'pt-BR',
    timezoneId: 'America/Sao_Paulo',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `${PYTHON} -m uvicorn src.main:app --host 127.0.0.1 --port 8000`,
      cwd: BACKEND,
      url: 'http://127.0.0.1:8000/api/health',
      env: backendEnv,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --strictPort',
      cwd: FRONTEND,
      url: 'http://127.0.0.1:5173',
      // Mesmo host nas duas pontas: no Windows `localhost` pode resolver para ::1.
      env: { VITE_API_BASE_URL: 'http://127.0.0.1:8000/api' },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
})
