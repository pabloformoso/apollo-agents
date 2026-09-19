# Apollo · handoff de producto y plataforma

**Fecha:** 2026-09-19  
**Rama de referencia:** `main`  
**Commit desplegado:** `107f3fa` (`feat: manage session generation model`, PR #207)  
**Repositorio:** `https://github.com/pabloformoso/apollo-agents`

Este documento sustituye al handoff anterior, que describía un estado de agosto y ya no era una guía fiable para continuar el producto.

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

### Gestión de modelos de sesiones

La gestión de Mind y la gestión del modelo de sesiones son superficies distintas:

- **Mind** controla la mente del Algorave y su servicio host-side.
- **ACE** controla el servicio de generación musical.
- **Session intelligence** controla el modelo que extrae el brief y ejecuta la planificación de sesiones.

El nuevo router `web/backend/session_model.py` y el panel `SessionModelPanel.tsx` permiten a un administrador:

- consultar los modelos disponibles en LM Studio;
- ver cuál está cargado;
- seleccionar modelo, contexto y Flash Attention;
- persistir la configuración en `.tmp/session-model-settings.json`;
- cargar y descargar modelos;
- ver el error devuelto por LM Studio;
- bloquear cambios de residencia mientras hay una sesión live activa.

La selección persistida se resuelve en tiempo de ejecución por el parser y el pipeline, por lo que no requiere reiniciar Apollo. `BRIEF_MODEL`, cuando está definido explícitamente, conserva prioridad para la extracción del brief. `SESSION_MODEL` sirve como valor inicial y `APOLLO_SESSION_MODEL_SETTINGS_PATH` permite cambiar la ubicación del fichero.

La gestión funciona con el proveedor compatible con LM Studio configurado mediante `AGENT_PROVIDER=ollama` y `OLLAMA_BASE_URL`. No es todavía un selector abstracto para Anthropic, Azure o LiteLLM.

## Diagnóstico actual de Gemma

El servidor LM Studio remoto anuncia `google/gemma-4-e4b`, pero el primer intento se hizo mientras ACE tenía el modelo de audio residente en la misma GPU. En ese estado, una llamada directa y la carga desde Session Intelligence devolvían:

```text
Failed to load model "google/gemma-4-e4b".
```

La prueba aislada confirmó la causa: al detener ACE, Gemma E4B cargó en 2,5 s con contexto 4096 y respondió `OK`; después se descargó Gemma y se restauró ACE. El problema era la residencia compartida de GPU, no el identificador del modelo.

También se corrigió un fallo de contrato en el selector: antes el desplegable sólo cambiaba el estado React y **Load selected model** leía de nuevo `AGENT_MODEL`, por lo que siempre intentaba Gemma. Ahora Load envía y persiste el borrador elegido de forma atómica. Si ACE mantiene la GPU ocupada, Apollo responde 409 con instrucciones para detenerlo, en lugar de propagar un 500 opaco de LM Studio.

La operación recomendada es detener ACE, cargar el modelo de sesiones con el contexto adecuado, validar brief + planificación y volver a iniciar ACE cuando se vaya a generar audio.

## Decisiones de arquitectura que deben mantenerse

1. **Una fuente de verdad para géneros.** Las ventanas BPM, estilo y demás metadata deben derivarse de `agent/genres.py`. No duplicarlas en React.
2. **Separación de responsabilidades.** ACE genera audio; el modelo de sesiones planifica; Mind atiende Algorave. No mezclar sus ciclos de carga ni sus estados en un único panel.
3. **El modelo no controla el callback de audio.** La planificación y las decisiones agénticas pueden ser asíncronas, pero la reproducción y el timing de audio siguen en el motor.
4. **El usuario conserva la decisión irreversible.** Publicar una take, construir una sesión o poner algo en directo debe seguir siendo una acción explícita.
5. **Persistencia server-side de la operación.** La selección del modelo no debe depender del estado React ni de una edición manual de `.env`; los cambios deben ser auditables y reaplicables al reiniciar.
6. **El README habla del producto.** Los detalles de despliegue, contratos y arquitectura deben permanecer en `CONTRIBUTING.md`, `CLAUDE.md` y `docs/`.
7. **La nomenclatura debe converger.** Apollo es el producto; “AI Music Entertainment System” es su categoría. Aún no hay una decisión final entre AMES, AMEP o MEPAI, así que no introducir esas siglas en rutas, APIs o nombres de componentes.

## Pendiente prioritario

### P0 · Resolver la carga del modelo de sesiones

- Validar en producción el flujo coordinado: detener ACE, cargar Session Intelligence, ejecutar una sesión completa y volver a iniciar ACE.
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

- `tests/web/test_session_model.py`: 8 pasadas.
- `tests/web/test_brief_parser.py`: 62 pasadas.
- `tests/web/test_pipeline_v260.py`: 7 pasadas.
- `tests/web/test_mind_control.py`: 14 pasadas.
- ESLint específico de los archivos frontend nuevos: correcto.
- Prueba React del selector: 1 pasada; verifica que Load envía el modelo seleccionado.
- `npm run build`: correcto.
- CI de PR #207: backend Python 3.12/3.13, frontend, E2E y Algorave: todo verde.

El lint completo tiene los fallos heredados descritos arriba; no son introducidos por el panel de modelo.

## Comandos de continuidad

```bash
git switch main
git pull --ff-only

git status --short --branch
git log -1 --oneline

docker compose ps
curl -fsS -o /dev/null -w '%{http_code}\n' https://apollo.pabloformoso.com/settings

# Backend afectado por el modelo de sesiones
docker compose run --rm -T backend uv run pytest -q tests/web/test_session_model.py tests/web/test_brief_parser.py tests/web/test_pipeline_v260.py

# Frontend
docker compose run --rm frontend npm run build
```

Antes de tocar un worktree, comprobar si está bloqueado y si tiene una tarea activa. No incluir nunca `.env`, tokens de LM Studio ni claves de proveedores en commits o handoffs públicos.
