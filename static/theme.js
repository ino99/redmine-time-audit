const THEME_KEY = "redmine-time-audit-theme";

function preferredTheme() {
  const stored = localStorage.getItem(THEME_KEY);
  if (stored === "dark" || stored === "light") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const button = document.getElementById("themeToggleButton");
  if (button) {
    button.textContent = theme === "dark" ? "ライト" : "ダーク";
      button.setAttribute("aria-label", theme === "dark" ? "ライトモードに切り替え" : "ダークモードに切り替え");
  }
  document.dispatchEvent(new CustomEvent("themechange", { detail: { theme } }));
}

function toggleTheme() {
  const nextTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  localStorage.setItem(THEME_KEY, nextTheme);
  applyTheme(nextTheme);
}

applyTheme(preferredTheme());

document.addEventListener("DOMContentLoaded", () => {
  applyTheme(preferredTheme());
  const button = document.getElementById("themeToggleButton");
  if (button) {
    button.addEventListener("click", toggleTheme);
  }
});
