"""Canned responses used when no LLM provider is reachable.

This is development scaffolding, not product behaviour. It lives outside the
integrations package so that nothing in the normal call path can reach it by
accident, and it is only consulted when APP_ENV is a development environment
(see LLMService.generate_text). Callers that do use it must label the result --
`LLMService.last_response_simulated` is set to True, API responses carry
`"status": "simulated"`, and the UI shows a banner.

Fabricated text that is indistinguishable from a real model answer is worse
than an error. If you change anything here, keep the labelling intact.
"""
import logging

logger = logging.getLogger("buzzcaf_ai.dev.fixtures")


def generate_simulated_response(system_prompt: str, user_prompt: str, require_json: bool) -> str:
    logger.info("Generating a dynamic LLM response...")
    
    # Parse agent identity from system prompt or user prompt
    agent_name = "ScriptWriter"
    full_text_search = (system_prompt or "") + "\n" + (user_prompt or "")
    
    if "Lead Channel Strategist (" in full_text_search:
        try:
            agent_name = full_text_search.split("Lead Channel Strategist (")[1].split(")")[0].strip()
        except Exception:
            agent_name = "ScriptWriter"
    else:
        for line in system_prompt.splitlines():
            if line.startswith("name:") or line.startswith("- **Agent Name**"):
                agent_name = line.split(":")[-1].strip().replace('"', '').replace('*', '')
                break
            
    # Cleanly extract user's actual question if prompt contains system/meta wrappers
    actual_question = user_prompt.strip()
    if "### User's Current Question/Directive:" in user_prompt:
        parts = user_prompt.split("### User's Current Question/Directive:")
        if len(parts) > 1:
            q_part = parts[1].split("Provide a helpful")[0].split("###")[0].strip()
            if q_part:
                actual_question = q_part
    elif "### Task Description" in user_prompt:
        parts = user_prompt.split("### Task Description")
        if len(parts) > 1:
            q_part = parts[1].split("###")[0].strip()
            if q_part:
                actual_question = q_part

    q_lower = actual_question.lower()
    sys_lower = system_prompt.lower()
    prompt_lower = sys_lower + " " + q_lower

    # Dedicated Script Dictation Completion & Extension Handler
    msg_lower = user_prompt.lower()
    if "creator's dictated" in msg_lower or "semi-written draft" in msg_lower or "complete the story" in q_lower or "script draft" in q_lower or "complete this script" in q_lower:
        draft_text = ""
        if "### Creator's Dictated Semi-Written Draft:" in user_prompt:
            try:
                parts = user_prompt.split("### Creator's Dictated Semi-Written Draft:")
                if len(parts) > 1:
                    draft_text = parts[1].split("Provide the complete")[0].replace('"""', '').strip()
            except Exception:
                draft_text = actual_question
        elif '"""' in user_prompt:
            try:
                draft_text = user_prompt.split('"""')[1].strip()
            except Exception:
                draft_text = actual_question
        
        if not draft_text or len(draft_text) < 10:
            draft_text = actual_question

        return f"""### 📜 Extended & Completed Hinglish Script (by {agent_name})

**[SCENE 1: CREATOR DRAFT RECAP & HOOK]**
NARRATOR (V.O.):
{draft_text}

---

**[SCENE 2: DEEPENING MYSTERY & UNCOVERING DECLASSIFIED EVIDENCE]**
NARRATOR (V.O.):
Lekin kahani yahan khatam nahi hoti. Jab humne is incident ke official archival logs aur declassified reports ko explore kiya, tab ek aisi file saamne aayi jo pichle 30 saalon se locked locker mein rakhi hui thi. 

Reports ke mutabiq, raat ke 3:15 AM par radar screen par ek aisi unknown signal frequency spot hui jo kisi bhi known commercial ya military aircraft se match nahi karti thi.

**[SCENE 3: THE PARANORMAL & HISTORICAL TURNING POINT]**
NARRATOR (V.O.):
Local eye-witnesses ne bataya ki us specific raat ko saare electronic devices ek saath glitch karne lage the. Phone battery 100% se 0% drop ho gayi aur radio par sirf ek repetitive static hiss sunayi de raha tha. 

Scientific investigation team jab mauke par pahuche, unke meters ne sudden electromagnetic pulse measure kiya jise aaj tak explain nahi kiya ja saka hai.

**[VISUAL B-ROLL & TIMING DIRECTIONS]**
- **00:00 - 00:30**: Slow macro zoom on steaming coffee cup with glitch overlay.
- **00:30 - 01:15**: High-contrast declassified newspaper clippings with yellow highlight animation.
- **01:15 - 02:00**: Thermal satellite map overlay showing radar flight anomalies.
- **02:00 - End**: Cinematic night-sky drone footage with low-frequency 432Hz ambient sound design.

**[SCENE 4: HIGH-RETENTION OUTRO & COMMENT TRIGGER]**
NARRATOR (V.O.):
Kya yeh ek rare atmospheric anomaly tha ya phir iske peeche koi aisa hidden truth hai jise duniya se chhupaya ja raha hai? Aapki kya rai hai, neeche comment section mein zaroor share karein!

---
*Script successfully expanded and finalized in Hinglish by {agent_name}.*"""

    is_greeting = any(w in q_lower for w in ["what can you do", "who are you", "what do you do", "help me", "capabilities", "hello", "hi", "what can yopui do", "what can u do", "what can you help"])

    # Beyond3Baje Strategist
    if "beyond3baje" in agent_name.lower():
        if is_greeting:
            return """Hello! I am your **Beyond3Baje Strategist**. I specialize in 100% real-world, fact-grounded documentaries, true crime, dark history, and historical disasters.

Here is what I can do for you:
- **Topic Discovery**: Brainstorm high-CTR true crime, lost history, and historical disaster concepts.
- **Hook & Pacing Design**: Craft 15-second retention hooks and 3-act documentary structures.
- **Scripting & Outlining**: Outline verified documentary scripts grounded in real-world archives.
- **Visual Asset Planning**: Suggest 3D maps, trial transcripts, and archival B-roll cues.

What topic or video idea would you like to discuss today?"""

        topics_db = [
            ("The Stora Sjöfallet Gold Heist", "How $400M in Gold Vanished from a Nuclear-Proof Vault in 40 Minutes.", "True Crime & Heists"),
            ("The Chernobyl Control Room Minutes Before Explosion", "Declassified Soviet safety logs and operator decision timeline.", "Dark History & Disasters"),
            ("India's Most Mysterious Missing Flight (1976)", "The coastal aviation disappearance with sealed air traffic radar logs.", "Unsolved Real-World Mysteries"),
            ("The 1947 Bombay Port Ammonium Nitrate Explosion", "Declassified admiralty reports on the naval ship disaster.", "Engineering & Historical Disasters"),
            ("The Unopened Chamber #7 of Raigad Treasury", "Subterranean rock-cut vaults beneath Chhatrapati Shivaji Maharaj's hill fort.", "Dark History & Lost Treasures")
        ]
        topic_lines = "\n".join([f"{idx+1}. **{t[0]}**: {t[1]} *(Pillar: {t[2]})*" for idx, t in enumerate(topics_db)])
        return f"""Here are top documentary & true story concepts for **Beyond3Baje**:

{topic_lines}

Which concept would you like to develop or outline into a script?"""

    # After Dark Strategist
    elif "afterdark" in agent_name.lower() or "after dark" in agent_name.lower():
        if is_greeting:
            return """Hello! I am your **Raat3Baje Strategist**. I specialize in parapsychological folklore, 3 AM high-strangeness encounters, and regional horror archives.

Here is how I can assist you:
- **Horror Topic Vault**: Discover regional 3 AM legends, haunted locations, and unexplained events.
- **Atmospheric Hooks**: Design eerie 45-second retention openings and 432Hz binaural soundscapes.
- **Script & Arc Design**: Build night-vision B-roll transitions and storytelling arcs.

Which terrifying topic or regional mystery shall we tackle today?"""

        topics_db = [
            ("The Phantom Telegraph of Sinhagad Pass", "19th-century British logs detailing phantom Morse telegraph clicks at 2 AM.", "Unexplained Transmissions"),
            ("The Silent Calls from the Deep Web", "Audio Incident #99 recorded on an unindexed onion node.", "Internet Myths"),
            ("The 3 AM Whistle of Dow Hill Boarding School", "Kurseong tea garden chronicles and headless apparition sightings.", "Haunted Locations"),
            ("Skinwalker Ranch Surveillance Logs", "2016 field incident report with thermal imaging anomalies.", "Unexplained Phenomena"),
            ("The Mass Disappearance of Kuldhara Village", "1825 Paliwal Brahmin migration leaving 84 villages deserted overnight.", "True Mysteries")
        ]
        topic_lines = "\n".join([f"{idx+1}. **{t[0]}**: {t[1]} *(Pillar: {t[2]})*" for idx, t in enumerate(topics_db)])
        return f"""Here are top horror & unexplained concepts for **Raat3Baje**:

{topic_lines}

Which 3 AM mystery concept would you like to outline into a full script?"""

    # Khayal3Baje Strategist
    elif "khayal" in agent_name.lower():
        if is_greeting:
            return """Namaste! I am your **Khayal3Baje Strategist**. I focus on authentic ancient mythology, textual epic lore, and world mythologies.

Here is how I can help you:
- **Epic Lore Discovery**: Uncover Puranic legends, Mahabharata/Ramayana lore, and ancient cuneiform mythologies.
- **Textual Authenticity**: Ground video concepts in authentic Sanskrit manuscripts and historical epics.
- **Visual Art Direction**: Design 3D Sanskrit text overlays, epic oil painting visual cues, and golden lighting.

Which ancient epic or myth would you like to explore next?"""

        topics_db = [
            ("The Secrets of Pashupatastra & Trimbakeshwar Manuscripts", "Puranic lore surrounding divine cosmic weapons.", "Vedic Weapons"),
            ("The Submerged Shivalinga of Harihareshwar", "Coastal sea cave legends documented in Skanda Purana.", "Puranic Coastal Lore"),
            ("The Lost Sun Temple Manuscripts of Ellora (Cave #16)", "Rock-cut architectural alignments with solstices.", "Vedic Astronomy"),
            ("The Celestial Weapons of Karna at Ramtek", "Mahabharata Vana Parva references to sacred armor.", "Mahabharata Epic Lore"),
            ("The 7 Immortal Chiranjivis Standing Guard", "Puranic legends of Markandeya & Parashurama in Sahyadri caves.", "Sacred Immortals")
        ]
        topic_lines = "\n".join([f"{idx+1}. **{t[0]}**: {t[1]} *(Pillar: {t[2]})*" for idx, t in enumerate(topics_db)])
        return f"""Here are ancient mythology & sacred lore concepts for **Khayal3Baje**:

{topic_lines}

Shall we outline the script structure or visual cues for one of these topics?"""

    # Life3Baje Strategist
    elif "life" in agent_name.lower() or "life" in prompt_lower:
        if is_greeting:
            return """Welcome! I am your **Life3Baje Strategist**. I specialize in reflective personal essays, creative self-experiments, and atmospheric video essays.

Here is how I can support your channel:
- **Essay & Solitude Topics**: Brainstorm quiet personal experiments, deep work reflections, and nostalgia essays.
- **Calm Atmospheric Pacing**: Craft cozy candlelit writing desk aesthetics and warm morning B-roll cues.
- **Scripting & Narrative Flow**: Write authentic, non-preachy personal essay narratives.

Which essay concept or creative journey topic shall we outline?"""

        topics_db = [
            ("I Spent 7 Days Writing in a Remote Sahyadri Cabin", "What quiet solitude taught me about focus.", "Creative Solitude"),
            ("Why I Rebuilt My Writing Desk (And Kept Only 3 Things)", "Eliminating digital noise for deep work.", "Personal Experiments"),
            ("The Quiet Nostalgia of Late Night Rain in Konkan", "Exploring why rain triggers forgotten childhood memories.", "Atmospheric Video Essay"),
            ("I Read 50-Year-Old Journals Found in a Local Bookshop", "What past generations can teach us about anxiety.", "Reflective Essays"),
            ("Why Growing Up Feels Strange & How We Lose Curiosity", "A visual video essay on adult burnout.", "Thoughts & Philosophy")
        ]
        topic_lines = "\n".join([f"{idx+1}. **{t[0]}**: {t[1]} *(Pillar: {t[2]})*" for idx, t in enumerate(topics_db)])
        return f"""Here are reflective video essay concepts for **Life3Baje**:

{topic_lines}

Which essay concept fits your creative direction best?"""

    # Originals Strategist
    else:
        if is_greeting:
            return """Hello! I am your **Originals Strategist**. I am your primary partner for story architecture, classic literature breakdowns, and original creator fiction.

Here is how I can help you:
- **Story Architecture**: Analyze storytelling rules from Ghibli, Pixar, Nolan, Kafka, and Murakami.
- **Original Fiction (30%)**: Outline original short stories, narratives, and creative fiction.
- **Script & Hook Design**: Build 4-act story arcs and high-retention narrative openings.

What literary breakdown or original story idea shall we refine today?"""

        topics_db = [
            ("Why Franz Kafka's Stories Still Scare Modern Readers", "Analyzing psychological absurdity and isolation.", "Great Literature"),
            ("How Studio Ghibli & Pixar Write Unforgettable Emotion", "The 22 rules of storytelling and silent beats.", "Story Analysis"),
            ("The Midnight Library (Original Fantasy Short Story)", "A 30% original creator fiction piece.", "Original Work"),
            ("The Secret Story Structure of Christopher Nolan Movies", "Non-linear timelines and emotional anchors.", "Story Architecture"),
            ("How Haruki Murakami Blurs Reality & Dreams", "Magical realism techniques in modern literature.", "Literature Breakdown")
        ]
        topic_lines = "\n".join([f"{idx+1}. **{t[0]}**: {t[1]} *(Pillar: {t[2]})*" for idx, t in enumerate(topics_db)])
        return f"""Here are story architecture & literary breakdown concepts for **Originals**:

{topic_lines}

Which literary breakdown or original story concept shall we explore next?"""

    return f"""# AI Strategist Analysis & Content Framework

### Executive Directive Summary
- **Target Channel**: Spilled Coffee Media
- **Core Focus**: High-retention narrative storytelling & deep research integration
- **Retention Goal**: 65%+ Audience Retention at the 3:00 Mark

### Key Strategic Recommendations
1. **The 15-Second Curiosity Hook**: Start directly inside the action without a slow intro.
2. **Visual Contrast & Map Overlays**: Use high-contrast document zooms and geographic timeline maps.
3. **Audience Engagement Trigger**: End with a provocative open question in the comment section.

*Directive processed in character by Spilled Coffee AI Strategist Engine.*"""
