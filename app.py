from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", str(BASE_DIR / "ai_prompt_hub.db")))

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "local-dev-secret")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "").lower() in {"1", "true", "yes"}
PAGE_SIZE = 8


def make_password_hash(password: str) -> str:
    return generate_password_hash(password, method="pbkdf2:sha256")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exception: object) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            handle TEXT NOT NULL UNIQUE,
            email TEXT,
            password_hash TEXT,
            bio TEXT NOT NULL,
            accent TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            prompt_text TEXT,
            tool_name TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS post_tags (
            post_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            PRIMARY KEY (post_id, tag_id),
            FOREIGN KEY (post_id) REFERENCES posts (id),
            FOREIGN KEY (tag_id) REFERENCES tags (id)
        );

        CREATE TABLE IF NOT EXISTS likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (post_id) REFERENCES posts (id)
        );

        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            author_name TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (post_id) REFERENCES posts (id)
        );

        CREATE TABLE IF NOT EXISTS follows (
            follower_id INTEGER NOT NULL,
            followed_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (follower_id, followed_id),
            FOREIGN KEY (follower_id) REFERENCES users (id),
            FOREIGN KEY (followed_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS saves (
            user_id INTEGER NOT NULL,
            post_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id, post_id),
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (post_id) REFERENCES posts (id)
        );

        CREATE TABLE IF NOT EXISTS feedback_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT NOT NULL,
            email TEXT,
            topic TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );
        """
    )
    existing_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()
    }
    if "email" not in existing_columns:
        db.execute("ALTER TABLE users ADD COLUMN email TEXT")
    if "password_hash" not in existing_columns:
        db.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)")
    db.commit()


def ensure_seed_data() -> None:
    db = get_db()
    existing = db.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]

    if not existing:
        users = [
            (
                "Maya Chen",
                "maya-builds",
                "maya@example.com",
                make_password_hash("demo1234"),
                "Turns rough AI thoughts into product-ready workflows.",
                "#ff6b6b",
            ),
            (
                "Jon Park",
                "jonpromptlab",
                "jon@example.com",
                make_password_hash("demo1234"),
                "Collects prompt chains for research, design, and code reviews.",
                "#2ec4b6",
            ),
            (
                "Ari Sol",
                "arisignal",
                "ari@example.com",
                make_password_hash("demo1234"),
                "Shares practical AI ideas teams can ship in a week.",
                "#f4a261",
            ),
        ]
        db.executemany(
            "INSERT INTO users (name, handle, email, password_hash, bio, accent) VALUES (?, ?, ?, ?, ?, ?)",
            users,
        )
    else:
        db.execute(
            """
            UPDATE users
            SET email = COALESCE(email, handle || '@example.com'),
                password_hash = COALESCE(password_hash, ?)
            """
            ,
            (make_password_hash("demo1234"),),
        )

    db.execute(
        """
        INSERT OR IGNORE INTO users (name, handle, email, password_hash, bio, accent)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "Demo Builder",
            "demo-builder",
            "demo@signalprompt.local",
            make_password_hash("demo1234"),
            "Default demo account for local testing.",
            "#1d4ed8",
        ),
    )

    if existing:
        db.commit()
        return

    user_map = {
        row["handle"]: row["id"]
        for row in db.execute("SELECT id, handle FROM users").fetchall()
    }

    posts = [
        (
            user_map["maya-builds"],
            "Prompt",
            "Weekly product review prompt for messy startup roadmaps",
            "This prompt turns a pile of notes, bugs, and feature asks into one ranked plan the team can act on Monday morning.",
            "You are my product chief of staff. Review the notes below, cluster them into themes, rank by urgency and revenue impact, and produce a 7-day execution plan with tradeoffs.",
            "GPT / Claude",
            "2026-04-27 09:15:00",
        ),
        (
            user_map["jonpromptlab"],
            "Workflow",
            "AI idea: convert support tickets into trend briefs every Friday",
            "A lightweight workflow for customer support leads: summarize repeated complaints, name the likely root cause, and draft one message for leadership.",
            "Analyze the support tickets, group by issue family, estimate frequency, and write an executive brief with root causes, suggested owner, and one quote per issue family.",
            "OpenAI API",
            "2026-04-28 13:40:00",
        ),
        (
            user_map["arisignal"],
            "Idea",
            "Trending concept: public prompt teardown posts",
            "People do not only want prompts. They want to know why a prompt worked, where it failed, and which variables matter most.",
            "",
            "Community format",
            "2026-04-29 08:20:00",
        ),
        (
            user_map["maya-builds"],
            "Prompt",
            "Design critique prompt for landing page screenshots",
            "Drop in a screenshot and get a harsh but useful review focused on clarity, hierarchy, and conversion friction.",
            "Act as a top-tier conversion designer. Critique this page for message clarity, information hierarchy, CTA friction, and trust signals. Then propose a tighter hero section.",
            "Vision model",
            "2026-04-29 19:10:00",
        ),
        (
            user_map["jonpromptlab"],
            "Workflow",
            "Prompt stack for AI newsletter curation",
            "Three-stage flow: gather links, cluster themes, then draft short commentary that sounds informed instead of generic.",
            "First classify each link by topic and signal strength. Next cluster similar stories. Finally write one-sentence commentary for each cluster with a contrarian angle.",
            "OpenAI API + RSS",
            "2026-04-30 07:35:00",
        ),
    ]
    db.executemany(
        """
        INSERT INTO posts (user_id, kind, title, summary, prompt_text, tool_name, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        posts,
    )

    tag_sets = {
        1: ["product", "planning", "ops"],
        2: ["support", "analytics", "ops"],
        3: ["community", "content", "social"],
        4: ["design", "ux", "conversion"],
        5: ["newsletter", "content", "research"],
    }

    for names in tag_sets.values():
        for name in names:
            db.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))

    tag_map = {
        row["name"]: row["id"]
        for row in db.execute("SELECT id, name FROM tags").fetchall()
    }
    for post_id, names in tag_sets.items():
        for name in names:
            db.execute(
                "INSERT INTO post_tags (post_id, tag_id) VALUES (?, ?)",
                (post_id, tag_map[name]),
            )

    likes = [(1, "2026-04-29 10:00:00"), (1, "2026-04-30 08:00:00"), (2, "2026-04-29 18:00:00"),
             (3, "2026-04-29 21:00:00"), (3, "2026-04-30 09:00:00"), (3, "2026-04-30 12:00:00"),
             (4, "2026-04-30 06:30:00"), (5, "2026-04-30 10:10:00"), (5, "2026-04-30 11:40:00")]
    db.executemany("INSERT INTO likes (post_id, created_at) VALUES (?, ?)", likes)

    comments = [
        (1, "Leah", "This is the first roadmap prompt I would actually hand to a PM.", "2026-04-29 11:20:00"),
        (3, "Dex", "The teardown angle is stronger than another generic prompt dump.", "2026-04-30 08:40:00"),
        (5, "Rina", "The clustering step matters. Without it, newsletters feel random.", "2026-04-30 09:15:00"),
    ]
    db.executemany(
        "INSERT INTO comments (post_id, author_name, body, created_at) VALUES (?, ?, ?, ?)",
        comments,
    )
    demo_user_id = user_map.get("demo-builder")
    if demo_user_id:
        db.executemany(
            "INSERT OR IGNORE INTO follows (follower_id, followed_id, created_at) VALUES (?, ?, ?)",
            [
                (demo_user_id, user_map["maya-builds"], "2026-04-30 09:30:00"),
                (demo_user_id, user_map["jonpromptlab"], "2026-04-30 09:35:00"),
            ],
        )
        db.executemany(
            "INSERT OR IGNORE INTO saves (user_id, post_id, created_at) VALUES (?, ?, ?)",
            [
                (demo_user_id, 1, "2026-04-30 09:40:00"),
                (demo_user_id, 5, "2026-04-30 09:45:00"),
            ],
        )
    db.commit()


def ensure_more_demo_posts() -> None:
    db = get_db()
    user_map = {
        row["handle"]: row["id"]
        for row in db.execute("SELECT id, handle FROM users").fetchall()
    }
    if not {"maya-builds", "jonpromptlab", "arisignal"}.issubset(user_map):
        return
    demo_posts = [
        ("maya-builds", "Prompt", "Prompt for turning lab notes into an action list", "Paste rough lab notes and get owners, next checks, risks, and one clean status update.", "Convert these lab notes into: 1. decisions made, 2. open questions, 3. owner/action/date, 4. concise status note.", "ChatGPT", ["lab", "ops", "status"]),
        ("jonpromptlab", "Workflow", "Daily AI standup from Slack notes", "A simple flow that turns scattered project messages into a morning standup brief.", "Summarize yesterday's updates, blockers, decisions, and today priorities. Keep it under 12 bullets.", "OpenAI API", ["slack", "standup", "automation"]),
        ("arisignal", "Idea", "AI prompt marketplace should rank by repeat usage", "Likes are weak. A better signal is how often people come back and reuse or fork a prompt.", "", "Community format", ["product", "ranking", "social"]),
        ("maya-builds", "Prompt", "Email reply improver for short rough answers", "Give the sender's note and your rough answer. The prompt preserves your intent but makes it professional.", "Rewrite my rough reply. Preserve my intent and timing. Add one useful context sentence if my answer is too short. Return only the reply.", "GPT", ["email", "writing", "work"]),
        ("jonpromptlab", "Workflow", "Turn PDFs into review checklists", "Upload a spec or datasheet, then generate a checklist that maps each concern to the page or section.", "Read this document and create a review checklist with issue, why it matters, page reference, and suggested owner.", "Vision + PDF parser", ["datasheet", "review", "hardware"]),
        ("arisignal", "Prompt", "Personal learning coach for dense papers", "A reusable prompt for turning technical papers into a study plan with questions and exercises.", "Teach me this paper. Start with the thesis, then prerequisites, then 10 questions, then 3 exercises.", "Claude", ["learning", "research", "papers"]),
        ("maya-builds", "Idea", "Prompt comments should include before and after output", "A prompt post is much more useful when the author shows the bad output, the changed prompt, and the improved output.", "", "Community format", ["prompting", "community", "quality"]),
        ("jonpromptlab", "Prompt", "Code review prompt for small risky diffs", "Focus review on behavior changes, missing tests, and edge cases instead of style comments.", "Review this diff. List only bugs, regressions, missing tests, and unclear requirements. Include file/line references.", "Codex", ["code", "review", "testing"]),
        ("arisignal", "Workflow", "Weekly prompt cleanup routine", "Every Friday, archive unused prompts, rename useful ones, and add example inputs for prompts worth keeping.", "Audit this prompt library. Group by use case, remove duplicates, rename unclear prompts, and mark top 10 reusable prompts.", "Notion + GPT", ["prompt-library", "ops", "cleanup"]),
        ("maya-builds", "Prompt", "Meeting transcript to decision log", "Turns long meeting transcripts into decisions, owners, and follow-up emails.", "Extract decisions, rejected options, action owners, deadlines, and a follow-up email draft from this transcript.", "Whisper + GPT", ["meetings", "decisions", "email"]),
        ("jonpromptlab", "Idea", "Prompt profiles should show strongest use cases", "Instead of a generic bio, creator profiles should show what kinds of prompts the person is best at.", "", "Product idea", ["profiles", "creators", "ux"]),
        ("arisignal", "Prompt", "Bug report to reproduction checklist", "Paste a messy bug report and receive exact repro steps plus logs or screenshots to request.", "Convert this bug report into repro steps, expected/actual result, likely area, and missing evidence to request.", "GPT", ["bugs", "qa", "support"]),
        ("maya-builds", "Workflow", "AI assistant for schematic review notes", "A process for turning schematic screenshots and comments into a review summary and action list.", "Review these schematic notes. Separate confirmed issues, questions, component value checks, and follow-up emails.", "Vision model", ["hardware", "schematic", "review"]),
        ("jonpromptlab", "Prompt", "Customer interview synthesis prompt", "Find repeated pain points and quote evidence without making the summary too generic.", "Cluster these interview notes by pain point. Include frequency, representative quote, and product implication.", "Claude", ["research", "customers", "product"]),
        ("arisignal", "Idea", "Saved prompts need private notes", "Saving is not enough. Users should be able to add why they saved a prompt and where they plan to use it.", "", "Product idea", ["saved", "notes", "workflow"]),
        ("maya-builds", "Prompt", "Make a rough SOP from tribal knowledge", "Paste informal instructions and get a clear SOP with scope, prerequisites, steps, and checks.", "Turn this rough process into an SOP with purpose, scope, prerequisites, steps, failure checks, and owner.", "GPT", ["sop", "process", "ops"]),
        ("jonpromptlab", "Workflow", "RSS to AI trend board", "Collect links from RSS, cluster by topic, and draft a short explanation of why each cluster matters.", "Cluster these links, title each cluster, explain why it matters, and rank by practical usefulness.", "RSS + OpenAI", ["trends", "rss", "newsletter"]),
        ("arisignal", "Prompt", "Ask better follow-up questions", "Use this when someone sends a vague request and you need focused clarifying questions.", "Given this request, ask up to 5 clarifying questions. Prioritize questions that change the implementation.", "GPT", ["questions", "planning", "work"]),
        ("maya-builds", "Idea", "Prompt posts should show required inputs", "Each prompt should list exactly what the user needs to provide before it can work well.", "", "Community format", ["prompting", "inputs", "quality"]),
        ("jonpromptlab", "Prompt", "Executive summary from noisy data", "Turns noisy tables or notes into a short leadership-ready summary with confidence level.", "Summarize this data for leadership. Include headline, evidence, caveats, confidence, and recommended next step.", "OpenAI API", ["summary", "data", "leadership"]),
        ("arisignal", "Workflow", "Personal AI inbox zero", "A daily routine for sorting messages into reply now, delegate, schedule, and ignore.", "Classify these messages into reply, delegate, schedule, archive. Draft replies for the reply bucket.", "Email + GPT", ["email", "productivity", "workflow"]),
        ("maya-builds", "Prompt", "Design QA checklist from screenshot", "Use a screenshot to catch layout overlap, text fit, missing states, and visual hierarchy issues.", "Inspect this screenshot for UI bugs. Focus on overlap, text truncation, spacing, hierarchy, and missing states.", "Vision model", ["design", "qa", "frontend"]),
        ("jonpromptlab", "Idea", "Prompt forks need changelogs", "When someone improves a prompt, the feed should show what changed and why it works better.", "", "Product idea", ["forks", "prompting", "community"]),
        ("arisignal", "Prompt", "Translate technical notes into plain English", "Great for converting dense engineering updates into a readable cross-functional note.", "Rewrite this technical update for a cross-functional audience. Keep facts precise and remove jargon where possible.", "GPT", ["writing", "technical", "communication"]),
        ("jonpromptlab", "Workflow", "Morning AI news brief from raw links", "Turn a pile of AI headlines into a concise news brief with what changed, why it matters, and what to ignore.", "Summarize these AI news links into five bullets. For each bullet include the source event, what changed, practical impact, and one caveat.", "RSS + OpenAI", ["ai-news", "news", "briefing"]),
        ("maya-builds", "Idea", "AI games should adapt difficulty from player intent", "Instead of fixed levels, an AI game can ask what kind of challenge the player wants and tune story, hints, and stakes in real time.", "", "Game design", ["ai-games", "games", "design"]),
        ("arisignal", "Prompt", "Turn rough user complaints into actionable feedback", "Use this to transform messy comments into issue themes, severity, and a clearer product recommendation.", "Analyze this user feedback. Group it into themes, estimate urgency, include one quote per theme, and suggest the best product response.", "GPT", ["feedback", "product", "users"]),
        ("jonpromptlab", "Prompt", "Break one AI story into operator takeaways", "Use this when one big model release lands and you need the practical implications, not hype.", "Read this AI news item and return: what changed, who benefits first, operational risks, and one action to take this week.", "GPT", ["ai-news", "analysis", "operators"]),
        ("maya-builds", "Workflow", "Competitive watchlist for AI product launches", "Track launches across labs and startups, then rank them by likely effect on your roadmap.", "Compare these AI launches by capability, pricing, integration friction, and which teams should care.", "Sheets + GPT", ["ai-news", "market", "tracking"]),
        ("arisignal", "Idea", "AI news should show second-order effects", "The best AI news summary is not the announcement itself. It is what teams now have to change because of it.", "", "Editorial format", ["ai-news", "strategy", "commentary"]),
        ("jonpromptlab", "Workflow", "NPC banter generator for AI games", "Generate short in-world dialogue that changes based on player choices and tone.", "Write branching NPC dialogue for this scene. Track player tone, prior choices, and one hidden clue in each branch.", "Narrative model", ["ai-games", "dialogue", "writing"]),
        ("maya-builds", "Prompt", "Prototype a text-based AI mystery game loop", "Sketch a compact game loop with clues, suspicion, consequences, and escalating stakes.", "Design a replayable AI mystery game with core loop, clue economy, failure states, and three escalating scenes.", "GPT", ["ai-games", "prototype", "design"]),
        ("arisignal", "Idea", "AI games need visible memory, not fake memory", "Players trust AI games more when the system shows what it remembers and lets them correct it.", "", "Game systems", ["ai-games", "ux", "systems"]),
        ("jonpromptlab", "Prompt", "Turn patch notes into AI news bullets", "Compress long release notes into a readable update for busy product or engineering leads.", "Summarize these patch notes into headline changes, hidden implications, migration work, and who should pay attention.", "OpenAI API", ["ai-news", "release-notes", "summary"]),
        ("maya-builds", "Workflow", "Dynamic quest generator for AI co-op games", "Generate quests that respond to party composition, inventory, and recent failures so sessions feel less scripted.", "Create three adaptive quests for this co-op party. Use their abilities, last two failures, and one surprise reward.", "Game engine + model", ["ai-games", "quests", "co-op"]),
        ("jonpromptlab", "Workflow", "AI YouTube roundup into one daily brief", "Pull the key claims from several AI YouTube videos and collapse them into one short update without repeating hype.", "Review these AI YouTube transcripts. Extract the real product, model, or tooling news, remove repeated talking points, and return a concise daily brief.", "YouTube transcripts + GPT", ["ai-news", "youtube", "briefing"]),
        ("maya-builds", "Prompt", "Magazine article to executive AI summary", "Turn a long AI magazine feature into a crisp summary for operators who do not have time to read the full piece.", "Summarize this AI magazine article into: headline takeaway, what changed, why it matters to teams, and one risk worth watching.", "GPT", ["ai-news", "magazine", "executive"]),
        ("arisignal", "Idea", "High-tech AI coverage should separate signal from product theater", "Too much AI reporting repeats launch language. Better coverage shows what shipped, what is still a demo, and what users can test today.", "", "Editorial format", ["ai-news", "high-tech", "analysis"]),
        ("jonpromptlab", "Prompt", "Research lab announcement triage", "Use this when OpenAI, Google DeepMind, Anthropic, or another lab publishes a release and you need the practical implications fast.", "Read this research lab announcement and return: claimed advance, what appears genuinely new, likely limitations, and which teams should care first.", "GPT", ["ai-news", "research-labs", "triage"]),
        ("maya-builds", "Workflow", "Cross-source AI news board", "Merge YouTube, magazine, research blog, and tech site coverage into one ranked board so you can see where sources agree or conflict.", "Combine these AI news sources, cluster them by story, mark source type, and rank stories by practical importance for builders.", "RSS + GPT", ["ai-news", "sources", "dashboard"]),
        ("arisignal", "Prompt", "VC memo from one week of AI launches", "Turn a noisy week of launches into an investor-style memo with market signals, weak claims, and likely winners.", "Review this week's AI launches and write a memo with category shifts, credible traction signals, pricing pressure, and what looks overhyped.", "GPT", ["ai-news", "market", "investing"]),
        ("jonpromptlab", "Workflow", "Conference keynote to shipping reality", "Reduce conference announcements into what actually shipped, what is roadmap theater, and what teams can test now.", "Break this keynote into shipped now, private beta, vague roadmap, and likely operational impact for builders.", "YouTube + GPT", ["ai-news", "events", "analysis"]),
        ("maya-builds", "Prompt", "AI rumor filter for operators", "Useful when timelines are noisy and teams need a grounded read on whether a story matters yet.", "Assess this AI rumor and return credibility, likely source motivation, what to watch next, and whether a team should react now.", "GPT", ["ai-news", "rumors", "operators"]),
        ("arisignal", "Idea", "AI news feeds should rank by deployment impact", "A story matters more when it changes budgets, hiring, infra, or customer expectations, not when it just gets clicks.", "", "Editorial format", ["ai-news", "ranking", "strategy"]),
        ("jonpromptlab", "Prompt", "Open-source model release quick read", "Condense a model release into benchmark caveats, hardware needs, and likely real-world fit.", "Summarize this open-source model release into benchmark signal, serving cost, context window tradeoffs, and best-fit use cases.", "OpenAI API", ["ai-news", "open-source", "models"]),
        ("maya-builds", "Workflow", "Daily AI regulation watcher", "Track policy, export controls, copyright cases, and standards updates without flooding the team.", "Summarize these AI policy links into decision risk, likely timeline, who is affected, and what product teams should prepare.", "RSS + GPT", ["ai-news", "policy", "tracking"]),
        ("arisignal", "Prompt", "Product launch comparison board", "Compare multiple AI releases in one table so product and engineering can see where the real gaps are.", "Compare these AI launches by differentiation, reliability claims, integration cost, enterprise fit, and likely adoption speed.", "Claude", ["ai-news", "launches", "comparison"]),
        ("jonpromptlab", "Workflow", "AI podcast roundup into one operator digest", "Pull concrete product and tooling signal from several AI podcasts and strip out repeated talking points.", "Review these AI podcast transcripts and return only product, tooling, and go-to-market signal worth sharing internally.", "Transcripts + GPT", ["ai-news", "podcasts", "briefing"]),
        ("maya-builds", "Idea", "AI news posts should include test instructions", "Every big story is more useful if readers know exactly what they can try today and what they still cannot verify.", "", "Editorial format", ["ai-news", "testing", "product"]),
        ("arisignal", "Prompt", "Earnings call AI signal extractor", "Find the real AI adoption clues in public company earnings calls without repeating generic CEO language.", "Extract AI-related claims from this earnings call. Mark direct product impact, pricing signal, hiring implication, and confidence level.", "GPT", ["ai-news", "earnings", "analysis"]),
        ("jonpromptlab", "Workflow", "AI acquisition watchlist", "Track acquihires, model infra deals, and strategic buys to see where the stack is consolidating.", "Summarize these AI acquisitions by category, talent motive, distribution value, and likely roadmap consequence.", "Sheets + GPT", ["ai-news", "m-and-a", "tracking"]),
        ("maya-builds", "Prompt", "Branching dialogue stress test for AI companions", "Push an AI companion system through conflicting moods, memory callbacks, and abrupt tone shifts.", "Write a dialogue stress test with five player tone changes, three memory callbacks, and one contradiction trap.", "Narrative model", ["ai-games", "dialogue", "testing"]),
        ("arisignal", "Idea", "AI games should expose model confidence to players", "If a scene, clue, or memory is low confidence, the game can turn that uncertainty into play instead of hiding it.", "", "Game systems", ["ai-games", "ux", "confidence"]),
        ("jonpromptlab", "Workflow", "Procedural town gossip engine", "Generate rumors, small quests, and social dynamics that evolve based on what the player already disrupted.", "Create a town gossip system with three factions, six rumor threads, and updates after each player decision.", "Game engine + model", ["ai-games", "worldbuilding", "systems"]),
        ("maya-builds", "Prompt", "Design an AI courtroom deduction game", "Prototype a courtroom loop with testimony gaps, bluffing, evidence pressure, and escalating reveals.", "Design a replayable AI courtroom game with witness contradiction mechanics, evidence economy, and late-case twists.", "GPT", ["ai-games", "prototype", "deduction"]),
        ("arisignal", "Prompt", "AI game retention loop critique", "Review an AI game concept for novelty drop-off, replay hooks, and what keeps players returning after the first session.", "Critique this AI game concept for retention. Cover first-session wow, repeatability, progression, and social hooks.", "Claude", ["ai-games", "retention", "design"]),
        ("jonpromptlab", "Workflow", "Adaptive boss encounter generator", "Create bosses that change attack patterns, dialogue, and weaknesses based on how the player learned the last fight.", "Generate three adaptive boss encounters using this player history, inventory, and prior failure pattern.", "Game engine + model", ["ai-games", "combat", "systems"]),
        ("maya-builds", "Idea", "AI games need visible world state changes", "Players believe the AI mattered when they can see the village, crew, or map react to earlier choices.", "", "Game design", ["ai-games", "world-state", "design"]),
        ("arisignal", "Workflow", "AI escape-room puzzle sequencer", "Sequence clues so puzzle difficulty flexes with player success while preserving a coherent mystery.", "Build an adaptive escape-room chain with clue gating, hint thresholds, red herrings, and fail-forward design.", "Puzzle engine + model", ["ai-games", "puzzles", "adaptive"]),
        ("jonpromptlab", "Prompt", "Companion memory repair prompt", "Use this when a companion model forgets key facts and you need a graceful in-world recovery.", "Repair this AI companion memory state. Preserve tone, restate known facts naturally, and avoid immersion-breaking exposition.", "GPT", ["ai-games", "memory", "writing"]),
        ("maya-builds", "Workflow", "Roguelike event writer for AI factions", "Generate events tied to faction grudges, scarce resources, and long-term consequences across runs.", "Write eight roguelike events for these factions. Include one dilemma, one scarce resource tradeoff, and one long-tail consequence each.", "Narrative model", ["ai-games", "roguelike", "events"]),
        ("arisignal", "Idea", "AI game prompts should ship with moderation boundaries", "If players can improvise anything, the design should define what the world refuses, redirects, or transforms.", "", "Game systems", ["ai-games", "safety", "systems"]),
        ("jonpromptlab", "Prompt", "Sandbox AI creature behavior pack", "Create creature personalities, needs, and reactions that stay legible to players instead of feeling random.", "Design four AI creature behavior profiles with needs, triggers, social bonds, and readable failure behaviors.", "Game engine + model", ["ai-games", "creatures", "simulation"]),
        ("maya-builds", "Workflow", "Live ops event planner for AI games", "Plan weekly events that remix existing mechanics, nudge social play, and surface overlooked systems.", "Generate a four-week live ops plan for this AI game with event theme, player goal, reward logic, and reuse of existing assets.", "Sheets + GPT", ["ai-games", "live-ops", "planning"]),
    ]
    base_time = datetime(2026, 5, 1, 12, 0, 0)
    for idx, (handle, kind, title, summary, prompt_text, tool_name, tags) in enumerate(demo_posts):
        existing = db.execute("SELECT id FROM posts WHERE title = ?", (title,)).fetchone()
        if existing:
            continue
        cursor = db.execute(
            """
            INSERT INTO posts (user_id, kind, title, summary, prompt_text, tool_name, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_map[handle],
                kind,
                title,
                summary,
                prompt_text,
                tool_name,
                (base_time - timedelta(minutes=idx * 37)).strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        post_id = cursor.lastrowid
        for tag in tags:
            db.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
            tag_id = db.execute("SELECT id FROM tags WHERE name = ?", (tag,)).fetchone()["id"]
            db.execute("INSERT OR IGNORE INTO post_tags (post_id, tag_id) VALUES (?, ?)", (post_id, tag_id))
        if idx % 2 == 0:
            db.execute("INSERT INTO likes (post_id, created_at) VALUES (?, ?)", (post_id, "2026-05-01 13:00:00"))
        if idx % 5 == 0:
            db.execute(
                "INSERT INTO comments (post_id, author_name, body, created_at) VALUES (?, ?, ?, ?)",
                (post_id, "Demo Reader", "Useful pattern. I would save this for later.", "2026-05-01 13:15:00"),
            )
    db.commit()


def parse_tags(raw_tags: str) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for item in raw_tags.split(","):
        tag = item.strip().lower().replace(" ", "-")
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags[:6]


def slugify_handle(raw_value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in raw_value.strip())
    parts = [part for part in cleaned.split("-") if part]
    return "-".join(parts)[:30]


def fetch_user_by_email(email: str) -> sqlite3.Row | None:
    return get_db().execute(
        "SELECT id, name, handle, email, password_hash, bio, accent FROM users WHERE email = ?",
        (email.lower().strip(),),
    ).fetchone()


def fetch_user_by_id(user_id: int | None) -> sqlite3.Row | None:
    if not user_id:
        return None
    return get_db().execute(
        "SELECT id, name, handle, email, bio, accent FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()


def current_user() -> sqlite3.Row | None:
    return getattr(g, "current_user", None)


@app.before_request
def load_current_user() -> None:
    user_id = session.get("user_id")
    g.current_user = fetch_user_by_id(user_id)


@app.context_processor
def inject_globals() -> dict:
    return {"current_user": current_user()}


def require_login():
    if current_user() is None:
        flash("Please sign in to do that.", "error")
        return redirect(url_for("home"))
    return None


def is_following(follower_id: int, followed_id: int) -> bool:
    if follower_id == followed_id:
        return False
    row = get_db().execute(
        "SELECT 1 FROM follows WHERE follower_id = ? AND followed_id = ?",
        (follower_id, followed_id),
    ).fetchone()
    return row is not None


def saved_post_ids(user_id: int | None) -> set[int]:
    if not user_id:
        return set()
    rows = get_db().execute(
        "SELECT post_id FROM saves WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    return {row["post_id"] for row in rows}


def attach_tags(posts: list[sqlite3.Row]) -> list[dict]:
    if not posts:
        return []
    db = get_db()
    post_ids = [post["id"] for post in posts]
    placeholders = ",".join("?" for _ in post_ids)
    tag_rows = db.execute(
        f"""
        SELECT pt.post_id, t.name
        FROM post_tags pt
        JOIN tags t ON t.id = pt.tag_id
        WHERE pt.post_id IN ({placeholders})
        ORDER BY t.name
        """,
        post_ids,
    ).fetchall()
    tags_by_post: dict[int, list[str]] = {post_id: [] for post_id in post_ids}
    for row in tag_rows:
        tags_by_post[row["post_id"]].append(row["name"])

    comment_rows = db.execute(
        f"""
        SELECT post_id, author_name, body, created_at
        FROM comments
        WHERE post_id IN ({placeholders})
        ORDER BY created_at DESC
        """,
        post_ids,
    ).fetchall()
    comments_by_post: dict[int, list[dict]] = {post_id: [] for post_id in post_ids}
    for row in comment_rows:
        comments_by_post[row["post_id"]].append(dict(row))

    saved_ids = saved_post_ids(current_user()["id"] if current_user() else None)

    enriched: list[dict] = []
    for post in posts:
        item = dict(post)
        item["tags"] = tags_by_post.get(post["id"], [])
        item["comments"] = comments_by_post.get(post["id"], [])
        item["is_saved"] = post["id"] in saved_ids
        enriched.append(item)
    return enriched


def base_post_query() -> str:
    return """
        SELECT
            p.id,
            p.kind,
            p.title,
            p.summary,
            p.prompt_text,
            p.tool_name,
            p.created_at,
            u.name,
            u.handle,
            u.accent,
            COALESCE(l.like_count, 0) AS like_count,
            COALESCE(c.comment_count, 0) AS comment_count,
            COALESCE(s.save_count, 0) AS save_count,
            (
                COALESCE(l.like_count, 0) * 3
                + COALESCE(c.comment_count, 0) * 5
                + COALESCE(s.save_count, 0) * 4
                + CASE
                    WHEN julianday('now') - julianday(p.created_at) < 1 THEN 8
                    WHEN julianday('now') - julianday(p.created_at) < 3 THEN 4
                    ELSE 0
                  END
            ) AS trend_score
        FROM posts p
        JOIN users u ON u.id = p.user_id
        LEFT JOIN (
            SELECT post_id, COUNT(*) AS like_count
            FROM likes
            GROUP BY post_id
        ) l ON l.post_id = p.id
        LEFT JOIN (
            SELECT post_id, COUNT(*) AS comment_count
            FROM comments
            GROUP BY post_id
        ) c ON c.post_id = p.id
        LEFT JOIN (
            SELECT post_id, COUNT(*) AS save_count
            FROM saves
            GROUP BY post_id
        ) s ON s.post_id = p.id
    """


def fetch_posts(
    sort_mode: str = "latest",
    query: str = "",
    tag: str = "",
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    db = get_db()
    sql = base_post_query()
    conditions: list[str] = []
    params: list[str] = []

    if query:
        conditions.append(
            """
            (
                p.title LIKE ?
                OR p.summary LIKE ?
                OR p.prompt_text LIKE ?
                OR EXISTS (
                    SELECT 1
                    FROM post_tags pt2
                    JOIN tags t2 ON t2.id = pt2.tag_id
                    WHERE pt2.post_id = p.id
                      AND t2.name LIKE ?
                )
            )
            """
        )
        needle = f"%{query}%"
        params.extend([needle, needle, needle, needle])

    if tag:
        conditions.append(
            """
            EXISTS (
                SELECT 1
                FROM post_tags pt3
                JOIN tags t3 ON t3.id = pt3.tag_id
                WHERE pt3.post_id = p.id
                  AND t3.name = ?
            )
            """
        )
        params.append(tag)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    order = "ORDER BY trend_score DESC, p.created_at DESC" if sort_mode == "trending" else "ORDER BY p.created_at DESC"
    sql = f"{sql} {order}"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    rows = db.execute(sql, params).fetchall()
    return attach_tags(rows)


def fetch_following_posts(
    user_id: int,
    sort_mode: str = "latest",
    query: str = "",
    tag: str = "",
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    db = get_db()
    sql = base_post_query()
    conditions = [
        """
        EXISTS (
            SELECT 1 FROM follows f
            WHERE f.followed_id = p.user_id
              AND f.follower_id = ?
        )
        """
    ]
    params: list[str] = [user_id]

    if query:
        needle = f"%{query}%"
        conditions.append(
            """
            (
                p.title LIKE ?
                OR p.summary LIKE ?
                OR p.prompt_text LIKE ?
                OR EXISTS (
                    SELECT 1
                    FROM post_tags pt2
                    JOIN tags t2 ON t2.id = pt2.tag_id
                    WHERE pt2.post_id = p.id
                      AND t2.name LIKE ?
                )
            )
            """
        )
        params.extend([needle, needle, needle, needle])

    if tag:
        conditions.append(
            """
            EXISTS (
                SELECT 1
                FROM post_tags pt3
                JOIN tags t3 ON t3.id = pt3.tag_id
                WHERE pt3.post_id = p.id
                  AND t3.name = ?
            )
            """
        )
        params.append(tag)

    sql += " WHERE " + " AND ".join(conditions)
    order = "ORDER BY trend_score DESC, p.created_at DESC" if sort_mode == "trending" else "ORDER BY p.created_at DESC"
    sql = f"{sql} {order}"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    rows = db.execute(sql, params).fetchall()
    return attach_tags(rows)


def fetch_creators() -> list[sqlite3.Row]:
    return get_db().execute(
        "SELECT id, name, handle FROM users ORDER BY name"
    ).fetchall()


def fetch_profile(handle: str) -> tuple[sqlite3.Row | None, list[dict], dict]:
    db = get_db()
    user = db.execute(
        "SELECT id, name, handle, bio, accent FROM users WHERE handle = ?",
        (handle,),
    ).fetchone()
    if user is None:
        return None, [], {}
    rows = db.execute(
        f"{base_post_query()} WHERE u.handle = ? ORDER BY p.created_at DESC",
        (handle,),
    ).fetchall()
    stats = {
        "followers": db.execute(
            "SELECT COUNT(*) AS count FROM follows WHERE followed_id = ?",
            (user["id"],),
        ).fetchone()["count"],
        "following": db.execute(
            "SELECT COUNT(*) AS count FROM follows WHERE follower_id = ?",
            (user["id"],),
        ).fetchone()["count"],
        "saved_posts": db.execute(
            "SELECT COUNT(*) AS count FROM saves WHERE user_id = ?",
            (user["id"],),
        ).fetchone()["count"],
        "is_followed": bool(current_user() and is_following(current_user()["id"], user["id"])),
    }
    return user, attach_tags(rows), stats


def fetch_top_tags(limit: int = 8) -> list[sqlite3.Row]:
    return get_db().execute(
        """
        SELECT t.name, COUNT(*) AS usage_count
        FROM tags t
        JOIN post_tags pt ON pt.tag_id = t.id
        GROUP BY t.id
        ORDER BY usage_count DESC, t.name ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def fetch_stats() -> dict[str, int]:
    db = get_db()
    return {
        "posts": db.execute("SELECT COUNT(*) AS count FROM posts").fetchone()["count"],
        "creators": db.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"],
        "likes": db.execute("SELECT COUNT(*) AS count FROM likes").fetchone()["count"],
        "comments": db.execute("SELECT COUNT(*) AS count FROM comments").fetchone()["count"],
    }


def fetch_saved_posts(user_id: int) -> list[dict]:
    rows = get_db().execute(
        f"""
        {base_post_query()}
        WHERE EXISTS (
            SELECT 1 FROM saves sv
            WHERE sv.post_id = p.id AND sv.user_id = ?
        )
        ORDER BY p.created_at DESC
        """,
        (user_id,),
    ).fetchall()
    return attach_tags(rows)


def fetch_recent_feedback(limit: int = 5) -> list[sqlite3.Row]:
    if current_user() is None:
        return []
    return get_db().execute(
        """
        SELECT topic, message, created_at
        FROM feedback_messages
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (current_user()["id"], limit),
    ).fetchall()


def render_feed_page(
    *,
    posts: list[dict],
    active_sort: str,
    search_query: str,
    active_tag: str,
    auth_mode: str,
    page_title: str,
    page_description: str,
    active_view: str,
    active_section: str = "latest",
):
    return render_template(
        "feed.html",
        posts=posts,
        creators=fetch_creators(),
        stats=fetch_stats(),
        top_tags=fetch_top_tags(),
        active_sort=active_sort,
        search_query=search_query,
        active_tag=active_tag,
        auth_mode=auth_mode,
        saved_posts=fetch_saved_posts(current_user()["id"]) if current_user() else [],
        page_title=page_title,
        page_description=page_description,
        active_view=active_view,
        active_section=active_section,
        page_size=PAGE_SIZE,
    )


def render_topic_page(
    *,
    tag: str,
    page_title: str,
    page_description: str,
    active_section: str,
):
    sort_mode = request.args.get("sort", "latest")
    query = request.args.get("q", "").strip()
    posts = fetch_posts(sort_mode=sort_mode, query=query, tag=tag, limit=PAGE_SIZE)
    return render_feed_page(
        posts=posts,
        active_sort=sort_mode,
        search_query=query,
        active_tag=tag,
        auth_mode=request.args.get("auth", "").strip(),
        page_title=page_title,
        page_description=page_description,
        active_view="global",
        active_section=active_section,
    )


@app.post("/auth/signup")
def signup():
    db = get_db()
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()
    handle = slugify_handle(request.form.get("handle", "") or name)

    if not name or not email or not password or not handle:
        flash("Name, handle, email, and password are required.", "error")
        return redirect(url_for("home"))
    if len(password) < 6:
        flash("Use at least 6 characters for the password.", "error")
        return redirect(url_for("home"))
    if fetch_user_by_email(email) is not None:
        flash("That email already has an account.", "error")
        return redirect(url_for("home"))
    if db.execute("SELECT 1 FROM users WHERE handle = ?", (handle,)).fetchone():
        flash("That handle is already taken.", "error")
        return redirect(url_for("home"))

    cursor = db.execute(
        """
        INSERT INTO users (name, handle, email, password_hash, bio, accent)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            handle,
            email,
            make_password_hash(password),
            "New creator. Add a sharper bio next.",
            "#7c3aed",
        ),
    )
    db.commit()
    session["user_id"] = cursor.lastrowid
    flash("Account created. You are signed in.", "success")
    return redirect(url_for("home"))


@app.post("/auth/login")
def login():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()
    user = fetch_user_by_email(email)
    if user is None or not user["password_hash"] or not check_password_hash(user["password_hash"], password):
        flash("Wrong email or password.", "error")
        return redirect(url_for("home"))
    session["user_id"] = user["id"]
    flash(f"Welcome back, {user['name']}.", "success")
    return redirect(url_for("home"))


@app.post("/auth/reset-password")
def reset_password():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()
    if not email or not password:
        flash("Email and new password are required.", "error")
        return redirect(url_for("home", auth="reset"))
    if len(password) < 6:
        flash("Use at least 6 characters for the new password.", "error")
        return redirect(url_for("home", auth="reset"))
    user = fetch_user_by_email(email)
    if user is None:
        flash("No account found for that email.", "error")
        return redirect(url_for("home", auth="reset"))
    db = get_db()
    db.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (make_password_hash(password), user["id"]),
    )
    db.commit()
    flash("Password reset. You can log in with the new password.", "success")
    return redirect(url_for("home", auth="login"))


@app.post("/auth/logout")
def logout():
    session.pop("user_id", None)
    flash("Signed out.", "success")
    return redirect(url_for("home"))


@app.route("/")
def home():
    sort_mode = request.args.get("sort", "latest")
    query = request.args.get("q", "").strip()
    tag = request.args.get("tag", "").strip().lower()
    posts = fetch_posts(sort_mode=sort_mode, query=query, tag=tag, limit=PAGE_SIZE)
    return render_feed_page(
        posts=posts,
        active_sort=sort_mode,
        search_query=query,
        active_tag=tag,
        auth_mode=request.args.get("auth", "").strip(),
        page_title="Global feed",
        page_description="See the broadest mix of AI ideas, prompt drops, and workflow teardowns from the whole community.",
        active_view="global",
        active_section="trending" if sort_mode == "trending" else "latest",
    )


@app.route("/following")
def following_feed():
    if (redirect_response := require_login()) is not None:
        return redirect_response
    sort_mode = request.args.get("sort", "latest")
    query = request.args.get("q", "").strip()
    tag = request.args.get("tag", "").strip().lower()
    posts = fetch_following_posts(current_user()["id"], sort_mode=sort_mode, query=query, tag=tag, limit=PAGE_SIZE)
    return render_feed_page(
        posts=posts,
        active_sort=sort_mode,
        search_query=query,
        active_tag=tag,
        auth_mode=request.args.get("auth", "").strip(),
        page_title="Following",
        page_description="A tighter feed from creators you chose to follow.",
        active_view="following",
        active_section="following",
    )


@app.route("/news")
def news_feed():
    return render_topic_page(
        tag="ai-news",
        page_title="AI news",
        page_description="AI news from YouTube creators, magazines, research labs, and high-tech publications, filtered for what actually matters.",
        active_section="news",
    )


@app.route("/games")
def games_feed():
    return render_topic_page(
        tag="ai-games",
        page_title="AI games",
        page_description="Experiments, mini products, and playful builds where AI is the core game mechanic.",
        active_section="games",
    )


@app.route("/feedback")
def feedback_feed():
    return render_template(
        "feedback.html",
        page_title="Feedback",
        page_description="Send product feedback directly to the site owner. Share bugs, feature requests, or anything confusing.",
        active_view="feedback",
        active_section="feedback",
        search_query="",
        auth_mode="",
        recent_feedback=fetch_recent_feedback(),
    )


@app.post("/feedback")
def submit_feedback():
    db = get_db()
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    topic = request.form.get("topic", "").strip()
    message = request.form.get("message", "").strip()

    if not name or not topic or not message:
        flash("Name, topic, and feedback message are required.", "error")
        return redirect(url_for("feedback_feed"))

    db.execute(
        """
        INSERT INTO feedback_messages (user_id, name, email, topic, message, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            current_user()["id"] if current_user() else None,
            name,
            email,
            topic,
            message,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    db.commit()
    flash("Feedback sent to the owner.", "success")
    return redirect(url_for("feedback_feed"))


@app.get("/api/posts")
def api_posts():
    view = request.args.get("view", "global")
    sort_mode = request.args.get("sort", "latest")
    query = request.args.get("q", "").strip()
    tag = request.args.get("tag", "").strip().lower()
    try:
        offset = max(0, int(request.args.get("offset", PAGE_SIZE)))
        limit = max(1, min(20, int(request.args.get("limit", PAGE_SIZE))))
    except ValueError:
        offset = PAGE_SIZE
        limit = PAGE_SIZE

    if view == "following":
        if current_user() is None:
            return jsonify({"html": "", "next_offset": offset, "has_more": False})
        posts = fetch_following_posts(
            current_user()["id"],
            sort_mode=sort_mode,
            query=query,
            tag=tag,
            limit=limit + 1,
            offset=offset,
        )
    else:
        posts = fetch_posts(
            sort_mode=sort_mode,
            query=query,
            tag=tag,
            limit=limit + 1,
            offset=offset,
        )

    visible_posts = posts[:limit]
    html = "".join(
        render_template("_post_card.html", post=post, active_sort=sort_mode)
        for post in visible_posts
    )
    return jsonify(
        {
            "html": html,
            "next_offset": offset + len(visible_posts),
            "has_more": len(posts) > limit,
        }
    )


@app.route("/saved")
def saved_feed():
    if (redirect_response := require_login()) is not None:
        return redirect_response
    posts = fetch_saved_posts(current_user()["id"])
    return render_feed_page(
        posts=posts,
        active_sort="latest",
        search_query="",
        active_tag="",
        auth_mode=request.args.get("auth", "").strip(),
        page_title="Saved library",
        page_description="Your personal collection of prompts, ideas, and workflows worth revisiting.",
        active_view="saved",
        active_section="saved",
    )


@app.route("/profile/<handle>")
def profile(handle: str):
    user, posts, profile_stats = fetch_profile(handle)
    if user is None:
        return redirect(url_for("home"))
    return render_template(
        "profile.html",
        user=user,
        posts=posts,
        profile_stats=profile_stats,
        stats=fetch_stats(),
        top_tags=fetch_top_tags(),
        search_query="",
        active_tag="",
        active_sort="latest",
        auth_mode="",
        active_view="profile",
        active_section="profile",
        saved_posts=fetch_saved_posts(current_user()["id"]) if current_user() else [],
    )


@app.post("/posts")
def create_post():
    if (redirect_response := require_login()) is not None:
        return redirect_response
    db = get_db()
    user_id = current_user()["id"]
    kind = request.form["kind"].strip() or "Idea"
    title = request.form.get("title", "").strip()
    summary = request.form["summary"].strip()
    prompt_text = request.form.get("prompt_text", "").strip()
    tool_name = request.form.get("tool_name", "").strip()
    tags = parse_tags(request.form.get("tags", ""))
    if not title and summary:
        first_line = summary.splitlines()[0].strip()
        title = first_line[:90] + ("..." if len(first_line) > 90 else "")
    if not title and prompt_text:
        title = "Shared AI prompt"

    if title and summary:
        cursor = db.execute(
            """
            INSERT INTO posts (user_id, kind, title, summary, prompt_text, tool_name, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, kind, title, summary, prompt_text, tool_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        post_id = cursor.lastrowid
        for tag in tags:
            db.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
            tag_id = db.execute("SELECT id FROM tags WHERE name = ?", (tag,)).fetchone()["id"]
            db.execute("INSERT OR IGNORE INTO post_tags (post_id, tag_id) VALUES (?, ?)", (post_id, tag_id))
        db.commit()
        flash("Post published to the feed.", "success")
    return redirect(url_for("home"))


@app.post("/posts/<int:post_id>/like")
def like_post(post_id: int):
    if (redirect_response := require_login()) is not None:
        return redirect_response
    db = get_db()
    db.execute(
        "INSERT INTO likes (post_id, created_at) VALUES (?, ?)",
        (post_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    db.commit()
    return redirect(request.referrer or url_for("home"))


@app.post("/posts/<int:post_id>/save")
def save_post(post_id: int):
    if (redirect_response := require_login()) is not None:
        return redirect_response
    db = get_db()
    row = db.execute(
        "SELECT 1 FROM saves WHERE user_id = ? AND post_id = ?",
        (current_user()["id"], post_id),
    ).fetchone()
    if row:
        db.execute(
            "DELETE FROM saves WHERE user_id = ? AND post_id = ?",
            (current_user()["id"], post_id),
        )
    else:
        db.execute(
            "INSERT INTO saves (user_id, post_id, created_at) VALUES (?, ?, ?)",
            (current_user()["id"], post_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
    db.commit()
    return redirect(request.referrer or url_for("home"))


@app.post("/profile/<handle>/follow")
def follow_creator(handle: str):
    if (redirect_response := require_login()) is not None:
        return redirect_response
    db = get_db()
    user = db.execute(
        "SELECT id FROM users WHERE handle = ?",
        (handle,),
    ).fetchone()
    if user is None or user["id"] == current_user()["id"]:
        return redirect(request.referrer or url_for("home"))
    row = db.execute(
        "SELECT 1 FROM follows WHERE follower_id = ? AND followed_id = ?",
        (current_user()["id"], user["id"]),
    ).fetchone()
    if row:
        db.execute(
            "DELETE FROM follows WHERE follower_id = ? AND followed_id = ?",
            (current_user()["id"], user["id"]),
        )
    else:
        db.execute(
            "INSERT INTO follows (follower_id, followed_id, created_at) VALUES (?, ?, ?)",
            (current_user()["id"], user["id"], datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
    db.commit()
    return redirect(request.referrer or url_for("profile", handle=handle))


@app.post("/posts/<int:post_id>/comment")
def comment_post(post_id: int):
    if (redirect_response := require_login()) is not None:
        return redirect_response
    author_name = current_user()["name"]
    body = request.form.get("body", "").strip()
    if body:
        db = get_db()
        db.execute(
            "INSERT INTO comments (post_id, author_name, body, created_at) VALUES (?, ?, ?, ?)",
            (post_id, author_name, body, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        db.commit()
    return redirect(request.referrer or url_for("home"))


with app.app_context():
    init_db()
    ensure_seed_data()
    ensure_more_demo_posts()


if __name__ == "__main__":
    debug_enabled = os.environ.get("FLASK_DEBUG", "").lower() in {"1", "true", "yes"}
    app.run(
        debug=debug_enabled,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5055")),
    )
