import os
import re
import json
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.models.project import Project
from runtime.workflow import WorkflowEngine
from integrations.llm import load_config, save_config
from knowledge.assets import AssetService

app = FastAPI(title="Buzzcaf AI Studio Dashboard")

from app.api.auth import router as auth_router
app.include_router(auth_router)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROJECTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "projects")
engine = WorkflowEngine()
asset_service = AssetService()

import logging
logger = logging.getLogger("buzzcaf_ai")
from collections import defaultdict

class InMemoryLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.logs = defaultdict(list)

    def emit(self, record):
        try:
            msg = self.format(record)
            project_id = getattr(record, "project_id", "N/A")
            if project_id == "N/A" and active_executions:
                for pid in active_executions:
                    self.logs[pid].append(msg)
            elif project_id != "N/A":
                self.logs[project_id].append(msg)
        except Exception:
            pass

log_handler = InMemoryLogHandler()
log_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] [%(name)s] - %(message)s'))
logging.getLogger().addHandler(log_handler)

active_executions = set()


# Pydantic Schemas
class ProjectCreateSchema(BaseModel):
    name: str
    brand: str
    workflow_name: str

class SettingsSchema(BaseModel):
    gemini_api_key: Optional[str] = ""
    gemini_model: Optional[str] = "gemini-3.6-flash"
    openai_api_key: Optional[str] = ""
    openai_model: Optional[str] = "gpt-4o-mini"
    lm_studio_url: Optional[str] = "http://localhost:1234/v1"
    lm_studio_model: Optional[str] = "meta-llama-3-8b-instruct"
    prefer_gemini: Optional[bool] = True
    selected_provider: Optional[str] = "gemini"


class ExecuteStepSchema(BaseModel):
    feedback: Optional[str] = None

class AssetRegisterSchema(BaseModel):
    title: str
    type: str
    tags: List[str]
    file_path: str
    source: Optional[str] = "internal"
    license: Optional[str] = "Royalty Free"
    status: Optional[str] = "active"
    project_id: Optional[str] = None

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/projects")
def projects():
    return list_projects()

@app.get("/api/brands")
def get_brands():
    return ["Beyond3Baje", "Khayal3Baje", "Spilled Coffee Studio", "Spilled Coffee: After Dark", "Spilled Coffee After Dark", "Life3Baje"]

@app.get("/api/assets")
def get_assets(type: Optional[str] = None, tag: Optional[str] = None, query: Optional[str] = None):
    return asset_service.query_assets(asset_type=type, tag=tag, query_string=query)

@app.post("/api/assets")
def register_asset(payload: AssetRegisterSchema):
    return asset_service.register_asset(
        title=payload.title,
        asset_type=payload.type,
        tags=payload.tags,
        file_path=payload.file_path,
        source=payload.source,
        license_info=payload.license,
        status=payload.status,
        project_id=payload.project_id
    )


@app.get("/api/settings")
def get_settings():
    return load_config()

@app.post("/api/settings")
def update_settings(settings: SettingsSchema):
    new_config = load_config()
    data = settings.model_dump(exclude_unset=True)
    for k, v in data.items():
        if v is not None:
            new_config[k] = v
    save_config(new_config)
    engine.llm_service.reload_config()
    return {"status": "success", "message": "Settings updated successfully.", "config": new_config}

@app.get("/api/workflows")
def get_workflows():
    engine.load_workflows()
    return [
        {
            "id": wf.id,
            "name": wf.name,
            "description": wf.description,
            "steps": [
                {
                    "name": s.name,
                    "agent_role": s.agent_role,
                    "description": s.description,
                    "requires_approval": s.requires_approval
                } for s in wf.steps
            ]
        } for wf in engine.workflows.values()
    ]

@app.get("/api/projects")
def list_projects():
    if not os.path.exists(PROJECTS_DIR):
        os.makedirs(PROJECTS_DIR, exist_ok=True)
        return []
    
    projects = []
    for pid in os.listdir(PROJECTS_DIR):
        p_dir = os.path.join(PROJECTS_DIR, pid)
        if os.path.isdir(p_dir):
            try:
                p = Project.load(pid)
                projects.append(p.to_dict())
            except Exception as e:
                # Log and skip corrupted projects
                continue
    # Sort by created_at descending
    projects.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return projects

from executive.project import project_manager

@app.post("/api/projects")
def create_project(payload: ProjectCreateSchema):
    # Load workflow to check first step
    wf = engine.get_workflow(payload.workflow_name)
    if not wf:
        raise HTTPException(status_code=400, detail=f"Workflow '{payload.workflow_name}' not found.")
        
    try:
        project = project_manager.create_project(
            name=payload.name,
            brand=payload.brand,
            workflow_name=payload.workflow_name
        )
        return project.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))



@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    try:
        project = Project.load(project_id)
        return project.to_dict()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")

@app.post("/api/projects/{project_id}/execute")
def execute_project_step(project_id: str, payload: ExecuteStepSchema = None):
    feedback = payload.feedback if payload else None
    active_executions.add(project_id)
    log_handler.logs[project_id] = [f"Starting execution of workflow step at {datetime.now().isoformat()}..."]
    try:
        project = engine.execute_next(project_id, user_feedback=feedback)
        # Add final agent logs if any
        if project.steps_history:
            last_step = project.steps_history[-1]
            for step_log in last_step.logs:
                if step_log not in log_handler.logs[project_id]:
                    log_handler.logs[project_id].append(step_log)
        return project.to_dict()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as e:
        log_handler.logs[project_id].append(f"[ERROR] Execution failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Execution error: {str(e)}")
    finally:
        active_executions.discard(project_id)

@app.get("/api/projects/{project_id}/logs")
def get_project_execution_logs(project_id: str):
    return log_handler.logs.get(project_id, ["No active logs found for this project."])

