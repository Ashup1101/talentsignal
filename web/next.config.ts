import type { NextConfig } from "next";

// Static export (Phase 6, D7): `next build` writes plain HTML/JS/CSS to out/, which nginx
// serves; nginx also proxies /api/ to the FastAPI service. No Node.js server in production.
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true, // /analyze/ → out/analyze/index.html: nginx serves it without rewrites
  images: { unoptimized: true }, // the image optimizer needs a Node.js server
  devIndicators: false, // no floating "N" badge over the pages in development
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
