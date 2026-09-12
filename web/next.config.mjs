/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async rewrites() {
    // In local development, optionally proxy /api requests to ai-gateway if NEXT_PUBLIC_API_URL is relative
    return [];
  },
};

export default nextConfig;
