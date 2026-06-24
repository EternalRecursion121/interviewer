/* AFFINE wiki — small, no-dep progressive enhancements.
   - Client-side filter for big layer listings (filters visible rows; no
     network, no rerender). Degrades to a plain list with JS off.
   - "On this page" scroll-spy highlight.
   - Back-to-top button shows after you've scrolled a screenful. */
(function () {
  "use strict";

  // ---- layer filter ------------------------------------------------------
  var input = document.getElementById("layerFilter");
  if (input) {
    var empty = document.getElementById("layerFilterEmpty");
    var items = Array.prototype.slice.call(
      document.querySelectorAll(".layer-item")
    );
    var groups = Array.prototype.slice.call(
      document.querySelectorAll(".layer-group")
    );

    var apply = function () {
      var q = input.value.trim().toLowerCase();
      var shown = 0;
      items.forEach(function (li) {
        var hay = li.getAttribute("data-name") || "";
        var hit = q === "" || hay.indexOf(q) !== -1;
        li.hidden = !hit;
        if (hit) shown++;
      });
      // Hide a letter heading whose whole group filtered out.
      groups.forEach(function (g) {
        var any = g.querySelectorAll(".layer-item:not([hidden])").length;
        g.hidden = any === 0;
      });
      if (empty) empty.hidden = shown !== 0;
    };

    input.addEventListener("input", apply);
    // Esc clears the box.
    input.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        input.value = "";
        apply();
      }
    });
  }

  // ---- on-this-page scroll-spy ------------------------------------------
  var tocLinks = Array.prototype.slice.call(
    document.querySelectorAll(".toc-list a")
  );
  if (tocLinks.length && "IntersectionObserver" in window) {
    var byId = {};
    tocLinks.forEach(function (a) {
      var id = decodeURIComponent((a.getAttribute("href") || "").slice(1));
      if (id) byId[id] = a;
    });
    var headings = Object.keys(byId)
      .map(function (id) { return document.getElementById(id); })
      .filter(Boolean);

    var spy = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (en) {
          if (en.isIntersecting) {
            tocLinks.forEach(function (a) { a.classList.remove("active"); });
            var a = byId[en.target.id];
            if (a) a.classList.add("active");
          }
        });
      },
      { rootMargin: "0px 0px -72% 0px", threshold: 0 }
    );
    headings.forEach(function (h) { spy.observe(h); });
  }

  // ---- back to top -------------------------------------------------------
  var top = document.querySelector(".back-to-top");
  if (top) {
    var onScroll = function () {
      if (window.scrollY > window.innerHeight * 0.9) {
        top.classList.add("show");
      } else {
        top.classList.remove("show");
      }
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    top.addEventListener("click", function (e) {
      e.preventDefault();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }
})();
