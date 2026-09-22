(function () {
  "use strict";

  var picker = document.getElementById("case-picker");
  var status = document.getElementById("load-status");
  var summary = document.getElementById("case-summary");
  var loadedFile = document.getElementById("loaded-file");
  var metadataList = document.getElementById("metadata-list");

  function clear(element) {
    while (element.firstChild) {
      element.removeChild(element.firstChild);
    }
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

  function addMetadata(label, value) {
    var term = document.createElement("dt");
    term.textContent = label;
    var description = document.createElement("dd");
    description.textContent = displayValue(value);
    metadataList.appendChild(term);
    metadataList.appendChild(description);
  }

  function setStatus(message, state) {
    status.textContent = message;
    status.dataset.state = state || "idle";
  }

  function renderCase(fileName, caseFile) {
    clear(metadataList);
    loadedFile.textContent = fileName;
    addMetadata("Dispute ID", caseFile.dispute_id);
    addMetadata("Run ID", caseFile.run_id);
    addMetadata("Category", caseFile.category);
    addMetadata("Generated at", caseFile.generated_at);
    addMetadata("Outcome", caseFile.resolution && caseFile.resolution.outcome);
    summary.hidden = false;
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
      summary.hidden = true;
      clear(metadataList);
      setStatus(error.message, "error");
    });
  }

  picker.addEventListener("change", function () {
    handleFile(picker.files[0]);
  });
}());
