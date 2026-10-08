# AgniNetra Live

The public app at <https://agninetra.chinmayathakral.com>: each evening's satellite fire
record told in plain words, a map, the air in 22 cities, two games and community
labelling. It is an outreach companion to the research; no research result depends on it.

## Parts

    pipeline/      builds each evening's feed and the game packs
    serve.py       one long running process: serves the app, rebuilds the feed, hosts the API
    community.py   Google sign in, qualifying rounds, Swipe answers and sync, in one SQLite file
    web/           the app: Vite and strict TypeScript, no framework, every input parsed with zod

**The feed.** `pipeline/build_feed.py` reads NASA FIRMS and this project's INSAT-3DS
detector, aggregates to 0.1 degree cells, splits the cells into seen by polar satellites
only, by both and by INSAT-3DS only, adds the half hour timeline, the 22 city forecasts
from CAMS through Open-Meteo and their back trajectories, and validates the result before
writing it. `serve.py` runs it every thirty minutes from 16:37 to 21:37 IST and at 23:37,
each build in its own process under a time limit, so a stalled download leaves the last
good feed up. The last four evenings are served, and the app's day switcher opens each.

**The games.** Heatle deals one verified site a day from `pipeline/build_heatle_pack.py`.
Swipe shows the 139 persistent hot spots that match no registry within 1 km, with their
details from `pipeline/site_details.py`. Qualifying rounds come from
`pipeline/build_qualify_pack.py`: 115 sites within 1 km of a Global Energy Monitor asset,
published under secret keyed names with rounded clues, their answers stored only as HMACs.

**Community labels.** A player signs in with Google, solves 10 qualifying rounds within 4
clues in the Heatle tab, then labels spots in Swipe: industry, not industry or cannot
tell, one answer per spot per person. `pipeline/community_labels.py` decides a spot
offline when at least 3 qualified players answered firmly and their agreement, weighted by
how well each did on the verified sites, reaches 75 percent.

## API

| Route | What it does |
|---|---|
| `GET /api/config` | whether labelling is on, the qualifying target and clue limit |
| `POST /api/session`, `DELETE /api/session` | sign in with a Google ID token, sign out |
| `GET /api/me`, `DELETE /api/me` | the player's profile; delete everything kept |
| `PUT /api/me/data` | sync game progress |
| `POST /api/qualify/start`, `/clue`, `/guess` | one qualifying round, dealt a clue at a time |
| `GET /api/swipe/next`, `POST /api/swipe/answer` | the next spot to label, and an answer |

Every API response is `Cache-Control: no-store`, and the service worker never caches
`/api/`. Sessions are stored as SHA-256 hashes for 30 days.

## Running it

From the repository root:

    cd apps/live/web && npm ci && npm run build && cd ../../..
    uv run python -m apps.live.serve --no-build

`--no-build` serves without rebuilding the feed. To build a feed by hand:

    uv run python -m apps.live.pipeline.build_feed --date 2024-11-01

Settings come from the environment or `.env`:

| Variable | Needed for |
|---|---|
| `FIRMS_MAP_KEY` | the polar satellite record |
| `MOSDAC_USERNAME`, `MOSDAC_PASSWORD` | INSAT-3DS granules |
| `GOOGLE_CLIENT_ID` | sign in; a Google OAuth web client whose authorised redirect is the site's root |
| `QUALIFY_SECRET` | qualifying answers; at least 32 random characters, the same value the qualifying pack was built with |

Without the first three the feed reports itself as blocked rather than inventing data.
Without the last two, labelling is off and the rest of Live works. If the qualifying
answers do not verify under `QUALIFY_SECRET`, the server logs that and keeps labelling off.

## Deploying

The root `Dockerfile` of the `agninetra` branch builds one container running `serve.py`.
Keep `/app/data` on a persistent volume: it holds the feed history, the social kit and
`live/community.db`. To decide community labels, run on the machine that holds it:

    uv run python -m apps.live.pipeline.community_labels data/live/community.db

## Rules built in

- Farm fires appear only per 11 km cell or district, never per field.
- Industry is "likely industrial heat", never "polluter". Points come from looking, never
  from burning.
- No analytics and no third party scripts: the content policy allows only the site's own
  scripts, and Google sign in is a redirect, not a Google script. No request is logged.
- Without an account nothing leaves the browser. With one, only the email address, game
  progress, qualifying rounds and labels are kept, and one tap deletes them.
