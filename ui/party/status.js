(function () {
  "use strict";

  // The headings a party reads, per status. The same plain words the form's outcome
  // panel uses, so a party who followed the link sees one vocabulary everywhere.
  var STATUS_HEADINGS = {
    decided: "We have made a decision",
    under_review: "Your case is still under review",
    passed_to_support: "Your report has been passed to our support team",
    needs_info: "We need a little more information"
  };

  var referenceInput = document.getElementById("reference-input");
  var referenceCheck = document.getElementById("reference-check");
  var referenceError = document.getElementById("reference-error");
  var lookupResult = document.getElementById("lookup-result");
  var accountList = document.getElementById("account-list");

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

  function showError(message) {
    referenceError.textContent = message;
    referenceError.hidden = false;
  }

  function clearError() {
    referenceError.textContent = "";
    referenceError.hidden = true;
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

  // ------------------------------------------------------------- one dispute

  function statusCard(view, container) {
    while (container.firstChild) {
      container.removeChild(container.firstChild);
    }
    var card = element("div", "step");
    card.appendChild(element("h2", null, STATUS_HEADINGS[view.status] || "Your dispute"));
    card.appendChild(element("p", "reference", "Reference number: " + view.dispute_id));
    card.appendChild(element("p", "outcome-message", view.message));
    if (view.status === "needs_info") {
      buildAnswerBoxes(view, card);
    }
    container.appendChild(card);
  }

  function buildAnswerBoxes(view, card) {
    var questions = Array.isArray(view.questions) ? view.questions : [];
    if (view.status !== "needs_info" || questions.length === 0) {
      return;
    }
    card.appendChild(element("p", "hint", "Please answer each question below, then send your replies."));
    var boxes = element("div", "question-boxes");
    questions.forEach(function (question, index) {
      var field = element("div", "field");
      var label = element("label", null, question);
      label.htmlFor = "status-reply-" + index;
      var input = element("textarea", "answer-input");
      input.id = "status-reply-" + index;
      input.rows = 2;
      // One click fills this question's box with the sentence the system already
      // accepts, so a party with nothing to add can still send the answers.
      var nothingMore = element("button", "nothing-more", "I have nothing more to add");
      nothingMore.type = "button";
      nothingMore.addEventListener("click", function () {
        input.value = "I have nothing more to add";
      });
      field.appendChild(label);
      field.appendChild(input);
      field.appendChild(nothingMore);
      boxes.appendChild(field);
    });
    card.appendChild(boxes);
    var error = element("p", "error", "");
    error.hidden = true;
    card.appendChild(error);
    var send = element("button", "primary", "Send my answers");
    send.type = "button";
    send.addEventListener("click", function () {
      var replies = [];
      var complete = true;
      Array.prototype.forEach.call(boxes.querySelectorAll("textarea"), function (input) {
        var label = boxes.querySelector('label[for="' + input.id + '"]');
        replies.push({ question: label ? label.textContent : "", answer: input.value });
        if (!input.value.trim()) {
          complete = false;
        }
      });
      if (!complete) {
        error.textContent = "Please answer each question before sending.";
        error.hidden = false;
        return;
      }
      send.disabled = true;
      request("POST", "/api/disputes/" + encodeURIComponent(view.run_id) + "/answers", { answers: replies })
        .then(function (updated) {
          statusCard(updated, card.parentNode);
        })
        .catch(function (requestError) {
          send.disabled = false;
          error.textContent = requestError.message;
          error.hidden = false;
        });
    });
    card.appendChild(send);
  }

  // --------------------------------------------------------- the demo account

  function accountCard(entry) {
    var card = element("div", "step");
    card.appendChild(element("h2", null, STATUS_HEADINGS[entry.status] || "Your dispute"));
    card.appendChild(element("p", "reference", "Reference number: " + entry.dispute_id));
    card.appendChild(element("p", "outcome-message", entry.message));
    if (entry.status === "needs_info") {
      buildAnswerBoxes(entry, card);
    }
    return card;
  }

  // One dispute to focus on, when a link asks for it by reference (the replay's landing
  // step 1 opens the no-show case by id). Null when absent or not a plain string.
  function focusedDispute() {
    var focused = new URLSearchParams(window.location.search).get("dispute");
    return typeof focused === "string" && focused ? focused : null;
  }

  function loadAccount() {
    request("GET", "/api/demo/rider").then(function (payload) {
      while (accountList.firstChild) {
        accountList.removeChild(accountList.firstChild);
      }
      var disputes = Array.isArray(payload.disputes) ? payload.disputes : [];
      var focused = focusedDispute();
      if (focused) {
        var matched = disputes.filter(function (entry) {
          return typeof entry === "object" && entry !== null && entry.dispute_id === focused;
        });
        if (matched.length > 0) {
          disputes = matched;
        }
      }
      if (disputes.length === 0) {
        accountList.appendChild(element("p", "hint", "No disputes have been filed on this demo yet."));
        return;
      }
      disputes.forEach(function (entry) {
        accountList.appendChild(accountCard(entry));
      });
    }).catch(function (error) {
      showError(error.message);
    });
  }

  referenceCheck.addEventListener("click", function () {
    clearError();
    var reference = referenceInput.value.trim();
    if (!reference) {
      showError("Please enter a reference number.");
      return;
    }
    request("GET", "/api/disputes/" + encodeURIComponent(reference))
      .then(function (view) {
        statusCard(view, lookupResult);
      })
      .catch(function (error) {
        showError(error.message);
      });
  });

  loadAccount();
}());
