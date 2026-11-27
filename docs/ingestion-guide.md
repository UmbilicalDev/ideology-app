# Guía de ingesta v2 (fases 1–4)

Esta guía lleva una Election desde cero hasta una Dataset Version v2 publicada, y explica cómo reformular después una Statement confusa. Está escrita para el Operador. Los términos del dominio y de la CLI (Party, Constituency, Source Text Bundle, Ingestion Ledger, Proposal, Pipeline Run, Dataset Version…) se dejan en inglés, como en `README.md` y `CONTEXT.md`. El detalle técnico de cada fase está en `docs/technical-discovery.md`; aquí no se copia.

Hay una sola fuente de verdad para saber qué falta: el comando de solo lectura

```bash
.venv/bin/ideology ingestion next DIR
```

Mira el bundle (`DIR`), el Ingestion Ledger y la base de datos, e imprime el **primer paso pendiente**: fase, código de paso, qué falta, en qué fichero, con qué formato, el comando siguiente, si gasta LLM (proveedor, modelo y llamadas previstas) y qué escribe en la base de datos compartida. No escribe nada, abre SQLite solo en modo lectura (`mode=ro`), no crea la base de datos si no existe y no construye ningún proveedor LLM. Sale con código 0 en todos los pasos, también en `done`.

Con un agente: «Use $ingestion-guide on data/elections/<slug>» (skill `.agents/skills/ingestion-guide/SKILL.md`). El agente repite `ingestion next`, te pide exactamente los datos que faltan, ejecuta solo comandos permitidos y te pide aprobación antes de cada gasto de LLM.

## 0. Antes de empezar

### Qué base de datos usar

- **Scratch** (pruebas, ensayos): un fichero propio, p. ej. `DATABASE_URL=sqlite:///$HOME/ideology-scratch/ingesta.db`. Nadie más lo usa; se puede borrar.
- **Compartida**: `DATABASE_URL=sqlite:///data/ideology.db` desde la raíz del repo. Se comparte por git; `proposals extract` y `pipeline run-v2` piden confirmación (`--yes` la salta) y rechazan un shell no interactivo sin `--yes`; `data import` y `db upgrade` no tienen `--yes` ni preguntan.

Exporta siempre la misma `DATABASE_URL` para `ingestion next` y para los comandos que te indica. La línea `Database:` de `next` dice cuál está leyendo.

### Ciclo de la base de datos compartida

Antes de cada comando que escribe en `data/ideology.db` (`db upgrade`, `data import`, `proposals extract`, `pipeline run-v2`), confirma tres cosas:

1. `git status --short` está limpio y has hecho `git pull`.
2. Nadie más está generando (una sola ejecución activa a la vez, de cualquier Election). Avisa al equipo.
3. Ningún proceso ni servidor `ideology` tiene el fichero abierto.

Después: `ideology db check` (debe decir `Safe to commit: yes`) y commit de los ficheros del bundle, del ledger y de `data/ideology.db` en el mismo PR. Quien revisa el PR lee el diff de `ingestion-ledger.json`: cada cambio debe corresponder a un comando del Operador (el ledger nunca se edita a mano). `next` añade líneas `Note:` cuando hay otra ejecución sin terminar o una extracción `in_progress`.

### Proveedor y modelo

`LLM_PROVIDER` (`anthropic` por defecto, o `claude_code` con tu suscripción local) y `LLM_MODEL` (p. ej. `LLM_MODEL=claude-sonnet-5-5`). Una extracción en curso queda fijada a su proveedor y modelo, y `--resume-from` / `--reuse-from` exigen los de la ejecución de origen: `next` los imprime en esos casos. Para ejecuciones largas con `claude_code`: `caffeinate -is` y la salida a `$HOME/ideology-logs/` (ver `docs/technical-discovery.md`, Integrations).

## Costes

Estimaciones para la Election de 2026 (12 programas, unas 1.000 páginas), copiadas de `docs/technical-discovery.md`. Son supuestos, no medidas: **comprobar antes de usar** (precio de lista de Sonnet, $3 / $15 por millón de tokens). `next` imprime el número exacto (o el máximo) de llamadas previstas para tu caso.

