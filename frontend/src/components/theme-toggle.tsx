"use client";

import { useEffect, useSyncExternalStore } from "react";
import { Moon, Sun, Monitor } from "lucide-react";

type Theme = "light" | "dark" | "system";
let fallbackTheme: Theme = "system";
function getTheme(): Theme {
  try {
    const value = localStorage.getItem("salonbook:theme");
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return fallbackTheme;
  }
}
function subscribe(callback: () => void) {
  window.addEventListener("storage", callback);
  window.addEventListener("salonbook:theme", callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener("salonbook:theme", callback);
  };
}
const names = { light: "روشن", dark: "تیره", system: "هماهنگ با دستگاه" };
export function ThemeToggle() {
  const theme = useSyncExternalStore(
    subscribe,
    getTheme,
    () => "system" as Theme,
  );
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  function change() {
    const next =
      theme === "system" ? "light" : theme === "light" ? "dark" : "system";
    fallbackTheme = next;
    try {
      localStorage.setItem("salonbook:theme", next);
    } catch {
      /* Keep this tab's preference usable when browser storage is unavailable. */
    }
    window.dispatchEvent(new Event("salonbook:theme"));
  }
  const Icon = theme === "light" ? Sun : theme === "dark" ? Moon : Monitor;
  return (
    <button
      className="icon-button"
      type="button"
      onClick={change}
      aria-label={`تغییر پوسته؛ اکنون ${names[theme]}`}
      title={`پوستهٔ ${names[theme]}`}
    >
      <Icon size={19} aria-hidden="true" />
    </button>
  );
}
