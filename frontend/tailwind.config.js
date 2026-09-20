/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: 'var(--bg)',
        surface: 'var(--surface)',
        border: 'var(--border)',
        text: 'var(--text)',
        muted: 'var(--muted)',
        accent: 'var(--accent)',
        red: { DEFAULT: 'var(--red)', bg: 'var(--red-bg)' },
        amber: { DEFAULT: 'var(--amber)', bg: 'var(--amber-bg)' },
        green: { DEFAULT: 'var(--green)', bg: 'var(--green-bg)' },
        info: { DEFAULT: 'var(--info)', bg: 'var(--info-bg)' },
      },
      borderRadius: {
        cards: '12px',
        controls: '8px',
      },
      boxShadow: {
        sm: '0 1px 2px 0 rgba(0, 0, 0, 0.05)',
      }
    },
  },
  plugins: [],
}
