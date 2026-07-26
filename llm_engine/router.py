from integrations.llm import LLMService

class LLMRouter:
    def __init__(self):
        self.llm = LLMService()

    def generate(self, provider: str, prompt: str, system_prompt: str = "") -> str:
        return self.llm.generate_text(system_prompt=system_prompt, user_prompt=prompt)
