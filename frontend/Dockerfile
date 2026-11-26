# package.json and package-lock.json also carry the app version. The "manifest" stage blanks it,
# so the COPY --from below (checked by content) and `npm ci` stay cached until a dependency changes.
FROM node:22-alpine AS manifest
WORKDIR /app
COPY package.json package-lock.json ./
RUN node -e "const fs = require('fs'); for (const f of ['package.json', 'package-lock.json']) { const j = JSON.parse(fs.readFileSync(f, 'utf8')); j.version = '0.0.0'; if (j.packages && j.packages['']) j.packages[''].version = '0.0.0'; fs.writeFileSync(f, JSON.stringify(j, null, 2) + '\n'); }"

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=manifest /app/package.json /app/package-lock.json ./
RUN npm ci
# The real package.json (with the version shown in the app) replaces the blanked one here.
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
