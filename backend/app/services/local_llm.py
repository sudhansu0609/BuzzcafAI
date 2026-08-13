import requests
import re
import json
from typing import List, Dict, Any, Optional, Generator

LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
OLLAMA_BASE_URL = "http://localhost:11434"

def clean_human_dialogue(text: str) -> str:
    if not text:
        return ""
    # Remove text inside parentheses, e.g. (She throws her head back and laughs...)
    cleaned = re.sub(r'\(.*?\)', '', text, flags=re.DOTALL)
    # Remove text inside asterisks, e.g. *laughs*, **(giggles)**
    cleaned = re.sub(r'\*+.*?\*+', '', cleaned, flags=re.DOTALL)
    # Remove text inside square brackets, e.g. [sighs]
    cleaned = re.sub(r'\[.*?\]', '', cleaned, flags=re.DOTALL)
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    result = " ".join(lines).strip()
    return result if result else text.strip()

def _is_chat_model(model_id: str, item: Dict[str, Any]) -> bool:
    """Exclude embedding/reranker models from the chat model picker.

    LM Studio's native /api/v0/models reports a "type" ("llm" / "embeddings" /
    "vlm"); the OpenAI-compatible /v1/models does not, so fall back to the name.
    """
    m_type = (item.get("type") or "").lower()
    if m_type in ("embeddings", "embedding"):
        return False
    lowered = model_id.lower()
    return not any(tag in lowered for tag in ("embed", "reranker", "-rerank"))


