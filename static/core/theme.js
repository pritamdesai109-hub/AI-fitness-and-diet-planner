(function () {
  var root = document.documentElement;
  var controls = document.querySelectorAll("[data-theme-toggle]");

  function applyTheme(theme) {
    var isDark = theme === "dark";
    root.setAttribute("data-theme", isDark ? "dark" : "light");
    document.querySelectorAll("[data-theme-toggle]").forEach(function (control) {
      var label = control.querySelector(".theme-toggle-label");
      var icon = control.querySelector(".theme-icon");
      var nextMode = isDark ? "light" : "dark";
      control.setAttribute("aria-label", "Switch to " + nextMode + " theme");
      control.setAttribute("title", "Switch to " + nextMode + " theme");
      if (label) {
        label.textContent = isDark ? "Light mode" : "Dark mode";
      }
      if (icon) {
        icon.textContent = isDark ? "☼" : "◐";
      }
    });
    document.querySelector('meta[name="theme-color"]').setAttribute(
      "content",
      isDark ? "#181c19" : "#fbf8f2"
    );
  }

  var preferredTheme = "light";
  try {
    var savedTheme = window.localStorage.getItem("ai-fitness-theme");
    if (savedTheme === "light" || savedTheme === "dark") {
      preferredTheme = savedTheme;
    }
  } catch (error) {
    console.warn("Theme preference could not be read from local storage.", error);
  }
  applyTheme(preferredTheme);

  controls.forEach(function (control) {
    control.addEventListener("click", function () {
      var nextTheme = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      applyTheme(nextTheme);
      try {
        window.localStorage.setItem("ai-fitness-theme", nextTheme);
      } catch (error) {
        console.warn("Theme preference could not be saved to local storage.", error);
      }
    });
  });
})();
