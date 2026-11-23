import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { installVideoSlotFetch } from './services/videoSlot';
import './styles/studio.css';

// Before the first request: a refused second video becomes the pop-up.
installVideoSlotFetch();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
