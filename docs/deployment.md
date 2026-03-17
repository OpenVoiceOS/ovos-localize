# Deployment

OVOS Localize runs entirely on GitHub Pages + GitHub Actions. No external server needed.

## Setup

### 1. Enable GitHub Pages

In the repo settings → Pages → Source: deploy from `dev` branch, root `/`.

The SPA (`index.html`) and data files (`data/`) are served directly.

### 2. Configure the bot token

Translation submissions work via a GitHub Action that creates PRs on behalf of users. This requires a **bot token** stored as a repository secret.

**Create a fine-grained PAT for the bot:**
1. Go to [github.com/settings/personal-access-tokens/new](https://github.com/settings/personal-access-tokens/new)
2. Name: `ovos-localize-bot`
3. Resource owner: `OpenVoiceOS`
4. Repository access: **All repositories** (the bot needs to create branches + PRs on any skill repo)
5. Permissions:
   - **Contents**: Read and write (to commit files)
   - **Pull requests**: Read and write (to open PRs)
6. Generate and copy the token

**Add as repo secret:**
1. Go to the ovos-localize repo → Settings → Secrets → Actions
2. New repository secret: `BOT_TOKEN` = the token you just created

### 3. How it works

```
User (browser)                    GitHub
─────────────                    ──────
1. Edit translation
2. Click "Submit"
3. POST /repos/OpenVoiceOS/     ──→  repository_dispatch event
   ovos-localize/dispatches          (event_type: submit-translation)
                                      │
                                      ▼
                                 submit_translation.yml runs:
                                 - Checks out target skill repo
                                 - Creates translate/{lang}/{file} branch
                                 - Commits the translated file
                                 - Opens PR to dev branch
                                 - PR body mentions @username
```

The user's token only needs permission to trigger dispatches on ovos-localize. The `BOT_TOKEN` secret handles the actual repo writes and PR creation.

### 4. Daily data refresh

`update_data.yml` runs daily at 02:00 UTC:
- Clones all repos in `skills.txt`
- Scans locale files, runs AST analysis + validation
- Commits updated JSON to `data/`
- GitHub Pages auto-deploys

### 5. User token permissions

Users create a fine-grained PAT scoped to the `ovos-localize` repo only, with:
- **Actions**: Read and write (to trigger `repository_dispatch`)

This is the minimum permission needed. Users never get write access to skill repos.
