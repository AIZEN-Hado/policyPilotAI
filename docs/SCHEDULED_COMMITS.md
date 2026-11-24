# Import this snapshot as 500 small commits

The script is `scripts/dev/schedule_commits.py`. It uses Python's standard library
and Git, without account tokens, network calls, automatic pushes or model downloads.
It creates an independent **bare repository** in
`artifacts/commit-schedule/repository.git`; the source directory is unchanged.

This source folder has no usable original Git history. The script therefore
labels every commit as a **retrospective snapshot import**, not an original
feature implementation or historical pivot. It splits text files at line
boundaries into exactly 500 non-empty tree changes and keeps PDFs/images whole.
Intermediate commits may contain incomplete code; deploy only the completed tree.
The initial `HISTORY_IMPORT.md` describes the documented project direction changes
and points to their records. Deleted intermediate implementations are not recreated.

## 1. Check identity and prepare

Run from the normal terminal:

```bash
cd /home/aizen/Downloads/PolicyPilotAI_ollama
git config --get user.name
git config --get user.email
python scripts/dev/schedule_commits.py prepare
```

The detected name is `AIZEN-Hado`. Both author and committer use the chosen name
and email. GitHub associates commits with the account owning the commit email,
not merely a matching display name. Check the email against GitHub Settings ->
Emails, or supply the exact GitHub-provided noreply email before preparation:

```bash
python scripts/dev/schedule_commits.py prepare \
  --author-name 'AIZEN-Hado' \
  --author-email 'COPY_YOUR_VERIFIED_OR_GITHUB_NOREPLY_EMAIL' \
  --directory artifacts/commit-schedule
```

Use one preparation command, not both. It will refuse an existing output directory
instead of overwriting a queue. If changing identity after preparing, make a fresh
queue with `--directory artifacts/commit-schedule-v2` and use that directory in all
following commands. No global Git settings are changed.

Preparation makes **zero commits**. Inspect `plan.json` for identity, start date,
all 500 messages and file ranges, then inspect `snapshot/` for export contents.
Only selected project/source/synthetic-data directories are included. Private
environment files, operator directories and `artifacts/` are excluded. Credential
prefix scanning aborts on known patterns; it cannot prove every file is secret-free.
Review before publishing. The frozen snapshot will not pick up later project edits.

## 2. Install and enable the local timer

```bash
python scripts/dev/schedule_commits.py install-timer
systemctl --user daemon-reload
systemctl --user enable --now policypilot-history-commits.timer
```

The installer only writes user service/timer files; the final command enables it.
No sudo or paid service is needed. The timer checks once per minute. The script
permits at most one commit in each of 50 daily slots, approximately 28 minutes
48 seconds apart, capped at 50 commits per calendar day in `Asia/Kolkata`.

By default, the first day starts at **midnight tomorrow** in that timezone, giving
ten complete online days for 500 commits. To begin today instead, supply
`--start-date YYYY-MM-DD` with today's local date during preparation. Partial days,
sleep, shutdown, logout that ends the user manager, missed slots or clock changes
can extend the schedule beyond ten days. It never backdates or bursts to catch up.
The computer and user timer must stay running. Turning off the computer pauses
progress without losing the queue. A user timer does not make an offline machine run.

This timer does not run a model or use any GPU/cloud budget. It does not stage
working files or commit later edits. Each tick performs one small import into the
separate repository, using a lock, real timestamps and crash recovery.

## 3. Check progress, pause or resume

```bash
python scripts/dev/schedule_commits.py status
systemctl --user list-timers policypilot-history-commits.timer
journalctl --user -u policypilot-history-commits.service -n 15 --no-pager
```

Pause:

```bash
systemctl --user disable --now policypilot-history-commits.timer
```

Resume:

```bash
systemctl --user enable --now policypilot-history-commits.timer
```

Do not edit the frozen snapshot, plan, scheduler state or bare repository while
the timer runs. These are separate from the source files you continue developing.
If an error occurs, pause and inspect; do not delete the queue as a first response.

## 4. Verify, then publish manually if desired

After status reaches 500/500:

```bash
systemctl --user disable --now policypilot-history-commits.timer
python scripts/dev/schedule_commits.py verify
git -C artifacts/commit-schedule/repository.git log -5 --format=fuller
git -C artifacts/commit-schedule/repository.git rev-list --count main
```

Verification checks final content hashes, executable modes, exact path set,
commit count, author/committer identity and Git object integrity. Only after
reviewing the result, create an **empty** GitHub repository: no README, license
or initial commit. Then run these commands yourself, replacing the repository name:

```bash
git -C artifacts/commit-schedule/repository.git remote add origin \
  git@github.com:AIZEN-Hado/YOUR_EMPTY_REPOSITORY.git
git -C artifacts/commit-schedule/repository.git push -u origin main
```

These manual commands are documentation only; the scheduler never invokes them.
There is no force push. Use a fresh repository rather than replacing another
project's history. Until you push, none of these local commits appears on GitHub.
Their recorded dates remain the actual days they were made. GitHub contribution
display also depends on its account-email, repository and default-branch rules.

References: [GitHub commit-email attribution](https://docs.github.com/en/account-and-profile/concepts/email-addresses),
[GitHub contribution rules](https://docs.github.com/en/account-and-profile/reference/profile-contributions-reference).

## Local verification

```bash
python -m unittest scripts.dev.test_schedule_commits -v
```

Tests create tiny fixture repositories only under temporary directories, with a
fixture author. They test 500-way partitioning without making 500 Git commits,
quota/slot timing, no catch-up bursts, credential filtering, author isolation,
hook isolation, final reconstruction, interrupted-state recovery and timer file
generation. They do not start the real project schedule.
