import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg:       'var(--color-bg)',
        surface:  'var(--color-surface)',
        surface2: 'var(--color-surface2)',
        surface3: 'var(--color-surface3)',
        divider:  'var(--color-divider)',
        border:   'var(--color-border)',
        text:     'var(--color-text)',
        muted:    'var(--color-muted)',
        faint:    'var(--color-faint)',
        primary:  'var(--color-primary)',
        success:  'var(--color-success)',
        error:    'var(--color-error)',
        warning:  'var(--color-warning)',
        gold:     'var(--color-gold)',
        purple:   'var(--color-purple)',
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      fontSize: {
        '2xs': ['10px', { letterSpacing: '0.04em' }],
        xs:    ['11px', { lineHeight: '1.4' }],
        sm:    ['12px', { lineHeight: '1.5' }],
        base:  ['13px', { lineHeight: '1.5' }],
      },
      borderRadius: {
        sm: '4px', DEFAULT: '6px', md: '6px', lg: '8px',
      },
      animation: {
        'pulse-live':    'pulse-live 1.8s ease-in-out infinite',
        'slide-right':   'slide-in-right 200ms cubic-bezier(0.16,1,0.3,1) forwards',
        'slide-up':      'slide-in-up 180ms cubic-bezier(0.16,1,0.3,1) forwards',
        'fade-in':       'fade-in 180ms ease forwards',
        'shimmer':       'shimmer 1.6s ease-in-out infinite',
        'count':         'count-up 250ms cubic-bezier(0.16,1,0.3,1) both',
      },
      keyframes: {
        'pulse-live': {
          '0%, 100%': { opacity: '1', transform: 'scale(1)' },
          '50%': { opacity: '0.4', transform: 'scale(0.85)' },
        },
        'slide-in-right': {
          from: { transform: 'translateX(100%)', opacity: '0' },
          to:   { transform: 'translateX(0)',    opacity: '1' },
        },
        'slide-in-up': {
          from: { transform: 'translateY(8px)', opacity: '0' },
          to:   { transform: 'translateY(0)',   opacity: '1' },
        },
        'fade-in': {
          from: { opacity: '0' },
          to:   { opacity: '1' },
        },
        'shimmer': {
          '0%':   { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition:  '200% 0' },
        },
        'count-up': {
          from: { opacity: '0', transform: 'translateY(4px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
      },
      boxShadow: {
        sm:  '0 1px 3px rgba(0,0,0,0.3)',
        md:  '0 4px 12px rgba(0,0,0,0.4)',
        lg:  '0 8px 24px rgba(0,0,0,0.5)',
        glow:'0 0 12px rgba(79,152,163,0.25)',
      },
    },
  },
  plugins: [],
}
export default config
