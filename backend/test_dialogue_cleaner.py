from app.services.local_llm import clean_human_dialogue

raw_test_text = """**(She throws her head back and laughs again—a slightly manic, greedy sound. She taps a rhythm on the desk with one perfectly manicured nail, looking utterly delighted by your repetition.)**

Haan bilkul! Ufffff... Kya poochh raha hai yaar? *(she winks)* Mera toh scene chal raha hai, direct dialogue suno!"""

cleaned = clean_human_dialogue(raw_test_text)

print("=== RAW LLM OUTPUT ===")
print(raw_test_text)
print("\n=== CLEANED HUMAN DIALOGUE ===")
print(cleaned)
print("==============================")
