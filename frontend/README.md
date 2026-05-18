# Frontend

`index.html` is a single-file demo of the Avaturn Live Web SDK driven by this
repo's session broker. The standalone server in `../server.py` serves it at
`/`, so you can open `http://localhost:8000` and click **Join** to start
talking to the Pipecat-powered avatar.

The SDK is loaded via [esm.sh](https://esm.sh) so there is no build step —
swap to a local bundle if you'd rather pin the version yourself:

```bash
npm install @avaturn-live/web-sdk
```

`AvaturnHead`'s `sessionToken` comes from `POST /api/sessions` on this repo's
broker, which in turn calls Avaturn Live's `POST /api/v1/sessions` with an
`external` conversation engine pointed at this repo's WebSocket endpoint.
