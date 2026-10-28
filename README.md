# ideology-app

Aplicación de consejo de voto (*voting advice application*, VAA) generada por IA para las elecciones generales españolas. El votante valora afirmaciones (*Statements*) generadas por la IA y obtiene un ranking de partidos por afinidad. Cada posición de partido (*Party Position*) se apoya en una cita literal de su programa electoral (*Evidence*, Evidencia), y los datos solo se publican tras pasar una Validación (*Validation*) automática: nadie edita a mano la salida de la IA. Las respuestas del votante nunca salen del navegador: el enlace para compartir (*Share Link*) las lleva en el fragmento de la URL (`#…`).

Datos publicados en `data/ideology.db`: la elección (*Election*) 1, "Elecciones generales 2023", con 9 partidos (*Parties*): PP, PSOE, VOX, SUMAR, ERC, JUNTS, EH Bildu, EAJ-PNV y BNG (CCa y UPN quedan fuera por decisión del proyecto). Está publicada la versión del dataset (*Dataset Version*) 3, con 26 afirmaciones.

Para entender el proyecto:

- [`CONTEXT.md`](CONTEXT.md): vocabulario del dominio (los términos en inglés que usan el código, la CLI y esta guía).
- [`docs/build-brief.md`](docs/build-brief.md): objetivos, no-objetivos y regla de afinidad.
- [`ARCHITECTURE.md`](ARCHITECTURE.md): capas, API y almacenamiento.
- [`DESIGN.md`](DESIGN.md): diseño de la interfaz.
- [`AGENTS.md`](AGENTS.md): instrucciones para agentes de IA que trabajan en el repositorio.

## Requisitos

- Python >= 3.12 (el `.venv` del equipo usa 3.15). `init.sh` usa `python3`, o el intérprete de `$PYTHON` si la defines.
- Node.js >= 22.13 y npm.
- git con acceso al repositorio, que es privado.
- Opcional: `sqlite3`, para inspeccionar la base de datos en solo lectura (`sqlite3 -readonly data/ideology.db`).
- Solo para generar con el pipeline: la CLI de Claude Code (`claude`) con una suscripción a Claude, o una clave de la API de Anthropic.
- Sistema: macOS o Linux. Los comandos del pipeline usan `caffeinate`, que solo existe en macOS: en Linux quítalo (`caffeinate -is`) y mantén el equipo despierto por otro medio (no hay ninguna herramienta de Linux probada). Windows no está cubierto: `init.sh` es bash.

## Puesta en marcha

```bash
git clone https://github.com/UmbilicalDev/ideology-app.git
cd ideology-app
./init.sh
```

`init.sh` es la puerta de verificación estándar y nunca arranca un servidor. En orden:

1. crea `.venv` si no existe;
2. comprueba la versión de Node;
3. instala la app con `pip install -e '.[dev]'`;
4. ejecuta pytest;
5. instala las dependencias web con `npm ci` (exactamente el `package-lock.json` versionado);
6. typecheck, Vitest y `vite build` del cliente web en `apps/web/dist`.

Termina con `All checks passed.`. En CI y en la documentación del proyecto se ejecuta como `CI=true ./init.sh`; usa esa forma tú también.

Arranca la app desde la raíz del repositorio, sobre la base de datos compartida:

```bash
DATABASE_URL=sqlite:///data/ideology.db .venv/bin/uvicorn ideology_app.main:app
```

y abre <http://127.0.0.1:8000/> (puerto por defecto de uvicorn). La portada muestra "Elecciones generales 2023".

> **Importante: `DATABASE_URL`.** Sin `DATABASE_URL` la app usa `sqlite:///ideology.db`, un fichero `ideology.db` en el directorio actual. Ese fichero se crea vacío, no tiene la elección de 2023 y `/api/v1/elections` responde 500 (`no such table`). El comando que imprime `init.sh` al final (`.venv/bin/uvicorn ideology_app.main:app --reload`) usa ese valor por defecto. Para ver los datos publicados, pon siempre `DATABASE_URL=sqlite:///data/ideology.db`.