| Fase | Comando | Llamadas | `anthropic` | `claude_code` |
|---|---|---|---|---|
| 3 extraer Proposals | `proposals extract` | 225 (una por bloque de 12.000 caracteres) | $8–12 | 2,5–3,5 h |
| 3 conflictos | `conflicts detect` | 80–240 (4–8 solapamientos) | $2–7 | 1–3 h |
| 4 generar Statements | `pipeline run-v2` | 245–410 | $8–12 (hasta $15) | 3–5 h |
| Reformulación | `pipeline run-v2 --reuse-from R` | 1 por entrada nueva o cambiada si nada cambió en las fases 1–3 desde R; si no, como una ejecución completa | céntimos (o como la fase 4) | minutos (o como la fase 4) |

Los programas regionales suben la fase 3 un 20–40 %. Las llamadas ya registradas no se repiten: se puede repartir el trabajo en varias sesiones con `--max-calls K`.

## Fase 1: candidaturas por circunscripción

**Qué necesitas**: tipo y fecha de la elección, y la proclamación de candidaturas del BOE (para cada candidatura: siglas, nombre completo de la papeleta y circunscripciones). Nunca datos inventados ni de memoria.

1. Crea el directorio y copia la plantilla (paso `create-bundle-directory`, después `write-manifest` si el directorio ya existía):

   ```bash
   mkdir -p data/elections/es-general-2030-06-02
   cp docs/templates/election-format-2.toml data/elections/es-general-2030-06-02/election.toml
   ```

   El nombre es `<país>-<tipo>-<fecha>` en minúsculas con la fecha ISO, y debe coincidir con `[election]`.
2. Rellena cada marcador de la plantilla (paso `fill-manifest-placeholders`; `next` lista cada `line N:`). Cada valor va entre comillas (`"PP"`), salvo la fecha (`2030-06-02`, sin comillas). Mientras quede un marcador, el fichero no es TOML válido y ningún comando lo acepta.
   - `[election]`: `country`, `type`, `date`, `name`.
   - `[candidatures]`: `source` (la proclamación del BOE) y `url` opcional.
   - `[[parties]]`: `short_name`, `name` y `constituencies` (`"all"` o una lista de códigos INE como `["08", "17"]`; `ideology constituency list` los imprime). `logo = "logos/siglas.svg"` opcional.
3. Si `next` da `fix-manifest`, el error dice fichero y línea; corrígelo. `convert-to-format-2` aparece con un bundle antiguo (formato 1): v2 necesita formato 2 (la conversión de 2026 es de `e2e-2026-constituencies`).
4. `declare-candidatures`: toda circunscripción (01–52) necesita al menos una candidatura. `next` lista las que faltan (`51 Ceuta`, `52 Melilla`…); añádelas desde el BOE.

## Fase 2: programas y revisión

**Qué necesitas**: el PDF oficial del programa de cada Party (guárdalo **fuera de `data/`**; nunca se sube un PDF) y su URL pública, o la decisión del Operador de que no hay programa.

1. `provide-manifestos`: por cada Party sin documento:

   ```bash
   .venv/bin/ideology source extract ~/programas/pp.pdf --party PP --out DIR/pp.md --url https://…/programa.pdf
   ```

   y un bloque `[[documents]]` en `election.toml` (`file`, `parties`; opcionales `constituencies` para el ámbito y `joint_for` para el programa conjunto de una coalición). Si no hay programa: `ideology ingestion no-manifesto DIR SIGLAS --note "dónde se buscó"`.
