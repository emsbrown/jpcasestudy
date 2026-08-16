#!/usr/bin/env python3
"""
JotPsych Re-engagement Machine
================================
Turns the 3-field lapsed-signup list (name, email, mobile) into a running,
self-measuring, self-improving nurture campaign that brings clinicians back,
and traces returns back to the machine.

REAL PARTS (would work unchanged on the real 15k list):
  - CSV input
  - domain-based segmentation (the decision)
  - variant selection via a simple bandit that shifts weight to what's working
  - QC gate that rejects bad drafts before they'd ever send
  - tracking-token generation for attribution
  - metrics/state persistence across runs (the "improves itself" part)

SIMULATED PARTS (clearly labeled, swap for the real thing in prod):
  - SEND: writes to outbox/ instead of an ESP/Twilio API
  - ENGAGEMENT: a probability draw instead of real opens/clicks/webhooks,
    weighted by QC/content quality so the bandit has a real signal to learn from
  - CLAUDE CALL: falls back to a local template if no live Claude CLI/API key
    is present (this sandbox has neither); set CLAUDE_MODE = "cli" or "api"
    and the same functions call the real thing with zero other changes.

Config to swap for the real run: INPUT_FILE below. Nothing else changes.
"""

import csv
import json
import os
import random
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# CONFIG — this is the one-line swap to run on the real clinician list
# ---------------------------------------------------------------------------
INPUT_FILE = "lapsed_clinicians.csv"          # <-- swap to the real export
STATE_FILE = "state.json"                      # bandit + history, persists across monthly runs
OUTBOX_DIR = Path("outbox")                    # simulated "sent" emails land here
METRICS_FILE = "metrics.json"                  # what the machine reports about itself
RUN_LOG_FILE = "run_log.jsonl"                 # append-only audit trail, one line per clinician per run

CLAUDE_MODE = os.environ.get("CLAUDE_MODE", "stub")  # "cli" | "api" | "stub"
EPSILON = 0.15                                 # bandit exploration rate

GENERIC_EMAIL_DOMAINS = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com"}

# Three content angles (the machine will learn which segment responds to which)
VARIANTS = {
    "consolidation": "Lead with: stop paying 6-7 vendors (EHR, e-rx, billing, telehealth, scribe, "
                      "messaging) separately. JotPsych is one login, from $299/mo.",
    "revenue_recovery": "Lead with: JotPsych catches the revenue leaking out of your practice today — "
                         "the unbilled visit, the undercoded note, the denied claim — and shows you how to get it back.",
    "time_back": "Lead with: the scribe drafts your note while you're still in the room, so you get "
                 "hours back each week for patients instead of paperwork.",
}

JOTPSYCH_CONTEXT = """
JotPsych is behavioral health practice software: AI scribe + billing/RCM + credentialing +
e-prescribing + scheduling, one login. Used by psychiatrists, PMHNPs, and therapists, solo
practices through 100+ clinician groups. Core software starts at $299/mo; billing is a
percentage of collections; no long-term contract lock-in. Real customer language: clinicians
say it saves ~1-2 hours/day, cuts note submission time, and improves documentation quality.
""".strip()


