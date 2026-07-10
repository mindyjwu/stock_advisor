/** @type {import('next').NextConfig} */
const nextConfig = {
  // The app is a pure API client; keep the build self-contained and skip the
  // interactive ESLint setup during CI/prod builds (types are still checked).
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;
