internal static class NativeTraceIdentity
{
    // These recorders use the same game 0.111.0, protocol-3 PlanAction/choice
    // encoding and full-state stamp. Their teacher differs only in search
    // semantics: replay executes the recorded original-game actions verbatim.
    // Keep old successful evidence usable after a teacher repair; never accept
    // arbitrary hashes or load a historical teacher as the current runtime.
    internal static bool IsReviewedCollector(string? sha256)
        => sha256 == HostAdapter.SolverHash
            || sha256 == "116098fd3856c83e8d9d79fff9e0ade89dd8c53b08182c70f09dcfad050b61b2"
            || sha256 == "e4785c9d02832896333590f40f7b8c81ed642de6025a0bc72c7b7ef98568bc68"
            || sha256 == "02bd107d204b4c4a5b28a7d305489aa8c937b62e0cfc8104f73a3f7a96687af9"
            || sha256 == "1950d98b8aa742f651a2c09d59e6044da8c0836a29f4c1258047a8d1048f9bfb"
            || sha256 == "1342fdf406fed02f730c2e241b740abd9c116c54f62190e5bdb7e041fe5cb707";
}
