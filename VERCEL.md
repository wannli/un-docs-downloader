# Vercel Deployment Setup

This repository is configured to deploy PR previews using Vercel while maintaining the data pipeline in GitHub Actions.

## Architecture

### Data Pipeline (GitHub Actions)
The core document processing remains in GitHub Actions:

1. **discover.yml** - Downloads UN documents from ODS API
2. **extract.yml** - Extracts text from PDFs
3. **detect.yml** - Identifies mandate-related signals
4. **link.yml** - Links related documents
5. **generate.yml** - Generates static site (master branch only)

All workflows commit processed data to `data/` directories and the final site to `docs/`.

### Vercel Deployment
Vercel provides PR previews by:

1. Reading pre-processed data from `data/linked/` (committed by GitHub Actions)
2. Running the static site generator via `scripts/vercel_build.py`
3. Serving the generated `docs/` folder as a static site
4. Creating preview URLs for every PR

## Setup Instructions

### 1. Connect Repository to Vercel

1. Go to [vercel.com](https://vercel.com) and sign in with GitHub
2. Click "Add New Project"
3. Import the `wannli/mandate-pipeline` repository
4. Vercel will auto-detect the configuration from `vercel.json`
5. Click "Deploy"

### 2. Configure Vercel Project Settings

In your Vercel project settings:

- **Build & Development Settings**:
  - Framework Preset: Other
  - Build Command: `pip install -e . && python scripts/vercel_build.py`
  - Output Directory: `docs`
  - Install Command: `pip install --upgrade pip`

- **Git Integration**:
  - Enable "Automatic Deployments from GitHub"
  - Enable "Deploy Previews" for all branches
  - Enable "Auto-merge deployments" (optional)

### 3. Environment Variables (Optional)

No environment variables are required by default. The build script uses:

- Pre-processed data from `data/linked/` (committed by GitHub Actions)
- Configuration from `config/` directory
- IGov decisions from `data/igov/`

### 4. Test the Deployment

1. Create a test PR
2. Vercel will automatically:
   - Detect the PR
   - Run the build script
   - Deploy a preview
   - Comment on the PR with the preview URL

## How It Works

### Build Process

```bash
# Install dependencies
pip install --upgrade pip
pip install -e .

# Generate static site
python scripts/vercel_build.py
```

The build script (`scripts/vercel_build.py`):
1. Loads documents from `data/linked/*.json`
2. Loads IGov decisions from `data/igov/`
3. Loads signal rules from `config/checks.yaml`
4. Generates `docs/index.html` and `docs/data.json`
5. Creates a complete static site in `docs/`

### What Gets Deployed

- **index.html** - Main interactive explorer
- **data.json** - All document data for client-side filtering
- **search-index.json** - Full-text search index
- **sessions/** - Per-session pages
- **igov/** - IGov decision pages
- Other static HTML pages

## PR Preview Workflow

1. **Developer creates PR** with source code changes
2. **GitHub Actions run** (if data/config changed):
   - Process any new documents
   - Update `data/linked/` with results
   - Commit back to PR branch
3. **Vercel builds preview**:
   - Reads latest `data/linked/` from PR branch
   - Generates fresh static site
   - Deploys to preview URL
4. **Preview URL appears** in PR comments
5. **Every push updates preview** automatically

## Benefits

✅ **PR Previews**: See changes instantly without merging
✅ **Fast Builds**: ~30-60s (vs 5+ min for full pipeline)
✅ **Cost Effective**: Vercel free tier sufficient for most projects
✅ **No Code Changes**: Data pipeline stays in GitHub Actions
✅ **Automatic**: Zero configuration after initial setup

## Troubleshooting

### Build Failures

If Vercel build fails, check:

1. **Python dependencies**: Ensure `pyproject.toml` has all requirements
2. **Data availability**: PR might not have `data/linked/` yet
3. **Build logs**: Check Vercel dashboard for detailed errors

### Empty Preview

If preview loads but shows no documents:

1. **Data not committed**: GitHub Actions may not have run yet
2. **Check PR branch**: Ensure `data/linked/` has JSON files
3. **Manual trigger**: Run `discover.yml` → `extract.yml` → `detect.yml` → `link.yml`

### Preview Out of Sync

If preview doesn't reflect latest changes:

1. **Push again**: Vercel triggers on push events
2. **Check deployment**: Visit Vercel dashboard
3. **Redeploy**: Use "Redeploy" button in Vercel

## Comparison: GitHub Pages vs Vercel

| Feature | GitHub Pages | Vercel |
|---------|-------------|--------|
| Master deployment | ✅ Yes | ✅ Yes |
| PR previews | ❌ No | ✅ Yes |
| Build time | 5-10 min | 30-60s |
| Custom domains | ✅ Yes | ✅ Yes |
| HTTPS | ✅ Yes | ✅ Yes |
| Cost | Free | Free tier |

**Recommendation**: Use both!
- GitHub Pages for official site (master branch)
- Vercel for PR previews (all branches)

## Files

- `vercel.json` - Vercel project configuration
- `scripts/vercel_build.py` - Build script for Vercel
- `.gitignore` - Excludes `.vercel/` directory

## Additional Resources

- [Vercel Documentation](https://vercel.com/docs)
- [Vercel GitHub Integration](https://vercel.com/docs/concepts/git/vercel-for-github)
- [Python on Vercel](https://vercel.com/docs/concepts/functions/serverless-functions/runtimes/python)
