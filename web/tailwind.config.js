/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./index.html",
    "./src/**/*.{ts,tsx,js,jsx}",
  ],
  safelist: [
    // grid breakpoints we rely on
    "grid",
    "grid-cols-2",
    "sm:grid-cols-4",
    "md:grid-cols-5",
    "lg:grid-cols-6",
    "xl:grid-cols-7",
    "2xl:grid-cols-8",
    "gap-4",
    // container helpers we used
    "w-full",
    "px-4",
  ],
  theme: { extend: {} },
  plugins: [],
};
