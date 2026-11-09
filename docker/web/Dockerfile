FROM node:22-alpine
RUN npm install -g firebase-tools@14.11.0
WORKDIR /srv
COPY firebase.json .firebaserc ./
EXPOSE 5055 9099 4055
CMD ["firebase", "emulators:start", "--only", "auth,hosting", "--project", "mks-agent-console"]
