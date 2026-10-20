# Evaluation protocol

Goal: measure how the attendance pipeline behaves in a real classroom, choose the decision threshold from data, and compare each improvement before vs. after.

## 1. Consent and privacy

- Record only people who agreed in writing to take part (a short consent form: purpose, what is stored, deletion on request).
- Use anonymous codes: `P01, P02, …` for enrolled people, `X01, X02, …` for people who are **not** enrolled. Keep the code ↔ name list offline.
- `eval_data/` and `results/*/probes.csv` stay on your machine (both are git-ignored). Only aggregate tables go into the README.

## 2. Data layout

```
eval_data/
├── enroll/                      session 1 (day A)
│   ├── P01/0001.jpg …
│   └── P02/…
└── test/                        session 2 (day B, different clothes/lighting)
    ├── normal/    P01/ P02/ … X01/ X02/
    ├── low_light/ P01/ … X01/
    ├── pose/      P01/ …        head turned ~30°, looking down
    └── glasses/   …             optional: mask, distance (2–4 m), backlight
```

Rules that keep the numbers honest:

- **Enroll and test come from different sessions.** Images from the same minute are almost identical and inflate accuracy.
- Any folder under `test/` whose code does not exist in `enroll/` counts as an **unknown person**. These probes measure whether strangers are rejected.
- Suggested size: 15–20 enrolled people, 5–10 unknown people, ~20 frames per person per condition.

## 3. Recording

Use the classroom camera (or the same webcam) at its normal position:

```bash
cd attendance_system
python -m tools.capture_eval --person P01 --split enroll --count 10
python -m tools.capture_eval --person P01 --split test --condition normal
python -m tools.capture_eval --person P01 --split test --condition low_light
python -m tools.capture_eval --person X01 --split test --condition normal
```

Frames are numbered in capture order. `--confirm-frames` relies on that order.

## 4. Running

```bash
cd attendance_system
python evaluate.py --data ../eval_data --out ../results/baseline --hardware "i5-xxxx, CPU only"
```

Outputs in `results/<run>/`:

| File | Content |
|---|---|
| `report.md` | summary table per condition, latency, recommended threshold |
| `metrics.json` | all numbers + run configuration |
| `sweep.csv`, `threshold_sweep.png` | rates for thresholds 0.20–0.90 |
| `probes.csv` | one row per test image (score, margin, decision) for error analysis |

Embeddings are cached in `eval_data/.embedding_cache.npz`, so repeated runs with different thresholds take seconds.

## 5. Metrics

For **known** people (enrolled):

- **Identification rate**: recognized as the correct person.
- **Misidentification rate**: recognized as *another* student. This is the most harmful error, because attendance goes to the wrong person.
- **False reject rate**: not recognized (student must retry).
- **Detection failure rate**: no face found at all.

For **unknown** people:

- **Unknown reject rate**: stranger correctly rejected.

Combined:

- **False accept rate** = (misidentified + accepted strangers) / all probes. This is the security number the threshold is tuned against (default target ≤ 1%).

## 6. Experiments (before vs. after)

| # | Question | Command |
|---|---|---|
| E1 | Baseline (current app settings) | `--out ../results/baseline` |
| E2 | 1 vs. many enrollment samples | `--enroll-samples 1` vs. default (all) |
| E3 | Single frame vs. multi-frame confirmation | `--confirm-frames 3` |
| E4 | Is preprocessing worth it? | `--preprocess` |
| E5 | Threshold from data | read `recommended` in `report.md` |

For each experiment, write down three things: what improved, what it cost (more rejects? slower?), and which cases still fail (look at `probes.csv`).
