
class SpecificationRegistry:
    def __init__(self):
        self._specs={}
    def register(self,spec):
        self._specs[spec.name]=spec
    def get(self,name):
        return self._specs.get(name)
