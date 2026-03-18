"""Claude CLI client — uses Max plan OAuth via subprocess.

Calls the `claude` CLI binary which authenticates via OAuth (same as Claude Code).
No API key needed. Uses your Max plan at zero extra cost.
"""
import asyncio
import json
import re
import logging
from typing import Optional

log = logging.getLogger(__name__)


async def claude_chat(prompt: str, model: str = "sonnet", max_tokens: int = 300) -> str:
    """Send a prompt to Claude via CLI and return the response text.

    Uses `claude --print` which outputs the response directly to stdout.
    The CLI handles OAuth authentication transparently.
    """
    cmd = [
        "claude",
        "--print",
        "--model", model,
        "--max-turns", "1",
        prompt,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            err = stderr.decode().strip()
            log.warning("claude CLI returned %d: %s", proc.returncode, err[:200])
            return ""
        return stdout.decode().strip()
    except asyncio.TimeoutError:
        log.warning("claude CLI timed out after 120s")
        proc.kill()
        return ""
    except FileNotFoundError:
        log.error("claude CLI not found — is Claude Code installed?")
        return ""
    except Exception as e:
        log.warning("claude CLI error: %s", str(e)[:200])
        return ""


async def claude_json(prompt: str, model: str = "sonnet", max_tokens: int = 300) -> Optional[dict]:
    """Send a prompt and parse JSON from the response."""
    response = await claude_chat(prompt, model=model, max_tokens=max_tokens)
    if not response:
        return None
    # Extract JSON from response
    json_match = re.search(r'\{.*\}', response, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        log.warning("Failed to parse JSON from claude response: %s", response[:200])
        return None
