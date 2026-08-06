import sys
print("Python version:", sys.version)
try:
    import torch
    print("PyTorch version:", torch.__version__)
    from TTS.api import TTS
    print("✓ Coqui TTS loaded successfully!")
except Exception as e:
    print("Loading info:", e)
