# Analytics Department Guide (`AnalyticsDepartment.md`)

**Department Name**: Analytics Department  
**Python Module**: `backend/app/departments/analytics.py`  
**Department Manager**: AnalyticsManager  
**Agent Count**: 6 Specialized Agents  

---

## 1. Overview & Department Mission

The **Analytics Department** evaluates channel growth metrics, monitors video click-through rates (CTR), audits viewer retention curves, analyzes traffic sources, and delivers data-driven content recommendations to production and executive teams.

---

## 2. Department Hierarchy & Agent Roster

```text
Analytics Department
├── AnalyticsManager .... Analytics Operations Lead [Manager]
├── PerformanceAnalyst .. Video Performance & Watch-Time Specialist
├── CTRAnalyst .......... Click-Through Rate & Thumbnail A/B Test Specialist
├── RetentionAnalyst .... Audience Retention & Pacing Auditor
├── RecommendationAgent . Algorithm Recommendation Engine Specialist
└── CompetitorAnalyst ... Niche Competitor & Benchmark Analyst
```

---

## 3. Agent Specifications & Prompt References

### 3.1 Analytics Manager (`AnalyticsManager.md`)
- **Role**: Head of Analytics
- **Mission**: Synthesizes performance dashboards, channel reports, and strategic recommendations.
- **Specification**: [backend/prompts/agents/AnalyticsManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/AnalyticsManager.md)

### 3.2 Performance Analyst (`PerformanceAnalyst.md`)
- **Role**: Performance Specialist
- **Mission**: Evaluates views, watch time, revenue, and subscriber conversion rates per video.
- **Specification**: [backend/prompts/agents/PerformanceAnalyst.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/PerformanceAnalyst.md)

### 3.3 CTR Analyst (`CTRAnalyst.md`)
- **Role**: CTR Specialist
- **Mission**: Analyzes impression CTR across titles and thumbnails to recommend A/B test tweaks.
- **Specification**: [backend/prompts/agents/CTRAnalyst.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/CTRAnalyst.md)

### 3.4 Retention Analyst (`RetentionAnalyst.md`)
- **Role**: Retention Auditor
- **Mission**: Pinpoints viewer drop-off timestamps in video graphs to provide script/editing feedback.
- **Specification**: [backend/prompts/agents/RetentionAnalyst.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/RetentionAnalyst.md)

### 3.5 Recommendation Agent (`RecommendationAgent.md`)
- **Role**: Algorithm Engine Specialist
- **Mission**: Evaluates algorithmic traffic sources (Suggested Videos vs YouTube Search).
- **Specification**: [backend/prompts/agents/RecommendationAgent.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/RecommendationAgent.md)

### 3.6 Competitor Analyst (`CompetitorAnalyst.md`)
- **Role**: Niche Competitor Analyst
- **Mission**: Monitors competing channels, outlier successful videos, and content gaps.
- **Specification**: [backend/prompts/agents/CompetitorAnalyst.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/CompetitorAnalyst.md)

---

## 4. Python Integration Example

```python
from app.departments.analytics import AnalyticsDepartment

dept = AnalyticsDepartment()
ana_mgr = dept.manager_agent
report = ana_mgr.execute("Synthesize monthly channel analytics report")
print(report)
```
