# Guía de estudio – HumanIA: agente de contratos laborales con IA local

> Enfoque: **conceptos técnicos y decisiones de diseño** para exponer el trabajo. El código aparece solo
> cuando ayuda a explicar una idea. Cada sección termina con "Si te preguntan…".

---

## 1. La idea en 30 segundos (elevator pitch)

HumanIA S.A. necesita armar **contratos de trabajo** sin errores y **sin que una IA invente texto legal**.
El sistema deja que el responsable de RR. HH. **converse en lenguaje natural** (o suba un DNI/PDF/foto) y
un agente va ordenando los datos. Pero el modelo de lenguaje (LLM) **solo extrae y clasifica**:

- Las **cláusulas legales son fijas** (aprobadas por la empresa); nunca las redacta la IA.
- Todo dato pasa por **validación determinista** (reglas fijas, sin IA).
- Si un dato es dudoso o contradice otro, el sistema **pregunta** en lugar de adivinar.
- **Aprobar es siempre una decisión humana** (un revisor), nunca del agente.

**Frase clave para la exposición:** *"Usamos la IA donde es buena (entender texto desordenado) y reglas
deterministas donde un error es caro (datos legales y aprobación)."*

---

## 2. Stack tecnológico y por qué cada pieza

| Pieza | Qué es | Para qué se usa acá |
|---|---|---|
| **Python 3.11 + uv** | Lenguaje y gestor de paquetes | Todo el backend; `uv` fija versiones (`uv.lock`) |
| **Pydantic v2** | Validación de datos con tipos | Modelo del contrato, validadores, esquema del LLM |
| **FastAPI** | Framework web | API REST + documentación automática (`/docs`, OpenAPI) |
| **Ollama** | Servidor para correr LLMs | Ejecuta el modelo de texto/visión y los embeddings |
| **deepseek-v4.1-flash:cloud** | LLM (por defecto) | Extraer datos y clasificar intención. `:cloud` = corre en Ollama Cloud |
| **nomic-embed-text** | Modelo de embeddings **local** | Convierte texto en vectores para el RAG |
| **ChromaDB** | Base de datos vectorial | Guarda los vectores y busca por similitud |
| **LangGraph** | Orquestador de agentes (grafos de estados) | El flujo del agente conversacional |
| **SQLite** | Base de datos embebida | Contratos (JSON), auditoría e historial de chat |
| **docxtpl (Jinja2) + python-docx** | Plantillas Word | Rellena el contrato `.docx` sin tocar las cláusulas |
| **LibreOffice (soffice)** | Suite ofimática en modo headless | Convierte DOCX → PDF |
| **PyMuPDF** | Librería de PDF | Leer PDFs, rasterizar páginas, marca de agua, verificar texto |
| **pytest** | Tests | Pruebas unitarias sin red + pruebas de integración opcionales |

**"IA local":** los embeddings y el RAG corren en la máquina (Ollama + Chroma). El LLM por defecto es un
modelo `:cloud` (se puede cambiar por uno 100 % local con una variable de entorno). Por eso el `.env.example`
avisa: *con modelos cloud, usar solo datos ficticios*.

**Si te preguntan "¿por qué Ollama?"** → Permite cambiar de modelo (local o cloud) tocando solo configuración,
con la misma API; el código no depende de un proveedor.

---

## 3. Arquitectura en capas

```
 Frontend (SPA)  ──HTTP──▶  API (FastAPI)  ──▶  Agente (LangGraph)  ──▶  Servicios  ──▶  Repositorios (SQLite)
                              │                    │                       │
                         auth, roles,         clasifica intención,     validación, extracción,
                         rate limit,          ejecuta acciones         RAG, plantillas, exportación
                         headers seguridad          │
                                                    └── Seguridad transversal (anti-inyección, filtro de salida)
```

Carpetas (`app/`):

- `schemas/` → **dominio**: modelos Pydantic (`ContractData`, `EmployeeData`, `CompanyData`, `LaborTerms`).
- `domain/` → **máquina de estados** del contrato.
- `services/` → lógica de negocio (extracción, validación, RAG, plantillas, exportación, chat…).
- `agent/` → el agente: grafo, clasificador de intención, guardrails, textos de respuesta.
- `security/` → detección de inyección, filtro de salida, rate limit, normalización de texto.
- `repositories/` → persistencia (SQLite).
- `api/` → FastAPI: routers, autenticación, esquemas de entrada/salida.
- `container.py` → **raíz de composición**: arma todo y conecta las dependencias.
- `core/` → configuración y excepciones.

