# Frontend image for Uptime Guardian (Vue 3 + Vite, served by nginx).
#
# Multi-stage build:
#   1. Build the static site with Node + pnpm.
#   2. Serve the compiled assets with nginx on port 3000.
#
# The backend API base URL is baked in at build time via VITE_API_BASE_URL
# (Vite inlines VITE_* env vars during `pnpm build`). Override it with
# `--build-arg VITE_API_BASE_URL=...` or the compose `args` block.

# ---- Stage 1: build ----
FROM node:20-alpine AS build

# Allow the API base URL to be configured at build time.
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

# Enable pnpm via corepack (bundled with Node 20) and pin a version
# compatible with Node 20 + lockfile v9 (avoids corepack pulling the
# latest pnpm which requires Node 22+).
RUN corepack enable && corepack prepare pnpm@9.15.4 --activate

WORKDIR /app

# Install dependencies first for better layer caching.
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Copy the rest of the source and build the static site into /app/dist.
COPY . .
RUN pnpm build

# ---- Stage 2: serve ----
FROM nginx:alpine AS serve

# Custom nginx config: listen on 3000 with SPA history-mode fallback.
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy the compiled assets from the build stage.
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
