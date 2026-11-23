# Konsey

Konsey asks the same question to Claude, GPT and Gemini through their official command-line tools (using your own subscriptions, no API keys), has the models critique each other anonymously, writes one shared answer, and lets each model vote on it separately; the votes are counted by code.

Türkçe: [README.tr.md](README.tr.md)

## How it works

1. **Independent answers (Round 0).** The question goes to the three models separately. Each answer includes a "validity limits" field: the conditions under which that answer would be wrong.
2. **Anonymous critique and correction.** By default one round (`--tur 1`, up to 3). Each model critiques the other answers without knowing who wrote them and without seeing its own. The author then accepts or rejects each point with a stated basis. Code filters which points reach the correction step.
3. **Synthesis.** One model writes a shared text from the corrected answers. It has no authority over the outcome.
4. **Separate approval.** Each of the three models is asked to approve the text (KABUL) or reject it (RET) with concrete objections. Votes are counted by code, not by a model.
5. **Report.** The result is unanimous, majority, or "no consensus", with the text, remaining disagreements, uncertainties and a record of every call. If a rejection comes with a concrete objection, the text is revised once and voted on a second time.

For numeric questions, if the three Round 0 answers agree within a tolerance, the discussion is skipped (`TUR0_UZLASI`; this is not unanimity).

The orchestrator is an ordinary Python program: state, timeouts, vote counting and safety checks are code, not model instructions.

## Requirements

