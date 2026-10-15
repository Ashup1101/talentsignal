# syntax=docker/dockerfile:1
# The TalentSignal frontend: the Next.js static export served by nginx, which also
# proxies /api/ to the API container. Build from the repo root:
#   docker build -f infra/docker/web.Dockerfile -t talentsignal-web .

# 1. Build web/out/ (plain HTML/CSS/JS). NEXT_PUBLIC_API_BASE stays empty: the browser
#    calls /api on the same origin. Debian-based Node, like the CI web job.
FROM node:24-slim AS build
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# 2. Serve it. No Node process at runtime.
FROM nginx:1.30-alpine
COPY infra/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/out /usr/share/nginx/html
