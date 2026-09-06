# Production Department Guide (`ProductionDepartment.md`)

**Department Name**: Production Department  
**Python Module**: `backend/app/departments/production.py`  
**Department Manager**: ProductionManager  
**Agent Count**: 8 Specialized Agents  

---

## 1. Overview & Department Mission

The **Production Department** converts approved scripts into visual storyboards, scene timing matrices, Midjourney/Flux prompt sets, character visual consistency sheets, environment setting specs, and cataloged media asset registries.

---

## 2. Department Hierarchy & Agent Roster

```text
Production Department
├── ProductionManager ... Head of Production Department [Manager]
├── StoryboardPlanner ... Camera Framing & Shot Sequence Specialist
├── ScenePlanner ........ Audio-Visual Sync & Scene Timing Specialist
├── PromptEngineer ...... AI Image & Video Prompt Engineer (Midjourney/Flux)
├── CharacterPlanner .... Visual Character Consistency Specialist
├── EnvironmentPlanner .. World Building & Setting Visual Specialist
├── AssetManager ........ Asset Registry & Inventory Manager
└── ProductionReviewer .. Visual Asset Quality Assurance Reviewer
```

---

## 3. Agent Specifications & Prompt References

### 3.1 Production Manager (`ProductionManager.md`)
- **Role**: Head of Production
- **Mission**: Coordinates storyboard creation, prompt engineering, and visual asset production pipelines.
- **Specification**: [backend/prompts/agents/ProductionManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/ProductionManager.md)

### 3.2 Storyboard Planner (`StoryboardPlanner.md`)
- **Role**: Storyboard Specialist
- **Mission**: Breaks scripts into visual frames, shot types, camera angles, and action descriptions.
- **Specification**: [backend/prompts/agents/StoryboardPlanner.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/StoryboardPlanner.md)

### 3.3 Scene Planner (`ScenePlanner.md`)
- **Role**: Scene Timing Specialist
- **Mission**: Calculates start/end timestamps and transition effects synchronized with voiceover audio.
- **Specification**: [backend/prompts/agents/ScenePlanner.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/ScenePlanner.md)

### 3.4 Prompt Engineer (`PromptEngineer.md`)
- **Role**: AI Prompt Engineer
- **Mission**: Generates master positive and negative generative prompts for Midjourney/Flux/SD.
- **Specification**: [backend/prompts/agents/PromptEngineer.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/PromptEngineer.md)

### 3.5 Character Planner (`CharacterPlanner.md`)
- **Role**: Visual Character Consistency Specialist
- **Mission**: Maintains facial features, attire specs, and visual anchor prompts for recurring story characters.
- **Specification**: [backend/prompts/agents/CharacterPlanner.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/CharacterPlanner.md)

### 3.6 Environment Planner (`EnvironmentPlanner.md`)
- **Role**: World Building Specialist
- **Mission**: Defines background settings, atmospheric lighting, and architectural visual parameters.
- **Specification**: [backend/prompts/agents/EnvironmentPlanner.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/EnvironmentPlanner.md)

### 3.7 Asset Manager (`AssetManager.md`)
- **Role**: Asset Inventory Manager
- **Mission**: Catalogs, validates, tags, and stores generated images, audio clips, and video elements.
- **Specification**: [backend/prompts/agents/AssetManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/AssetManager.md)

### 3.8 Production Reviewer (`ProductionReviewer.md`)
- **Role**: Production QA Reviewer
- **Mission**: Inspects visual quality, resolution, prompt fidelity, and visual continuity across scenes.
- **Specification**: [backend/prompts/agents/ProductionReviewer.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/ProductionReviewer.md)

---

## 4. Python Integration Example

```python
from app.departments.production import ProductionDepartment

dept = ProductionDepartment()
prod_mgr = dept.manager_agent
prod_plan = prod_mgr.execute("Generate production plan for approved script")
print(prod_plan)
```
