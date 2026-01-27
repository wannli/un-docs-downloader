#!/bin/bash
# Analyze GitHub Actions workflow metrics
# Usage: ./scripts/analyze-workflow-metrics.sh [workflow_name] [limit]
#
# This script fetches workflow run data from GitHub Actions and displays
# summary statistics to help identify optimization opportunities.
#
# Prerequisites:
#   - GitHub CLI (gh) must be installed and authenticated
#   - jq must be installed for JSON processing
#
# Examples:
#   ./scripts/analyze-workflow-metrics.sh              # All workflows, last 10 runs each
#   ./scripts/analyze-workflow-metrics.sh generate 20  # Generate workflow, last 20 runs
#   ./scripts/analyze-workflow-metrics.sh discover     # Discover workflow, last 10 runs

set -e

WORKFLOW_NAME="${1:-all}"
LIMIT="${2:-10}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  GitHub Actions Workflow Metrics Analyzer${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# Check prerequisites
if ! command -v gh &> /dev/null; then
    echo -e "${RED}Error: GitHub CLI (gh) is not installed${NC}"
    echo "Install it from: https://cli.github.com/"
    exit 1
fi

if ! command -v jq &> /dev/null; then
    echo -e "${RED}Error: jq is not installed${NC}"
    echo "Install it with: apt-get install jq (or brew install jq)"
    exit 1
fi

# Get repository info
REPO=$(gh repo view --json nameWithOwner -q '.nameWithOwner' 2>/dev/null || echo "")
if [ -z "$REPO" ]; then
    echo -e "${RED}Error: Not in a GitHub repository or not authenticated${NC}"
    exit 1
fi

echo -e "Repository: ${GREEN}$REPO${NC}"
echo -e "Workflow: ${GREEN}$WORKFLOW_NAME${NC}"
echo -e "Limit: ${GREEN}$LIMIT runs${NC}"
echo ""

analyze_workflow() {
    local workflow=$1
    local limit=$2

    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}  Workflow: $workflow${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    # Fetch workflow runs
    runs=$(gh run list --workflow="$workflow" --limit="$limit" --json databaseId,status,conclusion,createdAt,updatedAt,event 2>/dev/null || echo "[]")

    if [ "$runs" = "[]" ] || [ -z "$runs" ]; then
        echo -e "${RED}  No runs found for workflow: $workflow${NC}"
        return
    fi

    # Calculate statistics
    total_runs=$(echo "$runs" | jq 'length')
    successful=$(echo "$runs" | jq '[.[] | select(.conclusion == "success")] | length')
    failed=$(echo "$runs" | jq '[.[] | select(.conclusion == "failure")] | length')
    cancelled=$(echo "$runs" | jq '[.[] | select(.conclusion == "cancelled")] | length')

    # Calculate success rate
    if [ "$total_runs" -gt 0 ]; then
        success_rate=$(echo "scale=1; $successful * 100 / $total_runs" | bc)
    else
        success_rate=0
    fi

    echo ""
    echo "  📊 Run Statistics (last $limit runs):"
    echo "  ├── Total Runs: $total_runs"
    echo "  ├── Successful: $successful"
    echo "  ├── Failed: $failed"
    echo "  ├── Cancelled: $cancelled"
    echo "  └── Success Rate: ${success_rate}%"
    echo ""

    # Get trigger breakdown
    echo "  🎯 Triggers:"
    echo "$runs" | jq -r '.[].event' | sort | uniq -c | sort -rn | while read count event; do
        echo "  ├── $event: $count"
    done
    echo ""

    # Show recent runs with timing
    echo "  ⏱️  Recent Runs:"
    echo "$runs" | jq -r '.[:5] | .[] | "  ├── \(.createdAt | split("T")[0]) | \(.conclusion // "running") | \(.event)"'
    echo ""
}

# Get list of workflows
if [ "$WORKFLOW_NAME" = "all" ]; then
    workflows=$(gh workflow list --json name -q '.[].name' 2>/dev/null || echo "")
    if [ -z "$workflows" ]; then
        echo -e "${RED}No workflows found${NC}"
        exit 1
    fi

    echo "$workflows" | while read workflow; do
        analyze_workflow "$workflow" "$LIMIT"
    done
else
    analyze_workflow "$WORKFLOW_NAME" "$LIMIT"
fi

echo ""
echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  Tips for Analyzing Logs${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""
echo "1. View Step Summaries in GitHub Actions UI:"
echo "   - Go to Actions tab → Select a run → See Summary at top"
echo ""
echo "2. Search for timing annotations in logs:"
echo "   - Look for '::notice::' lines with duration_seconds"
echo "   - Format: step=<name> duration_seconds=<N>"
echo ""
echo "3. Download logs for bulk analysis:"
echo "   gh run download <run-id> --dir ./logs"
echo ""
echo "4. View specific run details:"
echo "   gh run view <run-id> --log"
echo ""
echo "5. Check build-metrics.json in docs/ for generation stats"
echo ""
