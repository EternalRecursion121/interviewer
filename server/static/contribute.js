/* Contribute — file/folder upload into unprocessed/uploads/. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var picked = [];               // [{file, rel}]
  var form = $("up"), drop = $("drop");
  var listEl = $("upList"), note = $("upNote"), btn = $("upBtn");
  var result = $("upResult");

  function fmtBytes(n) {
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
    return (n / 1048576).toFixed(1) + " MB";
  }

  function add(files) {
    for (var i = 0; i < files.length; i++) {
      var f = files[i];
      picked.push({ file: f, rel: f.webkitRelativePath || f.name });
    }
    render();
  }
  function render() {
    listEl.innerHTML = "";
    var total = 0;
    picked.forEach(function (p, idx) {
      total += p.file.size;
      var li = document.createElement("li");
      var name = document.createElement("span");
      name.className = "up-name";
      name.textContent = p.rel;
      var sz = document.createElement("span");
      sz.className = "up-sz";
      sz.textContent = fmtBytes(p.file.size);
      var x = document.createElement("button");
      x.type = "button"; x.className = "up-x"; x.textContent = "✕";
      x.onclick = function () { picked.splice(idx, 1); render(); };
      li.appendChild(name); li.appendChild(sz); li.appendChild(x);
      listEl.appendChild(li);
    });
    if (picked.length) {
      note.textContent = picked.length + " item(s) · " + fmtBytes(total);
      btn.disabled = false;
    } else {
      note.textContent = "nothing selected yet";
      btn.disabled = true;
    }
  }

  $("u-files").addEventListener("change", function (e) { add(e.target.files); e.target.value = ""; });
  $("u-dir").addEventListener("change", function (e) { add(e.target.files); e.target.value = ""; });

  ["dragenter", "dragover"].forEach(function (ev) {
    drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add("over"); });
  });
  ["dragleave", "drop"].forEach(function (ev) {
    drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove("over"); });
  });
  drop.addEventListener("drop", function (e) {
    if (e.dataTransfer && e.dataTransfer.files) add(e.dataTransfer.files);
  });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    if (!picked.length) return;
    btn.disabled = true;
    var prev = btn.textContent;
    btn.textContent = "sending…";
    var fd = new FormData();
    fd.append("label", $("u-label").value.trim());
    picked.forEach(function (p) {
      fd.append("files", p.file, p.file.name);
      fd.append("rel_paths", p.rel);
    });
    fetch("/api/upload", { method: "POST", body: fd })
      .then(function (r) { return r.json().then(function (j) {
        if (!r.ok) throw new Error(j.detail || ("HTTP " + r.status)); return j; }); })
      .then(function (j) {
        form.style.display = "none";
        result.style.display = "block";
        result.innerHTML =
          '<p class="iv-kicker">filed</p>' +
          "<h1 style=\"font-family:var(--serif);color:var(--aubergine);font-size:2rem;margin:.4rem 0 1rem\">" +
          j.file_count + " item(s) → <em>unprocessed/uploads/</em></h1>" +
          '<p class="notes-intro">Batch <code>' + j.batch + "</code>. It'll be read and folded into the wiki on the next integrate pass.</p>" +
          '<div class="notes-foot"><a class="btn" href="/contribute">contribute more</a>' +
          '<a class="btn btn-ghost" href="/wiki">back to the wiki →</a></div>';
        window.scrollTo({ top: 0, behavior: "smooth" });
      })
      .catch(function (err) {
        btn.disabled = false; btn.textContent = prev;
        var b = document.createElement("div");
        b.className = "banner-err";
        b.textContent = "upload failed: " + (err.message || err);
        form.insertBefore(b, form.firstChild);
      });
  });
})();
