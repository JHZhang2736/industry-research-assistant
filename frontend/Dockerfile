# syntax=docker/dockerfile:1.7

# === builder stage ===
FROM node:20-alpine AS builder

WORKDIR /build

# Copy lockfile + package.json first for layer caching
COPY package.json package-lock.json ./

RUN npm ci --ignore-scripts --legacy-peer-deps

# Copy rest of frontend source
COPY . .

# Build production bundle
RUN npm run build

# === runtime stage ===
FROM nginx:alpine

# Replace default nginx config
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built static files
COPY --from=builder /build/dist /usr/share/nginx/html

EXPOSE 80

# nginx:alpine 默认 CMD 就是启动 nginx，不需要覆盖
