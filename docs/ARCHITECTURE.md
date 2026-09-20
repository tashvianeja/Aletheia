# Architecture and contracts

Contract version 1 (2026-09-19). `core/events.py` is the authoritative executable model contract. Python 3.12, Pydantic v2, closed `DataCategory` string enum; dotted variants such as `government_id.passport`. Every event carries category names only, never detected values.

## Processes and boundaries

Qt runs on the main thread. The async service runs on a dedicated thread. A bounded, single-process analysis pool owns raw document bytes and opaque payload handles, preserving handle affinity across analysis/redaction. Native transport necessarily forwards bytes, then discards them; raw bytes are not returned to the engine, persisted, or logged. The browser-spawned host is a framing/authentication transport only. Pool failure discards handles, restarts the worker, and returns an explicit retryable error.

The on-device sentence encoder in `intelligence/` is a third boundary. It is an int8 MiniLM running under `onnxruntime` with a dependency-free WordPiece tokenizer, loaded lazily on the first form judged, held in the service process alongside the metadata executor, and released after 90 idle seconds so its roughly 95 MB resident cost does not count against the idle-memory budget. Nothing leaves the machine. When the weights or the runtime are absent, form judgement falls back to structural inference and reports less rather than reporting wrongly.

Optional LLM work is isolated from the critical analysis queue in a separate lazy `ProcessPoolExecutor` with one worker. It is created only when cloud assistance is enabled and torn down on disable/stop; cloud latency therefore does not block upload, form, or native decisions.

## Models

`Requester(kind, origin, etld_plus_one, bundle_id, exe_path, signer, display_name, purpose="unknown", purpose_confidence=0.0, trust_tier="unknown")`; `.key` is origin/bundle/executable/display name in precedence order. `Finding(category, confidence=1, span_ref="", page=None, validator_passed=False, stable_hash="")` has no raw value.

`PrivacyEvent(id=uuid, ts=UTC-now, event_type, source, requester, data_categories=[], payload_ref=None, platform="unknown", correlation_id=None)`. Discriminator event_type values: file_upload, form_observed, form_submit, consent_banner, policy_document, tracking, permission_request, system_access, clipboard_read, screen_capture, startup_registration, deep_check. See typed subclass fields in events.py.

`Decision(event_id, outcome: Outcome[IGNORE/INFORM/INTERVENE], risk:0..1, explanation:str, rationale:list[str], actions:list[str], default_action:str)`. Action IDs: cancel, continue, redact, unredact, strip_metadata, review_fields, clear_fields, redact_fields, reject_optional, block, open_settings, mark_expected, view_details, learn_more, clear_clipboard (the authoritative set is `core.ipc.protocol.ACTIONS`). `UserResponse(event_id, action, ts, remember=False)`.

## Service APIs

`EventBus.subscribe(handler: async Callable[[PrivacyEvent], None]) -> unsubscribe`; `await bus.publish(event)` isolates subscriber failures. `Service(settings, store=None)` owns `await start()`, `await stop()`, `await handle_message(message:dict) -> dict`, `await process_event(event, findings=None) -> Decision`, `await respond(response)`. UI receives decisions via subscribed callbacks; browser intervention waits use action polling with a safe 60s default.

Analysis agent owns `analysis.worker.analyze_payload(payload:dict[str,object])` and worker-local handles. Analysis results are typed category-only objects. `engine.decision.decide(event, findings=[], profile=None, preferences=None, learned_rules=None) -> Decision` is the stable pure entry point. Analysis/engine may expose additional typed models locally.

## IPC v1

Native framing: 4-byte little-endian unsigned byte length then UTF-8 JSON; maximum message 900 KiB. Requests `{v:1,id:str,type:str,payload:object}`. Responses `{v:1,id:str,ok:bool,result:object|null,error:{code:str,message:str}|null}`. Local host connection first sends `{token:<per-install secret>,request:<request>}` using the same framing. Unix socket is mode 0600 inside mode 0700 data directory. Windows uses AF_PIPE named pipe with the per-install token. Native host validates caller origin against configured extension allowlist.

Types: ping, event, file_start, file_chunk, file_finish, action, action_poll, context, deep_check, disconnect, focus. File chunks have upload_id, sequence, data (base64); start has upload_id, filename, size, mime, requester; finish has upload_id. Raw form values are forbidden; field metadata admits only field_id, category, label, name, input_type, autocomplete, required, asserted_required, filled, confidence, max_length. A form may also carry a `context` of page copy: submit_text, heading, legend, action_path, nearby_text, page_title. The browser's one-second ping carries `active_origin`, the origin of the tab in front (empty when that is not a web page), which the service records as `Service.active_origin` and announces to `page_listeners` on each change; surfaces that answer for one page, such as the thorough-check card, leave when it moves on.

## Storage