2. `repair-ledger`: el ledger no se puede leer (p. ej. tras un conflicto de merge). Toma un lado del fichero y repite los comandos del otro; nunca lo edites a mano.
3. `update-ledger`: `ideology ingestion update DIR` crea o pone al día `ingestion-ledger.json`. N (`--min-proposals`, 30 al crearlo) es una decisión del Operador.
4. `review-manifestos`: por fichero, `ideology ingestion review DIR FICHERO` muestra páginas, páginas sin texto y caracteres. Lee el `.md` y decide: `--keep`, o `--discard no-text-layer|not-a-manifesto|incomplete` con `--note` opcional. La decisión vale para todas las Parties que lo listan.

Las fases 1 y 2 no necesitan base de datos. Commit del bundle y del ledger.

## Fase 3: Proposals

1. `create-database` / `upgrade-database`: `ideology db upgrade` sobre una base scratch. La compartida no se crea: se restaura con git; una migración en la compartida la aplica el PR que la añade.
2. `import-bundle`: `ideology data import DIR` y después `ideology data check DIR`. Escribe en la base de datos.
3. `extract-proposals`: **gasta LLM**. `next` da las llamadas que faltan (bloques pendientes) y el proveedor y modelo (los fijados si hay una extracción en curso). `ideology proposals extract DIR --max-calls K`; repite hasta que no quede nada.
4. `fix-proposal-counts`: los recuentos del ledger no coinciden con las Proposals guardadas. `ideology proposals extract DIR` los registra con 0 llamadas.
5. `check-conflicts`: **gasta LLM**. Dos documentos de la misma Party con ámbitos que se cruzan forman un solapamiento. `ideology conflicts detect DIR --max-calls K` (escribe solo el ledger).
6. `decide-conflicts`: `ideology conflicts show DIR SIGLAS A.md B.md` y después `ideology conflicts decide DIR SIGLAS --prevails A.md --over B.md --reason "…"`. El ganador y el motivo los decide el Operador.

Commit del ledger y de `data/ideology.db` (tras `db check`).

## Fase 4: Statements

1. `phase4-blocked`: la puerta de la fase 4 rechaza; cada línea dice qué comando la desbloquea (`ideology ingestion gate DIR`).
2. `resume-run`: la última ejecución v2 con llamadas registradas quedó `failed` o `running` sin Dataset Version. `next` imprime `pipeline run-v2 DIR --resume-from R` con el proveedor y modelo de R. Si está `running`, puede seguir viva en otra máquina: confirma antes.
3. `generate-statements`: **gasta LLM** (3–5 h con `claude_code`). Ejecútalo en tu propia terminal:

   ```bash
   mkdir -p $HOME/ideology-logs
   caffeinate -is .venv/bin/ideology pipeline run-v2 DIR 2>&1 | tee $HOME/ideology-logs/<slug>-run-v2.log
   ```

   Una ejecución aprobada se publica.
4. `read-failed-run`: la ejecución terminó con Dataset Version pero falló Validation. Lee `ideology pipeline checks --run R` y `ideology pipeline report --run R`; corrige la causa y vuelve a ejecutar (`--reuse-from R` reutiliza las llamadas idénticas).
5. `done`: hay una Dataset Version v2 publicada y el fichero de reformulaciones coincide con el que usó la ejecución. `next` imprime la versión, el resumen de circunscripciones y de reformulaciones, y las que no se aplicaron. Revisa `ideology pipeline report --run R` y `ideology db check`.

`next` no detecta que algo de las fases 1–3 cambió después de la ejecución publicada (G10): tras cualquier cambio en esas fases, vuelve a ejecutar `pipeline run-v2 DIR`.

## Reformular una Statement confusa

`reword-statements` aparece cuando `DIR/statement-rewordings.toml` se añade, cambia o se borra respecto a la última ejecución. Formato:

```toml
format = 1

[[rewordings]]
ai_text = "texto exacto de la IA (copiado de ideology pipeline statements --run R)"
text = "la nueva redacción del Operador"
reason = "por qué la original confunde"
```

