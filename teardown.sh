#!/usr/bin/env bash
# teardown.sh — Delete the Smart Living Ledger CloudFormation stack
#
# Usage:
#   ./teardown.sh           # delete dev stack
#   ./teardown.sh staging   # delete staging stack
#
# IMPORTANT:
#   The DynamoDB table has DeletionPolicy: Retain — it will NOT be deleted
#   with the stack. This is intentional: you don't want to accidentally
#   lose all your IoT event history by running `sam delete`.
#
#   To delete the table manually after teardown:
#     aws dynamodb delete-table --table-name sll-events
#
# Why keep a teardown script?
#   The stack is throwaway per stage (dev/staging), so we need a repeatable
#   way to remove it without leaving orphaned resources billing quietly.
#   The table is retained on purpose so a teardown can't wipe event history.

set -euo pipefail

STAGE="${1:-dev}"
STACK_NAME="smart-living-ledger-${STAGE}"

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${RED}  Smart Living Ledger — TEARDOWN: ${YELLOW}${STAGE}${NC}"
echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${YELLOW}This will delete:${NC}"
echo "  - API Gateway"
echo "  - Lambda functions (ingest + query)"
echo "  - IAM roles"
echo "  - CloudWatch alarms and log groups"
echo ""
echo -e "${GREEN}This will NOT delete (DeletionPolicy: Retain):${NC}"
echo "  - DynamoDB table: sll-events"
echo ""
echo -e "${RED}Type the stack name to confirm: ${YELLOW}${STACK_NAME}${NC}"
read -r confirm

if [[ "$confirm" != "$STACK_NAME" ]]; then
    echo "Confirmation failed. Aborted."
    exit 1
fi

echo -e "\n${YELLOW}Deleting stack: ${STACK_NAME}...${NC}"
sam delete \
    --stack-name "$STACK_NAME" \
    --no-prompts \
    --region us-east-1

echo -e "\n${GREEN}✓ Stack deleted.${NC}"
echo ""
echo -e "${YELLOW}Note:${NC} DynamoDB table 'sll-events' was retained."
echo "To delete it manually:"
echo "  aws dynamodb delete-table --table-name sll-events"
echo ""
echo "To redeploy from scratch:"
echo "  ./deploy.sh ${STAGE}"
