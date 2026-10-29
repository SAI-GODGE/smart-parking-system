/* Smart Parking Management System - shared front-end behaviour.
 *
 * Everything here is progressive enhancement: the pages work without JS,
 * they just refresh less often and require a click on a named slot.
 */
(function () {
  "use strict";

  var CONFIG = window.SLOTS_CONFIG || {};
  var noticeTimer = null;

  /* ------------------------------------------------------------------ */
  /* Prevent accidental double submissions                              */
  /* ------------------------------------------------------------------ */
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) return;

    if (form.matches("[data-busy-form], #confirmForm")) {
      var button = form.querySelector('button[type="submit"]:not([disabled])');
      if (button) {
        button.disabled = true;
        button.dataset.originalText = button.dataset.originalText || button.innerHTML;
        button.innerHTML = '<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Please wait...';
      }
      window.setTimeout(function () {
        if (!button) return;
        button.disabled = false;
        button.innerHTML = button.dataset.originalText || button.innerHTML;
      }, 6000);
    }

    /* Bootstrap client-side validation styling */
    if (form.classList.contains("needs-validation")) {
      if (!form.checkValidity()) {
        event.preventDefault();
        event.stopPropagation();
      }
      form.classList.add("was-validated");
    }
  });

  /* ------------------------------------------------------------------ */
  /* Copy-to-clipboard buttons (data-copy="#selector")                  */
  /* ------------------------------------------------------------------ */
  document.addEventListener("click", function (event) {
    var btn = event.target.closest("[data-copy]");
    if (!btn) return;
    var target = document.querySelector(btn.getAttribute("data-copy"));
    if (!target) return;
    var text = target.textContent.trim();
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        var old = btn.innerHTML;
        btn.innerHTML = '<i class="bi bi-check2 me-1"></i>Copied';
        window.setTimeout(function () { btn.innerHTML = old; }, 1500);
      });
    }
  });

  /* ------------------------------------------------------------------ */
  /* Parking grid: filters, selection, live refresh                     */
  /* ------------------------------------------------------------------ */
  function showNotice(message, kind) {
    var notice = document.getElementById("bayNotice");
    if (!notice) return;
    notice.textContent = message;
    notice.className = "alert mt-3 mb-0 " + (kind === "info" ? "alert-info" : "alert-warning");
    notice.classList.remove("d-none");
    if (noticeTimer) window.clearTimeout(noticeTimer);
    noticeTimer = window.setTimeout(function () {
      notice.classList.add("d-none");
    }, 5000);
  }

  function applyFilters() {
    var floorSelect = document.getElementById("floorFilter");
    var zoneSelect = document.getElementById("zoneFilter");
    if (!floorSelect && !zoneSelect) return;
    var floor = floorSelect ? floorSelect.value : "";
    var zone = zoneSelect ? zoneSelect.value : "";
    document.querySelectorAll(".bay-tile").forEach(function (tile) {
      var ok = (!floor || tile.dataset.floor === floor) && (!zone || tile.dataset.zone === zone);
      tile.style.display = ok ? "" : "none";
    });
    /* Hide floor headings with no visible tiles */
    document.querySelectorAll(".bay-grid").forEach(function (grid) {
      var visible = Array.prototype.some.call(grid.children, function (child) {
        return child.style.display !== "none";
      });
      grid.style.display = visible ? "" : "none";
      var heading = grid.previousElementSibling;
      if (heading && heading.classList.contains("bay-floor-heading")) {
        heading.style.display = visible ? "" : "none";
      }
    });
  }

  function selectBay(tile, options) {
    options = options || {};
    if (!tile || tile.dataset.bookable !== "true") return false;

    document.querySelectorAll(".bay-tile.selected").forEach(function (t) {
      t.classList.remove("selected");
    });
    tile.classList.add("selected");

    var bayId = document.getElementById("bayIdInput");
    var label = document.getElementById("selectedLabel");
    var confirmBtn = document.getElementById("confirmBtn");
    if (bayId) bayId.value = tile.dataset.bayId;
    if (label) label.textContent = "space " + tile.dataset.label;
    if (confirmBtn) confirmBtn.disabled = false;

    if (options.focusForm) {
      var reg = document.getElementById("vehicle_registration");
      if (reg) {
        reg.focus({ preventScroll: false });
      }
      tile.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    return true;
  }

  function initGrid() {
    var wrap = document.getElementById("bayGridWrap");
    if (!wrap) return;

    wrap.addEventListener("click", function (event) {
      var tile = event.target.closest(".bay-tile");
      if (!tile) return;
      if (tile.dataset.bookable === "true") {
        selectBay(tile, { focusForm: true });
      } else {
        showNotice(CONFIG.takenMessage || "That space is not available. Please pick a green one.");
      }
    });

    wrap.addEventListener("keydown", function (event) {
      if (event.key !== "Enter" && event.key !== " ") return;
      var tile = event.target.closest(".bay-tile");
      if (!tile) return;
      event.preventDefault();
      if (tile.dataset.bookable === "true") {
        selectBay(tile, { focusForm: true });
      } else {
        showNotice(CONFIG.takenMessage || "That space is not available. Please pick a green one.");
      }
    });

    var recBtn = document.getElementById("chooseRecommended");
    if (recBtn) {
      recBtn.addEventListener("click", function () {
        var tile = wrap.querySelector('.bay-tile[data-bay-id="' + recBtn.dataset.bayId + '"]');
        if (tile) {
          selectBay(tile, { focusForm: true });
          showNotice(
            "Space " + tile.dataset.label + " selected (recommended for you).",
            "info"
          );
        }
      });
    }

    var floorSelect = document.getElementById("floorFilter");
    var zoneSelect = document.getElementById("zoneFilter");
    if (floorSelect) floorSelect.addEventListener("change", applyFilters);
    if (zoneSelect) zoneSelect.addEventListener("change", applyFilters);
    applyFilters();
  }

  function updateTile(tile, bay) {
    if (tile.dataset.status !== bay.status || tile.dataset.bookable !== String(bay.bookable)) {
      tile.classList.remove(
        "status-vacant", "status-reserved", "status-occupied", "status-maintenance",
        "is-bookable", "is-blocked"
      );
      tile.classList.add("status-" + bay.status, bay.bookable ? "is-bookable" : "is-blocked");
      tile.dataset.status = bay.status;
      tile.dataset.bookable = String(bay.bookable);
      var statusText = tile.querySelector(".bay-status-text");
      var shortLabels = { vacant: "Free", reserved: "Held", occupied: "Taken", maintenance: "Closed" };
      if (statusText) statusText.textContent = shortLabels[bay.status] || bay.status;
      tile.classList.add("just-updated");
      window.setTimeout(function () { tile.classList.remove("just-updated"); }, 700);
    }
  }

  function refreshAvailability() {
    var wrap = document.getElementById("bayGridWrap");
    if (!wrap || !wrap.dataset.refreshUrl) return;

    fetch(wrap.dataset.refreshUrl, { headers: { "Accept": "application/json" } })
      .then(function (response) {
        if (!response.ok) throw new Error("bad response");
        return response.json();
      })
      .then(function (data) {
        var tiles = {};
        wrap.querySelectorAll(".bay-tile").forEach(function (tile) {
          tiles[tile.dataset.bayId] = tile;
        });
        (data.bays || []).forEach(function (bay) {
          var tile = tiles[String(bay.id)];
          if (tile) updateTile(tile, bay);
        });

        /* Update visible statistics */
        if (data.counts) {
          Object.keys(data.counts).forEach(function (key) {
            var el = document.querySelector('[data-stat="' + key + '"]');
            if (el) el.textContent = data.counts[key];
          });
        }
        var freeCount = document.getElementById("freeCount");
        if (freeCount && typeof data.free_count === "number") {
          freeCount.textContent = data.free_count;
        }

        /* Selection safety: drop the selection if the bay is no longer free */
        var selected = wrap.querySelector(".bay-tile.selected");
        if (selected && selected.dataset.bookable !== "true") {
          selectBay(null);
          selected.classList.remove("selected");
          var bayId = document.getElementById("bayIdInput");
          var label = document.getElementById("selectedLabel");
          var confirmBtn = document.getElementById("confirmBtn");
          if (bayId) bayId.value = "";
          if (label) label.textContent = "no space yet";
          if (confirmBtn) confirmBtn.disabled = true;
          showNotice("The space you selected was just taken. Please choose another free one.");
        }

        var indicator = document.getElementById("refreshIndicator");
        if (indicator) {
          indicator.innerHTML = '<i class="bi bi-arrow-repeat me-1"></i>Updated ' +
            new Date().toLocaleTimeString();
        }
      })
      .catch(function () {
        /* Network hiccup - the next interval will try again. */
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initGrid();
    var wrap = document.getElementById("bayGridWrap");
    if (wrap && wrap.dataset.refreshUrl) {
      var interval = parseInt(CONFIG.refreshInterval || 10000, 10);
      window.setInterval(refreshAvailability, interval);
      window.setTimeout(refreshAvailability, 1500);
    }
  });
})();
