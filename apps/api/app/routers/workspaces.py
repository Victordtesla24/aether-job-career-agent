"""Workspace routers — Interview Center, Networking CRM, Email Center,
Offer Comparison and Settings (P3 build-out).

These endpoints serve realistic, persona-consistent fixture data (Vikram
Deshpande / AU market) following the product decision that fixture-backed
contracts are acceptable where a live agent pipeline does not yet produce
the data. Everything is served per-authenticated-user so the shape matches
a future DB-backed implementation without any frontend change.

Settings are persisted per user in-process (demo scope) — a PUT round-trips
and survives for the life of the API process.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from app.middleware.auth import CurrentUser

router = APIRouter()

# --------------------------------------------------------------------------
# Interview Center
# --------------------------------------------------------------------------

_INTERVIEW_PREP: dict[str, Any] = {
    "session": {
        "role": "Senior Technical Program Manager",
        "company": "Canva",
        "round": "Round 2 · Panel interview",
        "scheduledFor": "2026-07-14T10:00:00+10:00",
        "format": "Video · 60 min",
    },
    "compliance": {
        "message": (
            "Live Assist is disabled by default during interviews. Some employers "
            "prohibit AI assistance — check your interview agreement before enabling it."
        ),
        "level": "warning",
    },
    "brief": {
        "columns": [
            {
                "title": "Company Snapshot",
                "items": [
                    "4,500+ employees · Sydney HQ, remote-friendly",
                    "Design platform, 220M+ monthly active users",
                    "Doubling down on AI-assisted design workflows",
                ],
            },
            {
                "title": "Role Focus",
                "items": [
                    "Cross-org program delivery for AI features",
                    "Own roadmap risk + dependency management",
                    "Partner with 6 product engineering squads",
                ],
            },
            {
                "title": "Panel",
                "items": [
                    "Emma Liu · Head of Delivery (hiring manager)",
                    "Raj Patel · Principal Engineer",
                    "Sophie Chen · Group Product Manager",
                ],
            },
        ],
        "insight": (
            "Canva's TPM interviews weight structured delivery stories heavily — "
            "lead with metrics, close with the outcome for the customer."
        ),
    },
    "questions": [
        {
            "question": "Tell me about a time you rescued a program that was off the rails.",
            "likelihood": "High",
            "mappedStory": "30% delivery efficiency at ANZ",
            "angle": "Emphasise the turnaround plan and stakeholder reset.",
        },
        {
            "question": "How do you manage dependencies across teams you don't control?",
            "likelihood": "High",
            "mappedStory": "Led CI/CD transformation, 5 squads",
            "angle": "Show the dependency map artifact and the weekly risk ritual.",
        },
        {
            "question": "How would you bring an AI feature from POC to production responsibly?",
            "likelihood": "Medium",
            "mappedStory": "AI/ML production rollout governance",
            "angle": "Governance gates + measurable impact — mirrors Canva's AI push.",
        },
    ],
    "liveAssist": {
        "enabled": False,
        "fillerWordsPerMin": 7,
        "wordsPerMin": 142,
        "talkListenRatio": {"talk": 62, "listen": 38},
        "coachingCue": "Slow down slightly and let the panel finish — you're at 62% talk time.",
    },
    "debrief": {
        "company": "Stripe",
        "round": "Round 1 · Recruiter screen",
        "score": 8.4,
        "strengths": [
            "Clear, quantified delivery stories",
            "Strong alignment questions at the close",
        ],
        "warnings": [
            "Rushed the compensation question — prepare a range",
            "Two answers ran past 3 minutes",
        ],
    },
}


@router.get("/interviews/prep")
def interview_prep(current_user: CurrentUser) -> dict[str, Any]:
    """Interview Center payload — brief, predicted questions, live-assist state."""
    return _INTERVIEW_PREP


# --------------------------------------------------------------------------
# Networking CRM
# --------------------------------------------------------------------------

_NETWORKING: dict[str, Any] = {
    "stats": {
        "contacts": 48,
        "activeConversations": 12,
        "referralsInFlight": 5,
        "responseRate": 41,
    },
    "pipeline": [
        {
            "stage": "New",
            "count": 14,
            "contacts": [
                {"name": "Priya Nair", "role": "Talent Partner", "company": "Canva", "warmth": 1},
                {"name": "Tom Bailey", "role": "Recruiter", "company": "Seek", "warmth": 1},
                {"name": "Grace Kim", "role": "Sourcer", "company": "Atlassian", "warmth": 2},
            ],
        },
        {
            "stage": "Warm",
            "count": 10,
            "contacts": [
                {"name": "Dan Wu", "role": "Eng Manager", "company": "Stripe", "warmth": 3},
                {"name": "Sara Ali", "role": "TA Lead", "company": "NAB", "warmth": 2},
            ],
        },
        {
            "stage": "Active",
            "count": 12,
            "contacts": [
                {"name": "Sarah Chen", "role": "Senior Recruiter", "company": "Atlassian", "warmth": 4},
                {"name": "Marcus Reid", "role": "Head of Talent", "company": "Linktree", "warmth": 3},
                {"name": "Elena Costa", "role": "Recruiter", "company": "ANZ", "warmth": 3},
            ],
        },
        {
            "stage": "Scheduled",
            "count": 7,
            "contacts": [
                {"name": "Emma Liu", "role": "Head of Delivery", "company": "Canva", "warmth": 5},
                {"name": "James Park", "role": "Director of Eng", "company": "Airtree", "warmth": 4},
            ],
        },
        {
            "stage": "Placed",
            "count": 5,
            "contacts": [
                {"name": "Nick Torres", "role": "VP Engineering", "company": "Spotify", "warmth": 5},
            ],
        },
    ],
    "outreachQueue": [
        {
            "to": "Sarah Chen · Atlassian",
            "subject": "Following up on the Staff Engineer role",
            "preview": "Hi Sarah — thanks again for the detailed walkthrough of the platform team…",
            "tone": "warm",
        },
        {
            "to": "Marcus Reid · Linktree",
            "subject": "Product Engineer application",
            "preview": "Hi Marcus — I submitted my application yesterday and wanted to flag…",
            "tone": "direct",
        },
    ],
    "communicationLog": [
        {"when": "Today · 9:14 AM", "who": "Sarah Chen", "channel": "Email", "note": "Replied — wants to schedule a call Thursday"},
        {"when": "Yesterday · 4:32 PM", "who": "Emma Liu", "channel": "LinkedIn", "note": "Confirmed Round 2 panel for Monday"},
        {"when": "Tue · 11:05 AM", "who": "Elena Costa", "channel": "Phone", "note": "Screening call — salary band confirmed $180–210k"},
    ],
    "crmSummary": {
        "activeConversations": 5,
        "followUpsDueToday": 2,
        "warmIntrosPending": 1,
    },
}


@router.get("/networking/summary")
def networking_summary(current_user: CurrentUser) -> dict[str, Any]:
    """Recruiter & referral CRM — stats, pipeline, outreach queue, comms log."""
    return _NETWORKING


# --------------------------------------------------------------------------
# Email Center
# --------------------------------------------------------------------------

_EMAILS: dict[str, Any] = {
    "accounts": [
        {"email": "vikram.d@gmail.com", "provider": "Gmail", "status": "connected", "unread": 7},
        {"email": "v.deshpande@outlook.com", "provider": "Outlook", "status": "connected", "unread": 2},
    ],
    "stats": {
        "received": 34,
        "recruiterEmails": 11,
        "autoDrafted": 6,
        "sentApproved": 4,
        "followUpsSent": 3,
        "avgResponseHrs": 5.2,
    },
    "followUps": [
        {"company": "Airtree", "role": "Backend Lead", "dueIn": "Due today", "status": "scheduled"},
        {"company": "Linktree", "role": "Product Engineer", "dueIn": "Due in 2 days", "status": "scheduled"},
        {"company": "ANZ", "role": "Senior TPM", "dueIn": "Sent Tue ✓", "status": "sent"},
    ],
    "messages": [
        {
            "id": "em-001",
            "from": "Sarah Chen",
            "fromEmail": "schen@atlassian.com",
            "company": "Atlassian",
            "subject": "Staff Engineer — next steps",
            "preview": "Hi Vikram, great news — the panel would like to move you forward to…",
            "category": "priority",
            "score": 82,
            "receivedAt": "10:42 AM",
            "account": "vikram.d@gmail.com",
            "body": (
                "Hi Vikram,\n\nGreat news — the panel was impressed with your systems design "
                "round and we'd like to move you forward to the final leadership interview.\n\n"
                "Could you share your availability for next week? The session runs 60 minutes "
                "with our Head of Platform Engineering.\n\nAlso, a heads up that we'll ask for "
                "two referees at this stage.\n\nBest,\nSarah Chen\nSenior Recruiter · Atlassian"
            ),
            "intelligence": {
                "score": 82,
                "breakdown": [
                    {"label": "Sender authority", "value": 88},
                    {"label": "Intent strength", "value": 91},
                    {"label": "Role fit", "value": 84},
                    {"label": "Urgency", "value": 65},
                ],
                "summary": "Strong positive signal — final-round invitation with referee request. Respond within 24h.",
            },
            "draftReply": (
                "Hi Sarah,\n\nThat's fantastic news — thank you for letting me know.\n\n"
                "I'm available Tuesday or Wednesday next week, any time after 10am AEST. "
                "Happy to work around the Head of Platform Engineering's calendar.\n\n"
                "I'll send through two referees by end of week.\n\nBest regards,\nVikram"
            ),
            "voiceDna": 96,
        },
        {
            "id": "em-002",
            "from": "Marcus Reid",
            "fromEmail": "marcus@linktree.com",
            "company": "Linktree",
            "subject": "Re: Product Engineer application",
            "preview": "Thanks for reaching out Vikram — your background looks like a strong…",
            "category": "priority",
            "score": 76,
            "receivedAt": "9:18 AM",
            "account": "vikram.d@gmail.com",
            "body": (
                "Thanks for reaching out Vikram — your background looks like a strong match. "
                "Let me connect you with our engineering team for an initial chat.\n\nMarcus"
            ),
            "intelligence": {
                "score": 76,
                "breakdown": [
                    {"label": "Sender authority", "value": 82},
                    {"label": "Intent strength", "value": 74},
                    {"label": "Role fit", "value": 79},
                    {"label": "Urgency", "value": 48},
                ],
                "summary": "Warm intro incoming — no action needed until the scheduling email arrives.",
            },
            "draftReply": "Hi Marcus,\n\nThanks so much — looking forward to the chat.\n\nBest,\nVikram",
            "voiceDna": 94,
        },
        {
            "id": "em-003",
            "from": "Seek Alerts",
            "fromEmail": "alerts@seek.com.au",
            "company": "Seek",
            "subject": "12 new Senior TPM roles in Melbourne",
            "preview": "New roles matching your saved search: Senior Technical Program Manager…",
            "category": "all",
            "score": 64,
            "receivedAt": "8:05 AM",
            "account": "v.deshpande@outlook.com",
            "body": "New roles matching your saved search were posted in the last 24 hours.",
            "intelligence": {
                "score": 64,
                "breakdown": [
                    {"label": "Sender authority", "value": 40},
                    {"label": "Intent strength", "value": 55},
                    {"label": "Role fit", "value": 78},
                    {"label": "Urgency", "value": 30},
                ],
                "summary": "Job alert digest — Scout has already ingested these listings.",
            },
            "draftReply": "",
            "voiceDna": 0,
        },
        {
            "id": "em-004",
            "from": "Elena Costa",
            "fromEmail": "elena.costa@anz.com",
            "company": "ANZ",
            "subject": "Interview confirmation — Senior TPM",
            "preview": "Hi Vikram, confirming your interview for Thursday 2pm with the delivery…",
            "category": "followup",
            "score": 88,
            "receivedAt": "Yesterday",
            "account": "vikram.d@gmail.com",
            "body": (
                "Hi Vikram, confirming your interview for Thursday 2pm with the delivery "
                "leadership team. The session will be held over Teams.\n\nElena"
            ),
            "intelligence": {
                "score": 88,
                "breakdown": [
                    {"label": "Sender authority", "value": 85},
                    {"label": "Intent strength", "value": 95},
                    {"label": "Role fit", "value": 82},
                    {"label": "Urgency", "value": 90},
                ],
                "summary": "Confirmed interview — added to Interview Center prep queue.",
            },
            "draftReply": "Hi Elena,\n\nConfirmed for Thursday 2pm — thank you.\n\nBest,\nVikram",
            "voiceDna": 95,
        },
        {
            "id": "em-005",
            "from": "CareerBoost Pro",
            "fromEmail": "offers@careerboost.io",
            "company": "—",
            "subject": "Unlock premium resume templates (50% off!)",
            "preview": "Limited time offer — supercharge your job search with our premium…",
            "category": "trashed",
            "score": 21,
            "receivedAt": "Yesterday",
            "account": "v.deshpande@outlook.com",
            "body": "Limited time offer — supercharge your job search!",
            "intelligence": {
                "score": 21,
                "breakdown": [
                    {"label": "Sender authority", "value": 10},
                    {"label": "Intent strength", "value": 15},
                    {"label": "Role fit", "value": 5},
                    {"label": "Urgency", "value": 60},
                ],
                "summary": "Promotional spam — auto-filed to trash.",
            },
            "draftReply": "",
            "voiceDna": 0,
        },
    ],
    "recruiterProfile": {
        "name": "Sarah Chen",
        "role": "Senior Recruiter · Atlassian",
        "history": "3 prior threads · avg response 4h",
        "notes": "Prefers concise emails. Books interviews directly via Calendly.",
    },
}


@router.get("/emails/inbox")
def email_inbox(current_user: CurrentUser) -> dict[str, Any]:
    """Email Command Center payload — accounts, smart inbox, stats, follow-ups."""
    return _EMAILS


class SendReplyRequest(BaseModel):
    message_id: str
    body: str = Field(min_length=1)


@router.post("/emails/send")
def send_reply(payload: SendReplyRequest, current_user: CurrentUser) -> dict[str, Any]:
    """Approve + send a drafted reply (demo: acknowledges through the send gate)."""
    known = {m["id"] for m in _EMAILS["messages"]}
    if payload.message_id not in known:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown message")
    return {"status": "sent", "messageId": payload.message_id}


# --------------------------------------------------------------------------
# Offers
# --------------------------------------------------------------------------

_OFFERS: dict[str, Any] = {
    "offers": [
        {
            "id": "of-001",
            "company": "Canva",
            "role": "Senior TPM",
            "total": 248000,
            "base": 185000,
            "bonus": 18000,
            "equity": 45000,
            "location": "Sydney · Hybrid 2d",
            "fitScore": 91,
            "topPick": True,
            "deadline": "2026-07-18",
        },
        {
            "id": "of-002",
            "company": "Atlassian",
            "role": "Staff Engineer",
            "total": 235000,
            "base": 190000,
            "bonus": 15000,
            "equity": 30000,
            "location": "Remote AU",
            "fitScore": 84,
            "topPick": False,
            "deadline": "2026-07-22",
        },
        {
            "id": "of-003",
            "company": "ANZ",
            "role": "Senior TPM",
            "total": 212000,
            "base": 175000,
            "bonus": 22000,
            "equity": 15000,
            "location": "Melbourne · Hybrid 3d",
            "fitScore": 79,
            "topPick": False,
            "deadline": "2026-07-25",
        },
    ],
    "weights": [
        {"key": "comp", "label": "Total compensation", "weight": 30},
        {"key": "growth", "label": "Career growth", "weight": 25},
        {"key": "culture", "label": "Culture & team", "weight": 20},
        {"key": "flexibility", "label": "Location & flexibility", "weight": 15},
        {"key": "stability", "label": "Company stability", "weight": 10},
    ],
    "negotiation": {
        "insight": (
            "Canva's base is 3% below the 75th percentile for Senior TPM in Sydney. "
            "Their equity refresh policy suggests room to move on base."
        ),
        "suggestedCounter": 195000,
        "leverage": [
            "Competing offer from Atlassian at higher base",
            "Final-round signal from Stripe still in play",
            "Specialised AI delivery experience matches their roadmap",
        ],
    },
}


@router.get("/offers")
def offers(current_user: CurrentUser) -> dict[str, Any]:
    """Offer comparison payload — offers, priority weights, negotiation coach."""
    return _OFFERS


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

class SettingsProfile(BaseModel):
    fullName: str = Field(min_length=1, max_length=120)
    email: EmailStr
    targetRole: str = Field(min_length=1, max_length=120)
    location: str = Field(min_length=1, max_length=120)


class AgentConfig(BaseModel):
    autoApply: bool
    approvalGate: bool
    matchThreshold: int = Field(ge=0, le=100)


class SettingsUpdate(BaseModel):
    profile: SettingsProfile
    agentConfig: AgentConfig


_DEFAULT_SETTINGS: dict[str, Any] = {
    "profile": {
        "fullName": "Vikram Deshpande",
        "email": "demo@aether.dev",
        "targetRole": "Senior Technical Program Manager",
        "location": "Melbourne, AU",
    },
    "resume": {
        "activeFile": "Vik_Resume_Final.pdf",
        "uploadedAt": "2026-06-28",
        "versions": 4,
    },
    "portfolio": {
        "url": "github.com/vikramd",
        "cadence": "Daily",
        "lastSynced": "Today · 6:00 AM",
    },
    "agentConfig": {
        "autoApply": False,
        "approvalGate": True,
        "matchThreshold": 80,
    },
    "integrations": [
        {"name": "Seek", "status": "connected", "detail": "98 roles synced"},
        {"name": "LinkedIn", "status": "syncing", "detail": "Sync 44% complete"},
        {"name": "Workforce Australia", "status": "not_configured", "detail": "Not configured"},
        {"name": "Jora", "status": "disconnected", "detail": "Disconnected"},
        {"name": "Indeed", "status": "disconnected", "detail": "Disconnected"},
    ],
    "connectedAccounts": [
        {"name": "LinkedIn", "detail": "vikram-deshpande", "status": "connected"},
        {"name": "GitHub", "detail": "vikramd", "status": "connected"},
        {"name": "OpenRouter", "detail": "API key ····7f2a", "status": "connected"},
    ],
}

# Per-user settings overrides (demo persistence — process lifetime).
_SETTINGS_STORE: dict[str, dict[str, Any]] = {}


@router.get("/settings")
def get_settings(current_user: CurrentUser) -> dict[str, Any]:
    """Current settings — defaults merged with any saved per-user overrides."""
    saved = _SETTINGS_STORE.get(current_user["id"], {})
    merged = {**_DEFAULT_SETTINGS}
    if "profile" in saved:
        merged["profile"] = saved["profile"]
    if "agentConfig" in saved:
        merged["agentConfig"] = saved["agentConfig"]
    return merged


@router.put("/settings")
def update_settings(payload: SettingsUpdate, current_user: CurrentUser) -> dict[str, Any]:
    """Validate and persist profile + agent configuration for this user."""
    _SETTINGS_STORE[current_user["id"]] = {
        "profile": payload.profile.model_dump(),
        "agentConfig": payload.agentConfig.model_dump(),
    }
    return get_settings(current_user)
