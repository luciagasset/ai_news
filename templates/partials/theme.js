// Modo claro u oscuro: el elegido con el botón (si se guardó) o el del sistema
(() => {
  const KEY = "ai-news-theme";
  const root = document.documentElement;
  const system = matchMedia("(prefers-color-scheme: dark)");
  const saved = () => { let t = null; try { t = localStorage.getItem(KEY); } catch {} return t === "light" || t === "dark" ? t : null; };
  const apply = () => {
    const t = saved();
    if (t) root.dataset.theme = t; else delete root.dataset.theme;
    const mode = t || (system.matches ? "dark" : "light");
    root.dataset.mode = mode;
    // Color de la barra del navegador y de la app instalada
    document.querySelectorAll('meta[name="theme-color"]').forEach(m => {
      if (!m.dataset.media) m.dataset.media = m.media || "";
      m.media = t ? "" : m.dataset.media;
      if (t) m.content = t === "dark" ? "#000000" : "#f2f2f7";
      else m.content = m.dataset.media.includes("dark") ? "#000000" : "#f2f2f7";
    });
    document.querySelectorAll("[data-theme-toggle]").forEach(b => {
      const en = root.lang === "en";
      b.setAttribute("aria-label", mode === "dark" ? (en ? "Switch to light mode" : "Cambiar a modo día")
                                                   : (en ? "Switch to dark mode" : "Cambiar a modo noche"));
    });
  };
  apply();
  system.addEventListener?.("change", apply);
  document.addEventListener("click", e => {
    const b = e.target.closest?.("[data-theme-toggle]");
    if (!b) return;
    e.stopPropagation();
    try { localStorage.setItem(KEY, root.dataset.mode === "dark" ? "light" : "dark"); } catch {}
    apply();
  }, true);
  addEventListener("DOMContentLoaded", apply);
  // La etiqueta del botón sigue al idioma
  new MutationObserver(apply).observe(root, { attributes: true, attributeFilter: ["lang"] });
})();
