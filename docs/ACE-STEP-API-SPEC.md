# ACE-Step 1.5 — Especificación de API para la integración con Apollo

**Versión:** 1.0 (2026-08-29) · **Autor:** sesión ACE-Step (Pablo Formoso)
**Audiencia:** agentes del proyecto apollo-agents que van a construir el modo "generación de canciones" (UX tipo Suno) dentro del wizard de generación de sesiones de Apollo.

ACE-Step 1.5 es un modelo de generación de música (canción completa con voz a partir de caption + letra). Este documento especifica su API HTTP, cómo consumirla desde Apollo, y el puente hacia el contrato de catálogo (`tracks/tracks.json`). **No modificar el repo de ACE-Step**: todo lo de Apollo se construye contra esta API.

---

## 1. Despliegue y conexión

| Ítem | Valor |
| :--- | :--- |
| Proceso | `uv run acestep-api --host 0.0.0.0 --port 8001` (repo `~/code/ACE-Step-1.5` en la máquina de Pablo) |
| Base URL | `http://<ip-maquina-pablo>:8001` (LAN; no colisiona con puertos Apollo 4010/4020/4011/4021/4031/4032) |
| Auth | Opcional. Si `ACESTEP_API_KEY` está definido: header `Authorization: Bearer <key>` o campo `ai_token` en el body |
| Docs interactivas | `GET /docs` (FastAPI) |
| Health | `GET /health` |
| Carga del servidor | `GET /v1/stats` → jobs queued/running, `avg_job_seconds`, tamaño de cola |

**⚠️ GPU compartida (protocolo de VRAM):** la GPU de 16 GB se comparte con el LM Studio del DJ de Apollo. El server ACE-Step hace lazy-load (no toca VRAM hasta el primer request), pero **una vez cargado retiene ~12.5 GB**. Reglas: no invocar generación durante un directo (`docker logs --since 30m apollo-backend | grep live-ws` para comprobar); al terminar un lote, parar el server o coordinarlo con Pablo. Diseñad el flujo de Apollo asumiendo que ACE-Step puede estar apagado: comprobar `/health` y, si no responde, mostrar "generador no disponible" en vez de fallar.

---

## 2. Modelo de ejecución: asíncrono con polling

1. `POST /release_task` → devuelve `task_id` (encolado).
2. `POST /query_result` con `task_id_list` (acepta batch) → repetir hasta `status` = `1` (ok) o `2` (fallo). Polling recomendado: cada 2–5 s; usar `avg_job_seconds` de `/v1/stats` para estimar ETA en la UI.
3. `GET /v1/audio?path=<url-encoded>` → descarga del fichero (la URL viene ya montada en el campo `file` del resultado).

**Wrapper de todas las respuestas:**

```json
{ "data": { ... }, "code": 200, "error": null, "timestamp": 1700000000000, "extra": null }
```

Errores HTTP: `400` request inválido · `401` API key · `415` Content-Type · `429` cola llena (`ACESTEP_QUEUE_MAXSIZE`=200 por defecto; reintentar con backoff) · `500` error interno.

---

## 3. `POST /release_task` — crear generación

`Content-Type: application/json` (o `multipart/form-data` si se sube audio). Acepta snake_case y camelCase; los metadatos pueden ir anidados en `metas`/`metadata`.

### 3.1 Superficie "modo Suno" (lo que expone la UI simple)

| Parámetro | Tipo | Default | Uso en la UI |
| :--- | :--- | :--- | :--- |
| `prompt` (alias `caption`) | string | `""` | Descripción del estilo/género ("dark melodic techno, hypnotic") |
| `lyrics` | string | `""` | Letra con marcadores `[Verse]`, `[Chorus]`… (vacío = instrumental) |
| `sample_query` (alias `description`) | string | `""` | Modo descripción: una frase natural y el LM inventa caption+letra+metas. Requiere `thinking: true` |
| `use_format` | bool | `false` | El LM pule/estructura el caption y la letra que dé el usuario |
| `thinking` | bool | `false` | **Recomendado `true`**: el LM 5Hz planifica los códigos de audio → mejor calidad. (Se ignora automáticamente en `cover`/`repaint`/`extract`) |
| `audio_duration` (alias `duration`) | float | null | Segundos, rango 10–600. **Para catálogo Apollo: ≥ 120** |
| `vocal_language` | string | `"en"` | Idioma de la voz (`en`, `es`, `zh`, `ja`…) |
| `bpm` | int | null | 30–300. Si se omite, el LM lo completa — **capturar siempre el valor final** (§5) |
| `key_scale` | string | `""` | Ej. `"C Major"`, `"A Minor"`. Si se omite, lo completa el LM |
| `batch_size` | int | `2` | Nº de takes por request (máx. 8) → en Apollo son variantes `variant_of` |
| `audio_format` | string | `"mp3"` | **Para catálogo: `"wav"`** (48 kHz — ver §5). Otros: `flac`, `mp3`, `opus`, `aac`, `wav32` |

