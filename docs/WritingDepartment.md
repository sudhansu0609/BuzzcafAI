# Writing Department Guide (`WritingDepartment.md`)

**Department Name**: Writing Department  
**Python Module**: `backend/app/departments/writing.py`  
**Department Manager**: Editor  
**Agent Count**: 8 Specialized Agents  

---

## 1. Overview & Department Mission

The **Writing Department** transforms raw research briefs into high-retention video narration scripts, structured section outlines, horror/mythology specialized story beats, character dialogues, and polished prose.

---

## 2. Department Hierarchy & Agent Roster

```text
Writing Department
├── Editor ................ Copy Editor & Department Lead [Manager]
├── StoryPlanner .......... Narrative Architect & Hook Planner
├── OutlineWriter ......... Timestamped Section Outline Specialist
├── ScriptWriter .......... Master Narration Script Writer
├── DialogueWriter ........ Character Voice & Dialogue Specialist
├── HorrorSpecialist ...... Suspense & Psychological Dread Specialist
├── MythologySpecialist ... Historical & Mythological Lore Specialist
└── Reviewer .............. Script Quality Assurance Reviewer
```

---

## 3. Agent Specifications & Prompt References

### 3.1 Story Planner (`StoryPlanner.md`)
- **Role**: Narrative Architect
- **Mission**: Maps story arcs, opening hooks, tension curves, and pacing structures.
- **Specification**: [backend/prompts/agents/StoryPlanner.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/StoryPlanner.md)

### 3.2 Outline Writer (`OutlineWriter.md`)
- **Role**: Outline Specialist
- **Mission**: Generates timestamped section outlines with word count budgets and visual markers.
- **Specification**: [backend/prompts/agents/OutlineWriter.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/OutlineWriter.md)

### 3.3 Script Writer (`ScriptWriter.md`)
- **Role**: Master Script Writer
- **Mission**: Writes full voiceover narration drafts aligned with channel voice and style guides.
- **Specification**: [backend/prompts/agents/ScriptWriter.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/ScriptWriter.md)

### 3.4 Dialogue Writer (`DialogueWriter.md`)
- **Role**: Dialogue Specialist
- **Mission**: Crafts natural character voiceover dialogue and multi-speaker interactions.
- **Specification**: [backend/prompts/agents/DialogueWriter.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/DialogueWriter.md)

### 3.5 Horror Specialist (`HorrorSpecialist.md`)
- **Role**: Horror & Suspense Specialist
- **Mission**: Infuses psychological dread, unsettling ambiance, and tension hooks into horror scripts (e.g. Beyond3Baje).
- **Specification**: [backend/prompts/agents/HorrorSpecialist.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/HorrorSpecialist.md)

### 3.6 Mythology Specialist (`MythologySpecialist.md`)
- **Role**: Mythology Specialist
- **Mission**: Ensures historical accuracy and rich narrative depth for mythology scripts (e.g. Khayal3Baje).
- **Specification**: [backend/prompts/agents/MythologySpecialist.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/MythologySpecialist.md)

### 3.7 Editor (`Editor.md`)
- **Role**: Copy Editor & Prose Refiner
- **Mission**: Polishes grammar, flow, clarity, tone consistency, and sentence rhythm.
- **Specification**: [backend/prompts/agents/Editor.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/Editor.md)

### 3.8 Reviewer (`Reviewer.md`)
- **Role**: Script QA Reviewer
- **Mission**: Conducts final script review against channel brand guidelines and quality checklists.
- **Specification**: [backend/prompts/agents/Reviewer.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/Reviewer.md)

---

## 4. Python Integration Example

```python
from app.departments.writing import WritingDepartment

dept = WritingDepartment()
editor = dept.manager_agent
edited_script = editor.execute("Refine grammar and voiceover pacing for script draft")
print(edited_script)
```
