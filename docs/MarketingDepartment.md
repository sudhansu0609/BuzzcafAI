# Marketing Department Guide (`MarketingDepartment.md`)

**Department Name**: Marketing Department  
**Python Module**: `backend/app/departments/marketing.py`  
**Department Manager**: MarketingManager  
**Agent Count**: 6 Specialized Agents  

---

## 1. Overview & Department Mission

The **Marketing Department** drives channel growth, cross-platform promotional campaigns (Instagram Reels, TikTok, Twitter/X), viral trend adaptation, subscriber newsletters, and audience demographic research.

---

## 2. Department Hierarchy & Agent Roster

```text
Marketing Department
├── MarketingManager .... Marketing Operations Lead [Manager]
├── CampaignPlanner ..... Multi-Platform Campaign Specialist
├── TrendAnalyst ........ Viral Social Trends Specialist
├── SocialMediaManager .. Social Content Creator & Short-Form Copywriter
├── NewsletterManager ... Email & Subscriber Communications Specialist
└── AudienceResearcher .. Demographic Insights & Sentiment Analyst
```

---

## 3. Agent Specifications & Prompt References

### 3.1 Marketing Manager (`MarketingManager.md`)
- **Role**: Head of Marketing
- **Mission**: Strategizes promotion campaigns across social platforms and newsletters.
- **Specification**: [backend/prompts/agents/MarketingManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/MarketingManager.md)

### 3.2 Campaign Planner (`CampaignPlanner.md`)
- **Role**: Campaign Specialist
- **Mission**: Maps multi-platform promotional schedules (Instagram Reels, Shorts, Twitter/X).
- **Specification**: [backend/prompts/agents/CampaignPlanner.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/CampaignPlanner.md)

### 3.3 Trend Analyst (`TrendAnalyst.md`)
- **Role**: Viral Trends Specialist
- **Mission**: Monitors social media platforms for viral audio tracks and trending meme formats.
- **Specification**: [backend/prompts/agents/TrendAnalyst.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/TrendAnalyst.md)

### 3.4 Social Media Manager (`SocialMediaManager.md`)
- **Role**: Social Content Creator
- **Mission**: Generates promotional posts, teasers, shorts clips, and carousel images.
- **Specification**: [backend/prompts/agents/SocialMediaManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/SocialMediaManager.md)

### 3.5 Newsletter Manager (`NewsletterManager.md`)
- **Role**: Subscriber Communications
- **Mission**: Writes channel newsletters, behind-the-scenes updates, and subscriber announcements.
- **Specification**: [backend/prompts/agents/NewsletterManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/NewsletterManager.md)

### 3.6 Audience Researcher (`AudienceResearcher.md`)
- **Role**: Audience Analyst
- **Mission**: Analyzes viewer demographics, comment sentiment, and content preferences.
- **Specification**: [backend/prompts/agents/AudienceResearcher.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/AudienceResearcher.md)

---

## 4. Python Integration Example

```python
from app.departments.marketing import MarketingDepartment

dept = MarketingDepartment()
mkt_mgr = dept.manager_agent
campaign = mkt_mgr.execute("Plan promotional campaign for Khayal 3Baje Ep 12 release")
print(campaign)
```
