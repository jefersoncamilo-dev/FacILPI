import animate from "tailwindcss-animate"

// UX-01 (#83) / Onda 5 (#213): tokens da identidade FacILPI. As cores vivem
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
        "critico-texto": token("critico-texto"),
        // Nomes legados das telas existentes, remapeados para a nova
        // identidade. Cada jornada migra as proprias telas para os tokens acima.
        primaryDeep: token("foreground"),
        primaryLight: token("brand-soft"),
        bg: token("background"),
        surface: token("card"),
        textMain: token("foreground"),
        textMuted: token("muted-foreground"),
        // Onda 5 (#213): estados semanticos viram tokens (AA nos dois temas).
        success: token("primary"),
        warning: token("alerta-forte"),
        danger: token("critico-texto"),
        avatar: {
          DEFAULT: token("avatar"),
          foreground: token("avatar-foreground"),
        },
        "alerta-soft": token("alerta-soft"),
        "critico-soft": token("critico-soft"),
        info: {
          DEFAULT: token("info"),
          soft: token("info-soft"),
        },
        "brand-light": token("brand-light"),
        "background-desktop": token("background-desktop"),
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
        card: "var(--radius-card)",
        icon: "var(--radius-icon)",
      },
      boxShadow: {
        card: "var(--shadow-card)",
        cardHover: "0 14px 32px rgba(11, 49, 45, 0.12)",
        icon: "var(--shadow-icon)",
        search: "var(--shadow-search)",
        glass: "var(--shadow-glass)",
      },
      backgroundImage: {
        side: "var(--gradient-side)",
        highlight: "var(--gradient-highlight)",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
        display: ["Poppins", "Inter", "sans-serif"],
      },
      // Estilos de texto da Onda 5: [tamanho, { altura, espacamento, peso }].
      fontSize: {
        "titulo-tela": ["28px", { lineHeight: "34px", letterSpacing: "-0.02em", fontWeight: "600" }],
        "titulo-secao": ["18px", { lineHeight: "24px", letterSpacing: "-0.01em", fontWeight: "600" }],
        "titulo-cartao": ["17px", { lineHeight: "24px", letterSpacing: "-0.01em", fontWeight: "600" }],
        "numero-destaque": ["32px", { lineHeight: "36px", letterSpacing: "-0.02em", fontWeight: "600" }],
        corpo: ["17px", { lineHeight: "26px" }],
        "corpo-forte": ["17px", { lineHeight: "24px", letterSpacing: "-0.005em", fontWeight: "600" }],
        apoio: ["15px", { lineHeight: "22px" }],
        rotulo: ["13px", { lineHeight: "18px", letterSpacing: "0.01em", fontWeight: "600" }],
        botao: ["17px", { lineHeight: "22px", fontWeight: "600" }],
        navegacao: ["12px", { lineHeight: "16px", letterSpacing: "0.01em", fontWeight: "500" }],
      },
    },
  },
  plugins: [animate],
}
