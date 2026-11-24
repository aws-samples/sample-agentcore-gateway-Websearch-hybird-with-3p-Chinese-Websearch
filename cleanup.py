"""Delete everything this sample created: harness, gateway targets, gateway, API key credential
providers, interceptor Lambda and its log group, IAM roles."""

import json
import time
from pathlib import Path

import boto3

REGION = "us-east-1"
PREFIX = "ic-reroute-poc"
STATE = Path(__file__).parent / "state.json"
state = json.loads(STATE.read_text()) if STATE.exists() else {}

sess = boto3.Session(region_name=REGION)
ctl, lam, iam = sess.client("bedrock-agentcore-control"), sess.client("lambda"), sess.client("iam")
logs = sess.client("logs")

if state.get("harness_id"):  # created by harness_demo.py
    try:
        ctl.delete_harness(harnessId=state["harness_id"])
    except ctl.exceptions.ResourceNotFoundException:
        pass

gid = state.get("gateway_id")
if gid:
    # Delete every target on this PoC gateway (not only the ones in state.json).
    try:
        targets = ctl.list_gateway_targets(gatewayIdentifier=gid).get("items") or []
    except ctl.exceptions.ResourceNotFoundException:
        targets = []
    for t in targets:
        try:
            ctl.delete_gateway_target(gatewayIdentifier=gid, targetId=t["targetId"])
        except ctl.exceptions.ResourceNotFoundException:
            pass
    for _ in range(30):
        if not targets or not ctl.list_gateway_targets(gatewayIdentifier=gid).get("items"):
            break
        time.sleep(5)  # nosemgrep: arbitrary-sleep -- polling interval while targets are deleted
    try:
        ctl.delete_gateway(gatewayIdentifier=gid)
    except ctl.exceptions.ResourceNotFoundException:
        pass

# API key credential providers created by store_*_key.py (all named "<PREFIX>-<provider>")
providers, token = [], None
while True:
    page = ctl.list_api_key_credential_providers(**({"nextToken": token} if token else {}))
    providers += [p["name"] for p in page.get("credentialProviders") or [] if p["name"].startswith(f"{PREFIX}-")]
    token = page.get("nextToken")
    if not token:
        break
for name in providers:
    try:
        ctl.delete_api_key_credential_provider(name=name)
    except ctl.exceptions.ResourceNotFoundException:
        pass

fn = f"{PREFIX}-interceptor"
try:
    lam.delete_function(FunctionName=fn)
except lam.exceptions.ResourceNotFoundException:
    pass
try:
    logs.delete_log_group(logGroupName=f"/aws/lambda/{fn}")
except logs.exceptions.ResourceNotFoundException:
    pass

for role in (f"{PREFIX}-gateway-role", f"{PREFIX}-lambda-role", f"{PREFIX}-harness-role"):
    try:
        for p in iam.list_role_policies(RoleName=role)["PolicyNames"]:
            iam.delete_role_policy(RoleName=role, PolicyName=p)
        for p in iam.list_attached_role_policies(RoleName=role)["AttachedPolicies"]:
            iam.detach_role_policy(RoleName=role, PolicyArn=p["PolicyArn"])
        iam.delete_role(RoleName=role)
    except iam.exceptions.NoSuchEntityException:
        pass

STATE.unlink(missing_ok=True)
print("cleaned up")
