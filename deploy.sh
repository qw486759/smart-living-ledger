#!/usr/bin/env bash
# deploy.sh — Build and deploy Event-Driven IoT Platform to AWS via SAM
#
# Usage:
#   ./deploy.sh           # deploy to dev
#   ./deploy.sh staging   # deploy to staging
#   ./deploy.sh prod      # deploy to prod (requires explicit confirmation)
#
# Prerequisites:
#   - AWS CLI configured (aws sts get-caller-identity should work)
#   - SAM CLI installed (sam --version)
#   - Python 3.12 available
#
# What this script does:
#   1. Validates the SAM template (catches YAML/CloudFormation errors before deploy)
#   2. Builds Lambda packages (installs requirements.txt into deployment zips)
#   3. Deploys to AWS (creates/updates CloudFormation stack)
#   4. Prints the API URL for use in simulator + dashboard

set -euo pipefail  # Exit on error, undefined var, or pipe failure

STAGE="${1:-dev}"
TEMPLATE="infra/template.yaml"
CONFIG="samconfig.toml"

# ── Colour output ──────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Colour

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Event-Driven IoT Platform — Deploy to: ${YELLOW}${STAGE}${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# ── Safety check for prod ──────────────────────────────────────────────────
if [[ "$STAGE" == "prod" ]]; then
    echo -e "${RED}⚠️  Deploying to PRODUCTION. Are you sure? (yes/no)${NC}"
    read -r confirm
    if [[ "$confirm" != "yes" ]]; then
        echo "Aborted."
        exit 1
    fi
fi

# ── 1. Validate template ───────────────────────────────────────────────────
echo -e "\n${YELLOW}[1/3] Validating SAM template...${NC}"
sam validate \
    --template "$TEMPLATE" \
    --lint
echo -e "${GREEN}✓ Template valid${NC}"

# ── 2. Build ───────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}[2/3] Building Lambda packages...${NC}"
# SAM build:
#   - Reads each function's CodeUri
#   - Installs requirements.txt into .aws-sam/build/<FunctionName>/
#   - Creates a clean deployment artifact
sam build \
    --template "$TEMPLATE" \
    --config-file "$CONFIG"
echo -e "${GREEN}✓ Build complete${NC}"

# ── 3. Deploy ──────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}[3/3] Deploying to AWS (stage: ${STAGE})...${NC}"
echo -e "      This will show a changeset diff. Review before confirming.\n"

sam deploy \
    --config-file "$CONFIG" \
    --config-env "$STAGE"

# ── 4. Print outputs ───────────────────────────────────────────────────────
STACK_NAME="event-driven-iot-platform-${STAGE}"
echo -e "\n${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Deploy complete! Stack outputs:${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[*].[OutputKey,OutputValue]" \
    --output table

echo -e "\n${YELLOW}Next steps:${NC}"
echo "  1. Run the simulator:"
echo "     export EIP_INGEST_URL=<IngestEndpoint above>"
echo "     python simulator/simulator.py"
echo ""
echo "  2. Open the dashboard:"
echo "     Copy dashboard/config.example.js to dashboard/config.js"
echo "     Set window.EIP_API_BASE to <QueryEndpoint above>"
echo "     Open dashboard/index.html in a browser"
