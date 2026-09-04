# Hitchwiki / Hitchmap recommendations ops

## Attribution

- Spot coordinates and community ratings: [Hitchmap](https://hitchmap.com/) dump (`dump.sqlite`).
- Waiting-time model / heatmap: Hitchwiki projects
  ([heatchmap-models](https://huggingface.co/Hitchwiki/heatchmap-models),
  [hitchhiking-heatmap](https://huggingface.co/datasets/Hitchwiki/hitchhiking-heatmap)).
- Heatmap license: CC BY-SA 4.0. Model artifacts: see upstream LICENSE.
- Do **not** vendor the AGPL `heatchmap` package into the web runtime.
  Model unpickle stubs are downloaded only into a temporary directory during
  `sync_hitchwiki_ai --mode model`.

## Data flow

```
Hitchmap dump.sqlite
  → python manage.py sync_hitchwiki_spots
  → HitchwikiSpot (PostGIS)

pretrained model OR heatmap parquet
  → python manage.py sync_hitchwiki_ai
  → HitchwikiSpotAI

API / DetectedStop pipeline
  → PostGIS nearby search + deterministic ranking
  → JSON (no network, no ML)
```

## Commands

```bash
# Weekly spot sync (example)
nice -n 10 python manage.py sync_hitchwiki_spots

# Monthly AI enrichment after a successful spot sync (low-traffic window)
nice -n 15 python manage.py sync_hitchwiki_ai --mode auto
```

`HITCHWIKI_AI_MODE`:

- `auto` (default): try model, fall back to heatmap
- `model`: model only
- `heatmap`: heatmap only

Optional ML deps (offline host / one-off container only, not Daphne image):

```bash
pip install '.[hitchwiki-ai]'
```

## Example cron (do not install automatically)

```cron
# Sunday 03:15 UTC — spots
15 3 * * 0 cd /app && nice -n 10 python manage.py sync_hitchwiki_spots >> /var/log/hitchwiki_spots.log 2>&1

# 1st day of month 03:40 UTC — AI enrichment
40 3 1 * * cd /app && nice -n 15 python manage.py sync_hitchwiki_ai --mode auto >> /var/log/hitchwiki_ai.log 2>&1
```

Run AI sync during low traffic. Concurrent AI syncs are blocked with a PostgreSQL advisory lock.

## Feature flag

```env
HITCHWIKI_RECOMMENDATIONS_ENABLED=true
```

## Manual API (Flutter map button)

```
GET /api/hitchwiki/recommendations/?lat=52.23&lon=21.01&radius_km=5&limit=5
Authorization: Token <token>
```

Read-only: no `LocationReport`, no `DetectedStop`, no ML.

Legacy stop-based list remains:

```
GET /api/teams/recommendations/
```