# ---------------------------------------------------------------------------
# STEP 1 — INPUT (real: reads a file the machine did not write)
# ---------------------------------------------------------------------------
def load_clinicians(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# STEP 2 — DECISION #1: segment from the email domain alone (no extra fields)
# ---------------------------------------------------------------------------
def segment(email):
    domain = email.split("@")[-1].lower().strip()
    if domain in GENERIC_EMAIL_DOMAINS:
        return "solo_early_stage"
    return "established_group"


# ---------------------------------------------------------------------------
# STEP 3 — DECISION #2: which content variant to try (self-improving bandit)
# ---------------------------------------------------------------------------
def load_state():
    if Path(STATE_FILE).exists():
        return json.loads(Path(STATE_FILE).read_text())
    # cold start: no history yet, all variants untested per segment
    return {
        "cycle_count": 0,
        "segments": {
            seg: {v: {"sent": 0, "returned": 0} for v in VARIANTS}
            for seg in ("solo_early_stage", "established_group")
        },
    }


def save_state(state):
    Path(STATE_FILE).write_text(json.dumps(state, indent=2))


def choose_variant(seg, state):
    """Epsilon-greedy bandit: mostly exploit the best-performing variant for
    this segment so far, occasionally explore another. This is the piece that
    'gets better after every cycle without a person rewriting it' — the return
    rate per variant/segment shifts the weights on the next run automatically."""
    perf = state["segments"][seg]
    if random.random() < EPSILON or state["cycle_count"] == 0:
        return random.choice(list(VARIANTS))
    # exploit: pick the variant with the best observed return rate so far
    def rate(v):
        s = perf[v]["sent"]
        return perf[v]["returned"] / s if s > 0 else -1
    return max(VARIANTS, key=rate)


# ---------------------------------------------------------------------------
# STEP 4 — GENERATE the draft (real Claude call, or local stub for this sandbox)
# ---------------------------------------------------------------------------
def _resolve_claude_executable():
    """On Windows, npm-installed CLIs are .cmd wrapper scripts, and
    subprocess.run can't CreateProcess them directly without shell=True or
    the exact .cmd path. shutil.which() finds the real, runnable path."""
    import shutil
    path = shutil.which("claude")
    if path:
        return path
    # last-resort fallback for Windows npm global installs
    for candidate in ("claude.cmd", "claude.exe"):
        path = shutil.which(candidate)
        if path:
            return path
    raise FileNotFoundError(
        "Could not find the claude CLI on PATH. Run 'claude --version' "
        "manually to confirm it's installed and on PATH."
    )


def call_claude(prompt, system=None):
    if CLAUDE_MODE == "cli":
        claude_path = _resolve_claude_executable()
        cmd = [claude_path, "-p", prompt]
        if system:
            cmd += ["--append-system-prompt", system]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=90,
            shell=(os.name == "nt"),  # Windows .cmd wrappers need shell=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"claude CLI failed: {result.stderr}")
        return result.stdout.strip()

    if CLAUDE_MODE == "api":
        import urllib.request
        body = json.dumps({
            "model": "claude-sonnet-4-6",
            "max_tokens": 500,
            "system": system or "",
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "content-type": "application/json",
                "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                "anthropic-version": "2023-06-01",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return "".join(b["text"] for b in data["content"] if b["type"] == "text").strip()

    # ---- STUB: deterministic local generation so the loop runs end-to-end
    # right now, in this sandbox, with no key. Swap CLAUDE_MODE to "cli" on
    # E's machine and this function's output is the only thing that changes.
    return _stub_generate(prompt)


def _stub_generate(prompt):
    """Very small templated generator standing in for the live Claude call."""
    if "SUBJECT+BODY" in prompt:
        name = prompt.split("Clinician name: ")[1].split("\n")[0]
        angle = prompt.split("Angle: ")[1].split("\n")[0]
        first = name.split()[0]
        bodies = {
            "consolidation": (f"Subject: One login instead of seven, {first}?\n\n"
                               f"Hi {first},\n\nLast time we talked you were juggling separate tools for "
                               f"notes, e-prescribing, and billing. JotPsych runs all of it from one login, "
                               f"starting at $299/mo, month-to-month. Worth 15 minutes to see if it'd simplify "
                               f"your stack?\n\n— The JotPsych team"),
            "revenue_recovery": (f"Subject: The claim that got denied without you knowing, {first}\n\n"
                                  f"Hi {first},\n\nMost practices lose money to unbilled visits and undercoded "
                                  f"notes without ever seeing it happen. JotPsych flags it before it costs you. "
                                  f"Want a 15-min look at what it'd catch in your practice?\n\n— The JotPsych team"),
            "time_back": (f"Subject: Your notes, done before the patient leaves, {first}\n\n"
                          f"Hi {first},\n\nJotPsych's scribe drafts your note while you're still in the room — "
                          f"clinicians get 1-2 hours back a day. Want to see it on a real session?\n\n"
                          f"— The JotPsych team"),
        }
        return bodies.get(angle, bodies["time_back"])

    if "QC_CHECK" in prompt:
        draft = prompt.split("DRAFT:\n", 1)[1]
        reasons = []
        if len(draft) < 120:
            reasons.append("too short / thin to feel personal")
        if "AI" in draft or "as an AI" in draft.lower():
            reasons.append("reads as AI-written")
        if "!!!" in draft or draft.count("!") > 2:
            reasons.append("over-eager tone, doesn't sound like JotPsych")
        if "Subject:" not in draft:
            reasons.append("missing subject line")
        if reasons:
            return "REJECT: " + "; ".join(reasons)
        return "PASS"

    return ""


# ---------------------------------------------------------------------------
# STEP 5 — QC GATE (protects the brand; must catch bad output before it sends)
# ---------------------------------------------------------------------------
def qc_check(draft):
    prompt = f"QC_CHECK\nDRAFT:\n{draft}"
    result = call_claude(prompt, system=(
        "You are JotPsych's brand QC gate. Reject anything that sounds AI-written, "
        "generic, over-eager, or unclear on what JotPsych does. Reply PASS or "
        "REJECT: <reason>."
    ))
    if result.startswith("PASS"):
        return True, None
    return False, result.replace("REJECT:", "").strip()


# ---------------------------------------------------------------------------
# STEP 6 — ATTRIBUTION (unique token per send, so a return is traceable)
# ---------------------------------------------------------------------------
def tracking_link(clinician_id, variant):
    token = uuid.uuid4().hex[:10]
    return f"https://jotpsych.com/back?ref={token}&utm_source=reengage&utm_campaign={variant}", token


# ---------------------------------------------------------------------------
# STEP 7 — OUTPUT (simulated send: writes a file, in prod this is an ESP call)
# ---------------------------------------------------------------------------
def send_output(clinician, draft, link):
    OUTBOX_DIR.mkdir(exist_ok=True)
    safe_name = clinician["email"].replace("@", "_at_")
    path = OUTBOX_DIR / f"{safe_name}.txt"
    path.write_text(f"{draft}\n\n[tracking link: {link}]\n[SIMULATED SEND — would call ESP/Twilio API here]\n")
    return str(path)


# ---------------------------------------------------------------------------
# STEP 8 — SIMULATED ENGAGEMENT (stand-in for real opens/clicks/webhook)
#   Labeled clearly: this is the one part that can't be real without a live
#   list and a live ESP. The probability is tied to QC pass + variant, so the
#   bandit above has a genuine (if simulated) signal to learn from.
# ---------------------------------------------------------------------------
def simulate_engagement(variant, qc_passed):
    base_rate = {"consolidation": 0.09, "revenue_recovery": 0.14, "time_back": 0.06}[variant]
    if not qc_passed:
        base_rate *= 0.3
    return random.random() < base_rate


# ---------------------------------------------------------------------------
# ORCHESTRATION — one full monthly cycle
# ---------------------------------------------------------------------------
def run_cycle():
    clinicians = load_clinicians(INPUT_FILE)
    state = load_state()
    state["cycle_count"] += 1

    run_log = []
    rejected_examples = []
    sent_count = 0
    skipped_count = 0
    returned_count = 0

    for row in clinicians:
        name, email = row["name"], row["email"]
        seg = segment(email)                      # decision #1

        # audience judgment: skip if we don't even have a usable email
        if "@" not in email:
            skipped_count += 1
            run_log.append({"email": email, "action": "skipped", "reason": "invalid email"})
            continue

        variant = choose_variant(seg, state)       # decision #2
        gen_prompt = (f"SUBJECT+BODY\nClinician name: {name}\nAngle: {variant}\n"
                       f"Context: {JOTPSYCH_CONTEXT}\nInstruction: {VARIANTS[variant]}")
        draft = call_claude(gen_prompt, system="Write a short, warm, specific re-engagement email. No AI-sounding language.")

        qc_passed, reason = qc_check(draft)
        if not qc_passed:
            # one retry with the reason fed back in, matching a real QC loop
            retry_prompt = gen_prompt + f"\nPrevious attempt was rejected for: {reason}. Fix that and rewrite."
            draft = call_claude(retry_prompt, system="Write a short, warm, specific re-engagement email. No AI-sounding language.")
            qc_passed, reason2 = qc_check(draft)
            if not qc_passed:
                skipped_count += 1
                rejected_examples.append({"email": email, "first_reason": reason, "second_reason": reason2, "draft": draft})
                run_log.append({"email": email, "action": "rejected_twice", "reason": reason2})
                continue
            rejected_examples.append({"email": email, "first_reason": reason, "second_attempt": "passed"})

        clinician_id = uuid.uuid4().hex[:8]
        link, token = tracking_link(clinician_id, variant)
        outbox_path = send_output(row, draft, link)
        sent_count += 1

        state["segments"][seg][variant]["sent"] += 1
        returned = simulate_engagement(variant, qc_passed)   # SIMULATED signal
        if returned:
            state["segments"][seg][variant]["returned"] += 1
            returned_count += 1

        run_log.append({
            "email": email, "segment": seg, "variant": variant,
            "qc_passed": qc_passed, "token": token, "outbox_path": outbox_path,
            "simulated_return": returned,
        })

    save_state(state)

    with open(RUN_LOG_FILE, "a", encoding="utf-8") as f:
        for entry in run_log:
            entry["cycle"] = state["cycle_count"]
            entry["timestamp"] = datetime.now(timezone.utc).isoformat()
            f.write(json.dumps(entry) + "\n")

    metrics = {
        "cycle": state["cycle_count"],
        "run_at": datetime.now(timezone.utc).isoformat(),
        "total_input": len(clinicians),
        "sent": sent_count,
        "skipped_or_rejected_twice": skipped_count,
        "qc_catch_example": rejected_examples[0] if rejected_examples else None,
        "simulated_returns_this_cycle": returned_count,
        "variant_performance_by_segment": {
            seg: {v: dict(perf) for v, perf in variants.items()}
            for seg, variants in state["segments"].items()
        },
        "note": "sent/skip counts and QC decisions are real. 'returned' is SIMULATED "
                "(stand-in for a real webhook/CRM signal) so the bandit has something "
                "to learn from during this test run.",
    }
    Path(METRICS_FILE).write_text(json.dumps(metrics, indent=2))
    return metrics


def demo_qc_reject():
    """Standalone proof that the QC gate actually catches bad output.
    Feeds it a deliberately bad draft (the kind a raw, unchecked LLM call
    can produce) and shows the reject + reason."""
    bad_draft = ("As an AI language model, I would like to inform you that JotPsych "
                 "is a great tool!!! You should really really consider trying it out!!!")
    passed, reason = qc_check(bad_draft)
    return {"draft_tested": bad_draft, "qc_passed": passed, "rejection_reason": reason}


# ---------------------------------------------------------------------------
# STEP 9 — TRIGGER: this is what makes it a machine and not you pressing run.
# `--serve` starts a real long-running scheduler process that fires run_cycle()
# on its own, on an interval, with no human in the loop. For the real deploy,
# the interval is monthly (see MONTHLY_INTERVAL_SECONDS below); for this demo
# run it's compressed to something you can actually watch trigger itself in
# a few minutes, and that's labeled clearly in the output.
# ---------------------------------------------------------------------------
MONTHLY_INTERVAL_SECONDS = 60 * 60 * 24 * 30   # real production cadence
DEMO_INTERVAL_SECONDS = 20                      # compressed so you can watch it fire live


def run_scheduler(demo=True, max_cycles=None):
    interval = DEMO_INTERVAL_SECONDS if demo else MONTHLY_INTERVAL_SECONDS
    label = "DEMO (compressed interval, for proof-of-run)" if demo else "PRODUCTION (monthly)"
    print(f"[scheduler] starting — mode: {label} — interval: {interval}s — no human will press run again")
    fired = 0
    while True:
        ts = datetime.now(timezone.utc).isoformat()
        print(f"[scheduler] trigger fired at {ts} (cycle {fired + 1})")
        m = run_cycle()
        fired += 1
        print(f"[scheduler] cycle {fired} complete — sent={m['sent']} skipped={m['skipped_or_rejected_twice']}")
        if max_cycles and fired >= max_cycles:
            print(f"[scheduler] reached max_cycles={max_cycles}, stopping demo loop "
                  f"(in production this loop runs indefinitely, or is replaced by a cron entry "
                  f"calling `python3 machine.py --once`)")
            break
        import time
        time.sleep(interval)


if __name__ == "__main__":
    if "--demo-reject" in sys.argv:
        print(json.dumps(demo_qc_reject(), indent=2))
    elif "--serve" in sys.argv:
        # e.g. python3 machine.py --serve --demo --max-cycles 3
        demo_mode = "--demo" in sys.argv
        max_c = None
        if "--max-cycles" in sys.argv:
            idx = sys.argv.index("--max-cycles")
            max_c = int(sys.argv[idx + 1])
        run_scheduler(demo=demo_mode, max_cycles=max_c)
    else:
        m = run_cycle()
        print(json.dumps(m, indent=2))
