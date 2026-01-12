import React from "react";

type OnboardingModalProps = {
  open: boolean;
  onClose: () => void;
};

const OnboardingModal: React.FC<OnboardingModalProps> = ({ open, onClose }) => {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center px-4">
      {/* Dimmed background */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal content */}
      <div className="relative w-full max-w-lg rounded-3xl border border-sky-400/70 bg-slate-950/95 px-6 py-6 sm:px-8 sm:py-7 shadow-2xl shadow-sky-900/60">
        <h2 className="mb-2 text-xl font-extrabold tracking-wide text-sky-100 sm:text-2xl">
          Welcome to WhatNext
        </h2>

        <p className="mb-3 text-sm text-slate-200 sm:text-base">
          We&apos;ll help you decide what to watch next using:
        </p>

        <ul className="mb-5 mt-1 list-disc list-inside space-y-1.5 text-xs text-slate-300 sm:text-sm">
          <li>
            <span className="font-semibold text-sky-200">Discover</span> – hand-picked,
            highly rated shows.
          </li>
          <li>
            <span className="font-semibold text-sky-200">Search</span> – look up any show
            and add it to your favourites.
          </li>
          <li>
            <span className="font-semibold text-sky-200">Favourites &amp; Ratings</span> –
            tell us what you like.
          </li>
          <li>
            <span className="font-semibold text-sky-200">Recommendations</span> –
            personalised picks based on your taste.
          </li>
        </ul>

        <p className="mb-5 text-xs text-slate-400 sm:text-[13px]">
          You can always change your favourites and ratings later – the
          recommendations will update automatically.
        </p>

        <div className="flex justify-end gap-3">
          {/* If you ever want a second button, add it here */}
          <button
            type="button"
            onClick={onClose}
            className="inline-flex items-center justify-center rounded-full border border-sky-400 bg-sky-400 px-5 py-2 text-sm font-semibold text-slate-950 shadow-lg shadow-sky-900/70 transition hover:bg-sky-300"
          >
            Got it
          </button>
        </div>
      </div>
    </div>
  );
};

export default OnboardingModal;
