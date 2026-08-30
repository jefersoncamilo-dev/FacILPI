/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: "#2563EB",
        primaryDeep: "#1E3A8A",
        primaryLight: "#DBEAFE",
        cian: "#06B6D4",
        bg: "#F8FAFC",
        surface: "#ffffff",
        textMain: "#0F172A",
        textMuted: "#64748B",
        success: "#10B981",
        warning: "#F59E0B",
        danger: "#DC2626",
        purple: "#7C3AED",
      },
      borderRadius: {
        card: "14px",
      },
      boxShadow: {
        card: "0 4px 20px rgba(37,99,235,0.08)",
        cardHover: "0 8px 28px rgba(37,99,235,0.12)",
      }
    },
  },
  plugins: [],
}
