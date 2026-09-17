# S0 — Operar ACE-Step desde Apollo

## Plan y alcance

Objetivo: desde Generations se puede ver, arrancar y parar el servicio ACE,
sin pedir a Jarvis que ejecute un comando por cada lote. La instalación inicial
en el host sigue siendo una operación de despliegue.

Estado de esta primera entrega (2026-09-17): controlador, integración, interfaz
y plantillas implementados en `codex/s0-ace-control`, pendientes de revisión e
instalación en el host. No se ha arrancado ni parado el ACE real durante el trabajo.

1. Controlador en el host GPU: API autenticada, unidad systemd fija, estados
   observados y comandos idempotentes. No recibe comandos ni rutas del navegador.
2. Integración Apollo: permiso `manage_generator`, rutas de control, exclusión
   con generación/edición/inicio de directo y registro de operaciones.
3. Interfaz en Generations, visible con ACE apagado: estado, refresco, arranque,
   parada, trabajos pendientes y causas de bloqueo.
4. Pruebas de permisos, cola real, errores, carreras y comportamiento de UI.
5. Unidades y configuración de ejemplo; instalación y prueba real en Jarvis
   después de revisar los cambios y seguir el despliegue por PR del proyecto.

Decisiones para esta entrega:

- Arranque lazy (`--no-init`): iniciar el servicio no promete modelos cargados.
  El primer trabajo carga los modelos. Warm-up explícito y cambio de modelo
  quedan para una segunda entrega; requieren coordinar también todos los
  consumidores de LM Studio, incluido Algorave.
- Parada solo en reposo: trabajos en cola, ejecución o resultados aún pendientes
  de guardar impiden parar. No hay parada forzada ni `kill` desde la web.
  Drain automático queda pendiente; cerrar el navegador no debe abandonar una
  operación de drain, por lo que necesitará un trabajo persistente.
- El controlador usa systemd de usuario y solo `apollo-acestep.service`.
  Comandos acotados a cinco segundos; el estado posterior procede de systemd
  y `/health`. Un timeout no equivale a una operación fallida: refrescar estado.
- El acceso al controlador requiere un secreto distinto del de ACE. Apollo
  guarda ambos en servidor. Red privada/Tailscale o HTTPS, nunca HTTP público.
- El permiso nuevo pertenece a `apollo-admin` en Keycloak. Las cuentas locales
  mantienen sus permisos anteriores, pero registrarse localmente no concede
  control de procesos del host.
- Una instancia/proceso de Apollo y un proceso del controlador (la arquitectura
  Live actual ya mantiene el registro de sesiones en memoria). Un lock de Apollo
  serializa los cambios con admisión de trabajos y registro del directo. Toda
  generación gestionada debe pasar por Apollo; clientes directos de ACE o LM
  Studio quedan fuera de esa exclusión y deben detenerse durante los lotes.
- Configuración opt-in: sin `ACESTEP_CONTROL_URL` la integración existente sigue
  funcionando. Un controlador configurado pero caído bloquea operaciones GPU.

## Criterios de aceptación

- Un admin puede iniciar ACE apagado desde Generations y ver cuándo responde.
- Un usuario normal puede ver el estado, pero no iniciar/parar el servicio.
- Nunca interpretar cola desconocida como vacía, ni HTTP inaccesible como apagado.
- No parar durante trabajos ni antes de guardar los resultados conocidos por Apollo.
- No iniciar/generar con un directo activo o con modelos de LM Studio cargados.
- No abrir un directo mientras el servicio ACE gestionado esté encendido.
- No registrar tokens ni exponer comandos/configuración del host en el navegador.
- Pruebas sin GPU, sin servicios reales ni datos de producción.

## Instalación en Jarvis

Las plantillas están en `deploy/acestep/`. Revisar primero el proceso existente:
no instalar una segunda instancia sobre un ACE que ya escucha en 8001. Esperar
a que terminen trabajos/directos antes del cambio de gestión.