`ai_text` se copia exacto; `text` y `reason` los escribe el Operador. Las Context Notes no se reformulan. Después `pipeline run-v2 DIR --reuse-from R` (mismo proveedor y modelo que R): reutiliza borradores, posiciones y las comprobaciones ya hechas, y hace una llamada de equivalencia por entrada nueva o cambiada. Eso solo vale si nada cambió en las fases 1–3 desde R (una revisión, una extracción, un conflicto decidido de nuevo…): `next` no lo detecta, y entonces la reejecución es completa (`next` da también la cifra máxima, «up to P»). Una ejecución con el proveedor `fake` (datos de desarrollo) no se puede reejecutar desde la CLI. Una reformulación que cambia el sentido se rechaza y queda el texto de la IA.

## Retomar el trabajo

No hace falta recordar dónde te quedaste: `ingestion next DIR` lo deduce de los ficheros del bundle, del ledger y de la base de datos. Haz `git pull`, exporta la misma `DATABASE_URL` y ejecútalo. `ideology ingestion status DIR` muestra el estado por Party.

## Tabla de pasos

| Fase | Paso | Cuándo | Qué hacer |
|---|---|---|---|
| 1 | `create-bundle-directory` | no existe DIR | `mkdir -p` + copiar la plantilla |
| 1 | `write-manifest` | falta `election.toml` | copiar la plantilla |
| 1 | `fill-manifest-placeholders` | quedan marcadores | rellenar cada línea listada |
| 1 | `fix-manifest` | el bundle no se puede leer | corregir según el error |
| 1 | `convert-to-format-2` | manifiesto formato 1 | convertir a formato 2 |
| 1 | `declare-candidatures` | circunscripciones sin candidatura | añadir desde el BOE |
| 2 | `provide-manifestos` | Party sin documento ni `no-manifesto` | `source extract` + `[[documents]]`, o `no-manifesto` |
| 2 | `repair-ledger` | ledger ilegible | tomar un lado y repetir comandos |
| 2 | `update-ledger` | ledger ausente o desfasado | `ingestion update` |
| 2 | `review-manifestos` | documento sin revisión | `ingestion review --keep/--discard` |
| 3 | `create-database` | sin base o sin inicializar | `db upgrade` (compartida: git) |
| 3 | `upgrade-database` | migración antigua | `db upgrade` |
| 3 | `import-bundle` | la base no coincide con el bundle | `data import`, `data check` |
| 3 | `extract-proposals` | documento conservado sin extraer | `proposals extract --max-calls K` (LLM) |
| 3 | `fix-proposal-counts` | recuentos distintos | `proposals extract` (0 llamadas) |
| 3 | `check-conflicts` | solapamiento sin comprobar | `conflicts detect --max-calls K` (LLM) |
| 3 | `decide-conflicts` | contradicciones sin decidir | `conflicts show` + `conflicts decide` |
| 4 | `phase4-blocked` | la puerta rechaza | ver cada línea |
| 4 | `resume-run` | ejecución sin terminar | `run-v2 --resume-from R` (LLM) |
| 4 | `generate-statements` | sin Dataset Version v2 | `run-v2` en tu terminal (LLM) |
| 4 | `read-failed-run` | última ejecución falló Validation | `pipeline checks` / `report` |
| 4 | `reword-statements` | fichero de reformulaciones cambiado | `run-v2 --reuse-from R` (LLM) |
| 4 | `done` | publicado y al día | revisar; reformular si hace falta |

## Nunca

- Nunca edites a mano un `.md` del bundle (se reescribe con `source extract --force`), el `ingestion-ledger.json` (solo los comandos `ingestion`, `conflicts` y `proposals`) ni la base de datos.
- Nunca edites la salida de la IA: Proposals, Statements y Party Positions solo cambian con una nueva ejecución; una Statement solo cambia de texto con una reformulación comprobada.
- Nunca subas un PDF.
- Nunca bajes los umbrales (`VALIDATION_V2_MIN_STATEMENTS`, `VALIDATION_V2_MIN_PARTY_SIDES`, N) para que una ejecución pase.
- Nunca importes datos de desarrollo (`data/dev/`) en la base compartida ni en producción.
- Nunca inventes candidaturas, circunscripciones, nombres ni URLs de programas.
