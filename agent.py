"""Autonomous agent brain for the lead-gen bot.

Runs the bot 24/7 without supervision: a never-crashing async loop that schedules
recurring work (reply checks, outreach, prospecting, reports), reacts to inbound
replies, monitors its own health, and can be steered by the owner over WhatsApp.

It DRIVES the existing service layer rather than reimplementing it — every task
calls the same functions main.py uses (`build_components`, `run_prospecting`,
`run_outreach`, etc.), so manual and autonomous modes stay in lockstep.

Design rules (from the spec):
  * The agent must NEVER crash — every await is wrapped; a failure in one task
    degrades that task, not the process.
  * Live by default. `python agent.py` prospects and sends for real.
    `--dry-run` / `--test` are the safe opt-ins.
  * WhatsApp is the Playwright web provider; owner commands arrive as inbound
    messages scraped into the `whatsapp_responses` table.

CLI:
  python agent.py            # live autonomous loop
  python agent.py --dry-run  # full loop, but every send/DB-write only logs intent
  python agent.py --test     # one pass of each due task (implies dry-run), then exit
  python agent.py --status   # print state from data/agent_state.json, then exit
  python agent.py --pause    # ask a running agent to pause (writes state file)
  python agent.py --resume   # ask a running agent to resume
"""
import argparse
import asyncio
import json
import logging
import os
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Awaitable, Callable, Optional

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# CRITICAL ORDERING: main.py configures logging with FileHandler("data/...")
# at IMPORT time, which raises FileNotFoundError if data/ is missing. Create
# the directory BEFORE importing main so the import can never crash. The
# `from main import ...` below triggers that same import side-effect, so we do
# not need a separate bare `import main` (which would also shadow def main()).
# ---------------------------------------------------------------------------
Path("data").mkdir(parents=True, exist_ok=True)

from main import (  # noqa: E402  (deliberate: must follow the mkdir above)
    build_components,
    run_prospecting,
    run_outreach,
)
from src.database import LeadDatabase  # noqa: E402
from src.db.migrate import migrate  # noqa: E402
from src.whatsapp.whatsapp_api import select_whatsapp_provider  # noqa: E402

try:
    import pytz  # timezone gating for the daily report (already a dependency)
except Exception:  # pragma: no cover - pytz is in requirements but stay safe
    pytz = None

logger = logging.getLogger("agent")

STATE_PATH = Path("data/agent_state.json")
LOG_PATH = Path("data/agent_log.jsonl")
OWNER_PHONE = os.getenv("OWNER_PHONE", "")
OWNER_TZ = os.getenv("OWNER_TIMEZONE", "UTC")

# Loop cadence: how often the agent wakes to evaluate due tasks.
TICK_SECONDS = 5
# How often health metrics + alerts are computed.
HEALTH_EVERY_SECONDS = 300


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _today_str() -> str:
    return _utcnow().strftime("%Y-%m-%d")


def _normalize_phone(phone: str) -> str:
    """Digits-only form for owner-identity comparison.

    WhatsAppBot._format_phone() strips '+'/spaces before storing inbound rows,
    so OWNER_PHONE ('+8801...') must be normalized the same way to match.
    """
    if not phone:
        return ""
    return "".join(ch for ch in str(phone) if ch.isdigit())