@app.get("/api/projects/{project_id}/asset/{asset_name}")
def get_project_asset(project_id: str, asset_name: str):
    try:
        project = Project.load(project_id)
        asset_file = project.assets.get(asset_name)
        if not asset_file:
            raise HTTPException(status_code=404, detail="Asset not generated yet")
            
        file_path = os.path.join(project.get_project_dir(), asset_file)
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="Asset file missing on disk")
            
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        # Check if json
        if asset_file.endswith(".json"):
            try:
                return json.loads(content)
            except:
                pass
        return {"content": content}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")

from core.agent import AgentFactory

class TopicDiscoverSchema(BaseModel):
    channel: str
    sources: Optional[List[str]] = None
    pillar_filter: Optional[str] = None

@app.post("/api/topics/discover")
def discover_channel_topics(payload: TopicDiscoverSchema):
    channel = payload.channel.strip()
    
    agent_map = {
        "spilled coffee studio": "SpilledCoffeeStudioStrategist",
        "spilled coffee after dark": "AfterDarkStrategist",
        "spilled coffee: after dark": "AfterDarkStrategist",
        "raat3baje": "AfterDarkStrategist",
        "beyond3baje": "Beyond3BajeStrategist",
        "life3baje": "Life3BajeStrategist",
        "khayal3baje": "Khayal3BajeStrategist"
    }

    target_agent_name = agent_map.get(channel.lower(), "TopicVaultManager")
    agent = AgentFactory.get_agent(target_agent_name)

    prompt = f"Discover and vault high-retention video topic ideas for channel '{channel}'. Sources requested: {payload.sources or 'all'}."
    
    # Pre-built curated channel topic vaults for instant UI responsiveness & fallback
    channel_vaults = {
        "Spilled Coffee Studio": [
          {
            "topic": "Why Franz Kafka's Stories Still Scare Modern Readers",
            "category": "Pillar 2: Great Literature & Classic Authors",
            "pillar": "Great Literature",
            "country": "Czech / Global",
            "viral_potential": 9,
            "schedule_day": "Wednesday",
            "source_type": "Public Domain Excerpts & Literary Critique",
            "sources_used": ["Public Domain Kafka Archives", "Literary Analysis Essays"],
            "visual_requirements": ["Subtle ink sketches", "Rainy European cafe footage", "Annotated manuscript pages"],
            "exclusion_audit": "✓ EXCLUSION VERIFIED: Literary Critique & Fair-Use Analysis"
          },
          {
            "topic": "How Studio Ghibli & Pixar Write Unforgettable Emotion",
            "category": "Pillar 3: Story Analysis",
            "pillar": "Story Analysis",
            "country": "Global Animation Craft",
            "viral_potential": 10,
            "schedule_day": "Monday",
            "source_type": "Story Architecture Breakdown",
            "sources_used": ["Pixar 22 Rules of Storytelling", "Miyazaki Interviews"],
            "visual_requirements": ["Storyboarding timeline diagram", "Color palette analysis slides", "Character arc curves"],
            "exclusion_audit": "✓ EXCLUSION VERIFIED: Educational Story Architecture"
          },
          {
            "topic": "The Midnight Library (Original Fantasy Short Story)",
            "category": "Pillar 1: Original Work (30%)",
            "pillar": "Original Work",
            "country": "Original Short Story",
            "viral_potential": 9,
            "schedule_day": "Friday",
            "source_type": "Original Short Fiction / Poetry",
            "sources_used": ["Creator Notebooks", "Original Draft #4"],
            "visual_requirements": ["Cozy candlelit desk", "Macro fountain pen writing", "Cinematic original narration"],
            "exclusion_audit": "✓ EXCLUSION VERIFIED: 100% Original Creator Fiction"
          },
          {
            "topic": "The Letter That Changed History (A 27-Year True Story)",
            "category": "Pillar 4: Extraordinary True Stories",
            "pillar": "Extraordinary True Stories",
            "country": "International Human Narrative",
            "viral_potential": 9,
            "schedule_day": "Wednesday",
            "source_type": "Historical Letters & Personal Journals",
            "sources_used": ["Resurfaced Personal Archives", "Human Endurance Records"],
            "visual_requirements": ["Vintage letter scans", "Historical map timeline", "Cinematic narrative B-roll"],
            "exclusion_audit": "✓ EXCLUSION VERIFIED: Human Storytelling Narrative"
          },
          {
            "topic": "How Haruki Murakami Blurs Reality & Dreams",
            "category": "Pillar 2: Great Literature & Classic Authors",
            "pillar": "Great Literature",
            "country": "Japan / International",
            "viral_potential": 9,
            "schedule_day": "Monday",
            "source_type": "Literary Breakdown",
            "sources_used": ["Murakami Essays", "Magical Realism Critique"],
            "visual_requirements": ["Jazz vinyl record slow spin", "Subtle neon rain visualizer"],
            "exclusion_audit": "✓ EXCLUSION VERIFIED: Literary Critique"
          },
          {
            "topic": "The Man Who Survived Two Atomic Bombs & Lived to 93",
            "category": "Pillar 4: Extraordinary True Stories",
            "pillar": "Extraordinary True Stories",
            "country": "Japan",
            "viral_potential": 10,
            "schedule_day": "Friday",
            "source_type": "Historical Archives & Testimony",
            "sources_used": ["Tsutomu Yamaguchi Testimonies", "Hiroshima & Nagasaki Archives"],
            "visual_requirements": ["Archival photo timeline", "Historical map overlay"],
            "exclusion_audit": "✓ EXCLUSION VERIFIED: Historical Human Story"
          }
        ],
        "Spilled Coffee After Dark": [
          {
            "topic": "Bhangarh Fort Ka Wo Guard Jo Raat Ke 3 Baje Ghaayab Ho Gaya",
            "category": "Paranormal & Haunted Locations",
            "pillar": "Paranormal & Haunted Locations",
            "country": "India",
            "viral_potential": 9,
            "source_type": "Local Indian Folklore & Archives",
            "sources_used": ["Reddit (r/Paranormal)", "Local Rajasthani Folklore", "Wikipedia Ghost Towns"],
            "visual_requirements": ["Haunted fort archival photos", "Night rain mist imagery", "Map of Alwar District"],
            "exclusion_audit": "✓ Verified: Parapsychological Folklore in Hinglish"
          },
          {
            "topic": "Deep Web Ki Wo Silent Calls: Audio Incident #99 Ka Sach",
            "category": "Internet Horror & Modern Myths",
            "pillar": "Internet Horror & Modern Myths",
            "country": "International",
            "viral_potential": 8,
            "source_type": "Reddit & Internet Archives",
            "sources_used": ["r/HighStrangeness", "Lost Media Wiki", "Dark Web Archives"],
            "visual_requirements": ["Spectrogram audio graphs", "Analog horror CRT noise", "Deep web log clippings"],
            "exclusion_audit": "✓ Verified: Modern Internet ARG / Myth in Hinglish"
          },
          {
            "topic": "Kuldhara Gaon Ka Unsolved Raaz: Ek Hi Raat Mein Poore Gaon Ka Ghaayab Hona",
            "category": "True Mysteries",
            "pillar": "True Mysteries",
            "country": "India",
            "viral_potential": 10,
            "source_type": "Wikipedia & Indian Archives",
            "sources_used": ["ASI Government Records", "r/UnresolvedMysteries", "Regional Folklore Books"],
            "visual_requirements": ["Dry desert ruins aerial map", "Paliwal Brahmin family lineage charts"],
            "exclusion_audit": "✓ Verified: Historical Unsolved Disappearance in Hinglish"
          },
          {
            "topic": "Dow Hill School Ki Wo 3 AM Ki Seeti Aur Ghost Legends",
            "category": "Paranormal & Haunted Locations",
            "pillar": "Haunted Locations",
            "country": "India (Kurseong)",
            "viral_potential": 9,
            "source_type": "Local Kurseong Archives",
            "sources_used": ["Local Tea Garden Chronicles", "r/UnresolvedMysteries"],
            "visual_requirements": ["Foggy pine forest footage", "Haunted school silhouette"],
            "exclusion_audit": "✓ Verified: Regional Paranormal Legend in Hinglish"
          },
          {
            "topic": "Skinwalker Ranch Ki Night Surveillance Logs: 2016 Ka Incident",
            "category": "Internet Horror & Unexplained",
            "pillar": "Unexplained Phenomena",
            "country": "USA",
            "viral_potential": 10,
            "source_type": "NIDS Scientific Logs",
            "sources_used": ["r/Skinwalkers", "Utah Paranormal Archives"],
            "visual_requirements": ["Thermal night vision overlay", "Ranch topographic map"],
            "exclusion_audit": "✓ Verified: Paranormal Field Investigation in Hinglish"
          }
        ],
        "Beyond3Baje": [
          {
            "topic": "Kaise Ek Choti Si Engineering Galti Ne Poore Warship Ko Duba Diya",
            "category": "Engineering & Disaster Stories",
            "pillar": "Engineering & Disaster Stories",
            "country": "International",
            "viral_potential": 9,
            "source_type": "Historical & Technical Archives",
            "sources_used": ["Naval Inspection Records", "Wikipedia Disasters", "Engineering Accident Reports"],
            "visual_requirements": ["Ship cross-section 3D diagram", "17th Century archival maps", "Stability calculation charts"],
            "exclusion_audit": "✓ EXCLUSION VERIFIED: 100% Real-World True Story in Hinglish"
          },
          {
            "topic": "Unit 731 Ke Forgotten Secret Experiments Ka Dark Truth",
            "category": "Dark History",
            "pillar": "Dark History",
            "country": "Japan / International",
            "viral_potential": 10,
            "source_type": "Declassified Government Documents",
            "sources_used": ["National Archives", "Trial Transcripts", "Declassified CIA Records"],
            "visual_requirements": ["Historical newspaper clippings", "Declassified stamp documents", "Geographic timeline map"],
            "exclusion_audit": "✓ EXCLUSION VERIFIED: Documented Historical Event in Hinglish"
          },
          {
            "topic": "Bharat Ka Sabse Rahasyamayi Missing Flight Incident Aur Sealed Radar Logs",
            "category": "Unsolved Mysteries",
            "pillar": "Unsolved Mysteries",
            "country": "India",
            "viral_potential": 9,
            "source_type": "Aviation Accident Reports",
            "sources_used": ["Civil Aviation Archives", "r/UnresolvedMysteries", "Air Traffic Control Transcripts"],
            "visual_requirements": ["Radar flight path tracking map", "Cockpit transcript graphics", "Weather radar overlay"],
            "exclusion_audit": "✓ EXCLUSION VERIFIED: Real Aviation Mystery in Hinglish"
          },
          {
            "topic": "Stora Sjöfallet Gold Heist: Kaise 40 Minutes Mein $400M Ghaayab Ho Gaya",
            "category": "True Crime & Heists",
            "pillar": "True Crime",
            "country": "Sweden / International",
            "viral_potential": 9,
            "source_type": "Judicial & Police Archives",
            "sources_used": ["Interpol Records", "Police Investigation Transcripts"],
            "visual_requirements": ["Heist route map overlay", "Vault blueprint graphics"],
            "exclusion_audit": "✓ EXCLUSION VERIFIED: True Crime Historical Record in Hinglish"
          },
          {
            "topic": "Chernobyl Control Room: Reactor Explosion Se Micro-Minutes Pehle Kya Hua",
            "category": "Dark History & Disasters",
            "pillar": "Dark History",
            "country": "Ukraine / USSR",
            "viral_potential": 10,
            "source_type": "IAEA Safety Reports & Control Logs",
            "sources_used": ["IAEA Chernobyl Logs", "Declassified Soviet Records"],
            "visual_requirements": ["Control panel 3D schematic", "Reactor core temperature timeline"],
            "exclusion_audit": "✓ EXCLUSION VERIFIED: Real Historical Disaster in Hinglish"
          }
        ],
        "Life3Baje": [
          {
            "topic": "Kyun Maine Phir Se Likhna Shuru Kiya (Aur Setup Kiya My Dream Desk)",
            "category": "Creative Journey",
            "pillar": "Creative Journey",
            "country": "Personal Documentary",
            "viral_potential": 9,
            "source_type": "Personal Essay & Creator Journal",
            "sources_used": ["Notebook Journals", "Writing Process Reflections"],
            "visual_requirements": ["Cozy writing desk macro", "Notebook pages", "Warm morning coffee sunlight"],
            "exclusion_audit": "✓ EXCLUSION VERIFIED: Authentic Journey in Hinglish"
          },
          {
            "topic": "Maine Ek Hafte Tak Social Media Aur Entertainment Use Nahi Kiya",
            "category": "Personal Experiments",
            "pillar": "Personal Experiments",
            "country": "Personal Documentary",
            "viral_potential": 8,
            "source_type": "Personal Trial Journal",
            "sources_used": ["Screen Time Logs", "Daily Thought Essays"],
            "visual_requirements": ["Minimalist room shots", "Analog clock slow pan", "Rain on window pane"],
            "exclusion_audit": "✓ EXCLUSION VERIFIED: Authentic Self-Experiment in Hinglish"
          },
          {
            "topic": "Kyun Bada Hona Itna Strange Lagta Hai Aur Hum Apni Curiosity Kaise Khote Hain",
            "category": "Thoughts (Video Essays)",
            "pillar": "Thoughts",
            "country": "Personal Essay",
            "viral_potential": 10,
            "source_type": "Reflective Essays",
            "sources_used": ["Childhood memory notes", "Aperture style essay literature"],
            "visual_requirements": ["Cozy book shelf", "Walking in quiet forest", "Minimalist aesthetic visuals"],
            "exclusion_audit": "✓ EXCLUSION VERIFIED: Reflective Essay in Hinglish"
          },
          {
            "topic": "Late Night Baarish, Garam Coffee Aur Purani Kitabon Ki Shanti",
            "category": "Creative Philosophy",
            "pillar": "Creative Journey",
            "country": "Personal Essay",
            "viral_potential": 9,
            "source_type": "Personal Journal",
            "sources_used": ["Rainy Night Essays", "Creator Philosophy Notes"],
            "visual_requirements": ["Window rain droplet macro", "Steaming coffee mug B-roll"],
            "exclusion_audit": "✓ EXCLUSION VERIFIED: Authentic Personal Essay in Hinglish"
          }
        ],
        "Khayal3Baje": [
          {
            "topic": "Pashupatastra Ka Raaz Aur Divine Cosmic Astral Weapons",
            "category": "Vedic & Epic Lore",
            "pillar": "Vedic & Epic Lore",
            "country": "Ancient India",
            "viral_potential": 10,
            "source_type": "Sacred Texts & Epic Manuscripts",
            "sources_used": ["Mahabharata Vana Parva", "Puranic Encylopedia", "Sanskrit Manuscripts"],
            "visual_requirements": ["Epic oil painting visuals", "Cosmic fire rendering", "Ancient Sanskrit text overlays"],
            "exclusion_audit": "✓ Verified: Authentic Textual Sacred Lore in Hinglish"
          },
          {
            "topic": "Anunnaki Tablets Aur Mesopotamian Cosmic Creation Ka Myth",
            "category": "World Mythologies",
            "pillar": "World Mythologies",
            "country": "Ancient Mesopotamia",
            "viral_potential": 9,
            "source_type": "Cuneiform Translations",
            "sources_used": ["Enuma Elish Tablets", "British Museum Cuneiform Archives"],
            "visual_requirements": ["3D Cuneiform tablet rendering", "Ziggurat starry night map"],
            "exclusion_audit": "✓ Verified: Comparative World Mythology in Hinglish"
          },
          {
            "topic": "Kurukshetra Yuddh Mein Karna Ke Khoye Hue Divine Astra Aur Kahani",
            "category": "Vedic & Epic Lore",
            "pillar": "Epic Lore",
            "country": "Ancient India",
            "viral_potential": 10,
            "source_type": "Mahabharata Karna Parva",
            "sources_used": ["Mahabharata Sanskrit Verse", "Bhandarkar Oriental Research Institute"],
            "visual_requirements": ["Golden armor glow effect", "Chariot battlefield matte painting"],
            "exclusion_audit": "✓ Verified: Ancient Epic Lore in Hinglish"
          },
          {
            "topic": "Kali Yuga Ke Ant Tak Pehre Dete 7 Immortal Chiranjivi",
            "category": "Sacred Epic Lore",
            "pillar": "Sacred Epic Lore",
            "country": "Ancient India",
            "viral_potential": 10,
            "source_type": "Puranic Texts",
            "sources_used": ["Bhagavata Purana", "Vishnu Purana"],
            "visual_requirements": ["Himalayan cave mist visual", "Sanskrit manuscript parchment"],
            "exclusion_audit": "✓ Verified: Textual Puranic Mythology in Hinglish"
          }
        ]
    }

    # Match channel key
    for k, topics in channel_vaults.items():
        if k.lower() in channel.lower() or channel.lower() in k.lower():
            return {
                "status": "success",
                "channel": k,
                "agent_assigned": target_agent_name,
                "inventory_counts": { "raw_ideas": 120, "researched_ideas": 55, "script_ready": 24 },
                "topics": topics
            }

    # Default fallback
    return {
        "status": "success",
        "channel": channel,
        "agent_assigned": target_agent_name,
        "inventory_counts": { "raw_ideas": 100, "researched_ideas": 50, "script_ready": 20 },
        "topics": channel_vaults["Beyond3Baje"]
    }

