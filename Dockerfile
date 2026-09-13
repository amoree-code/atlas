FROM node:22-bookworm-slim

RUN apt-get update \
  && apt-get install --no-install-recommends -y python3 make g++ \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json pnpm-lock.yaml ./
RUN mkdir -p scripts
COPY scripts/prepare-node-pty.mjs ./scripts/prepare-node-pty.mjs
RUN corepack enable && pnpm install --frozen-lockfile

COPY . .
RUN pnpm test

CMD ["pnpm", "test"]
