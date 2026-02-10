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

function useIsMobile(breakpoint: number = 768): boolean {
  const [isMobile, setIsMobile] = React.useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return window.innerWidth < breakpoint;
  });

  React.useEffect(() => {
    function handleResize() {
      setIsMobile(window.innerWidth < breakpoint);
    }
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [breakpoint]);

  return isMobile;
}

function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

const PageHeader: React.FC<PageHeaderProps> = ({ title, subtitle, centered }) => {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const isMobile = useIsMobile(768);

  const [mobileMenuOpen, setMobileMenuOpen] = React.useState(false);

  const handleAuthClick = async () => {
    if (user) {
      try {
        await logout?.();
      } catch (err) {
        console.error("Logout failed:", err);
      }
    } else {
      navigate("/login");
    }
    setMobileMenuOpen(false);
  };

  const handleNavClick = (to: string) => {
    navigate(to);
    setMobileMenuOpen(false);
  };

  const authLabel = user ? "Sign out" : "Sign in";

  return (
    <header className="fixed inset-x-0 top-0 z-50">
      {/* Top bar */}
      <div
        className="w-full border-b border-slate-800/70"
        style={{
          background:
            "radial-gradient(circle at top, rgba(2,6,23,0.98) 0%, rgba(2,6,23,0.98) 55%, rgba(2,6,23,0.98) 100%)",
          boxShadow: "0 18px 40px rgba(15,23,42,0.85)",
          backdropFilter: "blur(18px)",
        }}
      >
        <div className="w-full px-3 sm:px-5 lg:px-8 py-2.5">
          <div className="grid grid-cols-[auto,1fr,auto] items-center gap-3">
            {/* LEFT: logo (no extra text) */}
            <Link
              to="/"
              className="group inline-flex items-center"
              aria-label="WhatNext home"
              onClick={() => setMobileMenuOpen(false)}
            >
              <div className="relative">
                <div
                  className="pointer-events-none absolute -inset-4 rounded-2xl opacity-70 blur-2xl"
                  style={{
                    background:
                      "radial-gradient(circle at 25% 15%, rgba(56,189,248,0.85), transparent 60%)",
                  }}
                />

                {/*
                  Make the logo clear:
                  - rectangular container
                  - height-driven (width auto)
                  - no cropping (object-fit: contain)
                */}
                <div
                  className={cx(
                    "relative overflow-hidden rounded-xl border border-slate-700/60 bg-white",
                    "shadow-[0_0_18px_rgba(56,189,248,0.45)]",
                    "transition-transform duration-200 group-hover:scale-[1.02]"
                  )}
                  style={{
                    height: isMobile ? 38 : 52,
                    width: isMobile ? 65 : 90,
                  }}
                >
                  <img
                    src="/logo1.png"
                    alt="WhatNext"
                    style={{
                      width: "100%",
                      height: "100%",
                      objectFit: "contain",
                      display: "block",
                    }}
                  />
                </div>
              </div>
            </Link>

            {/* CENTER: title + subtitle */}
            <div
              className="px-2"
              style={{
                textAlign: "center",
                lineHeight: 1.15,
                maxWidth: centered ? 820 : 720,
                margin: "0 auto",
              }}
            >
              <h1
                className="m-0 font-extrabold tracking-wide text-slate-50"
                style={{
                  fontSize: isMobile ? 16 : 26,
                  textShadow:
                    "0 0 14px rgba(15,23,42,0.9), 0 0 26px rgba(56,189,248,0.55)",
                }}
              >
                {title}
              </h1>

              {!!subtitle && !isMobile && (
                <p className="mt-1 mb-0 text-[13px] text-slate-300">
                  {subtitle}
                </p>
              )}
            </div>

            {/* RIGHT: nav + auth */}
            {isMobile ? (
              <div className="flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={handleAuthClick}
                  className={cx(
                    "inline-flex items-center justify-center rounded-full text-xs font-semibold",
                    "border transition-colors",
                    user
                      ? "bg-white text-black border-slate-300"
                      : "bg-slate-950/60 text-slate-100 border-slate-700/70"
                  )}
                  style={{ padding: "7px 12px", whiteSpace: "nowrap" }}
                >
                  {authLabel}
                </button>

                <button
                  type="button"
                  onClick={() => setMobileMenuOpen((v) => !v)}
                  aria-label="Toggle navigation menu"
                  className={cx(
                    "inline-flex items-center justify-center rounded-full text-xs font-semibold",
                    "border border-slate-700/70 bg-slate-950/60 text-slate-100 transition-colors"
                  )}
                  style={{ padding: "7px 10px" }}
                >
                  {mobileMenuOpen ? "Close" : "Menu"}
                </button>
              </div>
            ) : (
              <div className="flex items-center justify-end gap-3">
                <nav className="flex items-center gap-2.5">
                  {NAV_LINKS.map((link) => {
                    const isActive = location.pathname === link.to;
                    return (
                      <Link
                        key={link.key}
                        to={link.to}
                        className={cx(
                          "inline-flex items-center justify-center rounded-full",
                          "px-5 py-2 text-[15px] font-semibold no-underline",
                          "border transition-all duration-200",
                          isActive
                            ? "bg-cyan-400/90 border-cyan-300 shadow-[0_0_18px_rgba(34,211,238,0.55)] text-slate-950"
                            : "bg-slate-950/45 border-cyan-300/70 text-slate-50 hover:bg-slate-900/60"
                        )}
                        style={{ whiteSpace: "nowrap" }}
                      >
                        {link.label}
                      </Link>
                    );
                  })}
                </nav>

                <button
                  type="button"
                  onClick={handleAuthClick}
                  className={cx(
                    "inline-flex items-center justify-center rounded-full",
                    "px-5 py-2 text-[15px] font-semibold border transition-colors",
                    user
                      ? "bg-white text-black border-slate-300"
                      : "bg-slate-950/45 text-slate-100 border-slate-700/70 hover:bg-slate-900/60"
                  )}
                  style={{ whiteSpace: "nowrap" }}
                >
                  {authLabel}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Mobile dropdown */}
      {isMobile && mobileMenuOpen && (
        <div
          className="border-b border-slate-800/70"
          style={{
            background:
              "linear-gradient(to bottom, rgba(2,6,23,0.98), rgba(2,6,23,0.96))",
            backdropFilter: "blur(18px)",
          }}
        >
          <nav className="flex flex-col gap-2 px-3 sm:px-5 py-3">
            {NAV_LINKS.map((link) => {
              const isActive = location.pathname === link.to;
              return (
                <button
                  key={link.key}
                  type="button"
                  onClick={() => handleNavClick(link.to)}
                  className={cx(
                    "w-full inline-flex items-center justify-between rounded-xl",
                    "px-4 py-2.5 text-sm font-semibold border transition-colors",
                    isActive
                      ? "bg-cyan-400/15 border-cyan-300/60 text-slate-50"
                      : "bg-slate-950/45 border-slate-700/70 text-slate-100"
                  )}
                >
                  <span>{link.label}</span>
                  {isActive && (
                    <span className="text-[11px] uppercase tracking-widest opacity-80">
                      Active
                    </span>
                  )}
                </button>
              );
            })}
          </nav>
        </div>
      )}
    </header>
  );
};

export default PageHeader;
