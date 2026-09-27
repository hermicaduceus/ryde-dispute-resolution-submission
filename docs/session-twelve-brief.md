# Session twelve brief: step-three form UX rebuild

**Status:** PLANNER-AUTHORED BRIEF. Acceptance tests are already written and RED.
**Lane:** CodeBuddy edits `app/` and `ui/` only. `tests/` is the planner's lane and is already
re-baselined to this contract (see *Do not touch* below).
**Model:** `gpt-5.6-luna`, effort `max`.

## Why

the operator reviewed the live party flow and made three rulings (2026-09-27):

1. **Yes/No questions must be buttons, not textareas.** Typing "yes" into a box is
   friction for a question that has two answers.
2. **A conditional elaborate bar.** Whenever an answer to a yes/no question may need
   more information, the party gets a box to explain. the operator's ruling: this applies to
   *either* answer where warranted — `safety_concern` = Yes is the headline case, and
   `asked_driver_to_stop` = Yes is the second example. **Implementation ruling for this
   build: reveal the elaborate box on either choice, for every yes/no question.** The
   box is optional everywhere; a blank box leaves the bare choice as the answer.
   There are no per-question rules to encode; do not add a per-key matrix.
3. **`what_went_wrong` is dropped.** It asked the same thing as the required
   description ("What happened?"), and the party has already said what went wrong when
   they picked the category card. **The required field moves to the top of the page.**

## Scope, with the exact contract the acceptance tests pin

### 1. `app/schemas.py`

- Delete `("what_went_wrong", "What went wrong?")` from **both** `route_deviation` and
  `no_show_charge` in `INTAKE_QUESTIONS`. Keep every other entry and its order.
- Add, beside `INTAKE_QUESTIONS`:

  ```python
  #: The intake questions that are answered with a choice, not free text. This table is
  #: the ONE owner of that fact: the party page tags each question from it (a test reads
  #: the page and asserts they agree), and the server's questionnaire validation derives
  #: from INTAKE_QUESTIONS.
  YES_NO_INTAKE_KEYS = frozenset({
      "was_route_agreed",
      "asked_driver_to_stop",
      "safety_concern",
      "did_driver_contact_you",
  })
  ```

- `app/server.py` needs no change: `QUESTIONNAIRES` derives from `INTAKE_QUESTIONS`, so
  dropping the key automatically (a) removes `form:what_went_wrong` from
  `follow_up_slot_ids`, (b) makes a filing that sends `what_went_wrong` a 400
  (`unknown intake answer`), and (c) drops the blank-field follow-up question for it.
  **Verify each of those three yourself before reporting.**

### 2. `ui/party/party.js`

- `QUESTIONNAIRES`: delete the two `what_went_wrong` entries; tag every remaining entry
  with a kind, in this exact shape (the acceptance tests parse it):

  ```js
  { key: "was_route_agreed", label: "Did you and the driver agree to take a different route?", kind: "yes_no" }
  ```

  `kind` is `"yes_no"` for exactly the four keys in `YES_NO_INTAKE_KEYS`, `"open"` for
  `expected_route` and `where_were_you`. **Labels stay byte-identical to
  `INTAKE_QUESTIONS`** — the label-owner test compares them.
- `buildQuestions()`: dispatch on kind, in this shape:

  ```js
  if (question.kind === "yes_no") { ... } else if (question.kind === "open") { ... }
  ```

  The `"open"` path keeps today's behaviour: label + `<textarea class="answer-input">`
  with `dataset.questionKey`.
- New `function buildChoiceQuestion(question)`: builds the label (same text, `htmlFor`
  `"answer-" + key`) plus
  - two real buttons, `element("button", "choice-button", "Yes")` and `"No"`, each
    `type="button"`, carrying `data-choice` with the choice word;
  - one elaborate box, `<textarea class="answer-input elaborate" rows="2">` with
    `data-elaborate-for="<key>"`, `placeholder="Tell us more (optional)"`, **hidden
    until a choice is made**;
  - on click of either button: mark that button `.selected` (and unmark the sibling),
    show the elaborate box.
- Submission, in the existing `details-form` submit handler: build `answers` from
  `QUESTIONNAIRES[state.category]` rather than by sweeping every textarea —
  - `yes_no`: the value is the chosen word alone, or `choice + " - " + text` when the
    elaborate box has non-blank text. **No choice made → `""`** (blank answers are
    allowed, exactly as an empty textarea was);
  - `open`: the textarea value, unchanged.
- Keep the file XSS-safe by construction: **zero `innerHTML`**, all text through
  `textContent`/`element()`. Do not introduce a template string that builds markup.

### 3. `ui/party/index.html`

- Move the required "What happened?" block (`label for="description"` + `#description`
  + the `details-error` node and the amount field, in their current relative order) so
  it renders **before** `#question-list` in document order. Keep every id, the
  `required` handling in JS, and the error text unchanged. The submit button stays last.

### 4. `ui/party/party.css`

- Style `.choice-button` (and its `.selected` state) and the elaborate box using the
  existing Ryde tokens/variables only — no new hex values. Buttons must look clickable
  and the selected state must be obvious without colour alone (a border/weight change is
  enough). Keep WCAG AA contrast on the pastel canvas, per the W10 record.

## Do not touch

- `tests/**` — the acceptance file `tests/test_party_form_ux.py` is the RED-first target
  and `tests/test_session_eight.py` / `tests/test_party_surface.py` are already
  re-baselined for this contract by the planner. **The one exception:** if a *SHA-256 byte pin*
  on `ui/party/party.js` (`tests/test_party_rebrand.py:132`,
  `tests/test_w12_demo_notice.py:237`) fails because the file legitimately changed,
  update that one constant to the new digest and report both old and new values. No other
  test edits.
- `data/**`, `docs/policy.md`, `tools/**`, `runs/**`, and the Tencent endpoint work.
- The outcome panel, the round-two answers UI, and the W12 demo notice. W13 (no
  model-written text reaches a party) is untouched by this change.

## Addendum (the planner, after the first build pass): accessible choice groups

The first pass built the buttons correctly but left the field unlabelled for assistive
tech: the choices container is a `div`, so `label.htmlFor = "answer-" + key` points at
something a `<label for>` cannot label, and the chosen answer lives only in a CSS class.
Fix in `ui/party/party.js` only:

- Give the question label an id: `label.id = "label-" + question.key`.
- Put `role="group"` and `aria-labelledby="label-" + question.key` on the choices
  container, and **drop the `htmlFor` that pointed at it** (a `div` is not labelable).
- Each choice button gets `aria-pressed`: `"false"` until chosen, `"true"` when chosen;
  clicking one must set its own to `"true"` and the sibling's to `"false"`.
- Nothing else changes: same ids, same `data-choice`, same `data-elaborate-for`, same
  answer-join rule, same visual behaviour.

Acceptance: `tests/test_party_form_ux.py::ChoiceGroupAccessibility` (already written and
RED). Then re-run `python3 -m unittest discover -s tests -t .` and update the two
`party.js` SHA-256 pins exactly as before, reporting old and new digests.

## Evidence to report

1. `python3 -m unittest discover -s tests` — the whole suite, with the total count, and
   `tests.test_party_form_ux` green.
2. The three derived server behaviours verified with a real request each (400 on
   `what_went_wrong`, `form:what_went_wrong` gone from the slot list, blank-field
   follow-up no longer offered for it).
3. A one-line list of every file you changed and why.
