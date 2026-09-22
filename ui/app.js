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
    payloadFiles: {}
  };

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
    body.appendChild(element("p", "routing-explanation", "This case file records a ruled outcome but contains no ruling object, so the Judge's delivery cannot be verified."));
    var details = element("dl", "threshold-row");
    appendInfoRow(details, "Recorded outcome", resolution.outcome);
    appendInfoRow(details, "Ruling object", resolution.ruling);
    body.appendChild(details);
    card.appendChild(body);
    return card;
  }

  function renderRuledResolution(resolution) {
    if (!resolution.ruling || typeof resolution.ruling !== "object") {
      return renderMalformedRuledResolution(resolution);
    }
    var card = element("article", "resolution-card outcome-ruled");
    card.dataset.audience = "parties";
    appendOutcomeHeader(card, "RULING ISSUED", "outcome-ruled-badge", "The Judge delivered this decision to the parties.");
    var body = element("div", "resolution-body");
    appendRulingDetails(body, resolution.ruling, true);
    var threshold = element("dl", "threshold-row");
    appendInfoRow(threshold, "Confidence threshold", resolution.confidence_threshold, "info-row", "confidence_threshold");
    body.appendChild(threshold);
    appendPartyMessage(body, resolution.party_message);
    card.appendChild(body);
    return card;
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
    renderClaims(caseFile);
    renderResolution(caseFile);
    renderEvents(caseFile);
    workspace.hidden = false;
    setStatus("Loaded " + fileName + ".", "success");
  }

  function handleFile(file) {
    if (!file) {
      return;
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
      workspace.hidden = true;
      clear(metadataList);
      clear(grievanceContent);
      clear(evidenceContent);
      clear(claimsContent);
      clear(policyContent);
      clear(resolutionContent);
      clear(eventsContent);
      setStatus(error.message, "error");
    });
  }

  picker.addEventListener("change", function () {
    handleFile(picker.files[0]);
  });

  runFolderPicker.addEventListener("change", function () {
    attachRunFiles(runFolderPicker.files);
  });
}());