# ===========================================================================
# AgentState
# ===========================================================================
class AgentState(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    ERROR = "error"


# ===========================================================================
# SECTION 2 — TaskScheduler + Task
# ===========================================================================
@dataclass
class Task:
    """A recurring unit of work with a self-adjusting cooldown.

    `func` is a zero-arg async callable returning an int "amount of work done"
    (e.g. replies handled, messages sent). That return drives the dynamic
    cooldown: productive tasks speed up, idle tasks back off.
    """
    name: str
    func: Callable[[], Awaitable[int]]
    base_interval: float
    priority: int = 3                      # 1 = highest
    min_interval: float = 30.0
    max_interval: float = 21600.0
    clock_gated: bool = False              # True => cadence handled by func itself
    interval: float = 0.0
    next_run: float = 0.0                  # monotonic deadline
    last_run: Optional[str] = None         # iso, for display
    enabled: bool = True
    consecutive_idle: int = 0
    last_result: int = 0
    runs: int = 0
    failures: int = 0

    def __post_init__(self):
        if self.interval <= 0:
            self.interval = self.base_interval


class TaskScheduler:
    """Holds the task table, picks what's due, and runs each in isolation."""

    def __init__(self):
        self.tasks: dict[str, Task] = {}

    def register_task(self, name, func, base_interval, priority=3,
                      min_interval=30.0, max_interval=21600.0, clock_gated=False):
        task = Task(
            name=name, func=func, base_interval=base_interval, priority=priority,
            min_interval=min_interval, max_interval=max_interval,
            clock_gated=clock_gated,
        )
        # Stagger initial firing slightly by priority so the first tick doesn't
        # run every task at once (cheap, deterministic spread).
        task.next_run = time.monotonic() + (priority - 1) * 2
        self.tasks[name] = task
        return task

    def due_tasks(self) -> list[Task]:
        now = time.monotonic()
        due = [t for t in self.tasks.values() if t.enabled and now >= t.next_run]
        # Highest priority first; ties broken by the earliest deadline.
        due.sort(key=lambda t: (t.priority, t.next_run))
        return due

    async def run_due_tasks(self, agent: "AutonomousAgent") -> int:
        """Run every due task once, sequentially. Returns total work done.

        Sequential by design: all services share ONE aiosqlite connection
        (db.db), which is not safe for concurrent writes. Never gather these.
        """
        total = 0
        for task in self.due_tasks():
            agent.current_task = task.name
            try:
                result = await task.func()
                result = int(result or 0)
                task.last_result = result
                task.runs += 1
                total += result
                if result:
                    agent.tasks_completed_today += 1
                agent.monitor.log_action(task.name, "ok", detail={"result": result},
                                         task=task.name)
            except Exception as exc:  # a task failing must never stop the loop
                task.failures += 1
                task.last_result = 0
                result = 0
                logger.error("task %s failed: %s", task.name, exc)
                agent.monitor.log_action(task.name, "error", detail=str(exc),
                                         task=task.name)
            finally:
                task.last_run = _utcnow().isoformat()
                self._adjust_cooldown(task)
                task.next_run = time.monotonic() + task.interval
                agent.current_task = None
        return total

    def _adjust_cooldown(self, task: Task):
        """Dynamic cooldown: tighten when productive, back off when idle.

        Clock-gated tasks (daily report, weekly cleanup) decide their own timing
        inside func(), so we only refresh their poll interval, not a backoff.
        """
        if task.clock_gated:
            task.interval = task.base_interval
            return
        if task.last_result > 0:
            task.consecutive_idle = 0
            task.interval = max(task.min_interval, task.interval * 0.5)
        else:
            task.consecutive_idle += 1
            factor = 1.5 if task.consecutive_idle < 3 else 2.0
            task.interval = min(task.max_interval, task.interval * factor)


# ===========================================================================
# SECTION 3 — DecisionEngine
# ===========================================================================
# The 8 canonical reply classifications and the action each maps to. The raw
# classifiers in the codebase emit ~5 labels (email: interested/not_interested/
# question/out_of_office; whatsapp: +stop); _normalize() derives the extra three
# (unsubscribe / referral_wrong_person / auto_reply / neutral) from the body.
REPLY_CLASSES = (
    "interested", "not_interested", "question", "out_of_office",
    "unsubscribe", "referral_wrong_person", "auto_reply", "neutral",
)

_AUTO_REPLY_HINTS = (
    "automatic reply", "auto-reply", "autoreply", "out of the office",
    "away from my desk", "do not reply", "no-reply", "mailer-daemon",
    "delivery has failed", "undeliverable",
)
_REFERRAL_HINTS = (
    "wrong person", "not the right", "reach out to", "forward this to",
    "you should contact", "no longer with", "speak to", "talk to",
)


class Decision:
    """A single reactive action the engine wants to take."""
    def __init__(self, kind: str, priority: int, payload: dict):
        self.kind = kind
        self.priority = priority
        self.payload = payload


class DecisionEngine:
    """Reactive layer: decides what to do *right now* based on DB state.

    The recurring cadence is the scheduler's job; this engine handles
    event-driven work — chiefly routing inbound replies through the 8-way
    handler. Every handler branch is IDEMPOTENT (guards on current lead status /
    suppression list) because the inline pollers may have already actioned the
    same reply; this prevents duplicate booking links or answers.
    """

    def __init__(self, db, components: dict):
        self.db = db
        self.c = components

    # ----- classification -------------------------------------------------
    def _normalize(self, raw: str, body: str) -> str:
        raw = (raw or "").strip().lower()
        text = (body or "").lower()
        # Opt-out language always wins (compliance-critical).
        compliance = self.c["outbound"].compliance
        if raw == "stop" or compliance.is_optout(body):
            return "unsubscribe"
        if any(h in text for h in _AUTO_REPLY_HINTS):
            # Distinguish a true vacation autoresponder from a human OOO note.
            return "out_of_office" if raw == "out_of_office" else "auto_reply"
        if any(h in text for h in _REFERRAL_HINTS):
            return "referral_wrong_person"
        if raw in REPLY_CLASSES:
            return raw
        if raw == "not_interested":
            return "not_interested"
        return "neutral"

    # ----- the 8-way handler ---------------------------------------------
    async def handle_reply(self, response: dict, dry_run: bool = False) -> str:
        """Map a normalized reply to an action. Returns the canonical class.

        `response` = {lead_id, email, phone, body, classification, channel}.
        Idempotent: re-running on an already-handled reply is a no-op.
        """
        cls = self._normalize(response.get("classification"), response.get("body"))
        lead_id = response.get("lead_id")
        email = response.get("email")
        phone = response.get("phone")
        channel = response.get("channel", "email")

        async def _status() -> str:
            if not lead_id:
                return ""
            lead = await self.db.get_lead_by_id(lead_id)
            return (lead or {}).get("status", "")

        if dry_run:
            logger.info("[dry-run] would handle reply lead=%s as %s", lead_id, cls)
            return cls

        try:
            if cls == "interested":
                # Skip if the inline poller already qualified/booked this lead.
                if await _status() not in ("qualified", "booking_sent"):
                    lead = await self.db.get_lead_by_id(lead_id) if lead_id else {}
                    if lead:
                        await self.c["outbound"].send_booking_outreach(lead, channel)
                    if lead_id:
                        await self.db.update_lead_status(lead_id, "qualified")

            elif cls == "not_interested":
                if lead_id:
                    await self.db.stop_all_sequences(lead_id)
                    await self.db.update_lead_status(lead_id, "not_interested")

            elif cls == "unsubscribe":
                # Suppress globally + stop everything. Guard: skip if already done.
                if not await self.db.is_unsubscribed(email=email, phone=phone):
                    await self.db.add_unsubscribe(email=email, phone=phone,
                                                  reason=f"{channel} opt-out")
                if lead_id:
                    await self.db.stop_all_sequences(lead_id)
                    await self.db.update_lead_status(lead_id, "unsubscribed")

            elif cls == "out_of_office":
                if lead_id:
                    await self.db.reschedule_sequence(lead_id, 5)

            elif cls == "referral_wrong_person":
                # Pause this contact and flag for human review; nudge the owner.
                if lead_id:
                    await self.db.reschedule_sequence(lead_id, 14)
                    await self.db.update_lead_status(lead_id, "needs_review")
                await self._notify_owner(
                    f"Lead {lead_id or '?'} replied with a referral/wrong-person "
                    f"note — needs review.")

            elif cls == "auto_reply":
                # Vacation/bounce autoresponder — do not engage, do not count.
                pass

            else:  # neutral
                pass
        except Exception as exc:
            logger.error("handle_reply(%s) failed: %s", cls, exc)
        return cls

    async def _notify_owner(self, text: str):
        if not OWNER_PHONE:
            return
        try:
            await self.c["whatsapp"].send_message(OWNER_PHONE, text)
        except Exception as exc:
            logger.debug("owner notify failed: %s", exc)

    # ----- decision tree --------------------------------------------------
    async def decide_next_action(self, agent: "AutonomousAgent") -> list[Decision]:
        """Inspect DB state and return an ordered batch of reactive decisions."""
        if agent.state == AgentState.PAUSED:
            return []
        decisions: list[Decision] = []
        try:
            # 1. Unhandled email replies → route through handle_reply (top prio).
            unreplied = await self.db.get_unreplied_responses()
            for row in unreplied or []:
                resp = self._row_to_response(row)
                if resp:
                    decisions.append(Decision("reply", 1, resp))
        except Exception as exc:
            logger.debug("decide_next_action: unreplied scan failed: %s", exc)
        return decisions

    def _row_to_response(self, row) -> Optional[dict]:
        """email_responses row -> normalized response dict.

        Schema (database.py): id, lead_id, received_at, subject, body,
        classification, replied.
        """
        try:
            return {
                "response_id": row[0],
                "lead_id": row[1],
                "body": row[4] if len(row) > 4 else "",
                "classification": row[5] if len(row) > 5 else "",
                "email": None,
                "phone": None,
                "channel": "email",
            }
        except Exception:
            return None

    async def execute_batch(self, decisions: list[Decision], dry_run: bool) -> int:
        """Run decisions in priority order; mark email replies handled."""
        handled = 0
        for d in sorted(decisions, key=lambda x: x.priority):
            try:
                if d.kind == "reply":
                    # Enrich with the lead's email/phone so handlers can suppress.
                    lead_id = d.payload.get("lead_id")
                    if lead_id:
                        lead = await self.db.get_lead_by_id(lead_id)
                        d.payload["email"] = (lead or {}).get("email")
                        d.payload["phone"] = (lead or {}).get("phone")
                    await self.handle_reply(d.payload, dry_run=dry_run)
                    rid = d.payload.get("response_id")
                    if rid and not dry_run:
                        await self.db.mark_response_replied(rid)
                    handled += 1
            except Exception as exc:
                logger.error("execute_batch decision failed: %s", exc)
        return handled


# ===========================================================================
# SECTION 4 — AgentMonitor
# ===========================================================================
class AgentMonitor:
    """Action log (jsonl), periodic health metrics, and owner alerts."""

    def __init__(self, db, components: dict, log_path: Path = LOG_PATH):
        self.db = db
        self.c = components
        self.log_path = log_path
        self.state_ref = AgentState.STARTING
        self._last_alert: dict[str, float] = {}
        self.ALERT_COOLDOWN = 1800  # don't repeat the same alert within 30 min

    def log_action(self, action: str, status: str = "ok", detail=None, task=None):
        """Append exactly one JSON object per line. Logging must never crash."""
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "ts": _utcnow().isoformat(),
                "action": action,
                "status": status,
                "task": task,
                "detail": detail,
                "state": getattr(self.state_ref, "value", str(self.state_ref)),
            }
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except Exception as exc:  # pragma: no cover
            logger.debug("log_action failed: %s", exc)

    async def health_metrics(self, agent: "AutonomousAgent") -> dict:
        """Snapshot the agent + pipeline. Every value guarded — never raises."""
        async def _count(coro) -> int:
            try:
                rows = await coro
                return len(rows or [])
            except Exception:
                return 0

        uptime = (time.monotonic() - agent._start_monotonic)
        metrics = {
            "uptime_s": int(uptime),
            "state": agent.state.value,
            "tasks_completed_today": agent.tasks_completed_today,
            "pending_emails": await _count(self.db.get_pending_emails()),
            "pending_whatsapp": await _count(self.db.get_pending_messages()),
            "unreplied": await _count(self.db.get_unreplied_responses()),
            "hot_leads": await _count(self.db.get_leads_by_status("hot")),
            "booking_pipeline": await _count(self.db.get_booking_pipeline()),
            "last_heartbeat": agent.last_heartbeat.isoformat() if agent.last_heartbeat else None,
        }
        try:
            metrics["api_usage"] = self.c["usage"].snapshot()
        except Exception:
            metrics["api_usage"] = {}
        self.log_action("health", "ok", detail=metrics)
        return metrics

    async def check_alerts(self, agent: "AutonomousAgent", metrics: dict) -> list[str]:
        """Evaluate the 4 alert conditions; DM the owner (rate-limited)."""
        alerts: list[str] = []

        # 1. Stalled: up over an hour but nothing completed today.
        if metrics["uptime_s"] > 3600 and metrics["tasks_completed_today"] == 0:
            alerts.append("Agent has run >1h with zero completed tasks — check feeds/credentials.")

        # 2. Repeated task failures.
        failing = [t.name for t in agent.scheduler.tasks.values() if t.failures >= 3]
        if failing:
            alerts.append("Tasks repeatedly failing: " + ", ".join(failing))

        # 3. API quota near a ceiling.
        for source, info in (metrics.get("api_usage") or {}).items():
            limit = info.get("limit") or 0
            if limit and info.get("used", 0) >= 0.8 * limit:
                alerts.append(f"API quota for '{source}' at {info['used']}/{limit}.")

        # 4. Reply backlog / WhatsApp channel down.
        if metrics["unreplied"] > 25:
            alerts.append(f"Reply backlog building: {metrics['unreplied']} unhandled.")
        wa = self.c.get("whatsapp")
        if getattr(wa, "page", "n/a") is None:  # web provider with no live session
            alerts.append("WhatsApp web session is not connected.")

        for msg in alerts:
            await self._fire_alert(msg)
        return alerts

    async def _fire_alert(self, msg: str):
        key = msg.split(":")[0]
        now = time.monotonic()
        if now - self._last_alert.get(key, -1e9) < self.ALERT_COOLDOWN:
            return
        self._last_alert[key] = now
        self.log_action("alert", "warn", detail=msg)
        logger.warning("ALERT: %s", msg)
        if OWNER_PHONE:
            try:
                await self.c["whatsapp"].send_message(OWNER_PHONE, f"[agent] {msg}")
            except Exception as exc:
                logger.debug("alert DM failed: %s", exc)

    def status_text(self, agent: "AutonomousAgent", metrics: dict) -> str:
        lines = [
            "=== Autonomous Agent Status ===",
            f"State            : {agent.state.value}",
            f"Uptime           : {metrics.get('uptime_s', 0)}s",
            f"Tasks today      : {metrics.get('tasks_completed_today', 0)}",
            f"Current task     : {agent.current_task or '-'}",
            f"Pending emails   : {metrics.get('pending_emails', 0)}",
            f"Pending WhatsApp : {metrics.get('pending_whatsapp', 0)}",
            f"Unreplied        : {metrics.get('unreplied', 0)}",
            f"Hot leads        : {metrics.get('hot_leads', 0)}",
            f"Booking pipeline : {metrics.get('booking_pipeline', 0)}",
            "Tasks:",
        ]
        for t in sorted(agent.scheduler.tasks.values(), key=lambda x: x.priority):
            state = "on" if t.enabled else "OFF"
            lines.append(
                f"  [{state}] {t.name:<22} every ~{int(t.interval)}s  "
                f"runs={t.runs} fails={t.failures} idle={t.consecutive_idle}")
        return "\n".join(lines)


