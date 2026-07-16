# syntax=docker/dockerfile:1

# ---- Stage 1: build tĩnh bằng Vite ----
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Build không cần secret: app gọi API bằng đường dẫn tương đối /api/*,
# nginx (stage 2) mới là nơi proxy + gắn X-API-Key lúc chạy.
RUN npm run build

# ---- Stage 2: phục vụ bằng nginx + proxy API ----
FROM nginx:1.27-alpine AS runtime
# Template được entrypoint nginx chạy envsubst lúc khởi động,
# thay ${SERVICE_API_KEY} bằng biến môi trường (biến nội bộ nginx như $uri không bị đụng).
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
