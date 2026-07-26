# Spilled Coffee AI Studio: Production Deployment Guide (`DEPLOYMENT.md`)

**Version**: 1.0.0  
**Target Environment**: Linux / Windows / Docker Container Runtime  

---

## 1. Environment Prerequisites

- **Python**: Version 3.10+ (Recommended Python 3.12/3.14)
- **Node.js**: Version 18+ (For React/Vite Frontend)
- **Docker & Docker Compose**: Installed for containerized deployment
- **Redis**: Background queue broker (Optional for standalone local mode)

---

## 2. Docker Compose Deployment

The repository includes `docker-compose.yml` for unified multi-container deployment:

```yaml
version: "3.8"

services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    env_file:
      - ./backend/.env
    volumes:
      - ./backend/prompts:/app/prompts
      - ./backend/projects:/app/projects
    depends_on:
      - redis

  frontend:
    build: ./frontend
    ports:
      - "3000:80"
    depends_on:
      - backend

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
```

### Launch Command:
```bash
docker-compose up -d --build
```

---

## 3. Manual Local Installation

### Backend Setup:
```powershell
cd b:\youtubeProjects\Buzzcaf Media\SpilledCoffeeAI\backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend Setup:
```powershell
cd b:\youtubeProjects\Buzzcaf Media\SpilledCoffeeAI\frontend
npm install
npm run dev
```

---

## 4. Production Health Checks & Diagnostics

Verify system readiness:
```bash
curl http://localhost:8000/api/v1/health
```

Expected Response:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "agent_registry_count": 79,
  "database": "connected"
}
```
