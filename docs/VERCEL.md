# Serverless runtime
app.index:app is the native FastAPI entrypoint, using the same routes, authentication and CQRS handlers as container mode. PLZK_DEPLOYMENT_MODE=serverless uses a PostgreSQL connection per transaction; the email worker remains a persistent separate process.

The repository's editable shared package sources point to ../plazia/packages. A cloud build must receive the same versioned shared package source/wheel artifacts and resolve those paths. This standalone checkout is not a verified self-contained Vercel deployment. No Vercel project was modified by this task. See DEPLOYMENT.md for required Identity, Redis, OpenFGA, SMTP and schema authority.
