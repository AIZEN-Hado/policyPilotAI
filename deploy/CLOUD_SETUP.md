# Persistent model storage transition

Keep existing Render, PostgreSQL and private R2 document storage. The retired
queue endpoint is removed separately with remove_serverless.py; historical runs,
spend and source snapshots remain in artifacts. No paid provisioning is performed
by this setup documentation. Use RENDER_IMAGE_DEMO.md to deploy the app cleanup.

The replacement model service uses persistent artifact storage plus separately
managed session compute. Read docs/PERSISTENT_STORAGE_PLAN.md before selecting a
volume/Pod. Storage alone does not execute a model and can continue billing after
compute stops. Review actual price/retention against the USD 2.99 combined limit,
including all prior spend, before provisioning. Do not reset accounting history.

Existing deploy/cloud.env holds owner-only provider/document-store credentials.
Preserve it for scoped cleanup and the later Pod/storage setup; never source or
print it in diagnostics. New model-service credentials will be configured only
when the replacement service exists and has been verified.
