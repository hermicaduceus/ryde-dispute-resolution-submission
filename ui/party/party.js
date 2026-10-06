(function () {
  "use strict";

  // The intake questions per role and category, in form order. Keys match what the
  // server accepts; blank answers are allowed and are what the follow-up round is
  // for. The driver table mirrors app/schemas.DRIVER_INTAKE_QUESTIONS and uses
  // actor-directed keys, so a driver answer can never be read as a rider answer.
  var QUESTIONNAIRES_BY_ROLE = {
    rider: {
      route_deviation: [
        { key: "expected_route", label: "What route did the app show you, and roughly how long was it?", kind: "open" },
        { key: "was_route_agreed", label: "Did you and the driver agree to take a different route?", kind: "yes_no" },
        { key: "asked_driver_to_stop", label: "Did you ask the driver to stop anywhere along the way?", kind: "yes_no" },
        { key: "safety_concern", label: "At any point were you worried for your safety?", kind: "yes_no" }
      ],
      no_show_charge: [
        { key: "where_were_you", label: "Where were you when the trip was meant to start?", kind: "open" },
        { key: "did_driver_contact_you", label: "Did the driver try to contact you?", kind: "yes_no" },
        { key: "safety_concern", label: "At any point were you worried for your safety?", kind: "yes_no" }
      ]
    },
    driver: {
      route_deviation: [
        { key: "route_shown_to_driver", label: "What route did the app show you, and roughly how long was it?", kind: "open" },
        { key: "route_agreed_with_rider", label: "Did you and the rider agree to take a different route?", kind: "yes_no" },
        { key: "rider_requested_stop", label: "Did the rider ask you to stop anywhere along the way?", kind: "yes_no" },
        { key: "safety_concern", label: "At any point were you worried for your safety?", kind: "yes_no" }
      ],
      no_show_charge: [
        { key: "driver_waiting_place", label: "Where did you wait, and for roughly how long?", kind: "open" },
        { key: "driver_contacted_rider", label: "Did you try to call or message the rider?", kind: "yes_no" },
        { key: "safety_concern", label: "At any point were you worried for your safety?", kind: "yes_no" }
      ]
    }
  };

  var CATEGORIES_BY_ROLE = {
    rider: [
      { id: "route_deviation", label: "My trip went the wrong way" },
      { id: "no_show_charge", label: "I was charged for a trip that did not happen" },
      { id: "property_damage_mess", label: "Property damage or a mess left behind" },
      { id: "safety_incident", label: "A safety incident" },
      { id: "other", label: "Something else" }
    ],
    driver: [
      { id: "route_deviation", label: "A question about the route I took" },
      { id: "no_show_charge", label: "A no-show or waiting fee" },
      { id: "property_damage_mess", label: "A cleaning fee or damage report" },
      { id: "safety_incident", label: "A safety incident" },
      { id: "other", label: "Something else" }
    ]
  };

  var STATUS_HEADINGS = {
    decided: "We have made a decision",
    under_review: "Your case is still under review",
    passed_to_support: "Your report has been passed to our support team",
    needs_info: "We need a little more information"
  };

  var state = {
    category: null,
    tripId: null,
    trips: [],
    runId: null
  };

  // W30: request ownership. The trip list loads asynchronously, so only the newest
  // request may render or land. Every load, category reset and trip Back bumps this
  // epoch; a callback whose captured epoch no longer matches changes nothing.
  var tripRequestEpoch = 0;

  // W20: one serialized intake answer — choice, delimiter and explanation together —
  // is at most this many Unicode code points. The form refuses locally before any
  // request and leaves every control exactly as the party left it.
  var MAX_INTAKE_ANSWER_CODE_POINTS = 2000;
  var INTAKE_ANSWER_TOO_LONG = "Intake answers must be at most 2000 characters.";

  // W20: what the current question list was built for. Trip Continue rebuilds the
  // questions only when the category or the trip changed, so Back/Continue keeps
  // every answer; a different trip or a category switch clears the draft.
  var questionsKey = null;

  var stepCategory = document.getElementById("step-category");
  var stepTrip = document.getElementById("step-trip");
  var stepDetails = document.getElementById("step-details");
  var outcomePanel = document.getElementById("outcome");
  var categoryOptions = document.getElementById("category-options");
  var tripOptions = document.getElementById("trip-options");
  var questionList = document.getElementById("question-list");
  var questionBoxes = document.getElementById("question-boxes");
  var outcomeTitle = document.getElementById("outcome-title");
  var outcomeReference = document.getElementById("outcome-reference");
  var outcomeMessage = document.getElementById("outcome-message");
  var outcomeQuestions = document.getElementById("outcome-questions");
  var outcomeStatus = document.getElementById("outcome-status");

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined && text !== null) {
      node.textContent = String(text);
    }
    return node;
  }

  function showError(id, message) {
    var node = document.getElementById(id);
    node.textContent = message;
    node.hidden = false;
  }

  function clearError(id) {
    var node = document.getElementById(id);
    node.textContent = "";
    node.hidden = true;
  }

  function show(node) {
    node.hidden = false;
  }

  function hide(node) {
    node.hidden = true;
  }

  // Unicode code points, not UTF-16 code units: an astral character (an emoji) is
  // one character to the server and must be one here too.
  function codePointCount(text) {
    var count = 0;
    for (var i = 0; i < text.length; i += 1) {
      var code = text.charCodeAt(i);
      if (code >= 0xD800 && code <= 0xDBFF && i + 1 < text.length) {
        var next = text.charCodeAt(i + 1);
        if (next >= 0xDC00 && next <= 0xDFFF) {
          i += 1;
        }
      }
      count += 1;
    }
    return count;
  }

  function request(method, path, body) {
    var options = { method: method };
    if (body !== undefined) {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(body);
    }
    return fetch(path, options).then(function (response) {
      return response.json().then(function (payload) {
        if (!response.ok) {
          var reason = payload && payload.error ? payload.error : "Something went wrong. Please try again.";
          throw new Error(reason);
        }
        return payload;
      });
    });
  }

  // ------------------------------------------------------------- page role

  // The shell's own marker selects the questionnaire and the category copy. A
  // missing marker is the original rider shell; any other explicit value refuses
  // the whole page. This is demo copy selection, not authentication: the role is
  // never read from the URL, the document body or the fixed driver account.
  var formSteps = document.getElementById("form-steps");
  var role = formSteps.getAttribute("data-filed-by");
  if (role === null) {
    role = "rider";
  }
  var QUESTIONNAIRES = QUESTIONNAIRES_BY_ROLE[role];
  var CATEGORIES = CATEGORIES_BY_ROLE[role];
  if (role !== "rider" && role !== "driver") {
    showError("category-error",
      "This filing page could not be loaded. Please return to the help page and try again.");
    return;
  }

  // ------------------------------------------------------------- step one

  CATEGORIES.forEach(function (category) {
    var card = element("button", "option-card", category.label);
    card.type = "button";
    card.addEventListener("click", function () {
      state.category = category.id;
      Array.prototype.forEach.call(categoryOptions.children, function (child) {
        child.classList.remove("selected");
      });
      card.classList.add("selected");
      document.getElementById("category-next").disabled = false;
      // Changing the category resets everything downstream (R3 page side): the trip
      // list belongs to the category, so a trip picked for one category must never
      // survive a switch to another, and neither must any answer (W20) — the shared
      // safety question included. The epoch bump abandons any in-flight load.
      tripRequestEpoch += 1;
      state.tripId = null;
      questionsKey = null;
      while (questionList.firstChild) {
        questionList.removeChild(questionList.firstChild);
      }
      while (tripOptions.firstChild) {
        tripOptions.removeChild(tripOptions.firstChild);
      }
      document.getElementById("trip-next").disabled = true;
      clearError("trip-error");
      clearError("details-error");
      hide(stepTrip);
      hide(stepDetails);
    });
    categoryOptions.appendChild(card);
  });

  document.getElementById("category-next").addEventListener("click", function () {
    clearError("category-error");
    hide(stepCategory);
    show(stepTrip);
    hide(stepDetails);
    loadTrips();
  });

  // ------------------------------------------------------------- step two

  // W30: bring the whole trip card on screen once the list has rendered. The card
  // is at most one screen tall, so aligning its top shows the Continue/Back bar
  // too. A response that arrives after the party pressed Back must not move the
  // page, so a hidden trip step is left alone.
  function landTripCard() {
    if (stepTrip.hidden) {
      return;
    }
    stepTrip.scrollIntoView({ block: "start" });
  }

  function loadTrips() {
    var epoch = ++tripRequestEpoch;
    // W20: the trip picked before this reload is remembered so the rendered list can
    // restore it — Back from the details step must not lose the party's selection.
    var wanted = state.tripId;
    clearError("trip-error");
    var boxes = tripOptions;
    while (boxes.firstChild) {
      boxes.removeChild(boxes.firstChild);
    }
    state.tripId = null;
    document.getElementById("trip-next").disabled = true;
    boxes.appendChild(element("p", "loading", "Loading trips…"));
    request("GET", "/api/trips?category=" + encodeURIComponent(state.category))
      .then(function (payload) {
        if (epoch !== tripRequestEpoch) {
          return;
        }
        while (boxes.firstChild) {
          boxes.removeChild(boxes.firstChild);
        }
        state.trips = Array.isArray(payload.trips) ? payload.trips : [];
        if (state.trips.length === 0) {
          boxes.appendChild(element("p", "hint", "No trips are available in the sample dataset."));
          landTripCard();
          return;
        }
        state.trips.forEach(function (trip) {
          var meta = [trip.date, trip.kind_label].filter(Boolean).join(" · ");
          var lines = [
            element("strong", null, trip.label),
            element("span", "trip-meta", meta)
          ];
          var charge = "";
          if (trip.fare_sgd !== null && trip.fare_sgd !== undefined) {
            charge = " · SGD " + Number(trip.fare_sgd).toFixed(2)
              + (trip.charge_label ? " " + trip.charge_label : "");
          }
          var detail = element("span", "trip-meta", "");
          detail.textContent = "Trip " + trip.trip_id + charge;
          var card = element("button", "option-card trip-card");
          card.type = "button";
          lines.forEach(function (line) { card.appendChild(line); });
          card.appendChild(detail);
          card.addEventListener("click", function () {
            // W20: a different trip invalidates the answers on the details step; the
            // same trip (a re-click after Back) keeps them.
            if (questionsKey && questionsKey.tripId !== trip.trip_id) {
              questionsKey = null;
              while (questionList.firstChild) {
                questionList.removeChild(questionList.firstChild);
              }
            }
            state.tripId = trip.trip_id;
            Array.prototype.forEach.call(boxes.children, function (child) {
              child.classList.remove("selected");
            });
            card.classList.add("selected");
            document.getElementById("trip-next").disabled = false;
          });
          // W20: restore the selection the party already made when this reload's list
          // still carries that trip. A list without it leaves the step unselected.
          if (wanted !== null && trip.trip_id === wanted) {
            state.tripId = wanted;
            card.classList.add("selected");
            document.getElementById("trip-next").disabled = false;
          }
          boxes.appendChild(card);
        });
        landTripCard();
      })
      .catch(function (error) {
        if (epoch !== tripRequestEpoch) {
          return;
        }
        while (boxes.firstChild) {
          boxes.removeChild(boxes.firstChild);
        }
        showError("trip-error", error.message);
        landTripCard();
      });
  }

  document.getElementById("trip-back").addEventListener("click", function () {
    // Back invalidates an outstanding load immediately: no new request has to
    // start for a late response to be stale.
    tripRequestEpoch += 1;
    show(stepCategory);
    hide(stepTrip);
    stepCategory.scrollIntoView({ block: "start" });
  });

  document.getElementById("trip-next").addEventListener("click", function () {
    clearError("trip-error");
    hide(stepTrip);
    // W20: rebuild the questions only when the category or the trip changed; the
    // unchanged pair keeps the draft the party already typed.
    if (!questionsKey || questionsKey.category !== state.category
        || questionsKey.tripId !== state.tripId) {
      buildQuestions();
      questionsKey = { category: state.category, tripId: state.tripId };
    }
    show(stepDetails);
    window.scrollTo(0, 0);
  });

  // --------------------------------------------------------- step three

  function buildChoiceQuestion(question) {
    var field = element("div", "field");
    var label = element("label", null, question.label);
    // The choices container is a div, so a <label for> cannot point at it. The
    // question text reaches assistive tech via role="group" + aria-labelledby.
    label.id = "label-" + question.key;
    var choices = element("div", "choice-options");
    choices.id = "answer-" + question.key;
    choices.role = "group";
    choices.setAttribute("aria-labelledby", "label-" + question.key);
    var elaborate = element("textarea", "answer-input elaborate");
    elaborate.rows = 2;
    elaborate.setAttribute("data-elaborate-for", question.key);
    elaborate.placeholder = "Tell us more (optional)";
    elaborate.setAttribute("aria-label", "Tell us more: " + question.label);
    elaborate.hidden = true;

    ["Yes", "No"].forEach(function (choice) {
      var button = element("button", "choice-button", choice);
      button.type = "button";
      button.setAttribute("data-choice", choice);
      button.setAttribute("aria-pressed", "false");
      button.dataset.questionKey = question.key;
      button.addEventListener("click", function () {
        if (!button.classList.contains("selected")) {
          elaborate.value = "";
        }
        Array.prototype.forEach.call(choices.children, function (sibling) {
          sibling.classList.remove("selected");
          sibling.setAttribute("aria-pressed", "false");
        });
        button.classList.add("selected");
        button.setAttribute("aria-pressed", "true");
        show(elaborate);
      });
      choices.appendChild(button);
    });

    field.appendChild(label);
    field.appendChild(choices);
    field.appendChild(elaborate);
    return field;
  }

  function buildQuestions() {
    while (questionList.firstChild) {
      questionList.removeChild(questionList.firstChild);
    }
    var questions = QUESTIONNAIRES[state.category] || [];
    questions.forEach(function (question) {
      if (question.kind === "yes_no") {
        questionList.appendChild(buildChoiceQuestion(question));
      } else if (question.kind === "open") {
        var field = element("div", "field");
        var label = element("label", null, question.label);
        label.htmlFor = "answer-" + question.key;
        var input = element("textarea", "answer-input");
        input.id = "answer-" + question.key;
        input.rows = 2;
        input.dataset.questionKey = question.key;
        field.appendChild(label);
        field.appendChild(input);
        questionList.appendChild(field);
      }
    });
  }

  document.getElementById("details-back").addEventListener("click", function () {
    hide(stepDetails);
    show(stepTrip);
    loadTrips();
  });

  document.getElementById("details-form").addEventListener("submit", function (event) {
    event.preventDefault();
    clearError("details-error");
    var description = document.getElementById("description").value;
    if (!description.trim()) {
      showError("details-error", "Please tell us what happened before sending.");
      return;
    }
    var amountText = document.getElementById("claim-amount").value.trim();
    var amount = null;
    if (amountText !== "") {
      amount = Number(amountText);
      if (!isFinite(amount) || amount < 0 || amount > 500) {
        showError("details-error", "The amount must be between 0 and 500 SGD.");
        return;
      }
    }
    var answers = {};
    (QUESTIONNAIRES[state.category] || []).forEach(function (question) {
      if (question.kind === "yes_no") {
        var selected = questionList.querySelector(
          '.choice-button.selected[data-question-key="' + question.key + '"]'
        );
        var elaborate = questionList.querySelector(
          'textarea[data-elaborate-for="' + question.key + '"]'
        );
        var choice = selected ? selected.dataset.choice : "";
        var elaboration = elaborate ? elaborate.value.trim() : "";
        answers[question.key] = choice
          ? (elaboration ? choice + " - " + elaboration : choice)
          : "";
      } else if (question.kind === "open") {
        var input = questionList.querySelector(
          'textarea[data-question-key="' + question.key + '"]'
        );
        answers[question.key] = input ? input.value : "";
      }
    });

    // W20: the cap counts the complete serialized answer — choice, delimiter and
    // trimmed explanation together — in Unicode code points. Nothing is truncated
    // and nothing is sent: the party keeps every character they typed.
    var tooLong = Object.keys(answers).some(function (key) {
      return codePointCount(answers[key]) > MAX_INTAKE_ANSWER_CODE_POINTS;
    });
    if (tooLong) {
      showError("details-error", INTAKE_ANSWER_TOO_LONG);
      return;
    }

    var submit = document.getElementById("details-submit");
    submit.disabled = true;
    request("POST", "/api/disputes", {
      category: state.category,
      filed_by: role,
      trip_id: state.tripId,
      description: description,
      claim_amount_sgd: amount,
      answers: answers
    })
      .then(function (view) {
        renderOutcome(view);
      })
      .catch(function (error) {
        submit.disabled = false;
        showError("details-error", error.message);
      });
  });

  // ------------------------------------------------------------- outcome

  function renderOutcome(view) {
    hide(document.getElementById("form-steps"));
    show(outcomePanel);
    state.runId = view.run_id;
    outcomeTitle.textContent = STATUS_HEADINGS[view.status] || "Your dispute has been received";
    outcomeReference.textContent = view.dispute_id;
    outcomeMessage.textContent = view.message;
    hide(outcomeStatus);
    buildAnswerBoxes(view);
    window.scrollTo(0, 0);
  }

  function buildAnswerBoxes(view) {
    while (questionBoxes.firstChild) {
      questionBoxes.removeChild(questionBoxes.firstChild);
    }
    var questions = Array.isArray(view.questions) ? view.questions : [];
    if (view.status !== "needs_info" || questions.length === 0) {
      hide(outcomeQuestions);
      return;
    }
    show(outcomeQuestions);
    questions.forEach(function (question, index) {
      var field = element("div", "field");
      var label = element("label", null, question);
      label.htmlFor = "reply-" + index;
      var input = element("textarea", "answer-input");
      input.id = "reply-" + index;
      input.rows = 2;
      // A round-two question the party has nothing to add to still needs an answer:
      // one click fills this box with the same sentence the run harness uses, so the
      // form can be completed without the party inventing words.
      var nothingMore = element("button", "nothing-more", "I have nothing more to add");
      nothingMore.type = "button";
      nothingMore.addEventListener("click", function () {
        input.value = "I have nothing more to add";
      });
      field.appendChild(label);
      field.appendChild(input);
      field.appendChild(nothingMore);
      questionBoxes.appendChild(field);
    });
  }

  document.getElementById("answers-submit").addEventListener("click", function () {
    clearError("answers-error");
    var replies = [];
    var complete = true;
    Array.prototype.forEach.call(questionBoxes.querySelectorAll("textarea"), function (input) {
      var label = questionBoxes.querySelector('label[for="' + input.id + '"]');
      replies.push({ question: label ? label.textContent : "", answer: input.value });
      if (!input.value.trim()) {
        complete = false;
      }
    });
    if (!complete) {
      showError("answers-error", "Please answer each question before sending.");
      return;
    }
    var submit = document.getElementById("answers-submit");
    submit.disabled = true;
    outcomeStatus.textContent = "Sending your answers…";
    show(outcomeStatus);
    request("POST", "/api/disputes/" + encodeURIComponent(state.runId) + "/answers", {
      answers: replies
    })
      .then(function (view) {
        renderOutcome(view);
      })
      .catch(function (error) {
        submit.disabled = false;
        hide(outcomeStatus);
        showError("answers-error", error.message);
      });
  });
}());
