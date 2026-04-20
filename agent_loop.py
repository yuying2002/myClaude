import os
import subprocess
import re
import time
import json
from pathlib import Path
try:
    import yaml
except ImportError:
    yaml = None

try:
    import readline
    # #143 UTF-8 backspace fix for macOS libedit
    readline.parse_and_bind("set bind-tty-special-chars off")
    readline.parse_and_bind("set input-meta on")
    readline.parse_and_bind("set output-meta on")
    readline.parse_and_bind("set convert-meta off")
    readline.parse_and_bind("set enable-meta-keybindings on")
except ImportError:
    pass

from dotenv import load_dotenv
from openai import APIError, OpenAI, RateLimitError

load_dotenv(override=True)

MODEL = os.getenv("MODEL_ID", "qwen/qwen3-coder:free")
BASE_URL = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
WORKDIR = Path.cwd()
SKILLS_DIR = WORKDIR / "skills"

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url=BASE_URL)


class SkillLoader:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.skills: dict[str, dict] = {}
        self._load_all()

    def _load_all(self) -> None:
        if not self.skills_dir.exists():
            return
        for file_path in sorted(self.skills_dir.rglob("SKILL.md")):
            text = self._read_text(file_path)
            meta, body = self._parse_frontmatter(text)
            name = str(meta.get("name", file_path.parent.name))
            self.skills[name] = {
                "meta": meta,
                "body": body,
                "path": str(file_path),
            }

    def _read_text(self, path: Path) -> str:
        encodings = ("utf-8", "utf-16", "utf-16-le", "utf-16-be", "gbk")
        for encoding in encodings:
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        return path.read_text(encoding="utf-8", errors="replace")

    def _parse_frontmatter(self, text: str) -> tuple[dict, str]:
        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text.strip()
        if yaml is None:
            return {}, match.group(2).strip()
        try:
            meta = yaml.safe_load(match.group(1)) or {}
        except Exception:
            meta = {}
        return meta if isinstance(meta, dict) else {}, match.group(2).strip()

    def get_descriptions(self) -> str:
        if not self.skills:
            return "(no skills available)"
        lines: list[str] = []
        for name, skill in self.skills.items():
            meta = skill["meta"]
            desc = str(meta.get("description", "No description"))
            tags = str(meta.get("tags", "")).strip()
            line = f"  - {name}: {desc}"
            if tags:
                line += f" [{tags}]"
            lines.append(line)
        return "\n".join(lines)

    def get_content(self, name: str) -> str:
        skill = self.skills.get(name)
        if not skill:
            available = ", ".join(sorted(self.skills.keys())) or "(none)"
            return f"Error: Unknown skill '{name}'. Available: {available}"
        body = str(skill["body"]).strip()
        return f"<skill name=\"{name}\">\n{body}\n</skill>"[:50000]


SKILL_LOADER = SkillLoader(SKILLS_DIR)
SYSTEM = (
    f"You are a coding agent at {WORKDIR} on Windows. "
    "Use shell commands via Windows cmd semantics (dir /b, type, cd are valid). "
    "Use todo tool to plan multi-step tasks: mark in_progress before work, completed when done. "
    "You can use tools: bash, read_file, write_file, edit_file, todo, load_skill. "
    "When domain knowledge is uncertain, call load_skill before implementation. "
    "Avoid Linux-only assumptions. Act, don't explain.\n\n"
    "Skills available:\n"
    f"{SKILL_LOADER.get_descriptions()}"
)
SUBAGENT_SYSTEM = (
    f"You are a coding subagent at {WORKDIR} on Windows. "
    "Complete the assigned task with available tools, then return a concise summary. "
    "When domain knowledge is uncertain, call load_skill first. "
    "No delegation."
)

CHILD_TOOLS = [{
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Run a shell command.",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
}, {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read file contents from workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["path"],
        },
    },
}, {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "Write content to file in workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
}, {
    "type": "function",
    "function": {
        "name": "edit_file",
        "description": "Replace first exact old_text with new_text in file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
}, {
    "type": "function",
    "function": {
        "name": "load_skill",
        "description": "Load specialized skill instructions by name.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
            "required": ["name"],
        },
    },
}, {
    "type": "function",
    "function": {
        "name": "todo",
        "description": "Update task list for planning and progress tracking.",
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "text": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                            },
                        },
                        "required": ["id", "text", "status"],
                    },
                }
            },
            "required": ["items"],
        },
    },
}]

PARENT_TOOLS = CHILD_TOOLS + [{
    "type": "function",
    "function": {
        "name": "task",
        "description": "Spawn a subagent with fresh context. It shares filesystem state but not conversation history.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["prompt"],
        },
    },
}]


class TodoManager:
    def __init__(self):
        self.items: list[dict] = []

    def update(self, items: list) -> str:
        if len(items) > 20:
            raise ValueError("Max 20 todos allowed")
        validated = []
        in_progress_count = 0
        for i, item in enumerate(items):
            text = str(item.get("text", "")).strip()
            status = str(item.get("status", "pending")).lower()
            item_id = str(item.get("id", str(i + 1)))
            if not text:
                raise ValueError(f"Item {item_id}: text required")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {item_id}: invalid status '{status}'")
            if status == "in_progress":
                in_progress_count += 1
            validated.append({"id": item_id, "text": text, "status": status})
        if in_progress_count > 1:
            raise ValueError("Only one task can be in_progress at a time")
        self.items = validated
        return self.render()

    def render(self) -> str:
        if not self.items:
            return "No todos."
        lines = []
        markers = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}
        for item in self.items:
            lines.append(f"{markers[item['status']]} #{item['id']}: {item['text']}")
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)


TODO = TodoManager()