- macOS. Developed and tested only on macOS; the agy isolation step links the macOS Keychains folder, and other platforms were not tested.
- Python 3. Tested with 3.13; 3.10 or newer is expected but was not verified. Standard library only; there is no `requirements.txt`.
- The three official CLIs, each logged in with a subscription account (not an API key):
  - `claude` (Anthropic's Claude command-line tool)
  - `codex` (OpenAI Codex CLI)
  - `agy` (Google Antigravity CLI)

## Setup

```
git clone https://github.com/keremfarukozturk/konsey.git
cd konsey
python3 araclar/kurulum.py
```

`araclar/kurulum.py` is idempotent and does not overwrite existing files. It checks Python and the three commands, creates the session folder (`~/konsey-oturum`), writes the read-only agy hook (`.agents/hooks.json`) there, and sets up the isolated agy home (`~/.konsey-agy`) by calling `araclar/agy_yalitim_kur.py`. Use `--kontrol` to check without changing anything.

Then:

1. Log in once in each CLI (`claude`, `codex`, `agy`).
2. Edit `modeller.json`. The model names in the file are the maintainer's seats; replace them with models your accounts can use. Always write full model names. The Gemini seat must be a model whose name starts with `gemini-`. If `agy` is not at `~/.local/bin/agy`, set its path in the `komut` field.
3. Optional: set `KONSEY_OTURUM` (session folder) and `KONSEY_AGY_HOME` (isolated agy home) in the environment to use other locations. The session folder must be outside the repository folder.

## First run

```
caffeinate -i python3 konsey.py --duman
```

The smoke test asks each model one small question and checks the setup: tool surface, isolation, model identity, and quota where it can be read. It takes about a minute. If it reports a failure, do not ask real questions until it is resolved.

## Example use

```
caffeinate -i python3 konsey.py "Your question here?"
caffeinate -i python3 konsey.py -f question.md
caffeinate -i python3 konsey.py --arastir "A question that needs current sources?"
```

A question takes roughly 1 to 10 minutes. Keep the computer awake and online while it runs (`caffeinate -i` prevents idle sleep on macOS).

For numeric questions, ask for a last line in the form `SONUÇ: <number> <unit>`; the code uses it for the early-exit check.

## Options

Verified against `python3 konsey.py --help`.

| Option | Meaning |
|---|---|
| `soru` | The question text. |
| `-f`, `--soru-dosyasi FILE` | Read the question from a file. |
| `--kanit FILE` | Evidence file given verbatim to all three models. Models are offline; this is their only source. |
| `--baglam FILE` | Information about the asker. Sent in every round under its own heading; not treated as evidence. |
| `--tur N` | Maximum critique-and-correction rounds, 1 to 3 (default 1). Each extra round costs time and quota. |
| `--arastir` | Two researchers (Gemini and Codex) collect web sources using only the question text; the package is added to the evidence. Uses more quota. |
| `--arastir-onay` | Like `--arastir`, but shows the package and asks for confirmation first (needs a real terminal). |
| `--erken-cikis-yok` | Disable the Round 0 early exit for numeric questions. |
| `--tolerans X` | Largest relative difference between the three numeric results for early exit (default 0.01). |
| `--ayrinti` | Also print `ayrinti.md` to the terminal. |
| `--duman` | Smoke test. |
| `--duman-web` | Test that the researcher can reach the web. |
| `--zaman-asimi SEC` | Per-call time limit in seconds (the default comes from `modeller.json`, 600). |
| `--ayar FILE` | Settings file (default `modeller.json`). |
| `--tohum N` | Random seed for the ordering, to reproduce a run. |

With `--arastir` or `--kanit`, each evidence item gets an ID (K1, K2, ...). Models cite items as `[K3]`; code checks the citations (non-existent IDs, weak support labels) and adds "Kaynaklar" and "Atıf denetimi" sections to the report. The check confirms that a cited item exists and shows its labels; it does not verify that the item supports the claim.

## Outputs

Each run writes a folder `kayitlar/<date>_<seed>/` (outside Git). The main files:

- `rapor.md`: the report (also printed). Status, summary, answer, remaining disagreements, uncertainties, and a note with votes and verification status.
- `ayrinti.md`: every critique, what went to correction and what did not, decision counts, votes with reasons, tool checks, run information and quota before and after.
- `taslak.md`: the shared text.
- `telemetri.json`: durations and word counts.
- `kayit.json` and `tur0_<model>.json`: raw records.

Result statuses: `OYBIRLIGI` (all three approve), `COGUNLUK` (at least two approve), `UZLASI_YOK` (not enough approvals; the draft is shown as not approved), `TUR0_UZLASI` (numeric early exit), `YETERSIZ_KATILIM` (fewer than two models answered), `ARASTIRMA_DURDU` (research failed or was not confirmed).

Records contain your questions and the model answers. Keep that in mind before sharing a run folder.

## Quota notes

Quota is the practical limit. The OpenAI 5-hour window is usually the tightest. In the maintainer's runs on one set of consumer accounts: a numeric question that reached agreement in Round 0 took about 1 to 4 minutes; an open-ended question with one round took about 6 to 10 minutes and used roughly 5 to 11 percent of the 5-hour window. These are small-sample observations on one account, not guarantees. `--tur 2` roughly doubles time and quota, and `--arastir` adds more. The report's `ayrinti.md` shows quota before and after each run where the CLIs expose it. If a model's quota runs out, that seat's answer is missing and the council continues with two (at least two are required).

## Security model

- No API keys and no API credits. Only the official CLIs run, under your logged-in accounts. Provider-specific environment variables that could redirect a call to API billing or another account are removed from child processes.
- The models run without tools: Claude with its tools and MCP sources disabled, Codex with shell, connectors, plugins and web search disabled, agy in a separate isolated home with a hook that denies every tool call. Calls run from a folder outside the repository.
- These rules are checked by code after each call (tool lists, session records, permission denials, API-key source). A violation makes the call an error; it is not left to the prompt.
- The research package is untrusted data from the internet. Delimiters and labels reduce the risk of injected instructions but do not eliminate it.
- The orchestrator sends no HTTP requests of its own.

## Known limits

- Unanimity is not correctness. The three models can make the same mistake. Not measured: whether the council is more accurate than a single model. In the maintainer's small test sets, the council and single models gave the same results; the sets did not tell them apart.
- Citation checks are limited as described above; whether a source supports a claim is checked only by the models' votes.
- The agy auto-update could not be disabled; CLI versions can change silently. The smoke test and version records are the only guards.
- The test sets used for compliance checks were small and easy; sycophancy was not fully measured.
- Numeric parsing needs `SONUÇ: <number> <unit>`; a differing unit or an unreadable line counts as "no result" and the early exit is skipped.
- Factual claims without an evidence package are unverified shared opinion of the models.
- Tested only on macOS. Not a team or multi-user tool.

## Terms of use

Konsey runs the providers' official command-line tools with your accounts. You are responsible for complying with each provider's current terms of use. Some providers may restrict automated or multi-agent use of consumer subscriptions (check the terms especially for the Google Antigravity CLI). This software is not affiliated with or endorsed by any provider.

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Tests

```
python3 araclar/testleri_calistir.py
```

The suite uses fake CLIs; it makes no real model calls. Run it through this script (it uses a temporary HOME and fails if a test tries to write to your real home folder).
