# Deployment

OVOS Localize runs entirely on GitHub Pages + GitHub Actions. No external server needed.

## Setup

### 1. Enable GitHub Pages

In the repo settings → Pages → Source: deploy from `dev` branch, root `/`.

The SPA (`index.html`) and data files (`data/`) are served directly.

### 2. Create a GitHub App

Translation submissions work via a GitHub Action that creates PRs on skill repos. This uses a **GitHub App** (not a personal token) so PRs come from a bot identity.

**Create the App:**
1. Go to **github.com/organizations/OpenVoiceOS/settings/apps/new**
2. Fill in:
   - **Name**: `ovos-localize`
   - **Homepage URL**: `https://openvoiceos.github.io/ovos-localize/`
   - **Webhook**: uncheck "Active" (not needed)
3. **Permissions → Repository permissions**:
   - **Contents**: Read and write (to create branches and commit files)
   - **Pull requests**: Read and write (to open PRs)
4. **Where can this app be installed?**: "Only on this account"
5. Click **Create GitHub App**
6. Note the **App ID** shown on the settings page

**Generate a private key:**
1. On the App settings page, scroll to "Private keys"
2. Click **Generate a private key** — downloads a `.pem` file

**Install the App:**
1. Go to the App's page → **Install App**
2. Select the **OpenVoiceOS** organization
3. Choose **All repositories** (the bot needs access to any skill repo)
4. Click **Install**

**Add to the ovos-localize repo:**
1. Settings → **Variables → Actions** → New variable:
   - Name: `LOCALIZE_APP_ID`, Value: the App ID from step 6
2. Settings → **Secrets → Actions** → New secret:
   - Name: `LOCALIZE_APP_PRIVATE_KEY`, Value: paste the entire contents of the `.pem` file

### 3. How it works

```
User (browser)                    GitHub
──────────────                    ──────
1. Edit translation
2. Click "Submit"
3. POST /repos/OpenVoiceOS/     ──→  repository_dispatch event
   ovos-localize/dispatches          (event_type: submit-translation)
                                      │
                                      ▼
                                 submit_translation.yml runs:
                                 ├── actions/create-github-app-token
                                 │   generates a short-lived token
                                 │   scoped to the target skill repo
                                 ├── Checks out target skill repo
                                 ├── Creates translate/{lang}/{file} branch
                                 ├── Commits as ovos-localize[bot]
                                 └── Opens PR to dev branch
                                     (mentions @username in body)
```

**Key properties:**
- The GitHub App token is **short-lived** (expires in 1 hour) and scoped to the single target repo
- PRs appear as authored by `ovos-localize[bot]` — not tied to any personal account
- No personal tokens or service accounts needed for the bot side
- The user's token only needs permission to trigger `repository_dispatch` on the ovos-localize repo

### 4. Daily data refresh

`update_data.yml` runs daily at 02:00 UTC:
- Clones all repos in `skills.txt`
- Scans locale files, runs AST analysis + validation
- Commits updated JSON to `data/`
- GitHub Pages auto-deploys

### 5. User token permissions

Users create a fine-grained PAT scoped to the `ovos-localize` repo only, with:
- **Contents**: Read and write (required to trigger `repository_dispatch` events)

This is the minimum permission needed. Users never get write access to skill repos.

### 6. Summary of secrets/variables

| Name | Type | Where | Purpose |
|------|------|-------|---------|
| `LOCALIZE_APP_ID` | Variable | ovos-localize repo | GitHub App ID |
| `LOCALIZE_APP_PRIVATE_KEY` | Secret | ovos-localize repo | GitHub App private key (.pem) |
