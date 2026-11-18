# Session Handoff
Created: 2026-09-23 10:50 CEST
Working dir: /home/pablo/code/apollo-agents (prod = checkout principal en jarvis; trabajar desde un worktree)
Status: ready-to-resume
Base commit: e2d64be (main tras #219; esta PR de handoff añade un commit encima)
Working tree: clean
Branch: main (el checkout principal); un worktree nuevo parte de origin/main

## Goal
Presentar Apollo el jueves 2026-09-24 (open source, buscando sponsors, "el primer
Music Entertainment System dirigido por IA"). La demo se apoya en el algorave en
directo con el Mind entrando en back-to-back, el feed de razonamiento visible, y
el generador tipo Suno con portadas. Pablo graba hoy un vídeo scripted del
algorave (copia-pega de bloques, luego B2B) para el README y YouTube.

## Where I left off
Ayer el Mind fallaba en directo ("no ha construido Strudel válido", o llegaba
tarde). Diagnóstico con el log de LM Studio: 17 respuestas, 11 rechazadas, y
gemma pensaba 6–11 s por respuesta. PR #219 (thinking apagado, reparación de
bancos, bloque de rechazos en el prompt) mergeada y desplegada a las 10:44:
ff en el checkout principal y `systemctl --user restart apollo-mind`. Smoke en
prod: 4/4 frases válidas en 5–10 s. Después medí gpt-4o-mini (estudio abajo).

## Decisions made (with rationale)
- Thinking apagado por defecto en el Mind (`GENERATIVE_THINKING=1` lo enciende) — 6–11 s por respuesta sin ganar validez; una frase son 15 s.
- `repair_banks()` antes del validador — el rechazo más frecuente era `sh` sobre la 909; el validador sigue siendo la puerta.
- gemma-4-e4b se queda para el jueves; gpt-4o-mini NO se cambia antes de la demo — ver estudio.
- Portadas: Azure gpt-image-1-mini por generación y al publicar, dirección de arte con gpt-4o-mini (`APOLLO_COVER_PROMPT_DEPLOYMENT`); Qwen-Image vía ComfyUI después del jueves. Ninguna llamada de pago nueva sin proponer coste antes.
- Nav: Home · Catalog · Generations · Algorave · Settings (Create y Perform son viajes desde Home).
- GPU compartida: gemma (5,9 GB) y ACE no caben juntos; Jarvis paró kev/laya y no los rearranca hasta el viernes 25.

## Done
- Mind: thinking off, `repair_banks`, `rejections_block` — [strudel_mind.py](agent/generative/strudel_mind.py), tests en [test_strudel_mind.py](tests/test_strudel_mind.py); transportes en [bench_strudel_mind.py:208](scripts/bench_strudel_mind.py:208) y [algorave_playground.py:347](scripts/algorave_playground.py:347).
- Diez bloques Strudel validados para grabar — [algorave-showcase-blocks.md](docs/algorave-showcase-blocks.md).
- Showcase mode, feed de razonamiento en `/live`, espejo del algorave para OBS — [showcase.md](docs/showcase.md), [reasoning.ts](web/frontend/lib/reasoning.ts), [AlgoraveClient.tsx](web/frontend/app/algorave/AlgoraveClient.tsx).
- Generador tipo Suno con portadas y dirección de arte por canción — [GeneratorComposer.tsx](web/frontend/components/ember/GeneratorComposer.tsx), [covers.py](web/backend/covers.py).
- Controlador ACE endurecido (Restart=always) — [apollo-ace-control.service](deploy/acestep/apollo-ace-control.service).

## In progress
- Grabación del showcase: seguir [showcase.md](docs/showcase.md) y los bloques; subir a YouTube y sustituir `VIDEO_ID` (dos veces) en [README.md](README.md). Next concrete step: grep `VIDEO_ID` README.md y pegar el id.
- Ensayo completo antes del jueves: Settings → Load selected model → Home ▶ Showcase → curate → "take the booth" → `/live` → Algorave con B2B. Next concrete step: comprobar en Settings que gemma sigue cargado (`lms ps` en jarvis) y el Mind activo.

## Dead ends (do not retry)
- `reasoning_effort: "none"` para apagar el thinking — gemma piensa dentro del contenido (prosa donde va el código). Solo funciona `chat_template_kwargs.enable_thinking=false`, y no siempre: 3 de 4 respuestas en prod siguieron razonando ~490 tokens (5 s).
- Decirle al modelo en el prompt que la 909 no tiene shaker — lo seguía haciendo; por eso la reparación mecánica.
- Leer `.env`, `.tmp/*.json` o la BD de prod desde el worktree — permisos denegados; usar `docker exec apollo-backend` para leer ajustes.
- El botón "Save settings" del panel Main LLM — guarda pero NO carga; la carga es "Load selected model". Ayer ninguna carga llegó al backend (se cargó con `lms load`).

## Verification before resuming
```bash
git merge-base --is-ancestor e2d64be HEAD && echo ok   # Expected: ok (main contiene #219)
git status --porcelain     # Expected: vacío
git branch --show-current  # Expected: main (checkout principal) o la rama del worktree
~/.lmstudio/bin/lms ps     # Expected: google/gemma-4-e4b IDLE
systemctl --user is-active apollo-mind apollo-ace-control   # Expected: active active
nvidia-smi --query-gpu=memory.used --format=csv,noheader     # Expected: ~6500 MiB
```

Expected: gemma residente, Mind activo, GPU con 9 GB libres; pedir en /algorave responde en 5–10 s.

## Next steps
1. Grabar el showcase con [algorave-showcase-blocks.md](docs/algorave-showcase-blocks.md); tras cada bloque, "ask" y luego B2B con 8 compases de frase.
2. Sustituir `VIDEO_ID` en [README.md](README.md) y hacer PR.
3. Opcional y barato (una PR pequeña): prefill de asistente `// reason:` en `make_llm` — en 4/4 pruebas anuló el razonamiento (5,2–5,6 s, 3/4 válidas). Medir 8 asks antes de mergear.
4. Corregir el CLAUDE.md raíz: el checkout principal ya no está en Windows sino en jarvis (`/home/pablo/code/apollo-agents`).
5. Después del jueves: Qwen-Image como proveedor alternativo de portadas; backups restic (scripts de Jarvis pendientes de que Pablo los lance).

## Open questions for the user
- ¿Quieres el prefill (paso 3) antes del jueves, o dejamos gemma como está (5–10 s, 4/4 válidas)?
- El botón "Load selected model": ¿lo pulsaste ayer y no hizo nada, o pulsaste "Save settings"? Si fue lo primero hay un bug de front que no dejó rastro.

## Estudio: gpt-4o-mini frente a gemma-4-e4b para el Algorave Mind (medido 2026-09-22/23)

Mismo bloque de partida, misma intención, validador real, 8 ciclos, La menor, valla `deep`.

| | gemma-4-e4b (LM Studio, local) | gpt-4o-mini (Azure) |
|---|---|---|
| Validez | con thinking 6/17; sin thinking 8/8 (bench) y 4/4 (prod) | 8/8 |
| Latencia por intento | 5–6 s sin razonar; 10–17 s cuando razona | 6,8–8,5 s (media 7,9) |
| Coste | 0 (5,9 GB de VRAM) | 0,08 c/ask (28,4k tokens in + 3,7k out por 8 asks = 0,65 c); una hora de set a una frase cada 15 s ≈ 20 c |
| Variedad musical | alta: shaker, piano stabs, ride en vez de oh, arpegios, filtro del bajo | baja: 6 de 8 respuestas "abrir el filtro del bajo"; cambios tímidos |
| Dependencias | GPU compartida con ACE (no caben juntos) | red en el escenario; deja la GPU libre para ACE |
| Trabajo de código | ninguno | `mind_control.infer` responde 503 si el Main LLM no es LM Studio, `mind_supervisor` exige modelo residente, el servicio Mind apunta a `--base-url` de LM Studio: haría falta un transporte Azure en el playground y relajar las dos puertas |

Recomendación: gemma para el jueves (ya funciona y es la historia "todo local"). gpt-4o-mini
como plan B documentado si LM Studio falla en el escenario, o como opción de futuro cuando
ACE tenga que generar durante el algorave. No es un cambio para hacer antes de la demo.