Otras rutas del servidor:

- `/health` responde `{"status":"ok"}`.
- La API pública está bajo `/api/v1/`, con Swagger UI en `/api/docs` y OpenAPI en `/api/openapi.json`.
- `POST /api/v1/feedback` guarda una opinión anónima (`{"message": "...", "origin": "landing" | "results"}`, de 1 a 500 caracteres) en `FEEDBACK_DATABASE_URL` (por defecto `feedback.db` en el directorio actual, creado al arrancar). Para leerlas: `.venv/bin/ideology feedback list [--since AAAA-MM-DD]` (solo lectura, desde el mismo directorio).
- El cliente web se sirve desde `WEB_DIST_DIR` (por defecto `apps/web/dist`). Si falta `index.html`, el servidor registra un aviso y `/` responde 404: ejecuta `./init.sh` o `npm run build`.

Recarga en caliente del cliente (opcional), con uvicorn corriendo en el puerto 8000:

```bash
npm run dev -w @ideology-app/web
```

Vite arranca en su puerto por defecto y reenvía `/api` y `/health` a `http://127.0.0.1:8000`.

> **Atención: la base de datos compartida.** `data/ideology.db` está versionada en git y la comparte todo el equipo. No dejes un servidor ni un proceso `ideology` abierto sobre ella mientras haces `git pull`, cambias de rama o generas: git sustituye el fichero, y el proceso abierto sigue escribiendo en la copia antigua, así que esas escrituras se pierden. Detalles en [`docs/technical-discovery.md`](docs/technical-discovery.md) ("Shared database").

## Probarla

Con el servidor arrancado:

1. En la portada, elige "Elecciones generales 2023".
2. Responde el cuestionario (*Questionnaire*) de 26 afirmaciones en una escala de 5 puntos. Puedes usar "Saltar esta afirmación", marcar "Importante para mí" (cuenta doble) y volver con "Anterior".
3. Mira el ranking de partidos y el desglose por afirmación, con la cita de la Evidencia y su página. Cuando el documento tiene URL, la página es un enlace al PDF (`#page=N`); PSOE y VOX muestran solo la página.
4. En "Comparte tu resultado", "Copiar enlace" copia un enlace `/resultados#…`. Las respuestas van en el fragmento y no llegan al servidor.
5. La metodología está en `/metodologia` (enlace "Lee la metodología completa", en el apartado "Cómo funciona" de la portada).

API pública (solo lectura, GET):

- `/api/v1/elections`
- `/api/v1/elections/{id}`
- `/api/v1/elections/{id}/published-dataset-version`
- `/api/v1/dataset-versions/{id}`

Comprobaciones de solo lectura con la CLI:

```bash
DATABASE_URL=sqlite:///data/ideology.db .venv/bin/ideology db check
# Safe to commit: yes
DATABASE_URL=sqlite:///data/ideology.db .venv/bin/ideology data check data/elections/es-general-2023-07-23
# Database matches bundle es-general-2023-07-23: 9 documents
DATABASE_URL=sqlite:///data/ideology.db .venv/bin/ideology election list
# id  country  type     date        status  name
# 1   ES       general  2023-07-23  active  Elecciones generales 2023
```

## Tests

`CI=true ./init.sh` lo ejecuta todo. Pasos sueltos:

```bash
.venv/bin/python -m pytest                              # todo Python
.venv/bin/python -m pytest tests/test_cli_pipeline.py   # un fichero
npm test                                                # Vitest
npm run typecheck
npm run build
```

Los tests nunca llaman a un LLM real: usan el proveedor falso (*fake provider*). `tests/test_committed_database.py` comprueba la base de datos versionada (por ejemplo, que está en la última migración).

## Ejecutar el pipeline a mano

