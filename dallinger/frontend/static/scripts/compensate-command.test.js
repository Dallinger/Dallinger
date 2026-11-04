/*globals expect, test */

const { execFileSync } = require("child_process");
const { buildCompensateCommand } = require("./compensate-command");

// The arguments bash passes to `dallinger` when it runs `command`.
function shellArgs(command) {
  const script = "dallinger() { printf '%s\\0' \"$@\"; }; " + command;
  return execFileSync("bash", ["-c", script], { encoding: "utf8" })
    .split("\0")
    .slice(0, -1);
}

test("keeps a hostile worker id as one argument", () => {
  const workerId = "x'; touch /tmp/pwned; echo '";
  const command = buildCompensateCommand(
    { recruiter: "hot banana", worker_id: workerId },
    2.5,
    true,
  );
  expect(shellArgs(command)).toEqual([
    "compensate",
    "--recruiter",
    "hot banana",
    "--worker_id",
    workerId,
    "--dollars",
    "2.5",
    "--sandbox",
  ]);
});

test("leaves plain values unquoted", () => {
  expect(
    buildCompensateCommand({ recruiter: "prolific", worker_id: "A1B2" }, 1),
  ).toBe("dallinger compensate --recruiter prolific --worker_id A1B2 --dollars 1");
});

test("refuses worker ids that quoting can't make safe", () => {
  const refused = [
    "\x1b[201~\x03touch /tmp/pwned\r",
    "\\'; touch /tmp/pwned_fish; #",
    "",
    null,
  ];
  for (const workerId of refused) {
    expect(() =>
      buildCompensateCommand({ recruiter: "prolific", worker_id: workerId }, 1),
    ).toThrow();
  }
});