### Patrones de diseño que conviene nombrar

1. **Puertos y adaptadores (arquitectura hexagonal):** `LLMClient`, `EmbeddingClient`, `ContractRepository`,
   `PdfConverter` son *interfaces* (`Protocol`). Hay una implementación concreta (Ollama, SQLite, LibreOffice),
   pero los servicios dependen de la interfaz → fácil de testear con falsos (*fakes*) y de reemplazar.
2. **Inyección de dependencias + raíz de composición:** `build_services()` construye todo en un solo lugar.
3. **Single Source of Truth:** `ContractData` es la única fuente de verdad del contrato. Solo
   `ContractService` lo modifica y lo persiste; el LLM **nunca** escribe directo.
4. **Configuración por entorno:** `Settings` (pydantic-settings) lee variables `HUMANIA_*` con valores seguros por defecto.
5. **Excepciones de dominio:** todas heredan de `HumanIAError`; la API las traduce a respuestas claras.

---

## 4. El modelo del contrato (capa de dominio)

`ContractData` agrupa tres secciones: **empleado**, **empresa** y **condiciones laborales**, más:
`status`, `validation_flags` (resultado de validar cada campo), `collected_values` (datos aceptados aún sin
ensamblar) y `missing_fields`.

**Ideas importantes:**

- **Modelos estrictos** (`extra="forbid"`): ni el OCR ni el LLM pueden "colar" campos no previstos.
- **Recolección incremental:** los datos llegan de a poco; se guardan en `collected_values` (con ruta tipo
  `employee.dni`) y, cuando una sección está completa y válida, se **ensambla** el modelo de esa sección.
- **Validaciones deterministas de negocio:**
  - **DNI:** 7–8 dígitos.
  - **CUIL/CUIT:** formato `XX-XXXXXXXX-X` y **dígito verificador** (módulo 11 con pesos 5,4,3,2,7,6,5,4,3,2).
  - **El CUIL debe contener el DNI** (cruce entre campos).
  - **Remuneración:** mayor a 0, máximo 2 decimales (`Decimal`, no `float`, para dinero).
- **Modalidades** (`EmploymentType`): indeterminado, plazo fijo, a prueba, tiempo parcial. **Solo hay plantilla
  aprobada para "indeterminado"**; el resto se informa como no disponible en vez de improvisar.

**Si te preguntan "¿por qué Decimal y no float?"** → Los `float` tienen errores de redondeo binario; en dinero
hay que usar decimales exactos.

---

## 5. Máquina de estados

```
INITIAL ──primer dato──▶ COLLECTING_DATA ◀──────────────────┐
                           │    ▲                            │ el revisor pide cambios
      dato dudoso /        ▼    │ usuario confirma           │
      contradictorio    CONFLICT_DETECTED                    │
                           │                                 │
      completo y sin conflictos                              │
                           ▼                                 │
                    PENDING_HUMAN_REVIEW ────────────────────┘
                       │            │
                  aprueba        rechaza
                       ▼            ▼
                   APPROVED      REJECTED   (estados terminales)
```

- Una **tabla de transiciones permitidas** (`ALLOWED_TRANSITIONS`) es la única verdad sobre qué cambios son válidos.
- **Guardas de negocio:** para entrar a revisión el contrato debe estar completo y sin conflictos; para
  `CONFLICT_DETECTED` debe haber al menos un conflicto.
- **`APPROVED` no se alcanza por la máquina de estados**, solo vía `mark_as_reviewed()` (que aplica sus propias
  guardas). Así no hay "atajos" de código para aprobar.
- `APPROVED` y `REJECTED` son **terminales**: no hay vuelta atrás.

---

## 6. Extracción de datos con LLM (el corazón de la "IA")

**Objetivo:** convertir un mensaje desordenado o un documento (DNI, PDF, foto) en *candidatos* de campo
(`FieldCandidate`: campo, valor, confianza, origen). **No escribe nada en el contrato.**

### Técnicas para que el LLM sea confiable

1. **Salida estructurada (structured output):** se le pasa un **JSON Schema** (generado desde un modelo
   Pydantic) en el parámetro `format` de Ollama. El modelo solo puede responder JSON con esa forma.
   Los nombres de campo son un `Literal` cerrado: **no puede proponer campos nuevos**.
