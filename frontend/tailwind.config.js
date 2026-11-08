/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        automotive: {
          dark: '#070A12',
          bg: '#0A0E1A',
          card: '#0F1626',
          panel: '#131D31',
          panelHover: '#18243C',
          border: '#1E293B',
          borderLight: '#334155',
          cyan: '#00E5FF',
          blue: '#38BDF8',
          electric: '#0EA5E9',
          normal: '#10B981',
          warning: '#F59E0B',
          danger: '#EF4444',
          muted: '#64748B',
        }
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['JetBrains Mono', 'Menlo', 'Monaco', 'Courier New', 'monospace'],
      },
      boxShadow: {
        'automotive-cyan': '0 0 20px -3px rgba(0, 229, 255, 0.25)',
        'automotive-danger': '0 0 20px -3px rgba(239, 68, 68, 0.3)',
        'automotive-normal': '0 0 20px -3px rgba(16, 185, 129, 0.25)',
        'card-glow': '0 4px 20px -2px rgba(0, 0, 0, 0.5), inset 0 1px 0 0 rgba(255, 255, 255, 0.05)',
      }
    },
  },
  plugins: [],
}
