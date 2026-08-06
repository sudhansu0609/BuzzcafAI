# MidnightBuzz - Cloudflare Tunnel & Custom Domain Setup Guide

This document records the complete, step-by-step procedure for exposing **MidnightBuzz** and related local applications (`localhost:3005`) to the internet securely via **Cloudflare Named Tunnels** on your custom domain (**`midnightbuzz.buzzcaf.com`**).

---

## 1. Overview & Architecture

```
┌──────────────────────────────────────┐
│        Local PC (Windows)            │
│  Vite Server: http://127.0.0.1:3005  │
│  FastAPI API:  http://127.0.0.1:8095  │
└──────────────────┬───────────────────┘
                   │  (Encrypted QUIC Tunnel Connection)
                   ▼
┌──────────────────────────────────────┐
│      Cloudflare Edge Network         │
│  • Automatic Free Wildcard SSL       │
│  • Enterprise DDoS Protection        │
│  • Host Header Rewriting             │
└──────────────────┬───────────────────┘
                   │  (HTTPS)
                   ▼
      https://midnightbuzz.buzzcaf.com
```

---

## 2. Phase 1: Adding Domain to Cloudflare

1. Log into **[dash.cloudflare.com](https://dash.cloudflare.com/)**.
2. Click **Add a site** -> Type `buzzcaf.com` -> Select the **Free Plan ($0/mo)**.
3. Cloudflare will provide 2 Custom Nameservers:
   - `jonah.ns.cloudflare.com`
   - `joyce.ns.cloudflare.com`

---

## 3. Phase 2: Updating Squarespace DNS Nameservers

1. Log into **[Squarespace Domains Dashboard](https://domains.squarespace.com/)**.
2. Select **`buzzcaf.com`** -> Click **DNS Settings**.
3. Under **Nameservers**, select **Use Custom Nameservers**.
4. Enter the 2 Cloudflare Nameservers (`jonah.ns.cloudflare.com` and `joyce.ns.cloudflare.com`) and click **Save**.

---

## 4. Phase 3: Creating the Permanent Cloudflare Tunnel

1. Open **[one.dash.cloudflare.com](https://one.dash.cloudflare.com/)** (Cloudflare Zero Trust Dashboard).
2. Go to **Networks** -> **Tunnels** -> Click **Add a Tunnel**.
3. Name your tunnel: `midnightbuzz` -> Click **Save Tunnel**.
4. Select **Windows** and copy your **Connector Token** (starts with `ey...`).
5. In **Public Hostnames**, add the application routes:

| Subdomain | Domain | Type / Protocol | URL | Description |
| :--- | :--- | :--- | :--- | :--- |
| `midnightbuzz` | `buzzcaf.com` | **HTTP** | `127.0.0.1:3005` | MidnightBuzz AI Studio & Voice Chat |
| `media` | `buzzcaf.com` | **HTTP** | `127.0.0.1:3008` | Buzzcaf Media Service |
| `ai` | `buzzcaf.com` | **HTTP** | `127.0.0.1:3000` | Buzzcaf AI Core |
| `openui` | `buzzcaf.com` | **HTTP** | `127.0.0.1:8084` | OpenWebUI Presets |

> [!IMPORTANT]  
> Always set the **Type** to **`HTTP`** (not HTTPS) because local development servers run plain HTTP.

---

## 5. Phase 4: Vite Host Header Fix (`vite.config.ts`)

Vite 4 dev servers reject incoming requests if the `Host` header does not match `localhost:3005` (causing 502 Bad Gateway / 403 Forbidden). 

We solved this permanently by adding a Host Rewrite middleware in `frontend/vite.config.ts`:

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'allow-all-hosts',
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          // Rewrites incoming Cloudflare host header to localhost:3005 for Vite
          req.headers.host = 'localhost:3005';
          next();
        });
      }
    }
  ],
  server: {
    port: 3005,
    host: '0.0.0.0',
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8095',
        changeOrigin: true,
        secure: false,
      }
    }
  }
})
```

---

## 6. Phase 5: Running the Tunnel Service on Windows

### Manual Execution (Terminal)
Run this command in Windows Command Prompt or PowerShell:

```cmd
npx --yes cloudflared tunnel run --token <YOUR_TOKEN>
```

### Automatic Windows Service Execution (Starts on PC Boot)
To make the tunnel run 24/7 in the background automatically whenever Windows turns on:

1. Open PowerShell as **Administrator**.
2. Run:
   ```powershell
   npx --yes cloudflared service install <YOUR_TOKEN>
   ```

---

## 7. Troubleshooting & Gotchas Summary

| Error / Symptom | Cause | Permanent Fix |
| :--- | :--- | :--- |
| **Error 1014: CNAME Cross-User Banned** | CNAME pointed to temporary `trycloudflare.com` with proxy ON. | Use Named Tunnel (`.cfargotunnel.com`) inside Zero Trust dashboard. |
| **502 Bad Gateway (HTTPS SSL Mismatch)** | Tunnel route set to `https://localhost:3005`. | Change route protocol to **`HTTP`** (`http://127.0.0.1:3005`). |
| **502 / 403 Host Header Rejection** | Vite rejected external domain host header. | Apply the `allow-all-hosts` middleware plugin in `vite.config.ts`. |

---

## 8. App Access Summary

* 🌐 **Production URL**: **[https://midnightbuzz.buzzcaf.com](https://midnightbuzz.buzzcaf.com)**
* 🔑 **Master Security Password**: `buzzcaf123`
* 🎙️ **Voice Models**: Natural Indian Accents (`Prabhat`, `Swara`, `Madhur`, `Neerja`, etc.)
* 🎨 **Theme**: Clean Slate & White Light Theme
