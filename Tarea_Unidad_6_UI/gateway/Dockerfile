FROM node:22-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY src ./src
COPY public ./public
ENV NODE_ENV=production PORT=4000
# uid numérico: la PodSecurity "restricted" del cluster exige runAsNonRoot verificable.
USER 10001
EXPOSE 4000
CMD ["node", "src/server.js"]
