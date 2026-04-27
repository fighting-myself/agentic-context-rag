FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json /app/package.json
RUN npm install
COPY . /app
RUN npm run build

FROM nginx:1.27-alpine
ENV BACKEND_HOST=backend
COPY --from=builder /app/dist /usr/share/nginx/html
COPY templates/default.conf.template /etc/nginx/templates/default.conf.template
EXPOSE 80
