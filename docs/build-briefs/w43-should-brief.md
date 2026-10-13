# W43 SHOULD lane — build brief (draft, for the operator/dispatch)

**Lane:** W43 SHOULD (three should-fix defects from the 2026-10-13 Sol document review).
**Prepared baseline:** the lane's RED tests are already in `main` when you start. Frozen build
SHA at prep time: `486bfa58df029ab23ea54ac1587b237d32c359ef`.
**Interpreter:** `/usr/bin/python3` (3.9.6), absolute path, with `PYTHONPATH` removed:
`env -u PYTHONPATH /usr/bin/python3 -m unittest ...`.
**Fences:** no network, no servers, no commits other than the one named at the end, no `.env`
reads, no edits outside ALLOWED FILES. If a test looks wrong, STOP and report; never edit a
test to make the build pass.

---

## 1. ALLOWED FILES

Application (the fix):

| File | What changes |
|---|---|
| `app/cli.py` | the run id is uniquified against the runs already on disk; the CLI reports a refused run directory cleanly |
| `app/events.py` | the event log refuses a directory that already holds a run |
| `app/agents/judge.py` | RD-5's floor reads the overcharge the records prove (breakdown-only case); the fare-delta definition sentence |

Pins this round re-points (each one already fails on the prepared baseline, by design):

| File | What changes |
|---|---|
| `tests/test_w32_judge_prompt.py` | `SENTENCE` (new definition) and `BASE_JUDGE_AST_SHA256` (re-baselined from YOUR final `app/agents/judge.py`) |
| `tests/test_w24_prompt_panel.py` | `FROZEN_RUNTIME["app/agents/judge.py"]` only |
| `tests/test_w34_launcher.py` | `FROZEN_W34` entries for `app/agents/judge.py`, `app/cli.py`, `app/events.py` only |
| `tests/test_w35_r2_K.py` | `PROTECTED_TREE_SHA` only (`PROTECTED_TREE_FILES` stays 49) |
| `docs/prompts.md` | line 200: the quoted Judge sentence (one line, nothing else) |
| `tests/test_pipeline.py` | one line: the incidental `EventLog(run_dir, "test-run")` construction in `test_every_event_payload_ref_resolves` is dropped (a second event log over a filled run directory is now refused; the test reads the log from disk anyway) |

The lane's own new test files (already in `main`, do NOT edit them):

`tests/test_w43_should_run_id.py`, `tests/test_w43_should_rd5_floor.py`,
`tests/test_w43_should_judge_delta_sentence.py`.

**Nothing else.** In particular `app/server.py`, `app/eval.py`, `app/pipeline.py`,
`ui/`, `data/` and every other test file stay byte-identical.

> The pin list above is longer than the ticket's first guess. Four of these files are byte-freeze
> pins over the very files this round edits (`FROZEN_W34` hashes whole app files; `FROZEN_RUNTIME`
> and `PROTECTED_TREE_SHA` hash `app/agents/judge.py`; the W32 pin hashes the whole `judge.py`
> AST). The list was derived by running the full suite over a reference build and reading which
> tests reddened — that red set IS the set of pins this round may re-point, and nothing else may
> move.

---

## 2. CONTRACT

### S1 — same-second CLI invocations must never merge run histories

Today the run id is `%Y%m%dT%H%M%SZ-<slug(dispute_id)>` and `EventLog` accepts a directory that
already exists, so the two command forms README:122 and README:130-131 documents, run inside one
second, land on ONE directory: the log carries two `run.started` events with the sequence
restarting at 1 mid-file, the payload files are rewritten in place, and `case_file.json` embeds
only the later run's events.

Contract:

1. The generated run id stays `<UTC second>Z-<dispute slug>` for the FIRST run of that second —
   the visible format does not drift (the operator console's hint text and its pin say
   "named like `20260921T161731Z-RD-0109`"; `tests/test_w43_should_run_id.py` pins the exact
   name shape too). Each later run of the same second takes a numeric suffix: `-2`, `-3`, …
