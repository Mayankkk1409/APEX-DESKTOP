# Logo

| File | Format | Where the app loads it |
|---|---|---|
| `frontend/public/brand/apex-logo.png` | PNG, 800×800 | `ApexLogo` in `frontend/src/components/ApexLogo.tsx` sets `LOGO_SRC` to `/brand/apex-logo.png`. The favicon in `frontend/index.html` uses the same path. |

A copy of that PNG is in this folder as `apex-logo.png`.

Splash, login, signup, the dashboard, portfolio, settings, and the order certificates render `ApexLogo`. The splash word “APEX” is HTML text in `frontend/src/pages/Splash.tsx` beside that image.

Changing the mark means replacing this installed PNG. The component does not load a Canva file.

SVG wordmark: Not in the repo. Light and dark logo variants: Not in the repo. Canva ZIP: Not in the repo.

A different PNG sits at the repo root, `Screenshot_2026-08-23_at_7.51.56_PM-removebg-preview.png`. `README.md` says it was copied to `frontend/src/assets/apex-logo.png`. That assets path is not in the repo. The bytes do not match `frontend/public/brand/apex-logo.png`. The UI loads the public brand file.

## Email letter

The owner wants this logo embedded inside the HTML letter, not sent as a separate attachment.

The code still attaches it. `render_transactional_email` in `backend/app/services/signup_email.py` puts `<img src="cid:apex-logo">` in the HTML. `_compose` then calls `_attach_inline_logo`, which adds the PNG bytes as a `multipart/related` part with `disposition="inline"` and that content id. `_logo_path` prefers `frontend/public/brand/apex-logo.png`. The module text says this is an inline CID image and not a separate download. It is still a MIME part, not the image bytes written into the HTML itself.