2. **`temperature=0`** y tope de tokens de salida → respuestas lo más deterministas y acotadas posible.
3. **Evidencia literal (grounding):** por cada dato, el modelo debe citar el fragmento textual del que lo leyó.
   El sistema **verifica por código** que esa evidencia exista en la fuente y respalde el valor.
4. **Si no hay respaldo → se limita la confianza a 0.5** (por debajo del umbral 0.80) → fuerza una
   **confirmación humana**. Nunca se "descarta en silencio" ni se acepta a ciegas.
5. **Reconciliación con la evidencia:** para montos, fechas y modalidad, si el modelo transcribió mal pero la
   evidencia admite una única lectura, se corrige de forma determinista.
6. **Normalización determinista** (`normalization.py`): `15/03/1995`, `15 de marzo de 1995` o `15 MAR 1995`
   → `1995-03-15`; `$ 2.500.000,50` → `2500000.50` (formato es-AR); "a prueba" → `TRIAL_PERIOD`.
   Si no se puede normalizar, se deja tal cual y la validación lo rechaza: **nunca se adivina**.
7. **Reintentos:** si la respuesta no cumple el esquema, se reintenta hasta 2 veces avisando al modelo del error.
8. **Valores contradictorios del propio modelo** sobre un mismo campo → se baja la confianza y se avisa.
9. **Multimodalidad:** si hay imágenes se usa el **modelo de visión**; si hay texto, el de texto. Los PDF con
   capa de texto se leen directo; los **escaneados se rasterizan a PNG reducido** (lado máx. 1280 px) para el modelo de visión.

**Si te preguntan "¿y si el LLM alucina?"** → Hay tres barreras: (1) esquema cerrado, (2) evidencia verificada
contra la fuente, (3) validación determinista + confirmación humana ante cualquier duda. Además el LLM no
puede modificar el contrato ni redactar cláusulas.

---

## 7. Validación cruzada y conflictos (`ValidationService`)

Para cada candidato decide **sin IA**:

| Resultado | Cuándo | Qué pasa |
|---|---|---|
| **REJECTED** | Campo desconocido o valor inválido según el esquema | No se aplica; se informa el motivo |
| **CONFLICT** | El valor difiere del ya aceptado **o** la confianza < umbral (0.80) | Queda **pendiente de confirmación**; el contrato pasa a `CONFLICT_DETECTED` |
| **ACCEPTED** | Válido, consistente y con buena confianza | Pasa a `collected_values` |

- La comparación usa una **forma canónica** (`canonical`) para no generar falsos conflictos por formato
  (puntos del DNI, mayúsculas, espacios, formato de fecha).
- Un rechazo **no pisa** un valor ya aceptado.
- El usuario resuelve conflictos con **"sí" (usar el nuevo valor) o "no" (mantener el anterior)**, ya sea por
  chat o con un endpoint dedicado.
- Todo queda en una **auditoría** (`audit_log`): quién, cuándo, qué acción, en qué estado.

---

## 8. El agente conversacional (LangGraph)

**LangGraph** modela el agente como un **grafo de estados**: nodos (funciones) y aristas (transiciones).
El flujo es **fijo y predecible**, no un agente que "decide libremente" qué herramientas usar.

```
START → classify → (arista condicional por intención) → [nodo de acción] → compose → END
```

**Nodos de acción:** `provide_data`, `resolve_conflict`, `ask_info` (RAG), `submit_review`, `show_status`,
`show_draft`, `refuse`, `small_talk`. `compose` arma la respuesta final y agrega el **siguiente paso** calculado
desde el estado del contrato.

### Clasificación de intención (de lo más a lo menos determinista)

1. **Guardrails por patrón (regex):** si piden *aprobar/firmar* o *modificar cláusulas* → se rechaza sin llamar al modelo.
2. **Atajo sí/no** cuando hay un conflicto pendiente.
3. **LLM con salida restringida** a un conjunto **cerrado** de intenciones (`PROVIDE_DATA`, `ASK_INFO`, `SHOW_DRAFT`…).
4. **Fallback:** si el LLM falla, se asume `SMALL_TALK` (**no cambia el estado del contrato**).

### Propiedades de seguridad del diseño

