/**
 * Browser entry point.
 *
 * Kept deliberately thin: mount React and nothing else. All application state
 * lives in `App` and its hooks.
 */

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App'
import './index.css'

const container = document.getElementById('root')

if (container === null) {
  throw new Error('Root element #root is missing from index.html.')
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
