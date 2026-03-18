"""ezagent HTTP + WebSocket API server.

Start with: ez serve [--port 7771] [--host 127.0.0.1]
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import socket as _socket
import sqlite3
import subprocess
import sys
from pathlib import Path

import yaml
from fastapi import Body, FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ezagent.config import ProjectConfig


# ─── Socket helper ────────────────────────────────────────────────────────────

def _send_socket_sync(config: ProjectConfig, request: dict) -> list[dict]:
    """Blocking socket call to the daemon. Returns parsed response lines."""
    sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    sock.settimeout(300)
    try:
        sock.connect(config.socket_path)
    except (FileNotFoundError, ConnectionRefusedError, OSError):
        raise HTTPException(
            status_code=503,
            detail="Daemon not running. Start with: ez start",
        )
    sock.sendall(json.dumps(request).encode())
    sock.shutdown(_socket.SHUT_WR)
    buffer = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buffer += chunk
    sock.close()
    return [json.loads(line) for line in buffer.decode().strip().split("\n") if line]


async def _send_socket(config: ProjectConfig, request: dict) -> list[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _send_socket_sync, config, request)


def _daemon_running(config: ProjectConfig) -> bool:
    pid_path = config.pid_path
    if not os.path.exists(pid_path):
        return False
    try:
        pid = int(open(pid_path).read().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        return False


# ─── App factory ──────────────────────────────────────────────────────────────

def create_app(config: ProjectConfig) -> FastAPI:
    app = FastAPI(title="ezagent API", version="1")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.config = config

    # ── Status & Daemon ────────────────────────────────────────────────────────

    @app.get("/v1/status")
    async def get_status_endpoint() -> dict:
        from ezagent.daemon import get_status
        import click as _click
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, get_status)
        except _click.ClickException as e:
            raise HTTPException(status_code=500, detail=e.format_message())

    @app.post("/v1/daemon/start")
    async def daemon_start(request: Request) -> dict:
        cfg: ProjectConfig = request.app.state.config
        if _daemon_running(cfg):
            return {"ok": True, "message": "Daemon already running"}

        def _start():
            subprocess.run(
                ["ez", "start", "--daemon"],
                cwd=str(cfg.project_dir),
                capture_output=True,
            )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _start)
        return {"ok": True}

    @app.post("/v1/daemon/stop")
    async def daemon_stop(request: Request) -> dict:
        cfg: ProjectConfig = request.app.state.config
        pid_path = cfg.pid_path
        if not os.path.exists(pid_path):
            raise HTTPException(status_code=409, detail="No running daemon found")
        try:
            pid = int(open(pid_path).read().strip())
            os.kill(pid, signal.SIGTERM)
        except (ValueError, ProcessLookupError):
            pass
        for path in [cfg.socket_path, pid_path]:
            if os.path.exists(path):
                os.unlink(path)
        return {"ok": True}

    # ── Agents ────────────────────────────────────────────────────────────────

    @app.get("/v1/agents")
    async def list_agents(request: Request) -> list[dict]:
        cfg: ProjectConfig = request.app.state.config
        return [
            {
                "name": name,
                "description": ac.description,
                "provider": ac.provider or cfg.provider,
                "model": ac.model or cfg.model,
                "tools": ac.tools,
                "skills": ac.skills,
            }
            for name, ac in cfg.agents.items()
        ]

    @app.get("/v1/agents/{name}")
    async def get_agent(name: str, request: Request) -> dict:
        cfg: ProjectConfig = request.app.state.config
        ac = cfg.agents.get(name)
        if ac is None:
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        return {
            "name": name,
            "description": ac.description,
            "provider": ac.provider or cfg.provider,
            "model": ac.model or cfg.model,
            "tools": ac.tools,
            "skills": ac.skills,
            "schedule": [{"cron": s.cron, "message": s.message} for s in ac.schedule],
        }

    # ── Run Agent (REST) ───────────────────────────────────────────────────────

    class RunRequest(BaseModel):
        message: str
        debug: bool = False

    @app.post("/v1/agents/{name}/run")
    async def run_agent(name: str, request: Request) -> dict:
        cfg: ProjectConfig = request.app.state.config
        if name not in cfg.agents:
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        try:
            raw = await request.json()
        except Exception:
            raise HTTPException(status_code=422, detail="JSON body required")
        try:
            run_req = RunRequest.model_validate(raw)
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e))
        lines = await _send_socket(
            cfg, {"agent": name, "message": run_req.message, "debug": run_req.debug}
        )
        text = ""
        debug_events: list[str] = []
        for item in lines:
            if item.get("type") == "error":
                raise HTTPException(status_code=500, detail=item.get("text", "Agent error"))
            elif item.get("type") == "debug":
                debug_events.append(item.get("text", ""))
            else:
                text = item.get("text", "")
        return {"text": text, "debug_events": debug_events}

    # ── Run Agent (WebSocket) ──────────────────────────────────────────────────

    @app.websocket("/v1/agents/{name}/stream")
    async def stream_agent(name: str, websocket: WebSocket):
        cfg: ProjectConfig = websocket.app.state.config
        await websocket.accept()
        try:
            data = await websocket.receive_json()
            message = data.get("message", "")
            debug = data.get("debug", False)
        except Exception:
            await websocket.send_json({"type": "error", "text": "Invalid request"})
            await websocket.close()
            return

        if name not in cfg.agents:
            await websocket.send_json({"type": "error", "text": f"Agent '{name}' not found"})
            await websocket.close()
            return

        await websocket.send_json({"type": "start"})
        try:
            lines = await _send_socket(cfg, {"agent": name, "message": message, "debug": debug})
        except HTTPException as e:
            await websocket.send_json({"type": "error", "text": e.detail})
            await websocket.close()
            return
        except Exception as e:
            await websocket.send_json({"type": "error", "text": str(e)})
            await websocket.close()
            return

        for item in lines:
            await websocket.send_json(item)
        await websocket.close()

    # ── Run Discussion (REST) ──────────────────────────────────────────────────

    class DiscussionRequest(BaseModel):
        topic: str

    @app.post("/v1/discussions/{name}/run")
    async def run_discussion(name: str, request: Request) -> dict:
        cfg: ProjectConfig = request.app.state.config
        if name not in cfg.discussions:
            raise HTTPException(status_code=404, detail=f"Discussion '{name}' not found")
        try:
            raw = await request.json()
        except Exception:
            raise HTTPException(status_code=422, detail="JSON body required")
        try:
            disc_req = DiscussionRequest.model_validate(raw)
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e))
        lines = await _send_socket(
            cfg, {"type": "discuss", "discussion": name, "topic": disc_req.topic}
        )
        for item in lines:
            if "error" in item:
                raise HTTPException(status_code=500, detail=item["error"])
            return item
        raise HTTPException(status_code=502, detail="No response from daemon")

    # ── Orchestrations ────────────────────────────────────────────────────────

    @app.get("/v1/orchestrations")
    async def list_orchestrations(request: Request) -> list[dict]:
        cfg: ProjectConfig = request.app.state.config
        return [
            {
                "name": name,
                "pattern": oc.pattern,
                "planner": oc.planner,
                "workers": oc.workers,
                "aggregator": oc.aggregator,
                "parallel": oc.parallel,
            }
            for name, oc in cfg.orchestrations.items()
        ]

    @app.get("/v1/orchestrations/{name}")
    async def get_orchestration(name: str, request: Request) -> dict:
        cfg: ProjectConfig = request.app.state.config
        oc = cfg.orchestrations.get(name)
        if oc is None:
            raise HTTPException(status_code=404, detail=f"Orchestration '{name}' not found")
        return {
            "name": name,
            "pattern": oc.pattern,
            "planner": oc.planner,
            "workers": oc.workers,
            "aggregator": oc.aggregator,
            "parallel": oc.parallel,
        }

    class OrchestrationRunRequest(BaseModel):
        message: str

    @app.post("/v1/orchestrations/{name}/run")
    async def run_orchestration(name: str, request: Request) -> dict:
        cfg: ProjectConfig = request.app.state.config
        if name not in cfg.orchestrations:
            raise HTTPException(status_code=404, detail=f"Orchestration '{name}' not found")
        try:
            raw = await request.json()
        except Exception:
            raise HTTPException(status_code=422, detail="JSON body required")
        try:
            orch_req = OrchestrationRunRequest.model_validate(raw)
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e))
        lines = await _send_socket(
            cfg,
            {
                "type": "run_orchestration",
                "orchestration": name,
                "message": orch_req.message,
            },
        )
        for item in lines:
            if "error" in item:
                raise HTTPException(status_code=500, detail=item["error"])
            return item
        raise HTTPException(status_code=502, detail="No response from daemon")

    # ── Run Discussion (WebSocket) ─────────────────────────────────────────────

    @app.websocket("/v1/discussions/{name}/stream")
    async def stream_discussion(name: str, websocket: WebSocket):
        cfg: ProjectConfig = websocket.app.state.config
        await websocket.accept()
        try:
            data = await websocket.receive_json()
            topic = data.get("topic", "")
        except Exception:
            await websocket.send_json({"type": "error", "text": "Invalid request"})
            await websocket.close()
            return

        if name not in cfg.discussions:
            await websocket.send_json({"type": "error", "text": f"Discussion '{name}' not found"})
            await websocket.close()
            return

        await websocket.send_json({"type": "start"})
        try:
            lines = await _send_socket(cfg, {"type": "discuss", "discussion": name, "topic": topic})
        except HTTPException as e:
            await websocket.send_json({"type": "error", "text": e.detail})
            await websocket.close()
            return
        except Exception as e:
            await websocket.send_json({"type": "error", "text": str(e)})
            await websocket.close()
            return

        for item in lines:
            if "error" in item:
                await websocket.send_json({"type": "error", "text": item["error"]})
            else:
                await websocket.send_json({"type": "done", **item})
        await websocket.close()

    # ── Logs ──────────────────────────────────────────────────────────────────

    @app.get("/v1/logs")
    async def get_logs(
        request: Request,
        agent: str | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        cfg: ProjectConfig = request.app.state.config
        db_path = cfg.events_db_path
        if not db_path.exists():
            return []
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            query = (
                "SELECT run_uuid, agent_name, source, status, input_message, "
                "output_text, duration_ms, started_at "
                "FROM agent_runs"
            )
            conditions: list[str] = []
            params: list = []
            if agent:
                conditions.append("agent_name = ?")
                params.append(agent)
            if status:
                conditions.append("status = ?")
                params.append(status)
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            return [dict(row) for row in conn.execute(query, params).fetchall()]
        finally:
            conn.close()

    @app.get("/v1/logs/{run_uuid}")
    async def get_log_detail(run_uuid: str, request: Request) -> dict:
        cfg: ProjectConfig = request.app.state.config
        db_path = cfg.events_db_path
        if not db_path.exists():
            raise HTTPException(status_code=404, detail="No event log found")
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            run = conn.execute(
                "SELECT * FROM agent_runs WHERE run_uuid = ?", (run_uuid,)
            ).fetchone()
            if run is None:
                raise HTTPException(status_code=404, detail=f"Run '{run_uuid}' not found")
            tool_invocations = conn.execute(
                "SELECT * FROM tool_invocations WHERE run_uuid = ?", (run_uuid,)
            ).fetchall()
            llm_calls = conn.execute(
                "SELECT * FROM llm_calls WHERE run_uuid = ? ORDER BY call_number",
                (run_uuid,),
            ).fetchall()
            return {
                "run": dict(run),
                "tool_invocations": [dict(r) for r in tool_invocations],
                "llm_calls": [dict(r) for r in llm_calls],
            }
        finally:
            conn.close()

    # ── Config ─────────────────────────────────────────────────────────────────

    @app.get("/v1/config")
    async def get_config(request: Request) -> dict:
        cfg: ProjectConfig = request.app.state.config
        raw = (cfg.project_dir / "agents.yml").read_text()
        return {"raw": raw, "parsed": yaml.safe_load(raw) or {}}

    class ConfigUpdateRequest(BaseModel):
        content: str

    @app.put("/v1/config")
    async def update_config(
        request: Request,
        payload: ConfigUpdateRequest = Body(...),
    ) -> dict:
        cfg: ProjectConfig = request.app.state.config
        try:
            parsed = yaml.safe_load(payload.content) or {}
            if "agents" not in parsed:
                raise ValueError("agents.yml must contain an 'agents' key.")
            ProjectConfig(
                agents=parsed["agents"],
                discussions=parsed.get("discussions", {}),
                orchestrations=parsed.get("orchestrations", {}),
                project_dir=cfg.project_dir,
                provider=parsed.get("provider", "anthropic"),
                model=parsed.get("model", ""),
            )
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e))
        (cfg.project_dir / "agents.yml").write_text(payload.content)
        return {"ok": True}

    # ── Tools & Skills ─────────────────────────────────────────────────────────

    @app.get("/v1/tools")
    async def get_tools(request: Request) -> dict:
        import ast
        from ezagent.tools.builtins import PREBUILT_TOOLS
        cfg: ProjectConfig = request.app.state.config
        prebuilt = []
        for name, path in PREBUILT_TOOLS.items():
            main_py = path / "main.py"
            desc = ""
            if main_py.is_file():
                try:
                    tree = ast.parse(main_py.read_text())
                    doc = ast.get_docstring(tree) or ""
                    desc = doc.split("\n")[0]
                except Exception:
                    pass
            prebuilt.append({"name": name, "description": desc})
        tools_dir = cfg.project_dir / "tools"
        local: list[str] = []
        if tools_dir.is_dir():
            local = sorted(
                d.name for d in tools_dir.iterdir()
                if d.is_dir() and (d / "main.py").is_file()
            )
        return {"prebuilt": prebuilt, "local": local}

    class CreateToolRequest(BaseModel):
        name: str

    @app.post("/v1/tools")
    async def create_tool_endpoint(
        request: Request,
        payload: CreateToolRequest = Body(...),
    ) -> dict:
        from ezagent.scaffold import create_tool
        cfg: ProjectConfig = request.app.state.config
        try:
            path = create_tool(payload.name, cfg.project_dir / "tools")
        except FileExistsError as e:
            raise HTTPException(status_code=409, detail=str(e))
        return {"path": str(path)}

    class CreateSkillRequest(BaseModel):
        name: str

    @app.post("/v1/skills")
    async def create_skill_endpoint(
        request: Request,
        payload: CreateSkillRequest = Body(...),
    ) -> dict:
        from ezagent.scaffold import create_skill
        cfg: ProjectConfig = request.app.state.config
        try:
            path = create_skill(payload.name, cfg.project_dir / "skills")
        except FileExistsError as e:
            raise HTTPException(status_code=409, detail=str(e))
        return {"path": str(path)}

    return app
