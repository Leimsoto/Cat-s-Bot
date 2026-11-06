import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    rules: {
      // El dashboard usa efectos para cargar datos remotos en casi todos los
      // paneles. Las reglas nuevas del React Compiler son útiles como señal,
      // pero romperían el lint por deuda existente sin afectar el build.
      'react-hooks/set-state-in-effect': 'warn',
      'react-hooks/purity': 'warn',
      // Varios módulos exportan helpers reutilizables junto a componentes
      // (MessageEditor, SaveBarContext, icons). Mantenerlo como warning evita
      // bloquear checks por una restricción de Fast Refresh de desarrollo.
      'react-refresh/only-export-components': 'warn',
    },
  },
])
