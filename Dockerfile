FROM node:22-bookworm-slim

RUN apt-get update \
  && apt-get install --no-install-recommends -y python3 make g++ \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY packages/core/package.json ./packages/core/package.json
RUN mkdir -p scripts packages/core/scripts
COPY scripts/prepare-hooks.mjs ./scripts/
COPY packages/core/scripts/prepare-node-pty.mjs ./packages/core/scripts/
RUN corepack enable && pnpm install --frozen-lockfile

COPY . .
RUN pnpm test

RUN useradd --create-home --shell /usr/sbin/nologin atlas \
  && chown -R atlas:atlas /app
USER atlas

CMD ["pnpm", "test"]