- **El grafo no tiene acceso a `review`/`mark_as_reviewed`:** aunque alguien engañe al modelo, **no existe
  ninguna ruta de código** para que el agente apruebe o rechace.
- **El LLM nunca redacta texto sobre el contrato:** las respuestas salen de **plantillas fijas** (`replies.py`)
  rellenadas con valores ya validados.
- **El estado no vive en el grafo:** cada turno es independiente y reconstruye todo desde el repositorio.

**Si te preguntan "¿por qué un grafo y no un agente con herramientas?"** → Para un dominio legal queremos
**control y auditabilidad**: el flujo es acotado, cada acción está en una función conocida y el modelo solo
elige entre intenciones permitidas.

---

## 9. RAG: consultas sobre cláusulas y documentación

**RAG = Retrieval-Augmented Generation:** primero se **recuperan** fragmentos relevantes y luego el LLM
responde **usando solo esos fragmentos**.

**Indexación:**

1. Fuentes: las **cláusulas aprobadas** + documentos (PDF/MD/TXT) de `data/knowledge`.
2. **Chunking:** se trocea por párrafos hasta ~800 caracteres, con ~100 de **solape** para no perder contexto.
3. **Embeddings** con `nomic-embed-text` (local). Requiere **prefijos de tarea**: `search_document:` al indexar
   y `search_query:` al consultar.
4. Se guardan en **ChromaDB** con espacio de distancia **coseno**; los ids son **deterministas** (hash) →
   reindexar es idempotente.

**Consulta:**

1. Se embebe la pregunta y se buscan los **top-k (6)** fragmentos más similares.
2. Se descartan los que tengan **similitud coseno < 0.5**.
3. El LLM responde en JSON `{found, answer, source_ids}`, **citando ids de fragmentos**.
4. Si no hay evidencia → `found=false` y respuesta fija *"No tengo información sobre eso…"*. **No improvisa.**
5. Las **fuentes citadas se verifican**: solo se devuelven las que realmente existen entre los recuperados.

**Reglas:** el RAG es **solo lectura** (no cambia el contrato ni las cláusulas) y **nunca redacta ni reformula
cláusulas**: si cita una, copia el texto literal.

**Si te preguntan "¿qué es la similitud coseno?"** → Mide el ángulo entre dos vectores: 1 = misma dirección
(mismo significado), 0 = sin relación. Se usa porque importa la dirección semántica, no la magnitud.

---

## 10. Seguridad (muy probable que pregunten)

El sistema asume que **todo texto externo es no confiable**: mensajes del usuario, **documentos subidos**,
documentos indexados en el RAG e incluso la **salida del modelo**.

### 10.1 Contra *prompt injection* (entrada)

- **`normalize_input`:** normaliza Unicode (NFKC) y **elimina caracteres invisibles/de control** (ancho cero,
  direccionales) que sirven para esconder instrucciones; colapsa repeticiones (inundación).
- **`scan` (detector):** busca ~11 categorías de amenaza: anulación de instrucciones ("ignorá lo anterior"),
  secuestro de rol, extracción del prompt, exfiltración de secretos y de datos ajenos, jailbreak, escape de
  delimitadores, payloads codificados (base64/hex), inundación de salida, inyección de marcado y de código.
- **`fold`:** "pliega" el texto (sin tildes, minúsculas, *leetspeak* resuelto, letras separadas) para detectar
  evasiones como `1gn0ra` o `i.g.n.o.r.a`.
- **Estricto:** ante una coincidencia **se rechaza**, no se intenta "limpiar".
- **Inyección indirecta:** el mismo escaneo se aplica al **texto de los documentos subidos**, a lo que **extrae
  el LLM** (valor y evidencia) y a los **fragmentos del RAG** (un documento hostil no puede "dar órdenes").
- **Delimitadores:** el contenido del usuario va entre `<<<` y `>>>` y el prompt dice que es **dato, no
  instrucción**; `neutralize_delimiters` impide que el texto cierre el bloque o imite plantillas de chat.

### 10.2 Contra fugas (salida) – `OutputGuard`

- **Bloqueo total** si aparece algo que nunca debe salir: API keys, hashes, variables de entorno, rutas del
  servidor, trazas de error, **el texto del prompt interno** o la **marca canary**.
- **Canary token:** cadena secreta aleatoria por proceso incrustada en los prompts internos; si aparece en una
  salida, el modelo está volcando su prompt.
