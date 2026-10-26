# Stage 1: build the standalone page from the template and the street data.
FROM python:3.13-alpine AS build
WORKDIR /app
COPY scripts/build.py scripts/
COPY src/ src/
COPY data/ data/
RUN python3 scripts/build.py

# Stage 2: serve it with nginx.
FROM nginx:1.27-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/index.html /usr/share/nginx/html/index.html
EXPOSE 80