2. `EventLog` refuses a run directory that already holds a run (an `events.jsonl`, or a
   `payloads/` directory — the directory a run's first writer created). A directory that merely
   exists (a fresh `--out` path, a temp dir the caller made first) is NOT a run and is used as
   given. The `payloads/` creation is the atomic claim, so two writers racing for one id cannot
   both proceed.
3. `--run-id` is an override and stays one: a collision there is the operator's to fix, so the CLI
   prints a refusal on stderr and exits 1 (it must not die with a traceback, and must not write
   the run somewhere else).

Verbatim code (`app/cli.py`, after `_slug`):

```python
def generate_run_id(dispute_id: str, out_dir: Path, *, now: Optional[datetime] = None) -> str:
    """A run id no earlier run already owns.

    The stamp is UTC to the second and the dispute id keeps the directory readable, but two
    documented invocations in the same second would otherwise land on one directory and merge
    two histories into one log. So the id is uniquified against what is already on disk: the
    first run of a second keeps the plain documented name, and each later one takes a numeric
    suffix. ``--run-id`` overrides this entirely, and the event log refuses a directory that
    already exists, so a collision is never silently appended to.
    """
    stamp = (now if now is not None else datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    base = "%s-%s" % (stamp, _slug(dispute_id))
    run_id = base
    suffix = 1
    while (Path(out_dir) / run_id).exists():
        suffix += 1
        run_id = "%s-%d" % (base, suffix)
    return run_id
```

`app/cli.py::main` — replace the run-id construction and the `EventLog` line with:

```python
    out_dir = Path(args.out) if args.out else config.out_dir
    run_id = args.run_id or generate_run_id(dispute.dispute_id, out_dir)
    run_dir = out_dir / run_id
    try:
        events = EventLog(run_dir, run_id)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return EXIT_FAILED
```

`app/events.py::EventLog.__init__` — replace the two `mkdir` lines with:

```python
        # A run directory belongs to one run. Reusing a directory that already holds a run's
        # record restarts the sequence numbering, rewrites the same payload paths and leaves
        # two histories in one log while the case file embeds only the later one, so a second
        # writer is refused rather than appended into the first run's log. A directory that
        # merely EXISTS is not a run — a fresh --out path, or a temporary directory the caller
        # made first — and is used as given.
        if self.events_path.exists():
            raise ValueError(
                "refusing to reuse the run directory %s: it already holds a run's event log. "
                "Move it aside, or choose another run id." % self.run_dir
            )
        self.run_dir.mkdir(parents=True, exist_ok=True)
        try:
            # The atomic claim on this run directory: of two writers racing for one id, only
            # the one that creates the payloads directory proceeds.
            self.payloads_dir.mkdir(exist_ok=False)
        except FileExistsError as exc:
            raise ValueError(
                "refusing to reuse the run directory %s: it already holds a run's payloads. "
                "Move it aside, or choose another run id." % self.run_dir
            ) from exc
```

Keep `from datetime import datetime, timezone` at module level in `app/cli.py` and read the clock
as `datetime.now(timezone.utc)` — the RED test freezes that module-level name, so it must stay the
seam the run-id clock is read through (do not move the import into a function body).

### S2 — RD-5 gets a breakdown-only floor

Today RD-5's floor compares the ruling against `fare.difference_sgd`, which is computed from the
tariff rates. A route record that proves an overcharge through an INCONSISTENT BREAKDOWN alone —
charged SGD 15.00, recorded components summing SGD 10.00, no rates at all — leaves
`difference_sgd` None, so a no-action ruling and a short refund are both ruled with no gate
firing. README:159-160 promises RD-5 withholds a route ruling that "refunds less than the
overcharge the records prove".

Contract — the floor reads the overcharge the records prove, in this order:

1. `fare.difference_sgd` when it is a finite figure (unchanged behaviour, and it takes
   precedence);
2. otherwise, when ALL of these hold, `fare.charged_sgd - fare.component_sum_sgd`:
   the record states NO tariff rates at all (`not fare.rates`), `breakdown_consistent is False`,
   `charged_sgd` and `component_sum_sgd` are finite figures, and ESC-2 has not already fired.
3. A ruling that is not a refund of at least the proven figure, on a route case, when that figure
   is at or above `DE_MINIMIS_SGD`, is withheld by RD-5 — same reason and summary wording as
   today, with the proven figure named.
4. A difference that is PRESENT but not finite stays the existing unreadable branch (a full hold,
   RD-4 suppressed). RD-4 remains the ceiling and keeps its own suppression rules unchanged.

Deliberately narrow, and the narrowing is itself pinned:

- the widening reads the breakdown only where the record states NO rates; an unreadable rate is
  ESC-2's reason and ESC-2 already holds that case;
- when ESC-2 holds the case, RD-5 does not add a second reason (one record defect reads as one
  reason, exactly as RD-4 does);
- category scope is untouched: RD-5 gates route cases only.

This is Python in the gate block, never prompt text.

Verbatim code (`app/agents/judge.py`, the gate block — replace the `fare = pack.fare` … `gate_summaries.append(...)` opening of the RD-5 clause):

```python
        fare = pack.fare
        # RD-5's floor reads the overcharge the RECORDS prove, not only the one the tariff
        # rates recompute. A route record that states no tariff rates at all has no
        # difference_sgd to read, yet its own inconsistent breakdown can prove an overcharge
        # on its own (EV-3: the line items add up to less than the charge), so a floor reading
        # only that field lets a no-action or short refund through on a record whose own
        # numbers show the overcharge. The widening stays narrow on purpose: it reads the
        # breakdown only where the record states NO rates (a rate the record cannot read is
        # ESC-2's reason and ESC-2 already holds that case — one record defect reads as one
        # reason, as RD-4 does), and a difference present but not finite remains the unreadable
        # branch below. Refunding more than the proven figure is not this gate's concern:
        # RD-4 is the ceiling.
        rd5_proven_sgd = None
        if fare is not None and _is_figure(fare.difference_sgd):
            rd5_proven_sgd = round(fare.difference_sgd, 2)
        elif (
            fare is not None
            and fare.difference_sgd is None
            and not fare.rates
            and fare.breakdown_consistent is False
            and _is_figure(fare.charged_sgd)
            and _is_figure(fare.component_sum_sgd)
            and not any(gate == "ESC-2" for gate, _reason in gate_failures)
        ):
            rd5_proven_sgd = round(fare.charged_sgd - fare.component_sum_sgd, 2)
        if (
            dispute.category == CATEGORY_ROUTE_DEVIATION
            and rd5_proven_sgd is not None
            and rd5_proven_sgd >= DE_MINIMIS_SGD
        ):
            covered = (
                ruling.action == RulingAction.REFUND.value
                and round(ruling.recommended_amount_sgd, 2) >= rd5_proven_sgd
            )
            if not covered:
                gate_failures.append(
                    (
                        "RD-5",
                        "RD-5: the records prove an overcharge of SGD %.2f; the proposed "
                        "%s of SGD %.2f does not refund it"
                        % (
                            rd5_proven_sgd,
                            ruling.action,
                            ruling.recommended_amount_sgd,
                        ),
                    )
                )
                gate_summaries.append(
                    "the ruling refunds less than the overcharge the records prove (RD-5)"
                )
```

The `elif` that follows (difference present but not finite) is unchanged: it must still read
`fare.difference_sgd is not None and not _is_figure(fare.difference_sgd)`.

### S3 — the Judge prompt's fare-delta definition sentence

Today `Judge.system_prompt` tells the model the field is "the difference between the quoted fare
and the metered fare for the route taken". No quoted-fare field exists anywhere in the record
(`charged_sgd`, the breakdown components, the rates), and the field is actually
recomputed-actual-route minus recomputed-estimated-route. Replace the sentence; keep the closing
claim that delivery is decided by the code gates (the CONFIDENCE paragraph stays byte-identical).

Verbatim replacement inside `Judge.system_prompt` (the three string literals):

```python
            "deviation_fare_delta_sgd is the difference between the fare recomputed for "
            "the route actually taken and the fare recomputed for the estimated route, "
            "not money the rider paid.\n\n"
```

and the same sentence, once, as the quoted line in `docs/prompts.md` (line 200):

```
"deviation_fare_delta_sgd is the difference between the fare recomputed for the route actually taken and the fare recomputed for the estimated route, not money the rider paid."
```

The doc sentence wraps the shipped one in double quotes on its own line; everything around it
(the "Fare-field definition." lead-in and the following "The prompt gives the definition; whether
a route ruling is delivered is still decided by the gates above, in code.") is unchanged.

---

## 3. RE-POINT THE PINS FROM YOUR OWN FINAL BYTES

Run these AFTER the code is final (the digests move with every edit). The commands print the
value to paste; do not paste the values from this brief — yours are the truth.

```bash
cd <your worktree>
env -u PYTHONPATH /usr/bin/python3 - <<'EOF'
import hashlib
from pathlib import Path
for rel in ("app/agents/judge.py", "app/cli.py", "app/events.py"):
    print("FROZEN_W34", rel, hashlib.sha256(Path(rel).read_bytes()).hexdigest())
print("FROZEN_RUNTIME app/agents/judge.py",
      hashlib.sha256(Path("app/agents/judge.py").read_bytes()).hexdigest())
lines = []
for rel in ("app/agents", "app/llm", "docs/policy.md", "data"):
    path = Path(rel)
    files = [path] if path.is_file() else sorted(
        p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    for f in files:
        lines.append("%s\0%s\n" % (f.as_posix(), hashlib.sha256(f.read_bytes()).hexdigest()))
print("PROTECTED_TREE_FILES", len(lines))
print("PROTECTED_TREE_SHA", hashlib.sha256("".join(sorted(lines)).encode()).hexdigest())
EOF
```

- `tests/test_w34_launcher.py::FROZEN_W34` — the three entries above; keep the surrounding
  comments' convention (name the round that released the file) but the comment text is yours.
- `tests/test_w24_prompt_panel.py::FROZEN_RUNTIME` — the `app/agents/judge.py` entry only.
- `tests/test_w35_r2_K.py::PROTECTED_TREE_SHA` — the aggregate; `PROTECTED_TREE_FILES` must still
  be 49 (no file was added or removed).
- `tests/test_w32_judge_prompt.py::BASE_JUDGE_AST_SHA256` — the digest of the AST with the
  sentence removed; the pin's own helper prints it. Note it is an AST digest: comments, blank
  lines and where the sentence's string literals are split are free, but names, expression
  structure and string contents are not, so apply the code above as written.
- `tests/test_w32_judge_prompt.py::BASE_SYSTEM_SHA256` must NOT change (the sentence is removed
  before hashing) — if it fails, the prompt changed beyond the sentence.
- `tests/test_w32_judge_prompt.py::SENTENCE` — the new sentence, character for character. On the
  prepared baseline this pin is RED in four places; that is the point of it.

Stop rule: if a re-pointed pin still fails, compare your file against the code in §2 line by
line and fix the CODE. Never edit a constant to whatever your build produced without checking
that the only difference is the one the round intends.

---

## 4. RUN-ID FORMAT PIN INVENTORY

The run-id FORMAT is `<UTC second stamp>Z-<dispute slug>` (`_slug` keeps the case:
`20261013T045619Z-RD-0101`). Nothing in this round must change it, and the following places own
or consume it. None of them needs an edit — this is the list that says so.

| Where | What it pins / consumes | Action this round |
|---|---|---|
| `tests/test_w43_should_run_id.py::test_a_lone_run_keeps_the_documented_run_id_shape` | regex + exact name for a lone run | NEW pin (the lane's). Keeps the format; a `-1` suffix or a microsecond stamp reddens it |
| `ui/index.html:65` (`#run-folder-hint`) | operator-facing text: "named like `20260921T161731Z-RD-0109`" | none — no drift |
| `ui/app.js:38,40` | the same hint, two more variants | none |
| `tests/test_w35_C.py:47-52` | the exact hint strings (byte pin) | none |
| `app/eval.py:662-665`; `app/server.py:797-801` (`_new_run_id`) | their own run-id forms (`eval-<stamp>`, `<stamp>-<uuid8>`) | none — `app/eval.py`/`app/server.py` are not in ALLOWED FILES and must not be touched |
| `tests/test_w23_status_and_accounts.py:147-151` | copies runs under synthetic `<stamp>Z-<slug>` names and asserts the status endpoint returns the latest by run id | none — the suffix keeps lexicographic order after the base name |
| `tests/w27_replay_support.py:133,161`; `tests/test_w35_r2_K.py` run-fixture names | read run directories by their real name, no pattern | none |

Grep that produced it: `strftime`, `%Y%m%dT%H%M%SZ`, `[0-9]{8}T[0-9]{6}Z`, and
`run_id.(split|rsplit|startswith|endswith)` across `app/ tools/ ui/ tests/ docs/`.

---

## 5. SIBLING RED — DECLARED, DO NOT REPAIR

The MUST lane lands on `main` with this lane. Its RED tests are `tests/test_w43_must_*.py`
(exact file names as committed; substitute them if the parent renamed them). **Those files fail
on purpose** — they are the acceptance tests for the other three defects (NS-6 on web filings,
the non-finite rate/component holes, `party_view` on an unhashable outcome) and the sibling
builds them.

Every `FAIL:`/`ERROR:` in a `tests/test_w43_must_*.py` file on your branch is the sibling's
declared RED. Do not read it, do not repair it, do not weaken it, and do not count it as your
regression. Your own arithmetic is:

```
your branch's total failures  = this lane's RED (18 on the prepared baseline)
                              + the sibling's declared RED
total errors                  = 0
every FAIL: line in a file this lane owns
```

Green-on-the-prepared-baseline tests inside this lane's files are PRESERVE pins, not broken
tests: `test_a_lone_run_keeps_the_documented_run_id_shape`,
`test_a_directory_that_is_not_yet_a_run_is_usable`,
`test_a_refund_of_exactly_the_proof_is_delivered`,
`test_a_refund_above_the_proof_is_held_by_rd4_alone`,
`test_a_proof_below_the_de_minimis_line_is_not_gated`,
`test_an_unreadable_difference_still_holds_and_still_suppresses_rd4`,
`test_esc2_alone_holds_a_record_the_breakdown_also_proves`,
`test_a_record_that_states_rates_keeps_the_difference_based_floor`,
`test_no_show_case_with_an_inconsistent_breakdown_is_not_an_rd5_case`,
`test_the_definition_matches_how_the_evidence_layer_computes_the_field`,
`test_the_sentence_still_leaves_delivery_to_the_code_gates`,
`test_a_record_with_no_rates_is_not_this_clause`,
`test_a_missing_difference_is_still_not_gated`,
`test_the_de_minimis_floor`, `test_no_action_is_never_held_by_ns8`, and the
`tests/test_w22_*` money-gate files. They must stay GREEN: they are why the widening is scoped
the way it is.

---

## 6. DONE MEANS

```bash
cd <your worktree>
env -u PYTHONPATH /usr/bin/python3 -m unittest discover -s tests -t .
```

Expected on this lane's own prepared baseline (`red/`, the RED tests in place, source unfixed):
**1639 tests, 18 failures, 0 errors, 15 skipped** — every failure in the files listed in §3/§1 and
none anywhere else.

Expected after the build: **1639 tests, 0 failures, 0 errors, 15 skipped** (15 browser/platform
skips, identical before and after; none of the skipped classes covers a file this round edits).

With the sibling's files present the totals rise by the sibling's declared RED — measure them,
never add them up.

Then report, in this order:

1. the exact command you ran and its full summary line;
2. the diff of each ALLOWED FILE against the frozen SHA (the five app/doc/pin files, and the
   one line in `tests/test_pipeline.py`);
3. each re-pointed constant's final value;
4. any test you could not make green, with its assertion message;
5. anything the brief did not cover that you had to decide.

What a correct build looks like when you are done, without any paid run:

- `env -u PYTHONPATH /usr/bin/python3 -m unittest tests.test_w43_should_run_id tests.test_w43_should_rd5_floor tests.test_w43_should_judge_delta_sentence tests.test_w32_judge_prompt` → 30 tests, OK.
- Two CLI runs in the same second into one `--out` → two directories, `…Z-RD-0101` and
  `…Z-RD-0101-2`, each with its own 11-event log ending `run.completed: ruled`.
- A route record with charged SGD 15.00, components summing SGD 10.00 and no rates, judged
  "no action" → withheld, one reason, `RD-5`, and the operator summary naming the gate with no
  figure in it.
- The shipped Judge system prompt carries the recomputed-route definition exactly once and the
  old quoted/metered sentence nowhere.

---

## 7. BATTERY (already run against the reference, for your information)

`mutations.json` (17 rows, literal search/replace, each applying exactly once) was swept against
the reference: every row turned the lane's tests RED, zero survivors, zero misapplied, baseline
green. The battery's literals are the reference's source text, so they do NOT carry to your
implementation unchanged: after your build, re-aim each literal at the strings that actually
shipped, confirm it applies exactly once, and re-run the whole sweep before reporting a count.
Rows that revert one aspect each: run-id precision, the caller's inline id, the visible format,
the CLI's refusal handling, the event log's refusal, the payloads claim, the whole breakdown-only
floor, the no-rates narrowing, the ESC-2 suppression, the de minimis line, the `>=` boundary, the
proven figure in the reason, the category scope, the sentence (restored / deleted), the doc
quote, and the W32 pin constant.

---

## PARENT ADDENDUM (2026-10-13, dispatch)

- You work in YOUR git worktree of this repo, on YOUR branch (`w43-should`), cut from the
  commit that carries this brief and the RED tests. Commit ONLY the files in ALLOWED FILES,
  with a clear message naming the three fixes; never push, never touch `main`. End your
  report with the exact commit hash.
- The sibling lane's RED tests land on `main` together with yours: they are
  `tests/test_w43_must_ns6_web_filing.py`, `tests/test_w43_must_unreadable_components.py`,
  `tests/test_w43_must_party_view_shapes.py` (the parent committed them under exactly these
  names — no substitution needed). Every `FAIL:` in those files on your branch is the
  sibling's declared RED; do not read, repair, weaken or count them.
- Your own new test files are already in `main` under the names this brief lists; do not edit
  them.
- Interpreter for every run: `env -u PYTHONPATH /usr/bin/python3`, `PYTHONDONTWRITEBYTECODE=1`.
