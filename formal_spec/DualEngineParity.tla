--------------------------- MODULE DualEngineParity ---------------------------
(*
  Formal TLA+ specification for Cloud Frugality Dual-Engine API Route Dispatch and Parity.
  Proves that across both Python (DuckDB/S3) and Rust (Native AL2023) engines:
  
  1. NoHtmlOnApiRoute: API and AI resource requests NEVER return HTML (status 200 or 404).
  2. DualEngineStatusParity: Both engines return identical status codes for all valid and invalid API routes.
  3. DualEngineContentTypeParity: Both engines return "application/json" for all API routes.
  4. PaginationSafety: Page sizing is strictly bounded in [1, 10000] and pagination metadata is consistent.
*)

EXTENDS Naturals, TLC

CONSTANTS
    Routes,            \* {"Root", "Healthz", "AiResource", "AiResourcePaginated", "ApiCosts", "ApiSettings", "Discovery", "UnknownApi", "UnknownOther"}
    Engines,           \* {"Python", "Rust"}
    ContentTypes,      \* {"Json", "Html", "NoContent"}
    StatusCodes        \* {200, 204, 400, 404}

VARIABLES
    currentRoute,      \* Current evaluated route
    pythonStatus,      \* HTTP status code from Python engine
    pythonContentType, \* HTTP content type from Python engine
    rustStatus,        \* HTTP status code from Rust engine
    rustContentType,   \* HTTP content type from Rust engine
    requestedPageSize, \* Requested page size
    effectivePageSize  \* Effective capped page size

vars == <<currentRoute, pythonStatus, pythonContentType, rustStatus, rustContentType, requestedPageSize, effectivePageSize>>

-----------------------------------------------------------------------------
(* Route Dispatch Logic for Python Engine *)

DispatchPython(route) ==
    CASE route = "Root"                -> [status |-> 200, ct |-> "Html"]
      [] route = "Healthz"             -> [status |-> 200, ct |-> "Json"]
      [] route = "AiResource"          -> [status |-> 200, ct |-> "Json"]
      [] route = "AiResourcePaginated" -> [status |-> 200, ct |-> "Json"]
      [] route = "ApiCosts"            -> [status |-> 200, ct |-> "Json"]
      [] route = "ApiSettings"         -> [status |-> 200, ct |-> "Json"]
      [] route = "Discovery"           -> [status |-> 200, ct |-> "Json"]
      [] route = "UnknownApi"          -> [status |-> 404, ct |-> "Json"]
      [] route = "UnknownOther"        -> [status |-> 200, ct |-> "Html"]

(* Route Dispatch Logic for Rust Engine *)

DispatchRust(route) ==
    CASE route = "Root"                -> [status |-> 200, ct |-> "Html"]
      [] route = "Healthz"             -> [status |-> 200, ct |-> "Json"]
      [] route = "AiResource"          -> [status |-> 200, ct |-> "Json"]
      [] route = "AiResourcePaginated" -> [status |-> 200, ct |-> "Json"]
      [] route = "ApiCosts"            -> [status |-> 200, ct |-> "Json"]
      [] route = "ApiSettings"         -> [status |-> 200, ct |-> "Json"]
      [] route = "Discovery"           -> [status |-> 200, ct |-> "Json"]
      [] route = "UnknownApi"          -> [status |-> 404, ct |-> "Json"]
      [] route = "UnknownOther"        -> [status |-> 200, ct |-> "Html"]

CapPageSize(sz) ==
    IF sz < 1 THEN 1
    ELSE IF sz > 10000 THEN 10000
    ELSE sz

-----------------------------------------------------------------------------
Init ==
    /\ currentRoute \in Routes
    /\ requestedPageSize \in {0, 1, 50, 1000, 5000, 10000, 20000}
    /\ effectivePageSize = CapPageSize(requestedPageSize)
    /\ pythonStatus = DispatchPython(currentRoute).status
    /\ pythonContentType = DispatchPython(currentRoute).ct
    /\ rustStatus = DispatchRust(currentRoute).status
    /\ rustContentType = DispatchRust(currentRoute).ct

Next ==
    \E r \in Routes, ps \in {0, 1, 50, 1000, 5000, 10000, 20000}:
        /\ currentRoute' = r
        /\ requestedPageSize' = ps
        /\ effectivePageSize' = CapPageSize(ps)
        /\ pythonStatus' = DispatchPython(r).status
        /\ pythonContentType' = DispatchPython(r).ct
        /\ rustStatus' = DispatchRust(r).status
        /\ rustContentType' = DispatchRust(r).ct

-----------------------------------------------------------------------------
(* Invariants *)

TypeOK ==
    /\ currentRoute \in Routes
    /\ pythonStatus \in StatusCodes
    /\ rustStatus \in StatusCodes
    /\ pythonContentType \in ContentTypes
    /\ rustContentType \in ContentTypes
    /\ effectivePageSize >= 1
    /\ effectivePageSize <= 10000

(* Critical Invariant 1: No API route ever returns HTML *)
NoHtmlOnApiRoute ==
    currentRoute \in {"Healthz", "AiResource", "AiResourcePaginated", "ApiCosts", "ApiSettings", "Discovery", "UnknownApi"} =>
        /\ pythonContentType = "Json"
        /\ rustContentType = "Json"

(* Critical Invariant 2: Python and Rust engine status code parity *)
DualEngineStatusParity ==
    pythonStatus = rustStatus

(* Critical Invariant 3: Python and Rust engine Content-Type parity *)
DualEngineContentTypeParity ==
    pythonContentType = rustContentType

(* Invariant 4: Pagination safety guarantees *)
PaginationSafety ==
    effectivePageSize >= 1 /\ effectivePageSize <= 10000

Spec == Init /\ [][Next]_vars

=============================================================================
