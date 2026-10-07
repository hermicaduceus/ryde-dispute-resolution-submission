# Build session eight — brief: follow-up questions built in code (W13) + two small fixes (W11)

**Target:** `tests/test_session_eight.py` (16 tests) plus six rewritten tests in
`tests/test_party_surface.py`, `tests/test_session_six_fixes.py` and
`tests/test_session_six_fixes_2.py` fail on the current code. Make them pass **without editing
any test**, keep the full suite green (`python3 -m unittest`, expect 360 tests, OK), and change
nothing under `tests/`, `data/` or `tools/`. Commit in logical steps.

## The ruling behind this session (operator, 2026-09-24)

The party-facing decision message is already built in code from structured fields. The
advocates' follow-up questions are the one party-facing text a model still writes, and the only
thing checking them is the word filter (`is_party_safe`). That filter checks vocabulary, not
meaning: "How sure are you that the driver took the long way?" and "You cancelled well before
pickup, correct?" both pass it.

**Ruled: structured question slots.** An advocate no longer writes a question. It returns slot
ids from a fixed bank, and code renders each id into a sentence we wrote. Any free text in
`follow_up_questions` from the model is **ignored**. The word filter and the rest of
`_questions_for_party` stay exactly as they are, as the backstop.

There are two kinds of slot id:

- a **bank id** (`route_shown`, `waiting_place`, ...) renders the bank sentence for the
  dispute's category. The bank is written in the rider's voice, so it is offered **only when the
  rider filed**;
- a **form id** (`form:<intake key>`, e.g. `form:expected_route`) re-asks one intake question,
  quoting the label from `INTAKE_QUESTIONS`. Offered for either filer.

An id that is not offered for this dispute renders to nothing and is dropped with an operator
note. It is never passed through.

## Items

**B1. `app/schemas.py`: the bank and the renderer.** Insert this block directly after
`blank_field_question` and before `class ContractError`. The sentences are approved copy: use
them **verbatim** (the tests compare them character for character).

```python
#: W13: the follow-up questions an advocate may ask, per category. An advocate picks ids;
#: code renders the sentence, so no model-written text reaches a party. Sentences are
#: written for the rider: a driver-filed dispute is offered form slots only.
FOLLOW_UP_QUESTION_BANK: Dict[str, tuple] = {
    "route_deviation": (
        ("route_shown", "What route did the app show you before the trip started?"),
        ("route_discussed", "Did you and the driver talk about taking a different route? If so, what was said?"),
        ("stops_or_changes", "Did you ask the driver to stop, wait or change the destination during the trip? If so, where?"),
        ("road_conditions", "Did the driver mention a road closure or diversion during the trip?"),
        ("pickup_dropoff", "Were you picked up and dropped off where your booking said? If not, where?"),
    ),
    "no_show_charge": (
        ("waiting_place", "Where exactly were you waiting when the trip was meant to start?"),
        ("driver_contact", "Did the driver call or message you? If so, what was said?"),
        ("arrival_time", "Roughly what time did you reach the pickup point?"),
        ("cancel_reason", "Who cancelled the trip, and what was the reason?"),
    ),
}

#: A form slot re-asks one intake question, quoting its label from INTAKE_QUESTIONS.
FORM_SLOT_PREFIX = "form:"
FORM_SLOT_QUESTION_TEMPLATE = 'About the form question "%s": could you tell us a little more?'


def follow_up_slot_ids(category: str) -> List[str]:
    """Every slot id an advocate may pick for this category: bank ids, then form ids."""
    bank = [slot for slot, _ in FOLLOW_UP_QUESTION_BANK.get(category, ())]
    form = [FORM_SLOT_PREFIX + key for key, _ in INTAKE_QUESTIONS.get(category, ())]
    return bank + form


def render_follow_up_slot(category: Any, slot_id: Any, filed_by: str = "rider") -> Optional[str]:
    """The party-facing sentence for one slot id, or None when the id is not offered."""
    if not isinstance(category, str) or not isinstance(slot_id, str):
        return None
    if slot_id.startswith(FORM_SLOT_PREFIX):
        label = dict(INTAKE_QUESTIONS.get(category, ())).get(slot_id[len(FORM_SLOT_PREFIX):])
        return FORM_SLOT_QUESTION_TEMPLATE % label if label else None
    if filed_by != "rider":
        return None
    return dict(FOLLOW_UP_QUESTION_BANK.get(category, ())).get(slot_id)
```

**B2. `AdvocateCase` in `app/schemas.py`.**

- Add a field `follow_up_slots: List[str] = field(default_factory=list)` directly before
  `follow_up_questions`.