Esta sección resume los runbooks. La fuente detallada es [`docs/technical-discovery.md`](docs/technical-discovery.md) ("Local Claude Code CLI" y "Shared database"), y las specs [`shared-database`](docs/specs/shared-database.md), [`pipeline-run-checkpoint`](docs/specs/pipeline-run-checkpoint.md), [`pipeline-coverage-selection`](docs/specs/pipeline-coverage-selection.md), [`pipeline-verified-findings`](docs/specs/pipeline-verified-findings.md), [`source-text-bundle`](docs/specs/source-text-bundle.md), [`pipeline-run-report`](docs/specs/pipeline-run-report.md) y [`e2e-real-2023-election`](docs/specs/e2e-real-2023-election.md).

### Conceptos

- Una ejecución del pipeline (*Pipeline Run*) genera una bolsa de afirmaciones (*Statement Pool*) y las posiciones de cada partido, selecciona el cuestionario y lo valida.
- Si pasa la Validación, su versión del dataset se publica automáticamente y la elección pasa a `active`. Si falla, la versión queda como candidata y no se publica; la publicada sigue siendo la anterior.
- Las versiones del dataset son inmutables.
- `GENERATION_MODE`: `precomputed` (por defecto) o `live`. En `live`, los cambios de fuentes encolan ejecuciones, que se lanzan con `ideology pipeline run-queued`.
- Una sola ejecución activa a la vez en la base de datos compartida, para cualquier elección.
- Cada ejecución registra su proveedor y modelo (se ven en `pipeline list` y `pipeline report`).

### Configuración

Variables de entorno (lee `src/ideology_app/config.py`):

| Variable | Por defecto | Qué hace |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///ideology.db` | URL de SQLAlchemy. La base compartida es `sqlite:///data/ideology.db` (desde la raíz). También vale `ideology --database-url …`. |
| `LLM_PROVIDER` | `anthropic` | `anthropic`, `claude_code` o `fake`. |
| `LLM_MODEL` | según el proveedor | `anthropic`: `claude-sonnet-5-5`; `claude_code`: `claude-sonnet-4-6`; `fake`: `fake-model`. |
| `ANTHROPIC_API_KEY` | (ninguno) | Clave para `anthropic`. |
| `LLM_CLAUDE_CODE_BIN` | `claude` | Ejecutable de Claude Code. |
| `LLM_CLAUDE_CODE_TIMEOUT_SECONDS` | `900` | Límite de una llamada a la CLI. |
| `LLM_CLAUDE_CODE_MAX_WAIT_HOURS` | `48` | Espera máxima total por el límite de uso de la suscripción. |
| `GENERATION_MODE` | `precomputed` | `precomputed` o `live`. |
| `VALIDATION_MIN_PARTY_COVERAGE_PERCENT` | `50` | Cobertura mínima de cada partido. |
| `VALIDATION_MIN_STATEMENTS` | `25` | Mínimo de afirmaciones. |
| `VALIDATION_MAX_STATEMENTS` | `35` | Máximo de afirmaciones. |
| `VALIDATION_MAX_TOPIC_SHARE_PERCENT` | `30` | Peso máximo de un tema. |
| `ELECTIONS_DATA_DIR` | `data/elections` | Bundles de texto de los programas (*Source Text Bundles*). |
| `SOURCE_FILES_DIR` | `source_files` | PDFs subidos o descargados con `source add`. |
| `SOURCE_REFETCH_INTERVAL_HOURS` | `6` | Antigüedad mínima para que `source refetch` vuelva a descargar una URL. |
| `WEB_DIST_DIR` | `apps/web/dist` | Build del cliente web que sirve FastAPI. |
| `FEEDBACK_DATABASE_URL` | `sqlite:///feedback.db` | Almacén aparte de las opiniones anónimas (`POST /api/v1/feedback`), en el directorio actual e ignorado por git. No puede ser `data/ideology.db`, la base de `DATABASE_URL` ni una base en memoria: la app no arranca. También vale `ideology feedback --feedback-database-url …`. |

