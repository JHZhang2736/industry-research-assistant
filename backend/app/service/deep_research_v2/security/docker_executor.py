"""DooD 代码沙箱执行器：用 docker SDK 起一次性锁死容器运行不可信代码。

代码经环境变量 SANDBOX_CODE 注入容器（避免 DooD 下 bind-mount 解析到宿主路径
的陷阱）。容器无网络、只读 rootfs、cap-drop ALL、非 root、限资源、超时即销毁。
"""

import json
import logging

logger = logging.getLogger("deep_research_v2.security.docker_executor")


class DockerCodeExecutor:
    def __init__(
        self,
        image: str,
        mem_limit: str = "512m",
        cpus: float = 1.0,
        pids_limit: int = 64,
        timeout: int = 30,
    ):
        self.image = image
        self.mem_limit = mem_limit
        self.cpus = cpus
        self.pids_limit = pids_limit
        self.timeout = timeout

    def execute(self, code: str) -> dict:
        """同步执行（调用方用 asyncio.to_thread 包裹）。"""
        try:
            import docker
            from docker.errors import ImageNotFound
        except ImportError as e:
            return {"success": False, "output": "",
                    "error": f"docker SDK 未安装: {e}", "charts": []}

        try:
            client = docker.from_env()
        except Exception as e:  # noqa: BLE001
            return {"success": False, "output": "",
                    "error": f"无法连接 Docker 守护进程: {e}", "charts": []}

        # 确保镜像存在（不存在则拉取）
        try:
            client.images.get(self.image)
        except ImageNotFound:
            try:
                client.images.pull(self.image)
            except Exception as e:  # noqa: BLE001
                return {"success": False, "output": "",
                        "error": f"沙箱镜像不可用: {e}", "charts": []}

        container = None
        try:
            container = client.containers.run(
                self.image,
                command=["python", "/runner.py"],
                environment={"SANDBOX_CODE": code, "MPLCONFIGDIR": "/tmp", "HOME": "/tmp"},
                network_disabled=True,
                mem_limit=self.mem_limit,
                nano_cpus=int(self.cpus * 1_000_000_000),
                pids_limit=self.pids_limit,
                read_only=True,
                tmpfs={"/tmp": "size=64m"},
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                user="nobody",
                detach=True,
            )
            try:
                container.wait(timeout=self.timeout)
            except Exception as e:  # 超时/连接错误 → 视为超时
                logger.warning(f"[Sandbox] 执行超时或异常，销毁容器: {e}")
                try:
                    container.kill()
                except Exception:
                    pass
                return {"success": False, "output": "",
                        "error": f"sandbox timeout after {self.timeout}s", "charts": []}

            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", "replace")
            lines = [ln for ln in stdout.splitlines() if ln.strip()]
            if not lines:
                return {"success": False, "output": "",
                        "error": "沙箱无输出", "charts": []}
            try:
                return json.loads(lines[-1])
            except json.JSONDecodeError:
                return {"success": False, "output": stdout[:2000],
                        "error": "沙箱输出非 JSON", "charts": []}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "output": "", "error": str(e), "charts": []}
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:
                    pass
