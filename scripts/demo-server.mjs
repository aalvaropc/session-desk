import { spawn } from "node:child_process";
import { resolve } from "node:path";
const python =
  process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const fixture = process.argv.includes("--fixture");
const server = spawn(
  python,
  fixture
    ? ["tests/fixture_server.py"]
    : [
        "-m",
        "session_desk.cli",
        "--demo",
        "--serve",
        "--port",
        process.env.PANEL_TEST_PORT || "8766",
      ],
  { stdio: "inherit", env: { ...process.env, PYTHONPATH: resolve("src") } },
);
for (const signal of ["SIGINT", "SIGTERM"])
  process.on(signal, () => server.kill(signal));
server.on("exit", (code) => process.exit(code ?? 0));
