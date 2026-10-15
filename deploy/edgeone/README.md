# Live AI deploy on EdgeOne Makers

This folder turns the repository into the bundle behind the hosted live demo,
`https://ryde-dispute-live.edgeone.dev`. The application itself is not changed: `app/`, `data/`
and `ui/` ship as they are, and the folder adds one request adapter in front of the shipped
server.

## What is here

| File | Purpose |
|---|---|
| `site/cloud-functions/api/[[default]].py` | The adapter. EdgeOne routes every `/api/*` request to it. It runs the shipped `RydeRequestHandler` on the Tencent ADP provider, with a 100 s case budget and the filing limits below. |
| `site/cloud-functions/ryde_deploy_policy.py` | `docs/policy.md` as a Python string. The bundler drops `.md` files and `docs/`, so the adapter writes the policy back out after checking its SHA256. `package.py` refuses to build if the carrier no longer matches `docs/policy.md`. |
| `site/edgeone.json` | Redirects `/` to `/party/` and raises the function time limit to 120 s. |
| `package.py` | Assembles the bundle from the repository. |
| `tests/test_live_adapter.py` | 23 adapter tests on the keyless mock provider, so no test spends credits. |
| `tests/test_package.py` | 10 tests that the bundle is the shipped app plus these files and nothing else. |
| `tests/mutation_battery.py` | 29 planted defects in the adapter; each one must turn the adapter tests red. |

The main suite runs both test files through `tests/test_w58_deploy_edgeone.py`.

## Build the bundle

```sh
python3 deploy/edgeone/package.py /tmp/ryde-live-site --zip /tmp/ryde-live-edgeone.zip
```

The hosted pages differ from `ui/` in six links only. The site root redirects to the dispute
page, so each "Operator console" link (four party pages, the console's own tab, the start-page
card) points at `index.html` instead of the root. `package.py` makes those replacements and stops
if any of them does not match exactly once.

Upload the zip in the EdgeOne Makers console (project, Deploy, upload). Environment variables
apply only to a new deployment, so redeploy after changing one.

The bundle deployed on 15 Oct 2026 predates the publication corrections. Its `app/schemas.py`
differs by one name in a docstring; its policy carrier has the earlier explanatory text. Current
policy prose clarifies separately enforced safeguards and the existing RD-5 breakdown branch.
No Python gate, rule ID or monetary threshold changed. The hosted site was not redeployed; its
saved runs reflect that earlier policy text and prompt fingerprint.

## Keys

The adapter reads three Tencent ADP app keys from the EdgeOne project's environment variables:
`TENCENT_ADP_RIDER_APP_KEY`, `TENCENT_ADP_DRIVER_APP_KEY` and `TENCENT_ADP_JUDGE_APP_KEY`. No key is
in this folder or in the bundle. Without them every API call answers 503 "The live AI is not
available right now", and the platform log names the missing variable, never a value.

## Limits

Only a new route-deviation or no-show filing counts, because only those reach the agents:

- 10 per visitor in any rolling hour. The visitor is the `Eo-Connecting-Ip` header, which the
  EdgeOne edge overwrites. `X-Forwarded-For`, `EO-Client-IP` and `X-Real-IP` are ignored because
  a client can set them or every visitor shares them.
- 50 per Singapore calendar day across all visitors.

Follow-up answers, out-of-scope reports and console actions are never counted. A filing the app
refuses gives its slot back. At a limit the party sees a 429 message naming when it resets, and
the filled form stays.

## What does not persist

Cases and limit counts live in the function instance's `/tmp`. An idle instance is recycled and
a redeploy starts a new one, and either empties both: a case filed earlier, including one held
for human review, can be gone when its filer comes back. File it again; a case takes under a
minute. Counts can also exceed the daily cap when the platform runs more than one instance. Both
are accepted for a judging demo; durable storage would mean an external store and is not built.

## Run the tests

```sh
cd deploy/edgeone/tests
python3 -m unittest test_live_adapter test_package -v
python3 mutation_battery.py
```