- **Detección de copia del prompt** por **n-gramas** de 12 palabras.
- **Redacción** de datos personales que no pertenezcan al contexto de la conversación (DNI/CUIL ajenos, emails,
  IDs de otros contratos) y de enlaces externos / imágenes Markdown (evitan exfiltración vía URL).
- **Tope de longitud** y colapso de repeticiones.

### 10.3 API y acceso

- **Autenticación por API key** en el header `X-API-Key`. **Solo se guarda el hash SHA-256**, nunca la key;
  la comparación usa `hmac.compare_digest` (**tiempo constante**, evita *timing attacks*) y recorre todos los usuarios.
- **Roles:** `REQUESTER` (arma contratos) y `REVIEWER` (decide). Control de acceso por rol y por propiedad.
- **Responde 404 en vez de 403** cuando un contrato existe pero no es visible → **no revela su existencia**.
- **Rate limiting** (ventana deslizante): 20 mensajes/min por usuario y límite de intentos de autenticación
  fallidos por cliente (frena fuerza bruta). Es **por proceso** (con varias instancias habría que usar un almacén compartido).
- **Locks por contrato:** evitan que dos pedidos simultáneos pisen el mismo contrato (condición de carrera).
- **Cabeceras de seguridad:** `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Cache-Control: no-store`, CSP; **CORS** acotado a los orígenes del frontend.
- **Límites de carga:** tamaño máximo por archivo, cantidad de archivos, páginas por PDF, largo de mensaje.
- **Adjuntos:** se guardan con **nombre aleatorio** (nunca el del usuario), carpeta por contrato, permisos 0600,
  y se valida que la ruta no salga del almacén (previene *path traversal*).
- **Auditoría** de intentos bloqueados (se registra la categoría, **no el contenido**).

---

## 11. Generación de documentos y verificación de integridad

**Inmutabilidad legal:** el texto de las cláusulas vive en `STATIC_CLAUSES` (copiado del contrato autorizado).
El sistema **solo inyecta variables ya validadas** en marcadores Jinja2 (`{{ terms.puesto_funcion }}`) con
`StrictUndefined` (si falta una variable, falla en vez de dejar un hueco).

**Dos tipos de documento:**

| | Borrador | Final |
|---|---|---|
| Cuándo | Antes de la decisión del revisor | Solo si está `APPROVED` |
| Formato | PDF con **marca de agua "BORRADOR"** y encabezado | PDF + DOCX, sin marca |
| Reemisión | Se regenera cada vez | **Se emite una sola vez**; luego se sirve el mismo archivo |
| Extra | — | Completa el **control de revisión** (quién aprobó y cuándo) desde la auditoría |

**Cadena de verificación (defensa en profundidad):**

1. Antes y después de renderizar se comprueba que las cláusulas coincidan con las autorizadas.
2. Tras convertir a PDF, se **extrae el texto del PDF** y se verifica que cada cláusula figure íntegra.
3. Se calcula un **código de verificación** (`XXXX-XXXX-XXXX`) derivado del **contenido** (cláusulas + datos),
   se imprime en el pie y se comprueba que el PDF lo tenga.
4. Al emitir el final se registran en la auditoría los **hashes SHA-256** del PDF y del DOCX.
5. `GET /verification` recalcula hashes y comprueba que **nada fue alterado** desde la emisión.

**Detalles técnicos:** LibreOffice en *headless* con **perfil de usuario temporal por conversión** (no tolera
dos procesos con el mismo perfil) y un **semáforo** que limita conversiones simultáneas; publicación de
archivos **atómica** (`os.replace`) para no dejar archivos a medias.

---

## 12. Persistencia

- **SQLite**, una conexión por operación (seguro entre hilos), transacciones con *commit/rollback*.
- Tabla `contracts`: cada contrato guardado como **JSON** + estado + fechas.
- Tabla `audit_log`: **registro inmutable** (id autoincremental, actor, acción, estado, detalle). Guardar el
  contrato y escribir la auditoría ocurre en **la misma transacción**.
- **Historial del chat** (mensajes de usuario, agente y de sistema, con adjuntos, intención, fuentes y enlaces
  a documentos), paginado hacia atrás con `before`.
- El repositorio es un **puerto**: podría cambiarse por PostgreSQL sin tocar los servicios.

---

## 13. La API REST (resumen)