### 3.2 Panel "Experimental" (avanzados, colapsados por defecto)

| Parámetro | Tipo | Default | Notas |
| :--- | :--- | :--- | :--- |
| `inference_steps` | int | `8` | Turbo: 1–20 (recom. 8). Base: 1–200 (recom. 32–64) |
| `guidance_scale` | float | `7.0` | Solo modelo base |
| `seed` / `use_random_seed` | int / bool | `-1` / `true` | Reproducibilidad; el resultado devuelve `seed_value` usado |
| `time_signature` | string | `""` | `2`,`3`,`4`,`6` (= 2/4, 3/4, 4/4, 6/8) |
| `model` | string | null | DiT a usar; listar con `GET /v1/models` |
| `shift` | float | `3.0` | 1.0–5.0, solo modelo base |
| `infer_method` | string | `"ode"` | `ode` (Euler, rápido) o `sde` (estocástico) |
| `timesteps` | string | null | CSV custom; anula `inference_steps` y `shift` |
| `use_adg`, `cfg_interval_start/end` | bool/float | `false`/0.0–1.0 | Guidance avanzado (base) |
| `lm_temperature`, `lm_cfg_scale`, `lm_top_k`, `lm_top_p`, `lm_repetition_penalty`, `lm_negative_prompt` | — | 0.85 / 2.5 / null / 0.9 / 1.0 / — | Sampling del LM 5Hz |
| `use_cot_caption`, `use_cot_language`, `constrained_decoding` | bool | `true` | CoT del LM: reescritura de caption / detección de idioma / decoding restringido |

### 3.3 Edición de canciones (para el paso "modificar antes de verificar la playlist")

El wizard de Apollo puede reeditar un take antes de darlo por bueno:

| Parámetro | Tipo | Notas |
| :--- | :--- | :--- |
| `task_type` | string | `text2music` (default) · `repaint` (regenerar un tramo) · `cover` (versión sobre audio fuente) · `complete` (continuación) · `lego` · `extract` |
| `src_audio_path` | string | Ruta absoluta EN el server del audio fuente, o subir fichero por multipart (campo `src_audio` / `ctx_audio`) |
| `reference_audio_path` | string | Referencia de estilo (o multipart `reference_audio` / `ref_audio`) |
| `repainting_start` / `repainting_end` | float | Segundos; `end=-1` = hasta el final. Con `chunk_mask_mode: "explicit"` el rango se respeta como máscara exacta |
| `audio_cover_strength` | float | 0.0–1.0 (bajo ≈ 0.2 para style transfer) |

Ejemplo de repaint (regenerar los segundos 10–20 de un take):

```bash
curl -X POST $BASE/release_task \
  -F "prompt=same style, more energy" -F "task_type=repaint" \
  -F "src_audio=@take.wav" -F "repainting_start=10" -F "repainting_end=20" \
  -F "chunk_mask_mode=explicit" -F "audio_format=wav"
```

**Respuesta de `/release_task`:** `{"data": {"task_id": "...", "status": "queued", "queue_position": N}}`

---

## 4. `POST /query_result` — resultado

Body: `{"task_id_list": ["<id1>", "<id2>"]}` (batch). Cada entrada: `{"task_id", "status", "result"}` donde **`result` es un string JSON** que hay que parsear; contiene una lista con un elemento por take del batch:

| Campo | Descripción |
| :--- | :--- |
| `file` | URL relativa de descarga (`/v1/audio?path=...`) — anteponer la base URL |
| `status` | 0 en curso · 1 ok · 2 fallo |
| `prompt`, `lyrics` | Los realmente usados (tras CoT/format del LM) |
| `metas` | `{bpm, duration, genres, keyscale, timesignature}` — **los valores finales de generación** |
| `seed_value` | Semillas usadas (CSV, una por take) |
| `lm_model`, `dit_model`, `generation_info`, `create_time` | Trazabilidad |

---

## 5. Puente al catálogo de Apollo (lado Apollo)

