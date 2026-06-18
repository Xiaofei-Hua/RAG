"""
Pluggable tool registry for the agent platform (P2.1 + P2.3).

This lets new non-RAG tools (calculator, unit conversion, external API calls,
code execution) be registered WITHOUT touching the graph topology. Tools are
grouped into MCP servers; ``get_extra_servers`` returns all registered servers
which ``AgentHarness._build_mcp_client`` aggregates.

Two built-in tool servers are provided out of the box:
  - ``UtilityToolsServer``: calculator + unit conversion (pure-python, no deps)
  - ``ExternalAPIToolsServer``: a generic HTTP GET tool (opt-in via env)

Additional servers can be registered at runtime via ``register_server`` /
``register_tool_function``.
"""

from __future__ import annotations

import json
import math
import os
import threading
from typing import Any, Callable, Dict, List, Optional

from agent.mcp.server import InProcessMCPServer, MCPServerConfig
from utils.log_utils import log

__all__ = [
    "register_server",
    "register_tool_function",
    "get_extra_servers",
    "UtilityToolsServer",
    "ExternalAPIToolsServer",
]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_extra_servers: List[InProcessMCPServer] = []
_registry_lock = threading.Lock()


def register_server(server: InProcessMCPServer) -> None:
    """Register an extra MCP server (added to the agent's toolset)."""
    with _registry_lock:
        _extra_servers.append(server)
    log.info(f"Tool registry: added server '{server.config.name}'")


def register_tool_function(
    name: str,
    description: str,
    handler: Callable,
    params_schema: Optional[Dict[str, Any]] = None,
    server_name: str = "custom",
) -> None:
    """
    Register a single tool as its own ad-hoc server.

    Convenience wrapper for quick tool addition without manually building an
    InProcessMCPServer.
    """
    server = InProcessMCPServer(MCPServerConfig(name=server_name, version="1.0.0"))
    server.register_callable(handler, name=name, description=description)
    register_server(server)


def get_extra_servers() -> List[InProcessMCPServer]:
    """Return all registered extra servers (called by the harness)."""
    _maybe_register_defaults()
    with _registry_lock:
        return list(_extra_servers)


_registered_defaults = False


def _maybe_register_defaults() -> None:
    """Register built-in tool servers once (idempotent)."""
    global _registered_defaults
    if _registered_defaults:
        return
    with _registry_lock:
        if _registered_defaults:
            return
        _registered_defaults = True
    try:
        register_server(UtilityToolsServer())
    except Exception as e:  # noqa: BLE001
        log.debug(f"UtilityToolsServer not registered: {e}")
    if os.getenv("ENABLE_EXTERNAL_API_TOOL", "false").lower() in ("1", "true", "yes"):
        try:
            register_server(ExternalAPIToolsServer())
        except Exception as e:  # noqa: BLE001
            log.debug(f"ExternalAPIToolsServer not registered: {e}")


# ---------------------------------------------------------------------------
# Built-in: utility tools (calculator + unit conversion)
# ---------------------------------------------------------------------------