| Método y ruta | Quién | Para qué |
|---|---|---|
| `GET /health` | público | Estado del servicio |
| `GET /me` | todos | Usuario y rol |
| `GET /templates` | todos | Plantillas por modalidad y disponibilidad |
| `POST /knowledge/query` | todos | Consulta RAG con fuentes |
| `POST /contracts` | REQUESTER | Crea un borrador vacío |
| `GET /contracts` · `GET /contracts/{id}` | según rol | Lista / detalle (con acciones permitidas) |
| `POST /contracts/{id}/messages` | REQUESTER | Un turno de chat (texto y/o archivos) |
| `GET /contracts/{id}/messages` | REQUESTER | Historial paginado |
| `GET /contracts/{id}/attachments/{aid}` | REQUESTER | Ver un adjunto |
| `POST /contracts/{id}/conflicts/resolve` | REQUESTER | Confirmar o descartar un dato |
| `POST /contracts/{id}/submit` | REQUESTER | Enviar a revisión |
| `POST /contracts/{id}/review` | REVIEWER | `APPROVE` / `REJECT` / `REQUEST_CHANGES` |
| `GET /contracts/{id}/document` | según rol | Borrador o final (PDF/DOCX) |
| `GET /contracts/{id}/verification` | según rol | Verifica integridad del final |
| `GET /contracts/{id}/history` | según rol | Auditoría |

- **Documentación automática:** FastAPI genera OpenAPI (`/docs`, `docs/openapi.json`).
- **Visibilidad:** el solicitante ve solo sus contratos; el revisor ve los que están en revisión o ya decididos.
- **Errores uniformes:** `{ "error": "codigo", "detail": "mensaje" }`.

---

## 14. Flujo de punta a punta (para contarlo como historia)

1. **Ana (RR. HH.)** crea un contrato → estado `INITIAL`.
2. Escribe *"Necesito un contrato para Juan Pérez, DNI…"* y/o sube una foto del DNI.
3. La API valida el mensaje (límites, rate limit) y llama al **agente**.
4. El agente **escanea** el texto (anti-inyección), **clasifica** la intención → `PROVIDE_DATA`.
5. La **extracción** (LLM con esquema + evidencia) devuelve candidatos; el código **verifica y normaliza**.
6. La **validación** acepta, rechaza o marca conflicto cada dato. El contrato pasa a `COLLECTING_DATA`
   (o `CONFLICT_DETECTED` si hay algo dudoso y Ana debe confirmar).
7. El agente responde con **plantillas fijas** + el siguiente paso; la respuesta pasa por el **filtro de salida**.
8. Con datos completos, Ana pide el **borrador** (PDF con marca) y lo **envía a revisión** → `PENDING_HUMAN_REVIEW`.
9. **Bruno (revisor)** aprueba, rechaza o pide cambios. Si aprueba → `APPROVED`.
10. Se emite el **documento final** (una sola vez, con hashes registrados) y se puede **verificar** su integridad.

---

## 15. Decisiones de diseño y limitaciones (muestra madurez técnica)

**Decisiones clave:**

- Determinismo donde importa; IA solo para entender lenguaje natural.
- *Human-in-the-loop* obligatorio para aprobar.
- Defensa en profundidad (múltiples barreras independientes).
- Puertos/adaptadores para poder cambiar modelo, base o conversor.
- Fallar de forma segura (ante duda: preguntar o rechazar, nunca adivinar).

**Limitaciones honestas (conviene mencionarlas):**

- Solo hay plantilla para **contrato por tiempo indeterminado**.
- Los **detectores por regex** de inyección pueden dar falsos positivos/negativos; son una capa más, no la única.
- Rate limit y locks son **por proceso** (no escalan a varias instancias sin un almacén compartido).
- Con modelos **`:cloud`** los datos viajan a un servicio externo → solo datos ficticios en pruebas.
- Depende de **LibreOffice** instalado para generar PDF y de Ollama para el chat.
- Sin el modelo, todo funciona **excepto** enviar mensajes al agente (error `llm_unavailable`).

**Mejoras posibles:** más plantillas/modalidades, rate limit con Redis, base PostgreSQL, firma digital
del PDF, evaluación sistemática de la extracción con un set de documentos de prueba.

---

## 16. Pruebas

- Más de 20 archivos de test en `tests/`; los **unitarios no usan red** (el LLM y los embeddings se reemplazan
  por *fakes* gracias a los puertos).
