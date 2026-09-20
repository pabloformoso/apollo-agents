# Apollo · handoff de producto y plataforma

**Fecha:** 2026-09-19  
**Rama de referencia:** `main`  
**Commit desplegado:** `748227c` (`fix: apply selected session model safely`, PR #208)  
**Repositorio:** `https://github.com/pabloformoso/apollo-agents`

Este documento sustituye al handoff anterior, que describía un estado de agosto y ya no era una guía fiable para continuar el producto.

**Corrección (2026-09-19, tarde).** La versión anterior de este handoff interpretó mal la instrucción sobre la pantalla de Settings: presentaba "Mind" y "Session intelligence" como dos modelos con dos paneles, cuando son el **mismo LLM**. Desde la rama `claude/handoff-settings-screen-1qayie` Settings tiene exactamente dos residentes de la GPU: el **Main LLM** (todo lo que Apollo piensa: brief, planificación, DJ en directo y Mind de Algorave) y **ACE** (el generador de canciones, tal y como estaba). La sección "Gestión de modelos" y la decisión de arquitectura 2 están reescritas abajo.

## Estado actual

`main` está sincronizada con `origin/main`. Las PR de esta línea de trabajo están integradas:

| PR | Cambio | Estado |
| --- | --- | --- |
| [#202](https://github.com/pabloformoso/apollo-agents/pull/202) | Gestión de Mind y Settings | Mergeada |
| [#203](https://github.com/pabloformoso/apollo-agents/pull/203) | Identidad de producto, navegación y documentación | Mergeada |
| [#204](https://github.com/pabloformoso/apollo-agents/pull/204) | Flujo de generación ACE-Step parametrizable | Mergeada |
| [#205](https://github.com/pabloformoso/apollo-agents/pull/205) | Dashboard como entrada principal de Apollo | Mergeada |
| [#206](https://github.com/pabloformoso/apollo-agents/pull/206) | Rediseño de Sign in | Mergeada |
| [#207](https://github.com/pabloformoso/apollo-agents/pull/207) | Gestión del modelo de sesiones | Mergeada |
| [#208](https://github.com/pabloformoso/apollo-agents/pull/208) | Load aplica la selección del desplegable; 409 si ACE ocupa la GPU | Mergeada |
| `claude/handoff-settings-screen-1qayie` | Un solo **Main LLM** en Settings (Mind + sesiones unificados); ACE sin cambios | En PR |

El stack local se reinició después del último merge. En la última comprobación, backend y frontend estaban activos, `/settings` local respondía `200` y `https://apollo.pabloformoso.com/settings` respondía `200`.

El único fichero sin seguimiento en el checkout principal es `loops/beatmatch-learn/measurements.jsonl`. Es un artefacto de datos local y no forma parte de estos cambios.

## Trabajo entregado

### Identidad y documentación de Apollo

Apollo se presenta ahora como un **AI Music Entertainment System**. El nombre del producto sigue siendo Apollo; la categoría es una descripción de posicionamiento, no un cambio de marca. El README se reescribió alrededor de las experiencias del producto y dejó la arquitectura detallada en la documentación técnica. También se añadió `CONTRIBUTING.md`.

La navegación y el `Shell` usan la misma gramática visual Ember: superficies oscuras, tipografía display en cursiva, etiquetas monoespaciadas, color ember y componentes compartidos. Las superficies principales son Library, Generations, Catalog, Create, Perform y Algorave.

### Dashboard / Home

`/dashboard` es ahora la entrada de producto después del login. Incluye:

- hero con la última sesión completada y su artwork cuando existe;
- fallback visual con el patrón ember cuando no hay artwork;
- módulos para Catalog, Generate music, Build a session y Algorave;
- bloque de sesiones recientes para volver a una sesión existente;
- estadísticas básicas de sesiones y duración;
- `DashboardPlayer` persistente en la parte inferior.

El dashboard obtiene sesiones y catálogo desde SQLite mediante los endpoints existentes. El artwork destacado procede del track de la sesión cuando existe una portada; todavía no hay un servicio de selección aleatoria de artwork independiente.

### Sign in

`/login` tiene una entrada de producto dividida y responsive: formulario de acceso, tratamiento visual del sistema, roles Collaborators/Critic/Performer y mensaje “AI directed · human shaped”. Se conservaron tanto el login local como el flujo OIDC/Keycloak cuando el realm está configurado.

### Generador ACE-Step 1.5

La creación de canciones dejó de depender únicamente de un prompt libre y del nombre de la carpeta de género. El contrato actual permite controlar explícitamente:

- descripción de la canción;
- estilo musical editable, inicialmente derivado de `agent.genres`;
- género/carpeta de destino;
- BPM, con valor sugerido y ventana por género;
- duración entre 120 y 600 segundos;
- letra y lenguaje vocal;
- batch de 1 a 8 takes;
- seed y modo de seed aleatorio;
- tonalidad/escala y compás;
- inference steps experimentales;
- `use_format` para el formateador de ACE-Step.

La metadata de géneros sale del backend en `GET /api/generator/genres`, de modo que el frontend no mantiene una copia independiente de ventanas BPM y estilos. El backend compone `style_prompt + prompt`, valida el límite de caption de 512 caracteres de ACE-Step 1.5 y conserva el `genre_folder` como destino de catálogo. Un género no convierte automáticamente cualquier texto de estilo en una carpeta válida.

La UI muestra el caption combinado y evita truncar silenciosamente las palabras del usuario. Los errores del backend, incluidos 409 por conflicto de GPU y 503 por servicio apagado, se muestran en el diálogo.

### Main LLM y ACE: los dos residentes de la GPU

Settings tiene dos paneles, uno por residente de la GPU compartida:

- **Main LLM** es el único modelo de LM Studio con el que Apollo piensa: extracción del brief, planificación de sesiones, DJ en directo y **Mind de Algorave**. Se elige, se carga y se descarga desde un solo sitio.
- **ACE** es el servicio de generación musical. No es un LLM y no ha cambiado.

Lo que había antes (PR #202 + #207) eran dos paneles para un mismo modelo: "Session intelligence" cargaba por la API REST de LM Studio y "Mind" cargaba **otra copia** en el host con `lms load --identifier apollo-mind`, cada uno con su fichero de settings y su botón Load. Pulsar los dos ponía dos copias del mismo LLM en los 16 GB que ACE comparte. Eso es lo que se ha deshecho:

- `web/backend/main_llm.py` (router `/api/main-llm`, antes `session_model.py`) es la única gestión de modelo: inventario, selección (modelo, contexto, Flash Attention), load/unload por REST, persistencia en `.tmp/main-llm-settings.json` (`APOLLO_MAIN_LLM_SETTINGS_PATH`). El fichero antiguo `.tmp/session-model-settings.json` se sigue leyendo hasta el primer guardado, así que la selección hecha en prod sobrevive al cambio.
- Todos los consumidores resuelven el modelo por `main_llm.persisted_model()` / `current_model()`: `brief_parser`, `pipeline`, el crítico de `generator.py` y la inferencia del Mind. Nombrar un modelo distinto al residente provoca un JIT load de una segunda copia; por eso no hay selector por consumidor.
- El gateway `/api/mind` conserva sólo **start/stop del servicio** y `infer`, que fija `model` al Main LLM. El supervisor host (`mind_supervisor.py`) ya no tiene settings, alias ni load/unload: reenvía una petición sólo si `lms ps` muestra ese modelo residente y el servicio está activo. La unidad `apollo-mind.service` arranca el playground con `--any-model` (sirve el modelo que nombra cada petición) en lugar de `--model apollo-mind`.
- `MainLlmPanel.tsx` reemplaza a `SessionModelPanel.tsx` y `MindServicePanel.tsx`; incluye el bloque "Algorave Mind service" (Start/Stop). El botón de la página Algorave abre este mismo panel.
- **Unload** se rechaza mientras el Mind informa de una respuesta en vuelo o un transporte sin resolver (la petición sobrevive al navegador; el modelo debe sobrevivir a la petición).
- Ha desaparecido el opt-in `allow_shared_gpu`: el protocolo de la GPU es simétrico y sin excepciones. El supervisor de ACE rechaza arrancar mientras haya cualquier modelo residente en LM Studio.
- `SESSION_MODEL` ya no existe; `AGENT_MODEL` es el valor inicial. `BRIEF_MODEL` y `GENERATIVE_MODEL` siguen siendo overrides explícitos de entorno **por encima** de la selección de Settings.

La gestión funciona con el proveedor compatible con LM Studio configurado mediante `AGENT_PROVIDER=ollama` y `OLLAMA_BASE_URL`. No es todavía un selector abstracto para Anthropic, Azure o LiteLLM.

## Diagnóstico actual de Gemma

El servidor LM Studio remoto anuncia `google/gemma-4-e4b`, pero el primer intento se hizo mientras ACE tenía el modelo de audio residente en la misma GPU. En ese estado, una llamada directa y la carga desde Session Intelligence devolvían:

```text
Failed to load model "google/gemma-4-e4b".
```

La prueba aislada confirmó la causa: al detener ACE, Gemma E4B cargó en 2,5 s con contexto 4096 y respondió `OK`; después se descargó Gemma y se restauró ACE. El problema era la residencia compartida de GPU, no el identificador del modelo.

También se corrigió un fallo de contrato en el selector: antes el desplegable sólo cambiaba el estado React y **Load selected model** leía de nuevo `AGENT_MODEL`, por lo que siempre intentaba Gemma. Ahora Load envía y persiste el borrador elegido de forma atómica. Si ACE mantiene la GPU ocupada, Apollo responde 409 con instrucciones para detenerlo, en lugar de propagar un 500 opaco de LM Studio.

La operación recomendada es detener ACE, cargar el Main LLM con el contexto adecuado, validar brief + planificación (y el Mind, si se va a tocar en Algorave: Start Mind en el mismo panel) y volver a iniciar ACE cuando se vaya a generar audio, descargando antes el Main LLM.

## Decisiones de arquitectura que deben mantenerse

1. **Una fuente de verdad para géneros.** Las ventanas BPM, estilo y demás metadata deben derivarse de `agent/genres.py`. No duplicarlas en React.
2. **Dos residentes de la GPU, dos paneles.** ACE genera audio y es un servicio propio. Todo lo demás que piensa — brief, planificación, DJ en directo y Mind de Algorave — es **un solo LLM**, el Main LLM, con una sola selección y un solo ciclo de carga. El Mind es un *servicio* (start/stop) que usa ese modelo, nunca un segundo modelo. No volver a separar "modelo de sesiones" y "modelo del Mind": un segundo nombre es un segundo JIT load en la misma GPU.
3. **El modelo no controla el callback de audio.** La planificación y las decisiones agénticas pueden ser asíncronas, pero la reproducción y el timing de audio siguen en el motor.
4. **El usuario conserva la decisión irreversible.** Publicar una take, construir una sesión o poner algo en directo debe seguir siendo una acción explícita.
5. **Persistencia server-side de la operación.** La selección del modelo no debe depender del estado React ni de una edición manual de `.env`; los cambios deben ser auditables y reaplicables al reiniciar.
6. **El README habla del producto.** Los detalles de despliegue, contratos y arquitectura deben permanecer en `CONTRIBUTING.md`, `CLAUDE.md` y `docs/`.
7. **La nomenclatura debe converger.** Apollo es el producto; “AI Music Entertainment System” es su categoría. Aún no hay una decisión final entre AMES, AMEP o MEPAI, así que no introducir esas siglas en rutas, APIs o nombres de componentes.

## Pendiente prioritario

### P0 · Desplegar y validar el Main LLM unificado

- Desplegar la rama en el host GPU además del checkout principal: `mind_supervisor.py` forma parte del controlador ACE (`apollo-ace-control.service`) y la unidad `apollo-mind.service` ha cambiado su `ExecStart` (`--any-model`); hace falta `systemctl --user daemon-reload` y reiniciar el controlador **sin una petición del Mind en vuelo**.
- Validar en producción el flujo coordinado: detener ACE, cargar el Main LLM desde Settings, ejecutar una sesión completa, arrancar el Mind y pedirle una mutación en `/algorave` (comprobar en `lms ps` que sólo hay **una** instancia), descargar el Main LLM y volver a iniciar ACE.
- Probar un modelo alternativo desde Settings y comparar latencia, tool calling y calidad musical frente a Gemma E4B.
- Decidir si el contexto 4096 y la residencia exclusiva deben quedar documentados como default operativo.

### P1 · Validar el generador con música real

- Probar varios géneros, no sólo Healing/lofi, con BPM dentro y fuera de la ventana sugerida.
- Comparar qué produce ACE-Step cuando el estilo va en `style_prompt`, cuando se edita manualmente y cuando se usa sólo descripción.
- Revisar si `use_format` debe ser visible para usuarios normales o quedarse en Experimental.
- Añadir casos E2E que comprueben que cambiar género, BPM y estilo cambia realmente el payload enviado al backend.
- Verificar publicación: una take generada a BPM fuera de la ventana del género puede necesitar otro género de catálogo aunque ACE haya respetado el BPM solicitado.

### P1 · Cerrar la experiencia Home

- Añadir selección de artwork aleatorio o una imagen editorial cuando no exista un track destacado.
- Decidir si las sesiones recientes deben mostrar estado `draft`, `curating`, `ready` y `published` con acciones diferentes.
- Unificar el player inferior con las colas del catálogo y de Generations.
- Probar dashboard, login y settings en móvil; el artwork orbital del login se oculta deliberadamente en pantallas pequeñas.

### P2 · Salud técnica del frontend

El build, E2E y los checks de CI están verdes. El lint completo de ESLint local todavía informa errores heredados en `curate`, `editor`, `GreetingOverlay`, `Dialog`, `ModeSwitcher`, `TrackPicker`, `feedback`, `auth-bootstrap`, `auto-session`, `live` y `viewer`. Deben corregirse en una tarea separada para no mezclar una limpieza transversal con cambios de producto.

### P2 · Limpieza de worktrees

Los worktrees temporales inspeccionados no tenían modificaciones sin commitear. Las ramas principales asociadas a este trabajo están mergeadas: `codex/catalog-player`, `codex/dashboard-home`, `codex/dashboard-responsive`, `codex/generator-parameterized`, `codex/interface-product-system`, `codex/mind-settings`, `codex/s0-ace-control` y `codex/track-processing`.

También existen worktrees antiguos de agentes para ramas ya mergeadas (`feat/db-migrations`, `feat/telemetry-package`, `feature/healing-session-progress-65aa20`, `resolve/197`). Algunos están marcados como `locked` por procesos de agente. No borrarlos mientras sigan bloqueados; cuando no haya procesos activos, se pueden retirar con `git worktree remove` y eliminar las ramas remotas que ya no tengan una PR abierta.

## Verificación realizada en este ciclo

Rama `claude/handoff-settings-screen-1qayie` (unificación del Main LLM):

- `tests/web/test_main_llm.py` (antes `test_session_model.py`): 16 pasadas, incluida la lectura del fichero legado y el rechazo de unload con el Mind respondiendo.
- `tests/web/test_mind_control.py`: 17 pasadas; pinan que `/api/mind` ya no tiene load/unload/settings, que `infer` fija el Main LLM y que el host sólo reenvía con el modelo residente.
- `tests/test_algorave_playground.py`: `--any-model` cubierto (7 pruebas nuevas).
- `tests/web/test_generator_critique.py`: la precedencia del crítico incluye la selección de Settings.
- `tests/web/test_brief_parser.py`, `test_pipeline_v260.py`, `test_ace_control.py`: verdes.
- Vitest `__tests__/main-llm.test.tsx` (4) y `mind-route.test.ts` (3): verdes. ESLint de los archivos tocados: limpio. `tsc --noEmit`: 9 errores, los mismos 9 que en `main` (ficheros de test heredados).

Ciclo anterior (PR #207/#208): `test_brief_parser.py` 62, `test_pipeline_v260.py` 7, `npm run build` correcto, CI verde.

El lint completo tiene los fallos heredados descritos arriba; no son introducidos por el panel de modelo.

## Comandos de continuidad

```bash
git switch main
git pull --ff-only

git status --short --branch
git log -1 --oneline

docker compose ps
curl -fsS -o /dev/null -w '%{http_code}\n' https://apollo.pabloformoso.com/settings

# Backend afectado por el Main LLM
docker compose run --rm -T backend uv run pytest -q tests/web/test_main_llm.py tests/web/test_mind_control.py tests/web/test_brief_parser.py tests/web/test_pipeline_v260.py tests/test_algorave_playground.py

# Frontend
docker compose run --rm frontend npm run build
```

Antes de tocar un worktree, comprobar si está bloqueado y si tiene una tarea activa. No incluir nunca `.env`, tokens de LM Studio ni claves de proveedores en commits o handoffs públicos.
