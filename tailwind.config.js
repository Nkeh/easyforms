module.exports = {
  content: ["./templates/**/*.html", "./*/templates/**/*.html"],
  // core/forms.py sets these two classes on widgets from Python, not from any
  // scanned .html template, so Tailwind's JIT purges them from @layer
  // components output without an explicit safelist entry — content scanning
  // still applies to custom @layer classes, not just generated utilities.
  safelist: ["field-input", "field-checkbox"],
  theme: {
    fontFamily: {
      sans: [
        '"Schibsted Grotesk"',
        "ui-sans-serif",
        "system-ui",
        "-apple-system",
        '"Segoe UI"',
        "sans-serif",
      ],
    },
    extend: {
      colors: {
        paper: "#F5F7F6",
        ink: "#0E2238",
        "ink-raised": "#17324F",
        signal: "#27D980",
        "signal-deep": "#0A7A44",
        line: "#D3DAE1",
        danger: "#B42318",
        "danger-soft": "#FDECEA",
        warn: "#B45309",
        "warn-soft": "#FEF3C7",
      },
    },
  },
  plugins: [],
};
