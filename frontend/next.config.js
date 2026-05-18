/** @type {import('next').NextConfig} */
const nextConfig = {
  // TradingView charting_library lives in /public/charting_library/
  // and must NOT be processed by webpack
  webpack: (config) => {
    config.externals = config.externals || []
    config.externals.push({ 'charting_library': 'TradingView' })
    return config
  },
  async rewrites() {
    return [
      // Proxy API calls to FastAPI backend during dev
      {
        source: '/api/backend/:path*',
        destination: `${process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000'}/api/v1/:path*`,
      },
    ]
  },
}

module.exports = nextConfig
