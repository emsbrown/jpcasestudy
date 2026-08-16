Case Study: Re-engagement Machine

A small, self-running system that turns a lapsed-clinician list into a measurable monthly re-engagement program.
For reviewers: start hereEverything needed to evaluate the case study is in this repository.

**Recommended review path:**

1. **`ONE_PAGER.md`** — the recommendation, operating model, and rationale.
2. **`machine.py`** — the implementation, commented step by step.
3. **Root `.txt` files** — the actual generated/sent drafts.
4. **`metrics.json`** — the machine's reported operating metrics.

The goal is to make the work easy to evaluate as both a **business system and an implementation**: clear inputs, decision logic, quality controls, outputs, measurement, and an autonomous trigger.

---

## Run it in one click

The repository includes sample data, so no API key or external service is required.

### 1. Clone or download the repository

Open a terminal inside the downloaded folder.

**Windows:** Open the folder in File Explorer → click the address bar → type `powershell` → press Enter.

### 2. Run one complete cycle

```bash
python machine.py
```

That runs the full monthly workflow:

```text
lapsed_clinicians.csv
        ↓
Segmentation
        ↓
Content-angle selection
        ↓
Draft generation
        ↓
QC gate
        ↓
Simulated send
        ↓
Metrics + audit trail
```

The run takes a few seconds.

It reads the sample clinician list, determines a segment and content angle for each clinician, drafts the outreach, runs each message through the QC gate, and writes the resulting outputs to the repository.

### Outputs

* `outbox/` — simulated sends
* `metrics.json` — machine-reported metrics
* `run_log.jsonl` — timestamped audit trail
* `state.json` — learned state carried across cycles

---

## Prove it responds to new data

This is intentionally not a fixed demo. You can swap the input and produce different outputs.

### 1. Use the included alternate dataset

```bash
python -c "import machine; machine.INPUT_FILE = 'alt_test.csv'; print(machine.run_cycle())"
```

This:

* imports the project's code
* temporarily points `INPUT_FILE` at `alt_test.csv`
* runs a complete cycle
* prints the resulting summary

No source files are modified. This is a one-off input override.

Open the newly generated `.txt` files and compare them with the original outputs. You should see different names and, depending on the data, different segments and content angles.

That is the key distinction between a **machine** and a replayed demo: the output changes because the input changes.

### 2. Use your own test data

Create a CSV with:

```text
name,email
```

`mobile` is optional.

Then point the machine at that file using the same override pattern.

### 3. Point it at the real 15,000-clinician list

Open `machine.py` and change:

```python
INPUT_FILE = "lapsed_clinicians.csv"
```

to the filename of the real export.

The required fields are:

```text
name,email,mobile
```

No other architectural change is required for the input layer.

---

## Prove the machine triggers itself

The system also includes a real scheduler loop, so there is no human pressing "run" between cycles.

### Watch three autonomous cycles

```bash
python3 machine.py --serve --demo --max-cycles 3
```

In demo mode, the cadence is compressed to **20 seconds** so the behavior is observable during a review.

The process:

1. Starts the scheduler.
2. Waits for the next scheduled trigger.
3. Runs the complete cycle automatically.
4. Records the run and timestamp in `run_log.jsonl`.
5. Repeats until three cycles have completed.
6. Stops automatically.

No manual intervention is required after startup.

### Production cadence

```bash
python3 machine.py --serve
```

Production mode runs on a **30-day cadence** and continues indefinitely.

The same behavior can also be deployed behind a conventional scheduler, for example:

```cron
0 9 1 * * cd /path/to/reengagement_machine && python3 machine.py >> cron.log 2>&1
```

The important point is architectural rather than scheduler-specific: **the workflow has a defined trigger and does not depend on a person remembering to execute it.**

---

## Validate the QC gate

The repository includes a deliberate failure mode so the quality-control layer can be tested independently.

```bash
python3 machine.py --demo-reject
```

This demonstrates that the system does not simply generate and send whatever it produces. Output passes through a QC gate before reaching the simulated send layer.

---

## What this demonstrates

The case study is designed around a simple operating principle:

