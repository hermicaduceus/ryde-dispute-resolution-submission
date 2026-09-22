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
    policyIndex: {}
  };

  var picker = document.getElementById("case-picker");
  var status = document.getElementById("load-status");
  var workspace = document.getElementById("case-workspace");
  var loadedFile = document.getElementById("loaded-file");
  var metadataList = document.getElementById("metadata-list");
  var grievanceContent = document.getElementById("grievance-content");
  var evidenceContent = document.getElementById("evidence-content");
  var claimsContent = document.getElementById("claims-content");
  var policyContent = document.getElementById("policy-content");

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
      notBuilt.appendChild(element("h3", null, "Evidence Pack not built"));
      notBuilt.appendChild(element("p", null, "This case file does not contain computed evidence."));
      appendNotes(notBuilt, noteValues(null, null));
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

  function renderCase(fileName, caseFile) {
    state.caseFile = caseFile;
    loadedFile.textContent = fileName;
    renderMetadata(caseFile);
    renderGrievance(caseFile);
    renderEvidence(caseFile);
    renderClaims(caseFile);
    workspace.hidden = false;
    setStatus("Loaded " + fileName + ".", "success");
  }

  function handleFile(file) {
    if (!file) {
      return;
    }

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
      setStatus(error.message, "error");
    });
  }

  picker.addEventListener("change", function () {
    handleFile(picker.files[0]);
  });
}());
