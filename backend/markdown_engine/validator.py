
class SpecificationValidator:
    REQUIRED=('name','kind')
    def validate(self,spec):
        missing=[k for k in self.REQUIRED if not spec.metadata.get(k)]
        return missing