> **Automate the repeatable work, make decisions explicit, put controls around the risky parts, and measure the system's behavior.**

The implementation demonstrates:

* **Input → decision → action:** the system converts a raw lapsed-clinician list into individualized outreach.
* **Segmentation:** clinicians are classified before content is selected.
* **Content strategy:** the segment informs the outreach angle rather than relying on one generic message.
* **Quality control:** generated output must pass a gate before it is treated as sent.
* **Measurement:** the machine reports on its own activity.
* **Auditability:** runs are timestamped and persisted.
* **State:** `state.json` carries learning between cycles.
* **Autonomy:** a scheduler can initiate future cycles without a human pressing run.
* **Replaceable integrations:** the sandbox uses local simulation, while the production boundaries are clearly identified.

---

## Going live

The sandbox deliberately avoids external dependencies so the reviewer can run it immediately.

A production implementation has four integration points.

### 1. Connect the real audience

Replace:

```python
INPUT_FILE = "lapsed_clinicians.csv"
```

with the real export.

Expected fields:

```text
name,email,mobile
```

### 2. Connect the model

Set:

```python
CLAUDE_MODE = "cli"
```

to use an authenticated local `claude` CLI, or:

```python
CLAUDE_MODE = "api"
```

with `ANTHROPIC_API_KEY` configured for direct API access.

### 3. Connect the sending infrastructure

Replace `send_output()` so the generated messages are delivered through the production ESP, such as SendGrid or Postmark, rather than written to `outbox/`.

### 4. Connect real engagement signals

Replace `simulate_engagement()` with the real webhook/event source for outcomes such as booked demos or reactivation.

The existing `ref` token provides the mechanism for associating an engagement event back to the originating outreach.

---

## Operating model

The important production boundary is:

```text
             ┌─────────────────────┐
             │  Clinician Export   │
             └──────────┬──────────┘
                        ↓
             ┌─────────────────────┐
             │    Segmentation     │
             └──────────┬──────────┘
                        ↓
             ┌─────────────────────┐
             │ Content / Messaging │
             │      Decision       │
             └──────────┬──────────┘
                        ↓
             ┌─────────────────────┐
             │   Draft Generation  │
             └──────────┬──────────┘
                        ↓
             ┌─────────────────────┐
             │       QC Gate       │
             └──────────┬──────────┘
                        ↓
             ┌─────────────────────┐
             │    Send / ESP       │
             └──────────┬──────────┘
                        ↓
             ┌─────────────────────┐
             │ Engagement / Event  │
             └──────────┬──────────┘
                        ↓
             ┌─────────────────────┐
             │ Metrics + State     │
             └──────────┬──────────┘
                        │
                        └────→ next cycle
```

This is intentionally designed as a **closed operating loop**, not a one-off campaign script.

---

## Repository map

| File                    | Purpose                                            |
| ----------------------- | -------------------------------------------------- |
| `ONE_PAGER.md`          | Executive recommendation and case-study summary    |
| `machine.py`            | End-to-end workflow and scheduler                  |
| `lapsed_clinicians.csv` | Sample input dataset                               |
| `alt_test.csv`          | Alternate dataset for proving input responsiveness |
| `*.txt`                 | Generated/simulated sent drafts                    |
| `metrics.json`          | Machine-reported metrics                           |
| `run_log.jsonl`         | Run history and timestamps                         |
| `state.json`            | Persistent state across cycles                     |
| `outbox/`               | Sandbox send output                                |

---

## The reviewer's shortest path

If you have **5 minutes**:

1. Read `ONE_PAGER.md`.
2. Open `machine.py`.
3. Run `python machine.py`.
4. Inspect `outbox/` and `metrics.json`.

If you have **10–15 minutes**:

5. Run the alternate-input test.
6. Run `python3 machine.py --demo-reject`.
7. Run `python3 machine.py --serve --demo --max-cycles 3`.
8. Inspect `run_log.jsonl` and `state.json`.

That should be enough to see the full loop: **data in → decisions → controlled generation → output → measurement → state → autonomous next cycle.**
