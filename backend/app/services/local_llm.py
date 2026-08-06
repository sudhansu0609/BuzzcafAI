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

class LocalLLMService:
    @staticmethod
    def get_available_models() -> Dict[str, Any]:
        """Fetch available models from connected local engines (LM Studio / Ollama)."""
        models = []
        lm_studio_online = False
        ollama_online = False

        # Check LM Studio (OpenAI Compatible)
        try:
            res = requests.get(f"{LM_STUDIO_BASE_URL}/models", timeout=1.5)
            if res.status_code == 200:
                lm_studio_online = True
                data = res.json()
                for item in data.get("data", []):
                    models.append({
                        "id": item.get("id"),
                        "name": item.get("id"),
                        "provider": "LM Studio",
                        "online": True
                    })
        except Exception:
            pass

        # Check Ollama
        try:
            res = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=1.5)
            if res.status_code == 200:
                ollama_online = True
                data = res.json()
                for item in data.get("models", []):
                    m_name = item.get("name")
                    models.append({
                        "id": m_name,
                        "name": m_name,
                        "provider": "Ollama",
                        "online": True
                    })
        except Exception:
            pass

        # Fallback presets matching Open WebUI standard base models
        if not models:
            models = [
                {"id": "llama3.3:70b", "name": "Llama 3.3 (70B Instruct)", "provider": "Ollama / Base LLM", "online": False},
                {"id": "llama3.2:3b", "name": "Llama 3.2 (3B Chat)", "provider": "Ollama / Base LLM", "online": False},
                {"id": "deepseek-r1:70b", "name": "DeepSeek R1 (70B Reasoning)", "provider": "Ollama / Base LLM", "online": False},
                {"id": "deepseek-r1:8b", "name": "DeepSeek R1 (8B Reasoning)", "provider": "Ollama / Base LLM", "online": False},
                {"id": "qwen2.5-coder:32b", "name": "Qwen 2.5 Coder (32B)", "provider": "Ollama / Base LLM", "online": False},
                {"id": "qwen2.5:72b", "name": "Qwen 2.5 (72B Instruct)", "provider": "Ollama / Base LLM", "online": False},
                {"id": "mistral-small:24b", "name": "Mistral Small (24B)", "provider": "Ollama / Base LLM", "online": False},
                {"id": "gemma2:27b", "name": "Gemma 2 (27B)", "provider": "Ollama / Base LLM", "online": False},
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
        
        accumulated = ""
        buffer = ""
        
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
                            # Final sentence from remaining buffer
                            if buffer.strip():
                                yield "SENTENCE", buffer.strip()
                                buffer = ""
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
                                
                                # Check for sentence boundary — greedily emit all complete sentences
                                MIN_SENTENCE_LEN = 12
                                # Split on sentence-ending punctuation while keeping the delimiter
                                import re as _re
                                sentence_parts = _re.split(r'(?<=[.!?\n।])', buffer)
                                if len(sentence_parts) > 1:
                                    # All parts except the last are complete sentences
                                    remainder = sentence_parts[-1]
                                    for part in sentence_parts[:-1]:
                                        cleaned_sentence = clean_human_dialogue(part)
                                        if cleaned_sentence.strip() and len(cleaned_sentence.strip()) >= MIN_SENTENCE_LEN:
                                            yield "SENTENCE", cleaned_sentence.strip()
                                        elif cleaned_sentence.strip():
                                            # Too short — prepend to remainder so it merges with next sentence
                                            remainder = cleaned_sentence + remainder
                                    buffer = remainder
                        except json.JSONDecodeError:
                            continue
            
        except Exception as e:
            print(f"[LocalLLM] Streaming error: {e}")
            yield "ERROR", f"Streaming failed: {e}"