def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    if "<<" in command:
        return (
            "Error: Bash heredoc syntax ('<<') is not supported in Windows cmd. "
            "Use write_file/edit_file tools or Windows-compatible commands."
        )
    try:
        r = subprocess.run(
            ["cmd", "/c", command],
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"


def _read_text_with_fallback(path: Path) -> str:
    encodings = ("utf-8", "utf-16", "utf-16-le", "utf-16-be", "gbk")
    for encoding in encodings:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def run_read(path: str, limit: int | None = None) -> str:
    try:
        text = _read_text_with_fallback(safe_path(path))
        lines = text.splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        result = "\n".join(lines)
        return result[:50000] if result else "(empty file)"
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        content = _read_text_with_fallback(fp)
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "load_skill": lambda **kw: SKILL_LOADER.get_content(str(kw["name"])),
    "todo": lambda **kw: TODO.update(kw["items"]),
}


def _extract_retry_seconds(msg: str, default: int = 20) -> int:
    match = re.search(r"retry in ([0-9]+(?:\.[0-9]+)?)s", msg, re.IGNORECASE)
    if not match:
        return default
    return max(1, int(float(match.group(1)) + 0.5))


def _create_with_retry(messages: list[dict], tools: list[dict], temperature: float = 0.2):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=temperature,
            )
        except RateLimitError as e:
            text = str(e)
            if attempt < max_retries - 1:
                delay = _extract_retry_seconds(text)
                print(f"[rate-limit] retrying in {delay}s...")
                time.sleep(delay)
                continue
            raise RuntimeError(f"API Error: {text}") from e
        except APIError as e:
            raise RuntimeError(f"API Error: {e}") from e
    raise RuntimeError("API Error: request failed after retries")


def _parse_tool_args(raw_args: str) -> dict:
    try:
        parsed = json.loads(raw_args or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _command_likely_creates_artifacts(command: str) -> bool:
    c = command.lower()
    if any(tok in c for tok in ("mkdir", "md ", "copy ", "move ", "ren ", "type nul >", "echo ")):
        return True
    return ">" in c and "2>" not in c


def _todos_all_completed(items: list[dict]) -> bool:
    if not items:
        return False
    return all(str(item.get("status", "")).lower() == "completed" for item in items)


def run_subagent(prompt: str) -> str:
    # Fresh context for subagent; parent history is intentionally not shared.
    sub_messages: list[dict] = [
        {"role": "system", "content": SUBAGENT_SYSTEM},
        {"role": "user", "content": prompt},
    ]

    for _ in range(30):
        response = _create_with_retry(sub_messages, CHILD_TOOLS, temperature=0.1)
        if not response.choices:
            return "(no subagent response)"

        message = response.choices[0].message
        sub_messages.append(message.model_dump(exclude_none=True))
        function_calls = message.tool_calls or []

        if not function_calls:
            return (message.content or "").strip() or "(no subagent summary)"

        for call in function_calls:
            args = _parse_tool_args(call.function.arguments)
            tool_name = call.function.name
            handler = TOOL_HANDLERS.get(tool_name)
            try:
                output = handler(**args) if handler else f"Unknown tool: {tool_name}"
            except Exception as e:
                output = f"Error: {e}"
            sub_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": output,
                }
            )
    return "Error: Subagent exceeded max tool rounds (30)"


# -- The core pattern: a while loop that calls tools until the model stops --
def agent_loop(messages: list[dict]) -> str:
    rounds_since_todo = 0
    artifact_events = 0
    while True:
        try:
            response = _create_with_retry(messages, PARENT_TOOLS)
        except RuntimeError as e:
            return str(e)

        if not response.choices:
            return "(no model response)"

        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))
        function_calls = message.tool_calls or []

        if not function_calls:
            return (message.content or "").strip() or "(no output)"

        for call in function_calls:
            parsed = _parse_tool_args(call.function.arguments or "{}")
            tool_name = call.function.name
            if tool_name == "task":
                desc = str(parsed.get("description", "subtask"))
                prompt = str(parsed.get("prompt", ""))
                print(f"> task ({desc}):")
                output = run_subagent(prompt)
            else:
                handler = TOOL_HANDLERS.get(tool_name)
                try:
                    if tool_name == "todo":
                        items = parsed.get("items", [])
                        if isinstance(items, list) and _todos_all_completed(items) and artifact_events == 0:
                            output = (
                                "Error: Cannot mark all todos as completed yet. "
                                "No code/file artifacts were created in this run. "
                                "Create or modify files (or explicitly verify existing outputs) before completion."
                            )
                        else:
                            output = handler(**parsed) if handler else f"Unknown tool: {tool_name}"
                    else:
                        output = handler(**parsed) if handler else f"Unknown tool: {tool_name}"
                except Exception as e:
                    output = f"Error: {e}"
            print(f"> {tool_name}:")
            print(output[:200])
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": output,
                }
            )
            if tool_name in ("write_file", "edit_file") and not str(output).startswith("Error:"):
                artifact_events += 1
            if tool_name == "bash":
                command = str(parsed.get("command", ""))
                if _command_likely_creates_artifacts(command) and not str(output).startswith("Error:"):
                    artifact_events += 1
            if tool_name == "todo":
                rounds_since_todo = 0

        if all(call.function.name != "todo" for call in function_calls):
            rounds_since_todo += 1
            if rounds_since_todo >= 3:
                messages.append(
                    {
                        "role": "user",
                        "content": "<reminder>Update your todos.</reminder>",
                    }
                )


if __name__ == "__main__":
    history = [{"role": "system", "content": SYSTEM}]
    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        final_text = agent_loop(history)
        print(final_text)
        print()