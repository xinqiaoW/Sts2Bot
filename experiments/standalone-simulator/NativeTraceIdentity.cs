internal static class NativeTraceIdentity
{
    // These recorders use the same game 0.111.0, protocol-3 PlanAction/choice
    // encoding and full-state stamp. Their teacher differs only in search
    // semantics: replay executes the recorded original-game actions verbatim.
    // Keep old successful evidence usable after a teacher repair; never accept
    // arbitrary hashes or load a historical teacher as the current runtime.
    internal static bool IsReviewedCollector(string? sha256)
        => sha256 == HostAdapter.SolverHash
            || sha256 == "1950d98b8aa742f651a2c09d59e6044da8c0836a29f4c1258047a8d1048f9bfb"
            || sha256 == "1342fdf406fed02f730c2e241b740abd9c116c54f62190e5bdb7e041fe5cb707";
}
