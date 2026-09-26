import animate from "tailwindcss-animate"

// UX-01 (#83): tokens da identidade FacILPI (Haze Esmeralda). As cores vivem
// como variaveis HSL em index.css, no padrao shadcn/ui; aqui so as expomos.
const token = (name) => `hsl(var(--${name}) / <alpha-value>)`

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        border: token("border"),
        input: token("input"),
        ring: token("ring"),
        background: token("background"),
        foreground: token("foreground"),
        primary: {
          DEFAULT: token("primary"),
          foreground: token("primary-foreground"),
        },
        secondary: {
          DEFAULT: token("secondary"),
          foreground: token("secondary-foreground"),
        },
        muted: {
          DEFAULT: token("muted"),
          foreground: token("muted-foreground"),
        },
        accent: {
          DEFAULT: token("accent"),
          foreground: token("accent-foreground"),
        },
        destructive: {
          DEFAULT: token("destructive"),
          foreground: token("destructive-foreground"),
        },
        card: {
          DEFAULT: token("card"),
          foreground: token("card-foreground"),
        },
        brand: {
          DEFAULT: token("brand"),
          strong: token("brand-strong"),
          soft: token("brand-soft"),
          ink: token("brand-ink"),
        },
        // UX-11 (#101): atencao (laranja) e critico (vermelho).
        alerta: {
          DEFAULT: token("alerta"),
          forte: token("alerta-forte"),
        },
        critico: token("critico"),
        // Nomes legados das telas existentes, remapeados para a nova
        // identidade. Cada jornada migra as proprias telas para os tokens acima.
        primaryDeep: token("foreground"),
        primaryLight: token("brand-soft"),
        bg: token("background"),
        surface: token("card"),
        textMain: token("foreground"),
        textMuted: token("muted-foreground"),
        // Tons -700: texto pequeno sobre fundo claro precisa de contraste AA.
        success: "#047857",
        warning: "#C2410C",
        danger: "#DC2626",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
        card: "calc(var(--radius) + 4px)",
      },
      boxShadow: {
        card: "0 2px 8px rgb(0 0 0 / 0.04)",
        cardHover: "0 6px 16px rgb(0 0 0 / 0.08)",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
        display: ["Manrope", "Inter", "sans-serif"],
      },
    },
  },
  plugins: [animate],
}
