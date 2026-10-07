# Build session seven — brief: the architecture document

**Status at handoff: 2026-09-24.** Suite 339 tests: the only failures are the 14 in
`tests/test_architecture_doc.py`, which is this session's acceptance target. Read HEAD
yourself with `git log -1`.

Pre-flight:

```bash
cd ~/hermes-workspace/projects/ryde-build
git status --short                               # expect empty
python3 -m unittest discover -s tests -t .       # expect 339 tests, failures only in test_architecture_doc
```

## Why this session exists

The challenge statement requires "**Architecture Diagram** – A clear visual representation of
the multi-agent system and key components" (`docs/statement-extract.md`). The system is built.
Nothing yet explains it to a judge who has five minutes and has never seen the repo.

## The deliverable

Make `tests/test_architecture_doc.py` pass **without editing it**, keep every other test green,
and write a document a non-engineer judge can follow.

### 1. `docs/architecture.md`

Audience: a Ryde or Tencent Cloud judge who reads the README first, then this. Plain English,
short paragraphs, tables where a list of like things is compared. Target 1,200 to 2,000 words.
Use exactly these `##` sections, in this order:

1. **Overview**: what the system does in five sentences. Three agents, a deterministic
   evidence layer, gates in code, two surfaces.
2. **Diagram**: exactly one ```mermaid``` block, `flowchart TD`, at most 20 nodes. It must
   show the rider intake form, the server, the routing step (out-of-scope → human review), the
   Evidence Pack, the Rider Advocate and the Driver Advocate, the stop-and-ask branch back to
   the party, the Judge, the gates, the four outcomes, the event log feeding the operator
   console, and the policy document and dataset pack as inputs. Node text in plain words
   ("Rider Advocate", not `rider_advocate`). Keep node ids short (A, B, J...).
3. **Components**: a table with component, file(s) and one-line responsibility. Name every
   module listed in the test's `CORE_MODULES`, each as a backticked repo path.
4. **Lifecycle of a dispute**: the steps of `run_dispute` in `app/pipeline.py`, in the order
   the code runs them, naming the event each step emits (every value in `EventType`,
   backticked, e.g. `run.started`).
5. **The four outcomes**: a table with outcome (`ruled`, `withheld`, `human_review`,
   `needs_info`), when it happens, whether the Judge ran, what the party page shows (`decided`,
   `under_review`, `passed_to_support`, `needs_info`).
6. **Gates enforced in code**: each gate with its file and the condition as written in code:
   the confidence threshold (value from `app/config.json`), ESC-4's autonomous cap (value from
   `app/config.json`, written as `SGD 50`), ESC-2 for route cases whose deviation cannot be
   measured, the one-round follow-up limit, and routing of out-of-scope categories to human
   review. Say plainly that these are Python, not prompt instructions, and why: a prompt is a
   request, code is a guarantee.
7. **Observability**: `events.jsonl`, `payloads/`, `case_file.json` under `runs/<run_id>/`,
   and how `ui/` renders them (event strip, full payload one click deeper).
8. **What the parties see**: `party_view` in `app/server.py` is an allowlist that fails closed;
   `party_message_for_ruling` in `app/schemas.py` composes the decision message from structured
   fields, and the Judge's explanation stays in the operator console. Mention the word check on
   questions as a backstop, not the protection.
9. **Policy and dataset packs**: `docs/policy.md` is swappable; the two packs under
   `data/packs/` by name (backticked), which one is the default in `app/config.json` (say
   "default" on the same line as its name), and that ground truth is kept out of what the
   agents see.
10. **LLM provider**: the `LLMClient` seam in `app/llm/`, the mock provider, the Tencent
    adapter in `app/llm/tencent.py`, and the fact that every mock string carries a `MOCK`
    prefix. Be honest that the Tencent endpoint is not yet called.
11. **Limits**: what the system does not do yet, stated plainly (no real LLM calls yet, two
    categories only, driver-side form not built, the word check is incomplete by design).

### 2. `README.md`

- Rename "Planned architecture" to "Architecture". Keep the agent table, add the **same**
  Mermaid block as the doc (byte-identical inside the fence), and link
  `[docs/architecture.md](docs/architecture.md)`.
- In the Documents list, replace the "(required deliverable, to come)" line with a link.
- Remove the hard-coded test count from the run block: `python3 -m unittest discover -s tests -t .`
  with no number beside it.
- Touch nothing else in the README.

### 3. `CODEBUDDY.md` layout block only

Remove "(to come)" from the `ui/` and `architecture.md` lines, and change `(178, stdlib only)`
to `(stdlib only)`. Nothing else.

## Rules for this session

- **Every sentence must be true of the code at HEAD.** Read the code before you describe it.
  When unsure, cite the file and line you read, or leave the claim out. Do not describe
  anything as planned, coming or future except in **Limits**.
- **Do not edit anything under `app/`, `ui/`, `data/`, `tests/` or `tools/`.** If you find
  what looks like a bug while reading, do not fix it: list it at the end of your final
  message under "Found while reading".
- No internal labels: no tracker ids (W5, R1, S2, T3...), no "session six", no names of
  other tools. The test checks this.
- Use numbers only when they come from `app/config.json` or the code. Never estimate one.
- Commit in small steps (doc first, then README, then CODEBUDDY.md), each with the suite
  result in the message.
- On a conflict with `docs/statement-extract.md` or `CODEBUDDY.md`, stop and ask.

## Done means

```bash
python3 -m unittest discover -s tests -t .      # 339 tests, OK
```
and a final message listing each section with the files you read to write it.