Contrato destino: WAV estéreo 44.1 kHz/16-bit, ≥ 120 s, en `tracks/<genre_folder>/` + entrada en `tracks/tracks.json` `{id, display_name, file, genre_folder, genre, camelot_key, bpm, variant_of}`.

Pasos del publicador tras `status=1`:

1. **Descargar** cada take con `audio_format: "wav"` ya pedido en el release.
2. **Resamplear 48 kHz → 44.1 kHz/16-bit** (la salida nativa de ACE-Step es 48 kHz):
   `ffmpeg -i take.wav -ar 44100 -sample_fmt s16 -ac 2 out.wav`
3. **BPM y key**: usar `metas.bpm` y `metas.keyscale` del resultado (son los de generación — NO dejar que madmom los adivine; BPMs envenenados ya causaron derivas de género en directo). Convertir `keyscale` → Camelot:

   | Camelot | Minor (A) | Major (B) |
   | :--- | :--- | :--- |
   | 1 | Ab/G# Minor | B Major |
   | 2 | Eb/D# Minor | F#/Gb Major |
   | 3 | Bb/A# Minor | Db/C# Major |
   | 4 | F Minor | Ab/G# Major |
   | 5 | C Minor | Eb/D# Major |
   | 6 | G Minor | Bb/A# Major |
   | 7 | D Minor | F Major |
   | 8 | A Minor | C Major |
   | 9 | E Minor | G Major |
   | 10 | B Minor | D Major |
   | 11 | F#/Gb Minor | A Major |
   | 12 | C#/Db Minor | E Major |

4. **Variantes**: los N takes de un mismo `release_task` comparten pieza → un id por take y `variant_of` apuntando al take elegido como principal.
5. **Validaciones antes de ingestar**: duración ≥ 120 s (si no, no elegible para sesiones), `genre_folder` existente (género nuevo = checklist coordinado, no improvisarlo), y bpm dentro de la ventana del género (`BPM_GENRE_RANGES` es una octava exacta — al generar, fijar `bpm` dentro de la ventana del género destino en el propio `release_task`).
6. **Ingesta v1**: dejar el WAV en la carpeta y correr el builder (backup de `tracks.json` antes; escribe solo al final). La ingesta v2 (`--ingest` con sidecar `{bpm, key, display_name, variant_of}`) la especifica la sesión Apollo — no construirla desde este lado.
7. Sin portada (la genera Apollo). Letra: guardar `lyrics` del resultado como sidecar `.lrc`/`.txt` opcional (hoy ignorado, futuro overlay de directos).
8. Primer lote: avisar a la sesión Apollo para que valide la primera entrada antes de que el builder la haga canon.

**Consejo de generación por género:** pasar siempre `bpm` explícito (centro de la ventana del género), `audio_duration ≥ 150`, `thinking: true`, y el género en el `prompt`. Así `metas` vuelve coherente con el catálogo sin depender del autocompletado.

---

## 6. Endpoints auxiliares

| Endpoint | Método | Uso |
| :--- | :--- | :--- |
| `/format_input` | POST | LLM pule caption+letra sin generar (`{prompt, lyrics, temperature, param_obj}`) — útil para el botón "mejorar" del wizard |
| `/create_random_sample` | POST | Rellena el formulario con un ejemplo (`{"sample_type": "simple_mode"|"custom_mode"}`) |
| `/v1/models` | GET | Modelos DiT disponibles y default |
| `/v1/init` | POST | Cargar/cambiar modelo bajo demanda sin reiniciar (`{model, slot, init_llm, lm_model_path}`) — relevante para el protocolo de VRAM |
| `/v1/stats` | GET | Cola y tiempos medios |
| `/health` | GET | Vivo/no vivo (usar como feature-flag del generador en la UI) |

## 7. Flujo completo de referencia

```
POST /release_task
  {"prompt": "dark melodic techno, hypnotic, driving", "lyrics": "",
   "thinking": true, "bpm": 126, "audio_duration": 180,
   "batch_size": 2, "audio_format": "wav", "key_scale": "A Minor"}
→ task_id

loop cada 3 s:
  POST /query_result {"task_id_list": [task_id]}
  hasta status ∈ {1, 2}

si 1: parsear result (string JSON) → por cada take:
  GET  /v1/audio?path=...           → take_N.wav (48 kHz)
  ffmpeg -ar 44100 -sample_fmt s16  → tracks/<genre>/<id>.wav
  metas.bpm + camelot(metas.keyscale) + variant_of → tracks.json (vía builder)
```