Los umbrales de Validación son valores por defecto del código decididos por el equipo. No los cambies para una ejecución concreta: por eso el comando de generación los desactiva con `env -u`.

### Elegir proveedor

**`claude_code`**: usa tu suscripción a Claude, sin clave de API, y solo en local.

- Inicia sesión una vez con `claude auth login`. Una sesión iniciada con clave de API se rechaza antes de empezar.
- `claude auth status` puede decir que tienes sesión aunque el token haya caducado. Antes de una ejecución larga haz una prueba: `claude -p "responde solo: ok"`. Si da 401, repite `claude auth login`.
- Al llegar al límite de uso, la ejecución imprime `claude_code: usage limit reached (task …); waiting until <hora> …` y espera dentro del proceso a que se reinicie, hasta `LLM_CLAUDE_CODE_MAX_WAIT_HOURS` en total.
- Mantén el equipo enchufado, con la tapa abierta, con `caffeinate -is`, y en una terminal que no vayas a cerrar.
- **Pon siempre `LLM_MODEL=claude-sonnet-5-5`.** El valor por defecto de `claude_code` es `claude-sonnet-4-6`, y las ejecuciones de la base compartida usaron `claude-sonnet-5-5`.

**`anthropic`**: uso de pago de la API con `ANTHROPIC_API_KEY`. La clave se lee en la primera llamada, no antes: si falta, igualmente se crea una ejecución `failed` con 0 llamadas (`ANTHROPIC_API_KEY is not set`). Compruébala antes de lanzar sobre la base compartida, porque esa fila acabaría en el fichero versionado.

Para reanudar una ejecución hay que usar el mismo proveedor y el mismo modelo.

### Paso a paso en la base compartida

1. Sin ningún servidor ni proceso `ideology` abierto, comprueba que `git status --short` sale vacío y haz `git pull`.
2. Avisa al equipo de que vas a generar.
3. Comprobaciones previas:

   ```bash
   DATABASE_URL=sqlite:///data/ideology.db .venv/bin/ideology db check   # Safe to commit: yes
   claude -p "responde solo: ok"                                          # solo con claude_code
   mkdir -p "$HOME/ideology-logs"
   ```

   Los logs quedan fuera del repositorio y nunca se versionan.
4. Lanza la ejecución nueva (para la elección 1; cambia `--election` para otra). Copia el comando entero; solo puedes cambiar el nombre del directorio de logs:

   ```bash
   caffeinate -is env -u VALIDATION_MIN_PARTY_COVERAGE_PERCENT -u VALIDATION_MIN_STATEMENTS -u VALIDATION_MAX_STATEMENTS -u VALIDATION_MAX_TOPIC_SHARE_PERCENT -u LLM_PROVIDER -u LLM_MODEL -u LLM_CLAUDE_CODE_BIN -u LLM_CLAUDE_CODE_TIMEOUT_SECONDS -u LLM_CLAUDE_CODE_MAX_WAIT_HOURS DATABASE_URL=sqlite:///data/ideology.db LLM_PROVIDER=claude_code LLM_MODEL=claude-sonnet-5-5 GENERATION_MODE=precomputed .venv/bin/ideology pipeline run --election 1 --yes 2>&1 | tee -ai "$HOME/ideology-logs/run.log"
   ```

5. Sin `--yes`, sobre la base compartida la CLI muestra un aviso y pregunta `Continue? [y/N]`. Si la entrada estándar no es una terminal, se niega: `Error: refusing to generate on the shared database without confirmation; pass --yes`.
6. Durante la ejecución no verás casi nada hasta el final: no hay progreso por llamada, solo las líneas del límite de uso. Al terminar verás:
   - si pasa: `Pipeline run R: passed (dataset version V, N statements, M party positions)` y `Published dataset version V for election E`;
   - si falla: `Error: pipeline run R failed: …; see "ideology pipeline checks --run R"`.
