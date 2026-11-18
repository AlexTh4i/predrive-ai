FROM node:22-alpine AS build

WORKDIR /app

COPY admin-web/package.json admin-web/package-lock.json* ./
RUN npm ci

COPY admin-web/ ./
ENV VITE_USE_MOCK=false
ENV VITE_API_URL=/api/v1
RUN npm run build

FROM nginx:1.27-alpine

COPY admin-web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
    CMD wget -qO- http://127.0.0.1:80/healthz || exit 1
