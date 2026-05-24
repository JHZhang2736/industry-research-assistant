#!/usr/bin/env node
// 跨平台 postinstall：仅在 POSIX 系统（Linux / macOS）上补齐 node_modules/.bin/ 的可执行位。
// Windows 通过 .cmd shim 调用二进制，不依赖 Unix 执行权限，直接 no-op。
//
// 历史上 chmod +x 是为了应对部分 npm/yarn 版本或挂载场景（Docker 卷、WSL bind mount）
// 丢失执行位的情况；保留这层兜底对未来在 Linux 容器里跑 dev 有用。

import { execSync } from "node:child_process";

if (process.platform === "win32") {
  process.exit(0);
}

try {
  execSync("chmod +x node_modules/.bin/* 2>/dev/null || true", { stdio: "ignore" });
} catch {
  // 静默：执行权限不是关键路径，失败也不阻塞 install
}
