import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // Nexus dark palette
        bg:         '#171614',
        surface:    '#1c1b19',
        surface2:   '#201f1d',
        border:     '#393836',
        divider:    '#262523',
        text:       '#cdccca',
        muted:      '#797876',
        faint:      '#5a5957',
        primary:    '#4f98a3',
        'primary-hover': '#227f8b',
        success:    '#6daa45',
        error:      '#d163a7',
        warning:    '#bb653b',
        gold:       '#e8af34',
        // trade colors
        long:       '#6daa45',
        short:      '#d163a7',
      },
      fontFamily: {
        sans: ['var(--font-inter)', 'system-ui', 'sans-serif'],
        mono: ['var(--font-mono)', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.625rem', { lineHeight: '0.875rem' }],
      },
    },
  },
  plugins: [],
}

export default config
