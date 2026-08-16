# JotPsych Re-engagement Machine — Recommendation

## What I built
A monthly, self-running nurture machine for the ~15,000 signed-up-but-not-paying
clinicians. From only `name, email, mobile` it: segments each clinician (domain-based:
solo/early-stage vs. established group), picks one of three content angles per segment
using a self-improving bandit, generates a personalized draft, runs it through a brand
QC gate that rejects and retries bad output, sends (simulated: writes to `outbox/`),
and stamps every send with a unique tracking token for attribution.

**Why this and not a CRM:** the three forbidden examples (grouping, logging, flagging)
never leave the system. This one does — it produces and ships a distinct artifact
(the email) per clinician, every cycle.

## The numbers it reports on itself (5 test cycles, sample data)
- 30/30 clinicians processed each cycle, 0 dropped after QC retry
- QC gate demonstrably catches bad output — see `metrics.json` /
  `python3 machine.py --demo-reject` for a live example and rejection reason
- Bandit visibly reallocates send volume toward the higher-performing variant per
  segment across cycles (see `variant_performance_by_segment` in `metrics.json`) —
  `established_group` shifted from evenly split to ~34/9 sends favoring
  `revenue_recovery`, its best-observed variant
- Every send has a unique `ref` token in its tracking link — a real return can be
  joined back to `run_log.jsonl` by that token to credit the machine

## How the 1–2 human hours/month get spent
- Skim `metrics.json`: sent count, QC catch rate, which variant is winning per segment
- Spot-check 3–5 outbox drafts, not all of them — QC is doing the per-email reading
- Decide once a quarter whether to retire a losing variant or add a new one to the pool

## What's simulated vs. real (labeled in code)
Real: input, segmentation, variant selection, generation call, QC gate, tracking
tokens, state persistence. Simulated: the actual send (ESP/Twilio call) and the
return signal (real webhook from a booked-demo event). Swapping `INPUT_FILE` to the
real export and `CLAUDE_MODE` to `"cli"`/`"api"` is the only change needed to go live.

## Week 2
1. Wire `simulate_engagement()` to a real signal — a UTM-tagged landing page hit or a
   "welcome back" webhook from Stripe/CRM — so the bandit learns from real behavior.
2. Add mobile as a second channel for clinicians who don't open email after 2 cycles
   (same bandit, same QC gate, new send function).
3. Raise `EPSILON` or move to Thompson sampling — the epsilon-greedy bandit is slow to
   escape an early bad pick, visible in the solo_early_stage segment locking onto
   `consolidation` in cycle 1 before enough data came in.
