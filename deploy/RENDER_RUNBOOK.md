# Render deployment

Use RENDER_IMAGE_DEMO.md for the existing authenticated application and its data.
The old queue-based compute integration has been removed. Inference defaults to
disabled and processing cannot enter an unserviced queue. Build/test/publish only
the API image, retain PostgreSQL/R2/login settings and use the new image digest.

render-demo.yaml is the free web/database topology. render.yaml is a historical
paid web/worker topology; do not apply it just to update the existing free service.
Neither creates GPU compute, model storage or inference resources. Persistent
model storage and session compute are described in docs/PERSISTENT_STORAGE_PLAN.md.