`Store(path)` migrates on construction. `save_event(event)`, `save_decision(decision)`, `save_response(response)`, `history(limit=100, requester=None, outcome=None)`, `set_preference(key,value)`, `get_preferences()`, `put_profile(kind,key,profile)`, `get_profile(kind,key)`, `cache_document(origin,digest,profile,ttl_days=30)`, `get_cached_document(origin,digest)`, `purge(days=90)`, `export_preferences()`, `import_preferences(payload)`, `diagnostics()`, `close()`. sqlite3 with a thread lock, WAL, foreign keys, mode 0600.

Tables: schema_version(version); events(id,ts,event_type,requester,categories,event_json,status); decisions(id,event_id,ts,outcome,risk,decision_json); user_responses(id,event_id,ts,action,response_json); site_profiles(key,updated_at,profile_json); app_profiles(key,updated_at,profile_json); preferences(key,value_json,updated_at); learned_rules(key,value_json,updated_at); document_cache(origin,digest,created_at,expires_at,profile_json). Migration v1 baseline -> v2 adds status plus indexes. Stored category-only event projection excludes payload_ref, field labels/names, file names, URL query strings, raw extracted text. Public policy caches must be sanitized before persistence.

## Platform adapter

`PlatformAdapter` exposes `start(emit)`, `stop()`, `permissions_status()->dict[str,bool]`, `foreground_requester()->Requester`, `snapshot()->list[PrivacyEvent]`, `open_settings(permission)`, `set_autostart(enabled)`. Implementations inject registry/TCC/clipboard/filesystem readers for portable tests. Clipboard content classification goes straight to the analysis worker; only categories remain in the monitor.

## Browser boundary

The WebExtension runs as a thin sensor/actuator. Its background worker obtains website identity from browser sender data rather than page-supplied identity, validates event/request/response schemas, and allowlists form metadata fields. It holds observed URL/tracker context only in extension memory and clears tab context on navigation or close. Chromium’s fixed development extension ID is `bfdjphkbgihhbonhnmjbbfhckdddonob`; Firefox’s ID is `privacy-guardian@privacyguardian.local`. Native host name: `com.privacyguardian.host`.

The extension can create bounded dynamic blocking rules and remove relevant browser cookies after a user action. MAIN-world wrappers are best effort. Known upload paths can wait up to four seconds for initial analysis and then fail open; an `INTERVENE` decision waits for its safe 60-second service timeout. Synchronous file XHR can be aborted while ordinary XHR and beacons pass through. Firefox CNAME/DNS signals are cached best effort. Chromium native-host handshake and a fixture form-badge path have evidence; browser action coverage remains incomplete.

## Verification

Sol writes independent tests. Platform-specific real checks are separate from injected adapter tests. No claim of real Windows execution without a successful runner result. UI uses `tr()` for strings; optional LLM is disabled by default, sanitized at one choke point inside the optional process, and uses keyring credentials only.

### Metadata scheduling and cache concurrency

Forms, consent, and tracking metadata are analyzed by a bounded two-thread executor (at most eight outstanding jobs). File and clipboard contents stay in the single analysis process; metadata scheduling cannot access worker payload handles. Policy/terms cache entries are envelopes keyed by document kind under the existing origin/content-hash key. Purpose-dependent necessity is recomputed on cache reads. Profile mutation reloads current storage after all analysis awaits and merges the completed facts without another await, preserving concurrent observations. Each native host caps data dispatch at six concurrent requests; Windows pipe and Unix transports cap connections at32. The host sends a separate one-second heartbeat outside its data slots, and the service expires an orphaned session after five seconds without a request. Heartbeats never consume the browser-command mailbox.

Uploads receive a persisted category-empty event with `pending` status before worker dispatch. The same event ID becomes complete after analysis, or aborted after cancellation, session loss, worker failure, or timeout. In-flight metadata remains tracked while analysis runs, so an abrupt browser/native-host kill cannot lose the audit row or publish a late live popup. Partial file analysis has a minimum INFORM outcome with explicit unchecked-content wording, even when the analyzed sample contains no findings.

The host adds its own PID and process creation time to authenticated requests, overriding any browser-supplied values. These fields remain in service memory and are never persisted. Before publishing a file result, the service checks that this exact host process still exists and is not a zombie; the creation-time check prevents PID reuse from reviving a dead session. Maintenance also expires dead hosts immediately, while clients without process metadata retain the five-second lease. On EOF, the host sends disconnect before waiting for pending data tasks.

Service readiness includes preparing a lightweight worker without NER. A page exposing an upload control can prepare NER lazily once per worker generation. Heavy workers recycle after10 idle seconds and are replaced with lightweight workers; workers retaining live payloads keep their120-second lifetime. Numeric extraction/PII timings are available for diagnostics; file-stage logs use DEBUG level and contain no content or filenames. AF_PIPE uses bounded byte-message clients and authenticates the mandatory JSON envelope token; it does not run an unbounded stdlib authentication handshake inside accept().
