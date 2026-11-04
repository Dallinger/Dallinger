/*
 * Build `dallinger compensate` commands for the database dashboard.
 *
 * Admins paste these commands into a shell, and some recruiters let
 * participants choose their own worker id, so every value is quoted.
 */
(function (root) {
  var SAFE_SHELL_WORD = /^[A-Za-z0-9_.:@\/-]+$/;

  /** Quote a value as a single POSIX shell word. */
  function shellQuote(value) {
    var text = String(value);
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
