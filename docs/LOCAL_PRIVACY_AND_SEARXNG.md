# Local LLMs, Privacy, and SearXNG Guide

Buzzcaf AI is built to run **100% locally on your own machine** with zero data leakage, while allowing research agents to browse the live internet and synthesize cited, verified information.

---

## 1. Strict Local Privacy Mode

When **Strict Local Privacy Mode** is enabled (default in `backend/config/config.json` and in the Settings UI):
- All agent and subagent inference runs strictly on-device through **LM Studio**, **Ollama**, or **llama.cpp**.
- External cloud APIs (Google Gemini, OpenAI) are **strictly disabled** and removed from the fallback chain.
- If all local providers are offline or out of memory, requests fail or return simulated content in test environments; **no private prompts or documents are ever uploaded to the cloud**.

---

## 2. Supported Local LLM Engines & Live Model Detection

The Settings page (`/settings`) automatically scans your active local ports and populates interactive dropdowns of models currently loaded in memory:

| Engine | Default Port & URL | How to Start |
|---|---|---|
| **LM Studio** | `http://localhost:1234/v1` | Open LM Studio, load your preferred model (e.g. `qwen3.8-flash-next`, `gemma4-12b`), and start the local server. |
| **Ollama** | `http://localhost:11434/v1` | Run `ollama run qwen3.5:9b` or `ollama serve`. |
| **llama.cpp** | `http://127.0.0.1:8089/v1` | Started by the buzzcode engine or local server on port 8089. |

### Model Tiers
- **Fast Tier** (`TagGenerator`, `TitleGenerator`, `DescriptionWriter`, `MetadataOptimizer`): Defaults to `llamacpp` or fast local models.
- **Strong Tier** (`ResearchAgent`, `WebResearcher`, `CreativeDirectorAgent`, Studio Assistant): Uses the primary local model for deep analysis and narrative flow.

---

## 3. Privacy-Preserving Web Research & SearXNG

Agents can search the web and inspect articles to verify timelines and historical facts without leaking confidential project context.

### On-Device Query Sanitization
Before any query leaves the machine, `sanitize_search_query()` strips:
- Windows and Unix filesystem paths (e.g., `C:\...`, `/home/...`).
- API keys and tokens (e.g., `sk-...`, `AIza...`, `ghp_...`).
- Code blocks, prompt directives, and internal memory references.
- Only generic search keywords are dispatched.

### Search Providers
Under **Settings > Internet Access & Web Research**, select your preferred provider:
1. **Auto (SearXNG + DuckDuckGo + Wikipedia)**: Attempts your local/self-hosted SearXNG first. If SearXNG is offline, falls back seamlessly to Wikipedia and DuckDuckGo.
2. **SearXNG**: Queries your dedicated SearXNG metasearch instance.
3. **DuckDuckGo**: Anonymous instant answer search.
4. **Wikipedia**: Encyclopedic facts and summaries.

---

## 4. Running SearXNG Locally with Docker

A pre-configured Docker Compose setup is included in the `searxng/` folder:

### Quick Start
1. Open a terminal in the `searxng/` directory:
   ```bash
   cd searxng
   docker compose up -d
   ```
2. Verify SearXNG is running at:
   ```
   http://localhost:8080
   ```
3. Test the connection:
   - Go to **Settings** in the Buzzcaf AI Studio.
   - Under **Internet Access & Web Research**, ensure the URL is `http://localhost:8080`.
   - Click the **Test Connection** button. You should see `✓ Successfully connected to SearXNG!`.

### Configuration Notes
SearXNG requires JSON format output enabled in `searxng/settings.yml` (already configured):
```yaml
search:
  formats:
    - html
    - json
```

---

## 5. Agent Web Search Directives

Agents can invoke web searches autonomously in chat or workflow steps using:
```markdown
[WEB_SEARCH: historical timeline of Bhangarh Fort 1613]
```
or fetch article text with:
```markdown
[WEB_FETCH: https://en.wikipedia.org/wiki/Bhangarh_Fort]
```
The runtime automatically executes the query, strips tracking data, and injects verified sources into the agent's context.