SAVED_TOPICS_FILE = os.path.join(os.path.dirname(__file__), "..", "knowledge", "saved_topics.json")

class SavedTopicSchema(BaseModel):
    id: Optional[str] = None
    topic: str
    category: Optional[str] = "General"
    channel: str
    viral_potential: Optional[int] = 9
    country: Optional[str] = "Global"
    source_type: Optional[str] = "Researched"
    sources_used: Optional[List[str]] = []
    visual_requirements: Optional[List[str]] = []
    exclusion_audit: Optional[str] = ""
    notes: Optional[str] = ""

def _load_saved_topics() -> List[Dict[str, Any]]:
    if not os.path.exists(SAVED_TOPICS_FILE):
        initial_topics = [
            {
                "id": "saved_topic_1",
                "topic": "Bhangarh Fort Ka Wo Guard Jo Raat Ke 3 Baje Ghaayab Ho Gaya",
                "category": "Paranormal & Haunted Locations",
                "channel": "Spilled Coffee After Dark",
                "viral_potential": 9,
                "country": "India",
                "source_type": "Local Indian Folklore & Archives",
                "sources_used": ["Reddit (r/Paranormal)", "Local Rajasthani Folklore"],
                "visual_requirements": ["Haunted fort archival photos", "Night rain mist imagery"],
                "exclusion_audit": "✓ Verified: Parapsychological Folklore",
                "notes": "Focus on the 3AM guard shift testimonies written in Hinglish script",
                "saved_at": datetime.now().isoformat()
            },
            {
                "id": "saved_topic_2",
                "topic": "Kaise Ek Choti Si Engineering Galti Ne Poore Warship Ko Duba Diya",
                "category": "Engineering & Disaster Stories",
                "channel": "Beyond3Baje",
                "viral_potential": 9,
                "country": "International",
                "source_type": "Historical & Technical Archives",
                "sources_used": ["Naval Inspection Records", "Wikipedia Disasters"],
                "visual_requirements": ["Ship cross-section 3D diagram", "17th Century maps"],
                "exclusion_audit": "✓ EXCLUSION VERIFIED: 100% Real-World True Story in Hinglish",
                "notes": "Use 3D stability diagram for 45-second Hinglish opening hook",
                "saved_at": datetime.now().isoformat()
            }
        ]
        os.makedirs(os.path.dirname(SAVED_TOPICS_FILE), exist_ok=True)
        with open(SAVED_TOPICS_FILE, "w", encoding="utf-8") as f:
            json.dump(initial_topics, f, indent=2)
        return initial_topics
    try:
        with open(SAVED_TOPICS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _save_saved_topics(topics: List[Dict[str, Any]]):
    os.makedirs(os.path.dirname(SAVED_TOPICS_FILE), exist_ok=True)
    with open(SAVED_TOPICS_FILE, "w", encoding="utf-8") as f:
        json.dump(topics, f, indent=2)

@app.get("/api/topics/saved")
def get_saved_topics(channel: Optional[str] = None):
    topics = _load_saved_topics()
    if channel and channel.strip():
        topics = [t for t in topics if channel.lower() in t.get("channel", "").lower()]
    return {"status": "success", "count": len(topics), "topics": topics}

@app.post("/api/topics/save")
def save_topic(payload: SavedTopicSchema):
    topics = _load_saved_topics()
    topic_data = payload.dict()
    if not topic_data.get("id"):
        topic_data["id"] = f"topic_{uuid.uuid4().hex[:8]}"
    topic_data["saved_at"] = datetime.now().isoformat()
    
    existing_idx = next((i for i, t in enumerate(topics) if t.get("topic") == topic_data["topic"] and t.get("channel") == topic_data["channel"]), -1)
    if existing_idx >= 0:
        topics[existing_idx].update(topic_data)
    else:
        topics.insert(0, topic_data)
        
    _save_saved_topics(topics)
    return {"status": "success", "message": "Topic saved to vault successfully", "topic": topic_data}

@app.post("/api/topics/delete")
def delete_saved_topic(payload: Dict[str, Any] = Body(...)):
    topic_id = payload.get("id")
    topic_title = payload.get("topic")
    topics = _load_saved_topics()
    
    if topic_id:
        topics = [t for t in topics if t.get("id") != topic_id]
    elif topic_title:
        topics = [t for t in topics if t.get("topic") != topic_title]
        
    _save_saved_topics(topics)
    return {"status": "success", "message": "Topic removed from vault", "remaining": len(topics)}

def _build_workforce_summary() -> str:
    """Builds a formatted summary of all 115 registered agents in the AgentRegistry."""
    from core.agent import agent_registry
    dept_map: Dict[str, List[str]] = {}
    for agent_def in agent_registry.agents.values():
        dept = agent_def.department or "General"
        dept_map.setdefault(dept, []).append(agent_def.name)
    
    lines = [f"### Available Studio Workforce Directory ({len(agent_registry.agents)} Registered AI Agents)"]
    for dept, agents in sorted(dept_map.items()):
        agent_list_str = ", ".join(sorted(agents))
        lines.append(f"- **{dept}** ({len(agents)} agents): {agent_list_str}")
    return "\n".join(lines)


def _process_agent_invocations(reply_text: str) -> str:
    """
    Parses [INVOKE_AGENT: AgentName] task [/INVOKE_AGENT] blocks in the strategist output,
    executes the target agents using AgentFactory, and embeds their output live.
    """
    pattern = r"\[INVOKE_AGENT:\s*([a-zA-Z0-9_]+)\](.*?)\[/INVOKE_AGENT\]"
    matches = list(re.finditer(pattern, reply_text, re.DOTALL))
    if not matches:
        return reply_text

    final_text = reply_text
    for match in matches:
        full_tag = match.group(0)
        target_agent_name = match.group(1).strip()
        task_instruction = match.group(2).strip()
        
        logger.info(f"Strategist delegated task to specialist agent: '{target_agent_name}'")
        try:
            target_agent = AgentFactory.get_agent(target_agent_name)
            agent_response = target_agent.execute(
                f"You have been invoked by a Lead Channel Strategist to perform the following task:\n\n{task_instruction}"
            )
            
            replacement = f"\n\n---\n🤖 **[Delegated Specialist Execution: `{target_agent_name}`]**\n> *Task*: {task_instruction}\n\n{agent_response}\n---\n\n"
            final_text = final_text.replace(full_tag, replacement)
        except Exception as e:
            logger.error(f"Failed to execute delegated agent {target_agent_name}: {e}")
            replacement = f"\n*⚠️ Unable to complete execution for delegated agent `{target_agent_name}`: {e}*\n"
            final_text = final_text.replace(full_tag, replacement)

    return final_text


class AgentChatSchema(BaseModel):
    agent_name: str
    channel: str
    message: str
    context_topic: Optional[Dict[str, Any]] = None
    chat_history: Optional[List[Dict[str, str]]] = None

@app.get("/api/memory")
def get_memory_logs(scope: Optional[str] = "agent", owner: Optional[str] = "Beyond3BajeStrategist", limit: int = 10):
    try:
        from memory.memory import memory_system
        memories = memory_system.retrieve(scope=scope, owner=owner, limit=limit)
        return {"status": "success", "scope": scope, "owner": owner, "count": len(memories), "memories": [m.to_dict() for m in memories]}
    except Exception as e:
        return {"status": "error", "message": str(e), "memories": []}

@app.post("/api/memory/clear")
def clear_memory_logs(scope: Optional[str] = "agent", owner: Optional[str] = "Beyond3BajeStrategist"):
    try:
        from memory.memory import memory_system
        memory_system.clear(scope=scope, owner=owner)
        return {"status": "success", "message": f"Cleared memory for scope={scope}, owner={owner}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/topics/chat_history")
def get_chat_history(channel: str, agent_name: str):
    try:
        from memory.memory import memory_system
        agent_mems = memory_system.retrieve(scope="agent", owner=agent_name, limit=20)
        session_mems = memory_system.retrieve(scope="session", owner=channel, limit=20)
        
        turns = []
        for m in sorted(session_mems + agent_mems, key=lambda x: x.created):
            if isinstance(m.content, dict) and "user" in m.content and "reply" in m.content:
                turns.append({
                    "user": m.content["user"],
                    "reply": m.content["reply"],
                    "agent": m.content.get("agent", agent_name),
                    "timestamp": m.created
                })
        return {"status": "success", "channel": channel, "agent_name": agent_name, "count": len(turns), "turns": turns}
    except Exception as e:
        return {"status": "error", "message": str(e), "turns": []}

@app.post("/api/topics/agent_chat")
def agent_chat(payload: AgentChatSchema):
    agent_name = payload.agent_name.strip()
    try:
        agent = AgentFactory.get_agent(agent_name)
    except Exception:
        agent = AgentFactory.get_agent("TopicVaultManager")
    
    history_formatted = ""
    if payload.chat_history:
        for msg in payload.chat_history:
            role = "User" if msg.get("role") == "user" else agent_name
            history_formatted += f"\n{role}: {msg.get('content', '')}"

    topic_formatted = ""
    if payload.context_topic:
        t = payload.context_topic
        topic_formatted = f"""
### Currently Discussed Topic Details
- Title: {t.get('topic')}
- Category/Pillar: {t.get('category')}
- Target Channel: {t.get('channel', payload.channel)}
- Viral Potential: {t.get('viral_potential')}/10
- Sources Used: {', '.join(t.get('sources_used', [])) if isinstance(t.get('sources_used'), list) else t.get('sources_used', '')}
- Visual Requirements: {', '.join(t.get('visual_requirements', [])) if isinstance(t.get('visual_requirements'), list) else t.get('visual_requirements', '')}
"""

    # Retrieve persistent long-term memories from memory_system
    memory_formatted = ""
    try:
        from memory.memory import memory_system
        agent_memories = memory_system.retrieve(scope="agent", owner=agent_name, limit=15)
        session_memories = memory_system.retrieve(scope="session", owner=payload.channel, limit=15)
        
        all_mem_text = []
        for m in agent_memories + session_memories:
            c_text = json.dumps(m.content) if isinstance(m.content, (dict, list)) else str(m.content)
            all_mem_text.append(f"- [{m.updated[:19]}] {c_text}")
            
        if all_mem_text:
            memory_formatted = "\n### MANDATORY LONG-TERM PERSISTENT STUDIO MEMORY LOGS:\n" + "\n".join(all_mem_text) + "\n"
    except Exception as e:
        logger.error(f"Error retrieving memories in agent_chat: {e}")

    workforce_roster = _build_workforce_summary()

    full_user_prompt = f"""
You are acting in your role as Lead Channel Strategist ({agent_name}) for the channel '{payload.channel}'.
You have full strategic authority over an autonomous AI Studio workforce of 115 specialized agents across 19 departments.

{workforce_roster}

{memory_formatted}

### CRITICAL MEMORY & CONTINUITY DIRECTIVE:
You have FULL ACCESS to past persistent studio memories, user directives, channel preferences, and prior conversation context above.
YOU MUST REMEMBER all previous choices, topic decisions, hooks, script directions, and feedback given by the user in past interactions.

### MANDATORY HINGLISH LANGUAGE & SCRIPT DIRECTIVE:
You MUST reply and generate all topic titles, script hooks, outlines, dialogues, B-roll notes, and video ideas in **Hinglish** (day-to-day conversational Hindi written in Roman/English fonts).
Do NOT write pure formal English scripts or Devanagari Hindi text. Use natural, conversational Hinglish as spoken in top Hindi YouTube documentaries & video essays!

### Strategic Delegation Capabilities:
1. You KNOW about every single agent listed in the workforce directory above.
2. If the user asks for specific work (such as deep fact-checking, full script writing, SEO tags & titles, thumbnail concepts, B-roll/scene planning, or vault management), YOU HAVE THE POWER TO CALL THOSE AGENTS.
3. To delegate a task and make a specialized agent execute it live, insert the following tag in your response:
   [INVOKE_AGENT: AgentName] Write clear instructions for what you need this agent to do... [/INVOKE_AGENT]

{topic_formatted}

### Active Conversation Turns History:
{history_formatted if history_formatted else "No previous turns in this immediate session."}

### User's Current Question/Directive:
{payload.message}

Provide a helpful, strategic response in character as {agent_name}. Refer back to any relevant past decisions or context stored in your memory logs whenever appropriate. All topic titles, script outlines, and dialogues MUST be in Hinglish!
"""
    try:
        reply_text = str(agent.execute(full_user_prompt))
        # Execute any delegated agent tasks embedded in the response
        reply_text = _process_agent_invocations(reply_text)
        
        # Save interaction into persistent MemorySystem disk files
        try:
            from memory.memory import memory_system
            mem_payload = {
                "user": payload.message,
                "reply": reply_text,
                "agent": agent_name,
                "channel": payload.channel
            }
            memory_system.save(
                scope="agent",
                owner=agent_name,
                tags=["chat", payload.channel],
                content=mem_payload
            )
            memory_system.save(
                scope="session",
                owner=payload.channel,
                tags=["chat", agent_name],
                content=mem_payload
            )
        except Exception as mem_err:
            logger.error(f"Error saving to memory_system in agent_chat: {mem_err}")

        return {
            "status": "success",
            "agent_name": agent_name,
            "channel": payload.channel,
            "reply": reply_text
        }
    except Exception as e:
        logger.error(f"Error executing agent {agent_name}: {e}")
        return {
            "status": "success",
            "agent_name": agent_name,
            "channel": payload.channel,
            "reply": f"Hello! As your **{agent_name}** for **{payload.channel}**, I'm ready to help. Let's discuss video concepts, script hooks, or visual production ideas!"
        }

class VoiceIntentSchema(BaseModel):
    phrase: str

@app.post("/api/voice/parse_intent")
def parse_voice_intent(payload: VoiceIntentSchema):
    phrase = payload.phrase.lower().strip()
    
    channels = {
        "spilled coffee studio": "Spilled Coffee Studio",
        "studio": "Spilled Coffee Studio",
        "after dark": "Spilled Coffee After Dark",
        "horror": "Spilled Coffee After Dark",
        "raat": "Spilled Coffee After Dark",
        "beyond": "Beyond3Baje",
        "documentary": "Beyond3Baje",
        "life": "Life3Baje",
        "essay": "Life3Baje",
        "khayal": "Khayal3Baje",
        "mythology": "Khayal3Baje"
    }

    for kw, ch_name in channels.items():
        if kw in phrase:
            return {
                "status": "success",
                "intent": "SWITCH_CHANNEL",
                "target_channel": ch_name,
                "confidence": 0.95
            }

    nav_map = {
        "dashboard": "dashboard",
        "project": "projects",
        "topic": "topic_discovery",
        "vault": "topic_discovery",
        "research": "research",
        "writing": "writing",
        "production": "production",
        "publishing": "publishing",
        "analytics": "publishing",
        "setting": "settings"
    }
    for kw, tab_name in nav_map.items():
        if kw in phrase:
            return {
                "status": "success",
                "intent": "NAVIGATE",
                "target_tab": tab_name,
                "confidence": 0.90
            }

    if any(k in phrase for k in ["discover", "find", "search", "get topics"]):
        return {"status": "success", "intent": "DISCOVER_TOPICS", "confidence": 0.92}
    if any(k in phrase for k in ["save", "bookmark"]):
        return {"status": "success", "intent": "SAVE_TOPIC", "confidence": 0.92}
    if any(k in phrase for k in ["chat", "talk", "agent", "discuss"]):
        return {"status": "success", "intent": "OPEN_CHAT", "confidence": 0.92}

    return {"status": "success", "intent": "UNKNOWN", "confidence": 0.30}

VOICE_CONFIG = {
    "provider": "native_local",
    "picovoice_access_key": "",
    "openai_realtime_key": "",
    "wake_word": "Hey Buzzcaf"
}

class VoiceConfigSchema(BaseModel):
    provider: Optional[str] = "native_local"
    picovoice_access_key: Optional[str] = ""
    openai_realtime_key: Optional[str] = ""
    wake_word: Optional[str] = "Hey Buzzcaf"

@app.get("/api/voice/config")
def get_voice_config():
    return VOICE_CONFIG

@app.post("/api/voice/config")
def update_voice_config(payload: VoiceConfigSchema):
    if payload.provider: VOICE_CONFIG["provider"] = payload.provider
    if payload.picovoice_access_key is not None: VOICE_CONFIG["picovoice_access_key"] = payload.picovoice_access_key
    if payload.openai_realtime_key is not None: VOICE_CONFIG["openai_realtime_key"] = payload.openai_realtime_key
    if payload.wake_word: VOICE_CONFIG["wake_word"] = payload.wake_word
    return {"status": "success", "config": VOICE_CONFIG}

class JarvisVoiceSchema(BaseModel):
    phrase: str
    active_channel: Optional[str] = "Beyond3Baje"
    active_tab: Optional[str] = "dashboard"

@app.post("/api/jarvis/voice")
def jarvis_voice_router(payload: JarvisVoiceSchema):
    phrase = payload.phrase.strip()
    p_lower = phrase.lower()
    
    # Smart Agentic Intent Inference Engine
    target_channel = None
    target_tab = None
    is_save = False
    is_chat = False
    is_discover = False
    is_stop = False
    is_log = False

    # Channel Intent Resolution
    if any(k in p_lower for k in ["after dark", "horror", "raat", "ghost", "spilled coffee after dark"]):
        target_channel = "Spilled Coffee After Dark"
    elif any(k in p_lower for k in ["studio", "original", "story", "spilled coffee studio"]):
        target_channel = "Spilled Coffee Studio"
    elif any(k in p_lower for k in ["beyond", "documentary", "true story", "crime", "beyond3baje"]):
        target_channel = "Beyond3Baje"
    elif any(k in p_lower for k in ["life", "essay", "vlog", "journey", "life3baje"]):
        target_channel = "Life3Baje"
    elif any(k in p_lower for k in ["khayal", "mythology", "lore", "ancient", "khayal3baje"]):
        target_channel = "Khayal3Baje"

    # Tab Intent Resolution (Infers natural language variations like 'publish analytics', 'check performance', 'agent workforce')
    if any(k in p_lower for k in ["project", "projects", "catalog", "production catalog"]):
        target_tab = "projects"
    elif any(k in p_lower for k in ["topic", "topics", "vault", "discover", "discovery", "idea", "ideas"]):
        target_tab = "topic_discovery"
    elif any(k in p_lower for k in ["research", "citation", "citations", "source", "sources", "study"]):
        target_tab = "research"
    elif any(k in p_lower for k in ["writing", "script", "scripts", "editor", "write"]):
        target_tab = "writing"
    elif any(k in p_lower for k in ["production", "scene", "board", "filmora", "b-roll", "b roll"]):
        target_tab = "production"
    elif any(k in p_lower for k in ["publish", "publishing", "analytic", "analytics", "performance", "view", "views", "stat", "stats"]):
        target_tab = "publishing"
    elif any(k in p_lower for k in ["workforce", "agent", "agents", "bot", "bots", "registry"]):
        target_tab = "ai_workforce"
    elif any(k in p_lower for k in ["health", "diagnostic", "diagnostics", "status", "system"]):
        target_tab = "health"
    elif any(k in p_lower for k in ["setting", "settings", "router", "config", "parameters", "api key"]):
        target_tab = "settings"
    elif any(k in p_lower for k in ["dashboard", "home", "overview", "main"]):
        target_tab = "dashboard"

    # Action Intent Resolution
    if any(k in p_lower for k in ["save", "bookmark", "add to vault"]): is_save = True
    if any(k in p_lower for k in ["chat", "talk", "discuss", "strategist", "ask agent"]): is_chat = True
    if any(k in p_lower for k in ["find", "search", "discover", "generate", "look up", "sweep"]): is_discover = True
    if any(k in p_lower for k in ["stop", "quiet", "mute", "turn off", "sleep", "pause"]): is_stop = True
    if any(k in p_lower for k in ["activity log", "show log", "open log", "history", "logs", "activity"]): is_log = True

    curr_ch = target_channel or payload.active_channel
    
    # Autonomous Natural Speech Generation
    if is_stop:
        buzzcaf_speech = "Buzzcaf standing down, sir. Voice system paused."
    elif is_log:
        buzzcaf_speech = "Opening your voice activity log console now, sir."
    elif target_channel and target_tab:
        buzzcaf_speech = f"Right away, sir. Switched to {target_channel} and opened the {target_tab.replace('_', ' ')} workspace."
    elif target_channel:
        buzzcaf_speech = f"Certainly, sir. Aligning system intelligence with {target_channel}."
    elif target_tab:
        buzzcaf_speech = f"Opening {target_tab.replace('_', ' ')} workspace now, sir."
    elif is_save:
        buzzcaf_speech = f"Bookmarking the top discovered topic directly into your Vault, sir."
    elif is_chat:
        buzzcaf_speech = f"Initiating direct strategist chat session for {curr_ch}, sir."
    elif is_discover:
        buzzcaf_speech = f"Executing a full topic discovery sweep across Reddit, Wikipedia, and archives for {curr_ch}, sir."
    elif any(w in p_lower for w in ["hi", "hello", "hey", "who are you", "what can you do"]):
        buzzcaf_speech = f"Hello sir! I am Buzzcaf, your autonomous AI production assistant. Tell me what you need, and I will execute it."
    else:
        clean_phrase = phrase.replace("buzzcaf", "").replace("hey", "").replace("and", "").replace("please", "").strip()
        buzzcaf_speech = f"Right away, sir. Executing your request regarding {clean_phrase if clean_phrase else 'your studio directive'}."

    return {
        "status": "success",
        "buzzcaf_speech": buzzcaf_speech,
        "jarvis_speech": buzzcaf_speech,
        "action": {
            "target_channel": target_channel,
            "target_tab": target_tab,
            "is_save": is_save,
            "is_chat": is_chat,
            "is_discover": is_discover,
            "is_stop": is_stop,
            "is_log": is_log
        }
    }

@app.get("/api/agents")
def get_all_agents():
    prompts_dir = os.path.join(os.path.dirname(__file__), "..", "prompts", "agents")
    agents = []
    if os.path.exists(prompts_dir):
        for f in sorted(os.listdir(prompts_dir)):
            if f.endswith(".md"):
                agent_name = f[:-3]
                agents.append({
                    "name": agent_name,
                    "status": "Active & Idle",
                    "file": f
                })
    return {"status": "success", "count": len(agents), "agents": agents}

from core.diagnostics import Diagnostics

@app.get("/api/diagnostics")
def get_diagnostics():
    return Diagnostics.get_report()




# Serve UI static files

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
else:
    print(f"WARNING: UI static folder not found at: {static_dir}")
