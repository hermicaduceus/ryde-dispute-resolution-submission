(function () {
  "use strict";

  var evidenceSections = [
    "route",
    "duration",
    "fare",
    "cancellation",
    "chat",
    "profiles",
    "filing"
  ];
  var state = {
    caseFile: null,
    evidenceIndex: {},
    policyIndex: {},
    payloadFiles: {},
    openRun: null,
    currentQueueRun: null,
    openGeneration: 0,
    promptsGeneration: 0,
    pendingOpens: [],
    highlightTimer: null
  };

  var PROMPTS_FAILURE = "Not available: open this case through the local server.";
  var PROMPTS_UNKNOWN_RUN = "Unknown run.";
  var PROMPTS_SHOW_FULL_TEXT = "Show full text";
  var RUN_ID_PATTERN = /^[A-Za-z0-9._-]{1,128}$/;

  var picker = document.getElementById("case-picker");
  var runFolderPicker = document.getElementById("run-folder-picker");
  var status = document.getElementById("load-status");
  var payloadStatus = document.getElementById("payload-status");
  var workspace = document.getElementById("case-workspace");
  var loadedFile = document.getElementById("loaded-file");
  var metadataList = document.getElementById("metadata-list");
  var grievanceContent = document.getElementById("grievance-content");
  var evidenceContent = document.getElementById("evidence-content");
  var claimsContent = document.getElementById("claims-content");
  var policyContent = document.getElementById("policy-content");
  var resolutionContent = document.getElementById("resolution-content");
  var eventsContent = document.getElementById("events-content");
  var promptsContent = document.getElementById("prompts-content");
  var queueRefresh = document.getElementById("queue-refresh");
  var queueStatus = document.getElementById("queue-status");
  var queueContent = document.getElementById("queue-content");
  var overridesStatus = document.getElementById("overrides-status");
  var overridesContent = document.getElementById("overrides-content");
  var decisionSection = document.getElementById("decision-section");
  var decisionContent = document.getElementById("decision-content");
  var reviewUi = queueRefresh && queueStatus && queueContent && overridesStatus
    && overridesContent && decisionSection && decisionContent;
  var decisionUi = null;

  function clear(element) {
    while (element.firstChild) {
      element.removeChild(element.firstChild);
    }
  }

  function element(tagName, className, text) {
    var node = document.createElement(tagName);
    if (className) {
      node.className = className;
    }
    if (text !== undefined && text !== null) {
      node.textContent = String(text);
    }
    return node;
  }

  function displayValue(value) {
    if (value === null || value === undefined) {
      return "Not present in file";
    }
    if (typeof value === "object") {
      return JSON.stringify(value);
    }
    return String(value);
  }

  function humanizeKey(key) {
    return String(key)
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replace(/[_-]+/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .replace(/^\w/, function (letter) { return letter.toUpperCase(); });
  }

  function formatNumber(value, path) {
    if (typeof value !== "number" || !isFinite(value)) {
      return displayValue(value);
    }
    var name = String(path).split(".").pop();
    if (/_sgd$|amount_sgd$|price_sgd$|fare_sgd$|delta_sgd$/.test(name)) {
      return "SGD " + value.toFixed(2);
    }
    if (/_pct$/.test(name)) {
      return value.toFixed(2).replace(/\.00$/, "") + "%";
    }
    if (/_km$/.test(name)) {
      return value + " km";
    }
    if (/_minutes?$/.test(name)) {
      return value + " min";
    }
    if (/_m$/.test(name)) {
      return value + " m";
    }
    if (name === "rating" || name === "surge_multiplier") {
      return value.toFixed(2);
    }
    return String(value);
  }

  function formatEvidenceValue(value, path) {
    if (value === null || value === undefined) {
      return "NULL";
    }
    if (typeof value === "number") {
      return formatNumber(value, path);
    }
    if (typeof value === "boolean") {
      return value ? "Yes" : "No";
    }
    if (Array.isArray(value)) {
      return value.map(function (item) { return displayValue(item); }).join(", ");
    }
    return String(value);
  }

  function setStatus(message, stateName) {
    status.textContent = message;
    status.dataset.state = stateName || "idle";
  }

  function setPayloadStatus(message, stateName) {
    payloadStatus.textContent = message;
    payloadStatus.dataset.state = stateName || "idle";
  }

  function normalizedPayloadRef(reference) {
    if (typeof reference !== "string" || reference.trim() === "") {
      return null;
    }
    var normalized = reference.replace(/\\/g, "/");
    if (normalized.charAt(0) === "/" || /^[a-zA-Z]:/.test(normalized)) {
      return null;
    }
    var parts = normalized.split("/");
    if (parts.some(function (part) { return part === "" || part === "." || part === ".."; })) {
      return null;
    }
    return normalized;
  }

  function relativeRunPath(file) {
    var relative = file.webkitRelativePath || file.name;
    var separator = relative.indexOf("/");
    return separator === -1 ? relative : relative.slice(separator + 1);
  }

  function attachRunFiles(files) {
    state.payloadFiles = {};
    var attached = 0;
    Array.prototype.forEach.call(files || [], function (file) {
      var relative = normalizedPayloadRef(relativeRunPath(file));
      if (relative) {
        state.payloadFiles[relative] = file;
        attached += 1;
      }
    });
    if (attached > 0) {
      setPayloadStatus("Attached " + attached + " run file(s); event payloads can be opened.", "success");
    } else {
      setPayloadStatus("No run files were attached.", "error");
    }
    if (state.caseFile) {
      renderEvents(state.caseFile);
    }
  }

  function addMetadata(label, value) {
    var term = element("dt", null, label);
    var description = element("dd", null, displayValue(value));
    metadataList.appendChild(term);
    metadataList.appendChild(description);
  }

  function renderMetadata(caseFile) {
    clear(metadataList);
    addMetadata("Dispute ID", caseFile.dispute_id);
    addMetadata("Run ID", caseFile.run_id);
    addMetadata("Category", caseFile.category);
    addMetadata("Generated at", caseFile.generated_at);
    addMetadata("Confidence threshold", caseFile.confidence_threshold);
    addMetadata("Policy source", caseFile.policy && caseFile.policy.source_path);
    addMetadata("Outcome", caseFile.resolution && caseFile.resolution.outcome);
  }

  function appendInfoRow(parent, label, value, className, path) {
    var row = element("div", className || "info-row");
    row.appendChild(element("dt", null, label));
    row.appendChild(element("dd", null, path ? formatNumber(value, path) : displayValue(value)));
    parent.appendChild(row);
  }

  function renderGrievance(caseFile) {
    clear(grievanceContent);
    var intake = caseFile.intake || {};
    var article = element("article", "grievance-card");
    var marker = element("p", "grievance-marker", "Filed by " + displayValue(intake.filed_by));
    article.appendChild(marker);
    article.appendChild(element("blockquote", "claim-text", displayValue(intake.claim_text)));

    var facts = element("dl", "grievance-facts");
    appendInfoRow(facts, "Claim amount", intake.claim_amount_sgd, "info-row highlight", "claim_amount_sgd");
    appendInfoRow(facts, "Submitted category", intake.category_as_submitted);
    appendInfoRow(facts, "Filed at", intake.filed_at);
    article.appendChild(facts);

    var answerHeading = element("h3", "subsection-title", "Form answers");
    article.appendChild(answerHeading);
    var answers = element("dl", "answers-list");
    var formAnswers = intake.form_answers && typeof intake.form_answers === "object"
      ? intake.form_answers
      : {};
    var answerKeys = Object.keys(formAnswers);
    if (answerKeys.length === 0) {
      answers.appendChild(element("div", "empty-note", "No form answers were supplied in this case file."));
    } else {
      answerKeys.forEach(function (key) {
        appendInfoRow(answers, humanizeKey(key), formAnswers[key], "info-row");
      });
    }
    article.appendChild(answers);

    // R6: a type check is not a shape check. Only a non-array object with non-empty
    // string question and answer fields renders; every other shape — arrays, empty
    // objects, numeric or missing fields, null, strings, numbers — is skipped.
    var followUps = intake.follow_up_answers;
    if (Array.isArray(followUps)) {
      var validFollowUps = followUps.filter(function (item) {
        return item !== null && typeof item === "object" && !Array.isArray(item)
          && typeof item.question === "string" && item.question.trim() !== ""
          && typeof item.answer === "string" && item.answer.trim() !== "";
      });
      if (validFollowUps.length > 0) {
        var followHeading = element("h3", "subsection-title", "Follow-up answers (round two)");
        article.appendChild(followHeading);
        var followList = element("dl", "answers-list");
        validFollowUps.forEach(function (item) {
          appendInfoRow(followList, displayValue(item.question), displayValue(item.answer), "info-row");
        });
        article.appendChild(followList);
      }
    }
    grievanceContent.appendChild(article);
  }

  function noteValues(context, pack) {
    if (context && Array.isArray(context.notes) && context.notes.length > 0) {
      return context.notes;
    }
    if (pack && Array.isArray(pack.notes) && pack.notes.length > 0) {
      return pack.notes;
    }
    return ["No explanatory note supplied by this case file."];
  }

  function appendNotes(parent, notes) {
    var noteBox = element("div", "evidence-note");
    noteBox.appendChild(element("span", "note-label", "Notes"));
    var noteList = element("ul", "note-list");
    notes.forEach(function (note) {
      noteList.appendChild(element("li", null, displayValue(note)));
    });
    noteBox.appendChild(noteList);
    parent.appendChild(noteBox);
  }

  function evidenceAnchor(path) {
    return "evidence-" + String(path).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  }

  function appendEvidenceField(parent, key, value, path, context, pack) {
    var field = element("div", "evidence-field");
    field.id = evidenceAnchor(path);
    field.dataset.fieldPath = path;
    field.appendChild(element("dt", "field-label", humanizeKey(key)));
    var valueNode = element("dd", "field-value", formatEvidenceValue(value, path));
    if (value === null || value === undefined) {
      valueNode.classList.add("is-null");
      field.classList.add("has-null");
      appendNotes(field, noteValues(context, pack));
    }
    field.appendChild(valueNode);
    parent.appendChild(field);
    state.evidenceIndex[path] = {
      id: field.id,
      value: value
    };
  }

  function renderEvidenceObject(parent, object, prefix, pack) {
    var grid = element("dl", "evidence-grid");
    Object.keys(object).forEach(function (key) {
      if (key === "notes") {
        return;
      }
      var path = prefix ? prefix + "." + key : key;
      var value = object[key];
      if (value && typeof value === "object" && !Array.isArray(value)) {
        var group = element("div", "evidence-subgroup");
        group.appendChild(element("h4", "subgroup-title", humanizeKey(key)));
        renderEvidenceObject(group, value, path, pack);
        grid.appendChild(group);
      } else {
        appendEvidenceField(grid, key, value, path, object, pack);
      }
    });
    parent.appendChild(grid);
  }

  function renderEvidenceSection(parent, key, value, pack) {
    var section = element("article", "evidence-card");
    section.appendChild(element("h3", "evidence-card-title", humanizeKey(key)));
    if (value === null || value === undefined) {
      var nullField = element("div", "evidence-field has-null");
      nullField.id = evidenceAnchor(key);
      nullField.dataset.fieldPath = key;
      nullField.appendChild(element("dt", "field-label", humanizeKey(key)));
      nullField.appendChild(element("dd", "field-value is-null", "NULL"));
      appendNotes(nullField, noteValues(null, pack));
      section.appendChild(nullField);
      state.evidenceIndex[key] = { id: nullField.id, value: value };
    } else if (typeof value === "object" && !Array.isArray(value)) {
      renderEvidenceObject(section, value, key, pack);
      if (Array.isArray(value.notes) && value.notes.length > 0) {
        appendNotes(section, value.notes);
      }
    } else {
      var simpleGrid = element("dl", "evidence-grid");
      appendEvidenceField(simpleGrid, key, value, key, pack, pack);
      section.appendChild(simpleGrid);
    }
    parent.appendChild(section);
  }

  function renderEvidence(caseFile) {
    clear(evidenceContent);
    state.evidenceIndex = {};
    var pack = caseFile.evidence_pack;
    if (!pack || typeof pack !== "object") {
      var notBuilt = element("article", "deliberate-empty");
      var humanReview = caseFile.resolution && caseFile.resolution.outcome === "human_review";
      notBuilt.appendChild(element("h3", null, humanReview ? "Automated evidence not invoked" : "Evidence Pack not built"));
      notBuilt.appendChild(element("p", null, humanReview
        ? "This category was routed to human review before the Evidence Pack was built."
        : "This case file does not contain computed evidence."));
      if (!humanReview) {
        appendNotes(notBuilt, noteValues(null, null));
      }
      evidenceContent.appendChild(notBuilt);
      return;
    }

    var provenance = element("dl", "evidence-provenance");
    ["schema_version", "trip_id", "rider_id", "driver_id", "service_type", "generated_at"].forEach(function (key) {
      if (Object.prototype.hasOwnProperty.call(pack, key)) {
        appendInfoRow(provenance, humanizeKey(key), pack[key], "info-row");
      }
    });
    evidenceContent.appendChild(provenance);

    var rendered = {};
    evidenceSections.forEach(function (key) {
      if (Object.prototype.hasOwnProperty.call(pack, key)) {
        renderEvidenceSection(evidenceContent, key, pack[key], pack);
        rendered[key] = true;
      }
    });
    Object.keys(pack).forEach(function (key) {
      if (rendered[key] || key === "notes" || key === "schema_version" || key === "dispute_id" || key === "category" || key === "generated_at" || key === "trip_id" || key === "rider_id" || key === "driver_id" || key === "service_type") {
        return;
      }
      renderEvidenceSection(evidenceContent, key, pack[key], pack);
    });
    if (Array.isArray(pack.notes) && pack.notes.length > 0) {
      appendNotes(evidenceContent, pack.notes);
    }
  }

  function promptList(value) {
    return Array.isArray(value) ? value : [];
  }

  function promptFactText(value) {
    var items = promptList(value);
    return items.length === 0 ? "None" : items.join(", ");
  }

  function promptBadge(entry) {
    var data = entry && typeof entry === "object" ? entry : {};
    if (data.status === "match") {
      var fingerprint = typeof data.recorded_fingerprint === "string"
        ? data.recorded_fingerprint
        : (typeof data.rebuilt_fingerprint === "string" ? data.rebuilt_fingerprint : "");
      return "Matches what was sent (fingerprint " + fingerprint.slice(0, 8) + ")";
    }
    if (data.status === "changed") {
      return "The prompts have changed since this run. Showing today's version.";
    }
    if (data.status === "not_called") {
      return "This agent was not called in this run.";
    }
    return "Not available for this run.";
  }

  function promptPositionsText(positions) {
    var items = promptList(positions);
    if (items.length === 0) {
      return "No advocate positions were recorded.";
    }
    return items.map(function (position) {
      var item = position && typeof position === "object" ? position : {};
      var side = item.side === "driver" ? "Driver" : "Rider";
      var amount = formatMoney(item.amount_sgd);
      return side + ": " + displayValue(item.outcome)
        + (amount ? " of " + amount : ", no amount recorded");
    }).join(" · ");
  }

  function appendPromptSummary(parent, summary) {
    var data = summary && typeof summary === "object" ? summary : {};
    var facts = data.case_facts && typeof data.case_facts === "object" ? data.case_facts : {};
    var policy = data.policy && typeof data.policy === "object" ? data.policy : {};
    var list = element("dl", "grievance-facts");
    appendInfoRow(list, "Role", data.role);
    appendInfoRow(list, "Hard rules", promptList(data.hard_rules).join(" "));
    appendInfoRow(list, "Evidence sections", promptFactText(facts.evidence_sections));
    appendInfoRow(list, "Citable references", facts.citable_refs);
    appendInfoRow(list, "Form answers", facts.form_answers);
    appendInfoRow(list, "Claim amount", facts.claim_amount_sgd, "info-row", "claim_amount_sgd");
    if (data.advocate_positions !== null && data.advocate_positions !== undefined) {
      appendInfoRow(list, "Advocate positions", promptPositionsText(data.advocate_positions));
    }
    appendInfoRow(list, "Policy", displayValue(policy.rule_count) + " rules from " + displayValue(policy.source));
    appendInfoRow(list, "Asked to return", promptFactText(data.asked_to_return));
    parent.appendChild(list);
  }

  function renderPromptCard(entry) {
    var data = entry && typeof entry === "object" ? entry : {};
    var card = element("article", "claim-card");
    var header = element("header", "claim-card-header");
    header.appendChild(element("h3", null, displayValue(data.label)));
    header.appendChild(element("p", "agent-label", promptBadge(data)));
    card.appendChild(header);
    var body = element("div", "claim-card-body");
    appendPromptSummary(body, data.summary);
    var system = typeof data.system_prompt === "string" ? data.system_prompt : null;
    var user = typeof data.user_prompt === "string" ? data.user_prompt : null;
    if (system !== null && user !== null) {
      var details = element("details");
      details.appendChild(element("summary", null, PROMPTS_SHOW_FULL_TEXT));
      details.appendChild(element("pre", "payload-json", system + "\n\n" + user));
      body.appendChild(details);
    }
    card.appendChild(body);
    return card;
  }

  function showPromptsFailure() {
    if (!promptsContent) {
      return;
    }
    clear(promptsContent);
    promptsContent.appendChild(element("p", "empty-note", PROMPTS_FAILURE));
  }

  function settlePrompts(generation, result) {
    if (!promptsContent || generation !== state.promptsGeneration) {
      return;
    }
    var body = result && typeof result === "object" ? result.payload : null;
    var agents = body && typeof body === "object" && !Array.isArray(body) ? body.agents : null;
    if (!result || result.ok !== true || !Array.isArray(agents)) {
      showPromptsFailure();
      return;
    }
    clear(promptsContent);
    agents.forEach(function (entry) {
      promptsContent.appendChild(renderPromptCard(entry));
    });
  }

  function renderPrompts(caseFile) {
    if (!promptsContent) {
      return;
    }
    clear(promptsContent);
    state.promptsGeneration += 1;
    var generation = state.promptsGeneration;
    var runId = caseFile && typeof caseFile.run_id === "string" ? caseFile.run_id : "";
    fetchJsonAny("/api/review/" + encodeURIComponent(runId) + "/prompts").then(function (result) {
      settlePrompts(generation, result);
    });
  }

  function policyAnchor(ruleId) {
    return "policy-rule-" + String(ruleId).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  }

  function appendCitation(parent, reference, kind, validation) {
    var text = String(reference);
    var target = kind === "evidence" ? state.evidenceIndex[text] : state.policyIndex[text];
    var unknown = validation && (kind === "evidence"
      ? Array.isArray(validation.unknown_evidence_refs) && validation.unknown_evidence_refs.indexOf(text) !== -1
      : Array.isArray(validation.unknown_rule_ids) && validation.unknown_rule_ids.indexOf(text) !== -1);
    var citation;
    if (target && !unknown) {
      citation = element("a", "citation citation-" + kind, text);
      citation.href = "#" + target.id;
      if (kind === "evidence" && (target.value === null || target.value === undefined)) {
        citation.classList.add("citation-null");
      }
    } else {
      citation = element("span", "citation citation-unresolved", text);
      citation.title = "Citation could not be resolved in this case file.";
    }
    parent.appendChild(citation);
  }

  function appendCitations(parent, label, references, kind, validation) {
    if (!Array.isArray(references) || references.length === 0) {
      return;
    }
    var block = element("div", "citation-block");
    block.appendChild(element("h4", "citation-title", label));
    var list = element("div", "citation-list");
    references.forEach(function (reference) {
      appendCitation(list, reference, kind, validation);
    });
    block.appendChild(list);
    parent.appendChild(block);
  }

  function appendValidation(parent, validation) {
    if (!validation || typeof validation !== "object") {
      return;
    }
    var problems = [];
    ["unknown_evidence_refs", "unknown_rule_ids", "notes"].forEach(function (key) {
      if (Array.isArray(validation[key])) {
        validation[key].forEach(function (item) {
          problems.push(humanizeKey(key) + ": " + displayValue(item));
        });
      }
    });
    if (problems.length === 0) {
      return;
    }
    var box = element("div", "validation-box");
    box.appendChild(element("h4", "validation-title", "Validation notes"));
    var list = element("ul", "note-list");
    problems.forEach(function (problem) {
      list.appendChild(element("li", null, problem));
    });
    box.appendChild(list);
    parent.appendChild(box);
  }

  function renderPolicyReferences(caseFile) {
    clear(policyContent);
    state.policyIndex = {};
    var policy = caseFile.policy && typeof caseFile.policy === "object" ? caseFile.policy : {};
    var ruleIds = Array.isArray(policy.rule_ids) ? policy.rule_ids : [];
    var panel = element("div", "policy-reference");
    panel.appendChild(element("h3", "policy-reference-title", "Policy references"));
    panel.appendChild(element("p", "policy-source", "Source: " + displayValue(policy.source_path)));
    if (ruleIds.length === 0) {
      panel.appendChild(element("p", "empty-note", "No policy rule IDs were supplied in this case file."));
      policyContent.appendChild(panel);
      return;
    }
    var list = element("ul", "policy-list");
    ruleIds.forEach(function (ruleId) {
      var item = element("li", "policy-item", ruleId);
      item.id = policyAnchor(ruleId);
      item.dataset.ruleId = ruleId;
      state.policyIndex[String(ruleId)] = { id: item.id };
      list.appendChild(item);
    });
    panel.appendChild(list);
    policyContent.appendChild(panel);
  }

  function renderClaimCard(side, claim) {
    var card = element("article", "claim-card claim-" + side);
    var heading = side === "rider" ? "Rider Advocate" : "Driver Advocate";
    var header = element("header", "claim-card-header");
    header.appendChild(element("h3", null, heading));
    header.appendChild(element("p", "agent-label", claim ? displayValue(claim.agent) : "No advocate ran"));
    card.appendChild(header);

    if (!claim || typeof claim !== "object") {
      card.classList.add("claim-unavailable");
      card.appendChild(element("p", "claim-unavailable-message", "No advocate case was produced for this routed case file."));
      return card;
    }

    var claimBody = element("div", "claim-card-body");
    claimBody.appendChild(element("p", "claim-summary", displayValue(claim.claim_summary)));
    claimBody.appendChild(element("h4", "claim-label", "Argument"));
    claimBody.appendChild(element("p", "claim-argument", displayValue(claim.argument)));

    var request = element("dl", "request-grid");
    appendInfoRow(request, "Requested outcome", claim.requested_outcome);
    appendInfoRow(request, "Requested amount", claim.requested_amount_sgd, "info-row highlight", "requested_amount_sgd");
    claimBody.appendChild(request);

    var validation = claim.validation || {};
    appendCitations(claimBody, "Evidence cited", claim.evidence_cited, "evidence", validation);
    appendCitations(claimBody, "Policy rules", claim.policy_rule_ids, "policy", validation);

    if (Array.isArray(claim.follow_up_questions) && claim.follow_up_questions.length > 0) {
      claimBody.appendChild(element("h4", "claim-label", "Follow-up questions"));
      var followUps = element("ul", "question-list");
      claim.follow_up_questions.forEach(function (question) {
        followUps.appendChild(element("li", null, displayValue(question)));
      });
      claimBody.appendChild(followUps);
    }

    appendValidation(claimBody, validation);

    if (claim.llm && typeof claim.llm === "object") {
      var llmMeta = element("dl", "llm-meta");
      appendInfoRow(llmMeta, "Provider", claim.llm.provider);
      appendInfoRow(llmMeta, "Model", claim.llm.model);
      appendInfoRow(llmMeta, "Finish reason", claim.llm.finish_reason);
      claimBody.appendChild(llmMeta);
    }
    card.appendChild(claimBody);
    return card;
  }

  function renderClaims(caseFile) {
    clear(claimsContent);
    renderPolicyReferences(caseFile);
    var grid = element("div", "claims-grid");
    var claims = caseFile.claims && typeof caseFile.claims === "object" ? caseFile.claims : {};
    grid.appendChild(renderClaimCard("rider", claims.rider));
    grid.appendChild(renderClaimCard("driver", claims.driver));
    claimsContent.appendChild(grid);
  }

  function appendOutcomeHeader(parent, label, className, detail) {
    var header = element("header", "resolution-header");
    header.appendChild(element("span", "outcome-badge " + className, label));
    if (detail) {
      header.appendChild(element("p", "resolution-detail", detail));
    }
    parent.appendChild(header);
  }

  function appendPartyMessage(parent, message) {
    var box = element("div", "party-message");
    box.appendChild(element("h4", "party-message-label", "Party-facing message"));
    box.appendChild(element("p", null, displayValue(message)));
    parent.appendChild(box);
  }

  var rulingFields = ["action", "recommended_amount_sgd", "confidence", "explanation"];

  function isRulingObject(ruling) {
    if (!ruling || typeof ruling !== "object" || Array.isArray(ruling)) {
      return false;
    }
    return rulingFields.every(function (field) {
      return ruling[field] !== null && ruling[field] !== undefined;
    });
  }

  function appendRulingDetails(parent, ruling, includeCitations) {
    if (!ruling || typeof ruling !== "object") {
      return;
    }
    var metrics = element("dl", "resolution-metrics");
    appendInfoRow(metrics, "Action", ruling.action);
    appendInfoRow(metrics, "Recommended amount", ruling.recommended_amount_sgd, "info-row highlight", "recommended_amount_sgd");
    appendInfoRow(metrics, "Confidence", ruling.confidence, "info-row", "confidence");
    parent.appendChild(metrics);
    parent.appendChild(element("h4", "resolution-label", "Explanation"));
    parent.appendChild(element("p", "resolution-explanation", displayValue(ruling.explanation)));
    if (includeCitations) {
      appendCitations(parent, "Cited evidence", ruling.cited_evidence_refs, "evidence", ruling.validation || {});
      appendCitations(parent, "Cited policy rules", ruling.cited_rule_ids, "policy", ruling.validation || {});
      appendValidation(parent, ruling.validation || {});
    }
  }

  function appendResolutionNotes(parent, notes) {
    if (Array.isArray(notes) && notes.length > 0) {
      appendNotes(parent, notes);
    }
  }

  function renderMalformedRuledResolution(resolution) {
    var card = element("article", "resolution-card outcome-malformed");
    appendOutcomeHeader(card, "MALFORMED CASE FILE", "outcome-malformed-badge", "No delivery can be confirmed from this file.");
    var body = element("div", "resolution-body");
    body.appendChild(element("p", "routing-explanation", "This case file records a ruled outcome but does not carry a usable ruling object, so the Judge's delivery cannot be verified."));
    var details = element("dl", "threshold-row");
    appendInfoRow(details, "Recorded outcome", resolution.outcome);
    appendInfoRow(details, "Ruling object", resolution.ruling);
    body.appendChild(details);
    card.appendChild(body);
    return card;
  }

  function renderRuledResolution(resolution) {
    if (!isRulingObject(resolution.ruling)) {
      return renderMalformedRuledResolution(resolution);
    }
    var wrapper = element("div", "withheld-layout");
    var card = element("article", "resolution-card outcome-ruled");
    card.dataset.audience = "parties";
    appendOutcomeHeader(card, "RULING ISSUED", "outcome-ruled-badge", resolution.delivered_to_parties === true
      ? "The Judge delivered this decision to the parties."
      : "This case file records a ruled outcome but does not say the parties received it.");
    var body = element("div", "resolution-body");
    appendRulingDetails(body, resolution.ruling, true);
    var threshold = element("dl", "threshold-row");
    appendInfoRow(threshold, "Delivered to parties", resolution.delivered_to_parties);
    appendInfoRow(threshold, "Confidence threshold", resolution.confidence_threshold, "info-row", "confidence_threshold");
    body.appendChild(threshold);
    appendPartyMessage(body, resolution.party_message);
    card.appendChild(body);
    wrapper.appendChild(card);

    if (Array.isArray(resolution.notes) && resolution.notes.length > 0) {
      var humanCard = element("article", "resolution-card human-only-region");
      humanCard.dataset.audience = "human-review-only";
      var humanHeader = element("header", "human-only-header");
      humanHeader.appendChild(element("span", "human-only-label", "HUMAN-ONLY — NOT DELIVERED TO PARTIES"));
      humanHeader.appendChild(element("h3", null, "Notes for reviewer"));
      humanCard.appendChild(humanHeader);
      var humanBody = element("div", "resolution-body");
      appendResolutionNotes(humanBody, resolution.notes);
      humanCard.appendChild(humanBody);
      wrapper.appendChild(humanCard);
    }
    return wrapper;
  }

  function renderWithheldResolution(resolution) {
    var wrapper = element("div", "withheld-layout");
    var publicCard = element("article", "resolution-card outcome-withheld party-facing-region");
    publicCard.dataset.audience = "parties";
    appendOutcomeHeader(publicCard, "DECISION WITHHELD", "outcome-withheld-badge", "The parties have not received a ruling.");
    var publicBody = element("div", "resolution-body");
    appendPartyMessage(publicBody, resolution.party_message);
    var delivery = element("dl", "threshold-row");
    appendInfoRow(delivery, "Delivered to parties", resolution.delivered_to_parties);
    appendInfoRow(delivery, "Escalated for human review", resolution.escalated_for_human_review);
    publicBody.appendChild(delivery);
    publicCard.appendChild(publicBody);
    wrapper.appendChild(publicCard);

    var humanCard = element("article", "resolution-card human-only-region");
    humanCard.dataset.audience = "human-review-only";
    var humanHeader = element("header", "human-only-header");
    humanHeader.appendChild(element("span", "human-only-label", "HUMAN-ONLY — NOT DELIVERED TO PARTIES"));
    humanHeader.appendChild(element("h3", null, "Candidate for reviewer"));
    humanCard.appendChild(humanHeader);
    var humanBody = element("div", "resolution-body");
    appendRulingDetails(humanBody, resolution.withheld_candidate, true);
    var threshold = element("dl", "threshold-row");
    appendInfoRow(threshold, "Confidence threshold", resolution.confidence_threshold, "info-row", "confidence_threshold");
    humanBody.appendChild(threshold);
    appendResolutionNotes(humanBody, resolution.notes);
    humanCard.appendChild(humanBody);
    wrapper.appendChild(humanCard);
    return wrapper;
  }

  function renderHumanReviewResolution(caseFile, resolution) {
    var wrapper = element("div", "withheld-layout");
    var card = element("article", "resolution-card outcome-human-review");
    card.dataset.audience = "parties";
    appendOutcomeHeader(card, "ROUTED TO HUMAN REVIEW", "outcome-human-badge", "The system declined to act outside its supported categories.");
    var body = element("div", "resolution-body");
    var intake = caseFile.intake || {};
    var routing = element("dl", "routing-grid");
    appendInfoRow(routing, "Category as submitted", intake.category_as_submitted);
    appendInfoRow(routing, "Routed category", caseFile.category);
    body.appendChild(routing);
    body.appendChild(element("p", "routing-explanation", "No Evidence Pack, advocate cases, or Judge ruling were produced for this routed category."));
    appendPartyMessage(body, resolution.party_message);
    card.appendChild(body);
    wrapper.appendChild(card);

    var humanCard = element("article", "resolution-card human-only-region");
    humanCard.dataset.audience = "human-review-only";
    var humanHeader = element("header", "human-only-header");
    humanHeader.appendChild(element("span", "human-only-label", "HUMAN-ONLY — NOT DELIVERED TO PARTIES"));
    humanHeader.appendChild(element("h3", null, "Routing notes for reviewer"));
    humanCard.appendChild(humanHeader);
    var humanBody = element("div", "resolution-body");
    appendResolutionNotes(humanBody, resolution.notes);
    humanCard.appendChild(humanBody);
    wrapper.appendChild(humanCard);
    return wrapper;
  }

  function renderNeedsInfoResolution(caseFile, resolution) {
    var wrapper = element("div", "withheld-layout");
    var card = element("article", "resolution-card outcome-needs-info");
    card.dataset.audience = "parties";
    appendOutcomeHeader(card, "WAITING ON THE PARTY", "outcome-needs-badge",
      "The run stopped before the Judge: the filing party is being asked follow-up questions.");
    var body = element("div", "resolution-body");
    var questions = Array.isArray(resolution.questions_for_party) ? resolution.questions_for_party : [];
    if (questions.length > 0) {
      body.appendChild(element("h4", "resolution-label", "Questions asked of the filing party"));
      var list = element("ul", "question-list");
      questions.forEach(function (question) {
        list.appendChild(element("li", null, displayValue(question)));
      });
      body.appendChild(list);
    } else {
      body.appendChild(element("p", "routing-explanation", "No questions were recorded on this case file."));
    }
    var facts = element("dl", "threshold-row");
    appendInfoRow(facts, "Questions asked", questions.length);
    appendInfoRow(facts, "Judge ran", false);
    appendInfoRow(facts, "Round", Array.isArray(caseFile.intake && caseFile.intake.follow_up_answers)
      && caseFile.intake.follow_up_answers.length > 0 ? 2 : 1);
    body.appendChild(facts);
    appendPartyMessage(body, resolution.party_message);
    card.appendChild(body);
    wrapper.appendChild(card);

    if (Array.isArray(resolution.notes) && resolution.notes.length > 0) {
      var humanCard = element("article", "resolution-card human-only-region");
      humanCard.dataset.audience = "human-review-only";
      var humanHeader = element("header", "human-only-header");
      humanHeader.appendChild(element("span", "human-only-label", "HUMAN-ONLY — NOT DELIVERED TO PARTIES"));
      humanHeader.appendChild(element("h3", null, "Notes for reviewer"));
      humanCard.appendChild(humanHeader);
      var humanBody = element("div", "resolution-body");
      appendResolutionNotes(humanBody, resolution.notes);
      humanCard.appendChild(humanBody);
      wrapper.appendChild(humanCard);
    }
    return wrapper;
  }

  function renderResolution(caseFile) {
    clear(resolutionContent);
    var resolution = caseFile.resolution && typeof caseFile.resolution === "object"
      ? caseFile.resolution
      : {};
    if (resolution.outcome === "ruled") {
      resolutionContent.appendChild(renderRuledResolution(resolution));
    } else if (resolution.outcome === "withheld") {
      resolutionContent.appendChild(renderWithheldResolution(resolution));
    } else if (resolution.outcome === "human_review") {
      resolutionContent.appendChild(renderHumanReviewResolution(caseFile, resolution));
    } else if (resolution.outcome === "needs_info") {
      resolutionContent.appendChild(renderNeedsInfoResolution(caseFile, resolution));
    } else {
      var warning = element("article", "resolution-card outcome-unknown");
      appendOutcomeHeader(warning, "UNKNOWN OUTCOME", "outcome-unknown-badge", "Operator attention required.");
      warning.appendChild(element("p", "routing-explanation", "Outcome: " + displayValue(resolution.outcome)));
      resolutionContent.appendChild(warning);
    }
  }

  function loadEventPayload(event, panel) {
    if (panel.dataset.loaded === "true") {
      return;
    }
    panel.dataset.loaded = "true";
    var reference = normalizedPayloadRef(event.payload_ref);
    if (!reference) {
      panel.appendChild(element("p", "payload-unavailable", "No safe relative payload reference was supplied for this event."));
      return;
    }
    if (state.openRun) {
      panel.appendChild(element("p", "payload-loading", "Reading " + reference + "…"));
      fetchJson("/api/review/" + encodeURIComponent(state.openRun.runId) + "/" + reference)
        .then(function (payload) {
          clear(panel);
          panel.appendChild(element("p", "payload-path", reference));
          panel.appendChild(element("pre", "payload-json", JSON.stringify(payload, null, 2)));
        })
        .catch(function () {
          clear(panel);
          panel.appendChild(element("p", "payload-error", "The payload could not be read."));
        });
      return;
    }
    var file = state.payloadFiles[reference];
    if (!file) {
      panel.appendChild(element("p", "payload-unavailable", "Attach the run directory to open this payload."));
      return;
    }
    panel.appendChild(element("p", "payload-loading", "Reading " + reference + "…"));
    file.text().then(function (text) {
      var payload;
      try {
        payload = JSON.parse(text);
      } catch (error) {
        clear(panel);
        panel.appendChild(element("p", "payload-error", "This payload is not valid JSON."));
        return;
      }
      clear(panel);
      panel.appendChild(element("p", "payload-path", reference));
      panel.appendChild(element("pre", "payload-json", JSON.stringify(payload, null, 2)));
    }).catch(function () {
      clear(panel);
      panel.appendChild(element("p", "payload-error", "The payload could not be read."));
    });
  }

  function renderEvents(caseFile) {
    clear(eventsContent);
    var events = Array.isArray(caseFile.events) ? caseFile.events : [];
    if (events.length === 0) {
      var empty = element("article", "deliberate-empty");
      empty.appendChild(element("h3", null, "No event traffic in this case file"));
      empty.appendChild(element("p", null, "The case file did not contain an events array."));
      eventsContent.appendChild(empty);
      return;
    }
    var intro = element("p", "event-intro", "Agent-to-agent traffic is shown in sequence. Expand an event to inspect its payload.");
    eventsContent.appendChild(intro);
    var stream = element("div", "event-stream");
    events.forEach(function (event, index) {
      if (!event || typeof event !== "object" || Array.isArray(event)) {
        var malformed = element("div", "event-row event-malformed");
        malformed.appendChild(element("p", null, "Event row " + (index + 1) + " is malformed and cannot be shown."));
        stream.appendChild(malformed);
        return;
      }
      var details = element("details", "event-row");
      details.dataset.sequence = displayValue(event.seq);
      if (event.type === "judge.ruling_withheld") {
        details.classList.add("event-internal");
      }
      var summary = element("summary", "event-summary");
      summary.appendChild(element("span", "event-seq", "#" + displayValue(event.seq)));
      summary.appendChild(element("time", "event-time", displayValue(event.ts)));
      summary.appendChild(element("span", "event-type", displayValue(event.type)));
      var route = element("span", "event-route");
      route.appendChild(element("span", "event-actor", displayValue(event.from)));
      route.appendChild(element("span", "event-arrow", "→"));
      route.appendChild(element("span", "event-actor", displayValue(event.to)));
      summary.appendChild(route);
      summary.appendChild(element("span", "event-summary-text", displayValue(event.summary)));
      summary.appendChild(element("span", "event-payload-ref", normalizedPayloadRef(event.payload_ref) || "No payload reference"));
      details.appendChild(summary);
      var panel = element("div", "event-payload");
      details.appendChild(panel);
      details.addEventListener("toggle", function () {
        if (details.open) {
          loadEventPayload(event, panel);
        }
      });
      stream.appendChild(details);
    });
    eventsContent.appendChild(stream);
  }

  function renderCase(fileName, caseFile) {
    state.caseFile = caseFile;
    loadedFile.textContent = fileName;
    renderMetadata(caseFile);
    renderGrievance(caseFile);
    renderEvidence(caseFile);
    renderPrompts(caseFile);
    renderClaims(caseFile);
    renderResolution(caseFile);
    renderEvents(caseFile);
    renderDecisionSection(caseFile);
    workspace.hidden = false;
    setStatus("Loaded " + fileName + ".", "success");
  }

  function handleFile(file) {
    if (!file) {
      return;
    }

    state.openRun = null;
    state.currentQueueRun = null;
    invalidatePendingOpens();
    applyQueueSelection();
    if (decisionSection) {
      decisionSection.hidden = true;
    }
    state.payloadFiles = {};
    setPayloadStatus("Payload files are not attached.", "idle");
    setStatus("Reading " + file.name + "…", "loading");
    file.text().then(function (text) {
      var parsed;
      try {
        parsed = JSON.parse(text);
      } catch (error) {
        throw new Error("The selected file is not valid JSON.");
      }
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("The selected JSON must contain one case-file object.");
      }
      renderCase(file.name, parsed);
    }).catch(function (error) {
      state.openRun = null;
      if (decisionSection) {
        decisionSection.hidden = true;
      }
      workspace.hidden = true;
      clear(metadataList);
      clear(grievanceContent);
      clear(evidenceContent);
      if (promptsContent) {
        clear(promptsContent);
      }
      clear(claimsContent);
      clear(policyContent);
      clear(resolutionContent);
      clear(eventsContent);
      setStatus(error.message, "error");
    });
  }

  function fetchJson(url, options) {
    if (typeof fetch !== "function") {
      return Promise.reject(new Error("Review API is unavailable."));
    }
    var request;
    try {
      request = fetch(url, options);
    } catch (error) {
      return Promise.reject(error);
    }
    return Promise.resolve(request).then(function (response) {
      if (!response || !response.ok) {
        throw new Error("Review request failed.");
      }
      return response.json();
    });
  }

  function fetchJsonAny(url, options) {
    if (typeof fetch !== "function") {
      return Promise.resolve({ ok: false, status: 0, payload: {} });
    }
    var request;
    try {
      request = fetch(url, options);
    } catch (error) {
      return Promise.resolve({ ok: false, status: 0, payload: {} });
    }
    return Promise.resolve(request).then(function (response) {
      var parsed = response && typeof response.json === "function"
        ? response.json()
        : Promise.resolve({});
      return Promise.resolve(parsed).then(function (payload) {
        return {
          ok: Boolean(response && response.ok),
          status: response && response.status,
          payload: payload
        };
      }, function () {
        return {
          ok: Boolean(response && response.ok),
          status: response && response.status,
          payload: {}
        };
      });
    }, function () {
      return { ok: false, status: 0, payload: {} };
    });
  }

  function finiteNumber(value) {
    return typeof value === "number" && isFinite(value);
  }

  function formatMoney(value) {
    return finiteNumber(value) ? "SGD " + value.toFixed(2) : null;
  }

  function categoryLabel(category) {
    if (category === "route_deviation") {
      return "Route deviation";
    }
    if (category === "no_show_charge") {
      return "No-show charge";
    }
    return "Other";
  }

  function heldLabel(heldBy) {
    if (!Array.isArray(heldBy) || heldBy.length === 0) {
      return "not recorded";
    }
    return heldBy.map(function (gate) {
      return gate === "model_failure" ? "model failure" : displayValue(gate);
    }).join(", ");
  }

  function waitingLabel(value) {
    var seconds = Number(value);
    if (!finiteNumber(seconds)) {
      seconds = 0;
    }
    seconds = Math.max(0, Math.floor(seconds));
    if (seconds < 60) {
      return "Waiting under a minute";
    }
    if (seconds < 3600) {
      return "Waiting " + Math.floor(seconds / 60) + " min";
    }
    if (seconds < 86400) {
      return "Waiting " + Math.floor(seconds / 3600) + " h "
        + Math.floor((seconds % 3600) / 60) + " min";
    }
    return "Waiting " + Math.floor(seconds / 86400) + " d "
      + Math.floor((seconds % 86400) / 3600) + " h";
  }

  function queueAmountText(entry) {
    var amount = entry && entry.amount_sgd;
    var money = formatMoney(amount);
    if (!money) {
      return "No amount on record";
    }
    if (entry.amount_source === "proposed") {
      return money + " proposed";
    }
    if (entry.amount_source === "claimed") {
      return money + " claimed";
    }
    return money;
  }

  function setQueueRowStatus(statusElement, message) {
    if (statusElement) {
      statusElement.textContent = message || "";
    }
  }

  function restoreOpenButton(button) {
    if (button) {
      button.textContent = "Open case";
      button.disabled = false;
    }
  }

  function settlePendingOpen(generation) {
    for (var index = 0; index < state.pendingOpens.length; index += 1) {
      if (state.pendingOpens[index].generation === generation) {
        state.pendingOpens.splice(index, 1);
        return;
      }
    }
  }

  function isButtonPending(button) {
    for (var index = 0; index < state.pendingOpens.length; index += 1) {
      if (state.pendingOpens[index].button === button) {
        return true;
      }
    }
    return false;
  }

  function invalidatePendingOpens() {
    state.openGeneration += 1;
    var pendings = state.pendingOpens;
    state.pendingOpens = [];
    pendings.forEach(function (pending) {
      restoreOpenButton(pending.button);
    });
  }

  function applyQueueSelection() {
    if (!queueContent || typeof queueContent.querySelectorAll !== "function") {
      return;
    }
    var rows = queueContent.querySelectorAll(".queue-row");
    Array.prototype.forEach.call(rows, function (row) {
      var button = typeof row.querySelector === "function" ? row.querySelector(".queue-open") : null;
      if (!button) {
        return;
      }
      var current = state.currentQueueRun !== null
        && Boolean(row.dataset) && row.dataset.runId === state.currentQueueRun;
      if (current) {
        row.classList.add("is-open");
        button.textContent = "Currently open";
        button.setAttribute("aria-current", "true");
        button.disabled = false;
        return;
      }
      row.classList.remove("is-open");
      if (typeof button.removeAttribute === "function") {
        button.removeAttribute("aria-current");
      } else if (button.getAttribute && button.getAttribute("aria-current") !== null) {
        button.setAttribute("aria-current", "false");
      }
      if (!isButtonPending(button)) {
        restoreOpenButton(button);
      }
    });
  }

  function renderQueue(data) {
    clear(queueContent);
    var cases = data && Array.isArray(data.cases) ? data.cases : [];
    if (cases.length === 0) {
      queueStatus.textContent = "No cases are waiting for a human decision.";
      return;
    }
    queueStatus.textContent = cases.length === 1
      ? "1 case waiting."
      : cases.length + " cases waiting.";
    var list = element("ol", "queue-list");
    cases.forEach(function (rawEntry) {
      var entry = rawEntry && typeof rawEntry === "object" ? rawEntry : {};
      var row = element("li", "queue-row");
      row.dataset.runId = typeof entry.run_id === "string" ? entry.run_id : "";
      row.appendChild(element("span", "queue-category", categoryLabel(entry.category)));
      if (entry.safety === true) {
        row.appendChild(element("span", "queue-safety", "Safety"));
      }
      row.appendChild(element("span", "queue-amount", queueAmountText(entry)));
      row.appendChild(element("span", "queue-held", "Held by: " + heldLabel(entry.held_by)));
      row.appendChild(element("span", "queue-waiting", waitingLabel(entry.waiting_seconds)));
      var open = element("button", "queue-open", "Open case");
      open.type = "button";
      var openStatus = element("p", "queue-open-status");
      openStatus.setAttribute("role", "status");
      openStatus.setAttribute("aria-live", "polite");
      open.addEventListener("click", function () {
        openCase(entry, open, openStatus);
      });
      row.appendChild(open);
      row.appendChild(openStatus);
      list.appendChild(row);
    });
    queueContent.appendChild(list);
    applyQueueSelection();
  }

  function renderOverrides(data) {
    clear(overridesContent);
    var approved = data && data.approved_count;
    overridesContent.appendChild(element("p", "overrides-approved", "Approved as proposed: " + displayValue(approved)));
    var groups = data && Array.isArray(data.groups) ? data.groups : [];
    if (groups.length === 0) {
      overridesStatus.textContent = "No changed or rejected decisions yet.";
      return;
    }
    overridesStatus.textContent = "";
    groups.forEach(function (groupValue) {
      var group = groupValue && typeof groupValue === "object" ? groupValue : {};
      var article = element("article", "override-group");
      var count = group.count === 1 ? "1 case" : displayValue(group.count) + " cases";
      var heading = categoryLabel(group.category) + " · " + heldLabel(group.held_by)
        + " · " + displayValue(group.decision) + " to " + displayValue(group.action)
        + " · " + count;
      article.appendChild(element("h3", null, heading));
      var list = element("ul", null);
      var decisions = Array.isArray(group.decisions) ? group.decisions : [];
      decisions.forEach(function (decisionValue) {
        var decision = decisionValue && typeof decisionValue === "object" ? decisionValue : {};
        var entry = element("li", "override-entry");
        var identifier = decision.dispute_id || decision.run_id || "Not recorded";
        var amount = formatMoney(decision.amount_sgd) || "No amount on record";
        var proposed = decision.proposed;
        var proposalText = "No AI proposal";
        if (proposed && typeof proposed === "object") {
          if (proposed.action === "no action") {
            proposalText = "AI proposed no action";
          } else if (finiteNumber(proposed.amount_sgd)) {
            proposalText = "AI proposed " + formatMoney(proposed.amount_sgd);
          }
        }
        entry.appendChild(element("span", null, displayValue(identifier)));
        entry.appendChild(element("span", null, displayValue(decision.reviewer)));
        entry.appendChild(element("span", null, amount));
        entry.appendChild(element("span", null, proposalText));
        entry.appendChild(element("span", null, displayValue(decision.reason)));
        list.appendChild(entry);
      });
      article.appendChild(list);
      overridesContent.appendChild(article);
    });
  }

  function loadQueue() {
    return fetchJson("/api/review/queue").then(function (data) {
      renderQueue(data);
    }).catch(function () {
      clear(queueContent);
      queueStatus.textContent = "The review queue is not available. Open the console from the running server to use it.";
    });
  }

  function loadOverrides() {
    return fetchJson("/api/review/overrides").then(function (data) {
      renderOverrides(data);
    }).catch(function () {
      clear(overridesContent);
      overridesStatus.textContent = "Overrides are not available.";
    });
  }

  function loadReviewPanels() {
    loadQueue();
    loadOverrides();
  }

  function prefersReducedMotion() {
    return typeof window !== "undefined"
      && typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches === true;
  }

  function revealCaseSummary() {
    var summary = document.getElementById("case-summary");
    if (!summary) {
      return;
    }
    summary.setAttribute("tabindex", "-1");
    summary.classList.add("case-open-highlight");
    if (typeof summary.scrollIntoView === "function") {
      summary.scrollIntoView({
        block: "start",
        behavior: prefersReducedMotion() ? "auto" : "smooth"
      });
    }
    if (typeof summary.focus === "function") {
      summary.focus({ preventScroll: true });
    }
    if (state.highlightTimer !== null && typeof clearTimeout === "function") {
      clearTimeout(state.highlightTimer);
    }
    if (typeof setTimeout === "function") {
      state.highlightTimer = setTimeout(function () {
        state.highlightTimer = null;
        summary.classList.remove("case-open-highlight");
      }, 1200);
    }
  }

  function openCase(entry, button, statusElement) {
    var runId = entry && typeof entry.run_id === "string" ? entry.run_id : "";
    state.openGeneration += 1;
    var generation = state.openGeneration;
    setQueueRowStatus(statusElement, "");
    if (button) {
      button.textContent = "Opening…";
      button.disabled = true;
    }
    state.pendingOpens.push({ generation: generation, button: button });
    fetchJson("/api/review/" + encodeURIComponent(runId) + "/case").then(function (data) {
      if (generation !== state.openGeneration) {
        settlePendingOpen(generation);
        applyQueueSelection();
        return;
      }
      if (!data || !data.case_file || typeof data.case_file !== "object" || Array.isArray(data.case_file)) {
        throw new Error("Invalid case file");
      }
      settlePendingOpen(generation);
      state.openRun = {
        runId: runId,
        entry: entry && typeof entry === "object" ? entry : {},
        humanDecision: data.human_decision || null
      };
      state.currentQueueRun = runId;
      renderCase(runId, data.case_file);
      applyQueueSelection();
      revealCaseSummary();
    }).catch(function () {
      if (generation !== state.openGeneration) {
        settlePendingOpen(generation);
        applyQueueSelection();
        return;
      }
      settlePendingOpen(generation);
      state.openRun = null;
      if (decisionSection) {
        decisionSection.hidden = true;
      }
      setQueueRowStatus(statusElement, "The case could not be opened.");
      applyQueueSelection();
      setStatus("The case could not be opened.", "error");
    });
  }

  function locationSearch() {
    if (typeof window !== "undefined" && window.location && typeof window.location.search === "string") {
      return window.location.search;
    }
    if (typeof location !== "undefined" && location && typeof location.search === "string") {
      return location.search;
    }
    return "";
  }

  function deepLinkRunId() {
    var search = locationSearch();
    if (!search || typeof URLSearchParams !== "function") {
      return null;
    }
    var runId;
    try {
      runId = new URLSearchParams(search).get("run");
    } catch (error) {
      return null;
    }
    return runId === null || runId === undefined ? null : runId;
  }

  function openDeepLink() {
    var runId = deepLinkRunId();
    if (runId === null) {
      return;
    }
    if (!RUN_ID_PATTERN.test(runId)) {
      setStatus(PROMPTS_UNKNOWN_RUN, "error");
      return;
    }
    openCase({ run_id: runId }, null, null);
  }

  function decisionProposal() {
    var entry = state.openRun && state.openRun.entry;
    var proposed = entry && entry.proposed;
    return proposed && typeof proposed === "object" && !Array.isArray(proposed) ? proposed : null;
  }

  function decisionFare() {
    var pack = state.caseFile && state.caseFile.evidence_pack;
    var fare = pack && pack.fare;
    return fare && typeof fare === "object" ? fare.charged_sgd : null;
  }

  function typedAmount(value) {
    if (typeof value !== "string" || value.trim() === "") {
      return NaN;
    }
    return Number(value);
  }

  function syncDecisionControls() {
    if (!decisionUi) {
      return;
    }
    var enabled = decisionUi.change.checked === true;
    decisionUi.action.disabled = !enabled;
    decisionUi.amount.disabled = !enabled;
  }

  function appendDecisionLabel(form, forId, text) {
    var label = element("label", null, text);
    label.htmlFor = forId;
    form.appendChild(label);
  }

  function buildDecisionForm() {
    var entry = state.openRun && state.openRun.entry ? state.openRun.entry : {};
    var form = element("form");
    form.id = "decision-form";
    var options = element("div", "decision-options");
    var radios = [];
    [
      ["decision-approve", "approve", "Approve the AI's proposal"],
      ["decision-change", "change", "Change the decision"],
      ["decision-reject", "reject", "Reject: no action"]
    ].forEach(function (definition) {
      var option = element("div", "decision-option");
      var radio = element("input");
      radio.id = definition[0];
      radio.type = "radio";
      radio.name = "decision";
      radio.value = definition[1];
      radio.checked = false;
      radio.addEventListener("change", syncDecisionControls);
      option.appendChild(radio);
      var label = element("label", null, definition[2]);
      label.htmlFor = radio.id;
      option.appendChild(label);
      options.appendChild(option);
      radios.push(radio);
    });
    form.appendChild(options);

    var canApprove = entry.can_approve === true && decisionProposal() !== null;
    if (!canApprove) {
      radios[0].disabled = true;
      form.appendChild(element("p", "decision-note", "No AI proposal to approve; use Change."));
    }

    appendDecisionLabel(form, "decision-reviewer", "Your name");
    var reviewer = element("input");
    reviewer.id = "decision-reviewer";
    reviewer.type = "text";
    reviewer.maxLength = 80;
    form.appendChild(reviewer);

    appendDecisionLabel(form, "decision-reason", "Reason (staff only, never shown to the party)");
    var reason = element("textarea");
    reason.id = "decision-reason";
    reason.maxLength = 1000;
    form.appendChild(reason);

    appendDecisionLabel(form, "decision-action", "Action");
    var action = element("select");
    action.id = "decision-action";
    ["refund", "compensation", "no action"].forEach(function (value) {
      var option = element("option", null, value);
      option.value = value;
      action.appendChild(option);
    });
    form.appendChild(action);

    appendDecisionLabel(form, "decision-amount", "Amount (SGD)");
    var amount = element("input");
    amount.id = "decision-amount";
    amount.type = "number";
    amount.step = "0.01";
    amount.min = "0";
    form.appendChild(amount);

    action.disabled = true;
    amount.disabled = true;
    var review = element("button", null, "Review decision");
    review.id = "decision-review";
    review.type = "submit";
    form.appendChild(review);

    var error = element("p");
    error.id = "decision-error";
    error.setAttribute("role", "alert");
    error.textContent = "";
    form.appendChild(error);

    decisionUi = {
      form: form,
      radios: radios,
      approve: radios[0],
      change: radios[1],
      reject: radios[2],
      reviewer: reviewer,
      reason: reason,
      action: action,
      amount: amount,
      review: review,
      error: error,
      confirm: null,
      send: null,
      sending: false
    };
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      reviewDecision();
    });
    return form;
  }

  function selectedDecision() {
    if (!decisionUi) {
      return null;
    }
    for (var index = 0; index < decisionUi.radios.length; index += 1) {
      if (decisionUi.radios[index].checked) {
        return decisionUi.radios[index].value;
      }
    }
    return null;
  }

  function aiProposalText(proposed) {
    if (!proposed || typeof proposed !== "object") {
      return "AI proposed: no proposal on record";
    }
    if (proposed.action === "no action") {
      return "AI proposed: no action";
    }
    if (finiteNumber(proposed.amount_sgd)) {
      return "AI proposed: " + displayValue(proposed.action) + " of " + formatMoney(proposed.amount_sgd);
    }
    return "AI proposed: no proposal on record";
  }

  function buildConfirmation(decision) {
    if (!decisionUi.confirm) {
      var confirm = element("div", "decision-confirm");
      confirm.id = "decision-confirm";
      var send = element("button", null, "Confirm and send");
      send.id = "decision-confirm-send";
      send.type = "button";
      var back = element("button", null, "Go back and edit");
      back.id = "decision-confirm-back";
      back.type = "button";
      send.addEventListener("click", sendDecision);
      back.addEventListener("click", function () {
        if (decisionUi) {
          decisionUi.confirm.hidden = true;
          decisionUi.form.hidden = false;
        }
      });
      decisionUi.confirm = confirm;
      decisionUi.send = send;
      decisionUi.back = back;
      decisionContent.appendChild(confirm);
    }
    var confirmBox = decisionUi.confirm;
    clear(confirmBox);
    var proposed = decisionProposal();
    var amountForWarning = NaN;
    var amountLine;
    if (decision === "approve") {
      if (proposed && proposed.action === "no action") {
        amountLine = "Amount: no action";
      } else if (proposed && proposed.action && finiteNumber(proposed.amount_sgd)) {
        amountForWarning = proposed.amount_sgd;
        amountLine = "Amount: " + proposed.action + " of " + formatMoney(proposed.amount_sgd);
      } else {
        amountLine = "Amount: no action";
      }
    } else if (decision === "reject") {
      amountLine = "Amount: no action";
    } else {
      amountForWarning = typedAmount(decisionUi.amount.value);
      if (finiteNumber(amountForWarning)) {
        amountLine = "Amount: " + decisionUi.action.value + " of SGD " + amountForWarning.toFixed(2);
      } else {
        amountLine = "Amount: " + decisionUi.action.value + ", amount not a number";
      }
    }
    decisionUi.send.disabled = decision === "change" && !finiteNumber(amountForWarning);
    confirmBox.appendChild(element("p", null, "Decision: " + (decision === "approve" ? "Approve" : decision === "change" ? "Change" : "Reject")));
    confirmBox.appendChild(element("p", null, amountLine));
    var fare = decisionFare();
    if (finiteNumber(fare)) {
      confirmBox.appendChild(element("p", null, "Trip fare charged: " + formatMoney(fare)));
    } else {
      confirmBox.appendChild(element("p", null, "Trip fare charged: not on record"));
    }
    confirmBox.appendChild(element("p", null, aiProposalText(proposed)));
    if (finiteNumber(amountForWarning) && finiteNumber(fare) && amountForWarning > fare) {
      confirmBox.appendChild(element("p", "confirm-warning", "This amount is more than the trip fare."));
    }
    confirmBox.appendChild(decisionUi.send);
    confirmBox.appendChild(decisionUi.back);
    confirmBox.hidden = false;
    decisionUi.form.hidden = true;
  }

  function reviewDecision() {
    var decision = selectedDecision();
    if (!decision) {
      decisionUi.error.textContent = "Choose approve, change or reject.";
      return;
    }
    decisionUi.error.textContent = "";
    buildConfirmation(decision);
  }

  function decisionRequestBody(decision) {
    var body = {
      decision: decision,
      reviewer: decisionUi.reviewer.value,
      reason: decisionUi.reason.value
    };
    if (decision === "change") {
      body.action = decisionUi.action.value;
      body.amount_sgd = typedAmount(decisionUi.amount.value);
    }
    return body;
  }

  function showDecisionError(payload) {
    var message = payload && typeof payload.error === "string" && payload.error
      ? payload.error
      : "The decision could not be recorded.";
    decisionUi.confirm.hidden = true;
    decisionUi.form.hidden = false;
    decisionUi.error.textContent = message;
    decisionUi.send.disabled = false;
    decisionUi.sending = false;
  }

  function sendDecision() {
    if (!decisionUi || decisionUi.sending || !state.openRun) {
      return;
    }
    var ui = decisionUi;
    var runId = state.openRun.runId;
    var decision = selectedDecision();
    if (!decision) {
      return;
    }
    if (decision === "change" && !finiteNumber(typedAmount(ui.amount.value))) {
      return;
    }
    ui.sending = true;
    ui.send.disabled = true;
    var body = decisionRequestBody(decision);
    fetchJsonAny(
      "/api/review/" + encodeURIComponent(runId) + "/decision",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      }
    ).then(function (result) {
      if (decisionUi !== ui || !state.openRun || state.openRun.runId !== runId) {
        return;
      }
      if (!result.ok) {
        showDecisionError(result.payload);
        return;
      }
      var resultBox = element("div", "decision-result");
      resultBox.appendChild(element("p", null, "Decision recorded. The party now sees:"));
      var partyView = result.payload && result.payload.party_view;
      resultBox.appendChild(element("blockquote", null, partyView && partyView.message));
      clear(decisionContent);
      decisionContent.appendChild(resultBox);
      decisionUi = null;
      loadReviewPanels();
    }, function () {
      if (decisionUi !== ui || !state.openRun || state.openRun.runId !== runId) {
        return;
      }
      showDecisionError({});
    });
  }

  function renderRecordedDecision(decision) {
    var article = element("article", "human-decision-record");
    article.appendChild(element("h3", null, "Human decision recorded"));
    article.appendChild(element("p", null, "Decision: " + displayValue(decision.decision)));
    article.appendChild(element("p", null, "Reviewer: " + displayValue(decision.reviewer)));
    article.appendChild(element("p", null, "Reason: " + displayValue(decision.reason)));
    article.appendChild(element("p", null, "Action: " + displayValue(decision.action)));
    article.appendChild(element("p", null, "Amount: " + (formatMoney(decision.amount_sgd) || "no action")));
    article.appendChild(element("p", null, "Decided at: " + displayValue(decision.decided_at)));
    return article;
  }

  function renderDecisionSection(caseFile) {
    if (!decisionSection || !decisionContent) {
      return;
    }
    decisionSection.hidden = true;
    clear(decisionContent);
    decisionUi = null;
    var resolution = caseFile && caseFile.resolution;
    if (!state.openRun || !resolution || resolution.outcome !== "withheld") {
      return;
    }
    decisionSection.hidden = false;
    if (state.openRun.humanDecision && typeof state.openRun.humanDecision === "object") {
      decisionContent.appendChild(renderRecordedDecision(state.openRun.humanDecision));
      return;
    }
    decisionContent.appendChild(buildDecisionForm());
  }

  picker.addEventListener("change", function () {
    handleFile(picker.files[0]);
  });

  runFolderPicker.addEventListener("change", function () {
    attachRunFiles(runFolderPicker.files);
  });

  if (reviewUi && typeof fetch === "function") {
    queueRefresh.addEventListener("click", loadReviewPanels);
    loadReviewPanels();
  }

  openDeepLink();
}());