# ===========================================================================
# SECTION 1 + 5 — AutonomousAgent
# ===========================================================================
class AutonomousAgent:
    def __init__(self, dry_run: bool = False, test_mode: bool = False):
        # --- Section 1 properties ---
        self.state = AgentState.STARTING
        self.current_task: Optional[str] = None
        self.tasks_completed_today = 0
        self.started_at = _utcnow()
        self.last_heartbeat: Optional[datetime] = None

        self.dry_run = dry_run or test_mode
        self.test_mode = test_mode
        self.db: Optional[LeadDatabase] = None
        self.components: dict = {}
        self.scheduler = TaskScheduler()
        self.engine: Optional[DecisionEngine] = None
        self.monitor: Optional[AgentMonitor] = None

        self._shutdown = asyncio.Event()
        self.paused_event = asyncio.Event()
        self.paused_event.set()  # set == running
        self._start_monotonic = time.monotonic()
        self._last_owner_msg_id = 0
        self._today = _today_str()
        self._daily_report_sent_on: Optional[str] = None
        self._disabled_on_start: list[str] = []

    # ---------------------------------------------------------------- startup
    async def startup(self):
        try:
            Path("data").mkdir(parents=True, exist_ok=True)
            self.db = LeadDatabase()
            await self.db.connect()
            try:
                await migrate()  # ensure global enrichment columns exist
            except Exception as exc:
                logger.warning("migrate() failed (continuing): %s", exc)

            self.components = build_components(self.db)
            self._maybe_swap_whatsapp_provider()

            self.monitor = AgentMonitor(self.db, self.components)
            self.monitor.state_ref = self.state
            self.engine = DecisionEngine(self.db, self.components)

            # Web provider: try to bring up the browser session. Tolerate
            # failure (no QR/headless env) — the agent runs degraded, not dead.
            await self._try_start_whatsapp()

            self._register_tasks()
            self.restore_state()  # crash recovery (may set PAUSED / disabled tasks)

            health = await self._health_check()
            if self.state == AgentState.STARTING:
                self.state = AgentState.RUNNING
            self.monitor.state_ref = self.state
            self.monitor.log_action("startup", "ok", detail=health)
            logger.info("Agent startup complete (state=%s, dry_run=%s)",
                        self.state.value, self.dry_run)
        except Exception as exc:
            self.state = AgentState.ERROR
            logger.error("startup failed: %s", exc)
            if self.monitor:
                self.monitor.log_action("startup", "error", detail=str(exc))

    def _maybe_swap_whatsapp_provider(self):
        """build_components() always makes a WhatsAppBot; honor WHATSAPP_PROVIDER
        by swapping to the 360dialog API client when explicitly configured."""
        try:
            if os.getenv("WHATSAPP_PROVIDER", "web").lower() == "api":
                wa = select_whatsapp_provider(self.db, self.components.get("ai"))
                self.components["whatsapp"] = wa
                self.components["outbound"].whatsapp = wa
        except Exception as exc:
            logger.warning("provider swap failed (keeping web bot): %s", exc)

    async def _try_start_whatsapp(self):
        wa = self.components.get("whatsapp")
        start = getattr(wa, "start", None)
        if start is None or self.dry_run:
            return
        try:
            await start()
        except Exception as exc:
            logger.warning("WhatsApp session not started (degraded): %s", exc)

    async def _health_check(self) -> dict:
        health = {"db": False, "ai": False, "whatsapp": False, "owner": bool(OWNER_PHONE)}
        try:
            cur = await self.db.db.execute("SELECT 1")
            await cur.fetchone()
            health["db"] = True
        except Exception as exc:
            logger.warning("health: db check failed: %s", exc)
        try:
            health["ai"] = getattr(self.components.get("ai"), "provider", "none") != "none"
        except Exception:
            pass
        wa = self.components.get("whatsapp")
        health["whatsapp"] = getattr(wa, "page", None) is not None or \
            getattr(wa, "is_configured", lambda: False)()
        if not health["owner"]:
            logger.warning("health: OWNER_PHONE not set — remote control disabled")
        return health

    # ----------------------------------------------------------- task wiring
    def _register_tasks(self):
        """Build the 6 task closures over the live component set."""
        c = self.components

        async def check_replies() -> int:
            if self.dry_run:
                logger.info("[dry-run] would check email + WhatsApp replies")
                return 0
            done = 0
            poller = c["email_poller"]
            try:
                done += await poller.check_for_replies()
            except Exception as exc:
                logger.error("email reply check failed: %s", exc)
            wa = c["whatsapp"]
            poll = getattr(wa, "poll_new_messages", None)
            if poll and getattr(wa, "page", None) is not None:
                try:
                    done += await poll()
                except Exception as exc:
                    logger.error("whatsapp poll failed: %s", exc)
            return done

        async def send_initial_outreach() -> int:
            return await self._run_outreach_both()

        async def send_followups() -> int:
            # Same pending-sequence machinery; later steps are due-dated rows.
            return await self._run_outreach_both()

        async def prospect_new_leads() -> int:
            if self.dry_run:
                logger.info("[dry-run] would run global prospecting")
                return 0
            # Respect API quotas — don't spin prospecting when sources are dry.
            usage = c["usage"]
            if not any(usage.can_spend(s) for s in ("apollo", "github_authed",
                                                    "github_anon", "producthunt")):
                logger.info("prospecting skipped — all source quotas exhausted")
                return 0
            try:
                return await run_prospecting(self.db, c)
            except Exception as exc:
                logger.error("prospecting failed: %s", exc)
                return 0

        async def daily_report() -> int:
            return await self._maybe_daily_report()

        async def weekly_cleanup() -> int:
            return await self._weekly_cleanup()

        self.scheduler.register_task("check_replies", check_replies, 120,
                                     priority=1, min_interval=60, max_interval=900)
        self.scheduler.register_task("send_initial_outreach", send_initial_outreach,
                                     300, priority=2, min_interval=120, max_interval=1800)
        self.scheduler.register_task("send_followups", send_followups, 300,
                                     priority=2, min_interval=120, max_interval=1800)
        self.scheduler.register_task("prospect_new_leads", prospect_new_leads, 3600,
                                     priority=3, min_interval=1800, max_interval=21600)
        self.scheduler.register_task("daily_report", daily_report, 600,
                                     priority=4, clock_gated=True)
        self.scheduler.register_task("weekly_cleanup", weekly_cleanup, 3600,
                                     priority=5, clock_gated=True)

        # Re-apply any tasks disabled via a prior STOP OUTREACH (crash recovery).
        for name in self._disabled_on_start:
            if name in self.scheduler.tasks:
                self.scheduler.tasks[name].enabled = False

    async def _run_outreach_both(self) -> int:
        if self.dry_run:
            logger.info("[dry-run] would send pending email + WhatsApp outreach")
            return 0
        sent = 0
        for channel in ("email", "whatsapp"):
            try:
                sent += await run_outreach(self.db, self.components["outbound"], channel)
            except Exception as exc:
                logger.error("%s outreach failed: %s", channel, exc)
        return sent

    # --------------------------------------------------- clock-gated tasks
    def _owner_local_hour(self) -> int:
        if pytz is not None:
            try:
                return _utcnow().astimezone(pytz.timezone(OWNER_TZ)).hour
            except Exception:
                pass
        return _utcnow().hour

    async def _maybe_daily_report(self) -> int:
        """Fire once per day around 09:00 in the owner's timezone."""
        today = _today_str()
        if self._daily_report_sent_on == today:
            return 0
        if self._owner_local_hour() < 9:
            return 0
        if self.dry_run:
            logger.info("[dry-run] would send daily report")
            self._daily_report_sent_on = today
            return 0
        produced = 0
        try:
            analytics = self.components["analytics"]
            chart, stats = await analytics.generate_daily_report()
            logger.info("daily report chart: %s", chart)
            await self._send_owner_report(stats)
            produced = 1
        except Exception as exc:
            logger.error("daily report failed: %s", exc)
        self._daily_report_sent_on = today
        return produced

    async def _send_owner_report(self, stats: dict):
        """DM the owner a compact report. Uses analytics stats directly rather
        than DailySummary (which queries a table that doesn't exist on main)."""
        if not OWNER_PHONE:
            return
        try:
            text = "Daily Lead-Gen Report\n" + "\n".join(
                f"  {k}: {v}" for k, v in (stats or {}).items())
            await self.components["whatsapp"].send_message(OWNER_PHONE, text)
        except Exception as exc:
            logger.debug("owner report DM failed: %s", exc)

    async def _weekly_cleanup(self) -> int:
        """Light weekly housekeeping: prune the action log, DM a leaderboard.
        Gated to Monday ~08:00 owner-local, once per ISO week."""
        now = _utcnow()
        if now.weekday() != 0 or self._owner_local_hour() < 8:
            return 0
        week_key = now.strftime("%Y-W%U")
        if getattr(self, "_cleanup_week", None) == week_key:
            return 0
        self._cleanup_week = week_key
        if self.dry_run:
            logger.info("[dry-run] would run weekly cleanup")
            return 0
        try:
            self._prune_log()
            analytics = self.components["analytics"]
            _, _, whatsapp_text = await analytics.weekly_leaderboard()
            if OWNER_PHONE and whatsapp_text:
                await self.components["whatsapp"].send_message(OWNER_PHONE, whatsapp_text)
        except Exception as exc:
            logger.error("weekly cleanup failed: %s", exc)
        return 1

    def _prune_log(self, max_lines: int = 5000):
        """Keep agent_log.jsonl bounded so it can't grow without limit."""
        try:
            if not LOG_PATH.exists():
                return
            lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
            if len(lines) > max_lines:
                LOG_PATH.write_text("\n".join(lines[-max_lines:]) + "\n",
                                    encoding="utf-8")
        except Exception as exc:
            logger.debug("log prune failed: %s", exc)

    # --------------------------------------------------------- main loop
    async def run_forever(self):
        self._install_signal_handlers()
        self.monitor.log_action("loop_start", "ok")
        last_health = 0.0
        while not self._shutdown.is_set():
            loop_start = time.monotonic()
            try:
                self._maybe_rollover_day()
                self.last_heartbeat = _utcnow()

                # 1. Owner commands run every tick — even while paused, so RESUME
                #    can be received.
                await self.poll_owner_commands()

                if self.state != AgentState.PAUSED:
                    # 2. Recurring cadence tasks (sequential — shared DB conn).
                    await self.scheduler.run_due_tasks(self)
                    # 3. Reactive decisions (reply routing).
                    decisions = await self.engine.decide_next_action(self)
                    if decisions:
                        await self.engine.execute_batch(decisions, self.dry_run)

                # 4. Health + alerts every 5 minutes.
                if time.monotonic() - last_health >= HEALTH_EVERY_SECONDS:
                    metrics = await self.monitor.health_metrics(self)
                    await self.monitor.check_alerts(self, metrics)
                    last_health = time.monotonic()

                # 5. Persist state every tick for crash recovery.
                self.save_state()

                if self.test_mode:
                    break  # one pass only
            except Exception as exc:  # the loop itself must never die
                logger.error("loop iteration error: %s", exc)
                self.state = AgentState.ERROR
                if self.monitor:
                    self.monitor.log_action("loop_error", "error", detail=str(exc))
                    self.monitor.state_ref = self.state
                await asyncio.sleep(5)
            finally:
                if not (self.test_mode or self._shutdown.is_set()):
                    elapsed = time.monotonic() - loop_start
                    await asyncio.sleep(max(0.0, TICK_SECONDS - elapsed))
        if not self.test_mode:
            # In test mode the caller prints status (DB still open) then shuts down.
            await self.shutdown()

    # --------------------------------------------------------- lifecycle
    def _install_signal_handlers(self):
        def _request_stop(*_):
            self.state = AgentState.STOPPING
            if self.monitor:
                self.monitor.state_ref = self.state
            self._shutdown.set()
        try:
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGINT, _request_stop)
            loop.add_signal_handler(signal.SIGTERM, _request_stop)
        except (NotImplementedError, RuntimeError):
            # Windows: add_signal_handler is unsupported — fall back to signal().
            try:
                signal.signal(signal.SIGINT, _request_stop)
            except Exception:
                pass

    async def shutdown(self):
        self.state = AgentState.STOPPING
        logger.info("Shutting down…")
        self.save_state()
        wa = self.components.get("whatsapp")
        for closer in (getattr(wa, "close", None),
                       getattr(self.db, "close", None)):
            if closer:
                try:
                    await closer()
                except Exception as exc:
                    logger.debug("close failed: %s", exc)
        if self.monitor:
            self.monitor.log_action("shutdown", "ok")

    async def pause(self, reason: str = "manual"):
        self.state = AgentState.PAUSED
        self.paused_event.clear()
        if self.monitor:
            self.monitor.state_ref = self.state
            self.monitor.log_action("pause", "ok", detail=reason)
        self.save_state()
        logger.info("Agent paused (%s)", reason)

    async def resume(self):
        self.state = AgentState.RUNNING
        self.paused_event.set()
        # Stagger restart so tasks don't all fire on the same tick.
        for t in self.scheduler.tasks.values():
            t.next_run = time.monotonic() + (t.priority - 1) * 2
        if self.monitor:
            self.monitor.state_ref = self.state
            self.monitor.log_action("resume", "ok")
        self.save_state()
        logger.info("Agent resumed")

    def _maybe_rollover_day(self):
        today = _today_str()
        if today != self._today:
            self._today = today
            self.tasks_completed_today = 0

    # --------------------------------------------------- state persistence
    def save_state(self):
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "state": self.state.value,
                "started_at": self.started_at.isoformat(),
                "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
                "date": self._today,
                "tasks_completed_today": self.tasks_completed_today,
                "last_owner_msg_id": self._last_owner_msg_id,
                "disabled_tasks": [t.name for t in self.scheduler.tasks.values()
                                   if not t.enabled],
                "task_intervals": {t.name: round(t.interval)
                                   for t in self.scheduler.tasks.values()},
                "daily_report_sent_on": self._daily_report_sent_on,
                "pause_reason": "owner" if self.state == AgentState.PAUSED else None,
            }
            with open(STATE_PATH, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except Exception as exc:
            logger.debug("save_state failed: %s", exc)

    def restore_state(self):
        """Resume prior state on startup. Corrupt/missing file → fresh start."""
        if not STATE_PATH.exists():
            return
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("ignoring corrupt agent_state.json: %s", exc)
            return
        try:
            self._last_owner_msg_id = int(data.get("last_owner_msg_id", 0))
            # Only restore today's completion count (else start fresh).
            if data.get("date") == _today_str():
                self.tasks_completed_today = int(data.get("tasks_completed_today", 0))
                self._daily_report_sent_on = data.get("daily_report_sent_on")
            self._disabled_on_start = list(data.get("disabled_tasks", []))
            for name, iv in (data.get("task_intervals") or {}).items():
                if name in self.scheduler.tasks:
                    self.scheduler.tasks[name].interval = float(iv)
            if data.get("state") == AgentState.PAUSED.value:
                self.state = AgentState.PAUSED
                self.paused_event.clear()
            logger.info("Restored agent state (owner_cursor=%s, paused=%s)",
                        self._last_owner_msg_id, self.state == AgentState.PAUSED)
        except Exception as exc:
            logger.warning("restore_state partial failure: %s", exc)

    # ===================================================================
    # SECTION 5 — Human control via WhatsApp
    # ===================================================================
    async def poll_owner_commands(self):
        """Read new inbound WhatsApp rows, act on those from the owner.

        DB-only: the web bot's poll_new_messages() (run by check_replies) and the
        360dialog webhook both write whatsapp_responses; we just read it. No edit
        to whatsapp_bot.py / main.py required.
        """
        if not OWNER_PHONE or not self.db or not self.db.db:
            return
        try:
            cur = await self.db.db.execute(
                "SELECT id, phone, body FROM whatsapp_responses "
                "WHERE id > ? ORDER BY id", (self._last_owner_msg_id,))
            rows = await cur.fetchall()
        except Exception as exc:
            logger.debug("owner-command poll failed: %s", exc)
            return
        owner_norm = _normalize_phone(OWNER_PHONE)
        for row in rows or []:
            msg_id, phone, body = row[0], row[1], row[2]
            self._last_owner_msg_id = max(self._last_owner_msg_id, msg_id)
            if self.verify_owner(phone, owner_norm):
                await self.parse_command(body or "")
        self.save_state()

    def verify_owner(self, phone: str, owner_norm: Optional[str] = None) -> bool:
        owner_norm = owner_norm if owner_norm is not None else _normalize_phone(OWNER_PHONE)
        if not owner_norm:
            return False
        return _normalize_phone(phone).endswith(owner_norm[-10:])

    async def parse_command(self, body: str) -> str:
        cmd = (body or "").strip().upper()
        try:
            if cmd == "PAUSE":
                await self.pause("owner")
                await self._reply_owner("Paused. Send RESUME to continue.")
                return "PAUSE"
            if cmd == "RESUME":
                await self.resume()
                await self._reply_owner("Resumed.")
                return "RESUME"
            if cmd == "STATUS":
                metrics = await self.monitor.health_metrics(self)
                await self._reply_owner(self.monitor.status_text(self, metrics))
                return "STATUS"
            if cmd == "REPORT":
                stats = await self.components["analytics"].get_stats()
                await self._send_owner_report(stats)
                await self._reply_owner("Report sent.")
                return "REPORT"
            if cmd in ("STOP OUTREACH", "STOP"):
                for name in ("send_initial_outreach", "send_followups",
                             "prospect_new_leads"):
                    if name in self.scheduler.tasks:
                        self.scheduler.tasks[name].enabled = False
                self.save_state()
                await self._reply_owner("Outreach stopped. Replies still handled. "
                                        "Send RESUME-OUTREACH to re-enable.")
                return "STOP_OUTREACH"
            if cmd in ("RESUME OUTREACH", "RESUME-OUTREACH", "START OUTREACH"):
                for name in ("send_initial_outreach", "send_followups",
                             "prospect_new_leads"):
                    if name in self.scheduler.tasks:
                        self.scheduler.tasks[name].enabled = True
                self.save_state()
                await self._reply_owner("Outreach re-enabled.")
                return "RESUME_OUTREACH"
            if cmd == "HOT LEADS":
                await self._reply_hot_leads()
                return "HOT_LEADS"
            await self._reply_owner(
                "Commands: PAUSE, RESUME, STATUS, REPORT, STOP OUTREACH, HOT LEADS")
            return "UNKNOWN"
        except Exception as exc:
            logger.error("parse_command(%s) failed: %s", cmd, exc)
            return "ERROR"

    async def _reply_owner(self, text: str):
        try:
            await self.components["whatsapp"].send_message(OWNER_PHONE, text)
        except Exception as exc:
            logger.debug("owner reply failed: %s", exc)

    async def _reply_hot_leads(self):
        try:
            leads = await self.db.get_leads_by_status("hot")
        except Exception as exc:
            await self._reply_owner(f"Could not fetch hot leads: {exc}")
            return
        if not leads:
            await self._reply_owner("No hot leads right now.")
            return
        lines = ["Top hot leads:"]
        for row in leads[:10]:
            company = row[1] if len(row) > 1 else "?"
            score = row[11] if len(row) > 11 else "?"
            lines.append(f"  {company} (score {score})")
        await self._reply_owner("\n".join(lines))

    async def status_dict(self) -> dict:
        metrics = await self.monitor.health_metrics(self) if self.monitor else {}
        return {"state": self.state.value, "metrics": metrics}


# ===========================================================================
# SECTION 6 — Entry point
# ===========================================================================
def _print_status_from_disk():
    """--status: read the last persisted state + health line. Read-only."""
    if not STATE_PATH.exists():
        print("No agent_state.json found — the agent has not run yet.")
        return
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except Exception as exc:
        print(f"Could not read agent_state.json: {exc}")
        return
    print("=== Autonomous Agent (from disk) ===")
    for key in ("state", "started_at", "last_heartbeat", "date",
                "tasks_completed_today", "disabled_tasks", "daily_report_sent_on"):
        print(f"  {key:<22}: {state.get(key)}")
    # Last health line from the action log, if present.
    if LOG_PATH.exists():
        try:
            last_health = None
            for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line)
                if rec.get("action") == "health":
                    last_health = rec
            if last_health:
                m = last_health.get("detail", {})
                print("  --- last health ---")
                for k in ("pending_emails", "pending_whatsapp", "unreplied",
                          "hot_leads", "booking_pipeline"):
                    print(f"  {k:<22}: {m.get(k)}")
        except Exception:
            pass


