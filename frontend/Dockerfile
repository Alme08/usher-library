# Frontend development image for the Usher Library React app.
#
# This is a DEVELOPMENT image (not production). It is intentionally not
# multi-stage and not size-optimized: the goal of T4 is to prove the
# provisional page is served in isolation. Production hardening
# (multi-stage build, static asset CDN, etc.) is out of scope for this
# spec and must be designed behind an ADR.
#
# Security posture (docs/architecture/security.md §28):
#   * runs as a non-root user
#   * exposes only the Vite dev server port (5173)
#   * no privileged mode
#   * no Docker socket mounted
#   * no secrets baked in
#
# Vite already binds to 0.0.0.0:5173 via `frontend/vite.config.ts`, so the
# dev server is reachable from the host without extra flags. `npm ci`
# installs exact versions from `package-lock.json` (deterministic build,
# RNF-3: no paid services / no surprise updates). `curl` is required by
# the Compose healthcheck (RF-9) to confirm the provisional page is
# served on port 5173 once the dev server is up.

# --- Runtime base -------------------------------------------------------------
FROM node:24-bookworm-slim AS frontend-dev

# Disable npm update prompts and keep the global cache out of the image.
ENV NPM_CONFIG_UPDATE_NOTIFIER=false \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_AUDIT=false

# `curl` is the lightest HTTP probe available in the base image and lets
# the Compose healthcheck confirm that the dev server is serving the
# provisional page (RF-9, RF-10).
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Dependencies -------------------------------------------------------------
# Copy manifest + lockfile first so `npm ci` is cached as long as the
# dependency graph is unchanged.
COPY package.json package-lock.json ./
RUN npm ci

# --- Application source -------------------------------------------------------
# `.dockerignore` excludes `node_modules`, `dist`, caches and editor files.
COPY . .

# --- Non-root user ------------------------------------------------------------
# node:24-bookworm-slim already ships a `node` user (uid 1000). Reuse it
# and make sure the working tree is owned by it so `npm`/`vite` can write
# to `.vite/` and the HMR cache.
RUN chown -R node:node /app
USER node

# --- Network ------------------------------------------------------------------
EXPOSE 5173

# --- Entrypoint ---------------------------------------------------------------
# Run the Vite dev server. The host/port are already pinned in
# `vite.config.ts`; `npm run dev` forwards to `vite` which respects them.
CMD ["npm", "run", "dev"]
