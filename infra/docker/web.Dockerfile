# syntax=docker/dockerfile:1
# The TalentSignal frontend: the Next.js static export served by nginx, which also
# proxies /api/ to the API container (and terminates HTTPS on the server). Build from the repo root:
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

# 2. Serve it. No Node process at runtime. The site config (HTTP, or HTTPS once the server
#    has a certificate for TLS_HOST) is chosen at container start by 40-talentsignal-tls.sh.
FROM nginx:1.30-alpine
RUN rm -f /etc/nginx/conf.d/default.conf && mkdir -p /etc/letsencrypt /var/www/acme  # mount points (server)
COPY infra/docker/nginx/00-http.conf /etc/nginx/conf.d/
COPY infra/docker/nginx/app.locations infra/docker/nginx/http.conf infra/docker/nginx/https.conf /etc/nginx/talentsignal/
COPY --chmod=755 infra/docker/nginx/40-talentsignal-tls.sh /docker-entrypoint.d/
COPY --from=build /web/out /usr/share/nginx/html

# The commit this image was built from: /version.json (the CD job waits for it to change)
# and the label update.sh reads on the server.
ARG GIT_SHA=local
RUN printf '{"commit":"%s"}\n' "$GIT_SHA" > /usr/share/nginx/html/version.json
LABEL org.opencontainers.image.revision=$GIT_SHA
