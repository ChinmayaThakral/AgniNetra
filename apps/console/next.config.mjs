/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The dev overlay badge sits bottom left and covers the first class filter.
  devIndicators: false,
  // Next 16 can write its own instruction files into the project from `next dev`.
  // They are not part of this console.
  agentRules: false,
};

export default nextConfig;
