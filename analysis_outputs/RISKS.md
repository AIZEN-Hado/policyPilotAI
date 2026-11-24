# Findings from static inspection

Runtime impact has not been tested. Findings below distinguish directly visible implementation gaps from inferred failure modes.

| Priority | Evidence | Finding / consequence |
|---|---|---|
| P0 | app/routes.py | No authentication or ownership checks on claim history, decisions, or ingestion; reachable callers can access the exposed operations. |
| P0 | app/decision_engine.py:123; app/rag/store.py:31 | Retrieval uses type/description and metadata contains only source/page. Policy number is passed to the prompt but does not restrict retrieval. Cross-policy evidence can influence a recommendation. |
| P0 | app/decision_engine.py:139; app/utils/validators.py | Schema validation exists, but there is no evidence/citation validation or human approval workflow. Valid JSON can still describe an unsupported outcome. |
| P1 | app/decision_engine.py:134 | Synchronous inference and retrieval execute in an async request handler, blocking that event loop during processing. |
| P1 | app/rag/retriever.py:23 | Reader cache has no index refresh. It also assigns the cache before load succeeds, so a failed first load can leave an empty cached wrapper; verify with a regression test. |
| P1 | app/rag/ingest.py; app/rag/store.py:62 | Ingestion writes the live index without publication locking/versioning; overlapping ingestion or reads may observe inconsistent artifacts. Jobs have no persistent status/recovery. |
| P1 | app/rag/store.py:78 | Dangerous deserialization is enabled. Exploitation depends on an attacker being able to replace index artifacts; enforce trusted ownership and integrity or replace this persistence format. |
| P1 | app/rag/store.py:57; ui/components.py:147 | Retrieval scores are hardcoded to zero; displayed confidence comes from the model and is not calibrated accuracy. |
| P1 | app/main.py:24; app/config.py; app/routes.py:92 | Wildcard CORS, debug enabled by default, raw exception details, and unbounded history limit need production controls. CORS is not an authentication boundary. |
| P1 | app/db.py | Startup create_all is not a migration strategy; monetary amounts use floats, incident dates use strings, and decision provenance lacks policy/prompt/index versions. |
| P1 | tests/test_rag.py:55; tests/test_api.py | FAISS patch targets an absent module attribute because FAISS is imported inside methods. API tests have no isolated DB/lifespan fixture. Expected test failures/environment coupling require execution to confirm. |
| P1 | Repository root | No container deployment, CI configuration, migration scripts, or operational runbooks found. Dependency compatibility and vulnerabilities were not checked. |
| P2 | ui/streamlit_app.py:18; ui/components.py:41 | Hardcoded localhost service URLs complicate deployment; remote icon contradicts strictly offline UI operation. Embedding artifacts also require initial provisioning. |

No measured model accuracy, throughput, latency, recovery time, or runtime test results are available from this review.
