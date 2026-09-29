(function () {
  "use strict";

  function activateToast(toast) {
    if (toast.dataset.activated) return;
    toast.dataset.activated = "true";

    // Two rAFs so the initial (hidden) state is painted before the
    // visible class is added — otherwise the browser may coalesce both
    // states into one frame and skip the transition.
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        toast.classList.add("toast-visible");
      });
    });

    var dismiss = function () {
      if (toast.dataset.dismissing) return;
      toast.dataset.dismissing = "true";
      toast.classList.remove("toast-visible");
      toast.classList.add("toast-leaving");
      window.setTimeout(function () {
        toast.remove();
      }, 220);
    };

    var timer = window.setTimeout(dismiss, 4000);

    var button = toast.querySelector(".toast-dismiss");
    if (button) {
      button.addEventListener("click", function () {
        window.clearTimeout(timer);
        dismiss();
      });
    }
  }

  function initToasts() {
    document.querySelectorAll(".toast").forEach(activateToast);
  }

  function initHtmxToasts() {
    // Toasts injected via hx-swap-oob (dashboard/_toast_oob.html) arrive
    // outside the normal DOMContentLoaded pass. htmx:afterSwap also fires
    // once OOB swaps have settled, so rescan rather than rely on the exact
    // shape of the OOB event detail (which container/inserted-node it
    // points to differs by swap style).
    document.body.addEventListener("htmx:afterSwap", function () {
      document.querySelectorAll("#toast-container .toast").forEach(activateToast);
    });
  }

  function initMobileMenu() {
    var toggle = document.getElementById("mobile-menu-toggle");
    var close = document.getElementById("mobile-menu-close");
    var drawer = document.getElementById("mobile-drawer");
    var backdrop = document.getElementById("mobile-drawer-backdrop");
    if (!toggle || !drawer || !backdrop) return;

    var open = function () {
      drawer.classList.add("drawer-open");
      backdrop.classList.add("backdrop-visible");
      toggle.setAttribute("aria-expanded", "true");
      var firstLink = drawer.querySelector("a, button");
      if (firstLink) firstLink.focus();
      document.addEventListener("keydown", onKeydown);
    };

    var hide = function () {
      drawer.classList.remove("drawer-open");
      backdrop.classList.remove("backdrop-visible");
      toggle.setAttribute("aria-expanded", "false");
      toggle.focus();
      document.removeEventListener("keydown", onKeydown);
    };

    var onKeydown = function (event) {
      if (event.key === "Escape") hide();
    };

    toggle.addEventListener("click", open);
    if (close) close.addEventListener("click", hide);
    backdrop.addEventListener("click", hide);
  }

  function initCopyButtons() {
    var buttons = document.querySelectorAll("[data-copy-target]");
    if (!buttons.length) return;

    buttons.forEach(function (button) {
      var target = document.getElementById(button.dataset.copyTarget);
      var label = button.querySelector("[data-copy-label]");
      if (!target || !label) return;
      var originalText = label.textContent;

      button.addEventListener("click", function () {
        if (!navigator.clipboard) return;
        navigator.clipboard.writeText(target.innerText).then(function () {
          window.clearTimeout(button.dataset.copyTimer);
          label.textContent = "Copied ✓";
          var timer = window.setTimeout(function () {
            label.textContent = originalText;
          }, 1500);
          button.dataset.copyTimer = timer;
        });
      });
    });
  }

  function initFilterTabs() {
    // Delegated on document, not the nav itself: HTMX's outerHTML swap
    // replaces #submissions-panel (nav included) wholesale on every filter
    // click, which would silently kill a listener bound to the old node.
    document.addEventListener("click", function (event) {
      var link = event.target.closest("[data-filter-value]");
      if (!link) return;
      var nav = link.closest('nav[aria-label="Filter by status"]');
      if (!nav) return;
      nav.querySelectorAll("[data-filter-value]").forEach(function (tab) {
        var active = tab === link;
        tab.classList.toggle("tab-active", active);
        tab.classList.toggle("tab-inactive", !active);
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initToasts();
    initHtmxToasts();
    initMobileMenu();
    initCopyButtons();
    initFilterTabs();
  });
})();
