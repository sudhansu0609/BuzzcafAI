import sys
import importlib.abc
import importlib.machinery
import re

class FairseqPatcher(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "fairseq.dataclass.configs" or fullname == "hydra.conf":
            # Let the default machinery find the spec
            for finder in sys.meta_path:
                if finder is self: continue
                if hasattr(finder, 'find_spec'):
                    spec = finder.find_spec(fullname, path, target)
                    if spec:
                        # We will wrap the loader to modify source
                        original_loader = spec.loader
                        class PatchingLoader(importlib.abc.Loader):
                            def create_module(self, spec):
                                return original_loader.create_module(spec) if hasattr(original_loader, 'create_module') else None
                            
                            def exec_module(self, module):
                                source = original_loader.get_source(fullname)
                                if fullname == "fairseq.dataclass.configs":
                                    source = "from dataclasses import field\n" + source
                                    source = re.sub(r'(\w+):\s*([A-Za-z0-9_]+)\s*=\s*\2\(\)', r'\1: \2 = field(default_factory=\2)', source)
                                elif fullname == "hydra.conf":
                                    source = "from dataclasses import field\n" + source
                                    source = re.sub(r'(\w+):\s*([A-Za-z0-9_.]+(?:\[.*?\])?)\s*=\s*([A-Za-z0-9_.]+)\(\)', r'\1: \2 = field(default_factory=\3)', source)
                                
                                code = compile(source, spec.origin, 'exec')
                                exec(code, module.__dict__)
                        
                        spec.loader = PatchingLoader()
                        return spec
        return None

sys.meta_path.insert(0, FairseqPatcher())

try:
    import rvc_python
    print("SUCCESS: rvc_python imported!")
except Exception as e:
    print(f"FAILED: {e}")
