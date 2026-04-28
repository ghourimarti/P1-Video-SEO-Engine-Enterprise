# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────────────────────────
# Anime RAG Web — multi-stage Dockerfile (M9 hardened)
#
# Uses Next.js standalone output mode for a minimal production image.
# Enable in next.config.ts: output: "standalone"
#
# Stages
#   deps        pnpm install (cached)
#   builder     next build → .next/standalone
#   production  non-root, copy only standalone output + static assets
#
# Build
#   docker build --target production -t anime-rag-web:latest apps/web
# ─────────────────────────────────────────────────────────────────────────────

ARG NODE_VERSION=20

# ── Stage 1: install dependencies ─────────────────────────────────────────────
FROM node:${NODE_VERSION}-slim AS deps

# Enable corepack for pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app

# Copy manifests first — Docker cache layer for node_modules
COPY package.json pnpm-lock.yaml* ./

RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile --prod=false

# ── Stage 2: build ────────────────────────────────────────────────────────────
FROM node:${NODE_VERSION}-slim AS builder

RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Build args surfaced as NEXT_PUBLIC_ env vars baked at build time
ARG NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=""
ARG NEXT_PUBLIC_API_URL="http://localhost:8000"
ENV NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=${NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY}
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

# Disable Next.js telemetry in CI
ENV NEXT_TELEMETRY_DISABLED=1

RUN pnpm build

# ── Stage 3: production ───────────────────────────────────────────────────────
FROM node:${NODE_VERSION}-slim AS production

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

# Non-root user
RUN groupadd --system --gid 1001 nodejs \
 && useradd  --system --uid 1001 --gid nodejs \
             --no-create-home --shell /sbin/nologin nextjs

WORKDIR /app

# Copy standalone output (includes server.js + bundled node_modules)
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
# Copy static assets (Next.js serves these from /_next/static)
COPY --from=builder --chown=nextjs:nodejs /app/.next/static     ./.next/static
# Copy public folder (favicon, images, etc.)
COPY --from=builder --chown=nextjs:nodejs /app/public           ./public

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD node -e "require('http').get('http://localhost:3000/', (r) => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))"

# Next.js standalone uses server.js as the entrypoint
CMD ["node", "server.js"]
