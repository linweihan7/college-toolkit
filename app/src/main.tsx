import React from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { initSync } from './state/sync';
import './styles.css';

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// Kick off optional cloud sync after paint; no-ops unless a Supabase connection
// is configured, so it never blocks or breaks the logged-out app.
void initSync();

