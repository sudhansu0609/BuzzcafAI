# Publishing Department Guide (`PublishingDepartment.md`)

**Department Name**: Publishing Department  
**Python Module**: `backend/app/departments/publishing.py`  
**Department Manager**: PublishingManager  
**Agent Count**: 7 Specialized Agents  

---

## 1. Overview & Department Mission

The **Publishing Department** manages video metadata, SEO keyword optimization, CTR thumbnail concepts, YouTube API uploads, publication timing schedules, and community engagement posts.

---

## 2. Department Hierarchy & Agent Roster

```text
Publishing Department
├── PublishingManager ....... Publishing Operations Lead [Manager]
├── SEOSpecialist ........... Search Engine & Algorithm Optimizer
├── MetadataOptimizer ....... Title, Description & Tag Generator
├── ThumbnailSpecialist ..... Thumbnail Concept & CTR Visual Specialist
├── UploadManager ........... YouTube Data API Upload Operator
├── PublishingScheduleManager Release Timing & Calendar Specialist
└── CommunityPublisher ...... YouTube Community & Engagement Publisher
```

---

## 3. Agent Specifications & Prompt References

### 3.1 Publishing Manager (`PublishingManager.md`)
- **Role**: Head of Publishing
- **Mission**: Manages final metadata, thumbnail approval, upload queues, and publishing execution.
- **Specification**: [backend/prompts/agents/PublishingManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/PublishingManager.md)

### 3.2 SEO Specialist (`SEOSpecialist.md`)
- **Role**: Algorithm Optimizer
- **Mission**: Conducts keyword research, tag optimization, and search intent targeting.
- **Specification**: [backend/prompts/agents/SEOSpecialist.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/SEOSpecialist.md)

### 3.3 Metadata Optimizer (`MetadataOptimizer.md`)
- **Role**: Metadata Generator
- **Mission**: Crafts compelling video titles, detailed descriptions, chapter timestamps, and tags.
- **Specification**: [backend/prompts/agents/MetadataOptimizer.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/MetadataOptimizer.md)

### 3.4 Thumbnail Specialist (`ThumbnailSpecialist.md`)
- **Role**: CTR Designer
- **Mission**: Designs high-click-through visual concepts and text overlays for thumbnails.
- **Specification**: [backend/prompts/agents/ThumbnailSpecialist.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/ThumbnailSpecialist.md)

### 3.5 Upload Manager (`UploadManager.md`)
- **Role**: API Upload Operator
- **Mission**: Executes API uploads to YouTube, setting privacy, monetization, and playlists.
- **Specification**: [backend/prompts/agents/UploadManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/UploadManager.md)

### 3.6 Schedule Manager (`PublishingScheduleManager.md`)
- **Role**: Timing Specialist
- **Mission**: Sets optimal release times based on audience activity data.
- **Specification**: [backend/prompts/agents/PublishingScheduleManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/PublishingScheduleManager.md)

### 3.7 Community Publisher (`CommunityPublisher.md`)
- **Role**: Engagement Publisher
- **Mission**: Drafts YouTube Community posts, pinned comments, and premiere chat teasers.
- **Specification**: [backend/prompts/agents/CommunityPublisher.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/CommunityPublisher.md)

---

## 4. Python Integration Example

```python
from app.departments.publishing import PublishingDepartment

dept = PublishingDepartment()
pub_mgr = dept.manager_agent
order = pub_mgr.execute("Prepare publication order for video file: final_output.mp4")
print(order)
```
