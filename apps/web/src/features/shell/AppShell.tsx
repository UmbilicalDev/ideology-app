import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";

import type { FeedbackApi } from "@ideology-app/core";

import { BallotIcon, BookIcon, ChipIcon, CloseIcon, HomeIcon, MenuIcon } from "../../ui/icons";
import { APP_NAME } from "../common/BrandTitle";
import { ProductLogo } from "../common/ProductLogo";
import { FeedbackButton } from "../feedback/FeedbackButton";
import { HOME_PATH, METHODOLOGY_PATH, SHARED_RESULTS_PATH, TRANSPARENCY_PATH } from "../paths";

export const APP_TAGLINE = "Comparador de programas electorales";

const NAV_ITEMS: readonly { readonly to: string; readonly label: string; readonly icon: ReactNode }[] = [
  { to: HOME_PATH, label: "Elecciones", icon: <BallotIcon /> },
  { to: METHODOLOGY_PATH, label: "Cómo funciona", icon: <BookIcon /> },
  { to: TRANSPARENCY_PATH, label: "Transparencia IA", icon: <ChipIcon /> },
];

// The section name in the top bar; the first NAV_ITEMS entry is the home.
const SECTION_NAMES: Readonly<Record<string, string>> = {
  [HOME_PATH]: "Elecciones",
  [METHODOLOGY_PATH]: "Cómo funciona",
  [TRANSPARENCY_PATH]: "Transparencia IA",
  [SHARED_RESULTS_PATH]: "Resultado compartido",
};

// Below this width the sidebar is a drawer (DESIGN.md "App shell"); keep in
// sync with the media query in components.css.
const DRAWER_QUERY = "(max-width: 767.98px)";

/**
 * The web-app layout of every Voter page except the Questionnaire (DESIGN.md
 * "App shell"): a sidebar with the brand, the three sections and `Danos tu
 * opinión`, and a canvas with a top bar. Below 768px the sidebar is a modal
 * drawer opened from the top bar.
 */
export function AppShell({ api }: { readonly api: FeedbackApi }) {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const sidebarRef = useRef<HTMLElement>(null);
  // Set by close(): the menu button gets focus back once the canvas is no
  // longer inert (it cannot take focus while it is).
  const restoreFocus = useRef(false);

  // A navigation closes the drawer. The links also close it on click, in the
  // same update as the navigation, so the canvas is no longer inert when the
  // new page focuses its heading (and tapping the current section closes it);
  // this effect covers any other navigation.
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  // Growing past the drawer width closes it, so the canvas is never inert.
  useEffect(() => {
    const query = window.matchMedia?.(DRAWER_QUERY);
    if (query === undefined) {
      return;
    }
    const onChange = () => {
      if (!query.matches) setOpen(false);
    };
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    if (!open) {
      if (restoreFocus.current) {
        restoreFocus.current = false;
        menuButtonRef.current?.focus();
      }
      return;
    }
    sidebarRef.current?.querySelector<HTMLElement>("a, button")?.focus();
    function onKeyDown(event: KeyboardEvent) {
      // The feedback dialog handles its own Escape; the drawer stays open
      // under it (a hidden drawer would hide the dialog too).
      if (event.key !== "Escape" || document.querySelector("dialog[open]") !== null) {
        return;
      }
      close();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  function close() {
    restoreFocus.current = true;
    setOpen(false);
  }

  // A link to the current page does not navigate, so no page takes focus:
  // it goes back to the menu button as on any other close.
  function closeFor(to: string) {
    if (to === pathname) {
      close();
    } else {
      setOpen(false);
    }
  }

  const section = SECTION_NAMES[pathname];

  return (
    <div className="app-shell" data-nav-open={open}>
      <div className="app-shell__scrim" aria-hidden="true" onClick={close} />
      <aside
        id="app-sidebar"
        className="sidebar"
        aria-label="Menú principal"
        ref={sidebarRef}
      >
        <div className="sidebar__top">
          <div className="sidebar__brand-row">
            <Link className="sidebar__brand" to={HOME_PATH} onClick={() => closeFor(HOME_PATH)}>
              <ProductLogo className="sidebar__logo" size={36} />
              <span>{APP_NAME}</span>
            </Link>
            <button
              type="button"
              className="icon-button sidebar__close"
              aria-label="Cerrar menú"
              onClick={close}
            >
              <CloseIcon />
            </button>
          </div>
          <p className="sidebar__tagline">{APP_TAGLINE}</p>
          <nav aria-label="Secciones">
            <ul className="sidebar-nav">
              {/* Only on the shared result (the end screen's focus bar has
                  `Salir`); a plain link, so it is never shown as the current
                  section next to `Elecciones`. */}
              {pathname !== SHARED_RESULTS_PATH ? null : (
                <li>
                  <Link className="sidebar-nav__link" to={HOME_PATH} onClick={() => setOpen(false)}>
                    <HomeIcon />
                    <span>Ir al inicio</span>
                  </Link>
                </li>
              )}
              {NAV_ITEMS.map((item) => (
                <li key={item.to}>
                  <NavLink
                    className="sidebar-nav__link"
                    to={item.to}
                    end
                    onClick={() => closeFor(item.to)}
                  >
                    {item.icon}
                    <span>{item.label}</span>
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
        </div>
        <div className="sidebar__footer">
          <FeedbackButton api={api} origin="landing" />
        </div>
      </aside>
      <div className="app-shell__canvas" inert={open}>
        <header className="topbar">
          <button
            type="button"
            className="icon-button topbar__menu"
            aria-label="Abrir menú"
            aria-expanded={open}
            aria-controls="app-sidebar"
            ref={menuButtonRef}
            onClick={() => setOpen(true)}
          >
            <MenuIcon />
          </button>
          <p className="topbar__crumb">
            <Link className="topbar__crumb-root" to={HOME_PATH} aria-label={`${APP_NAME}, ir al inicio`}>
              {APP_NAME}
            </Link>
            {section === undefined ? null : (
              <>
                <span className="topbar__crumb-sep" aria-hidden="true">
                  /
                </span>
                <span>{section}</span>
              </>
            )}
          </p>
        </header>
        <div className="app-shell__content">
          <Outlet />
        </div>
        <footer className="app-footer">
          <p>
            {APP_NAME} no es una recomendación de voto. Las afirmaciones y las posiciones las genera
            una inteligencia artificial y pueden contener errores.
          </p>
        </footer>
      </div>
    </div>
  );
}