def _write_state_field(field_name: str, value):
    """--pause / --resume: nudge a running agent by writing the state file.
    The live loop reads its own state from memory, but on next save it honors a
    PAUSED flag set here at startup; primarily this primes the next start."""
    data = {}
    if STATE_PATH.exists():
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            data = {}
    data[field_name] = value
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Autonomous lead-gen agent. No flags = live 24/7 loop.")
    p.add_argument("--status", action="store_true",
                   help="Print last persisted state and exit (read-only).")
    p.add_argument("--pause", action="store_true",
                   help="Mark the agent paused in agent_state.json and exit.")
    p.add_argument("--resume", action="store_true",
                   help="Mark the agent running in agent_state.json and exit.")
    p.add_argument("--dry-run", action="store_true",
                   help="Run the full loop but only log intent — no sends/writes.")
    p.add_argument("--test", action="store_true",
                   help="Startup + one pass of each due task (implies dry-run), then exit.")
    return p.parse_args(argv)


async def _amain(args):
    agent = AutonomousAgent(dry_run=args.dry_run, test_mode=args.test)
    await agent.startup()
    if agent.state == AgentState.ERROR and not args.test:
        logger.error("Agent failed to start; exiting.")
        return
    if args.test:
        # Smoke test: force every task due, run one pass, print status, exit.
        for t in agent.scheduler.tasks.values():
            t.next_run = time.monotonic() - 1
        await agent.run_forever()  # test_mode breaks after one iteration
        metrics = await agent.monitor.health_metrics(agent)
        print(agent.monitor.status_text(agent, metrics))
        await agent.shutdown()
        return
    await agent.run_forever()


def main():
    args = parse_args()
    if args.status:
        _print_status_from_disk()
        return
    if args.pause:
        _write_state_field("state", AgentState.PAUSED.value)
        print("Marked agent PAUSED in agent_state.json.")
        return
    if args.resume:
        _write_state_field("state", AgentState.RUNNING.value)
        print("Marked agent RUNNING in agent_state.json.")
        return
    try:
        asyncio.run(_amain(args))
    except KeyboardInterrupt:
        print("\nInterrupted — exiting.")
    except Exception as exc:  # top-level guard: never crash to a traceback
        logger.error("fatal: %s", exc)


if __name__ == "__main__":
    main()
