import asyncio
import logging
import os
import sys
from typing import Awaitable, Callable, Optional

BAN_MARKER = "##BANNED##"

OnLog = Callable[[str, str], Awaitable[None]]  # token, line
OnBanned = Callable[[str], Awaitable[None]]    # token
OnExit = Callable[[str, int], Awaitable[None]] # token, returncode

logger = logging.getLogger("admin_bot.fleet")


class WorkerFleet:
    """Supervises worker_bot subprocesses for all active mirrors."""

    def __init__(self, on_log: OnLog, on_banned: OnBanned, on_exit: OnExit) -> None:
        self._on_log = on_log
        self._on_banned = on_banned
        self._on_exit = on_exit
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._pump_tasks: dict[str, asyncio.Task] = {}

    def is_running(self, token: Optional[str] = None) -> bool:
        if token is not None:
            proc = self._processes.get(token)
            return proc is not None and proc.returncode is None
        return any(proc.returncode is None for proc in self._processes.values())

    async def start(self, token: str) -> None:
        if self.is_running(token):
            return

        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "worker_bot.main",
            "--token",
            token,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=os.getcwd(),
        )
        self._processes[token] = process
        self._pump_tasks[token] = asyncio.create_task(self._pump(token, process))

    async def stop(self, token: str) -> None:
        process = self._processes.get(token)
        if process is None:
            return
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        pump_task = self._pump_tasks.get(token)
        if pump_task is not None:
            pump_task.cancel()
        self._processes.pop(token, None)
        self._pump_tasks.pop(token, None)

    async def stop_all(self) -> None:
        tokens = list(self._processes.keys())
        for token in tokens:
            await self.stop(token)

    async def _pump(self, token: str, process: asyncio.subprocess.Process) -> None:
        assert process.stdout is not None
        banned = False
        try:
            async for raw_line in process.stdout:
                line = raw_line.decode(errors="replace").rstrip()
                if not line:
                    continue
                if line == BAN_MARKER:
                    banned = True
                    await self._on_banned(token)
                    continue
                await self._on_log(token, line)
        finally:
            returncode = await process.wait()
            self._processes.pop(token, None)
            self._pump_tasks.pop(token, None)
            if not banned:
                await self._on_exit(token, returncode)
