# Metask desktop account integration

Contract: the user-supplied `oauth-integration(1).md`, including RFC 8414 discovery, authorization code + S256 PKCE, RFC 8628 device grant, rotating refresh and RFC 7009 revocation. This is a public desktop client with no embedded secret or OIDC assumptions.

## Registration and configuration

An administrator must register MetaBrowser independently in Metask's application administration. Default `client_id` is `metabrowser`; enable `authorization_code` and `refresh_token`, scopes `read` and `model:invoke`, and register:

```
http://localhost/auth/metask/callback
```

The registered loopback host is `localhost`, not `127.0.0.1`. The contract permits dynamic ports for public loopback clients. The browser binds an ephemeral port before requesting authorization and uses its exact redirect URI for token exchange. Optional device login additionally requires `urn:ietf:params:oauth:grant-type:device_code` in the registration. Registration must exist server-side; a client-side default does not create it.

Account configuration is separate from model API keys. Optional non-secret JSON at `~/Library/Application Support/MetaBrowser/account/config.json`:

```json
{"site":"https://app.metask-ai.com","client_id":"metabrowser"}
```

`METASK_SITE_URL`, `METABROWSER_OAUTH_CLIENT_ID` and `METABROWSER_ACCOUNT_HOME` override these defaults. Only HTTPS issuers/endpoints are accepted, except explicit HTTP loopback for development. Public discovery GET follows up to five redirects and validates metadata against the final origin. Redirects are not followed with credentials. Both account scopes are explicitly requested. Do not use a Metacodes client ID or web-session/administration token as a shortcut.

## Native UI

The actual Chromium avatar toolbar entry is replaced with Metask identity and interaction. Signed-out windows show “登录 Metask”; clicking opens a native anchored `app.metask-ai.com` account bubble. Signed-in windows show the account name and expose logout. The original Google profile-menu action and sign-in IPH methods are not used. Existing avatar-menu keyboard commands dispatch through the same replaced button interface. The toolbar observes public UI account metadata, including restore/login/logout, without receiving credentials or adopting Google IdentityManager state. Subscription ownership uses an owned View property so the pinned avatar class ABI stays unchanged.

Google browser sign-in is disabled in this product's profile, including its next-startup preference. The app-menu account subsection uses Metask and removes Google sync and Google account-management rows. Legacy Google sign-in/sync command IDs route to the native Metask account surface. Settings People/account/sync routes render a Metask account card, and Google browser-signin choice/toggle controls are removed from service settings. These are actual rebuilt Settings TypeScript, bundled/minified JS and Grit/repacked resource files, not page-injected CSS or binary substitutions. Other website accounts and local data import remain ordinary browser features; no Metask bookmark/password sync is claimed.

Configuration provides login, cancel, restore, device fallback and logout. PKCE opens an ordinary browser tab for user login/consent, never an injected page or automated authorization. Account name is obtained from `userinfo`; stable identity is `sub`. The initial dialogue restores a saved account without starting a model request. The model list includes only explicitly supported text endpoints; unknown capabilities are excluded. Enter a listed model and apply it to begin a new session with that model's declared protocol.

API keys remain an independent manual option. The password field is not filled with an OAuth bearer. OAuth requests use an internal native transport, while the configuration shows the actual gateway URL.

## Credential and execution lifecycle

Access/refresh tokens and their metadata are one Keychain generic-password item under service `com.metask.metabrowser.oauth`, isolated by account-root/issuer/client ID. Only a private lock file is created on disk. No automatic plaintext-store migration imports old credentials; reauthorize instead. Credential events do not enter the transcript, page, local Skills, A2A tasks or model prompts.

Refresh, login publication and logout share a mutex and private `flock` across processes. Refresh re-reads credentials under the lock, includes `client_id`, preserves scopes, honors actual expiry and atomically stores the new pair. A stale access token that was already rotated does not cause a second refresh. Network uncertainty, 5xx during refresh or invalid_grant clears the unusable credential instead of retrying the consumed refresh token. Configuration errors are reported distinctly.

The unchanged SDK holds a random local capability. A native loopback HTTP transport checks that capability, forbids browser Origins, restricts paths/models to the account catalogue and injects account bearers only upstream. A token-expired/invalid-token 401 can trigger one refresh and one replay of that HTTP request before response bytes have streamed. No AgentLoop, file operation or browser action is repeated. Upstream transport failures and other status codes are not silently replayed. Each local capability is bound to the login generation and `sub`, so an old conversation cannot adopt a different login's credentials. Already submitted upstream work may continue; logout is not task cancellation or refund.

Logout sends the current refresh token to the discovered revocation endpoint, accepts an empty HTTP 200 body, and clears local credentials even on network failure. The UI distinguishes confirmed revocation from local-only logout. Refresh and revoke requests have bounded timeouts.

## Verification

```sh
python3 tests/integration/oauth_contract_test.py
python3 tests/integration/account_catalog_test.py
zig build test
```

The OAuth test creates an isolated loopback issuer and temporary, dummy-only real Keychain item, then removes it. It verifies discovered custom paths, explicit scopes/client ID, PKCE/S256, rejected/duplicate state, identity, endpoint-capability selection, no plaintext token file, local capability/origin/model checks, SSE, refresh rotation and one-request retry, uncertain-refresh non-reuse, restore, empty-body revoke, local cleanup on revoke failure and cancellation. It does not call a paid model or approve a real account.

Real issuer metadata currently returns HTTP 403 from this machine. Production client registration and user consent therefore remain separate live acceptance steps; passing the local contract test does not establish a real account session.

## Production catalog compatibility

Production currently also emits explicit `supported` booleans without `status` or endpoint-local modality arrays. For that schema, text input/output must both be explicitly supported at the capability level. If an endpoint supplies modality arrays, they take precedence; any explicit unknown/unsupported status remains excluded. Model names are never used to infer protocol.

## Pinned SDK streaming compatibility

The pinned SDK chat parser interprets every frame containing a top-level `usage` key as a usage-only record. Production GLM includes `usage: null` with text/reasoning deltas. The native OAuth relay omits null usage and splits combined delta/non-null usage into separate SSE records, preserving actual usage. It buffers partial lines with a 2 MiB limit and leaves Anthropic/Responses streams untouched. The host reports a visible error if an otherwise successful run emits no text. Actual GLM two-turn UI acceptance and the regression evidence are in `out/evidence/metacodes-live-reply-acceptance.json`.
