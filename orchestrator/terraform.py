# orchestrator/terraform.py

import subprocess
import os
import json

TF_DIR = os.path.join(os.path.dirname(__file__), "..", "terraform")


def run_terraform(cmd: list, workspace: str, env_vars: dict = None) -> str:
    env = os.environ.copy()

    if env_vars:
        env.update(env_vars)

    try:
        result = subprocess.run(
            cmd,
            cwd=TF_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min timeout
        )
    except subprocess.TimeoutExpired:
        raise Exception(f"Terraform command timed out after 10 minutes: {' '.join(cmd)}")

    if result.returncode != 0:
        raise Exception(
            f"Terraform failed:\n"
            f"CMD: {' '.join(cmd)}\n"
            f"STDOUT: {result.stdout}\n"
            f"STDERR: {result.stderr}"
        )
    return result.stdout


def create_workspace(workspace: str):
    # -or-create: selects if exists, creates if not — no try/except needed
    run_terraform(["terraform", "workspace", "select", "-or-create", workspace], workspace)


def apply(user_id: str, cidr: str, lab_name: str, vpn_ip: str, workspace: str, lab_password: str) -> dict:
    create_workspace(workspace)
    run_terraform(
        [
            "terraform", "apply", "-auto-approve",
            f"-var=user_id={user_id}",
            f"-var=cidr_block={cidr}",
            f"-var=lab_name={lab_name}",
            f"-var=vpn_server_ip={vpn_ip}",
            f"-var=lab_password={lab_password}",   # NEW: password for labuser account
            f"-var=admin_key_name=terrakey",        # NEW: admin emergency SSH key
        ],
        workspace,
    )
    out = run_terraform(["terraform", "output", "-json"], workspace)
    return json.loads(out)


def destroy(workspace: str, user_id: str, cidr: str, lab_name: str, vpn_ip: str, lab_password: str):
    # Explicitly select workspace before destroying
    try:
        run_terraform(["terraform", "workspace", "select", workspace], workspace)
    except Exception as e:
        raise Exception(
            f"Could not select workspace '{workspace}' for destroy — "
            f"it may have already been deleted or never created: {e}"
        )

    run_terraform(
        [
            "terraform", "destroy", "-auto-approve",
            f"-var=user_id={user_id}",
            f"-var=cidr_block={cidr}",
            f"-var=lab_name={lab_name}",
            f"-var=vpn_server_ip={vpn_ip}",
            f"-var=lab_password={lab_password}",   # required — variable has no default
            f"-var=admin_key_name=terrakey",
        ],
        workspace,
    )

    # Delete the workspace after destroying all resources
    try:
        run_terraform(["terraform", "workspace", "select", "default"], "default")
        run_terraform(["terraform", "workspace", "delete", workspace], "default")
    except Exception as e:
        print(f"[WARN] Could not delete workspace '{workspace}' after destroy: {e}")