1. Tras merge y despliegue del código, copiar las dos unidades a
   `~/.config/systemd/user/`. Ajustar rutas si los repositorios no están en
   `~/code/`. El virtualenv de Apollo necesita el grupo `web` y el de ACE debe
   contener `acestep-api`.
2. Crear `~/.config/apollo/ace-control.env` a partir del ejemplo con modo 0600.
   Generar un secreto largo para `ACESTEP_CONTROL_TOKEN` (mínimo 32 caracteres).
   El controlador no carga `.env` del repositorio.
3. Revisar los parámetros/modelos del ACE actual y ponerlos en
   `~/.config/apollo/acestep.env`. ACE y el controlador deben compartir
   `ACESTEP_API_KEY`. Mantener `--no-init` y el puerto 8001 de la unidad.
4. `systemctl --user daemon-reload`, después
   `systemctl --user enable --now apollo-ace-control.service`.
   No habilitar ACE al arranque: lo arrancará Apollo. Si el servicio debe
   sobrevivir al logout, configurar linger para el usuario del host.
5. La unidad escucha en loopback: exponer 8010 solo mediante la red privada o
   un proxy HTTPS autenticado por el token; ajustar el bind para Tailscale si
   Apollo está en otro host. No publicar el puerto directamente en Internet.
6. En el backend de Apollo configurar `ACESTEP_CONTROL_URL`,
   `ACESTEP_CONTROL_TOKEN` y el `ACESTEP_BASE_URL` existente apuntando al mismo
   ACE. Un único worker de uvicorn. Reiniciar según las reglas de producción.
7. Volver a iniciar sesión como admin para obtener la nueva capacidad; abrir
   Generations. Probar arranque, un lote, guardar resultados y parada. Verificar
   la liberación de GPU en el host, sin inferirla solo de un ping HTTP.

Los estados `starting`/`stopping` se refrescan automáticamente. Un servicio activo
sin `/health` se muestra como `unresponsive`; el botón de parada no puede forzar
la terminación cuando no se puede conocer la cola. El operador puede consultar
`journalctl --user -u apollo-acestep -u apollo-ace-control` en el host.

Limitaciones de esta entrega: la guardia de resultados incluye todos los
usuarios; si otro usuario dejó un lote pendiente, debe usar Resume en su
biblioteca. La recogida automática de todos los lotes y el drain persistente
forman la siguiente entrega. La comprobación de LM Studio impide tomar una GPU
ocupada, pero no descarga sus modelos: si hay uno cargado, el operador debe
liberarlo primero. Tampoco impide que clientes externos vuelvan a cargarlo.
Parar ACE deja los archivos en disco; para escuchar takes no publicados hace
falta volver a arrancarlo, ya que su audio se sirve desde la API de ACE.

Rollback: quitar `ACESTEP_CONTROL_URL` y `ACESTEP_CONTROL_TOKEN` del backend,
reiniciar Apollo en ventana sin directo y volver al manejo manual del servicio.
No se migran ni eliminan archivos de audio o catálogo en S0.

## Validación de la entrega

- 269 tests backend: controlador, auth/roles, cola real, tareas/ediciones,
  bloqueo de parada con resultados pendientes y admisión del WebSocket de directo.
- 637 tests frontend (suite completa), incluido el nuevo control y la
  ausencia de reintentos automáticos ante bloqueo GPU.
- `npm run build -- --webpack`: compilación, tipos y prerender de producción OK.
  Se usó webpack porque las dependencias locales se reutilizaron por symlink
  fuera de la raíz del worktree; no se cambió el bundler del proyecto.
- Chromium sobre el build en 4011, APIs simuladas: stopped → start → botón
  Generate songs disponible → stop → botón de generación oculto. Sin pageerror.
- Lint de los componentes de servicio, cliente del generador y Generations OK.
- `tsc --noEmit` independiente detecta nueve errores en tests de Algorave
  no modificados por S0 (Pattern.midi y casts de mocks). No se ha dado ese
  comando por aprobado; el build de Next y los tests ejecutables sí pasan.
- Pendiente: prueba con systemd/ACE/GPU reales tras instalar las unidades y
  configurar la conectividad. Los tests no sustituyen esa comprobación.
