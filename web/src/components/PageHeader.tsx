import React from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";

export type PageHeaderProps = {
  title: string;
  subtitle?: string;
  centered?: boolean;
};

type NavLinkDef = {
  to: string;
  label: string;
  key: string;
};

const NAV_LINKS: NavLinkDef[] = [
  { to: "/discover", label: "Discover", key: "discover" },
  { to: "/search", label: "Search", key: "search" },
  { to: "/favorites", label: "Favourites", key: "favourites" },
  { to: "/recs", label: "Recommendations", key: "recs" },
  { to: "/wrapped", label: "Profile", key: "wrapped" },
];

function useIsMobile(breakpoint = 768): boolean {
  const [isMobile, setIsMobile] = React.useState(() => {
    if (typeof window === "undefined") return false;
    return window.innerWidth < breakpoint;
  });

  React.useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < breakpoint);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [breakpoint]);

  return isMobile;
}

const PageHeader: React.FC<PageHeaderProps> = ({ title, subtitle, centered }) => {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  const isMobile = useIsMobile(900);
  const [mobileOpen, setMobileOpen] = React.useState(false);

  const authLabel = user ? "Sign out" : "Sign in";

  const handleAuthClick = async () => {
    try {
      if (user) await logout?.();
      else navigate("/login");
    } catch (err) {
      console.error("Auth action failed:", err);
    } finally {
      setMobileOpen(false);
    }
  };

  const handleNavClick = (to: string) => {
    navigate(to);
    setMobileOpen(false);
  };

  // If you keep the image in /public/logo1.png:
  const logoSrc = "/logo1.png";

  // If you keep the image in src/assets, do this instead:
  // import logoSrc from "../assets/logo1.png";

  return (
    <header className="fixed inset-x-0 top-0 z-50 border-b border-slate-800/60 bg-slate-950/85 backdrop-blur-xl">
      <div className="mx-auto w-full max-w-7xl px-4 md:px-6">
        <div className="flex h-16 items-center gap-4 md:h-[72px]">
          {/* LEFT: Logo */}
          <Link to="/discover" className="flex items-center gap-3 shrink-0">
            <div className="relative">
              <div className="pointer-events-none absolute -inset-3 rounded-xl opacity-60 blur-2xl bg-cyan-400/40" />
              <div className="relative flex items-center justify-center rounded-xl border border-slate-700/60 bg-slate-950 shadow-[0_0_18px_rgba(56,189,248,0.25)]">
                {/* Responsive logo box: bigger on desktop so text in logo is readable */}
                <div className="h-10 w-[120px] md:h-12 md:w-[160px] px-2 py-1">
                  <img
                    src={logoSrc}
                    alt="WhatNext"
                    className="h-full w-full object-contain"
                    draggable={false}
                  />
                </div>
              </div>
            </div>
          </Link>

          {/* CENTER: Title */}
          <div
            className={[
              "flex-1",
              centered ? "text-center" : "text-center md:text-left",
            ].join(" ")}
          >
            <div className="leading-tight">
              <h1 className="text-base font-extrabold tracking-wide text-slate-50 md:text-xl">
                {title}
              </h1>
              {subtitle && (
                <p className="hidden text-xs text-slate-300/90 md:block">
                  {subtitle}
                </p>
              )}
            </div>
          </div>

          {/* RIGHT: Nav + Auth */}
          {isMobile ? (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleAuthClick}
                className="rounded-full border border-slate-700/70 bg-slate-900 px-3 py-1.5 text-xs font-semibold text-slate-100 hover:bg-slate-800"
              >
                {authLabel}
              </button>

              <button
                type="button"
                onClick={() => setMobileOpen((v) => !v)}
                className="rounded-full border border-slate-700/70 bg-slate-900 px-3 py-1.5 text-xs font-semibold text-slate-100 hover:bg-slate-800"
                aria-label="Toggle navigation"
              >
                {mobileOpen ? "Close" : "Menu"}
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-3">
              <nav className="flex items-center gap-2">
                {NAV_LINKS.map((link) => {
                  const isActive = location.pathname === link.to;
                  return (
                    <Link
                      key={link.key}
                      to={link.to}
                      className={[
                        "rounded-full px-4 py-2 text-sm font-semibold transition",
                        "border",
                        isActive
                          ? "bg-cyan-400/15 text-cyan-200 border-cyan-300/60 shadow-[0_0_16px_rgba(34,211,238,0.25)]"
                          : "bg-slate-900/60 text-slate-100 border-slate-700/70 hover:bg-slate-800/70",
                      ].join(" ")}
                    >
                      {link.label}
                    </Link>
                  );
                })}
              </nav>

              <button
                type="button"
                onClick={handleAuthClick}
                className={[
                  "rounded-full px-4 py-2 text-sm font-semibold transition border",
                  user
                    ? "bg-white text-slate-900 border-slate-200 hover:bg-slate-100"
                    : "bg-slate-900/60 text-slate-100 border-slate-700/70 hover:bg-slate-800/70",
                ].join(" ")}
              >
                {authLabel}
              </button>
            </div>
          )}
        </div>

        {/* Mobile dropdown */}
        {isMobile && mobileOpen && (
          <div className="pb-3">
            <div className="mt-2 grid gap-2 rounded-2xl border border-slate-800/70 bg-slate-950/90 p-3">
              {NAV_LINKS.map((link) => {
                const isActive = location.pathname === link.to;
                return (
                  <button
                    key={link.key}
                    type="button"
                    onClick={() => handleNavClick(link.to)}
                    className={[
                      "w-full rounded-xl px-3 py-2 text-left text-sm font-semibold border transition",
                      isActive
                        ? "bg-cyan-400/15 text-cyan-200 border-cyan-300/60"
                        : "bg-slate-900/60 text-slate-100 border-slate-700/70 hover:bg-slate-800/70",
                    ].join(" ")}
                  >
                    {link.label}
                  </button>
                );
              })}
              <button
                type="button"
                onClick={handleAuthClick}
                className="w-full rounded-xl px-3 py-2 text-left text-sm font-semibold border border-slate-700/70 bg-slate-900/60 text-slate-100 hover:bg-slate-800/70"
              >
                {authLabel}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Spacer so content below doesn’t hide under fixed header */}
      <div className="h-16 md:h-[72px]" />
    </header>
  );
};

export default PageHeader;
