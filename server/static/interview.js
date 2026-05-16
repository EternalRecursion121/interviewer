/* AFFINE interview — phase-1 form → streamed conversation → notes review.
   SSE is consumed over fetch() (endpoints are POST, so EventSource won't do). */
(function () {
  "use strict";

  var sessionId = null;
  var ended = false;

  var $ = function (id) { return document.getElementById(id); };
  var introBlock = $("introBlock");
  var form = $("phase1");
  var chat = $("chat");
  var transcript = $("transcript");
  var statusEl = $("status");
  var input = $("input");
  var sendBtn = $("sendBtn");
  var endBtn = $("endBtn");
  var notesStage = $("notesStage");
  var notesEdit = $("notesEdit");

  /* ---- tiny safe markdown (escape, then **bold** *italic* paras) -------- */
  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function mdInline(s) {
    return esc(s)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  }
  function mdBlock(s) {
    var paras = s.split(/\n{2,}/).map(function (p) {
      return "<p>" + mdInline(p).replace(/\n/g, "<br>") + "</p>";
    });
    return paras.join("");
  }

  /* ---- transcript helpers --------------------------------------------- */
  function addMsg(who, cls) {
    var wrap = document.createElement("div");
    wrap.className = "msg " + cls;
    var label = document.createElement("div");
    label.className = "who";
    label.textContent = who;
    var bubble = document.createElement("div");
    bubble.className = "bubble";
    wrap.appendChild(label);
    wrap.appendChild(bubble);
    transcript.appendChild(wrap);
    scroll();
    return bubble;
  }
  function addTool(label) {
    var t = document.createElement("div");
    t.className = "tool-trace";
    t.textContent = label;
    transcript.appendChild(t);
    scroll();
    return t;
  }
  function scroll() {
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  }
  function setStatus(html) { statusEl.innerHTML = html || ""; }

  function fmtTime(elapsed, budget) {
    var m = Math.floor(elapsed / 60);
    var s = "" + m + " min in";
    if (budget) {
      var rem = Math.max(0, Math.round((budget - elapsed) / 60));
      s += ' · <span class="iv-time">~' + rem + " min left of what you set</span>";
    }
    return s;
  }

  /* ---- SSE over fetch -------------------------------------------------- */
  function streamSSE(url, payload, handlers) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(function (resp) {
      if (!resp.ok) {
        return resp.text().then(function (t) {
          throw new Error("HTTP " + resp.status + ": " + t);
        });
      }
      var reader = resp.body.getReader();
      var dec = new TextDecoder();
      var buf = "";
      function pump() {
        return reader.read().then(function (r) {
          if (r.done) return;
          buf += dec.decode(r.value, { stream: true });
          var chunks = buf.split("\n\n");
          buf = chunks.pop();
          chunks.forEach(function (raw) {
            var ev = null, data = "";
            raw.split("\n").forEach(function (line) {
              if (line.indexOf("event:") === 0) ev = line.slice(6).trim();
              else if (line.indexOf("data:") === 0) data += line.slice(5).trim();
            });
            if (ev && handlers[ev]) {
              var parsed = {};
              try { parsed = data ? JSON.parse(data) : {}; } catch (e) {}
              handlers[ev](parsed);
            }
          });
          return pump();
        });
      }
      return pump();
    });
  }

  /* ---- a turn (opening or reply) -------------------------------------- */
  function runTurn(url, payload) {
    var bubble = null;
    var acc = "";
    var toolEls = {};
    setStatus("…");
    input.disabled = true;
    sendBtn.disabled = true;

    var handlers = {
      session_created: function (d) { sessionId = d.session_id; },
      text_delta: function (d) {
        if (!bubble) {
          bubble = addMsg("the interviewer", "them");
          bubble.classList.add("cursor");
        }
        acc += d.text;
        bubble.innerHTML = mdBlock(acc);
        bubble.classList.add("cursor");
        scroll();
      },
      tool_use: function (d) {
        toolEls[d.id] = addTool(d.label || "consulting the wiki");
      },
      tool_done: function (d) {
        if (toolEls[d.id]) toolEls[d.id].classList.add("done");
      },
      turn_done: function (d) {
        if (bubble) bubble.classList.remove("cursor");
        ended = !!d.interview_ended;
        if (ended) {
          setStatus("the conversation has wrapped — writing your notes…");
        } else {
          setStatus(fmtTime(d.elapsed_seconds || 0, d.time_budget_seconds));
          input.disabled = false;
          sendBtn.disabled = false;
          input.focus();
        }
      },
      notes_writing: function () {
        setStatus("the conversation has wrapped — writing your notes…");
      },
      notes_written: function () { loadNotes(); },
      error: function (d) {
        if (bubble) bubble.classList.remove("cursor");
        showError(d.message || "something went wrong");
        input.disabled = false; sendBtn.disabled = false;
      },
      transcript_saved: function () {},
    };

    return streamSSE(url, payload, handlers).catch(function (e) {
      showError(e.message || String(e));
      input.disabled = false; sendBtn.disabled = false;
    });
  }

  function showError(msg) {
    var b = document.createElement("div");
    b.className = "banner-err";
    b.textContent = msg;
    transcript.appendChild(b);
    scroll();
  }

  /* ---- start ----------------------------------------------------------- */
  function gather() {
    var timeSel = $("f-time").value;
    var payload = {
      name: $("f-name").value.trim() || null,
      working_on: $("f-working").value.trim() || null,
      stuck_on: $("f-stuck").value.trim() || null,
      want_to_know: $("f-know").value.trim() || null,
    };
    if (timeSel !== "" && timeSel !== "0") {
      payload.time_available_minutes = parseFloat(timeSel);
    }
    return payload;
  }

  function begin(payload) {
    introBlock.classList.add("hidden");
    form.classList.add("hidden");
    chat.classList.add("active");
    runTurn("/api/sessions/start-stream", payload);
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    begin(gather());
  });
  $("skipBtn").addEventListener("click", function () { begin({}); });

  /* ---- send a reply ---------------------------------------------------- */
  function send() {
    var text = input.value.trim();
    if (!text || !sessionId || ended) return;
    addMsg("you", "me").innerHTML = mdBlock(text);
    input.value = "";
    input.style.height = "auto";
    runTurn("/api/sessions/" + sessionId + "/turn-stream", { text: text });
  }
  sendBtn.addEventListener("click", send);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  input.addEventListener("input", function () {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 176) + "px";
  });

  /* ---- end early ------------------------------------------------------- */
  endBtn.addEventListener("click", function () {
    if (!sessionId || ended) return;
    if (!confirm("End the conversation and write up the notes?")) return;
    ended = true;
    input.disabled = true; sendBtn.disabled = true;
    setStatus("writing your notes…");
    fetch("/api/sessions/" + sessionId + "/end", { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (d) { showNotes(d.notes_content || ""); })
      .catch(function (e) { showError(String(e)); });
  });

  /* ---- notes review ---------------------------------------------------- */
  function loadNotes() {
    if (!sessionId) return;
    fetch("/api/sessions/" + sessionId + "/notes")
      .then(function (r) { return r.json(); })
      .then(function (d) { showNotes(d.notes_content || ""); })
      .catch(function () {
        setTimeout(loadNotes, 1500); // reflector may still be writing
      });
  }
  function showNotes(content) {
    chat.classList.remove("active");
    notesStage.classList.add("active");
    notesEdit.value = content;
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  $("saveNotesBtn").addEventListener("click", function () {
    if (!sessionId) return;
    var btn = $("saveNotesBtn");
    btn.disabled = true;
    fetch("/api/sessions/" + sessionId + "/notes", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: notesEdit.value }),
    }).then(function (r) { return r.json(); })
      .then(function () {
        var f = $("savedFlag");
        f.style.display = "inline";
        setTimeout(function () { f.style.display = "none"; }, 2600);
      })
      .finally(function () { btn.disabled = false; });
  });
})();