- Los de **integración** (marcados `integration`) corren contra un Ollama real: `pytest -m integration`.
- Cubren: esquema y CUIT/CUIL, máquina de estados, validación, extracción, normalización, RAG, agente,
  seguridad (inyección, fugas), API (roles, aislamiento), exportación y verificación, historial de chat.

---

## 17. Preguntas típicas de defensa (con respuesta corta)

1. **¿Qué hace la IA y qué no?** Extrae datos y clasifica intención. No redacta cláusulas, no valida, no aprueba, no escribe en el contrato.
2. **¿Cómo evitan que alucine?** Esquema JSON cerrado + evidencia literal verificada + confianza limitada + validación determinista + confirmación humana.
3. **¿Qué es prompt injection y cómo se defienden?** Texto que intenta darle órdenes al modelo. Normalización, detector por categorías, delimitadores, canary, filtro de salida y escaneo también de documentos (inyección indirecta).
4. **¿Puede el agente aprobar un contrato?** No: el grafo no tiene acceso a la revisión y la máquina de estados bloquea `APPROVED` fuera de `mark_as_reviewed()`, que solo usa el endpoint del revisor.
5. **¿Qué es RAG y por qué lo usan?** Recuperar fragmentos y responder solo con ellos, citando fuentes; evita respuestas inventadas sobre las cláusulas.
6. **¿Qué son los embeddings?** Vectores numéricos que representan el significado de un texto; textos parecidos quedan cerca.
7. **¿Cómo garantizan que el PDF final no fue alterado?** Hashes SHA-256 registrados en la auditoría + código de verificación derivado del contenido + verificación de cláusulas sobre el texto del PDF.
8. **¿Por qué LangGraph?** Flujo explícito, auditable y acotado (grafo de estados) en lugar de un agente libre.
9. **¿Cómo manejan dos usuarios editando a la vez?** Locks por contrato dentro del proceso.
10. **¿Cómo protegen las API keys?** Solo se guarda el hash SHA-256; comparación en tiempo constante; nunca se muestran ni se registran.
11. **¿Qué pasa si el modelo se cae?** Se informa `llm_unavailable`; el resto de la API sigue funcionando y el clasificador cae a `SMALL_TALK` sin cambiar estado.
12. **¿Qué es la auditoría?** Tabla inmutable con quién hizo qué y cuándo, escrita en la misma transacción que el cambio.

---

## 18. Glosario

- **LLM:** modelo de lenguaje grande.
- **Prompt / system prompt:** instrucciones que se le dan al modelo.
- **Prompt injection:** ataque que mete instrucciones maliciosas en el texto de entrada.
- **Structured output:** forzar al modelo a responder con un esquema JSON.
- **Grounding:** respaldar una afirmación en una fuente verificable.
- **Embedding:** vector que representa el significado de un texto.
- **Base vectorial:** base de datos que busca por similitud de vectores (ChromaDB).
- **RAG:** generación aumentada por recuperación.
- **Chunking:** trocear textos largos en fragmentos.
- **Guardrail:** barrera de seguridad previa o posterior al modelo.
- **Canary token:** marca secreta para detectar fugas del prompt.
- **HITL (human-in-the-loop):** una persona toma la decisión final.
- **Puerto/adaptador:** interfaz + implementación intercambiable.
- **Idempotente:** repetir la operación da el mismo resultado.
- **Hash SHA-256:** huella de un archivo; cambia si el archivo cambia.
- **CUIT/CUIL:** identificadores fiscal y laboral argentinos (con dígito verificador).
- **CORS:** política del navegador sobre qué orígenes pueden llamar a la API.

---

## 19. Guion sugerido para exponer (≈10 min)

1. **Problema y objetivo** (1 min): contratos sin errores y sin texto legal inventado.
2. **Principio rector** (1 min): IA para entender, reglas para decidir, humano para aprobar.
3. **Arquitectura** (2 min): capas, puertos/adaptadores, `ContractData` como fuente de verdad.
4. **Flujo del agente** (2 min): intención → extracción → validación → conflictos → estado.
5. **RAG** (1 min): consultas sobre cláusulas con fuentes.
6. **Seguridad** (2 min): inyección, filtro de salida, roles, hashes.
7. **Documentos e integridad** (1 min): borrador vs. final, verificación.
8. **Limitaciones y mejoras** (30 s) y **cierre** (30 s).
