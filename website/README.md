# mail2pay sign-up site

Static landing page for [mail2pay](../README.md). Users sign up via
[Clerk](https://clerk.com); the serverless email handler rejects inbound
mail from addresses that are not registered Clerk users.

No build step. Plain HTML + CSS + ES modules.

## Local development

1. Create a Clerk application at <https://dashboard.clerk.com> and copy the
   publishable key (starts with `pk_test_…`).
2. Copy the config template and fill in your key:

   ```sh
   cp website/config.example.js website/config.js
   # edit website/config.js — set publishableKey
   ```

3. Serve the folder:

   ```sh
   python -m http.server --directory website 8080
   # open http://localhost:8080
   ```

`website/config.js` is gitignored; never commit a real key.

## Production deploy

Deployment is handled by `.github/workflows/deploy-pages.yml`, which writes
`config.js` from the `CLERK_PUBLISHABLE_KEY` GitHub Actions secret at build
time and publishes the result to GitHub Pages.
