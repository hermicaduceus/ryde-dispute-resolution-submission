(function () {
  "use strict";

  // The intake questions per category, in form order. Keys match what the server
  // accepts; blank answers are allowed and are what the follow-up round is for.
  var QUESTIONNAIRES = {
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
  };

  var CATEGORIES = [
    { id: "route_deviation", label: "My trip went the wrong way" },
    { id: "no_show_charge", label: "I was charged for a trip that did not happen" },
    { id: "property_damage_mess", label: "Property damage or a mess left behind" },
    { id: "safety_incident", label: "A safety incident" },
    { id: "other", label: "Something else" }
  ];

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
      // survive a switch to another.
      state.tripId = null;
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
    window.scrollTo(0, 0);
  });

  // ------------------------------------------------------------- step two

  function loadTrips() {
    var boxes = tripOptions;
    while (boxes.firstChild) {
      boxes.removeChild(boxes.firstChild);
    }
    state.tripId = null;
    document.getElementById("trip-next").disabled = true;
    boxes.appendChild(element("p", "loading", "Loading trips…"));
    request("GET", "/api/trips?category=" + encodeURIComponent(state.category))
      .then(function (payload) {
        while (boxes.firstChild) {
          boxes.removeChild(boxes.firstChild);
        }
        state.trips = Array.isArray(payload.trips) ? payload.trips : [];
        if (state.trips.length === 0) {
          boxes.appendChild(element("p", "hint", "No trips are available in the sample dataset."));
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
            state.tripId = trip.trip_id;
            Array.prototype.forEach.call(boxes.children, function (child) {
              child.classList.remove("selected");
            });
            card.classList.add("selected");
            document.getElementById("trip-next").disabled = false;
          });
          boxes.appendChild(card);
        });
      })
      .catch(function (error) {
        while (boxes.firstChild) {
          boxes.removeChild(boxes.firstChild);
        }
        showError("trip-error", error.message);
      });
  }

  document.getElementById("trip-back").addEventListener("click", function () {
    show(stepCategory);
    hide(stepTrip);
  });

  document.getElementById("trip-next").addEventListener("click", function () {
    clearError("trip-error");
    hide(stepTrip);
    buildQuestions();
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

    var submit = document.getElementById("details-submit");
    submit.disabled = true;
    request("POST", "/api/disputes", {
      category: state.category,
      filed_by: "rider",
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
      field.appendChild(label);
      field.appendChild(input);
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