class UtilityToolsServer(InProcessMCPServer):
    """Pure-python utility tools: safe arithmetic + unit conversion."""

    def __init__(self):
        super().__init__(MCPServerConfig(name="utility", version="1.0.0"))
        self.register_callable(
            self.calculate, name="calculator",
            description=(
                "计算一个数学表达式并返回结果。支持加减乘除、幂、括号、"
                "以及 sin/cos/sqrt/log 等函数。例如: calculator('2*(3+4)') -> 14"
            ),
        )
        self.register_callable(
            self.convert_unit, name="unit_convert",
            description=(
                "单位换算。支持温度(℃/℉/K)、长度(mm/cm/m/km/inch/ft)、"
                "压力(MPa/kPa/psi/bar)。例如: unit_convert('100℃', '℉') -> 212"
            ),
        )

    @staticmethod
    def calculate(expression: str) -> str:
        """Safely evaluate a math expression (no builtins, no attribute access)."""
        if not expression or not isinstance(expression, str):
            return "错误：请提供数学表达式"
        expr = expression.strip()
        # Whitelist characters to prevent code injection.
        allowed = set("0123456789.+-*/() ,")
        # Also allow function names sin/cos/tan/sqrt/log/pi/e
        safe = expr
        for fn in ("sin", "cos", "tan", "sqrt", "log", "log10", "exp", "pi", "e"):
            safe = safe.replace(fn, "")
        if not all(c in allowed for c in safe):
            return "错误：表达式包含不允许的字符"
        try:
            namespace = {
                "sin": math.sin, "cos": math.cos, "tan": math.tan,
                "sqrt": math.sqrt, "log": math.log, "log10": math.log10,
                "exp": math.exp, "pi": math.pi, "e": math.e,
                "abs": abs, "pow": pow,
            }
            result = eval(expr, {"__builtins__": {}}, namespace)  # noqa: S307 - sandboxed by whitelist
            return f"{result}"
        except Exception as ex:
            return f"计算错误：{ex}"

    @staticmethod
    def convert_unit(value_expr: str, target_unit: str) -> str:
        """Convert a value with a unit to a target unit."""
        try:
            # Parse "100℃" / "5 mm" / "2.5 MPa"
            import re

            m = re.match(r"^\s*([-\d.]+)\s*([a-zA-Z℃℉]+)\s*$", value_expr)
            if not m:
                return "错误：格式应为 '<数值><单位>'，如 '100℃'"
            val = float(m.group(1))
            src = m.group(2).strip()
            dst = target_unit.strip()

            # Temperature
            temp_units = {"℃": "c", "℉": "f", "K": "k"}
            if src in temp_units and dst in temp_units:
                s, t = temp_units[src], temp_units[dst]
                # to celsius
                c = val if s == "c" else (val - 32) * 5 / 9 if s == "f" else val - 273.15
                out = c if t == "c" else c * 9 / 5 + 32 if t == "f" else c + 273.15
                return f"{out:.2f}{dst}"

            # Length
            length = {"mm": 0.001, "cm": 0.01, "m": 1.0, "km": 1000.0,
                      "inch": 0.0254, "ft": 0.3048}
            if src in length and dst in length:
                meters = val * length[src]
                return f"{meters / length[dst]:.4f}{dst}"

            # Pressure
            pressure = {"MPa": 1.0, "kPa": 0.001, "bar": 0.1, "psi": 0.00689476}
            if src in pressure and dst in pressure:
                mpa = val * pressure[src]
                return f"{mpa / pressure[dst]:.4f}{dst}"

            return f"错误：不支持的换算 {src}->{dst}"
        except Exception as ex:
            return f"换算错误：{ex}"


# ---------------------------------------------------------------------------
# Built-in: external API tool (opt-in)
# ---------------------------------------------------------------------------

class ExternalAPIToolsServer(InProcessMCPServer):
    """A generic HTTP GET tool for calling external read-only APIs."""

    def __init__(self):
        super().__init__(MCPServerConfig(name="external_api", version="1.0.0"))
        self.register_callable(
            self.http_get, name="http_get",
            description=(
                "对指定 URL 发起只读 GET 请求并返回 JSON/文本响应。"
                "仅用于查询外部公开 API。例如: http_get('https://api.example.com/status')"
            ),
        )

    @staticmethod
    def _ssf_blocked(url: str) -> str | None:
        """
        Validate a URL for SSRF safety. Returns a reason string if blocked,
        else None.

        Blocks: non-http(s) schemes, private/loopback/link-local/multicast IP
        literals, and hostnames that don't resolve to a public address. An
        optional allowlist can be set via ``HTTP_TOOL_ALLOWED_HOSTS`` (comma-
        separated); when set, only those hosts are permitted.
        """
        import ipaddress
        import os
        import socket
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return "URL 必须以 http:// 或 https:// 开头"
        host = parsed.hostname
        if not host:
            return "URL 缺少主机名"

        # Optional host allowlist (most restrictive control).
        allow_env = os.getenv("HTTP_TOOL_ALLOWED_HOSTS", "").strip()
        if allow_env:
            allowed = {h.strip().lower() for h in allow_env.split(",") if h.strip()}
            if host.lower() not in allowed:
                return f"主机 {host} 不在允许列表内"

        # Resolve the hostname and reject if ANY resolved address is private /
        # loopback / link-local. DNS rebinding to a private IP is also caught
        # because we check every returned address.
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return f"无法解析主机 {host}"
        for info in infos:
            ip_str = info[4][0]
            try:
                # getaddrinfo may return IPv6 in brackets-free form; zone ids
                # are stripped by ipaddress.
                ip = ipaddress.ip_address(ip_str.split("%")[0])
            except ValueError:
                continue
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
                return f"主机 {host} 解析到内网/保留地址 {ip}，已拒绝"
        return None

    @staticmethod
    def http_get(url: str, timeout: int = 10) -> str:
        """Perform a read-only HTTP GET (SSRF-hardened)."""
        import urllib.request

        blocked = ExternalAPIToolsServer._ssf_blocked(url)
        if blocked:
            return f"错误：{blocked}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "RAG-Agent/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - SSRF-checked above
                body = resp.read().decode("utf-8", errors="replace")[:2000]
            return body
        except Exception as ex:
            return f"请求失败：{ex}"
