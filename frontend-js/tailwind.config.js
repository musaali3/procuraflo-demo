/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#EEF9FB',
          100: '#D8F2F3',
          500: '#12B8B0',
          600: '#0A98A1',
          700: '#087785',
          900: '#06213A',
        },
        primary: '#1677D8',
        'primary-bright': '#1683E8',
        'pf-emerald': '#14B866',
        slate: { 950: '#0b1220' },
      },
    },
  },
  plugins: [],
};
