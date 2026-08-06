import ChatTTS
import torch
import soundfile as sf

print("=== TESTING CHATTTS HIGH EMOTION LOCAL ENGINE ===")
chat = ChatTTS.Chat()
chat.load(source='huggingface', compile=False)

text = "Uff! [laughter] Achaa, suno... Aaj ka din toh [laugh_0] bahut mast hone wala hai!"
params_infer_code = ChatTTS.Chat.InferCodeParams(
    prompt='[choice_0]',
)
params_refine_text = ChatTTS.Chat.RefineTextParams(
    prompt='[oral_2][laugh_2]',
)

wavs = chat.infer([text], params_refine_text=params_refine_text, params_infer_code=params_infer_code)
if wavs and len(wavs) > 0:
    sf.write("temp_chattts_test.wav", wavs[0], 24000)
    print("=== CHATTTS LOCAL HIGH EMOTION AUDIO GENERATED ===", len(wavs[0]))
