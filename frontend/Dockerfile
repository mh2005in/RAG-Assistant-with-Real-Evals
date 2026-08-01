# Build the Angular app to static files, then serve them with nginx. Two stages
# keep the final image small (just nginx + the compiled bundle, no Node or
# node_modules).

# --- Build stage ------------------------------------------------------------
FROM node:22-alpine AS build

WORKDIR /app

# Install deps first, in their own layer, so the cache survives source changes.
# npm ci installs exactly what package-lock.json pins (reproducible).
COPY package.json package-lock.json ./
RUN npm ci

# Compile. Output lands in dist/rag-frontend/browser (Angular application
# builder). See .dockerignore for what is left out of the context.
COPY . .
RUN npm run build

# --- Serve stage ------------------------------------------------------------
FROM nginx:1.27-alpine

# Serve the SPA and reverse-proxy the API paths to the app service (see
# nginx.conf) so the browser talks to a single origin -- no CORS needed.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/rag-frontend/browser /usr/share/nginx/html

EXPOSE 80

# Readiness check: the SPA is up once nginx serves index.html. Use 127.0.0.1
# explicitly, not "localhost" -- the container resolves localhost to ::1 (IPv6)
# first, but nginx binds IPv4 only (listen 80), so a localhost probe would fail.
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=5 \
    CMD wget -q --spider http://127.0.0.1/ || exit 1
