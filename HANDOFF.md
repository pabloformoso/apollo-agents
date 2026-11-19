# Session Handoff
Created: 2026-11-18
Status: ready-to-resume
Base commit: 91e6a9a (main tras #225, último merge 2026-09-25)
Previous handoff: HANDOFF.2026-09-23.md (demo del 24-sep)

## Goal
Reactivar el proyecto tras ~2 meses parado: dejar main sin vulnerabilidades
conocidas en el árbol de producción, la CI sin intermitencias y los docs al día,
y después retomar el backlog.

## Estado al retomar (diagnóstico 2026-11-17)
- main: CI verde en #225. Ninguna PR abierta.
- Backend: 2787 tests pasan. Frontend: 748 tests, `next build` verde.
- Ramas: 134 remotas, 130 ya en main (squash). Las 4 restantes están
  superadas (spike/strudel-in-next, feature/clever-matsumoto-9deb06,
  claude/beat-matching-precision-7B5V2, chore/refresh-frontend-lockfile).
  No hay trabajo perdido en ninguna rama.

## Done (PR de rescate, rama feature/vigilant-mccarthy-a7wxbm)
- Test intermitente del frontend (1 de cada 4 runs con exit 1): vitest con
  `globals: false` nunca desmontaba lo renderizado — ver
  web/frontend/lib/__tests__/setup.ts.
- Next 16.2.4 → 16.4.6 y `npm audit fix`: `npm audit --omit=dev` = 0.
- Python: starlette/fastapi, urllib3, requests, cryptography, weasyprint,
  oauthlib, etc. al día en uv.lock; Pillow 11.3 → 13.0 con un
  `override-dependencies` en pyproject.toml (moviepy 2.2.1 fija pillow<12).
- CLAUDE.md: el checkout de prod está en jarvis, no en Windows.

## Pendiente de despliegue (Pablo, en jarvis)
Tras el squash-merge: comprobar que no hay set en directo
(`docker logs --since 30m apollo-backend | grep live-ws`), luego
`git fetch && git merge --ff-only origin/main`. Cambian dependencias, así
que un restart NO basta, y `up --build` tampoco a secas:

```bash
docker compose build backend frontend
docker compose up -d -V   # -V: node_modules del frontend es un volumen ANÓNIMO; sin -V se queda el viejo
docker compose exec backend uv sync --group web --group youtube --frozen   # el venv es el volumen apollo_backend_venv, la imagen nueva no lo pisa
docker compose restart backend
uv sync && systemctl --user restart apollo-mind apollo-ace-control         # servicios fuera de compose, venv del host
```

Comprobar: `docker compose exec frontend node -e "console.log(require('next/package.json').version)"`
→ 16.4.6, y `docker compose exec backend uv pip show pillow` → 13.0.0.

## Riesgos conocidos
- Pillow 13 por encima del límite de moviepy: tests + render de humo
  (títulos, loop de artwork, resize de moviepy) OK, pero no se ha renderizado
  una sesión completa. Primera sesión tras el deploy: mirar el vídeo.
- fastapi 0.136 → 0.163 y cryptography 46 → 50 son saltos grandes; la suite
  pasa, pero vigilar el login Keycloak/JWT en prod.
- JWT: python-jose → PyJWT 2.15.1 (quita sus dos avisos y los de ecdsa).
  Un token emitido por jose se decodifica igual con PyJWT (comprobado), así
  que nadie pierde la sesión. PyJWT avisa (`InsecureKeyLengthWarning`, no
  error) si `JWT_SECRET` tiene menos de 32 bytes: mirar su longitud en el
  `.env` de prod; rotarlo cierra todas las sesiones, decidirlo aparte.
- Sin versión corregida todavía: picomatch (dev, ReDoS).

## Next steps
1. Mergear la PR de rescate y desplegar (arriba).
2. Borrar 133 ramas remotas — aprobado por Pablo el 2026-11-19, pero esta
   sesión solo puede escribir en su propia rama (GitHub responde 403), así que
   hay que lanzar `delete-merged-branches.sh` desde un checkout propio.
   Auditoría (punta de cada rama contra main y contra el head de cada PR
   mergeada, clon completo): 23 en main, 102 dentro de una PR mergeada, 8 no.
   Esas 8 solo viven en su rama; para restaurar una:
   `git push origin <sha>:refs/heads/<rama>` desde un clon que la tenga.
   - feat/gen-surge-cli b0e6815312ae, feat/gen-surge-cli-fix f59da895d0bb,
     feat/gen-v32 69696f336d01 — parche idéntico en main (#78, #80, #76).
   - claude/blissful-fermi-6fedfd 1fba8f1ccbf6 — el arreglo de genre_guard lo
     resolvió el issue #23; lo demás era solo para Windows.
   - spike/strudel-in-next 2f1b1553b8e9, feature/clever-matsumoto-9deb06
     cb02dce73a78, claude/beat-matching-precision-7B5V2 61195003d728,
     chore/refresh-frontend-lockfile 24d1fc4a6e3c — superadas.
3. Stall-watchdog alarm (backlog de agent/CLAUDE.md): no existe en ninguna
   rama, hay que escribirla desde cero.
4. Del handoff anterior, aún abiertos: VIDEO_ID del showcase en README.md,
   prefill `// reason:` del Mind, Qwen-Image para portadas, backups restic.
5. ~~Sustituir python-jose~~ — hecho (PyJWT).
