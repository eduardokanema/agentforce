import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#090d18',
        surface: '#0d1525',
        card: '#111c2e',
        'card-hover': '#162234',
        border: '#1b2d42',
        'border-lit': '#264060',
        text: '#dde6f0',
        dim: '#8da0b5',
        muted: '#4d6070',
        blue: '#4d94ff',
        'blue-bg': '#0f2040',
        green: '#2ecc8a',
        'green-bg': '#0a2818',
        amber: '#f0b429',
        'amber-bg': '#2d1f06',
        red: '#ff6b6b',
        'red-bg': '#2d0f0f',
        purple: '#9b7dff',
        'purple-bg': '#1f1045',
        teal: '#2dd4bf'
      }
    }
  },
  plugins: [],
} satisfies Config;
