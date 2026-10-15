/*
 * W27 replay shim: the only script an exported replay site adds to the app.
 *
 * Loaded first in <head> by every page. It resolves the snapshot label
 * (?snapshot=before|after, else sessionStorage, else "after"), serves every /api/
 * request from the recorded bodies under /replay/data/<label>/, refuses anything
 * that would change state, and inserts the replay banner as the first child of
 * <body>. Plain ES5, like ui/app.js.
 */
(function () {
  "use strict";

  var RECORDED_ON = "{{RECORDED_ON}}";
  var TEST_PREFIX = "{{MOCK_PREFIX}}";
  var STORAGE_KEY = "replay-snapshot";
  var DATA_ROOT = "/replay/data/";
  var NOT_IN_REPLAY = "Not in this replay.";
  var GENERIC_REFUSAL = "This is a replay. The recorded rider filed this case already. Use the replay page's steps to see what happened next.";
  var DECISION_HEAD = "This is a replay. In the recorded run, the reviewer chose: ";
  var DECISION_TAIL = ". Use 'Show after the decision' in the banner to see the result.";
  var DECISION_PATH = /^\/api\/review\/([^\/]+)\/decision$/;

  var nativeFetch = window.fetch;
  var manifests = {};
  var bannerPlaced = false;

  function isSnapshot(value) {
    return value === "before" || value === "after";
  }

  function fromStorage() {
    try {
      var value = sessionStorage.getItem(STORAGE_KEY);
      return isSnapshot(value) ? value : null;
    } catch (error) {
      return null;
    }
  }

  function remember(snapshot) {
    try {
      sessionStorage.setItem(STORAGE_KEY, snapshot);
    } catch (error) {
      /* no storage: the URL parameter still selects the snapshot per page */
    }
  }

  function queryParams() {
    var params = {};
    var query = String(location.search || "").replace(/^\?/, "");
    if (!query) {
      return params;
    }
    var parts = query.split("&");
    for (var index = 0; index < parts.length; index += 1) {
      if (!parts[index]) {
        continue;
      }
      var eq = parts[index].indexOf("=");
      var name = eq === -1 ? parts[index] : parts[index].slice(0, eq);
      var value = eq === -1 ? "" : parts[index].slice(eq + 1);
      try {
        name = decodeURIComponent(name);
      } catch (error) {
        name = "";
      }
      try {
        value = decodeURIComponent(value);
      } catch (error) {
        value = "";
      }
      if (!Object.prototype.hasOwnProperty.call(params, name)) {
        params[name] = value;
      }
    }
    return params;
  }

  function currentSnapshot() {
    var chosen = queryParams().snapshot;
    if (isSnapshot(chosen)) {
      remember(chosen);
      return chosen;
    }
    var stored = fromStorage();
    if (stored) {
      return stored;
    }
    remember("after");
    return "after";
  }

  function switchHref(snapshot) {
    var other = snapshot === "before" ? "after" : "before";
    var query = String(location.search || "").replace(/^\?/, "");
    var kept = [];
    if (query) {
      var parts = query.split("&");
      for (var index = 0; index < parts.length; index += 1) {
        if (!parts[index] || parts[index].split("=")[0] === "snapshot") {
          continue;
        }
        kept.push(parts[index]);
      }
    }
    kept.push("snapshot=" + other);
    return location.pathname + "?" + kept.join("&");
  }

  function bannerSentence(snapshot) {
    return TEST_PREFIX + "Replay of saved runs recorded on " + RECORDED_ON + ", " +
      (snapshot === "before" ? "before" : "after") +
      " the human decision. Forms work as a guided walk-through; nothing you submit is processed.";
  }

  function jsonResponse(status, payload) {
    return new Response(JSON.stringify(payload), {
      status: status,
      headers: { "Content-Type": "application/json" }
    });
  }

  function manifestFor(label) {
    if (!manifests[label]) {
      manifests[label] = nativeFetch(DATA_ROOT + label + "/manifest.json")
        .then(function (response) {
          return response.text();
        })
        .then(function (text) {
          return JSON.parse(text);
        });
    }
    return manifests[label];
  }

  function recordedResponse(label, key) {
    return manifestFor(label).then(function (manifest) {
      var file = manifest[key];
      if (typeof file !== "string") {
        return jsonResponse(404, { error: NOT_IN_REPLAY });
      }
      return nativeFetch(DATA_ROOT + label + "/" + file)
        .then(function (response) {
          return response.text();
        })
        .then(function (text) {
          return new Response(text, { status: 200 });
        });
    });
  }

  function decisionResponse(runId) {
    return manifestFor("after").then(function (manifest) {
      var file = manifest["GET /api/review/" + runId + "/case"];
      if (typeof file !== "string") {
        return jsonResponse(403, { error: GENERIC_REFUSAL });
      }
      return nativeFetch(DATA_ROOT + "after/" + file)
        .then(function (response) {
          return response.text();
        })
        .then(function (text) {
          var body = null;
          try {
            body = JSON.parse(text);
          } catch (error) {
            body = null;
          }
          var decision = body && body.human_decision;
          if (!decision || typeof decision.decision !== "string") {
            return jsonResponse(403, { error: GENERIC_REFUSAL });
          }
          var chose = decision.decision;
          var amount = decision.amount_sgd;
          if (amount !== null && amount !== undefined) {
            chose += ", SGD " + Number(amount).toFixed(2);
          }
          return jsonResponse(403, { error: DECISION_HEAD + chose + DECISION_TAIL });
        });
    });
  }

  function requestTarget(input) {
    var url = typeof input === "string" ? input : String(input && input.url ? input.url : input);
    var parsed = new URL(url, location.href);
    return { pathname: parsed.pathname, path: parsed.pathname + parsed.search };
  }

  function replayFetch(input, init) {
    var method = "GET";
    if (init && init.method !== undefined && init.method !== null) {
      method = String(init.method).toUpperCase();
    }
    var target = requestTarget(input);
    if (target.pathname !== "/api" && target.pathname.indexOf("/api/") !== 0) {
      return nativeFetch.apply(window, arguments);
    }
    if (method === "GET") {
      return recordedResponse(currentSnapshot(), "GET " + target.path);
    }
    var match = DECISION_PATH.exec(target.pathname);
    if (method === "POST" && match) {
      return decisionResponse(match[1]);
    }
    return Promise.resolve(jsonResponse(403, { error: GENERIC_REFUSAL }));
  }

  window.fetch = replayFetch;

  function insertBanner() {
    if (bannerPlaced || !document.body) {
      return;
    }
    if (document.getElementById("replay-banner")) {
      bannerPlaced = true;
      return;
    }
    bannerPlaced = true;
    var snapshot = currentSnapshot();
    var banner = document.createElement("div");
    banner.setAttribute("id", "replay-banner");
    banner.setAttribute("role", "note");
    banner.appendChild(document.createTextNode(bannerSentence(snapshot)));
    var back = document.createElement("a");
    back.setAttribute("id", "replay-back");
    back.setAttribute("href", "/replay/");
    // Spacing via the CSSOM (no text node), so the banner sentence pins stay exact and a
    // strict style-src CSP still allows it. sol review of dec6cab, MINOR 1.
    back.style.marginLeft = "1em";
    back.appendChild(document.createTextNode("Back to the steps"));
    banner.appendChild(back);
    var link = document.createElement("a");
    link.setAttribute("id", "replay-switch");
    link.setAttribute("href", switchHref(snapshot));
    link.style.marginLeft = "1em";
    link.appendChild(document.createTextNode(
      snapshot === "before" ? "Show after the decision" : "Show before the decision"
    ));
    banner.appendChild(link);
    document.body.insertBefore(banner, document.body.firstChild);
  }

  document.addEventListener("DOMContentLoaded", insertBanner);
  window.addEventListener("load", insertBanner);
  insertBanner();
}());
