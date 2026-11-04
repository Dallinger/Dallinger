/*
 * Build `dallinger compensate` commands for the database dashboard.
 *
 * Admins paste these commands into a shell, and some recruiters let
 * participants choose their own worker id, so every value is quoted.
 */
(function (root) {
  var SAFE_SHELL_WORD = /^[A-Za-z0-9_.:@\/-]+$/;
  // Quoting can't protect these: a terminal acts on them when they are pasted.
  var CONTROL_CHARACTER = /[\x00-\x1f\x7f-\x9f]/;
  // fish treats `\'` and `\\` inside single quotes as escapes.
  var BACKSLASH = /\\/;

  /** Quote a value as a single word for POSIX shells and fish. */
  function shellQuote(value) {
    if (value === null || value === undefined || value === "") {
      throw new Error("Missing value for the compensate command.");
    }
    var text = String(value);
    if (CONTROL_CHARACTER.test(text)) {
      throw new Error("Value contains a control character: " + JSON.stringify(text));
    }
    if (BACKSLASH.test(text)) {
      throw new Error("Value contains a backslash: " + JSON.stringify(text));
    }
    if (SAFE_SHELL_WORD.test(text)) {
      return text;
    }
    return "'" + text.replace(/'/g, "'\\''") + "'";
  }

  /** Return the `dallinger compensate` command for one participant. */
  function buildCompensateCommand(participant, dollarAmount, isSandbox) {
    var command = [
      "dallinger compensate",
      "--recruiter", shellQuote(participant.recruiter),
      "--worker_id", shellQuote(participant.worker_id),
      "--dollars", shellQuote(dollarAmount),
    ].join(" ");
    return isSandbox ? command + " --sandbox" : command;
  }

  root.dallingerCompensate = {
    shellQuote: shellQuote,
    buildCompensateCommand: buildCompensateCommand,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = root.dallingerCompensate;
  }
})(typeof window !== "undefined" ? window : this);
