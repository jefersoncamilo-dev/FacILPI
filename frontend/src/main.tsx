import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import './index.css'
import { aplicarAparencia } from './lib/aparencia'

// Tema e visual simples antes do primeiro desenho, para não piscar.
aplicarAparencia()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