class LocalLLMService:
    @staticmethod
    def get_available_models() -> Dict[str, Any]:
        """Fetch available models from connected local engines (LM Studio / Ollama)."""
        models = []
        lm_studio_online = False
        ollama_online = False

        # Check LM Studio (OpenAI Compatible & Native API)
        lm_urls = [
            f"{LM_STUDIO_BASE_URL}/models",
            "http://localhost:1234/api/v0/models"
        ]
        for url in lm_urls:
            if lm_studio_online and models:
                break
            try:
                res = requests.get(url, timeout=5.0)
                if res.status_code == 200:
                    data = res.json()
                    raw_models = data.get("data", [])
                    if raw_models:
                        lm_studio_online = True
                        for item in raw_models:
                            m_id = item.get("id")
                            if m_id and _is_chat_model(m_id, item) and not any(m["id"] == m_id for m in models):
                                models.append({
                                    "id": m_id,
                                    "name": m_id,
                                    "provider": "LM Studio",
                                    "online": True
                                })
            except Exception:
                pass

        # Check Ollama
        try:
            res = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3.0)
            if res.status_code == 200:
                ollama_online = True
                data = res.json()
                for item in data.get("models", []):
                    m_name = item.get("name")
                    if m_name and not any(m["id"] == m_name for m in models):
                        models.append({
                            "id": m_name,
                            "name": m_name,
                            "provider": "Ollama",
                            "online": True
                        })
        except Exception:
            pass

        # Fallback presets if engines offline
        if not models:
            models = [
                {"id": "gemma-4-e4b-it-obliterated", "name": "Gemma 4 E4B (LM Studio)", "provider": "LM Studio Preset", "online": False},
                {"id": "google/gemma-4-12b-qat", "name": "Google Gemma 4 12B QAT", "provider": "LM Studio Preset", "online": False},
                {"id": "gemma-4-12b-coder-fable5-composer2.5-v1", "name": "Gemma 4 12B Coder", "provider": "LM Studio Preset", "online": False},
                {"id": "qwen3.6-27b-fable-fusion-711-uncensored-heretic-nm-dau-neo-max-mtp", "name": "Qwen 3.6 27B Fable Fusion", "provider": "LM Studio Preset", "online": False},
                {"id": "rombos-llm-v2.6-qwen-14b", "name": "Rombos LLM v2.6 Qwen 14B", "provider": "LM Studio Preset", "online": False},
                {"id": "qwen/qwen3-coder-30b", "name": "Qwen 3 Coder 30B", "provider": "LM Studio Preset", "online": False},
                {"id": "devstral-small-2-24b-instruct-2512", "name": "Devstral Small 24B", "provider": "LM Studio Preset", "online": False},
                {"id": "qwen/qwen3.5-9b", "name": "Qwen 3.5 9B", "provider": "LM Studio Preset", "online": False},
                {"id": "llama3.3:70b", "name": "Llama 3.3 (70B Instruct)", "provider": "Ollama / Base LLM", "online": False},
                {"id": "llama3.2:3b", "name": "Llama 3.2 (3B Chat)", "provider": "Ollama / Base LLM", "online": False},
                {"id": "deepseek-r1:70b", "name": "DeepSeek R1 (70B Reasoning)", "provider": "Ollama / Base LLM", "online": False},
                {"id": "deepseek-r1:8b", "name": "DeepSeek R1 (8B Reasoning)", "provider": "Ollama / Base LLM", "online": False},
                {"id": "gpt-4o", "name": "GPT-4o (OpenAI Cloud)", "provider": "OpenAI / Cloud", "online": False},
                {"id": "claude-3.5-sonnet", "name": "Claude 3.5 Sonnet", "provider": "Anthropic / Cloud", "online": False},
                {"id": "gemini-1.5-flash", "name": "Gemini 1.5 Flash", "provider": "Google / Cloud", "online": False}
            ]

        return {
            "lmStudioOnline": lm_studio_online,
            "ollamaOnline": ollama_online,
            "models": models
        }

    @staticmethod
    def generate_chat_response(
        system_prompt: str,
        user_message: str,
        chat_history: List[Dict[str, str]],
        model_name: str = "llama3.3:70b",
        temperature: float = 0.7,
        top_p: float = 0.9,
        max_tokens: int = 1024
    ) -> str:
        """Query local LLM via LM Studio or Ollama OpenAI API standard."""

        STRICT_DIRECT_DIALOGUE_RULE = (
            "\n\n[CRITICAL RULE FOR DIALOGUE & INTONATION]:\n"
            "1. Speak ONLY in direct human spoken dialogue. DO NOT include any stage directions, physical actions, sound descriptions, "
            "narration, or roleplay actions inside parentheses, brackets, or asterisks (e.g. NEVER write *(laughs)*, *(she sighs)*, or **(action)**).\n"
            "2. Write with rich, expressive human speech punctuation! Use exclamations (!), question marks (?), commas (,), and natural breath pauses (...) "
            "so your voice has natural emotional inflections, excitement, warmth, and realistic conversational cadence.\n"
            "3. Use natural conversational interjections ('Uff!', 'Achaa...', 'Haan!', 'Arey!') naturally in speech."
        )
        full_system_prompt = system_prompt + STRICT_DIRECT_DIALOGUE_RULE
        messages = [{"role": "system", "content": full_system_prompt}]
        for msg in chat_history[-6:]:
            raw_role = str(msg.get("role", "user")).lower()
            if raw_role in ["assistant", "agent", "bot", "model"]:
                role = "assistant"
            elif raw_role in ["user", "human"]:
                role = "user"
            elif raw_role in ["system", "tool"]:
                role = raw_role
            else:
                role = "user"
        # Append user message — if system prompt mandates Devanagari Hindi, append a strict instruction to user turn
        final_user_msg = user_message
        if any(kw in full_system_prompt for kw in ["देवनागरी", "Devanagari", "Hindi Devanagari"]):
            final_user_msg += "\n\n[STRICT RULE: Write your ENTIRE response strictly in Devanagari Hindi script (हिंदी देवनागरी लिपि) ONLY. Do NOT use English/Roman alphabet or Hinglish.]"

        messages.append({"role": "user", "content": final_user_msg})

        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max(max_tokens, 2048)
        }

        # 1. Try LM Studio (Port 1234)
        try:
            target_model = model_name
            models_res = requests.get(f"{LM_STUDIO_BASE_URL}/models", timeout=2.0)
            if models_res.status_code == 200:
                l_models = [m.get("id") for m in models_res.json().get("data", []) if m.get("id")]
                if l_models:
                    # If target model is not in LM Studio, automatically use the active loaded model
                    if target_model not in l_models:
                        target_model = l_models[0]

            payload["model"] = target_model
            res = requests.post(f"{LM_STUDIO_BASE_URL}/chat/completions", json=payload, timeout=90.0)
            if res.status_code == 200:
                data = res.json()
                msg = data["choices"][0]["message"]
                content = msg.get("content", "").strip()
                reasoning = msg.get("reasoning_content", "").strip()
                
                # Combine or use reasoning content if content is empty
                if not content and reasoning:
                    content = reasoning
                elif reasoning and content and len(content) < 20:
                    content = f"{reasoning}\n\n{content}"
                
                if content:
                    cleaned_output = clean_human_dialogue(content)
                    print(f"[LocalLLM] [SUCCESS] LM Studio responded using active model '{target_model}' ({len(cleaned_output)} chars)")
                    return cleaned_output

            # Retry with empty model string (LM Studio default loaded model mode)
            payload["model"] = ""
            res2 = requests.post(f"{LM_STUDIO_BASE_URL}/chat/completions", json=payload, timeout=90.0)
            if res2.status_code == 200:
                data2 = res2.json()
                msg2 = data2["choices"][0]["message"]
                content2 = msg2.get("content", "").strip()
                reasoning2 = msg2.get("reasoning_content", "").strip()
                
                if not content2 and reasoning2:
                    content2 = reasoning2
                elif reasoning2 and content2 and len(content2) < 20:
                    content2 = f"{reasoning2}\n\n{content2}"
                
                if content2:
                    cleaned2 = clean_human_dialogue(content2)
                    print(f"[LocalLLM] [SUCCESS] LM Studio responded via default loaded model ({len(cleaned2)} chars)")
                    return cleaned2
                else:
                    err_msg = res.text[:200]
                    print(f"[LocalLLM] LM Studio returned status {res.status_code}: {err_msg}")
        except Exception as e:
            print(f"[LocalLLM] LM Studio notice: {e}")

        # 2. Try Ollama OpenAI endpoint (Port 11434)
        try:
            res = requests.post(f"{OLLAMA_BASE_URL}/v1/chat/completions", json=payload, timeout=90.0)
            if res.status_code == 200:
                data = res.json()
                content = data["choices"][0]["message"]["content"]
                cleaned_ol = clean_human_dialogue(content)
                print(f"[LocalLLM] [SUCCESS] Ollama responded using model '{model_name}'")
                return cleaned_ol
        except Exception as e:
            print(f"[LocalLLM] Ollama notice: {e}")

        # If local engines are offline or error out, return an informative error message (no fake hardcoded text)
        return "[Local LLM Engine Error]: No active response from LM Studio (port 1234) or Ollama (port 11434). Please ensure your model is loaded in LM Studio."

    def stream_chat(self, messages: List[Dict[str, str]], model_name: str = "gpt-4"):
        """Stream tokens from LM Studio. Yields (token, accumulated_text) tuples.
        Also yields complete sentences as they form for parallel TTS."""
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": 0.7,
            "stream": True
        }
        
        import re as _re

        accumulated = ""
        buffer = ""       # partial sentence still being typed
        pending = ""      # complete sentences waiting to become a TTS chunk
        first_chunk = True

        # XTTS renders a 60-200 character line fluently, but rambles or mumbles
        # on short fragments — measured over-generation of 1.5-2.7x the expected
        # duration for lines under 25 chars, against 0.6-0.8x for full lines. So
        # whole sentences are grouped into a chunk before being handed to TTS
        # instead of every "Haan!" getting its own synthesis pass. The first
        # chunk is allowed to be smaller to keep time-to-first-audio down.
        FIRST_CHUNK_MIN = 45
        CHUNK_MIN = 90
        CHUNK_MAX = 220

        def take_chunk(final: bool) -> str:
            """Pop the next TTS chunk off `pending`, or '' to let it keep growing."""
            nonlocal pending, first_chunk
            text = pending.strip()
            if not text:
                pending = ""
                return ""
            if not final and len(text) < (FIRST_CHUNK_MIN if first_chunk else CHUNK_MIN):
                return ""
            if len(text) > CHUNK_MAX:
                cut = text.rfind(' ', 0, CHUNK_MAX)
                if cut <= 0:
                    cut = CHUNK_MAX
                chunk, pending = text[:cut].strip(), text[cut:].strip()
            else:
                chunk, pending = text, ""
            first_chunk = False
            return chunk

        try:
            response = requests.post(
                f"{LM_STUDIO_BASE_URL}/chat/completions",
                json=payload,
                timeout=90.0,
                stream=True
            )

            if response.status_code == 200:
                for line in response.iter_lines():
                    if not line:
                        continue

                    line_str = line.decode('utf-8')
                    if line_str.startswith('data: '):
                        data_str = line_str[6:]
                        if data_str == '[DONE]':
                            # Flush whatever is left, including a trailing
                            # fragment with no closing punctuation.
                            leftover = clean_human_dialogue(buffer).strip()
                            if leftover:
                                pending = f"{pending} {leftover}".strip()
                            buffer = ""
                            while True:
                                chunk = take_chunk(final=True)
                                if not chunk:
                                    break
                                yield "SENTENCE", chunk
                            yield "DONE", accumulated
                            return

                        try:
                            data = json.loads(data_str)
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")

                            if content:
                                accumulated += content
                                buffer += content
                                yield "TOKEN", content

                                # Split on sentence-ending punctuation while keeping the delimiter
                                sentence_parts = _re.split(r'(?<=[.!?\n।])', buffer)
                                if len(sentence_parts) > 1:
                                    # All parts except the last are complete
                                    # sentences. Append them in order — the old
                                    # code prepended short ones onto the
                                    # remainder, which reversed them and made
                                    # the agent speak clauses out of sequence.
                                    for part in sentence_parts[:-1]:
                                        cleaned_sentence = clean_human_dialogue(part).strip()
                                        if cleaned_sentence:
                                            pending = f"{pending} {cleaned_sentence}".strip()
                                    buffer = sentence_parts[-1]
                                    while True:
                                        chunk = take_chunk(final=False)
                                        if not chunk:
                                            break
                                        yield "SENTENCE", chunk
                        except json.JSONDecodeError:
                            continue

        except Exception as e:
            print(f"[LocalLLM] Streaming error: {e}")
            yield "ERROR", f"Streaming failed: {e}"
