# ☕ Buzzcaf Media - Autonomous AI YouTube Channel Production & Studio Platform

An enterprise-grade, multi-agent AI production studio platform powering 5 distinct YouTube channel brands (**Beyond3Baje**, **Spilled Coffee After Dark**, **Life3Baje**, **Khayal3Baje**, and **Spilled Coffee Studio**). Driven by an autonomous 115-agent AI workforce operating across 19 specialized studio departments.

---

## 🚀 Key Features & Studio Capabilities

- **115 Autonomous AI Agents**: Structured across 19 studio departments (Executive, Research, Creative, Writing, Voice Dictation, Scriptwriting, SEO, Analytics, Production, Publishing, etc.).
- **Universal Hinglish Content Standard**: All topic discoveries, video titles, opening hooks, script outlines, full narration scripts, scene dialogues, and thumbnail concepts are generated in **Hinglish** (day-to-day conversational Hindi in Roman/English fonts).
- **Voice Dictation Studio 🎙️**: Continuous Web Speech API engine with real-time speech-to-text, auto-restart on pause, mic power toggle, voice commands (`"delete line"`, `"new line"`, `"clear canvas"`), and High Sensitivity mode.
- **Draggable & Resizable Split Canvas**: 78% default script draft canvas with vertical resizer bar and quick split ratio presets (78%, 85%, 60%).
- **AI Story & Script Completer 🚀**: Seamlessly sends dictation drafts to specialized AI writing agents (`ScriptWriter`, `WriterAgent`, `HorrorSpecialist`, `MythologySpecialist`) to expand semi-written stories into multi-act Hinglish video scripts with visual B-roll cues.
- **Topic Vault & Live Agent Chat**: Channel-scoped persistent topic discovery, bookmarked topic vault, memory logs disk sync, and instant agent dropdown switchers.

---

## 🏗️ Architecture & Stack

- **Backend**: FastAPI (Python 3.10+), PyDantic, Uvicorn, Google Gemini API 1.5 Flash / OpenAI / Local LM Studio.
- **Frontend**: React 18, TypeScript, Vite, Vanilla CSS design system (Dark Glassmorphism, 4K Responsive Layouts).
- **Memory & Storage**: Disk-persisted JSON memory logs (`MemorySystem`), local storage caching.

---

## ⚡ Getting Started

### 1. Backend Server Setup
```bash
cd backend
pip install -r requirements.txt
python main.py start-server --port 8000 --host 127.0.0.1
```
*Backend API Swagger Documentation will be available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)*

### 2. Frontend Dashboard Setup
```bash
cd frontend
npm install
npm run dev
```
*Frontend Studio Application will be live at [http://localhost:5173/](http://localhost:5173/)*

---

## 📺 Channel Brands Managed

1. **Beyond3Baje 🔍**: 100% real-world, fact-grounded documentaries, true crime, dark history, and historical engineering disasters.
2. **Spilled Coffee After Dark 🕯️**: Parapsychological folklore, 3 AM high-strangeness encounters, and regional horror archives.
3. **Life3Baje 🌿**: Reflective personal essays, creative self-experiments, and cozy atmospheric video essays.
4. **Khayal3Baje 📜**: Authentic ancient mythology, textual epic lore, and world mythologies.
5. **Spilled Coffee Studio ☕**: Story architecture, classic literature breakdowns, and original creator fiction.

---

## 📄 License

MIT License. Developed for Buzzcaf Media YouTube Production Workflows.
