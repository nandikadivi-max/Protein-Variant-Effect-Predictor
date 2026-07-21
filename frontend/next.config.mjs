/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Mol* ships large ES modules; transpiling it keeps Next's bundler happy.
  transpilePackages: ["molstar"],
};

export default nextConfig;
