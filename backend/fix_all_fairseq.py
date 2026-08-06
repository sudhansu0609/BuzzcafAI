import os
import re

fairseq_dir = r"B:\youtubeProjects\Buzzcaf Media\MidnightBuzz\backend\voice_env\Lib\site-packages\fairseq"

count = 0
for root, dirs, files in os.walk(fairseq_dir):
    for f in files:
        if f.endswith(".py"):
            filepath = os.path.join(root, f)
            try:
                with open(filepath, "r", encoding="utf-8") as file:
                    content = file.read()
                
                # 1. Replace field(default=ConfigClass()) with field(default_factory=ConfigClass)
                new_content = re.sub(
                    r"field\(\s*default\s*=\s*([A-Za-z0-9_.]+)\(\)\s*(,\s*metadata=.*?)?\)",
                    r"field(default_factory=\1\2)",
                    content,
                    flags=re.DOTALL
                )

                # 2. Replace field_name: ConfigClass = ConfigClass() with field_name: ConfigClass = field(default_factory=ConfigClass)
                # EXCLUDE keywords like else, if, elif, def, class, return
                new_content = re.sub(
                    r"^([ \t]+)(?!(?:else|if|elif|def|class|return)\b)([a-zA-Z0-9_]+)\s*:\s*([A-Za-z0-9_.\[\]]+)\s*=\s*([A-Za-z0-9_.]+)\(\)\s*$",
                    r"\1\2: \3 = field(default_factory=\4)",
                    new_content,
                    flags=re.MULTILINE
                )

                if new_content != content:
                    with open(filepath, "w", encoding="utf-8") as file:
                        file.write(new_content)
                    count += 1
            except Exception as e:
                pass

print(f"Safe patch applied to {count} fairseq files!")
