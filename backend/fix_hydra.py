import re

filepath = r"B:\youtubeProjects\Buzzcaf Media\MidnightBuzz\backend\voice_env\Lib\site-packages\hydra\conf\__init__.py"
with open(filepath, "r", encoding="utf-8") as f:
    code = f.read()

# Replace any foo: Bar = Bar() with foo: Bar = field(default_factory=Bar)
# match lines like:     help: HelpConf = HelpConf()
def replace_match(match):
    indent = match.group(1)
    field_name = match.group(2)
    type_name = match.group(3)
    default_call = match.group(4)
    if type_name == default_call:
        return f"{indent}{field_name}: {type_name} = field(default_factory={type_name})"
    return match.group(0)

pattern = r"^(\s+)(\w+):\s*([A-Za-z0-9_.]+)\s*=\s*([A-Za-z0-9_.]+)\(\)"
new_code = re.sub(pattern, replace_match, code, flags=re.MULTILINE)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(new_code)

print("Hydra conf patched!")
