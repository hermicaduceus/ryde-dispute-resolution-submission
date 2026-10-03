(function () {
  "use strict";

  var STATUS_HEADINGS = {
    decided: "We have made a decision",
    under_review: "Your case is still under review"
  };

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

  function loadAccount() {
    fetch("/api/demo/driver", { method: "GET" }).then(function (response) {
      return response.json().then(function (payload) {
        if (!response.ok) {
          var reason = payload && payload.error ? payload.error : "Something went wrong. Please try again.";
          throw new Error(reason);
        }
        return payload;
      });
    }).then(function (payload) {
      while (accountList.firstChild) {
        accountList.removeChild(accountList.firstChild);
      }
      var disputes = Array.isArray(payload.disputes) ? payload.disputes : [];
      if (disputes.length === 0) {
        accountList.appendChild(element("p", "hint", "No disputes have been filed about your trips yet."));
        return;
      }
      disputes.forEach(function (entry) {
        var card = element("div", "step");
        card.appendChild(element("h2", null, STATUS_HEADINGS[entry.status] || "Your trip"));
        card.appendChild(element("p", "reference", "Reference number: " + entry.dispute_id));
        card.appendChild(element("p", "outcome-message", entry.message));
        accountList.appendChild(card);
      });
    }).catch(function (error) {
      accountList.appendChild(element("p", "error", error.message));
    });
  }

  loadAccount();
}());
