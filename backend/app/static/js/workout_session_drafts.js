(function () {
  "use strict";

  const STORAGE_PREFIX = "health-tracker:v1:workout-draft:";
  const LOCAL_DEBOUNCE_MS = 500;

  function removeCompletedDraft() {
    const marker = document.getElementById("completed-workout-submission");
    if (!marker) return;
    const prefix = `${STORAGE_PREFIX}${marker.dataset.userPublicId}:`;
    for (let index = localStorage.length - 1; index >= 0; index -= 1) {
      const key = localStorage.key(index);
      if (!key || !key.startsWith(prefix)) continue;
      try {
        const candidate = JSON.parse(localStorage.getItem(key));
        if (candidate && candidate.client_submission_id === marker.dataset.clientSubmissionId) {
          localStorage.removeItem(key);
        }
      } catch (_error) {
        localStorage.removeItem(key);
      }
    }
  }

  removeCompletedDraft();
  const form = document.getElementById("workout-session-form");
  if (!form) return;

  const status = document.getElementById("workout-draft-status");
  const discard = document.getElementById("discard-workout-draft");
  const submit = form.querySelector('button[type="submit"], input[type="submit"]');
  const csrf = form.querySelector('[name="csrf_token"]');
  const submission = form.querySelector('[name="client_submission_id"]');
  const maxBytes = Number(form.dataset.draftMaxBytes || 262144);
  const ttlDays = Number(form.dataset.draftTtlDays || 7);
  const serverDebounceMs = Number(form.dataset.serverDebounceMs || 3000);
  const key = [
    STORAGE_PREFIX.slice(0, -1),
    form.dataset.userPublicId,
    form.dataset.planVersionPublicId,
    form.dataset.weekNumber,
    form.dataset.dayNumber,
  ].join(":");
  let localTimer = null;
  let serverTimer = null;
  let serverPublicId = null;
  let serverRevision = null;

  function setStatus(code, message, kind) {
    if (!status) return;
    status.dataset.statusCode = code;
    status.textContent = message;
    status.className = `status status-${kind || "muted"}`;
  }

  function byteLength(value) {
    return new TextEncoder().encode(value).length;
  }

  function formFields() {
    const fields = {};
    form.querySelectorAll("[name]").forEach((control) => {
      if (!control.name || control.name === "csrf_token" || control.type === "submit") return;
      if (control.type === "checkbox") fields[control.name] = control.checked;
      else if (control.type === "radio") {
        if (control.checked) fields[control.name] = control.value;
      } else if (control.multiple) {
        fields[control.name] = Array.from(control.selectedOptions).map((item) => item.value);
      } else fields[control.name] = control.value;
    });
    return fields;
  }

  function buildPayload() {
    const now = new Date();
    return {
      schema_version: "1.0",
      client_submission_id: submission.value,
      context: {
        form_url: form.dataset.formUrl,
        plan_public_id: form.dataset.planPublicId,
        training_plan_version_public_id: form.dataset.planVersionPublicId,
        planned_workout_public_id: form.dataset.plannedWorkoutPublicId || null,
        planned_week_number: Number(form.dataset.weekNumber),
        planned_day_number: Number(form.dataset.dayNumber),
      },
      fields: formFields(),
      updated_at: now.toISOString(),
      expires_at: new Date(now.getTime() + ttlDays * 86400000).toISOString(),
    };
  }

  function validCandidate(candidate) {
    return Boolean(
      candidate && candidate.schema_version === "1.0" &&
      candidate.client_submission_id && candidate.context &&
      candidate.context.training_plan_version_public_id === form.dataset.planVersionPublicId &&
      Number(candidate.context.planned_week_number) === Number(form.dataset.weekNumber) &&
      Number(candidate.context.planned_day_number) === Number(form.dataset.dayNumber) &&
      candidate.fields && typeof candidate.fields === "object" &&
      new Date(candidate.expires_at).getTime() > Date.now()
    );
  }

  function applyCandidate(candidate) {
    Object.entries(candidate.fields).forEach(([name, value]) => {
      form.querySelectorAll(`[name="${CSS.escape(name)}"]`).forEach((control) => {
        if (control.type === "checkbox") control.checked = Boolean(value);
        else if (control.type === "radio") control.checked = control.value === String(value);
        else if (control.multiple && Array.isArray(value)) {
          Array.from(control.options).forEach((option) => {
            option.selected = value.includes(option.value);
          });
        } else if (value !== null && value !== undefined) control.value = String(value);
      });
    });
    submission.value = candidate.client_submission_id;
  }

  function localCandidate() {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw);
      if (!validCandidate(parsed) || byteLength(raw) > maxBytes) {
        localStorage.removeItem(key);
        return null;
      }
      return parsed;
    } catch (_error) {
      localStorage.removeItem(key);
      setStatus("draft_corrupt", "El borrador local estaba dañado y fue descartado", "warning");
      return null;
    }
  }

  function embeddedServerDraft() {
    const node = document.getElementById("server-workout-draft");
    if (!node) return null;
    try {
      const envelope = JSON.parse(node.textContent);
      if (!envelope || !validCandidate(envelope.payload)) return null;
      serverPublicId = envelope.public_id;
      serverRevision = envelope.revision;
      return envelope.payload;
    } catch (_error) {
      return null;
    }
  }

  async function saveServer(payload) {
    if (!csrf || !csrf.value) return;
    const url = serverPublicId ? `/workout-session-drafts/${encodeURIComponent(serverPublicId)}` : "/workout-session-drafts";
    const body = serverPublicId ? { payload: payload, revision: serverRevision } : { payload: payload };
    try {
      const response = await fetch(url, {
        method: serverPublicId ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf.value },
        credentials: "same-origin",
        body: JSON.stringify(body),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        const code = result.error && result.error.code;
        setStatus(code || "draft_save_failed", code === "draft_conflict" ? "Conflicto de borrador" : "No se pudo guardar el borrador en servidor", "warning");
        return;
      }
      serverPublicId = result.data.public_id;
      serverRevision = result.data.revision;
      setStatus("draft_saved", "Borrador guardado", "success");
    } catch (_error) {
      setStatus("draft_server_offline", "Borrador local guardado; servidor no disponible", "warning");
    }
  }

  function saveLocal() {
    const payload = buildPayload();
    const serialized = JSON.stringify(payload);
    if (byteLength(serialized) > maxBytes) {
      setStatus("draft_too_large", "No se pudo guardar: borrador demasiado grande", "danger");
      return;
    }
    try {
      localStorage.setItem(key, serialized);
      setStatus("draft_saved", "Borrador guardado", "success");
    } catch (_error) {
      setStatus("draft_local_failed", "No se pudo guardar el borrador local", "danger");
      return;
    }
    window.clearTimeout(serverTimer);
    serverTimer = window.setTimeout(() => saveServer(payload), serverDebounceMs);
  }

  function scheduleSave() {
    setStatus("draft_saving", "Guardando…", "muted");
    window.clearTimeout(localTimer);
    localTimer = window.setTimeout(saveLocal, LOCAL_DEBOUNCE_MS);
  }

  const local = localCandidate();
  const server = embeddedServerDraft();
  if (form.dataset.recoveredPost === "true") {
    setStatus("csrf_expired_recovered", "Borrador recuperado", "warning");
    scheduleSave();
  } else {
    const candidates = [local, server].filter(Boolean).sort(
      (left, right) => new Date(right.updated_at) - new Date(left.updated_at)
    );
    if (candidates.length) {
      applyCandidate(candidates[0]);
      setStatus("draft_restored", "Borrador recuperado", "warning");
    }
  }

  form.addEventListener("input", scheduleSave);
  form.addEventListener("change", scheduleSave);
  form.querySelectorAll("tbody").forEach((body) => {
    new MutationObserver(scheduleSave).observe(body, { childList: true, subtree: true });
  });
  form.addEventListener("submit", () => {
    saveLocal();
    setStatus("session_saving", "Guardando sesión…", "muted");
    if (submit) {
      submit.disabled = true;
      if (submit.tagName === "INPUT") submit.value = submit.dataset.savingLabel || "Guardando…";
      else submit.textContent = submit.dataset.savingLabel || "Guardando…";
    }
  });

  if (discard) discard.addEventListener("click", async () => {
    if (!window.confirm("¿Descartar este borrador y los datos capturados?")) return;
    localStorage.removeItem(key);
    if (serverPublicId && csrf && csrf.value) {
      await fetch(`/workout-session-drafts/${encodeURIComponent(serverPublicId)}`, {
        method: "DELETE",
        headers: { "X-CSRFToken": csrf.value },
        credentials: "same-origin",
      }).catch(() => null);
    }
    window.location.assign(form.dataset.formUrl);
  });
})();
