from pydantic import BaseModel
class WorkflowRun(BaseModel):
 workflow:str
 project_id:str