7. Tamaño de referencia para 2023 (9 partidos): unas 168 llamadas y unos 3,0 M tokens de entrada y 0,11 M de salida. Sin esperas por límite de uso tardó 902 s; la ejecución 2 tardó 9.390 s con una espera. Puede necesitar varias ventanas de uso.
8. Después, haz lo que dice "Paradas y reanudaciones" (comprobar, versionar la base y avisar), también cuando la ejecución termina.

### Paradas y reanudaciones

- Para parar, pulsa Ctrl-C una vez y espera a que el proceso salga. La ejecución termina `failed: interrupted`. Si el equipo se duerme o se apaga, una ejecución matada puede quedar en `running`.
- Cada llamada completada ya está guardada en la base.
- Después de terminar o parar:
  1. `DATABASE_URL=sqlite:///data/ideology.db .venv/bin/ideology db check` debe imprimir `Safe to commit: yes`. Si hay una ejecución sin terminar, la lista e indica `resume with --resume-from R`.
  2. Versiona **solo** la base: `git add data/ideology.db`, con un mensaje que nombre la ejecución y `--resume-from R`. Haz push y avisa al equipo.
  3. Durante una generación, los commits de la base van a la rama de trabajo, y llegan a `main` por PR.
- Para reanudar: el mismo comando más `--resume-from R`. Solo se piden al proveedor las llamadas que faltan.
- Protección de ejecuciones sin terminar: sobre la base compartida, una ejecución nueva se rechaza mientras la última ejecución con llamadas registradas de esa elección esté `running` o `failed`, no tenga versión del dataset y use el mismo proveedor y modelo. Ese mensaje significa "reanuda". Usa `--fresh` (empezar de cero) solo si lo decides a propósito.
- `--reuse-from R` vuelve a ejecutar después de una ejecución *terminada* (con versión del dataset, haya pasado o fallado), reutilizando con cero tokens las llamadas idénticas. Sirve, por ejemplo, tras cambiar un prompt o la selección.
- `--resume-from` y `--reuse-from` no se pueden combinar, y tampoco `--fresh` con `--resume-from`.
- Si un compañero reanuda en otro equipo, primero hace `git pull` y usa la misma revisión del código, el mismo proveedor y el mismo modelo.

### Leer los resultados

Todos son de solo lectura; usa el mismo prefijo `DATABASE_URL=sqlite:///data/ideology.db .venv/bin/ideology`:

- `pipeline list --election E`: las ejecuciones de una elección.
- `pipeline report --run R`: estado, proveedor y modelo, `prompt_versions`, llamadas y tokens, `resumed_from`/`reused_calls`, `validation_settings`, `statement_selection`, `selection_coverage` (cobertura por partido), `findings_check`, `publication` y el informe de Validación.
- `pipeline checks --run R`: los resultados de la Validación.
- `pipeline statements --dataset-version V`: las afirmaciones de una versión.
- `pipeline positions --dataset-version V [--party P]`: las posiciones con su Evidencia.
- `party list --election E`: los partidos y sus ids (`P` es un id de partido).
- `source list --party P`: los documentos fuente (*Source Documents*) de un partido.
- `source text --document D [--page N]`: el texto extraído de un documento.

### Cuando la Validación falla

- La ejecución obtiene una versión del dataset que no se publica; la publicada se mantiene.
- Lee `pipeline checks --run R` para ver qué comprobación falló.
- Nunca edites a mano la salida, la base de datos ni un `.md` de un bundle, y no bajes umbrales para una ejecución.
- Los cambios van por código (prompts, selección) y luego se vuelve a ejecutar con `--reuse-from R`.
- `pipeline validate --run R` existe solo para una ejecución que quedó en `validating`.

### Programas y elecciones

- Extraer el texto de un programa (no usa la base de datos):

  ```bash
  .venv/bin/ideology source extract PDF --party SHORT --out data/elections/<slug>/<fichero>.md [--url URL] [--force]
  ```

  Sin `--url` la Evidencia no muestra enlace. Nunca versiones un PDF ni edites un `.md`.
