import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import tseslint from 'typescript-eslint'

// QA-01: lint mínimo e honesto — regras que pegam defeito real (hooks, código
// morto, erros de JS/TS). Estilo fica de fora de propósito.
export default tseslint.config(
  { ignores: ['dist', 'coverage', 'node_modules'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { ecmaVersion: 2022, globals: globals.browser },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      // ~30 `any` em produção (quase todos `catch (e: any)`): aviso visível,
      // sem bloquear o CI até a limpeza dedicada.
      '@typescript-eslint/no-explicit-any': 'warn',
    },
  },
  {
    // Mocks de teste usam `as any` e guardam `this` (instância do mock) de propósito.
    files: ['src/__tests__/**', '**/*.test.{ts,tsx}'],
    rules: { '@typescript-eslint/no-explicit-any': 'off', '@typescript-eslint/no-this-alias': 'off' },
  },
)