- `from_payload` gains two keyword-only parameters after `validation`:
  `category: Optional[str] = None, filed_by: str = "rider"`.
- In `from_payload`, read `slots = _optional_text_list(payload, "follow_up_slots", agent)`.
  Render each one with `render_follow_up_slot(category, slot, filed_by)`. When it returns
  `None`, append this to `notes`:
  `"follow-up slot %r dropped: not offered for this %s dispute" % (slot, category)`.
  Keep the rendered sentences in order and drop exact duplicates.
- Set `follow_up_slots=slots` and `follow_up_questions=<the rendered sentences>`.
  **`from_payload` must never read `payload["follow_up_questions"]` again.** That is the
  whole fix.
- In `to_dict`, emit `"follow_up_slots"` directly before `"follow_up_questions"`.

**B3. `app/agents/base.py`: the advocate contract.**

- `OUTPUT_SCHEMA`: replace the `follow_up_questions` entry with
  `"follow_up_slots": ["at most 3 slot ids from FOLLOW-UP QUESTION SLOTS, or []"]`.
- `system_prompt`: the FOLLOW-UP QUESTIONS section refers to `follow_up_slots` and says the
  party never sees text the advocate writes. The literal string `follow_up_questions` must not
  appear anywhere in the system prompt.
- `user_prompt`: add a `FOLLOW-UP QUESTION SLOTS` block, placed before `YOUR TASK`, with one line
  `slot_id: sentence` for every id in `follow_up_slot_ids(dispute.category)` that
  `render_follow_up_slot(dispute.category, slot, dispute.filed_by)` renders. Skip ids that
  render to `None`. When none render, print `(none offered)`.
- `run()`: pass `category=dispute.category, filed_by=dispute.filed_by` to
  `AdvocateCase.from_payload`. The `advocate.follow_up_requested` event payload keeps
  `questions` (the rendered sentences) and also carries `"slots": case.follow_up_slots`.

**B4. `app/llm/mock.py`: the mock asks through form slots.** Replace the free-text
follow-up block in `_advocate_response`. It keeps the same trigger: the filing party's advocate
only, only when the dispute carries no follow-up answers. It now returns
`"follow_up_slots": [FORM_SLOT_PREFIX + key for key in blank_keys if key in labels]` and no
`follow_up_questions` key at all. Import `FORM_SLOT_PREFIX` and drop the now-unused
`blank_field_question` import. The mock's questions lose their `MOCK` prefix, which is accepted:
the question is code-written copy now, and the slot ids stay visible to the operator.

**B5. `app/pipeline.py` `_questions_for_party`: logic unchanged.** Update the docstring only:
the questions it receives are code-rendered slot sentences, and the word check is a backstop.

**B6. `app/cli.py` `_print_report`: the `llm:` label.** It reads only `resolution["ruling"]`,
so a withheld case (for example `--pack ryde-synth-v1 --dispute RD-0109`) prints `llm: n/a`
although the Judge ran. Read `resolution["ruling"] or resolution["withheld_candidate"]` and fall
back to `n/a` only when both are empty. `OS-0301`, which never reaches the Judge, must still
print `n/a`.

**B7. `app/evidence/compute.py`, the `promo = abs(...)` line: comment only, no code change.**
It was reported as a possible bug and it is not. `tools/build_corpus.py` stores promo
**negative** (`breakdown["promo_sgd"] = -round(promo, 2)`) and the fare formula subtracts it, so
`abs()` makes the stored sign irrelevant. Say so in a comment at the line.
`W11PromoSign` fails if `abs()` is removed.

**B8. `docs/architecture.md`: make the question path true again.** Around lines 102-107, 124,
182-186 and 238-241 the doc says the advocates' model writes the follow-up questions and that
the word check is "a real but imperfect filter" for them. Both are now false. Rewrite those
passages to say: advocates pick slot ids; code renders each question from a fixed bank or from
the form's own labels; no model-written text reaches a party; the word check is a backstop for
questions as it already is for the decision message. Keep `tests/test_architecture_doc.py`
green, and name no internal session numbers or tool names in the doc.

## Out of scope

`ui/`, `app/server.py`, the logic of `_questions_for_party`, the party page, and anything under
`tests/`, `data/` or `tools/`. If a test looks wrong, stop and ask. Do not edit it.

## Done means

- `python3 -m unittest`: 360 tests, OK.
- `python3 -m app.cli --pack ryde-synth-v1 --dispute RD-0109` prints `llm: mock` in its header.
- `git status --short` is clean after your last commit.