- Añade el fichero a `election.toml` (sigue el formato de [`data/elections/es-general-2023-07-23/election.toml`](data/elections/es-general-2023-07-23/election.toml)). Una elección nueva es un directorio `<slug>/` nuevo con su propio `election.toml`.
- Luego `db upgrade` y `data import data/elections/<slug>`, y comprueba con `data check data/elections/<slug>`. La importación es idempotente; un `.md` cambiado registra un documento que sustituye al anterior.
- Logos de partido (opcional): guarda el fichero del usuario en `data/elections/<slug>/logos/<partido>.svg` (o `.png` / `.webp`) y añade `logo = "logos/<partido>.svg"` a ese partido en `election.toml`. Solo PNG, WebP o SVG (por contenido), hasta 256 KiB, y un SVG sin scripts ni referencias externas. `data import` guarda el logo y `data check` lo compara; si un fichero se rechaza, no lo edites: devuélveselo al usuario.
- Fuera de un bundle: `party logo SHORT --election E --file F` o `--clear` (escribe en la base; en una elección con bundle, `data check` lo señalará hasta que `election.toml` declare el mismo fichero).
- Una elección importada queda en `draft` hasta su primera ejecución publicada.
- Tras una migración, ejecuta `db upgrade` sobre la base compartida. Un PR que añade una migración también versiona la base actualizada.
- Ambas escrituras siguen el ciclo pull → escribir → `db check` → commit → push, y nunca mientras alguien está generando. `data import` sobre la base compartida no pide confirmación.

### No hay ensayo gratis

- `LLM_PROVIDER=fake` desde la CLI falla en el acto con `Error: pipeline run N failed: FakeProvider has no response for task 'statement_candidates'` y deja una ejecución `failed` con 0 llamadas. El proveedor falso es solo para los tests. Nunca lo apuntes a `data/ideology.db`.
- No hay forma de ensayar sin gastar. Lo más parecido es la comprobación previa: el comando sin `--yes`, contestando `N`.

## Problemas frecuentes

- **401 o `` Claude Code is not logged in or its login expired; run `claude auth login` ``**: repite `claude auth login` y la prueba con `claude -p`.
- **`Claude Code CLI 'claude' not found on PATH`**: instala Claude Code o apunta `LLM_CLAUDE_CODE_BIN` al ejecutable.
- **La portada sale vacía o la API da 500**: falta `DATABASE_URL=sqlite:///data/ideology.db` (ver "Puesta en marcha").
- **`CERTIFICATE_VERIFY_FAILED`**: solo con `source add --url` en un Python sin certificados raíz. Usa `SSL_CERT_FILE=/etc/ssl/cert.pem`. No afecta a los bundles ni a las ejecuciones.
- **Conflicto de merge en `data/ideology.db`**: nunca mezcles dos ficheros. Quédate con un lado (`git checkout --ours data/ideology.db` o `--theirs`), repite `db upgrade` o `data import` si a ese lado le faltan, y reanuda.
- **`db check` lista un fichero `-journal`, `-wal` o `-shm`, o dice `Safe to commit: no`**: para todos los procesos y no versiones la base.
- **"has an unfinished run"**: ver "Paradas y reanudaciones".

## Más documentación

- [`docs/technical-discovery.md`](docs/technical-discovery.md): stack, configuración, runbooks.
- [`docs/domain-model.md`](docs/domain-model.md): entidades, ciclos de vida y comprobaciones de Validación.
- [`docs/risks-and-open-questions.md`](docs/risks-and-open-questions.md): riesgos y preguntas abiertas.
- [`CONSTRAINTS.md`](CONSTRAINTS.md): reglas operativas.
- [`docs/specs/`](docs/specs/): una spec por funcionalidad.
- [`PROGRESS.md`](PROGRESS.md): estado verificado y registro de sesiones.
