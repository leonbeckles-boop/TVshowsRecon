/* Optional: centered version of your login page container only.
 * If your current login.tsx already contains the form logic,
 * you can just wrap it with the same outer <main>/<div> to center and constrain width.
 */

import React from "react";

export default function LoginCenteredShell({ children }: { children: React.ReactNode }) {
  return (
    <main className="min-h-[calc(100vh-64px)] flex items-center justify-center p-4">
      <div className="w-full max-w-md rounded-2xl shadow-xl border border-gray-200 bg-white p-6">
        {children}
      </div>
    </main>
  );
}
